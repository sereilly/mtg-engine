"""Lowering board changes: destruction, bouncing, tapping, control, exile.

Destroy (targeted and sweeping), the delayed destroy a combat trigger binds,
tap/untap, return-to-zone, regeneration, control changes, sacrifice, and exile.

Control changes lower to a *contribution* rather than a move — see
`engine/control.py`. What lowering owes is the timestamped source, not a new
owner.
"""

import dataclasses

from ...oracle_types import OracleInstruction
from ...subject_filters import object_only_filter
from .. import ast
from ..errors import LoweringError
from ._common import (
    _describe_several_card_targets,
    _describe_several_targets,
    _describe_targets,
    _filter_payload,
    _full_mana_payload,
    _is_enchanted,
    _is_source,
    _is_target,
    _names_several_targets,
    _restrictions_beyond,
    _targets_only,
)


# ---------------------------------------------------------------------------
# Destruction, tapping, zones
# ---------------------------------------------------------------------------

# "Destroy all X" shapes with a dedicated sweep handler.
_DESTROY_ALL_KINDS: dict[tuple[str, ...], str] = {
    ("artifact",): "destroy_all_artifacts",
    ("creature",): "destroy_all_creatures",
    ("enchantment",): "destroy_all_enchantments",
    ("land",): "destroy_all_lands",
    ("artifact", "creature", "enchantment"): "destroy_all_artifacts_creatures_enchantments",
}

_BASIC_LAND_TYPES = frozenset({"plains", "island", "swamp", "mountain", "forest"})


# Trigger events that bind the creature a delayed "destroy that creature at end
# of combat" acts on. `delayed_destroy_blocked_or_blocker` reads the blocking
# pair out of the trigger's own context and takes no payload at all, so the
# sentence only means what it says while one of these fired.
_BLOCK_PAIR_EVENTS = frozenset({"creature_blocks_or_blocked_by_nonwall"})


# Trigger events whose fire site stamps the object the event was about onto the
# stack item, so an effect may say "that <noun>" and mean it.
_EVENT_SUBJECT_DESTROY_EVENTS: frozenset[str] = frozenset({
    "matching_creature_damages_planeswalker",   # Hooded Blightfang
})


def _lower_destroy(node: ast.Destroy, event: str | None = None) -> tuple[OracleInstruction, ...]:
    if node.delay:
        return _lower_delayed_destroy(node, event)
    if not isinstance(node.subject, ast.TargetSpec):
        raise LoweringError("destroy needs an object target", node=node)
    spec = node.subject
    filt = spec.filter

    if spec.quantifier in ("all", "each"):
        # "Destroy all Plains" — a basic land type, not a creature subtype.
        if filt.subtypes and not filt.card_types:
            if len(filt.subtypes) == 1 and filt.subtypes[0] in _BASIC_LAND_TYPES:
                subtype = filt.subtypes[0]
                # The handler keys on the plural form the card prints; Plains is
                # already plural.
                plural = subtype if subtype.endswith("s") else f"{subtype}s"
                return (
                    OracleInstruction(
                        "destroy_all_lands_of_type", "", {"land_type": plural},
                    ),
                )
            raise LoweringError("no sweep handler for this subtype", node=node)
        kind = _DESTROY_ALL_KINDS.get(tuple(sorted(filt.card_types)))
        if kind is None:
            raise LoweringError("no sweep handler for this destroy scope", node=node)
        payload = {"bypass_regeneration": True} if node.no_regen else {}
        return (OracleInstruction(kind, "", payload),)

    # "…destroy **that planeswalker**." (Hooded Blightfang.) "That" is not a
    # target the card ever asked for — it is the object the trigger's event was
    # about, which the fire site stamps onto the stack item by permanent id. So
    # this rides the ordinary destroy handler and simply does not describe a
    # cast-time target: `_describe_targets` below would raise a picker for a
    # choice CR 603.3d says was never offered. Admitted only under the events
    # whose fire site records one, because everywhere else "that" has no
    # referent and a bare destroy would hit whatever the context happened to
    # hold.
    if spec.quantifier == "that":
        if event not in _EVENT_SUBJECT_DESTROY_EVENTS:
            raise LoweringError(
                "\"that\" names the firing event's object, and this event records none",
                node=node,
            )
        payload = _filter_payload(filt)
        if node.no_regen:
            payload["bypass_regeneration"] = True
        return (OracleInstruction("destroy_target_permanent", "", payload),)

    if spec.quantifier not in ("target", "up_to"):
        raise LoweringError("unsupported destroy quantifier", node=node)

    payload = _filter_payload(filt)
    if node.no_regen:
        payload["bypass_regeneration"] = True
    _describe_targets(payload, spec)
    return (OracleInstruction("destroy_target_permanent", "", payload),)


def _lower_delayed_destroy(
    node: ast.Destroy, event: str | None
) -> tuple[OracleInstruction, ...]:
    """"…destroy that creature at end of combat." (Thicket Basilisk, Cockatrice.)

    The handler destroys the creature this one blocked or was blocked by, which
    is a fact only the trigger knows — so the *event* is checked as strictly as
    the subject is. Under any other trigger the same sentence names a creature
    nobody recorded, and the handler would destroy nothing while the card
    reported as supported.
    """
    if event not in _BLOCK_PAIR_EVENTS:
        raise LoweringError(
            "a delayed destroy at end of combat only has a handler on a "
            "blocks-or-blocked trigger",
            node=node,
        )
    spec = node.subject
    if not isinstance(spec, ast.TargetSpec) or spec.quantifier != "that":
        raise LoweringError(
            "the end-of-combat destroy acts on the creature the trigger bound", node=node
        )
    if spec.filter != ast.ObjectFilter(card_types=("creature",)):
        raise LoweringError("no delayed-destroy handler narrows what it destroys", node=node)
    if node.no_regen:
        raise LoweringError(
            "the end-of-combat destroy handler does not bypass regeneration", node=node
        )
    return (OracleInstruction("delayed_destroy_blocked_or_blocker", "", {}),)


def _lower_put_on_library_bottom(node: ast.PutOnLibraryBottom) -> tuple[OracleInstruction, ...]:
    """"Put target card from your graveyard on the bottom of your library."
    (Epitaph Golem.) Only that exact scope has a handler: the card comes out
    of the caster's own graveyard and goes under their own library."""
    spec = node.target
    if not isinstance(spec, ast.TargetSpec) or not _is_target(spec):
        raise LoweringError("the bottoming handler reads one chosen card", node=node)
    filt = spec.filter
    if not filt.is_card or filt.zone != "graveyard" or (
        filt.zone_owner is None or filt.zone_owner.kind != "you"
    ):
        raise LoweringError(
            "the bottoming handler reads the caster's own graveyard", node=node
        )
    if filt != ast.ObjectFilter(is_card=True, zone="graveyard", zone_owner=filt.zone_owner):
        raise LoweringError("no bottoming handler honours this restriction", node=node)
    return (OracleInstruction("put_graveyard_card_on_library_bottom", "", {}),)


def _lower_tap(node: ast.Tap | ast.Untap) -> tuple[OracleInstruction, ...]:
    if not isinstance(node.subject, ast.TargetSpec):
        raise LoweringError("tap/untap needs an object target", node=node)
    spec = node.subject

    # "Untap this artifact" (Basalt Monolith), "untap enchanted creature" and
    # "Tap this creature" (Seasoned Hallowblade) name their subject without a
    # target being chosen — the source and the enchanted permanent are known —
    # so each has its own handler.
    if isinstance(node, ast.Untap):
        if _is_source(spec):
            return (OracleInstruction("untap_self", "", {}),)
        if _is_enchanted(spec):
            return (OracleInstruction("untap_enchanted_creature", "", {}),)
    elif _is_source(spec):
        return (OracleInstruction("tap_self", "", {}),)

    # "Untap up to four lands." (Rewind.) No "target" is printed: nothing is
    # chosen as the spell is cast — the controller picks the lands as it
    # resolves (a pending choice), which is why this branch demands the spec
    # be *untargeted* and why it never reaches engine/targeting.py.
    if (
        isinstance(node, ast.Untap)
        and spec.quantifier == "up_to"
        and not spec.targeted
        and spec.filter.card_types == ("land",)
        and spec.filter == ast.ObjectFilter(card_types=("land",))
    ):
        return (
            OracleInstruction(
                "untap_up_to_matching",
                "",
                {"amount": spec.count, "filter": {"type_filter": "land"}},
            ),
        )
    if _names_several_targets(spec):
        # "Tap up to two target creatures." (Frost Breath.) The same instruction
        # as the one-target tap — the effect per permanent is identical — with
        # the several-targets opt-in, which is what says the handler resolves a
        # list and the picker collects up to N.
        #
        # Gated to exactly what that handler reads: a *targeted* "up to N" over
        # creatures. `_describe_several_targets` refuses the untargeted spelling
        # itself ("up to four lands", Rewind, is chosen on resolution), and the
        # filter equality keeps a narrowing the handler's
        # `permanent_matches_filter` plus its two seat tests cannot answer from
        # compiling into a wider tap.
        if (
            isinstance(node, ast.Tap)
            and spec.filter.card_types == ("creature",)
            and not _restrictions_beyond(
                spec.filter, frozenset({"card_types", "controller", "other_than_source"})
            )
        ):
            several = _filter_payload(spec.filter)
            _describe_several_targets(several, spec)
            return (OracleInstruction("tap_target_permanent", "", several),)
        # Untap is untouched. Both untap handlers resolve exactly one permanent,
        # so this used to untap one and call the card supported. What a lowering
        # may accept is "one target", and `_is_target` is the one place that says
        # so — the literal quantifier tuple that admitted this is gone.
        raise LoweringError("no handler taps or untaps several targets", node=node)
    if not _is_target(spec):
        raise LoweringError("no handler for non-targeted tap/untap", node=node)
    payload = _filter_payload(spec.filter)

    if isinstance(node, ast.Tap):
        tap_payload = dict(payload)
        _describe_targets(tap_payload, spec)
        return (OracleInstruction("tap_target_permanent", "", tap_payload),)

    # Untap has two handlers with different reach: the generic one ignores
    # filters entirely, so a restricted untap must route to the land-specific
    # handler or refuse. Lowering "untap target land" to the generic kind would
    # let it untap a creature.
    if not payload:
        return (OracleInstruction("untap_target_permanent", "", _targets_only(spec)),)
    if payload == {"type_filter": "land"}:
        return (OracleInstruction("untap_target_land", "", _targets_only(spec)),)
    raise LoweringError("no untap handler honors this restriction", node=node)


# The scratchpad key the tap records and this sentence reads. One name, in one
# place, because ``engine/grammar/lower.py``'s ``_PRODUCES`` writes it and the
# refusal below is what proves a producer ran — two spellings would make the
# refusal vacuous while the handler read an empty record and marked nothing.
_TAPPED_PERMANENTS = "tapped_permanents"


def _lower_doesnt_untap_next_step(
    node: ast.DoesntUntapNextStep, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """"Those creatures don't untap during their controller's next untap step."
    (Frost Breath.)

    Three refusals, and each is a way the sentence could otherwise mean more than
    it says:

    * The subject must be the **bound plural** ("those creatures"). A chosen
      target would be a second, independent choice the card never offered; the
      quantifier is what tells them apart.
    * The subject may carry no restriction beyond its card type. "Those
      creatures" restates what the previous sentence already chose, so there is
      nothing here for an adjective to narrow — a filter carrying one would be
      dropped, and the effect would reach permanents the printed adjective
      excludes.
    * A **producer must have run** in this same effect. The handler reads the
      list out of the resolution scratchpad, and with nothing recorded it marks
      nothing while the card compiles clean. This is the same discipline
      ``_back_reference_payload`` applies to "that much".
    """
    subject = node.subject
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier != "those":
        raise LoweringError(
            "this sentence acts on the objects the previous one chose, and its "
            "subject does not name them",
            node=node,
        )
    if _restrictions_beyond(subject.filter, frozenset({"card_types"})):
        raise LoweringError(
            "a bound plural carries no narrowing the marker could honour", node=node
        )
    if _TAPPED_PERMANENTS not in produced:
        raise LoweringError(
            f"back-reference to {_TAPPED_PERMANENTS!r} with no producer in this effect",
            node=node,
        )
    return (
        OracleInstruction(
            "skip_next_untap", "", {"permanents_from": _TAPPED_PERMANENTS}
        ),
    )


def _reads_no_return_restriction(filt: ast.ObjectFilter) -> bool:
    """Whether *filt* carries a narrowing none of the zone-change handlers reads.

    All three take their whole instruction from the card: two read an empty
    payload and the third reads one boolean. So any adjective beyond the card
    type is invisible to them, and a filter carrying one has to refuse — "return
    target *black* creature card from your graveyard to your hand" lowered to
    Raise Dead's instruction would happily return a white one.
    """
    tri_state = (filt.tapped, filt.attacking, filt.blocking, filt.blocked)
    return bool(
        filt.supertypes or filt.subtypes or filt.colors or filt.excluded_colors
        or filt.excluded_types or filt.excluded_subtypes or filt.with_keywords
        or filt.without_keywords or filt.controller or filt.power or filt.toughness
        or filt.mana_value or filt.named or filt.other_than_source
        or filt.is_source or filt.is_enchanted
        or any(state is not None for state in tri_state)
    )


def _graveyard_to_hand_payload(filt: ast.ObjectFilter) -> dict[str, object]:
    """The card-type half of a graveyard-to-hand return's payload.

    One function because the one-card and several-card branches have to narrow
    *identically*: the named card type is a filter the handler applies, so it is
    carried rather than collapsed - reading "artifact card" as "any card" would
    let Reconstruction return a creature. A *union* ("instant or sorcery card",
    Shipwreck Dowser) travels as its own additive key, so Raise Dead's payload
    stays byte-identical. Two copies of this is how "up to two target artifact
    cards" ends up returning a creature.
    """
    if len(filt.card_types) > 1:
        return {
            "any_card": False,
            "card_type": None,
            "card_types": list(filt.card_types),
        }
    card_type = filt.card_types[0] if filt.card_types else None
    return {"any_card": card_type is None, "card_type": card_type}


def _lower_return_to_zone(node: ast.ReturnToZone) -> tuple[OracleInstruction, ...]:
    """"Return <object> [from <zone>] to <zone>" — Raise Dead, Regrowth,
    Resurrection and Unsummon.

    The *pair* of zones picks the handler, which is why they are both parsed
    rather than pattern-matched out of the sentence: graveyard→hand,
    graveyard→battlefield and battlefield→owner's hand are three unrelated
    handlers reading three different target indices (a graveyard position, a
    graveyard position, a battlefield position). The legacy rules told them
    apart by substring, and told Raise Dead from Regrowth by probing for
    ``"creature card" not in text`` — which is why "return target artifact card
    from your graveyard to your hand" would have returned a creature.

    Nothing here is described for engine/targeting.py. The `targets` vocabulary
    names battlefield permanents, so describing a graveyard card with it would
    tell the picker to offer creatures in play for a reanimation spell — the
    exact bug the Animate Dead targeting test pins.
    """
    # "Return target spell or creature to its owner's hand." (Unsubstantiate):
    # a spell on the stack goes back to its owner's hand (CR 608.2b never
    # applies — the spell is the target, not a resolver of it), a creature is
    # the ordinary bounce. One instruction; the handler branches on which kind
    # of object was chosen.
    if node.also_stack:
        return (OracleInstruction("return_spell_or_creature_to_hand", "", {}),)
    subject = node.subject
    # "Return up to two target creatures to their owners' hands." (Read the
    # Tides' second mode.) Same instruction as the single-target bounce — the
    # effect per creature is identical — described with the several-targets
    # opt-in so the handler resolves a list and the picker collects up to N.
    if (
        isinstance(subject, ast.TargetSpec)
        and _names_several_targets(subject)
        and node.from_zone is None
        and node.to.name == "hand"
        and node.to.owner is not None
        and node.to.owner.kind == "owner"
        and not subject.filter.is_card
        and subject.filter.card_types == ("creature",)
    ):
        several: dict[str, object] = {}
        _describe_several_targets(several, subject)
        return (OracleInstruction("bounce_target_creature", "", several),)
    # "Return up to two target creature cards from your graveyard to your hand."
    # (Sanguine Indulgence.) The same instruction as the one-card return - the
    # effect per card is identical, and `_graveyard_to_hand_payload` is the same
    # narrowing - plus the several-targets opt-in, which is what says the handler
    # resolves a list and the picker collects up to N.
    #
    # Gated to exactly the shape that handler reads: the caster's own graveyard,
    # their own hand, and nothing `_reads_no_return_restriction` refuses for the
    # one-card path, since the several path reads the same payload keys and no
    # more. "Up to two target **black** creature cards" therefore refuses rather
    # than returning any two.
    if (
        isinstance(subject, ast.TargetSpec)
        and _names_several_targets(subject)
        and node.from_zone is not None
        and node.from_zone.name == "graveyard"
        and node.from_zone.owner is not None
        and node.from_zone.owner.kind == "you"
        and node.to.name == "hand"
        and node.to.owner is not None
        and node.to.owner.kind == "you"
        and subject.filter.is_card
    ):
        if _reads_no_return_restriction(subject.filter):
            # Raised here rather than left to the generic refusal below, so the
            # named clause says which half is missing: the arity is fine and the
            # adjective is not.
            raise LoweringError("no return handler honours this restriction", node=node)
        several_cards = _graveyard_to_hand_payload(subject.filter)
        _describe_several_card_targets(several_cards, subject)
        return (
            OracleInstruction(
                "return_creature_from_graveyard_to_hand", "", several_cards
            ),
        )
    # "Return **this card** from your graveyard to the battlefield [tapped]."
    # (Silversmote Ghoul; CR 113.6m's own example is Reassembling Skeleton.)
    # Nothing is chosen — the ability names the object it is printed on — so this
    # is not a targeted return and never reaches `_is_target` below.
    #
    # `functions_from` is the load-bearing key and it is *derived*, not declared:
    # CR 113.6m says an ability whose effect moves the object it is on out of a
    # zone functions only in that zone, so the zone the sentence names as the
    # source is the zone the ability works from. The scan in engine/events.py
    # reads that key rather than a list of instruction kinds, for the reason
    # end_step.py's intervening-if gate is keyed on a payload shape: a list is
    # only ever as complete as the last card that touched it.
    if _is_source(subject) and node.from_zone is not None and node.from_zone.name == "graveyard":
        assert isinstance(subject, ast.TargetSpec)
        if node.from_zone.owner is None or node.from_zone.owner.kind != "you":
            raise LoweringError(
                "a card returns itself from its owner's graveyard", node=node
            )
        if node.to.name != "battlefield" or node.to.owner is not None:
            raise LoweringError(
                f"no handler returns a card from the graveyard to the {node.to.name}",
                node=node,
            )
        # Every ObjectFilter field beyond the three the phrase "this card from
        # your graveyard" sets. Written against the dataclass, so a restriction
        # added later refuses rather than being silently dropped.
        leftovers = _restrictions_beyond(
            subject.filter, frozenset({"is_source", "zone", "zone_owner"})
        )
        if leftovers:
            raise LoweringError(
                f"the self-return handler does not honour {leftovers[0]!r}", node=node
            )
        return (
            OracleInstruction(
                "return_self_from_graveyard", "",
                {"tapped": node.entering_tapped, "functions_from": "graveyard"},
            ),
        )
    if not _is_target(subject):
        # "target" and "up to one target" (Liliana, Death Mage's +1) both
        # resolve one chosen object; anything wider has no handler.
        raise LoweringError("no handler for returning a non-targeted object", node=node)
    assert isinstance(subject, ast.TargetSpec)
    filt = subject.filter

    # The narrowings the *bounce* path enforces at resolution (the payload
    # filter reaches the handler's predicate): "non-Spirit creature" (Roaming
    # Ghostlight), "other target creature or planeswalker" (Barrin, Tolarian
    # Archmage). Stripped before the blanket refusal below so only these two —
    # not every adjective — pass; the graveyard handlers still see the full
    # filter and keep their own gates.
    bounce_extras = (filt.excluded_subtypes, filt.other_than_source)
    bare_for_gate = dataclasses.replace(
        filt, excluded_subtypes=(), other_than_source=False
    )
    if node.from_zone is None and _reads_no_return_restriction(bare_for_gate):
        raise LoweringError("no return handler honours this restriction", node=node)
    if node.from_zone is not None and _reads_no_return_restriction(filt):
        raise LoweringError("no return handler honours this restriction", node=node)

    source, destination = node.from_zone, node.to

    if source is not None and source.name == "graveyard":
        # Both graveyard handlers search the caster's own graveyard and nowhere
        # else, so "from a graveyard" is a different card, not a wording of this
        # one.
        if source.owner is None or source.owner.kind != "you":
            raise LoweringError("no handler searches a graveyard but your own", node=node)
        if not filt.is_card:
            raise LoweringError("a graveyard holds cards, not permanents", node=node)

        if destination.name == "hand":
            if destination.owner is None or destination.owner.kind != "you":
                raise LoweringError("this handler returns cards to your own hand", node=node)
            return (
                OracleInstruction(
                    "return_creature_from_graveyard_to_hand",
                    "",
                    _graveyard_to_hand_payload(filt),
                ),
            )

        if destination.name == "battlefield":
            if destination.owner is not None:
                raise LoweringError("no handler for a reanimation under another's control", node=node)
            # `reanimate_creature` only ever puts a creature onto the
            # battlefield. Regrowth's untyped "target card" has no lowering
            # here: claiming it would silently narrow the player's choice.
            if filt.card_types != ("creature",):
                raise LoweringError("the reanimation handler only moves creature cards", node=node)
            return (OracleInstruction("reanimate_creature", "", {}),)

        raise LoweringError(f"no handler moves a card to the {destination.name}", node=node)

    if source is None and destination.name == "hand":
        # A permanent going home. `bounce_target_creature` returns it to its
        # owner's hand by construction, so "to your hand" is a different effect
        # (it matters the moment you have stolen the creature) and refuses.
        if destination.owner is None or destination.owner.kind != "owner":
            raise LoweringError("the bounce handler returns a permanent to its owner", node=node)
        if filt.is_card:
            raise LoweringError("no handler bounces a card that is not in play", node=node)
        if set(filt.card_types) not in ({"creature"}, {"creature", "planeswalker"}):
            raise LoweringError("the bounce handler only returns creatures", node=node)
        if any(bounce_extras) or filt.card_types != ("creature",):
            # A narrowed or widened bounce carries what the handler's
            # predicate and the picker must both honour; the bare Unsummon
            # payload stays byte-identical on the branch below.
            payload: dict[str, object] = {"filter": {
                key: value
                for key, value in _filter_payload(filt).items()
                if key in ("type_filter", "exclude_subtypes", "exclude_self")
            }}
            _describe_targets(payload, subject)
            return (OracleInstruction("bounce_target_creature", "", payload),)
        return (OracleInstruction("bounce_target_creature", "", {}),)

    raise LoweringError("no handler for this zone change", node=node)


def _lower_tap_or_untap(node: ast.TapOrUntap) -> tuple[OracleInstruction, ...]:
    """"Tap or untap target <objects>." (Twiddle.)

    The toggle used to honour no restriction at all — ``predicate=lambda p:
    True`` — so any filter had to refuse: "tap or untap target **creature**"
    lowered onto it would have let the card untap a land while still reporting
    supported. It reads the filter now (Tolarian Kraken), the same way the plain
    ``tap_target_permanent`` beside it does, so the narrowing is carried rather
    than refused.

    What still refuses is a narrowing the *matcher* cannot test — the payload is
    handed to ``permanent_matches_filter``, which answers about a permanent alone,
    so a phrase reaching past it would be dropped where it is applied.
    """
    spec = node.subject
    if not isinstance(spec, ast.TargetSpec) or spec.quantifier != "target":
        raise LoweringError("no handler for a non-targeted tap-or-untap", node=node)
    described = _filter_payload(spec.filter)
    if described and object_only_filter(described) is None:
        raise LoweringError("no tap-or-untap handler honours this restriction", node=node)
    payload = _targets_only(spec)
    payload.update(described)
    return (OracleInstruction("tap_or_untap_target", "", payload),)


def _lower_regenerate(node: ast.Regenerate) -> tuple[OracleInstruction, ...]:
    """"Regenerate target creature" / "Regenerate this creature" (CR 701.19).

    Three handlers exist, differing in *what* they shield: the spell's target,
    the ability's own source, or the creature an Aura enchants. Picking by the
    subject keeps each one's contract rather than routing everything through
    the targeted one, which would shield the wrong creature.
    """
    subject = node.subject
    if _is_enchanted(subject):
        return (OracleInstruction("grant_regeneration_to_enchanted_creature", "", {}),)
    if _is_source(subject):
        return (OracleInstruction("grant_regeneration_to_self", "", {}),)
    if not (isinstance(subject, ast.TargetSpec) and subject.quantifier == "target"):
        raise LoweringError("no handler for regenerating this subject", node=node)
    filt = subject.filter
    payload: dict[str, object] = {}
    # Elephant Graveyard regenerates a *target Elephant*. The handler honours
    # exactly one restriction, `subtype_filter`; anything else it would ignore
    # must be refused rather than dropped, or the shield lands on the wrong
    # creature while the card still reports as supported.
    if filt.subtypes:
        if len(filt.subtypes) > 1:
            raise LoweringError("no handler for a multi-subtype regenerate", node=node)
        payload["subtype_filter"] = filt.subtypes[0]
    if (
        filt.colors or filt.excluded_colors or filt.excluded_types
        or filt.with_keywords or filt.without_keywords or filt.attacking or filt.blocking
    ):
        raise LoweringError("no handler honours this regenerate restriction", node=node)
    _describe_targets(payload, subject)
    return (OracleInstruction("grant_regeneration_to_target_creature", "", payload),)


def _lower_sacrifice_unless_pay(node: ast.SacrificeUnlessPay) -> tuple[OracleInstruction, ...]:
    """"Sacrifice this <permanent> unless you pay <cost>."

    Two handlers exist and the noun picks between them — an enchantment's
    prompt is a different registry entry from any other permanent's. Both
    sacrifice the source, so only a self-referential subject is accepted;
    sacrificing something *chosen* needs the pending-choice queue.
    """
    subject = node.subject
    if not _is_source(subject):
        raise LoweringError("no handler for sacrificing a chosen permanent", node=node)
    types = subject.filter.card_types if isinstance(subject, ast.TargetSpec) else ()
    kind = (
        "upkeep_pay_or_sacrifice_enchantment"
        if types == ("enchantment",)
        else "upkeep_pay_or_sacrifice_self"
    )
    return (OracleInstruction(kind, "", {"mana": _full_mana_payload(node.cost)}),)


_LINKED_STEAL_FILTER = ast.ObjectFilter(card_types=("artifact",))


def _lower_gain_control(node: ast.GainControl) -> tuple[OracleInstruction, ...]:
    """``Gain control of target artifact for as long as you control this
    creature.`` (Aladdin, CR 611.3.)

    ``steal_target_permanent_linked_to_self`` takes no payload at all: it looks
    for an artifact in its own source code and ends the control change from
    ``ON_LEAVE_BATTLEFIELD``. So the filter is compared for **equality** against
    the one shape it implements rather than probed field by field — a
    restriction the AST grows later then refuses here instead of being silently
    ignored by a lowering written before it existed.

    No ``targets`` description is emitted: ``engine/targeting.py`` already
    answers "artifact" for this kind, and the payload has to stay byte-identical
    to what the rule it replaces produced.
    """
    subject = node.subject
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier != "target":
        raise LoweringError("the linked-control handler needs a named target", node=node)
    if subject.filter != _LINKED_STEAL_FILTER:
        raise LoweringError(
            "the only linked-control handler gains control of an artifact", node=node
        )
    return (OracleInstruction("steal_target_permanent_linked_to_self", "", {}),)


# Who a sacrifice can be owed by. "You" is the absent value — a bare imperative
# means the effect's own controller — so it is the one payer with no key.
#
# ``target_opponent`` and ``target_player`` stay apart even though the handler
# resolves both to the seat the spell chose: CR 115.4 makes them different
# spells, and collapsing them would offer the caster's own seat as a legal
# target for "target **opponent** sacrifices".
_SACRIFICE_PAYERS: frozenset[str] = frozenset(
    {"you", "each_opponent", "target_opponent", "target_player"}
)

# Two keys the forced-sacrifice prompt performs rather than tests, so they are
# lifted out of the filter instead of refusing the line:
#
# - ``exclude_self`` ("sacrifice **another** creature") rides beside the filter
#   as the prompt's own ``exclude`` argument, which compares by identity — a
#   look-alike on the same battlefield is a different permanent.
# - ``their_choice`` ("a creature **of their choice**", Run Afoul) says the
#   sacrificing player picks, which is what CR 701.21a already says and what the
#   prompt already does. It is read and dropped *here*, at the one lowering whose
#   rule puts the choice there; anywhere else the word refuses.
_SACRIFICE_CARRIED = frozenset({"exclude_self", "their_choice"})


def _forced_sacrifice_filter(filt: ast.ObjectFilter) -> dict | None:
    """The filter payload the forced-sacrifice prompt should list, or None when
    the noun phrase says something the prompt cannot test.

    Two shapes are refused before the key check, because both would reduce to an
    *empty* payload — a prompt listing every permanent on the board:

    - a self-referential or enchanted subject ("sacrifice **this** creature",
      Sea Serpent), which is a different instruction entirely and is read below;
    - a phrase with no card type at all, which no card in the pool prints as a
      sacrifice and which would let the prompt eat a land.
    """
    if filt.is_source or filt.is_enchanted or not filt.card_types:
        return None
    return object_only_filter(filt.to_payload(), carried_separately=_SACRIFICE_CARRIED)


def _lower_sacrifice(node: ast.Sacrifice) -> tuple[OracleInstruction, ...]:
    """Only "sacrifice this <permanent>" has a handler.

    Sacrificing something *chosen* ("sacrifice a creature") is a different
    problem: the choice belongs to a player, so it needs the pending-choice
    machinery rather than an instruction that acts on a known permanent.
    Refusing here keeps that distinction visible instead of quietly sacrificing
    the wrong thing.
    """
    # "Sacrifice a creature" / "sacrifice another creature" (Dire Fleet
    # Warmonger's optional cost): the *controller chooses* which, so this
    # arms the forced-sacrifice prompt rather than acting on a known
    # permanent.
    #
    # "Each opponent sacrifices a creature" (Goremand) and "Target opponent
    # sacrifices …" (Run Afoul) are the same prompt owed by a different set of
    # seats, so they are the same instruction with the payer named — never a
    # second kind. CR 701.21a says the sacrificing player chooses, which is
    # exactly what the prompt already does; the only thing that changes is who
    # is asked, and that is also what lets the printed "of their choice" be
    # read and then dropped rather than refused.
    if (
        node.player.kind in _SACRIFICE_PAYERS
        and isinstance(node.subject, ast.TargetSpec)
        and not node.subject.targeted
        and node.subject.count == 1
        and not _is_source(node.subject)
    ):
        described = _forced_sacrifice_filter(node.subject.filter)
        if described is None:
            raise LoweringError(
                "the sacrifice prompt cannot test this restriction", node=node
            )
        payload: dict[str, object] = {"filter": described}
        if node.subject.filter.other_than_source:
            payload["exclude_self"] = True
        if node.player.kind != "you":
            payload["who"] = node.player.kind
        return (OracleInstruction("sacrifice_matching_permanent", "", payload),)
    if not _is_source(node.subject):
        raise LoweringError("no handler for sacrificing a chosen permanent", node=node)
    if node.player.kind != "you":
        raise LoweringError("no handler for another player sacrificing", node=node)
    return (OracleInstruction("sacrifice_self", "", {}),)


_EXILED_CREATURE = ast.ObjectFilter(card_types=("creature",))


def _lower_exile(node: ast.Exile) -> tuple[OracleInstruction, ...]:
    """"Exile target creature until end of turn." — and nothing else.

    ``exile_target_creature_until_eot`` is the one exile handler that stands on
    its own: it moves the creature to exile and records the return
    (CR 406.1/400.7), so the whole sentence is what it performs. Every part of
    the clause is checked against that rather than dropped —

    * **the duration.** Without it the sentence is a *permanent* exile, which
      this handler does not perform: it would return the creature at cleanup.
    * **the subject.** A chosen creature, not a sweep and not the source: the
      handler resolves one target permanent.

    A duration this file does not implement is refused rather than falling
    through to the permanent exile below. "Exile it until this creature leaves
    the battlefield" is a different effect, and lowering it onto a permanent
    exile would be the loudest possible mis-play: the card would never come
    back.

    With no duration the sentence is a permanent exile, and *which* handler
    performs it is a question about the zone the subject names:

    * **the battlefield** — ``exile_target_permanent``. The permanent leaves
      through ``remove_from_battlefield`` and its card goes to its owner's
      exile (CR 400.3, CR 406.1).
    * **a graveyard** — ``exile_target_graveyard_card``. No permanent is
      involved, so the battlefield-scoped filter payload would point both the
      handler and engine/targeting.py at the wrong zone; ``_filter_payload``
      already refuses that shape, which is why this branch comes first.

    ``exile_creature_gain_life_equal_to_power`` stays unreachable from here: it
    performs *both* halves of Swords to Plowshares' sentence, so a bare
    ``Exile`` lowering onto it would gain life the card never offered.
    """
    if node.duration.kind in ("until_end_of_turn", "this_turn"):
        subject = node.subject
        if (
            isinstance(subject, ast.TargetSpec)
            and subject.quantifier == "target"
            and subject.count == 1
            and subject.filter == _EXILED_CREATURE
        ):
            payload: dict[str, object] = {}
            _describe_targets(payload, subject)
            return (OracleInstruction("exile_target_creature_until_eot", "", payload),)
        raise LoweringError(
            "the temporary-exile handler resolves one targeted creature", node=node
        )
    if node.duration.kind is not None:
        raise LoweringError(
            f"no handler exiles for the duration {node.duration.kind!r}", node=node
        )

    subject = node.subject
    if isinstance(subject, ast.TargetSpec) and subject.quantifier in ("each", "all"):
        # "Exile each permanent with mana value X or less that's one or more
        # colors." (Ugin, the Spirit Dragon's −X.) The payload is hand-rolled:
        # ``to_payload`` cannot carry a *variable* mana-value bound, and
        # dropping the bound would widen the sweep to every mana value.
        filt = subject.filter
        if filt.zone != "battlefield" or filt.is_card:
            raise LoweringError("the exile sweep reads battlefield permanents", node=node)
        payload = {}
        if filt.card_types:
            payload["type_filter"] = (
                filt.card_types[0] if len(filt.card_types) == 1 else list(filt.card_types)
            )
        if filt.colored:
            payload["colored_only"] = True
        if filt.mana_value is not None:
            bound = filt.mana_value.value
            payload["mana_value"] = {
                "op": filt.mana_value.op,
                "value": bound.value if isinstance(bound, ast.Fixed) else bound.name,
            }
        leftovers = _restrictions_beyond(
            filt, frozenset({"card_types", "colored", "mana_value", "zone"})
        )
        if leftovers:
            raise LoweringError(
                f"the exile sweep does not honour {leftovers[0]!r}", node=node
            )
        return (OracleInstruction("exile_all_matching", "", payload),)
    if (
        not isinstance(subject, ast.TargetSpec)
        or subject.quantifier != "target"
        or subject.count != 1
    ):
        # A sweep with no handler and a bare "exile it" are separate effects;
        # only the shapes above are implemented.
        raise LoweringError(
            "only a single chosen permanent or card is exiled", node=node
        )

    filt = subject.filter
    if filt.zone == "graveyard" and filt.is_card:
        if filt.zone_owner is not None or filt.card_types or filt.subtypes or filt.colors:
            # The picker this lowers onto enumerates *any* card in *any*
            # graveyard. Narrowing it is a payload-derived spec, not something
            # to fake by dropping the narrowing here.
            raise LoweringError(
                "no graveyard picker narrows to this card or this player yet",
                node=node,
            )
        return (
            OracleInstruction("exile_target_graveyard_card", "", {"any_card": True}),
        )

    exile_payload = _filter_payload(filt)
    _describe_targets(exile_payload, subject)
    return (OracleInstruction("exile_target_permanent", "", exile_payload),)


def _lower_phase_out(node: ast.PhaseOut) -> tuple[OracleInstruction, ...]:
    """CR 702.26's two printed shapes: one chosen creature (Teferi, Master of
    Time's −3) and a swept set belonging to a targeted opponent with the
    can't-phase-in rider (Teferi, Timeless Voyager's −8)."""
    subject = node.subject
    if _is_target(subject):
        assert isinstance(subject, ast.TargetSpec)
        if node.cant_phase_in_until_your_next_turn:
            raise LoweringError(
                "the phase-in block rider only rides the opponent sweep", node=node
            )
        payload: dict[str, object] = {}
        _describe_targets(payload, subject)
        return (OracleInstruction("phase_out_target", "", payload),)
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "each"
        and subject.filter.card_types == ("creature",)
        and subject.filter.controller == "target_opponent"
    ):
        return (
            OracleInstruction(
                "phase_out_opponent_creatures",
                "",
                {
                    "cant_phase_in_until_your_next_turn": node.cant_phase_in_until_your_next_turn,
                    "targets": {"quantifier": "target", "kind": "player", "opponents_only": True},
                },
            ),
        )
    raise LoweringError("no handler phases out this subject", node=node)


def _lower_put_on_library_top(node: ast.PutOnLibraryTop) -> tuple[OracleInstruction, ...]:
    """"Put target creature on top of its owner's library." (Teferi, Timeless
    Voyager's −3.) One chosen battlefield creature; the owner is resolved by
    the handler (CR 400.3), which is why no player rides the payload."""
    if not _is_target(node.target):
        raise LoweringError("the tuck handler resolves one chosen creature", node=node)
    assert isinstance(node.target, ast.TargetSpec)
    filt = node.target.filter
    if filt.card_types != ("creature",) or filt.zone != "battlefield" or filt.is_card:
        raise LoweringError("the tuck handler reads battlefield creatures", node=node)
    payload: dict[str, object] = {}
    _describe_targets(payload, node.target)
    return (OracleInstruction("put_target_on_library_top", "", payload),)


def _lower_put_onto_battlefield(node: ast.PutOntoBattlefield) -> tuple[OracleInstruction, ...]:
    """The two "put … onto the battlefield" shapes the pool prints:

    * "Put up to seven permanent cards from your hand onto the battlefield."
      (Ugin, the Spirit Dragon's −10) — an up-to-N sweep of the caster's own
      hand, chosen by its controller.
    * "Put target creature card from a graveyard onto the battlefield under
      your control." (Liliana, Waker of the Dead's emblem) — a one-card
      reanimation from any graveyard, with any granted keywords riding along
      ("It gains haste.").
    """
    target = node.target
    if not isinstance(target, ast.TargetSpec):
        raise LoweringError("no handler puts that onto the battlefield", node=node)
    filt = target.filter
    if filt.zone == "hand":
        if filt.zone_owner is None or filt.zone_owner.kind != "you":
            raise LoweringError("only your own hand has a handler here", node=node)
        if target.quantifier != "up_to" or not filt.is_card:
            raise LoweringError("the from-hand handler reads 'up to N … cards'", node=node)
        return (
            OracleInstruction(
                "put_cards_from_hand_onto_battlefield",
                "",
                {
                    "count": target.count,
                    "card_types": list(filt.card_types),
                    # An empty type list with is_card means "permanent cards" —
                    # the handler holds the CR 110.4 list of permanent types.
                    "permanents_only": not filt.card_types,
                },
            ),
        )
    if filt.zone == "graveyard":
        if not _is_target(target) or not filt.is_card:
            raise LoweringError("the reanimation handler reads one chosen card", node=node)
        if filt.card_types != ("creature",):
            raise LoweringError("the reanimation handler only moves creature cards", node=node)
        return (
            OracleInstruction(
                "reanimate_creature",
                "",
                {
                    # "from a graveyard" (no owner) widens the search to every
                    # player's graveyard; "under your control" is CR 400.3's
                    # exception spelled out, honored by the handler.
                    "any_graveyard": filt.zone_owner is None,
                    "under_your_control": node.under_your_control,
                    "gains": list(node.gains),
                },
            ),
        )
    raise LoweringError("no handler for this battlefield entry", node=node)


def _fused_exile_then_controller_life(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"Exile target creature. Its controller gains life equal to its power."
    (Swords to Plowshares.)

    Fused because the handler is: it pops the creature off the battlefield and
    reads ``effective_power`` from the object it just removed, which no pair of
    independent instructions can do — the second one would be looking for a
    permanent that is no longer there. Every part of the shape is checked
    against what that handler implements, so a card exiling something else, or
    paying the life to someone else, falls through and is refused by
    :func:`_lower_exile` rather than borrowing this.

    Returning None rather than raising leaves a near miss to be reported
    against the effect it actually failed on.
    """
    if len(steps) != 2:
        return None
    exile, gain = steps
    if not isinstance(exile, ast.Exile) or not isinstance(gain, ast.GainLife):
        return None
    subject = exile.subject
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier != "target":
        return None
    if subject.filter != _EXILED_CREATURE:
        return None
    if gain.player.kind != "controller":
        return None
    if gain.amount != ast.ThatMuch("its_power"):
        return None
    return (OracleInstruction("exile_creature_gain_life_equal_to_power", "", {}),)
