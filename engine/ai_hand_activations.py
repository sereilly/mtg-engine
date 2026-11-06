"""Which ability an AI seat activates from a card **in its hand** (CR
113.6j): cycling, and whatever else prints a cost payable only from a hand.

**Which abilities those are is the engine's reading**, never a list here:
``usable_activated_abilities(program, zone=HAND)``, the reader
``Game.activate_from_hand`` gates on and the one that keeps such an ability
off a permanent's list — so this policy names no card and no keyword.
**What the activation sets off is weighed**: the flat score reads what the
ability does (a cycle's draw), and carrying it out on a copy of the game
(:func:`_rehearse_hand_activation`, ``ai_rehearsal.rehearse``) reads what
it triggers — a harmful one is not proposed, and the swing is added to the
score.

A module of its own rather than a second chooser in ``ai_abilities``,
beside its graveyard twin (``ai_graveyard_activations``) and for that
module's reason: the action shape is its own
(``ai_actions.HandActivationAction``) and so is the engine door
(``Game.activate_from_hand``).
"""

from __future__ import annotations

from .ai_valuation import is_mana_ability
from .game import Game
from .oracle import compile_card_oracle
from .activation_zones import HAND
from .targeting import usable_activated_abilities
from .ai_payment import _plan_land_taps, tap_planned_lands
from .ai_rehearsal import Rehearsal, deliberating, rehearse
from .ai_actions import HandActivationAction
from .ai_scoring import SWING_CAP, _score_activation, _worth_proposing


def choose_hand_activation_action(
    game: Game, player_index: int
) -> HandActivationAction | None:
    """The best ability this seat can activate from its **hand**, or None.

    Cycling, and whatever else prints a cost payable only from a hand
    (CR 113.6j). Which abilities those are is not decided here — it is
    ``usable_activated_abilities(program, zone=HAND)``, the same reader
    ``Game.activate_from_hand`` gates on and the same one that keeps the ability
    off a permanent's list — so this policy names no card and no keyword.

    Called **after** the seat's cast for the turn, so the untapped lands the
    payment is planned against are the mana the cast did not want: a seat
    cycles with what is left over rather than instead of playing its spell.

    One action per call, like ``ai_abilities.choose_activation_action``, and the tie-break
    is hand order — the seat cycles once a priority pass rather than emptying
    its hand in a loop, and a seeded run reproduces exactly.

    **What the activation sets off is weighed** (:func:`_rehearse_hand_
    activation`): the score read a cycle's draw and nothing it triggers, so
    Slice and Dice's "When you cycle this card, you may have it deal 1 damage
    to each creature" was cycled whatever it did to the seat's own board (ONS
    W1G3). A harmful candidate is not proposed and the swing is added to the
    score; a plain cycle measures nothing and keeps its score.
    """
    with deliberating():
        return _choose_hand_activation_action(game, player_index)


def _choose_hand_activation_action(
    game: Game, player_index: int,
) -> HandActivationAction | None:
    """:func:`choose_hand_activation_action` inside its deliberation."""
    from dataclasses import replace

    player = game.players[player_index]
    best: HandActivationAction | None = None
    for hand_index, card in enumerate(player.hand):
        program = compile_card_oracle(card)
        from_hand = usable_activated_abilities(program, zone=HAND)
        if not from_hand:
            continue
        ability = from_hand[0]
        if ability.instruction is None:
            continue

        # A mana ability activated for its own sake empties at the end of the
        # step; the same floor `ai_abilities.choose_activation_action` keeps
        # one zone over.
        if is_mana_ability(ability.instruction):
            continue

        # Any cost beyond mana and the discard the zone read is derived from is
        # a trade this policy cannot price — the same honest floor the
        # battlefield loop takes, and derived from the compiled cost so it
        # names no card.
        cost = ability.cost
        if (
            cost.sacrifice_filter is not None
            or cost.discard_cards
            or cost.pay_life
            or cost.exile_top_of_library
        ):
            continue

        land_taps: tuple[int, ...] = ()
        # The cost as CR 601.2f computes it, through the same reader
        # ``Game.activate_from_hand`` charges: a Fluctuator on the board makes
        # a Cycling {2} free, and a policy pricing the printed cost would pass
        # over an ability the engine would let it take for nothing.
        from .mixins.stack.card_activation import hand_activation_cost

        tap_colors: tuple[str, ...] = ()
        required = hand_activation_cost(game, player_index, card, ability)[0]
        if game.enforce_mana_costs and any(required.values()):
            plan = _plan_land_taps(game, player, required)
            if plan is None:
                continue
            land_taps, tap_colors = plan

        # The seat is the target: nothing activatable from a hand in the pool
        # aims anywhere else, and an ability that did would be refused at
        # announcement rather than aimed by this policy.
        score = _score_activation(game, player_index, ability.instruction, player_index)
        if score <= 0.0:
            continue
        candidate = HandActivationAction(
            card_name=card.name,
            hand_index=hand_index,
            ability_index=0,
            land_tap_indices=land_taps,
            score=score,
            land_tap_colors=tap_colors,
        )
        rehearsal = _rehearse_hand_activation(game, player_index, candidate)
        if rehearsal is not None:
            if not _worth_proposing(rehearsal):
                continue
            candidate = replace(
                candidate,
                score=score + max(-SWING_CAP, min(SWING_CAP, rehearsal.swing)),
            )
        if best is None or candidate.score > best.score:
            best = candidate
    return best


def _rehearse_hand_activation(
    game: Game, seat: int, action: HandActivationAction,
) -> Rehearsal | None:
    """What activating *action* from the hand would do, carried out on a
    scratch copy (``ai_rehearsal.rehearse``) as the simulator's executor
    carries it out — the planned lands tapped, ``activate_from_hand``, the
    stack resolved on defaults — against the same copy with those lands
    tapped and nothing activated.

    The card leaving the hand is the activation's own cost, not a cast's trip,
    so it is **read as a change** (``leaves_hand=False``): a plain cycle is a
    card out and a card in, a swing of nothing, and what is left over is what
    the cycle set off."""

    def perform(table):
        planned = tap_planned_lands(table, seat, action)
        return table.activate_from_hand(
            seat, planned.card_name,
            ability_index=planned.ability_index, hand_index=planned.hand_index,
        )

    def paid_for(table, _carried) -> None:
        pool = table.players[seat].mana_pool
        floating = dict(pool)
        tap_planned_lands(table, seat, action)
        pool.clear()
        pool.update(floating)

    taps = bool(action.land_tap_indices)
    return rehearse(
        game, seat, perform, spell_name=None, leaves_hand=False,
        label=f"{action.card_name}'s ability from hand",
        key=(
            "hand_activation", seat, action.card_name, action.hand_index,
            action.ability_index, action.land_tap_indices, action.land_tap_colors,
        ),
        without=paid_for if taps else None,
        without_key=(
            ("paid", action.land_tap_indices, action.land_tap_colors)
            if taps else None
        ),
    )
