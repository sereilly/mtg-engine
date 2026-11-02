"""``prompt_owed_by`` names the seat owing a session-level decision too.

The status line's "who is the game waiting on" read the pending-choice queue
alone (``web/prompts.prompt_owed_by``), so while a person chose their cleanup
discard or answered an upkeep payment — decisions held on the *session*, not
on the queue — the other viewer's panel said nothing about them (the "Three
wire leftovers from Legions' client group" Known-gaps entry).
``web/state_view._prompt_owed_by`` falls back to ``_SESSION_DECISIONS``, each
row asked through the very test its own payload is served by.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import CardDefinition, Permanent
from web.app import app, store
from web.runtime import CARD_BY_NAME
from web.state_view import _SESSION_DECISIONS
from web.turn_steps import _gather_upkeep_decisions

client = TestClient(app)


def _hvh():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 99002,
    }).json()
    sid = created["session_id"]
    joined = client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    assert joined.status_code == 200, joined.text
    session = store.get(sid)
    session.pregame_phase = None
    return sid, session


def _owed(sid, seat):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()[
        "prompt_owed_by"
    ]


def _sorcery(name):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Sorcery", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Sorcery"},
    )


def test_the_cleanup_discard_is_named_to_the_other_viewer():
    sid, session = _hvh()
    game = session.game
    game.active_player_index = 0
    session.current_turn = 0
    # Entered through the engine's own seam, which spends the turn's phase
    # plan (CR 500.8); writing the three fields by hand left turn 1's plan
    # still owing its combat phase, so the next step was combat.
    game._set_phase_and_step("postcombat_main", "postcombat_main")
    game.players[0].hand = [_sorcery(f"Spell {i}") for i in range(9)]
    for _ in range(2):
        moved = client.post(f"/api/sessions/{sid}/action", json={
            "seat": 0, "action": "next_phase",
        })
        assert moved.status_code == 200, moved.text
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert state["current_phase"] == "cleanup"
    assert state["cleanup_discard"]["required_count"] == 2

    assert _owed(sid, 1) == {
        "seat": 0, "name": game.players[0].name, "kind": "cleanup_discard",
        "doing": "discard down to their maximum hand size",
    }
    assert _owed(sid, 0)["doing"] == "discard down to your maximum hand size"

    for index in (0, 1):
        picked = client.post(f"/api/sessions/{sid}/action", json={
            "seat": 0, "action": "cleanup_select", "hand_index": index,
        })
        assert picked.status_code == 200, picked.text
    # The second pick completes the discard and the turn moves on.
    assert len(game.players[0].hand) == 7
    owed = _owed(sid, 1)
    assert owed is None or owed["kind"] != "cleanup_discard", owed


def test_an_upkeep_payment_is_named_to_the_other_viewer():
    sid, session = _hvh()
    game = session.game
    game.enforce_mana_costs = False
    game.active_player_index = 0
    session.current_turn = 0
    pit = Permanent(card=CARD_BY_NAME["breeding pit"])
    game._put_permanent_onto_battlefield(0, pit, None)
    game.players[0].mana_pool = {"B": 2}
    game._set_phase_and_step("beginning", "upkeep")
    assert _gather_upkeep_decisions(session, 0)

    assert _owed(sid, 1) == {
        "seat": 0, "name": game.players[0].name, "kind": "upkeep_pay",
        "doing": "decide whether to pay their upkeep costs",
    }
    paid = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "pay_upkeep", "card_name": "Breeding Pit",
        "prompt_permanent_id": pit.permanent_id,
    })
    assert paid.status_code == 200, paid.text
    owed = _owed(sid, 1)
    assert owed is None or owed["kind"] != "upkeep_pay", owed


def test_the_queue_is_still_asked_first_and_nothing_owed_is_none():
    sid, session = _hvh()
    session.game.active_player_index = 0
    session.current_turn = 0
    assert _owed(sid, 1) is None
    kinds = [kind for kind, _doing, _owes in _SESSION_DECISIONS]
    assert len(kinds) == len(set(kinds))
    assert {"cleanup_discard", "upkeep_pay", "optional_trigger"} <= set(kinds)
