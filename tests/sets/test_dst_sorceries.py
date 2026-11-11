"""Darksteel sorceries.

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


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.
#
# Counters that move: Aether Snap's sweep of every kind and Dismantle's
# "that many" read off the artifact it destroyed.

from engine import Game as _W1G1Game, PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from engine.named_counters import add_counters as _w1g1_add_counters
from engine.named_counters import counter_kinds_on as _w1g1_kinds
from engine.named_counters import counters_on as _w1g1_counters_on
from tests.helpers import settle as _w1g1_settle


def _w1g1_table(set_pool, *, hand=(), interactive=()):
    lea = set_pool("LEA")
    game = _W1G1Game(players=[
        _W1G1PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g1_settle(game)
    return game


def _w1g1_put(game, card, seat):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g1_settle(game)
    return permanent


def test_w1g1_aether_snap_removes_every_kind_of_counter_and_exiles_tokens(set_pool):
    """"Remove all counters from all permanents and exile all tokens." Its
    ruling (2004-12-01): "no matter what kind they are" — +1/+1, -1/-1 and
    charge alike, on both sides — and the Spawn token a Spawning Pit made is
    exiled. The Arcbound creatures, 0/0 once their counters are gone, die
    with none, so their modular puts nothing anywhere."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool, hand=[dst["Aether Snap"]])
    pit = _w1g1_put(game, dst["Spawning Pit"], 0)
    _w1g1_add_counters(pit, "charge", 3)
    made = game.activate_permanent_ability(0, "Spawning Pit", ability_index=1)
    assert made.supported, made
    _w1g1_settle(game)
    spawn = next(p for p in game.players[0].battlefield if p.metadata.get("is_token"))
    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)
    coretapper = _w1g1_put(game, dst["Coretapper"], 0)
    bruiser = _w1g1_put(game, dst["Arcbound Bruiser"], 1)
    karstoderm = _w1g1_put(game, dst["Karstoderm"], 1)
    game.place_pt_counters(karstoderm, "-1/-1", 1)
    assert _w1g1_counters_on(pit, "charge") == 1

    result = game.cast_from_hand(0, "Aether Snap")
    assert result.supported, result
    _w1g1_settle(game)

    for permanent in game.all_permanents():
        assert _w1g1_kinds(permanent) == {}, permanent.card.name
    assert pit in game.players[0].battlefield
    assert spawn not in game.players[0].battlefield
    assert not any(p.metadata.get("is_token") for p in game.all_permanents())
    assert worker not in game.players[0].battlefield
    assert bruiser not in game.players[1].battlefield
    assert karstoderm not in game.players[1].battlefield
    # The Worker's modular still named the surviving Coretapper, with nothing
    # to give it.
    assert coretapper in game.players[0].battlefield
    assert "Arcbound Worker: no counters to place" in game.log


def test_w1g1_dismantle_puts_that_many_counters_on_an_artifact_you_control(set_pool):
    """"Destroy target artifact. If that artifact had counters on it, put that
    many +1/+1 counters or charge counters on an artifact you control." The
    count is what it had as it was destroyed (CR 608.2h) — the Bruiser's
    three — and a seat nobody asks takes the +1/+1 option on its creature."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool, hand=[dst["Dismantle"]])
    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)
    bruiser = _w1g1_put(game, dst["Arcbound Bruiser"], 1)

    result = game.cast_from_hand(0, "Dismantle", target_permanent_ids=[bruiser.permanent_id])
    assert result.supported, result
    _w1g1_settle(game)

    assert bruiser not in game.players[1].battlefield
    assert _w1g1_counters_on(worker, "+1/+1") == 4
    # The Bruiser's own modular had only my Worker to name, and its seat
    # declined to feed an opponent's creature.
    assert "P1 declined Arcbound Bruiser (it would help an opponent's permanent)" in game.log


def test_w1g1_dismantle_asks_which_counter_and_which_artifact(set_pool):
    """Its ruling (2020-08-07): "When Dismantle resolves, you choose which type
    of counters you want and choose an artifact you control" — nothing is
    targeted but the destroyed artifact. Driven as an interactive seat: the
    kind, then the artifact, and charge counters on a noncreature one."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool, hand=[dst["Dismantle"]], interactive=(0,))
    coretapper = _w1g1_put(game, dst["Coretapper"], 0)
    pit = _w1g1_put(game, dst["Spawning Pit"], 0)
    bruiser = _w1g1_put(game, dst["Arcbound Bruiser"], 1)

    game.cast_from_hand(0, "Dismantle", target_permanent_ids=[bruiser.permanent_id])
    owed = _w1g1_settle(game, defaults=False)
    assert owed is not None and owed.kind == "mode_choice"
    assert owed.data["labels"] == ["a +1/+1 counter", "a charge counter"]
    game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    owed = _w1g1_settle(game, defaults=False)
    assert owed is not None and owed.kind == "permanent_choice"
    assert owed.data["prompt"] == "Choose an artifact to put a charge counter on."
    game.confirm_permanent_choice(0, pit.permanent_id)
    _w1g1_settle(game)

    assert _w1g1_counters_on(pit, "charge") == 3
    assert _w1g1_kinds(coretapper) == {}


def test_w1g1_dismantle_on_an_artifact_with_no_counters_puts_none(set_pool):
    """No counters on the destroyed artifact: the condition is false and
    nothing is asked or placed."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool, hand=[dst["Dismantle"]], interactive=(0,))
    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)
    coretapper = _w1g1_put(game, dst["Coretapper"], 1)

    game.cast_from_hand(0, "Dismantle", target_permanent_ids=[coretapper.permanent_id])
    assert _w1g1_settle(game, defaults=False) is None

    assert coretapper not in game.players[1].battlefield
    assert _w1g1_counters_on(worker, "+1/+1") == 1


def test_w1g1_dismantle_still_places_when_the_artifact_survives(set_pool):
    """Its ruling (2020-08-07): "If the target is legal but not destroyed (most
    likely because it has indestructible), you do put counters on an
    artifact." Darksteel Reactor keeps its two charge counters and two more
    land on the Worker."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool, hand=[dst["Dismantle"]])
    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)
    reactor = _w1g1_put(game, dst["Darksteel Reactor"], 1)
    _w1g1_add_counters(reactor, "charge", 2)

    game.cast_from_hand(0, "Dismantle", target_permanent_ids=[reactor.permanent_id])
    _w1g1_settle(game)

    assert reactor in game.players[1].battlefield
    assert _w1g1_counters_on(reactor, "charge") == 2
    assert _w1g1_counters_on(worker, "+1/+1") == 3

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

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
