"""The AI's own face-down cast spares the colour its turn-up needs.

Forest, Mountain, Mountain, Mountain and Branchsnap Lorian in hand ({1}{G}{G},
morph {G}): one Forest cannot pay the printed cost, so the seat casts it face
down for {3} (CR 702.37a) — and then turns it face up for {G} (CR 702.37e,
a special action, ``ai_special_actions``). The face-down cast was planned as
the face-up card, and the payer's wants leave the card being paid for out of
the hand, so nothing wanted the Forest: the {3} took it first (board order) and
the Lorian stayed a 2/2. The plan is now drawn for the 2/2 the cast path casts
(CR 702.37c, ``ai_cast_gates._alternative_cost_tap_plan``), whose card brings
its turn-up (``mana_wants.wants_brought_by``), so the {3} is three Mountains
and the Forest turns it up in the same main phase.

Driven through the simulator's own executors: ``ai_simulator._play_one_cast``
(the policy's choice, the shared ``tap_planned_lands``, the engine's cast) and
``ai_special_actions.special_action_before_combat``.
"""
from __future__ import annotations

from unittest import mock

from engine import Game, PlayerState
from engine import mana_wants as wants_module
from engine.ai_policy import choose_cast_action
from engine.ai_simulator import SimulationReport, _play_one_cast
from engine.ai_special_actions import special_action_before_combat
from engine.card_loader import load_catalog
from engine.face_down import is_face_down
from engine.models import Permanent

_CARDS = {card.name: card for card in load_catalog()}
_BOARD = ["Forest", "Mountain", "Mountain", "Mountain"]


def _table() -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.players[0].battlefield = [Permanent(card=_CARDS[name]) for name in _BOARD]
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.players[0].hand = [_CARDS["Branchsnap Lorian"]]
    game.players[0].library = [_CARDS["Mountain"]] * 10
    game.players[1].library = [_CARDS["Mountain"]] * 10
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase = game.current_step = "precombat_main"
    game._recompute_continuous_effects()
    return game


def _planned(game: Game) -> list[str]:
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Branchsnap Lorian"
    assert action.alternative_cost, "the printed {1}{G}{G} is unpayable: a morph cast"
    return sorted(game.permanent_at(0, slot).card.name for slot in action.land_tap_indices)


def test_the_face_down_cast_is_paid_with_mountains_and_turned_up_with_the_forest():
    game = _table()
    assert _planned(game) == ["Mountain"] * 3

    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    assert _play_one_cast(game, 0, report, 1, 1)
    (lorian,) = [p for p in game.controlled_by(0) if p.is_creature]
    assert is_face_down(lorian)
    forest = next(p for p in game.controlled_by(0) if p.card.name == "Forest")
    assert not forest.tapped

    taken = special_action_before_combat(game, 0)
    assert taken is not None and taken[1] is None, taken
    assert not is_face_down(lorian) and lorian.card.name == "Branchsnap Lorian"
    assert forest.tapped
    assert (lorian.effective_power, lorian.effective_toughness) == (4, 1)


def test_the_card_being_cast_is_the_want_that_was_left_out():
    """Backwards — what round kg2's census could not see, because its want
    was always a second card: with the turn-up a card being cast brings left
    unread, the plan is the board order and takes the Forest."""
    with mock.patch.object(wants_module, "wants_brought_by", lambda paying_for: ()):
        planned = _planned(_table())
    assert planned == ["Forest", "Mountain", "Mountain"]
