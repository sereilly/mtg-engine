"""Web-API tests for *standing* reveals of hidden zones (CR 701.20a, CR 401.5).

`test_revealed_hand_ui_api.py` covers the in-progress reveals — a prompt one
player owes about another's hand. These cover the static ones: while a
"Players play with their hands revealed." permanent stands, every viewer's
payload carries the other seats' hand faces, and while a library-top reveal
stands, the top card rides the payload as `library_top` — for exactly the
seats the printed scope names, and only while the source is on the
battlefield.

LEG and M21 are measured, not shipped, so no deck can hold these cards — they
are placed into the session directly, which is what the cast-from-zone suite
does for the same reason.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_LEG = {c.name: c for c in load_cards(manifest_set_path("LEG", include_measured=True))}
_M21 = {c.name: c for c in load_cards(manifest_set_path("M21", include_measured=True))}


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 411,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return sid, store.get(sid).game


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _hand_names(state: dict, seat: int) -> list:
    return [
        card["name"] if isinstance(card, dict) else card
        for card in state["players"][seat]["hand"]
    ]


def test_an_opponents_hand_is_hidden_without_a_reveal():
    sid, game = _session()

    state = _state(sid, seat=0)
    assert set(_hand_names(state, 1)) == {"<hidden>"}
    assert state["players"][0]["library_top"] is None
    assert state["players"][1]["library_top"] is None


def test_revelation_shows_the_opponents_hand_and_leaves_with_the_permanent():
    sid, game = _session()
    revelation = Permanent(card=_LEG["Revelation"])
    game.players[0].battlefield.append(revelation)

    for viewer in (0, 1):
        state = _state(sid, seat=viewer)
        other = 1 - viewer
        real_names = [c.name for c in game.players[other].hand]
        assert _hand_names(state, other) == real_names, (
            "the reveal is symmetric: both seats see real card faces"
        )

    game.remove_from_battlefield(revelation)
    assert set(_hand_names(_state(sid, seat=0), 1)) == {"<hidden>"}


def test_field_of_dreams_puts_both_library_tops_on_the_wire():
    sid, game = _session()
    field = Permanent(card=_LEG["Field of Dreams"])
    game.players[1].battlefield.append(field)

    state = _state(sid, seat=0)
    for seat in (0, 1):
        top = state["players"][seat]["library_top"]
        assert top is not None
        assert top["name"] == game.players[seat].library[0].name

    # The hand stays hidden: the two reveals are separate effects.
    assert set(_hand_names(state, 1)) == {"<hidden>"}

    game.remove_from_battlefield(field)
    assert _state(sid, seat=0)["players"][1]["library_top"] is None


def test_an_own_scoped_top_reveal_shows_only_its_controllers_library():
    """Conspicuous Snoop's "Play with the top card of your library revealed."
    reaches one library, and the payload scopes with it — for every viewer,
    because revealed is revealed to all players (CR 701.20a)."""
    sid, game = _session()
    snoop = Permanent(card=_M21["Conspicuous Snoop"])
    game.players[0].battlefield.append(snoop)

    for viewer in (0, 1):
        state = _state(sid, seat=viewer)
        top = state["players"][0]["library_top"]
        assert top is not None
        assert top["name"] == game.players[0].library[0].name
        assert state["players"][1]["library_top"] is None
