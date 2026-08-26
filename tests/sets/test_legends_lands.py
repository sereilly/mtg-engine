"""Per-card tests for Legends' lands.

Five of them are one sentence with one word changed —
``<colour> legendary creatures you control have "bands with other legendary
creatures."`` — which is exactly why the tests below check the *narrowing*
rather than the sentence: a colour dropped from the filter grants the band to
every legend on the board, and nothing about the card would look wrong.

Round 24 stopped these five reporting supported while doing nothing (a land
whose static line no reader claimed). This round is the other half: the line is
carried out, and the ability it grants changes what combat does.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle

#: The cycle, and the colour each one names.
BANDING_LANDS = {
    "Adventurers' Guildhouse": "G",
    "Cathedral of Serra": "W",
    "Mountain Stronghold": "R",
    "Seafarer's Quay": "U",
    "Unholy Citadel": "B",
}

_BAND = "bands with other legendary creatures"


def _legend(name: str, colors: tuple[str, ...]) -> CardDefinition:
    """A vanilla legendary creature in the given colours."""
    type_line = "Legendary Creature - Test"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=colors, color_identity=colors, keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def _nonlegend(name: str, colors: tuple[str, ...]) -> CardDefinition:
    type_line = "Creature - Test"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=colors, color_identity=colors, keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def _board(land: Permanent, creatures: list[Permanent]) -> tuple[Game, PlayerState]:
    p1 = PlayerState(name="P1", battlefield=[land, *creatures])
    game = Game(players=[p1, PlayerState(name="P2")])
    game._recalculate_lord_buffs()
    return game, p1


def _to_declare_attackers(game: Game) -> None:
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers


@pytest.mark.parametrize("land_name,color", sorted(BANDING_LANDS.items()))
def test_the_banding_land_is_supported_and_carries_its_static(
    set_pool, land_name, color
):
    """Supported *and* carrying an instruction. Round 24's gate asks the first
    question; a land that passes it with no instruction behind the line is the
    hollow card the gate exists to catch."""
    program = compile_card_oracle(set_pool("LEG")[land_name])

    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == ["lord_buff"]
    assert program.instructions[0].payload["colors"] == [color]
    assert program.instructions[0].payload["supertypes"] == ["legendary"]
    assert program.instructions[0].payload["keywords"] == [_BAND]


@pytest.mark.parametrize("land_name,color", sorted(BANDING_LANDS.items()))
def test_the_band_reaches_only_that_colour_of_legend(set_pool, land_name, color):
    """Three ways to be outside the sentence, all on one board: the wrong
    colour, not legendary, and both."""
    land = Permanent(card=set_pool("LEG")[land_name])
    right = Permanent(card=_legend("Right", (color,)))
    wrong_colour = Permanent(card=_legend("Wrong Colour", ("C",)))
    not_legendary = Permanent(card=_nonlegend("Commoner", (color,)))
    _board(land, [right, wrong_colour, not_legendary])

    assert right.has_keyword(_BAND)
    assert not wrong_colour.has_keyword(_BAND)
    assert not not_legendary.has_keyword(_BAND)


def test_two_legends_band_under_the_guildhouse(set_pool):
    """The band the land exists to enable: neither creature has banding."""
    land = Permanent(card=set_pool("LEG")["Adventurers' Guildhouse"])
    a = Permanent(card=_legend("A", ("G",)))
    b = Permanent(card=_legend("B", ("G",)))
    game, _ = _board(land, [a, b])
    _to_declare_attackers(game)

    ok, msg = game.declare_attackers(0, [1, 2], bands=[[1, 2]])
    assert ok, msg
    assert game.combat_bands == [[1, 2]]


def test_a_nonlegendary_creature_cannot_join_the_legendary_band(set_pool):
    """CR 702.22c's second form admits "any number of **other [quality]**
    creatures" and no others — the plain form's one-non-bander allowance is a
    different rule."""
    land = Permanent(card=set_pool("LEG")["Adventurers' Guildhouse"])
    a = Permanent(card=_legend("A", ("G",)))
    b = Permanent(card=_legend("B", ("G",)))
    bear = Permanent(card=_nonlegend("Bear", ("G",)))
    game, _ = _board(land, [a, b, bear])
    _to_declare_attackers(game)

    ok, _ = game.declare_attackers(0, [1, 2, 3], bands=[[1, 2, 3]])
    assert not ok


def test_without_the_land_two_legends_cannot_band(set_pool):
    """The band comes from the land, not from being legendary."""
    a = Permanent(card=_legend("A", ("G",)))
    b = Permanent(card=_legend("B", ("G",)))
    p1 = PlayerState(name="P1", battlefield=[a, b])
    game = Game(players=[p1, PlayerState(name="P2")])
    game._recalculate_lord_buffs()
    _to_declare_attackers(game)

    ok, _ = game.declare_attackers(0, [0, 1], bands=[[0, 1]])
    assert not ok


def test_the_grant_ends_when_the_land_leaves(set_pool):
    """A static ability is re-derived every recompute (CR 611.3a), so removal is
    the absence of a contribution rather than an undo anyone has to remember."""
    land = Permanent(card=set_pool("LEG")["Cathedral of Serra"])
    legend = Permanent(card=_legend("Legend", ("W",)))
    game, p1 = _board(land, [legend])
    assert legend.has_keyword(_BAND)

    game.remove_from_battlefield(land)
    game._recalculate_lord_buffs()

    assert not legend.has_keyword(_BAND)


def test_two_lands_of_different_colours_each_grant_their_own(set_pool):
    """Nothing here is per-card: two of the cycle on one board reach two
    different sets."""
    guildhouse = Permanent(card=set_pool("LEG")["Adventurers' Guildhouse"])
    citadel = Permanent(card=set_pool("LEG")["Unholy Citadel"])
    green = Permanent(card=_legend("Green Legend", ("G",)))
    black = Permanent(card=_legend("Black Legend", ("B",)))
    red = Permanent(card=_legend("Red Legend", ("R",)))
    p1 = PlayerState(name="P1", battlefield=[guildhouse, citadel, green, black, red])
    game = Game(players=[p1, PlayerState(name="P2")])
    game._recalculate_lord_buffs()

    assert green.has_keyword(_BAND)
    assert black.has_keyword(_BAND)
    assert not red.has_keyword(_BAND)


def test_the_band_is_not_plain_banding(set_pool):
    """CR 702.22c's parenthetical: a creature with "bands with other" is a
    creature *without* banding for the plain form's count. Conflating the two
    would let one granted legend drag any creature into a band."""
    land = Permanent(card=set_pool("LEG")["Mountain Stronghold"])
    legend = Permanent(card=_legend("Legend", ("R",)))
    bear = Permanent(card=_nonlegend("Bear", ("R",)))
    game, _ = _board(land, [legend, bear])
    _to_declare_attackers(game)

    assert not game._creature_has_banding(legend)
    ok, _ = game.declare_attackers(0, [1, 2], bands=[[1, 2]])
    assert not ok


# ---------------------------------------------------------------------------
# Tolaria — the removal, on a land that also taps for mana
# ---------------------------------------------------------------------------


def test_tolaria_taps_for_blue_and_carries_its_removal(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Tolaria"])

    assert program.supported, program.reason
    kinds = [a.instruction.kind for a in program.activated_abilities]
    assert kinds == ["add_mana_from_text", "remove_target_keyword_until_eot"]
    payload = program.activated_abilities[1].instruction.payload
    assert payload["keywords"] == ("banding", "bands with other")


def test_tolaria_strips_a_granted_band_during_upkeep(set_pool):
    """Both halves of the printed line, on a creature that has both."""
    from engine.keywords import grant_keyword

    guildhouse = Permanent(card=set_pool("LEG")["Adventurers' Guildhouse"])
    tolaria = Permanent(card=set_pool("LEG")["Tolaria"])
    legend = Permanent(card=_legend("Legend", ("G",)))
    p1 = PlayerState(name="P1", battlefield=[guildhouse, legend])
    p2 = PlayerState(name="P2", battlefield=[tolaria])
    game = Game(players=[p1, p2])
    game._recalculate_lord_buffs()
    grant_keyword(legend, "banding")
    assert legend.has_keyword(_BAND) and legend.has_keyword("banding")

    game.start_turn(0)
    game._set_phase_and_step("beginning", "upkeep")  # the printed clause's step
    # ``ability_index=1`` because Tolaria prints two: the mana ability and this
    # one. Naming the card alone would activate the first and pass.
    result = game.activate_permanent_ability(
        1, "Tolaria", target_player_index=0, target_permanent_index=1,
        ability_index=1,
    )
    game._settle()

    assert result.supported, result.reason
    assert not legend.has_keyword(_BAND)
    assert not legend.has_keyword("banding")


def test_tolaria_is_refused_outside_an_upkeep_step(set_pool):
    """"Activate only during any upkeep step." An unenforced restriction is not
    a dead ability — it is one that works more often than the card allows."""
    tolaria = Permanent(card=set_pool("LEG")["Tolaria"])
    legend = Permanent(card=_legend("Legend", ("G",)))
    p1 = PlayerState(name="P1", battlefield=[legend])
    p2 = PlayerState(name="P2", battlefield=[tolaria])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._set_phase_and_step("precombat_main", "precombat_main")

    result = game.activate_permanent_ability(
        1, "Tolaria", target_player_index=0, target_permanent_index=0,
        ability_index=1,
    )

    assert not result.supported
