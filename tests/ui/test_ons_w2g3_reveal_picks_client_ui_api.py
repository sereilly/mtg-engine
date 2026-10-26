"""Onslaught's reveal-and-pick prompts, as the client draws them (W2G3).

* ``opponent_picks_revealed`` (Animal Magnetism): "Reveal the top five cards
  of your library. An opponent chooses a creature card from among them. Put
  that card onto the battlefield and the rest into your graveyard." The
  prompt offered every revealed card (a land was a 400) and said the chosen
  one went "into their battlefield". The client now disables what
  ``legal_indices`` leaves out and says where the chosen card goes
  (``fate``), where the rest go (``other_fate``) and — new on the wire —
  where they were revealed from (``from_zone``).
* ``revealed_hand_pick`` (Blackmail): "Target player reveals three cards from
  their hand and you choose one of them." The slots the player kept back
  (``shown_indices``; the server sends them as ``hidden`` stand-ins) are drawn
  face down, and the subtitle no longer says the whole hand was revealed.

The payloads are the server's, driven through the actions a client sends; the
wording and tiles are the real client functions', run in node.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from web.app import app, store

from tests.helpers import run_app_js

client = TestClient(app)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _table(set_pool, *, hand, pool, their_hand=(), library=None):
    sid = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 51037,
    }).json()["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    ons = set_pool("ONS")
    game.players[0].hand = [ons[name] for name in hand]
    game.players[1].hand = [ons[name] for name in their_hand]
    game.players[0].battlefield = []
    game.players[1].battlefield = []
    if library is not None:
        game.players[0].library = [ons[name] for name in library] + game.players[0].library
    game.players[0].mana_pool.update(pool)
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.priority_player_index = 0
    return sid, game


def _resolve_top(sid):
    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 200


@needs_node
def test_w2g3_animal_magnetism_offers_only_creatures_and_says_where_each_goes(set_pool):
    sid, game = _table(
        set_pool, hand=["Animal Magnetism"], pool={"G": 5},
        library=["Forest", "Elvish Warrior", "Forest", "Glory Seeker", "Forest"],
    )
    assert _act(sid, seat=0, action="cast", card_name="Animal Magnetism").status_code == 200
    _resolve_top(sid)
    info = _state(sid, 1)["opponent_picks_revealed"]
    assert info["legal_indices"] == [1, 3]
    assert (info["fate"], info["other_fate"], info["from_zone"]) == ("battlefield", "graveyard", "library")
    text = run_app_js(
        ["opponentPicksRevealedText"],
        "return opponentPicksRevealedText(INPUT.info);",
        {"info": info},
        prelude="let seat = 1;",
    )
    assert "from the top of their library" in text
    assert "goes onto the battlefield under their control" in text
    assert "The rest go into their graveyard" in text
    assert "Only 2 of them can be chosen" in text

    # A land the client disables is refused by the server too…
    refused = _act(sid, seat=1, action="opponent_picks_revealed_confirm", pile_index=0)
    assert refused.status_code == 400
    # …and a creature lands where the prompt said, the rest where it said.
    assert _act(sid, seat=1, action="opponent_picks_revealed_confirm", pile_index=3).status_code == 200
    assert [p.card.name for p in game.players[0].battlefield] == ["Glory Seeker"]
    assert [c.name for c in game.players[0].graveyard].count("Forest") == 3


@needs_node
def test_w2g3_blackmail_draws_the_unrevealed_slots_face_down(set_pool):
    sid, game = _table(
        set_pool, hand=["Blackmail"], pool={"B": 1},
        their_hand=["Shock", "Goblin Sledder", "Mountain", "Lay Waste", "Goblin Taskmaster"],
    )
    assert _act(sid, seat=0, action="cast", card_name="Blackmail", target_seat=1).status_code == 200
    _resolve_top(sid)
    assert _state(sid, 1)["choose_cards_in_hand"]["verb"] == "reveal"
    assert _act(sid, seat=1, action="choose_cards_in_hand_confirm",
                hand_indices=[2, 3, 4]).status_code == 200
    info = _state(sid, 0)["revealed_hand_pick"]
    assert info["shown_indices"] == [2, 3, 4]
    assert [c.get("hidden", False) for c in info["cards"]] == [True, True, False, False, False]
    drawn = run_app_js(
        ["revealedHandPickSubtitle", "revealedHandPickTile", "escapeHtml"],
        "const legal = new Set(INPUT.info.legal_indices);"
        " return { subtitle: revealedHandPickSubtitle(INPUT.info),"
        " tiles: INPUT.info.cards.map((c, i) => revealedHandPickTile(c, i, legal)) };",
        {"info": info},
        prelude="let seat = 0;",
    )
    assert "revealed 3 of the 5 cards in their hand" in drawn["subtitle"]
    assert "revealed their hand." not in drawn["subtitle"]
    assert all("card_back.webp" in tile and "face-down" in tile for tile in drawn["tiles"][:2])
    assert not any("Shock" in tile or "Goblin Sledder" in tile for tile in drawn["tiles"])
    assert "Lay Waste" in drawn["tiles"][3]

    # A hidden slot is not a pick; a revealed one is.
    assert _act(sid, seat=0, action="revealed_hand_pick_confirm", hand_index=0).status_code == 400
    assert _act(sid, seat=0, action="revealed_hand_pick_confirm", hand_index=3).status_code == 200
    assert [c.name for c in game.players[1].graveyard] == ["Lay Waste"]


@needs_node
def test_w2g3_a_whole_revealed_hand_keeps_duress_wording():
    info = {"card_name": "Duress", "victim_name": "Bob", "legal_indices": [0],
            "cards": [{"name": "Shock", "image_uri": None}], "shown_indices": None}
    subtitle = run_app_js(
        ["revealedHandPickSubtitle"], "return revealedHandPickSubtitle(INPUT.info);",
        {"info": info}, prelude="let seat = 0;",
    )
    assert subtitle.startswith("Duress: Bob revealed their hand.")
