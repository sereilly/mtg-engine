"""The upkeep prompt's *address* reaches the server — both ends of it.

``prompt_permanent_id`` is a field the server now requires of every upkeep
decision whose prompt carries one, and ``sendAction`` does not supply it: each
call site in ``web/static/app.js`` adds it by hand. That is precisely the
position ``GameActionRequest.seat`` was in when ``renderSpecialActions``
forgot it and made every CR 116 special action unreachable for four sets — no
log line, no error on screen, a 422 in a console nobody reads
(``tests/ui/test_special_action_wire.py`` tells that story). A new required
field earns the same guard, and this is it.

The failure mode here is quieter than a 422, which is why it is pinned rather
than trusted. A body missing the field gets a 400 with a readable detail, so
the *first* copy of a card would still look like it worked in manual play —
but the wire only exists so a player with **two** Breeding Pits can pay for one
and let the other go, and a call site that dropped the id would take that back
without failing anything. See ``tests/rules/test_upkeep_prompt_identity.py``
for the rule.

Pinned from both ends, as the special-action guard is:

* the **bodies** the client builds, read out of ``app.js`` — the only reader of
  those lines is a browser, and a missing field is silent there;
* the **API** behind them, which must take the body with the id and refuse the
  one without, so neither side can drift alone.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store
from web.runtime import CARD_BY_NAME
from web.turn_steps import _gather_upkeep_decisions

client = TestClient(app)

_APP_JS = Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"

#: Every action whose handler goes through ``_answered_upkeep_prompt``. A new
#: one belongs here the day it is registered — the list is short because the
#: upkeep protocol is the only prompt channel that does not run through
#: ``engine/pending_choices.py``.
_UPKEEP_PROMPT_ACTIONS = {
    "pay_upkeep",
    "sacrifice_upkeep",
    "resolve_optional_trigger",
    "pay_upkeep_prevention",
}


def _action_bodies(source: str) -> list[tuple[int, str]]:
    """Every ``sendAction({…})`` / ``submitPromptAction({…})`` object literal.

    Brace-counted rather than regex-matched, for the reason the special-action
    guard gives: the bodies are multi-line and hold nested objects, and a
    non-greedy match to the first ``}`` stops inside one of them and reports a
    missing field that is there.
    """
    bodies: list[tuple[int, str]] = []
    for match in re.finditer(r"(?:sendAction|submitPromptAction)\(\{", source):
        start = match.end() - 1
        depth = 0
        for index in range(start, len(source)):
            char = source[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    bodies.append((source.count("\n", 0, start) + 1,
                                   source[start:index + 1]))
                    break
    return bodies


def _top_level_keys(body: str) -> set[str]:
    """The keys of the outermost object literal, ignoring nested ones."""
    keys: set[str] = set()
    depth = 0
    for token in re.finditer(r"[{}]|([A-Za-z_$][\w$]*)\s*(?=[,:}])", body):
        text = token.group(0)
        if text == "{":
            depth += 1
            continue
        if text == "}":
            depth -= 1
            continue
        if depth == 1:
            keys.add(token.group(1))
    return keys


def _declared_action(body: str) -> str | None:
    """The literal ``action:`` string of an outermost object, if it has one."""
    match = re.search(r'\baction:\s*"([a-z_]+)"', body)
    return match.group(1) if match else None


def test_every_upkeep_prompt_body_carries_the_permanent_id():
    """The client half: no upkeep answer leaves the browser unaddressed."""
    source = _APP_JS.read_text(encoding="utf-8")
    bodies = _action_bodies(source)
    assert len(bodies) > 100, "the scan stopped finding call sites"

    upkeep_bodies = [
        (line, body) for line, body in bodies
        if _declared_action(body) in _UPKEEP_PROMPT_ACTIONS
    ]
    # All four actions, or the scan has drifted rather than the code.
    assert {_declared_action(b) for _line, b in upkeep_bodies} == _UPKEEP_PROMPT_ACTIONS

    missing = [
        (line, _declared_action(body))
        for line, body in upkeep_bodies
        if "prompt_permanent_id" not in _top_level_keys(body)
    ]
    assert missing == [], (
        "upkeep decision bodies without a `prompt_permanent_id`; the server "
        f"answers each with a 400 and the click does nothing: {missing}"
    )


def _two_breeding_pits():
    """A session whose seat 0 owes two upkeep payments with one card name.

    Two Breeding Pits is the smallest board on which the printed name is not an
    address, which is the board the whole field exists for.
    """
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H",
        "host_colors": 2, "guest_colors": 2, "seed": 9,
    }).json()
    sid = created["session_id"]
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.active_player_index = 0
    session.current_turn = 0

    kept = Permanent(card=CARD_BY_NAME["breeding pit"])
    doomed = Permanent(card=CARD_BY_NAME["breeding pit"])
    game.players[0].battlefield = [kept, doomed]
    game.players[0].mana_pool = {"B": 4}
    game._settle()
    game._set_phase_and_step("beginning", "upkeep")
    _gather_upkeep_decisions(session, 0)
    return sid, session, game, kept, doomed


def test_the_state_offers_two_prompts_and_the_posted_bodies_answer_them_apart():
    """The API half: the exact bodies the buttons build, one per permanent."""
    sid, session, game, kept, doomed = _two_breeding_pits()

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    choices = state["upkeep_pay"]["choices"]
    assert [c["card_name"] for c in choices] == ["Breeding Pit", "Breeding Pit"]
    assert {c["permanent_id"] for c in choices} == {
        kept.permanent_id, doomed.permanent_id
    }
    # Affordability is filed under the same key the answer will be, which is
    # what lets the client grey out one button and not the other.
    assert set(state["upkeep_pay"]["can_pay"]) == {
        str(kept.permanent_id), str(doomed.permanent_id)
    }

    paid = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "pay_upkeep", "card_name": "Breeding Pit",
        "prompt_permanent_id": kept.permanent_id,
    })
    assert paid.status_code == 200, paid.text
    # Still one decision open — the other Breeding Pit's.
    assert [c["permanent_id"] for c in
            client.get(f"/api/sessions/{sid}/state?seat=0").json()
            ["upkeep_pay"]["pending"]] == [doomed.permanent_id]

    dropped = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "sacrifice_upkeep", "card_name": "Breeding Pit",
        "prompt_permanent_id": doomed.permanent_id,
    })
    assert dropped.status_code == 200, dropped.text

    surviving = [p for p in game.players[0].battlefield
                 if p.card.name == "Breeding Pit"]
    assert [p.permanent_id for p in surviving] == [kept.permanent_id]
    assert [c.name for c in game.players[0].graveyard] == ["Breeding Pit"]


def test_the_same_body_without_the_id_is_refused():
    """The negative that names the defect: not that the action is unreachable,
    but that one field decides *which* decision is being answered."""
    sid, _session, _game, _kept, _doomed = _two_breeding_pits()

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "pay_upkeep", "card_name": "Breeding Pit",
    })
    assert response.status_code == 400
    assert "prompt_permanent_id" in response.json()["detail"], response.text


def test_an_id_that_is_not_pending_is_refused_rather_than_falling_back():
    """A stale id is not quietly downgraded to the name beside it.

    The client wrote its request against the board it last polled; if that
    permanent has gone, the name now points at a different decision. Acting on
    it is the bug — ``web/actions.py`` says the same of its own 404.
    """
    sid, _session, game, kept, doomed = _two_breeding_pits()

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "pay_upkeep", "card_name": "Breeding Pit",
        "prompt_permanent_id": max(kept.permanent_id, doomed.permanent_id) + 500,
    })
    assert response.status_code == 400
    assert "not awaiting" in response.json()["detail"], response.text
    # And nothing was decided on the way past.
    assert len([p for p in game.players[0].battlefield
                if p.card.name == "Breeding Pit"]) == 2
