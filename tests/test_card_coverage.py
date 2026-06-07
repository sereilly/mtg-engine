from __future__ import annotations

import pytest

from engine import Game, PlayerState, classify_card


def _build_test_case(card, all_cards):
    island = next(c for c in all_cards if c.name == "Island")
    p1 = PlayerState(name="P1", hand=[card])
    p2 = PlayerState(name="P2", library=[island, island, island, island])
    game = Game(players=[p1, p2])

    classification = classify_card(card)
    result = game.cast_from_hand(0, card.name, target_player_index=1)

    # Classified-unsupported cards must always return unsupported.
    if not classification.supported:
        assert not result.supported
    # Classified-supported cards may return supported=False when no valid target
    # exists in the test setup — that is correct Rule 601.2c behavior.
    if result.supported:
        assert result.effect_kind == classification.effect_kind


def pytest_generate_tests(metafunc):
    if "card_name" not in metafunc.fixturenames:
        return

    # The conftest fixture is not available here, so read from request config path.
    from engine import load_cards
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    cards = load_cards(root / "lea_cards.json")
    names = [card.name for card in cards]
    metafunc.parametrize("card_name", names)


def test_each_card_simulates_without_crash(card_name, all_cards):
    card = next(c for c in all_cards if c.name == card_name)
    _build_test_case(card, all_cards)
