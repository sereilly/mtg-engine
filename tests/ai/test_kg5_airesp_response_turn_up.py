"""An AI seat turns a face-down creature face up **in response** to another
seat's spell (CR 116.2b, 702.37e) — the special action asked at instant speed.

    116.2b Turning a face-down creature face up is a special action. A
    player can take this action any time they have priority.

``ai_special_actions`` weighed ``turn_face_up`` only in the seat's own main
phase with its combat ahead, so the morphs printed to answer a spell never
did: Mischievous Quanar ("When this creature is turned face up, copy target
instant or sorcery spell"), Voidmage Apprentice ("…counter target spell"),
Willbender ("…change the target of target spell or ability with a single
target") sat face down while the Lightning Bolt they exist for resolved (kg4,
the Known-gaps "AI leftovers" entry). ``ai_priority.act_at_priority`` now asks
``choose_response_special_action`` in its ``"response"`` window: each offer
rehearsed against the stack resolving with nothing taken.

The census is every pool morph whose turn-up trigger targets a spell, read
off the compiled program — never a list of names — each against an
opponent's Lightning Bolt at the seat's Grizzly Bears.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_priority import act_at_priority
from engine.ai_simulator import SimulationReport, _priority_answerer
from engine.card_loader import load_cards, manifest_set_paths
from engine.face_down import TURNED_FACE_UP, face_down_card, is_face_down
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import _from_instructions
from tests.helpers import settle

#: The census must examine at least this many morphs (Mischievous Quanar,
#: Voidmage Apprentice, Willbender in the pool at kg5).
_SPELL_ANSWERING_MORPHS_FLOOR = 3


def _pool() -> dict:
    pool: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    return pool


_POOL = _pool()


def _spell_answering_morphs() -> list:
    """Every supported pool unit whose "When this creature is turned face up"
    trigger targets a spell on the stack (its derived spec's kind)."""
    found = []
    for unit in compilation_units(list(_POOL.values())):
        if "morph" not in (unit.oracle_text or "").lower():
            continue
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        for trigger in program.triggered_abilities:
            if trigger.condition.kind != TURNED_FACE_UP or trigger.instruction is None:
                continue
            spec = _from_instructions((trigger.instruction,)) or {}
            if spec.get("kind") == "stack":
                found.append(unit)
                break
    return found


def _permanent(card, *, face_down: bool = False) -> Permanent:
    permanent = Permanent(card=face_down_card(card) if face_down else card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _board(morph, *, spell: str = "Lightning Bolt", at: str = "bears", lands: int = 4):
    """Seat 1's main phase: it casts *spell* at seat 0's Grizzly Bears (or the
    face-down creature itself, ``at="morph"``); seat 0 holds the face-down
    *morph*, the Bears and *lands* Islands, and has priority."""
    hidden = _permanent(morph, face_down=True)
    bears = _permanent(_POOL["Grizzly Bears"])
    giant = _permanent(_POOL["Hill Giant"])
    islands = [_permanent(_POOL["Island"]) for _ in range(lands)]
    plains = [_permanent(_POOL["Plains"]) for _ in range(2)]
    us = PlayerState(name="A", battlefield=[hidden, bears, *islands, *plains],
                     library=[_POOL["Island"]] * 10)
    them = PlayerState(name="B", battlefield=[giant], library=[_POOL["Island"]] * 10)
    game = Game(players=[us, them])
    game.enforce_mana_costs = True
    game.active_player_index = 1
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    game.start_priority_window(1)
    them.hand = [_POOL[spell]]
    them.mana_pool.update({"R": 2})
    aimed = hidden if at == "morph" else bears
    cast = game.queue_from_hand(
        1, spell, target_player_index=0, target_permanent_ids=[aimed.permanent_id],
    )
    assert cast.supported, cast.details
    game.priority_player_index = 0
    return game, hidden, bears, giant


def test_the_census_finds_the_spell_answering_morphs():
    """The population is read off the compiled programs, and is not empty."""
    names = sorted(unit.name for unit in _spell_answering_morphs())
    assert len(names) >= _SPELL_ANSWERING_MORPHS_FLOOR, names


@pytest.mark.parametrize(
    "morph", [unit.name for unit in _spell_answering_morphs()],
)
def test_a_morph_printed_to_answer_a_spell_is_turned_up_over_it(morph):
    """In response to the opponent's Bolt at its Bears, the seat turns the
    morph face up, and the turn-up's trigger targets the Bolt — and the Bolt
    does not do what it was cast to do: the Bears survive, or the Bolt (or a
    copy of it) lands on the opponent's side."""
    game, hidden, bears, giant = _board(_POOL[morph])
    act = act_at_priority(game, 0)
    assert act is not None and act.kind == "special" and act.supported, act
    assert act.window == "response" and act.answering == "Lightning Bolt"
    assert not is_face_down(hidden)
    assert f"{morph}: targets Lightning Bolt" in game.log
    settle(game)
    bears_alive = any(p is bears for p in game.controlled_by(0))
    giant_gone = not any(p is giant for p in game.controlled_by(1))
    assert bears_alive or giant_gone or game.players[1].life < 20, game.log[-12:]


def test_a_body_that_survives_the_burn_is_turned_up_in_front_of_it():
    """No trigger at all: Exalted Angel face down is a 2/2, and a Lightning
    Bolt aimed at it kills it. Face up it is a 4/5 that takes the 3 and
    lives — the response is the whole of the answer."""
    game, hidden, _bears, _giant = _board(_POOL["Exalted Angel"], at="morph")
    act = act_at_priority(game, 0)
    assert act is not None and act.kind == "special" and act.supported, act
    settle(game)
    assert any(p is hidden for p in game.controlled_by(0)), game.log[-8:]
    assert hidden.card.name == "Exalted Angel"


def test_nothing_is_turned_up_over_the_seats_own_spell():
    """A seat does not answer its own object (``instant_speed_window``)."""
    game, hidden, bears, _giant = _board(_POOL["Mischievous Quanar"])
    game.stack[-1].caster_index = 0
    assert act_at_priority(game, 0) is None
    assert is_face_down(hidden)


def test_the_simulators_priority_driver_takes_it_and_counts_it():
    """Driven through the engine's priority round with the simulator's own
    answer installed (``Game.priority_driver``): the turn-up is taken before
    the Bolt resolves, logged ``[in response to Lightning Bolt]`` and counted
    in ``SimulationReport.special_actions_in_response``."""
    game, hidden, bears, giant = _board(_POOL["Voidmage Apprentice"])
    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    game.priority_driver = _priority_answerer(game, report, 1, [3])
    game.priority_player_index = None
    game.offer_priority(first=0)
    settle(game)
    assert report.special_actions_in_response["turn_face_up"] == 1, report.log_lines
    assert report.special_actions_taken["turn_face_up"] == 1
    assert any(
        "special action turn_face_up (Face-down creature) -> taken "
        "[in response to Lightning Bolt]" in line
        for line in report.log_lines
    ), report.log_lines
    assert "Lightning Bolt was countered by Voidmage Apprentice" in " ".join(game.log)
    assert any(p is bears for p in game.controlled_by(0))
