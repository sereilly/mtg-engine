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
#
# Imprint, copies cast for free, and the hand. Each card is driven through
# the real entry points: the cast, its entry trigger on the stack, the "may"
# answered by an interactive seat and by a seat nobody asks, then the linked
# ability (CR 607.2a) — a combat for Spellbinder, an upkeep for Panoptic
# Mirror, an activation for Death-Mask Duplicant and Aether Vial.

from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from tests.helpers import declare_attack as _w1g3_declare_attack
from tests.helpers import drive_combat as _w1g3_drive_combat
from tests.helpers import settle as _w1g3_settle


def _w1g3_table(hand=(), *, interactive=False, library=(), bob_library=()):
    alice = _W1G3PlayerState(name="Alice", hand=list(hand), library=list(library))
    bob = _W1G3PlayerState(name="Bob", library=list(bob_library))
    game = _W1G3Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.priority_player_index = 0
    game._set_phase_and_step("precombat_main", None)
    return game, alice, bob


def _w1g3_put(game, seat, card):
    permanent = _W1G3Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g3_named(game, name):
    return next(p for p in game.all_permanents() if p.card.name == name)


def _w1g3_imprint_from_hand(game, alice, source_name, card_name):
    """Cast *source_name* for an interactive seat 0, take its imprint offer
    and pick *card_name* out of the hand."""
    assert game.cast_from_hand(0, source_name).supported
    offer = _w1g3_settle(game, defaults=False)
    assert offer is not None and offer.kind == "optional_pay"
    assert game.confirm_optional_pay(0, accept=True)
    pick = _w1g3_settle(game, defaults=False)
    assert pick is not None and pick.kind == "exile_from_hand_choice"
    slot = next(i for i, c in enumerate(alice.hand) if c.name == card_name)
    assert slot in game.live_exile_from_hand_choices(pick)
    assert game.confirm_exile_from_hand_choice(0, slot)
    _w1g3_settle(game)
    return _w1g3_named(game, source_name)


def _w1g3_spellbinder_on_bears(set_pool, *, interactive):
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g3_table(
        [dst["Spellbinder"], lea["Lightning Bolt"], lea["Giant Growth"]],
        interactive=True,
    )
    bears = _w1g3_put(game, 0, lea["Grizzly Bears"])
    binder = _w1g3_imprint_from_hand(game, alice, "Spellbinder", "Lightning Bolt")
    assert [c.name for c in alice.exile] == ["Lightning Bolt"]
    assert [c.name for c in alice.hand] == ["Giant Growth"], "an instant, and only one"
    game.interactive_seats = {0} if interactive else set()
    equip = game.activate_permanent_ability(
        0, "Spellbinder", permanent_index=game.battlefield_index_of(binder),
        ability_index=0, target_permanent_ids=[bears.permanent_id],
    )
    assert equip.supported, equip.details
    _w1g3_settle(game)
    assert binder.metadata.get("attached_to") is bears
    return game, alice, bob, binder, bears


def test_w1g3_spellbinder_imprints_an_instant_as_it_enters(set_pool):
    """"Imprint — When this Equipment enters, you may exile an instant card
    from your hand." The entry trigger offers the exile (an optional pay),
    and the pick is held to instants: Giant Growth and Lightning Bolt are
    offered, the Equipment itself was cast and a creature card is not."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g3_table(
        [dst["Spellbinder"], lea["Lightning Bolt"], lea["Grizzly Bears"]],
        interactive=True,
    )
    assert game.cast_from_hand(0, "Spellbinder").supported
    offer = _w1g3_settle(game, defaults=False)
    assert offer is not None and offer.kind == "optional_pay"
    assert game.confirm_optional_pay(0, accept=True)
    pick = _w1g3_settle(game, defaults=False)
    assert pick is not None and pick.kind == "exile_from_hand_choice"
    offered = {alice.hand[i].name for i in game.live_exile_from_hand_choices(pick)}
    assert offered == {"Lightning Bolt"}
    # A declined imprint exiles nothing (the "may").
    game2, alice2, _ = _w1g3_table(
        [dst["Spellbinder"], lea["Lightning Bolt"]], interactive=True,
    )
    assert game2.cast_from_hand(0, "Spellbinder").supported
    offer = _w1g3_settle(game2, defaults=False)
    assert offer is not None and offer.kind == "optional_pay"
    assert game2.confirm_optional_pay(0, accept=False)
    _w1g3_settle(game2)
    assert alice2.exile == [] and [c.name for c in alice2.hand] == ["Lightning Bolt"]


def test_w1g3_spellbinder_casts_a_copy_when_the_equipped_creature_connects(set_pool):
    """"Whenever equipped creature deals combat damage to a player, you may
    copy the exiled card. If you do, you may cast the copy without paying its
    mana cost." Grizzly Bears carries it into Bob: 2 combat damage, then the
    copied Bolt (CR 707.12, cast during the trigger's resolution) for 3; the
    imprinted Bolt stays exiled and the copy ceases to exist (CR 707.10a)."""
    game, alice, bob, binder, bears = _w1g3_spellbinder_on_bears(
        set_pool, interactive=True,
    )
    _w1g3_declare_attack(game, 0)
    _w1g3_drive_combat(game, through="combat_damage", defaults=False)
    offer = _w1g3_settle(game, defaults=False)
    assert offer is not None and offer.kind == "copy_cast"
    assert offer.data["card_name"] == "Lightning Bolt"
    assert bob.life == 18, "the combat damage is dealt before the copy"
    assert game.confirm_copy_cast(0, True, target_player_index=1)
    _w1g3_settle(game)
    assert bob.life == 15
    assert [c.name for c in alice.exile] == ["Lightning Bolt"]
    assert alice.graveyard == [], "the copy went nowhere"
    assert "cast a copy of Lightning Bolt without paying its mana cost (Spellbinder)" in (
        " ".join(game.log)
    )


def test_w1g3_spellbinder_offer_answered_by_a_seat_nobody_asks(set_pool):
    """The same combat at a table nobody sits at: the rehearsed chooser
    (``ai_policy.choose_copy_cast``) takes the copy and aims it at Bob."""
    game, alice, bob, binder, bears = _w1g3_spellbinder_on_bears(
        set_pool, interactive=False,
    )
    _w1g3_declare_attack(game, 0)
    _w1g3_drive_combat(game)
    assert bob.life == 15
    assert [c.name for c in alice.exile] == ["Lightning Bolt"]


def test_w1g3_spellbinder_does_nothing_when_unattached_or_blocked(set_pool):
    """Equipped creature dealing no combat damage to a player — blocked by a
    wall — sets nothing off; and attaching it again is no second imprint
    (the ruling: it imprints only once, when it enters)."""
    lea = set_pool("LEA")
    game, alice, bob, binder, bears = _w1g3_spellbinder_on_bears(
        set_pool, interactive=True,
    )
    _w1g3_put(game, 1, lea["Wall of Stone"])
    _w1g3_declare_attack(game, 0, blocks={0: 0})
    _w1g3_drive_combat(game)
    assert "Bob declared 1 blocker(s)" in game.log
    assert bob.life == 20 and game.pending_choices == []
    assert [c.name for c in alice.exile] == ["Lightning Bolt"]


def _w1g3_vial_with(set_pool, charge, hand, *, interactive=False):
    from engine.named_counters import add_counters

    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g3_table([lea[name] for name in hand], interactive=interactive)
    vial = _w1g3_put(game, 0, dst["Aether Vial"])
    if charge:
        add_counters(vial, "charge", charge)
    return game, alice, vial


def test_w1g3_aether_vial_puts_the_creature_its_counters_name(set_pool):
    """"{T}: You may put a creature card with mana value equal to the number
    of charge counters on this artifact from your hand onto the battlefield."
    Two counters: the pick offers Grizzly Bears alone — not Hill Giant (4),
    Llanowar Elves (1) or the land — and the Bears enter without being cast
    (no spell on the stack)."""
    game, alice, vial = _w1g3_vial_with(
        set_pool, 2, ["Grizzly Bears", "Hill Giant", "Llanowar Elves", "Forest"],
        interactive=True,
    )
    assert game.activate_permanent_ability(
        0, "Aether Vial", permanent_index=game.battlefield_index_of(vial),
        ability_index=0,
    ).supported
    offer = _w1g3_settle(game, defaults=False)
    assert offer is not None and offer.kind == "optional_pay", "the printed may"
    assert game.confirm_optional_pay(0, accept=True)
    pick = _w1g3_settle(game, defaults=False)
    assert pick is not None and pick.kind == "put_from_hand_choice"
    offered = [alice.hand[i].name for i in game.live_put_from_hand_choices(pick)]
    assert offered == ["Grizzly Bears"]
    hill = next(i for i, c in enumerate(alice.hand) if c.name == "Hill Giant")
    assert not game.confirm_put_from_hand_choice(0, hill), "a 4 is refused"
    bears = next(i for i, c in enumerate(alice.hand) if c.name == "Grizzly Bears")
    assert game.confirm_put_from_hand_choice(0, bears)
    _w1g3_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Aether Vial", "Grizzly Bears"]
    assert vial.tapped
    assert not any("cast Grizzly Bears" in line for line in game.log)


def test_w1g3_aether_vial_counts_its_counters_as_it_resolves(set_pool):
    """The count is read at resolution, and from the Vial as it last existed
    once it has left (the 2017-11-17 ruling): one counter and the Vial
    destroyed in response still puts the one-drop in. With no counter the
    activation finds nothing (a land is no creature card, and nothing in the
    hand has mana value 0)."""
    game, alice, vial = _w1g3_vial_with(
        set_pool, 1, ["Grizzly Bears", "Llanowar Elves"],
    )
    assert game.queue_permanent_ability(
        0, "Aether Vial", permanent_index=game.battlefield_index_of(vial),
        ability_index=0,
    ).supported
    game.remove_from_battlefield(vial)
    _w1g3_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Llanowar Elves"]

    game, alice, vial = _w1g3_vial_with(set_pool, 0, ["Grizzly Bears", "Forest"])
    assert game.activate_permanent_ability(
        0, "Aether Vial", permanent_index=game.battlefield_index_of(vial),
        ability_index=0,
    ).supported
    _w1g3_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Aether Vial"]
    assert "has no card Aether Vial could put onto the battlefield" in " ".join(game.log)


def test_w1g3_aether_vial_upkeep_counter_and_a_seat_nobody_asks(set_pool):
    """"At the beginning of your upkeep, you may put a charge counter on this
    artifact." The upkeep puts the first counter on; a seat nobody asks then
    puts its one-drop in with the activation's default answers."""
    from engine.named_counters import counters_on

    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g3_table(
        [lea["Llanowar Elves"]], library=[lea["Forest"]] * 3,
        bob_library=[lea["Forest"]] * 3,
    )
    vial = _w1g3_put(game, 0, dst["Aether Vial"])
    game.start_turn(0)
    _w1g3_settle(game)
    assert counters_on(vial, "charge") == 1
    assert game.activate_permanent_ability(
        0, "Aether Vial", permanent_index=game.battlefield_index_of(vial),
        ability_index=0,
    ).supported
    _w1g3_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Aether Vial", "Llanowar Elves"]


def _w1g3_mirror_imprint(game, mirror, name, x):
    """Activate Panoptic Mirror's imprint for an interactive seat 0 with X =
    *x* and exile *name*; returns the names the pick offered."""
    alice = game.players[0]
    mirror.tapped = False
    assert game.activate_permanent_ability(
        0, "Panoptic Mirror", permanent_index=game.battlefield_index_of(mirror),
        ability_index=0, x_value=x,
    ).supported
    offer = _w1g3_settle(game, defaults=False)
    assert offer is not None and offer.kind == "optional_pay"
    assert game.confirm_optional_pay(0, accept=True)
    pick = _w1g3_settle(game, defaults=False)
    assert pick is not None and pick.kind == "exile_from_hand_choice"
    offered = [alice.hand[i].name for i in game.live_exile_from_hand_choices(pick)]
    slot = next(i for i, c in enumerate(alice.hand) if c.name == name)
    assert game.confirm_exile_from_hand_choice(0, slot)
    _w1g3_settle(game)
    return offered


def _w1g3_mirror_with(set_pool, imprints, *, hand_extra=()):
    """Panoptic Mirror on Alice's side with each of *imprints* (name, X)
    exiled by its own activation; Alice interactive."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    names = [name for name, _x in imprints] + list(hand_extra)
    game, alice, bob = _w1g3_table(
        [lea[name] for name in names], interactive=True,
        library=[lea["Island"]] * 6, bob_library=[lea["Island"]] * 6,
    )
    mirror = _w1g3_put(game, 0, dst["Panoptic Mirror"])
    for name, x in imprints:
        _w1g3_mirror_imprint(game, mirror, name, x)
    return game, alice, bob, mirror


def test_w1g3_panoptic_mirror_imprints_an_instant_or_sorcery_of_mana_value_x(set_pool):
    """"Imprint — {X}, {T}: You may exile an instant or sorcery card with mana
    value X from your hand." X = 1 offers the one-mana instants and not Stone
    Rain (3) or a creature; X is a number by the time the offer is asked (it
    used to reach the card matcher as the symbol and raise)."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g3_table(
        [lea["Lightning Bolt"], lea["Ancestral Recall"], lea["Stone Rain"],
         lea["Llanowar Elves"]],
        interactive=True,
    )
    mirror = _w1g3_put(game, 0, dst["Panoptic Mirror"])
    offered = _w1g3_mirror_imprint(game, mirror, "Lightning Bolt", 1)
    assert sorted(offered) == ["Ancestral Recall", "Lightning Bolt"]
    offered = _w1g3_mirror_imprint(game, mirror, "Stone Rain", 3)
    assert offered == ["Stone Rain"]
    assert sorted(c.name for c in alice.exile) == ["Lightning Bolt", "Stone Rain"]
    assert mirror.tapped


def test_w1g3_panoptic_mirror_copies_one_exiled_card_of_its_controllers_choice(set_pool):
    """"At the beginning of your upkeep, you may copy a card exiled with this
    artifact. If you do, you may cast the copy without paying its mana cost."
    CR 607.3's "a" card: with two imprinted, the offers come card by card and
    the first taken is the choice — Bolt declined, Ancestral Recall's copy
    cast for Alice; nothing else is copied (the ruling: it triggers once, not
    once per card). Taking the first offer withdraws the second."""
    game, alice, bob, mirror = _w1g3_mirror_with(
        set_pool, [("Lightning Bolt", 1), ("Ancestral Recall", 1)],
    )
    hand_before = len(alice.hand)
    game.start_turn(0)
    first = _w1g3_settle(game, defaults=False)
    assert first is not None and first.kind == "copy_cast"
    assert first.data["card_name"] == "Lightning Bolt"
    assert game.confirm_copy_cast(0, False)
    second = _w1g3_settle(game, defaults=False)
    assert second is not None and second.data["card_name"] == "Ancestral Recall"
    assert game.confirm_copy_cast(0, True, target_player_index=0)
    _w1g3_settle(game)
    assert len(alice.hand) == hand_before + 3 and bob.life == 20
    assert sorted(c.name for c in alice.exile) == ["Ancestral Recall", "Lightning Bolt"]

    game, alice, bob, mirror = _w1g3_mirror_with(
        set_pool, [("Lightning Bolt", 1), ("Ancestral Recall", 1)],
    )
    hand_before = len(alice.hand)
    game.start_turn(0)
    first = _w1g3_settle(game, defaults=False)
    assert first is not None and first.data["card_name"] == "Lightning Bolt"
    assert game.confirm_copy_cast(0, True, target_player_index=1)
    assert not [c for c in game.pending_choices if c.kind == "copy_cast"], (
        "the other card's offer is withdrawn: one copy"
    )
    _w1g3_settle(game)
    assert bob.life == 17 and len(alice.hand) == hand_before


def test_w1g3_panoptic_mirror_seat_nobody_asks_and_an_empty_mirror(set_pool):
    """A seat nobody asks copies one card (its rehearsed chooser, Bolt at
    Bob) and stops; a Mirror with nothing imprinted does nothing."""
    game, alice, bob, mirror = _w1g3_mirror_with(
        set_pool, [("Lightning Bolt", 1), ("Ancestral Recall", 1)],
    )
    game.interactive_seats = set()
    hand_before = len(alice.hand)
    game.start_turn(0)
    _w1g3_settle(game)
    copies = [line for line in game.log if "cast a copy of" in line]
    assert len(copies) == 1, copies
    assert bob.life == 17 or len(alice.hand) == hand_before + 3

    dst = set_pool("DST")
    game, alice, bob = _w1g3_table(library=[set_pool("LEA")["Island"]] * 3)
    _w1g3_put(game, 0, dst["Panoptic Mirror"])
    game.start_turn(0)
    _w1g3_settle(game)
    assert "Panoptic Mirror: no card is exiled with it to copy" in game.log


def test_w1g3_panoptic_mirror_imprint_in_response_to_its_upkeep_trigger(set_pool):
    """The 2004-12-01 ruling: "You may imprint a card on Panoptic Mirror in
    response to the upkeep-triggered ability. If you do, that card is
    available to copy when the triggered ability resolves." The trigger is on
    the stack with the Mirror empty; the imprint resolves above it; the
    trigger then offers the Bolt."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g3_table(
        [lea["Lightning Bolt"]], interactive=True,
        library=[lea["Island"]] * 3, bob_library=[lea["Island"]] * 3,
    )
    mirror = _w1g3_put(game, 0, dst["Panoptic Mirror"])
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)
    game.resolve_upkeep(0, defer_priority=True)
    assert [item.card.name for item in game.stack] == ["Panoptic Mirror"]
    assert game.queue_permanent_ability(
        0, "Panoptic Mirror", permanent_index=game.battlefield_index_of(mirror),
        ability_index=0, x_value=1,
    ).supported
    assert len(game.stack) == 2
    offer = _w1g3_settle(game, defaults=False)
    assert offer is not None and offer.kind == "optional_pay"
    assert game.confirm_optional_pay(0, accept=True)
    pick = _w1g3_settle(game, defaults=False)
    assert game.confirm_exile_from_hand_choice(0, 0)
    copy = _w1g3_settle(game, defaults=False)
    assert copy is not None and copy.kind == "copy_cast"
    assert copy.data["card_name"] == "Lightning Bolt"
    assert game.confirm_copy_cast(0, True, target_player_index=1)
    _w1g3_settle(game)
    assert bob.life == 17


def _w1g3_duplicant_with(set_pool, graveyard, *, bob_graveyard=(), interactive=False):
    dst = set_pool("DST")
    pool = {**set_pool("LEA"), **set_pool("LEG")}
    game, alice, bob = _w1g3_table(interactive=interactive)
    alice.graveyard.extend(pool[name] for name in graveyard)
    bob.graveyard.extend(pool[name] for name in bob_graveyard)
    duplicant = _w1g3_put(game, 0, dst["Death-Mask Duplicant"])
    return game, alice, bob, duplicant


def _w1g3_imprint_creature(game, duplicant, name):
    alice = game.players[0]
    slot = next(i for i, c in enumerate(alice.graveyard) if c.name == name)
    result = game.activate_permanent_ability(
        0, "Death-Mask Duplicant", permanent_index=game.battlefield_index_of(duplicant),
        ability_index=0, target_player_index=0, target_graveyard_indices=[slot],
    )
    assert result.supported, result.details
    _w1g3_settle(game)
    game._recompute_continuous_effects()


def test_w1g3_death_mask_duplicant_imprints_a_creature_card_from_its_own_graveyard(set_pool):
    """"Imprint — {1}: Exile target creature card from your graveyard." The
    picker is the caster's own pile and creature cards only: Bob's Black
    Knight and Alice's Lightning Bolt are refused before anything is paid;
    Serra Angel is exiled with the Duplicant (CR 607.2a), and the ability
    may be activated again (the 2004-12-01 ruling: any number of times)."""
    from engine.linked_exile import cards_still_exiled_with
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    game, alice, bob, duplicant = _w1g3_duplicant_with(
        set_pool, ["Serra Angel", "Lightning Bolt", "Grizzly Bears"],
        bob_graveyard=["Black Knight"],
    )
    (ability,) = compile_card_oracle(duplicant.card).activated_abilities
    assert derive_activation_spec(ability).get("own_graveyard_only") is True
    refused = game.activate_permanent_ability(
        0, "Death-Mask Duplicant", permanent_index=game.battlefield_index_of(duplicant),
        ability_index=0, target_player_index=1, target_graveyard_indices=[0],
    )
    assert not refused.supported and [c.name for c in bob.graveyard] == ["Black Knight"]
    refused = game.activate_permanent_ability(
        0, "Death-Mask Duplicant", permanent_index=game.battlefield_index_of(duplicant),
        ability_index=0, target_player_index=0, target_graveyard_indices=[1],
    )
    assert not refused.supported, "Lightning Bolt is no creature card"
    _w1g3_imprint_creature(game, duplicant, "Serra Angel")
    _w1g3_imprint_creature(game, duplicant, "Grizzly Bears")
    assert [c.name for c, _o in cards_still_exiled_with(game, duplicant)] == [
        "Serra Angel", "Grizzly Bears",
    ]
    assert [c.name for c in alice.graveyard] == ["Lightning Bolt"]


def test_w1g3_death_mask_duplicant_has_the_keywords_its_exiled_cards_have(set_pool):
    """"As long as a card exiled with this creature has flying, this creature
    has flying. The same is true for fear, first strike, double strike,
    haste, landwalk, protection, and trample." Each keyword arrives with the
    card that has it — landwalk and protection as the very abilities printed
    (the 2004-12-01 ruling: all landwalk and protection abilities of the
    imprinted cards), never the bare family word — and goes when that card
    leaves exile (CR 611.3a)."""
    game, alice, bob, duplicant = _w1g3_duplicant_with(
        set_pool, ["Serra Angel", "White Knight", "Bog Wraith", "Livonya Silone"],
    )

    def has(word):
        return game._has_keyword(duplicant, word)

    assert not any(has(w) for w in ("flying", "first strike", "swampwalk"))
    _w1g3_imprint_creature(game, duplicant, "Serra Angel")
    assert has("flying") and not has("vigilance"), "vigilance is not on the list"
    _w1g3_imprint_creature(game, duplicant, "White Knight")
    assert has("first strike")
    assert game._protection_qualities(duplicant) == {("color", "B")}
    _w1g3_imprint_creature(game, duplicant, "Bog Wraith")
    _w1g3_imprint_creature(game, duplicant, "Livonya Silone")
    assert has("swampwalk") and has("legendary landwalk")
    assert not has("landwalk") and not has("protection"), "no bare family word"
    assert not has("trample") and not has("haste")
    knight = next(c for c in alice.exile if c.name == "White Knight")
    assert game.take_card_from_exile(0, knight)
    game._recompute_continuous_effects()
    assert game._protection_qualities(duplicant) == set()
    assert has("first strike"), "Livonya Silone still has it"


def test_w1g3_death_mask_duplicant_walks_and_is_protected_in_combat(set_pool):
    """The copied abilities do what they print: Bog Wraith's swampwalk makes
    the Duplicant unblockable while Bob controls a Swamp, and White Knight's
    protection from black keeps Black Knight from blocking it (CR 702.16f)."""
    lea = set_pool("LEA")
    for imprinted in (False, True):
        game, alice, bob, duplicant = _w1g3_duplicant_with(set_pool, ["Bog Wraith"])
        if imprinted:
            _w1g3_imprint_creature(game, duplicant, "Bog Wraith")
        _w1g3_put(game, 1, lea["Swamp"])
        _w1g3_put(game, 1, lea["Grizzly Bears"])
        _w1g3_declare_attack(game, 0)
        ok, _why = game.declare_blockers(1, {1: [0]})
        assert ok is not imprinted, "swampwalk: the Bears cannot block"

    for imprinted in (False, True):
        game, alice, bob, duplicant = _w1g3_duplicant_with(set_pool, ["White Knight"])
        if imprinted:
            _w1g3_imprint_creature(game, duplicant, "White Knight")
        _w1g3_put(game, 1, lea["Black Knight"])
        _w1g3_declare_attack(game, 0)
        ok, _why = game.declare_blockers(1, {0: [0]})
        assert ok is not imprinted, "protection from black: Black Knight cannot block"


def _w1g3_powder_table(set_pool, hand, *, library_extra=()):
    """A dealt two-seat table (no turn begun) with Alice's hand set to
    *hand* out of her library."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    pool = {**lea, **dst}
    library = [lea["Forest"]] * 17 + [lea["Grizzly Bears"]] * 19 + [dst["Serum Powder"]] * 2
    library += [pool[name] for name in library_extra]
    alice = _W1G3PlayerState(name="Alice", library=library)
    bob = _W1G3PlayerState(name="Bob", library=[lea["Forest"]] * 20)
    game = _W1G3Game(players=[alice, bob])
    for name in hand:
        drawn = next(c for c in alice.library if c.name == name)
        alice.library.remove(drawn)
        alice.hand.append(drawn)
    return game, alice, bob


def test_w1g3_serum_powder_exchanges_a_hand_and_taps_for_colourless(set_pool):
    """"Any time you could mulligan and this card is in your hand, you may
    exile all the cards from your hand, then draw that many cards." Seven
    exiled (the Powder with them, face up for the rest of the game: the
    2017-11-17 ruling), seven drawn. On the battlefield it is a mana rock."""
    game, alice, bob = _w1g3_powder_table(
        set_pool, ["Serum Powder"] + ["Grizzly Bears"] * 6,
    )
    library_before = len(alice.library)
    assert game.pregame_hand_exchange(0)
    assert len(alice.hand) == 7 and len(alice.exile) == 7
    assert [c.name for c in alice.exile].count("Serum Powder") == 1
    assert len(alice.library) == library_before - 7
    assert "and drew 7 (Serum Powder)" in game.log[-1]
    powder_drawn = any(c.name == "Serum Powder" for c in alice.hand)
    assert game.pregame_hand_exchange(0) is powder_drawn, (
        "only a Powder still in the hand exchanges again"
    )

    game, alice, bob = _w1g3_table()
    powder = _w1g3_put(game, 0, set_pool("DST")["Serum Powder"])
    assert game.activate_permanent_ability(
        0, "Serum Powder", permanent_index=game.battlefield_index_of(powder),
        ability_index=0,
    ).supported
    assert alice.mana_pool.get("C") == 1


def test_w1g3_serum_powder_after_a_mulligan_bottoms_what_is_owed_first(set_pool):
    """CR 103.5 puts a mulligan's cards on the bottom as it is taken, so the
    hand exchanged after one is the hand without them: the bottom is named
    first (one card for one mulligan), the remaining six are exiled, six
    drawn, and the keep owes nothing more. The exchange refuses a bottom of
    the wrong size, and one that would take the only Powder out of the hand."""
    game, alice, bob = _w1g3_powder_table(set_pool, [])
    game.deal_opening_hands(0)
    assert game.pregame_mulligan_draw(0)
    alice.library.extend(alice.hand)
    alice.hand.clear()
    for name in ["Serum Powder"] + ["Grizzly Bears"] * 6:
        drawn = next(c for c in alice.library if c.name == name)
        alice.library.remove(drawn)
        alice.hand.append(drawn)
    assert game.mulligan_bottom_owed(0) == 1
    assert not game.pregame_hand_exchange(0, [])
    assert not game.pregame_hand_exchange(0, [0]), "the Powder itself"
    assert len(alice.exile) == 0 and len(alice.hand) == 7, "nothing moved"
    assert game.pregame_hand_exchange(0, [3])
    assert len(alice.hand) == 6 and len(alice.exile) == 6
    assert alice.library[-1].name == "Grizzly Bears", "the bottomed card"
    assert game.mulligan_bottom_owed(0) == 0
    game.keep_opening_hand(0, [])
    assert len(alice.hand) == 6
    assert alice.mulligan_bottom_paid == 0, "spent at the keep"


def test_w1g3_serum_powder_the_ai_exchanges_a_hand_it_would_mulligan(set_pool):
    """The AI's opening-hand rounds (``ai_mulligan.take_opening_mulligans``):
    a no-land seven holding a Powder is exchanged rather than mulliganed —
    the exchange costs no card — and the seat then declares over the new
    hand. A hand it would keep is kept with the Powder in it."""
    from engine.ai_mulligan import take_opening_mulligans

    game, alice, bob = _w1g3_powder_table(
        set_pool, ["Serum Powder"] + ["Grizzly Bears"] * 6,
    )
    bob.hand.extend(bob.library[:7])
    del bob.library[:7]
    take_opening_mulligans(game, 0)
    exchanges = [line for line in game.log if "(Serum Powder)" in line and "exiled" in line]
    assert len(exchanges) >= 1
    assert len(alice.exile) >= 7
    assert alice.exile[0].name == "Serum Powder"

    game, alice, bob = _w1g3_powder_table(
        set_pool, ["Serum Powder", "Forest", "Forest", "Forest"] + ["Grizzly Bears"] * 3,
    )
    bob.hand.extend(bob.library[:7])
    del bob.library[:7]
    take_opening_mulligans(game, 0)
    assert alice.exile == [] and "Serum Powder" in [c.name for c in alice.hand]

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.named_counters import add_counters as _w1g5_add_counters
from engine.named_counters import counters_on as _w1g5_counters_on
from tests.helpers import settle as _w1g5_settle


def _w1g5_table(set_pool, *, mine=(), theirs=(), hand=(), life=20, interactive=()):
    """A two-seat game before seat 0's first turn. Cards are named (DST, LEA
    or ATQ); Alice starts at *life* — set before the turn starts, so the
    life-loss sweep's first sight of her records it rather than reading a
    loss of the difference."""
    pools = [set_pool("DST"), set_pool("LEA"), set_pool("ATQ")]

    def named(name):
        return next(pool[name] for pool in pools if name in pool)

    game = _W1G5Game(players=[
        _W1G5PlayerState(name="Alice", hand=[named(n) for n in hand],
                         library=[named("Island")] * 10),
        _W1G5PlayerState(name="Bob", library=[named("Island")] * 10),
    ])
    game.players[0].life = life
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _W1G5Permanent(card=named(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    return game, placed[0], placed[1]


def _w1g5_untapped(game, seat, name):
    return sum(1 for p in game.controlled_by(seat) if p.card.name == name and not p.tapped)


def test_w1g5_well_of_lost_dreams_pays_and_draws_up_to_the_life_gained(set_pool):
    """"Whenever you gain life, you may pay {X}, where X is less than or equal
    to the amount of life you gained. If you do, draw X cards." Nourish gains
    6 with four lands up: a seat nobody asks pays what the board covers (4),
    under the ceiling, and draws 4. Angel's Feather's 1 life caps the next
    payment at 1 with lands to spare: one land tapped, one card drawn."""
    game, _mine, _theirs = _w1g5_table(
        set_pool, mine=["Well of Lost Dreams"] + ["Forest"] * 4, hand=["Nourish"],
    )
    game.start_turn(0)
    _w1g5_settle(game)
    game.cast_from_hand(0, "Nourish")
    _w1g5_settle(game)
    alice = game.players[0]
    assert alice.life == 26
    assert len(alice.hand) == 4 and len(alice.library) == 6
    assert _w1g5_untapped(game, 0, "Forest") == 0
    assert "Alice drew 4 card(s) (Well of Lost Dreams)" in game.log

    game, _mine, _theirs = _w1g5_table(
        set_pool, mine=["Well of Lost Dreams", "Angel's Feather"] + ["Forest"] * 3,
        hand=["Savannah Lions"],
    )
    game.start_turn(0)
    _w1g5_settle(game)
    game.cast_from_hand(0, "Savannah Lions")
    _w1g5_settle(game)
    assert game.players[0].life == 21
    assert len(game.players[0].hand) == 1
    assert _w1g5_untapped(game, 0, "Forest") == 2


def test_w1g5_well_of_lost_dreams_holds_an_asked_seat_to_the_ceiling(set_pool):
    """Asked, the seat names X itself (CR 107.3f) — and the clause bounds the
    answer: with 1 life gained, paying 2 is refused and the prompt stays owed;
    paying 1 taps one land and draws one card. The prompt carries the ceiling
    as its ``maximum``."""
    game, _mine, _theirs = _w1g5_table(
        set_pool, mine=["Well of Lost Dreams", "Angel's Feather"] + ["Forest"] * 3,
        hand=["Savannah Lions"], interactive=(0,),
    )
    game.start_turn(0)
    _w1g5_settle(game)
    game.cast_from_hand(0, "Savannah Lions")
    feather = _w1g5_settle(game, defaults=False)
    assert feather.kind == "optional_pay"
    assert game.confirm_optional_pay(0, accept=True)
    offer = _w1g5_settle(game, defaults=False)
    assert offer.kind == "pay_any_amount" and offer.data["maximum"] == 1
    assert not game.confirm_pay_any_amount(0, 2)
    assert game.confirm_pay_any_amount(0, 1)
    _w1g5_settle(game)
    assert game.players[0].life == 21
    assert len(game.players[0].hand) == 1
    assert _w1g5_untapped(game, 0, "Forest") == 2


def test_w1g5_lichs_tomb_keeps_its_controller_alive_below_zero_at_a_price(set_pool):
    """"You don't lose the game for having 0 or less life. Whenever you lose
    life, sacrifice a permanent for each 1 life you lost." At 2 life, a
    Lightning Bolt takes Alice to -1: CR 704.5a does not end the game, and
    three permanents go — not the Tomb, which a seat nobody asks gives up last
    because its departure loses the game. When the Tomb itself leaves, she
    loses at the next check."""
    game, mine, _theirs = _w1g5_table(
        set_pool,
        mine=["Lich's Tomb", "Forest", "Grizzly Bears", "Ornithopter", "Sol Ring"],
        hand=["Lightning Bolt"], life=2,
    )
    game.start_turn(0)
    _w1g5_settle(game)
    tomb = mine[0]
    game.cast_from_hand(0, "Lightning Bolt", target_player_index=0)
    _w1g5_settle(game)
    alice = game.players[0]
    assert alice.life == -1 and not alice.lost
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Grizzly Bears", "Lich's Tomb"]
    assert sum("(Lich's Tomb)" in line and "sacrificed" in line for line in game.log) == 3

    game.sacrifice_permanent(tomb)
    _w1g5_settle(game)
    assert alice.lost
    assert "Alice lost the game (704.5a: 0 or less life)" in game.log


def test_w1g5_lichs_tomb_asks_its_controller_which_permanents_and_how_many(set_pool):
    """Asked, the controller picks exactly as many permanents as life was
    lost — 3 for a Bolt: two are refused, three are taken. A life gain is not
    a loss and asks nothing."""
    game, mine, _theirs = _w1g5_table(
        set_pool,
        mine=["Lich's Tomb", "Forest", "Grizzly Bears", "Ornithopter", "Sol Ring"],
        hand=["Lightning Bolt", "Nourish"], interactive=(0,),
    )
    game.start_turn(0)
    _w1g5_settle(game)
    _tomb, forest, bears, thopter, ring = mine
    game.cast_from_hand(0, "Lightning Bolt", target_player_index=0)
    owed = _w1g5_settle(game, defaults=False)
    assert owed.kind == "sacrifice" and owed.data["count"] == 3
    assert not game.confirm_sacrifice(0, permanent_ids=[forest.permanent_id, ring.permanent_id])
    assert game.confirm_sacrifice(
        0, permanent_ids=[forest.permanent_id, thopter.permanent_id, ring.permanent_id],
    )
    _w1g5_settle(game)
    assert game.players[0].life == 17
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Grizzly Bears", "Lich's Tomb"]
    game.cast_from_hand(0, "Nourish")
    assert _w1g5_settle(game, defaults=False) is None
    assert game.players[0].life == 23
    assert any(p is bears for p in game.controlled_by(0))


def test_w1g5_darksteel_reactor_wins_at_twenty_charge_counters(set_pool):
    """"When this artifact has twenty or more charge counters on it, you win
    the game." A state trigger (CR 603.8) and CR 104.2b's win: at 19 counters
    the upkeep's charge counter makes 20, and Alice wins. At 18 the upkeep
    makes 19 and the game goes on — and an asked seat that declines the
    counter stays at 19 and does not win."""
    game, mine, _theirs = _w1g5_table(set_pool, mine=["Darksteel Reactor"])
    _w1g5_add_counters(mine[0], "charge", 19)
    game.start_turn(0)
    _w1g5_settle(game)
    assert _w1g5_counters_on(mine[0], "charge") == 20
    assert game.is_game_over()
    assert game.players[1].lost and not game.players[0].lost
    assert "Darksteel Reactor: Alice wins the game (104.2b)" in game.log

    game, mine, _theirs = _w1g5_table(set_pool, mine=["Darksteel Reactor"])
    _w1g5_add_counters(mine[0], "charge", 18)
    game.start_turn(0)
    _w1g5_settle(game)
    assert _w1g5_counters_on(mine[0], "charge") == 19
    assert not game.is_game_over()

    game, mine, _theirs = _w1g5_table(set_pool, mine=["Darksteel Reactor"], interactive=(0,))
    _w1g5_add_counters(mine[0], "charge", 19)
    game.start_turn(0)
    offer = _w1g5_settle(game, defaults=False)
    assert offer is not None
    assert game.confirm_optional_pay(0, accept=False)
    _w1g5_settle(game)
    assert _w1g5_counters_on(mine[0], "charge") == 19
    assert not game.is_game_over()

# ==== end W1G5 ======================================================
