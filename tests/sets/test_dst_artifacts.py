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

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================
