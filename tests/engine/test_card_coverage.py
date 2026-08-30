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

    # Conftest fixtures are not available at collection time, so the catalog
    # is loaded from the manifest directly — the same list, covering every set.
    from engine.card_loader import load_catalog

    metafunc.parametrize("card_name", [card.name for card in load_catalog()])


def test_each_card_simulates_without_crash(card_name, catalog_by_name, all_cards):
    card = catalog_by_name[card_name]
    _build_test_case(card, all_cards)


def test_classify_card_never_widens_the_compilers_answer():
    """`classify_card` is a pass-through, and the whole pool is the assertion.

    It used to widen: a card the compiler refused for "unsupported triggered
    ability" was reported **supported** whenever any *other* trigger of it
    compiled. That is the widened-gate shape — the question is "is every line of
    this card read?" and the answer given was "does some line of it work?" — and
    it was not confined to a census: `mixins/stack/casting.py`, `web/catalog.py`
    and `engine/ai_policy.py` all ask this rather than the compiler, so such a
    card was castable and playable with a printed trigger doing nothing.

    Over the shipped **and** measured pool, because the one card it was hiding
    was in the measured half — a guard over the shipped pool alone would have
    passed on the day it was written and every day before it.
    """
    from engine.card_loader import load_cards, manifest_set_paths
    from engine.oracle import compile_card_oracle

    disagreements = [
        card.name
        for card in load_cards(manifest_set_paths(include_measured=True))
        if classify_card(card).supported != compile_card_oracle(card).supported
    ]

    assert disagreements == []
