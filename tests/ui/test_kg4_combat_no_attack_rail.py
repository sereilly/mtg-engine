"""A turn nobody attacks on has no declare blockers or combat damage step to
stop at (CR 508.8), on the web as in the engine.

The phase rail lets a person flag a step to be handed priority in it. Before
CR 508.8 was kept, a combat with no attack still entered the declare blockers
step and the combat damage step, so a person who had flagged either was handed
priority there on an AI's turn with nobody attacking — in a step the rules do
not have — and on their own turn the Next button walked them into the declare
blockers step after declaring nobody. Now the engine never enters either step,
and the rail lands the person in the next step that exists: the end of
combat's, if they flagged it.
"""
from __future__ import annotations

from tests.helpers import client, combat_ids
from web.app import store

SKIPPED = ("declare_blockers", "combat_damage")


def _session(seed: int, *, ai_turn: bool) -> str:
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "guest_name": "AI",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": seed,
        },
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    # Nobody has a creature, so nothing can attack and nothing can block.
    for player in game.players:
        player.battlefield = []
    game.players[1].hand = []
    seat = 1 if ai_turn else 0
    session.current_turn = seat
    game.active_player_index = seat
    return sid


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


def test_a_person_who_flagged_the_skipped_steps_is_not_stopped_on_an_ai_turn_with_no_attack():
    """The AI (seat 1) has nothing to attack with. The person flagged declare
    blockers, combat damage and end of combat on the opponent's rail: they
    are handed priority at the end of combat and nowhere in between."""
    sid = _session(84001, ai_turn=True)
    game = store.get(sid).game
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.start_priority_window(1)
    rail = {"stop_steps": [*SKIPPED, "end_of_combat"]}

    handed: list[str] = []
    seen: list[str] = []
    for _ in range(30):
        state = _state(sid)
        if state["current_turn"] != 1:
            break
        seen.append(state["current_step"])
        if state["priority_player"] == 0:
            handed.append(state["current_step"])
            response = client.post(
                f"/api/sessions/{sid}/action",
                json={"seat": 0, "action": "pass_priority", **rail},
            )
        else:
            response = client.post(
                f"/api/sessions/{sid}/action",
                json={"seat": 0, "action": "ai_step", **rail},
            )
        assert response.status_code == 200, response.text
        seen.append(response.json()["current_step"])

    assert "end_of_combat" in handed, (handed, seen)
    assert not set(SKIPPED) & set(handed), handed
    assert not set(SKIPPED) & set(seen), seen
    assert any("steps skipped (508.8)" in line for line in game.log), game.log[-8:]


def test_declaring_nobody_on_ones_own_turn_moves_on_to_the_end_of_combat():
    """The person (seat 0) declares no attackers with declare blockers and
    combat damage flagged on their own rail: Next goes to the end of combat,
    where they hold priority (CR 511.1)."""
    sid = _session(84002, ai_turn=False)
    game = store.get(sid).game
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_attackers_locked = False

    declared = client.post(
        f"/api/sessions/{sid}/action",
        json=combat_ids(game, {
            "seat": 0, "action": "declare_attackers", "attacker_indices": [], "target_seat": 1,
        }),
    )
    assert declared.status_code == 200, declared.text

    moved = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "next_phase", "self_stop_steps": list(SKIPPED)},
    )
    assert moved.status_code == 200, moved.text
    payload = moved.json()
    assert payload["current_step"] == "end_of_combat", payload["current_step"]
    assert payload["priority_player"] == 0
