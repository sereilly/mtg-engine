"""A text change an AI seat **activates** names its two words (kg4 `aiact`,
part 1), and every executor of an `ActivationAction` makes its whole
announcement from one place.

**The defect.** "{T}: Change the text of target white enchantment you control
that doesn't have cumulative upkeep by replacing all instances of one color
word with another." (Balduvian Shaman.) The activation announces the two
words (CR 612, through CR 602.2b) on the activation path's ``old_color`` /
``mana_color`` — the keys the web sends a person's answer on — and
`ActivationAction` had no field for either, so the five executors forwarded
none: the engine took no words, the handler logged that it had no effect,
and the main-phase chooser, which never rehearsed it, proposed it every turn
the Shaman was untapped as an ability "worth" 2.5 that changed nothing.

**The fix.** `ai_actions.activation_announcement` is every keyword an
`ActivationAction` announces (the twin of `cast_announcement`), and every
executor makes its call with it; the chooser weighs the object and the words
together through the cast side's ranking
(`ai_text_changes.ranked_word_choices`), rehearses the best few with what the
words aim at added (`ai_abilities._text_change_activation`), and proposes a
change only above the floor a text change cast is held to.
"""
from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

import pytest

from engine import ai_simulator
from engine.ai_abilities import choose_activation_action
from engine.ai_actions import (ACTIVATION_FIELDS_NOT_ANNOUNCED, ActivationAction,
                               activation_announcement)
from engine.ai_text_changes import ability_text_change_mode
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from engine.text_changes import current_text_card
from tests.helpers import _nosick

_CARDS = {card.name: card for card in load_catalog()}

#: The census floor: the shipped abilities whose activation announces a text
#: change's words (Balduvian Shaman).
_TEXT_CHANGE_ABILITY_FLOOR = 1

#: The Circle a colour word is worth changing on, facing black creatures.
_OWN = ("Circle of Protection: Red", "Plains", "Plains")
_BLACK = ("Scathe Zombies", "Scathe Zombies", "Swamp")


def _text_changing_abilities() -> list[str]:
    """Every shipped card with an activated ability whose text change names
    its words as it is activated."""
    return sorted({
        unit.name for unit in compilation_units(load_catalog())
        if any(
            ability_text_change_mode(ability.instruction) is not None
            for ability in usable_activated_abilities(compile_card_oracle(unit))
        )
    })


def _table(own, other):
    """Two seats as `run_ai_simulation` builds them, mana enforced, in seat
    0's precombat main phase, every permanent able to tap."""
    players = [
        PlayerState(name=name, library=[_CARDS["Forest"]] * 8)
        for name in ("AI-A", "AI-B")
    ]
    game = ai_simulator._SimulatedGame(
        players=players, enforce_mana_costs=True,
        prompt_driver=ai_simulator._resolve_pending_choices,
    )
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    game.priority_driver = ai_simulator._priority_answerer(game, report, 1, [1])
    game.turn = 3
    game.active_player_index = 0
    for seat, board in enumerate((own, other)):
        for name in board:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game, report


def _on(game, seat, name):
    return next((p for p in game.controlled_by(seat) if p.card.name == name), None)


def test_the_census_finds_every_ability_whose_activation_announces_words():
    found = _text_changing_abilities()
    assert len(found) >= _TEXT_CHANGE_ABILITY_FLOOR, found
    assert "Balduvian Shaman" in found


@pytest.mark.parametrize("name", _text_changing_abilities())
def test_each_text_changing_ability_is_activated_naming_words_that_pay(name):
    """On a board where the word pays — the seat's own Circle of Protection:
    Red facing black creatures — the ability is proposed naming two words, the
    simulator's executor announces them, and the Circle names black."""
    game, report = _table((name, *_OWN), _BLACK)
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == name, action
    assert (action.old_color, action.new_color) == ("R", "B"), action
    ai_simulator._play_activations(game, 0, report, 1, 3)
    circle = _on(game, 0, "Circle of Protection: Red")
    text = current_text_card(circle).oracle_text.lower()
    assert "black source" in text and "red source" not in text, text
    assert any("changed red text to black" in line for line in game.log), game.log[-6:]
    assert report.refused_activations == {}, report.refused_activations


def test_a_word_already_aimed_is_not_rewritten():
    """The Circle names red and the opponent's creatures are red: no other
    word aims at more, so the Shaman is not tapped to rewrite it (and the
    Circle does not take on cumulative upkeep for nothing)."""
    game, _report = _table(
        ("Balduvian Shaman", *_OWN), ("Mons's Goblin Raiders", "Mountain"),
    )
    action = choose_activation_action(game, 0)
    assert action is None or action.permanent_name != "Balduvian Shaman", action


def test_every_field_an_activation_action_carries_reaches_the_activation():
    """`activation_announcement` is the one place an `ActivationAction`
    becomes an activation, so a field added to the action is forwarded by
    every executor or is named as not an announcement."""
    action = ActivationAction(
        permanent_name="Probe", permanent_index=2, target_player_index=1,
        land_tap_indices=(0,), score=1.0, target_permanent_ids=[3], target_graveyard_indices=[4],
        target_role_refs=[{"permanent_id": 9}], land_tap_colors=("W",),
        source_controller_index=1, ability_index=2, cost_hand_index=0,
        chosen_keyword="flying", x_value=4, old_color="R", new_color="B",
    )
    announced = activation_announcement(action)
    carried = {field.name for field in fields(ActivationAction)} - ACTIVATION_FIELDS_NOT_ANNOUNCED
    renamed = {"new_color": "mana_color"}
    assert set(announced) == {renamed.get(name, name) for name in carried}
    for name in carried:
        assert announced[renamed.get(name, name)] == getattr(action, name), name


def _executor_calls(tree):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
            and getattr(node.func, "attr", getattr(node.func, "id", None)) in (
                "activate_permanent_ability", "queue_permanent_ability", "activate",
            )
        ):
            yield node


def test_the_executors_all_make_the_whole_announcement():
    """The simulator's two sites (its main phase, its foreign activation),
    the web AI step's two and the rehearsal's queue (which the instant-speed
    executor shares) call the engine with ``**activation_announcement(...)``
    and spell out no keyword of their own — the web's foreign executor had
    dropped the role answer, the keyword and the X, and all five the words."""
    root = Path(__file__).resolve().parents[2]
    abilities = ast.parse((root / "engine/ai_activation_rehearsal.py").read_text(encoding="utf-8"))
    queue = next(
        node for node in ast.walk(abilities)
        if isinstance(node, ast.FunctionDef) and node.name == "_queue_activation"
    )
    trees = [
        (relative, ast.parse((root / relative).read_text(encoding="utf-8")))
        for relative in ("engine/ai_simulator.py", "web/game_flow.py")
    ] + [("engine/ai_activation_rehearsal.py::_queue_activation", queue)]
    found = 0
    for relative, tree in trees:
        for node in _executor_calls(tree):
            spelled = {keyword.arg for keyword in node.keywords if keyword.arg}
            splatted = [keyword.value for keyword in node.keywords if keyword.arg is None]
            found += 1
            assert not spelled, (relative, node.lineno, sorted(spelled))
            assert len(splatted) == 1 and isinstance(splatted[0], ast.Call), (
                relative, node.lineno,
            )
            assert getattr(splatted[0].func, "id", None) == "activation_announcement", (
                relative, node.lineno,
            )
    assert found == 5, f"expected the five AI activation executors, found {found}"
