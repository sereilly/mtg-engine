"""Lowering board changes: bouncing, regeneration, sacrifice, phasing, control.

Regeneration, sacrifice (as an effect and as a toll), phasing out, exchanging
control, and putting a permanent back on the bottom of a library.

Destruction left for ``destruction`` at the thousand-line guard; tapping left
for ``tapping`` one round earlier. What stays is what the CR calls something
else.

Control changes lower to a *contribution* rather than a move — see
`engine/control.py`. What lowering owes is the timestamped source, not a new
owner.
"""

import dataclasses

from ...oracle_types import X_FROM_COUNT_PER_RECIPIENT, OracleInstruction
from ...subject_filters import (
    TESTABLE_SUBJECT_FILTER_KEYS, object_only_filter, untestable_filter_keys,
)
from .. import ast
from ..errors import LoweringError
from ._amounts import halved_count_spec
from ._sacrifices import _SACRIFICE_CARRIED, _forced_sacrifice_filter
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
    _RECORDED_PERMANENTS,
    _EVENT_SUBJECT_CONTROLLERS,
    _EVENT_SUBJECT_PLAYERS,
    EVENT_SUBJECT_CONTROLLER,
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
#
# ``each_player`` is Pox's, and it is `each_opponent` plus the caster: the prompt
# is owed by every living seat rather than by every living opponent, which is
# one more entry in the same list the handler already builds.


# ``controller`` is the possessive with nothing in front of it — "**its**
# controller sacrifices a creature of their choice" (Funeral March). It names
# the controller of the object the *trigger's own event* was about, which is
# the same seat ``that_player`` resolves to under an object event, reached by a
# pronoun instead of a demonstrative. Admitted only under an event that freezes
# one, exactly as ``that_player`` is: without that gate "its" would fall
# through to the handler's unknown-payer branch, or worse, to the caster.
_SACRIFICE_PAYERS: frozenset[str] = frozenset(
    {
        "you", "each_player", "each_opponent", "target_opponent",
        "target_player", "that_player", "controller",
    }
)

# Two keys the forced-sacrifice prompt performs rather than tests, so they are
# lifted out of the filter instead of refusing the line:
#
# - ``exclude_self`` ("sacrifice **another** creature") rides beside the filter
#   as the prompt's own ``exclude`` argument, which compares by identity — a
#   look-alike on the same battlefield is a different permanent.
# - ``their_choice`` ("a creature **of their choice**", Run Afoul) says the
#   sacrificing player picks, which is what CR 701.21a already says and what the
#   prompt already does. It is read and dropped here, at a lowering whose rule
#   puts the choice there; anywhere else the word refuses.
#
#   "Anywhere else the word refuses" was a claim and not a mechanism until The
#   Abyss: ``to_payload`` emits ``their_choice`` so a gate can see it, but only
#   the gates asking "are all these keys testable?" look, and the single-target
#   destroy asked none — so the word rode into the payload, nothing read it, and
#   the ability's controller picked. ``_filter_payload`` now refuses it unless
#   the call site names it in ``carried_separately``, which is what makes the
#   sentence above true of every lowering rather than of this one.


def _per_payer_count(node: ast.Sacrifice) -> dict:
    """How many *this payer* sacrifices, as a spec the evaluator answers per
    seat. ("…sacrifices a third of the creatures they control", Pox.)

    The two narrowings the printed phrase carries are stripped before the count
    is built, and neither is a narrowing lost:

    * **"they control"** is CR 701.21a restated — a player can only sacrifice
      what they control — and the evaluator is already owner-scoped, so handing
      it the key would make ``count_spec`` refuse a phrase that says nothing.
    * **"of their choice"** is whose decision it is, not what may be chosen;
      the prompt is the decision.
    """
    counted = node.count
    if isinstance(counted, ast.Half) and isinstance(counted.of, ast.CountOf):
        counted = dataclasses.replace(
            counted,
            of=ast.CountOf(
                dataclasses.replace(
                    counted.of.filter, controller=None, their_choice=False
                )
            ),
        )
    spec = halved_count_spec(counted, node)
    if spec is None:
        raise LoweringError(
            "the sacrifice prompt sizes itself from a counted fraction", node=node
        )
    return spec


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
    # "When this creature leaves the battlefield this turn, **sacrifice that
    # creature**." (Phantasmal Mount.) The object the creating ability bound
    # (CR 603.7c), carried by id in the trigger's context — the mirror of
    # ``destroy_bound_permanent`` one family over, and its own kind for the same
    # reason: routed through the chosen-sacrifice prompt below the ability would
    # ask its controller to pick, and Phantasmal Mount's rider is not a choice.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
        and not node.subject.targeted
        and event in _BOUND_OBJECT_DELAYED_EVENTS
    ):
        return (
            OracleInstruction(
                "sacrifice_bound_permanent", "", _filter_payload(node.subject.filter)
            ),
        )
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
        # "…sacrifices **a third of** the creatures they control of their
        # choice." (Pox.) One number per seat, so it cannot be the printed
        # count: it is a fraction of *that* player's board, and the handler
        # asks the evaluator once per payer through the same channel the
        # per-recipient damage and the each-player discard already use.
        if node.count is not None:
            payload[X_FROM_COUNT_PER_RECIPIENT] = _per_payer_count(node)
        elif node.subject.count != 1:
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
            # "Whenever a creature dies, **that creature's controller**
            # sacrifices a land of their choice." (Earthlink.) The possessive
            # reaches the AST as the same `that_player`, so the two tables are
            # read in turn exactly as the damage lowering reads them: one
            # freezes the seat the event was *about*, the other the seat that
            # *controlled* what it was about, and they name disjoint events —
            # so the order is documentation rather than precedence.
            if event in _EVENT_SUBJECT_PLAYERS:
                payload["who"] = EVENT_SUBJECT_PLAYER
            elif event in _EVENT_SUBJECT_CONTROLLERS:
                payload["who"] = EVENT_SUBJECT_CONTROLLER
            else:
                raise LoweringError(
                    f"no event named {event!r} freezes the seat 'that player' names",
                    node=node,
                )
        elif node.player.kind == "controller":
            # "When enchanted creature leaves the battlefield, **its
            # controller** sacrifices a creature of their choice." (Funeral
            # March.) The possessive names the departing host's controller, not
            # the Aura's — they are different seats whenever the Aura is on an
            # opponent's creature, which is every printing of this card that
            # matters. By resolution the host is in a graveyard, an exile or a
            # hand, so the seat is the one the fire site froze (CR 603.10,
            # idiom 6) rather than one re-derived here.
            if event not in _EVENT_SUBJECT_CONTROLLERS:
                raise LoweringError(
                    f"no event named {event!r} freezes the seat 'its controller' names",
                    node=node,
                )
            payload["who"] = EVENT_SUBJECT_CONTROLLER
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
