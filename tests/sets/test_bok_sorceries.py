"""Betrayers of Kamigawa sorceries.

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

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

from engine import Game as _W1G10Game
from engine.models import PlayerState as _W1G10PlayerState
from tests.helpers import settle as _w1g10_settle


def _w1g10_table(set_pool, *, hand=(), library=(), opponent_library=None,
                 graveyard=(), opponent_hand=(), opponent_graveyard=()):
    """Alice's first main phase, costs off, both seats headless."""
    lea = set_pool("LEA")
    game = _W1G10Game(players=[
        _W1G10PlayerState(name="Alice", hand=list(hand), library=list(library),
                          graveyard=list(graveyard)),
        _W1G10PlayerState(
            name="Bob", hand=list(opponent_hand),
            graveyard=list(opponent_graveyard),
            library=list(opponent_library if opponent_library is not None
                         else [lea["Island"]] * 10),
        ),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g10_settle(game)
    return game


def test_w1g10_heed_the_mists_draws_the_milled_cards_mana_value(set_pool):
    """Heed the Mists: "Mill a card, then draw cards equal to the milled card's
    mana value." A milled Hill Giant ({3}{R}) draws four cards."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    library = [lea["Hill Giant"], *[lea["Island"]] * 6]
    game = _w1g10_table(set_pool, hand=[bok["Heed the Mists"]], library=library)
    assert game.cast_from_hand(0, "Heed the Mists").supported
    _w1g10_settle(game)
    alice = game.players[0]
    assert [card.name for card in alice.graveyard] == ["Hill Giant", "Heed the Mists"]
    assert [card.name for card in alice.hand] == ["Island"] * 4
    assert len(alice.library) == 2


def test_w1g10_heed_the_mists_a_milled_land_draws_nothing(set_pool):
    """A land's mana value is 0, so nothing is drawn; an empty library mills
    nothing and draws nothing (CR 107.2's zero), and no one loses for it."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g10_table(set_pool, hand=[bok["Heed the Mists"]] * 2,
                        library=[lea["Island"], lea["Hill Giant"]])
    assert game.cast_from_hand(0, "Heed the Mists").supported
    _w1g10_settle(game)
    alice = game.players[0]
    assert [card.name for card in alice.graveyard] == ["Island", "Heed the Mists"]
    assert [card.name for card in alice.hand] == ["Heed the Mists"]
    alice.library.clear()
    assert game.cast_from_hand(0, "Heed the Mists").supported
    _w1g10_settle(game)
    assert alice.hand == []
    assert not game.is_game_over()


def test_w1g10_enshrined_memories_keeps_the_creatures_among_the_top_x(set_pool):
    """Enshrined Memories, X=3: "Reveal the top X cards of your library. Put all
    creature cards revealed this way into your hand and the rest on the bottom
    of your library in any order." The fourth card is never revealed."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    library = [lea["Grizzly Bears"], lea["Island"], lea["Hill Giant"],
               lea["Llanowar Elves"], lea["Forest"]]
    game = _w1g10_table(set_pool, hand=[bok["Enshrined Memories"]], library=library)
    assert game.cast_from_hand(0, "Enshrined Memories", x_value=3).supported
    _w1g10_settle(game)
    alice = game.players[0]
    assert sorted(card.name for card in alice.hand) == ["Grizzly Bears", "Hill Giant"]
    assert [card.name for card in alice.library] == [
        "Llanowar Elves", "Forest", "Island",
    ]
    assert any("revealed Grizzly Bears, Island, Hill Giant" in line for line in game.log)


def test_w1g10_enshrined_memories_for_zero_reveals_nothing(set_pool):
    """X=0 reveals no card and moves none."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    library = [lea["Grizzly Bears"], lea["Island"]]
    game = _w1g10_table(set_pool, hand=[bok["Enshrined Memories"]], library=library)
    assert game.cast_from_hand(0, "Enshrined Memories", x_value=0).supported
    _w1g10_settle(game)
    alice = game.players[0]
    assert alice.hand == []
    assert [card.name for card in alice.library] == ["Grizzly Bears", "Island"]

# ==== end w1g10 ======================================================
