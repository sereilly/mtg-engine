"""A "next time that source would deal damage" rider names **the card that
armed it** in CR 616.1e's ``effect_order`` option, not the source it sits on.

CR 616.1: "the affected object's controller (or its owner if it doesn't have a
controller) or the affected player chooses one to apply" — a choice among
*effects*, and the option names what generates each one
(``effect_ordering.option_text``). Desperate Gambit's two riders are a count on
the chosen source (``engine/next_damage.py``), which recorded no arming card,
so the option named the object the count sat on: "The chosen source deals
double that damage instead, this once (Warmonger)" beside "(Furnace of Rath)".
The count now has a name record beside it (``next_damage.names_key``), written
by the one arming handler and read by both interceptors' ``sources``.

The census is every card in both manifest roles whose program arms a rider
(the two instruction kinds the arming handler serves), each driven against a
second effect at an interactive seat. Validated backwards: on the base
(``59f133e6``) every board here fails, the option naming the marked source.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from tests.helpers import declare_attack, drive_combat, settle

#: The instruction kinds whose handler arms a ``next_damage`` rider.
_ARMING = {"double_next_damage_from_chosen_source", "prevent_next_damage_from_chosen_source"}
#: Each card that arms one, and the board here that drives it.
_DRIVEN = {
    "Desperate Gambit": "test_desperate_gambit_s_rider_names_desperate_gambit",
    "Impulsive Maneuvers": "test_impulsive_maneuvers_rider_names_impulsive_maneuvers",
}


def _walk(value):
    if isinstance(value, OracleInstruction):
        yield value
        yield from _walk(dict(value.payload or {}))
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for item in dataclasses.fields(value):
            yield from _walk(getattr(value, item.name))


@pytest.mark.cr("616.1e")
def test_every_card_arming_a_next_damage_rider_is_driven():
    """By shape, over both roles: the cards whose compiled program carries an
    arming kind are exactly the ones driven below, and the arming handler is
    the only engine code that writes a rider (it is what passes the name)."""
    found = set()
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        if any(ins.kind in _ARMING for ins in _walk(compile_card_oracle(card))):
            found.add(card.name)
    assert len(found) >= 2, found
    assert found == set(_DRIVEN), found
    writers = sorted(
        path.relative_to(Path("engine")).as_posix()
        for path in Path("engine").rglob("*.py")
        if re.search(r"next_damage import \([^)]*\barm\b|next_damage import [^(\n]*\barm\b",
                     path.read_text(encoding="utf-8"))
    )
    assert writers == ["handlers/prevention.py"], writers


def _game(catalog_by_name, *, hand0=(), interactive=(1,)):
    game = Game(players=[
        PlayerState(name="Alice", library=[catalog_by_name["Island"]] * 20,
                    hand=[catalog_by_name[name] for name in hand0]),
        PlayerState(name="Bob", library=[catalog_by_name["Island"]] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    return game


def _put(game, catalog_by_name, seat, name):
    permanent = Permanent(card=catalog_by_name[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _rig_coin(monkeypatch, won: bool) -> None:
    from engine.handlers import control_flow

    monkeypatch.setattr(control_flow, "flip_coin", lambda win_probability=0.5: won)


def _asked(game) -> list[str]:
    """The options of the ``effect_order`` prompt owed now, answered with its
    first option so play goes on."""
    choice = game.pending_choice_of("effect_order")
    assert choice is not None, game.log[-6:]
    options = [str(option) for option in choice.data["options"]]
    assert game.resolve_pending_choice("effect_order", choice.player_index, option_index=0)
    return options


@pytest.mark.cr("616.1e", "615.8")
@pytest.mark.parametrize("won", [True, False], ids=["won", "lost"])
def test_desperate_gambit_s_rider_names_desperate_gambit(catalog_by_name, monkeypatch, won):
    """Alice's Gambit on her Warmonger; Bob (asked) holds Furnace of Rath (won:
    two multipliers) or a Pentagram of the Ages shield against the Warmonger
    (lost: two preventions). His option for the rider names Desperate Gambit,
    and no option names the Warmonger."""
    _rig_coin(monkeypatch, won)
    game = _game(catalog_by_name, hand0=["Desperate Gambit"])
    monger = _put(game, catalog_by_name, 0, "Warmonger")
    if won:
        _put(game, catalog_by_name, 1, "Furnace of Rath")
    else:
        _put(game, catalog_by_name, 1, "Pentagram of the Ages")
        armed = game.activate_permanent_ability(
            1, "Pentagram of the Ages", target_permanent_ids=[monger.permanent_id],
        )
        assert armed.supported, armed.details
        settle(game)
    assert game.cast_from_hand(0, "Desperate Gambit").supported
    settle(game)
    assert "Desperate Gambit: chose Warmonger" in game.log, game.log

    assert game.queue_permanent_ability(0, "Warmonger").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    options = _asked(game)
    rider = [option for option in options if "chosen source" in option and "Gambit" in option]
    assert rider == [
        "The chosen source deals double that damage instead, this once (Desperate Gambit)"
        if won else "Prevent the next damage the chosen source would deal (Desperate Gambit)"
    ], options
    assert not any("(Warmonger)" in option for option in options), options
    settle(game)
    # The rider's count and its name record go together: spent, both are gone.
    assert not any(key.startswith("next_damage_it_deals") for key in monger.metadata), monger.metadata


@pytest.mark.cr("616.1e", "510.2")
def test_impulsive_maneuvers_rider_names_impulsive_maneuvers(catalog_by_name, monkeypatch):
    """Alice's Grizzly Bears attack under her Impulsive Maneuvers and the flip
    is won; Bob (asked) holds Furnace of Rath. On the Bears' combat damage to
    him both multipliers apply, and the rider's option names Impulsive
    Maneuvers, not the Bears."""
    _rig_coin(monkeypatch, True)
    game = _game(catalog_by_name)
    _put(game, catalog_by_name, 0, "Impulsive Maneuvers")
    _put(game, catalog_by_name, 0, "Grizzly Bears")
    _put(game, catalog_by_name, 1, "Furnace of Rath")
    declare_attack(game, 0)
    seen: list[list[str]] = []

    def answer(game, choice):
        seen.append([str(option) for option in choice.data["options"]])
        assert game.resolve_pending_choice("effect_order", choice.player_index, option_index=0)

    drive_combat(game, through="combat_damage", answers={"effect_order": answer})
    assert seen, game.log[-8:]
    assert any(
        "The chosen source deals double that damage instead, this once (Impulsive Maneuvers)"
        in options for options in seen
    ), seen
    assert not any("(Grizzly Bears)" in option for options in seen for option in options), seen
    assert game.players[1].life == 20 - 8, game.log
