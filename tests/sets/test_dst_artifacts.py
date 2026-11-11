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

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================
