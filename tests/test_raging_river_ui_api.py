"""Web-API tests for Raging River's left/right pile assignment.

Raging River was reported FAILED in-game: "Ability triggered but opponent (AI)
didn't divide their creatures into left and right piles and I didn't get to assign
my attackers to each pile." The division is now real combat state: the defending
player divides their non-flying creatures and the attacking player labels each
attacker, surfaced as `raging_river` and set via assign_defender_piles /
assign_attacker_piles.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from engine import load_cards
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_CARDS = {c.name: c for c in load_cards(Path(__file__).resolve().parent.parent / "lea_cards.json")}


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 7777,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.players[0].battlefield = [
        Permanent(card=_CARDS["Raging River"]),
        Permanent(card=_CARDS["Grizzly Bears"]),  # attacker index 1
    ]
    game.players[0].battlefield[1].metadata["summoning_sickness_turn"] = -99
    game.players[1].battlefield = [
        Permanent(card=_CARDS["Hill Giant"]),        # defender index 0
        Permanent(card=_CARDS["Hurloon Minotaur"]),  # defender index 1
    ]
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_defending_player_index = 1
    game.declare_attackers(0, [1], 1)
    game.resolve_stack()  # Raging River's attack trigger resolves; piles seeded
    return sid, session, game


def test_both_players_are_prompted_to_assign_piles():
    sid, session, game = _session()

    attacker_view = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["raging_river"]
    assert attacker_view is not None
    assert [a["index"] for a in attacker_view["label_attackers"]] == [1]

    defender_view = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()["raging_river"]
    assert defender_view is not None
    assert {c["index"] for c in defender_view["divide_creatures"]} == {0, 1}


def test_assigning_piles_via_the_api():
    sid, session, game = _session()

    r1 = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "assign_defender_piles", "piles": {"0": "left", "1": "right"}},
    )
    assert r1.status_code == 200, r1.text
    r2 = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "assign_attacker_piles", "piles": {"1": "left"}},
    )
    assert r2.status_code == 200, r2.text

    assert game.combat_defender_piles == {0: "left", 1: "right"}
    assert game.combat_attacker_piles == {1: "left"}


def test_attacker_prompt_clears_after_assignment():
    """Reported FAILED: "Got stuck on the raging river prompt." After both players
    commit their piles the prompt must stop re-appearing (the seeded default piles
    otherwise made it look perpetually pending)."""
    sid, session, game = _session()
    # Defender commits, then attacker commits.
    client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "assign_defender_piles", "piles": {"0": "left", "1": "right"}},
    )
    client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "assign_attacker_piles", "piles": {"1": "left"}},
    )
    attacker_view = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["raging_river"]
    defender_view = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()["raging_river"]
    assert attacker_view is None
    assert defender_view is None


def test_no_prompt_when_defender_has_no_nonflying_creatures():
    """With no creatures to divide, the defender should never be prompted, and the
    attacker prompt should clear once they label — no infinite prompt loop."""
    sid, session, game = _session()
    game.players[1].battlefield = []  # remove the defender's would-be blockers
    # The defender has nothing to divide -> no prompt for them.
    defender_view = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()["raging_river"]
    assert defender_view is None
    # The attacker still labels, then their prompt clears.
    client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "assign_attacker_piles", "piles": {"1": "left"}},
    )
    attacker_view = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["raging_river"]
    assert attacker_view is None


def test_wrong_pile_block_is_rejected_after_assignment():
    sid, session, game = _session()
    client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "assign_defender_piles", "piles": {"0": "left", "1": "right"}},
    )
    client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "assign_attacker_piles", "piles": {"1": "left"}},
    )
    game.advance_combat_phase()  # -> declare_blockers

    # Minotaur (right pile) blocking a left-pile attacker is illegal.
    bad = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "declare_blockers", "blocker_pairs": {"1": 1}},
    )
    assert bad.status_code == 400
    assert "pile" in bad.json()["detail"].lower()
