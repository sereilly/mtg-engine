"""Apocalypse sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

from engine import Game as _w1g3s_Game, PlayerState as _w1g3s_Player
from engine.game_types import CardDefinition as _w1g3s_CardDefinition


def _w1g3s_index_game(set_pool, size, *, interactive=()):
    """Index in seat 0's hand over a library of *size* numbered cards."""
    library = [
        _w1g3s_CardDefinition(
            name=f"Card {n}", mana_cost="", cmc=0.0, type_line="Land",
            oracle_text="", colors=(), color_identity=(), keywords=(),
            produced_mana=(), raw={"name": f"Card {n}", "type_line": "Land"},
        )
        for n in range(1, size + 1)
    ]
    game = _w1g3s_Game(players=[
        _w1g3s_Player(name="P0", hand=[set_pool("APC")["Index"]], library=library),
        _w1g3s_Player(name="P1"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    return game  # W1G3 sorceries: the Index game


def test_w1g3_index_puts_the_top_five_back_in_the_order_its_caster_chooses(set_pool):
    """"Look at the top five cards of your library, then put them back in any
    order." The caster is shown five of six and asked for an order; a
    permutation of the wrong length is refused, the answer is the new top of
    the library, and the sixth card stays sixth. Nothing is drawn."""
    game = _w1g3s_index_game(set_pool, 6, interactive={0})
    me = game.players[0]

    assert game.cast_from_hand(0, "Index").supported

    waiting = game.waiting_prompt()
    assert waiting is not None and waiting.kind == "reorder_library"
    assert waiting.data["top_count"] == 5 and waiting.data.get("position") is None
    assert [c.name for c in game.reorder_library_pile(waiting)] == [
        f"Card {n}" for n in range(1, 6)
    ]
    assert [item.card.name for item in game.stack] == ["Index"]

    assert not game.confirm_reorder_library(0, [0, 1, 2])
    assert not game.confirm_reorder_library(0, [5, 4, 3, 2, 1])
    assert game.confirm_reorder_library(0, [4, 3, 2, 1, 0])
    game._settle()

    assert [c.name for c in me.library] == [
        "Card 5", "Card 4", "Card 3", "Card 2", "Card 1", "Card 6",
    ]
    assert me.hand == [] and game.stack == []
    assert [c.name for c in me.graveyard] == ["Index"]


def test_w1g3_index_over_a_short_library_orders_what_is_there(set_pool):
    """Three cards are looked at when three is all there is (CR 609.3), and
    one card has no order to choose: nothing is asked and the spell resolves."""
    game = _w1g3s_index_game(set_pool, 3, interactive={0})
    assert game.cast_from_hand(0, "Index").supported
    assert game.waiting_prompt().data["top_count"] == 3
    assert game.confirm_reorder_library(0, [1, 2, 0])
    game._settle()
    assert [c.name for c in game.players[0].library] == ["Card 2", "Card 3", "Card 1"]

    game = _w1g3s_index_game(set_pool, 1, interactive={0})
    assert game.cast_from_hand(0, "Index").supported
    assert game.pending_choices == [] and game.stack == []
    assert [c.name for c in game.players[0].library] == ["Card 1"]
    assert [c.name for c in game.players[0].graveyard] == ["Index"]

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
