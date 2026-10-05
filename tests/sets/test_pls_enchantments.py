"""Planeshift enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: colour ---
# Being a colour (CR 613 layer 5) and what an Aura says about the colour of the
# creature it is on. Colour is read through the layers everywhere below
# (`Game._effective_colors`), never off the printed card.
import pytest as _w1g6_pytest

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_card(set_pool, name):
    """*name* from Planeshift, else Invasion, else Alpha."""
    for code in ("PLS", "INV", "LEA"):
        if name in set_pool(code):
            return set_pool(code)[name]
    raise KeyError(f"not in PLS, INV or LEA: {name}")  # _w1g6_card (enchantments)


def _w1g6_table(set_pool, mine=(), theirs=(), *, hand=(), mana=False, interactive=(0,)):
    """Seat 0 holds *mine* (and *hand* in hand), seat 1 *theirs*, nothing
    summoning-sick, on seat 0's turn. Returns the game and both boards."""
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    w1g6_game.enforce_mana_costs = mana
    w1g6_game.interactive_seats = set(interactive)
    w1g6_game.active_player_index = 0
    w1g6_tables = []
    for seat, names in ((0, mine), (1, theirs)):
        placed = []
        for name in names:
            perm = _W1G6Permanent(card=_w1g6_card(set_pool, name))
            w1g6_game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            placed.append(perm)
        w1g6_tables.append(placed)
    w1g6_game.players[0].hand.extend(_w1g6_card(set_pool, name) for name in hand)
    return w1g6_game, w1g6_tables[0], w1g6_tables[1]  # _w1g6_table (enchantments)


def _w1g6_colors(game, perm):
    return sorted(game._effective_colors(perm))  # _w1g6_colors (enchantments)


def _w1g6_recolor(game, perm, colour):
    """Turn *perm* *colour* until end of turn, through layer 5's turn-long
    channel — what "becomes black until end of turn" writes."""
    perm.metadata["color_override_until_eot"] = colour
    game._recompute_continuous_effects()
    assert _w1g6_colors(game, perm) == [colour]
    return perm  # _w1g6_recolor


def _w1g6_enchant(game, set_pool, name, host, *, seat=0):
    """*seat* casts the Aura *name* on *host* through the real cast path and
    the stack is drained. Returns the Aura permanent."""
    game.players[seat].hand.append(_w1g6_card(set_pool, name))
    cast = game.queue_from_hand(seat, name, target_permanent_ids=[host.permanent_id])
    assert cast.supported, cast.details
    _w1g6_resolve_stack(game)
    return next(
        perm for perm in game.controlled_by(seat) if perm.card.name == name
    )  # _w1g6_enchant


def _w1g6_cast_sky(set_pool, mine, theirs, colour, *, interactive=(0,)):
    """Seat 0 casts Shifting Sky and (when asked) answers *colour*."""
    game, my_side, their_side = _w1g6_table(
        set_pool, mine, theirs, hand=["Shifting Sky"], interactive=interactive,
    )
    assert game.queue_from_hand(0, "Shifting Sky").supported
    game.resolve_top_of_stack()
    sky = next(p for p in game.controlled_by(0) if p.card.name == "Shifting Sky")
    if interactive:
        assert [(c.kind, c.player_index) for c in game.pending_choices] == [("enter_choice", 0)]
        assert game.confirm_enter_choice(0, mana_color=colour)
    return game, sky, my_side, their_side  # _w1g6_cast_sky


def test_w1g6_shifting_sky_makes_every_nonland_permanent_the_chosen_colour(set_pool):
    """"As this enchantment enters, choose a color. / All nonland permanents
    are the chosen color." Black is answered: every player's creatures, the
    colourless artifact, the white enchantment and the Sky itself are black —
    black *instead of* what they were (CR 105.3) — and no land is. When the Sky
    leaves, each is its printed colour again with nothing to undo."""
    assert _w1g6_compile(_w1g6_card(set_pool, "Shifting Sky")).supported
    game, sky, mine, theirs = _w1g6_cast_sky(
        set_pool, ["Island", "Grizzly Bears", "Howling Mine"],
        ["Hill Giant", "Mountain", "Crusade", "Savannah Lions"], "B",
    )
    island, bears, mine_artifact = mine
    giant, mountain, crusade, lions = theirs

    for perm in (bears, mine_artifact, sky, giant, crusade, lions):
        assert _w1g6_colors(game, perm) == ["B"], perm.card.name
    for land in (island, mountain):
        assert _w1g6_colors(game, land) == [], land.card.name

    game.remove_from_battlefield(sky)
    game._recompute_continuous_effects()
    assert [_w1g6_colors(game, p) for p in (bears, mine_artifact, giant, crusade, lions)] == [
        ["G"], [], ["R"], ["W"], ["W"],
    ]


def test_w1g6_shifting_skys_colour_is_what_every_other_card_reads(set_pool):
    """The colour is layer 5's, so everything that asks about colour sees it:
    under a black Sky Crusade's "white creatures get +1/+1" stops applying to
    the Lions and Terror ("nonblack") has no creature it may name; under a
    white one the red Giant is a white creature Crusade pumps."""
    game, _sky, _mine, theirs = _w1g6_cast_sky(
        set_pool, [], ["Hill Giant", "Crusade", "Savannah Lions"], "B",
    )
    giant, _crusade, lions = theirs
    assert (lions.effective_power, lions.effective_toughness) == (2, 1)
    game.players[0].hand.append(_w1g6_card(set_pool, "Terror"))
    refused = game.queue_from_hand(0, "Terror", target_permanent_ids=[giant.permanent_id])
    assert not refused.supported, refused.details

    game, _sky, _mine, theirs = _w1g6_cast_sky(
        set_pool, [], ["Hill Giant", "Crusade", "Savannah Lions"], "W",
    )
    giant, _crusade, lions = theirs
    assert (lions.effective_power, lions.effective_toughness) == (3, 2)
    assert (giant.effective_power, giant.effective_toughness) == (4, 4)


def test_w1g6_shifting_sky_follows_its_record_and_a_headless_seat_is_never_asked(set_pool):
    """Derived from the Sky's entry record on every recompute: a seat nobody
    asks takes the default with no prompt left owing and the board is that
    colour at once; a later answer recolours the board; and a permanent that
    enters afterwards is the chosen colour as soon as it is there."""
    game, sky, mine, theirs = _w1g6_cast_sky(
        set_pool, ["Grizzly Bears"], ["Hill Giant"], None, interactive=(),
    )
    assert game.pending_choices == []
    default = sky.metadata["chosen_color"]
    assert default in ("W", "U", "B", "R", "G")
    assert _w1g6_colors(game, mine[0]) == [default] == _w1g6_colors(game, theirs[0])

    sky.metadata["chosen_color"] = "U"
    game._recompute_continuous_effects()
    assert _w1g6_colors(game, mine[0]) == ["U"] == _w1g6_colors(game, theirs[0])

    late = _W1G6Permanent(card=_w1g6_card(set_pool, "Savannah Lions"))
    game._put_permanent_onto_battlefield(1, late, None)
    assert _w1g6_colors(game, late) == ["U"]


def _w1g6_shape(game, perm):
    """(colours, is a Goblin, is a Zombie, power, toughness) through the
    layers."""
    return (
        _w1g6_colors(game, perm), perm.has_type("goblin"), perm.has_type("zombie"),
        perm.effective_power, perm.effective_toughness,
    )  # _w1g6_shape


def test_w1g6_dralnus_crusade_makes_every_goblin_a_black_zombie_as_well(set_pool):
    """"All Goblins get +1/+1. / All Goblins are black and are Zombies in
    addition to their other creature types." Both players' Goblins are black —
    instead of red (CR 105.3, layer 5) — and Goblin **Zombies** (CR 205.1b,
    layer 4: the type is added, so they are still Goblins), and 2/2. The Bears
    and the Giant are neither, and when the Crusade leaves every Goblin is a
    red 1/1 Goblin again."""
    assert _w1g6_compile(_w1g6_card(set_pool, "Dralnu's Crusade")).supported
    game, mine, theirs = _w1g6_table(
        set_pool, ["Mons's Goblin Raiders", "Grizzly Bears"],
        ["Goblin Balloon Brigade", "Hill Giant"], hand=["Dralnu's Crusade"],
    )
    raiders, bears = mine
    brigade, giant = theirs
    assert _w1g6_shape(game, raiders) == (["R"], True, False, 1, 1)

    assert game.queue_from_hand(0, "Dralnu's Crusade").supported
    _w1g6_resolve_stack(game)
    crusade = next(p for p in game.controlled_by(0) if p.card.name == "Dralnu's Crusade")

    assert _w1g6_shape(game, raiders) == (["B"], True, True, 2, 2)
    assert _w1g6_shape(game, brigade) == (["B"], True, True, 2, 2)
    assert _w1g6_shape(game, bears) == (["G"], False, False, 2, 2)
    assert _w1g6_shape(game, giant) == (["R"], False, False, 3, 3)
    assert _w1g6_colors(game, crusade) == ["B", "R"], "the enchantment is no Goblin"

    game.remove_from_battlefield(crusade)
    game._recompute_continuous_effects()
    assert _w1g6_shape(game, raiders) == (["R"], True, False, 1, 1)
    assert _w1g6_shape(game, brigade) == (["R"], True, False, 1, 1)


def test_w1g6_dralnus_crusade_goblins_are_zombies_to_lord_of_the_undead_and_black_to_terror(set_pool):
    """What the two layers buy. "Other Zombie creatures get +1/+1" (Lord of the
    Undead) counts a Crusade Goblin: 1/1, +1/+1 from the Crusade, +1/+1 from
    the Lord. And the Goblin is a black creature, so a Terror ("nonblack") may
    not name it — the same Terror could a moment before the Crusade resolved."""
    game, mine, theirs = _w1g6_table(
        set_pool, ["Lord of the Undead"], ["Mons's Goblin Raiders"],
        hand=["Terror", "Dralnu's Crusade"],
    )
    lord, raiders = mine[0], theirs[0]
    assert (raiders.effective_power, raiders.effective_toughness) == (1, 1)
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[raiders.permanent_id]).supported
    game.stack.clear()
    game.players[0].hand.append(_w1g6_card(set_pool, "Terror"))

    assert game.queue_from_hand(0, "Dralnu's Crusade").supported
    _w1g6_resolve_stack(game)

    assert (raiders.effective_power, raiders.effective_toughness) == (3, 3)
    assert (lord.effective_power, lord.effective_toughness) == (2, 2), "other Zombies"
    refused = game.queue_from_hand(0, "Terror", target_permanent_ids=[raiders.permanent_id])
    assert not refused.supported, refused.details


def test_w1g6_dralnus_crusade_reads_goblin_through_the_layers(set_pool):
    """The scope is "Goblins" as the board currently is, not as cards are
    printed: Bears made Goblins by a Conspiracy naming Goblin are black Goblin
    Zombies under the Crusade, and stop being when the Conspiracy leaves."""
    game, mine, _theirs = _w1g6_table(set_pool, ["Grizzly Bears", "Dralnu's Crusade"], [])
    bears = mine[0]
    assert _w1g6_shape(game, bears) == (["G"], False, False, 2, 2)

    conspiracy = _W1G6Permanent(card=set_pool("MMQ")["Conspiracy"])
    game._put_permanent_onto_battlefield(0, conspiracy, None)
    conspiracy.metadata["chosen_creature_type"] = "goblin"
    game._recompute_continuous_effects()
    assert _w1g6_shape(game, bears) == (["B"], True, True, 3, 3)

    game.remove_from_battlefield(conspiracy)
    game._recompute_continuous_effects()
    assert _w1g6_shape(game, bears) == (["G"], False, False, 2, 2)


def _w1g6_declare_block(game, attacker, blocker):
    """Seat 0 attacks with *attacker* and seat 1 offers *blocker*; returns the
    engine's answer to the block."""
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(attacker)])[0]
    game._set_phase_and_step("combat", "declare_blockers")
    return game.declare_blockers(1, {
        game.battlefield_index_of(blocker): [game.battlefield_index_of(attacker)],
    })  # _w1g6_declare_block


def test_w1g6_hobble_draws_a_card_and_stops_its_creature_attacking(set_pool):
    """"Enchant creature / When this Aura enters, draw a card. / Enchanted
    creature can't attack." Cast on the opponent's white Lions: its caster
    draws one card, and on the Lions' own turn the declaration naming them is
    refused while the Giant beside them attacks freely."""
    hobble = _w1g6_card(set_pool, "Hobble")
    assert _w1g6_compile(hobble).supported
    game, _mine, theirs = _w1g6_table(set_pool, ["Grizzly Bears"], ["Savannah Lions", "Hill Giant"])
    lions, giant = theirs
    game.players[0].library.extend([_w1g6_card(set_pool, "Forest")] * 3)

    _w1g6_enchant(game, set_pool, "Hobble", lions)
    assert [card.name for card in game.players[0].hand] == ["Forest"]

    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    assert not game.declare_attackers(1, [game.battlefield_index_of(lions)])[0]
    assert game.declare_attackers(1, [game.battlefield_index_of(giant)])[0]


def test_w1g6_hobbles_block_ban_follows_the_creatures_colour_through_the_layers(set_pool):
    """"Enchanted creature can't block if it's black." A condition, re-read
    whenever combat asks (CR 613 layer 5): the white Lions under Hobble may
    block; the same Lions turned black for the turn may not; and once the turn
    is over and they are white again, they may. A printed-black creature under
    it can never block."""
    for blocker, may_block in (("Scathe Zombies", False), ("Savannah Lions", True)):
        game, mine, theirs = _w1g6_table(set_pool, ["Grizzly Bears"], [blocker])
        _w1g6_enchant(game, set_pool, "Hobble", theirs[0])
        assert _w1g6_declare_block(game, mine[0], theirs[0])[0] is may_block, blocker

    game, mine, theirs = _w1g6_table(set_pool, ["Grizzly Bears"], ["Savannah Lions"])
    bears, lions = mine[0], theirs[0]
    _w1g6_enchant(game, set_pool, "Hobble", lions)
    _w1g6_recolor(game, lions, "B")
    refused = _w1g6_declare_block(game, bears, lions)
    assert not refused[0], refused

    game, mine, theirs = _w1g6_table(set_pool, ["Grizzly Bears"], ["Savannah Lions"])
    bears, lions = mine[0], theirs[0]
    _w1g6_enchant(game, set_pool, "Hobble", lions)
    _w1g6_recolor(game, lions, "B")
    game.resolve_cleanup_step(0)
    assert _w1g6_colors(game, lions) == ["W"]
    assert _w1g6_declare_block(game, bears, lions)[0]


def test_w1g6_a_black_creature_without_hobble_blocks_as_it_always_did(set_pool):
    """The ban is the Aura's: a black creature nothing enchants blocks, and so
    does a black creature wearing a different Aura."""
    game, mine, theirs = _w1g6_table(set_pool, ["Grizzly Bears"], ["Scathe Zombies"])
    assert _w1g6_declare_block(game, mine[0], theirs[0])[0]


def _w1g6_defiance(set_pool, mine, theirs):
    """Heroic Defiance cast on seat 0's first permanent. Returns the game and
    that creature."""
    game, my_side, their_side = _w1g6_table(set_pool, mine, theirs)
    host = my_side[0]
    _w1g6_enchant(game, set_pool, "Heroic Defiance", host)
    return game, host, their_side  # _w1g6_defiance


def test_w1g6_heroic_defiance_pumps_a_creature_that_is_not_the_most_common_colour(set_pool):
    """"Enchanted creature gets +3/+3 unless it shares a color with the most
    common color among all permanents or a color tied for most common." Two red
    permanents lead the census (the white Aura, the green Bears and a black
    creature are one each), so the green Bears are 5/5 — once, not twice."""
    assert _w1g6_compile(_w1g6_card(set_pool, "Heroic Defiance")).supported
    game, bears, _theirs = _w1g6_defiance(
        set_pool, ["Grizzly Bears"], ["Hill Giant", "Mons's Goblin Raiders", "Scathe Zombies"],
    )
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)


def test_w1g6_heroic_defiance_follows_the_census_and_the_creatures_colour(set_pool):
    """Continuous, and both halves are layer-5 reads. The Bears turned red for
    the turn share the leading colour and are 2/2; at cleanup they are green
    and 5/5 again. With one red creature gone every colour is level, green is
    "a color tied for most common", and the bonus is off; and a creature made
    colourless shares no colour at all (CR 105.2) and has it."""
    game, bears, theirs = _w1g6_defiance(
        set_pool, ["Grizzly Bears"], ["Hill Giant", "Mons's Goblin Raiders", "Scathe Zombies"],
    )
    _w1g6_recolor(game, bears, "R")
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)

    game.resolve_cleanup_step(0)
    assert _w1g6_colors(game, bears) == ["G"]
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)

    game.remove_from_battlefield(theirs[1])
    game._recompute_continuous_effects()
    assert (bears.effective_power, bears.effective_toughness) == (2, 2), "all tied"

    bears.metadata["color_override"] = ()
    game._recompute_continuous_effects()
    assert _w1g6_colors(game, bears) == []
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)


def test_w1g6_heroic_defiance_gives_nothing_to_a_creature_of_the_leading_colour(set_pool):
    """Cast on a red creature while red leads, it is +0/+0 — and the bonus
    arrives the moment red stops leading, with nothing re-cast."""
    game, giant, theirs = _w1g6_defiance(
        set_pool, ["Hill Giant", "Mons's Goblin Raiders"], ["Grizzly Bears", "Llanowar Elves"],
    )
    assert (giant.effective_power, giant.effective_toughness) == (3, 3), "red and green tie"

    extra = _W1G6Permanent(card=_w1g6_card(set_pool, "Giant Spider"))
    game._put_permanent_onto_battlefield(1, extra, None)
    game._recompute_continuous_effects()
    assert (giant.effective_power, giant.effective_toughness) == (6, 6), "green leads alone"
