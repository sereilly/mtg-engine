"""CR 605 / CR 106.12: what a land is *tapped for* is read ability by ability,
and a tap that asks for a symbol runs the ability that makes it.

Each mana ability of a land is its own ability (CR 605.1a), and tapping a land
for mana is activating one of them (CR 106.12) — the player chooses which.
Three readers say what a land can be tapped for: the payment planner's hook
(``Game._land_payment_colors``, which every "you may pay" and the wire's
colour list ask), the castable highlight (``board_payment.board_can_pay``) and
the tap seam itself (``Game.tap_land_for_mana``). They disagreed three ways:

* **the hook answered with the printed summary**, which lists every symbol
  *any* ability of the land makes, whatever that ability costs. A School of
  the Unseen ("{T}: Add {C}." / "{2}, {T}: Add one mana of any color.") paid a
  {R} with a tap; a Tinder Farm paid {R}{W} without being sacrificed;
* **the seam ran the land's first tap-alone ability whatever was asked**, so a
  Karplusan Forest asked for {R} made {C} — unless the caller named the
  ability by index, which the AI's executor did and a human's click did not;
* **a symbol that is not a colour raised.** "{T}: Add {B} or {R}." asked for
  {C} — the wire's own ``mana_color`` value — went through the colour
  normalizer and ended in a ``ValueError`` (a 500 from the route): 25 lands
  with an ability named, the five Lairs with none.

And one land made nothing at all where it should: a Reflecting Pool under a
Blanket of Night is itself a Swamp (CR 305.7's last sentence), so a land its
controller controls could produce {B}; it read only what lands *print*.

**The census.** Every land in the pool, alone and under each "in addition to
its other land types" static, asked for each of the six symbols — with no
ability named and with each of its tap-alone abilities named — the truth
found by tapping. Measured on the tree before the fix, over 2,304 (board,
symbol) cases on 384 boards: the hook disagreed with the tap 151 times, the
tap asked for a symbol missed an ability that makes it 60 times, 50 taps
raised, and one land that should make mana made none. The committed run takes
every fourth land and the pinned ones.

Still as it was, and not a disagreement: a land whose mana the *board* counts
(Gaea's Cradle with no creature, a Reflecting Pool alone) is on the list of
lands that tap for mana and makes nothing there. The hook answers for the
board — it says so, with no symbols.
"""

from __future__ import annotations

from collections import Counter

import pytest

from engine import Game, PlayerState
from engine.board_payment import board_can_pay, tap_alone_symbols
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.mana_could_produce import lands_could_produce
from engine.mana_payment import generic_cost, plan_payment, untapped_mana_lands
from engine.mixins.turn_management import is_tap_alone_mana_ability
from engine.models import Permanent
from tests.helpers import _nosick

SYMBOLS = ("W", "U", "B", "R", "G", "C")

#: One land per shape, always examined: a painland (two tap-alone abilities),
#: a land with a free {C} and a priced colour, a land that pays by being
#: sacrificed, "{X} or {Y}" with one ability, a Lair (three alternatives), a
#: land whose colours the board defines, a basic, a dual, "any color", and a
#: depletion land (no tap-alone ability at all).
PINNED = (
    "Karplusan Forest", "School of the Unseen", "Tinder Farm", "Bloodfell Caves",
    "Crosis's Catacombs", "Reflecting Pool", "Forest", "Tropical Island",
    "City of Brass", "Hickory Woodlot", "Underground River", "Mishra's Factory",
)

STRIDE = 4


@pytest.fixture(scope="module")
def _by_name():
    return {card.name: card for card in load_catalog()}


def _board(by_name, land_name, *others):
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
    for name in others:
        other = Permanent(card=by_name[name])
        game._put_permanent_onto_battlefield(0, other, None)
        _nosick(other)
    game.auto_resolve_pending_choices()
    game._recompute_continuous_effects()
    land.tapped = False
    return game, land


def _pool(game) -> dict:
    return {s: n for s, n in game.players[0].mana_pool.items() if n}


def _counters(land) -> dict:
    return {k: v for k, v in land.metadata.items() if k.endswith("_counters")}


def _tap_makes(by_name, land_name, others, symbol, index):
    """Whether one tap through the seam asking *symbol* puts a *symbol* in the
    pool and spends no counter — or "raised"."""
    game, land = _board(by_name, land_name, *others)
    if not game.is_on_battlefield(land):
        return None
    before = _counters(land)
    try:
        tapped = game.tap_land_for_mana(
            0, land.card.name, symbol, permanent_id=land.permanent_id,
            ability_index=index,
        )
    except Exception:  # noqa: BLE001 - the census counts every raise
        return "raised"
    spent = any(
        int(_counters(land).get(key, 0) or 0) < int(value or 0)
        for key, value in before.items()
    )
    return bool(tapped and game.players[0].mana_pool.get(symbol, 0) >= 1 and not spent)


def _lands(by_name):
    names = sorted(
        card.name for card in by_name.values()
        if "land" in card.type_line.lower().split("—")[0]
    )
    return sorted(set(names[::STRIDE]) | set(PINNED))


def _adders(by_name):
    return [()] + [
        (unit.name,)
        for unit in sorted(compilation_units(by_name.values()), key=lambda c: c.name)
        if "in addition to its other land types" in (unit.oracle_text or "").lower()
        and "land" not in unit.type_line.lower().split("—")[0]
    ]


def _census(by_name, lands=None):
    counts: Counter = Counter()
    wrong = []
    for others in _adders(by_name):
        for name in lands or _lands(by_name):
            game, land = _board(by_name, name, *others)
            if not game.is_on_battlefield(land):
                continue
            counts["boards"] += 1
            indices = [
                index for index, ability in enumerate(game.usable_abilities_of(land))
                if is_tap_alone_mana_ability(ability)
            ]
            for symbol in SYMBOLS:
                counts["cases"] += 1
                row = (*others, name, symbol)
                asked = _tap_makes(by_name, name, others, symbol, None)
                named = [_tap_makes(by_name, name, others, symbol, i) for i in indices]
                if "raised" in (asked, *named):
                    wrong.append((*row, "a tap raised"))
                    continue
                counts["named"] += len(named)
                truth = bool(asked) or any(named)
                counts["makes"] += truth
                if bool(asked) != truth:
                    wrong.append((*row, "asked for it and missed the ability that makes it"))
                game, land = _board(by_name, name, *others)
                listed = any(
                    p is land for p in untapped_mana_lands(game.controlled_by(0))
                )
                hook = listed and symbol in tuple(game._land_payment_colors(land))
                if hook != truth:
                    wrong.append((*row, "the hook says", hook, "the tap makes", truth))
                glows = board_can_pay(game, 0, {symbol: 1})
                if glows != truth:
                    wrong.append((*row, "the highlight says", glows, "the tap makes", truth))
    return counts, wrong


@pytest.mark.cr("605.1a", "106.12", "106.1b", "305.7")
def test_what_a_land_is_tapped_for_is_one_answer_for_three_readers(_by_name):
    counts, wrong = _census(_by_name)

    # Floors: a sweep that reaches nothing passes. Measured 116 boards, 696
    # cases, 552 taps with an ability named, 201 cases that make the symbol.
    assert counts["boards"] >= 100, counts
    assert counts["cases"] >= 600, counts
    assert counts["named"] >= 480, counts
    assert counts["makes"] >= 180, counts
    assert wrong == [], wrong[:20]


@pytest.mark.cr("605.1a")
def test_the_census_names_a_hook_that_reads_the_summary_and_a_tap_that_does_not_choose(
    _by_name, monkeypatch,
):
    """Backwards: the hook as the printed summary and the seam running its
    first ability whatever is asked, which is what they were."""
    import engine.board_payment as board_payment
    import engine.mixins.stack.choices.payments as choices
    import web.serialization as serialization

    monkeypatch.setattr(board_payment, "tap_alone_symbols", lambda game, land: None)
    monkeypatch.setattr(serialization, "tap_alone_symbols", lambda game, land: None)
    monkeypatch.setattr(
        board_payment, "tap_alone_ability_for", lambda game, land, symbol: None
    )
    assert choices  # the hook imports the name at call time

    _counts, wrong = _census(
        _by_name, ["Karplusan Forest", "School of the Unseen", "Tinder Farm"]
    )
    assert ("Karplusan Forest", "R", "the hook says", True, "the tap makes", False) not in wrong
    assert (
        "Karplusan Forest", "R", "asked for it and missed the ability that makes it"
    ) in wrong
    assert (
        "School of the Unseen", "R", "the hook says", True, "the tap makes", False
    ) in wrong
    assert ("Tinder Farm", "W", "the hook says", True, "the tap makes", False) in wrong


# --- the cards, one board each -------------------------------------------


@pytest.mark.cr("605.1a", "106.12")
def test_a_painland_asked_for_a_colour_runs_the_ability_that_makes_it(_by_name):
    game, forest = _board(_by_name, "Karplusan Forest")
    assert tuple(game._land_payment_colors(forest)) == ("C", "R", "G")

    assert game.tap_land_for_mana(0, "Karplusan Forest", "R", permanent_id=forest.permanent_id)
    assert _pool(game) == {"R": 1}
    assert game.players[0].life == 19

    # Asked for nothing, or for the symbol its first ability makes: no damage.
    for asked in (None, "C"):
        game, forest = _board(_by_name, "Karplusan Forest")
        assert game.tap_land_for_mana(
            0, "Karplusan Forest", asked, permanent_id=forest.permanent_id
        )
        assert _pool(game) == {"C": 1}, asked
        assert game.players[0].life == 20, asked


@pytest.mark.cr("605.1a", "118.3")
def test_a_priced_abilitys_colours_are_not_what_the_land_is_tapped_for(_by_name):
    """The planner taps and pays nothing more, so a symbol only a *priced*
    ability makes is not one it may count."""
    game, school = _board(_by_name, "School of the Unseen")
    assert "R" in school.effective_card.produced_mana
    assert tuple(game._land_payment_colors(school)) == ("C",)
    lands = untapped_mana_lands(game.controlled_by(0))
    assert plan_payment({}, lands, {"R": 1}, produces=game._land_payment_colors) is None
    assert plan_payment(
        {}, lands, generic_cost(1), produces=game._land_payment_colors
    ) is not None
    # …and a tap asked for the colour makes the {C} the tap alone makes.
    assert game.tap_land_for_mana(0, school.card.name, "R", permanent_id=school.permanent_id)
    assert _pool(game) == {"C": 1}

    # "{T}: Add {G}." / "{T}, Sacrifice this land: Add {R}{W}." (Tinder Farm.)
    game, farm = _board(_by_name, "Tinder Farm")
    assert tuple(game._land_payment_colors(farm)) == ("G",)
    assert plan_payment(
        {}, untapped_mana_lands(game.controlled_by(0)), {"W": 1},
        produces=game._land_payment_colors,
    ) is None
    assert tap_alone_symbols(game, farm) == ("G",)


@pytest.mark.cr("106.1b")
def test_a_symbol_the_ability_does_not_offer_takes_its_first_and_never_raises(_by_name):
    """{C} is one of the six types a tap may be asked for and not one of the
    five colours. Asked of "{T}: Add {B} or {R}." it raised."""
    game, caves = _board(_by_name, "Bloodfell Caves")
    (index,) = [
        i for i, ability in enumerate(game.usable_abilities_of(caves))
        if is_tap_alone_mana_ability(ability)
    ]
    assert game.tap_land_for_mana(
        0, caves.card.name, "C", permanent_id=caves.permanent_id, ability_index=index,
    )
    assert _pool(game) == {"B": 1}

    game, lair = _board(_by_name, "Crosis's Catacombs")
    lair.tapped = False
    assert game.is_on_battlefield(lair)
    assert game.tap_land_for_mana(0, lair.card.name, "C", permanent_id=lair.permanent_id)
    made = _pool(game)
    assert sum(made.values()) == 1 and set(made) <= {"U", "B", "R"}, made

    # A string that is no mana symbol is refused, with nothing tapped.
    game, forest = _board(_by_name, "Forest")
    assert game.tap_land_for_mana(0, "Forest", "any", permanent_id=forest.permanent_id) is False
    assert not forest.tapped
    assert _pool(game) == {}
    # …and an empty one names nothing, which is the default.
    assert game.tap_land_for_mana(0, "Forest", "", permanent_id=forest.permanent_id)
    assert _pool(game) == {"G": 1}


@pytest.mark.cr("305.7", "106.7")
def test_a_reflecting_pool_that_is_itself_a_swamp_could_produce_black(_by_name):
    """"Each land is a Swamp in addition to its other land types." The Pool
    has the Swamp's "{T}: Add {B}" (CR 305.6), so a land its controller
    controls — the Pool — could produce {B}. Alone, it made nothing."""
    game, pool = _board(_by_name, "Reflecting Pool")
    assert lands_could_produce(game)[pool.permanent_id] == frozenset()
    assert not board_can_pay(game, 0, {"B": 1})

    game, pool = _board(_by_name, "Reflecting Pool", "Blanket of Night")
    assert lands_could_produce(game)[pool.permanent_id] == frozenset({"B"})
    assert tuple(game._land_payment_colors(pool)) == ("B",)
    assert board_can_pay(game, 0, {"B": 1})
    assert not board_can_pay(game, 0, {"G": 1})
    assert game.tap_land_for_mana(0, pool.card.name, "B", permanent_id=pool.permanent_id)
    assert _pool(game) == {"B": 1}


@pytest.mark.cr("305.7", "605.1a")
def test_a_gained_types_mana_is_free_where_the_lands_own_ability_would_cost(_by_name):
    """An Underground River under the Blanket asked for {B}: the gained
    Swamp's "{T}: Add {B}", not the painful ability its summary lists {B}
    for — and not the {C} its first ability makes, which is what it got."""
    game, river = _board(_by_name, "Underground River", "Blanket of Night")
    assert game.tap_land_for_mana(0, river.card.name, "B", permanent_id=river.permanent_id)
    assert _pool(game) == {"B": 1}
    assert game.players[0].life == 20

    # …and {U} is still the River's own, at the River's own price.
    game, river = _board(_by_name, "Underground River", "Blanket of Night")
    assert game.tap_land_for_mana(0, river.card.name, "U", permanent_id=river.permanent_id)
    assert _pool(game) == {"U": 1}
    assert game.players[0].life == 19

    # A School of the Unseen there is {C} or the Swamp's {B}: the highlight
    # read the summary's {B} as already counted and never added the free one.
    game, school = _board(_by_name, "School of the Unseen", "Blanket of Night")
    assert tuple(game._land_payment_colors(school)) == ("C", "B")
    assert board_can_pay(game, 0, {"B": 1})
    assert game.tap_land_for_mana(0, school.card.name, "B", permanent_id=school.permanent_id)
    assert _pool(game) == {"B": 1}
