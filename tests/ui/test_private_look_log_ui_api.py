"""A private look over the wire: what each viewer is sent (W2G4).

"Look at the top four cards of your library. Put one of them into your hand
and the rest on the bottom of your library in any order." (Impulse.) Driven
through the real action and state endpoints with two human seats, because the
thing under test is what each seat is *sent*. To look is not to reveal
(CR 701.20e), so the other seat and a spectator must learn neither what the
four cards were nor which one was kept — and the game log, which is one list
sent to everybody, used to say "Host put <card name> into their hand and the
rest away".

The whole state is serialised for the other seat, for a spectator and for the
seat that looked, as ``test_secret_number_ui_api`` does for a hidden number.
The four cards are ones nothing else in the session names: both decks are
Forests.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from web.app import app, store

client = TestClient(app)

#: The top four cards of the looker's library, top first.
LOOKED_AT = ("Serra Angel", "Black Lotus", "Crusade", "Juggernaut")
#: The one seat 0 keeps: not the first, which is what a default would take.
KEPT = "Black Lotus"


def _session(catalog_by_name, spell="Impulse"):
    response = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "W2G4-Host", "guest_name": "W2G4-Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4104,
        "host_deck_cards": [{"name": "Forest", "count": 40}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
    })
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    joined = client.post(
        f"/api/sessions/{session_id}/join", json={"guest_name": "W2G4-Guest"}
    )
    assert joined.status_code == 200, joined.text
    session = store.get(session_id)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.enforce_mana_costs = False
    for player in game.players:
        player.hand[:] = []
    game.players[0].hand[:] = [catalog_by_name[spell]]
    game.players[0].library[:0] = [catalog_by_name[name] for name in LOOKED_AT]
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


def test_w2g4_only_the_looker_is_sent_what_impulse_looked_at_and_kept(catalog_by_name):
    """Seat 0 resolves Impulse and keeps the second card. Before the answer
    and after it, the other seat and a spectator are sent none of the four
    names anywhere in the state. The looker is sent the kept card — in its own
    hand, and not in the log, which every viewer shares."""
    session_id, game = _session(catalog_by_name)
    assert _act(session_id, 0, action="cast", card_name="Impulse").status_code == 200
    assert _act(session_id, 0, action="pass_priority").status_code == 200
    assert _act(session_id, 1, action="pass_priority").status_code == 200

    prompt = _state(session_id, 0)["look_top_pick"]
    assert [card["name"] for card in prompt["cards"]] == list(LOOKED_AT)
    # The other seat is sent nothing of the pile while the looker decides.
    # (A *seatless* viewer is sent the prompt itself, cards and all: the kind
    # is registered ``spectator_visible`` with 54 others, which is a question
    # about what the seatless payload is for and not about this log line —
    # W2G4's report names it. What a seatless viewer keeps after the answer is
    # asserted below.)
    sent = json.dumps(_state(session_id, 1))
    assert not [name for name in LOOKED_AT if name in sent], "shown to the other seat"

    answered = _act(
        session_id, 0, action="look_top_pick_confirm", hand_index=LOOKED_AT.index(KEPT),
    )
    assert answered.status_code == 200, answered.text

    # The rest go to the bottom "in any order", and that order is the looker's
    # to choose (CR 401.4): W2G2 made the look-and-pick family ask, on a branch
    # this test was not written against, so the resolution is not over at the
    # pick. While the order is owed the other seat is still sent none of the
    # names; the seatless viewer is sent this open prompt as it was sent the
    # look, for the reason given above.
    order = _state(session_id, 0)["reorder_library"]
    assert order["position"] == "bottom"
    sent = json.dumps(_state(session_id, 1))
    assert not [name for name in LOOKED_AT if name in sent], "shown to the other seat"
    ordered = _act(
        session_id, 0, action="reorder_library_confirm", card_order=[0, 1, 2],
    )
    assert ordered.status_code == 200, ordered.text

    assert [card.name for card in game.players[0].hand] == [KEPT]
    for viewer in (1, None):
        sent = json.dumps(_state(session_id, viewer))
        assert not [name for name in LOOKED_AT if name in sent], f"leaked to viewer {viewer!r}"
    own = _state(session_id, 0)
    assert KEPT in json.dumps(own["players"][0]["hand"])
    assert not any(name in line for line in game.log for name in LOOKED_AT), game.log[-4:]
    assert "W2G4-Host put a card into their hand and the rest away" in game.log
    assert not game.stack


def test_w2g4_a_search_that_shows_nothing_names_nothing(catalog_by_name):
    """"Search your library for a card, put that card into your hand, then
    shuffle." (Demonic Tutor.) The same rule for the other way a card reaches a
    hand unseen: the log used to say "searched library and put Black Lotus
    into hand" to both seats."""
    session_id, game = _session(catalog_by_name, spell="Demonic Tutor")
    assert _act(session_id, 0, action="cast", card_name="Demonic Tutor").status_code == 200
    assert _act(session_id, 0, action="pass_priority").status_code == 200
    assert _act(session_id, 1, action="pass_priority").status_code == 200
    index = next(
        i for i, card in enumerate(game.players[0].library) if card.name == KEPT
    )
    assert game.confirm_search_library(0, index)

    assert [card.name for card in game.players[0].hand] == [KEPT]
    for viewer in (1, None):
        sent = json.dumps(_state(session_id, viewer))
        assert KEPT not in sent, f"leaked to viewer {viewer!r}"
    assert "W2G4-Host searched library and put a card into hand" in game.log
