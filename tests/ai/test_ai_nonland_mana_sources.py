"""The AI's payment plan counts mana that does not come from a land.

`ai_policy._plan_land_taps` asked the tap seam's gate of every permanent, and
that gate's first line refuses anything that is not a land. So the Moxen, Sol
Ring, Llanowar Elves, Birds of Paradise and every other "{T}: Add …" permanent
were **cast and never used**: W1G5 measured it on four Planeshift cards and
inferred the rest. Measured: 131 mana abilities on 122 supported non-land
permanents across both manifest roles, 64 of them a bare "{T}: Add …" (62
shipped), and in ten seeded Alpha games nineteen such permanents entered the
battlefield and none made a mana.

The plan now counts a non-land's mana ability when **its whole cost is {T}**
and what one activation makes can be read off the compiled ability
(``ai_valuation.planned_mana_yield``), after every land. A mana ability with a
further cost is not free mana and stays out: "{1}, {T}: Add one mana of any
color" (Mana Cylix), "{T}, Sacrifice this artifact" (Black Lotus), "Sacrifice
this creature" (Morgue Toad).

The census below is the honesty check the land side has had since NEM — what
the plan believes a source makes, against what activating it makes — over
every such permanent in the pool. On the tree before this it counts none.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import (CastAction, _can_pay_cost, _nonland_mana_source,
                              _plan_land_taps, choose_activation_action,
                              choose_cast_action, tap_planned_lands)
from engine.ai_valuation import ManaYield, planned_mana_yield
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.mana_payment import is_mana_ability
from engine.mixins.turn_management import is_tap_alone_mana_ability
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _mk_card, resolve_stack

#: Non-land permanents whose plan-counted mana the census drove, both roles.
_COUNTED_FLOOR = 45
_SYMBOLS = ("W", "U", "B", "R", "G", "C")


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


def _w2g5_table(pool, *, mine=(), theirs=(), hand=()) -> Game:
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState("AI", library=[forest] * 30, hand=[pool[name] for name in hand]),
        PlayerState("Other", library=[forest] * 30),
    ])
    game.enforce_mana_costs = True
    game.active_player_index = 0
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            _w2g5_enter(game, pool[name], seat)
    return game


def _w2g5_enter(game, card, seat=0, *, sick=False) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game.auto_resolve_pending_choices()
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = False
    return permanent


def _w2g5_cost(**symbols) -> dict:
    return {**{symbol: 0 for symbol in _SYMBOLS}, "generic": 0, **symbols}


def _w2g5_pay(game, plan) -> None:
    tap_planned_lands(game, 0, CastAction(
        card_name="-", target_player_index=0, x_value=None,
        land_tap_indices=plan[0], score=0.0, hand_index=0, land_tap_colors=plan[1],
    ))


def _w2g5_floating(game) -> dict:
    return {symbol: n for symbol, n in game.players[0].mana_pool.items() if n}


def test_w2g5_every_nonland_source_the_plan_counts_makes_what_it_counted(pool):
    """The census. Every supported non-land permanent with a mana ability,
    alone beside tapped lands (so a "could produce" clause has a board to
    read): where the plan counts it, executing a plan for exactly what the
    source is said to make must leave that mana in the pool and the source
    tapped. Where it does not count a bare "{T}: Add …", the reason has to be
    the payload — restricted mana, an amount the board decides."""
    counted, uncounted_tap_alone, costed = [], [], []
    for name, card in sorted(pool.items()):
        if card.primary_type in ("instant", "sorcery", "land"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        abilities = [
            ability for ability in usable_activated_abilities(program)
            if ability.instruction is not None and is_mana_ability(ability)
        ]
        if not abilities:
            continue
        game = _w2g5_table(pool)
        for seat in (0, 1):
            for land in ("Forest", "Island"):
                _w2g5_enter(game, pool[land], seat).tapped = True
        source = _w2g5_enter(game, card)
        if not game.is_on_battlefield(source):
            continue  # an entry replacement put it elsewhere (Mox Diamond)
        planned = _nonland_mana_source(game, 0, source)
        tap_alone = [a for a in abilities if is_tap_alone_mana_ability(a)]
        if planned is None:
            if tap_alone:
                assert all(
                    planned_mana_yield(a.instruction) is None for a in tap_alone
                ), name
                uncounted_tap_alone.append(name)
            else:
                costed.append(name)
            continue
        assert is_tap_alone_mana_ability(
            usable_activated_abilities(program)[planned.ability_index]
        ), name
        required = (
            _w2g5_cost(**planned.run) if planned.run
            else _w2g5_cost(**{planned.symbols[0]: planned.amount})
        )
        plan = _plan_land_taps(game, game.players[0], required)
        assert plan is not None, (name, required, planned)
        _w2g5_pay(game, plan)
        assert source.tapped, name
        assert _can_pay_cost(
            dict(game.players[0].mana_pool), required, game.players[0]
        ), (name, required, _w2g5_floating(game))
        counted.append(name)

    assert len(counted) >= _COUNTED_FLOOR, counted
    assert {
        "Sol Ring", "Mox Sapphire", "Llanowar Elves", "Birds of Paradise",
        "Fellwar Stone", "Mana Vault", "Bloodstone Cameo", "Sol Grail",
        "Star Compass", "Quirion Explorer",
    } <= set(counted)
    # Bare "{T}: Add …" the plan leaves out, each for what its payload carries.
    assert {
        "Adarkar Unicorn", "Soldevi Machinist", "Vodalian Arcanist",  # CR 106.6
        "Priest of Titania", "Rofellos, Llanowar Emissary", "Metalworker",
    } <= set(uncounted_tap_alone)
    # …and a mana ability that costs more than the tap is not free mana.
    assert {"Black Lotus", "Lotus Petal", "Mana Cylix", "Morgue Toad",
            "Tinder Wall", "Celestial Prism"} <= set(costed)


@pytest.mark.parametrize("text,expected", [
    ("{T}: Add {C}{C}.", ManaYield(symbols=("C",), amount=2)),
    ("{T}: Add {B} or {R}.", ManaYield(symbols=("B", "R"), amount=1)),
    ("{T}: Add one mana of any color.",
     ManaYield(symbols=("W", "U", "B", "R", "G"), amount=1)),
    ("{T}: Add {B}. This creature deals 1 damage to you.",
     ManaYield(symbols=("B",), amount=1)),
    ("{T}: Add one mana of any color that a land an opponent controls could produce.",
     ManaYield(amount=1, board_narrowed=True)),
    ("{T}: Add {C}. Spend this mana only to cast an instant or sorcery spell.", None),
    ("{T}: Add {G} for each Elf on the battlefield.", None),
])
def test_w2g5_a_mana_abilitys_yield_is_read_off_its_payload(text, expected):
    """Invented permanents, so the reading is a claim about the printed
    template and not about which cards print it."""
    card = _mk_card(
        name="Invented Source", mana_cost="{2}", type_line="Artifact Creature — Golem",
        oracle_text=text,
    )
    ability = compile_card_oracle(card).activated_abilities[0]
    assert planned_mana_yield(ability.instruction) == expected


def test_w2g5_the_ai_pays_for_a_spell_with_sol_ring(pool):
    """Two Forests and a Sol Ring cast a four-mana creature: the plan names the
    Ring, the executor activates it, and the cast is paid for."""
    game = _w2g5_table(pool, mine=("Forest", "Forest", "Sol Ring"), hand=("Giant Spider",))
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Giant Spider"
    ring = next(p for p in game.controlled_by(0) if p.card.name == "Sol Ring")
    assert [p is ring for p in game.controlled_by(0)].index(True) in action.land_tap_indices
    tap_planned_lands(game, 0, action)
    assert ring.tapped
    result = game.cast_from_hand(0, "Giant Spider")
    assert result.supported, result
    resolve_stack(game)
    assert "Giant Spider" in [p.card.name for p in game.controlled_by(0)]
    assert _w2g5_floating(game) == {}


def test_w2g5_lands_are_tapped_before_any_other_source(pool):
    """A board whose lands pay is planned exactly as it always was: the Ring
    stays untapped and so does the creature that could have attacked."""
    game = _w2g5_table(
        pool, mine=("Sol Ring", "Llanowar Elves", "Forest", "Forest", "Forest", "Forest"),
        hand=("Giant Spider",),
    )
    action = choose_cast_action(game, 0)
    board = list(game.controlled_by(0))
    assert sorted(board[slot].card.name for slot in action.land_tap_indices) == ["Forest"] * 4


def test_w2g5_a_mana_creature_pays_only_once_it_could_tap(pool):
    """CR 302.6: a creature's {T} ability waits out summoning sickness, and a
    {T} mana ability is a {T} ability. An artifact's does not."""
    game = _w2g5_table(pool, mine=("Forest",), hand=("Grizzly Bears",))
    elves = _w2g5_enter(game, pool["Llanowar Elves"], sick=True)
    assert _nonland_mana_source(game, 0, elves) is None
    assert _plan_land_taps(game, game.players[0], _w2g5_cost(G=1, generic=1)) is None
    elves.metadata["summoning_sickness_turn"] = -99
    plan = _plan_land_taps(game, game.players[0], _w2g5_cost(G=1, generic=1))
    assert plan is not None and len(plan[0]) == 2
    mox = _w2g5_enter(game, pool["Mox Emerald"], sick=True)
    assert _nonland_mana_source(game, 0, mox) is not None


def test_w2g5_a_source_under_an_activation_ban_is_not_counted(pool):
    """The plan asks what the activation path will ask: under "Activated
    abilities of artifacts can't be activated" (Null Rod) a Sol Ring is no
    mana, and a plan that counted it would be a cast refused every turn."""
    game = _w2g5_table(pool, mine=("Forest", "Sol Ring"))
    ring = next(p for p in game.controlled_by(0) if p.card.name == "Sol Ring")
    assert _nonland_mana_source(game, 0, ring) is not None
    _w2g5_enter(game, pool["Null Rod"], seat=1)
    assert _nonland_mana_source(game, 0, ring) is None
    assert _plan_land_taps(game, game.players[0], _w2g5_cost(generic=3)) is None
    result = game.activate_permanent_ability(0, "Sol Ring", permanent_index=1)
    assert not result.supported


def test_w2g5_a_sacrifice_or_a_priced_mana_ability_is_never_planned(pool):
    """Black Lotus, a creature that sacrifices itself for mana and a filter
    that spends one to make one: none is counted, so no plan sacrifices a
    permanent to cast a one-drop."""
    game = _w2g5_table(
        pool, mine=("Black Lotus", "Morgue Toad", "Mana Cylix", "Tinder Wall"),
        hand=("Llanowar Elves",),
    )
    for permanent in game.controlled_by(0):
        assert _nonland_mana_source(game, 0, permanent) is None, permanent.card.name
    assert choose_cast_action(game, 0) is None
    assert len(list(game.controlled_by(0))) == 4


def test_w2g5_a_permanent_never_pays_for_its_own_ability_with_its_own_tap(pool):
    """An invented artifact with a {T} ability *and* a {T} mana ability: the
    plan for the first must not count the second, which would spend the one
    tap twice. With a land it is activated off the land; alone it is not
    proposed at all."""
    gadget = _mk_card(
        name="Twin Spigot", mana_cost="{2}", type_line="Artifact",
        oracle_text="{1}, {T}: You gain 2 life.\n{T}: Add {C}.",
    )
    assert compile_card_oracle(gadget).supported
    game = _w2g5_table(pool)
    _w2g5_enter(game, gadget)
    assert choose_activation_action(game, 0) is None
    _w2g5_enter(game, pool["Forest"])
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Twin Spigot"
    board = list(game.controlled_by(0))
    assert [board[slot].card.name for slot in action.land_tap_indices] == ["Forest"]


def test_w2g5_reflecting_pool_is_planned_for_what_its_board_defines(pool):
    """`_BOARD_DEPENDENT_MANA_KEYS` listed "any type that a land you control
    could produce" beside the lands whose *amount* the board decides, so a
    Reflecting Pool stayed out of every plan although its amount is one and
    its types are `Game.narrowed_land_mana_colors`' exact answer."""
    game = _w2g5_table(pool, mine=("Reflecting Pool", "Swamp"), hand=("Black Knight",))
    plan = _plan_land_taps(game, game.players[0], _w2g5_cost(B=2))
    assert plan is not None and plan[1] == ("B", "B")
    _w2g5_pay(game, plan)
    assert _w2g5_floating(game) == {"B": 2}

    # …and only for that: beside a Forest it is no black mana, and alone it is
    # no mana at all (CR 106.7).
    forest = _w2g5_table(pool, mine=("Reflecting Pool", "Forest"))
    assert _plan_land_taps(forest, forest.players[0], _w2g5_cost(B=1)) is None
    alone = _w2g5_table(pool, mine=("Reflecting Pool",))
    assert _plan_land_taps(alone, alone.players[0], _w2g5_cost(generic=1)) is None

    # A board that offers only colourless: the plan asks for {C} and gets it.
    factory = _w2g5_table(pool, mine=("Reflecting Pool", "Mishra's Factory"))
    plan = _plan_land_taps(factory, factory.players[0], _w2g5_cost(generic=2))
    assert plan is not None
    _w2g5_pay(factory, plan)
    assert _w2g5_floating(factory) == {"C": 2}
