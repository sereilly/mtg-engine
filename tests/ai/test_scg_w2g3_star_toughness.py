"""A creature whose toughness is a ``*`` is not cast to die (SCG W2G3).

W1G4, seed 4242: the AI cast Ancient Ooze ("power and toughness are each
equal to the total mana value of other creatures you control") onto an empty
board twice, and it died at 0/0 (CR 704.5f). A permanent's cast score is what
it is (``ai_scoring._score_cast``), and it read a ``*`` as 0 without anything
asking what the board would make of it: no permanent cast was rehearsed. A
creature whose printed toughness a characteristic-defining ability fills in
(CR 604.3, ``ai_scoring.body_needs_the_board``) is now rehearsed before it is
proposed and held when it would not stay (``ai_scoring._arrives_to_stay``),
and its body is weighed at what the ability counts where the card is
(``Game.card_pt_outside_battlefield``), not at 0.

Validated backwards: on ``843cf32a`` the census below casts seventeen of the
forty-seven such creatures into a board that kills them (Ancient Ooze,
Cantivore, Maro, Revenant, Wood Elemental, …), every one scored 3.7.
"""

from __future__ import annotations

from engine.ai_actions import cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.card_loader import load_catalog
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick, resolve_stack

#: How many ``*``-toughness creatures the census must examine (47 across
#: both roles on the base: 46 shipped and Ancient Ooze), and how many of them
#: it must see cast and kept — the gate holds the dying ones, not all of them.
_EXAMINED_FLOOR = 40
_KEPT_FLOOR = 20

_BASICS = ("Plains", "Island", "Swamp", "Mountain", "Forest")


def _pool(set_pool) -> dict:
    return {**{card.name: card for card in load_catalog()}, **set_pool("SCG")}


def _table(pool, hand, board) -> Game:
    game = Game(players=[
        PlayerState(name="AI", hand=list(hand), library=[pool["Island"]] * 10),
        PlayerState(name="Opp", library=[pool["Island"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for name in board:
        game.players[0].battlefield.append(_nosick(Permanent(card=pool[name])))
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game.start_priority_window(0)
    return game


def _cast(game, action) -> None:
    action = tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(0, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    game.check_state_based_actions()


def test_no_star_toughness_creature_is_cast_to_die(set_pool):
    """Each alone in hand over five of every basic land and nothing else: a
    creature the AI casts is on the battlefield once the stack is empty."""
    pool = _pool(set_pool)
    stars = sorted(
        (
            card for card in pool.values()
            if card.primary_type == "creature" and "*" in str(card.printed_toughness or "")
        ),
        key=lambda card: card.name,
    )
    died, kept = [], []
    for card in stars:
        game = _table(pool, [card], [name for name in _BASICS for _ in range(5)])
        action = choose_cast_action(game, 0)
        if action is None:
            continue
        _cast(game, action)
        if any(permanent.card.name == card.name for permanent in game.controlled_by(0)):
            kept.append(card.name)
        else:
            died.append(card.name)
    assert len(stars) >= _EXAMINED_FLOOR, [card.name for card in stars]
    assert not died, died
    assert len(kept) >= _KEPT_FLOOR, kept


def test_ancient_ooze_is_held_on_an_empty_board(set_pool):
    pool = _pool(set_pool)
    game = _table(pool, [pool["Ancient Ooze"]], ["Forest"] * 7)
    assert choose_cast_action(game, 0) is None


def test_ancient_ooze_is_cast_and_weighed_at_its_body_beside_a_creature(set_pool):
    """Beside a Hill Giant (mana value 4) the Ooze is a 4/4: proposed, scored
    above the 0/0 a ``*`` used to read as, and on the battlefield as a 4/4."""
    pool = _pool(set_pool)
    game = _table(pool, [pool["Ancient Ooze"]], ["Forest"] * 7 + ["Hill Giant"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Ancient Ooze"
    empty = _table(pool, [pool["Grizzly Bears"]], ["Forest"] * 2)
    bears = choose_cast_action(empty, 0)
    assert bears is not None and action.score > bears.score
    _cast(game, action)
    ooze = next(p for p in game.controlled_by(0) if p.card.name == "Ancient Ooze")
    assert (ooze.effective_power, ooze.effective_toughness) == (4, 4)
