"""A cycle whose trigger has nothing to act on is held, and a cycle is weighed
at instant speed (kg4 `aiact`, part 6).

**The defect.** "Cycling {4}{U}{U}. When you cycle this card, you may counter
target spell." (Decree of Silence.) The hand was asked in its owner's main
phase alone (``ai_hand_activations``; ROADMAP: "from-hand (cycling)
activations are not asked at instant speed"), where the stack is empty: the
trigger finds no target and is removed (CR 603.3d), and the seat paid six
mana for a card — the counter it carried spent on nothing (SCG W1G2).

**The fix.** At sorcery speed a cycle whose "When you cycle this card"
trigger names a target and finds none (the engine's own enumeration,
``ai_hand_activations._cycle_trigger_finds_nothing``) is held; the shared
priority answer (``ai_priority.act_at_priority``) asks the hand after the
battlefield, where only a cycle whose rehearsal leaves the seat ahead once
the turn is over is made. A plain cycle keeps its main phase.
"""
from __future__ import annotations

from collections import Counter

import pytest

from engine import ai_simulator
from engine.activation_zones import HAND
from engine.ai_hand_activations import (_cycle_trigger_finds_nothing,
                                        choose_hand_activation_action)
from engine.ai_priority import act_at_priority
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import derive_instruction_spec, usable_activated_abilities
from tests.helpers import _nosick, resolve_stack

_CATALOG = load_catalog()
_CARDS = {card.name: card for card in _CATALOG}
_LANDS = ("Island",) * 4 + ("Plains", "Plains", "Swamp", "Swamp", "Forest", "Forest", "Mountain", "Mountain")

#: The census floor: shipped cycling cards whose "When you cycle this card"
#: trigger names a target (11 at kg4: Decree of Silence, Complicate, Decree
#: of Savagery, Death Pulse, Choking Tethers, …).
_TARGETED_CYCLE_TRIGGER_FLOOR = 10


def _targeted_cycle_triggers() -> list[str]:
    names = set()
    for unit in compilation_units(_CATALOG):
        program = compile_card_oracle(unit)
        if not usable_activated_abilities(program, zone=HAND):
            continue
        for trigger in program.triggered_abilities:
            if trigger.condition.kind != "self_cycled" or trigger.instruction is None:
                continue
            spec = derive_instruction_spec([trigger.instruction])
            if isinstance(spec, dict) and spec.get("kind") not in (None, "none", "modal"):
                names.add(unit.name)
    return sorted(names)


def _table(hand, own=_LANDS, other=("Forest", "Forest"), *, active=0):
    """Two seats as `run_ai_simulation` builds them (mana enforced, both
    drivers), seat *active*'s precombat main phase, every permanent able to
    tap. Seat 0 holds *hand*."""
    players = [
        PlayerState(name=name, library=[_CARDS["Forest"]] * 8)
        for name in ("AI-A", "AI-B")
    ]
    players[0].hand = [_CARDS[name] for name in hand]
    game = ai_simulator._SimulatedGame(
        players=players, enforce_mana_costs=True,
        prompt_driver=ai_simulator._resolve_pending_choices,
    )
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    game.priority_driver = ai_simulator._priority_answerer(game, report, 1, [1])
    game.turn = 3
    game.active_player_index = active
    for seat, board in enumerate((own, other)):
        for name in board:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game, report


def test_the_census_finds_every_targeted_cycle_trigger():
    found = _targeted_cycle_triggers()
    assert len(found) >= _TARGETED_CYCLE_TRIGGER_FLOOR, found
    assert {"Decree of Silence", "Complicate", "Decree of Savagery"} <= set(found)


#: Of those, the ones whose trigger names no player — a spell or a creature
#: only — and so finds nothing on an empty stack and an empty board (7 at
#: kg4); "any target" and "target player" always have a seat to name.
_HELD_FLOOR = 6


@pytest.mark.parametrize("name", _targeted_cycle_triggers())
def test_a_cycle_whose_trigger_finds_nothing_is_held_in_the_main_phase(name):
    """An empty stack and no creature anywhere: a trigger that can name
    nothing is not worth cycling for, so the cycle is not proposed — and the
    simulator's main phase leaves the card in hand. A trigger that can name
    a seat is weighed by its rehearsal as before."""
    game, report = _table((name,))
    if not _cycle_trigger_finds_nothing(game, 0, _CARDS[name]):
        pytest.skip("its trigger can name a player on any board")
    assert choose_hand_activation_action(game, 0) is None
    ai_simulator._play_activations(game, 0, report, 1, 3)
    assert [card.name for card in game.players[0].hand] == [name]


def test_the_held_census_examined_something():
    held = [
        name for name in _targeted_cycle_triggers()
        if _cycle_trigger_finds_nothing(_table((name,))[0], 0, _CARDS[name])
    ]
    assert len(held) >= _HELD_FLOOR, held
    assert {"Decree of Silence", "Complicate", "Decree of Savagery"} <= set(held)


def test_a_plain_cycle_keeps_its_main_phase():
    """A cycle with no trigger (a card out, a card in) is the main phase's,
    as it always was, and is not made at instant speed."""
    plain = "Disciple of Grace"
    program = compile_card_oracle(_CARDS[plain])
    assert usable_activated_abilities(program, zone=HAND) and not program.triggered_abilities
    game, _report = _table((plain,))
    action = choose_hand_activation_action(game, 0)
    assert action is not None and action.card_name == plain, action
    assert choose_hand_activation_action(game, 0, at_instant_speed=True) is None


def test_decree_of_silence_is_cycled_in_response_and_counters_the_spell():
    """The opponent casts Grizzly Bears; seat 0, given priority, cycles
    Decree of Silence and its trigger counters the Bears — the simulator
    records it as an instant-speed activation from the hand."""
    game, report = _table(("Decree of Silence",), active=1)
    game.players[1].hand.append(_CARDS["Grizzly Bears"])
    game.players[1].mana_pool["G"] = 2
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert ai_simulator._answer_priority(game, 0, report, 1, 3)
    resolve_stack(game)
    assert any(card.name == "Grizzly Bears" for card in game.players[1].graveyard)
    assert not any(p.card.name == "Grizzly Bears" for p in game.controlled_by(1))
    assert any(card.name == "Decree of Silence" for card in game.players[0].graveyard)
    assert report.activations_from_hand_at_instant_speed == Counter({"Decree of Silence": 1})
    assert any(
        "activate Decree of Silence from hand" in line and "in response to Grizzly Bears" in line
        for line in report.log_lines
    ), report.log_lines


def test_the_decree_is_not_cycled_in_response_to_its_own_seats_spell():
    """CR 117.3c: a seat does not answer its own object — the response
    window is another seat's (``ai_priority.instant_speed_window``)."""
    game, _report = _table(("Decree of Silence", "Grizzly Bears"), active=0)
    game.players[0].mana_pool["G"] = 2
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert act_at_priority(game, 0) is None
