"""A web AI that plays a land keeps priority and goes on with its main phase
(CR 116.2a, 116.3: playing a land is a special action, and its player
receives priority again afterwards).

``game_flow._ai_step`` handed the priority round on after every supported play
from the hand, the land included, so the person was handed priority over an
empty stack in the AI's precombat main phase — and their pass, the client's
default there (``opponentDisabledPhases``), ended the phase (CR 117.4) before
the AI cast anything after its land. Every web AI with a land to play cast its
spells in its second main phase.
"""

from __future__ import annotations

import pytest

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import client, seat_plays_first

_CARDS = {card.name: card for card in load_catalog()}


@pytest.mark.cr("116.3", "117.4")
def test_the_ai_casts_after_its_land_in_the_same_main_phase():
    """The AI's turn 1, one Forest on its battlefield and Forest and Grizzly
    Bears in hand; the person passes whenever they hold priority, as their
    client does by default. The AI plays the Forest and casts the Bears in
    that same precombat main phase; the person is first asked there over the
    Bears on the stack, not over an empty stack after the land."""
    created = client.post("/api/sessions", json={"mode": "human_vs_ai", "seed": 5}).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, 1)
    game = session.game
    for player in game.players:
        player.battlefield = []
        player.graveyard = []
        player.library = [_CARDS["Plains"]] * 20
    game.players[0].hand = []
    game._put_permanent_onto_battlefield(1, Permanent(card=_CARDS["Forest"]), None)
    game.players[1].hand = [_CARDS["Forest"], _CARDS["Grizzly Bears"]]

    asked: list[tuple[str, int]] = []
    entered_in = None
    for _ in range(40):
        state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
        if state["current_turn"] != 1:
            break
        if state["priority_player"] == 0:
            asked.append((state["current_step"], len(state["stack"])))
            action = "pass_priority"
        else:
            action = "ai_step"
        response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": action})
        assert response.status_code == 200, response.json()
        if entered_in is None and any(
            p.card.name == "Grizzly Bears" for p in game.players[1].battlefield
        ):
            entered_in = game.current_step
    else:
        raise AssertionError(f"the AI's turn never ended: {game.log[-12:]}")

    assert [p.card.name for p in game.players[1].battlefield].count("Forest") == 2
    assert entered_in == "precombat_main", (entered_in, game.log[-20:])
    assert asked and asked[0] == ("precombat_main", 1), asked
