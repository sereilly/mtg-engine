"""Planeshift instants.

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


# --- W1G4: domain ---
from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_cast_spec
from tests.helpers import resolve_stack as _w1g4_resolve


def _w1g4_instant_table(set_pool, spell, mine=(), theirs=()):
    """*spell* in seat 0's hand over two boards of Alpha permanents, costs off:
    what the card under test does is a size, not a price."""
    w1g4_lea = set_pool("LEA")
    w1g4_game = _W1G4Game(players=[
        _W1G4PlayerState(name="W1G4-A", hand=[set_pool("PLS")[spell]]),
        _W1G4PlayerState(name="W1G4-B"),
    ])
    w1g4_game.enforce_mana_costs = False
    w1g4_game.active_player_index = 0
    w1g4_boards = []
    for w1g4_seat, w1g4_names in enumerate((mine, theirs)):
        w1g4_board = []
        for w1g4_name in w1g4_names:
            w1g4_perm = _W1G4Permanent(card=w1g4_lea[w1g4_name])
            w1g4_game._put_permanent_onto_battlefield(w1g4_seat, w1g4_perm, None)
            w1g4_board.append(w1g4_perm)
        w1g4_boards.append(w1g4_board)
    return w1g4_game, w1g4_boards[0], w1g4_boards[1]  # _w1g4_instant_table


# -- supported on arrival: driven, not built ----------------------------------


def test_w1g4_gaeas_might_offers_a_creature(set_pool):
    card = set_pool("PLS")["Gaea's Might"]
    program = _w1g4_compile(card)
    assert program.supported, program.reason
    assert _w1g4_cast_spec(card, program) == {"kind": "creature"}


def test_w1g4_gaeas_might_pumps_by_its_casters_domain(set_pool):
    """"Target creature gets +1/+1 until end of turn for each basic land type
    among lands you control." Three lands holding five types make the Bears
    7/7; on an opponent's creature the size is still the caster's two types,
    not the five its controller has."""
    game, mine, _theirs = _w1g4_instant_table(
        set_pool, "Gaea's Might",
        mine=["Grizzly Bears", "Plains", "Tropical Island", "Badlands"],
    )
    bears = mine[0]
    cast = game.cast_from_hand(
        0, "Gaea's Might", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    assert cast.supported, cast.details
    _w1g4_resolve(game)
    assert (bears.effective_power, bears.effective_toughness) == (7, 7)
    assert "Gaea's Might gives Grizzly Bears +5/+5 until end of turn" in game.log

    game, _mine, theirs = _w1g4_instant_table(
        set_pool, "Gaea's Might", mine=["Forest", "Island"],
        theirs=["Grizzly Bears", "Plains", "Island", "Swamp", "Mountain", "Forest"],
    )
    assert game.cast_from_hand(
        0, "Gaea's Might", target_player_index=1,
        target_permanent_ids=[theirs[0].permanent_id],
    ).supported
    _w1g4_resolve(game)
    assert (theirs[0].effective_power, theirs[0].effective_toughness) == (4, 4)


def test_w1g4_gaeas_might_is_locked_in_and_ends_with_the_turn(set_pool):
    """CR 611.2c: the size is fixed as the spell resolves. A land lost
    afterwards takes nothing back — the Bears stay 7/7 — and the cleanup step
    ends the whole of it."""
    game, mine, _theirs = _w1g4_instant_table(
        set_pool, "Gaea's Might",
        mine=["Grizzly Bears", "Plains", "Tropical Island", "Badlands"],
    )
    bears, _plains, _tropical, badlands = mine
    assert game.cast_from_hand(
        0, "Gaea's Might", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g4_resolve(game)
    game.sacrifice_permanent(badlands)
    game._recompute_continuous_effects()
    assert (bears.effective_power, bears.effective_toughness) == (7, 7)

    game.resolve_cleanup_step(0)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
