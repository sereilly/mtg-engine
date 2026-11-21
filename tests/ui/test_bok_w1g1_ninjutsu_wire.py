"""Ninjutsu's server half (CR 702.49a): the offer a hand card carries during
the declare blockers step, and the body that activates it.

A person must be offered a Ninja's ninjutsu as a hand ability once blockers
are declared, and must choose which unblocked attacker goes home. The state's
``hand_abilities`` entry is that offer — ``payable`` false with ``unpayable``
saying why before the declaration (nothing is unblocked yet, CR 509.1h), and
``cost_spec`` the battlefield road's ``return_cost`` picker (CR 601.2b) — and
``activate_hand`` takes the answer as ``cost_permanent_ids``. The client half
(a picker over that spec on the hand button) is a wave-2 job; this pins the
wire it will read.

Betrayers of Kamigawa is ``measured``, so ``CARD_BY_NAME`` holds none of its
cards: the Ninja is handed to the session's game from ``set_pool("BOK")``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store

from ..helpers import _mk_creature_card, _nosick

client = TestClient(app)


def _session_in_combat(set_pool, *, declared_blocks: bool):
    """Seat 0 attacking with two 2/2 Runners, the Ninja in hand, holding
    priority in the declare blockers step — with the empty declaration made or
    not yet."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H",
        "host_colors": 2, "guest_colors": 2, "seed": 11,
    }).json()
    sid = created["session_id"]
    game = store.get(sid).game
    game.enforce_mana_costs = False
    for permanent in list(game.all_permanents()):
        game.remove_from_battlefield(permanent)
    runners = []
    for i in range(2):
        runner = _nosick(Permanent(card=_mk_creature_card(f"Runner {i}", 2, 2)))
        game._put_permanent_onto_battlefield(0, runner, None)
        _nosick(runner)
        runners.append(runner)
    game._sync_control()
    ninja = set_pool("BOK")["Ninja of the Deep Hours"]
    game.players[0].hand.append(ninja)
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0, 1], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    if declared_blocks:
        assert game.declare_blockers(1, {})[0]
    game.priority_player_index = 0
    return sid, game, runners, ninja


def _ninja_entry(sid):
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    return next(
        e for e in state["hand_abilities"] if e["name"] == "Ninja of the Deep Hours"
    )


def test_before_the_declaration_the_offer_is_shown_unpayable_and_says_why(set_pool):
    sid, _game, _runners, _ninja = _session_in_combat(set_pool, declared_blocks=False)
    entry = _ninja_entry(sid)
    assert entry["payable"] is False
    assert "return" in (entry["unpayable"] or "")
    assert entry["cost_text"].startswith("Ninjutsu {1}{U}")


def test_after_the_declaration_the_offer_names_the_return_it_asks_for(set_pool):
    sid, _game, _runners, _ninja = _session_in_combat(set_pool, declared_blocks=True)
    entry = _ninja_entry(sid)
    assert entry["payable"] is True
    assert entry["unpayable"] is None
    spec = entry["cost_spec"]
    assert spec["return_cost"] is True and spec["count"] == 1
    assert spec["own_only"] is True
    assert spec["filter"] == {"attacking_only": True, "unblocked_only": True}


def test_the_posted_body_returns_the_named_attacker(set_pool):
    """The body the hand button will build, with the picker's answer: the
    second Runner goes home, the first stays attacking, and the Ninja's
    ability is on the stack with the card still in hand (CR 702.49b)."""
    sid, game, runners, ninja = _session_in_combat(set_pool, declared_blocks=True)
    entry = _ninja_entry(sid)
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate_hand",
        "card_name": entry["name"], "hand_index": entry["hand_index"],
        "ability_index": entry["ability_index"],
        "cost_permanent_ids": [runners[1].permanent_id],
    })
    assert response.status_code == 200, response.text
    assert any(p is runners[0] for p in game.controlled_by(0))
    assert not any(p is runners[1] for p in game.controlled_by(0))
    assert "Runner 1" in [c.name for c in game.players[0].hand]
    assert any(c is ninja for c in game.players[0].hand) or any(
        p.card is ninja for p in game.controlled_by(0)
    )
