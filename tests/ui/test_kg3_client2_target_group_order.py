"""Kaboom!'s within-group target order, answered from the browser.

kg3/ai built the ``target_group_order`` prompt's server half (Kaboom!'s
2022-09-09 ruling: "those targets will be handled one at a time in turn
order. … You choose the relative order of targets within that group") and
left the client in ``test_prompt_client_coverage._AWAITING_CLIENT``. The
client: ``getTargetGroupOrderInfo`` reads ``state.target_group_order``,
``applyTargetGroupOrderPrompt`` draws it with the ``order_triggers`` widget
(``applyOrderListPrompt``, shared now), each player's group under that
player's name, a move kept inside its group (``orderListMove``), and OK sends
``target_order`` — every index once — with ``target_group_order_confirm``.

Driven here at a three-seat table with two planeswalkers on one opponent,
through the app: the served prompt, the client's getter and move rule over
it, and the order the widget sends landing on the board.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on
from web.app import app, store

from tests.helpers import app_js_function_body, run_app_js

client = TestClient(app)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_CARDS = {card.name: card for card in load_catalog()}
_WALKERS = ("Chandra, Heart of Fire", "Liliana, Death Mage")


def _walker(name: str, loyalty: int = 6) -> Permanent:
    walker = Permanent(card=_CARDS[name])
    walker.metadata["summoning_sickness_turn"] = -99
    add_counters(walker, "loyalty", loyalty)
    return walker


def _kaboom_at_a_table_of_three():
    """Seat 0 (a person) casts Kaboom! at seat 1 and seat 1's two
    planeswalkers; the two AI seats pass, the spell resolves and stops on the
    order of seat 1's group. Returns ``(sid, game, walkers)``."""
    created = client.post("/api/sessions", json={
        "mode": "free_for_all", "seed": 2611,
        "seats": [
            {"name": "Host", "is_ai": False, "colors": 2},
            {"name": "Bree", "is_ai": True, "colors": 2},
            {"name": "Cato", "is_ai": True, "colors": 2},
        ],
    })
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    walkers = [_walker(name) for name in _WALKERS]
    game.players[0].hand = [_CARDS["Kaboom!"]]
    game.players[0].library = [_CARDS[n] for n in ("Hill Giant", "Shock", "Gray Ogre", "Island", "Island")]
    for player in game.players:
        player.battlefield = []
        player.life = 20
    game.players[1].battlefield = list(walkers)
    game._sync_control()
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.start_priority_window(0)

    cast = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Kaboom!",
        "target_role_refs": [{"seat": 1}, *({"permanent_id": w.permanent_id} for w in walkers)],
    })
    assert cast.status_code == 200, cast.text
    for _ in range(6):
        if client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json().get("target_group_order"):
            break
        client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"})
    return sid, game, walkers


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def test_the_caster_is_served_seat_ones_group_and_the_others_are_not():
    sid, _game, walkers = _kaboom_at_a_table_of_three()

    served = _state(sid)["target_group_order"]

    assert served["player_seat"] == 0 and served["card_name"] == "Kaboom!"
    assert [(t["name"], t["group"], t["id"]) for t in served["targets"]] == [
        ("Bree", 1, None),
        (_WALKERS[0], 1, walkers[0].permanent_id),
        (_WALKERS[1], 1, walkers[1].permanent_id),
    ]
    # Nothing is dealt while the order is owed (CR 608.2).
    assert _state(sid)["players"][1]["life"] == 20


@needs_node
def test_the_clients_getter_and_move_rule_read_the_served_prompt():
    sid, _game, _walkers = _kaboom_at_a_table_of_three()
    state = _state(sid)
    # A second group, as the active player's own targets would make one: a
    # move may not carry a row across it.
    two_groups = [{**t, "group": 0 if t["index"] == 0 else t["group"]} for t in state["target_group_order"]["targets"]]

    answer = run_app_js(
        ["getTargetGroupOrderInfo", "orderListMove"],
        """
        const info = getTargetGroupOrderInfo(INPUT.state);
        const groupOf = (targets) => {
          const byIndex = new Map(targets.map((t) => [t.index, t.group]));
          return (index) => byIndex.get(index);
        };
        const order = info.targets.map((t) => t.index);
        return {
          seen: info.targets.length,
          other_seat: getTargetGroupOrderInfo({ ...INPUT.state, target_group_order: { ...info, player_seat: 1 } }),
          walker_first: orderListMove(order, groupOf(info.targets), 1, 0),
          last_down: orderListMove(order, groupOf(info.targets), 2, 3),
          across_groups: orderListMove(order, groupOf(INPUT.two_groups), 1, 0),
          within_second: orderListMove(order, groupOf(INPUT.two_groups), 2, 1),
        };
        """,
        {"state": state, "two_groups": two_groups},
        prelude="let seat = 0; let currentState = null;",
    )

    assert answer == {
        "seen": 3,
        "other_seat": None,
        "walker_first": [1, 0, 2],
        "last_down": None,
        "across_groups": None,
        "within_second": [0, 2, 1],
    }


def test_the_order_the_widget_sends_is_the_order_the_targets_are_dealt_in():
    """Liliana first, then Chandra, then Bree — the revealed Hill Giant (4),
    Shock (1) and Gray Ogre (3) go in that order."""
    sid, game, (chandra, liliana) = _kaboom_at_a_table_of_three()

    answered = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "target_group_order_confirm", "target_order": [2, 1, 0],
    })
    assert answered.status_code == 200, answered.text
    for _ in range(6):
        if not game.stack:
            break
        client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"})

    assert counters_on(liliana, "loyalty") == 2
    assert counters_on(chandra, "loyalty") == 5
    assert game.players[1].life == 17
    assert any(
        f"handles Kaboom!'s targets in the order {_WALKERS[1]}, {_WALKERS[0]}, Bree" in line
        for line in game.log
    )


def test_an_order_out_of_its_groups_or_short_of_a_target_is_refused_and_stays_owed():
    sid, game, _walkers = _kaboom_at_a_table_of_three()

    short = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "target_group_order_confirm", "target_order": [1, 0],
    })

    assert short.status_code == 400
    assert _state(sid)["target_group_order"] is not None
    assert any(item.card.name == "Kaboom!" for item in game.stack)


def test_the_panel_dispatches_the_prompt_and_sends_the_order():
    panel = app_js_function_body("applyTargetGroupOrderPrompt")
    assert "applyOrderListPrompt(" in panel
    assert 'action: "target_group_order_confirm"' in panel and "target_order: chosen" in panel
    assert "group: Number(t.group)" in panel
    cascade = app_js_function_body("renderActivationPrompt")
    assert cascade.index("applyOrderTriggersPrompt(orderTriggersInfo)") < cascade.index(
        "applyTargetGroupOrderPrompt(targetGroupOrderInfo)"
    )
    assert "getTargetGroupOrderInfo(state)" in app_js_function_body("shouldShowPriorityPrompt")
    # The shared widget asks the move rule for every arrow it draws and every
    # move it makes.
    widget = app_js_function_body("applyOrderListPrompt")
    assert widget.count("orderListMove(") == 2
