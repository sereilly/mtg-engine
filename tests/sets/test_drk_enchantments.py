"""Per-card tests for The Dark's enchantments and Auras.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import Permanent


# --- G2: auras and land statics (The Dark) ---


def test_blood_moon_makes_every_nonbasic_land_a_mountain(set_pool):
    """"Nonbasic lands are Mountains." CR 613 layer 4 with CR 305.7's
    replacement: the dual land is no longer an Island, and it produces the new
    type's mana rather than its printed pair."""
    tundra = Permanent(card=set_pool("LEA")["Tundra"])
    swamp = Permanent(card=set_pool("LEA")["Swamp"])
    moon = Permanent(card=set_pool("DRK")["Blood Moon"])
    p1 = PlayerState(name="P1", battlefield=[moon])
    p2 = PlayerState(name="P2", battlefield=[tundra, swamp])
    game = Game(players=[p1, p2])
    game._refresh_dynamic_creatures()
    game._recalculate_lord_buffs()

    assert tundra.has_type("mountain"), game.log
    assert not tundra.has_type("island"), "CR 305.7: the old land types are gone"
    assert tundra.effective_produced_mana == ("R",)
    assert swamp.has_type("swamp"), "a basic land is not a nonbasic one"


def test_blood_moon_stops_applying_when_it_leaves(set_pool):
    """CR 611.3b: the derived channel is rebuilt from the board on every
    recompute, so removal is the absence of a contribution rather than a delta
    anyone has to subtract."""
    tundra = Permanent(card=set_pool("LEA")["Tundra"])
    moon = Permanent(card=set_pool("DRK")["Blood Moon"])
    p1 = PlayerState(name="P1", battlefield=[moon, tundra])
    game = Game(players=[p1, PlayerState(name="P2")])
    game._refresh_dynamic_creatures()
    game._recalculate_lord_buffs()
    assert tundra.has_type("mountain")

    game.remove_from_battlefield(moon)
    game._refresh_dynamic_creatures()
    game._recalculate_lord_buffs()

    assert tundra.has_type("island") and not tundra.has_type("mountain"), game.log


def _caves_on(game: Game, land: Permanent, aura_name: str, set_pool) -> Permanent:
    aura = Permanent(card=set_pool("DRK")[aura_name])
    game.players[0].battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, land)
    game._refresh_dynamic_creatures()
    game._recalculate_lord_buffs()
    return aura


def test_goblin_caves_buffs_goblins_only_while_it_enchants_a_basic_mountain(set_pool):
    """"As long as enchanted land is a basic Mountain, Goblin creatures get
    +0/+2." The condition is asked through ``subject_matches`` — the same
    reader every other noun phrase gets — so it is re-asked on every recompute
    and the anthem switches off with nothing to undo."""
    pool = set_pool("DRK")
    mountain = Permanent(card=set_pool("LEA")["Mountain"])
    goblin = Permanent(card=set_pool("LEA")["Goblin Balloon Brigade"])   # 1/1 Goblin
    bear = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[mountain, goblin, bear])
    game = Game(players=[p1, PlayerState(name="P2")])
    aura = _caves_on(game, mountain, "Goblin Caves", set_pool)

    assert (goblin.effective_power, goblin.effective_toughness) == (1, 3), game.log
    assert (bear.effective_power, bear.effective_toughness) == (2, 2), (
        "a Bear is not a Goblin"
    )

    game.remove_from_battlefield(aura)
    game._refresh_dynamic_creatures()
    game._recalculate_lord_buffs()
    assert (goblin.effective_power, goblin.effective_toughness) == (1, 1)


def test_goblin_caves_on_a_nonbasic_land_gives_nothing(set_pool):
    """"a **basic** Mountain" is a supertype (CR 205.4a), and dropping it would
    make every dual land in the pool switch the anthem on."""
    tundra = Permanent(card=set_pool("LEA")["Tundra"])
    goblin = Permanent(card=set_pool("LEA")["Goblin Balloon Brigade"])
    p1 = PlayerState(name="P1", battlefield=[tundra, goblin])
    game = Game(players=[p1, PlayerState(name="P2")])
    _caves_on(game, tundra, "Goblin Caves", set_pool)

    assert (goblin.effective_power, goblin.effective_toughness) == (1, 1), game.log


def test_blood_moon_does_not_make_a_nonbasic_land_a_basic_mountain(set_pool):
    """The interaction the two cards' printed words decide. Blood Moon changes
    the land's *subtypes* (CR 305.7); it says nothing about the basic
    supertype, so Goblin Caves' "basic Mountain" test still fails — and the
    anthem must ask through the layers to get that right rather than off the
    printed line."""
    tundra = Permanent(card=set_pool("LEA")["Tundra"])
    goblin = Permanent(card=set_pool("LEA")["Goblin Balloon Brigade"])
    moon = Permanent(card=set_pool("DRK")["Blood Moon"])
    p1 = PlayerState(name="P1", battlefield=[tundra, goblin, moon])
    game = Game(players=[p1, PlayerState(name="P2")])
    _caves_on(game, tundra, "Goblin Caves", set_pool)

    assert tundra.has_type("mountain"), "Blood Moon still applies"
    assert (goblin.effective_power, goblin.effective_toughness) == (1, 1), game.log


def test_goblin_shrine_burns_every_goblin_when_it_leaves(set_pool):
    """"When this Aura leaves the battlefield, it deals 1 damage to each Goblin
    creature." CR 603.6c, announced from the one transition off the
    battlefield; the noun phrase is the filter the sweep tests, so the Bear
    beside the Goblins is untouched."""
    pool = set_pool("DRK")
    mountain = Permanent(card=set_pool("LEA")["Mountain"])
    mine = Permanent(card=set_pool("LEA")["Goblin Balloon Brigade"])
    theirs = Permanent(card=set_pool("LEA")["Goblin Balloon Brigade"])
    bear = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[mountain, mine])
    p2 = PlayerState(name="P2", battlefield=[theirs, bear])
    game = Game(players=[p1, p2])
    aura = _caves_on(game, mountain, "Goblin Shrine", set_pool)
    assert (mine.effective_power, mine.effective_toughness) == (2, 1), (
        "+1/+0 while it enchants a basic Mountain"
    )

    game.remove_from_battlefield(aura)
    game.resolve_top_of_stack()

    assert mine.damage_marked == 1 and theirs.damage_marked == 1, game.log
    assert bear.damage_marked == 0, "a Bear is not a Goblin"


def test_tangle_kelp_taps_on_entry_and_holds_a_creature_that_attacked(set_pool):
    """"Enchanted creature doesn't untap during its controller's untap step if
    it attacked during its controller's last turn." Goblin Rock Sled's sentence
    about a different subject, answered by the same attack record."""
    pool = set_pool("DRK")
    bear = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[bear])
    p2 = PlayerState(name="P2", hand=[pool["Tangle Kelp"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg

    game.cast_from_hand(1, "Tangle Kelp", target_player_index=0, target_permanent_index=0)
    game.resolve_top_of_stack()
    assert bear.tapped

    game.start_next_turn()   # P2
    game.start_next_turn()   # P1: the Bear attacked during P1's last turn
    assert bear.tapped, game.log

    game.start_next_turn()   # P2
    game.start_next_turn()   # P1: it sat out, so the Kelp lets it go
    assert not bear.tapped, game.log
