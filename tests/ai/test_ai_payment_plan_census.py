"""The AI's payment plan is the engine's exact one, and it pays what it plans.

`ai_policy._plan_land_taps` was a greedy pass over its own reading of what a
land makes. Two things followed, both measured on the tree before this file:

* **It disagreed with the castable highlight** (`board_payment.board_can_pay`)
  on 8 of 14,626 land-and-cost pairs, all Ancient Tomb: "{T}: Add {C}{C}. This
  land deals 2 damage to you." is a two-step effect whose pips the planner's
  amount reader did not open, so a card glowed that the AI seat never cast.
* **It stranded pips a board could pay.** Each coloured pip took the first
  land that could make it and never gave it back: Reflecting Pool, Swamp and
  Forest could not find {B}{G}{G} with the Pool first.

It is `mana_payment.plan_payment` now — the augmenting-path matching the
optional-pay planner and the highlight already ask — over
`board_payment.land_tap_yields`, the highlight's own reading of a tap. So the
census is an equality with the highlight in **both** directions, over the
population the highlight's own census uses
(`tests/engine/test_castable_highlight_asks_the_planner.py`), and then the
half the highlight has no use for: every plan is *executed* through
`tap_planned_lands`, the executor the simulator and the web AI seat share, and
the engine's own payment is asked of the pool that leaves.

The second half of the file is what a plan may now count that it could not: a
source that pays by being sacrificed (Black Lotus). No such source was ever
planned, because a sacrifice during payment renumbers the battlefield under an
announcement the executors made by slot.
"""
from __future__ import annotations

import itertools
from collections import Counter
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from engine import Game, PlayerState, ai_policy
from engine.ai_policy import (_nonland_mana_source, _plan_land_taps,
                              choose_activation_action, choose_cast_action,
                              tap_planned_lands)
from engine.ai_simulator import SimulationReport, _play_one_cast
from engine.board_payment import board_can_pay
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.mana_payment import is_mana_ability
from engine.mixins.turn_management import is_tap_alone_mana_ability
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.restricted_mana import CAST, PaymentPurpose
from engine.targeting import usable_activated_abilities
from tests.helpers import _mk_card, resolve_stack

_SYMBOLS = ("W", "U", "B", "R", "G", "C")

_POOL: dict = {}
for _card in load_cards(manifest_set_paths(include_measured=True)):
    _POOL.setdefault(_card.name, _card)


def _paying(card):
    """The plan's "this is for a spell" context — absent on a tree that has no
    such thing, where the census is run to be validated backwards."""
    context = getattr(ai_policy, "_paying_for", None)
    return context(card) if context is not None else nullcontext()


def _cost_card(cost: tuple[str, ...], *, type_line: str = "Sorcery") -> CardDefinition:
    """A colourless spell that costs *cost* and needs no target."""
    generic = sum(1 for symbol in cost if symbol == "1")
    printed = (f"{{{generic}}}" if generic else "") + "".join(
        f"{{{symbol}}}" for symbol in cost if symbol != "1"
    )
    return CardDefinition(
        name="Cost " + printed, mana_cost=printed, cmc=float(len(cost)),
        type_line=type_line, oracle_text="You gain 1 life.", colors=(),
        color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Cost " + printed, "type_line": type_line},
    )


def _costs_for(land: CardDefinition) -> list[CardDefinition]:
    """The highlight census's costs for one land: one to three symbols out of
    what it lists, generic and one symbol it does not, and {4} {5} {6}."""
    symbols = sorted({str(s).upper() for s in (land.produced_mana or ())} | {"1"})
    control = next((s for s in _SYMBOLS if s not in symbols), None)
    if control is not None:
        symbols.append(control)
    costs: list[tuple[str, ...]] = []
    for size in (1, 2, 3):
        costs.extend(itertools.combinations_with_replacement(symbols, size))
    costs.extend([("1",) * 4, ("1",) * 5, ("1",) * 6])
    return [_cost_card(cost) for cost in costs]


def _lands() -> list[str]:
    return sorted(
        card.name for card in compilation_units(_POOL.values())
        if card.face_of is None and card.primary_type == "land"
        and compile_card_oracle(card).supported
    )


def _board(names) -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.players[0].battlefield = [Permanent(card=_POOL[name]) for name in names]
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game._recompute_continuous_effects()
    return game


def _plan(game: Game, card: CardDefinition):
    required = game._parse_mana_cost(card.mana_cost, x_value=0)
    with _paying(card):
        return _plan_land_taps(game, game.players[0], dict(required))


def _plan_pays_when_executed(names, card: CardDefinition, plan) -> bool:
    """Tap *plan* on a fresh copy of the board through the shared executor and
    ask the cast path's own payment of the pool that leaves."""
    game = _board(names)
    tap_planned_lands(
        game, 0, SimpleNamespace(land_tap_indices=plan[0], land_tap_colors=plan[1]),
    )
    return bool(game._pay_mana_cost(
        game.players[0], game._parse_mana_cost(card.mana_cost, x_value=0),
        purpose=PaymentPurpose(CAST, card=card),
    ))


def _census(boards_and_costs):
    """``(examined, planned, plans the board cannot pay, payable boards the
    plan declines, plans that came up short when tapped)``."""
    examined = planned = 0
    over: Counter = Counter()
    under: Counter = Counter()
    short: Counter = Counter()
    for names, cards in boards_and_costs:
        game = _board(names)
        for card in cards:
            required = game._parse_mana_cost(card.mana_cost, x_value=0)
            plan = _plan(game, card)
            exact = board_can_pay(
                game, 0, dict(required), purpose=PaymentPurpose(CAST, card=card),
            )
            examined += 1
            key = f"{'+'.join(names)} for {card.mana_cost}"
            if plan is not None and not exact:
                over[key] += 1
            if exact and plan is None:
                under[key] += 1
            if plan is not None:
                planned += 1
                if not _plan_pays_when_executed(names, card, plan):
                    short[key] += 1
    return examined, planned, over, under, short


#: The census is cut into slices so a parallel run spreads it; every land is
#: in exactly one.
_SLICES = 4


@pytest.mark.parametrize("part", range(_SLICES))
def test_the_plan_and_the_highlight_agree_and_the_plan_pays(part):
    """Every supported land, alone and in a pair, against every cost the
    highlight census asks of it. Before: 8 payable pairs the planner declined
    (Ancient Tomb, alone and paired) and none it over-planned."""
    boards = []
    for name in _lands()[part::_SLICES]:
        cards = _costs_for(_POOL[name])
        boards += [([name], cards), ([name, name], cards)]
    examined, planned, over, under, short = _census(boards)
    assert not over, f"plans a payment the board cannot make: {dict(over)}"
    assert not under, f"declines a cost the lands can pay: {dict(under)}"
    assert not short, f"the taps did not make what the plan counted: {dict(short)}"
    # Measured: 14,626 pairs and 1,856 plans in all, about a quarter a slice.
    assert examined >= 3400 and planned >= 380, (examined, planned)


#: Lands whose mana overlaps, so one land's choice is another's only way to
#: pay: the boards a greedy pass strands.
_MIXED = ("Swamp", "Forest", "Island", "Reflecting Pool", "City of Brass",
          "Taiga", "Underground Sea")


def _mixed_boards():
    costs = [
        _cost_card(cost)
        for size in (2, 3)
        for cost in itertools.combinations_with_replacement(("U", "B", "G", "R", "1"), size)
    ]
    for trio in itertools.combinations(_MIXED, 3):
        yield list(trio), costs
        yield list(reversed(trio)), costs


def test_a_pip_one_land_took_is_given_back_when_another_needs_it():
    """Three overlapping lands in both board orders, every two- and three-pip
    cost over their colours. Before: the greedy pass declined payable boards
    here — Reflecting Pool, Swamp and Forest for {B}{G}{G} among them."""
    examined, planned, over, under, short = _census(_mixed_boards())
    assert not over, dict(over)
    assert not under, f"declines a cost the lands can pay: {dict(under)}"
    assert not short, dict(short)
    assert examined >= 3400 and planned >= 1500, (examined, planned)

    game = _board(["Reflecting Pool", "Swamp", "Forest", "Forest"])
    plan = _plan(game, _cost_card(("B", "G", "G")))
    assert plan is not None
    named = {game.permanent_at(0, slot).card.name: colour for slot, colour in zip(*plan)}
    assert named["Swamp"] == "B" and named["Forest"] == "G"


def test_a_board_of_basics_is_tapped_in_the_order_it_always_was():
    """The coloured pip first, from the first land that makes it, then the
    generic in board order — and a land with a choice of colours is kept back
    while a land with none can pay."""
    game = _board(["Forest", "Island", "Swamp", "Island"])
    assert _plan(game, _cost_card(("1", "1", "U"))) == ((1, 0, 2), ("U", "G", "B"))
    game = _board(["Taiga", "Mountain", "Forest"])
    plan = _plan(game, _cost_card(("R",)))
    assert [game.permanent_at(0, slot).card.name for slot in plan[0]] == ["Mountain"]


# --- A source that pays by leaving -------------------------------------------


def _table(mine, theirs=(), hand=()) -> Game:
    forest = _POOL["Forest"]
    game = Game(players=[
        PlayerState(name="AI", library=[forest] * 20),
        PlayerState(name="Opp", library=[forest] * 20),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn = 5
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            _enter(game, _POOL[name], seat)
    game.players[0].hand = [_POOL[name] if isinstance(name, str) else name for name in hand]
    return game


def _enter(game: Game, card: CardDefinition, seat: int = 0) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game.auto_resolve_pending_choices()
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = False
    return permanent


def _mana_permanents():
    # By compilation unit, the population every "does its text compile to X"
    # sweep takes (`tests/engine/test_face_blind_guards.py`); a permanent has
    # one face, so the halves are passed over by type.
    for card in sorted(compilation_units(_POOL.values()), key=lambda unit: unit.name):
        name = card.name
        if card.primary_type in ("instant", "sorcery", "land") or card.face_of is not None:
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        abilities = [
            ability for ability in usable_activated_abilities(program)
            if ability.instruction is not None and is_mana_ability(ability)
        ]
        if abilities:
            yield name, card, abilities


def test_every_source_the_plan_counts_and_what_it_leaves_alone():
    """**Sources planned of sources that could be.** Every supported non-land
    permanent with a mana ability, alone beside tapped lands. Before this
    round a plan counted the ones that only tap (62) and none of the 24 that
    are sacrificed; it counts the ones that give up *only themselves* now.
    Each of those is planned for a spell just dear enough to be worth it,
    paid through the shared executor, and has to be in the graveyard with the
    cost paid — and is not planned at all for a spell no bigger than itself,
    nor ever while a free source is asked alone."""
    taps, sacrificed, left = [], [], []
    for name, card, abilities in _mana_permanents():
        game = _table([])
        for seat in (0, 1):
            for land in ("Forest", "Island"):
                _enter(game, _POOL[land], seat).tapped = True
        source = _enter(game, card)
        if not game.is_on_battlefield(source):
            continue  # an entry replacement put it elsewhere (Mox Diamond)
        found = _nonland_mana_source(game, 0, source, may_sacrifice=True)
        if found is None:
            left.append(name)
            continue
        if not found.sacrifices:
            assert _nonland_mana_source(game, 0, source) is not None, name
            taps.append(name)
            continue
        # Asked without the offer, a sacrificed source is not a source.
        assert _nonland_mana_source(game, 0, source) is None, name
        assert not any(is_tap_alone_mana_ability(a) for a in abilities), name
        made = dict(found.run) if found.run else {found.symbols[0]: found.amount}
        pips = tuple(symbol for symbol, count in made.items() for _ in range(count))
        # A spell one mana dearer than the permanent, and no cheaper than what
        # the source makes: the rest comes from Wastes-like colourless rocks.
        size = max(len(pips), int(card.cmc or 0) + 1)
        spell = _cost_card(pips + ("1",) * (size - len(pips)))
        for _ in range(size - len(pips)):
            _enter(game, _POOL["Mox Pearl"])
        seat = game.players[0]
        required = game._parse_mana_cost(spell.mana_cost, x_value=0)

        with _paying(spell):
            plan = _plan_land_taps(game, seat, dict(required))
        assert plan is not None, (name, spell.mana_cost)
        slot = game.battlefield_index_of(source)
        assert slot in plan[0], (name, plan)
        # …and never for a spell no bigger than itself, an ability or a toll.
        if int(card.cmc or 0) >= 1:
            small = _cost_card(pips[:1])
            with _paying(small):
                cheap = _plan_land_taps(
                    game, seat, dict(game._parse_mana_cost(small.mana_cost, x_value=0)),
                )
            assert cheap is None or slot not in cheap[0], (name, cheap)
        bare = _plan_land_taps(game, seat, dict(required))
        assert bare is None or slot not in bare[0], (name, bare)

        tap_planned_lands(
            game, 0, SimpleNamespace(land_tap_indices=plan[0], land_tap_colors=plan[1]),
        )
        assert not game.is_on_battlefield(source), name
        assert any(held is card for held in seat.graveyard), name
        assert game._pay_mana_cost(
            seat, required, purpose=PaymentPurpose(CAST, card=spell),
        ), (name, spell.mana_cost, dict(seat.mana_pool))
        sacrificed.append(name)

    assert len(taps) >= 55, taps
    assert {"Sol Ring", "Llanowar Elves", "Eye of Ramos", "Skull of Ramos"} <= set(taps)
    assert set(sacrificed) >= {
        "Black Lotus", "Lotus Petal", "Blood Pet", "Basal Thrull", "Blood Vassal",
        "Tinder Wall", "Morgue Toad", "Gaea's Touch",
    }, sacrificed
    # What the AI will not give up for mana, by the kind of price: another
    # permanent, a card, a counter, life — and mana for mana.
    assert {
        "Ashnod's Altar", "Phyrexian Altar", "Squandered Resources",   # another permanent
        "Bog Witch", "Skirge Familiar", "Lion's Eye Diamond",          # cards from hand
        "Iceberg", "Phyrexian Lens",                                   # a counter, life
        "Mana Cylix", "Coal Golem", "Implements of Sacrifice",         # mana for mana
    } <= set(left), left


def test_the_lotus_is_the_last_thing_reached_for_and_only_as_many_as_pay():
    """With lands that pay, the Lotus stays; with lands one short, one Lotus
    of two goes and the lands are tapped beside it."""
    bears = _POOL["Grizzly Bears"]
    game = _table(["Forest", "Forest", "Black Lotus"], hand=["Grizzly Bears"])
    action = choose_cast_action(game, 0)
    assert [game.permanent_at(0, s).card.name for s in action.land_tap_indices] == ["Forest", "Forest"]

    game = _table(["Forest", "Black Lotus", "Black Lotus"], hand=["Grizzly Bears"])
    action = choose_cast_action(game, 0)
    assert sorted(
        game.permanent_at(0, s).card.name for s in action.land_tap_indices
    ) == ["Black Lotus", "Forest"], action
    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    assert _play_one_cast(game, 0, report, 1, 1)
    resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(0)].count("Black Lotus") == 1
    assert any(p.card is bears for p in game.controlled_by(0))
    assert [c.name for c in game.players[0].graveyard] == ["Black Lotus"]
    assert not report.refused_casts and not report.issues


def test_an_aura_paid_for_with_the_lotus_lands_on_the_creature_it_named():
    """The reason no sacrificed source was ever planned: the Lotus is in slot
    0, the Aura's host is announced as a slot behind it, and the sacrifice
    moves every one of those slots down. The executor announces the action as
    it reads **after** the payment (`tap_planned_lands`' return)."""
    game = _table(["Black Lotus", "Grizzly Bears", "Hill Giant"], hand=["Holy Strength"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Holy Strength"
    assert [game.permanent_at(0, s).card.name for s in action.land_tap_indices] == ["Black Lotus"]
    host = game.permanent_at(action.target_player_index, action.target_permanent_index)
    other = next(
        p for p in game.controlled_by(0) if p.is_creature and p is not host
    )
    before = (host.effective_power, other.effective_power)

    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    assert _play_one_cast(game, 0, report, 1, 1), game.log[-4:]
    resolve_stack(game)

    assert not report.refused_casts, report.refused_casts
    assert host.effective_power == before[0] + 1, game.log[-6:]
    assert other.effective_power == before[1]
    assert [c.name for c in game.players[0].graveyard] == ["Black Lotus"]


def test_the_lotus_is_not_spent_on_an_ability_or_on_its_own_target():
    """An ability's cost is never worth a permanent, and a spell aimed at the
    source is not paid for by sacrificing it."""
    pump = _mk_card(
        name="Test Pumper", mana_cost="{1}", type_line="Artifact",
        oracle_text="{1}: Target creature gets +1/+1 until end of turn.",
    )
    game = _table(["Black Lotus", "Grizzly Bears"])
    _enter(game, pump)
    assert choose_activation_action(game, 0) is None
    _enter(game, _POOL["Forest"])
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Test Pumper"
    assert [game.permanent_at(0, s).card.name for s in action.land_tap_indices] == ["Forest"]

    # "Enchant artifact" on the seat's only artifact, which is also its only
    # mana: the plan would sacrifice the host.
    aura = _mk_card(
        name="Test Polish", mana_cost="{G}", type_line="Enchantment — Aura",
        oracle_text="Enchant artifact\nEnchanted artifact has flying.",
    )
    game = _table(["Black Lotus"], hand=[aura])
    assert choose_cast_action(game, 0) is None
