"""CR 508.1d told to the attacking player, before and after they declare.

A person's declaration reaches the same gate the AI's does
(``Game.attack_requirement_refusal``), and a refused one is a 400 whose detail
names the requirement the player could have obeyed — and, when the
requirements cannot all be obeyed together, how many the declaration obeyed of
how many it had to. Before the click, the state carries
``combat.attack_requirements`` — every requirement on the active player's
creatures able to obey one and the most one legal declaration obeys
(``Game.attack_requirement_summary``, the gate's own numbers), the attack twin
of ``combat.block_requirements``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import _mk_creature_card
from web.app import app, store

client = TestClient(app)

_CARDS = {card.name: card for card in load_catalog()}


def _declare_attackers_board(mine):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "H", "host_colors": 2,
              "guest_colors": 2, "seed": 5},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.joined_seats.add(1)
    session.current_turn = 0
    game = session.game
    permanents = []
    for entry in mine:
        perm = Permanent(card=_CARDS[entry] if isinstance(entry, str) else entry)
        perm.metadata["summoning_sickness_turn"] = -99
        permanents.append(perm)
    game.players[0].battlefield = permanents
    game.players[1].battlefield = []
    game._sync_control()
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_attackers_locked = False
    return sid, game


def _combat(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()["combat"]


def _declare(sid, indices):
    return client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "declare_attackers", "attacker_indices": indices,
        "target_seat": 1,
    })


def test_the_state_says_what_the_attack_must_obey_and_the_gate_holds_it():
    sid, _game = _declare_attackers_board(
        ["Juggernaut", _mk_creature_card("Bear", 2, 2), "Dueling Grounds"]
    )
    (entry,) = _combat(sid)["attack_requirements"]
    assert entry == {
        "attacking_player_index": 0,
        "requirements": [{
            "attacker_index": 0, "reason": "Juggernaut must attack if able",
            "conditional": False,
        }],
        "most_obeyable": 1,
    }
    refused = _declare(sid, [1])
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Juggernaut must attack if able"
    accepted = _declare(sid, [0])
    assert accepted.status_code == 200, accepted.json()
    assert _combat(sid)["attack_requirements"] == [], "a declared combat owes nothing more"


def test_requirements_that_cannot_all_be_obeyed_say_the_count():
    sid, _game = _declare_attackers_board(
        ["Juggernaut", "Juggernaut", "Juggernaut", "Caverns of Despair"]
    )
    (entry,) = _combat(sid)["attack_requirements"]
    assert len(entry["requirements"]) == 3 and entry["most_obeyable"] == 2
    refused = _declare(sid, [2])
    assert refused.status_code == 400
    assert "obeys 1 of the 2 attack requirements" in refused.json()["detail"]
    assert _declare(sid, [0, 2]).status_code == 200


def test_a_conditional_requirement_is_marked_and_a_board_with_none_carries_none():
    sid, _game = _declare_attackers_board(
        ["Ekundu Cyclops", _mk_creature_card("Bear", 2, 2)]
    )
    (entry,) = _combat(sid)["attack_requirements"]
    assert entry["requirements"] == [{
        "attacker_index": 0, "reason": "Ekundu Cyclops must attack if able",
        "conditional": True,
    }]
    sid, _game = _declare_attackers_board([_mk_creature_card("Bear", 2, 2)])
    assert _combat(sid)["attack_requirements"] == []
    assert _combat(sid, seat=1)["attack_requirements"] == []
