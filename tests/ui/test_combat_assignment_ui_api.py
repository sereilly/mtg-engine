"""Combat damage assignment over the wire, for both seats.

``tests/rules/test_combat_damage_assignment.py`` holds the rule and
``tests/engine/test_combat_assignment_census.py`` the pool. This file is the
web flow — every step an action a client sends — and the part of the client
that nothing can load (``app.js`` is DOM-coupled), read as text.

What it was written against, each measured on the tree before the fix:

* **The wire accepted an under-assignment.** A six-power Craw Wurm blocked by
  two, announced over HTTP as one and none: 200, one damage on a White Knight,
  five nowhere. (Driven against the running server, 2026-10-06.)
* **A defending player was never asked** "as though it weren't blocked" under
  a banding blocker, and the wire had no way to say it.
* **Three ways for a combat damage step to be left with nothing that could
  resolve it** — none of them a refusal, each a game that simply stopped:
  two people and one banding double-block, once the defender had answered; a
  person attacking into an AI's banding double-block; and a second combat
  damage step with nothing left in it to divide.
* **The client decided who assigns** from one blocker's keyword line, and
  opened its dialog once per step where CR 510.4 has two.

Verified in the running app on 2026-10-06 (port 8031, real clicks, the state
API after each); the round's report lists what was driven.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store

from tests.helpers import _mk_card, _mk_creature_card, app_js_function_body

client = TestClient(app)

OFFER = "You may have this creature assign its combat damage as though it weren't blocked."
FORMATION = (
    "Rather than the attacking player, you assign the combat damage of each "
    "creature attacking you. You can divide that creature's combat damage as "
    "you choose among any of the creatures blocking it."
)


def _session(mode: str = "human_vs_human") -> str:
    created = client.post(
        "/api/sessions",
        json={
            "mode": mode, "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 51012,
        },
    ).json()
    sid = created["session_id"]
    if mode == "human_vs_human":
        client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return sid


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _to_combat_damage(attackers, blockers, *, blocks=None, mode="human_vs_human",
                      attacker_seat=0, extra_defender=()):
    """*attacker_seat* attacks the other seat with *attackers*; *blockers*
    block as *blocks* says (default: all of them block attacker 0). **Every
    step a human seat takes is an action a client sends**; an AI seat's are
    taken by the web flow's own stepping.

    Returns ``(sid, game, attacker permanents, blocker permanents, offset)``
    — ``offset`` being how many noncreature permanents sit ahead of the
    blockers on the defender's battlefield — with the session advanced into
    combat damage (or as far past it as the flow went unasked).
    """
    sid = _session(mode)
    session = store.get(sid)
    game = session.game
    defender_seat = 1 - attacker_seat
    mine = [Permanent(card=card) for card in attackers]
    extras = [Permanent(card=card) for card in extra_defender]
    theirs = [Permanent(card=card) for card in blockers]
    game.players[attacker_seat].battlefield = list(mine)
    game.players[defender_seat].battlefield = extras + theirs
    for player in game.players:
        player.hand = []
        player.life = 20
    session.current_turn = attacker_seat
    game.active_player_index = attacker_seat
    game._set_phase_and_step("combat", "declare_attackers")
    offset = len(extras)
    pairs = blocks if blocks is not None else {i: 0 for i in range(len(theirs))}
    pairs = {str(slot + offset): a for slot, a in pairs.items()}

    human = mode == "human_vs_human" or attacker_seat == 0
    if human:
        declared = _act(
            sid, seat=attacker_seat, action="declare_attackers",
            attacker_indices=list(range(len(mine))), target_seat=defender_seat,
        )
        assert declared.status_code == 200, declared.text
        assert _act(sid, seat=attacker_seat, action="next_phase").status_code == 200
    else:
        ok, why = game.declare_attackers(
            attacker_seat, list(range(len(mine))), defending_player_index=defender_seat
        )
        assert ok, why
        game.advance_combat_phase()
    if mode == "human_vs_human" or defender_seat == 0:
        blocked = _act(sid, seat=defender_seat, action="declare_blockers", blocker_pairs=pairs)
        assert blocked.status_code == 200, blocked.text
    else:
        ok, why = game.declare_blockers(
            defender_seat, {int(slot): a for slot, a in pairs.items()}
        )
        assert ok, why
    if human:
        advanced = _act(sid, seat=attacker_seat, action="next_phase")
        assert advanced.status_code == 200, advanced.text
    return sid, game, mine, theirs, offset


def _waiting(sid: str) -> bool:
    state = _state(sid, 0)
    return state["current_step"] == "combat_damage" and not state["combat"]["damage_resolved"]


def _plain(name: str = "Plain Ogre", power: int = 3, toughness: int = 3):
    return _mk_creature_card(name, power, toughness)


def _wall(name: str, power: int = 0, toughness: int = 9, text: str = ""):
    return _mk_creature_card(name, power, toughness, text)


# ---------------------------------------------------------------------------
# Part 1 — the wire is held to CR 510.1c
# ---------------------------------------------------------------------------


def test_an_under_assignment_is_a_400_and_nothing_is_dealt():
    sid, game, (ogre,), (a, b), _ = _to_combat_damage(
        [_plain()], [_wall("Wall A"), _wall("Wall B")]
    )
    assert _waiting(sid)

    refused = _act(sid, seat=0, action="assign_combat_damage",
                   attacker_damage={"0": {"0": 1, "1": 0}})

    assert refused.status_code == 400
    assert "all of its combat damage" in refused.json()["detail"]
    assert _waiting(sid), "CR 510.1e: the game returns to before the assignment"
    assert (a.damage_marked, b.damage_marked, ogre.damage_marked) == (0, 0, 0)

    # And the same seat can then announce a legal one.
    accepted = _act(sid, seat=0, action="assign_combat_damage",
                    attacker_damage={"0": {"0": 1, "1": 2}})
    assert accepted.status_code == 200, accepted.text
    assert (a.damage_marked, b.damage_marked) == (1, 2)


def test_damage_named_onto_a_bystander_is_a_400():
    sid, game, _mine, (a, b, bystander), _ = _to_combat_damage(
        [_plain()], [_wall("Wall A"), _wall("Wall B"), _wall("Bystander")],
        blocks={0: 0, 1: 0},
    )

    refused = _act(sid, seat=0, action="assign_combat_damage",
                   attacker_damage={"0": {"0": 1, "1": 0, "2": 2}})

    assert refused.status_code == 400
    assert "only to the creatures blocking it" in refused.json()["detail"]
    assert _waiting(sid) and bystander.damage_marked == 0


def test_a_trampler_keeps_its_arithmetic_over_the_wire():
    wurm = _mk_creature_card("Trampling Wurm", 6, 6, "Trample")
    sid, game, _mine, (a, b), _ = _to_combat_damage(
        [wurm], [_wall("Wall A", toughness=1), _wall("Wall B", toughness=4)]
    )

    short = _act(sid, seat=0, action="assign_combat_damage",
                 attacker_damage={"0": {"0": 1, "1": 2}})
    assert short.status_code == 400
    assert "trample requires lethal damage" in short.json()["detail"]

    over = _act(sid, seat=0, action="assign_combat_damage",
                attacker_damage={"0": {"0": 1, "1": 4}})
    assert over.status_code == 200, over.text
    assert over.json()["players"][1]["life"] == 19
    assert (a.damage_marked, b.damage_marked) == (1, 4)


# ---------------------------------------------------------------------------
# Part 3 — the server says who assigns
# ---------------------------------------------------------------------------


def test_the_state_says_which_seat_assigns_each_attacker():
    sid, _g, _m, _t, _ = _to_combat_damage([_plain()], [_wall("Wall A"), _wall("Wall B")])
    assert _state(sid, 0)["combat"]["damage_assigned_by"] == {"0": 0}

    sid, _g, _m, _t, _ = _to_combat_damage(
        [_plain()], [_wall("Bander", text="Banding"), _wall("Wall B")]
    )
    for seat in (0, 1):
        assert _state(sid, seat)["combat"]["damage_assigned_by"] == {"0": 1}, seat

    # The two the client's keyword test could not see.
    legends = [
        _mk_card("Wolf One", "Legendary Creature — Wolf", "Bands with other legendary creatures"),
        _mk_card("Wolf Two", "Legendary Creature — Wolf", ""),
    ]
    for card in legends:
        card.raw.update({"power": "1", "toughness": "5"})
    sid, _g, _m, _t, _ = _to_combat_damage([_plain()], legends)
    state = _state(sid, 1)
    assert state["combat"]["damage_assigned_by"] == {"0": 1}
    assert state["banding_assignment"]["attacker_indices"] == [0]

    formation = _mk_card("Probe Formation", "Enchantment", FORMATION)
    sid, _g, _m, _t, _ = _to_combat_damage(
        [_plain()], [_wall("Wall A"), _wall("Wall B")], extra_defender=[formation]
    )
    state = _state(sid, 1)
    assert state["combat"]["damage_assigned_by"] == {"0": 1}
    assert state["banding_assignment"]["attacker_indices"] == [0]
    assert _state(sid, 0)["banding_assignment"] is None


def test_the_client_reads_who_assigns_from_the_server():
    """The decision is one function, and it reads the state. It read the
    creatures blocking for the word "banding"."""
    reader = app_js_function_body("defenderAssignsAttackerDamage")
    assert "damage_assigned_by?.[attackerIdx]" in reader
    assert "oracle_text" not in reader and "cardHasBanding" not in reader

    assert "!defenderAssignsAttackerDamage(state, g.attackerIdx)" in app_js_function_body(
        "getAttackerAssignGroups"
    )
    defender = app_js_function_body("getDefenderBandingGroups")
    assert "state?.banding_assignment" in defender
    assert "seat !== info.defender_seat" in defender
    assert "cardHasBanding" not in defender and "oracle_text" not in defender
    assert "owed.get(attackerIdx)?.offer ? 1 : 2" in defender, (
        "an offered attacker is a decision with one blocker"
    )


# ---------------------------------------------------------------------------
# Part 2 — the defending player's "as though it weren't blocked"
# ---------------------------------------------------------------------------


def _offered(power: int = 5, toughness: int = 5):
    return _mk_creature_card("Slipping Beast", power, toughness, OFFER)


def test_one_banding_blocker_asks_the_defender_and_nobody_else():
    sid, game, (beast,), (sentry,), _ = _to_combat_damage(
        [_offered()], [_wall("Banding Sentry", power=1, toughness=4, text="Banding")]
    )

    assert _waiting(sid), "the defender's choice was made for them"
    defender = _state(sid, 1)
    assert defender["banding_assignment"] == {
        "defender_seat": 1,
        "attacker_indices": [0],
        "attackers": [{
            "attacker_index": 0,
            "attacker_id": beast.permanent_id,
            "damage": 5,
            "blocker_indices": [0],
            "offer": {"recipient": {"kind": "player", "seat": 1, "name": game.players[1].name}},
        }],
    }
    assert defender["unblocked_assignment"] is None
    attacker = _state(sid, 0)
    assert attacker["banding_assignment"] is None
    assert attacker["unblocked_assignment"] is None, "it is not the attacker's to answer"
    assert (game.players[1].life, sentry.damage_marked) == (20, 0)


def test_the_attacker_cannot_move_past_the_defenders_question():
    sid, game, (beast,), (sentry,), _ = _to_combat_damage(
        [_offered()], [_wall("Banding Sentry", power=1, toughness=4, text="Banding")]
    )

    advanced = _act(sid, seat=0, action="next_phase")
    assert advanced.status_code == 400 and "banding" in advanced.json()["detail"].lower()
    taken = _act(sid, seat=0, action="assign_combat_damage",
                 attacker_damage={}, as_though_unblocked_ids=[beast.permanent_id])
    assert taken.status_code == 400
    assert _waiting(sid) and game.players[1].life == 20


def test_the_defender_takes_the_offer_over_the_wire():
    sid, game, (beast,), (sentry,), _ = _to_combat_damage(
        [_offered()], [_wall("Banding Sentry", power=1, toughness=4, text="Banding")]
    )

    answered = _act(sid, seat=1, action="assign_banding_damage",
                    banding_damage={}, as_though_unblocked_ids=[beast.permanent_id])

    assert answered.status_code == 200, answered.text
    state = answered.json()
    # The last announcement owed, so the damage is dealt by it — the human
    # attacker has no dialog of their own to resolve this from.
    assert state["combat"]["damage_resolved"] is True
    assert state["players"][1]["life"] == 15
    assert sentry.damage_marked == 0 and beast.damage_marked == 1
    assert state["banding_assignment"] is None


def test_the_defender_keeps_it_on_the_blocker_over_the_wire():
    sid, game, (beast,), (sentry,), _ = _to_combat_damage(
        [_offered()], [_wall("Banding Sentry", power=1, toughness=4, text="Banding")]
    )

    answered = _act(sid, seat=1, action="assign_banding_damage",
                    banding_damage={"0": {"0": 5}})

    assert answered.status_code == 200, answered.text
    assert answered.json()["players"][1]["life"] == 20
    assert [card.name for card in game.players[1].graveyard] == ["Banding Sentry"]


def test_the_defenders_refusals_are_400s_and_leave_the_question_open():
    sid, game, (beast,), (sentry, wall), _ = _to_combat_damage(
        [_offered()],
        [_wall("Banding Sentry", power=1, toughness=4, text="Banding"), _wall("Wall B")],
    )

    both = _act(sid, seat=1, action="assign_banding_damage",
                banding_damage={"0": {"0": 2, "1": 0}},
                as_though_unblocked_ids=[beast.permanent_id])
    assert both.status_code == 400 and "not some of each" in both.json()["detail"]
    short = _act(sid, seat=1, action="assign_banding_damage",
                 banding_damage={"0": {"0": 2, "1": 0}})
    assert short.status_code == 400 and "all of its combat damage" in short.json()["detail"]
    wrong_seat = _act(sid, seat=0, action="assign_banding_damage",
                      banding_damage={}, as_though_unblocked_ids=[beast.permanent_id])
    assert wrong_seat.status_code == 400

    assert _waiting(sid)
    assert _state(sid, 1)["banding_assignment"]["attacker_indices"] == [0]
    assert (game.players[1].life, sentry.damage_marked, wall.damage_marked) == (20, 0, 0)


def test_a_human_defending_against_an_ai_is_asked_and_the_ai_then_resolves():
    """The arrangement the round's brief names: the AI attacks, a person
    blocks with a creature with banding. The AI's damage waits for the
    defender, and their answer resumes it."""
    sid, game, (beast,), (sentry,), _ = _to_combat_damage(
        [_offered()], [_wall("Banding Sentry", power=1, toughness=4, text="Banding")],
        mode="human_vs_ai", attacker_seat=1,
    )
    for _ in range(8):
        state = _state(sid, 0)
        if state["current_step"] == "combat_damage" or state["current_turn_phase"] != "combat":
            break
        if state.get("priority_player") == 0:
            assert _act(sid, seat=0, action="pass_priority").status_code == 200
        else:
            assert _act(sid, seat=0, action="ai_step").status_code == 200
    state = _state(sid, 0)
    assert state["current_step"] == "combat_damage"
    assert state["combat"]["damage_resolved"] is False, "the AI resolved over the defender"
    assert [e["attacker_id"] for e in state["banding_assignment"]["attackers"]] == [
        beast.permanent_id
    ]
    assert game.players[0].life == 20

    answered = _act(sid, seat=0, action="assign_banding_damage",
                    banding_damage={}, as_though_unblocked_ids=[beast.permanent_id])

    assert answered.status_code == 200, answered.text
    assert game.combat_damage_resolved
    assert game.players[0].life == 15 and sentry.damage_marked == 0


def test_a_printed_substitution_asks_the_defender_the_same_way():
    formation = _mk_card("Probe Formation", "Enchantment", FORMATION)
    sid, game, (beast,), (wall,), offset = _to_combat_damage(
        [_offered()], [_wall("Wall A", power=1)], extra_defender=[formation]
    )

    assert _waiting(sid)
    entry = _state(sid, 1)["banding_assignment"]["attackers"][0]
    assert entry["blocker_indices"] == [offset] and entry["offer"] is not None

    answered = _act(sid, seat=1, action="assign_banding_damage",
                    banding_damage={"0": {str(offset): 5}})
    assert answered.status_code == 200, answered.text
    assert answered.json()["players"][1]["life"] == 20 and wall.damage_marked == 5


def test_the_dialog_sends_the_defenders_answer_by_id():
    """The client's half: in "banding" mode an offered group taking the offer
    goes out as an id with no division, exactly as the attacker's own does."""
    dialog = app_js_function_body("openDamageDialog")
    banding = dialog.index('action: "assign_banding_damage"')
    attacker = dialog.index('action: "assign_combat_damage"')
    assert banding < attacker
    assert "as_though_unblocked_ids: asThoughUnblockedIds" in dialog[banding:attacker]
    assert "banding_damage: assignment" in dialog[banding:attacker]
    # Auto-assign answers as the engine would unasked — which for a defender
    # is to keep the damage on the blockers.
    assert 'mode === "banding" ? "blockers" : "unblocked"' in dialog

    render = app_js_function_body("renderCombatDamageDialogBody")
    assert "You assign its damage, so the choice is yours." in render
    # "All 5 to you" — the defender is choosing whether it comes to them.
    assert "recipient.seat === seat" in app_js_function_body("unblockedRecipientLabel")


# ---------------------------------------------------------------------------
# Three ways the step was left with nothing that could resolve it
# ---------------------------------------------------------------------------


def test_two_people_and_a_banding_double_block_resolve_when_the_defender_answers():
    """Measured on the tree before: after the defender's 200 the step stayed
    at ``damage_resolved: False`` through every Next Phase and pass either
    seat could send. An attacker the defender assigns is in no dialog of the
    attacker's, so nothing of theirs could deal it."""
    sid, game, _mine, (sentry, wall), _ = _to_combat_damage(
        [_plain()], [_wall("Bander", text="Banding"), _wall("Wall B")]
    )
    assert _waiting(sid)

    answered = _act(sid, seat=1, action="assign_banding_damage",
                    banding_damage={"0": {"0": 0, "1": 3}})

    assert answered.status_code == 200, answered.text
    assert answered.json()["combat"]["damage_resolved"] is True
    assert (sentry.damage_marked, wall.damage_marked) == (0, 3)


def test_the_defenders_answer_does_not_resolve_past_the_attackers_own_division():
    """The control: where the attacker still owes a division of their own,
    the defender's answer is not the last announcement and deals nothing."""
    sid, game, _mine, (sentry, b, c, d), _ = _to_combat_damage(
        [_plain(), _plain("Plain Bear", 2, 2)],
        [_wall("Bander", text="Banding"), _wall("Wall B"), _wall("Wall C"), _wall("Wall D")],
        blocks={0: 0, 1: 0, 2: 1, 3: 1},
    )

    answered = _act(sid, seat=1, action="assign_banding_damage",
                    banding_damage={"0": {"0": 3, "1": 0}})
    assert answered.status_code == 200, answered.text
    assert _waiting(sid), "the attacker's own double block was resolved for them"

    resolved = _act(sid, seat=0, action="assign_combat_damage",
                    attacker_damage={"1": {"2": 0, "3": 2}})
    assert resolved.status_code == 200, resolved.text
    assert (sentry.damage_marked, b.damage_marked, c.damage_marked, d.damage_marked) == (3, 0, 0, 2)


def test_a_person_attacking_into_an_ais_banding_double_block_is_not_stranded():
    """Measured before: six Next Phase presses, ``damage_resolved`` False
    after each, and no dialog on either side — the division is the AI's
    (CR 702.22j), the attacker's client rightly shows none, and the server
    was waiting for one. With nobody to ask, the default stands."""
    sid, game, _mine, (sentry, wall), _ = _to_combat_damage(
        [_plain()], [_wall("Bander", text="Banding"), _wall("Wall B")],
        mode="human_vs_ai",
    )
    state = _state(sid, 0)
    assert state["banding_assignment"] is None and state["combat"]["damage_assigned_by"] == {"0": 1}

    for _ in range(3):
        if not _waiting(sid):
            break
        assert _act(sid, seat=0, action="next_phase").status_code == 200

    assert not _waiting(sid), "combat damage never resolved"
    assert sentry.damage_marked + wall.damage_marked == 3


def test_a_second_step_with_nothing_to_divide_is_dealt_when_the_attacker_moves_on():
    """Measured before: a double striker kills one of its two blockers in the
    first-strike step, and the second step is never dealt — three presses,
    ``first_strike_done: True, damage_resolved: False`` after each."""
    fencer = _mk_creature_card("Fencer", 3, 3, "Double strike")
    sid, game, _mine, (pup, wall), _ = _to_combat_damage(
        [fencer], [_wall("Pup", toughness=2), _wall("Wall B")]
    )
    first = _act(sid, seat=0, action="assign_combat_damage",
                 attacker_damage={"0": {"0": 3, "1": 0}})
    assert first.status_code == 200, first.text
    state = _state(sid, 0)
    assert state["combat"]["first_strike_done"] is True
    assert state["combat"]["damage_resolved"] is False
    assert wall.damage_marked == 0

    assert _act(sid, seat=0, action="next_phase").status_code == 200

    state = _state(sid, 0)
    assert state["combat"]["damage_resolved"] is True, "the second step was never dealt"
    assert wall.damage_marked == 3


# ---------------------------------------------------------------------------
# Part 4 — the second combat damage step asks again
# ---------------------------------------------------------------------------


def test_an_ordinary_multi_blocks_second_step_is_still_owed_over_the_wire():
    """CR 510.4, with no "as though it weren't blocked" anywhere: the first
    answer resolves the first-strike step and the same division is owed again
    for the second, over the board the first one left."""
    fencer = _mk_creature_card("Fencer", 3, 3, "Double strike")
    sid, game, _mine, (a, b), _ = _to_combat_damage(
        [fencer], [_wall("Wall A"), _wall("Wall B")]
    )

    first = _act(sid, seat=0, action="assign_combat_damage",
                 attacker_damage={"0": {"0": 3, "1": 0}})
    assert first.status_code == 200, first.text
    state = _state(sid, 0)
    assert state["combat"]["first_strike_done"] is True
    assert state["combat"]["damage_resolved"] is False

    # Pressing on does not deal a step somebody still has to divide.
    assert _act(sid, seat=0, action="next_phase").status_code == 200
    assert _waiting(sid)

    second = _act(sid, seat=0, action="assign_combat_damage",
                  attacker_damage={"0": {"0": 0, "1": 3}})
    assert second.status_code == 200, second.text
    assert second.json()["combat"]["damage_resolved"] is True
    assert (a.damage_marked, b.damage_marked) == (3, 3)


def test_the_dialogs_open_once_per_combat_damage_step_not_once_per_step_name():
    """The client's half. The server keeps one ``current_step`` for both
    combat damage steps and says which with ``first_strike_done``; the dialogs
    keyed their auto-open on the step alone, so the second never opened.

    Four dialogs share the key — the attacker's, the defender's banding one,
    the multi-blocking creature's and the band blocker's — and all four took
    the same fix."""
    key = app_js_function_body("getCombatDamagePassKey")
    assert "first_strike_done" in key and "getCombatDraftStepKey(state)" in key

    controls = app_js_function_body("renderCombatControls")
    assert controls.count("getCombatDamagePassKey(state)") == 4
    assert "getCombatDraftStepKey(state)" not in controls

    # A new step starts from empty drafts: the first one's divisions were made
    # over creatures that may be dead now, and its offers answered for it alone.
    applied = app_js_function_body("renderState")
    changed = applied.index("damagePassKey !== combatDamagePassKey")
    for draft in ("combatDamageDraft = {};", "combatDamageOfferDraft = {};",
                  "combatBandBlockerDraft = {};", "combatMultiblockDraft = {};"):
        assert draft in applied[changed:changed + 400], draft

    # And each dialog, once its answer is accepted, hands over to whichever
    # one the new state owes rather than only closing itself.
    settle = app_js_function_body("settleCombatDamageDialog")
    assert 'combatDamageDialogKey = "";' in settle
    assert "renderCombatControls(currentState)" in settle
    assert "if (accepted) settleCombatDamageDialog();" in app_js_function_body("openBandBlockerDialog")
    assert "if (accepted) settleCombatDamageDialog();" in app_js_function_body(
        "openMultiblockDamageDialog"
    )


# ---------------------------------------------------------------------------
# Part 5 — a menu left open across a board change
# ---------------------------------------------------------------------------


def test_an_open_ability_menu_is_read_again_from_the_state_it_outlived():
    """Driven in the running app before the fix: a Karplusan Forest's ability
    menu, open while an opponent's Blood Moon resolved, still listed both
    abilities, ran the one clicked through to a mana fan offering green from a
    land that is a Mountain, and sent it — a 400 from the server was the only
    thing that stopped it. The menu is re-read on every state now, and again
    at the click."""
    refresh = app_js_function_body("refreshPendingPermanentPrompts")
    assert "findPermanentInState(state, permanentId)" in refresh
    assert "getActivatedAbilityOptions(found.card)" in refresh
    assert "found.card.abilities_lost" in refresh, "the server's sentence is what is shown"
    assert refresh.count("pendingAbilityChoice = null;") == 2, "gone, or changed"

    # Re-pointed at the permanent's current slot when nothing changed — the
    # menu held the index it was opened with.
    assert "permanentIndex: found.index" in refresh

    assert "refreshPendingPermanentPrompts(state);" in app_js_function_body("renderState")
    click = app_js_function_body("resolveAbilityChoice")
    assert click.index("refreshPendingPermanentPrompts(currentState);") < click.index(
        "pending.options.find("
    )


def test_the_server_still_refuses_what_a_stale_client_would_send():
    """The server's half is unchanged and is what this round relied on while
    measuring: a land whose type was set has lost its printed abilities
    (CR 305.7), and naming one of them is a 400 with the reason."""
    from web.runtime import CARD_BY_NAME

    sid = _session()
    session = store.get(sid)
    game = session.game
    forest = Permanent(card=CARD_BY_NAME["karplusan forest"])
    moon = Permanent(card=CARD_BY_NAME["blood moon"])
    game.players[0].battlefield = []
    game.players[1].battlefield = []
    game._put_permanent_onto_battlefield(0, forest, None)
    game._put_permanent_onto_battlefield(1, moon, None)
    state = _state(sid, 0)
    card = state["players"][0]["battlefield"][0]
    assert card["abilities_lost"], "Blood Moon did not reach the land"

    refused = _act(sid, seat=0, action="activate", permanent_name="Karplusan Forest",
                   permanent_index=0, ability_index=1, mana_color="G")

    assert refused.status_code == 400
    assert "lost its abilities" in refused.json()["detail"]
    assert forest.tapped is False
