from pathlib import Path

from web.deck_builder import build_random_deck


def test_random_deck_has_60_cards_and_24_lands():
    deck, colors = build_random_deck(Path("lea_cards.json"), color_count=3, seed=101)

    assert len(colors) == 3
    assert len(deck) == 60
    assert sum(1 for card in deck if card.primary_type == "land") == 24


def test_random_deck_all_color_counts():
    for count in range(1, 6):
        deck, colors = build_random_deck(Path("lea_cards.json"), color_count=count, seed=500 + count)
        assert len(colors) == count
        assert len(deck) == 60
        assert sum(1 for card in deck if card.primary_type == "land") == 24
