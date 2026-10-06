"""The secret-number prompt over the wire (W2G1, Goblin Game).

"Each player hides at least one item, then all players reveal them
simultaneously." Driven through the real action and state endpoints with two
human seats, because the thing under test is what each seat is *sent*: a seat
must not learn another seat's number before it has committed its own, and the
only way to hold that is to serialise the state for every viewer between the
answers and look for the number.

The sentinels are numbers nothing else in a fresh session's payload could be —
a life total, a permanent id, a turn or an option on a prompt's own button
list — so a hit is the secret and not a coincidence.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from web.app import app, store

client = TestClient(app)

#: What seat 0 and seat 1 name. Far above either life total (the engine accepts
#: it: the card prints no ceiling and the number is a loss), and with no digit
#: run a 20-life game's payload would otherwise contain.
SEAT_0_SECRET = 7391
SEAT_1_SECRET = 8462


def _session(set_pool, mode="human_vs_human", lives=(20, 20)):
    response = client.post("/api/sessions", json={
        "mode": mode, "host_name": "W2G1-Host", "guest_name": "W2G1-Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 2103,
        "host_deck_cards": [{"name": "Forest", "count": 40}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
    })
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    if mode == "human_vs_human":
        joined = client.post(
            f"/api/sessions/{session_id}/join", json={"guest_name": "W2G1-Guest"}
        )
        assert joined.status_code == 200, joined.text
    session = store.get(session_id)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.enforce_mana_costs = False
    for player, life in zip(game.players, lives):
        player.life = life
        player.hand[:] = []
    game.players[0].hand[:] = [set_pool("PLS")["Goblin Game"]]
    game.start_priority_window(0)
    return session_id, game


def _act(session_id, seat, **body):
    return client.post(
        f"/api/sessions/{session_id}/action", json={"seat": seat, **body}
    )


def _state(session_id, seat=None):
    params = {} if seat is None else {"seat": seat}
    response = client.get(f"/api/sessions/{session_id}/state", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _cast_and_resolve_to_the_prompts(session_id):
    assert _act(session_id, 0, action="cast", card_name="Goblin Game").status_code == 200
    assert _act(session_id, 0, action="pass_priority").status_code == 200
    assert _act(session_id, 1, action="pass_priority").status_code == 200


def test_w2g1_each_seat_is_sent_its_own_prompt_and_nothing_else(set_pool):
    """Both seats owe the prompt at once. Each is sent its own — the floor,
    its own life total, a button per number up to it — and a seatless viewer
    is sent none."""
    session_id, _game = _session(set_pool, lives=(20, 12))
    _cast_and_resolve_to_the_prompts(session_id)

    for seat, life in ((0, 20), (1, 12)):
        prompt = _state(session_id, seat)["secret_number"]
        assert prompt == {
            "player_seat": seat, "card_name": "Goblin Game",
            "minimum": 1, "maximum": None, "life": life,
            "options": list(range(1, life + 1)),
        }
    assert _state(session_id)["secret_number"] is None


def test_w2g1_no_seat_is_sent_anothers_number_before_the_reveal(set_pool):
    """The card. Seat 0 commits; then the whole state is serialised for seat
    1, for a spectator and for seat 0 itself, and seat 0's number is in none of
    them — not in the log, not in any prompt, not on the stack item. Seat 1 is
    still sent the same prompt it was sent before anybody answered. Then seat 1
    commits and the reveal is one log line every viewer gets."""
    session_id, game = _session(set_pool)
    _cast_and_resolve_to_the_prompts(session_id)
    seat_1_before = _state(session_id, 1)["secret_number"]
    log_before = list(game.log)

    assert _act(
        session_id, 0, action="secret_number_confirm", number=SEAT_0_SECRET,
    ).status_code == 200

    for viewer in (1, None, 0):
        sent = json.dumps(_state(session_id, viewer))
        assert str(SEAT_0_SECRET) not in sent, f"leaked to viewer {viewer!r}"
    assert _state(session_id, 1)["secret_number"] == seat_1_before
    assert _state(session_id, 0)["secret_number"] is None
    assert game.log == log_before, "an answer logs nothing until the last"
    assert [player.life for player in game.players] == [20, 20]
    assert game.stack, "the spell is still resolving"

    assert _act(
        session_id, 1, action="secret_number_confirm", number=SEAT_1_SECRET,
    ).status_code == 200
    reveal = (
        f"Goblin Game: W2G1-Host revealed {SEAT_0_SECRET}, "
        f"W2G1-Guest revealed {SEAT_1_SECRET}"
    )
    for viewer in (0, 1, None):
        state = _state(session_id, viewer)
        assert reveal in state["log"]
        assert state["secret_number"] is None
    # Each lost its own number; seat 0 revealed the fewest, and halving a
    # negative life total halves 0 (the card's ruling).
    assert [player.life for player in game.players] == [
        20 - SEAT_0_SECRET, 20 - SEAT_1_SECRET,
    ]
    assert "Goblin Game: W2G1-Host revealed the fewest" in game.log


def test_w2g1_an_illegal_number_is_a_400_and_the_prompt_stays_owed(set_pool):
    """"At least one item": zero is refused with a 400 and nothing is
    recorded; a missing number is a 400; and a seat that has already answered
    — or never owed the prompt — cannot answer again."""
    session_id, game = _session(set_pool)
    _cast_and_resolve_to_the_prompts(session_id)

    zero = _act(session_id, 0, action="secret_number_confirm", number=0)
    assert zero.status_code == 400
    assert "below the least" in zero.json()["detail"]
    assert _act(session_id, 0, action="secret_number_confirm").status_code == 400
    assert _state(session_id, 0)["secret_number"] is not None
    assert [c.player_index for c in game.pending_choices_of("secret_number")] == [0, 1]

    assert _act(session_id, 0, action="secret_number_confirm", number=3).status_code == 200
    again = _act(session_id, 0, action="secret_number_confirm", number=9)
    assert again.status_code == 400
    assert "no hidden number is pending" in again.json()["detail"]
    assert [c.player_index for c in game.pending_choices_of("secret_number")] == [1]


def test_w2g1_a_seat_that_has_answered_may_not_act_until_every_seat_has(set_pool):
    """The spell is mid-resolution and nobody has priority (CR 608.2,
    CR 117.3b): the seat that committed first is refused every other action —
    by the prompt's own message — until the other seat commits too."""
    session_id, game = _session(set_pool)
    _cast_and_resolve_to_the_prompts(session_id)
    assert _act(session_id, 0, action="secret_number_confirm", number=2).status_code == 200

    blocked = _act(session_id, 0, action="pass_priority")
    assert blocked.status_code == 400
    assert "hidden number" in blocked.json()["detail"]
    assert game.stack

    assert _act(session_id, 1, action="secret_number_confirm", number=5).status_code == 200
    assert not game.stack
    # 18 -> the fewest -> lose 9 -> 9; 15.
    assert [player.life for player in game.players] == [9, 15]
    assert _act(session_id, 0, action="pass_priority").status_code == 200


def test_w2g1_an_ai_seat_commits_unseen_and_the_human_is_still_asked(set_pool):
    """Against an AI: its number is taken as the prompt is armed, the human
    is sent a prompt and no hint of it, and the reveal names both when the
    human answers. The AI's answer is the policy's over level life totals — the
    floor."""
    session_id, game = _session(set_pool, mode="human_vs_ai")
    assert _act(session_id, 0, action="cast", card_name="Goblin Game").status_code == 200
    assert _act(session_id, 0, action="pass_priority").status_code == 200

    state = _state(session_id, 0)
    assert state["secret_number"]["player_seat"] == 0
    assert not any("revealed" in line for line in state["log"])
    assert [c.player_index for c in game.pending_choices_of("secret_number")] == [0]

    assert _act(session_id, 0, action="secret_number_confirm", number=4).status_code == 200
    assert any(
        line.startswith("Goblin Game: W2G1-Host revealed 4, ")
        and line.endswith(" revealed 1")
        for line in game.log
    )
    # 16 | 19 -> the fewest -> lose 10 -> 9.
    assert [player.life for player in game.players] == [16, 9]
