"""A cycle trigger through the browser's route: cycle, see the trigger above
the cycling ability, answer what it asks, then draw.

ONS W1G3 adds no prompt and no gesture — a cycling ability is
``activate_hand`` (``tests/ui/test_hand_ability_wire.py``) and the cycle
triggers ask through ``trigger_target`` and ``optional_pay``, both already
rendered — but it is the first time either is asked *between* a cycling cost
and its draw, so the order a person meets them in is pinned here: the trigger
holds the stack (CR 608.2) and nothing is drawn until it is answered.

Onslaught is still ``measured``, so ``CARD_BY_NAME`` does not hold its cards;
the cards are handed to the session's game directly, the way the hand-ability
wire test hands it Waker of Waves.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store

from ..helpers import _mk_creature_card

client = TestClient(app)


def _session_holding(set_pool, *names):
    """A human-vs-AI session whose human seat 0 holds *names* with priority in
    its precombat main phase.

    The AI's hand is emptied: it is offered priority after every action
    (``Game.priority_driver``), and whether it answers a cycle with an instant
    of its own depends on what it was dealt and on the process's RNG, which
    other tests move. What is pinned here is the human's road, not the AI's
    policy."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H",
        "host_colors": 2, "guest_colors": 2, "seed": 11,
    }).json()
    sid = created["session_id"]
    game = store.get(sid).game
    game.active_player_index = 0
    game.priority_player_index = 0
    game.enforce_mana_costs = False
    game.players[1].hand.clear()
    for name in names:
        game.players[0].hand.append(set_pool("ONS")[name])
    return sid, game


def _cycle(sid, name):
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    entry = next(e for e in state["hand_abilities"] if e["name"] == name)
    assert entry["cost_text"].startswith("Cycling ")
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate_hand", "card_name": name,
        "hand_index": entry["hand_index"], "ability_index": entry["ability_index"],
    })
    assert response.status_code == 200, response.text
    return response


def test_a_human_cycles_renewed_faith_and_answers_its_trigger_before_the_draw(set_pool):
    sid, game = _session_holding(set_pool, "Renewed Faith")
    human = game.players[0]
    hand_before = len(human.hand)

    _cycle(sid, "Renewed Faith")
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    texts = [entry.get("ability_text") or "" for entry in state["stack"]]
    assert any(t.startswith("When you cycle this card") for t in texts), state["stack"]
    assert [item.ability_text for item in game.stack][-1].startswith("When you cycle")

    # Both players pass: the trigger resolves and asks; the draw waits.
    assert client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "pass_priority",
    }).status_code == 200
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert state["waiting_on_prompt"], state.get("waiting_on_prompt")
    offers = [e for e in game.pending_optional_pays if e["player_index"] == 0]
    assert [e["card_name"] for e in offers] == ["Renewed Faith"]
    assert len(human.hand) == hand_before - 1, "nothing drawn yet"

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "resolve_optional_pay",
        "card_name": "Renewed Faith", "accept": True,
    })
    assert response.status_code == 200, response.text
    assert human.life == 22

    for _ in range(3):
        if not game.stack:
            break
        assert client.post(f"/api/sessions/{sid}/action", json={
            "seat": 0, "action": "pass_priority",
        }).status_code == 200
    assert game.stack == []
    assert len(human.hand) == hand_before, "the cycling ability drew"


def test_a_human_names_choking_tethers_trigger_target_on_the_wire(set_pool):
    sid, game = _session_holding(set_pool, "Choking Tethers")
    theirs = Permanent(card=_mk_creature_card("Their Bear", 2, 2))
    game._put_permanent_onto_battlefield(1, theirs, None)
    game._sync_control()

    _cycle(sid, "Choking Tethers")
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    prompt = state["trigger_target"]
    assert prompt is not None, sorted(k for k, v in state.items() if v)
    assert prompt["card_name"] == "Choking Tethers"
    ids = {c.get("id") for c in prompt["candidates"] if c.get("kind") == "permanent"}
    assert theirs.permanent_id in ids
    assert len(game.stack) == 2 and game.stack[-1].ability_text.startswith(
        "When you cycle this card"
    )

    response = client.post(f"/api/sessions/{sid}/action", json={
        # The body app.js's `onPermanent` builds for this prompt.
        "seat": 0, "action": "trigger_target_confirm",
        "target_permanent_id": theirs.permanent_id,
    })
    assert response.status_code == 200, response.text
    assert game.stack[-1].target_permanent_id == [theirs.permanent_id]

    assert client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "pass_priority",
    }).status_code == 200
    assert client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "resolve_optional_pay",
        "card_name": "Choking Tethers", "accept": True,
    }).status_code == 200
    assert theirs.tapped
