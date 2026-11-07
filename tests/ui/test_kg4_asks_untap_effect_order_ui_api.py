"""CR 616.1e inside the untap step, through the web layer.

Freyalise's Winds' counter on an Undiscovered Paradise due back to its
owner's hand this untap step: both replace its untap (CR 614), and its
controller chooses which applies (616.1e). The untap step gives nobody
priority (CR 502.4), so the web's beginning phase is what must wait: it
pauses on the question before the upkeep, as it does for the untap step's
type choice, and the answer resumes it (round kg4 `asks`).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.handlers.returns import RETURN_AT_NEXT_UNTAP_SEAT
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on
import web.app as webapp
from web.app import app
from tests.helpers import seat_plays_first

client = TestClient(app)

_SHIPPED = {card.name: card for card in load_catalog()}


def _session():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2,
              "guest_colors": 2, "seed": 4245},
    ).json()
    sid = created["session_id"]
    session = seat_plays_first(sid)
    game = session.game
    winds = Permanent(card=_SHIPPED["Freyalise's Winds"])
    paradise = Permanent(card=_SHIPPED["Undiscovered Paradise"])
    for player in game.players:
        player.battlefield = []
    game._put_permanent_onto_battlefield(1, winds, None)
    game._put_permanent_onto_battlefield(0, paradise, None)
    game.pending_choices.clear()
    paradise.tapped = True
    paradise.metadata[RETURN_AT_NEXT_UNTAP_SEAT] = 0
    add_counters(paradise, "wind", 1)
    return sid, session, game, paradise


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def test_the_beginning_phase_waits_for_the_untap_question_and_the_answer_resumes_it():
    for option in (0, 1):
        sid, session, game, paradise = _session()
        webapp._begin_turn(session, 0, defer_untap_selection=True)

        state = _state(sid)
        prompt = state["effect_order"]
        assert prompt is not None, "armed and never rendered"
        assert prompt["player_seat"] == 0 and prompt["event_kind"] == "would_untap"
        assert len(prompt["options"]) == 2
        assert state["waiting_on_prompt"] is True
        # The upkeep has not begun: the phase is paused in the untap step.
        assert game.current_step == "untap"
        assert session.paused_beginning_phase == ("untap_step", 0)
        assert paradise.tapped and counters_on(paradise, "wind") == 1

        answered = client.post(f"/api/sessions/{sid}/action", json={
            "seat": 0, "action": "effect_order_confirm", "option_index": option,
        })
        assert answered.status_code == 200, answered.text
        assert answered.json()["effect_order"] is None
        if "counter" in prompt["options"][option]:
            assert game.is_on_battlefield(paradise) and paradise.tapped
            assert counters_on(paradise, "wind") == 0
        else:
            assert not game.is_on_battlefield(paradise)
            assert [card.name for card in game.players[0].hand].count(
                "Undiscovered Paradise"
            ) == 1
        # …and the phase moved on past the untap step.
        assert session.paused_beginning_phase is None
        assert game.current_step != "untap"
