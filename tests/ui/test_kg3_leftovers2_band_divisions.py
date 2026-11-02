"""A blocked band's divisions are asked of the player who owes them.

CR 702.22h: a creature blocking one member of an attacking band blocks every
member, so a band blocked by two creatures leaves each member with two
blockers — and each member's combat damage is then a division among them
(CR 510.1c), its controller's, while each blocker's is the *active* player's
to divide among the band (CR 702.22k). Both are the active player's
announcement (CR 510.1).

Found by kg3/client2 in the browser: Hill Giant and Benalish Hero banded,
blocked by Wall of Stone and Gray Ogre. The band-blocker dialog posted the
Ogre's split alone, the step was dealt, and the Giant's 3 all went to the Wall
— the attacking player was never asked how it divides. Three readings left
the band's spread blocks out:

* the client's damage dialog grouped an attacker's blockers from the declared
  pairs (``combat.blockers``) alone, never ``combat.band_blocks``, so the
  Giant had one blocker there and no division to ask;
* the engine's "can a dialog surface this?"
  (``_manual_assignment_has_declared_multiblock``) counted declared blockers,
  so where no CR 702.22k choice held the step (two walls with no power) the
  web dealt the default without asking;
* the defending player's CR 702.22j list (``defender_assignments_owed``, and
  the ``banding_assignment`` it serves) counted declared blockers too.

And the band-blocker dialog now hands its split to the attacker division and
the two go as one announcement (``heldBandBlockerSplit``), driven in the
browser.

Measured backwards on 90bef6d1: the client grouped no attacker on the Wall and
Ogre board, the powerless walls' step was dealt with the Giant's default, and
the defending player was owed nothing on the both-sides-banding board.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store

from tests.helpers import combat_ids, run_app_js

client = TestClient(app)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_POOL = {card.name: card for card in load_catalog()}


def _perm(name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _band_blocked(theirs: list[str], pairs: dict, *, mine=("Hill Giant", "Benalish Hero")):
    """Two people. Seat 0 attacks with *mine* as one band; seat 1 declares
    *pairs* ({blocker slot: attacker slot}) with *theirs*; the players pass
    into the combat damage step the way the client does."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 70122,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    attackers = [_perm(name) for name in mine]
    blockers = [_perm(name) for name in theirs]
    game.players[0].battlefield = list(attackers)
    game.players[1].battlefield = list(blockers)
    game._sync_control()
    for player in game.players:
        player.hand = []
        player.life = 20
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    declared = _act(sid, **combat_ids(game, {
        "seat": 0, "action": "declare_attackers", "attacker_indices": [0, 1],
        "target_seat": 1, "bands": [[0, 1]],
    }))
    assert declared.status_code == 200, declared.text
    for _ in range(10):
        if game.current_step == "declare_blockers":
            break
        assert _act(sid, seat=game.priority_player_index, action="pass_priority").status_code == 200
    blocked = _act(sid, **combat_ids(game, {
        "seat": 1, "action": "declare_blockers", "blocker_pairs": pairs,
    }))
    assert blocked.status_code == 200, blocked.text
    for _ in range(10):
        if game.current_step == "combat_damage" or game.combat_damage_resolved:
            break
        assert _act(sid, seat=game.priority_player_index, action="pass_priority").status_code == 200
    return sid, game, attackers, blockers


_GROUP_FUNCTIONS = [
    "getAttackerAssignGroups", "getUnblockedAssignmentOffers",
    "getTrampleAssignmentOffers", "getCombatState", "withDividedAssignmentGroups",
    "getDividedAssignmentOffers", "getBlockedAttackerGroups", "cardHasKeyword",
    "defenderAssignsAttackerDamage", "getDefenderBandingGroups",
]


def _client_groups(state: dict, *, seat: int = 0, banding: bool = False) -> list:
    """The damage dialog's groups as the client draws them from *state*:
    each attacker's name and the names of the creatures blocking it."""
    return run_app_js(
        _GROUP_FUNCTIONS,
        f"""
        const state = INPUT;
        const groups = {"getDefenderBandingGroups" if banding else "getAttackerAssignGroups"}(state);
        return groups.map((g) => [g.attackerCard.name, g.blockers.map((b) => b.card.name).sort()]);
        """,
        state,
        prelude=f"let seat = {seat}; let currentState = null;",
    )


# ---------------------------------------------------------------------------
# The attacking player's two divisions (CR 510.1c, CR 702.22k)
# ---------------------------------------------------------------------------


def test_the_band_spreads_each_blocker_and_the_attacker_owes_both_divisions():
    sid, game, (giant, hero), (wall, ogre) = _band_blocked(
        ["Wall of Stone", "Gray Ogre"], {"0": 0, "1": 1},
    )

    assert game.current_step == "combat_damage"
    assert not game.combat_damage_resolved, "the step waits for the attacking player"
    # CR 702.22h: each member is blocked by both.
    assert [game.permanent_at(1, slot) for slot in game._attacker_all_blockers(0)] == [wall, ogre]
    assert [game.permanent_at(1, slot) for slot in game._attacker_all_blockers(1)] == [wall, ogre]
    assert game._manual_assignment_has_declared_multiblock(), "a dialog can surface it"
    state = _state(sid, 0)
    # CR 702.22k: the Ogre's damage is the attacking player's to divide (the
    # Wall has none to divide).
    assert [entry["member_indices"] for entry in state["band_blocker_assignment"]["blockers"]] == [[0, 1]]
    assert state["band_blocker_assignment"]["blockers"][0]["blocker_idx"] == game.battlefield_index_of(ogre)


@needs_node
def test_the_client_groups_each_band_member_with_every_creature_blocking_it():
    """Backwards on 90bef6d1 this was ``[]``: each member had one declared
    blocker, so the dialog asked about neither member's damage."""
    sid, _game, _mine, _theirs = _band_blocked(["Wall of Stone", "Gray Ogre"], {"0": 0, "1": 1})

    assert _client_groups(_state(sid, 0)) == [
        ["Hill Giant", ["Gray Ogre", "Wall of Stone"]],
        ["Benalish Hero", ["Gray Ogre", "Wall of Stone"]],
    ]


@needs_node
def test_the_band_blocker_split_waits_for_the_attackers_division():
    """The band-blocker dialog's choice is held while the attacker's own
    division is still to come (``bandBlockerSplitWaits``), and handed back for
    the one announcement only in the combat damage step it was made in."""
    sid, _game, _mine, _theirs = _band_blocked(["Wall of Stone", "Gray Ogre"], {"0": 0, "1": 1})
    state = _state(sid, 0)

    seen = run_app_js(
        [*_GROUP_FUNCTIONS, "bandBlockerSplitWaits", "heldBandBlockerSplit",
         "getCombatDamagePassKey", "getCombatDraftStepKey"],
        """
        const state = INPUT;
        const waits = bandBlockerSplitWaits(state);
        const before = heldBandBlockerSplit(state);
        combatBandBlockerHeld = { key: getCombatDamagePassKey(state), split: { 7: { 8: 2 } } };
        const held = heldBandBlockerSplit(state);
        const later = heldBandBlockerSplit({ ...state, combat: { ...state.combat, first_strike_done: true } });
        return { waits, before, held, later };
        """,
        state,
        prelude="let seat = 0; let currentState = null; let combatBandBlockerHeld = null;",
    )

    assert seen == {"waits": True, "before": None, "held": {"7": {"8": 2}}, "later": None}


def test_one_announcement_deals_both_divisions():
    """What the dialogs send: the Giant's 3 divided 1 to the Wall and 2 to
    the Ogre, the Hero's 1 to the Ogre, and the Ogre's 2 onto the Hero."""
    sid, game, (giant, hero), (wall, ogre) = _band_blocked(
        ["Wall of Stone", "Gray Ogre"], {"0": 0, "1": 1},
    )

    answered = _act(
        sid, seat=0, action="assign_combat_damage",
        attacker_damage_by_id={
            str(giant.permanent_id): {str(wall.permanent_id): 1, str(ogre.permanent_id): 2},
            str(hero.permanent_id): {str(ogre.permanent_id): 1},
        },
        blocker_damage_split_by_id={
            str(ogre.permanent_id): {str(giant.permanent_id): 0, str(hero.permanent_id): 2},
        },
    )

    assert answered.status_code == 200, answered.text
    assert game.combat_damage_resolved
    assert not game.is_on_battlefield(ogre), "3 damage on a 2/2"
    assert wall.damage_marked == 1
    assert not game.is_on_battlefield(hero), "the Ogre's 2 went to the Hero"
    assert game.is_on_battlefield(giant) and giant.damage_marked == 0


def test_a_band_blocked_by_powerless_walls_waits_for_the_attackers_division():
    """No blocker has power, so there is no CR 702.22k choice to hold the step
    — and each member still has two blockers to divide among (CR 510.1c).
    Backwards on 90bef6d1 the web dealt the engine's default when the
    attacking player moved on, all 3 of the Giant's onto the Wall of Stone."""
    sid, game, (giant, hero), (stone, wood) = _band_blocked(
        ["Wall of Stone", "Wall of Wood"], {"0": 0, "1": 1},
    )

    assert game.current_step == "combat_damage"
    moved = _act(sid, seat=0, action="next_phase")
    assert not game.combat_damage_resolved, (moved.status_code, moved.text, game.log[-4:])
    assert _state(sid, 0)["band_blocker_assignment"] is None, "no blocker has damage to divide"

    answered = _act(
        sid, seat=0, action="assign_combat_damage",
        attacker_damage_by_id={
            str(giant.permanent_id): {str(stone.permanent_id): 0, str(wood.permanent_id): 3},
            str(hero.permanent_id): {str(stone.permanent_id): 1},
        },
    )

    assert answered.status_code == 200, answered.text
    assert not game.is_on_battlefield(wood), "the Giant's 3 killed the Wall of Wood"
    assert stone.damage_marked == 1


# ---------------------------------------------------------------------------
# The defending player's division (CR 702.22j) over the band's spread blocks
# ---------------------------------------------------------------------------


def test_the_defending_player_owes_the_division_of_a_member_the_band_spread_blockers_onto():
    """The defender's own Benalish Hero (banding) blocks the Giant and their
    Gray Ogre the attacking Hero: CR 702.22h puts both in front of each member,
    and a creature with banding among them makes each member's division the
    defending player's (CR 702.22j). Backwards on 90bef6d1 nothing was owed —
    each member had one *declared* blocker — and the defender was not asked."""
    sid, game, (giant, hero), (their_hero, ogre) = _band_blocked(
        ["Benalish Hero", "Gray Ogre"], {"0": 0, "1": 1},
    )

    assert game.combat_damage_assigner(0) == 1 and game.combat_damage_assigner(1) == 1
    assert game.defender_assignments_owed(1) == [0, 1]
    info = _state(sid, 1)["banding_assignment"]
    assert [sorted(entry["blocker_indices"]) for entry in info["attackers"]] == [[0, 1], [0, 1]]
    assert not game.combat_damage_resolved


@needs_node
def test_the_defenders_dialog_groups_the_band_spread_blockers():
    sid, _game, _mine, _theirs = _band_blocked(["Benalish Hero", "Gray Ogre"], {"0": 0, "1": 1})

    assert _client_groups(_state(sid, 1), seat=1, banding=True) == [
        ["Hill Giant", ["Benalish Hero", "Gray Ogre"]],
        ["Benalish Hero", ["Benalish Hero", "Gray Ogre"]],
    ]
