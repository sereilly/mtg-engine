"""CR 605 / 106.12: tapping a land for mana is activating *one* of its mana
abilities — the one its controller chooses — and the tap seam asks the same
gates the activation path does.

``Game.tap_land_for_mana`` is the seam every tap-for-mana event goes through
(the Desolation record, CR 106.12b's swaps, Mana Flare and the other
``land_tapped_for_mana`` triggers). It took no ability index and ran the land's
**first** tap-alone mana ability, so:

- a mana ability *granted* to a land (Overlaid Terrain's "{T}: Add two mana of
  any one color.") lost to the land's own whenever it had one — 115 shipped
  lands do — and a Karplusan Forest under Overlaid Terrain asked for {U} made
  {C};
- a painland's coloured second ability could not go through the seam at all,
  so the wire sent it down the activation path, which announces none of the
  above.

It also skipped three gates the activation path asks of the very same ability:
CR 305.7 (a land whose type an effect set loses its printed abilities — a
Karplusan Forest under Blood Moon tapped for its printed {C}), CR 302.6 through
CR 602.5a (a land that is a creature and arrived this turn), and CR 602.5's
per-permanent ban (Interdict).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.spell_prohibitions import forbid_permanent_activations_this_turn
from tests.helpers import _nosick, resolve_stack


def _w2g3_seat(*permanents, hand=(), library=None):
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(permanents), hand=list(hand),
                    library=list(library or [])),
        PlayerState(name="P2", library=list(library or [])),
    ])
    game.interactive_seats = set()
    game._settle()
    return game


def _w2g3_pool(game):
    return {s: n for s, n in game.players[0].mana_pool.items() if n}


def _w2g3_karplusan_under_terrain(set_pool):
    """Overlaid Terrain sacrifices every land as it enters, so the Forest
    arrives after it — which is also the order the grant has to survive."""
    terrain = Permanent(card=set_pool("NEM")["Overlaid Terrain"])
    game = _w2g3_seat(terrain)
    forest = Permanent(card=set_pool("ICE")["Karplusan Forest"])
    game._put_permanent_onto_battlefield(0, forest, None)
    game._settle()
    return game, forest


@pytest.mark.cr("605.1a", "106.12")
def test_a_granted_mana_ability_is_reachable_through_the_tap_seam(set_pool):
    game, forest = _w2g3_karplusan_under_terrain(set_pool)

    assert game.tap_land_for_mana(
        0, "Karplusan Forest", "U", permanent_id=forest.permanent_id, ability_index=2,
    )

    assert _w2g3_pool(game) == {"U": 2}, game.log
    assert game.players[0].life == 20
    assert game.players[0].tapped_land_for_mana_this_turn


@pytest.mark.cr("605.1a", "106.12")
def test_the_lands_own_first_ability_is_still_the_default(set_pool):
    game, forest = _w2g3_karplusan_under_terrain(set_pool)

    assert game.tap_land_for_mana(0, "Karplusan Forest", "U", permanent_id=forest.permanent_id)

    assert _w2g3_pool(game) == {"C": 1}, game.log


@pytest.mark.cr("605.1a", "106.12")
def test_a_painlands_coloured_ability_through_the_seam_makes_the_colour_and_deals_damage(set_pool):
    """"{T}: Add {R} or {G}. This land deals 1 damage to you." lowers to a
    sequence; the colour reaches its nested add step, and the rider runs."""
    forest = Permanent(card=set_pool("ICE")["Karplusan Forest"])
    game = _w2g3_seat(forest)

    assert game.tap_land_for_mana(
        0, "Karplusan Forest", "G", permanent_id=forest.permanent_id, ability_index=1,
    )

    assert _w2g3_pool(game) == {"G": 1}, game.log
    assert game.players[0].life == 19
    assert game.players[0].tapped_land_for_mana_this_turn


@pytest.mark.cr("106.12b", "605.1a")
def test_a_swap_reaches_a_painlands_coloured_ability_through_the_seam(set_pool):
    forest = Permanent(card=set_pool("ICE")["Karplusan Forest"])
    game = _w2g3_seat(forest, Permanent(card=set_pool("ICE")["Infernal Darkness"]))

    game.tap_land_for_mana(
        0, "Karplusan Forest", "R", permanent_id=forest.permanent_id, ability_index=1,
    )

    assert _w2g3_pool(game) == {"B": 1}, game.log
    assert game.players[0].life == 19


@pytest.mark.cr("602.2b", "106.12")
def test_a_priced_mana_ability_chosen_by_index_is_refused_with_nothing_tapped(set_pool):
    """"{T}, Remove a mining counter from this land: …" costs more than the tap,
    which the activation path pays and this seam never does."""
    mine = Permanent(card=set_pool("WTH")["Gemstone Mine"])
    game = _w2g3_seat(mine)

    assert not game.tap_land_for_mana(
        0, "Gemstone Mine", "R", permanent_id=mine.permanent_id, ability_index=0,
    )
    assert not mine.tapped
    assert _w2g3_pool(game) == {}


@pytest.mark.cr("305.7")
def test_blood_moon_takes_the_printed_mana_abilities_away_at_the_tap_seam_too(set_pool):
    """A Karplusan Forest that is a Mountain makes {R} and deals no damage; a
    Mishra's Workshop that is a Mountain makes one unrestricted {R}."""
    forest = Permanent(card=set_pool("ICE")["Karplusan Forest"])
    workshop = Permanent(card=set_pool("ATQ")["Mishra's Workshop"])
    game = _w2g3_seat(forest, workshop, Permanent(card=set_pool("DRK")["Blood Moon"]))

    game.tap_land_for_mana(0, "Karplusan Forest", "G", permanent_id=forest.permanent_id)
    game.tap_land_for_mana(0, "Mishra's Workshop", "C", permanent_id=workshop.permanent_id)

    assert _w2g3_pool(game) == {"R": 2}, game.log
    assert game.players[0].life == 20
    assert not any(any(b.values()) for b in game.players[0].restricted_mana.values())


@pytest.mark.cr("302.6", "602.5a")
def test_a_land_animated_the_turn_it_arrived_cannot_tap_for_mana(set_pool):
    """Mishra's Factory played this turn and animated is a creature that has
    not been controlled since the turn began, and its {T} mana ability is a
    {T} ability (CR 302.6)."""
    game = _w2g3_seat(hand=[set_pool("ATQ")["Mishra's Factory"]])
    assert game.cast_from_hand(0, "Mishra's Factory").supported
    factory = next(p for p in game.controlled_by(0) if p.card.name == "Mishra's Factory")
    game.enforce_mana_costs = True
    game.players[0].mana_pool["C"] = 1
    assert game.activate_permanent_ability(0, "Mishra's Factory", ability_index=1).supported
    resolve_stack(game)
    assert factory.is_creature

    assert not game.tap_land_for_mana(
        0, "Mishra's Factory", "C", permanent_id=factory.permanent_id,
    )
    assert not factory.tapped
    assert _w2g3_pool(game) == {}


@pytest.mark.cr("302.6")
def test_an_animated_land_that_has_been_there_all_turn_still_taps(set_pool):
    factory = _nosick(Permanent(card=set_pool("ATQ")["Mishra's Factory"]))
    game = _w2g3_seat(factory)
    game.enforce_mana_costs = True
    game.players[0].mana_pool["C"] = 1
    assert game.activate_permanent_ability(0, "Mishra's Factory", ability_index=1).supported
    resolve_stack(game)

    assert game.tap_land_for_mana(0, "Mishra's Factory", "C", permanent_id=factory.permanent_id)
    assert _w2g3_pool(game) == {"C": 1}


@pytest.mark.cr("602.5")
def test_a_land_whose_abilities_are_forbidden_this_turn_cannot_tap_for_mana(set_pool):
    """Interdict: "That permanent's activated abilities can't be activated this
    turn." No mana-ability exception is printed, and the activation path
    already refused the same ability."""
    forest = Permanent(card=set_pool("ICE")["Karplusan Forest"])
    game = _w2g3_seat(forest)
    forbid_permanent_activations_this_turn(game, forest)

    assert not game.activate_permanent_ability(0, "Karplusan Forest", ability_index=0).supported
    assert not game.tap_land_for_mana(0, "Karplusan Forest", "G", permanent_id=forest.permanent_id)
    assert not forest.tapped
    assert _w2g3_pool(game) == {}
