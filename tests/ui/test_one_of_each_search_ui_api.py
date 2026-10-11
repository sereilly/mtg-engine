"""Web-API tests for a search that finds one card per printed description.

Guided Passage's shape, armed directly because a measured set's card cannot be
put in a web deck: an **opponent** chooses, out of the caster's library, a
creature card, a land card and a noncreature, nonland card, and the cards go to
the library owner's hand. What the client is sent and what the wire accepts are
pinned here; the engine half is `tests/engine/test_search_one_of_each.py`.

The dialog itself is not exercised (the board is not touched in this wave), so
what these hold is the contract a dialog needs: the prompt reaches the seat
that chooses and nobody else, the cards it shows are the *other* seat's
library, the per-find descriptions ride beside the union `legal_indices` is,
and an answer that is not one card per description is a 400 with nothing moved.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from web.app import app, store
from tests.helpers import LEA_PATH

client = TestClient(app)

_CARDS = {c.name: c for c in load_cards(LEA_PATH)}
_LIBRARY = ["Forest", "Hill Giant", "Grizzly Bears", "Sol Ring", "Clockwork Beast"]
_DESCRIBED = [
    {"card_type": "creature"},
    {"card_type": "land"},
    {"exclude_types": ["creature", "land"]},
]


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
    game.players[0].hand = []
    game.players[1].hand = []
    game.players[0].library = [_CARDS[name] for name in _LIBRARY]
    session.current_turn = 0
    game.active_player_index = 0
    game.arm_pending_choice(
        "search_library", 1,
        zone_seat=0, count=3, card_type="any", zones=("library",),
        restrictions={"one_of_each": [dict(slot) for slot in _DESCRIBED]},
        destination="hand", destinations=["hand"] * 3, tapped=[False] * 3,
        card_name="Guided Passage",
    )
    return sid, session, game


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _confirm(sid: str, seat: int, *indices: int):
    return client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": seat,
            "action": "search_library_confirm",
            "search_picks": [{"zone": "library", "index": i} for i in indices],
        },
    )


def test_the_choosing_seat_is_shown_the_other_seats_library_and_the_descriptions():
    sid, _session_obj, _game = _session()

    prompt = _state(sid, 1)["search_library"]
    assert prompt is not None
    assert prompt["caster_seat"] == 1
    assert [card["name"] for card in prompt["cards"]] == _LIBRARY
    assert prompt["legal_indices"] == [0, 1, 2, 3, 4], "every card fills some description"
    assert prompt["multi"] is True and prompt["max_picks"] == 3
    assert prompt["up_to"] is False, "nothing here is optional"
    assert prompt["one_of_each"] == _DESCRIBED

    assert _state(sid, 0)["search_library"] is None, "the library's owner is not asked"


def test_an_answer_that_is_not_one_card_per_description_is_refused():
    sid, _session_obj, game = _session()

    for indices in ((1, 2, 0), (1, 0), (4, 0, 2)):
        refused = _confirm(sid, 1, *indices)
        assert refused.status_code == 400, indices
    assert _confirm(sid, 0, 1, 0, 3).status_code == 400, "not the owner's to answer"
    assert [card.name for card in game.players[0].library] == _LIBRARY
    assert _state(sid, 1)["search_library"] is not None, "still owed"


def test_the_answer_lands_in_the_library_owners_hand():
    sid, _session_obj, game = _session()

    accepted = _confirm(sid, 1, 4, 0, 3)
    assert accepted.status_code == 200, accepted.text

    assert [card.name for card in game.players[0].hand] == [
        "Clockwork Beast", "Forest", "Sol Ring",
    ]
    assert game.players[1].hand == []
    assert sorted(card.name for card in game.players[0].library) == [
        "Grizzly Bears", "Hill Giant",
    ]
    assert _state(sid, 1)["search_library"] is None
