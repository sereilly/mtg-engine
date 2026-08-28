"""Per-card tests for The Dark's artifacts.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.shields import PREVENT_HALF, shields_of_kind


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
