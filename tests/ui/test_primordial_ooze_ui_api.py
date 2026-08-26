"""Web-API tests for Primordial Ooze's variable upkeep payment.

"Then you may pay {X}, where X is the number of +1/+1 counters on it."

The prompt is the ordinary ``optional_pay``, which is the point: an X in an
offered cost is a number read late, not a new kind of question. What only the
app can show is that the number reaches the seat being asked — the offer is
rendered from the entry's symbol dict, and a cost still carrying the string "x"
would render as a prompt nobody could price.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.pt import add_pt_counters
from web.app import app, store

client = TestClient(app)

_R31_CARDS = {
    c.name: c
    for path in manifest_set_paths(include_measured=True)
    for c in load_cards(path)
}


def _r31_ooze_session(counters: int = 2, lands: int = 4):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 311,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    ooze = Permanent(card=_R31_CARDS["Primordial Ooze"])
    if counters:
        add_pt_counters(ooze, "+1/+1", counters)
    game.players[0].battlefield = [ooze] + [
        Permanent(card=_R31_CARDS["Mountain"]) for _ in range(lands)
    ]
    session.current_turn = 0
    game.start_turn(0)
    game._settle()
    return sid, game, ooze


def test_the_offer_reaches_the_seat_priced_in_mana():
    sid, _game, ooze = _r31_ooze_session()

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    offers = state["optional_pay"]["pending"]
    assert len(offers) == 1
    assert offers[0]["card_name"] == "Primordial Ooze"
    assert offers[0]["prompt"] == "Pay {3}?"
    assert offers[0]["cost"] == {"generic": 3}


def test_declining_through_the_api_taps_it_and_burns_its_controller():
    sid, game, ooze = _r31_ooze_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "resolve_optional_pay", "accept": False},
    )
    assert resp.status_code == 200, resp.text

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert state["optional_pay"] is None, "the offer is gone once it is answered"
    assert state["players"][0]["life"] == 17
    face = next(
        p for p in state["players"][0]["battlefield"] if p["name"] == "Primordial Ooze"
    )
    assert face["tapped"] is True


def test_paying_through_the_api_spends_the_lands():
    sid, game, ooze = _r31_ooze_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "resolve_optional_pay", "accept": True},
    )
    assert resp.status_code == 200, resp.text

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert state["players"][0]["life"] == 20
    untapped = [
        p for p in state["players"][0]["battlefield"]
        if p["name"] == "Mountain" and not p["tapped"]
    ]
    assert len(untapped) == 1
