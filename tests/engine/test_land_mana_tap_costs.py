"""Tapping a land for mana never pays less than the land asks (CR 602.2b).

``Game.tap_land_for_mana`` is the seam the web's land click and the AI's
auto-tap both come down. It runs the land's *compiled* mana ability when that
ability's cost is the tap alone, and otherwise falls back to
``CardDefinition.produced_mana`` — Scryfall's summary of **which symbols** a
land can make, which says nothing about how many or at what price.

That fallback was reached by every land whose mana ability costs a counter as
well as the tap: the five Mercadian Masques depletion lands, the storage-land
cycles ("{T}, Remove any number of storage counters from this land: Add {B} for
each storage counter removed this way") and Gemstone Mine. Each of them tapped
for one free mana, spent no counter, and therefore never reached the "if there
are no counters on this land, sacrifice it" the cycle is built around — an
unbounded mana source, silently, in the tapper's favour.

Found while making the depletion lands supported and fixed at the seam, so the
storage lands that had shipped with it were fixed at the same time. The sweep
below is pool-wide because that is the shape of the bug: the seam is generic
and the cards that reach it are whatever the pool happens to print.
"""

from __future__ import annotations

import pytest

from engine.faces import compilation_units
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.mana_payment import is_mana_ability
from engine.mixins.turn_management import _is_free_beyond_tapping
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _pool():
    return compilation_units(load_cards(manifest_set_paths(include_measured=True)))


def _priced_mana_lands(cards):
    """Lands whose every compiled mana ability costs more than the tap."""
    found = []
    for card in cards:
        if card.primary_type != "land":
            continue
        abilities = [
            ability
            for ability in compile_card_oracle(card).activated_abilities
            if ability.supported
            and ability.instruction is not None
            and (
                is_mana_ability(ability)
                or ability.instruction.kind == "if_then"
            )
        ]
        if not abilities:
            continue
        if any(
            ability.cost.requires_tap and _is_free_beyond_tapping(ability.cost)
            for ability in abilities
        ):
            continue
        found.append(card)
    return found


def _board(card):
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.interactive_seats = set()
    land = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, land, None)
    land.tapped = False
    return game, land


def test_a_land_whose_mana_costs_more_than_the_tap_refuses_the_tap_seam():
    """Every such land in the pool, and a floor on how many were examined.

    The floor is the lesson a sweep with none learns the hard way: asked of a
    predicate that had drifted, this test would examine zero lands, find no
    counter-example and pass on the broken engine. Sixteen lands answer it
    today across five sets; the floor is deliberately well below that so an
    ordinary ingest does not move it, and well above zero.
    """
    lands = _priced_mana_lands(_pool())
    assert len(lands) >= 10

    leaked = []
    for card in lands:
        game, land = _board(card)
        symbol = (card.produced_mana or ("G",))[0]
        if game.tap_land_for_mana(0, card.name, symbol):
            leaked.append((card.name, dict(game.players[0].mana_pool)))

    assert leaked == []


@pytest.mark.parametrize(
    "name", ["Peat Bog", "Gemstone Mine", "Bottomless Vault", "Mercadian Bazaar"],
)
def test_the_named_cycles_still_produce_through_their_own_ability(name):
    """Refusing the seam must not make the cards unplayable.

    One from each shape the sweep caught — a depletion land, Gemstone Mine, and
    two storage lands one set apart — activated the way the rules ask, with the
    cost charged. The counter comes off and the mana arrives; only the free
    route is gone.
    """
    from engine.named_counters import add_counters, counters_on

    cards = {card.name: card for card in _pool()}
    game, land = _board(cards[name])
    abilities = compile_card_oracle(land.card).activated_abilities
    # The one that *spends* counters, by index: a storage land's first ability
    # puts one on, so naming index 0 would activate the wrong half and read a
    # pool of zero as a broken seam.
    index = next(
        position for position, ability in enumerate(abilities)
        if ability.cost.remove_counter
    )
    kind = abilities[index].cost.remove_counter
    if counters_on(land, kind) < 2:
        add_counters(land, kind, 2 - counters_on(land, kind))
    held = counters_on(land, kind)

    result = game.activate_permanent_ability(
        0, name, ability_index=index, mana_color="U",
    )

    assert result.supported is True
    assert sum(game.players[0].mana_pool.values()) > 0
    assert counters_on(land, kind) < held


def test_a_tap_only_land_is_untouched():
    """The control. A land whose mana ability is the tap alone, and a basic with
    no compiled ability at all, both still tap — the guard above narrows one
    branch and must not close the seam."""
    cards = {card.name: card for card in _pool()}
    for name, symbol in (("Badlands", "B"), ("Swamp", "B")):
        game, _land = _board(cards[name])
        assert game.tap_land_for_mana(0, name, symbol) is True
        assert game.players[0].mana_pool[symbol] >= 1


def test_every_reader_that_counts_land_mana_counts_what_the_tap_seam_taps():
    """The payment planner's land list (``untapped_mana_lands``) and the AI's
    tap plan count a land as mana exactly when the tap seam would tap it.

    The guard above holds the seam; this holds the two readers that *plan*
    around it, which the seam's fix did not reach. Measured at PCY W3G1 over
    both manifest roles, the planner still counted the sixteen lands above as
    one free mana of their summary's colour — an optional "pay {1}" or an
    upkeep cost tapped a Peat Bog and spent no counter — and the AI's plan
    counted every land that makes no mana at all (Bazaar of Baghdad, the
    fetchlands, Maze of Ith: 23 in both roles) as a {C} the seam then refused, which
    is a cast proposed and declined every turn. Rhystic Cave is the land that
    made it a rule: its mana needs priority (CR 304.5) and any player may deny
    it, so nothing that pays mid-payment may count it.

    One reading answers all three — ``Game._land_mana_abilities``, through
    ``mana_payment.taps_for_payment`` for the payment planner and through the
    seam's own gate (``Game.land_mana_tap_refusal``) for the AI's plan; this
    sweep checks each against the seam's own behaviour, land by land, rather
    than against a second list. The floor is on how many lands it
    examined, for the reason the sweep above gives.
    """
    from engine.ai_policy import _land_mana_is_unplannable, _plan_land_taps
    from engine.mana_payment import taps_for_payment, untapped_mana_lands

    lands = [card for card in _pool() if card.primary_type == "land"]
    assert len(lands) >= 150

    disagree = []
    declined = []
    refused = examined = 0
    for card in lands:
        game, land = _board(card)
        if not game.is_on_battlefield(land):
            # "If this land would enter, sacrifice an untapped Mountain
            # instead" (Dormant Volcano, Lotus Vale, the Ice Age outposts): on
            # an empty board it never stays, so there is nothing to tap.
            continue
        examined += 1
        counted = taps_for_payment(land)
        in_planner = bool(untapped_mana_lands([land]))
        # The AI's plan is the one reader allowed to count *fewer* lands than
        # the seam taps, and only the ones it says it cannot count (PCY W3G4):
        # a tap the seam accepts is not always a mana a plan can spend.
        # Mishra's Workshop's goes into a restricted bucket (CR 106.6) and a
        # plan is not told what the mana is for; Gaea's Cradle, Serra's
        # Sanctum, Tolarian Academy, City of Shadows and Reflecting Pool make
        # what the rest of the board decides, which alone on this board is
        # nothing. Asked before the tap, which is what the plan is.
        unplannable = _land_mana_is_unplannable(game, land)
        planned = _plan_land_taps(game, game.players[0], {"generic": 1}) is not None
        symbol = (card.produced_mana or ("G",))[0]
        tapped = game.tap_land_for_mana(0, card.name, symbol)
        refused += not tapped
        declined += [card.name] if tapped and unplannable else []
        if (
            counted != tapped
            or (in_planner and not tapped)
            or planned != (tapped and not unplannable)
        ):
            disagree.append((card.name, counted, in_planner, planned, tapped))

    assert disagree == []
    # The exclusion is a handful of lands, not a way out of the comparison: a
    # predicate that began declining ordinary lands would empty this sweep's
    # third reader while every row above still agreed.
    assert len(declined) * 20 <= examined, sorted(declined)
    assert examined >= 150
    # The seam refuses 39 of the 166 examined today (the sixteen priced lands,
    # Rhystic Cave, and the lands that make no mana); a sweep that refused none
    # would be a sweep that stopped asking.
    assert refused >= 30
