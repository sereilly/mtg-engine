"""Control-flow instructions: sequencing, conditions, optional costs, iteration.

These are what let an effect be *composed* rather than fused into a bespoke
instruction kind. The legacy compiler delivered exactly one instruction per
spell, so every "do X and also Y" card needed its own kind —
``deal_damage_and_gain_life``, ``deal_damage_and_self_damage``,
``grant_islandwalk_and_linked_destroy`` and 25 more, which is combinatorial in
the number of base effects and was the single largest driver of kind growth.

With ``sequence`` in the IR, "X and Y" is two ordinary instructions and no new
kind at all. ``if_then`` / ``may`` / ``for_each`` wrap nested sequences the same
way, so conditions and optional costs stop being baked into effect kinds too.

Nested steps travel in the payload as tuples of ``OracleInstruction`` and are
dispatched back through ``EFFECT_HANDLERS`` — the same O(1) dict every other
effect uses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..resumption import run_resumable
from ._common import permanent_matches_filter
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


def _steps(instruction: OracleInstruction, key: str) -> tuple:
    value = instruction.payload.get(key) or ()
    return tuple(value)


def _run(game: Game, steps: tuple, context: OracleExecutionContext) -> tuple[bool, str]:
    """Execute nested instructions in order against the shared context.

    The context is deliberately *not* copied: results recorded by one step
    ("damage_dealt") must be visible to the next.

    Run through ``run_resumable`` so a step that stops to ask the player
    something (CR 616.1e) takes the steps behind it with it: they are recorded
    and run when the answer arrives, rather than executing against a step that
    has not happened yet. That is also why the loop is the last thing here —
    ``resolved`` is folded in as each step goes, not tallied afterwards.
    """
    outcome = {"resolved": False}

    def run_step(step) -> None:
        supported, _ = game._execute_oracle_instruction(step, context)
        outcome["resolved"] = outcome["resolved"] or supported

    run_resumable(game, steps, run_step)
    return True, "resolved" if outcome["resolved"] else "no effect"


@effect_handler("sequence")
def sequence(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Perform each step in order (CR 608.2: a spell's instructions resolve in
    the order written)."""
    return _run(game, _steps(instruction, "steps"), context)


def evaluate_condition(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    """Evaluate a lowered condition payload.

    Kept small on purpose: an unrecognized condition returns False rather than
    guessing, and the grammar refuses to lower conditions it cannot describe, so
    an unknown condition never reaches here from a grammar-compiled card.
    """
    kind = payload.get("kind")

    if kind == "controls":
        who = payload.get("who", "you")
        players = [context.caster] if who == "you" else list(game.players)
        if who in ("each_opponent", "target_opponent", "opponent"):
            players = [p for p in game.players if p is not context.caster]
        filters = payload.get("filter") or {}
        count = sum(
            1
            for player in players
            for permanent in game.controlled_by(player)
            if permanent_matches_filter(permanent, filters)
        )
        wanted = payload.get("count")
        op = payload.get("op", "eq")
        # "if an opponent controls more creatures than you" (Garruk,
        # Unleashed's −2): the bound is the asker's own matching count, and
        # "an opponent" means any single opponent beating it.
        if op == "more_than_you":
            filters = payload.get("filter") or {}
            own = sum(
                1
                for permanent in game.controlled_by(context.caster)
                if permanent_matches_filter(permanent, filters)
            )
            return any(
                sum(
                    1
                    for permanent in game.controlled_by(player)
                    if permanent_matches_filter(permanent, filters)
                ) > own
                for player in game.players
                if player is not context.caster and not player.lost
            )
        if wanted is None:
            return count > 0
        if op == "eq":
            return count == wanted
        if op == "le":
            return count <= wanted
        if op == "ge":
            return count >= wanted
        return False

    if kind == "is_state":
        source = context.source_permanent
        if source is None:
            return False
        state = payload.get("state")
        value = bool(getattr(source, state, False)) if state else False
        return (not value) if payload.get("negated") else value

    if kind == "died_this_turn":
        return int(getattr(game, "creatures_died_this_turn", 0) or 0) > 0

    if kind == "returned_to_hand_this_turn":
        # "a permanent was put into your hand from the battlefield this turn"
        # (Barrin). "Your" is the ability's controller; the bounce paths feed
        # the per-seat counter.
        seat = game.players.index(context.caster)
        return int(game.permanents_to_hand_this_turn.get(seat, 0)) > 0

    if kind == "life_gained_this_turn":
        # Per player, because the counter is: "you" is the ability's
        # controller, which is context.caster for a triggered ability too.
        who = payload.get("who", "you")
        players = (
            [context.caster] if who == "you"
            else [p for p in game.players if p is not context.caster]
        )
        wanted = int(payload.get("amount", 0))
        return any(
            int(getattr(p, "life_gained_this_turn", 0) or 0) >= wanted
            for p in players
        )

    return False


@effect_handler("if_then")
def if_then(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"If <condition>, <then>" — including CR 603.4 intervening-if conditions,
    which the legacy compiler dropped, so conditional triggers always fired."""
    condition = instruction.payload.get("condition") or {}
    if evaluate_condition(game, context, condition):
        return _run(game, _steps(instruction, "then"), context)
    return _run(game, _steps(instruction, "else"), context)


@effect_handler("may")
def may(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"You may pay {N}. If you do, …" / "You may <action>."

    Offers an optional cost or action to its controller and, when taken, runs
    the consequence as an ordinary instruction sequence. That is what lets an
    optional cost sit in front of *any* effect: the previous mechanism could
    only express "gain N life", "draw N cards" or "take N damage", so every card
    outside that vocabulary needed its own name-keyed hook.

    The prompt is an ``optional_pay`` entry on the generic pending-choice queue,
    and the *consequence* has no fixed shape.
    """
    actor = instruction.payload.get("actor", "you")
    player = context.caster if actor == "you" else context.target
    player_index = game.players.index(player)
    cost = instruction.payload.get("cost")
    on_accept = _steps(instruction, "action") + _steps(instruction, "then")
    on_decline = _steps(instruction, "otherwise")

    # An offer the player cannot afford is never made; its decline branch (a
    # "…unless you pay" penalty) still applies.
    if cost is not None and not game._player_can_pay_generic(player, int(cost)):
        return _run(game, on_decline, context) if on_decline else (True, "resolved")

    entry = {
        "card_name": context.card.name,
        "cost": int(cost or 0),
        "life": 0,
        "_source_permanent": context.source_permanent,
        # Instructions to run on accept/decline, with the resolution context
        # they belong to. _pay_optional executes these when present.
        "_on_accept": on_accept,
        "_on_decline": on_decline,
        "_context": context,
    }
    if cost:
        entry["prompt"] = f"Pay {{{int(cost)}}}?"
    # Mirror a plain "gain N life" consequence into the legacy `life` field so
    # the prompt UI keeps describing what accepting does. Display only —
    # _pay_optional runs the instruction branch and returns before reading it.
    # This goes away when the pending-choice queue carries its own description.
    if len(on_accept) == 1 and on_accept[0].kind == "target_gains_life":
        amount = on_accept[0].payload.get("amount")
        if isinstance(amount, int):
            entry["life"] = amount
    game.arm_pending_choice("optional_pay", player_index, **entry)
    return True, "resolved"


@effect_handler("for_each")
def for_each(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"For each <objects>, <effect>." The matching set is snapshotted before
    the first iteration so an effect that removes objects cannot shorten its own
    loop."""
    filters = instruction.payload.get("iterator") or {}
    steps = _steps(instruction, "effect")
    matched = [
        permanent
        for player in game.players
        for permanent in list(player.battlefield)
        if permanent_matches_filter(game, permanent, filters)
    ]
    previous = context.iteration_target
    for permanent in matched:
        context.iteration_target = permanent
        _run(game, steps, context)
    context.iteration_target = previous
    return True, "resolved"
