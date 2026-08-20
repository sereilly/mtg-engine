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


# --- The counted search: every find in one answer, then where each goes ------
#
# Cultivate's shape ("up to two basic land cards … put one onto the battlefield
# tapped and the other into your hand"), armed directly so the wire is what is
# under test; the engine flow has its own tests beside the card.


def _counted_session():
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
    game.players[0].library = [_CARDS["Forest"], _CARDS["Black Lotus"], _CARDS["Island"]]
    session.current_turn = 0
    game.active_player_index = 0
    game.arm_pending_choice(
        "search_library", 0,
        count=2, card_type="land", zones=("library",),
        restrictions={"supertypes": ["basic"]},
        destination="hand",
        destinations=["battlefield", "hand"], tapped=[True, False],
        enters_tapped=False, untap_found_if=None, up_to=True, reveal=True,
        card_name="Cultivate",
    )
    return sid, session, game


def test_a_counted_search_renders_multi_and_confirms_whole():
    sid, session, game = _counted_session()

    prompt = _state(sid)["search_library"]
    assert prompt["multi"] is True
    assert prompt["max_picks"] == 2
    assert prompt["destinations"] == ["battlefield", "hand"]
    assert prompt["legal_indices"] == [0, 2], "the Lotus is not a basic land"

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "search_library_confirm",
            "search_picks": [
                {"zone": "library", "index": 0},
                {"zone": "library", "index": 2},
            ],
        },
    )
    assert resp.status_code == 200, resp.text

    # The search is over; where each find lands is the next prompt.
    state = _state(sid)
    assert state["search_library"] is None
    followup = state["search_destination"]
    assert followup is not None
    assert followup["caster_seat"] == 0
    assert [card["name"] for card in followup["cards"]] == ["Forest", "Island"]
    assert followup["slots"] == [
        {"destination": "battlefield", "tapped": True},
        {"destination": "hand", "tapped": False},
    ]

    # The owing seat cannot act around the destination question.
    refused = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"}
    )
    assert refused.status_code == 400
    assert "found card" in refused.json()["detail"]

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "search_destination_confirm", "search_assignments": [1, 0]},
    )
    assert resp.status_code == 200, resp.text

    assert [(p.card.name, p.tapped) for p in game.controlled_by(0)] == [("Island", True)]
    assert [c.name for c in game.players[0].hand] == ["Forest"]
    assert _state(sid)["search_destination"] is None
    assert game.resume_stack == [] and not game.effect_suspended


def test_a_counted_search_refuses_the_single_find_answer():
    sid, session, game = _counted_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "search_library_confirm", "hand_index": 0},
    )
    assert resp.status_code == 400
    assert len(game.players[0].library) == 3, "nothing moved on a refused answer"


def test_a_doubled_slot_is_a_refused_assignment():
    sid, session, game = _counted_session()
    client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "search_library_confirm",
            "search_picks": [
                {"zone": "library", "index": 0},
                {"zone": "library", "index": 2},
            ],
        },
    )

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "search_destination_confirm", "search_assignments": [0, 0]},
    )
    assert resp.status_code == 400
    assert _state(sid)["search_destination"] is not None, "still owed"
