"""Mirrodin artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.
#
# Imprint (an ability word, CR 207.2c) over CR 607.2a's linked abilities:
# "the exiled card" is the card this permanent's own entry trigger exiled and
# still in exile (``linked_exile.cards_still_exiled_with``). Each card is
# driven through the real entry points — cast, the entry trigger on the stack,
# the "may" answered by an interactive seat and by a seat nobody asks, then the
# linked ability.

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.mana_could_produce import (
    ability_colors_on_offer as _w1g5_colors_on_offer,
)
from engine.oracle import compile_card_oracle as _w1g5_compile
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_table(set_pool, hand=(), *, interactive=False, bob_hand=()):
    lea = set_pool("LEA")
    alice = _W1G5PlayerState(
        name="Alice", hand=list(hand), library=[lea["Plains"]] * 8,
    )
    bob = _W1G5PlayerState(
        name="Bob", hand=list(bob_hand), library=[lea["Island"]] * 8,
    )
    game = _W1G5Game(players=[alice, bob])
    game.enforce_mana_costs = True
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g5_put(game, seat, card):
    permanent = _W1G5Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g5_named(game, name):
    return next(p for p in game.all_permanents() if p.card.name == name)


def _w1g5_imprint_from_hand(game, alice, source_name, card_name):
    """Cast *source_name* for an interactive seat 0, take its imprint offer
    and pick *card_name* out of the hand."""
    assert game.cast_from_hand(0, source_name).supported
    assert game.resolve_top_of_stack() is False, "the imprint offer holds the trigger"
    assert [c.kind for c in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True)
    (pick,) = game.pending_choices
    assert pick.kind == "exile_from_hand_choice"
    slot = next(i for i, c in enumerate(alice.hand) if c.name == card_name)
    assert slot in game.live_exile_from_hand_choices(pick)
    assert game.confirm_exile_from_hand_choice(0, slot)
    _w1g5_resolve_stack(game)
    return _w1g5_named(game, source_name)


def _w1g5_tap_for(game, permanent, color):
    for symbol in list(game.players[0].mana_pool):
        game.players[0].mana_pool[symbol] = 0
    permanent.tapped = False
    result = game.activate_permanent_ability(
        0, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent),
        ability_index=0, mana_color=color,
    )
    assert result.supported, result.details
    return {k: v for k, v in game.players[0].mana_pool.items() if v}


def test_w1g5_chrome_mox_taps_only_for_the_imprinted_cards_colors(set_pool):
    """"{T}: Add one mana of any of the exiled card's colors." A red card
    imprinted makes {R}, and a colour named outside the set is re-checked to
    one inside it (the colour fan offers only {R})."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], lea["Lightning Bolt"], lea["Wheel of Fortune"]],
        interactive=True,
    )
    mox = _w1g5_imprint_from_hand(game, alice, "Chrome Mox", "Lightning Bolt")
    assert [c.name for c in alice.exile] == ["Lightning Bolt"]
    (ability,) = _w1g5_compile(mox.card).activated_abilities
    assert ability.supported
    assert _w1g5_colors_on_offer(game, mox, ability.instruction) == ("R",)
    assert _w1g5_tap_for(game, mox, "R") == {"R": 1}
    assert _w1g5_tap_for(game, mox, "G") == {"R": 1}


def test_w1g5_chrome_mox_offers_each_color_of_a_multicolored_card(set_pool):
    """Ruling 2025-02-07: "If the exiled card is multicolored, you choose one
    of that card's colors each time you tap this artifact for mana.\""""
    mrd, inv = set_pool("MRD"), set_pool("INV")
    gold = next(
        c for c in sorted(inv.values(), key=lambda c: c.name)
        if set(c.colors) == {"W", "U"} and "Land" not in c.type_line
        and "Artifact" not in c.type_line
    )
    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], gold], interactive=True,
    )
    mox = _w1g5_imprint_from_hand(game, alice, "Chrome Mox", gold.name)
    (ability,) = _w1g5_compile(mox.card).activated_abilities
    assert _w1g5_colors_on_offer(game, mox, ability.instruction) == ("W", "U")
    assert _w1g5_tap_for(game, mox, "U") == {"U": 1}
    assert _w1g5_tap_for(game, mox, "W") == {"W": 1}


def test_w1g5_chrome_mox_adds_nothing_with_no_card_or_once_the_card_leaves(set_pool):
    """Ruling 2025-02-07: "If no card is exiled with this artifact, it can't
    add mana." A declined imprint links nothing; a card that leaves exile is no
    longer "the exiled card"; and the Mox returning is a new object with no
    exiled card at all (CR 400.7)."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], lea["Lightning Bolt"]], interactive=True,
    )
    assert game.cast_from_hand(0, "Chrome Mox").supported
    assert game.resolve_top_of_stack() is False
    assert game.confirm_optional_pay(0, accept=False)
    _w1g5_resolve_stack(game)
    mox = _w1g5_named(game, "Chrome Mox")
    assert alice.exile == [] and [c.name for c in alice.hand] == ["Lightning Bolt"]
    assert _w1g5_tap_for(game, mox, "R") == {}
    assert "it adds no mana" in game.log[-1]

    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], lea["Lightning Bolt"]], interactive=True,
    )
    mox = _w1g5_imprint_from_hand(game, alice, "Chrome Mox", "Lightning Bolt")
    assert _w1g5_tap_for(game, mox, "R") == {"R": 1}
    game.remove_from_battlefield(mox)
    returned = _w1g5_put(game, 0, mrd["Chrome Mox"])
    assert [c.name for c in alice.exile] == ["Lightning Bolt"]
    assert _w1g5_tap_for(game, returned, "R") == {}

    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], lea["Lightning Bolt"]], interactive=True,
    )
    mox = _w1g5_imprint_from_hand(game, alice, "Chrome Mox", "Lightning Bolt")
    (bolt,) = alice.exile
    assert game.take_card_from_exile(0, bolt)
    assert _w1g5_tap_for(game, mox, "R") == {}


def _w1g5_golem_imprints(set_pool, graveyard_index, *, interactive=True):
    """Mirror Golem cast with Terror and Grizzly Bears in Bob's graveyard; the
    imprint's target is the card at *graveyard_index* (an interactive seat
    names it on the trigger's target prompt, CR 603.3d)."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g5_table(
        set_pool, [mrd["Mirror Golem"]], interactive=interactive,
        bob_hand=[lea["Lightning Bolt"], lea["Terror"]],
    )
    game.enforce_mana_costs = False
    bob.graveyard.extend([lea["Terror"], lea["Grizzly Bears"]])
    assert game.cast_from_hand(0, "Mirror Golem").supported
    if interactive:
        assert game.resolve_top_of_stack() is False
        assert [c.kind for c in game.pending_choices] == ["trigger_target"]
        assert game.confirm_trigger_target(0, seat=1, graveyard_index=graveyard_index)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game, alice, bob, _w1g5_named(game, "Mirror Golem")


def test_w1g5_mirror_golem_is_protected_from_the_exiled_instants_type(set_pool):
    """"This creature has protection from each of the exiled card's card
    types." Terror imprinted: an instant cannot target the Golem (CR 702.16b)
    — Bob's Terror and Lightning Bolt are both refused — and its damage would
    be prevented (CR 702.16e)."""
    game, _alice, bob, golem = _w1g5_golem_imprints(set_pool, 0)
    assert [c.name for c in bob.exile] == ["Terror"]
    assert game._protection_qualities(golem) == {("card_type", "instant")}
    bolt = set_pool("LEA")["Lightning Bolt"]
    assert not game._can_be_targeted(golem, bolt, caster_index=1)
    assert game._is_protected_from(golem, bolt, as_damage_source=True, seat=1)
    refused = game.cast_from_hand(1, "Lightning Bolt", target_permanent_ids=[golem.permanent_id])
    assert not refused.supported
    assert game.is_on_battlefield(golem)


def test_w1g5_mirror_golem_with_a_creature_imprinted_answers_creatures_only(set_pool):
    """Grizzly Bears imprinted: protection from creatures (a creature cannot
    block it or damage it, CR 702.16e/f) and nothing else — an instant
    targets it as usual."""
    game, _alice, bob, golem = _w1g5_golem_imprints(set_pool, 1)
    assert [c.name for c in bob.exile] == ["Grizzly Bears"]
    assert game._protection_qualities(golem) == {("card_type", "creature")}
    bears = _w1g5_put(game, 1, set_pool("LEA")["Grizzly Bears"])
    assert game._is_protected_from(golem, bears)
    bolt = set_pool("LEA")["Lightning Bolt"]
    assert game._can_be_targeted(golem, bolt, caster_index=1)


def test_w1g5_mirror_golem_loses_the_protection_with_the_card(set_pool):
    """The exiled card leaving exile takes the protection with it, and a
    Golem that never imprinted (the seat nobody asks takes the first legal
    target) has the one quality its card gives."""
    game, _alice, bob, golem = _w1g5_golem_imprints(set_pool, 0, interactive=False)
    assert game._protection_qualities(golem) == {("card_type", "instant")}
    (terror,) = bob.exile
    assert game.take_card_from_exile(1, terror)
    assert game._protection_qualities(golem) == set()

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
