"""Serum Powder's exchange at the web table's keep-or-mulligan offer (CR 103.5b).

"Any time you could mulligan and this card is in your hand, you may exile all
the cards from your hand, then draw that many cards." The declaring seat's
offer carries ``hand_exchange`` (the hand slots of the cards granting it and
the bottom owed first) — to that seat alone, since the slots say where a card
sits in a hidden hand — and the ``mulligan_exchange`` action takes it, naming
in ``hand_indices`` the cards the seat's mulligans still owe the bottom. The
seat is then offered keep-or-mulligan again over the new hand.

Darksteel is a measured set, so no deck the web app builds holds a Powder:
each test puts one into the host's dealt hand from ``set_pool("DST")``. The
client half (a button on the offer, and a bottom pick before it when one is
owed) is the wave-2 client group's.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from web.app import app, store

client = TestClient(app)


def _create() -> str:
    for seed in range(1, 60):
        created = client.post("/api/sessions", json={
            "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
            "guest_colors": 2, "seed": seed, "enable_pregame": True,
        })
        assert created.status_code == 200, created.text
        sid = created.json()["session_id"]
        session = store.get(sid)
        if session.pregame_phase == "coin_flip" and session.coin_flip_winner == 0:
            assert _post(sid, "coin_flip_choose", hand_index=0).status_code == 200
        info = _pregame(sid, 0)
        if info and info["phase"] == "mulligan" and info.get("is_my_turn"):
            return sid
    raise AssertionError("no seed reached the host's offer")


def _post(sid: str, action: str, **extra):
    return client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": action, **extra}
    )


def _pregame(sid: str, seat: int) -> dict | None:
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()["pregame"]


def _give_powder(sid: str, powder) -> int:
    """Swap the host's first card for a Serum Powder; returns its slot."""
    player = store.get(sid).game.players[0]
    player.library.append(player.hand[0])
    player.hand[0] = powder
    return 0


def test_the_offer_carries_the_exchange_to_its_seat_alone(set_pool):
    sid = _create()
    assert _pregame(sid, 0).get("hand_exchange") is None, "no Powder, no third answer"
    _give_powder(sid, set_pool("DST")["Serum Powder"])
    offer = _pregame(sid, 0)
    assert offer["hand_exchange"] == {"source_indices": [0], "bottom_owed": 0}
    assert (_pregame(sid, 1) or {}).get("hand_exchange") is None, (
        "another seat is not told where the Powder sits"
    )


def test_the_exchange_then_the_offer_again(set_pool):
    sid = _create()
    _give_powder(sid, set_pool("DST")["Serum Powder"])
    game = store.get(sid).game
    hand_before = list(game.players[0].hand)
    taken = _post(sid, "mulligan_exchange", hand_indices=[])
    assert taken.status_code == 200, taken.text
    player = game.players[0]
    assert len(player.hand) == 7
    assert [card.name for card in player.exile] == [card.name for card in hand_before]
    offer = _pregame(sid, 0)
    assert offer["phase"] == "mulligan" and offer["is_my_turn"], "the seat declares next"
    again = _post(sid, "mulligan_exchange", hand_indices=[])
    if not any(card.name == "Serum Powder" for card in player.hand):
        assert again.status_code == 400 and "no card in your hand" in again.text


def test_after_a_mulligan_the_bottom_is_named_first(set_pool):
    sid = _create()
    assert _post(sid, "mulligan_take").status_code == 200
    for _ in range(4):
        offer = _pregame(sid, 0)
        if offer and offer["phase"] == "mulligan" and offer.get("is_my_turn"):
            break
    else:
        raise AssertionError("the host was not offered again")
    _give_powder(sid, set_pool("DST")["Serum Powder"])
    offer = _pregame(sid, 0)
    assert offer["hand_exchange"]["bottom_owed"] == 1
    refused = _post(sid, "mulligan_exchange", hand_indices=[])
    assert refused.status_code == 400 and "exactly 1" in refused.text
    refused = _post(sid, "mulligan_exchange", hand_indices=[0])
    assert refused.status_code == 400, "the Powder cannot pay the bottom"
    assert _post(sid, "mulligan_exchange", hand_indices=[3]).status_code == 200
    player = store.get(sid).game.players[0]
    assert len(player.hand) == 6 and len(player.exile) == 6
    assert _pregame(sid, 0)["bottom_owed"] == 0
    assert _post(sid, "mulligan_keep").status_code == 200
    assert len(player.hand) == 6, "the keep owed no further bottom"


def test_the_simultaneous_table_offers_it_too(set_pool):
    """The host setting that asks every seat at once: the declaring seat's
    offer carries the exchange, and the seat is still to declare after it."""
    for seed in range(1, 60):
        created = client.post("/api/sessions", json={
            "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
            "guest_colors": 2, "seed": seed, "enable_pregame": True,
            "simultaneous_mulligan": True,
        })
        sid = created.json()["session_id"]
        session = store.get(sid)
        if session.pregame_phase == "coin_flip" and session.coin_flip_winner == 0:
            assert _post(sid, "coin_flip_choose", hand_index=0).status_code == 200
        info = _pregame(sid, 0)
        if info and info["phase"] == "mulligan" and info.get("is_my_turn"):
            break
    else:
        raise AssertionError("no seed reached the host's offer")
    _give_powder(sid, set_pool("DST")["Serum Powder"])
    assert _pregame(sid, 0)["hand_exchange"]["source_indices"] == [0]
    assert _post(sid, "mulligan_exchange", hand_indices=[]).status_code == 200
    assert len(store.get(sid).game.players[0].exile) == 7
    info = _pregame(sid, 0)
    assert info["phase"] == "mulligan" and info["is_my_turn"]
