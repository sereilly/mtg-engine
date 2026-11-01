"""The auto-tap pays with Birchlore Rangers (ONS W2G5), through the wire.

"Tap two untapped Elves you control: Add one mana of any color." The web's
auto-tap is the AI's planner (``web/payment_plan.py``), so a mana ability the
planner never counted was one a person's Auto-Tap button never used either,
and the castable highlight left the card dark. Now the hand card glows, the
preview names the Rangers and the two Elves its cost taps (``cost_taps``), and
the ``auto_tap`` cast taps exactly those.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store

client = TestClient(app)


def _w2g5_session(set_pool, board, hand, *, sick=()):
    ons, lea = set_pool("ONS"), set_pool("LEA")

    def card(name):
        return ons[name] if name in ons else lea[name]

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
        permanent = Permanent(card=card(name))
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = game.turn if name in sick else -99
        permanent.tapped = False
    game._recompute_continuous_effects()
    game.players[0].hand = [card(name) for name in hand]
    game.stack.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, session


def test_w2g5_the_auto_tap_pays_with_birchlore_rangers(set_pool):
    sid, session = _w2g5_session(
        set_pool,
        ["Forest", "Birchlore Rangers", "Elvish Warrior", "Llanowar Elves"],
        ["Wirewood Savage"], sick=("Elvish Warrior",),
    )
    game = session.game
    me = client.get(f"/api/sessions/{sid}/state?seat=0").json()["players"][0]
    assert 0 in me["playable_hand_indices"]

    body = {"seat": 0, "action": "cast", "card_name": "Wirewood Savage", "target_seat": 1}
    plan = client.post(f"/api/sessions/{sid}/payment_plan", json=body).json()
    assert plan["payable"] is True, plan
    rangers = next(tap for tap in plan["taps"] if tap["name"] == "Birchlore Rangers")
    assert [tapped["name"] for tapped in rangers["cost_taps"]] == [
        "Elvish Warrior", "Birchlore Rangers",
    ]

    response = client.post(f"/api/sessions/{sid}/action", json={**body, "auto_tap": True})
    assert response.status_code == 200, response.text
    assert all(p.tapped for p in game.controlled_by(0))
    assert [item.card.name for item in game.stack] == ["Wirewood Savage"]
    assert not any(game.players[0].mana_pool.values())


def test_ons_p5_the_dialog_names_the_elves_the_rangers_cost_taps(set_pool):
    """The dialog said "Auto-Tap will tap 2 permanents … Birchlore Rangers for
    {G}, Plains for {W}" and tapped an Elvish Warrior it never named (ONS
    Phase 5, in the browser): the preview's ``cost_taps`` reached the client
    and nothing read them. The plan the server sends, through the client's
    own readers."""
    from tests.helpers import run_app_js

    sid, _session = _w2g5_session(
        set_pool,
        ["Forest", "Birchlore Rangers", "Elvish Warrior", "Llanowar Elves"],
        ["Wirewood Savage"], sick=("Elvish Warrior",),
    )
    body = {"seat": 0, "action": "cast", "card_name": "Wirewood Savage", "target_seat": 1}
    plan = client.post(f"/api/sessions/{sid}/payment_plan", json=body).json()
    assert plan["payable"] is True, plan

    out = run_app_js(
        ["autoTapPlanLines", "autoTapPlanTapCount"],
        "return { lines: autoTapPlanLines(INPUT), count: autoTapPlanTapCount(INPUT) };",
        plan,
    )
    rangers_line = next(line for line in out["lines"] if line.startswith("Birchlore Rangers"))
    assert "(tapping Elvish Warrior and Birchlore Rangers)" in rangers_line, out
    sideways = {tap["id"] for tap in plan["taps"] if not tap.get("cost_taps")}
    for tap in plan["taps"]:
        sideways |= {tapped["id"] for tapped in tap.get("cost_taps") or []}
    assert out["count"] == len(sideways), (out, plan["taps"])
