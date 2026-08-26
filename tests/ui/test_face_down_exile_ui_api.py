"""Web-API tests for a card exiled **face down** (CR 406.3, Knowledge Vault).

Exile is a public zone, so its payload normally carries every card's face. A
card put there face down is hidden from every player — its owner included,
since Knowledge Vault's ``{2}, {T}`` says nothing about looking — and reaches
the client as the same ``"<hidden>"`` placeholder a concealed hand uses.

LEG is measured, not shipped, so no deck can hold the Vault: it is placed into
the session directly, which is what the revealed-zones suite does for the same
reason.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_LEG = {c.name: c for c in load_cards(manifest_set_path("LEG", include_measured=True))}


def _r30_session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 30,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return sid, store.get(sid).game


def _r30_exile_payload(sid: str, viewer: int, seat: int) -> list:
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": viewer}).json()
    return [
        card["name"] if isinstance(card, dict) else card
        for card in state["players"][seat]["exile"]
    ]


def test_a_face_down_exiled_card_is_hidden_from_everyone():
    sid, game = _r30_session()
    vault = Permanent(card=_LEG["Knowledge Vault"])
    game.players[0].battlefield.append(vault)
    game.players[0].library.insert(0, _LEG["Nova Pentacle"])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(
        0, "Knowledge Vault",
        permanent_index=game.players[0].battlefield.index(vault),
        ability_index=0,
    )
    game._settle()

    assert [c.name for c in game.players[0].exile] == ["Nova Pentacle"]
    assert _r30_exile_payload(sid, 0, 0) == ["<hidden>"], "hidden from its owner"
    assert _r30_exile_payload(sid, 1, 0) == ["<hidden>"], "hidden from the opponent"


def test_a_face_up_exiled_card_still_shows():
    """The hiding is per exiling, not per zone: a card that reached exile any
    other way keeps its face, on the same board."""
    sid, game = _r30_session()
    game.players[0].exile.append(_LEG["Alchor's Tomb"])

    assert _r30_exile_payload(sid, 1, 0) == ["Alchor's Tomb"]
