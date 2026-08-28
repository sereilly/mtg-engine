"""Per-card tests for The Dark's artifacts.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.shields import PREVENT_HALF, shields_of_kind
from engine.models import CardDefinition, Permanent


# --- G1: damage family (The Dark) ---


def _dark_sphere(set_pool):
    sphere = Permanent(card=set_pool("DRK")["Dark Sphere"])
    sphere.summoning_sick = False
    burner = Permanent(card=set_pool("LEA")["Rod of Ruin"])
    burner.summoning_sick = False
    players = [PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    players[0].battlefield = [sphere]
    players[1].battlefield = [burner]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game._sync_control()
    return game, players, sphere, burner


def test_dark_sphere_arms_a_half_shield_against_the_chosen_source(set_pool):
    game, players, sphere, burner = _dark_sphere(set_pool)

    result = game.activate_permanent_ability(
        0, "Dark Sphere", target_permanent_ids=[burner.permanent_id]
    )

    assert result.supported, result.details
    shields = shields_of_kind(players[0], PREVENT_HALF)
    assert len(shields) == 1 and shields[0].half == "down", game.log


def test_dark_sphere_prevents_half_the_damage_rounded_down(set_pool):
    """"prevent half that damage, **rounded down**": 7 damage becomes 4, not 3.
    The share is computed when the event exists, because half of an event
    nobody has sized yet is not a number."""
    game, players, sphere, burner = _dark_sphere(set_pool)
    game.activate_permanent_ability(
        0, "Dark Sphere", target_permanent_ids=[burner.permanent_id]
    )

    game._deal_damage_to_player(players[0], 7, source=burner)

    assert players[0].life == 16, game.log


def test_dark_sphere_is_spent_on_the_first_event_it_answers(set_pool):
    """"The **next time** a source … would deal damage": one instance, and the
    second event is unshielded."""
    game, players, sphere, burner = _dark_sphere(set_pool)
    game.activate_permanent_ability(
        0, "Dark Sphere", target_permanent_ids=[burner.permanent_id]
    )

    game._deal_damage_to_player(players[0], 4, source=burner)
    game._deal_damage_to_player(players[0], 4, source=burner)

    assert players[0].life == 14, game.log
    assert shields_of_kind(players[0], PREVENT_HALF) == []


def test_dark_sphere_ignores_damage_from_a_source_it_did_not_choose(set_pool):
    """"a source of your choice" is a property the shield records and CR 615.9
    rechecks. A shield that answered every source is a strictly larger card.

    Two *different* cards, deliberately: the chosen-source matcher the shield
    path uses compares by ``CardDefinition`` as well as by identity, so a second
    printing of the same card is matched as though it were the chosen one. That
    is the look-alike bug ``damage_redirects.source_matches`` was written to
    avoid, still live on the prevention side — see this branch's report.
    """
    game, players, sphere, burner = _dark_sphere(set_pool)
    other = Permanent(card=set_pool("LEA")["Wall of Fire"])
    players[1].battlefield.append(other)
    game._sync_control()
    game.activate_permanent_ability(
        0, "Dark Sphere", target_permanent_ids=[burner.permanent_id]
    )

    game._deal_damage_to_player(players[0], 4, source=other)

    assert players[0].life == 16, game.log
    assert len(shields_of_kind(players[0], PREVENT_HALF)) == 1


def test_a_one_point_event_leaves_the_half_shield_armed(set_pool):
    """Half of 1, rounded down, is 0 — and a shield that would prevent nothing
    does not apply, the same reading Forcefield's cap is given."""
    game, players, sphere, burner = _dark_sphere(set_pool)
    game.activate_permanent_ability(
        0, "Dark Sphere", target_permanent_ids=[burner.permanent_id]
    )

    game._deal_damage_to_player(players[0], 1, source=burner)

    assert players[0].life == 19, game.log
    assert len(shields_of_kind(players[0], PREVENT_HALF)) == 1

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
