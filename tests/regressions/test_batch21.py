"""Regression tests for the twenty-first batch of bugs reported in-game.

Clusters covered in this batch:
- Upkeep priority hold: a player who flagged the upkeep stop on the phase rail
  ("hold priority on my upkeep") was shown the pay-or-sacrifice prompt for their
  own upkeep trigger before the priority window ever opened, so they could not
  act first. CR 503.1/503.1a give the active player priority at the start of
  upkeep with the triggers on the stack; the "unless you pay" choice belongs to
  the trigger's resolution, after that window. The prompt is now held back until
  the window closes, and mana floated during the window still pays the cost.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from tests.helpers import CARDS_BY_NAME as _C
from web.app import app, store, _end_turn

client = TestClient(app)


# ---------------------------------------------------------------------------
# "I tried to hold priority on my upkeep, but I had an upkeep trigger that
#  showed a prompt before I had a chance to do anything else first."
# ---------------------------------------------------------------------------


def _stasis_upkeep_session(*, hold_upkeep: bool, mode: str = "human_vs_human"):
    """A session parked on P0's second upkeep with Stasis ({U} or sacrifice) and
    an untapped Island out. `hold_upkeep` mirrors the phase-rail upkeep toggle."""
    payload = {"mode": mode, "host_name": "P1", "guest_name": "P2", "seed": 21001}
    if mode == "human_vs_ai":
        payload |= {"host_colors": 2, "guest_colors": 2}
    sid = client.post("/api/sessions", json=payload).json()["session_id"]
    if mode == "human_vs_human":
        client.post(f"/api/sessions/{sid}/join", json={"guest_name": "P2"})

    session = store.get(sid)
    session.self_stop_steps = {"upkeep"} if hold_upkeep else set()
    p0 = session.game.players[0]
    p0.battlefield = [Permanent(card=_C["Stasis"]), Permanent(card=_C["Island"])]
    p0.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    p0.hand = []

    _end_turn(session, allow_manual_cleanup_selection=False)  # → P1's turn
    _end_turn(session, allow_manual_cleanup_selection=False)  # → P0's turn 2
    return sid, session, p0


def _upkeep_pay_info(sid: str):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["upkeep_pay"]


class TestUpkeepPriorityHold:
    def test_priority_window_opens_before_the_trigger_prompt(self):
        sid, session, p0 = _stasis_upkeep_session(hold_upkeep=True)

        assert session.game.current_step == "upkeep"
        assert session.game.priority_player_index == 0, "the active player holds the CR 503.1 window"
        assert session.upkeep_decisions_deferred is True
        # The prompt that used to jump the queue must not be up yet...
        assert _upkeep_pay_info(sid) is None
        assert session.upkeep_pay_choices == []
        # ...and the trigger has not resolved either way.
        assert any(perm.card.name == "Stasis" for perm in p0.battlefield)

    def test_player_can_act_in_the_window_then_answers_the_prompt(self):
        sid, session, p0 = _stasis_upkeep_session(hold_upkeep=True)

        # Acting first is the whole point of the hold: tap Island for {U}.
        tapped = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "tap", "permanent_name": "Island"},
        )
        assert tapped.status_code == 200, tapped.text
        assert p0.mana_pool["U"] == 1

        # Passing through the window surfaces the upkeep prompt, still at upkeep.
        advanced = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "next_phase"},
        )
        assert advanced.status_code == 200, advanced.text
        assert advanced.json()["current_step"] == "upkeep"
        assert session.upkeep_decisions_deferred is False
        info = _upkeep_pay_info(sid)
        assert info is not None
        assert any(c["card_name"] == "Stasis" for c in info["choices"])

        # The mana floated during the window is still there to pay with — the
        # deferred resolution must not have ended the step out from under it.
        assert p0.mana_pool["U"] == 1
        paid = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "pay_upkeep", "card_name": "Stasis"},
        )
        assert paid.status_code == 200, paid.text
        assert any(perm.card.name == "Stasis" for perm in p0.battlefield)
        assert session.game.current_turn_phase == "precombat_main"

    def test_passing_priority_also_surfaces_the_prompt(self):
        """The other way out of the window: pass priority rather than Next Phase."""
        sid, session, p0 = _stasis_upkeep_session(hold_upkeep=True, mode="human_vs_ai")

        passed = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "pass_priority"},
        )
        assert passed.status_code == 200, passed.text
        assert session.game.current_step == "upkeep"
        assert any(c["card_name"] == "Stasis" for c in session.upkeep_pay_choices)

    def test_ending_the_turn_cannot_skip_the_held_upkeep(self):
        sid, session, p0 = _stasis_upkeep_session(hold_upkeep=True)

        ended = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "end_turn"},
        )
        assert ended.status_code == 400
        assert session.game.current_step == "upkeep"
        assert any(perm.card.name == "Stasis" for perm in p0.battlefield)

    def test_without_the_hold_the_prompt_still_comes_straight_away(self):
        """Unflagged upkeeps keep the old behavior — the prompt is the pause."""
        sid, session, p0 = _stasis_upkeep_session(hold_upkeep=False)

        assert session.game.current_step == "upkeep"
        assert session.upkeep_decisions_deferred is False
        info = _upkeep_pay_info(sid)
        assert info is not None
        assert any(c["card_name"] == "Stasis" for c in info["choices"])
