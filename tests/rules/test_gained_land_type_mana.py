"""CR 305.7's last sentence: a land that *gains* a land type has two kinds of
mana ability, and what a tap makes is a question per symbol.

"If an effect instead causes a land to gain one or more land types in addition
to its own, it keeps its land types and rules text, and it gains the new land
types and mana abilities." A Hickory Woodlot under Blanket of Night ("Each
land is a Swamp in addition to its other land types") prints "{T}, Remove a
depletion counter from this land: Add {G}{G}" and has the Swamp's intrinsic
"{T}: Add {B}" (CR 305.6). The tap seam (``Game.tap_land_for_mana``) had this
right — it runs no ability that costs more than the tap, and makes the gained
type's {B}. Everything that *counts* the land as mana did not:

* ``mana_payment.taps_for_payment`` answered for the whole land by the ability
  it prints, so the payment planner's land list left it out, the wire said
  ``taps_for_mana: false`` and a click activated the depletion ability;
* the planner's hook (``Game._land_payment_colors``) and the wire's colour
  list offered the {G} the summary names, for a tap that makes {B};
* the castable highlight (``board_payment.board_can_pay``) glowed over that
  {G} — and, for a land with a tap-alone ability of its own (a Karplusan
  Forest), did not count the gained {B} at all.

**The census**: every land in the pool under every "in addition to its other
land types" source the pool prints (one: Blanket of Night), six symbols each,
with the truth found by tapping — through the seam, by every tap-alone ability
the land has, spending no counter. 192 lands, 1,152 cases; 146 read wrong on
the tree before the fix (111 by the highlight, 17 by the planner's hook, 18 by
``taps_for_payment``). The committed run samples the lands and pins the ones
that carried the defect.

Left: the planner's hook answers with a land's whole summary where the land
has several tap-alone abilities and the default tap runs the first (a
painland asked for {R} makes {C}) — 75 cases, with or without a gained type,
and what ``board_payment`` exists to answer instead. And a Reflecting Pool
under the Blanket is itself a Swamp and makes nothing alone.
"""

from __future__ import annotations

from collections import Counter

import pytest

from engine import Game, PlayerState
from engine.board_payment import board_can_pay
from engine.card_loader import load_catalog
from engine.land_types import added_land_types
from engine.mana_payment import taps_for_payment, untapped_mana_lands
from engine.mixins.turn_management import is_tap_alone_mana_ability
from engine.models import Permanent
from tests.helpers import _nosick

SYMBOLS = ("W", "U", "B", "R", "G", "C")

#: Lands that carried the defect, always examined: three whose only mana
#: ability costs more than the tap, and two with a tap-alone one of their own.
PINNED = (
    "Hickory Woodlot", "Peat Bog", "Gemstone Mine", "Karplusan Forest",
    "Mishra's Factory",
)
STRIDE = 8


@pytest.fixture(scope="module")
def _by_name():
    return {card.name: card for card in load_catalog()}


def _board(by_name, land_name, adder="Blanket of Night"):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Island"]] * 12)
        for seat in range(2)
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    land = Permanent(card=by_name[land_name])
    game._put_permanent_onto_battlefield(0, land, None)
    _nosick(land)
    if adder:
        game._put_permanent_onto_battlefield(0, Permanent(card=by_name[adder]), None)
    game._recompute_continuous_effects()
    land.tapped = False
    return game, land


def _counters(land) -> dict:
    return {
        key: int(value or 0)
        for key, value in land.metadata.items() if key.endswith("_counters")
    }


def _spent(before: dict, after: dict) -> bool:
    return any(after.get(key, 0) < value for key, value in before.items())


def _a_tap_makes(by_name, land_name, symbol, *, default_only=False) -> bool:
    """Whether one tap of the land through the seam, asking *symbol*, puts a
    *symbol* in the pool and spends no counter — by the default tap, or by any
    tap-alone ability the land has."""
    game, land = _board(by_name, land_name)
    indices = [None]
    if not default_only:
        indices += [
            index for index, ability in enumerate(game.usable_abilities_of(land))
            if is_tap_alone_mana_ability(ability)
        ]
    for index in indices:
        game, land = _board(by_name, land_name)
        before = _counters(land)
        try:
            tapped = game.tap_land_for_mana(
                0, land.card.name, symbol,
                permanent_id=land.permanent_id, ability_index=index,
            )
        except ValueError:
            # An any-colour ability asked for {C}: not a colour it can name.
            tapped = False
        if (
            tapped
            and game.players[0].mana_pool.get(symbol, 0) >= 1
            and not _spent(before, _counters(land))
        ):
            return True
    return False


def _census(by_name, names):
    counts: Counter = Counter()
    wrong = []
    for name in names:
        game, land = _board(by_name, name)
        if not game.is_on_battlefield(land) or not added_land_types(land):
            continue
        counts["lands"] += 1
        any_symbol = False
        for symbol in SYMBOLS:
            counts["cases"] += 1
            real = _a_tap_makes(by_name, name, symbol)
            any_symbol = any_symbol or real
            game, land = _board(by_name, name)
            if board_can_pay(game, 0, {symbol: 1}) != real:
                wrong.append((name, symbol, "highlight", not real, real))
            # The planner taps by the default tap, so that is its truth — and
            # only for a land with no tap-alone ability of its own (see the
            # module docstring for the ones left).
            if game._land_mana_abilities(land)[0] is None:
                planned = any(
                    perm is land
                    for perm in untapped_mana_lands(game.controlled_by(0))
                ) and symbol in tuple(game._land_payment_colors(land))
                default = _a_tap_makes(by_name, name, symbol, default_only=True)
                if planned != default:
                    wrong.append((name, symbol, "planner", planned, default))
        game, land = _board(by_name, name)
        if name != "Reflecting Pool" and bool(taps_for_payment(land)) != any_symbol:
            wrong.append((name, "*", "taps_for_payment", not any_symbol, any_symbol))
    return counts, wrong


def _sampled_lands(by_name):
    lands = sorted(
        card.name for card in by_name.values()
        if "land" in card.type_line.lower().split("—")[0]
    )
    chosen = set(lands[::STRIDE]) | set(PINNED)
    return [name for name in lands if name in chosen]


@pytest.mark.cr("305.7", "305.6")
def test_every_reader_counts_a_land_that_gained_a_type_as_the_seam_taps_it(_by_name):
    counts, wrong = _census(_by_name, _sampled_lands(_by_name))

    assert counts["lands"] >= 25 and counts["cases"] >= 150, counts
    assert wrong == [], f"{len(wrong)} readings disagree with the tap: {wrong[:15]}"


@pytest.mark.cr("305.7")
def test_the_census_names_a_land_counted_by_the_ability_it_prints(_by_name, monkeypatch):
    """Backwards: no land has a gained type's mana ability, as far as the
    readers are told — which is how each of them read it."""
    from engine.mixins.turn_management import TurnManagementMixin

    monkeypatch.setattr(
        TurnManagementMixin, "_tap_alone_makes_only_gained_mana",
        staticmethod(lambda land: ()),
    )
    real = TurnManagementMixin._land_mana_abilities

    import sys

    import engine.mana_payment as mana_payment

    def as_it_was(land) -> bool:
        free, priced = real(land)
        if free is not None:
            return True
        if priced:
            return False
        return bool(land.effective_produced_mana or land.basic_land_types)

    # Both names: the planner's list reads the module's, the census this
    # file's own import of it.
    monkeypatch.setattr(mana_payment, "taps_for_payment", as_it_was)
    monkeypatch.setattr(sys.modules[__name__], "taps_for_payment", as_it_was)

    _counts, wrong = _census(_by_name, PINNED)

    assert ("Hickory Woodlot", "*", "taps_for_payment", False, True) in wrong
    assert ("Hickory Woodlot", "G", "highlight", True, False) in wrong
    assert ("Hickory Woodlot", "B", "planner", False, True) in wrong
    assert {row[0] for row in wrong} >= {"Hickory Woodlot", "Peat Bog", "Gemstone Mine"}


# --- the card ---------------------------------------------------------------


@pytest.mark.cr("305.7", "305.6")
def test_a_hickory_woodlot_under_blanket_of_night_is_tapped_for_black(_by_name):
    """It taps for {B} and keeps its counters; it is on the planner's list as
    a {B} land and pays a generic cost; the highlight reads {B} and not {G}."""
    game, woodlot = _board(_by_name, "Hickory Woodlot")
    counters = _counters(woodlot)
    assert counters.get("depletion_counters") == 2

    assert taps_for_payment(woodlot)
    assert [p.card.name for p in untapped_mana_lands(game.controlled_by(0))] == [
        "Hickory Woodlot"
    ]
    assert tuple(game._land_payment_colors(woodlot)) == ("B",)
    assert board_can_pay(game, 0, {"B": 1})
    assert not board_can_pay(game, 0, {"G": 1})
    assert not board_can_pay(game, 0, {"B": 2})

    # A payment made with no priority window ("…unless you pay {1}") plans it.
    plan = game._counter_payment_plan(game.players[0], {"generic": 1})
    assert plan is not None and [p.card.name for p in plan.tapped] == ["Hickory Woodlot"]

    # Asked for the colour it prints, the tap still makes the one it has free.
    assert game.tap_land_for_mana(0, "Hickory Woodlot", "G", permanent_id=woodlot.permanent_id)
    assert game.players[0].mana_pool.get("B", 0) == 1
    assert game.players[0].mana_pool.get("G", 0) == 0
    assert woodlot.tapped and _counters(woodlot) == counters

    # Without the Blanket it is a land the seam does not tap.
    game, woodlot = _board(_by_name, "Hickory Woodlot", adder=None)
    assert not taps_for_payment(woodlot)
    assert untapped_mana_lands(game.controlled_by(0)) == []
    assert not board_can_pay(game, 0, {"G": 1})


@pytest.mark.cr("305.7", "305.6")
def test_a_painland_under_blanket_of_night_is_counted_for_black_too(_by_name):
    """A land with a tap-alone ability of its own: the highlight counted what
    it prints and not the gained {B}, which the seam makes when asked."""
    game, forest = _board(_by_name, "Karplusan Forest")
    assert board_can_pay(game, 0, {"B": 1})
    assert board_can_pay(game, 0, {"R": 1})
    assert not board_can_pay(game, 0, {"B": 1, "R": 1})
    assert game.tap_land_for_mana(0, "Karplusan Forest", "B", permanent_id=forest.permanent_id)
    assert game.players[0].mana_pool.get("B", 0) == 1
    assert game.players[0].life == 20
