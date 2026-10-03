"""CR 106.6 / 106.12b: a land-mana swap reaches restricted mana, and keeps the
restriction.

A swap ("if a land is tapped for mana, it produces {B} instead of any other
type") is a replacement over the **mana production event** (CR 106.12b). Where
the produced mana goes is a fact about the ability that made it: "Spend this
mana only to cast artifact spells" (Mishra's Workshop) is a restriction the
ability creates (CR 106.6), and CR 106.6a says such a restriction applies to
all the mana produced even when a replacement changes how much. So the swap
changes the type and the restriction stays.

The tap seam compared only the open pool before and after the production, and
the Workshop's mana goes to its own ``artifact`` bucket — so it escaped every
swap in the pool: under Contamination it made {C}{C}{C} where the card says one
{B}. Census (W1G6's, re-run): of every land with a free compiled mana ability,
exactly Mishra's Workshop produces restricted mana; the fixture lands below
stand in for the two by-type swaps, which no shipped restricted land is typed
for.

**Hall of Gemstone's "instead of any other color"** is the same comparison's
other half. It was read as "any other type", so the swap turned colourless mana
coloured — an Ancient Tomb or a Workshop under it made the chosen colour. CR
106.1a has five colours and CR 106.1b six types; {C} is the sixth type and no
colour, so Hall leaves it alone.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _mk_card, _nosick, resolve_stack


def _w2g3_board(*permanents, library=None):
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(permanents), library=list(library or [])),
        PlayerState(name="P2", library=list(library or [])),
    ])
    game.interactive_seats = set()
    game._settle()
    return game


def _w2g3_restricted(game):
    """The seat's restricted buckets with the empties dropped."""
    return {
        key: {s: n for s, n in bucket.items() if n}
        for key, bucket in game.players[0].restricted_mana.items()
        if any(bucket.values())
    }


def _w2g3_open_pool(game):
    return {s: n for s, n in game.players[0].mana_pool.items() if n}


def _w2g3_restricted_plains(name="Restricted Plains", basic="Plains", symbol="W"):
    """A land the pool does not print: a basic land type *and* restricted mana,
    which is what the two by-type swaps need to meet one."""
    return _mk_card(
        name=name, type_line=f"Land — {basic}",
        oracle_text=f"{{T}}: Add {{{symbol}}}{{{symbol}}}. Spend this mana only to cast artifact spells.",
        produced_mana=(symbol,),
    )


@pytest.mark.cr("106.6", "106.12b")
def test_infernal_darkness_turns_the_workshops_mana_black_and_keeps_it_for_artifacts(set_pool):
    workshop = Permanent(card=set_pool("ATQ")["Mishra's Workshop"])
    game = _w2g3_board(workshop, Permanent(card=set_pool("ICE")["Infernal Darkness"]))

    assert game.tap_land_for_mana(0, "Mishra's Workshop", "C")

    assert _w2g3_restricted(game) == {"artifact": {"B": 3}}, game.log
    assert _w2g3_open_pool(game) == {}


@pytest.mark.cr("106.6", "106.12b")
def test_infernal_darkness_workshop_mana_casts_an_artifact_and_not_a_creature(set_pool):
    """The behaviour the buckets are for: the black is spendable on an artifact
    and still not on anything else."""
    workshop = Permanent(card=set_pool("ATQ")["Mishra's Workshop"])
    game = _w2g3_board(workshop, Permanent(card=set_pool("ICE")["Infernal Darkness"]))
    game.enforce_mana_costs = True
    game.players[0].hand = [set_pool("LEA")["Scathe Zombies"], set_pool("ATQ")["Jalum Tome"]]
    game.tap_land_for_mana(0, "Mishra's Workshop", "C")

    zombies = game.cast_from_hand(0, "Scathe Zombies")
    assert not zombies.supported, "{2}{B} is not an artifact spell"
    tome = game.cast_from_hand(0, "Jalum Tome")
    assert tome.supported, tome.details
    resolve_stack(game)
    assert any(p.card.name == "Jalum Tome" for p in game.controlled_by(0))
    assert _w2g3_restricted(game) == {}


@pytest.mark.cr("106.6", "106.12b")
def test_ritual_of_subdual_leaves_the_workshops_colorless_restricted(set_pool):
    workshop = Permanent(card=set_pool("ATQ")["Mishra's Workshop"])
    game = _w2g3_board(workshop, Permanent(card=set_pool("ICE")["Ritual of Subdual"]))

    game.tap_land_for_mana(0, "Mishra's Workshop", "C")

    assert _w2g3_restricted(game) == {"artifact": {"C": 3}}
    assert _w2g3_open_pool(game) == {}


@pytest.mark.cr("106.6a", "106.12b")
def test_contamination_makes_the_workshop_one_restricted_black(set_pool):
    """"…instead of any other type **and amount**": three becomes one, and the
    one is still the Workshop's."""
    workshop = Permanent(card=set_pool("ATQ")["Mishra's Workshop"])
    game = _w2g3_board(workshop, Permanent(card=set_pool("USG")["Contamination"]))

    game.tap_land_for_mana(0, "Mishra's Workshop", "C")

    assert _w2g3_restricted(game) == {"artifact": {"B": 1}}, game.log
    assert _w2g3_open_pool(game) == {}


@pytest.mark.cr("106.6", "106.12b")
def test_deep_water_turns_the_workshops_mana_blue_and_keeps_it_for_artifacts(set_pool):
    workshop = Permanent(card=set_pool("ATQ")["Mishra's Workshop"])
    deep_water = Permanent(card=set_pool("DRK")["Deep Water"])
    game = _w2g3_board(workshop, deep_water)
    game.enforce_mana_costs = True
    game.players[0].mana_pool["U"] = 1
    assert game.activate_permanent_ability(0, "Deep Water").supported
    resolve_stack(game)

    game.tap_land_for_mana(0, "Mishra's Workshop", "C")

    assert _w2g3_restricted(game) == {"artifact": {"U": 3}}, game.log
    assert _w2g3_open_pool(game) == {}


@pytest.mark.cr("106.6a", "106.12b")
def test_harvest_mage_makes_the_workshop_one_restricted_mana_of_the_named_color(set_pool):
    mage = _nosick(Permanent(card=set_pool("NEM")["Harvest Mage"]))
    workshop = Permanent(card=set_pool("ATQ")["Mishra's Workshop"])
    game = _w2g3_board(mage, workshop)
    game.players[0].hand = [set_pool("LEA")["Forest"]]
    game.enforce_mana_costs = True
    game.players[0].mana_pool["G"] = 1
    assert game.activate_permanent_ability(0, "Harvest Mage", ability_index=0).supported
    resolve_stack(game)

    game.tap_land_for_mana(0, "Mishra's Workshop", "R", permanent_id=workshop.permanent_id)

    assert _w2g3_restricted(game) == {"artifact": {"R": 1}}, game.log
    assert _w2g3_open_pool(game) == {}


@pytest.mark.cr("106.6", "106.12b")
def test_naked_singularity_swaps_a_restricted_swamp_by_its_type():
    """"…Swamps produce {W}…" — by land type, so the land has to be a Swamp,
    which no restricted land in the pool is: an invented one stands in."""
    from engine.card_loader import load_catalog

    singularity = next(c for c in load_catalog() if c.name == "Naked Singularity")
    land = Permanent(card=_w2g3_restricted_plains("Restricted Swamp", "Swamp", "B"))
    game = _w2g3_board(land, Permanent(card=singularity))

    game.tap_land_for_mana(0, "Restricted Swamp", "B", permanent_id=land.permanent_id)

    assert _w2g3_restricted(game) == {"artifact": {"W": 2}}, game.log
    assert _w2g3_open_pool(game) == {}


@pytest.mark.cr("106.6", "106.12b")
def test_reality_twist_swaps_a_restricted_plains_by_its_type():
    from engine.card_loader import load_catalog

    twist = next(c for c in load_catalog() if c.name == "Reality Twist")
    land = Permanent(card=_w2g3_restricted_plains())
    game = _w2g3_board(land, Permanent(card=twist))

    game.tap_land_for_mana(0, "Restricted Plains", "W", permanent_id=land.permanent_id)

    assert _w2g3_restricted(game) == {"artifact": {"R": 2}}, game.log
    assert _w2g3_open_pool(game) == {}


def _w2g3_hall_game(set_pool, *lands):
    hall = Permanent(card=set_pool("MIR")["Hall of Gemstone"])
    game = _w2g3_board(hall, *lands, library=[set_pool("LEA")["Forest"]] * 20)
    game.start_turn(0)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    for symbol in game.players[0].mana_pool:
        game.players[0].mana_pool[symbol] = 0
    chosen = hall.metadata.get("chosen_color")
    assert chosen in ("W", "U", "B", "R", "G"), game.log
    return game, chosen


@pytest.mark.cr("106.1a", "106.1b", "106.12b")
def test_hall_of_gemstone_leaves_colorless_mana_colorless(set_pool):
    """"…produce mana of the chosen color instead of any other **color**."
    Ancient Tomb's {C}{C} has no colour to replace."""
    tomb = Permanent(card=set_pool("TMP")["Ancient Tomb"])
    workshop = Permanent(card=set_pool("ATQ")["Mishra's Workshop"])
    game, chosen = _w2g3_hall_game(set_pool, tomb, workshop)

    game.tap_land_for_mana(0, "Ancient Tomb", "C", permanent_id=tomb.permanent_id)
    game.tap_land_for_mana(0, "Mishra's Workshop", "C", permanent_id=workshop.permanent_id)

    assert _w2g3_open_pool(game) == {"C": 2}, game.log
    assert _w2g3_restricted(game) == {"artifact": {"C": 3}}, game.log
    # The planner and the client's prompt read the same answer.
    assert game._land_payment_colors(tomb) == ("C",)


@pytest.mark.cr("106.1a", "106.6", "106.12b")
def test_hall_of_gemstone_still_swaps_coloured_mana_restricted_or_not(set_pool):
    forest = Permanent(card=set_pool("LEA")["Forest"])
    restricted = Permanent(card=_w2g3_restricted_plains())
    game, chosen = _w2g3_hall_game(set_pool, forest, restricted)

    game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)
    game.tap_land_for_mana(0, "Restricted Plains", "W", permanent_id=restricted.permanent_id)

    assert _w2g3_open_pool(game) == {chosen: 1}, game.log
    assert _w2g3_restricted(game) == {"artifact": {chosen: 2}}, game.log
    assert game._land_payment_colors(forest) == (chosen,)
