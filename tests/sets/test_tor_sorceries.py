"""Torment sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
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

import pytest as _w1g4_pytest

from engine import Game as _W1g4Game, PlayerState as _W1g4PlayerState
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_skullscorch(set_pool, their_hand, *, interactive=(), accept=None):
    """Skullscorch cast at P2 holding *their_hand* Giant Growths."""
    lea = set_pool("LEA")
    game = _W1g4Game(players=[
        _W1g4PlayerState("P1", library=[lea["Swamp"]] * 5,
                         hand=[set_pool("TOR")["Skullscorch"]]),
        _W1g4PlayerState("P2", library=[lea["Swamp"]] * 5,
                         hand=[lea["Giant Growth"]] * their_hand),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_step = "precombat_main"
    assert game.cast_from_hand(0, "Skullscorch", target_player_index=1).details == "resolved"
    if accept is not None:
        while game.stack and not game.pending_choices:
            game.resolve_top_of_stack()
        assert [(c.kind, c.player_index) for c in game.pending_choices] == [("optional_pay", 1)]
        assert game.confirm_optional_pay(1, accept=accept)
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game


@_w1g4_pytest.mark.parametrize("accept, life, hand", [(True, 16, 3), (False, 20, 1)])
def test_w1g4_skullscorch_the_target_chooses_damage_or_the_discard(set_pool, accept, life, hand):
    """"Target player discards two cards at random unless that player has
    Skullscorch deal 4 damage to them." The offer is the target's."""
    game = _w1g4_skullscorch(set_pool, 3, interactive=(1,), accept=accept)

    assert game.players[1].life == life
    assert len(game.players[1].hand) == hand


@_w1g4_pytest.mark.parametrize("held, life, hand", [(0, 20, 0), (1, 20, 0)])
def test_w1g4_skullscorch_a_seat_nobody_asks_keeps_its_life_over_a_short_hand(
    set_pool, held, life, hand
):
    """A seat nobody asks weighs the two losses (``toll_decline_is_smaller_loss``):
    two random cards out of a hand holding none or one are worth less than 4
    life, so it takes the discard. Unpriced, the random discard left the
    standing policy — pay tolls — to take 4 damage to protect an empty hand."""
    game = _w1g4_skullscorch(set_pool, held)

    assert game.players[1].life == life
    assert len(game.players[1].hand) == hand
    assert any("declined Skullscorch" in line for line in game.log)

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

# ==== end W1G8 ======================================================
