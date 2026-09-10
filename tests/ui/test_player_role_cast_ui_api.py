"""A roles **cast** one of whose slots is a player, over HTTP.

Every roles announcement before this one names permanents (and, on the
activation side, a card in a graveyard), so the wire had two shapes: the
positional ``target_permanent_ids`` list, and ``target_role_refs`` for an
announcement whose slots sit in two zones. Donate — "Target player gains control
of target permanent you control" — is the first whose slot 0 is a **seat**, and
a seat fits neither: a hole in the id list cannot say whether the slot is a
player or a permanent that has left.

So ``TargetRoleRef`` grew a third alternative and ``_queue_spell_from_request``
translates it, at the boundary, into the two channels a cast already has — the
id list with ``None`` where the slot is not a permanent, and ``target_seat``,
which is where a stack item has carried "the player this spell targets" all
along. This asserts the whole path: the picker the browser is handed, the
announcement it sends back, and the board afterwards.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_UDS = {c.name: c for c in load_cards(manifest_set_path("UDS", include_measured=True))}
_M21 = {c.name: c for c in load_cards(manifest_set_path("M21", include_measured=True))}


def _donate_session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4141,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].hand = [_UDS["Donate"]]
    mine = Permanent(card=_M21["Concordia Pegasus"])
    game.players[0].battlefield = [mine]
    game.players[1].battlefield = []
    session.current_turn = 0
    game.active_player_index = 0
    game._sync_control()
    return sid, game, mine


def test_the_picker_offers_a_seat_for_the_first_role():
    """What the browser is handed: role 0's list is seats, each carrying under
    ``next`` the permanents role 1 would then allow."""
    sid, game, mine = _donate_session()

    spec = game.cast_target_spec(0, _UDS["Donate"])

    assert [role["kind"] for role in spec["roles"]] == ["player", "permanent"]
    assert [entry["kind"] for entry in spec["valid_targets"]] == ["player", "player"]
    assert {entry["seat"] for entry in spec["valid_targets"]} == {0, 1}
    for entry in spec["valid_targets"]:
        assert [step["index"] for step in entry["next"]] == [0]


def test_a_seat_role_ref_lands_the_control_change():
    """The announcement the walk sends: one ref per role, in role order, the
    first naming a seat and the second a permanent id."""
    sid, game, mine = _donate_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Donate",
            "target_role_refs": [
                {"seat": 1},
                {"permanent_id": mine.permanent_id},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    game._settle()

    assert game.controller_index_of(mine) == 1
    assert [p.card.name for p in game.players[1].battlefield] == [
        "Concordia Pegasus"
    ]


def test_a_stale_permanent_id_in_a_role_ref_refuses_the_cast():
    """A permanent that has left is never a fall back to whichever one now sits
    at its index.

    Refused by the **announcement gate** rather than by the preamble's 404, and
    that is the shape a role ref has always had: ``_resolve_permanent_ids``
    resolves ``target_permanent_ids`` and the singular ids, never the refs — so
    a stale slot arrives as an id nothing resolves and CR 601.2c declines the
    whole announcement. Asserted so a later change that starts 404ing them says
    so out loud.
    """
    sid, game, mine = _donate_session()
    game.remove_from_battlefield(mine)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Donate",
            "target_role_refs": [
                {"seat": 1},
                {"permanent_id": mine.permanent_id},
            ],
        },
    )
    assert resp.status_code == 400, resp.text


# --- The browser's half of the same announcement ---------------------------
def test_the_role_walk_sends_a_seat_ref_for_a_player_role():
    """``confirmRoleTargets`` builds the announcement, and a player slot has to
    take the wider shape for the same reason a graveyard slot does.

    Read as text (see ``tests.helpers.app_js_function_body``): ``app.js`` is
    DOM-coupled and cannot be loaded here, and which branch builds which body is
    the real answer rather than a paraphrase.
    """
    from tests.helpers import app_js_function_body

    body = app_js_function_body("confirmRoleTargets")
    assert 'return { seat: t.seat };' in body
    assert 'needsRoleRefs' in body and 't.zone === "player"' in body


def test_a_face_click_answers_the_walk_rather_than_sending_a_cast():
    """A life pill clicked while a roles walk stands on a player role is that
    step's answer. Guarded on the *current role* — a face clicked while the walk
    wants a permanent is a mis-click, and answering it would fill the wrong
    slot."""
    from tests.helpers import app_js_function_body

    body = app_js_function_body("handlePlayerTargetClick")
    assert 'pendingCastTarget.targetKind === "roles"' in body
    assert "roleChoosesAPlayer(currentRole(pendingCastTarget))" in body
    assert "chooseRolePlayer(targetSeat)" in body
