"""Paying for one thing leaves the payer's next thing payable: a census over
boards × costs, for every planner that chooses which sources pay.

Two planners choose which sources pay a cost, and both chose by the order the
sources were listed in, blind to what the payer still wanted:

* **the AI's payment plan** (`ai_payment._PaymentPlanner`), which the web's
  auto-tap asks too: a face-down {3} on four Plains and three Mountains
  tapped three Plains and stranded Exalted Angel's {2}{W}{W} turn-up; Astral
  Slide's {2}{W} on Plains, Mountain, Plains, Mountain, Plains, Plains tapped a
  Mountain and stranded Solar Blast's cycling {1}{R}{R} (Onslaught's Phase 5);
* **every effect-collected cost** (`Game._pay_planned_cost` over
  `mana_payment.plan_payment`) — an upkeep price, a toll, a counterspell's
  "unless", an optional offer, a turn-up — which listed the lands in board
  order and took a City of Brass for a {1} beside a Swamp.

Both now go through one preference (`mana_payment._sparing_choice`): of the
ways to pay, the one that leaves the most of the payer's other wants
(`mana_wants.mana_wants`) payable. Measured on the tree before it, over every
pair below: the AI planner stranded 680 of 6,583 pairs, the effect payer
1,168 of 5,654; after it, none.

**The census.** For each board and each pair *(cost paid now, want left)*
drawn from the pool's real mana costs — one card per distinct printed cost —
where the board can pay both together (so *some* payment of the first leaves
the second payable): the want's card goes into the payer's hand, the cost is
planned the way each planner plans it, and the rest of the board is asked to
pay the want. A **strand** is a pair where it cannot. The AI planner is asked
with the spell being cast in hand beside the want (the cast leaves its own
copy out); the effect payer is driven through `Game._pay_planned_cost`, so
the lands are really tapped for mana.

A Sol Ring makes two mana with one tap, so "the board can pay both together"
can count its two units toward both — which only floating mana within one step
does. Such a pair (no set of *sources* pays the cost and leaves the want
payable) is counted apart as ``floating_only``, never as a strand: the
planner scores a part-spent source as tapped (CR 106.4 empties its other unit
at the step's end) and prefers the choice that taps fewer sources.

`test_the_census_names_the_order_blind_planner` runs it backwards — the
sparing choice switched off — and must find strands on both planners, the
entry's two boards among them.
"""
from __future__ import annotations

import itertools
from contextlib import contextmanager
from unittest import mock

import pytest

from engine import Game, PlayerState, mana_payment
from engine.activation_zones import HAND
from engine.ai_payment import _PaymentPlanner, _paying_for
from engine.card_loader import load_catalog
from engine.mana_payment import mana_cost_from_symbols, plan_payment
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import stable_sample

_CARDS = {card.name: card for card in load_catalog()}

#: label -> battlefield. Basics in different orders and mixes, a dual, a
#: painland, a five-colour land, a two-colour land, and non-land sources: one
#: that makes two units with one tap, a creature, a five-colour creature.
BOARDS: dict[str, list[str]] = {
    "four Plains, three Mountains": ["Plains"] * 4 + ["Mountain"] * 3,
    "Plains and Mountains interleaved": [
        "Plains", "Mountain", "Plains", "Mountain", "Plains", "Plains",
    ],
    "Mountains first": ["Mountain", "Mountain", "Plains", "Plains", "Plains"],
    "three colours of basics": ["Forest", "Island", "Swamp", "Forest", "Island", "Swamp"],
    "a dual among basics": ["Tundra", "Plains", "Island", "Mountain", "Mountain"],
    "a dual first": ["Plateau", "Mountain", "Plains", "Island", "Plains"],
    "a painland": ["Adarkar Wastes", "Plains", "Island", "Mountain", "Mountain"],
    "a City of Brass": ["City of Brass", "Swamp", "Swamp", "Forest", "Forest"],
    "a two-colour land": ["Shivan Oasis", "Forest", "Mountain", "Plains", "Plains"],
    "a Sol Ring": ["Sol Ring", "Plains", "Mountain", "Mountain"],
    "a Llanowar Elves": ["Llanowar Elves", "Forest", "Island", "Island", "Forest"],
    "a Birds of Paradise": ["Birds of Paradise", "Forest", "Swamp", "Swamp"],
}

#: The entry's two boards, examined whatever the sample: a face-down {3}
#: against Exalted Angel's {2}{W}{W}, and Astral Slide's {2}{W} against Solar
#: Blast's cycling {1}{R}{R} — each a printed mana cost here too.
ENTRY_ROWS = (
    ("four Plains, three Mountains", "{3}", "{2}{W}{W}"),
    ("Plains and Mountains interleaved", "{2}{W}", "{1}{R}{R}"),
)

#: One pair in this many is examined in the quick pass; the full pass
#: (`MTG_FULL_CENSUS`) examines every one.
_EVERY = 12


def _real_costs() -> dict[str, object]:
    """``{printed cost: card}`` — one card per distinct mana cost a payment
    can read: a non-land whose program is supported and which has no ability
    that works from a hand (so the card in hand is one want, not two)."""
    found: dict[str, object] = {}
    for name in sorted(_CARDS):
        card = _CARDS[name]
        if card.primary_type == "land":
            continue
        cost = mana_cost_from_symbols(card.mana_cost or "")
        if not cost:
            continue
        printed = mana_payment.mana_cost_label(cost)
        if printed in found:
            continue
        program = compile_card_oracle(card)
        if not program.supported or usable_activated_abilities(program, zone=HAND):
            continue
        found[printed] = card
    return found


def _board(names, hand=()) -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.players[0].battlefield = [Permanent(card=_CARDS[name]) for name in names]
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.players[0].hand = list(hand)
    game._recompute_continuous_effects()
    return game


def _cost(printed: str) -> dict[str, int]:
    return dict(mana_cost_from_symbols(printed) or {})


def _together(first: dict, second: dict) -> dict:
    total = dict(first)
    for symbol, amount in second.items():
        total[symbol] = total.get(symbol, 0) + amount
    return total


def _what_it_makes(planner: _PaymentPlanner) -> "tuple[set[str], int]":
    made: set[str] = set()
    for source in planner.sources:
        for option in source.options:
            for unit in option.units:
                made |= set(unit)
    units = sum(max(len(option.units) for option in s.options) for s in planner.sources)
    return made & set("WUBRGC"), units


def _rows(names, costs):
    """``(cost printed, want printed)`` for every pair the board could pay
    together, sampled — the entry's rows always."""
    empty = _board(names)
    planner = _PaymentPlanner(empty, empty.players[0])
    made, units = _what_it_makes(planner)
    usable = [
        printed for printed in costs
        if {s for s in _cost(printed) if s != "generic"} <= made
        and sum(_cost(printed).values()) <= units
    ]
    payable = {printed for printed in usable if planner.plan(_cost(printed)) is not None}
    label = next(key for key, value in BOARDS.items() if value == names)
    for first, second in itertools.product(sorted(payable), sorted(payable)):
        row = (label, first, second)
        if row not in ENTRY_ROWS and not stable_sample("|".join(row), _EVERY):
            continue
        if planner.plan(_together(_cost(first), _cost(second))) is None:
            continue
        yield first, second


def _sources_leave(names, first: dict, second: dict) -> bool:
    """Whether some set of *sources* pays *first* with the untouched rest
    paying *second* — the joint plan counts a Sol Ring's two units toward
    both, which only one step's floating mana does."""
    game = _board(names)
    planner = _PaymentPlanner(game, game.players[0])
    for size in range(len(planner.sources) + 1):
        for chosen in itertools.combinations(planner.sources, size):
            rest = [source for source in planner.sources if source not in chosen]
            if planner._plan_with(list(chosen), first) is not None and (
                planner._plan_with(rest, second) is not None
            ):
                return True
    return False


@contextmanager
def _order_blind():
    """The tree before the sparing choice: every planner pays in its order."""
    with mock.patch.object(mana_payment, "_sparing_choice", lambda *args, **kwargs: None):
        yield


def _ai_census() -> dict:
    """The AI planner (`_PaymentPlanner`, `_plan_land_taps`' body and the
    web auto-tap's planner), asked with the spell and the want in hand."""
    costs = _real_costs()
    found = {"examined": 0, "strands": [], "floating_only": [], "boards": set(), "rows": set()}
    for label, names in BOARDS.items():
        game = _board(names)
        player = game.players[0]
        for first, second in _rows(names, costs):
            player.hand = [costs[first], costs[second]]
            with _paying_for(costs[first]):
                planner = _PaymentPlanner(game, player)
            slots, _colours = planner.plan(_cost(first))
            left = [source for source in planner.sources if source.slot not in slots]
            found["examined"] += 1
            found["boards"].add(label)
            found["rows"].add((label, first, second))
            if planner._plan_with(left, _cost(second)) is not None:
                continue
            row = (label, first, second, [game.permanent_at(0, s).card.name for s in slots])
            if _sources_leave(names, _cost(first), _cost(second)):
                found["strands"].append(row)
            else:
                found["floating_only"].append(row)
    return found


def _effect_census() -> dict:
    """The effect payer: `Game._pay_planned_cost` over `plan_payment` and
    `Game.payment_lands`, the lands really tapped for mana."""
    costs = _real_costs()
    found = {"examined": 0, "strands": [], "boards": set(), "rows": set()}
    for label, names in BOARDS.items():
        if not all(_CARDS[name].primary_type == "land" for name in names):
            continue
        for first, second in _rows(names, costs):
            game = _board(names, hand=[costs[second]])
            player = game.players[0]

            def planner(required, game=game, player=player):
                return lambda: plan_payment(
                    player.mana_pool, game.payment_lands(0), required,
                    produces=game._land_payment_colors, payer=player,
                )

            assert game._pay_planned_cost(player, planner(_cost(first))), (label, first)
            found["examined"] += 1
            found["boards"].add(label)
            found["rows"].add((label, first, second))
            if planner(_cost(second))() is None:
                found["strands"].append((
                    label, first, second,
                    [p.card.name for p in game.controlled_by(0) if p.tapped],
                ))
    return found


@pytest.fixture(scope="module")
def ai_census():
    return _ai_census()


@pytest.fixture(scope="module")
def effect_census():
    return _effect_census()


def test_the_ai_planner_leaves_every_want_a_payment_could_have_left(ai_census):
    """680 of 6,583 pairs stranded before. A pair only floating mana could
    keep is not one: it is on a board with a source that makes two units."""
    assert ai_census["strands"] == []
    assert {row[0] for row in ai_census["floating_only"]} <= {"a Sol Ring"}


def test_an_effect_collected_cost_leaves_every_want_it_could_have_left(effect_census):
    """1,168 of 5,654 pairs stranded before — a City of Brass spent on a {1}
    beside a Swamp, three Plains on a {3} beside the Mountains."""
    assert effect_census["strands"] == []


def test_the_census_examined_enough(ai_census, effect_census):
    assert ai_census["boards"] == set(BOARDS), ai_census["boards"]
    assert len(effect_census["boards"]) >= 9, effect_census["boards"]
    assert ai_census["examined"] >= 450, ai_census["examined"]
    assert effect_census["examined"] >= 400, effect_census["examined"]
    for row in ENTRY_ROWS:
        assert row in ai_census["rows"], row
        assert row in effect_census["rows"], row


def test_the_census_names_the_order_blind_planner():
    """Run backwards: with the sparing choice switched off, both planners
    strand — the entry's two boards among them — so a census reading zero is
    measuring this defect."""
    with _order_blind():
        ai = _ai_census()
        effect = _effect_census()
    assert len(ai["strands"]) >= 40, len(ai["strands"])
    assert len(effect["strands"]) >= 70, len(effect["strands"])
    for row in ENTRY_ROWS:
        assert row in {strand[:3] for strand in ai["strands"]}, row
        assert row in {strand[:3] for strand in effect["strands"]}, row
