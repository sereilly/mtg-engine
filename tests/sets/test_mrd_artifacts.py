"""Mirrodin artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_game(set_pool, mine=(), hand=(), theirs=(), their_hand=(), interactive=(),
               library=None):
    pool = set_pool("MRD")
    other = set_pool("LEA")

    def card(name):
        return pool[name] if name in pool else other[name]

    p1 = _w1g7_PlayerState(
        name="P1",
        battlefield=[_w1g7_nosick(_w1g7_Permanent(card=card(n))) for n in mine],
        hand=[card(n) for n in hand],
        library=[card(n) for n in library] if library is not None else [other["Island"]] * 10,
    )
    p2 = _w1g7_PlayerState(
        name="P2",
        battlefield=[_w1g7_nosick(_w1g7_Permanent(card=card(n))) for n in theirs],
        hand=[card(n) for n in their_hand], library=[other["Island"]] * 10,
    )
    game = _w1g7_Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p1, p2


def _w1g7_settle(game):
    _w1g7_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g7_resolve(game)


def _w1g7_named(player, name):
    return next(p for p in player.battlefield if p.card.name == name)


def test_w1g7_serum_tank_counts_its_own_entry_and_every_other_artifact(set_pool):
    """"Whenever this artifact **or another artifact** enters, put a charge
    counter on this artifact." The union row read "this creature or" alone, so
    the line matched nothing and the Tank shipped "supported" on its draw line
    with no way to get a counter. Its own entry counts, another artifact counts,
    an opponent's artifact counts, a nonartifact creature does not — and the
    counter pays the draw."""
    game, p1, _p2 = _w1g7_game(
        set_pool, hand=["Serum Tank", "Ornithopter", "Grizzly Bears"],
        their_hand=["Ornithopter"],
    )
    game.cast_from_hand(0, "Serum Tank")
    _w1g7_settle(game)
    tank = _w1g7_named(p1, "Serum Tank")
    assert tank.metadata.get("charge_counters") == 1
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert tank.metadata.get("charge_counters") == 2
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert tank.metadata.get("charge_counters") == 3
    game.cast_from_hand(0, "Grizzly Bears")
    _w1g7_settle(game)
    assert tank.metadata.get("charge_counters") == 3

    _w1g7_nosick(tank)
    hand_before = len(p1.hand)
    result = game.activate_permanent_ability(
        0, "Serum Tank", permanent_index=game.battlefield_index_of(tank),
    )
    assert result.supported, result.details
    _w1g7_settle(game)
    assert tank.metadata.get("charge_counters") == 2
    assert len(p1.hand) == hand_before + 1


# ==== end W1G7 ======================================================
