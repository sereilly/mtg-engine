"""Betrayers of Kamigawa creatures (legendary ones too) — the later groups' sections.

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


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), opponent_hand=(), interactive=(), library=20):
    """Two seats on seat 0's first main phase, costs not enforced."""
    lea = set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * library,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g7_settle(game)
    return game


def _w1g7_put(game, card, seat=0):
    permanent = _W1G7Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_w1g7_ishi_ishi_shoots_the_opponent_who_casts_a_spirit_or_arcane_spell(set_pool):
    """Whenever an opponent casts a Spirit or Arcane spell, Ishi-Ishi deals 2
    damage to that player. An Arcane instant and a Spirit creature spell each
    cost their caster 2; a spell that is neither costs nothing, and neither
    does Ishi-Ishi's own controller's Spirit (the trigger is "an opponent")."""
    bok, chk, lea = set_pool("BOK"), set_pool("CHK"), set_pool("LEA")
    game = _w1g7_table(
        set_pool,
        hand=[chk["Kami of the Hunt"]],
        opponent_hand=[chk["Glacial Ray"], lea["Lightning Bolt"], chk["Kami of the Hunt"]],
    )
    _w1g7_put(game, bok["Ishi-Ishi, Akki Crackshot"])
    bears = _w1g7_put(game, lea["Grizzly Bears"])
    assert game.cast_from_hand(
        1, "Glacial Ray", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert [p.life for p in game.players] == [20, 18]
    assert "Ishi-Ishi, Akki Crackshot dealt 2 damage to P1" in game.log
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g7_settle(game)
    assert [p.life for p in game.players] == [17, 18]
    # Its controller's own Spirit spell is no opponent's.
    assert game.cast_from_hand(0, "Kami of the Hunt").supported
    _w1g7_settle(game)
    assert [p.life for p in game.players] == [17, 18]
    game.start_turn(1)
    _w1g7_settle(game)
    assert game.cast_from_hand(1, "Kami of the Hunt").supported
    _w1g7_settle(game)
    assert [p.life for p in game.players] == [17, 16]

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
