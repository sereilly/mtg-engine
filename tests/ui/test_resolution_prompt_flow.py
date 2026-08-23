"""The reported Sanctum of All flow, through the web layer the player used.

The engine half is guarded in
``tests/regressions/test_resolution_holds_priority.py``. This is the half the
player actually saw: the state payload the board polls, and the action gate that
decides what they may do while the prompt is up. A resolution that is still
asking must show its object on the stack, show the prompt, and refuse to be
passed past — including the *second* prompt, the one the first answer arms,
which is where the reported bug landed.
"""

from __future__ import annotations

from web.app import store
from tests.helpers import client
from engine.models import Permanent, PlayerState


def _sanctum_upkeep_session(set_pool, seed=5150):
    pool = set_pool("M21")
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": seed,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.players[0].battlefield = [Permanent(card=pool["Sanctum of All"])]
    game.players[0].library = [pool["Sanctum of Tranquil Light"]]
    session.current_turn = 0
    game.active_player_index = 0
    game.interactive_seats = {0, 1}
    game.resolve_upkeep(0, defer_priority=True)
    game.start_priority_window(0)
    return sid, session


def _state(sid, seat):
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def _pass(sid, seat):
    return client.post(
        f"/api/sessions/{sid}/action", json={"seat": seat, "action": "pass_priority"}
    )


def test_the_optional_prompt_is_shown_with_the_ability_still_on_the_stack(set_pool):
    sid, _ = _sanctum_upkeep_session(set_pool)

    _pass(sid, 0)
    assert _pass(sid, 1).status_code == 200

    state = _state(sid, 0)
    assert [item["card"]["name"] for item in state["stack"]] == ["Sanctum of All"]
    assert state["optional_pay"] is not None
    assert state["optional_pay"]["pending"][0]["card_name"] == "Sanctum of All"


def test_priority_cannot_be_passed_past_either_prompt(set_pool):
    sid, _ = _sanctum_upkeep_session(set_pool)
    _pass(sid, 0)
    _pass(sid, 1)

    # The offer itself.
    refused = _pass(sid, 0)
    assert refused.status_code == 400

    accepted = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "resolve_optional_pay", "accept": True},
    )
    assert accepted.status_code == 200

    # And the search the answer armed — the step the ability used to skip past
    # by leaving the stack the moment the offer was answered.
    state = _state(sid, 0)
    assert [item["card"]["name"] for item in state["stack"]] == ["Sanctum of All"]
    assert state["search_library"] is not None
    assert _pass(sid, 0).status_code == 400
    # A library search stops the whole table, not just the seat searching it.
    assert _pass(sid, 1).status_code == 400


def test_the_turn_stops_at_the_upkeep_the_trigger_fired_in(set_pool):
    """The path the report came in on, which the hand-built upkeep above misses.

    A turn reached by ``end_turn`` runs its beginning phase through
    ``_resolve_upkeep_step``, which drained the upkeep's whole stack with no
    priority window at all — the trigger resolved, the prompt was armed, and the
    draw step and main phase ran on top of it. The player was looking at their
    main phase with an unanswered "you may search your library" on screen.
    """
    pool = set_pool("M21")
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 8121,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    game = store.get(sid).game
    game.players[0].battlefield = [Permanent(card=pool["Sanctum of All"])]
    game.players[0].library = [pool["Sanctum of Tranquil Light"], *game.players[0].library]

    # Seat 0's turn ends, seat 1's runs, and seat 0's next upkeep is the trigger.
    client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
    client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "end_turn"})
    while store.get(sid).cleanup_required_discards:
        client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 1, "action": "cleanup_select", "hand_index": 0},
        )
        client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "end_turn"})

    state = _state(sid, 0)
    assert state["current_step"] == "upkeep", state["current_step"]
    assert [item["card"]["name"] for item in state["stack"]] == ["Sanctum of All"]
    assert state["optional_pay"] is not None
    assert "Sanctum of All ability resolved" not in state["log"]

    # Answering it resumes the beginning phase: the draw step runs and the turn
    # lands in the main phase, rather than having run there already.
    client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "resolve_optional_pay", "accept": True},
    )
    client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "search_library_confirm",
            "hand_index": 0,
            "search_zone": "library",
        },
    )
    state = _state(sid, 0)
    assert state["current_step"] == "precombat_main"
    assert state["stack"] == []
    board = [p.card.name for p in store.get(sid).game.players[0].battlefield]
    assert "Sanctum of Tranquil Light" in board


def test_an_ai_seats_own_upkeep_prompt_does_not_stall_the_turn(set_pool):
    """The other half of the pause: a prompt owed by a seat that answers itself.

    Holding a resolution for *every* prompt would stop an AI's upkeep dead until
    the human happened to click something, so the drain answers AI-owned prompts
    where it stands and carries on. Only a human's decision stops the phase.
    """
    pool = set_pool("M21")
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 6060,
        },
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    game = session.game
    # Seat 1 is the AI; give it the Shrine and hand it the turn.
    game.players[1].battlefield = [Permanent(card=pool["Sanctum of All"])]
    game.players[1].library = [pool["Sanctum of Tranquil Light"], *game.players[1].library]

    client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})

    state = _state(sid, 0)
    assert state["stack"] == []
    assert state["optional_pay"] is None
    assert state["search_library"] is None
    assert store.get(sid).paused_beginning_phase is None
    # The AI took its own default, and its turn is under way.
    assert state["current_turn"] == 1


def test_the_ability_leaves_the_stack_when_the_search_is_answered(set_pool):
    sid, session = _sanctum_upkeep_session(set_pool)
    _pass(sid, 0)
    _pass(sid, 1)
    client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "resolve_optional_pay", "accept": True},
    )

    answered = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "search_library_confirm",
            "hand_index": 0,
            "search_zone": "library",
        },
    )
    assert answered.status_code == 200

    state = _state(sid, 0)
    assert state["stack"] == []
    assert state["search_library"] is None
    assert state["optional_pay"] is None
    board = [p.card.name for p in session.game.players[0].battlefield]
    assert "Sanctum of Tranquil Light" in board


# ---------------------------------------------------------------------------
# A held *spell* is on the stack and nowhere else while its prompt is owed
# ---------------------------------------------------------------------------


def _mind_rot_session(set_pool, seed=5151):
    """Host casts Mind Rot at Guest; both pass; Guest (human) owes the discard."""
    pool = set_pool("M21")
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": seed,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].hand = [pool["Mind Rot"]]
    game.players[0].graveyard = []
    game.players[1].hand = [pool["Opt"], pool["Storm Caller"], pool["Forest"]]
    session.current_turn = 0
    game.active_player_index = 0
    game.current_turn_phase = "main"
    game.current_step = "precombat_main"
    game.interactive_seats = {0, 1}
    assert game._cast_onto_stack(0, "Mind Rot", target_player_index=1).supported
    game.start_priority_window(0)
    return sid, session


def test_a_held_spell_is_reported_on_the_stack_and_not_in_the_graveyard(set_pool):
    """The card was in both: the stack payload carried it (held) and the
    graveyard payload carried it too, because the engine binned it before the
    discard it asked for was answered. CR 608.2n puts the graveyard last."""
    sid, _ = _mind_rot_session(set_pool)

    _pass(sid, 0)
    assert _pass(sid, 1).status_code == 200

    state = _state(sid, 1)
    assert [item["card"]["name"] for item in state["stack"]] == ["Mind Rot"]
    assert state["stack"][0]["resolution_held"] is True
    host = state["players"][0]
    assert [c["name"] for c in host["graveyard"]] == []
    assert state["discard_select"] is not None
    assert state["discard_select"]["player_seat"] == 1


def test_answering_the_discard_moves_the_spell_to_the_graveyard(set_pool):
    sid, _ = _mind_rot_session(set_pool)
    _pass(sid, 0)
    _pass(sid, 1)

    answered = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "discard_confirm", "discard_indices": [0, 1]},
    )
    assert answered.status_code == 200, answered.text

    state = _state(sid, 0)
    assert state["stack"] == []
    assert [c["name"] for c in state["players"][0]["graveyard"]] == ["Mind Rot"]
    assert state["discard_select"] is None
    # CR 117.3b: the active player has priority again, not the seat that answered.
    assert state["priority_player"] == 0
