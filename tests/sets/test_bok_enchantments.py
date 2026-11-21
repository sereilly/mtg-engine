"""Betrayers of Kamigawa enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
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

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.aura_attachment import attach_aura as _w1g8_attach_aura
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (declare_attack as _w1g8_declare_attack,
                           drive_combat as _w1g8_drive_combat,
                           stock_libraries as _w1g8_stock_libraries)


def test_w1g8_mark_of_sakiko_grants_its_host_the_kept_mana_trigger(set_pool):
    """'Enchanted creature has "Whenever this creature deals combat damage to
    a player, add that much {G}. Until end of turn, you don't lose this mana
    as steps and phases end."' The host deals 3 and its controller adds
    {G}{G}{G} that stays into the postcombat main phase; the unenchanted
    attacker beside it adds nothing, and the Aura gone takes the ability."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    giant = _w1g8_Permanent(card=lea["Hill Giant"])
    bears = _w1g8_Permanent(card=lea["Grizzly Bears"])
    mark = _w1g8_Permanent(card=bok["Mark of Sakiko"])
    game = _w1g8_Game(players=[
        _w1g8_PlayerState(name="P0", battlefield=[giant, bears, mark]),
        _w1g8_PlayerState(name="P1"),
    ])
    _w1g8_stock_libraries(game)
    game._sync_control()
    _w1g8_attach_aura(mark, giant)
    game.active_player_index = 0
    _w1g8_declare_attack(game, 0)
    _w1g8_drive_combat(game)
    assert game.players[1].life == 15
    assert game.players[0].restricted_mana["kept_until_end_of_turn"] == {"G": 3}
    assert "Hill Giant produced {G}{G}{G} (kept until end of turn)" in game.log
    assert not any("Grizzly Bears produced" in line for line in game.log)
    assert game.current_step == "postcombat_main"
    assert "deals combat damage" not in (bears.effective_card.oracle_text or "")

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
