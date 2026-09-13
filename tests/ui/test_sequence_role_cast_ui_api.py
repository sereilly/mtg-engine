"""A roles cast whose seat slot is printed "target player **or planeswalker**".

Donate put a seat into a roles announcement and ``tests/ui/
test_player_role_cast_ui_api.py`` asserts that path. This is the same wire one
printed word wider: CR 115.4's union slot, which is answered by the very seats
the narrow spelling is answered by — so every reader that asked ``kind ==
"player"`` had the whole vocabulary right up until Shower of Sparks became a
roles spell, and then had half of it.

Four readers spelled that question for themselves: the cast gate's slot filler,
the CR 608.2b re-check, ``resolve_role_player`` and ``app.js``. They read
``engine.targeting.SEAT_ROLE_KINDS`` now, and the client mirrors it by name —
the failure a fifth spelling causes is not a crash but a seat slot filled from
the *permanent* channel, which then finds nothing in it.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack
from web.app import app, store

client = TestClient(app)

_USG = {c.name: c for c in load_cards(manifest_set_path("USG"))}
_M21 = {c.name: c for c in load_cards(manifest_set_path("M21"))}


def _sparks_session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 3434,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].hand = [_USG["Shower of Sparks"]]
    game.players[0].battlefield = []
    theirs = Permanent(card=_M21["Concordia Pegasus"])
    game.players[1].battlefield = [theirs]
    session.current_turn = 0
    game.active_player_index = 0
    game._sync_control()
    return sid, game, theirs


def test_the_picker_walks_a_creature_then_a_seat():
    """The payload the browser is handed: role 0 is the creature and its
    ``next`` holds the seats role 1 admits."""
    _sid, game, _theirs = _sparks_session()

    spec = game.cast_target_spec(0, _USG["Shower of Sparks"])

    assert [role["kind"] for role in spec["roles"]] == [
        "creature", "player_or_planeswalker",
    ]
    (creature,) = spec["valid_targets"]
    assert creature["name"] == "Concordia Pegasus"
    assert {option["kind"] for option in creature["next"]} == {"player"}
    assert {option["seat"] for option in creature["next"]} == {0, 1}


def test_a_seat_role_ref_lands_the_second_point_on_the_player():
    """The whole path, over HTTP: the browser sends one ref per role and the
    two halves of the sentence reach two different objects."""
    sid, game, theirs = _sparks_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Shower of Sparks",
            "target_role_refs": [
                {"permanent_id": game.permanent_id_of(theirs)},
                {"seat": 1},
            ],
        },
    )

    assert resp.status_code == 200, resp.text
    resolve_stack(game)
    assert game.players[1].life == 19
    assert sum(
        "dealt 1 damage to Concordia Pegasus" in line for line in game.log
    ) == 1


def test_the_client_reads_both_spellings_of_a_seat_role():
    """``app.js`` mirrors ``engine.targeting.SEAT_ROLE_KINDS``.

    Read as text (``tests.helpers.app_js_function_body``) for this file's
    neighbour's reason: the client is DOM-coupled and cannot be imported here,
    and which list the branch consults is the real answer.
    """
    from engine.targeting import SEAT_ROLE_KINDS
    from tests.helpers import app_js_function_body

    body = app_js_function_body("roleChoosesAPlayer")
    assert "SEAT_ROLE_KINDS.includes(role.kind)" in body
    source = (
        __import__("pathlib").Path("web/static/app.js").read_text(encoding="utf-8")
    )
    for kind in SEAT_ROLE_KINDS:
        assert f'"{kind}"' in source.split("const SEAT_ROLE_KINDS = ")[1][:120], (
            f"the client's seat-role list is missing {kind!r}; it mirrors "
            "engine.targeting.SEAT_ROLE_KINDS and a slot it does not know is "
            "one it waits for a card click on"
        )
