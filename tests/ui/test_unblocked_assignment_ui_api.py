"""The wire and the dialog for "You may have this creature assign its combat
damage as though it weren't blocked."

The rule is held in ``tests/rules/test_unblocked_assignment.py`` and the pool
in ``tests/engine/test_unblocked_assignment_census.py``. This file is the part
neither can see, which is where the defect was: a person driving the web app.

* **One blocker.** The server resolved the damage as the step was entered and
  the client opened no dialog, so the offer was always taken for them.
* **Several.** The client's dialog required all the attacker's power to be
  assigned among the blockers, so the offer could not be taken at all — and
  the wire had no way to announce it other than by saying nothing.

Verified in the running app on 2026-10-06 (Thorn Elemental, human vs AI, real
clicks, the state API after each): before, one blocker went straight to the
second main phase with the AI on 40 → 33 and no prompt, and two blockers
opened a dialog whose Confirm stayed disabled at "Assigned 0 / 7 — Assign all
7 damage among the blockers"; after, both arrangements stop on a dialog that
asks, and all four answers land.

Three layers, as three groups of tests: the actions over HTTP driven the way
the client drives them, the state payload each seat sees, and — only because
``app.js`` is DOM-coupled and nothing can load it — the client's source read
as text for the three things the server cannot check for it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.combat_assignment import (AS_THOUGH_UNBLOCKED_LOG,
                                      MAY_ASSIGN_AS_UNBLOCKED)
from engine.models import Permanent
from web.app import app, store

from tests.helpers import _mk_creature_card, app_js_function_body

client = TestClient(app)

OFFER = "You may have this creature assign its combat damage as though it weren't blocked."


def _beast(power: int = 5, toughness: int = 5):
    return _mk_creature_card("Slipping Beast", power, toughness, OFFER)


def _session(mode: str = "human_vs_human") -> str:
    created = client.post(
        "/api/sessions",
        json={
            "mode": mode, "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 51011,
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


def _to_combat_damage(attackers, blockers, *, blocks=None):
    """Seat 0 attacks seat 1 with *attackers*; *blockers* block as *blocks*
    says (default: all of them block attacker 0). **Every step is an action a
    client sends** — declare, Next Phase, block, Next Phase — so what is under
    test is the web flow's own stepping, not a rigged ``current_step``.

    Returns ``(sid, game, attacker permanents, blocker permanents)`` with the
    session having just been advanced into combat damage.
    """
    sid = _session()
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
    assert _act(sid, seat=0, action="next_phase").status_code == 200
    pairs = blocks if blocks is not None else {str(i): 0 for i in range(len(theirs))}
    blocked = _act(sid, seat=1, action="declare_blockers", blocker_pairs=pairs)
    assert blocked.status_code == 200, blocked.text
    advanced = _act(sid, seat=0, action="next_phase")
    assert advanced.status_code == 200, advanced.text
    return sid, game, mine, theirs


def _waiting(sid: str) -> bool:
    state = _state(sid, 0)
    return state["current_step"] == "combat_damage" and not state["combat"]["damage_resolved"]


# ---------------------------------------------------------------------------
# The game stops and the state says what is being asked
# ---------------------------------------------------------------------------


def test_one_blocker_stops_at_combat_damage_and_the_active_seat_is_told_why():
    sid, game, (beast,), (wall,) = _to_combat_damage(
        [_beast()], [_mk_creature_card("Wall", 1, 4)]
    )

    state = _state(sid, 0)
    assert state["current_step"] == "combat_damage"
    assert state["combat"]["damage_resolved"] is False, "the offer was taken unasked"
    assert state["players"][1]["life"] == 20
    assert state["unblocked_assignment"] == {
        "attacker_seat": 0,
        "attackers": [{
            "attacker_index": 0,
            "attacker_id": beast.permanent_id,
            "damage": 5,
            "recipient": {"kind": "player", "seat": 1, "name": game.players[1].name},
        }],
    }
    # The choice is the active player's; the defender is shown no prompt.
    assert _state(sid, 1)["unblocked_assignment"] is None


def test_next_phase_does_not_run_past_the_question():
    """The web flow auto-resolves a manual assignment its dialog cannot show
    (``web/game_flow.py``). This one it can show, so pressing Next Phase again
    must leave the step waiting — the path that would have made the fix a
    dialog that flashes and is answered for you."""
    sid, game, _mine, (wall,) = _to_combat_damage(
        [_beast()], [_mk_creature_card("Wall", 1, 4)]
    )

    for _ in range(3):
        assert _act(sid, seat=0, action="next_phase").status_code == 200
        assert _waiting(sid)
    assert game.players[1].life == 20 and wall.damage_marked == 0


def test_several_blockers_carry_the_same_question():
    sid, _game, (beast,), _walls = _to_combat_damage(
        [_beast()],
        [_mk_creature_card("Wall A", 1, 4), _mk_creature_card("Wall B", 1, 4)],
    )

    assert _waiting(sid)
    offered = _state(sid, 0)["unblocked_assignment"]["attackers"]
    assert [entry["attacker_id"] for entry in offered] == [beast.permanent_id]


def test_an_ordinary_attackers_prompts_are_what_they_were():
    """The promise to the paths beside this one. No sentence, no question: a
    single block resolves through the same clicks, and a double block stops
    for its division with no offer attached."""
    plain = _mk_creature_card("Plain Bear", 3, 3)

    sid, game, _mine, (wall,) = _to_combat_damage([plain], [_mk_creature_card("Wall", 1, 4)])
    state = _state(sid, 0)
    assert state["unblocked_assignment"] is None
    assert not _waiting(sid), "an ordinary single block must not stop"
    assert wall.damage_marked == 3 and game.players[1].life == 20

    sid, game, _mine, _walls = _to_combat_damage(
        [plain], [_mk_creature_card("Wall A", 1, 4), _mk_creature_card("Wall B", 1, 4)]
    )
    state = _state(sid, 0)
    assert _waiting(sid), "an ordinary double block still owes its division"
    assert state["unblocked_assignment"] is None
    assert state["banding_assignment"] is None
    assert state["multiblock_blocker_assignment"] is None


# ---------------------------------------------------------------------------
# Both answers over the wire, one blocker and several
# ---------------------------------------------------------------------------


def test_one_blocker_the_offer_taken():
    sid, game, (beast,), (wall,) = _to_combat_damage(
        [_beast()], [_mk_creature_card("Wall", 1, 4)]
    )

    answered = _act(
        sid, seat=0, action="assign_combat_damage",
        attacker_damage={}, as_though_unblocked_ids=[beast.permanent_id],
    )

    assert answered.status_code == 200, answered.text
    state = answered.json()
    assert state["players"][1]["life"] == 15
    assert state["combat"]["damage_resolved"] is True
    assert state["unblocked_assignment"] is None
    assert wall.damage_marked == 0 and beast.damage_marked == 1


def test_one_blocker_the_offer_declined_kills_the_blocker():
    """The answer a person could not give."""
    sid, game, (beast,), (wall,) = _to_combat_damage(
        [_beast()], [_mk_creature_card("Wall", 1, 4)]
    )

    answered = _act(
        sid, seat=0, action="assign_combat_damage",
        attacker_damage={"0": {"0": 5}}, as_though_unblocked_ids=[],
    )

    assert answered.status_code == 200, answered.text
    state = answered.json()
    assert state["players"][1]["life"] == 20
    assert [card["name"] for card in state["players"][1]["battlefield"]] == []
    assert [card.name for card in game.players[1].graveyard] == ["Wall"]


def test_several_blockers_the_offer_taken():
    """The other answer a person could not give."""
    sid, game, (beast,), (a, b) = _to_combat_damage(
        [_beast()],
        [_mk_creature_card("Wall A", 1, 4), _mk_creature_card("Wall B", 1, 4)],
    )

    answered = _act(
        sid, seat=0, action="assign_combat_damage",
        attacker_damage={}, as_though_unblocked_ids=[beast.permanent_id],
    )

    assert answered.status_code == 200, answered.text
    assert answered.json()["players"][1]["life"] == 15
    assert (a.damage_marked, b.damage_marked) == (0, 0)


def test_several_blockers_the_offer_declined_is_an_ordinary_division():
    sid, game, _mine, (a, b) = _to_combat_damage(
        [_beast()],
        [_mk_creature_card("Wall A", 1, 4), _mk_creature_card("Wall B", 1, 4)],
    )

    answered = _act(
        sid, seat=0, action="assign_combat_damage",
        attacker_damage={"0": {"0": 2, "1": 3}}, as_though_unblocked_ids=[],
    )

    assert answered.status_code == 200, answered.text
    assert answered.json()["players"][1]["life"] == 20
    assert (a.damage_marked, b.damage_marked) == (2, 3)


def test_the_granted_sentence_is_asked_over_the_wire_too():
    """Garruk's grant is a mark on the creature rather than a line on its
    card; the state block and the answer must not care which."""
    plain = _mk_creature_card("Plain Bear", 3, 3)
    sid = _session()
    session = store.get(sid)
    game = session.game
    bear = Permanent(card=plain, metadata={MAY_ASSIGN_AS_UNBLOCKED: True})
    wall = Permanent(card=_mk_creature_card("Wall", 1, 4))
    game.players[0].battlefield = [bear]
    game.players[1].battlefield = [wall]
    game.players[0].life = game.players[1].life = 20
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert _act(sid, seat=0, action="declare_attackers",
                attacker_indices=[0], target_seat=1).status_code == 200
    assert _act(sid, seat=0, action="next_phase").status_code == 200
    assert _act(sid, seat=1, action="declare_blockers",
                blocker_pairs={"0": 0}).status_code == 200
    assert _act(sid, seat=0, action="next_phase").status_code == 200

    assert _waiting(sid)
    offered = _state(sid, 0)["unblocked_assignment"]["attackers"]
    assert [(e["attacker_id"], e["damage"]) for e in offered] == [(bear.permanent_id, 3)]
    answered = _act(
        sid, seat=0, action="assign_combat_damage",
        attacker_damage={}, as_though_unblocked_ids=[bear.permanent_id],
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["players"][1]["life"] == 17 and wall.damage_marked == 0


# ---------------------------------------------------------------------------
# What the server refuses
# ---------------------------------------------------------------------------


def test_some_of_each_is_a_400_and_the_step_is_still_waiting():
    sid, game, (beast,), (wall,) = _to_combat_damage(
        [_beast()], [_mk_creature_card("Wall", 1, 4)]
    )

    refused = _act(
        sid, seat=0, action="assign_combat_damage",
        attacker_damage={"0": {"0": 2}}, as_though_unblocked_ids=[beast.permanent_id],
    )

    assert refused.status_code == 400
    assert "not some of each" in refused.json()["detail"]
    assert _waiting(sid)
    assert game.players[1].life == 20 and wall.damage_marked == 0


def test_a_partial_decline_and_a_creature_without_the_offer_are_400s():
    sid, game, (beast,), (wall,) = _to_combat_damage(
        [_beast()], [_mk_creature_card("Wall", 1, 4)]
    )
    partial = _act(sid, seat=0, action="assign_combat_damage",
                   attacker_damage={"0": {"0": 3}})
    assert partial.status_code == 400
    assert "all of its combat damage" in partial.json()["detail"]
    assert _waiting(sid)

    plain = _mk_creature_card("Plain Bear", 3, 3)
    sid, game, (bear,), _walls = _to_combat_damage(
        [plain], [_mk_creature_card("Wall A", 1, 4), _mk_creature_card("Wall B", 1, 4)]
    )
    cheat = _act(sid, seat=0, action="assign_combat_damage",
                 attacker_damage={}, as_though_unblocked_ids=[bear.permanent_id])
    assert cheat.status_code == 400
    assert "can't assign its combat damage as though it weren't blocked" in cheat.json()["detail"]
    assert _waiting(sid) and game.players[1].life == 20


# ---------------------------------------------------------------------------
# The attackers the dialog does not show
# ---------------------------------------------------------------------------


def test_an_attacker_the_dialog_did_not_show_still_deals_its_damage():
    """The dialog announces the attackers with a decision in them. A second
    attacker with one blocker has none (CR 510.1c: it "assigns all its combat
    damage to that creature"), is not in the announcement, and must keep the
    default — it was assigned *nothing*, because an absent entry means nothing
    to ``resolve_combat_damage``.

    Both shapes: beside an offered attacker (new — the dialog now opens for
    one blocker), and beside an ordinary multi-block (measured on the tree
    before this round: the second attacker's blocker took 0 of 2)."""
    plain = _mk_creature_card("Plain Bear", 2, 2)
    walls = [_mk_creature_card(name, 0, 5) for name in ("Wall A", "Wall B")]

    sid, game, (beast, bear), (a, b) = _to_combat_damage(
        [_beast(), plain], walls, blocks={"0": 0, "1": 1}
    )
    assert _waiting(sid)
    answered = _act(
        sid, seat=0, action="assign_combat_damage",
        attacker_damage={}, as_though_unblocked_ids=[beast.permanent_id],
    )
    assert answered.status_code == 200, answered.text
    assert game.players[1].life == 15
    assert (a.damage_marked, b.damage_marked) == (0, 2), "the bear hit its own blocker"

    three = walls + [_mk_creature_card("Wall C", 0, 5)]
    big = _mk_creature_card("Plain Ogre", 3, 3)
    sid, game, _mine, (a, b, c) = _to_combat_damage(
        [big, plain], three, blocks={"0": 0, "1": 0, "2": 1}
    )
    assert _waiting(sid)
    answered = _act(sid, seat=0, action="assign_combat_damage",
                    attacker_damage={"0": {"0": 3, "1": 0}})
    assert answered.status_code == 200, answered.text
    assert (a.damage_marked, b.damage_marked, c.damage_marked) == (3, 0, 2)


# ---------------------------------------------------------------------------
# A seat nobody is sitting in
# ---------------------------------------------------------------------------


def test_an_ai_attacker_keeps_the_default_and_the_human_defender_is_not_asked():
    """The stated default: the offer taken. A human *defending* against it
    has no choice to make (CR 510.1: the active player announces), sees no
    prompt, and the game does not wait."""
    sid = _session("human_vs_ai")
    session = store.get(sid)
    game = session.game
    beast = Permanent(card=_beast())
    wall = Permanent(card=_mk_creature_card("Wall", 1, 4))
    game.players[1].battlefield = [beast]
    game.players[0].battlefield = [wall]
    game.players[0].hand = []
    game.players[1].hand = []
    game.players[0].life = game.players[1].life = 20
    session.current_turn = 1
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(1, [0], defending_player_index=0)
    assert ok, why

    seen_offer = False
    for _ in range(8):
        state = _state(sid, 0)
        seen_offer = seen_offer or state["unblocked_assignment"] is not None
        if state["current_turn_phase"] != "combat":
            break
        if state["current_step"] == "declare_blockers" and not state["combat"]["blockers_locked"]:
            assert _act(sid, seat=0, action="declare_blockers",
                        blocker_pairs={"0": 0}).status_code == 200
        elif state.get("priority_player") == 0:
            assert _act(sid, seat=0, action="pass_priority").status_code == 200
        else:
            assert _act(sid, seat=0, action="ai_step").status_code == 200

    assert _state(sid, 0)["current_turn_phase"] != "combat", "combat never finished"
    assert not seen_offer
    assert game.players[0].life == 15, "the AI's default is the offer taken"
    assert wall.damage_marked == 0


# ---------------------------------------------------------------------------
# The client, read as text
# ---------------------------------------------------------------------------
#
# ``app.js`` is DOM-coupled and bare ``node`` cannot load it, so nothing can
# call these functions. What can be checked is the three places the server's
# half of the fix would be undone by the client's: which attackers the dialog
# shows, whether an unanswered offer can be confirmed, and what Confirm sends.


def test_the_dialog_shows_an_offered_attacker_with_a_single_blocker():
    """The dialog's groups came from ``getMultiBlockedAttackerGroups``, which
    drops any attacker with fewer than two blockers. An offered attacker has a
    decision with one, and which attackers are offered is the *server's* list."""
    groups = app_js_function_body("getAttackerAssignGroups")
    assert "getUnblockedAssignmentOffers(state)" in groups
    assert "offers.has(attackerIdx) ? 1 : 2" in groups
    assert "offer: offers.get(g.attackerIdx)" in groups

    offers = app_js_function_body("getUnblockedAssignmentOffers")
    assert "state?.unblocked_assignment" in offers
    assert "seat !== info.attacker_seat" in offers, "another seat's offer is not this seat's"

    # The stop is honoured by the auto-pass helpers through the same groups.
    assert "getAttackerAssignGroups(state).length > 0" in app_js_function_body(
        "combatDamageAssignmentPending"
    )


def test_an_unanswered_offer_cannot_be_confirmed():
    """Neither answer starts selected: the dialog asks. Confirm is disabled
    while any group is invalid, and an offered group with no answer is."""
    validate = app_js_function_body("validateCombatDamageGroup")
    assert "combatDamageOfferDraft[group.attackerIdx]" in validate
    assert 'answer === "unblocked"' in validate
    assert 'answer !== "blockers"' in validate
    assert "valid: false" in validate

    render = app_js_function_body("renderCombatDamageDialogBody")
    assert 'choice("unblocked"' in render and '"blockers"' in render
    assert "confirmBtn.disabled = !allValid" in render


def test_confirm_announces_the_offer_by_id_and_sends_no_division_for_it():
    """The wire's two answers: the attacker's id in ``as_though_unblocked_ids``
    and no entry for it, or an entry and no id. Sending both is the 400 above,
    and sending the old shape — a division for every group — is the dialog
    that could never say yes."""
    dialog = app_js_function_body("openDamageDialog")
    assert "as_though_unblocked_ids: asThoughUnblockedIds" in dialog
    assert "asThoughUnblockedIds.push(g.offer.attackerId)" in dialog
    taken = dialog.index('combatDamageOfferDraft[g.attackerIdx] === "unblocked"')
    division = dialog.index("assignment[g.attackerIdx] = combatDamageDraft[g.attackerIdx]")
    assert dialog.index("continue;", taken) < division, (
        "an attacker taking the offer must skip the division"
    )


def test_the_damage_animation_is_told_when_the_blow_landed_on_the_player():
    """The animation rebuilds the strikes from the *previous* state, mirroring
    the default assignment, so it drew a creature that went past its blocker
    hitting the blocker. The engine's log line is what tells it otherwise, and
    the client's copy of that line is held to the engine's here — two spellings
    of one sentence is how the animation would quietly stop matching."""
    trigger = app_js_function_body("maybeTriggerCombatDamageFx")
    assert f'" assigns its combat damage {AS_THOUGH_UNBLOCKED_LOG}"' in trigger
    assert "buildCombatDamageStrikes(prev, firstStrikePass, regularPass, sentPastBlockers)" in trigger

    strikes = app_js_function_body("buildCombatDamageStrikes")
    assert "past.get(attackerCard.name)" in strikes
    assert "powerLeft = attackerStrikes && !goesPast ? power : 0" in strikes, (
        "a creature going past its blockers assigns them nothing"
    )
    assert "if (goesPast) {" in strikes and "playerDamage = power;" in strikes


def test_the_log_line_reaches_both_seats_over_the_wire():
    sid, game, (beast,), _walls = _to_combat_damage(
        [_beast()], [_mk_creature_card("Wall", 1, 4)]
    )
    assert _act(
        sid, seat=0, action="assign_combat_damage",
        attacker_damage={}, as_though_unblocked_ids=[beast.permanent_id],
    ).status_code == 200

    line = f"Slipping Beast assigns its combat damage {AS_THOUGH_UNBLOCKED_LOG}"
    for seat in (0, 1):
        assert line in _state(sid, seat)["log"], seat
