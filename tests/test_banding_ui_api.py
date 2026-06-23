"""Web-API tests for the interactive banding UI flow (CR 702.22).

These cover the HTTP plumbing the canvas front-end drives:
  * declaring an attacking band (`bands` on declare_attackers),
  * the defending player's CR 702.22j damage-split prompt (`banding_assignment`
    in the serialized state), and
  * the `assign_banding_damage` action plus the guard that stops the active
    player from resolving combat damage before the defender has assigned.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import CardDefinition, Permanent
from web.app import app, store


client = TestClient(app)


def _creature(name: str, power: int, toughness: int, *, banding: bool = False) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature - Test",
        oracle_text="Banding" if banding else "",
        colors=(),
        color_identity=(),
        keywords=("Banding",) if banding else (),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test", "power": str(power), "toughness": str(toughness)},
    )


def _new_hvh_session() -> str:
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 70122,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return sid


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


# ---------------------------------------------------------------------------
# Band declaration (CR 702.22c)
# ---------------------------------------------------------------------------

def test_declare_attackers_accepts_a_band():
    sid = _new_hvh_session()
    session = store.get(sid)
    game = session.game
    # Two attackers, one with banding — a legal band.
    game.players[0].battlefield = [
        Permanent(card=_creature("Wolf", 1, 1, banding=True)),
        Permanent(card=_creature("Beater", 3, 3)),
    ]
    game.players[1].battlefield = [Permanent(card=_creature("Blocker", 3, 3))]
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "declare_attackers",
            "attacker_indices": [0, 1],
            "target_seat": 1,
            "bands": [[0, 1]],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["combat"]["bands"] == [[0, 1]]


def test_declare_attackers_rejects_an_illegal_band():
    sid = _new_hvh_session()
    session = store.get(sid)
    game = session.game
    # Two non-banding attackers cannot form a band (CR 702.22c).
    game.players[0].battlefield = [
        Permanent(card=_creature("Bear", 2, 2)),
        Permanent(card=_creature("Beater", 3, 3)),
    ]
    game.players[1].battlefield = [Permanent(card=_creature("Blocker", 3, 3))]
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "declare_attackers",
            "attacker_indices": [0, 1],
            "target_seat": 1,
            "bands": [[0, 1]],
        },
    )
    assert resp.status_code == 400
    assert "band" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Defender banding damage assignment (CR 702.22j)
# ---------------------------------------------------------------------------

def _to_banding_combat_damage(sid: str):
    """Drive the session's game to the combat_damage step with an attacker blocked
    by the defender's banding creature plus a vanilla chump."""
    session = store.get(sid)
    game = session.game
    game.players[0].battlefield = [Permanent(card=_creature("Ogre", 3, 3))]
    game.players[1].battlefield = [
        Permanent(card=_creature("Wolf", 1, 1, banding=True)),  # defender index 0
        Permanent(card=_creature("Chump", 2, 2)),               # defender index 1
    ]
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, msg = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    ok, msg = game.declare_blockers(1, {0: 0, 1: 0})  # both block the Ogre
    assert ok, msg
    game.advance_combat_phase()  # combat_damage
    assert game.current_step == "combat_damage"
    return session, game


def test_defender_sees_banding_assignment_prompt():
    sid = _new_hvh_session()
    _to_banding_combat_damage(sid)

    # The defender (seat 1) is prompted to split the banded attacker's damage.
    defender_state = _state(sid, 1)
    assert defender_state["banding_assignment"] is not None
    assert defender_state["banding_assignment"]["defender_seat"] == 1
    assert defender_state["banding_assignment"]["attacker_indices"] == [0]

    # The active player (seat 0) is not the one who assigns it.
    assert _state(sid, 0)["banding_assignment"] is None


def test_active_player_cannot_advance_until_banding_is_assigned():
    sid = _new_hvh_session()
    _to_banding_combat_damage(sid)

    blocked = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "next_phase"},
    )
    assert blocked.status_code == 400
    assert "banding" in blocked.json()["detail"].lower()


def test_defender_assigns_banding_damage_and_combat_resolves():
    sid = _new_hvh_session()
    session, game = _to_banding_combat_damage(sid)

    # Defender dumps all 3 onto their own banding Wolf, sparing the Chump.
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "assign_banding_damage", "banding_damage": {"0": {"0": 3, "1": 0}}},
    )
    assert resp.status_code == 200, resp.text

    # The prompt clears once the assignment is recorded.
    assert _state(sid, 1)["banding_assignment"] is None

    # The active player resolves; the engine honors the defender's split.
    game.priority_player_index = 0
    resolve = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "assign_combat_damage", "attacker_damage": {}},
    )
    assert resolve.status_code == 200, resolve.text

    names = [p.card.name for p in game.players[1].battlefield]
    assert "Wolf" not in names   # absorbed all 3 damage
    assert "Chump" in names      # saved by the defender's banding split


def test_only_the_defender_may_assign_banding_damage():
    sid = _new_hvh_session()
    _to_banding_combat_damage(sid)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "assign_banding_damage", "banding_damage": {"0": {"0": 3}}},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Regression: a human attacking with a band that the opponent blocks must not
# deadlock combat (Benalish Hero — "the game got stuck passing priority back and
# forth in a loop"). The propagated single shared blocker (CR 702.22h) has no
# dialog to present, so the server auto-resolves instead of looping forever.
# ---------------------------------------------------------------------------

def _new_hva_session() -> str:
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 70123,
        },
    ).json()
    return created["session_id"]


def test_human_band_attack_blocked_by_ai_does_not_deadlock_combat():
    sid = _new_hva_session()
    session = store.get(sid)
    game = session.game
    # Human (seat 0) attacks with a band; the AI (seat 1) has one blocker.
    game.players[0].battlefield = [
        Permanent(card=_creature("Hero", 1, 1, banding=True)),
        Permanent(card=_creature("Beater", 3, 3)),
    ]
    for perm in game.players[0].battlefield:
        perm.metadata["summoning_sickness_turn"] = -99
    game.players[1].battlefield = [Permanent(card=_creature("Blocker", 2, 2))]
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")

    declared = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "declare_attackers",
            "attacker_indices": [0, 1],
            "target_seat": 1,
            "bands": [[0, 1]],
        },
    )
    assert declared.status_code == 200, declared.text

    # Drive the turn the way the client does: pass when we hold priority, otherwise
    # advance the phase. A bounded loop — if the deadlock regresses this never
    # leaves combat_damage and the assertion below fires instead of hanging.
    progressed = False
    for _ in range(15):
        action = "pass_priority" if game.priority_player_index == 0 else "next_phase"
        resp = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": action})
        assert resp.status_code == 200, resp.text
        if session.current_turn != 0 or game.current_step in ("end", "cleanup"):
            progressed = True
            break

    assert progressed, "combat deadlocked at the band block instead of resolving"
    # The lone blocker took combat damage from the band and died — proof the damage
    # step actually resolved rather than spinning on priority.
    assert not any(p.card.name == "Blocker" for p in game.players[1].battlefield)
