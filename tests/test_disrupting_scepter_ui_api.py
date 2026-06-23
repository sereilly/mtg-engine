"""Web-API tests for the Disrupting Scepter / Library of Leng discard prompt.

Disrupting Scepter was reported FAILED in-game ("I didn't get to choose the card
to discard") and Library of Leng ("I didn't get the option of discarding to the
top of my library after using disrupting scepter on myself"). The non-random
discard now defers to the discarding player's choice, surfaced as a prompt and
completed via the `discard_confirm` action — optionally to the top of the library
when Library of Leng is in play.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from engine import load_cards
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_CARDS = {c.name: c for c in load_cards(Path(__file__).resolve().parent.parent / "lea_cards.json")}


def _session(with_library_of_leng: bool):
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
    battlefield = [Permanent(card=_CARDS["Disrupting Scepter"])]
    if with_library_of_leng:
        battlefield.append(Permanent(card=_CARDS["Library of Leng"]))
    game.players[0].battlefield = battlefield
    game.players[0].hand = [_CARDS["Island"], _CARDS["Mountain"], _CARDS["Forest"]]
    session.current_turn = 0
    game.active_player_index = 0
    # Resolve the activated ability directly so the pending discard is set up.
    game.activate_permanent_ability(0, "Disrupting Scepter", target_player_index=0)
    return sid, session, game


def test_discard_prompt_is_surfaced_to_the_discarding_player():
    sid, session, game = _session(with_library_of_leng=False)

    info = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["discard_select"]
    assert info is not None
    assert info["player_seat"] == 0
    assert info["count"] == 1
    assert info["allow_top_of_library"] is False
    assert len(info["cards"]) == 3


def test_player_chooses_which_card_to_discard():
    sid, session, game = _session(with_library_of_leng=False)

    # Choose to discard the Mountain (index 1).
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "discard_confirm", "discard_indices": [1]},
    )
    assert resp.status_code == 200, resp.text
    assert [c.name for c in game.players[0].graveyard] == ["Mountain"]
    assert sorted(c.name for c in game.players[0].hand) == ["Forest", "Island"]
    assert game.pending_discard is None


def test_library_of_leng_allows_discarding_to_top_of_library():
    sid, session, game = _session(with_library_of_leng=True)

    info = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["discard_select"]
    assert info["allow_top_of_library"] is True

    before_library = len(game.players[0].library)
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "discard_confirm", "discard_indices": [0], "to_library": True},
    )
    assert resp.status_code == 200, resp.text
    # The discarded card went to the top of the library, not the graveyard.
    assert game.players[0].graveyard == []
    assert len(game.players[0].library) == before_library + 1
    assert game.players[0].library[0].name == "Island"
