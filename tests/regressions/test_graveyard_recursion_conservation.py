"""Regression: returning one copy from a graveyard deleted every copy.

A graveyard holds ``CardDefinition`` objects and ``load_cards`` dedupes by
``oracle_id``, so two copies of one card in one graveyard are **the same
object**. Nether Shadow's upkeep return removed its card with
``[c for c in graveyard if c is not card]``, which therefore removed *all* of
them — while putting only the eligible one onto the battlefield.

Measured before the fix, with one Shadow deep enough to return and a second on
top of the pile: **five cards went in and four came out.** One was deleted from
the game.

This is the look-alike bug class ``tests/engine/test_control_reads.py`` bans on
the battlefield, and it is worse here: on the battlefield two copies are distinct
``Permanent`` objects and the removal takes the wrong *one*, where in a graveyard
it takes every one. The candidate scan already knew the index — it computed it to
count the cards above — and threw it away, so the fix is to keep it and pop.

Every case below asserts card **conservation**, which is the property the bug
broke: what goes in comes out, somewhere.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.card_loader import load_catalog
from engine.models import PlayerState

_CATALOG = {c.name: c for c in load_catalog()}


def _upkeep(graveyard):
    p1 = PlayerState(name="P1", graveyard=list(graveyard))
    game = Game(players=[p1, PlayerState(name="P2")])
    game.resolve_upkeep(0)
    game._settle()
    return p1


_SHADOW = "Nether Shadow"
_ABOVE = ("Grizzly Bears", "Hill Giant", "Scryb Sprites")


@pytest.mark.parametrize(
    ("names", "expected_returned"),
    [
        # One copy deep enough, one on top that is not. The bug case.
        ((_SHADOW, *_ABOVE, _SHADOW), 1),
        # Both deep enough — both return, and nothing extra vanishes.
        ((_SHADOW, _SHADOW, *_ABOVE), 2),
        # One copy, not deep enough: nothing moves.
        ((*_ABOVE, _SHADOW), 0),
    ],
)
def test_a_graveyard_return_conserves_every_copy(names, expected_returned):
    cards = [_CATALOG[name] for name in names]
    player = _upkeep(cards)

    returned = [p for p in player.battlefield if p.card.name == _SHADOW]
    assert len(returned) == expected_returned
    assert len(player.battlefield) + len(player.graveyard) == len(cards), (
        "a card was deleted from the game"
    )
    # And the copies that did not return are still where they were.
    assert [c.name for c in player.graveyard].count(_SHADOW) == (
        names.count(_SHADOW) - expected_returned
    )
