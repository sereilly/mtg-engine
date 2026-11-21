"""Champions of Kamigawa sorceries.

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
#
# Glimpse of Nature: "Whenever you cast a creature spell this turn, draw a
# card." — a delayed triggered ability the resolution creates, lasting the
# turn (CR 603.7b), read by the delayed-cast table's second spelling.
from engine import Game as _W1G4Game
from engine.models import PlayerState as _W1G4PlayerState
from tests.helpers import settle as _w1g4_settle


def _w1g4_glimpsed(set_pool, *, hand=(), opponent_hand=()):
    """Alice's first main phase with Glimpse of Nature resolved."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="Alice", hand=[chk["Glimpse of Nature"], *hand],
                         library=[lea["Island"]] * 10),
        _W1G4PlayerState(name="Bob", hand=list(opponent_hand),
                         library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g4_settle(game)
    assert game.queue_from_hand(0, "Glimpse of Nature").supported
    _w1g4_settle(game)
    return game


def test_w1g4_glimpse_of_nature_draws_for_each_creature_spell_this_turn(set_pool):
    """Two creature spells, two cards — and each draw resolves above the
    spell that triggered it (the 2026-03-20 ruling)."""
    lea = set_pool("LEA")
    game = _w1g4_glimpsed(set_pool, hand=[lea["Grizzly Bears"], lea["Hill Giant"]])
    library = len(game.players[0].library)
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert [item.card.name for item in game.stack] == ["Grizzly Bears", "Glimpse of Nature"]
    game.resolve_top_of_stack()
    assert len(game.players[0].library) == library - 1
    assert [item.card.name for item in game.stack] == ["Grizzly Bears"]
    _w1g4_settle(game)
    assert game.queue_from_hand(0, "Hill Giant").supported
    _w1g4_settle(game)
    assert len(game.players[0].library) == library - 2, game.log


def test_w1g4_glimpse_of_nature_draws_even_when_the_creature_is_countered(set_pool):
    """The 2026-03-20 ruling: the draw "resolves even if that spell is
    countered" — Bob's Counterspell, cast above the trigger, still leaves
    Alice her card."""
    lea = set_pool("LEA")
    game = _w1g4_glimpsed(
        set_pool, hand=[lea["Grizzly Bears"]], opponent_hand=[lea["Counterspell"]],
    )
    library = len(game.players[0].library)
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    # ``target_stack_index`` indexes the stack bottom-first: 0 is the Bears.
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g4_settle(game)
    assert "Grizzly Bears" in [card.name for card in game.players[0].graveyard], game.log
    assert len(game.players[0].library) == library - 1


def test_w1g4_glimpse_of_nature_ignores_other_spells_and_other_turns(set_pool):
    """A noncreature spell draws nothing, an opponent's creature spell draws
    nothing ("you cast"), and the trigger is gone by the next turn."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g4_glimpsed(
        set_pool, hand=[chk["Counsel of the Soratami"], lea["Grizzly Bears"]],
        opponent_hand=[lea["Grizzly Bears"]],
    )
    library = len(game.players[0].library)
    assert game.queue_from_hand(0, "Counsel of the Soratami").supported
    _w1g4_settle(game)
    assert len(game.players[0].library) == library - 2, game.log    # Counsel's own two
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    _w1g4_settle(game)
    assert len(game.players[0].library) == library - 2
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    game.start_turn(0)
    _w1g4_settle(game)
    library = len(game.players[0].library)
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    _w1g4_settle(game)
    assert len(game.players[0].library) == library, game.log

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
