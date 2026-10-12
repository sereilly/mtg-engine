"""A prompt an AI seat comes to owe *because a human answered theirs* is
answered in the same request.

Tahngarth's Glare: "Look at the top three cards of target opponent's library,
then put them back in any order. **That player** looks at the top three cards
of your library, then puts them back in any order." Cast by a person against an
AI, the person's reorder arms the AI's. ``do_action`` drained AI-owned prompts
*before* the handler and not after, so the response to the confirm still had
the spell on the stack with priority apparently the caster's; the browser's
auto-pass answered that state, the next request's preamble finished the spell,
and the pass was then applied to the empty stack that followed. Both players
had passed, and the caster's main phase was over — found by casting the card in
a browser, twice in two.
"""

from __future__ import annotations

from tests.helpers import client

LANDS = [{"name": name, "count": 8} for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")]


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


def _act(sid: str, **body) -> dict:
    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})
    assert response.status_code == 200, response.text
    return response.json()


def _reach_own_precombat_main(sid: str) -> dict:
    for _ in range(80):
        state = _state(sid)
        if state["current_turn"] == 0 and state["current_step"] == "precombat_main" and state["priority_player"] == 0:
            return state
        if state["current_turn"] != 0 and state["priority_player"] != 0:
            _act(sid, action="ai_step")
        elif state.get("cleanup_discard"):
            _act(sid, action="cleanup_select", hand_index=0)
        else:
            _act(sid, action="pass_priority")
    raise AssertionError("never reached the human's precombat main phase")


def test_the_ai_half_of_tahngarths_glare_is_answered_with_the_humans():
    sid = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_deck_cards": LANDS, "guest_deck_cards": LANDS, "seed": 11},
    ).json()["session_id"]
    before = _reach_own_precombat_main(sid)
    me, ai = (player["name"] for player in before["players"])

    _act(sid, action="debug_add_to_hand", card_name="Tahngarth's Glare")
    _act(sid, action="debug_add_mana", mana_color="R")
    _act(sid, action="cast", card_name="Tahngarth's Glare", target_seat=1)
    asked = _act(sid, action="pass_priority")

    # The caster's half: the game waits on it, and says so.
    assert asked["reorder_library"]["target_seat"] == 1
    assert asked["waiting_on_prompt"] is True
    assert [item["label"] for item in asked["stack"]] == ["Tahngarth's Glare"]

    answered = _act(sid, action="reorder_library_confirm", card_order=[0, 1, 2])

    # …and the AI's half, in the same request: nothing is owed, the spell has
    # left the stack, and the turn is where the caster left it.
    assert answered["reorder_library"] is None
    assert answered["waiting_on_prompt"] is False
    assert answered["stack"] == []
    assert (answered["current_turn"], answered["current_step"]) == (0, "precombat_main")
    assert answered["priority_player"] == 0
    assert answered["turn_number"] == before["turn_number"]

    log = answered["log"]
    mine = log.index(f"{me} is looking at the top 3 cards of {ai}'s library")
    theirs = log.index(f"{ai} is looking at the top 3 cards of {me}'s library")
    assert mine < theirs < log.index("Tahngarth's Glare finished resolving")
    # Nobody has passed priority since the spell resolved.
    assert not any("passed priority" in line for line in log[theirs:])
