"""A face-down creature looked at by an effect, on the wire (Onslaught, W1G2).

CR 708.5: "You can't look at … face-down spells or permanents controlled by
another player" — unless an effect says to. Aven Soulgazer's "{2}{W}: Look at
target face-down creature." says to, for its controller alone (Spy Network's
2004-10-04 ruling: "Only you get to look. You can't show them to others.").

So the looker's state payload carries the hidden card on the
``face_down_look`` prompt, addressed by the permanent's id — and the other
seat's payload and a spectator's carry nothing of it, anywhere, before or
after the look. The prompt is taken down by ``dismiss_face_down_look`` on the
one action route.

The client half (drawing the prompt and sending the dismissal) is a wave-2
group's; this pins what the server sends it.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from engine.face_down import face_down_card
from engine.models import Permanent
from tests.helpers import resolve_stack
from web.app import app, store
from web.state_view import build_state

client = TestClient(app)

#: What the face-down Colossus would give away.
SECRETS = ("Krosan Colossus", "{6}{G}{G}")


def _table(ons):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "H", "host_colors": 2,
              "guest_colors": 2, "seed": 12},
    ).json()
    session = store.get(created["session_id"])
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    p1, p2 = game.players
    p1.hand[:] = []
    p2.hand[:] = []
    soulgazer = Permanent(card=ons["Aven Soulgazer"])
    soulgazer.metadata["summoning_sickness_turn"] = -99
    colossus = Permanent(card=face_down_card(ons["Krosan Colossus"]))
    p1.battlefield[:] = [soulgazer]
    p2.battlefield[:] = [colossus]
    game._sync_control()
    game.active_player_index = session.current_turn = 0
    game.current_turn_phase, game.current_step = "precombat_main", "precombat_main"
    game.priority_player_index = 0
    return created["session_id"], session, game, colossus


def _leaks(payload) -> list[str]:
    text = json.dumps(payload, default=str)
    return [secret for secret in SECRETS if secret in text]


def test_only_the_looker_is_sent_the_face_down_card(set_pool):
    sid, session, game, colossus = _table(set_pool("ONS"))
    # Before the look: the Colossus's controller alone may see it (W1G1's
    # census holds the rest of that).
    assert _leaks(build_state(session, 0)) == []

    result = game.activate_permanent_ability(
        0, "Aven Soulgazer", target_player_index=1,
        target_permanent_ids=[colossus.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)

    looker = build_state(session, 0)
    look = looker["face_down_look"]
    assert look is not None and look["viewer_seat"] == 0
    (seen,) = look["permanents"]
    assert seen["id"] == colossus.permanent_id and seen["controller_seat"] == 1
    assert seen["card"]["name"] == "Krosan Colossus"
    assert looker["waiting_on_prompt"] is False, "a notification holds nothing"

    owner = build_state(session, 1)
    assert owner["face_down_look"] is None
    spectator = build_state(session, None)
    assert spectator["face_down_look"] is None and _leaks(spectator) == []
    # The opponent's own payload names its own hidden card (CR 708.5) — and
    # nothing in it says that seat 0 looked at anything but a face-down
    # creature: the log is every seat's.
    assert not any("Krosan Colossus" in line for line in game.log)
    assert any("looked at 1 face-down creature(s)" in line for line in owner["log"])

    answered = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "dismiss_face_down_look"},
    )
    assert answered.status_code == 200, answered.text
    assert build_state(session, 0)["face_down_look"] is None
    assert _leaks(build_state(session, 0)) == []
