"""An ``ai_step`` advances the AI turn it was asked to step, and no other.

Found by playing the promoted Apocalypse set in a browser: whenever the human
passed priority in the AI's *second* main phase — a stop set on the phase
rail's M2, or simply the AI playing a land or resolving a spell there — the
human's next turn began at Declare Attackers. Three requests do it::

    pass_priority   (human, AI's postcombat main, empty stack)  -> AI's end step
    ai_step                                                     -> human's turn,
                                                                   already in combat

``_action_ai_step`` ran ``_advance_phase`` and then ``_advance_ai_turn``. From
the end step the first call is the whole turn handoff — cleanup, then the next
player's untap, upkeep and draw — and the second read "the turn I am advancing"
only *inside* its loop, after the turn had changed, so it walked the human's
precombat main phase into combat.
"""

from __future__ import annotations

from tests.helpers import client

LANDS = [{"name": name, "count": 8} for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")]
#: The phase rail as the browser sends it with a stop on the opponent's M2.
RAIL = {"stop_steps": ["postcombat_main"], "self_stop_steps": ["precombat_main", "postcombat_main"]}


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


def _act(sid: str, **body):
    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **RAIL, **body})
    return response.status_code, response.json()


def _finish_own_turn(sid: str) -> None:
    for _ in range(40):
        state = _state(sid)
        if state["current_turn"] != 0:
            return
        if state.get("cleanup_discard"):
            code, _ = _act(sid, action="cleanup_select", hand_index=0)
        elif state["current_step"] == "declare_attackers" and state["priority_player"] is None:
            code, _ = _act(sid, action="declare_attackers", attacker_indices=[], target_seat=1)
        else:
            code, _ = _act(sid, action="pass_priority")
            if code != 200:
                code, _ = _act(sid, action="next_phase")
        assert code == 200
    raise AssertionError("the human's turn never ended")


def _play_ai_turn(sid: str) -> int:
    """Drive the AI's turn the way the client does. Returns how many times the
    human's pass in the AI's second main phase moved the game to its end step —
    the state the next ``ai_step`` used to walk on from."""
    handed_on_from_second_main = 0
    for _ in range(60):
        state = _state(sid)
        if state["current_turn"] == 0:
            return handed_on_from_second_main
        if state["priority_player"] == 0:
            before = state["current_step"]
            code, after = _act(sid, action="pass_priority")
            assert code == 200
            if before == "postcombat_main" and after["current_step"] == "end":
                handed_on_from_second_main += 1
        else:
            code, _ = _act(sid, action="ai_step")
            assert code == 200
    raise AssertionError("the AI's turn never ended")


def test_the_humans_turn_begins_in_its_precombat_main_phase():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_deck_cards": LANDS, "guest_deck_cards": LANDS, "seed": 11},
    ).json()
    sid = created["session_id"]

    exercised = 0
    human_turns = 0
    for _ in range(4):
        _finish_own_turn(sid)
        exercised += _play_ai_turn(sid)
        state = _state(sid)
        assert state["current_turn"] == 0
        human_turns += 1
        assert state["current_step"] == "precombat_main", (
            f"turn {state['turn_number']}: the human's turn began at {state['current_step']}"
        )
        assert state["priority_player"] == 0

    # The honesty count: a run in which the human never handed the AI its end
    # step from the second main phase proves nothing about the request that
    # follows it.
    assert human_turns == 4
    assert exercised >= 1
