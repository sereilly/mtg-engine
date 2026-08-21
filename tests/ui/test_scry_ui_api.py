"""Web-API tests for the scry prompt (CR 701.22a).

Scry has been a registered pending choice since the first temple was
ingested — the handler arms it, ``web/prompts.py`` renders it, the action
answers it — and the browser never showed it, because ``app.js`` had no
renderer reading ``state.scry``. Playing Temple of Malady in the browser
therefore produced a land that entered tapped and a game that sat waiting on a
prompt nobody could see. These pin the wire both ways for a *played land*
(the trigger fires off the non-cast entry path, not a resolving spell) and
``tests/ui/test_prompt_client_coverage.py`` keeps the next registered prompt
from shipping the same way.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.app import app, store

client = TestClient(app)

APP_JS = Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"
INDEX_HTML = Path(__file__).resolve().parents[2] / "web" / "static" / "index.html"


def _session(set_pool):
    m21 = set_pool("M21")
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4242,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].hand = [m21["Temple of Malady"]]
    game.players[0].library = [m21["Swamp"], m21["Forest"], m21["Island"]]
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    return sid, session, game


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _play_temple(sid: str):
    played = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Temple of Malady"},
    )
    assert played.status_code == 200, played.json()


def test_playing_the_temple_renders_a_scry_prompt_for_its_controller(set_pool):
    sid, session, game = _session(set_pool)
    _play_temple(sid)

    assert game.pending_scry is not None, "the ETB trigger armed the choice"
    state = _state(sid)
    prompt = state["scry"]
    assert prompt is not None
    assert prompt["caster_seat"] == 0
    assert prompt["card_name"] == "Temple of Malady"
    assert prompt["amount"] == 1
    assert prompt["top_count"] == 1
    assert [c["name"] for c in prompt["cards"]] == ["Swamp"]
    # The other seat does not see the looked-at card.
    assert _state(sid, seat=1)["scry"] is None


def test_the_scry_blocks_other_actions_until_answered(set_pool):
    sid, session, game = _session(set_pool)
    _play_temple(sid)

    refused = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"}
    )
    assert refused.status_code == 400
    assert "scry" in refused.json()["detail"]


@pytest.mark.parametrize(
    "bottom_count, expected",
    [
        (0, ["Swamp", "Forest", "Island"]),
        (1, ["Forest", "Island", "Swamp"]),
    ],
)
def test_confirming_arranges_the_library_and_clears_the_prompt(set_pool, bottom_count, expected):
    sid, session, game = _session(set_pool)
    _play_temple(sid)

    answered = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "scry_confirm",
            "card_order": [0],
            "bottom_count": bottom_count,
        },
    )
    assert answered.status_code == 200, answered.json()
    assert [c.name for c in game.players[0].library] == expected
    assert _state(sid)["scry"] is None
    assert game.pending_scry is None


def test_scry_modal_markup_matches_the_script():
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")
    for element_id in ("scryModal", "scryCards", "scryConfirmBtn", "scryKeepBtn", "scryBottomBtn"):
        assert f'id="{element_id}"' in html, element_id
        assert f'getElementById("{element_id}")' in js, element_id
