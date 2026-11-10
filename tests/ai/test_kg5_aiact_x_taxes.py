"""An announced X is sized at the price the activation will charge (kg5 aiact).

``ai_activation_rehearsal._sized_x_activation`` planned each X off the printed
symbols alone — X generic (or the colour "Spend only red mana on X" names) on
top of the cost's own pips — and never asked the charger the activation path
pays through (``Game.activation_mana_charge``: CR 601.2f via 602.2b, the
increases then the reductions). So under Gloom's "Activated abilities of white
enchantments cost {3} more" a Testament of Faith planned X lands for a charge
of X+3 and the engine refused it with the lands tapped, and under
Heartstone's "{1} less" a Silklash Spider on four Forests sized X no higher
than 2, where the same four Forests pay X=3.

Validated backwards: with the printed-symbol plan restored, the census below
finds Testament of Faith's sized X unpayable under Gloom (X=8 planned on the
thirty lands for a charge of {11}), the Gloom board sizes X=5 on five Plains,
and the Spider on four Forests is proposed at X=1 against a 3/3 flier (X=3
was five lands by its own plan).
"""

from __future__ import annotations

from engine import ai_activation_rehearsal
from engine.ai_abilities import choose_activation_action
from engine.ai_actions import ActivationAction, activation_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_simulator import SimulationReport, _play_activations
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.targeting import usable_activated_abilities
from engine.oracle import compile_card_oracle
from tests.helpers import stock_libraries


def _board(mine=(), theirs=()):
    """The AI's precombat main phase, costs enforced, nothing summoning sick."""
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    stock_libraries(game)
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn = 5
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    for seat, group in ((0, mine), (1, theirs)):
        for card in group:
            game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    return game


def _named(game, name):
    return next(p for p in game.all_permanents() if p.card.name == name)


def _planned_lands_pay(game, seat, action, source, ability) -> bool:
    """Whether the lands *action* plans to tap make at least the mana the
    activation will charge at its X, colour by colour (generic from anything)."""
    charge = game.activation_mana_charge(seat, source, ability, x_value=action.x_value)
    assert not isinstance(charge, str), charge
    required = dict(charge[0])
    made: dict[str, int] = {}
    for color in action.land_tap_colors:
        made[color] = made.get(color, 0) + 1
    for symbol, amount in required.items():
        if symbol == "generic" or not amount:
            continue
        if made.get(symbol, 0) < amount:
            return False
        made[symbol] -= amount
    return sum(made.values()) >= int(required.get("generic", 0) or 0)


def test_heartstone_s_reduction_buys_the_spider_the_x_that_kills_the_flier(set_pool):
    """Silklash Spider, Heartstone and four Forests against a 3/3 flier: the
    charge for X=3 is {2}{G}{G} under Heartstone, which the four Forests pay.
    Planned off the printed symbols X=3 was five lands, X=2 killed nothing,
    and the Spider was never activated. Driven through the simulator's own
    executor, which pays from the lands it plans."""
    lea = set_pool("LEA")
    game = _board(
        mine=[set_pool("ONS")["Silklash Spider"], set_pool("STH")["Heartstone"],
              *[lea["Forest"]] * 4],
        theirs=[lea["Phantom Monster"]],
    )
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Silklash Spider"
    assert action.x_value == 3 and len(action.land_tap_indices) == 4
    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    _play_activations(game, 0, report, 1, 1)
    assert not report.refused_activations, report.refused_activations
    assert [card.name for card in game.players[1].graveyard] == ["Phantom Monster"]


def test_gloom_s_tax_is_planned_into_the_x(set_pool, monkeypatch):
    """Testament of Faith under an opponent's Gloom on five Plains: every X
    costs three more, so the largest X the Plains pay is 2. The sizing is
    asked with every X worth its size (the worth read is the rehearsal's,
    which this board's empty combat would price at nothing): planned off the
    printed {X} alone it sized X=5 on five Plains and the engine refused the
    activation — a charge of {8}."""
    lea = set_pool("LEA")
    game = _board(
        mine=[set_pool("ODY")["Testament of Faith"], *[lea["Plains"]] * 5],
        theirs=[lea["Gloom"]],
    )
    testament = _named(game, "Testament of Faith")
    ability = game.usable_abilities_of(testament)[0]
    monkeypatch.setattr(
        ai_activation_rehearsal, "_land_ability_worth",
        lambda _game, _seat, sized: float(sized.x_value),
    )
    candidate = ActivationAction(
        permanent_name=testament.card.name,
        permanent_index=game.battlefield_index_of(testament),
        target_player_index=0, land_tap_indices=(), score=1.0,
    )
    sized = ai_activation_rehearsal._sized_x_activation(game, 0, testament, ability, candidate)
    assert sized is not None and sized.x_value == 2
    assert _planned_lands_pay(game, 0, sized, testament, ability)
    planned = tap_planned_lands(game, 0, sized)
    result = game.activate_permanent_ability(
        0, planned.permanent_name, **activation_announcement(planned),
    )
    assert result.supported, result.details
    assert testament.is_creature and testament.effective_power == 2


def _x_abilities(cards):
    """``(card, ability_index)`` for each announced-X ability of a supported
    card (an X the card defines is not announced, and an X that sizes the
    target list is declined before the sizing)."""
    from engine.cost_x_definitions import cost_x_is_defined
    from engine.targeting import derive_activation_spec

    for card in cards:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            line = ability.source_line or ""
            if not line.lower().split(":", 1)[0].count("{x}") or cost_x_is_defined(line):
                continue
            if (derive_activation_spec(ability) or {}).get("x_targets"):
                continue
            yield card, index


def test_every_sized_x_under_a_cost_modifier_is_payable_as_planned(set_pool, monkeypatch):
    """Census over both manifest roles: each announced-X ability on a creature
    under Heartstone, and on a white enchantment under Gloom, sized with every
    X worth its size on six lands of each basic type. The lands the sizing
    plans must pay the charge the activation path will make at that X.
    Asserts a floor on what it examined, a reduction and a tax both."""
    from engine.card_loader import load_cards, manifest_set_paths
    from engine.faces import compilation_units

    lea = set_pool("LEA")
    basics = [lea[name] for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")]
    heartstone, gloom = set_pool("STH")["Heartstone"], lea["Gloom"]
    cards = compilation_units(load_cards(manifest_set_paths(include_measured=True)))
    monkeypatch.setattr(
        ai_activation_rehearsal, "_land_ability_worth",
        lambda _game, _seat, sized: float(sized.x_value),
    )
    examined = {"Heartstone": 0, "Gloom": 0}
    wrong = []
    for card, index in _x_abilities(cards):
        types = card.type_line.lower()
        if "creature" in types:
            modifier = heartstone
        elif "enchantment" in types and "W" in (card.mana_cost or ""):
            modifier = gloom
        else:
            continue
        game = _board(mine=[card, *basics * 6], theirs=[modifier])
        source = _named(game, card.name)
        abilities = game.usable_abilities_of(source)
        if index >= len(abilities):
            continue
        ability = abilities[index]
        candidate = ActivationAction(
            permanent_name=card.name, permanent_index=game.battlefield_index_of(source),
            target_player_index=1, land_tap_indices=(), score=1.0,
            ability_index=index or None,
        )
        sized = ai_activation_rehearsal._sized_x_activation(game, 0, source, ability, candidate)
        if sized is None:
            continue
        examined[modifier.name] += 1
        if not _planned_lands_pay(game, 0, sized, source, ability):
            wrong.append((card.name, modifier.name, sized.x_value, sized.land_tap_colors))
    assert not wrong, wrong
    assert examined["Heartstone"] >= 8, examined
    assert examined["Gloom"] >= 1, examined
