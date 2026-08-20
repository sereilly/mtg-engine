"""Web-API tests for a spell that stops mid-resolution to ask its controller.

A search, a scry and a library reorder suspend the resolution they are part of
(``ChoiceSpec.suspends``), so the spell is *still resolving* while the prompt is
open: it has left the stack, it is out of hand, and CR 608.2n's move to the
graveyard is behind the answer. That is a state the client can observe, and
these pin what it sees — the prompt rendered, the actions around it refused, and
the resolution finishing the whole way through on confirm.

Demonic Tutor because it is the shipped card with the shape; the mechanism is
the same for every kind registered ``suspends``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from web.app import app, store
from tests.helpers import LEA_PATH

client = TestClient(app)

_CARDS = {c.name: c for c in load_cards(LEA_PATH)}


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 909,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].hand = [_CARDS["Demonic Tutor"]]
    game.players[0].library = [_CARDS["Black Lotus"], _CARDS["Swamp"], _CARDS["Swamp"]]
    session.current_turn = 0
    game.active_player_index = 0
    game.cast_from_hand(0, "Demonic Tutor", target_player_index=1)
    return sid, session, game


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def test_the_prompt_is_rendered_while_the_spell_is_still_resolving():
    sid, session, game = _session()

    state = _state(sid)
    assert state["search_library"] is not None
    assert not game.stack, "the spell has left the stack"
    assert not any(c.name == "Demonic Tutor" for c in game.players[0].hand)
    assert not any(c.name == "Demonic Tutor" for c in game.players[0].graveyard), (
        "the card reaches the graveyard as the last part of resolution (CR 608.2n), "
        "which is behind this prompt"
    )


def test_the_owing_seat_cannot_act_around_the_open_prompt():
    sid, session, game = _session()

    refused = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"}
    )
    assert refused.status_code == 400
    assert "library search" in refused.json()["detail"]


def test_declining_is_a_legal_answer_and_finishes_the_resolution():
    """"Fail to find" (CR 701.19b) answers the prompt rather than acting around
    it, so the gate must let it through — ``search_library_decline`` shipped
    registered but unreachable, every attempt refused with the search prompt's
    own blocked_detail, which stranded the seat whenever nothing in the library
    matched the restriction."""
    sid, session, game = _session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "search_library_decline"},
    )
    assert resp.status_code == 200, resp.text

    assert not any(c.name == "Black Lotus" for c in game.players[0].hand), (
        "declining finds nothing"
    )
    assert any(c.name == "Demonic Tutor" for c in game.players[0].graveyard), (
        "and the suspended tail of the resolution still ran"
    )
    assert _state(sid)["search_library"] is None
    assert game.resume_stack == [] and not game.effect_suspended


def test_confirming_finishes_the_whole_resolution():
    sid, session, game = _session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        # The wire spells the chosen library slot `hand_index` — one card-index
        # field shared by every picker.
        json={"seat": 0, "action": "search_library_confirm", "hand_index": 0},
    )
    assert resp.status_code == 200, resp.text

    assert any(c.name == "Black Lotus" for c in game.players[0].hand), "the search found"
    assert any(c.name == "Demonic Tutor" for c in game.players[0].graveyard), (
        "and the suspended tail of the resolution ran"
    )
    assert _state(sid)["search_library"] is None
    assert game.resume_stack == [] and not game.effect_suspended
