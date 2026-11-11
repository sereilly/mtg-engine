"""CR 106.6's "abilities of artifacts" asks what the source *is* (CR 613.1d).

"Spend this mana only to activate abilities of artifacts." (Soldevi
Machinist, Ice Age) and "…only to cast artifact spells or activate abilities
of artifacts." (Vedalken Engineer, Darksteel) narrow a payment by the type of
the permanent whose ability it is. That type is a characteristic, and a
permanent's characteristics are the printed card after every layer
(CR 613.1) — layer 4 included, where Mycosynth Lattice makes every permanent
an artifact and Neurok Transmuter makes an artifact creature stop being one.

The predicate read ``effective_card.type_line``, which is layers 1 and 3 only,
so the Lattice's Blinkmoth Nexus could not be paid for and a stripped Adarkar
Sentinel could. Each test drives the real activation entry point with costs
enforced and reads the restricted bucket afterwards.
"""

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
    game._settle()
    return permanent


def _restricted(game):
    return {
        key: {symbol: n for symbol, n in bucket.items() if n}
        for key, bucket in game.players[0].restricted_mana.items()
        if any(bucket.values())
    }


def _make_mana(game, producer):
    """Tap *producer* for its restricted mana as a default seat; return the
    bucket key it landed under."""
    tapped = game.activate_permanent_ability(0, producer)
    assert tapped.supported, tapped.details
    settle(game)
    (key,) = _restricted(game)
    assert not any(game.players[0].mana_pool.values()), "restricted mana is held apart"
    return key


@pytest.mark.cr("106.6", "613.1d")
@pytest.mark.parametrize("producer", ["Soldevi Machinist", "Vedalken Engineer"])
@pytest.mark.parametrize("lattice", [True, False])
def test_mana_for_artifact_abilities_pays_a_lattice_made_artifact(
    set_pool, producer, lattice,
):
    """Blinkmoth Nexus is a land; under Mycosynth Lattice ("All permanents
    are artifacts in addition to their other types") it is an artifact land,
    and its "{1}: … becomes a 1/1 Blinkmoth artifact creature" is an ability
    of an artifact the restricted mana may pay for. Without the Lattice the
    same activation is refused and the mana stays where it was. The Nexus is
    tapped first so it cannot pay for itself."""
    game = _table(set_pool)
    pool = {"Soldevi Machinist": "ICE", "Vedalken Engineer": "DST"}
    _put(game, set_pool(pool[producer])[producer])
    nexus = _put(game, set_pool("DST")["Blinkmoth Nexus"])
    if lattice:
        _put(game, set_pool("DST")["Mycosynth Lattice"])
    nexus.tapped = True
    assert nexus.has_type("artifact") is lattice
    key = _make_mana(game, producer)
    before = sum(_restricted(game)[key].values())
    game.enforce_mana_costs = True

    result = game.activate_permanent_ability(0, "Blinkmoth Nexus", ability_index=1)
    settle(game)

    if lattice:
        assert result.supported, result.details
        assert nexus.is_creature and nexus.has_type("blinkmoth")
        assert sum(_restricted(game)[key].values()) == before - 1
    else:
        assert not result.supported
        assert "insufficient mana" in result.details
        assert not nexus.is_creature
        assert sum(_restricted(game)[key].values()) == before


@pytest.mark.cr("106.6", "613.1d", "205.1a")
@pytest.mark.parametrize("stripped", [True, False])
def test_mana_for_artifact_abilities_refuses_a_transmuted_artifact_creature(
    set_pool, stripped,
):
    """The removing half: Neurok Transmuter's "{U}: Until end of turn, target
    artifact creature becomes blue and isn't an artifact" leaves Adarkar
    Sentinel a creature with no artifact type, so its "{1}: +0/+1" is no
    longer an ability of an artifact and the Machinist's {C}{C} may not pay
    it — the direction that works more often than the card allows. Unstripped,
    the same mana pays."""
    game = _table(set_pool)
    _put(game, set_pool("DST")["Neurok Transmuter"])
    _put(game, set_pool("ICE")["Soldevi Machinist"])
    sentinel = _put(game, set_pool("ICE")["Adarkar Sentinel"])
    if stripped:
        transmute = game.activate_permanent_ability(
            0, "Neurok Transmuter", ability_index=1,
            target_permanent_ids=[sentinel.permanent_id],
        )
        assert transmute.supported, transmute.details
        settle(game)
    assert sentinel.has_type("artifact") is not stripped
    assert sentinel.is_creature
    key = _make_mana(game, "Soldevi Machinist")
    game.enforce_mana_costs = True

    result = game.activate_permanent_ability(0, "Adarkar Sentinel")
    settle(game)

    if stripped:
        assert not result.supported
        assert sentinel.effective_toughness == 3
        assert _restricted(game) == {key: {"C": 2}}
    else:
        assert result.supported, result.details
        assert sentinel.effective_toughness == 4
        assert _restricted(game) == {key: {"C": 1}}
