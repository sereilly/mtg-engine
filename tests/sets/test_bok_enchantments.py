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

from engine import Game as _w1g4_Game
from engine import PlayerState as _w1g4_PlayerState
from engine.aura_attachment import attach_aura as _w1g4_attach_aura
from engine.models import Permanent as _w1g4_Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_derive_cast_spec
from tests.helpers import settle as _w1g4_settle


def _w1g4_card(set_pool, name):
    """A card by name, from Betrayers of Kamigawa first, then Champions of
    Kamigawa, then Alpha for the fillers."""
    for code in ("BOK", "CHK", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g4_table(set_pool, hand=(), *, mine=(), theirs=(), active=0,
                interactive=(), library=None):
    """Seat 0 to act in *active*'s first main phase, mana off; each named
    permanent untapped and able to act."""
    card = lambda name: _w1g4_card(set_pool, name)  # noqa: E731
    game = _w1g4_Game(players=[
        _w1g4_PlayerState(
            "A", hand=[card(n) for n in hand],
            library=[card(n) for n in (library or ["Forest"] * 12)],
        ),
        _w1g4_PlayerState("B", library=[card("Forest")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
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


def test_w1g4_threads_of_disloyalty_picks_only_a_two_drop(set_pool):
    """"Enchant creature with mana value 2 or less": the picker carries the
    bound, the cast gate refuses a three-drop, and a two-drop is stolen."""
    threads = set_pool("BOK")["Threads of Disloyalty"]
    spec = _w1g4_derive_cast_spec(threads, _w1g4_compile(threads))
    assert spec == {"kind": "creature", "filter": {"mana_value": {"op": "le", "value": 2}}}
    game, _mine, theirs = _w1g4_table(
        set_pool, ["Threads of Disloyalty"], theirs=["Grizzly Bears", "Hill Giant"],
    )
    bears, giant = theirs
    refused = game.cast_from_hand(
        0, "Threads of Disloyalty", target_player_index=1,
        target_permanent_ids=[giant.permanent_id],
    )
    assert not refused.supported
    assert [c.name for c in game.players[0].hand] == ["Threads of Disloyalty"]
    result = game.cast_from_hand(
        0, "Threads of Disloyalty", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.details
    _w1g4_settle(game)
    assert game.controller_index_of(bears) == 0, game.log
    assert game.controller_index_of(giant) == 1


def test_w1g4_threads_of_disloyalty_falls_off_a_three_drop(set_pool):
    """The ruling (2005-02-01): "If it somehow enchants a creature with mana
    value 3 or greater, Threads of Disloyalty is put into the graveyard the
    next time state-based actions are checked" (CR 704.5m) — and the control
    it gave ends with it."""
    game, mine, theirs = _w1g4_table(
        set_pool, mine=["Threads of Disloyalty"], theirs=["Hill Giant"],
    )
    threads, giant = mine[0], theirs[0]
    _w1g4_attach_aura(threads, giant)
    _w1g4_settle(game)
    assert not game.is_on_battlefield(threads)
    assert "Threads of Disloyalty" in [c.name for c in game.players[0].graveyard]
    assert game.controller_index_of(giant) == 1

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
