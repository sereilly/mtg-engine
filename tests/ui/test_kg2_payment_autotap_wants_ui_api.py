"""The auto-tap pays with the lands the rest of the turn needs least — the
entry's two boards through the wire.

A person's auto-tap (``web/payment_plan.py``) asks the AI's planner
(``ai_payment._PaymentPlanner``) which permanents pay, and that planner paid
generic mana in board order (Onslaught's Phase 5): a face-down {3} on four
Plains and three Mountains tapped three Plains, and Exalted Angel, face down
beside it, could no longer be turned up for {2}{W}{W}; Astral Slide's {2}{W}
on Plains, Mountain, Plains, Mountain, Plains, Plains tapped a Mountain, and
Solar Blast's cycling {1}{R}{R} was stranded. The plan now keeps what the
person's other costs need (``mana_wants.mana_wants`` — their own hand and
their own face-down permanents, CR 400.2 / CR 708.5), so each second action
goes through; and the preview the dialog shows is still exactly what the
action taps.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.face_down import turn_face_down
from engine.models import Permanent
from tests.helpers import resolve_stack
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _session(board, hand):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4245,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    game.enforce_mana_costs = True
    game.players[0].battlefield = []
    game.players[1].battlefield = []
    for name in board:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        permanent.tapped = False
    game._recompute_continuous_effects()
    game.players[0].hand = [_CARDS[name] for name in hand]
    game.players[0].library = [_CARDS["Plains"]] * 5
    game.stack.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _preview(sid, body):
    response = client.post(f"/api/sessions/{sid}/payment_plan", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _act(sid, body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _tapped(game) -> list[str]:
    return sorted(p.card.name for p in game.controlled_by(0) if p.tapped)


def _tapped_ids(game) -> list[int]:
    return sorted(p.permanent_id for p in game.controlled_by(0) if p.tapped)


def test_a_face_down_cast_leaves_the_angels_turn_up_payable():
    """Four Plains, three Mountains and a face-down Exalted Angel; a morph
    cast face down for {3}. The plan leaves two Plains for the Angel's
    {2}{W}{W}, and the Angel then turns up through the route — its morph cost
    paid by the special action's own payer (``Game._pay_planned_cost``)."""
    sid, game = _session(
        ["Plains"] * 4 + ["Mountain"] * 3 + ["Exalted Angel"], ["Whipcorder"],
    )
    (angel,) = [p for p in game.controlled_by(0) if p.card.name == "Exalted Angel"]
    assert turn_face_down(game, angel)
    body = {
        "seat": 0, "action": "cast", "card_name": "Whipcorder",
        "alternative_cost": True,
    }

    plan = _preview(sid, body)
    assert plan["payable"] is True
    assert plan["cost"].get("generic") == 3, plan["cost"]
    assert sum(tap["name"] == "Plains" for tap in plan["taps"]) <= 2, plan["taps"]

    response = _act(sid, {**body, "auto_tap": True})
    assert response.status_code == 200, response.text
    assert _tapped_ids(game) == sorted(tap["id"] for tap in plan["taps"])
    resolve_stack(game)
    untapped = [p.card.name for p in game.controlled_by(0) if p.has_type("land") and not p.tapped]
    assert untapped.count("Plains") >= 2 and len(untapped) == 4, untapped

    game.priority_player_index = 0
    response = _act(sid, {
        "seat": 0, "action": "special_action",
        "permanent_id": angel.permanent_id, "special_action_kind": "turn_face_up",
    })
    assert response.status_code == 200, response.text
    assert angel.card.name == "Exalted Angel"
    assert all(p.tapped for p in game.controlled_by(0) if p.has_type("land"))


def test_astral_slide_leaves_solar_blasts_cycling_payable():
    """Plains, Mountain, Plains, Mountain, Plains, Plains; Astral Slide and
    Solar Blast in hand. The Slide's {2}{W} is paid with three Plains, and
    Solar Blast cycles for {1}{R}{R} with the two Mountains and the last
    Plains."""
    sid, game = _session(
        ["Plains", "Mountain", "Plains", "Mountain", "Plains", "Plains"],
        ["Astral Slide", "Solar Blast"],
    )
    body = {"seat": 0, "action": "cast", "card_name": "Astral Slide"}

    plan = _preview(sid, body)
    assert plan["payable"] is True
    assert sorted(tap["name"] for tap in plan["taps"]) == ["Plains"] * 3

    response = _act(sid, {**body, "auto_tap": True})
    assert response.status_code == 200, response.text
    assert _tapped_ids(game) == sorted(tap["id"] for tap in plan["taps"])
    resolve_stack(game)
    assert any(p.card.name == "Astral Slide" for p in game.controlled_by(0))

    game.priority_player_index = 0
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    (entry,) = [e for e in state["hand_abilities"] if e["name"] == "Solar Blast"]
    assert entry["payable"] is True
    cycle = {
        "seat": 0, "action": "activate_hand", "card_name": "Solar Blast",
        "hand_index": entry["hand_index"], "ability_index": entry["ability_index"],
    }
    cycled = _preview(sid, cycle)
    assert cycled["payable"] is True, cycled
    response = _act(sid, {**cycle, "auto_tap": True})
    assert response.status_code == 200, response.text
    assert "Solar Blast" not in [card.name for card in game.players[0].hand]
    assert _tapped(game) == ["Mountain", "Mountain"] + ["Plains"] * 4


def test_with_nothing_else_wanted_the_plan_is_the_board_order():
    """No competing want — the hand holds only the spell being cast — and the
    plan is the one the order gives, exactly as before."""
    sid, game = _session(
        ["Plains", "Mountain", "Plains", "Mountain", "Plains", "Plains"], ["Astral Slide"],
    )
    plan = _preview(sid, {"seat": 0, "action": "cast", "card_name": "Astral Slide"})
    assert [tap["name"] for tap in plan["taps"]] == ["Plains", "Mountain", "Plains"]
