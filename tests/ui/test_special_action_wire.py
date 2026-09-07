"""The CR 116 special-action button reaches the server.

Exodus's promotion smoke test clicked "End Dominating Licid's effect" on a real
board and **nothing happened** — no log line, no mana spent, no error on
screen. The console had a 422:

    {"loc": ["body", "seat"], "msg": "Field required"}

``GameActionRequest.seat`` is required of every action and ``sendAction`` does
not add it, so each of the 124 call sites in ``web/static/app.js`` supplies it
itself. ``renderSpecialActions`` was the one that did not, which means every
CR 116 special action the UI has ever offered — 116.2c's Licids (Tempest's
five, Stronghold's, Exodus's two), 116.2d's Volrath's Curse, 116.2e's Circling
Vultures — answered a click with a rejected request since the buttons shipped.

Nothing could see it. ``tests/rules/test_special_actions.py`` drives the engine
seam, ``web/state_view`` serves the offer correctly, and the button renders: the
whole feature is right except the four fields the click puts in an envelope.
So this is pinned from both ends —

* the **body** the client builds, read out of ``app.js`` (the only reader of
  that line is the browser, and a missing field is silent there);
* the **API** behind it, which must accept that body and refuse the one without
  a seat, so neither side can drift alone.

The first assertion is deliberately over *every* ``sendAction`` call rather than
this one, because "one call site forgot the required field" is the bug class,
not the bug.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store
from web.runtime import CARD_BY_NAME

from ..helpers import resolve_stack

client = TestClient(app)

_APP_JS = Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"


def _send_action_bodies(source: str) -> list[tuple[int, str]]:
    """Every ``sendAction({ … })`` object literal in *source*, with its line.

    Brace-counted rather than regex-matched: the bodies are multi-line and
    contain nested objects, and a non-greedy match to the first ``}`` would
    stop inside one of them and report a missing field that is there.
    """
    bodies: list[tuple[int, str]] = []
    for match in re.finditer(r"sendAction\(\{", source):
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


def test_every_send_action_body_carries_the_required_seat():
    """``seat`` is the one field ``GameActionRequest`` requires and
    ``sendAction`` does not supply."""
    source = _APP_JS.read_text(encoding="utf-8")
    bodies = _send_action_bodies(source)
    assert len(bodies) > 100, "the scan stopped finding call sites"

    missing = [
        (line, " ".join(body.split())[:90])
        for line, body in bodies
        if "seat" not in _top_level_keys(body)
    ]
    assert missing == [], (
        "sendAction bodies without a `seat`; the server answers each with a "
        f"422 and the click does nothing: {missing}"
    )


def _licid_attached_to_a_bear():
    """A session whose seat 0 has a Dominating Licid attached to a Grizzly
    Bears it took control of — the board the button is offered on."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H",
        "host_colors": 2, "guest_colors": 2, "seed": 4,
    }).json()
    sid = created["session_id"]
    game = store.get(sid).game
    game.active_player_index = 0
    game.priority_player_index = 0

    licid = Permanent(card=CARD_BY_NAME["dominating licid"])
    bear = Permanent(card=CARD_BY_NAME["grizzly bears"])
    game._put_permanent_onto_battlefield(0, licid, None)
    game._put_permanent_onto_battlefield(1, bear, None)
    game._settle()
    licid.metadata.pop("summoning_sickness_turn", None)
    game.players[0].mana_pool["U"] = 5

    assert client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_name": "Dominating Licid",
        "permanent_id": licid.permanent_id, "ability_index": 0,
        "target_permanent_id": bear.permanent_id,
    }).status_code == 200
    resolve_stack(game)
    game.check_state_based_actions()
    game.priority_player_index = 0
    return sid, game, licid, bear


def test_the_state_offers_the_action_and_the_posted_body_is_accepted():
    """The offer is served, and the body the button builds takes it."""
    sid, game, licid, bear = _licid_attached_to_a_bear()

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert state["special_actions"] == [
        {"permanent_id": licid.permanent_id, "name": "Dominating Licid",
         "kind": "end_own_continuous_effect"}
    ]
    assert game.controller_index_of(bear) == 0

    entry = state["special_actions"][0]
    response = client.post(f"/api/sessions/{sid}/action", json={
        # Exactly what `renderSpecialActions` sends: `hand_index` is absent for
        # a permanent-made offer, which is what the two-address seam expects.
        "seat": 0,
        "action": "special_action",
        "permanent_id": entry["permanent_id"],
        "special_action_kind": entry["kind"],
    })
    assert response.status_code == 200, response.text
    assert licid.is_creature and not licid.has_type("aura")
    # And CR 704.3 ran on the way out, so the theft is over on this same poll.
    assert game.controller_index_of(bear) == 1


def test_the_same_body_without_a_seat_is_the_422_that_was_shipping():
    """The negative that names the defect: it is not that the action is
    unreachable, it is that one field was left out of the envelope."""
    sid, _game, licid, _bear = _licid_attached_to_a_bear()

    response = client.post(f"/api/sessions/{sid}/action", json={
        "action": "special_action",
        "permanent_id": licid.permanent_id,
        "special_action_kind": "end_own_continuous_effect",
    })
    assert response.status_code == 422
    assert any(
        detail.get("loc") == ["body", "seat"]
        for detail in response.json()["detail"]
    ), response.text
