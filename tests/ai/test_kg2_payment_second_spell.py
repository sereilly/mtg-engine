"""The AI casts its second spell on the turn its first used to strand it.

Plains, Mountain, Plains, Mountain, Plains, Plains — the board the entry's
Astral Slide was cast from in Onslaught's Phase 5 — and a hand of Regal Unicorn
({2}{W}) and Hurloon Minotaur ({1}{R}{R}): six mana, exactly both. The AI casts
the Unicorn first, and its payment plan (`ai_payment._PaymentPlanner`) paid
the generic in board order — a Plains for the {W}, then the Mountain and the
Plains behind it — leaving one Mountain for a spell that needs two. The plan
now weighs what else the seat wants (`mana_wants.mana_wants`, through
`mana_payment._sparing_choice`), pays the Unicorn with three Plains, and the
Minotaur follows in the same main phase. Driven through the simulator's own
executor (`ai_simulator._play_one_cast`: the policy's choice, the shared
`tap_planned_lands`, the engine's cast).
"""
from __future__ import annotations

from unittest import mock

from engine import Game, PlayerState, mana_payment
from engine.ai_simulator import SimulationReport, _play_one_cast
from engine.card_loader import load_catalog
from engine.models import Permanent

_CARDS = {card.name: card for card in load_catalog()}
_BOARD = ["Plains", "Mountain", "Plains", "Mountain", "Plains", "Plains"]


def _table() -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.players[0].battlefield = [Permanent(card=_CARDS[name]) for name in _BOARD]
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.players[0].hand = [_CARDS["Regal Unicorn"], _CARDS["Hurloon Minotaur"]]
    game.players[0].library = [_CARDS["Plains"]] * 10
    game.players[1].library = [_CARDS["Plains"]] * 10
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase = game.current_step = "precombat_main"
    game._recompute_continuous_effects()
    return game


def _main_phase(game: Game) -> SimulationReport:
    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    for _ in range(4):
        if not _play_one_cast(game, 0, report, 1, 1):
            break
    return report


def _creatures(game: Game) -> list[str]:
    return [p.card.name for p in game.controlled_by(0) if p.is_creature]


def test_the_unicorn_is_paid_with_plains_and_the_minotaur_follows():
    game = _table()
    report = _main_phase(game)

    assert report.log_lines == [
        "G1 T1 AI cast Regal Unicorn -> resolved",
        "G1 T1 AI cast Hurloon Minotaur -> resolved",
    ]
    assert sorted(_creatures(game)) == ["Hurloon Minotaur", "Regal Unicorn"]
    assert game.players[0].hand == []
    assert all(p.tapped for p in game.controlled_by(0) if p.has_type("land"))
    assert not report.refused_casts


def test_the_board_measures_the_order_blind_plan():
    """Backwards: with the sparing choice switched off the Unicorn is paid in
    board order and the Minotaur stays in hand — so the test above is about
    the payment, not about a board where any order works."""
    with mock.patch.object(mana_payment, "_sparing_choice", lambda *args, **kwargs: None):
        game = _table()
        report = _main_phase(game)
    assert report.log_lines == ["G1 T1 AI cast Regal Unicorn -> resolved"]
    assert [card.name for card in game.players[0].hand] == ["Hurloon Minotaur"]
    untapped = [p.card.name for p in game.controlled_by(0) if not p.tapped]
    assert untapped.count("Mountain") == 1, untapped
