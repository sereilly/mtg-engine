"""CR 613 layers 4 and 5 as Darksteel rewrites them wholesale.

Mycosynth Lattice ("All permanents are artifacts in addition to their other
types. All cards that aren't on the battlefield, spells, and permanents are
colorless. Players may spend mana as though it were mana of any color.") and
Neurok Transmuter ("…target artifact creature becomes blue and isn't an
artifact"). Each test names the rule it holds and drives a real board: entry
through the entry seam, abilities through the activation entry point, the
state read after `settle`.
"""

import pytest

from engine import Game, PlayerState
from engine.layer_bridge import displayed_type_line
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


@pytest.mark.cr("613.8a", "613.8b")
@pytest.mark.parametrize("lattice_first", [True, False])
def test_march_waits_behind_the_lattice_whichever_is_older(set_pool, lattice_first):
    """March of the Machines' scope is "noncreature artifact", and applying the
    Lattice changes what that set holds, so March depends on it (CR 613.8a)
    and waits until the Lattice has applied (CR 613.8b) — in either order of
    arrival. Every land becomes a 0/0 artifact creature and dies; the
    Lattice and March themselves become artifact creatures sized by mana
    value."""
    lea, mrd = set_pool("LEA"), set_pool("MRD")
    game = _table(set_pool)
    forest = _put(game, lea["Forest"])
    island = _put(game, lea["Island"], seat=1)
    bears = _put(game, lea["Grizzly Bears"])
    lattice_card = set_pool("DST")["Mycosynth Lattice"]
    march_card = mrd["March of the Machines"]
    if lattice_first:
        lattice = _put(game, lattice_card)
        march = _put(game, march_card)
    else:
        march = _put(game, march_card)
        lattice = _put(game, lattice_card)
    settle(game)
    assert (lattice.timestamp < march.timestamp) is lattice_first

    assert not game.is_on_battlefield(forest)
    assert not game.is_on_battlefield(island)
    assert forest.card in game.players[0].graveyard
    assert island.card in game.players[1].graveyard
    assert lattice.is_creature and (lattice.effective_power, lattice.effective_toughness) == (6, 6)
    assert march.is_creature and (march.effective_power, march.effective_toughness) == (4, 4)
    # A creature already is one: March passes it by, and it keeps its size.
    assert bears.has_type("artifact") and (bears.effective_power, bears.effective_toughness) == (2, 2)


@pytest.mark.cr("303.4d", "704.5m")
def test_an_aura_the_lattice_and_march_animate_falls_off(set_pool):
    """The Lattice's 2009-10-01 ruling: an Aura the Lattice makes an artifact
    and March of the Machines then makes a creature can't enchant anything
    (CR 303.4d), and is put into its owner's graveyard (CR 704.5m)."""
    lea, pacifism = set_pool("LEA"), set_pool("6ED")["Pacifism"]
    game = _table(set_pool)
    game.players[0].hand.append(pacifism)
    bears = _put(game, lea["Grizzly Bears"], seat=1)
    assert game.cast_from_hand(
        0, "Pacifism", target_permanent_ids=[bears.permanent_id],
    ).supported
    settle(game)
    assert [p.card.name for p in game.all_permanents()].count("Pacifism") == 1

    _put(game, set_pool("DST")["Mycosynth Lattice"])
    _put(game, set_pool("MRD")["March of the Machines"])
    settle(game)
    assert "Pacifism" not in [p.card.name for p in game.all_permanents()]
    assert pacifism in game.players[0].graveyard


@pytest.mark.cr("613.7", "613.7a", "613.7b")
def test_neurok_after_the_lattice_wins_until_end_of_turn(set_pool):
    """Inside layer 4 the later effect applies last (CR 613.7): the Lattice's
    addition has its own timestamp (CR 613.7a) and the Transmuter's removal
    the moment it resolved (CR 613.7b), so the creature is not an artifact
    until the removal ends — and an artifact again afterwards."""
    lea = set_pool("LEA")
    game = _table(set_pool)
    _put(game, set_pool("DST")["Mycosynth Lattice"])
    _put(game, set_pool("DST")["Neurok Transmuter"])
    bears = _put(game, lea["Grizzly Bears"], seat=1)
    settle(game)
    assert bears.has_type("artifact")

    assert game.activate_permanent_ability(
        0, "Neurok Transmuter", ability_index=1,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    settle(game)
    assert not bears.has_type("artifact") and bears.is_creature
    # Blue by the later layer-5 effect, over the Lattice's colourless.
    assert game._effective_colors(bears) == {"U"}

    game.resolve_cleanup_step(0)
    assert bears.has_type("artifact")
    assert game._effective_colors(bears) == set()


@pytest.mark.cr("205.1a")
def test_losing_the_artifact_type_takes_the_artifact_subtypes(set_pool):
    """CR 205.1a: "If an object's card type is removed, the subtypes
    correlated with that card type ... are also removed". A Bonesplitter
    March of the Machines has animated, stripped of the artifact type, is no
    Equipment either — and, March no longer reaching it, has no type at all
    (the Transmuter's 2004-12-01 ruling)."""
    mrd = set_pool("MRD")
    game = _table(set_pool)
    _put(game, set_pool("DST")["Neurok Transmuter"])
    _put(game, mrd["March of the Machines"])
    bone = _put(game, mrd["Bonesplitter"])
    settle(game)
    assert bone.has_type("equipment") and bone.is_creature

    assert game.activate_permanent_ability(
        0, "Neurok Transmuter", ability_index=1,
        target_permanent_ids=[bone.permanent_id],
    ).supported
    settle(game)
    assert not bone.has_type("equipment") and not bone.has_type("artifact")
    assert displayed_type_line(bone) == ""


@pytest.mark.cr("105.2c", "613.1e")
def test_the_lattice_sets_every_object_colorless_not_a_sixth_colour(set_pool):
    """CR 105.2c: colourless is no colour, so under the Lattice no two objects
    share one — a "white creature" scope finds none, and a white card in a
    hand answers with no colour at all (CR 613.1e reaches it: a card is an
    object, CR 109.1)."""
    from engine.object_colors import card_colors, share_a_color

    lea = set_pool("LEA")
    game = _table(set_pool)
    angel = _put(game, lea["Serra Angel"])
    knight = _put(game, lea["White Knight"], seat=1)
    _put(game, set_pool("DST")["Mycosynth Lattice"])
    settle(game)
    assert not share_a_color(game._effective_colors(angel), game._effective_colors(knight))
    assert card_colors(game, lea["Swords to Plowshares"], 0) == ()


@pytest.mark.cr("609.4b")
def test_the_lattice_changes_how_a_cost_is_paid_not_the_cost(set_pool):
    """CR 609.4b: spending mana "as though it were mana of any color" changes
    how a cost may be paid and not the cost: {C}{C} pays Grizzly Bears'
    {1}{G}, and a single {C} still cannot pay two mana."""
    lea = set_pool("LEA")
    game = _table(set_pool)
    game.enforce_mana_costs = True
    _put(game, set_pool("DST")["Mycosynth Lattice"], seat=1)
    game.players[0].hand.extend([lea["Grizzly Bears"], lea["Grizzly Bears"]])
    settle(game)
    game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 1}
    assert not game.cast_from_hand(0, "Grizzly Bears").supported
    game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 2}
    assert game.cast_from_hand(0, "Grizzly Bears").supported
    settle(game)
    assert game.players[0].mana_pool.get("C", 0) == 0
