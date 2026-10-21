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

from engine import Game as _W1G8Game, PlayerState as _W1G8Player
from engine.models import Permanent as _W1G8Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_eddy_table(set_pool, *, lands=True):
    """Churning Eddy in seat 0's hand; a Grizzly Bears and a Forest for
    seat 1, a Hill Giant and an Island for seat 0."""
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player("A", hand=[set_pool("TOR")["Churning Eddy"]]),
        _W1G8Player("B"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    placed = {}
    for seat, key, name in (
        (1, "bears", "Grizzly Bears"), (0, "giant", "Hill Giant"),
        (1, "forest", "Forest"), (0, "island", "Island"),
    ):
        if not lands and key in ("forest", "island"):
            continue
        placed[key] = _W1G8Permanent(card=lea[name])
        game._put_permanent_onto_battlefield(seat, placed[key], None)
    return game, placed


def test_w1g8_churning_eddy_returns_a_creature_and_a_land_on_two_boards(set_pool):
    """"Return target creature and target land to their owners' hands." It
    refused at the parse ("no spell picks two targets from one verb"): two
    targets of one verb are one announcement (CR 601.2c), described as ordered
    roles the way Fumarole's destroy is. The two need not sit on one
    battlefield, and each goes to its own owner's hand (CR 400.3)."""
    game, placed = _w1g8_eddy_table(set_pool)
    assert _w1g8_compile(set_pool("TOR")["Churning Eddy"]).supported

    spec = game.cast_target_spec(0, set_pool("TOR")["Churning Eddy"])
    assert [role["kind"] for role in spec["roles"]] == ["creature", "land"]
    assert sorted(o["name"] for o in spec["valid_targets"]) == [
        "Grizzly Bears", "Hill Giant",
    ], "the creature slot offers creatures and nothing else"

    result = game.cast_from_hand(
        0, "Churning Eddy",
        target_permanent_ids=[placed["bears"].permanent_id, placed["island"].permanent_id],
    )
    assert result.supported, result.details
    _w1g8_resolve_stack(game)

    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].hand] == ["Island"]
    assert game.is_on_battlefield(placed["giant"])
    assert game.is_on_battlefield(placed["forest"])


def test_w1g8_churning_eddy_needs_both_targets_to_be_cast(set_pool):
    """Every target is chosen as part of one announcement: with no land on the
    battlefield there is no legal announcement, and the spell is not cast
    (CR 601.2c) — not cast and half-resolved."""
    game, placed = _w1g8_eddy_table(set_pool, lands=False)
    refused = game.cast_from_hand(
        0, "Churning Eddy", target_permanent_ids=[placed["bears"].permanent_id],
    )
    assert not refused.supported
    assert [c.name for c in game.players[0].hand] == ["Churning Eddy"]
    assert game.is_on_battlefield(placed["bears"])


def test_w1g8_churning_eddy_still_returns_the_target_that_is_left(set_pool):
    """CR 608.2b: one illegal target of two leaves the other to be returned —
    and the departed slot is not filled by whatever slid into its place."""
    game, placed = _w1g8_eddy_table(set_pool)
    result = game.queue_from_hand(
        0, "Churning Eddy",
        target_permanent_ids=[placed["bears"].permanent_id, placed["forest"].permanent_id],
    )
    assert result.supported, result.details
    game.remove_from_battlefield(placed["bears"])
    _w1g8_resolve_stack(game)

    assert [c.name for c in game.players[1].hand] == ["Forest"]
    assert game.is_on_battlefield(placed["giant"]), "not a stand-in for the Bears"
    assert game.is_on_battlefield(placed["island"])

# ==== end W1G8 ======================================================
