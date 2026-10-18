"""A search for "a card" over the wire: no failing to find (CR 701.23d).

Demonic Tutor and Entomb offered "Fail to Find" and
``{"action":"search_library_decline"}`` took it: "searched and found nothing
more", with a library full of cards. A search that names no quality must find.

What a client is sent and may send now:

* every ``search_library`` payload carries ``min_picks`` — the engine's floor:
  1 for a search for "a card" while the zone holds one, 0 for a search with a
  stated quality (CR 701.23b) and for "up to";
* ``search_library_decline`` under a floor is a **400** that keeps the prompt
  (it used to return 200 whether or not the engine accepted the decline).

The rule and the pool census are
``tests/rules/test_unqualified_search_must_find.py``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.game_types import OracleExecutionContext
from engine.oracle import compile_card_oracle
from web.app import app, store
from web.runtime import CARD_BY_NAME

client = TestClient(app)


def _search(card_name: str):
    created = client.post(
        "/api/sessions", json={"mode": "human_vs_human", "seed": 6021},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    game = store.get(sid).game
    game.interactive_seats = {0, 1}
    me = game.players[0]
    me.library = [
        CARD_BY_NAME[name] for name in ("forest", "sol ring", "grizzly bears")
    ]
    me.hand = []
    card = CARD_BY_NAME[card_name]
    game._execute_oracle_instruction(
        compile_card_oracle(card).instructions[0],
        OracleExecutionContext(caster=me, target=me, card=card),
    )
    return sid, game, me


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})


def test_demonic_tutor_cannot_fail_to_find():
    sid, _game, me = _search("demonic tutor")

    prompt = _state(sid)["search_library"]
    assert prompt["min_picks"] == 1 and prompt["card_type"] == "any"

    declined = _act(sid, action="search_library_decline")
    assert declined.status_code == 400
    assert "must find a card" in declined.json()["detail"]
    assert _state(sid)["search_library"] is not None
    assert len(me.library) == 3 and me.hand == []

    found = _act(sid, action="search_library_confirm", hand_index=1)
    assert found.status_code == 200, found.text
    assert [card.name for card in me.hand] == ["Sol Ring"]
    assert _state(sid)["search_library"] is None


def test_a_search_with_a_stated_quality_still_may():
    sid, _game, me = _search("enlightened tutor")

    assert _state(sid)["search_library"]["min_picks"] == 0

    declined = _act(sid, action="search_library_decline")
    assert declined.status_code == 200, declined.text
    assert _state(sid)["search_library"] is None
    assert me.hand == []
