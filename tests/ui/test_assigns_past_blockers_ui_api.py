"""An attacker that assigns its combat damage as though it weren't blocked
**whatever is announced** has no division for anybody to ask about.

"{G}{G}, Discard a card: You may have this creature assign its combat damage
this turn as though it weren't blocked." (Gurzigost.) Once the offer is
answered yes the creature carries Outmaneuver's mandatory mark, and the
damage step sends every point past its blockers and discards whatever
division was announced (``Game._assign_attacker_combat_damage``). The step
still stopped for one, and the client still asked for one:

Found in the running app at the Torment promotion's Phase 5 (2026-10-21):
Gurzigost, its offer answered yes, attacked into four blockers. The combat
damage step stopped on "Assign Combat Damage", the dialog asked for six
damage divided among Centaur Veteran, Nantuko Shade, Faceless Butcher and
Gurzigost, a person divided it 3/1/2/0 and confirmed, and all six were dealt
to the defending player with every blocker unhurt. The outcome was the
card's; the question was one whose answer went nowhere.

Now the step does not wait for such an attacker
(``Game.assigns_past_its_blockers``), the combat payload names it
(``assigns_past_blockers``), and the client's dialog leaves it out
(``getAttackerAssignGroups``) when another attacker's division keeps the
dialog open.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.combat_assignment import MUST_ASSIGN_AS_UNBLOCKED
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


def _wall(name: str):
    return _mk_creature_card(name, 0, 4)


def _to_combat_damage(attackers, blockers, blocks, *, marked=(0,)):
    """Seat 0 attacks seat 1 with *attackers*, the ones at *marked* carrying
    the mandatory mark (Gurzigost's offer taken; Outmaneuver), and *blockers*
    block as *blocks* says. Every step is an action a client sends."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 51021,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    mine = [Permanent(card=card) for card in attackers]
    theirs = [Permanent(card=card) for card in blockers]
    game.players[0].battlefield = list(mine)
    game.players[1].battlefield = list(theirs)
    game.players[0].life = game.players[1].life = 20
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")

    declared = _act(
        sid, seat=0, action="declare_attackers",
        attacker_indices=list(range(len(mine))), target_seat=1,
    )
    assert declared.status_code == 200, declared.text
    for slot in marked:
        mine[slot].metadata[MUST_ASSIGN_AS_UNBLOCKED] = True
    assert _act(sid, seat=0, action="next_phase").status_code == 200
    blocked = _act(sid, seat=1, action="declare_blockers", blocker_pairs=blocks)
    assert blocked.status_code == 200, blocked.text
    advanced = _act(sid, seat=0, action="next_phase")
    assert advanced.status_code == 200, advanced.text
    return sid, game, mine, theirs


def test_a_marked_attacker_blocked_by_two_does_not_stop_the_step():
    bear = _mk_creature_card("Marked Bear", 6, 8)
    sid, game, (attacker,), walls = _to_combat_damage(
        [bear], [_wall("Wall A"), _wall("Wall B")], {"0": 0, "1": 0},
    )

    state = _state(sid, 0)
    assert state["combat"]["damage_resolved"] is True, (
        "the step waited for a division nobody's answer could change"
    )
    assert game.players[1].life == 14
    assert [wall.damage_marked for wall in walls] == [0, 0]


def test_the_engine_says_there_is_nothing_to_divide():
    """The two predicates the web flow reads, asked directly with the step
    held open by an ordinary double block beside the marked one."""
    sid, game, _mine, _walls = _to_combat_damage(
        [_mk_creature_card("Marked Bear", 6, 8), _mk_creature_card("Plain Bear", 3, 3)],
        [_wall("Wall A"), _wall("Wall B"), _wall("Wall C"), _wall("Wall D")],
        {"0": 0, "1": 0, "2": 1, "3": 1},
    )

    assert game.assigns_past_its_blockers(0) is True
    assert game.assigns_past_its_blockers(1) is False
    assert game._needs_manual_damage_assignment(), "the plain bear owes its division"
    combat = _state(sid, 0)["combat"]
    assert combat["damage_resolved"] is False
    assert combat["assigns_past_blockers"] == [0]
    # Every seat is told: a defender's client draws the same dialog-less combat.
    assert _state(sid, 1)["combat"]["assigns_past_blockers"] == [0]


def test_answering_only_the_ordinary_division_deals_both():
    sid, game, _mine, walls = _to_combat_damage(
        [_mk_creature_card("Marked Bear", 6, 8), _mk_creature_card("Plain Bear", 3, 3)],
        [_wall("Wall A"), _wall("Wall B"), _wall("Wall C"), _wall("Wall D")],
        {"0": 0, "1": 0, "2": 1, "3": 1},
    )

    answered = _act(
        sid, seat=0, action="assign_combat_damage",
        attacker_damage={"1": {"2": 1, "3": 2}},
    )

    assert answered.status_code == 200, answered.text
    assert game.combat_damage_resolved
    assert game.players[1].life == 14
    assert [wall.damage_marked for wall in walls] == [0, 0, 1, 2]


def test_an_unmarked_double_block_still_stops():
    """The neighbour that must keep working: no mark, a division owed."""
    sid, game, _mine, _walls = _to_combat_damage(
        [_mk_creature_card("Plain Bear", 3, 3)], [_wall("Wall A"), _wall("Wall B")],
        {"0": 0, "1": 0}, marked=(),
    )

    combat = _state(sid, 0)["combat"]
    assert combat["damage_resolved"] is False
    assert combat["assigns_past_blockers"] == []
    assert game._manual_assignment_has_declared_multiblock()


_GROUPS = [
    "getCombatState", "getUnblockedAssignmentOffers", "getBlockedAttackerGroups",
    "defenderAssignsAttackerDamage", "cardHasKeyword", "getAttackerAssignGroups",
]


@needs_node
def test_the_dialog_leaves_the_marked_attacker_out():
    """The real ``getAttackerAssignGroups`` over the payload the server sent:
    the plain bear's division is asked, the marked one is not."""
    sid, _game, _mine, _walls = _to_combat_damage(
        [_mk_creature_card("Marked Bear", 6, 8), _mk_creature_card("Plain Bear", 3, 3)],
        [_wall("Wall A"), _wall("Wall B"), _wall("Wall C"), _wall("Wall D")],
        {"0": 0, "1": 0, "2": 1, "3": 1},
    )

    groups = run_app_js(
        _GROUPS,
        "return getAttackerAssignGroups(INPUT.state).map((g) => g.attackerIdx);",
        {"state": _state(sid, 0)},
        prelude="let seat = 0; let currentState = null;",
    )

    assert groups == [1]


@needs_node
def test_without_the_field_the_dialog_is_what_it_was():
    """An older payload (no ``assigns_past_blockers``) loses nothing: both
    double blocks are asked about, as they always were."""
    sid, _game, _mine, _walls = _to_combat_damage(
        [_mk_creature_card("Marked Bear", 6, 8), _mk_creature_card("Plain Bear", 3, 3)],
        [_wall("Wall A"), _wall("Wall B"), _wall("Wall C"), _wall("Wall D")],
        {"0": 0, "1": 0, "2": 1, "3": 1},
    )
    state = _state(sid, 0)
    del state["combat"]["assigns_past_blockers"]

    groups = run_app_js(
        _GROUPS,
        "return getAttackerAssignGroups(INPUT.state).map((g) => g.attackerIdx);",
        {"state": state},
        prelude="let seat = 0; let currentState = null;",
    )

    assert groups == [0, 1]
