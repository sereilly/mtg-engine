"""``build_limited_deck`` — the simulator's deck, drawn from the set under test.

It replaced a hand-written 36-card list of Alpha cards, which meant
``simulate_ai_games.py --set`` worked for exactly the three base sets and
refused every other one ("the card pool has no 'Island'"). The refusal was
right — a pool that cannot supply the decklist must stop rather than run a
smaller game and report it clean — but it left seven of the ten shipped sets
with no way to be simulated at all.

CR 100.2b is the model: a limited deck is built from one product **and basic
land cards**, 40 cards minimum. The basics matter more than they look —
Antiquities, Legends and The Dark print none between them, and a deck of their
coloured spells with only their own lands casts nothing.
"""

from __future__ import annotations

import pytest

from engine.ai_simulator import (
    LIMITED_DECK_SIZE,
    LIMITED_LAND_COUNT,
    build_limited_deck,
)
from engine.card_loader import manifest_set_codes


def _pool(set_cards, code):
    return {card.name: card for card in set_cards(code)}


@pytest.mark.parametrize("code", manifest_set_codes())
def test_every_shipped_set_builds_a_playable_deck(set_cards, code):
    """The point of the change: all ten, not the three with basic lands."""
    deck = build_limited_deck(_pool(set_cards, code), seed=11)

    assert len(deck) == LIMITED_DECK_SIZE
    lands = [card for card in deck if "land" in (card.type_line or "").lower()]
    assert len(lands) == LIMITED_LAND_COUNT
    assert any(card.produced_mana for card in lands), (
        f"{code}: no land in the deck produces mana, so nothing can be cast — "
        "a run over this set would report a clean sweep over games that never "
        "happened"
    )


@pytest.mark.parametrize("code", manifest_set_codes())
def test_the_spells_come_from_the_set_under_test(set_cards, code):
    """Only the *lands* may come from outside it (CR 100.2b's basics). A spell
    from another set would make ``--set`` a label rather than a scope."""
    pool = _pool(set_cards, code)
    deck = build_limited_deck(pool, seed=5)

    foreign = sorted(
        {
            card.name
            for card in deck
            if card.name not in pool
            and "basic" not in (card.type_line or "").lower()
        }
    )
    assert not foreign, f"{code}: non-basic cards from outside the set: {foreign}"


def test_it_is_deterministic_for_a_seed(set_cards):
    pool = _pool(set_cards, "LEA")
    first = [card.name for card in build_limited_deck(pool, seed=99)]
    second = [card.name for card in build_limited_deck(pool, seed=99)]
    assert first == second


def test_different_seeds_give_different_decks(set_cards):
    """Otherwise every game in a run plays the same 40 cards and the batch is
    one game repeated."""
    pool = _pool(set_cards, "LEA")
    first = [card.name for card in build_limited_deck(pool, seed=1)]
    second = [card.name for card in build_limited_deck(pool, seed=2)]
    assert first != second


def test_required_cards_are_always_dealt(set_cards):
    """How a regression test keeps its subject. Without it, a test asserting
    what the AI does holding Ancestral Recall passes on any seed that dealt
    none — a vacuous pass where there used to be a fixed decklist."""
    pool = _pool(set_cards, "LEA")
    for seed in range(1, 6):
        names = [
            card.name
            for card in build_limited_deck(
                pool, seed=seed, required=("Ancestral Recall", "Prodigal Sorcerer")
            )
        ]
        assert "Ancestral Recall" in names
        assert "Prodigal Sorcerer" in names


def test_spells_are_singletons(set_cards):
    """A draft pool rather than a constructed list, and deliberately: 23
    different cards per deck is 23 times the coverage of the eight-card
    playset deck this replaced, and finding bad interactions across a set is
    what the simulator is for."""
    pool = _pool(set_cards, "LEA")
    deck = build_limited_deck(pool, seed=7)
    spells = [c for c in deck if "land" not in (c.type_line or "").lower()]
    assert len(spells) == len({c.name for c in spells})
