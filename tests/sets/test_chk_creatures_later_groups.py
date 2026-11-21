"""Champions of Kamigawa creatures (legendary ones too) — the later groups' sections.

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


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

from engine import PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (
    _game as _w1g8_game,
    _nosick as _w1g8_nosick,
    declare_attack as _w1g8_declare_attack,
    drive_combat as _w1g8_drive_combat,
    settle as _w1g8_settle,
    stock_libraries as _w1g8_stock_libraries,
)


def _w1g8_table(mine=(), theirs=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's precombat main phase of turn 2, the permanents
    placed through the entry funnel without a beginning phase run (so no
    upkeep trigger of theirs has fired), libraries stocked."""
    game = _w1g8_game(
        _w1g8_PlayerState(name="P1", hand=list(hand), life=20),
        _w1g8_PlayerState(name="P2", hand=list(opponent_hand), life=20),
    )
    _w1g8_stock_libraries(game)
    game.turn = 2
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    placed = []
    for seat, cards in ((0, mine), (1, theirs)):
        row = []
        for card in cards:
            permanent = _w1g8_Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            row.append(_w1g8_nosick(permanent))
        placed.append(row)
    game._sync_control()
    _w1g8_settle(game)
    return game, placed[0], placed[1]


# --- Shisato, Whispering Hunter ---------------------------------------------
# "Whenever Shisato deals combat damage to a player, that player skips their
# next untap step." The seat is the one the damage event froze (CR 603.10),
# and the skip is CR 614.10's one-shot: spent by the damaged player's next
# untap step, never by Shisato's controller's.


def test_w1g8_shisato_skips_the_damaged_players_next_untap_step(set_pool):
    shisato = set_pool("CHK")["Shisato, Whispering Hunter"]
    bears = set_pool("LEA")["Grizzly Bears"]
    game, (hunter,), (bear,) = _w1g8_table([shisato], [bears])
    _w1g8_declare_attack(game, 0)
    _w1g8_drive_combat(game)
    assert game.players[1].life == 18
    hunter.tapped = True
    bear.tapped = True

    game.start_turn(1)
    _w1g8_settle(game)
    assert bear.tapped, game.log[-6:]
    assert "P2 skips their untap step" in game.log
    # Shisato's controller's untap step was not the one named.
    game.start_turn(0)
    _w1g8_settle(game)
    assert not hunter.tapped
    # Spent once: the damaged player's next untap step happens.
    game.start_turn(1)
    assert not bear.tapped


def test_w1g8_a_blocked_shisato_skips_nothing(set_pool):
    shisato = set_pool("CHK")["Shisato, Whispering Hunter"]
    wall = set_pool("LEA")["Wall of Stone"]
    game, _, _ = _w1g8_table([shisato], [wall])
    _w1g8_declare_attack(game, 0, blocks={0: 0})
    _w1g8_drive_combat(game)
    assert game.players[1].life == 20
    assert not game.skip_step_counts


def test_w1g8_shisato_sacrifices_a_snake_at_its_controllers_upkeep(set_pool):
    """"At the beginning of your upkeep, sacrifice a Snake." Shisato is a
    Snake itself, so alone it is the one sacrificed."""
    shisato = set_pool("CHK")["Shisato, Whispering Hunter"]
    game, (hunter,), _ = _w1g8_table([shisato], [])
    game.start_turn(1)
    _w1g8_settle(game)
    assert game.is_on_battlefield(hunter)
    game.start_turn(0)
    _w1g8_settle(game)
    assert not game.is_on_battlefield(hunter)
    assert shisato in game.players[0].graveyard

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================
