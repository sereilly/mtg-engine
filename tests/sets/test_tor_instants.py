"""Torment instants.

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

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _w1g5_Game
from engine import PlayerState as _w1g5_PlayerState
from tests.helpers import _mk_card as _w1g5_mk_card
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_insidious_game(set_pool, *, library, interactive=False):
    lea = set_pool("LEA")
    dreams = set_pool("TOR")["Insidious Dreams"]
    filler = _w1g5_mk_card(name="W1G5 Filler", type_line="Land")
    game = _w1g5_Game(players=[
        _w1g5_PlayerState(
            "A", library=list(library),
            hand=[dreams, lea["Forest"], lea["Lightning Bolt"], lea["Island"]],
        ),
        _w1g5_PlayerState("B", library=[filler] * 5),
    ])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    game._sync_control()
    return game


def _w1g5_library():
    return [_w1g5_mk_card(name=f"W1G5 Card {i}", type_line="Land") for i in range(8)]


def test_w1g5_insidious_dreams_puts_the_x_cards_it_found_on_top_in_the_chosen_order(set_pool):
    """X=2: two cards discarded, two found; the finder's pick order is the
    order on top ("in any order", the reading Goblin Recruiter already has)."""
    library = _w1g5_library()
    game = _w1g5_insidious_game(set_pool, library=library, interactive=True)

    result = game.cast_from_hand(
        0, "Insidious Dreams", x_value=2, cost_hand_index=1, cost_other_hand_indices=[2],
    )
    search = game.pending_choice_of("search_library", 0)

    assert result.supported, result.details
    assert [card.name for card in game.players[0].hand] == ["Island"]
    assert search is not None
    names = [card.name for card in game.players[0].library]
    picks = [
        {"zone": "library", "index": names.index("W1G5 Card 6")},
        {"zone": "library", "index": names.index("W1G5 Card 3")},
    ]
    assert game.resolve_pending_choice("search_library", 0, picks=picks)
    _w1g5_resolve_stack(game)

    top = [card.name for card in game.players[0].library[:2]]
    assert top == ["W1G5 Card 6", "W1G5 Card 3"]
    assert len(game.players[0].library) == 8


def test_w1g5_insidious_dreams_must_find_x_cards(set_pool):
    """"for X cards" prints no "up to": a quantity search is a floor
    (CR 701.23d), so an answer finding one of two is refused."""
    game = _w1g5_insidious_game(set_pool, library=_w1g5_library(), interactive=True)

    game.cast_from_hand(0, "Insidious Dreams", x_value=2)
    search = game.pending_choice_of("search_library", 0)

    assert game._search_floor(search) == 2
    assert not game.resolve_pending_choice(
        "search_library", 0, picks=[{"zone": "library", "index": 0}],
    )
    assert game.pending_choice_of("search_library", 0) is search


def test_w1g5_insidious_dreams_at_x_zero_shuffles_and_finds_nothing(set_pool):
    library = _w1g5_library()
    game = _w1g5_insidious_game(set_pool, library=library)

    result = game.cast_from_hand(0, "Insidious Dreams", x_value=0)
    _w1g5_resolve_stack(game)

    assert result.supported, result.details
    assert len(game.players[0].hand) == 3
    assert len(game.players[0].library) == 8
    assert "A searched their library for 0 cards and shuffled" in game.log

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
