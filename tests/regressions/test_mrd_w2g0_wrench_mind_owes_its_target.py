"""Wrench Mind owes its target (Mirrodin's promotion rehearsal, W2G0; W2G5
found it in ``tests/engine/test_player_target_resolution_census.py``).

"Target player discards two cards unless they discard an artifact card."
The lowering is a ``may`` whose actor is that player, the artifact discard —
no quantifier of its own — on the taken branch, and
``legality._inside_an_offer`` read that as an offer the spell merely makes,
so the spell owed no target (CR 601.2c): a bare cast named nobody and
resolved on the default seat, through the opponent's Ivory Mask (CR 702.18a
for a player). An offer *to the target* is not the caster's to decline, so
only a ``may`` whose actor is the caster counts now, and the bare cast is
defaulted like every other: to a seat the picker offers.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _table(set_pool, *, masked: bool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    hand = [lea["Mountain"], lea["Grizzly Bears"], lea["Giant Growth"]]
    game = Game(players=[
        PlayerState(name="A", hand=[mrd["Wrench Mind"], *hand], library=[lea["Plains"]] * 5),
        PlayerState(name="B", hand=list(hand), library=[lea["Plains"]] * 5),
    ])
    game.enforce_mana_costs = False
    if masked:
        game._put_permanent_onto_battlefield(
            1, Permanent(card=set_pool("MMQ")["Ivory Mask"]), None,
        )
    return game


@pytest.mark.cr("601.2c", "702.18a")
def test_a_bare_wrench_mind_never_resolves_on_a_masked_opponent(set_pool):
    """Behind the Mask the opponent is no legal target, so the bare cast is
    aimed at the one seat the picker offers — the caster — and the opponent
    keeps every card."""
    game = _table(set_pool, masked=True)
    spec = game.cast_target_spec(0, set_pool("MRD")["Wrench Mind"])
    assert {entry["seat"] for entry in spec["valid_targets"]} == {0}

    assert game.cast_from_hand(0, "Wrench Mind").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert len(game.players[1].hand) == 3 and game.players[1].graveyard == []
    assert len(game.players[0].hand) == 1


@pytest.mark.cr("601.2c")
def test_a_bare_wrench_mind_at_an_open_table_hits_the_opponent(set_pool):
    """The control: with nothing in the way the default is the opposing
    seat, which discards two (it holds no artifact card)."""
    game = _table(set_pool, masked=False)

    assert game.cast_from_hand(0, "Wrench Mind").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert len(game.players[1].hand) == 1 and len(game.players[1].graveyard) == 2
    assert len(game.players[0].hand) == 3
