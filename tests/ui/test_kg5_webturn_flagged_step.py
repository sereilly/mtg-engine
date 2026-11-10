"""At a step the person flagged on the phase rail during an AI's turn, every
AI seat priority passes through on its way to the person is asked first
(CR 117.3d: "Then the next player in turn order receives priority").

The rail's hold (``game_flow._hold_at_flagged_step``) passed the active AI's
priority and then each AI seat's between it and the person with a bare
``pass_priority``: the seat was never asked (``engine.ai_priority.
act_at_priority``), so a free-for-all AI holding a draw for the opponent's end
step kept it in hand whenever a person had flagged the step — and the upkeep's
and the draw step's holds (``turn_steps``) made the same bare passes.

Census: one whole AI turn, every step flagged, at a three-seat table in both
seatings — the AI between the active AI and the person in seat order, and
after it with the person first. Every ask of ``act_at_priority`` is recorded
with its seat and step; each step the person is handed priority in must have
asked the seat between first.
"""

from __future__ import annotations

import pytest

import web.game_flow as game_flow
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import client, seat_plays_first

_CARDS = {card.name: card for card in load_catalog()}

_EVERY_STEP = [
    "upkeep", "draw", "precombat_main", "beginning_of_combat", "declare_attackers",
    "declare_blockers", "combat_damage", "end_of_combat", "postcombat_main", "end",
]

#: (the person's seat, the active AI's, the AI's between them in turn order).
_SEATINGS = [(2, 0, 1), (0, 1, 2)]


def _table(person: int):
    seats = [{"name": f"P{i}", "is_ai": i != person, "colors": 2} for i in range(3)]
    created = client.post(
        "/api/sessions", json={"mode": "free_for_all", "seed": 11, "seats": seats},
    ).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, person)
    for player in session.game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.library = [_CARDS["Plains"]] * 12
    return sid, session


def _put(game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_CARDS[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat={seat}").json()


def _act(sid: str, seat: int, **body) -> dict:
    response = client.post(f"/api/sessions/{sid}/action", json={"seat": seat, **body})
    assert response.status_code == 200, (body, response.json())
    return response.json()


@pytest.mark.cr("117.3a", "117.3d")
@pytest.mark.parametrize("person, active, between", _SEATINGS)
def test_every_flagged_step_asks_the_ai_between_before_the_person(
    monkeypatch, person, active, between,
):
    """The person ends their turn with every step of the next (an AI's)
    flagged. At each step they are handed priority in, the AI seat priority
    passed through on the way was asked first; at the end step it answers
    with Ancestral Recall, which the person is then asked over before it
    resolves."""
    sid, session = _table(person)
    game = session.game
    _put(game, between, "Island")
    game.players[between].hand = [_CARDS["Ancestral Recall"]]

    events: list[tuple] = []
    real_ask = game_flow.act_at_priority

    def recording_ask(game_, seat, **kwargs):
        events.append(("asked", seat, game_.current_step))
        return real_ask(game_, seat, **kwargs)

    monkeypatch.setattr(game_flow, "act_at_priority", recording_ask)

    _act(sid, person, action="end_turn", stop_steps=_EVERY_STEP)
    assert game.active_player_index == active
    stacks_seen: dict[str, list[int]] = {}
    for _ in range(80):
        state = _state(sid, person)
        if state["current_turn"] != active:
            break
        if state["priority_player"] == person:
            step = state["current_step"]
            events.append(("person", step))
            stacks_seen.setdefault(step, []).append(len(state["stack"]))
            _act(sid, person, action="pass_priority", stop_steps=_EVERY_STEP)
        else:
            _act(sid, person, action="ai_step", stop_steps=_EVERY_STEP)
    else:
        raise AssertionError(f"the AI's turn never ended: {game.log[-12:]}")

    # The floor: the person was handed priority in every step of the turn
    # that has a window and a reason to be held (no attack, so no blockers
    # or damage step), the beginning phase's two included.
    held = set(stacks_seen)
    assert {
        "upkeep", "draw", "precombat_main", "beginning_of_combat",
        "declare_attackers", "end_of_combat", "postcombat_main", "end",
    } <= held, stacks_seen

    unasked = []
    for step in held:
        first_hold = events.index(("person", step))
        if ("asked", between, step) not in events[:first_hold]:
            unasked.append(step)
    assert not unasked, (unasked, events)

    # What the seat between did when asked: Ancestral Recall at the active
    # AI's end step (`instant_speed_window`'s "end_step"), put on the stack
    # and answered by the person before it resolved (CR 117.3c, 117.4).
    assert stacks_seen["end"][0] == 1, stacks_seen
    assert any("Ancestral Recall resolved" in line for line in game.log), game.log[-20:]
    assert [card.name for card in game.players[between].graveyard] == ["Ancestral Recall"]


@pytest.mark.cr("117.3a", "503.1")
def test_the_ais_flagged_upkeep_opens_with_its_own_priority():
    """Two seats, the person flagging the AI's upkeep: the upkeep stops with
    the active AI holding priority (CR 117.3a, 503.1), and the AI's step that
    answers it hands priority to the person. The upkeep's hold passed the
    AI's priority on as the turn began, unasked."""
    created = client.post("/api/sessions", json={"mode": "human_vs_ai", "seed": 5}).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, 0)
    game = session.game
    game.players[0].hand = game.players[0].hand[:5]

    after_end = _act(sid, 0, action="end_turn", stop_steps=["upkeep"])
    assert (after_end["current_turn"], after_end["current_step"]) == (1, "upkeep")
    assert after_end["priority_player"] == 1

    after_step = _act(sid, 0, action="ai_step", stop_steps=["upkeep"])
    assert (after_step["current_turn"], after_step["current_step"]) == (1, "upkeep")
    assert after_step["priority_player"] == 0
