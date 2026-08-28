"""Per-card tests for The Dark's artifacts.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


# --- G5: zones and characteristics (The Dark) ---------------------------------


def _nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _basic(name: str, subtype: str, symbol: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0,
        type_line=f"Basic Land - {subtype}", oracle_text="",
        colors=(), color_identity=(symbol,), keywords=(), produced_mana=(symbol,),
        raw={"name": name, "type_line": f"Basic Land - {subtype}"},
    )


def test_living_armor_gives_counters_equal_to_the_targets_mana_value(set_pool):
    """"Put **X** +0/+1 counters on target creature, where X is **that
    creature's** mana value."

    The where-clause's referent is spelled out as a possessive rather than as
    "its", and it means the same thing - one production for both word orders,
    so which characteristics a card may name does not depend on how it was
    printed.
    """
    pool = set_pool("DRK")
    p1 = PlayerState(
        name="P1",
        battlefield=[
            _nosick(Permanent(card=pool["Living Armor"])),
            Permanent(card=pool["Necropolis"]),
        ],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    wall = p1.battlefield[1]
    printed = wall.effective_toughness
    mana_value = int(pool["Necropolis"].cmc)
    assert mana_value > 1, "the fixture needs a target worth more than one counter"

    result = game.activate_permanent_ability(
        0, "Living Armor", permanent_index=0,
        target_player_index=0, target_permanent_ids=[wall.permanent_id],
    )

    assert result.supported, result.details
    assert wall.effective_toughness == printed + mana_value, game.log
    assert wall.effective_power == 0, "+0/+1 adds no power"
    assert "Living Armor" not in {
        perm.card.name for perm in p1.battlefield
    }, "the sacrifice is part of the cost"


def test_fellwar_stone_copies_a_color_an_opponents_land_makes(set_pool):
    """"Add one mana of any color **that a land an opponent controls could
    produce**." The restriction is read off the opponents' board through the
    control seam, not off the Stone."""
    pool = set_pool("DRK")
    p1 = PlayerState(
        name="P1", battlefield=[_nosick(Permanent(card=pool["Fellwar Stone"]))],
    )
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=_basic("Swamp", "Swamp", "B"))])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.activate_permanent_ability(0, "Fellwar Stone", permanent_index=0)

    assert result.supported, result.details
    assert p1.mana_pool["B"] == 1, (dict(p1.mana_pool), game.log)
    assert sum(p1.mana_pool.values()) == 1


def test_fellwar_stone_makes_nothing_when_no_opponent_land_makes_color(set_pool):
    """The control: with the set empty there is no colour to copy, so the
    ability produces nothing rather than defaulting to green."""
    pool = set_pool("DRK")
    p1 = PlayerState(
        name="P1", battlefield=[_nosick(Permanent(card=pool["Fellwar Stone"]))],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    game.activate_permanent_ability(0, "Fellwar Stone", permanent_index=0)

    assert sum(p1.mana_pool.values()) == 0, (dict(p1.mana_pool), game.log)
