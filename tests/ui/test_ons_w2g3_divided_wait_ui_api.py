"""Butcher Orgg's division, the human seat's whole wire: the step waits.

W1G9 built the gate, the state block (``divided_assignment``) and the field
that announces a division (``divided_among_defenders`` on
``assign_combat_damage``), and exercised them at the one moment the server
already stopped — a double block. An unblocked or single-blocked Orgg was
dealt as the step was entered, so the person who controls it was never asked.
The engine now waits for them (``engine/phases/divided_damage_wait.py``) and
the client's damage dialog asks (``withDividedAssignmentGroups`` in
``web/static/app.js``). This file drives the wire the way that dialog does:
the state while the step waits, ``next_phase`` not running past it, a
division and a decline each landing, and a seat nobody sits in not stopped.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.combat_assignment import DIVIDED_AMONG_DEFENDERS_LOG
from engine.models import Permanent
from web.app import app, store

from tests.helpers import _mk_creature_card, run_app_js

client = TestClient(app)
APP_JS = Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"
needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _session() -> str:
    body = {
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 51023,
    }
    sid = client.post("/api/sessions", json=body).json()["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return sid


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _orgg_at_damage(set_pool, *, blockers: int):
    """Seat 0's Butcher Orgg attacks seat 1, who controls two 2/2s and a 0/9
    Wall; *blockers* of the 2/2s block it. Every step a client action. Returns
    the session at the combat damage step."""
    sid = _session()
    session = store.get(sid)
    game = session.game
    orgg = Permanent(card=set_pool("ONS")["Butcher Orgg"])
    bears = [Permanent(card=_mk_creature_card(f"Bear {n}", 2, 2)) for n in "AB"]
    wall = Permanent(card=_mk_creature_card("Wall", 0, 9))
    game.players[0].battlefield = [orgg]
    game.players[1].battlefield = [*bears, wall]
    for player in game.players:
        player.hand = []
        player.life = 20
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert _act(sid, seat=0, action="declare_attackers",
                attacker_indices=[0], target_seat=1).status_code == 200
    assert _act(sid, seat=0, action="next_phase").status_code == 200
    pairs = {str(i): 0 for i in range(blockers)}
    assert _act(sid, seat=1, action="declare_blockers", blocker_pairs=pairs).status_code == 200
    assert _act(sid, seat=0, action="next_phase").status_code == 200
    return sid, game, orgg, bears, wall


def test_w2g3_an_unblocked_orgg_holds_the_step_until_its_controller_divides(set_pool):
    sid, game, orgg, bears, wall = _orgg_at_damage(set_pool, blockers=0)
    state = _state(sid, 0)
    assert state["current_step"] == "combat_damage"
    assert not state["combat"]["damage_resolved"], "dealt without asking"
    (entry,) = state["divided_assignment"]["attackers"]
    assert entry["attacker_id"] == orgg.permanent_id and entry["damage"] == 6
    assert _state(sid, 1)["divided_assignment"] is None

    # Moving on does not run past the question.
    assert _act(sid, seat=0, action="next_phase").status_code == 200
    assert not _state(sid, 0)["combat"]["damage_resolved"]
    assert game.players[1].life == 20

    sent = _act(sid, seat=0, action="assign_combat_damage", attacker_damage={},
                as_though_unblocked_ids=[], divided_among_defenders={
                    str(orgg.permanent_id): {str(bears[0].permanent_id): 2,
                                             str(wall.permanent_id): 1, "player": 3},
                })
    assert sent.status_code == 200, sent.text
    assert game.players[1].life == 17
    assert not game.is_on_battlefield(bears[0]) and game.is_on_battlefield(bears[1])
    assert wall.damage_marked == 1
    assert any(DIVIDED_AMONG_DEFENDERS_LOG in line for line in game.log)
    assert _state(sid, 0)["divided_assignment"] is None


def test_w2g3_declining_is_the_assignment_without_the_orgg_in_it(set_pool):
    """One blocker: the dialog's "assign it normally" sends no division and no
    entry (CR 510.1c leaves nothing to divide), and all six go to the
    blocker."""
    sid, game, orgg, bears, wall = _orgg_at_damage(set_pool, blockers=1)
    assert not _state(sid, 0)["combat"]["damage_resolved"], "dealt without asking"
    assert _state(sid, 0)["divided_assignment"]["attackers"][0]["attacker_id"] == orgg.permanent_id
    sent = _act(sid, seat=0, action="assign_combat_damage", attacker_damage={},
                as_though_unblocked_ids=[])
    assert sent.status_code == 200, sent.text
    assert not game.is_on_battlefield(bears[0])
    assert game.players[1].life == 20 and wall.damage_marked == 0
    assert not any(DIVIDED_AMONG_DEFENDERS_LOG in line for line in game.log)


def test_w2g3_a_division_naming_a_recipient_with_nothing_is_a_400(set_pool):
    """The client leaves a 0 out; the server refuses one sent (minimum 1 point
    per player or creature, ruling 2004-10-04) and the step still waits."""
    sid, game, orgg, bears, _wall = _orgg_at_damage(set_pool, blockers=0)
    sent = _act(sid, seat=0, action="assign_combat_damage", divided_among_defenders={
        str(orgg.permanent_id): {str(bears[0].permanent_id): 0, "player": 6},
    })
    assert sent.status_code == 400, sent.text
    assert game.players[1].life == 20
    assert not _state(sid, 0)["combat"]["damage_resolved"]


_DIALOG = [
    "getCombatState", "getUnblockedAssignmentOffers", "getBlockedAttackerGroups",
    "defenderAssignsAttackerDamage", "cardHasKeyword", "getAttackerAssignGroups",
    "getDividedAssignmentOffers", "withDividedAssignmentGroups", "getCombatDraftStepKey",
    "getCombatDamagePassKey", "dividedDraftFor", "validateDividedGroup",
    "validateCombatDamageGroup", "collectDividedAmongDefenders",
    "dividedGroupSkipsAttackerDamage",
]
_DIALOG_PRELUDE = (
    "let seat = 0; let currentState = null; let combatDamageDialogMode = 'attacker';"
    " let combatDamageDraft = {}; let combatDamageOfferDraft = {};"
    " let combatDividedDraft = { key: '', byAttacker: {} };"
)


@needs_node
def test_w2g3_the_dialog_builds_the_division_the_server_accepts(set_pool):
    """The real dialog functions over the payload the server sent: the
    unblocked Orgg is a group with the offer, unanswered it cannot be
    confirmed, a division short of six cannot either, and the one it builds
    for "2 to a Bear, 4 to the player" is the body the route takes."""
    sid, game, orgg, bears, _wall = _orgg_at_damage(set_pool, blockers=0)
    state = _state(sid, 0)
    out = run_app_js(
        _DIALOG,
        """
        currentState = INPUT.state;
        const groups = getAttackerAssignGroups(INPUT.state);
        const g = groups[0];
        const unanswered = validateCombatDamageGroup(g).valid;
        const draft = dividedDraftFor(g);
        draft.answer = "divide";
        draft.shares = { player: 3, [String(INPUT.bear)]: 2 };
        const short = validateCombatDamageGroup(g);
        draft.shares = { player: 4, [String(INPUT.bear)]: 2, [String(INPUT.other)]: 0 };
        const full = validateCombatDamageGroup(g);
        return {
          count: groups.length, divide: !!g.divide, power: g.power, unanswered,
          short: short.valid, full: full.valid,
          skips: dividedGroupSkipsAttackerDamage(g),
          divided: collectDividedAmongDefenders(groups),
        };
        """,
        {"state": state, "bear": bears[0].permanent_id, "other": bears[1].permanent_id},
        prelude=_DIALOG_PRELUDE,
    )
    assert out["count"] == 1 and out["divide"] and out["power"] == 6
    assert out["unanswered"] is False, "the question is asked, not pre-answered"
    assert out["short"] is False and out["full"] is True and out["skips"] is True
    assert out["divided"] == {
        str(orgg.permanent_id): {"player": 4, str(bears[0].permanent_id): 2},
    }, "a recipient given 0 is not named"
    sent = _act(sid, seat=0, action="assign_combat_damage", attacker_damage={},
                as_though_unblocked_ids=[], divided_among_defenders=out["divided"])
    assert sent.status_code == 200, sent.text
    assert game.players[1].life == 16 and not game.is_on_battlefield(bears[0])


def test_w2g3_the_client_reads_the_block_and_sends_the_division():
    """The two halves the dialog is made of, by name: the getter reads
    ``state.divided_assignment`` and the confirm announces
    ``divided_among_defenders`` on ``assign_combat_damage``."""
    js = APP_JS.read_text(encoding="utf-8")
    getter = re.search(r"\nfunction getDividedAssignmentOffers\(.*?\n\}\n", js, re.S).group(0)
    assert "state?.divided_assignment" in getter
    assert "announcement.divided_among_defenders = dividedAmongDefenders" in js
    groups = re.search(r"\nfunction getAttackerAssignGroups\(.*?\n\}\n", js, re.S).group(0)
    assert "withDividedAssignmentGroups(" in groups
