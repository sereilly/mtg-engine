"""CR 509.1c told to the declaring player before they declare.

kg/blocks made the declaration gate compute the maximisation, and a refused
declaration's 400 names the requirement and the count — which the browser
shows in its action hint (driven: three Watchdogs under Caverns of Despair,
one declared, "Watchdog blocks each combat if able (this declaration obeys 1
of the 2 blocking requirements that can be obeyed together)"). That is the
refusal; nothing said it *before* the click. The state now carries
``combat.block_requirements`` — per defending player, every requirement and
the most one legal declaration obeys (``Game.block_requirement_summary``, the
gate's own numbers) — and the Declare Blockers panel lists them
(``blockRequirementLines``).
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import _mk_creature_card, run_app_js
from web.app import app, store
from tests.helpers import combat_ids

client = TestClient(app)

_CARDS = {card.name: card for card in load_catalog()}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _declare_blockers_board(*, caverns: bool = True, defenders=("Watchdog",) * 3):
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
    raider = Permanent(card=_mk_creature_card("Raider", 2, 2))
    raider.metadata["summoning_sickness_turn"] = -99
    watchdogs = [Permanent(card=_CARDS[name]) for name in defenders]
    for dog in watchdogs:
        dog.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield = [raider] + (
        [Permanent(card=_CARDS["Caverns of Despair"])] if caverns else []
    )
    game.players[1].battlefield = watchdogs
    game._sync_control()
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_defending_player_index = 1
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    return sid, game


def _combat(sid: str, seat: int = 1) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()["combat"]


def test_the_state_says_what_the_declaration_must_obey():
    sid, game = _declare_blockers_board()
    (entry,) = _combat(sid)["block_requirements"]
    assert entry["defending_player_index"] == 1
    assert [r["reason"] for r in entry["requirements"]] == [
        "Watchdog blocks each combat if able"
    ] * 3
    assert sorted(r["blocker_index"] for r in entry["requirements"]) == [0, 1, 2]
    assert entry["most_obeyable"] == 2
    # The numbers are the gate's: one blocker is refused with them, two taken.
    refused = client.post(f"/api/sessions/{sid}/action", json=combat_ids(store.get(sid).game, {
        "seat": 1, "action": "declare_blockers", "blocker_pairs": {"0": 0},
    }))
    assert refused.status_code == 400
    assert "obeys 1 of the 2" in refused.json()["detail"]
    accepted = client.post(f"/api/sessions/{sid}/action", json=combat_ids(store.get(sid).game, {
        "seat": 1, "action": "declare_blockers", "blocker_pairs": {"0": 0, "1": 0},
    }))
    assert accepted.status_code == 200, accepted.json()
    assert _combat(sid)["block_requirements"] == [], "a declared combat owes nothing more"


def test_every_requirement_obeyable_says_so_without_a_count():
    sid, _game = _declare_blockers_board(caverns=False, defenders=("Watchdog",) * 2)
    (entry,) = _combat(sid)["block_requirements"]
    assert len(entry["requirements"]) == 2 and entry["most_obeyable"] == 2


def test_a_combat_with_no_requirement_carries_none():
    sid, _game = _declare_blockers_board(defenders=("Grizzly Bears",))
    assert _combat(sid)["block_requirements"] == []


@needs_node
def test_the_panel_lists_the_requirement_once_and_the_count():
    sid, _game = _declare_blockers_board()
    combat = _combat(sid)
    out = run_app_js(
        ["blockRequirementLines"],
        "return [blockRequirementLines(INPUT.combat, 1), blockRequirementLines(INPUT.combat, 0)];",
        {"combat": combat},
    )
    assert out[0] == [
        "Required: Watchdog blocks each combat if able (×3).",
        "Only 2 of these 3 requirements can be obeyed together — your declaration must obey 2 (CR 509.1c).",
    ]
    assert out[1] == [], "the attacking seat is told nothing about its opponent's declaration"
