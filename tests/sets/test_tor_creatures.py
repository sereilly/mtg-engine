"""Torment creatures (legendary ones too).

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
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_swarm_table(set_pool, *, humans=()):
    """Shambling Swarm and a Savannah Lions for seat 0, a Grizzly Bears and a
    Hill Giant for seat 1, and a Lightning Bolt in seat 1's hand to kill the
    Swarm with."""
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player("A", library=[lea["Forest"]] * 10),
        _W1G8Player("B", library=[lea["Forest"]] * 10, hand=[lea["Lightning Bolt"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(humans)
    placed = {}
    for seat, name, card in (
        (0, "swarm", set_pool("TOR")["Shambling Swarm"]),
        (0, "lions", lea["Savannah Lions"]),
        (1, "bears", lea["Grizzly Bears"]),
        (1, "giant", lea["Hill Giant"]),
    ):
        placed[name] = _W1G8Permanent(card=card)
        game._put_permanent_onto_battlefield(seat, placed[name], None)
    return game, placed


def _w1g8_bolt_the_swarm(game, swarm):
    result = game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[swarm.permanent_id],
    )
    assert result.supported, result.details
    _w1g8_resolve_stack(game)


def _w1g8_body(permanent):
    return permanent.effective_power, permanent.effective_toughness


def test_w1g8_shambling_swarm_dies_and_a_seat_nobody_asks_spreads_its_counters(set_pool):
    """"When this creature dies, distribute three -1/-1 counters among one,
    two, or three target creatures." It compiled, reported supported and
    announced nothing: the handler found one creature on its own and put all
    three counters on it, and a person was never asked. A seat nobody asks
    now announces as a divided spell is proposed — the opponent's creatures,
    spread — and the shares come back at the next end step."""
    game, placed = _w1g8_swarm_table(set_pool)
    _w1g8_bolt_the_swarm(game, placed["swarm"])

    assert "Shambling Swarm: targets Grizzly Bears (2), Hill Giant (1)" in game.log
    game.check_state_based_actions()
    assert not game.is_on_battlefield(placed["bears"]), "2/2 with two -1/-1 counters"
    assert _w1g8_body(placed["giant"]) == (2, 2)
    assert _w1g8_body(placed["lions"]) == (2, 1), "its controller's own is spared"

    # One delayed removal per counter, each bound to its own creature; the
    # Bears' two find nothing (CR 400.7), the Giant's one finds the Giant.
    assert sorted(t.bound_permanent_id for t in game.delayed_triggers) == sorted([
        placed["bears"].permanent_id, placed["bears"].permanent_id,
        placed["giant"].permanent_id,
    ])
    game.resolve_end_step(1)
    _w1g8_resolve_stack(game)
    assert _w1g8_body(placed["giant"]) == (3, 3)
    assert placed["giant"].metadata.get("minus_counters", 0) == 0
    assert not game.delayed_triggers


def test_w1g8_shambling_swarm_asks_its_controller_for_the_division(set_pool):
    """A person is asked which creatures **and** how the three counters are
    divided among them (CR 603.3d, CR 601.2d) — and the dying Swarm itself is
    not on offer, because the ability goes on the stack after it has died.
    Two targets are 2+1 or 1+2, which is the announcer's choice: an answer
    leaving it out is refused, and so is one that does not total three."""
    game, placed = _w1g8_swarm_table(set_pool, humans=(0,))
    bolt = game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[placed["swarm"].permanent_id],
    )
    assert bolt.supported
    game.resolve_top_of_stack()

    (asked,) = game.pending_choices
    assert asked.kind == "trigger_target"
    assert (asked.data["max_targets"], asked.data["division_total"]) == (3, 3)
    assert asked.data["division"] == "chosen"
    offered = {t["permanent_id"] for t in asked.data["targets"]}
    assert placed["swarm"].permanent_id not in offered
    assert offered == {
        placed[name].permanent_id for name in ("lions", "bears", "giant")
    }

    pair = [placed["bears"].permanent_id, placed["giant"].permanent_id]
    assert not game.confirm_trigger_target(0, permanent_ids=pair), "2+1 or 1+2?"
    assert not game.confirm_trigger_target(0, permanent_ids=pair, amounts=[1, 1])
    assert not game.confirm_trigger_target(0, permanent_ids=pair, amounts=[3, 0])
    assert not game.confirm_trigger_target(0, permanent_ids=[]), "one or more"
    assert game.pending_choices == [asked]

    assert game.confirm_trigger_target(0, permanent_ids=pair, amounts=[1, 2])
    _w1g8_resolve_stack(game)
    game.check_state_based_actions()
    assert _w1g8_body(placed["bears"]) == (1, 1)
    assert _w1g8_body(placed["giant"]) == (1, 1)

    game.resolve_end_step(1)
    _w1g8_resolve_stack(game)
    assert _w1g8_body(placed["bears"]) == (2, 2)
    assert _w1g8_body(placed["giant"]) == (3, 3)


def test_w1g8_shambling_swarm_forced_divisions_need_no_amounts(set_pool):
    """One target takes all three and three targets take one apiece — no
    choice is left to make, so an answer naming either needs no division."""
    game, placed = _w1g8_swarm_table(set_pool, humans=(0,))
    game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[placed["swarm"].permanent_id],
    )
    game.resolve_top_of_stack()
    assert game.confirm_trigger_target(0, permanent_id=placed["giant"].permanent_id)
    _w1g8_resolve_stack(game)
    assert _w1g8_body(placed["giant"]) == (0, 0)
    assert _w1g8_body(placed["bears"]) == (2, 2)


def test_w1g8_shambling_swarm_keeps_a_departed_targets_share_out(set_pool):
    """CR 608.2b: a target that has left is illegal and its share goes
    nowhere — the survivor keeps exactly what was announced for it, and the
    ability still resolves for it."""
    game, placed = _w1g8_swarm_table(set_pool, humans=(0,))
    game.players[0].hand.append(set_pool("LEA")["Unsummon"])
    game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[placed["swarm"].permanent_id],
    )
    game.resolve_top_of_stack()
    pair = [placed["bears"].permanent_id, placed["giant"].permanent_id]
    assert game.confirm_trigger_target(0, permanent_ids=pair, amounts=[2, 1])

    # In response, the Bears go back to their owner's hand.
    bounce = game.cast_from_hand(
        0, "Unsummon", target_player_index=1,
        target_permanent_ids=[placed["bears"].permanent_id],
    )
    assert bounce.supported, bounce.details
    _w1g8_resolve_stack(game)

    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]
    assert _w1g8_body(placed["giant"]) == (2, 2)
    assert placed["giant"].metadata.get("minus_counters") == 1

# ==== end W1G8 ======================================================
