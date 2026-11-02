"""The auto-tap sees the costs a payment's wants could not: driven through the
wire on the census's own rows (``tests/ai/test_kg3_payment_wants_census.py``).

* Aurora Griffin cast on four Plains and three Mountains: its own {W} ability
  is the next thing its caster pays for, and the plan tapped all four Plains
  for the {3}{W}.
* Juggernaut's {4} beside Embolden in the graveyard: Embolden's flashback
  {1}{W} is a card's price, and the plan tapped four Plains.
* A face-down permanent being turned face up is the payment's own card: its
  morph cost is no want beside it, and its face-up abilities are.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.face_down import turn_face_down
from engine.mana_wants import mana_wants
from engine.models import Permanent
from tests.helpers import resolve_stack
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _session(board, hand, graveyard=()):
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
    game.players[0].graveyard = [_CARDS[name] for name in graveyard]
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


def _untapped_lands(game) -> list[str]:
    return sorted(p.card.name for p in game.controlled_by(0) if p.has_type("land") and not p.tapped)


def test_a_permanent_spell_leaves_its_own_ability_payable():
    sid, game = _session(["Plains"] * 4 + ["Mountain"] * 3, ["Aurora Griffin"])
    body = {"seat": 0, "action": "cast", "card_name": "Aurora Griffin"}
    plan = _preview(sid, body)
    assert plan["payable"] is True
    assert sum(tap["name"] == "Plains" for tap in plan["taps"]) <= 3, plan["taps"]

    response = client.post(f"/api/sessions/{sid}/action", json={**body, "auto_tap": True})
    assert response.status_code == 200, response.text
    resolve_stack(game)
    assert "Plains" in _untapped_lands(game), _untapped_lands(game)

    (griffin,) = [p for p in game.controlled_by(0) if p.card.name == "Aurora Griffin"]
    game.priority_player_index = 0
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_id": griffin.permanent_id,
        "ability_index": 0, "target_seat": 0, "target_permanent_id": griffin.permanent_id,
        "auto_tap": True,
    })
    assert response.status_code == 200, response.text


def test_a_payment_leaves_a_graveyard_flashback_payable():
    sid, game = _session(["Plains"] * 4 + ["Mountain"] * 3, ["Juggernaut"], ["Embolden"])
    body = {"seat": 0, "action": "cast", "card_name": "Juggernaut"}
    plan = _preview(sid, body)
    assert plan["payable"] is True
    assert sum(tap["name"] == "Plains" for tap in plan["taps"]) <= 3, plan["taps"]

    response = client.post(f"/api/sessions/{sid}/action", json={**body, "auto_tap": True})
    assert response.status_code == 200, response.text
    resolve_stack(game)
    left = _untapped_lands(game)
    assert "Plains" in left and len(left) == 3, left


def test_a_turn_up_is_not_its_own_want_and_brings_its_abilities():
    """Exalted Angel face down: its {2}{W}{W} morph cost is a want of the seat —
    until the payment *is* its turn-up; then the turn-up is gone from the
    wants and the face-up card's abilities stand in the abilities' tier."""
    sid, game = _session(["Plains"] * 4 + ["Mountain"] * 3 + ["Exalted Angel"], [])
    (angel,) = [p for p in game.controlled_by(0) if p.card.name == "Exalted Angel"]
    assert turn_face_down(game, angel)

    beside = mana_wants(game, 0)
    assert {"generic": 2, "W": 2} in [dict(want) for want in beside.cards]
    own = mana_wants(game, 0, paying_for=angel)
    assert {"generic": 2, "W": 2} not in [dict(want) for want in own.cards]

    game.priority_player_index = 0
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "special_action",
        "permanent_id": angel.permanent_id, "special_action_kind": "turn_face_up",
    })
    assert response.status_code == 200, response.text
    assert angel.card.name == "Exalted Angel"
