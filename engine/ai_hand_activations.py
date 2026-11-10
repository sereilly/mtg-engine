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

from .activation_prohibitions import activation_prohibition
from .ai_valuation import is_mana_ability, land_searches
from .game import Game
from .oracle import compile_card_oracle
from .activation_zones import HAND
from .targeting import usable_activated_abilities
from .ai_payment import _plan_land_taps, tap_planned_lands
from .ai_rehearsal import Rehearsal, deliberating, rehearse
from .ai_standing import spare_land_find_price
from .ai_actions import HandActivationAction
from .ai_scoring import SWING_CAP, _score_activation, _worth_proposing
from .ai_player_control import plays_for_another


def choose_hand_activation_action(
    game: Game, player_index: int, *, at_instant_speed: bool = False,
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

    **A cycle whose own trigger has nothing to act on is held** at sorcery
    speed (:func:`_cycle_trigger_finds_nothing`): "When you cycle this card,
    you may counter target spell" (Decree of Silence, Complicate) in a main
    phase with an empty stack is six mana for a card, and the counter it
    carries is spent on nothing — the seat cycled Decree of Silence so
    (SCG W1G2). Held, it is weighed again **at instant speed**
    (*at_instant_speed*, ``ai_priority.act_at_priority``), where only a
    proposal whose rehearsal leaves the seat ahead once the turn is over is
    made: the Decree in response to an opponent's spell, a Death Pulse's
    -1/-1 at the end of the opponent's turn. A plain cycle — a card out and
    a card in — is never one there, and keeps its main phase.
    """
    # CR 723.5: a seat another player decides for plays nothing
    # optional for itself (``ai_player_control``'s measured policy).
    if plays_for_another(game, player_index):
        return None
    with deliberating():
        return _choose_hand_activation_action(
            game, player_index, at_instant_speed=at_instant_speed,
        )


def holds_a_hand_ability(game: Game, player_index: int) -> bool:
    """Whether *player_index*'s hand holds a card with an ability it could
    activate from there (the reader `Game.activate_from_hand` gates on) whose
    mana its board can pay — the cheap question asked before the dear one at
    instant speed, by `ai_priority.act_at_priority`, as
    ``ai_policy.holds_an_ability_it_could_activate`` is for the battlefield."""
    from .mixins.stack.card_activation import hand_activation_cost

    player = game.players[player_index]
    for card in player.hand:
        from_hand = usable_activated_abilities(compile_card_oracle(card), zone=HAND)
        if not from_hand or from_hand[0].instruction is None:
            continue
        if not game.enforce_mana_costs:
            return True
        required = hand_activation_cost(game, player_index, card, from_hand[0])[0]
        if not any(required.values()) or _plan_land_taps(game, player, required) is not None:
            return True
    return False


def _cycle_trigger_finds_nothing(game: Game, player_index: int, card) -> bool:
    """Whether *card* prints a "When you cycle this card" trigger
    (``self_cycled``) that names a target and finds none now — the engine's
    own enumeration of what the trigger could choose (CR 603.3d: a trigger
    with no legal target is removed from the stack, so what it does is lost).

    Read off the compiled program and asked of the engine, so it names no
    card: Decree of Silence and Complicate find no spell on an empty stack,
    Decree of Savagery no creature on an empty board; Slice and Dice, which
    names no target, always has something to do."""
    from .targeting import derive_instruction_spec

    for trigger in compile_card_oracle(card).triggered_abilities:
        if trigger.condition.kind != "self_cycled" or trigger.instruction is None:
            continue
        spec = derive_instruction_spec([trigger.instruction])
        if not isinstance(spec, dict) or spec.get("kind") in (None, "none", "modal"):
            continue
        if not game._enumerate_targets(
            player_index, card, spec, for_cast=False,
            ability_instruction=trigger.instruction, triggered=True,
        ):
            return True
    return False


def _choose_hand_activation_action(
    game: Game, player_index: int, *, at_instant_speed: bool = False,
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
        # CR 602.5 before anything is priced: the table ``activate_from_hand``
        # refuses with (``engine/activation_prohibitions.py``) — a Stabilizer's
        # "Players can't cycle cards", a City of Solitude on another seat's
        # turn. Proposing what the engine refuses is the seat's one activation
        # of the priority pass spent on nothing, every pass.
        if activation_prohibition(game, player_index, card, ability) is not None:
            continue

        # A mana ability activated for its own sake empties at the end of the
        # step; the same floor `ai_abilities.choose_activation_action` keeps
        # one zone over.
        if is_mana_ability(ability.instruction):
            continue
        # A cycle whose trigger has nothing to act on now waits for a moment
        # it has (see the docstring) — at sorcery speed; at instant speed the
        # rehearsal below says what it does.
        if not at_instant_speed and _cycle_trigger_finds_nothing(game, player_index, card):
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
        # A landcycle for a land the seat does not need gives a card up for
        # a spare land, which no standing prices (kg4: Eternal Dragon
        # returned for five and plainscycled for two, turn after turn).
        price = spare_land_find_price(
            game, player_index, land_searches(ability.instruction),
        )
        if price and rehearsal is None:
            continue
        if price:
            rehearsal = replace(
                rehearsal, now=rehearsal.now - price, lasting=rehearsal.lasting - price,
            )
        if at_instant_speed and (
            rehearsal is None or not _worth_proposing(rehearsal)
            or rehearsal.lasting <= 0.0
        ):
            # At instant speed only what leaves the seat ahead once the turn
            # is over, as `ai_policy.choose_instant_speed_activation` asks of
            # a permanent's ability — and nothing nobody could weigh.
            continue
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


def activate_chosen_hand_ability(game: Game, seat: int, action: HandActivationAction):
    """Carry out *action* on *game*: the planned lands tapped and the ability
    activated from the hand — ``Game.activate_from_hand``, the **queue** form,
    which leaves it on the stack for the table to answer (CR 117.3c). The
    engine's result. The executor the rehearsal and the instant-speed answer
    (`ai_priority.act_at_priority`) share."""
    planned = tap_planned_lands(game, seat, action)
    return game.activate_from_hand(
        seat, planned.card_name,
        ability_index=planned.ability_index, hand_index=planned.hand_index,
    )


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
        return activate_chosen_hand_ability(table, seat, action)

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
