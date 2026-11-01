"""A morph cast's timing is judged as the face-down spell (CR 702.37c, 708.4).

The cast route asked ``casts_at_instant_speed`` of the hand card whatever the
cast announced, so under Quick Sliver ("Any player may cast Sliver spells as
though they had flash") a Sliver cast **face down** — a 2/2 with no creature
types (CR 708.2) — was flashable. No printed Sliver has morph, so the card
here is invented; the gate is ``face_down.cast_timing_card``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_timing import casts_at_instant_speed
from engine.face_down import cast_timing_card, is_face_down_card
from engine.models import CardDefinition, Permanent
from web.app import app, store

client = TestClient(app)

_W2G3_CARDS = {
    c.name: c
    for path in manifest_set_paths(include_measured=True)
    for c in load_cards(path)
}

#: Nobody printed this: a Sliver with morph.
_VEILED_SLIVER = CardDefinition(
    name="Veiled Sliver", mana_cost="{3}{G}", cmc=4.0,
    type_line="Creature — Sliver", oracle_text="Morph {2}{G}",
    colors=("G",), color_identity=("G",), keywords=("Morph",), produced_mana=(),
    raw={"name": "Veiled Sliver", "type_line": "Creature — Sliver",
         "power": "3", "toughness": "3"},
)


def _w2g3_session():
    """Seat 0's turn with Quick Sliver out; seat 1 holds the invented Sliver
    and has priority in seat 0's main phase."""
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 44,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.players[0].battlefield = [Permanent(card=_W2G3_CARDS["Quick Sliver"])]
    game.players[1].battlefield = []
    game.players[1].hand = [_VEILED_SLIVER]
    game._sync_control()
    session.current_turn = 0
    game.active_player_index = 0
    game.start_priority_window(1)
    return sid, game


def test_the_face_down_spell_has_no_sliver_type_to_borrow_flash_from():
    _sid, game = _w2g3_session()
    assert casts_at_instant_speed(_VEILED_SLIVER, game, 1), "face up, Quick Sliver covers it"
    timed = cast_timing_card(game, 1, _VEILED_SLIVER, alternative_cost=True)
    assert is_face_down_card(timed)
    assert not casts_at_instant_speed(timed, game, 1)
    assert cast_timing_card(game, 1, _VEILED_SLIVER, alternative_cost=False) is _VEILED_SLIVER


def test_a_face_down_cast_on_another_players_turn_is_refused():
    sid, game = _w2g3_session()
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "cast", "card_name": "Veiled Sliver",
              "alternative_cost": True},
    )
    assert resp.status_code == 400, resp.text
    assert "on your turn" in resp.json()["detail"]
    assert [c.name for c in game.players[1].hand] == ["Veiled Sliver"]
    assert not game.stack


def test_the_same_card_cast_face_up_is_flashed_in():
    sid, game = _w2g3_session()
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "cast", "card_name": "Veiled Sliver"},
    )
    assert resp.status_code == 200, resp.text
    assert game.players[1].hand == []
