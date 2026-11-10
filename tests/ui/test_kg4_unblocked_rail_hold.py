"""The phase rail's hold on an AI's turn hands priority on until a person
holds it (CR 117.3d), and hands nobody anything once every player has passed
(CR 117.4).

``game_flow._hold_at_flagged_step`` (``seats._hold_priority_for_human`` when
this was written) is what a step the person flagged on the
rail does on the AI's turn: the active AI passes, and the person holds
priority. It passed once and answered True whatever the pass said. At a
three-player table the seat after the active AI may be another AI — a seat
no request drives (``ai_step`` acts for the seat whose turn it is) — and the
game stopped there for good. And where that pass was the last of a round
(every player still in the game passed in succession; a person who has left
is skipped, CR 800.4) the step was over, yet the hold reported a hand-off
and the next request held the step again and offered priority once more.
"""

from __future__ import annotations

from collections import Counter

import pytest

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import client, seat_plays_first
from web.game_flow import _hold_at_flagged_step

_CARDS = {card.name: card for card in load_catalog()}


def _session(seats):
    created = client.post(
        "/api/sessions", json={"mode": "free_for_all", "seed": 11, "seats": seats},
    ).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, 1)
    for player in session.game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.library = [_CARDS["Plains"]] * 12
    return sid, session


def _put(game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_CARDS[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat={seat}").json()


def _act(sid: str, seat: int = 0, **body) -> dict:
    response = client.post(f"/api/sessions/{sid}/action", json={"seat": seat, **body})
    assert response.status_code == 200, (body, response.json())
    return response.json()


_SEATS = [{"name": f"P{i}", "is_ai": i != 0, "colors": 2} for i in range(3)]


_EVERY_STEP = [
    "upkeep", "draw", "precombat_main", "beginning_of_combat", "declare_attackers",
    "declare_blockers", "combat_damage", "end_of_combat", "postcombat_main", "end",
]


@pytest.mark.cr("117.3d", "117.4")
def test_the_rails_hold_hands_priority_past_another_ai_to_the_person():
    """A three-player free-for-all, the person in seat 0, the AIs in 1 and 2;
    the AI in seat 1 attacks and the person flags every step. Each flagged
    step, the person is handed priority once over an empty stack — after the
    other AI has passed it on — and the turn ends. The hold passed the active
    AI's priority once and stopped with it at seat 2."""
    sid, session = _session(_SEATS)
    game = session.game
    session.force_ai_attack_all = True
    _put(game, 1, "Grizzly Bears")

    asked: Counter = Counter()
    for _ in range(80):
        state = _state(sid)
        if state["current_turn"] != 1:
            break
        if state["priority_player"] == 0:
            asked[(state["current_step"], len(state["stack"]))] += 1
            _act(sid, action="pass_priority", stop_steps=_EVERY_STEP)
        else:
            _act(sid, action="ai_step", stop_steps=_EVERY_STEP)
    else:
        raise AssertionError(f"the AI's turn never ended: {game.log[-12:]}")

    held = {step for step, stack in asked if stack == 0}
    assert {"precombat_main", "beginning_of_combat", "end"} <= held, asked
    assert all(count == 1 for count in asked.values()), asked


@pytest.mark.cr("117.4", "800.4")
def test_a_person_who_has_left_the_game_is_handed_nothing():
    """The same table with the person out of the game (CR 800.4: their
    priority is skipped; the game goes on between the AIs) and their rail
    still flagging every step. Nobody is left to hand priority to: the hold
    hands nothing on and the AI's turn goes on. It passed the active AI's
    priority to the other AI and reported a hand-off, every request."""
    sid, session = _session(_SEATS)
    game = session.game
    game.players[0].life = 0
    game.check_state_based_actions()
    assert game.players[0].lost and not game.is_game_over()

    session.opponent_stop_steps = set(_EVERY_STEP)
    assert _hold_at_flagged_step(session) is False
    for _ in range(40):
        if _state(sid)["current_turn"] != 1:
            break
        _act(sid, action="ai_step", stop_steps=_EVERY_STEP)
    else:
        raise AssertionError(f"the AI's turn never ended: {game.log[-12:]}")
