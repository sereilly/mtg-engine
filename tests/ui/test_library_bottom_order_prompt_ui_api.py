"""The bottom-of-library order, through the wire a browser uses.

"…and the rest on the bottom of your library in any order" (Goblin Ringleader
and Apocalypse's six other recruiters) arms the ``reorder_library`` prompt
pointed at the library's *other end* (``Game.offer_library_bottom_order``,
CR 401.4). The engine half is ``tests/engine/test_sorted_reveal_bottom.py``.
This is the half a player sees: the cards the state payload shows are the ones
that went down, the answer the client already sends for a top-of-library
reorder (``reorder_library_confirm`` + ``card_order``) arranges them, and the
game does not move on while the question is open.

Armed directly on the session's game rather than by casting a recruiter: the
web app's catalog is the *shipped* pool, and Apocalypse is a measured set
until it is promoted. The prompt is the same object either way.
"""

from __future__ import annotations

from web.app import store
from tests.helpers import _mk_card, client


def _session_with_bottom_order(names, count):
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
    game.interactive_seats = {0, 1}
    game.players[0].library = [
        _mk_card(name=name, type_line="Artifact") for name in names
    ]
    assert game.offer_library_bottom_order(game.players[0], count)
    return sid, session


def _state(sid, seat):
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_owner_is_shown_the_cards_that_went_to_the_bottom():
    sid, _ = _session_with_bottom_order(["A", "B", "C", "D", "E"], 3)

    prompt = _state(sid, 0)["reorder_library"]

    assert prompt is not None
    assert prompt["position"] == "bottom"
    assert prompt["caster_seat"] == 0 and prompt["target_seat"] == 0
    assert prompt["top_count"] == 3 and prompt["may_shuffle"] is False
    assert [card["name"] for card in prompt["cards"]] == ["C", "D", "E"]


def test_the_other_seat_is_not_shown_the_order_being_chosen():
    """CR 401.4: "That library's owner doesn't reveal the order in which the
    cards go into the library." The prompt is the owner's alone."""
    sid, _ = _session_with_bottom_order(["A", "B", "C", "D", "E"], 3)

    assert _state(sid, 1)["reorder_library"] is None


def test_the_client_s_existing_answer_arranges_the_bottom_and_nothing_else():
    sid, session = _session_with_bottom_order(["A", "B", "C", "D", "E"], 3)

    refused = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "reorder_library_confirm", "card_order": [0, 1]},
    )
    assert refused.status_code == 400

    answered = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "reorder_library_confirm", "card_order": [1, 2, 0]},
    )
    assert answered.status_code == 200, answered.text

    assert [c.name for c in session.game.players[0].library] == ["A", "B", "D", "E", "C"]
    assert _state(sid, 0)["reorder_library"] is None


def test_nothing_else_may_be_done_while_the_order_is_owed():
    sid, session = _session_with_bottom_order(["A", "B", "C"], 2)

    for seat in (0, 1):
        blocked = client.post(
            f"/api/sessions/{sid}/action", json={"seat": seat, "action": "pass_priority"},
        )
        assert blocked.status_code == 400, blocked.text
    assert session.game.pending_reorder_library is not None


def test_a_top_of_library_reorder_says_which_end_it_is():
    """The same prompt armed the way every look-and-put-back arms it reports
    ``position: "top"`` and the top cards — so a client that labels the modal
    by this field is right for both."""
    sid, session = _session_with_bottom_order(["A", "B", "C", "D"], 2)
    game = session.game
    game.pending_choices.clear()
    game.arm_pending_choice(
        "reorder_library", 0, target_index=0, top_count=3, may_shuffle=False,
    )

    prompt = _state(sid, 0)["reorder_library"]

    assert prompt["position"] == "top"
    assert [card["name"] for card in prompt["cards"]] == ["A", "B", "C"]
