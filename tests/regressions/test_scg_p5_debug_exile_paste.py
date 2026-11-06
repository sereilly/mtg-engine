"""The Debug Menu's raw-state paste puts exiled cards through the arrival seam
(SCG Phase 5, found at the engine closer's merge).

No exile holds one object twice (``Game.put_card_into_exile``, CR 400.7): every
record about an exiled card names its object, so two exiled copies sharing one
object are told apart by nothing. The paste rebuilt each pile from card names,
and a name is the catalog's one object, so a paste naming two Mountains in
exile made the very shape the closer removed. The verification agent sets
boards up through that paste, so a re-check could have watched the defect
come back through the Debug Menu rather than through play.
"""
from __future__ import annotations

from tests.helpers import client


def _session() -> str:
    lands = [{"name": "Mountain", "count": 40}]
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_deck_cards": lands, "guest_deck_cards": lands, "seed": 3,
    })
    assert created.status_code == 200, created.text
    return created.json()["session_id"]


def test_a_pasted_exile_naming_one_card_twice_holds_two_objects():
    from web.app import store

    sid = _session()
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    state["players"][0]["exile"] = [{"name": "Mountain"}, {"name": "Mountain"}]
    state["players"][1]["exile"] = [{"name": "Mountain"}]
    pasted = client.post(f"/api/sessions/{sid}/raw-state", json={"state": state, "seat": 0})
    assert pasted.status_code == 200, pasted.text

    game = store.get(sid).game
    exiled = game.players[0].exile + game.players[1].exile
    assert [card.name for card in exiled] == ["Mountain"] * 3
    assert len({id(card) for card in exiled}) == 3, "two exiled copies share one object"
