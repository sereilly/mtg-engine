"""Mirrodin instants, the later groups' sections.

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


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

from engine import Game as _w1g6_Game, PlayerState as _w1g6_PlayerState
from engine.models import Permanent as _w1g6_Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from engine.targeting import derive_cast_spec as _w1g6_derive_cast_spec
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def test_w1g6_forge_armor_puts_the_sacrificed_artifact_s_mana_value_in_counters(
    set_pool,
):
    """"As an additional cost to cast this spell, sacrifice an artifact." /
    "Put X +1/+1 counters on target creature, where X is the sacrificed
    artifact's mana value."

    The artifact named for the cost is the one paid (CR 601.2h), and its mana
    value — read off what the cost ate, not off the board — is how many
    counters land: Oblivion Stone ({3}) makes a 1/1 Myr a 4/4, while the cheaper
    artifact beside it is kept.
    """
    pool = set_pool("MRD")
    card = pool["Forge Armor"]
    program = _w1g6_compile(card)
    assert program.supported, program.reason
    assert _w1g6_derive_cast_spec(card, program) == {
        "kind": "creature",
        "cost_spec": {"kind": "artifact", "own_only": True, "sacrifice_cost": True},
    }

    stone = _w1g6_Permanent(card=pool["Oblivion Stone"])      # mana value 3
    chalice = _w1g6_Permanent(card=pool["Chalice of the Void"])  # mana value 0
    myr = _w1g6_Permanent(card=pool["Leaden Myr"])            # a 1/1
    game = _w1g6_Game(players=[
        _w1g6_PlayerState(name="P1", battlefield=[stone, chalice, myr],
                          hand=[card]),
        _w1g6_PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()

    result = game.queue_from_hand(
        0, "Forge Armor",
        cost_permanent_ids=[stone.permanent_id],
        target_permanent_ids=[myr.permanent_id],
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(stone)
    assert game.is_on_battlefield(chalice)
    _w1g6_resolve_stack(game)

    assert myr.metadata.get("plus_counters") == 3
    assert (myr.effective_power, myr.effective_toughness) == (4, 4)

# ==== end W1G6 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================
