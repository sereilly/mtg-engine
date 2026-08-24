"""Lowering board changes: destruction, bouncing, tapping, control, exile.

Destroy (targeted and sweeping), the delayed destroy a combat trigger binds,
tap/untap, return-to-zone, regeneration, control changes, sacrifice, and exile.

Control changes lower to a *contribution* rather than a move — see
`engine/control.py`. What lowering owes is the timestamped source, not a new
owner.
"""

import dataclasses

from ...oracle_types import OracleInstruction
from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS, object_only_filter
from .. import ast
from ..errors import LoweringError
from ._common import (
    _describe_several_targets,
    _describe_targets,
    _filter_payload,
    _full_mana_payload,
    _is_enchanted,
    _is_source,
    _is_target,
    _is_you,
    _names_several_targets,
    _restrictions_beyond,
    _targets_only,
    _UNTAPPED_PERMANENTS,
    is_mana_value_x,
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


# Trigger events that bind a *blocking pair*, so "destroy that creature at end
# of combat" names the other half of it. Both fire sites push the blocker as the
# trigger's target, which is what the handler resolves — so the sentence only
# means what it says while one of these fired.
_BLOCK_PAIR_EVENTS = frozenset({
    "creature_blocks_or_blocked_by_nonwall",   # Thicket Basilisk, Cockatrice
    "creature_becomes_blocked",                # Battering Ram
})


# Trigger events whose fire site stamps the object the event was about onto the
# stack item, so an effect may say "that <noun>" and mean it.
_EVENT_SUBJECT_DESTROY_EVENTS: frozenset[str] = frozenset({
    # Hooded Blightfang: "… deals damage to a planeswalker, destroy **that**
    # planeswalker". The damaged object is what `damage_events._announce`
    # stamps onto the stack item, so "that <noun>" under this event names it.
    # A damage event whose recipient was a player stamps nothing, and the
    # destroy then resolves nothing rather than finding a permanent by index.
    "damage_dealt",
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
            # "Destroy all Equipment attached to that creature." (Turn to
            # Slag.) A sweep over a *narrowed* set rather than a card type, so
            # it carries the filter instead of naming a per-scope handler.
            described = _filter_payload(filt)
            if object_only_filter(described) is None:
                raise LoweringError("no sweep handler for this subtype", node=node)
            if filt.attached_to is not None:
                described["attached_to"] = filt.attached_to
            if node.no_regen:
                described["bypass_regeneration"] = True
            return (OracleInstruction("destroy_all_matching", "", described),)
        # "Destroy all creatures blocking or blocked by it." (Abu Ja'far.)
        # The noun phrase parses now (Sentinel's target reads the same
        # relation), but this sweep must not fall through to the generic
        # creature sweep below — that path keys on card types alone, so the
        # relation would be dropped and the trigger would wipe the board.
        # Refused rather than lowered onto the hook's
        # `destroy_creatures_in_combat_with_source`: taking the line over is
        # an accept-probe review away (the deletion probe flags the implicit
        # "all" exactly as it did for every other destroy sweep), and until
        # that review the refusal hands the line back to
        # `card_hooks.CARD_LINE_INSTRUCTIONS`, which implements it in full.
        if filt.in_combat_with_source or filt.dealt_damage_to_source_this_turn:
            raise LoweringError(
                "a destroy sweep over a source relation stays with its card "
                "hook until the probe review takes it", node=node,
            )
        kind = _DESTROY_ALL_KINDS.get(tuple(sorted(filt.card_types)))
        if kind is None:
            raise LoweringError("no sweep handler for this destroy scope", node=node)
        payload = {"bypass_regeneration": True} if node.no_regen else {}
        return (OracleInstruction(kind, "", payload),)

    # "Destroy **it**", where the sentence's "it" is the permanent this Aura
    # enchants (Blight: "When enchanted land becomes tapped, destroy it"), and
    # the equivalent spelling that names it outright. Its own handler for the
    # reason `untap_enchanted_creature` and
    # `grant_regeneration_to_enchanted_creature` have theirs: the subject is
    # known from the source's own attachment, so routing it through the
    # targeted destroy would ask for a pick the card never offers — and would
    # find a permanent by index on whichever battlefield the context happened
    # to carry.
    if _is_enchanted(spec):
        attached_payload: dict[str, object] = {}
        if node.no_regen:
            attached_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("destroy_attached_permanent", "", attached_payload),
        )

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

    # "Destroy target artifact **with mana value X**." (Detonate.) The bound is
    # the X chosen on the cast, so it has no literal to ride the payload as an
    # ordinary narrowing — it is split off into a flag the legality check reads
    # against that X, exactly as Spell Blast's counter does. Splitting it out
    # rather than leaving it on the filter is what keeps `_filter_payload` free
    # to go on refusing every *other* variable bound.
    mv_equals_x = is_mana_value_x(filt.mana_value)
    if mv_equals_x:
        # Off the *spec* as well as the local filter: `_describe_targets` below
        # builds the picker's description from the spec's own filter, so a copy
        # left behind there would refuse the line at that call instead.
        filt = dataclasses.replace(filt, mana_value=None)
        spec = dataclasses.replace(spec, filter=filt)
    payload = _filter_payload(filt)
    if mv_equals_x:
        payload["mv_equals_x"] = True
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
    filt = spec.filter
    if filt.card_types != ("creature",) or _restrictions_beyond(
        filt, frozenset({"card_types", "subtypes"})
    ):
        raise LoweringError("no delayed-destroy handler narrows what it destroys", node=node)
    if node.no_regen:
        raise LoweringError(
            "the end-of-combat destroy handler does not bypass regeneration", node=node
        )
    # "destroy that **Wall**" (Battering Ram). The trigger that fired already
    # required a Wall, so the noun re-states what was bound rather than choosing
    # again — but it rides the payload and the handler tests it anyway, because
    # a word consumed and never read is a word that could be deleted.
    payload: dict[str, object] = {}
    if filt.subtypes:
        payload["subtype_filter"] = filt.subtypes[0]
    return (OracleInstruction("delayed_destroy_blocked_or_blocker", "", payload),)


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


def _lower_attach(node: ast.Attach) -> tuple[OracleInstruction, ...]:
    """"Attach this permanent to target creature you control." (CR 702.6a.)

    One handler, ``attach_source_to_target``, and one shape for it: the source
    moves, one chosen permanent receives it. The host filter rides the payload
    exactly as a tap's does — ``type_filter``/``controller`` for the resolution
    to re-check (CR 608.2b), ``targets`` for ``engine/targeting.py`` to build
    the picker from — so CR 702.6c's narrowed equip ("target legendary creature
    you control") costs nothing here. A chosen *subject* ("target Equipment you
    control", Brass Squire) has no handler yet and refuses naming that.
    """
    if not isinstance(node.subject, ast.TargetSpec) or not _is_source(node.subject):
        raise LoweringError(
            "no handler attaches anything but the source itself", node=node
        )
    if not isinstance(node.host, ast.TargetSpec) or not _is_target(node.host):
        raise LoweringError("attach needs one chosen permanent to attach to", node=node)
    payload = _filter_payload(node.host.filter)
    _describe_targets(payload, node.host)
    return (OracleInstruction("attach_source_to_target", "", payload),)


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
    elif _is_enchanted(spec):
        # "When this Aura enters, tap enchanted creature." (Paralyze, Venarian
        # Gold, Cocoon.) The tap twin of the enchanted untap above, for the
        # same reason: the subject is the source's own attachment, so no
        # target exists to route through the targeted tap.
        return (OracleInstruction("tap_enchanted_creature", "", {}),)

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
    # "Untap all lands you control." (Reset.) "Tap all legendary creatures."
    # (Arena of the Ancients.) A sweep over a described set: untargeted, so
    # nothing is chosen and every matching permanent is affected. Two gates,
    # the pairing round 68 established: `_restrictions_beyond` reads the AST so
    # a narrowing `to_payload` never emits cannot vanish silently, and the key
    # check holds the payload to what `subject_matches` demonstrates — a key
    # outside that set is one the handler would quietly ignore, which would
    # tap or untap a strictly larger set than the card prints. The honoured
    # fields are only what the pool prints (round 43's rule): a bare type, a
    # supertype (Arena of the Ancients' "legendary") and a controller
    # ("you control", Reset).
    if spec.quantifier in ("all", "each") and not spec.targeted:
        leftovers = _restrictions_beyond(
            spec.filter, frozenset({"card_types", "supertypes", "controller"})
        )
        if leftovers:
            raise LoweringError(
                "the tap/untap sweep cannot narrow by: " + ", ".join(leftovers),
                node=node,
            )
        described = _filter_payload(spec.filter)
        if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
            raise LoweringError(
                "the tap/untap sweep cannot test this restriction", node=node
            )
        kind = "tap_all_matching" if isinstance(node, ast.Tap) else "untap_all_matching"
        return (OracleInstruction(kind, "", described),)
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
        # "Untap X target lands." (Candelabra of Tawnos.) Untap reaches the same
        # several-targets opt-in the tap above uses: `untap_target_permanent`
        # resolves a list when the description says there is one.
        #
        # Gated the same way, and for the same reason — the filter must be one
        # the handler's `permanent_matches_filter` can answer in full, or a
        # narrowing would be dropped and the untap would reach more permanents
        # than the card names.
        if (
            isinstance(node, ast.Untap)
            and not _restrictions_beyond(
                spec.filter, frozenset({"card_types", "controller", "other_than_source"})
            )
        ):
            several = _filter_payload(spec.filter)
            _describe_several_targets(several, spec)
            return (OracleInstruction("untap_target_permanent", "", several),)
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
    # Every other narrowing rides the generic handler, which applies it. It used
    # to refuse here because that handler ignored filters entirely — lowering
    # "untap target land" onto it would have untapped a creature — and the land
    # form above keeps its own handler so its payload stays byte-identical.
    if object_only_filter(payload) is None:
        raise LoweringError("no untap handler honors this restriction", node=node)
    untap_payload = dict(payload)
    _describe_targets(untap_payload, spec)
    return (OracleInstruction("untap_target_permanent", "", untap_payload),)


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


def _lower_gain_control(
    node: ast.GainControl, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """``Gain control of <subject> <duration>.``

    Four shapes, and which one a card is depends on its duration and subject:

    * "…until end of turn" on a chosen target (Traitorous Greed) — an ordinary
      targeted instruction carrying its noun phrase.
    * "…until end of turn" on "**that creature**" (Disharmony) — the object a
      previous step of this same effect chose, read out of the resolution
      scratchpad; a producer must have run, the same discipline
      ``_lower_doesnt_untap_next_step`` applies.
    * "…for as long as you control this creature" — Aladdin's linked steal
      when targeted, The Wretched's blocker sweep when the subject is "all
      creatures blocking this creature".
    * "…and this creature remains tapped" (Willow Satyr, Rubinia Soulsinger) —
      the two-condition linked duration; the conditions ride the payload and
      the state-based sweep re-checks them (CR 611.2b,
      ``engine/control.LINKED_CONTROL_CONDITIONS``).

    ``steal_target_permanent_linked_to_self`` takes no payload at all: it looks
    for an artifact in its own source code and ends the control change from
    ``ON_LEAVE_BATTLEFIELD``. So Aladdin's filter is compared for **equality**
    against the one shape that handler implements rather than probed field by
    field — a restriction the AST grows later then refuses here instead of
    being silently ignored by a lowering written before it existed. No
    ``targets`` description is emitted for it: ``engine/targeting.py`` already
    answers "artifact" for the kind, and the payload has to stay byte-identical
    to what the rule it replaces produced.
    """
    subject = node.subject
    if not isinstance(subject, ast.TargetSpec):
        raise LoweringError("the linked-control handler needs a named target", node=node)
    if node.duration == "until_end_of_turn":
        if subject.quantifier == "that":
            # "Gain control of **that creature** until end of turn."
            # (Disharmony.) The bound object, not a second choice — and bound
            # by id when the earlier step resolved, so a restated narrowing
            # would have nothing to narrow.
            if _restrictions_beyond(subject.filter, frozenset({"card_types"})):
                raise LoweringError(
                    "a bound object carries no narrowing the record could honour",
                    node=node,
                )
            if _UNTAPPED_PERMANENTS not in produced:
                raise LoweringError(
                    f"back-reference to {_UNTAPPED_PERMANENTS!r} with no "
                    "producer in this effect",
                    node=node,
                )
            return (
                OracleInstruction(
                    "gain_control_until_eot", "",
                    {"permanents_from": _UNTAPPED_PERMANENTS},
                ),
            )
        if subject.quantifier != "target":
            raise LoweringError(
                "the linked-control handler needs a named target", node=node
            )
        described = _filter_payload(subject.filter)
        if object_only_filter(described) is None:
            raise LoweringError(
                "the control change cannot test this restriction", node=node
            )
        _describe_targets(described, subject)
        return (OracleInstruction("gain_control_until_eot", "", described),)
    if node.duration == "while_you_control_source_tapped":
        # Willow Satyr / Rubinia Soulsinger. The filter must be one the
        # resolution can test (Willow's "legendary" is the supertypes key),
        # and the conditions are payload data so the sweep stays one reader.
        if subject.quantifier != "target":
            raise LoweringError(
                "the linked-control handler needs a named target", node=node
            )
        described = _filter_payload(subject.filter)
        if object_only_filter(described) is None:
            raise LoweringError(
                "the control change cannot test this restriction", node=node
            )
        _describe_targets(described, subject)
        described["link_conditions"] = [
            "you_control_source", "source_remains_tapped",
        ]
        return (OracleInstruction("steal_target_linked_to_source", "", described),)
    # while_you_control_source
    if (
        subject.quantifier == "all"
        and subject.filter.blocking_source
        and not _restrictions_beyond(
            subject.filter, frozenset({"card_types", "blocking_source"})
        )
        and subject.filter.card_types == ("creature",)
    ):
        # "Gain control of all creatures blocking this creature…"
        # (The Wretched.) The set was fixed when the trigger fired
        # (CR 611.2c): the end-of-combat dispatcher captures the blockers by
        # id into the trigger context, because by resolution the combat
        # record has been cleared.
        return (
            OracleInstruction(
                "steal_blockers_of_source", "",
                {"link_conditions": ["you_control_source"]},
            ),
        )
    if subject.quantifier != "target":
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


def _fused_upkeep_pay_to_untap(
    node: ast.TriggeredAbilityNode,
) -> tuple[OracleInstruction, ...] | None:
    """"At the beginning of your upkeep, you may pay {N}. If you do, untap this
    <permanent>." (Mana Vault, Basalt Monolith, Brass Man, Island Fish Jasconius.)

    Fused for the reason every upkeep shape is fused: the dispatcher in
    ``engine/phases/upkeep_effects.py`` is keyed on the (trigger condition,
    instruction kind) pair, and ``upkeep_pay_to_untap_self``'s handler
    implements the whole prompt — the pay/decline choice, the affordability
    check and the untap. A decomposed ``may(pay, untap_self)`` is a truer
    reading of the sentence and has no handler at all.

    Recognised on the **node**, before ``lower_statement`` runs, because two of
    the four cards would never reach a post-hoc check: the generic ``may``
    lowering refuses a coloured optional cost outright (Island Fish Jasconius
    pays {U}{U}{U}), and the refusal is right for every other card that takes
    that path. Only the fused kind's own handler knows how to charge one.

    Returns None — not a refusal — for anything that is not exactly this shape,
    so a near miss ("…untap target creature", "…and you gain 1 life") drops back
    to the ordinary lowering and is refused there by name.
    """
    if node.event.kind != "upkeep_self" or node.intervening_if is not None:
        return None
    statement = node.statement
    if not isinstance(statement, ast.May):
        return None
    if statement.action is not None or statement.otherwise is not None:
        return None
    if not isinstance(statement.cost, ast.ManaCost) or not _is_you(statement.actor):
        return None
    # The consequence is untapping the source and nothing else. `untap_self`'s
    # handler is not consulted here — the fused handler untaps `ctx.permanent`
    # directly — so the subject is checked against the source rather than
    # against what any untap lowering would accept.
    then = statement.then
    if not isinstance(then, ast.Untap) or not _is_source(then.subject):
        return None
    return (
        OracleInstruction(
            "upkeep_pay_to_untap_self", "", {"mana": _full_mana_payload(statement.cost)}
        ),
    )


def _lower_sacrifice_expansion_permanents(
    node: ast.SacrificeExpansionPermanents,
) -> tuple[OracleInstruction, ...]:
    """Golgothian Sylex. The set code was resolved at parse time from the
    manifest, so the instruction carries which set rather than which words."""
    return (
        OracleInstruction(
            "sacrifice_expansion_permanents", "", {"set_code": node.set_code}
        ),
    )


def _lower_doesnt_untap_while_source_tapped(
    node: ast.DoesntUntapWhileSourceTapped,
) -> tuple[OracleInstruction, ...]:
    """Phyrexian Gremlins. The subject is the permanent the sentence before it
    tapped — a back-reference, so nothing is described for the picker: the
    choice was made by that sentence and describing it again would ask for a
    second one."""
    subject = node.subject
    # "Tap target artifact. **It** doesn't untap …" — the pronoun refers to the
    # permanent the sentence before it chose. The noun parser collapses a bare
    # "it" onto the same self-reference shape the card's own name produces, so
    # what is required here is that shape and nothing narrower: an adjective
    # would be restating a choice already made, and a *chosen* subject would be
    # a second target the card never offered.
    #
    # The handler reads the chosen target and does nothing when there is none,
    # which is the failing-safe direction — this sentence is only printed after
    # one that chooses.
    if not (
        isinstance(subject, ast.TargetSpec)
        # "**It** doesn't untap…" or the card naming itself — both spellings of
        # the same back-reference, which is why the pronoun's own quantifier is
        # accepted beside "this".
        and subject.quantifier in ("this", "it")
        and subject.filter == ast.ObjectFilter(is_source=True)
    ):
        raise LoweringError(
            "the linked untap restriction acts on the permanent the previous "
            "sentence tapped",
            node=node,
        )
    return (OracleInstruction("restrict_untap_while_source_tapped", "", {}),)


def _lower_delayed_self_action(
    node: ast.DelayedSelfAction,
) -> tuple[OracleInstruction, ...]:
    """Rocket Launcher / Rakalite. The action is payload, the delay is the kind
    — because what a reader downstream must not get wrong is *when*."""
    return (
        OracleInstruction(
            # Keyed `self_action`, not `action`: a payload key called
            # "action" is read as *nested instructions* by the composition
            # readers (test_front_end_safety's flattener among them), and a
            # bare word sitting where a list of steps is expected is a crash
            # rather than a wrong answer — but only because something looked.
            "arm_self_action_at_next_end_step", "", {"self_action": node.action}
        ),
    )
