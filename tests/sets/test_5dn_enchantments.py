"""Fifth Dawn enchantments, Auras included.

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

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import drive_combat as _w1g6_drive_combat
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, hand=()):
    plains = set_pool("LEA")["Plains"]
    game = _W1G6Game(players=[
        _W1G6PlayerState(name=f"P{seat}", hand=list(hand) if seat == 0 else [],
                         library=[plains] * 20)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g6_settle(game)
    return game


def _w1g6_put(game, seat, card):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g6_settle(game)
    return permanent


def _w1g6_counters(permanent):
    return (permanent.effective_power, permanent.effective_toughness)


def test_w1g6_rite_of_passage_grows_a_creature_that_survives_the_damage(set_pool):
    """'Whenever a creature you control is dealt damage, put a +1/+1 counter
    on it. (It must survive the damage to get the counter.)' The counter goes
    on the damaged creature — the object the event froze, not the
    enchantment — as the trigger resolves, so one the damage killed gets
    nothing, and an opponent's damaged creature triggers nothing."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[lea["Lightning Bolt"], lea["Lightning Bolt"]])
    _w1g6_put(game, 0, fdn["Rite of Passage"])
    sorcerer = _w1g6_put(game, 0, lea["Prodigal Sorcerer"])
    giant = _w1g6_put(game, 0, lea["Hill Giant"])
    bears = _w1g6_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g6_put(game, 1, lea["Grizzly Bears"])

    # Survives the ping: one counter, on the Giant.
    result = game.activate_permanent_ability(
        0, "Prodigal Sorcerer", permanent_index=game.battlefield_index_of(sorcerer),
        target_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result
    _w1g6_settle(game)
    assert _w1g6_counters(giant) == (4, 4)
    assert _w1g6_counters(sorcerer) == (1, 1)

    # Lethal: no counter, and no other creature takes it.
    result = game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
    assert result.supported, result
    _w1g6_settle(game)
    assert not game.is_on_battlefield(bears)
    assert _w1g6_counters(giant) == (4, 4)
    assert "Rite of Passage: the permanent it names is gone" in game.log

    # An opponent's creature: no trigger at all.
    resolved = game.log.count("Rite of Passage ability resolved")
    result = game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[theirs.permanent_id])
    assert result.supported, result
    _w1g6_settle(game)
    assert not game.is_on_battlefield(theirs)
    assert game.log.count("Rite of Passage ability resolved") == resolved


def test_w1g6_rite_of_passage_one_counter_for_one_simultaneous_dealing(set_pool):
    """Two sources at once is one trigger and one counter (ruling
    2004-12-01): a Force of Nature (8/8) blocked by two Grizzly Bears takes 4 at
    once and survives as a 9/9, not a 10/10."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g6_table(set_pool)
    _w1g6_put(game, 0, fdn["Rite of Passage"])
    wurm = _w1g6_put(game, 0, lea["Force of Nature"])
    blockers = [_w1g6_put(game, 1, lea["Grizzly Bears"]) for _ in range(2)]
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [game.battlefield_index_of(wurm)], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    blocks = {game.battlefield_index_of(b): game.battlefield_index_of(wurm) for b in blockers}
    ok, why = game.declare_blockers(1, blocks)
    assert ok, why
    _w1g6_drive_combat(game)
    assert game.is_on_battlefield(wurm)
    assert _w1g6_counters(wurm) == (9, 9)

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================
