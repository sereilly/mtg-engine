"""CR 616.1e asked from outside the handlers, through the web layer.

A damage event outside ``engine/handlers`` asks the affected seat which of two
applicable effects applies first (round kg3,
``tests/regressions/test_kg3_damage_outside_handlers_ask.py`` is the engine's
census). This is the check that a person is in fact shown the question, held
to it, and able to answer it — from a land tapped for mana (Manabarbs, the
damage dealt in the middle of a ``tap`` action) and from a redirect applied
inside another event's process (Pariah moving a Prodigal Sorcerer's ping).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.shields import add_shield, make_counting_pool, make_numeric_pool, shields_on
from web.app import app, store

client = TestClient(app)

_SHIPPED = {card.name: card for card in load_catalog()}


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4243,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].battlefield, game.players[1].battlefield = [], []
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _put(game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_SHIPPED[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game.pending_choices.clear()
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _arm_two(recipient) -> None:
    add_shield(recipient, make_numeric_pool(10, source_name="Plain Pool"))
    add_shield(recipient, make_counting_pool(10, "+1/+1", source_name="Counting Pool"))


def _pools(recipient) -> dict:
    return {s.source_name: s.amount for s in shields_on(recipient)}


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _asked_and_answered(sid: str, game, recipient, option: int) -> None:
    state = _state(sid)
    prompt = state["effect_order"]
    assert prompt is not None, "armed and never rendered"
    assert prompt["player_seat"] == 0 and len(prompt["options"]) == 2
    assert state["waiting_on_prompt"] is True
    assert _state(sid, seat=1)["effect_order"] is None
    assert _pools(recipient) == {"Plain Pool": 10, "Counting Pool": 10}
    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 400
    assert _act(
        sid, seat=1, action="effect_order_confirm", option_index=option,
    ).status_code == 400
    picked = "Counting Pool" if "counters" in prompt["options"][option] else "Plain Pool"
    answered = _act(sid, seat=0, action="effect_order_confirm", option_index=option)
    assert answered.status_code == 200, answered.text
    assert answered.json()["effect_order"] is None
    assert _pools(recipient) == {"Plain Pool": 10, "Counting Pool": 10, picked: 9}


def test_a_land_tapped_under_manabarbs_asks_its_tapper():
    for option in (0, 1):
        sid, game = _session()
        _put(game, 1, "Manabarbs")
        mountain = _put(game, 0, "Mountain")
        _arm_two(game.players[0])
        tapped = _act(sid, seat=0, action="tap", permanent_name="Mountain")
        assert tapped.status_code == 200, tapped.text
        assert mountain.tapped and game.players[0].mana_pool.get("R", 0) == 1
        _asked_and_answered(sid, game, game.players[0], option)
        assert game.players[0].life == 20
        assert any("Manabarbs triggered" in line for line in game.log)


def test_a_redirect_asks_the_seat_its_damage_is_moved_to():
    """Seat 1's Prodigal Sorcerer pings seat 0, whose Pariah moves the damage
    onto the creature it enchants: the moved damage asks that creature's
    controller, and the ping's ability waits on the stack for the answer."""
    for option in (0, 1):
        sid, game = _session()
        bears = _put(game, 0, "Grizzly Bears")
        pariah = _put(game, 0, "Pariah")
        from engine.aura_attachment import attach_aura

        attach_aura(pariah, bears)
        _put(game, 1, "Prodigal Sorcerer")
        _arm_two(bears)
        game.start_priority_window(1)
        activated = _act(
            sid, seat=1, action="activate", permanent_name="Prodigal Sorcerer",
            target_seat=0,
        )
        assert activated.status_code == 200, activated.text
        for seat in (1, 0):
            passed = _act(sid, seat=seat, action="pass_priority")
            assert passed.status_code == 200, passed.text
        _asked_and_answered(sid, game, bears, option)
        assert game.players[0].life == 20 and bears.damage_marked == 0
        assert any("is dealt to Grizzly Bears instead" in line for line in game.log)
        assert _state(sid)["stack"] == []
