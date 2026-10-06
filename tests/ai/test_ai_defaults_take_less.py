"""Defaults that took everything, and one that took nothing.

Four places a seat nobody asks — an AI seat, a headless game — answered a
quantity with the largest number the rules allow, or with none at all:

* **An X paid in life was the whole life total.** "As an additional cost to
  cast this spell, pay X life" (Fire Covenant, Hatred): the announcement was
  sized by the cast's own ceiling, which CR 119.4 puts at the seat's life, so
  the AI paid twenty life at twenty and lost the game to the state-based check
  behind its own spell.
* **"Any number" was every card.** Skyship Weatherlight's entry search exiled
  every artifact and creature in the seat's library; the pile comes back one
  card at random per {4}, {T} (PLS W1G8).
* **A divided prevention spell had nothing to divide.** Remedy and Pollen
  Remedy describe a division "as you choose" and their spec did not carry the
  amount, so the AI's reader saw a total of zero — no lawful announcement — and
  never cast either (PLS W1G1). The browser's reader fell back to asking for an
  X the cards do not print.
* **A choice a later sentence tests was the first in board order.** Guard
  Dogs' "choose a permanent you control" took a land, which shares a colour
  with nothing (PLS W1G6).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import (SLOW_RETURN_PILE_SIZE, X_LIFE_RESERVE,
                              _cast_candidate, tap_planned_lands)
from engine.ai_valuation import (_walk_program, exiled_search_pile_comes_back,
                                 exiled_search_pile_comes_back_one_at_a_time)
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_costs import additional_costs
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec
from tests.helpers import resolve_stack


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


def _w2g5_table(pool, hand, *, library=None, enforce=True) -> Game:
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState("AI", library=list(library or [forest] * 30), hand=list(hand)),
        PlayerState("Other", library=[forest] * 30),
    ])
    game.enforce_mana_costs = enforce
    game.active_player_index = 0
    return game


def _w2g5_put(game, pool, seat, name) -> Permanent:
    permanent = Permanent(card=pool[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w2g5_furnish(game, pool) -> None:
    for seat in (0, 1):
        for name in ("Grizzly Bears", "Hill Giant", "Serra Angel"):
            _w2g5_put(game, pool, seat, name)
        for name in ("Forest", "Mountain", "Island", "Swamp", "Plains"):
            for _ in range(3):
                _w2g5_put(game, pool, seat, name)


# --- An X paid in life ------------------------------------------------------


def _w2g5_life_x_spells(pool) -> list:
    return [
        card for card in pool.values()
        if card.primary_type in ("instant", "sorcery")
        and compile_card_oracle(card).supported
        and any(cost.pay_life_x for cost in additional_costs(card))
    ]


def test_w2g5_an_x_paid_in_life_keeps_a_reserve(pool):
    """Every spell in the pool whose X is paid in life, on a board where it has
    something to do: the X the AI announces leaves it `X_LIFE_RESERVE`, and at
    the reserve it is not proposed at all."""
    spells = _w2g5_life_x_spells(pool)
    assert {"Fire Covenant", "Hatred"} <= {card.name for card in spells}
    proposed = 0
    for card in spells:
        game = _w2g5_table(pool, [card])
        _w2g5_furnish(game, pool)
        action = _cast_candidate(game, 0, card, 0)
        if action is None:
            continue  # a printed timing gate (Necrologia's "during your end step")
        proposed += 1
        assert 0 < action.x_value <= game.players[0].life - X_LIFE_RESERVE, card.name

        low = _w2g5_table(pool, [card])
        _w2g5_furnish(low, pool)
        low.players[0].life = X_LIFE_RESERVE
        assert _cast_candidate(low, 0, card, 0) is None, card.name
    assert proposed >= 2


def test_w2g5_hatred_does_not_pay_the_casters_whole_life(pool):
    """The defect, played out. At twenty life the AI announced X = 20, paid it,
    and was at zero when its own spell resolved."""
    game = _w2g5_table(pool, [pool["Hatred"]])
    _w2g5_furnish(game, pool)
    action = _cast_candidate(game, 0, pool["Hatred"], 0)
    tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(
        0, "Hatred", target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids, x_value=action.x_value,
    )
    assert result.supported, result
    resolve_stack(game)
    assert game.players[0].life == 20 - action.x_value >= X_LIFE_RESERVE
    assert not game.players[0].lost


# --- "Any number", into a pile that comes back a card at a time --------------


def test_w2g5_which_exile_searches_come_back_a_card_at_a_time(pool):
    """The derivation, over every card in the pool that searches and exiles:
    only a pile whose one reader is a priced activated ability returning a
    single card answers yes."""
    searchers = {
        card.name: card for card in pool.values()
        if compile_card_oracle(card).supported
        and any(step.kind == "search_and_exile_matching"
                for step in _walk_program(compile_card_oracle(card)))
    }
    assert len(searchers) >= 6, sorted(searchers)
    slow = {
        name for name, card in searchers.items()
        if exiled_search_pile_comes_back_one_at_a_time(card)
    }
    assert slow == {"Skyship Weatherlight"}
    # A slow pile is still one that comes back; one that never does is not slow.
    assert all(exiled_search_pile_comes_back(searchers[name]) for name in slow)
    assert not exiled_search_pile_comes_back_one_at_a_time(pool["Mana Severance"])
    assert not exiled_search_pile_comes_back_one_at_a_time(pool["Foresight"])


def test_w2g5_skyship_weatherlight_does_not_exile_the_whole_library(pool):
    """A headless seat's Weatherlight keeps the few cards it most wants and
    leaves the rest of its creatures and artifacts in the library — it used to
    take all nine."""
    library = (
        [pool["Forest"]] * 10 + [pool["Grizzly Bears"]] * 4 + [pool["Craw Wurm"]] * 2
        + [pool["Sol Ring"], pool["Serra Angel"], pool["Lightning Bolt"], pool["Hill Giant"]]
    )
    game = _w2g5_table(pool, [pool["Skyship Weatherlight"]], library=library, enforce=False)
    assert game.cast_from_hand(0, "Skyship Weatherlight").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    exiled = list(game.players[0].exile)
    assert 0 < len(exiled) <= SLOW_RETURN_PILE_SIZE
    assert all(
        "Creature" in card.type_line or "Artifact" in card.type_line for card in exiled
    )
    assert len(game.players[0].library) == len(library) - len(exiled)
    # The pile is still the Weatherlight's to read back.
    ship = next(p for p in game.controlled_by(0) if p.card.name == "Skyship Weatherlight")
    ship.metadata["summoning_sickness_turn"] = -99
    assert game.activate_permanent_ability(0, "Skyship Weatherlight").supported
    resolve_stack(game)
    assert len(game.players[0].hand) == 1 and len(game.players[0].exile) == len(exiled) - 1


# --- A division with nothing to divide --------------------------------------


def test_w2g5_every_divided_spell_says_how_much_it_divides(pool):
    """The spec of a "divided as you choose" spell carries the printed amount,
    or the amount is an X somebody announces or the card defines. A spec with
    neither is a division of nothing: the AI holds the card for ever and the
    browser asks for an X the card does not print."""
    examined = unsized = 0
    for card in pool.values():
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        spec = derive_cast_spec(card, program)
        if not isinstance(spec, dict) or spec.get("kind") != "divided":
            continue
        if spec.get("division") != "chosen":
            continue
        examined += 1
        prints_x = "x" in (card.oracle_text or "").lower().replace("exile", "")
        if not isinstance(spec.get("division_total"), int) and not prints_x:
            unsized += 1
            pytest.fail(f"{card.name}: a chosen division with no total and no X")
    assert examined >= 12 and unsized == 0
    assert derive_cast_spec(pool["Remedy"], compile_card_oracle(pool["Remedy"]))[
        "division_total"
    ] == 5


@pytest.mark.parametrize("name,total", [("Remedy", 5), ("Pollen Remedy", 3)])
def test_w2g5_the_ai_casts_a_divided_prevention_spell(pool, name, total):
    """Remedy and an unkicked Pollen Remedy, cast by the AI: the whole amount
    divided among its own face and creatures, never an opponent's, and the
    shields are there when it has resolved."""
    game = _w2g5_table(pool, [pool[name]])
    mine = [_w2g5_put(game, pool, 0, creature) for creature in ("Grizzly Bears", "Hill Giant")]
    for creature in ("Grizzly Bears", "Hill Giant"):
        _w2g5_put(game, pool, 1, creature)
    for _ in range(2):
        _w2g5_put(game, pool, 0, "Plains")
    action = _cast_candidate(game, 0, pool[name], 0)
    assert action is not None and action.divided_targets
    assert {seat for seat, *_rest in action.divided_targets} == {0}
    assert sum(share for *_target, share in action.divided_targets) == total
    tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(
        0, name, target_player_index=action.target_player_index,
        divided_targets=action.divided_targets,
        optional_cost_payments=action.optional_cost_payments,
    )
    assert result.supported, result
    resolve_stack(game)
    shielded = sum(
        f"{who} gains prevention shield" in line
        for line in game.log for who in ("AI", "Grizzly Bears", "Hill Giant")
    )
    assert shielded == len(action.divided_targets)
    assert all(game.is_on_battlefield(permanent) for permanent in mine)


# --- A pick a later sentence tests ------------------------------------------


def test_w2g5_guard_dogs_picks_a_permanent_that_shares_the_targets_color(pool):
    """"Choose a permanent you control. Prevent all combat damage target
    creature would deal this turn if it shares a color with that permanent."
    A headless seat's pick was its first permanent in board order — a Forest —
    and the ability prevented nothing. It takes the first that shares a colour
    with the target, here its own red Hill Giant, and the damage is prevented.
    """
    from engine.ai_valuation import pick_is_tested_for_a_shared_color

    printing = sorted(
        card.name for card in pool.values()
        if compile_card_oracle(card).supported
        and pick_is_tested_for_a_shared_color(card, "attach_host")
    )
    assert "Guard Dogs" in printing

    game = _w2g5_table(pool, [], enforce=False)
    for name in ("Forest", "Plains", "Grizzly Bears", "Hill Giant", "Guard Dogs"):
        _w2g5_put(game, pool, 0, name)
    attacker = _w2g5_put(game, pool, 1, "Hill Giant")
    result = game.activate_permanent_ability(
        0, "Guard Dogs", target_player_index=1,
        target_permanent_ids=[attacker.permanent_id],
    )
    assert result.supported, result
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert "Guard Dogs: chose Hill Giant" in game.log
    assert any("all combat damage Hill Giant would deal" in line for line in game.log)

    # With nothing that shares the colour the pick is board order's, as it was.
    plain = _w2g5_table(pool, [], enforce=False)
    for name in ("Forest", "Grizzly Bears", "Guard Dogs"):
        _w2g5_put(plain, pool, 0, name)
    attacker = _w2g5_put(plain, pool, 1, "Hill Giant")
    assert plain.activate_permanent_ability(
        0, "Guard Dogs", target_player_index=1,
        target_permanent_ids=[attacker.permanent_id],
    ).supported
    resolve_stack(plain)
    plain.auto_resolve_pending_choices()
    assert "Guard Dogs: chose Forest" in plain.log
