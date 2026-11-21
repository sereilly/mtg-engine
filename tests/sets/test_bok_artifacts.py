"""Betrayers of Kamigawa artifacts.

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
#
# That Which Was Taken's counter-keyed static grant: "Each permanent with a
# divinity counter on it has indestructible" (``LordBuffFilter``'s
# ``with_named_counter``, asked of the named-counter store at every read).
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.named_counters import counters_on as _w1g6_counters_on
from tests.helpers import settle as _w1g6_settle


def _w1g6_put(game, seat, card):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g6_table(set_pool, *, hand=(), mine=(), theirs=()):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="Alice", hand=list(hand), library=[lea["Island"]] * 10),
        _W1G6PlayerState(name="Bob", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    placed = [_w1g6_put(game, 0, card) for card in mine]
    placed += [_w1g6_put(game, 1, card) for card in theirs]
    game.start_turn(0)
    _w1g6_settle(game)
    return game, placed


def test_w1g6_that_which_was_taken_shields_what_holds_a_divinity_counter(set_pool):
    """"{4}, {T}: Put a divinity counter on target permanent other than That
    Which Was Taken." then "Each permanent with a divinity counter on it has
    indestructible": an opponent's Hill Giant given a counter survives Terror;
    the Artifact itself is not a legal target; once That Which Was Taken is
    destroyed the counter stays but shields nothing (2013-07-01 ruling: "only
    while That Which Was Taken is on the battlefield"), and Terror kills."""
    lea = set_pool("LEA")
    bok = set_pool("BOK")
    game, (taken, giant) = _w1g6_table(
        set_pool, hand=[lea["Terror"], lea["Terror"], lea["Shatter"]],
        mine=[bok["That Which Was Taken"]], theirs=[lea["Hill Giant"]],
    )
    refused = game.activate_permanent_ability(
        0, "That Which Was Taken", target_permanent_ids=[taken.permanent_id],
    )
    assert not refused.supported
    assert game.activate_permanent_ability(
        0, "That Which Was Taken", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert _w1g6_counters_on(giant, "divinity") == 1 and taken.tapped
    assert giant.has_keyword("indestructible")
    assert not taken.has_keyword("indestructible")

    assert game.cast_from_hand(
        0, "Terror", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert giant in game.controlled_by(1), game.log

    assert game.cast_from_hand(
        0, "Shatter", target_permanent_ids=[taken.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert taken not in game.controlled_by(0)
    assert _w1g6_counters_on(giant, "divinity") == 1
    assert not giant.has_keyword("indestructible")
    assert game.cast_from_hand(
        0, "Terror", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert giant not in game.controlled_by(1), game.log


def test_w1g6_that_which_was_taken_loses_the_shield_with_the_counter(set_pool):
    """The set is re-derived from the board (CR 611.3a): a permanent whose
    divinity counter Spinal Parasite removes ("Remove a counter from target
    permanent") stops being indestructible."""
    lea = set_pool("LEA")
    bok = set_pool("BOK")
    game, (taken, bears) = _w1g6_table(
        set_pool, mine=[bok["That Which Was Taken"], lea["Grizzly Bears"]],
    )
    # A 0/0 with sunburst: placed with the two counters it removes.
    parasite = _W1G6Permanent(card=set_pool("5DN")["Spinal Parasite"])
    game._put_permanent_onto_battlefield(0, parasite, None)
    from engine.named_counters import add_counters as _w1g6_add_counters

    _w1g6_add_counters(parasite, "+1/+1", 2)
    parasite.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    assert game.activate_permanent_ability(
        0, "That Which Was Taken", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert bears.has_keyword("indestructible")
    assert game.activate_permanent_ability(
        0, "Spinal Parasite", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert _w1g6_counters_on(bears, "divinity") == 0, game.log
    assert not bears.has_keyword("indestructible")

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
