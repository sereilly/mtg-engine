"""Aphetto Dredging through the wire: a creature type announced before the
targets it narrows (the card's 2004-10-04 ruling, CR 601.2b then 601.2c).

What the wave-2 client builds on:

* the hand card's ``target_spec`` says the cast announces a creature type
  (``announces_creature_type``, ``creature_types``, ``default_creature_type``)
  and which word its ``valid_targets`` were listed under
  (``chosen_creature_type`` — the default until the client asks again);
* ``build_card_target_spec(..., chosen_creature_type=…)`` — the
  ``card_target_spec`` route's body, with the route's new query parameter — is
  the re-ask once the type is picked, and lists that type's cards;
* ``{"action": "cast", "chosen_creature_type": …, "target_seat": 0,
  "target_permanent_indices": [...]}`` casts it, judged under the word sent.

The route itself looks the card up in the shipped catalog, which a measured
set is not in, so the card is registered there for the one test that goes
through it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.helpers import _mk_card
from web.app import app, store
from web.state_view import build_card_target_spec

client = TestClient(app)


def _yard_card(name, subtype):
    return _mk_card(
        name=name, mana_cost="{1}{B}", type_line=f"Creature - {subtype}",
        colors=("B",),
    )


@pytest.fixture
def table(set_pool):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "H", "host_colors": 2,
              "guest_colors": 2, "seed": 3},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.priority_player_index = 0
    p1 = game.players[0]
    p1.hand[:] = [set_pool("ONS")["Aphetto Dredging"]]
    p1.graveyard[:] = [
        _yard_card("Goblin A", "Goblin"), _yard_card("Elf A", "Elf"),
        _yard_card("Goblin B", "Goblin"), _yard_card("Elf B", "Elf"),
        _yard_card("Goblin C", "Goblin"),
    ]
    return sid, session, game


def _hand_spec(sid):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    (card,) = [c for c in state["players"][0]["hand"] if c["name"] == "Aphetto Dredging"]
    return card["target_spec"]


def test_the_hand_card_says_the_type_comes_first_and_lists_the_default(table):
    sid, _session, _game = table
    spec = _hand_spec(sid)
    assert spec["announces_creature_type"] is True
    assert "elf" in spec["creature_types"] and "goblin" in spec["creature_types"]
    assert spec["default_creature_type"] == "goblin"
    assert spec["chosen_creature_type"] == "goblin"
    assert [t["name"] for t in spec["valid_targets"]] == [
        "Goblin A", "Goblin B", "Goblin C",
    ]


def test_the_re_ask_lists_the_chosen_types_cards(table):
    _sid, session, game = table
    asked = build_card_target_spec(
        session, game.players[0].hand[0], 0, hand_index=0,
        chosen_creature_type="elf",
    )["target_spec"]
    assert asked["chosen_creature_type"] == "elf"
    assert [(t["seat"], t["index"], t["name"]) for t in asked["valid_targets"]] == [
        (0, 1, "Elf A"), (0, 3, "Elf B"),
    ]


def test_the_route_re_asks_with_the_type_as_a_query_parameter(table, monkeypatch):
    """The route's own lookup is the shipped catalog; the card is registered
    in it for this test, as the promotion will register it."""
    import web.runtime as runtime

    sid, _session, game = table
    card = game.players[0].hand[0]
    monkeypatch.setitem(runtime.CARD_BY_NAME, card.name.casefold(), card)
    response = client.get(
        f"/api/sessions/{sid}/card_target_spec",
        params={"card_name": "Aphetto Dredging", "seat": 0, "hand_index": 0,
                "chosen_creature_type": "elf"},
    )
    assert response.status_code == 200, response.text
    spec = response.json()["target_spec"]
    assert spec["chosen_creature_type"] == "elf"
    assert [t["name"] for t in spec["valid_targets"]] == ["Elf A", "Elf B"]


def test_a_cast_sent_with_the_type_returns_that_types_cards(table):
    sid, _session, game = table
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Aphetto Dredging",
        "chosen_creature_type": "elf",
        "target_seat": 0, "target_permanent_indices": [1, 3],
    })
    assert response.status_code == 200, response.text
    game.resolve_stack()
    assert sorted(c.name for c in game.players[0].hand) == ["Elf A", "Elf B"]


def test_a_cast_naming_a_card_of_another_type_is_refused(table):
    sid, _session, game = table
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Aphetto Dredging",
        "chosen_creature_type": "elf",
        "target_seat": 0, "target_permanent_indices": [0],
    })
    assert response.status_code == 400, response.text
    assert [c.name for c in game.players[0].hand] == ["Aphetto Dredging"]
