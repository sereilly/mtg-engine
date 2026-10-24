"""Judgment enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
from engine import Game as _w1g8_Game
from engine import PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_chaos_board(set_pool) -> "_w1g8_Game":
    """Seat 0 controls Planar Chaos; seat 0's turn, mana costs waived."""
    game = _w1g8_Game(players=[
        _w1g8_PlayerState(name="P1"), _w1g8_PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._put_permanent_onto_battlefield(
        0, _w1g8_Permanent(card=set_pool("JUD")["Planar Chaos"]), None,
    )
    return game


def test_w1g8_planar_chaos_counters_a_spell_whose_caster_loses_the_flip(set_pool, monkeypatch):
    """"Whenever a player casts a spell, that player flips a coin. If they lose
    the flip, counter that spell." The trigger is a stack object above the
    spell (CR 603.3); the opponent who cast the Bolt flips and loses, and the
    Bolt is countered — seat 0 keeps its life."""
    monkeypatch.setattr("engine.handlers.control_flow.flip_coin", lambda: False)
    game = _w1g8_chaos_board(set_pool)
    game.players[1].hand.append(set_pool("LEA")["Lightning Bolt"])
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert [item.card.name for item in game.stack] == ["Lightning Bolt", "Planar Chaos"]
    _w1g8_resolve_stack(game)
    assert game.players[0].life == 20
    assert "Planar Chaos: P2 lost the coin flip" in game.log
    assert [card.name for card in game.players[1].graveyard] == ["Lightning Bolt"]


def test_w1g8_planar_chaos_lets_a_spell_through_when_its_caster_wins(set_pool, monkeypatch):
    """The winner is the player who flipped (CR 705.2) — the Bolt's caster,
    not Planar Chaos's controller — and the spell resolves. Planar Chaos's
    controller is held to it too: their own spell is flipped for."""
    monkeypatch.setattr("engine.handlers.control_flow.flip_coin", lambda: True)
    game = _w1g8_chaos_board(set_pool)
    game.players[1].hand.append(set_pool("LEA")["Lightning Bolt"])
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g8_resolve_stack(game)
    assert game.players[0].life == 17
    assert "Planar Chaos: P2 won the coin flip" in game.log

    monkeypatch.setattr("engine.handlers.control_flow.flip_coin", lambda: False)
    game.players[0].hand.append(set_pool("LEA")["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 20
    assert "Planar Chaos: P1 lost the coin flip" in game.log


def test_w1g8_planar_chaos_is_sacrificed_when_its_upkeep_flip_is_lost(set_pool, monkeypatch):
    """"At the beginning of your upkeep, flip a coin. If you lose the flip,
    sacrifice this enchantment." Driven through the real turn: seat 0's next
    upkeep puts the trigger on the stack, and the lost flip sacrifices it."""
    game = _w1g8_chaos_board(set_pool)
    monkeypatch.setattr("engine.handlers.control_flow.flip_coin", lambda: False)
    game.start_turn(1)
    game.start_turn(0)
    _w1g8_resolve_stack(game)
    assert not any(p.card.name == "Planar Chaos" for p in game.controlled_by(0))
    assert [card.name for card in game.players[0].graveyard] == ["Planar Chaos"]

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
