"""Invasion sorceries.

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

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G8: odd ones ---
from engine import Game as _W1G8Game, PlayerState as _W1G8PlayerState
from engine.models import Permanent as _W1G8Permanent
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_wave_table(set_pool, *, active: int, blue_mana: int):
    """Seat 0 holds Breaking Wave with *blue_mana* floating, in *active*'s
    precombat main phase, costs enforced. Seat 0's Grizzly Bears and seat 1's
    Scryb Sprites and Forest start tapped; seat 1's Hill Giant untapped."""
    pool = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8PlayerState(name=f"P{seat}", life=20, library=[pool["Island"]] * 10)
        for seat in range(2)
    ])
    game.interactive_seats = set()
    game.start_turn(active)
    game.current_turn_phase = "precombat_main"
    game.enforce_mana_costs = True
    board = {}
    for seat, name, tapped in (
        (0, "Grizzly Bears", True), (1, "Hill Giant", False),
        (1, "Scryb Sprites", True), (1, "Forest", True),
    ):
        permanent = _W1G8Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.tapped = tapped
        board[name] = permanent
    game.players[0].hand = [set_pool("INV")["Breaking Wave"]]
    game.players[0].mana_pool["U"] = blue_mana
    return game, board


def test_breaking_wave_inverts_every_creature_at_once(set_pool):
    """"Simultaneously untap all tapped creatures and tap all untapped
    creatures." Both sets are read before either is turned: the tapped Bears
    and Sprites untap, the untapped Hill Giant taps — on both battlefields —
    and the tapped Forest, not a creature, is left alone. Cast in its
    controller's main phase it costs its printed {2}{U}{U}."""
    game, board = _w1g8_wave_table(set_pool, active=0, blue_mana=4)

    assert game.cast_from_hand(0, "Breaking Wave").supported
    _w1g8_resolve_stack(game)

    assert not board["Grizzly Bears"].tapped
    assert not board["Scryb Sprites"].tapped
    assert board["Hill Giant"].tapped
    assert board["Forest"].tapped
    assert game.players[0].mana_pool["U"] == 0


def test_breaking_wave_costs_two_more_outside_sorcery_timing(set_pool):
    """"You may cast this spell as though it had flash if you pay {2} more to
    cast it." On the opponent's turn four mana is not enough — the cast is
    refused with nothing spent and nothing turned."""
    game, board = _w1g8_wave_table(set_pool, active=1, blue_mana=4)

    assert not game.cast_from_hand(0, "Breaking Wave").supported

    assert game.players[0].mana_pool["U"] == 4
    assert [card.name for card in game.players[0].hand] == ["Breaking Wave"]
    assert board["Grizzly Bears"].tapped and not board["Hill Giant"].tapped


def test_breaking_wave_is_cast_as_though_it_had_flash_for_six(set_pool):
    """The permission bought: on the opponent's turn, six mana casts it and
    all six are spent. In its controller's own main phase the same six leave
    two floating — the price is owed only when the permission is used."""
    game, board = _w1g8_wave_table(set_pool, active=1, blue_mana=6)
    assert game.cast_from_hand(0, "Breaking Wave").supported
    _w1g8_resolve_stack(game)
    assert game.players[0].mana_pool["U"] == 0
    assert board["Hill Giant"].tapped and not board["Grizzly Bears"].tapped

    game, _board = _w1g8_wave_table(set_pool, active=0, blue_mana=6)
    assert game.cast_from_hand(0, "Breaking Wave").supported
    assert game.players[0].mana_pool["U"] == 2
