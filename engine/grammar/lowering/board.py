"""Lowering board changes: destruction, bouncing, tapping, control, exile.

Destroy (targeted and sweeping), the delayed destroy a combat trigger binds,
tap/untap, return-to-zone, regeneration, control changes, sacrifice, and exile.

Control changes lower to a *contribution* rather than a move — see
`engine/control.py`. What lowering owes is the timestamped source, not a new
owner.
"""

import dataclasses

from ...oracle_types import OracleInstruction
from ...subject_filters import (
    TESTABLE_SUBJECT_FILTER_KEYS, object_only_filter, untestable_filter_keys,
)
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
    is_mana_value_x,
)
from ._events import (
    _EVENT_SUBJECT_PLAYERS,
    EVENT_SUBJECT_PLAYER,
    binds_block_pair,
    names_attached_permanent,
    CHOSEN_PERMANENT,
    _BOUND_OBJECT_DELAYED_EVENTS,
    _UNTAPPED_PERMANENTS,
)


#: Where a chosen attachment host is recorded for the step behind it to read.
#: One name in one place, because the two instructions the lowering emits have
#: to agree about it and a literal written twice is two chances to disagree.


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


def _lower_destroy(
    node: ast.Destroy,
    event: str | None = None,
    event_subject: object | None = None,
) -> tuple[OracleInstruction, ...]:
    if node.delay:
        return _lower_delayed_destroy(node, event, event_subject)
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
            if untestable_filter_keys(described):
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
        # "Destroy all creatures that were blocked by that creature this
        # turn." (Glyph of Doom.) A relation to the object the delayed ability
        # was bound to, which `permanent_matches_filter` cannot answer — it is
        # a record on *that* creature, not a characteristic of these — so it
        # travels as its own payload key and the handler resolves it.
        #
        # Refused under any other event, and refused *before* the generic paths
        # below, because `_filter_payload` does not carry the field: falling
        # through would leave the sweep with card types alone and destroy every
        # creature on the battlefield. That is the same shape as the colour
        # dropped from `Destroy all black creatures`, and the reason this
        # branch is a branch rather than a payload key.
        if filt.blocked_by_bound_object:
            if event not in _BOUND_OBJECT_DELAYED_EVENTS:
                raise LoweringError(
                    "\"that creature\" names the object a delayed ability was "
                    "bound to, and this event binds none", node=node,
                )
            blocked_payload = _filter_payload(
                filt, carried_separately=frozenset({"blocked_by_bound_object"})
            )
            if untestable_filter_keys(blocked_payload):
                raise LoweringError("no sweep handler for this narrowing", node=node)
            blocked_payload["blocked_by_bound_object"] = True
            if node.no_regen:
                blocked_payload["bypass_regeneration"] = True
            return (
                OracleInstruction("destroy_all_matching", "", blocked_payload),
            )
        # "Destroy all creatures that were blocked by **target Wall** this
        # turn." (Glyph of Reincarnation.) The sibling of the branch above, and
        # a branch for its reason: the relation has no payload form, so falling
        # through to the generic paths would leave the sweep with card types
        # alone and destroy every creature on the battlefield.
        #
        # What differs is where the blocker comes from. It is this spell's own
        # target, so the noun phrase the relation carries is hoisted into a
        # ``targets`` description — that is the evidence
        # ``engine/targeting.py`` reads to raise a Wall picker, and without it
        # the spell would be cast with nothing chosen and resolve against no
        # blocker at all.
        if filt.blocked_by_target_object is not None:
            blocker = filt.blocked_by_target_object
            blocked_payload = _filter_payload(
                filt, carried_separately=frozenset({"blocked_by_target_object"})
            )
            if untestable_filter_keys(blocked_payload):
                raise LoweringError("no sweep handler for this narrowing", node=node)
            blocker_payload = _filter_payload(blocker)
            if object_only_filter(blocker_payload) is None:
                raise LoweringError(
                    "no picker offers a blocker narrowed this way", node=node
                )
            blocked_payload["blocked_by_target_object"] = True
            blocked_payload["targets"] = {
                "kind": "object", "count": 1, "filter": blocker_payload,
            }
            if node.no_regen:
                blocked_payload["bypass_regeneration"] = True
            return (
                OracleInstruction("destroy_all_matching", "", blocked_payload),
            )
        if filt.in_combat_with_source or filt.dealt_damage_to_source_this_turn:
            raise LoweringError(
                "a destroy sweep over a source relation stays with its card "
                "hook until the probe review takes it", node=node,
            )
        # "Destroy all **black** creatures." (Cleanse.) / "Destroy all
        # **nonblack** creatures." (Hellfire.) The type-keyed sweeps below take
        # an empty payload and read their scope off their own kind, so every
        # other word of the noun phrase is a key nothing would carry — and a
        # dropped colour here is not a card that does less, it is a card that
        # destroys the whole board. Routed to the filtered sweep instead, which
        # is the same handler "Destroy all Equipment attached to that creature"
        # already uses; refused when the narrowing is one the matcher cannot
        # test, for the reason `object_only_filter` exists.
        described = _filter_payload(filt)
        narrowing = {
            key: value for key, value in described.items()
            if key not in ("type_filter", "type_filter_all")
        }
        if narrowing:
            if untestable_filter_keys(described):
                raise LoweringError("no sweep handler for this narrowing", node=node)
            narrowed_payload = dict(described)
            if node.no_regen:
                narrowed_payload["bypass_regeneration"] = True
            return (
                OracleInstruction("destroy_all_matching", "", narrowed_payload),
            )
        kind = _DESTROY_ALL_KINDS.get(tuple(sorted(filt.card_types)))
        if kind is None:
            # A type union no per-scope kind names — "Destroy all artifacts,
            # creatures, and lands" (Jokulhaups). The **filtered** sweep already
            # answers it: `type_filter` takes a list and
            # `permanent_matches_filter` reads one as a union, which is the same
            # question the per-scope kinds ask with the answer baked into the
            # kind. So this routes rather than refuses, and a set printing a
            # fourth union costs no row.
            #
            # The named kinds stay for the unions that have one: the compiler,
            # this table and the behaviour snapshots all key on them, and
            # rewriting a shipped card's instruction kind is a change to what
            # those snapshots describe rather than to what the card does.
            if not filt.card_types:
                raise LoweringError(
                    "no sweep handler for this destroy scope", node=node
                )
            union_payload = dict(described)
            if node.no_regen:
                union_payload["bypass_regeneration"] = True
            return (
                OracleInstruction("destroy_all_matching", "", union_payload),
            )
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
    #
    # "…destroy **that land**" (Erosion) is the same referent spelled with the
    # noun repeated instead of the pronoun, and only under an event whose
    # condition already named it -- see `names_attached_permanent`. Asked here,
    # above the "that" branch below, because that branch reads the *firing
    # event's* object and would destroy whatever the fire site had stamped.
    if names_attached_permanent(spec, event):
        attached_payload: dict[str, object] = {}
        if node.no_regen:
            attached_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("destroy_attached_permanent", "", attached_payload),
        )

    # "**Destroy this Aura.**" (Imprison.) The sentence names its own source —
    # the SELF token, or "this <type>" where the type is the source's own — so
    # like the attached destroy above it chooses nothing and there is nothing
    # for a picker to offer. Its own handler rather than the targeted one for
    # exactly that reason: routed through `destroy_target_permanent` the
    # ability would ask for a pick the card never printed and then destroy
    # whichever permanent the resolution context happened to carry.
    #
    # Above the "that" branch below, and not folded into it: "that creature" is
    # the object a trigger's *event* was about and only exists under an event
    # that recorded one, while "this Aura" is the ability's source and is
    # answerable under every event and none.
    if _is_source(spec):
        self_payload: dict[str, object] = {}
        if node.no_regen:
            self_payload["bypass_regeneration"] = True
        return (OracleInstruction("destroy_self", "", self_payload),)

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
        # "…destroy **that creature**" inside a *delayed* ability (War Barge).
        # The object is the one the creating ability bound (CR 603.7c), carried
        # by id in the trigger's context — never a pick, and never the object
        # the delay *watched*, which for this card is the artifact itself. Its
        # own kind for the reason `destroy_self` and `destroy_attached_permanent`
        # have theirs: routed through the targeted destroy the ability would ask
        # for a choice the card never offered, and then destroy whichever
        # permanent the resolution context happened to carry.
        if event in _BOUND_OBJECT_DELAYED_EVENTS:
            bound_payload = _filter_payload(filt)
            if node.no_regen:
                bound_payload["bypass_regeneration"] = True
            return (
                OracleInstruction("destroy_bound_permanent", "", bound_payload),
            )
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
    node: ast.Destroy,
    event: str | None,
    event_subject: object | None = None,
) -> tuple[OracleInstruction, ...]:
    """"…destroy that creature at end of combat." (Thicket Basilisk, Cockatrice.)

    The handler destroys the creature this one blocked or was blocked by, which
    is a fact only the trigger knows — so the *event* is checked as strictly as
    the subject is. Under any other trigger the same sentence names a creature
    nobody recorded, and the handler would destroy nothing while the card
    reported as supported.
    """
    if not binds_block_pair(event, event_subject):
        raise LoweringError(
            "a delayed destroy at end of combat only has a handler on a "
            "blocks-or-blocked trigger that names one creature",
            node=node,
        )
    spec = node.subject
    # "that creature" (Thicket Basilisk) and "**the other** creature" (Infinite
    # Authority) are one referent under this event: the pair has two members,
    # the ability's own creature is one of them, and both spellings name the
    # one `block_pair_permanents` returns. The ordinal is admitted only here,
    # where a pair is what the trigger bound.
    if not isinstance(spec, ast.TargetSpec) or spec.quantifier not in ("that", "other"):
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
    # The printed narrowing is payload, not a hand-listed key. Elephant
    # Graveyard's "target Elephant" and Horror of Horrors' "target black
    # creature" are the same noun phrase, and the shield's eligibility test is
    # the one matcher every other filter reader uses. What must not ride along
    # is a narrowing that matcher cannot answer — the shield would land on a
    # creature the card never named — so the payload is gated by
    # `object_only_filter`: the resolution picks from a single player's
    # battlefield, with no observer seat and no source to compare against.
    described = _filter_payload(filt)
    carried = object_only_filter(described)
    if carried is None:
        raise LoweringError("no handler honours this regenerate restriction", node=node)
    payload: dict[str, object] = dict(carried)
    _describe_targets(payload, subject)
    return (OracleInstruction("grant_regeneration_to_target_creature", "", payload),)


def _lower_destroy_unless_pay(
    node: ast.DestroyUnlessPay, event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """"At the beginning of your upkeep, destroy this creature unless you pay
    {3}{B}{B}{B}. If this creature is destroyed this way, it deals 7 damage to
    you." (Cosmic Horror.)

    Fused, like the sacrifice twin above and for the same reason: the upkeep
    dispatcher is keyed on (trigger condition, instruction kind) pairs whose
    handlers run the whole pay-or-consequence prompt. The event is threaded
    down here rather than inferred, exactly as `_lower_damage_unless_pay` does
    it — the handler takes its seat and its mana from the upkeep context, so
    under any other trigger there is nothing to dispatch to and the line must
    refuse rather than compile into a card that does nothing.
    """
    if not _is_source(node.subject):
        raise LoweringError(
            "the pay-or-destroy prompt destroys the ability's own source", node=node
        )
    if event != "upkeep_self":
        raise LoweringError(
            f"no handler pairs {event!r} with a pay-or-destroy prompt", node=node
        )
    payload: dict[str, object] = {"mana": _full_mana_payload(node.cost)}
    if node.damage_if_destroyed is not None:
        payload["damage_if_destroyed"] = node.damage_if_destroyed
    return (OracleInstruction("upkeep_pay_or_destroy_self", "", payload),)


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




# Who a sacrifice can be owed by. "You" is the absent value — a bare imperative
# means the effect's own controller — so it is the one payer with no key.
#
# ``target_opponent`` and ``target_player`` stay apart even though the handler
# resolves both to the seat the spell chose: CR 115.4 makes them different
# spells, and collapsing them would offer the caster's own seat as a legal
# target for "target **opponent** sacrifices".
#
# ``that_player`` is the seat a trigger's own condition named ("at the beginning
# of **each player's** upkeep, **that player** sacrifices …", Mana Vortex). It
# is admitted only under an event that freezes one — see ``_lower_sacrifice``.
_SACRIFICE_PAYERS: frozenset[str] = frozenset(
    {"you", "each_opponent", "target_opponent", "target_player", "that_player"}
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
    - a phrase naming neither a card type nor a subtype, which would let the
      prompt eat anything on the board. A *subtype* alone is a real set and
      names it exactly — "two Swamps" (Mold Demon) is the whole cost, and it
      says nothing about card types because on that card it does not need to.
    """
    if filt.is_source or filt.is_enchanted or not (filt.card_types or filt.subtypes):
        return None
    return object_only_filter(filt.to_payload(), carried_separately=_SACRIFICE_CARRIED)


def _lower_destroy_each_unless_paid(
    node: ast.DestroyEachUnlessPaid,
) -> tuple[OracleInstruction, ...]:
    """"For each land, destroy that land unless any player pays 1 life."
    (Cleansing.)

    One instruction rather than a sweep plus a rider: the offer is made about
    one permanent at a time, so the loop and the buyout are the same effect and
    nothing but the handler can hold the record of which members were bought.

    The noun phrase is gated by ``object_only_filter`` for the reason the
    forced-sacrifice prompt is: the loop walks every battlefield with no
    observer seat and no source to compare against, so a narrowing the matcher
    could only answer relative to one of those would be dropped — and a dropped
    narrowing on a sweep takes the board rather than doing less.
    """
    described = object_only_filter(_filter_payload(node.filter))
    if described is None:
        raise LoweringError(
            "the per-permanent buyout cannot test this restriction", node=node
        )
    if node.payer != "any_player":
        raise LoweringError("only 'any player' may buy a permanent off", node=node)
    return (
        OracleInstruction(
            "destroy_each_unless_life_paid", "",
            {"filter": dict(described), "life": int(node.life)},
        ),
    )


def _lower_sacrifice(
    node: ast.Sacrifice, event: str | None = None
) -> tuple[OracleInstruction, ...]:
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
    # "…unless they sacrifice **that artifact**" (Curse Artifact) — the
    # permanent this Aura is attached to, which the trigger's own condition
    # named. Above the chosen-sacrifice prompt below and not routed through it:
    # "that artifact" is one known permanent, and "an artifact" is a pick from
    # every artifact its controller has, so a player with two of them would be
    # offered the wrong one to give up.
    if names_attached_permanent(node.subject, event):
        return (OracleInstruction("sacrifice_attached_permanent", "", {}),)
    if (
        node.player.kind in _SACRIFICE_PAYERS
        and isinstance(node.subject, ast.TargetSpec)
        and not node.subject.targeted
        and not _is_source(node.subject)
    ):
        described = _forced_sacrifice_filter(node.subject.filter)
        if described is None:
            raise LoweringError(
                "the sacrifice prompt cannot test this restriction", node=node
            )
        payload: dict[str, object] = {"filter": described}
        if node.subject.count != 1:
            # "Sacrifice **two** Swamps" (Mold Demon). How many is payload on
            # the one prompt, never a second kind: the forced-sacrifice queue
            # has taken a count since it was written, and it was the lowering
            # that only ever passed one.
            payload["count"] = node.subject.count
        if node.subject.filter.other_than_source:
            payload["exclude_self"] = True
        if node.player.kind == "that_player":
            # "At the beginning of each player's upkeep, **that player**
            # sacrifices a land of their choice." (Mana Vortex.) The seat the
            # firing event named, which varies per firing and so is frozen by
            # the fire site rather than re-derived at resolution — the same
            # table and the same reason the damage lowering reads it (idiom 6).
            # An event that freezes no such seat refuses the line: reading an
            # absent key would sacrifice the *source controller's* land on
            # every upkeep, which is a different card that happens to work.
            if event not in _EVENT_SUBJECT_PLAYERS:
                raise LoweringError(
                    f"no event named {event!r} freezes the seat 'that player' names",
                    node=node,
                )
            payload["who"] = EVENT_SUBJECT_PLAYER
        elif node.player.kind != "you":
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
            "arm_self_action_at_next_end_step", "",
            # The referent rides beside the action for the same reason the
            # action does: one sentence, one kind, and what differs is data.
            # Absent for "this artifact", so every payload written before Glyph
            # of Destruction is byte-identical.
            {"self_action": node.action}
            | ({"subject": node.subject} if node.subject != "source" else {}),
        ),
    )


def _lower_exchange_greatest_mana_value(
    node: ast.ExchangeGreatestManaValue,
) -> tuple[OracleInstruction, ...]:
    """Juxtapose's paragraph → a ``sequence`` of ordinary instructions.

    Three steps per printed type, and none of them is new machinery: each side
    of the exchange is a ``choose_permanent`` narrowed to "the <type> that seat
    controls with the greatest mana value", and the exchange itself reads the
    two ids those steps recorded. Writing it as one fused kind would have hidden
    the tie-break sentence inside a handler; written this way the sentence *is*
    the prompt, and ``only_on_tie`` is the printed condition under which it is
    asked — with one candidate there is nothing to choose and no prompt is made.

    The two seats are the spell's controller and its chosen player, which is why
    the second choice's ``chooser`` is ``target``: CR 701.12 leaves the pick to
    each permanent's own controller, and the card says so.
    """
    steps: list[OracleInstruction] = []
    for card_type in node.card_types:
        keys = []
        for side, chooser in (("you", "you"), ("target", "target")):
            key = f"exchanged_{card_type}_{side}"
            keys.append(key)
            steps.append(
                OracleInstruction(
                    "choose_permanent", "",
                    {
                        "result_key": key,
                        "filter": {"type_filter": card_type},
                        "controlled_by": chooser,
                        "greatest_mana_value": True,
                        "only_on_tie": True,
                        "chooser": chooser,
                        "prompt": (
                            f"Choose which {card_type} with the greatest mana "
                            "value to exchange."
                        ),
                    },
                )
            )
        steps.append(
            OracleInstruction(
                "exchange_control_of_bound", "",
                {"first_from": keys[0], "second_from": keys[1]},
            )
        )
    return (OracleInstruction("sequence", "", {"steps": tuple(steps)}),)


def _lower_for_each_destroyed(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"**For each creature that died this way,** <effect>." (Glyph of
    Reincarnation.)

    A loop over the objects an earlier step of *this same effect* destroyed —
    the set behind ``destroyed_this_way``, which the sweep handlers record
    because by the time this runs the board no longer holds it. Here rather
    than beside ``_lower_for_each`` in ``lowering/counters``: that one repeats a
    counter placement a fixed number of times and never looks at what died,
    while this is about the destroy family's own record.

    Refused without a producer, as every back-reference in this grammar is:
    "this way" with no earlier step names nothing at all, and an empty loop is a
    sentence that reports supported and does not run.

    The inner statement arrives already lowered, the way ``lower_where_x``'s
    does and for its reason — nothing here cares how it was lowered, only that
    it is repeated once per object.
    """
    if "destroyed_this_way" not in produced:
        raise LoweringError(
            "'died this way' with no earlier step in this effect that "
            "destroyed anything", node=node,
        )
    filt = node.iterator.filter
    if filt.to_payload() != {"type_filter": "creature"} or filt.zone != "battlefield":
        raise LoweringError(
            "'died this way' iterates what the earlier step destroyed and "
            "cannot be narrowed further", node=node,
        )
    if not inner:
        raise LoweringError("a per-object loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {
                # Named rather than implied: the loop reads the objects an
                # earlier step recorded under this key, and the key is what
                # ties the two halves of the sentence together.
                "iterator": {"produced_by": "destroyed_this_way_objects"},
                "effect": inner,
            },
        ),
    )
