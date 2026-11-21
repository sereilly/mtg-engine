"""Champions of Kamigawa's prompts and gestures as a person meets them (CHK
wave 2, the client group, W2G1).

Every one of these was clicked in a browser first, on a session with the set
promoted (``MTG_PROMOTE=CHK``; the report says what was clicked); this file
holds what the clicks found. Each payload is the server's own, read from a web
session's state after the engine armed it; each client function is the real
source, lifted out of ``app.js`` (or ``battlefield-canvas.js``) by
``run_app_js``.

Champions of Kamigawa is a measured set until it is promoted, so no deck the
web app deals holds one of its cards: each test puts the cards it names onto a
session's board from ``set_pool``, which works on either manifest role.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.flip_cards import flip_permanent
from engine.models import Permanent
from web.app import app

from tests.helpers import run_app_js, seat_plays_first

client = TestClient(app)

#: The sets the cards below are first printed in, searched in this order.
_W2G1_SETS = ("CHK", "LEA", "MIR", "TMP", "5DN", "DST", "MRD", "ONS", "M21")


def _w2g1_card(set_pool, name: str):
    for code in _W2G1_SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w2g1_session(seed: int = 7):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
        "guest_colors": 2, "seed": seed,
    })
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    session = seat_plays_first(sid)
    game = session.game
    for player in game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
    game._sync_control()
    return sid, game


def _w2g1_place(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w2g1_state(sid: str, seat: int = 0) -> dict:
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def _w2g1_on_board(state: dict, seat: int, permanent_id: int) -> dict:
    return next(
        entry for entry in state["players"][seat]["battlefield"]
        if entry["id"] == permanent_id
    )


# ---------------------------------------------------------------------------
# Flip cards (CR 710): the marker, and the viewer's two halves
# ---------------------------------------------------------------------------

_W2G1_FLIP_PRELUDE = """
function escapeHtml(value) { return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;"); }
function renderSymbolsInline(text) { return escapeHtml(text); }
"""


def test_w2g1_a_flipped_permanent_is_marked_and_its_viewer_shows_both_halves(set_pool):
    """CR 710.3: whether a permanent is flipped is clear at all times. The
    canvas marks exactly the flipped Jushi Apprentice (`_isFlipped`: the art
    turned and a FLIPPED ribbon); the viewer names the half that applies —
    Tomoya the Revealer for the flipped one, Jushi Apprentice for the one that
    has not flipped and for the card in hand (CR 710.2) — and prints the other
    half upside down."""
    sid, game = _w2g1_session()
    jushi = _w2g1_card(set_pool, "Jushi Apprentice")
    flipped = _w2g1_place(game, 0, jushi)
    unflipped = _w2g1_place(game, 0, jushi)
    game.players[0].hand = [jushi]
    assert flip_permanent(game, flipped)
    game._recompute_continuous_effects()
    state = _w2g1_state(sid)
    payloads = [
        _w2g1_on_board(state, 0, flipped.permanent_id),
        _w2g1_on_board(state, 0, unflipped.permanent_id),
        state["players"][0]["hand"][0],
    ]
    assert [entry["name"] for entry in payloads] == [
        "Tomoya the Revealer", "Jushi Apprentice", "Jushi Apprentice",
    ]
    seen = run_app_js(
        ["_isFlipped", "flipPreviewHalves", "flipPreviewLead", "flipPreviewInactiveHtml"],
        """
        return INPUT.map((card) => {
          const halves = flipPreviewHalves(card);
          return {
            marked: _isFlipped(card),
            active: halves.active.name,
            inactive: halves.inactive.name,
            lead: flipPreviewLead(halves),
            upsideDown: flipPreviewInactiveHtml(halves.inactive),
          };
        });
        """,
        payloads,
        prelude=_W2G1_FLIP_PRELUDE,
        scripts=("battlefield-canvas.js", "app.js"),
    )
    assert [(row["marked"], row["active"], row["inactive"]) for row in seen] == [
        (True, "Tomoya the Revealer", "Jushi Apprentice"),
        (False, "Jushi Apprentice", "Tomoya the Revealer"),
        (False, "Jushi Apprentice", "Tomoya the Revealer"),
    ]
    assert seen[0]["lead"].startswith("⇅ Flipped")
    assert "not flipped" in seen[1]["lead"]
    assert "off the battlefield" in seen[2]["lead"]
    assert 'class="preview-flip-inactive"' in seen[0]["upsideDown"]
    assert "Jushi Apprentice 1/2" in seen[0]["upsideDown"]
    assert "Tomoya the Revealer 2/3" in seen[1]["upsideDown"]


def test_w2g1_a_card_with_one_half_has_no_flip_viewer(set_pool):
    """A card printing one half carries no `flip`, and the viewer adds nothing
    for it — nor for a bare name."""
    sid, game = _w2g1_session()
    bears = _w2g1_place(game, 0, _w2g1_card(set_pool, "Grizzly Bears"))
    state = _w2g1_state(sid)
    payload = _w2g1_on_board(state, 0, bears.permanent_id)
    assert "flip" not in payload and payload["flipped"] is False
    seen = run_app_js(
        ["_isFlipped", "flipPreviewHalves"],
        "return [flipPreviewHalves(INPUT), flipPreviewHalves('Grizzly Bears'), _isFlipped(INPUT)];",
        payload,
        scripts=("battlefield-canvas.js", "app.js"),
    )
    assert seen == [None, None, False]
