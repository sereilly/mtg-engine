"""No planner tapped a source that hurts while one that does not sat beside it:
a census of what a tap costs, and of who pays it.

Every planner chose which sources pay a cost by the payer's other wants
(``mana_payment._sparing_choice``) and, where nothing was wanted, by the order
the sources were listed in — blind to what a source charges beyond the tap. A
City of Brass paid a {1} beside a Swamp; a Karplusan Forest first on the
battlefield was asked for the {R} while a Mountain paid the generic; kg2's
preference kept an Island by tapping Timberline Ridge. ``engine/mana_drawbacks``
is the price — read off what the tap runs: the mana ability's own steps, every
trigger the tap fires (its own, an Aura's, a "whenever a player taps a land
for mana"), its standing text about staying tapped — and the sparing choice
weighs it after the wants.

Two censuses:

* **The price is what the tap costs.** Every plannable mana source in the
  shipped pool, alone on a board, and each symbol it can be asked for — and
  every card printing a tap trigger, on a board where it watches a land or a
  mana creature — is tapped through the engine's own seams, the turn is run
  through its end step, its controller's untap step, upkeep and draw step,
  and what it cost (life, a source lost, a missed untap or a return to the
  hand, a harmful counter) is held to ``mana_drawbacks.tap_prices``.
* **No payment pays more than it must.** For boards mixing each kind of
  drawback source with free sources of its colours, and every real mana cost
  they can pay, each planner — the AI's (the web auto-tap's), and the effect
  payer's (``Game._pay_planned_cost``) — pays, and the price it paid is
  compared with the cheapest set of sources and colours that pays the cost
  and leaves the payer's want as payable. A **strand** is a payment dearer
  than that, or one that strands the want where a set of sources would have
  kept it. Run backwards with the prices switched off, both planners strand.

The effect payer used to credit a land with **one** mana (``plan_payment``
over ``Game.payment_lands``), so Ancient Tomb's second {C} was invisible to
its sparing choice and a card in hand only that mana could keep payable was
stranded — 3 rows of the one-in-twenty sample, held out of the count as
``multi_mana`` until round ``kg3``'s ``leftovers`` group. It now plans a land
that makes several mana a tap as that many units of one source
(``board_payment.land_payment_units``, the AI planner's ``land_tap_yields``),
and those rows are counted like every other; with the units switched off
(:func:`_one_mana_per_land`) they strand again.
"""
from __future__ import annotations

import itertools
import re
from contextlib import contextmanager
from unittest import mock

import pytest

from engine import Game, PlayerState
from engine import mana_payment
from engine.ai_mana_sources import _nonland_mana_source
from engine.ai_payment import _PaymentPlanner, _paying_for, tap_planned_lands
from engine.board_payment import land_tap_yields
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.mana_drawbacks import SOURCE_LOST, tap_prices
from engine.mana_payment import mana_cost_from_symbols, plan_payment
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack, stable_sample

_CARDS = {card.name: card for card in load_catalog()}

_SYMBOLS = ("W", "U", "B", "R", "G", "C")
_ENTERS_WITH = re.compile(r"enters with (one|two|three|four|five) ([a-z]+) counters? on it")
_NUMBER = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def _game(cards, *, active: int = 0, theirs=()) -> Game:
    game = Game(players=[
        PlayerState(name="P1", library=[_CARDS["Island"]] * 10),
        PlayerState(name="P2", library=[_CARDS["Island"]] * 10),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = True
    game.players[0].battlefield = [Permanent(card=card) for card in cards]
    game.players[1].battlefield = [Permanent(card=card) for card in theirs]
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
        # The counters it would have entered with ("This Aura enters with
        # three ore counters on it", Orcish Mine).
        entered = _ENTERS_WITH.search((permanent.card.oracle_text or "").lower())
        if entered:
            add_counters(permanent, entered.group(2), _NUMBER.get(entered.group(1), 0))
    game.active_player_index = active
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game._recompute_continuous_effects()
    return game


# -- census 1: the price is what the tap costs ----------------------------------


def _what_it_is_asked_for(game, permanent):
    """``(symbols, ability index)`` the planners may ask *permanent* for, or
    None where no planner taps it."""
    if permanent.has_type("land"):
        symbols = sorted({
            symbol for found in land_tap_yields(game, permanent)
            for unit in found.units for symbol in unit if symbol in _SYMBOLS
        })
        return (symbols, None) if symbols else None
    source = _nonland_mana_source(game, 0, permanent)
    if source is None:
        return None
    return sorted(s for s in source.symbols if s in _SYMBOLS), source.ability_index


def _tap(game, permanent, symbol, ability_index):
    if permanent.has_type("land"):
        return game.tap_land_for_mana(
            0, permanent.card.name, symbol, permanent_id=permanent.permanent_id,
            ability_index=game.land_mana_ability_for(permanent, symbol),
        )
    slot = game.battlefield_index_of(permanent)
    result = game.activate_permanent_ability(
        0, permanent.card.name, permanent_index=slot, ability_index=ability_index,
        mana_color=symbol if symbol in ("W", "U", "B", "R", "G") else None,
    )
    return result.supported


def _settle(game) -> None:
    """Drain the stack and answer whatever it left owed with the defaults an
    AI or headless seat takes (an "unless that player pays" offer)."""
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)


def _turn_cost(game, permanent, symbol, ability_index, *, tap: bool) -> "int | None":
    """What seat 0 lost over the rest of the turn and its next beginning
    phase — with *permanent* tapped for *symbol* first, or not: through the
    end step, the controller's untap step, upkeep and draw step."""
    auras = [
        aura for aura in game.all_permanents()
        if aura.metadata.get("attached_to") is permanent
    ]
    ore = {id(aura): counters_on(aura, "ore") for aura in auras}
    shackles = counters_on(permanent, "-0/-2")
    life = game.players[0].life
    if tap and not _tap(game, permanent, symbol, ability_index):
        return None
    _settle(game)
    game.resolve_end_step(game.active_player_index)
    _settle(game)
    harm = life - game.players[0].life
    if not game.is_on_battlefield(permanent) or game.controller_index_of(permanent) != 0:
        # Back in its owner's hand is a land drop to play it again; anywhere
        # else, or another seat's, the source is gone.
        in_hand = any(card is permanent.card for card in game.players[0].hand)
        return harm + (1 if in_hand else SOURCE_LOST)
    harm += counters_on(permanent, "-0/-2") - shackles
    harm += sum(
        ore[id(aura)] - counters_on(aura, "ore") for aura in auras
        if game.is_on_battlefield(aura)
    )
    life = game.players[0].life
    game.resolve_untap_step(0)
    _settle(game)
    if not game.is_on_battlefield(permanent) or permanent.tapped:
        harm += 1  # it stayed tapped, or went back to the hand instead
    game.resolve_upkeep(0)
    _settle(game)
    game.resolve_draw_step(0)
    _settle(game)
    return harm + life - game.players[0].life


def _measured(build, position, symbol, ability_index) -> "int | None":
    """What tapping the source costs: the turn run with the tap, less the same
    turn run without it on a twin board (an upkeep life gain, a land that
    phases out, an end-step sacrifice are the board's, not the tap's)."""
    game = build()
    tapped = _turn_cost(
        game, game.players[0].battlefield[position], symbol, ability_index, tap=True,
    )
    if tapped is None:
        return None
    twin = build()
    untouched = _turn_cost(
        twin, twin.players[0].battlefield[position], symbol, ability_index, tap=False,
    )
    return tapped - untouched


def _price_rows():
    """``(label, board cards, theirs, active, the source's position)`` for
    every plannable source alone, then every tap-trigger card watching a
    land or a mana creature."""
    for name in sorted(_CARDS):
        card = _CARDS[name]
        program = compile_card_oracle(card)
        if card.primary_type == "land" or any(
            "add" in (ability.source_line or "").lower() for ability in program.activated_abilities
        ):
            yield name, [card], [], 0, 0
    watchers = [
        card for card in compilation_units(_CARDS.values())
        if any(
            trig.condition is not None and trig.condition.kind in (
                "permanent_becomes_tapped", "permanent_tapped_or_ability_activated",
                "land_tapped_for_mana",
            )
            for trig in compile_card_oracle(card).triggered_abilities
        )
    ]
    for watcher in sorted(watchers, key=lambda card: card.name):
        for host in ("Swamp", "Llanowar Elves", "Sol Ring"):
            for active in (0, 1):
                yield (f"{watcher.name} / {host} / active {active}",
                       [_CARDS[host], watcher], [], active, 0)
                yield (f"{watcher.name} (theirs) / {host} / active {active}",
                       [_CARDS[host]], [watcher], active, 0)


def _attach_if_aura(game, cards) -> bool:
    """Attach an Aura among the board's cards to the source (seat 0's first
    permanent) — False where it may not enchant it."""
    from engine.aura_attachment import attach_aura, aura_attach_refusal, is_aura_card

    source = game.players[0].battlefield[0]
    for permanent in list(game.all_permanents()):
        if permanent is not source and is_aura_card(permanent.card):
            if aura_attach_refusal(game, permanent, source) is not None:
                return False
            attach_aura(permanent, source)
    game._recompute_continuous_effects()
    return True


#: Tap prices the derivation does not read yet, each with what it misses —
#: held to still disagree, so the day one is priced its entry goes.
UNPRICED = {
    # A counter put on the tapped permanent that another card's text keeps
    # tapped (a "would untap" replacement, a board-wide untap restriction on
    # "each permanent with an hourglass counter"): the price would need the
    # untap step's own judgement of a counter that is not there yet.
    "Freyalise's Winds": "a wind counter on the tapped permanent; the Winds replace its untap",
    "Temporal Distortion": "an hourglass counter on the tapped permanent; the Distortion keeps it tapped",
}


def _price_census() -> dict:
    found = {"examined": 0, "priced": 0, "wrong": [], "unpriced": [], "sources": set()}
    for label, cards, theirs, active, position in _price_rows():

        def build(cards=cards, theirs=theirs, active=active):
            game = _game(cards, active=active, theirs=theirs)
            return game if _attach_if_aura(game, cards) else None

        probe = build()
        if probe is None:
            continue
        asked = _what_it_is_asked_for(probe, probe.players[0].battlefield[position])
        if asked is None:
            continue
        symbols, ability_index = asked
        for symbol in symbols:
            game = build()
            permanent = game.players[0].battlefield[position]
            derived = tap_prices(game, permanent, [symbol], ability_index=ability_index)[symbol]
            measured = _measured(build, position, symbol, ability_index)
            if measured is None:
                continue
            found["examined"] += 1
            found["sources"].add(label)
            found["priced"] += bool(derived)
            if derived == measured:
                continue
            row = (label, symbol, derived, measured)
            if any(label.startswith(name) for name in UNPRICED):
                found["unpriced"].append(row)
            else:
                found["wrong"].append(row)
    return found


@pytest.fixture(scope="module")
def price_census():
    return _price_census()


def test_the_price_is_what_the_tap_costs(price_census):
    assert price_census["wrong"] == [], price_census["wrong"][:20]
    assert price_census["examined"] >= 500, price_census["examined"]
    assert price_census["priced"] >= 50, price_census["priced"]


def test_the_unpriced_shapes_are_still_unpriced(price_census):
    """Each ``UNPRICED`` entry still disagrees: a fix removes its entry."""
    seen = {label.split(" ")[0] for label, *_ in price_census["unpriced"]}
    named = {
        name for name in UNPRICED
        if any(row[0].startswith(name) for row in price_census["unpriced"])
    }
    assert named == set(UNPRICED), (named, seen)


def test_a_derivation_reading_nothing_is_wrong_wherever_a_tap_costs(price_census):
    """Backwards: every row the census priced is a row a price of 0 gets
    wrong — the census measures the price, not its own echo."""
    assert price_census["priced"] >= 50


# -- census 2: no payment pays more than it must --------------------------------

#: label -> seat 0's battlefield (an Aura in it is attached to the first
#: permanent). Each kind of drawback beside free sources of its colours.
BOARDS: dict[str, list[str]] = {
    "a painland first": ["Karplusan Forest", "Mountain", "Forest", "Plains"],
    "a painland last": ["Plains", "Island", "Island", "Adarkar Wastes"],
    "a City of Brass first": ["City of Brass", "Swamp", "Forest", "Forest"],
    "a depletion land": ["Timberline Ridge", "Mountain", "Forest", "Island"],
    "a land that skips its untap": ["Cinder Marsh", "Swamp", "Mountain", "Plains"],
    "an Ancient Tomb": ["Ancient Tomb", "Plains", "Plains", "Mountain"],
    "a Tarnished Citadel": ["Tarnished Citadel", "Island", "Swamp", "Plains"],
    "a Grand Coliseum": ["Grand Coliseum", "Forest", "Forest", "Island"],
    "an Undiscovered Paradise": ["Undiscovered Paradise", "Plains", "Island", "Island"],
    "a Rainbow Vale": ["Rainbow Vale", "Forest", "Mountain", "Mountain"],
    "a threshold land": ["Barbarian Ring", "Mountain", "Mountain", "Plains"],
    "two drawbacks": ["Karplusan Forest", "City of Brass", "Forest", "Mountain"],
    "a Psychic Venom on a Swamp": ["Swamp", "Psychic Venom", "Swamp", "Forest"],
    "an Elves of Deep Shadow": ["Elves of Deep Shadow", "Swamp", "Swamp", "Forest"],
    "a Mana Vault": ["Mana Vault", "Plains", "Plains", "Mountain", "Mountain"],
}

#: The boards the effect payer can be asked over: it taps lands only.
_LAND_ONLY = {
    label for label, names in BOARDS.items()
    if all(_CARDS[name].primary_type == "land" or "Aura" in _CARDS[name].type_line for name in names)
}


def _drawback_board(names, hand=()) -> Game:
    game = _game([_CARDS[name] for name in names])
    _attach_if_aura(game, None)
    game.players[0].hand = list(hand)
    return game


def _alternatives(game, permanent, options, ability_index):
    """``[(made, price)]`` — each way one tap of *permanent* can come out:
    the symbols it makes and what that tap costs."""
    found = []
    for option in options:
        if option.ask is not None:
            asks = [(option.ask, [option.ask] * len(option.units))]
        elif len(option.units) == 1:
            asks = [(symbol, [symbol]) for symbol in sorted(option.units[0]) if symbol in _SYMBOLS]
        else:
            made = [sorted(unit)[0] for unit in option.units]
            asks = [(made[0], made)]
        for symbol, made in asks:
            price = tap_prices(game, permanent, [symbol], ability_index=ability_index)[symbol]
            found.append((tuple(made), price))
    return found


def _pays(made, cost) -> bool:
    left = list(made)
    for symbol in _SYMBOLS:
        for _ in range(int(cost.get(symbol, 0))):
            if symbol not in left:
                return False
            left.remove(symbol)
    return len(left) >= int(cost.get("generic", 0))


def _cheapest(game, planner, cost, want=None) -> "int | None":
    """The least any set of the planner's sources, asked for any symbols,
    pays *cost* for — leaving *want* payable by the rest where one is named
    and some set can."""
    ways = []
    for source in planner.sources:
        permanent = game.permanent_at(0, source.slot)
        index = None
        if not permanent.has_type("land"):
            nonland = _nonland_mana_source(game, 0, permanent)
            index = nonland.ability_index if nonland is not None else None
        ways.append((source, _alternatives(game, permanent, source.options, index)))
    best = None
    best_keeping = None
    for size in range(1, len(ways) + 1):
        for chosen in itertools.combinations(ways, size):
            for picks in itertools.product(*(alternatives for _source, alternatives in chosen)):
                made = [symbol for symbols, _price in picks for symbol in symbols]
                if not _pays(made, cost):
                    continue
                price = sum(price for _symbols, price in picks)
                best = price if best is None else min(best, price)
                if want is not None:
                    taken = {source.slot for source, _alts in chosen}
                    rest = [s for s in planner.sources if s.slot not in taken]
                    if planner._plan_with(rest, want) is not None:
                        best_keeping = price if best_keeping is None else min(best_keeping, price)
    if want is not None and best_keeping is not None:
        return best_keeping
    return best


def _paid_by_ai(game, cost):
    planner = _PaymentPlanner(game, game.players[0])
    found = planner.plan(cost)
    if found is None:
        return None
    left = [source for source in planner.sources if source.slot not in set(found[0])]
    total = 0
    for slot, colour in zip(*found):
        permanent = game.permanent_at(0, slot)
        index = None
        if not permanent.has_type("land"):
            nonland = _nonland_mana_source(game, 0, permanent)
            index = nonland.ability_index if nonland is not None else None
        total += tap_prices(game, permanent, [colour], ability_index=index)[colour]
    return total, lambda want: planner._plan_with(left, want) is not None


def _paid_by_effect(game, cost):
    """`Game._pay_planned_cost` over `plan_payment` and `Game.payment_lands`,
    each tap it really makes priced as it is made."""
    player = game.players[0]
    taps: list = []
    real = game.tap_land_for_mana

    def recording(seat, name, color=None, *args, permanent_id=None, ability_index=None, **kwargs):
        land = game.permanent_by_id(permanent_id)
        taps.append(tap_prices(game, land, [color])[color] if land is not None else 0)
        return real(seat, name, color, *args, permanent_id=permanent_id,
                    ability_index=ability_index, **kwargs)

    with mock.patch.object(game, "tap_land_for_mana", recording):
        paid = game._pay_planned_cost(player, lambda: plan_payment(
            player.mana_pool, game.payment_lands(0), cost,
            produces=game._land_payment_colors, payer=player,
        ))
    if not paid:
        return None
    player.mana_pool.clear()

    def keeps(want):
        return _PaymentPlanner(game, player).plan(want) is not None

    return sum(taps), keeps


PAYERS = {"ai": _paid_by_ai, "effect": _paid_by_effect}

#: One (board, cost, want) row in this many with a want in hand; the full
#: pass (`MTG_FULL_CENSUS`) examines every one.
_EVERY_WANT = 20
_EVERY_COST = 2


def _real_costs() -> dict:
    from tests.ai.test_kg2_payment_colour_census import _real_costs as kg2_costs

    return kg2_costs()


def _payment_census(payer: str, *, with_want: bool = False) -> dict:
    costs = _real_costs()
    found = {"examined": 0, "strands": [], "boards": set(), "multi_mana": 0}
    pay = PAYERS[payer]
    for label, names in BOARDS.items():
        if payer == "effect" and label not in _LAND_ONLY:
            continue
        bare = _drawback_board(names)
        planner = _PaymentPlanner(bare, bare.players[0])
        payable = [
            printed for printed in costs
            if planner.plan(mana_cost_from_symbols(printed) or {}) is not None
        ]
        wants = payable if with_want else [None]
        for printed in payable:
            if not with_want and not stable_sample("|".join((label, printed)), _EVERY_COST):
                continue
            cost = mana_cost_from_symbols(printed) or {}
            for wanted in wants:
                if wanted and not stable_sample("|".join((label, printed, wanted)), _EVERY_WANT):
                    continue
                want = mana_cost_from_symbols(wanted) if wanted else None
                if want is not None and planner.plan(_together(cost, want)) is None:
                    continue
                hand = [costs[wanted]] if wanted else []
                game = _drawback_board(names, hand)
                least = _cheapest(game, _PaymentPlanner(game, game.players[0]), cost, want)
                paid = pay(game, cost)
                if paid is None or least is None:
                    continue
                found["examined"] += 1
                found["boards"].add(label)
                # Rows on a board with a land making several mana a tap:
                # counted like the rest (the module's note), and counted here
                # so the census says it examined them.
                found["multi_mana"] += bool(want is not None and _makes_several(game))
                if paid[0] > least:
                    found["strands"].append((label, printed, wanted, paid[0], least))
                elif want is not None and not paid[1](want) and _a_set_keeps(
                    _drawback_board(names), cost, want,
                ):
                    found["strands"].append((label, printed, wanted, "want stranded"))
    return found


def _makes_several(game) -> bool:
    """Whether a land on seat 0's battlefield makes more than one mana a tap."""
    return any(
        len(found.units) > 1
        for land in game.controlled_by(0) if land.has_type("land")
        for found in land_tap_yields(game, land)
    )


def _a_set_keeps(game, cost, want) -> bool:
    """Whether some set of sources pays *cost* and leaves *want* payable."""
    planner = _PaymentPlanner(game, game.players[0])
    for size in range(1, len(planner.sources) + 1):
        for chosen in itertools.combinations(planner.sources, size):
            rest = [s for s in planner.sources if s not in chosen]
            if planner._plan_with(list(chosen), cost) is not None and (
                planner._plan_with(rest, want) is not None
            ):
                return True
    return False


def _together(first, second):
    total = dict(first)
    for symbol, amount in second.items():
        total[symbol] = total.get(symbol, 0) + amount
    return total


@contextmanager
def _price_blind():
    """The tree before: no planner is told what a tap costs."""
    from engine import mana_drawbacks

    def nothing(game, permanent, symbols, **kwargs):
        return {symbol: 0 for symbol in symbols}

    with mock.patch.object(mana_drawbacks, "tap_prices", nothing):
        yield


@pytest.fixture(scope="module", params=sorted(PAYERS))
def payment_census(request):
    return request.param, _payment_census(request.param)


def test_no_payment_pays_more_than_it_must(payment_census):
    name, found = payment_census
    assert found["strands"] == [], (name, found["strands"][:10])


def test_the_payment_census_examined_enough(payment_census):
    name, found = payment_census
    floor = 250 if name == "ai" else 200
    assert found["examined"] >= floor, (name, found["examined"])
    assert len(found["boards"]) >= (len(BOARDS) if name == "ai" else len(_LAND_ONLY)), (
        name, sorted(found["boards"]),
    )


@pytest.fixture(scope="module", params=sorted(PAYERS))
def wanting_census(request):
    return request.param, _payment_census(request.param, with_want=True)


def test_a_price_is_weighed_after_the_wants(wanting_census):
    """With a card in hand: no payment strands it where a set of sources
    would have kept it, and none pays more than the cheapest set that does."""
    name, found = wanting_census
    assert found["strands"] == [], (name, found["strands"][:10])
    assert found["examined"] >= 180, (name, found["examined"])
    assert found["multi_mana"] >= 3, (name, found["multi_mana"])


@contextmanager
def _one_mana_per_land():
    """The effect payer before: every land one unit of mana."""
    from engine import board_payment

    with mock.patch.object(board_payment, "land_payment_units", lambda game, land: None):
        yield


@pytest.mark.full
def test_the_wanting_census_names_the_one_mana_per_land_payer():
    """Backwards: with each land credited one mana, the effect payer strands
    a want only an Ancient Tomb's second {C} could keep — on the rows the
    census used to hold out as ``multi_mana``."""
    with _one_mana_per_land():
        found = _payment_census("effect", with_want=True)
    tomb = [row for row in found["strands"] if row[0] == "an Ancient Tomb"]
    assert len(tomb) >= 3, found["strands"]


@pytest.mark.full
def test_the_payment_census_names_the_price_blind_planner():
    """Backwards: with the prices switched off, both planners pay more than
    they must — measured over every row with nothing wanted: 29 (AI) and 201
    (effect payer) of 613 and 548; with a want, of a one-in-twenty sample, 3
    and 29 of 119 and 107."""
    with _price_blind():
        for name in PAYERS:
            floor = 10 if name == "ai" else 50
            assert len(_payment_census(name)["strands"]) >= floor, name
            assert len(_payment_census(name, with_want=True)["strands"]) >= 2, name
