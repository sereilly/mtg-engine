"""Regression: "Regenerate target artifact" names every artifact, not only the
artifact creatures.

Found driving Darksteel's Pteron Ghost (DST W1G2). The regeneration target
reader (``handlers/regeneration.regeneration_target_legal``, asked by the
picker, the cast gate and the handler) stood on ``creature_floor_holds``,
which keeps a *creature* floor for any described card type — so "target
artifact" was answered as "target artifact creature". CR 701.19a regenerates
any permanent. Two shipped Mirrodin cards printed the sentence and could
regenerate no Equipment, no Ingot, no Myr Retriever's Talisman: the picker
offered nothing and the ability was refused with "no valid target".

"Regenerate target creature" (Death Ward's empty payload) keeps its floor:
a noncreature artifact is still no target for it.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import settle


def _table(set_pool):
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[island] * 20) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _put(game, card, seat=0):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    settle(game)
    return permanent


@pytest.mark.parametrize("code, name", [
    ("MRD", "Welding Jar"), ("MRD", "Loxodon Mender"), ("DST", "Pteron Ghost"),
])
def test_regenerate_target_artifact_shields_a_noncreature_artifact(set_pool, code, name):
    game = _table(set_pool)
    source = _put(game, set_pool(code)[name])
    star = _put(game, set_pool("DST")["Vulshok Morningstar"])
    result = game.activate_permanent_ability(
        0, name, permanent_index=game.battlefield_index_of(source),
        target_permanent_ids=[star.permanent_id], ability_index=0,
    )
    assert result.supported, result
    settle(game)
    game.players[0].hand = [set_pool("LEA")["Shatter"]]
    assert game.cast_from_hand(0, "Shatter", target_permanent_ids=[star.permanent_id]).supported
    settle(game)
    assert star in game.controlled_by(0)
    assert star.tapped
    assert "Vulshok Morningstar regenerated" in game.log


def test_regenerate_target_creature_still_refuses_a_noncreature(set_pool):
    game = _table(set_pool)
    _put(game, set_pool("LEA")["Grizzly Bears"])
    star = _put(game, set_pool("DST")["Vulshok Morningstar"])
    game.players[0].hand = [set_pool("LEA")["Death Ward"]]
    refused = game.cast_from_hand(0, "Death Ward", target_permanent_ids=[star.permanent_id])
    assert not refused.supported
