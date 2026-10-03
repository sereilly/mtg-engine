"""Prophecy enchantments.

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

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: tokens, zones and triggers ---
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.tokens import make_token_card as _w1g6_make_token_card
from tests.helpers import _mk_card as _w1g6_mk_card, resolve_stack as _w1g6_resolve


def _w1g6_put(game, seat, card, *, token=False):
    perm = _W1G6Permanent(card=card)
    if token:
        perm.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm  # _w1g6_put


def _w1g6_table(p0=None, p1=None):
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", **(p0 or {})),
        _W1G6PlayerState(name="P1", **(p1 or {})),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    return game  # _w1g6_table


def _w1g6_land(name="Forest"):
    return _w1g6_mk_card(name, f"Basic Land — {name}")


def test_w1g6_overburden_bounces_a_land_of_the_creatures_controller(set_pool):
    """"Whenever a player puts a nontoken creature onto the battlefield, that
    player returns a land they control to its owner's hand." The seat whose
    creature entered returns one of *its* lands — the enchantment's controller
    keeps theirs — and a token entering asks nothing."""
    pcy = set_pool("PCY")
    bear = _w1g6_mk_card("Bear", "{1}{G}", "Creature — Bear", "")
    game = _w1g6_table(p1={"hand": [bear]})
    _w1g6_put(game, 0, pcy["Overburden"])
    mine = _w1g6_put(game, 0, _w1g6_land("Island"))
    theirs = [_w1g6_put(game, 1, _w1g6_land(n)) for n in ("Forest", "Mountain")]

    # A token entering is not a nontoken creature: nothing triggers.
    _w1g6_put(game, 1, _w1g6_make_token_card("Elf Token", 1, 1, "Creature — Elf"),
              token=True)
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in game.players[1].hand] == ["Bear"]
    assert all(game.is_on_battlefield(p) for p in theirs)

    # The same entry path with a nontoken creature does trigger — for the
    # enchantment's own controller this time, who returns their own land.
    _w1g6_put(game, 0, _w1g6_mk_card("Wolf", "Creature — Wolf"))
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    assert [c.name for c in game.players[0].hand] == ["Island"]
    assert not game.is_on_battlefield(mine)
    assert all(game.is_on_battlefield(p) for p in theirs)

    game.start_turn(1)
    game._close_current_priority_step()
    result = game.cast_from_hand(1, "Bear")
    assert result.supported, result.details
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)

    assert [c.name for c in game.players[1].hand] in (["Forest"], ["Mountain"])
    assert sum(game.is_on_battlefield(p) for p in theirs) == 1
    assert [c.name for c in game.players[0].hand] == ["Island"]
