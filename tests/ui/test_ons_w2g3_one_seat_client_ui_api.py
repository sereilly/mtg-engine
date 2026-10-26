"""Onslaught's "each player" prompts, one seat at a time, as each seat reads
them (W2G3).

W1G13 made each-player discards and hand picks arrive one seat at a time in
turn order. What each seat was then shown:

* **Strongarm Tactics** ("Each player discards a card. Then each player who
  didn't discard a creature card this way loses 4 life."): "Discard a Card" —
  no spell, no round. The ``discard`` prompt now carries the spell
  (``card_name``) and the round (``each_player``: every seat in turn order
  with what it has discarded), and the client says "you are 2 of 3. Alice
  discarded Swamp. Cara is next."
* **Death Match** ("Whenever a creature enters, that creature's controller
  may have target creature of their choice get -3/-3"): the creature's
  controller is asked for the target of a trigger they do not control, and
  was told "Death Match: its triggered ability needs a target". The
  ``trigger_target`` prompt names the controller and the ability's words when
  the seat asked is someone else.
* **Tempting Wurm** ("each opponent may put any number of artifact, creature,
  enchantment, and/or land cards from their hand onto the battlefield"): the
  pick said "Choose any number of the cards in your hand". The
  ``choose_cards_in_hand`` prompt says where the cards go (``destination``,
  read off the step behind the pick).
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.models import Permanent
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


def _table(set_pool, *, hands, boards=None, active=0):
    created = client.post("/api/sessions", json={
        "mode": "free_for_all", "seed": 11,
        "seats": [{"name": n, "is_ai": False, "colors": 2} for n in ("Alice", "Bob", "Cara")],
    })
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    session.current_turn = active
    game.active_player_index = active
    game.current_turn_phase = game.current_step = "precombat_main"
    game.priority_player_index = active
    game.interactive_seats = {0, 1, 2}
    ons = set_pool("ONS")
    for seat, player in enumerate(game.players):
        player.hand[:] = [ons[name] for name in hands[seat]]
        player.battlefield[:] = [Permanent(card=ons[name]) for name in (boards or {}).get(seat, ())]
        for perm in player.battlefield:
            perm.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return sid, game


def _pass_round(sid, first):
    for offset in range(3):
        assert _act(sid, seat=(first + offset) % 3, action="pass_priority").status_code == 200


@needs_node
def test_w2g3_strongarm_tactics_tells_each_seat_where_it_stands(set_pool):
    sid, game = _table(set_pool, hands=[
        ["Strongarm Tactics", "Glory Seeker", "Swamp"], ["Glory Seeker", "Plains"], ["Daru Lancer", "Island"],
    ])
    assert _act(sid, seat=0, action="cast", card_name="Strongarm Tactics").status_code == 200
    _pass_round(sid, 0)
    first = _state(sid, 0)["discard_select"]
    assert first["card_name"] == "Strongarm Tactics"
    assert [(e["name"], e["discarded"]) for e in first["each_player"]] == [
        ("Alice", []), ("Bob", []), ("Cara", []),
    ]
    assert _act(sid, seat=0, action="discard_confirm", discard_indices=[1]).status_code == 200
    second = _state(sid, 1)["discard_select"]
    assert [(e["name"], e["discarded"]) for e in second["each_player"]] == [
        ("Alice", ["Swamp"]), ("Bob", []), ("Cara", []),
    ]
    text = run_app_js(
        ["discardSelectContext"], "return discardSelectContext(INPUT.info);",
        {"info": second}, prelude="let seat = 1;",
    )
    assert text == (
        "Strongarm Tactics: each player discards in turn order — you are 2 of 3. "
        "Alice discarded Swamp. Cara is next."
    )
    assert _act(sid, seat=1, action="discard_confirm", discard_indices=[0]).status_code == 200
    assert _act(sid, seat=2, action="discard_confirm", discard_indices=[1]).status_code == 200
    assert [p.life for p in game.players] == [16, 20, 16]


def test_w2g3_a_discard_nothing_on_the_stack_armed_is_unchanged(set_pool):
    sid, game = _table(set_pool, hands=[["Glory Seeker", "Swamp"], [], []])
    game.arm_pending_choice("discard", 0, count=1)
    info = _state(sid, 0)["discard_select"]
    assert "card_name" not in info and "each_player" not in info


@needs_node
def test_w2g3_death_match_tells_the_chooser_whose_trigger_it_is(set_pool):
    sid, game = _table(
        set_pool, hands=[[], ["Glory Seeker"], []],
        boards={0: ["Death Match", "Elvish Warrior"], 1: ["Goblin Sledder"]}, active=1,
    )
    assert _act(sid, seat=1, action="cast", card_name="Glory Seeker").status_code == 200
    _pass_round(sid, 1)
    assert _state(sid, 0)["trigger_target"] is None, "Death Match's controller is not asked"
    info = _state(sid, 1)["trigger_target"]
    assert info["controller_seat"] == 0 and info["controller_name"] == "Alice"
    assert "that creature's controller may" in info["ability_text"]
    text = run_app_js(
        ["triggerTargetForAnotherText"], "return triggerTargetForAnotherText(INPUT.info);",
        {"info": info}, prelude="let seat = 1;",
    )
    assert text.startswith("Alice's Death Match triggered — “Whenever a creature enters")
    assert text.endswith("You choose its target.")
    warrior = game.players[0].battlefield[1]
    assert _act(sid, seat=1, action="trigger_target_confirm",
                target_permanent_id=warrior.permanent_id).status_code == 200
    _pass_round(sid, 1)
    assert _state(sid, 1)["optional_pay"]["pending"][0]["player_index"] == 1
    assert _act(sid, seat=1, action="resolve_optional_pay", card_name="Death Match",
                accept=True).status_code == 200
    assert not game.is_on_battlefield(warrior)


@needs_node
def test_w2g3_tempting_wurm_says_the_cards_go_onto_the_battlefield(set_pool):
    sid, game = _table(set_pool, hands=[
        ["Tempting Wurm"], ["Glory Seeker", "Plains", "Shock"], ["Daru Lancer", "Island"],
    ])
    assert _act(sid, seat=0, action="cast", card_name="Tempting Wurm").status_code == 200
    _pass_round(sid, 0)
    _pass_round(sid, 0)
    info = _state(sid, 1)["choose_cards_in_hand"]
    assert info["destination"] == "battlefield"
    assert [c["name"] for c in info["choices"]] == ["Glory Seeker", "Plains"], "never the Shock"
    assert _act(sid, seat=1, action="choose_cards_in_hand_confirm", hand_indices=[0]).status_code == 200
    assert _state(sid, 2)["choose_cards_in_hand"]["destination"] == "battlefield"
    assert _act(sid, seat=2, action="choose_cards_in_hand_confirm", hand_indices=[]).status_code == 200
    assert [p.card.name for p in game.players[1].battlefield] == ["Glory Seeker"]
    assert game.players[2].battlefield == []
