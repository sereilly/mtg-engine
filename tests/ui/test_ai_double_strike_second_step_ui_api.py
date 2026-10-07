"""An AI's double striker, a person's banding blocker: the second combat damage
step is the defending player's to answer again.

CR 510.4: when anything has first or double strike there are two combat
damage steps, and each is its own assignment. Where a creature with banding
blocks (CR 702.22j) the assignment is the **defending** player's — the
division among the blockers, and for an attacker that "may … assign its
combat damage as though it weren't blocked", whether it is.

A person *attacking* with a double striker has been asked per step since the
dialogs learned to reopen (``tests/ui/test_combat_assignment_ui_api.py``,
"Part 4"). The mirror was left: an **AI** attacking resolved both steps in
one call (``web/combat_prompts._ai_assign_combat_damage``), so the person
defending answered once and their answer was replayed for a step they had
never seen the board of — the blocker dead, or the damage they had kept on a
creature now better taken themself.

Every step a person takes here is an action a client sends, and what is read
back is the state API.
"""
from __future__ import annotations

from tests.helpers import _mk_creature_card
from tests.ui import test_combat_assignment_ui_api as wire

OFFER = wire.OFFER


def _double_striker(power: int = 3, toughness: int = 6, offer: bool = True):
    text = "Double strike" + (f"\n{OFFER}" if offer else "")
    return _mk_creature_card("Twice-Striking Beast", power, toughness, text)


def _ai_attacks(attackers, blockers):
    """The AI (seat 1) attacks a person (seat 0) who blocks attacker 0 with
    every one of *blockers*; advanced until the game stops at combat damage."""
    sid, game, mine, theirs, _ = wire._to_combat_damage(
        attackers, blockers, mode="human_vs_ai", attacker_seat=1,
    )
    for _ in range(8):
        state = wire._state(sid, 0)
        if state["current_step"] == "combat_damage" or state["current_turn_phase"] != "combat":
            break
        if state.get("priority_player") == 0:
            assert wire._act(sid, seat=0, action="pass_priority").status_code == 200
        else:
            assert wire._act(sid, seat=0, action="ai_step").status_code == 200
    return sid, game, mine, theirs


def test_the_defender_is_asked_again_for_the_second_step():
    """A 3/6 double striker with the offer, blocked by a 1/4 with banding.
    First step: the person keeps the damage on the blocker (3 marked on a
    1/4). Second step: asked again, and this time they take it themself —
    three more would kill the blocker. Before: one answer, dealt twice; the
    blocker died and the person was never asked."""
    sid, game, (beast,), (sentry,) = _ai_attacks(
        [_double_striker()],
        [wire._wall("Banding Sentry", power=1, toughness=4, text="Banding")],
    )
    state = wire._state(sid, 0)
    assert state["current_step"] == "combat_damage"
    assert state["combat"]["first_strike_done"] is False
    assert [e["attacker_id"] for e in state["banding_assignment"]["attackers"]] == [
        beast.permanent_id
    ]

    first = wire._act(sid, seat=0, action="assign_banding_damage",
                      banding_damage={"0": {"0": 3}})
    assert first.status_code == 200, first.text

    # The first-strike step, and only it: three on the blocker, and the
    # question is the defending player's again.
    state = wire._state(sid, 0)
    assert state["combat"]["first_strike_done"] is True
    assert state["combat"]["damage_resolved"] is False, "both steps were dealt on one answer"
    assert sentry.damage_marked == 3 and game.players[0].life == 20
    assert [e["attacker_id"] for e in state["banding_assignment"]["attackers"]] == [
        beast.permanent_id
    ]
    # The AI does not move past it.
    assert wire._act(sid, seat=0, action="ai_step").status_code == 200
    assert wire._state(sid, 0)["combat"]["damage_resolved"] is False

    second = wire._act(sid, seat=0, action="assign_banding_damage",
                       banding_damage={}, as_though_unblocked_ids=[beast.permanent_id])
    assert second.status_code == 200, second.text
    assert game.combat_damage_resolved
    assert game.players[0].life == 17
    assert any(permanent is sentry for permanent in game.controlled_by(0)), (
        "the blocker the second answer spared was dealt the first answer again"
    )


def test_a_division_is_asked_again_over_the_board_the_first_step_left():
    """A 2/6 double striker (no offer) blocked by a 1/1 with banding and a
    0/3. First step: both points on the 1/1, which dies. Second step: one
    creature is left blocking, there is nothing to divide (CR 510.1c) and
    nobody is asked — the AI deals it."""
    sid, game, (beast,), (hero, wall) = _ai_attacks(
        [_double_striker(power=2, offer=False)],
        [wire._wall("Banding Hero", power=1, toughness=1, text="Banding"),
         wire._wall("Plain Wall", power=0, toughness=3)],
    )
    state = wire._state(sid, 0)
    assert state["banding_assignment"]["attacker_indices"] == [0]

    first = wire._act(sid, seat=0, action="assign_banding_damage",
                      banding_damage={"0": {"0": 2, "1": 0}})
    assert first.status_code == 200, first.text
    for _ in range(4):
        if game.combat_damage_resolved:
            break
        assert wire._act(sid, seat=0, action="ai_step").status_code == 200
    assert game.combat_damage_resolved, "the second step was never dealt"
    survivors = [permanent.card.name for permanent in game.controlled_by(0)]
    assert survivors == ["Plain Wall"]
    assert wall.damage_marked == 2 or game.current_turn_phase != "combat"


def test_two_blockers_still_standing_are_divided_among_again():
    """A 2/6 double striker blocked by a 1/3 with banding and a 0/3: the
    first step's two points go on one, and the second step's are the
    defending player's to put on the other — nobody dies. Replayed, the
    first answer killed the creature it had been put on."""
    sid, game, (beast,), (hero, wall) = _ai_attacks(
        [_double_striker(power=2, offer=False)],
        [wire._wall("Banding Hero", power=1, toughness=3, text="Banding"),
         wire._wall("Plain Wall", power=0, toughness=3)],
    )
    first = wire._act(sid, seat=0, action="assign_banding_damage",
                      banding_damage={"0": {"0": 2, "1": 0}})
    assert first.status_code == 200, first.text
    state = wire._state(sid, 0)
    assert state["combat"]["first_strike_done"] is True
    assert state["combat"]["damage_resolved"] is False
    assert state["banding_assignment"]["attacker_indices"] == [0]
    assert hero.damage_marked == 2 and wall.damage_marked == 0

    second = wire._act(sid, seat=0, action="assign_banding_damage",
                       banding_damage={"0": {"0": 0, "1": 2}})
    assert second.status_code == 200, second.text
    assert game.combat_damage_resolved
    assert sorted(permanent.card.name for permanent in game.controlled_by(0)) == [
        "Banding Hero", "Plain Wall",
    ]
