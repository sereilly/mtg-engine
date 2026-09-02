"""``Game.take_card_from_hand`` — removing exactly one copy from a hand.

Split out rather than folded into a card's test because the hazard is not about
a card. A hand is a ``list[CardDefinition]`` and every copy of a card in a deck
is *the same Python object* (``web/deck_builder.py``: ``[card] * count``), so
the obvious identity filter removes all of them and the caller then puts one
somewhere. ``engine/phases/upkeep_step.py`` documents the same class found in a
graveyard; five hand sites had it, and the AI simulator's fixed eight-card
decklist could reach none of them.
"""

from __future__ import annotations

import ast
import pathlib

from engine.game import Game
from engine.models import PlayerState
from tests.source_index import source_text, source_tree

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _game_with_hand(hand):
    p1 = PlayerState(name="P1", hand=list(hand))
    return Game(players=[p1, PlayerState(name="P2")]), p1


def test_it_removes_one_copy_of_a_shared_object(catalog_by_name):
    forest = catalog_by_name["Forest"]
    game, player = _game_with_hand([forest, forest, forest])

    assert game.take_card_from_hand(player, forest) is True
    assert len(player.hand) == 2
    assert all(card is forest for card in player.hand)


def test_it_matches_by_identity_not_by_value(catalog_by_name):
    """Two printings of one card are different objects that compare *equal*
    only if every field matches; a look-alike from another set must not be the
    one removed. ``list.remove``/``list.index`` compare by value, which is why
    this seam does neither."""
    alpha_forest = catalog_by_name["Forest"]
    game, player = _game_with_hand([alpha_forest, catalog_by_name["Grizzly Bears"]])

    assert game.take_card_from_hand(player, alpha_forest) is True
    assert [c.name for c in player.hand] == ["Grizzly Bears"]


def test_it_reports_a_card_that_is_not_there(catalog_by_name):
    """False rather than an exception: CR 608.2's "do as much as possible" is
    the caller's decision, and every caller already logs its own version."""
    game, player = _game_with_hand([catalog_by_name["Forest"]])
    assert game.take_card_from_hand(player, catalog_by_name["Black Lotus"]) is False
    assert len(player.hand) == 1


def test_it_accepts_a_seat_index_as_well_as_a_player(catalog_by_name):
    """Both spellings reach the zone seams from call sites that hold one or the
    other — the same reason ``put_card_into_hand`` takes both."""
    forest = catalog_by_name["Forest"]
    game, player = _game_with_hand([forest, forest])

    assert game.take_card_from_hand(0, forest) is True
    assert len(player.hand) == 1


def test_no_engine_module_filters_a_hand_by_identity():
    """The guard that keeps the seam the only way.

    An ``if c is not card`` comprehension over a hand is the bug this file
    exists for, and it reads as obviously correct — which is why it was written
    five times. Anything new that spells it out fails here rather than waiting
    for a deck to hold two copies of one card.
    """
    offenders: list[str] = []
    for path in sorted((ROOT / "engine").rglob("*.py")):
        tree = source_tree(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ListComp):
                continue
            source = ast.get_source_segment(
                source_text(path), node
            ) or ""
            flat = " ".join(source.split())
            if ".hand" in flat and " is not " in flat:
                offenders.append(f"{path.relative_to(ROOT)}: {flat[:90]}")
    assert not offenders, (
        "hands filtered by identity — this removes *every* copy of a shared "
        "CardDefinition. Use Game.take_card_from_hand:\n  "
        + "\n  ".join(offenders)
    )
