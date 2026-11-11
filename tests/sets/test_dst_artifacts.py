"""Darksteel artifacts.

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
# Modular (CR 702.43) on the eleven Arcbound creatures, each driven through
# the real entry seam, a real death (a Bolt, a sacrifice, a -1/-1 counter, a
# combat) and the real trigger; the keyword's own rules tests are
# ``tests/rules/test_dst_w1g1_modular.py``.

from engine import Game as _W1G1Game, PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from engine.named_counters import counters_on as _w1g1_counters_on
from engine.oracle import compile_card_oracle as _w1g1_compile
from engine.targeting import derive_activation_spec as _w1g1_activation_spec
from tests.helpers import declare_attack as _w1g1_declare_attack
from tests.helpers import drive_combat as _w1g1_drive_combat
from tests.helpers import settle as _w1g1_settle


def _w1g1_table(set_pool, *, interactive=(), hand=(), graveyard=()):
    """Two seats on seat 0's first main phase, libraries to draw from."""
    lea = set_pool("LEA")
    game = _W1G1Game(players=[
        _W1G1PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
            graveyard=list(graveyard) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g1_settle(game)
    return game


def _w1g1_put(game, card, seat, *, sick=False):
    """*card* onto *seat*'s battlefield through the entry seam (so a modular
    creature enters with its counters, CR 702.43a)."""
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    _w1g1_settle(game)
    return permanent


def _w1g1_plus(permanent):
    return _w1g1_counters_on(permanent, "+1/+1")


def _w1g1_bolt(game, set_pool, victim, seat=0):
    """Kill *victim* with a real Lightning Bolt and settle the death."""
    game.players[seat].hand.append(set_pool("LEA")["Lightning Bolt"])
    result = game.cast_from_hand(
        seat, "Lightning Bolt", target_permanent_ids=[victim.permanent_id]
    )
    assert result.supported, (result, game.log[-4:])
    _w1g1_settle(game)


def test_w1g1_arcbound_worker_passes_its_counter_on_when_it_dies(set_pool):
    """"Modular 1": a 0/0 that enters a 1/1, and whose death puts its counter
    on target artifact creature — the seat's own, when an AI seat aims it."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool)
    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)
    stinger = _w1g1_put(game, dst["Arcbound Stinger"], 0)
    hybrid = _w1g1_put(game, dst["Arcbound Hybrid"], 1)
    assert _w1g1_plus(worker) == 1
    assert (worker.effective_power, worker.effective_toughness) == (1, 1)

    _w1g1_bolt(game, set_pool, worker)

    assert worker not in game.players[0].battlefield
    assert _w1g1_plus(stinger) == 2 and stinger.effective_power == 2
    assert _w1g1_plus(hybrid) == 2, "the opponent's artifact creature is not aimed at"
    assert "Arcbound Stinger gets a +1/+1 counter (Arcbound Worker)" in game.log


def test_w1g1_arcbound_bruiser_passes_every_counter_it_died_with(set_pool):
    """"Modular 3", and the count is the one it left with (CR 603.10a): a
    fourth counter gained after it entered goes too."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool)
    bruiser = _w1g1_put(game, dst["Arcbound Bruiser"], 0)
    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)
    assert _w1g1_plus(bruiser) == 3
    game.place_pt_counters(bruiser, "+1/+1", 1)
    assert bruiser.effective_toughness == 4

    # Two Bolts: the first leaves a 4/4 with 3 damage, the second kills it.
    _w1g1_bolt(game, set_pool, bruiser)
    assert bruiser in game.players[0].battlefield
    _w1g1_bolt(game, set_pool, bruiser)

    assert bruiser not in game.players[0].battlefield
    assert _w1g1_plus(worker) == 5, "1 of its own and the 4 the Bruiser died with"


def test_w1g1_arcbound_worker_killed_by_a_minus_counter_still_passes_one(set_pool):
    """Every Arcbound's ruling (2006-09-25): killed by -1/-1 counters, modular
    puts "the number of +1/+1 counters on this creature before it left the
    battlefield" — CR 704.5f and 704.5q are one simultaneous check, so the
    annihilation never reaches the creature that died."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool)
    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)
    stinger = _w1g1_put(game, dst["Arcbound Stinger"], 0)

    game.place_pt_counters(worker, "-1/-1", 1)
    _w1g1_settle(game)

    assert worker not in game.players[0].battlefield
    assert _w1g1_plus(stinger) == 2


def test_w1g1_arcbound_crusher_grows_as_artifacts_enter(set_pool):
    """"Trample / Whenever another artifact enters, put a +1/+1 counter on this
    creature. / Modular 1" — the entry of another artifact grows it, its own
    entry does not, and it dies passing every counter it had."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool)
    crusher = _w1g1_put(game, dst["Arcbound Crusher"], 0)
    assert _w1g1_plus(crusher) == 1, "its own entry is not 'another artifact'"
    assert game._has_keyword(crusher, "trample")

    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)
    assert _w1g1_plus(crusher) == 2

    _w1g1_bolt(game, set_pool, crusher)
    assert crusher not in game.players[0].battlefield
    assert _w1g1_plus(worker) == 3


def test_w1g1_arcbound_fiend_takes_a_counter_from_the_best_holder(set_pool):
    """"At the beginning of your upkeep, you may move a +1/+1 counter from
    target creature onto this creature." An AI seat aims it at the opposing
    creature holding counters, not at the first creature offered (CR 122.5:
    a move from a creature with none is nothing)."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    fiend = _w1g1_put(game, dst["Arcbound Fiend"], 0)
    _w1g1_put(game, lea["Grizzly Bears"], 1)
    hybrid = _w1g1_put(game, dst["Arcbound Hybrid"], 1)
    assert _w1g1_plus(fiend) == 3 and game._has_keyword(fiend, "fear")

    game.resolve_upkeep(0)
    _w1g1_settle(game)

    assert _w1g1_plus(fiend) == 4 and fiend.effective_power == 4
    assert _w1g1_plus(hybrid) == 1 and hybrid.effective_toughness == 1
    assert "Moved 1 +1/+1 counter(s) from Arcbound Hybrid onto Arcbound Fiend" in game.log


def test_w1g1_arcbound_fiend_moves_nothing_off_a_creature_without_one(set_pool):
    """The card's ruling (2004-12-01): the target "doesn't have to have any
    +1/+1 counters on it. If it doesn't … nothing happens" — and targeting
    itself moves nothing (CR 122.5, the same object twice). Driven as an
    interactive seat through the trigger's target prompt and the "may"."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    for pick in ("bears", "itself"):
        game = _w1g1_table(set_pool, interactive=(0,))
        fiend = _w1g1_put(game, dst["Arcbound Fiend"], 0)
        bears = _w1g1_put(game, lea["Grizzly Bears"], 1)
        game.resolve_upkeep(0)
        owed = _w1g1_settle(game, defaults=False)
        assert owed is not None and owed.kind == "trigger_target"
        aimed = bears if pick == "bears" else fiend
        game.confirm_trigger_target(0, permanent_id=aimed.permanent_id)
        owed = _w1g1_settle(game, defaults=False)
        assert owed is not None and owed.kind == "optional_pay"
        game.confirm_optional_pay(0, accept=True)
        _w1g1_settle(game)
        assert _w1g1_plus(fiend) == 3, pick
        assert _w1g1_plus(bears) == 0, pick


def test_w1g1_arcbound_hybrid_attacks_the_turn_it_enters(set_pool):
    """"Haste / Modular 2": a 2/2 that is summoning sick and attacks anyway."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool)
    hybrid = _w1g1_put(game, dst["Arcbound Hybrid"], 0, sick=True)
    assert (hybrid.effective_power, hybrid.effective_toughness) == (2, 2)

    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        0, [game.battlefield_index_of(hybrid)], defending_player_index=1
    )
    assert ok, why
    _w1g1_drive_combat(game)
    assert game.players[1].life == 18


def test_w1g1_arcbound_lancer_strikes_first_as_a_4_4(set_pool):
    """"First strike / Modular 4": a 4/4 first striker kills a 6/4 blocker
    before the blocker deals its damage."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    lancer = _w1g1_put(game, dst["Arcbound Lancer"], 0)
    blocker = _w1g1_put(game, lea["Craw Wurm"], 1)
    assert (lancer.effective_power, lancer.effective_toughness) == (4, 4)
    assert game._has_keyword(lancer, "first strike")

    _w1g1_declare_attack(game, 0, blocks={0: 0})
    _w1g1_drive_combat(game)

    assert lancer in game.players[0].battlefield and lancer.damage_marked == 0
    assert blocker not in game.players[1].battlefield


def test_w1g1_arcbound_overseer_feeds_only_its_own_modular_creatures(set_pool):
    """"At the beginning of your upkeep, put a +1/+1 counter on each creature
    you control with modular." "With modular" is the word CR 702.43a names,
    asked of layer 6: a creature without it and an opponent's Arcbound get
    nothing."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    overseer = _w1g1_put(game, dst["Arcbound Overseer"], 0)
    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    theirs = _w1g1_put(game, dst["Arcbound Stinger"], 1)
    assert _w1g1_plus(overseer) == 6

    game.resolve_upkeep(0)
    _w1g1_settle(game)

    assert _w1g1_plus(overseer) == 7 and _w1g1_plus(worker) == 2
    assert _w1g1_plus(bears) == 0 and _w1g1_plus(theirs) == 1


def test_w1g1_arcbound_ravager_eats_an_arcbound_and_its_modular(set_pool):
    """"Sacrifice an artifact: Put a +1/+1 counter on this creature." The
    sacrificed Worker's modular trigger aims at the Ravager too: one counter
    for the activation and one for the Worker's own."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool)
    ravager = _w1g1_put(game, dst["Arcbound Ravager"], 0)
    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)

    result = game.activate_permanent_ability(
        0, "Arcbound Ravager", cost_permanent_ids=[worker.permanent_id]
    )
    assert result.supported, result
    _w1g1_settle(game)

    assert worker not in game.players[0].battlefield
    assert worker.card in game.players[0].graveyard
    assert _w1g1_plus(ravager) == 3 and ravager.effective_power == 3


def test_w1g1_arcbound_reclaimer_stacks_an_artifact_card(set_pool):
    """"Remove a +1/+1 counter from this creature: Put target artifact card
    from your graveyard on top of your library." The picker offers the
    artifact card and not the creature card beside it, and the cost is a
    counter off the Reclaimer."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g1_table(
        set_pool, graveyard=[lea["Grizzly Bears"], dst["Arcbound Worker"]],
    )
    reclaimer = _w1g1_put(game, dst["Arcbound Reclaimer"], 0)
    ability = _w1g1_compile(reclaimer.card).activated_abilities[0]
    spec = _w1g1_activation_spec(ability)
    assert spec["card_type"] == "artifact" and spec["own_graveyard_only"]

    result = game.activate_permanent_ability(
        0, "Arcbound Reclaimer", target_graveyard_indices=[1]
    )
    assert result.supported, result
    _w1g1_settle(game)

    assert _w1g1_plus(reclaimer) == 1
    assert game.players[0].library[0].name == "Arcbound Worker"
    assert [c.name for c in game.players[0].graveyard] == ["Grizzly Bears"]


def test_w1g1_arcbound_slith_grows_on_combat_damage_to_a_player(set_pool):
    """"Whenever this creature deals combat damage to a player, put a +1/+1
    counter on it." Unblocked, the 1/1 hits for 1 and becomes a 2/2."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool)
    slith = _w1g1_put(game, dst["Arcbound Slith"], 0)

    _w1g1_declare_attack(game, 0)
    _w1g1_drive_combat(game)

    assert game.players[1].life == 19
    assert _w1g1_plus(slith) == 2 and slith.effective_power == 2


def test_w1g1_arcbound_stinger_flies_and_passes_its_counter(set_pool):
    """"Flying / Modular 1": a 1/1 flier whose death feeds the next one."""
    dst = set_pool("DST")
    game = _w1g1_table(set_pool)
    stinger = _w1g1_put(game, dst["Arcbound Stinger"], 0)
    worker = _w1g1_put(game, dst["Arcbound Worker"], 0)
    assert game._has_keyword(stinger, "flying") and _w1g1_plus(stinger) == 1

    _w1g1_bolt(game, set_pool, stinger)

    assert _w1g1_plus(worker) == 2

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
