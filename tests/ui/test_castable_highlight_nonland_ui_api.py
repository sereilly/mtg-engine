"""The castable glow over a Sol Ring, an Elf and a Mana Flare, over the wire.

``playable_hand_indices`` counted lands alone, so a card a Sol Ring pays for
was dark — and the AI seat across the table had been tapping that Ring for its
own spells since Planeshift. "Castable" is castable with what the seat could
tap (CR 601.2g): the state API now asks ``board_can_pay(…,
nonland_sources=True)``. The census is
``tests/engine/test_castable_highlight_counts_every_tap.py``; these are named
boards, each driven through the activation the glow promises and then the
cast.

What this file does **not** drive is the auto-tap. The client planned that
itself when this was written, lands alone, so a card that glowed on the
strength of a Sol Ring opened the "insufficient mana" prompt with the button
disabled; the plan is the server's now, and
``tests/ui/test_auto_tap_plan_census.py`` holds it to this glow.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _session(board, hand, *, sick=()):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4245,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = True
    game.players[0].battlefield = []
    game.players[1].battlefield = []
    for name in board:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = (
            game.turn if name in sick else -99
        )
        permanent.tapped = False
    game._recompute_continuous_effects()
    game.players[0].hand = [_CARDS[name] for name in hand]
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _glowing(sid, hand) -> list[str]:
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    return [hand[index] for index in state["players"][0]["playable_hand_indices"]]


def _activate(sid, game, name, **extra):
    permanent = next(p for p in game.controlled_by(0) if p.card.name == name)
    return client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_name": name,
        "permanent_id": permanent.permanent_id, **extra,
    })


def test_a_sol_ring_pays_for_what_glows():
    """{2}: a Sol Ring alone. It glowed for nobody; tapped, the cast goes."""
    hand = ["Rod of Ruin", "Grizzly Bears"]
    sid, game = _session(["Sol Ring"], hand)
    # {4} and {1}{G}: neither is two colourless.
    assert _glowing(sid, hand) == []

    hand = ["Sol Ring", "Jayemdae Tome"]
    sid, game = _session(["Sol Ring", "Sol Ring"], hand)
    assert _glowing(sid, hand) == ["Sol Ring", "Jayemdae Tome"]
    for _ in range(2):
        ring = next(p for p in game.controlled_by(0) if not p.tapped)
        response = client.post(f"/api/sessions/{sid}/action", json={
            "seat": 0, "action": "activate", "permanent_name": "Sol Ring",
            "permanent_id": ring.permanent_id,
        })
        assert response.status_code == 200, response.text
    assert game.players[0].mana_pool.get("C", 0) == 4
    assert game.cast_from_hand(0, "Jayemdae Tome").supported


def test_an_elf_and_a_forest_pay_for_a_bear():
    hand = ["Grizzly Bears"]
    sid, game = _session(["Forest"], hand)
    assert _glowing(sid, hand) == []

    sid, game = _session(["Forest", "Llanowar Elves"], hand)
    assert _glowing(sid, hand) == hand
    assert _activate(sid, game, "Llanowar Elves").status_code == 200
    assert _activate(sid, game, "Forest", mana_color="G").status_code == 200
    assert game.cast_from_hand(0, "Grizzly Bears").supported

    # The Elf that arrived this turn cannot be tapped (CR 602.5a), and the
    # card is as dark as the click would be refused.
    sid, game = _session(["Forest", "Llanowar Elves"], hand, sick=("Llanowar Elves",))
    assert _glowing(sid, hand) == []
    assert _activate(sid, game, "Llanowar Elves").status_code == 400


def test_a_null_rod_turns_the_ring_off_for_the_glow_and_the_click():
    hand = ["Jayemdae Tome"]
    sid, game = _session(["Sol Ring", "Sol Ring", "Null Rod"], hand)
    assert _glowing(sid, hand) == []
    response = _activate(sid, game, "Sol Ring")
    assert response.status_code == 400
    assert "can't be activated" in response.text


def test_a_mana_flare_doubles_what_a_forest_pays():
    """"Whenever a player taps a land for mana, that player adds one
    additional mana of any type that land produced.\""""
    hand = ["Grizzly Bears", "Craw Wurm"]
    sid, game = _session(["Forest"], hand)
    assert _glowing(sid, hand) == []

    sid, game = _session(["Mana Flare", "Forest"], hand)
    assert _glowing(sid, hand) == ["Grizzly Bears"]
    assert _activate(sid, game, "Forest", mana_color="G").status_code == 200
    assert game.players[0].mana_pool.get("G", 0) == 2
    assert game.cast_from_hand(0, "Grizzly Bears").supported

    sid, game = _session(["Mana Flare", "Forest", "Forest", "Forest"], hand)
    assert _glowing(sid, hand) == hand
