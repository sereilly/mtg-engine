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


# ---------------------------------------------------------------------------
# The Tabernacle at Pendrell Vale (round 26) - a board-wide static that grants a
# triggered ability to every creature, whoever controls it
# ---------------------------------------------------------------------------


def _tabernacle_board(set_pool, mana=None):
    """The Tabernacle plus one creature on each side."""
    tabernacle = Permanent(card=set_pool("LEG")["The Tabernacle at Pendrell Vale"])
    mine = Permanent(card=_legend("Mine", ("G",)))
    theirs = Permanent(card=_legend("Theirs", ("G",)))
    p1 = PlayerState(
        name="P1", battlefield=[tabernacle, mine],
        mana_pool=dict(mana) if mana else {},
    )
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game._refresh_dynamic_creatures()
    return game, p1, p2, mine, theirs


def test_the_tabernacle_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["The Tabernacle at Pendrell Vale"])
    assert program.supported, program.reason


def test_the_ability_is_appended_to_every_creature_on_both_sides(set_pool):
    """The grant reaches the effective card, so the compiler produces the
    trigger like a printed one - which is what makes the upkeep step find it
    without knowing a land granted it."""
    _game, _p1, _p2, mine, theirs = _tabernacle_board(set_pool)

    for creature in (mine, theirs):
        (trigger,) = compile_card_oracle(creature.effective_card).triggered_abilities
        assert trigger.condition.kind == "upkeep_self"
        assert trigger.instruction.kind == "upkeep_pay_or_destroy_self"
        assert trigger.instruction.payload["mana"]["generic"] == 1


@pytest.mark.cr("613.1f")
def test_an_unpaid_creature_is_destroyed_on_its_own_controllers_upkeep(set_pool):
    """"At beginning of **your** upkeep" is the creature's controller's upkeep,
    so P2's creature is untouched while P1 is the active player."""
    game, p1, _p2, mine, theirs = _tabernacle_board(set_pool)

    game.resolve_upkeep(0)
    game._settle()

    assert not game.is_on_battlefield(mine)
    assert [card.name for card in p1.graveyard] == ["Mine"]
    assert game.is_on_battlefield(theirs)


@pytest.mark.cr("613.1f")
def test_a_paid_creature_survives_and_the_mana_is_spent(set_pool):
    game, p1, _p2, mine, _theirs = _tabernacle_board(
        set_pool, {"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 0}
    )

    game.resolve_upkeep(0)
    game._settle()

    assert game.is_on_battlefield(mine)
    assert sum(p1.mana_pool.values()) == 0


@pytest.mark.cr("611.3")
def test_the_grant_ends_when_the_tabernacle_leaves(set_pool):
    game, p1, _p2, mine, _theirs = _tabernacle_board(set_pool)
    game.remove_from_battlefield(p1.battlefield[0])
    game._refresh_dynamic_creatures()

    assert not compile_card_oracle(mine.effective_card).triggered_abilities

    game.resolve_upkeep(0)
    game._settle()

    assert game.is_on_battlefield(mine)


# ---------------------------------------------------------------------------
# Phase 4 promotion — two lands whose second ability compiled to nothing.
#
# Both reported *supported* on their mana ability, so the card looked complete
# while the ability anyone actually taps it for logged "ability not
# implemented". Ability index 1 throughout: index 0 is the mana line.
# ---------------------------------------------------------------------------


def _p4_land_game(land, *others, opponent_battlefield=()):
    for permanent in (land, *others, *opponent_battlefield):
        permanent.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=[land, *others])
    p2 = PlayerState(name="P2", battlefield=list(opponent_battlefield))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def _p4_body(name: str, power: int, toughness: int, text: str = "", keywords=()):
    type_line = "Creature - Test"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=text,
        colors=(), color_identity=(), keywords=tuple(keywords), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def test_pendelhaven_pumps_a_one_one(set_pool):
    """"{T}: Target 1/1 creature gets +1/+2 until end of turn."

    A printed power/toughness pair standing as an adjective (CR 208.1) — the
    lexer gives it its own token kind, so the noun phrase's adjective loop
    stopped dead on it and the whole line refused with "expected a subject".
    """
    pendelhaven = Permanent(card=set_pool("LEG")["Pendelhaven"])
    onesie = Permanent(card=_p4_body("Onesie", 1, 1))
    game, p1, _ = _p4_land_game(pendelhaven, onesie)

    result = game.activate_permanent_ability(
        0, "Pendelhaven", target_player_index=0, target_permanent_index=1,
        ability_index=1,
    )
    game._settle()

    assert result.supported
    assert (onesie.effective_power, onesie.effective_toughness) == (2, 3)


def test_pendelhaven_will_not_pump_anything_bigger(set_pool):
    """"1/1" is a *restriction*, and one dropped on the way to the dispatcher
    is a land that pumps any creature on the board. Both halves are checked:
    the filter carries a power and a toughness comparison, and emitting one
    without the other would let a 1/3 through."""
    pendelhaven = Permanent(card=set_pool("LEG")["Pendelhaven"])
    twosie = Permanent(card=_p4_body("Twosie", 2, 2))
    game, p1, _ = _p4_land_game(pendelhaven, twosie)

    result = game.activate_permanent_ability(
        0, "Pendelhaven", target_player_index=0, target_permanent_index=1,
        ability_index=1,
    )

    assert not result.supported, "a 2/2 is not a legal target for this ability"
    assert (twosie.effective_power, twosie.effective_toughness) == (2, 2)


def test_hammerheim_strips_every_landwalk(set_pool):
    """"{T}: Target creature loses all landwalk abilities until end of turn."

    A keyword *family* (CR 702.14a), so the phrase names every member — and the
    member list is derived from the keyword registry rather than spelled beside
    it, so a landwalk the engine learns to grant is one this can take away.
    """
    hammerheim = Permanent(card=set_pool("LEG")["Hammerheim"])
    walker = Permanent(
        card=_p4_body("Walker", 2, 2, text="Islandwalk", keywords=("Islandwalk",))
    )
    game, p1, p2 = _p4_land_game(hammerheim, opponent_battlefield=[walker])
    assert game._has_keyword(walker, "islandwalk")

    result = game.activate_permanent_ability(
        0, "Hammerheim", target_player_index=1, target_permanent_index=0,
        ability_index=1,
    )
    game._settle()

    assert result.supported
    assert not game._has_keyword(walker, "islandwalk")


def test_hammerheim_leaves_other_evasion_alone(set_pool):
    """"All landwalk abilities" is a family, not "all abilities". A member list
    that reached past the family would strip flying too, which is a strictly
    better card than the one printed."""
    hammerheim = Permanent(card=set_pool("LEG")["Hammerheim"])
    flier = Permanent(
        card=_p4_body("Flier", 2, 2, text="Flying\nForestwalk",
                      keywords=("Flying", "Forestwalk"))
    )
    game, p1, p2 = _p4_land_game(hammerheim, opponent_battlefield=[flier])

    result = game.activate_permanent_ability(
        0, "Hammerheim", target_player_index=1, target_permanent_index=0,
        ability_index=1,
    )
    game._settle()

    assert result.supported
    assert not game._has_keyword(flier, "forestwalk")
    assert game._has_keyword(flier, "flying")
