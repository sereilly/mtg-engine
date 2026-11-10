"""A discard paid as a cost at resolution, as a person is served it.

"Target player discards two cards unless they discard an artifact card"
(Wrench Mind): the artifact discard is a cost (CR 118.12a), so the person
taking the offer is not shown Library of Leng's library top for it ("costs
aren't effects", the Library's 2004-10-04 ruling), and the Dodecapod they pay
with goes to their graveyard — no opponent's spell *caused* the discard
(``tests/regressions/test_kg5_costs_resolution_discard_costs.py`` is the
engine's half). On e245e624c the prompt offered the top, and Dodecapod
entered the battlefield.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_SHIPPED = {card.name: card for card in load_catalog()}


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4246,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    for player in game.players:
        player.battlefield = []
    session.current_turn = 1
    game.active_player_index = 1
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(1)
    return sid, game


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def test_the_artifact_discard_wrench_mind_offers_is_served_without_the_library_top():
    sid, game = _session()
    leng = Permanent(card=_SHIPPED["Library of Leng"])
    game._put_permanent_onto_battlefield(0, leng, None)
    game.pending_choices.clear()
    game.players[0].hand = [_SHIPPED["Dodecapod"], _SHIPPED["Hill Giant"]]
    game.players[0].library = [_SHIPPED["Island"]] * 3
    game.players[1].hand.append(_SHIPPED["Wrench Mind"])

    cast = _act(sid, seat=1, action="cast", card_name="Wrench Mind", target_seat=0)
    assert cast.status_code == 200, cast.text
    for seat in (1, 0):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 200

    accepted = _act(sid, seat=0, action="resolve_optional_pay", accept=True)
    assert accepted.status_code == 200, accepted.text
    prompt = _state(sid)["discard_select"]
    assert prompt is not None, "the artifact discard was never asked"
    assert prompt["count"] == 1
    assert prompt["allow_top_of_library"] is False

    paid = _act(sid, seat=0, action="discard_confirm", discard_indices=[0], to_library=True)
    assert paid.status_code == 200, paid.text
    assert [card.name for card in game.players[0].graveyard] == ["Dodecapod"]
    assert [card.name for card in game.players[0].hand] == ["Hill Giant"]
    assert [card.name for card in game.players[0].library] == ["Island"] * 3
    assert not any(p.card.name == "Dodecapod" for p in game.all_permanents())
