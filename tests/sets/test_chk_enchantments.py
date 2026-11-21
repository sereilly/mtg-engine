"""Champions of Kamigawa enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.models import Permanent as _W1G9Permanent
from tests.helpers import settle as _w1g9_settle


def _w1g9_card(set_pool, name):
    for code in ("CHK", "LEA", "TMP"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g9_table(set_pool, *, mine=(), theirs=()):
    card = lambda name: _w1g9_card(set_pool, name)  # noqa: E731
    game = _W1G9Game(players=[
        _W1G9PlayerState(name="Alice", library=[card("Island")] * 12),
        _W1G9PlayerState(name="Bob", library=[card("Island")] * 12),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _W1G9Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g9_settle(game)
    return game, placed[0], placed[1]


def _w1g9_pool(player):
    return {symbol: n for symbol, n in player.mana_pool.items() if n}


def test_w1g9_heartbeat_of_spring_adds_one_mana_inline_for_every_players_land(set_pool):
    """"Whenever a player taps a land for mana, that player adds one mana of
    any type that land produced." A triggered mana ability (CR 605.1b): the
    extra mana is there as the tap returns, with nothing on the stack. One
    unit, of a type the land made, when the land made two (ruling
    2020-08-07: "you choose one type that was produced and add one mana of
    that type"); unrestricted beside a land whose own mana is restricted
    ("with no restrictions or riders"); and for the opponent's land too."""
    game, mine, theirs = _w1g9_table(
        set_pool,
        mine=["Heartbeat of Spring", "Forest", "Ancient Tomb", "Untaidake, the Cloud Keeper"],
        theirs=["Island"],
    )
    alice, bob = game.players
    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=mine[1].permanent_id)
    assert _w1g9_pool(alice) == {"G": 2}
    assert game.stack == []

    assert game.tap_land_for_mana(0, "Ancient Tomb", "C", permanent_id=mine[2].permanent_id)
    assert _w1g9_pool(alice) == {"G": 2, "C": 3}
    assert alice.life == 18

    slot = [p.permanent_id for p in alice.battlefield].index(mine[3].permanent_id)
    assert game.activate_permanent_ability(
        0, "Untaidake, the Cloud Keeper", permanent_index=slot,
    ).supported
    assert alice.restricted_mana == {"legendary": {"C": 2}}
    assert _w1g9_pool(alice) == {"G": 2, "C": 4}
    assert game.stack == []

    assert game.tap_land_for_mana(1, "Island", "U", permanent_id=theirs[0].permanent_id)
    assert _w1g9_pool(bob) == {"U": 2}

# ==== end w1g9 ======================================================
