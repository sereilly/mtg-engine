"""No step is left with an object still on its stack at a table with a
person (SCG Phase 5, W1's second half; CR 500.2: "A phase or step in which
players receive priority ends when the stack is empty and all players pass in
succession").

The brief traced smoke game 1's turn 11 to a step left with its stack owed.
It was not that: the AI cycled Shoreline Ranger in its declare blockers step
*before the blocks* (no player holds priority then, CR 117.3a, 509.1; see
``test_scg_p5_ai_priority_round.py``), and the ability resolved in that step
once the blocks were in. But the census the brief asked for — every road out
of a step, watched for an object still on the stack — found two that were:

* the AI's draw step after an upkeep the person held on the phase rail:
  ``game_flow._advance_phase``'s upkeep branch ran the draw step and entered
  the main phase without asking whether the draw step's window had stopped
  on a question — the AI's Sylvan Library ("you may draw two additional
  cards") rode into the main phase on the stack;
* the person's own draw step after Island Sanctuary's question: the answer's
  handler did the same, and the person's Sylvan Library offer was answered in
  the main phase.

The spy is the one line every step change passes through
(``Game._set_phase_and_step``), so it watches every road the scenarios drive,
not only the two that were red.
"""

from __future__ import annotations

import pytest

from engine.card_loader import load_catalog
from engine.game import Game
from engine.models import Permanent
from tests.helpers import client, seat_plays_first
from web.app import store

_CARDS = {card.name: card for card in load_catalog()}
_LANDS = [{"name": name, "count": 8} for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")]


@pytest.fixture
def left_owing(monkeypatch):
    """Every step change, at a table with a person, that leaves a step which
    gives priority with an object still on the stack."""
    seen: list = []
    original = Game._set_phase_and_step

    def watching(self, phase, step):
        leaving = (self.current_turn_phase, self.current_step)
        if (
            self.interactive_seats
            and self.current_step
            and leaving != (phase, step)
            and self.stack
            and self._receives_priority(self.current_step)
        ):
            seen.append((leaving, (phase, step), [item.card.name for item in self.stack]))
        original(self, phase, step)

    monkeypatch.setattr(Game, "_set_phase_and_step", watching)
    return seen


def _session(first: int):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_deck_cards": _LANDS, "guest_deck_cards": _LANDS, "seed": 11},
    ).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, first)
    session.game.enforce_mana_costs = True
    for player in session.game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.library = [_CARDS["Plains"]] * 12
    return sid, session


def _put(game, seat: int, names) -> list:
    placed = []
    for name in names:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    return placed


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


def _act(sid: str, **body) -> dict:
    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})
    assert response.status_code == 200, (body, response.json())
    return response.json()


def _browser(sid: str, *, until, limit: int = 60) -> None:
    """The browser's requests until *until(state)*: the person answers an
    optional-pay offer with no, Island Sanctuary with "draw", passes with
    priority, declares nothing; ``ai_step`` on the AI's turn."""
    for _ in range(limit):
        state = _state(sid)
        if until(state):
            return
        combat = state.get("combat") or {}
        if state.get("optional_pay"):
            entry = state["optional_pay"]["pending"][0]
            _act(sid, action="resolve_optional_pay", card_name=entry["card_name"], accept=False)
        elif state.get("island_sanctuary_pending"):
            _act(sid, action="island_sanctuary_draw")
        elif state["priority_player"] == 0:
            _act(sid, action="pass_priority")
        elif state["current_turn"] == 1:
            _act(sid, action="ai_step")
        elif state["current_step"] == "declare_attackers" and not combat.get("attackers_locked"):
            _act(sid, action="declare_attackers", attacker_ids=[], target_seat=1)
        elif state.get("cleanup_discard"):
            _act(sid, action="cleanup_select", hand_index=0)
        else:
            _act(sid, action="next_phase")
    raise AssertionError(f"never got there: {_state(sid)['log'][-12:]}")


def test_the_ais_draw_step_after_a_held_upkeep_is_not_left_owing(left_owing):
    """The person holds the AI's upkeep on the phase rail; the AI's Sylvan
    Library asks the AI in its draw step. The draw step waits for the answer."""
    sid, session = _session(first=0)
    game = session.game
    _put(game, 1, ["Sylvan Library"])
    _act(sid, action="end_turn", stop_steps=["upkeep"])
    _browser(sid, until=lambda s: s["current_turn"] == 1 and s["current_step"] == "precombat_main")
    assert any("Sylvan Library finished resolving" in line for line in game.log), game.log[-12:]
    assert left_owing == []


def test_the_persons_draw_step_after_island_sanctuary_is_not_left_owing(left_owing):
    """The person's Island Sanctuary and Sylvan Library: answering the
    Sanctuary draws; the Library's offer is answered in the draw step."""
    sid, session = _session(first=1)
    game = session.game
    _put(game, 0, ["Island Sanctuary", "Sylvan Library"])
    seen_offer_in = []

    def until(state):
        if state.get("optional_pay"):
            seen_offer_in.append(state["current_step"])
        return state["current_turn"] == 0 and state["current_step"] == "precombat_main" and not state["stack"]

    _browser(sid, until=until)
    assert seen_offer_in and set(seen_offer_in) == {"draw"}, (seen_offer_in, game.log[-12:])
    assert left_owing == []


def test_the_ais_turn_with_its_abilities_is_not_left_owing(left_owing):
    """A whole AI turn of the doors W1 fixed — an ability, a cycle, an attack
    trigger — watched for a step left with any of them on the stack."""
    sid, session = _session(first=1)
    game = session.game
    _put(game, 1, ["Prodigal Sorcerer", "Charging Paladin", "Island", "Island"])
    game.players[1].hand = [_CARDS["Shoreline Ranger"]]
    game.players[1].library = [_CARDS["Island"]] * 8
    _browser(sid, until=lambda s: s["current_turn"] == 0)
    assert any("Charging Paladin" in line for line in game.log), game.log[-20:]
    assert left_owing == []
