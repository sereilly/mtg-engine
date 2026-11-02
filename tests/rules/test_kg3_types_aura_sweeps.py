"""CR 704.5m and 702.16c ask what an attached permanent and its host **are**.

Both sweeps in ``mixins/game_ending.py`` are questions about types, and both
used to answer one of them off the printed card:

* **Is the attached permanent an Aura?** CR 613 layer 4's answer, not the
  printed word. "{U}, {T}: This creature loses this ability and becomes an
  Aura enchantment with enchant creature. Attach it to target creature."
  (Gliding Licid.) The Licid's printed line says Creature — Licid, so the
  CR 702.16c sweep — which read ``"Aura" in perm.card.type_line`` — never asked
  whether the creature it enchants has protection from blue, and a Licid
  stayed on a host given protection from its colour, still granting flying.
  The other way round a permanent that has *lost* the Aura type (CR 205.1a)
  is not an Aura to either sweep; 704.5p unattaches it instead.

* **Is the host what the enchant ability names?** CR 303.4c: "If an Aura is
  enchanting an illegal object or player as defined by its enchant ability
  and other applicable effects … the Aura is put into its owner's
  graveyard." The sweep enforced the clause's *seat* half alone ("enchant
  creature you control"), so an "Enchant creature" Aura stayed on a Mishra's
  Factory after its animation ended, an "Enchant Wall" Aura stayed on a Wall a
  Conspiracy had made a Goblin, and an "Enchant creature without flying" Aura
  stayed on a creature a Licid had given flying. The picker and the cast gate
  already refused every one of those hosts (``permanent_matches_enchant_noun``);
  the sweep asks the same predicate now (``aura_attachment.unsatisfied_enchant_clause``).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.type_changes import lose_types
from tests.helpers import _nosick, resolve_stack


def _duel(pool, mine, theirs=()):
    library = [pool["Forest"]] * 10
    game = Game(players=[
        PlayerState(name="P0", battlefield=list(mine), library=list(library)),
        PlayerState(name="P1", battlefield=list(theirs), library=list(library)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    game._sync_control()
    for player in game.players:
        for permanent in player.battlefield:
            _nosick(permanent)
    game._recompute_continuous_effects()
    return game


def _cast_aura(game, name, host):
    result = game.cast_from_hand(0, name, target_permanent_ids=[host.permanent_id])
    assert result.supported, result
    resolve_stack(game)
    return next(p for p in game.all_permanents() if p.card.name == name)


def _licid_on(game, host):
    result = game.activate_permanent_ability(
        0, "Gliding Licid", ability_index=0,
        target_permanent_ids=[host.permanent_id],
    )
    assert result.supported, result
    resolve_stack(game)


@pytest.fixture(scope="module")
def pool(set_pool):
    found = {}
    for code, names in (
        ("4ED", ("Forest", "Grizzly Bears", "Blue Ward", "Holy Strength", "Flight",
                 "Wall of Stone", "Animate Wall", "Mishra's Factory")),
        ("STH", ("Gliding Licid",)),
        ("HML", ("Roots",)),
        ("MMQ", ("Conspiracy",)),
    ):
        for name in names:
            found[name] = set_pool(code)[name]
    return found


@pytest.mark.cr("702.16c", "613.1d")
def test_a_licid_that_became_an_aura_falls_off_a_host_with_protection_from_its_colour(pool):
    bears = Permanent(card=pool["Grizzly Bears"])
    licid = Permanent(card=pool["Gliding Licid"])
    game = _duel(pool, [licid, bears])
    game.players[0].hand.append(pool["Blue Ward"])
    _licid_on(game, bears)
    assert licid.has_type("aura") and licid.metadata.get("attached_to") is bears
    assert game._has_keyword(bears, "flying")

    _cast_aura(game, "Blue Ward", bears)

    assert not game.is_on_battlefield(licid)
    assert "Gliding Licid" in [card.name for card in game.players[0].graveyard]
    assert any(
        "Gliding Licid put into graveyard (702.16c" in line for line in game.log
    )
    assert not game._has_keyword(bears, "flying")
    # Blue Ward's own "this effect doesn't remove Blue Ward" keeps it on.
    assert any(p.card.name == "Blue Ward" for p in game.all_permanents())


@pytest.mark.cr("704.5p", "205.1a")
def test_an_aura_that_lost_the_aura_type_is_not_swept_as_one(pool):
    """CR 205.1a: a permanent whose Aura subtype an effect removed is not an
    Aura, so CR 702.16c's sweep does not put a blue one into the graveyard over
    its host's protection from blue — CR 704.5p unattaches it and it stays.
    The printed read binned it, its line still saying "Aura"."""
    from engine.aura_attachment import attach_aura

    bears = Permanent(card=pool["Grizzly Bears"])
    flight = Permanent(card=pool["Flight"])
    ward = Permanent(card=pool["Blue Ward"])
    game = _duel(pool, [bears, flight, ward])
    attach_aura(flight, bears)
    # The layer-4 write API stands in for an effect that removes the Aura
    # subtype; no printed card in the pool takes it from an attached Aura.
    lose_types(flight, subtypes=["aura"], source="a test effect", seat=0)
    attach_aura(ward, bears)
    game._recompute_continuous_effects()
    assert not flight.has_type("aura")

    game.check_state_based_actions()

    assert game.is_on_battlefield(flight)
    assert flight.metadata.get("attached_to") is None
    assert any("Flight became unattached (704.5p" in line for line in game.log)
    assert not any("Flight put into graveyard" in line for line in game.log)


@pytest.mark.cr("704.5m", "303.4c")
def test_an_enchant_creature_aura_falls_off_a_land_whose_animation_ended(pool):
    factory = Permanent(card=pool["Mishra's Factory"])
    game = _duel(pool, [factory])
    game.players[0].hand.append(pool["Holy Strength"])
    result = game.activate_permanent_ability(0, "Mishra's Factory", ability_index=1)
    assert result.supported, result
    resolve_stack(game)
    assert factory.is_creature
    holy = _cast_aura(game, "Holy Strength", factory)
    assert holy.metadata.get("attached_to") is factory

    game.resolve_cleanup_step(0)
    game.check_state_based_actions()

    assert not factory.is_creature
    assert not game.is_on_battlefield(holy)
    assert "Holy Strength" in [card.name for card in game.players[0].graveyard]
    assert any(
        "Holy Strength put into graveyard (704.5m" in line for line in game.log
    )


@pytest.mark.cr("704.5m", "205.1a")
def test_an_enchant_wall_aura_falls_off_a_wall_a_conspiracy_retyped(pool):
    """Conspiracy's first sentence replaces the Wall's creature types
    (CR 205.1a; the card's ruling, 2013-09-20: "Affected … creatures lose all
    of their other creature types"), so it is no longer a Wall and "Enchant
    Wall" no longer allows it."""
    wall = Permanent(card=pool["Wall of Stone"])
    game = _duel(pool, [wall])
    game.players[0].hand.append(pool["Animate Wall"])
    animate = _cast_aura(game, "Animate Wall", wall)
    assert animate.metadata.get("attached_to") is wall

    conspiracy = Permanent(card=pool["Conspiracy"])
    conspiracy.metadata["chosen_creature_type"] = "Goblin"
    game.players[0].battlefield.append(conspiracy)
    game._sync_control()
    game._recompute_continuous_effects()
    assert wall.has_type("goblin") and not wall.has_type("wall")

    game.check_state_based_actions()

    assert not game.is_on_battlefield(animate)
    assert game.is_on_battlefield(wall)


@pytest.mark.cr("704.5m", "702.5a")
def test_an_aura_for_a_creature_without_flying_falls_off_one_that_gained_it(pool):
    bears = Permanent(card=pool["Grizzly Bears"])
    licid = Permanent(card=pool["Gliding Licid"])
    game = _duel(pool, [bears, licid])
    game.players[0].hand.append(pool["Roots"])
    roots = _cast_aura(game, "Roots", bears)
    assert roots.metadata.get("attached_to") is bears

    _licid_on(game, bears)

    assert game._has_keyword(bears, "flying")
    assert not game.is_on_battlefield(roots)
    assert game.is_on_battlefield(licid)


@pytest.mark.cr("704.5m", "303.4c")
def test_a_host_that_still_answers_the_clause_keeps_its_aura(pool):
    """The other direction, so the sweep is not simply binning Auras: Holy
    Strength on a creature that stays a creature, and Animate Wall on a Wall
    under no Conspiracy, are both legal and stay through a state check."""
    bears = Permanent(card=pool["Grizzly Bears"])
    wall = Permanent(card=pool["Wall of Stone"])
    game = _duel(pool, [bears, wall])
    game.players[0].hand.extend([pool["Holy Strength"], pool["Animate Wall"]])
    holy = _cast_aura(game, "Holy Strength", bears)
    animate = _cast_aura(game, "Animate Wall", wall)

    game.check_state_based_actions()

    assert game.is_on_battlefield(holy) and game.is_on_battlefield(animate)
