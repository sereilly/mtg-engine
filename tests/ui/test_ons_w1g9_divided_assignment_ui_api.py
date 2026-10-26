"""The wire for Butcher Orgg: "You may assign this creature's combat damage
divided as you choose among defending player and/or any number of creatures
they control."

The rule is held in ``tests/sets/test_ons_creatures_later_groups.py`` (W1G9's
section). This file is the server half of the human seat: the state block that
says which attackers may divide and among whom (``divided_assignment``), and
the field that announces a division (``divided_among_defenders`` on
``assign_combat_damage``), driven the way a client drives them. The client's
dialog is a wave-2 job; the step does not wait for it (a single-blocked or
unblocked Orgg resolves as it always did), so the route is exercised here at
the one moment the server already stops for the active player — a
double block, where the division is theirs to announce.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.combat_assignment import DIVIDED_AMONG_DEFENDERS_LOG
from engine.models import Permanent
from web.app import app, store

from tests.helpers import _mk_creature_card

client = TestClient(app)


def _session() -> str:
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 51019,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return sid


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _double_blocked_orgg(set_pool):
    """Seat 0's Butcher Orgg attacks seat 1, two Walls block it, and a 2/2
    stands by; every step a client action. Returns the session at the combat
    damage step, waiting on seat 0's announcement."""
    sid = _session()
    session = store.get(sid)
    game = session.game
    orgg = Permanent(card=set_pool("ONS")["Butcher Orgg"])
    walls = [Permanent(card=_mk_creature_card(f"Wall {n}", 0, 9)) for n in "AB"]
    bystander = Permanent(card=_mk_creature_card("Bystander", 2, 2))
    game.players[0].battlefield = [orgg]
    game.players[1].battlefield = [*walls, bystander]
    for player in game.players:
        player.hand = []
        player.life = 20
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert _act(sid, seat=0, action="declare_attackers",
                attacker_indices=[0], target_seat=1).status_code == 200
    assert _act(sid, seat=0, action="next_phase").status_code == 200
    assert _act(sid, seat=1, action="declare_blockers",
                blocker_pairs={"0": 0, "1": 0}).status_code == 200
    assert _act(sid, seat=0, action="next_phase").status_code == 200
    state = _state(sid, 0)
    assert state["current_step"] == "combat_damage"
    assert not state["combat"]["damage_resolved"]
    return sid, game, orgg, walls, bystander


def test_w1g9_the_state_names_the_orgg_and_whom_it_may_divide_among(set_pool):
    sid, _game, orgg, walls, bystander = _double_blocked_orgg(set_pool)
    block = _state(sid, 0)["divided_assignment"]
    assert block["attacker_seat"] == 0
    (entry,) = block["attackers"]
    assert entry["attacker_id"] == orgg.permanent_id
    assert entry["damage"] == 6 and entry["defending_seat"] == 1
    assert {c["id"] for c in entry["creatures"]} == {
        walls[0].permanent_id, walls[1].permanent_id, bystander.permanent_id,
    }
    assert _state(sid, 1)["divided_assignment"] is None, "the attacker's alone"


def test_w1g9_a_division_over_the_wire_lands_and_a_bad_one_is_a_400(set_pool):
    sid, game, orgg, walls, bystander = _double_blocked_orgg(set_pool)
    short = _act(sid, seat=0, action="assign_combat_damage", divided_among_defenders={
        str(orgg.permanent_id): {"player": 5},
    })
    assert short.status_code == 400, short.text
    assert game.players[1].life == 20

    sent = _act(sid, seat=0, action="assign_combat_damage", divided_among_defenders={
        str(orgg.permanent_id): {str(bystander.permanent_id): 2, "player": 4},
    })
    assert sent.status_code == 200, sent.text
    assert game.players[1].life == 16
    assert not game.is_on_battlefield(bystander)
    assert all(wall.damage_marked == 0 for wall in walls)
    assert any(DIVIDED_AMONG_DEFENDERS_LOG in line for line in game.log)
