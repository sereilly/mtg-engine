"""The wire and the dialog of a trampler blocked by one creature (CR 702.19b).

The engine stops the combat damage step for an interactive assigner with
damage to spare (``Game.trample_assignments_to_ask``); the state names the
attacker to the seat that assigns — ``trample_assignment`` for the active
player, ``banding_assignment.attackers[].trample`` for a defending player who
assigns (CR 702.22j) — and the client lists it in the damage dialog with its
one blocker, the rest of its damage trampling over to ``recipient``. The
answer is the ordinary division.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store

from tests.helpers import _mk_creature_card, run_app_js

client = TestClient(app)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _to_combat_damage(blocker_text: str = "", blocker_toughness: int = 1):
    """Two people: seat 0 attacks with a 6/6 trampler, seat 1 blocks with one
    creature. Every step is an action a client sends."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 70219,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    beast = Permanent(card=_mk_creature_card("Stomping Beast", 6, 6, "Trample"))
    guard = Permanent(card=_mk_creature_card("Guard", 1, blocker_toughness, blocker_text))
    game.players[0].battlefield = [beast]
    game.players[1].battlefield = [guard]
    game._sync_control()
    game.players[0].life = game.players[1].life = 20
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    declared = _act(sid, seat=0, action="declare_attackers", attacker_indices=[0], target_seat=1)
    assert declared.status_code == 200, declared.text
    assert _act(sid, seat=0, action="next_phase").status_code == 200
    blocked = _act(sid, seat=1, action="declare_blockers", blocker_pairs={"0": 0})
    assert blocked.status_code == 200, blocked.text
    advanced = _act(sid, seat=0, action="next_phase")
    assert advanced.status_code == 200, advanced.text
    return sid, game, beast, guard


def test_the_attacker_is_named_to_the_active_seat_alone():
    sid, game, beast, _guard = _to_combat_damage()

    mine = _state(sid, 0)
    assert mine["combat"]["damage_resolved"] is False, "the step resolved unasked"
    assert mine["trample_assignment"] == {
        "attacker_seat": 0,
        "attackers": [{
            "attacker_index": 0,
            "attacker_id": beast.permanent_id,
            "damage": 6,
            "recipient": {"kind": "player", "seat": 1, "name": game.players[1].name},
        }],
    }
    assert _state(sid, 1)["trample_assignment"] is None
    # The step waits on the attacker: a pass does not run past it.
    assert mine["waiting_on_prompt"] or mine["combat"]["damage_resolved"] is False


@pytest.mark.parametrize(("to_guard", "life"), [(6, 20), (1, 15)], ids=["all-on", "lethal"])
def test_the_ordinary_division_is_the_answer(to_guard, life):
    sid, game, _beast, _guard = _to_combat_damage()

    answered = _act(sid, seat=0, action="assign_combat_damage", attacker_damage={"0": {"0": to_guard}})

    assert answered.status_code == 200, answered.text
    assert game.combat_damage_resolved
    assert game.players[1].life == life
    assert answered.json()["trample_assignment"] is None


def test_too_little_on_the_blocker_is_refused_and_the_step_still_waits():
    sid, game, _beast, _guard = _to_combat_damage(blocker_toughness=3)

    refused = _act(sid, seat=0, action="assign_combat_damage", attacker_damage={"0": {"0": 2}})

    assert refused.status_code == 400
    assert "lethal" in refused.json()["detail"]
    assert not game.combat_damage_resolved
    assert _state(sid, 0)["trample_assignment"] is not None


def test_a_defending_player_who_assigns_is_asked_in_their_own_prompt():
    """Banding on the blocker: the defending player assigns the trampler's
    damage (CR 702.22j) and may keep all six on their creature."""
    sid, game, _beast, guard = _to_combat_damage(blocker_text="Banding", blocker_toughness=2)

    theirs = _state(sid, 1)
    [entry] = theirs["banding_assignment"]["attackers"]
    assert entry["trample"] == {
        "recipient": {"kind": "player", "seat": 1, "name": game.players[1].name},
    }
    assert _state(sid, 0)["trample_assignment"] is None, "not the attacker's to place"

    answered = _act(sid, seat=1, action="assign_banding_damage", banding_damage={"0": {"0": 6}})

    assert answered.status_code == 200, answered.text
    assert game.combat_damage_resolved
    assert game.players[1].life == 20
    assert not game.is_on_battlefield(guard)


_GROUPS = [
    "getCombatState", "getUnblockedAssignmentOffers", "getTrampleAssignmentOffers",
    "getBlockedAttackerGroups", "defenderAssignsAttackerDamage", "cardHasKeyword",
    "getAttackerAssignGroups", "getDividedAssignmentOffers", "withDividedAssignmentGroups",
    "getDefenderBandingGroups",
]


@needs_node
def test_the_dialog_lists_the_trampler_with_its_one_blocker():
    """The real ``getAttackerAssignGroups`` over the payload the server sent."""
    sid, _game, _beast, _guard = _to_combat_damage()

    groups = run_app_js(
        _GROUPS,
        """
        return getAttackerAssignGroups(INPUT.state).map((g) => ({
          attacker: g.attackerIdx, blockers: g.blockers.map((b) => b.blockerIdx),
          trample: g.trample, to: g.trampleTo,
        }));
        """,
        {"state": _state(sid, 0)},
        prelude="let seat = 0; let currentState = null;",
    )

    assert groups == [{
        "attacker": 0, "blockers": [0], "trample": True,
        "to": {"kind": "player", "seat": 1, "name": "Joiner"},
    }]


@needs_node
def test_the_defenders_dialog_lists_it_too():
    sid, _game, _beast, _guard = _to_combat_damage(blocker_text="Banding", blocker_toughness=2)

    groups = run_app_js(
        _GROUPS,
        """
        return getDefenderBandingGroups(INPUT.state).map((g) => ({
          attacker: g.attackerIdx, blockers: g.blockers.length, to: g.trampleTo,
        }));
        """,
        {"state": _state(sid, 1)},
        prelude="let seat = 1; let currentState = null;",
    )

    assert groups == [{"attacker": 0, "blockers": 1, "to": {"kind": "player", "seat": 1, "name": "Joiner"}}]
