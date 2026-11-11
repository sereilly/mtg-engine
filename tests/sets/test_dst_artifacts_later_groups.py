"""Darksteel artifacts — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_card(set_pool, name):
    return next(
        pool[name] for pool in (set_pool("DST"), set_pool("MRD"), set_pool("LEA"))
        if name in pool
    )  # _w1g7_card


def _w1g7_table(set_pool, *, hand=(), opponent_hand=(), mine=(), theirs=(),
                interactive=(), enforce=False):
    """Seat 0 active in its first main phase, every permanent past summoning
    sickness and untapped; costs enforced only when asked."""
    game = _W1G7Game(players=[
        _W1G7PlayerState(name="W1G7-A",
                         hand=[_w1g7_card(set_pool, n) for n in hand],
                         library=[_w1g7_card(set_pool, "Forest") for _ in range(10)]),
        _W1G7PlayerState(name="W1G7-B",
                         hand=[_w1g7_card(set_pool, n) for n in opponent_hand],
                         library=[_w1g7_card(set_pool, "Forest") for _ in range(10)]),
    ])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set(interactive)
    rows = []
    for seat, names in ((0, mine), (1, theirs)):
        row = []
        for name in names:
            row.append(_w1g7_put(game, seat, _w1g7_card(set_pool, name)))
        rows.append(row)
    game.start_turn(0)
    _w1g7_settle(game)
    return game, rows[0], rows[1]  # _w1g7_table


def _w1g7_put(game, seat, card):
    perm = _W1G7Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm  # _w1g7_put


def test_w1g7_drill_skimmer_has_shroud_only_beside_another_artifact_creature(
    set_pool,
):
    """"This creature has shroud as long as you control another artifact
    creature." Alone it is a legal target — "another" (CR 113.7) never counts
    itself; beside a Myr Moonvessel it has shroud and the Bolt is refused; the
    Moonvessel itself gains nothing; with the Moonvessel gone the Bolt is
    legal again and kills it."""
    game, mine, _theirs = _w1g7_table(
        set_pool, opponent_hand=["Lightning Bolt", "Lightning Bolt"],
        mine=["Drill-Skimmer"],
    )
    skimmer = mine[0]
    assert not game._has_keyword(skimmer, "shroud")
    moonvessel = _w1g7_put(game, 0, _w1g7_card(set_pool, "Myr Moonvessel"))
    _w1g7_settle(game)
    assert game._has_keyword(skimmer, "shroud")
    assert not game._has_keyword(moonvessel, "shroud")
    game.active_player_index = 1
    refused = game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[skimmer.permanent_id]
    )
    assert not refused.supported and "illegal target" in refused.details
    bolt = game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[moonvessel.permanent_id]
    )
    assert bolt.supported, bolt.details
    _w1g7_settle(game)
    assert not game.is_on_battlefield(moonvessel)
    assert not game._has_keyword(skimmer, "shroud")
    game.players[1].hand.append(_w1g7_card(set_pool, "Lightning Bolt"))
    finisher = game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[skimmer.permanent_id]
    )
    assert finisher.supported, finisher.details
    _w1g7_settle(game)
    assert not game.is_on_battlefield(skimmer)


def test_w1g7_drill_skimmer_gaining_shroud_in_response_counters_the_bolt(set_pool):
    """The Bolt is aimed at a lone Skimmer; before it resolves a second
    artifact creature arrives, the Skimmer has shroud, and its one target is
    illegal (CR 608.2b): the Bolt does nothing. Two Skimmers shroud each
    other."""
    game, mine, _theirs = _w1g7_table(
        set_pool, opponent_hand=["Lightning Bolt"], mine=["Drill-Skimmer"],
    )
    skimmer = mine[0]
    game.active_player_index = 1
    bolt = game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[skimmer.permanent_id]
    )
    assert bolt.supported, bolt.details
    assert game.stack
    second = _w1g7_put(game, 0, _w1g7_card(set_pool, "Drill-Skimmer"))
    _w1g7_settle(game)
    assert game.is_on_battlefield(skimmer) and skimmer.damage_marked == 0
    assert game._has_keyword(skimmer, "shroud")
    assert game._has_keyword(second, "shroud")


# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
