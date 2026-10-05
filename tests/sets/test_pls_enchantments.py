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
