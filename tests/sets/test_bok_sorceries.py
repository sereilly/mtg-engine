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

from engine import Game as _w1g4_Game
from engine import PlayerState as _w1g4_PlayerState
from engine.models import Permanent as _w1g4_Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_derive_cast_spec
from tests.helpers import settle as _w1g4_settle


def _w1g4_card(set_pool, name):
    """A card by name, from Betrayers of Kamigawa first and Alpha for fillers."""
    bok = set_pool("BOK")
    return bok[name] if name in bok else set_pool("LEA")[name]


def _w1g4_table(set_pool, hand=(), *, mine=(), theirs=(), active=0):
    """Seat 0 to act in *active*'s first main phase, mana off; each named
    permanent untapped and able to act."""
    card = lambda name: _w1g4_card(set_pool, name)  # noqa: E731
    game = _w1g4_Game(players=[
        _w1g4_PlayerState("A", hand=[card(n) for n in hand], library=[card("Forest")] * 12),
        _w1g4_PlayerState("B", library=[card("Forest")] * 12),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g4_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game.start_turn(active)
    game._settle()
    return game, placed[0], placed[1]


def test_w1g4_twist_allegiance_announces_its_opponent(set_pool):
    """"You and **target opponent** …": the cast derivation offers an
    opponent picker (``picker_sweep``'s one Betrayers of Kamigawa finding —
    with none, a client sent a bare cast). Reins of Power, whose seat its
    untap sweep announces, keeps the picker it had."""
    twist = set_pool("BOK")["Twist Allegiance"]
    assert _w1g4_derive_cast_spec(twist, _w1g4_compile(twist)) == {
        "kind": "player", "opponents_only": True,
    }


def test_w1g4_twist_allegiance_swaps_untaps_and_hastes_both_boards(set_pool):
    """Each player gains control of every creature the other controlled,
    untapped and hasty, until end of turn; at cleanup each goes home."""
    game, mine, theirs = _w1g4_table(
        set_pool, ["Twist Allegiance"], mine=["Grizzly Bears"], theirs=["Hill Giant"],
    )
    mine[0].tapped = theirs[0].tapped = True
    result = game.cast_from_hand(0, "Twist Allegiance", target_player_index=1)
    assert result.supported, result.details
    _w1g4_settle(game)
    assert game.controller_index_of(theirs[0]) == 0, game.log
    assert game.controller_index_of(mine[0]) == 1, game.log
    for creature in (mine[0], theirs[0]):
        assert not creature.tapped
        assert game._has_keyword(creature, "haste")
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    _w1g4_settle(game)
    assert game.controller_index_of(theirs[0]) == 1
    assert game.controller_index_of(mine[0]) == 0
    assert not game._has_keyword(theirs[0], "haste")

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

# ==== end w1g10 ======================================================
