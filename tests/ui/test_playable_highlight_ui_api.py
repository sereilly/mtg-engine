"""What the board highlights as castable *right now*.

Two payload fields, one computation (``web/state_view.py``): a card in hand and
a commander in the command zone are asked the same question — timing, targets,
and whether the mana on the board could pay — and the client gives both the
same glow.

The command zone is the interesting half, because two different questions look
alike there. ``castable_from_zones`` says the zone is open at all (CR 903.8 is a
rule, so it is open for as long as the commander sits there);
``playable_command_indices`` says the cast could happen now, tax included.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store

client = TestClient(app)


def _commander_session() -> str:
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai",
        "host_name": "Host",
        "host_colors": 2,
        "guest_colors": 2,
        "seed": 9031,
        "variant": "commander",
        "host_deck_cards": [{"name": "Swamp", "count": 40}],
        "host_deck_commander": [{"name": "Kaervek, the Spiteful", "count": 1}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
        "guest_deck_commander": [{"name": "Azusa, Lost but Seeking", "count": 1}],
    })
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _on_priority(session_id: str):
    """Put seat 0 in its own precombat main phase holding priority — the window
    a cast can actually start in."""
    session = store.get(session_id)
    session.current_turn = 0
    session.game.active_player_index = 0
    session.game.start_priority_window(0)
    return session, session.game


def _state(session_id: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{session_id}/state", params={"seat": seat}).json()


def test_the_commander_is_not_highlighted_with_no_mana_on_the_board():
    session_id = _commander_session()
    _on_priority(session_id)

    state = _state(session_id)
    # Offered by the rule, but not castable yet: the two fields disagree, which
    # is exactly the distinction the highlight is for.
    assert [e["zone"] for e in state["castable_from_zones"]] == ["command"]
    assert state["players"][0]["playable_command_indices"] == []


def test_the_commander_is_highlighted_once_the_mana_is_there():
    session_id = _commander_session()
    _, game = _on_priority(session_id)
    # Kaervek, the Spiteful costs {2}{B}{B}.
    game.players[0].mana_pool.update({"B": 2, "C": 2})

    assert _state(session_id)["players"][0]["playable_command_indices"] == [0]


def test_untapped_lands_count_toward_the_commander_the_way_they_do_for_a_hand_card():
    session_id = _commander_session()
    _, game = _on_priority(session_id)
    swamp = next(card for card in game.players[0].library if card.name == "Swamp")
    # Four untapped Swamps and an empty pool: the highlight reads the mana the
    # board *could* make, which is what a player about to tap them is asking.
    for _ in range(4):
        game.players[0].battlefield.append(Permanent(card=swamp))

    assert _state(session_id)["players"][0]["playable_command_indices"] == [0]


def test_the_commander_tax_can_take_the_highlight_away():
    session_id = _commander_session()
    _, game = _on_priority(session_id)
    game.players[0].mana_pool.update({"B": 2, "C": 2})
    # CR 903.8: one previous cast from the command zone makes this one {2} more,
    # which the same board can no longer pay.
    game.players[0].commander_casts["Kaervek, the Spiteful"] = 1

    assert _state(session_id)["players"][0]["playable_command_indices"] == []

    game.players[0].mana_pool.update({"C": 4})
    assert _state(session_id)["players"][0]["playable_command_indices"] == [0]


def test_only_the_seat_that_owns_the_commander_is_told_it_is_castable():
    session_id = _commander_session()
    _, game = _on_priority(session_id)
    game.players[0].mana_pool.update({"B": 2, "C": 2})

    # A viewer in another seat reads the same field for seat 0 and gets nothing:
    # it is the viewer's own castability, like the hand's.
    assert _state(session_id, seat=1)["players"][0]["playable_command_indices"] == []


def test_the_hand_still_answers_through_the_same_computation():
    session_id = _commander_session()
    _, game = _on_priority(session_id)
    hand = game.players[0].hand

    # An all-Swamp opening hand on your own main phase: every card is playable,
    # and CR 305.2's one land per turn is what takes them all away again.
    assert _state(session_id)["players"][0]["playable_hand_indices"] == list(range(len(hand)))

    game.lands_played_this_turn[0] = 1
    assert _state(session_id)["players"][0]["playable_hand_indices"] == []
