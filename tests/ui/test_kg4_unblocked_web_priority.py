"""On the web, "attacks and isn't blocked" goes round the table before it
resolves (CR 509.2a, 117.4).

CR 509.2a puts an ability that triggered as blockers were declared on the
stack before the active player gets priority in the declare blockers step,
and CR 117.4 resolves it only once every player has passed in succession.
The engine fired "attacks and isn't blocked" from the step's leaving pass,
so on the web both seats were given the step's priority over an empty stack,
passed it, and the leaving window resolved the trigger with nobody asked
(probe: ``scratch/kg4/webprio/probe_unblocked_trigger.py``). Every road a
declaration completes by is driven here as the browser drives it — the
person passes when served priority, declares when the blocks are theirs, and
otherwise asks for an ``ai_step`` (the AI's turn) or ``next_phase`` (their
own): the AI attacking a person who declares no blocks, a person with no
creature (``game_flow._declares_for_a_person_who_cannot_block``), a person
attacking the AI, and two people where the defender has no creature (the
engine's own lock, reached by the attacker's ``next_phase``).
"""

from __future__ import annotations

import pytest

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import client, seat_plays_first
from web.app import store

_CARDS = {card.name: card for card in load_catalog()}
_LANDS = [{"name": name, "count": 8} for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")]


def _session(mode: str, first: int, **payload):
    created = client.post(
        "/api/sessions", json={"mode": mode, "seed": 11, **payload},
    ).json()
    sid = created["session_id"]
    if mode == "human_vs_human":
        client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = seat_plays_first(sid, first)
    for player in session.game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.library = [_CARDS["Plains"]] * 12
    return sid, session


def _put(game, seat: int, names) -> list:
    placed = []
    for name in names:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    return placed


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat={seat}").json()


def _act(sid: str, seat: int = 0, **body) -> dict:
    response = client.post(f"/api/sessions/{sid}/action", json={"seat": seat, **body})
    assert response.status_code == 200, (body, response.json())
    return response.json()


def _row(state: dict) -> tuple:
    """What a served state says about the declare blockers step: (step, who
    holds priority, blocks locked, the stack's labels)."""
    combat = state.get("combat") or {}
    return (
        state["current_step"], state["priority_player"],
        bool(combat.get("blockers_locked")),
        tuple(item["label"] for item in state["stack"]),
    )


def _play_the_ais_turn(sid: str, stops: list[str]) -> list[tuple]:
    """The AI's turn as the browser plays it; every state served in combat."""
    served = []
    for _ in range(80):
        state = _state(sid)
        if state["current_turn"] == 0 or state["status"] == "finished":
            return served
        if state["current_turn_phase"] == "combat":
            served.append(_row(state))
        combat = state.get("combat") or {}
        if state["priority_player"] == 0:
            _act(sid, action="pass_priority", stop_steps=stops)
        elif (
            state["current_step"] == "declare_blockers" and combat.get("attackers")
            and not combat.get("blockers_locked")
            and combat.get("defending_player_index") == 0
        ):
            _act(sid, action="declare_blockers", target_seat=0,
                 blocker_pairs_by_id={}, stop_steps=stops)
        else:
            _act(sid, action="ai_step", stop_steps=stops)
    raise AssertionError("the AI's turn never ended")


def _asked_over(served: list[tuple], seat: int, name: str) -> bool:
    """*seat* was served declare-blockers priority with *name*'s trigger on
    the stack, once the blocks were in."""
    return any(
        step == "declare_blockers" and holder == seat and locked
        and any(name in label for label in labels)
        for step, holder, locked, labels in served
    )


@pytest.mark.cr("509.2a", "117.4", "509.3g")
@pytest.mark.parametrize("stops", ([], ["declare_blockers"]))
@pytest.mark.parametrize("person_has_a_creature", (True, False))
@pytest.mark.parametrize("attacker", ("Murk Dwellers", "Goblin Vandal"))
def test_the_person_is_asked_over_the_ais_unblocked_trigger(stops, person_has_a_creature, attacker):
    """The AI attacks with Murk Dwellers ("…it gets +2/+0 until end of turn")
    or Goblin Vandal ("…you may pay {R}. If you do, destroy target artifact
    defending player controls …", which chooses its target as it goes on the
    stack). The person declares no blocks with a Wall of Wood, or has no
    creature; their rail holds the step or does not. The trigger is on the
    stack when the person is handed priority in the step, and it resolves
    after that."""
    sid, session = _session(
        "human_vs_ai", 1, host_deck_cards=_LANDS, guest_deck_cards=_LANDS,
    )
    game = session.game
    session.force_ai_attack_all = True
    _put(game, 1, [attacker, "Mountain"])
    _put(game, 0, ["Jayemdae Tome"])
    if person_has_a_creature:
        _put(game, 0, ["Wall of Wood"])

    served = _play_the_ais_turn(sid, stops)

    assert any(line.startswith(f"{attacker} triggered (attacked") for line in game.log), game.log[-25:]
    assert _asked_over(served, 0, attacker), (served, game.log[-25:])
    triggered = next(i for i, line in enumerate(game.log) if line.startswith(f"{attacker} triggered"))
    asked = next(i for i, line in enumerate(game.log) if i > triggered and line.startswith("Player 1 passed"))
    resolved = next(
        (i for i, line in enumerate(game.log) if i > triggered and f"{attacker} ability resolved" in line),
        None,
    )
    assert resolved is None or asked < resolved, game.log[triggered:]


@pytest.mark.cr("509.2a", "117.4")
def test_the_attacking_person_is_asked_over_their_unblocked_trigger():
    """The person attacks the AI, which has no creature, with Murk Dwellers.
    The AI's (empty) declaration is made by ``_advance_phase``'s
    ``declare_ai_blockers``, and CR 509.2 gives the person priority first,
    with the trigger on the stack."""
    sid, session = _session(
        "human_vs_ai", 0, host_deck_cards=_LANDS, guest_deck_cards=_LANDS,
    )
    game = session.game
    (dwellers,) = _put(game, 0, ["Murk Dwellers"])
    for _ in range(10):
        if _state(sid)["current_step"] == "declare_attackers":
            break
        _act(sid, action="next_phase")
    _act(sid, action="declare_attackers", attacker_ids=[dwellers.permanent_id], target_seat=1)
    served = []
    for _ in range(30):
        state = _state(sid)
        if state["current_turn_phase"] != "combat":
            break
        served.append(_row(state))
        if state["priority_player"] == 0:
            _act(sid, action="pass_priority")
        else:
            _act(sid, action="next_phase")

    assert "AI declared 0 blocker(s)" in game.log, game.log[-20:]
    assert _asked_over(served, 0, "Murk Dwellers"), (served, game.log[-20:])
    assert game.players[1].life == 16, game.log[-20:]


@pytest.mark.cr("509.2a", "509.1a", "117.4")
def test_two_people_are_both_asked_when_the_defender_has_no_creature():
    """Two people; the attacker's Murk Dwellers at a defender with no
    creature, whose declaration nobody makes: the attacker's ``next_phase``
    reaches the engine's own lock ("has no valid blockers"). The trigger is
    on the stack as the active person is handed priority, then the
    defender, and it resolves after both have passed."""
    sid, session = _session("human_vs_human", 0, host_colors=2, guest_colors=2)
    game = session.game
    (dwellers,) = _put(game, 0, ["Murk Dwellers"])
    for _ in range(10):
        if _state(sid)["current_step"] == "declare_attackers":
            break
        _act(sid, action="next_phase")
    _act(sid, action="declare_attackers", attacker_ids=[dwellers.permanent_id], target_seat=1)
    served = []
    for _ in range(30):
        state = _state(sid)
        if state["current_turn_phase"] != "combat":
            break
        served.append(_row(state))
        holder = state["priority_player"]
        if holder is None:
            _act(sid, action="next_phase")
        else:
            _act(sid, seat=holder, action="pass_priority")

    assert "Joiner has no valid blockers" in game.log, game.log[-20:]
    assert _asked_over(served, 0, "Murk Dwellers"), (served, game.log[-20:])
    assert _asked_over(served, 1, "Murk Dwellers"), (served, game.log[-20:])
    assert game.players[1].life == 16, game.log[-20:]



@pytest.mark.cr("509.2a", "117.4")
def test_a_refused_ai_declaration_still_puts_the_trigger_round_the_table(monkeypatch):
    """The web's safety valve: an AI defender whose every declaration was
    refused blocks with nobody (``declare_ai_blockers`` answers False —
    stubbed here, since no shipped board makes all three refusals). The
    blocks are locked through the engine's completion of a declaration, so
    the person's Murk Dwellers trigger is on the stack as the person is
    handed priority. The valve set the flag itself, and the step's leaving
    pass then fired the trigger and resolved it unasked."""
    import web.game_flow as game_flow

    sid, session = _session(
        "human_vs_ai", 0, host_deck_cards=_LANDS, guest_deck_cards=_LANDS,
    )
    game = session.game
    (dwellers,) = _put(game, 0, ["Murk Dwellers"])
    monkeypatch.setattr(game_flow, "declare_ai_blockers", lambda game, seat: False)
    for _ in range(10):
        if _state(sid)["current_step"] == "declare_attackers":
            break
        _act(sid, action="next_phase")
    _act(sid, action="declare_attackers", attacker_ids=[dwellers.permanent_id], target_seat=1)
    served = []
    for _ in range(30):
        state = _state(sid)
        if state["current_turn_phase"] != "combat":
            break
        served.append(_row(state))
        if state["priority_player"] == 0:
            _act(sid, action="pass_priority")
        else:
            _act(sid, action="next_phase")

    assert _asked_over(served, 0, "Murk Dwellers"), (served, game.log[-20:])
    assert game.players[1].life == 16, game.log[-20:]
