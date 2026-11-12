"""Fifth Dawn artifacts — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.
#
# Doubling Cube: CR 701.10f's "double … unspent mana", a mana ability.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.mana_abilities import is_mana_ability as _w1g7_is_mana_ability
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, mine=(), enforce=False):
    lea = set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(name=f"P{seat}", library=[lea["Island"]] * 20)
        for seat in range(2)
    ])
    game.enforce_mana_costs = enforce
    game.start_turn(0)
    _w1g7_settle(game)
    placed = []
    for card in mine:
        permanent = _W1G7Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    _w1g7_settle(game)
    return game, placed


def _w1g7_pool(player):
    return {symbol: n for symbol, n in player.mana_pool.items() if n}


def test_w1g7_doubling_cube_doubles_each_type_and_copies_no_restriction(set_pool):
    """Its rulings (2004-12-01): the type is the colour or colourless, and
    "Any restrictions on the unspent mana aren't copied" — artifacts-only
    {U}{U}{U} stays as it was and {U}{U}{U} for anything joins it. It is a
    mana ability: it never touches the stack."""
    cube = set_pool("5DN")["Doubling Cube"]
    assert _w1g7_is_mana_ability(_w1g7_compile(cube).activated_abilities[0])
    game, (permanent,) = _w1g7_table(set_pool, mine=[cube])
    player = game.players[0]
    player.mana_pool.update({"W": 1, "B": 2, "C": 4})
    player.restricted_mana.setdefault("artifact", {})["U"] = 3

    result = game.activate_permanent_ability(0, "Doubling Cube")

    assert result.supported, result
    assert not game.stack
    assert permanent.tapped
    assert _w1g7_pool(player) == {"W": 2, "U": 3, "B": 4, "C": 8}
    assert player.restricted_mana["artifact"] == {"U": 3}


def test_w1g7_doubling_cube_doubles_what_is_left_after_its_own_cost(set_pool):
    """CR 602.2/605.3: the {3} is paid as the ability is activated and the
    effect doubles the pool it leaves — five {C} pay three and the two left
    become four. An empty pool adds nothing."""
    cube = set_pool("5DN")["Doubling Cube"]
    game, _ = _w1g7_table(set_pool, mine=[cube], enforce=True)
    player = game.players[0]
    player.mana_pool["C"] = 5

    result = game.activate_permanent_ability(0, "Doubling Cube")

    assert result.supported, result
    assert _w1g7_pool(player) == {"C": 4}
    assert "Doubling Cube doubled P0's unspent mana, adding {C}{C}" in game.log

    game, _ = _w1g7_table(set_pool, mine=[cube])
    game.activate_permanent_ability(0, "Doubling Cube")
    assert _w1g7_pool(game.players[0]) == {}
    assert "Doubling Cube: P0 has no unspent mana to double" in game.log

# ==== end w1g7 ======================================================
