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
    is_mana_value_x,
)
from ._events import (
    binds_block_pair,
    _UNTAPPED_PERMANENTS,
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
            if object_only_filter(described) is None:
                raise LoweringError("no sweep handler for this narrowing", node=node)
            narrowed_payload = dict(described)
            if node.no_regen:
                narrowed_payload["bypass_regeneration"] = True
            return (
                OracleInstruction("destroy_all_matching", "", narrowed_payload),
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


def _lower_exchange_control(node: ast.ExchangeControl) -> tuple[OracleInstruction, ...]:
    """"Exchange control of target artifact, creature, or land you control and
    target permanent an opponent controls…" (Gauntlets of Chaos, CR 701.12b.)

    Two chosen slots, described the way the two-target pump describes its pair:
    ``filters`` carries one filter per slot so the picker can enumerate both
    halves and the handler can re-check each at resolution (CR 608.2b), while
    ``filter`` stays the shape every one-slot reader already expects.

    ``shares_type`` and the printed type list travel as payload rather than as
    part of the kind, because a card exchanging (say) two enchantments would be
    this same effect with a different noun phrase.
    """
    if not isinstance(node.first, ast.TargetSpec) or not _is_target(node.first):
        raise LoweringError(
            "an exchange of control needs a chosen permanent on each side", node=node
        )
    if not isinstance(node.second, ast.TargetSpec) or not _is_target(node.second):
        raise LoweringError(
            "an exchange of control needs a chosen permanent on each side", node=node
        )
    first = _filter_payload(node.first.filter)
    second = _filter_payload(node.second.filter)
    payload: dict[str, object] = {
        "targets": {
            "quantifier": "target",
            "kind": "object",
            "filter": first,
            "filters": [first, second],
            "count": 2,
            # Two permanents on two battlefields are distinct by construction,
            # but saying so is what stops one player's own permanent filling
            # both slots if a later card drops the controller words.
            "distinct": True,
        },
        # The relation between the slots (see the node's docstring), and the
        # types it is measured over — "one of **those** types" is the first
        # slot's printed list, so it is read off that filter rather than
        # spelled out again here.
        "shares_a_type": bool(node.shares_a_type),
        "destroy_attached_auras": bool(node.destroy_attached_auras),
    }
    return (OracleInstruction("exchange_control_of_targets", "", payload),)




# The scratchpad key the tap records and this sentence reads. One name, in one
# place, because ``engine/grammar/lower.py``'s ``_PRODUCES`` writes it and the
# refusal below is what proves a producer ran — two spellings would make the
# refusal vacuous while the handler read an empty record and marked nothing.






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
    - a phrase naming neither a card type nor a subtype, which would let the
      prompt eat anything on the board. A *subtype* alone is a real set and
      names it exactly — "two Swamps" (Mold Demon) is the whole cost, and it
      says nothing about card types because on that card it does not need to.
    """
    if filt.is_source or filt.is_enchanted or not (filt.card_types or filt.subtypes):
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
            "arm_self_action_at_next_end_step", "", {"self_action": node.action}
        ),
    )
