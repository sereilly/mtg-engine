"""A choice and a P/T trade are read through their modes and by the moment
(kg4 aivalue).

Two side readers in ``ai_target_sides`` read an ability step by step with the
wrappers opened (``_effect_steps``), and a ``choose_one`` is not a wrapper
there: read as one step it names nothing and has no side.

* **A targeted choice** (``ability_target_side``): "{T}: Target creature loses
  flying, first strike, or trample until end of turn" (Walking Sponge) fell
  back to the biggest creature on either board and was aimed at its
  controller's own Serra Angel.
* **A host effect** (``host_effect_side``): Pemmin's Aura's "{1}: Enchanted
  creature gets +1/-1 or -1/+1 until end of turn" and Flowstone Blade's "{R}:
  Enchanted creature gets +1/-1 until end of turn" are a pump on a big body
  and removal on an X/1. Flowstone Blade's trade read as a gift by its
  category, so the host gate refused it on an opponent's Llanowar Elves —
  never weighed as removal — and the flat score activated it on its
  controller's own Elves, which it killed. Such an ability is now rehearsed
  (``host_effect_by_the_moment``).

Validated backwards: with ``host_effect_by_the_moment`` answering False and
the modes left shut (the base), the census finds Flowstone Blade activated on
its controller's own X/1 and refused on the opponent's, and Walking Sponge
aimed at its controller's own creature.
"""

from __future__ import annotations

from unittest import mock

import pytest

from engine import ai_abilities, ai_target_sides
from engine.ai_abilities import _activation_candidate, choose_activation_action
from engine.ai_target_sides import host_effect_by_the_moment
from engine.ai_weighed_cast import _effect_steps
from engine.aura_attachment import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _nosick, resolve_stack


@pytest.fixture(scope="module")
def pool() -> dict:
    cards = load_cards(manifest_set_paths(include_measured=True))
    return {card.name: card for card in compilation_units(cards)}


def _host_board(pool, aura, host_seat: int, host: str) -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.players[0].battlefield = [_nosick(Permanent(card=aura))]
    game.players[host_seat].battlefield.append(_nosick(Permanent(card=pool[host])))
    for player in game.players:
        player.library = [pool["Island"]] * 10
    attach_aura(game.players[0].battlefield[0], game.players[host_seat].battlefield[-1])
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    game.start_priority_window(0)
    return game


def _by_the_moment(pool) -> list:
    """``(card, ability index)`` for every usable activated ability of a
    supported card (both manifest roles) whose every step lands on its
    source's host and whose worth there is the host's body: some step, or
    some mode of a choice, a P/T trade (a person's reading: one half up and
    the other down by printed numbers)."""
    rows = []
    for name, card in sorted(pool.items()):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            if ability.instruction is None or ability.cost.sacrifice_filter is not None:
                continue
            trades = []
            for step in _effect_steps(ability.instruction):
                modes = [
                    mode["instruction"] for mode in (step.payload or {}).get("modes") or ()
                ] if step.kind == "choose_one" else [step]
                for leaf in modes:
                    payload = leaf.payload or {}
                    power, toughness = payload.get("power"), payload.get("toughness")
                    trades.append(
                        "enchanted" in leaf.kind
                        and isinstance(power, int) and isinstance(toughness, int)
                        and power * toughness < 0
                    )
            if trades and all(trades):
                rows.append((card, index))
    return rows


def _proposed(pool, card, index, host_seat, host) -> bool:
    game = _host_board(pool, card, host_seat, host)
    aura = game.players[0].battlefield[0]
    usable = game.usable_abilities_of(aura)
    return _activation_candidate(
        game, 0, 0, aura, usable[index], None if index == 0 else index,
    ) is not None


def _census(pool) -> dict:
    found = {"examined": [], "kills_own": [], "spares_their_x1": [], "removal": []}
    for card, index in _by_the_moment(pool):
        found["examined"].append((card.name, index))
        if _proposed(pool, card, index, 0, "Llanowar Elves"):
            found["kills_own"].append(card.name)
        if _proposed(pool, card, index, 1, "Llanowar Elves"):
            found["removal"].append(card.name)
        else:
            found["spares_their_x1"].append(card.name)
    return found


def test_a_host_trade_is_removal_on_their_x1_and_never_kills_its_own(pool):
    found = _census(pool)
    assert found["kills_own"] == [], found
    assert found["spares_their_x1"] == [], found
    assert {"Pemmin's Aura", "Flowstone Blade"} <= {name for name, _i in found["examined"]}
    assert all(host_effect_by_the_moment(
        usable_activated_abilities(compile_card_oracle(pool[name]))[index].instruction
    ) for name, index in found["examined"])


def test_without_the_reading_the_census_finds_the_base(pool):
    """Backwards: the host trade read by its category, as on 313bd09d."""
    with mock.patch.object(ai_target_sides, "host_effect_by_the_moment", lambda i: False), \
            mock.patch.object(ai_abilities, "host_effect_by_the_moment", lambda i: False), \
            mock.patch.object(ai_target_sides, "_side_steps", _effect_steps):
        found = _census(pool)
    assert "Flowstone Blade" in found["kills_own"], found
    assert "Flowstone Blade" in found["spares_their_x1"], found


def test_flowstone_blade_kills_an_opponents_llanowar_elves(pool):
    """The board driven: the main-phase chooser proposes it, the activation
    resolves through the engine, and the opponent's Elves is in the
    graveyard; on the seat's own Elves nothing is proposed."""
    game = _host_board(pool, pool["Flowstone Blade"], 1, "Llanowar Elves")
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Flowstone Blade"
    result = game.queue_permanent_ability(0, "Flowstone Blade", permanent_index=0)
    assert result.supported, result.details
    resolve_stack(game)
    game.check_state_based_actions()
    assert [card.name for card in game.players[1].graveyard] == ["Llanowar Elves"], game.log[-6:]

    game = _host_board(pool, pool["Flowstone Blade"], 0, "Llanowar Elves")
    action = choose_activation_action(game, 0)
    assert action is None or action.permanent_name != "Flowstone Blade"


def test_a_host_trade_on_a_big_opposing_body_is_not_a_gift(pool):
    """+1/-1 on the opponent's Hill Giant kills nothing and lends it a point
    of power: not proposed, where the base refused it by its side."""
    for card, index in _by_the_moment(pool):
        assert not _proposed(pool, card, index, 1, "Hill Giant"), card.name


# --- a targeted choice ----------------------------------------------------------


def _choice_board(pool, source) -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    angel = pool["Serra Angel"]
    game.players[0].battlefield = [_nosick(Permanent(card=pool[source])), _nosick(Permanent(card=angel))]
    game.players[1].battlefield = [_nosick(Permanent(card=angel))]
    for player in game.players:
        player.library = [pool["Island"]] * 10
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game.start_priority_window(0)
    return game


def test_a_choice_of_hampers_is_aimed_at_the_opponent(pool):
    """Walking Sponge's "loses flying, first strike, or trample": every mode
    a loss, so the target is the opponent's flier."""
    game = _choice_board(pool, "Walking Sponge")
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Walking Sponge"
    assert action.target_player_index == 1


def test_with_the_modes_shut_walking_sponge_aims_at_its_own_angel(pool):
    """Backwards: the choice read as one step, as on 313bd09d."""
    with mock.patch.object(ai_target_sides, "_side_steps", _effect_steps):
        game = _choice_board(pool, "Walking Sponge")
        action = choose_activation_action(game, 0)
    assert action is not None and action.target_player_index == 0


def test_every_targeted_choice_reads_the_side_its_modes_agree_on(pool):
    """Every usable activated ability of a supported card (both roles) whose
    effect is one choice among targeted modes that all read one side: the
    ability reads that side."""
    examined = []
    for name, card in sorted(pool.items()):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for ability in usable_activated_abilities(program):
            if ability.instruction is None:
                continue
            steps = _effect_steps(ability.instruction)
            if len(steps) != 1 or steps[0].kind != "choose_one":
                continue
            modes = [mode["instruction"] for mode in steps[0].payload.get("modes") or ()]
            if not modes or not all(
                isinstance((mode.payload or {}).get("targets"), dict) for mode in modes
            ):
                continue
            sides = {ai_target_sides.instruction_target_side(mode) for mode in modes}
            if len(sides) != 1 or None in sides:
                continue
            examined.append(name)
            assert ai_target_sides.ability_target_side(ability.instruction) in sides, name
    assert {"Walking Sponge"} <= set(examined), examined
    assert len(examined) >= 3, examined
