"""The keep-or-mulligan prompt says what a keep costs (CR 103.5, 103.5c).

CR 103.5: a player who takes a mulligan "puts a number of those cards equal to
the number of times that player has taken a mulligan on the bottom of their
library". CR 103.5c: "In a multiplayer game and in any Brawl game, the first
mulligan a player takes doesn't count toward the number of cards that player
will put on the bottom of their library or the number of mulligans that player
may take."

The server always counted that way (``Game.mulligan_effective_count``); the
client's two mulligan prompts did not. ``applyMulliganPrompt`` said "you will
put N cards on the bottom" from the raw ``mulligans_taken`` and hid the Take
Mulligan button at seven of them, and ``applyMulliganBottomPrompt`` said "You
took N mulligans" from the cards owed. The offer now carries ``bottom_owed``
and ``may_mulligan`` (``pregame._keep_terms``, the refusal's own predicate)
and the bottom choice carries ``mulligans_taken``; each sentence reads its own
key. The client half runs the real ``app.js`` functions over the payloads the
server served.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from web.app import app, store
from web.pregame import _round_undecided
from web.seats import _seat_type

from tests.helpers import run_app_js

client = TestClient(app)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_THREE = [
    {"name": "Host", "is_ai": False},
    {"name": "Bot1", "is_ai": True},
    {"name": "Bot2", "is_ai": True},
]


def _create(body: dict) -> str:
    created = client.post("/api/sessions", json=body)
    assert created.status_code == 200, created.text
    return created.json()["session_id"]


def _post(sid: str, action: str, **extra):
    return client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": action, **extra}
    )


def _pregame(sid: str) -> dict | None:
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": 0})
    assert response.status_code == 200, response.text
    return response.json()["pregame"]


def _host_at_the_keep(body: dict) -> str:
    """A table, past the flip, at the host's first keep-or-mulligan offer."""
    for seed in range(1, 80):
        sid = _create({**body, "seed": seed, "enable_pregame": True})
        session = store.get(sid)
        if session.pregame_phase == "coin_flip":
            if _seat_type(session, session.coin_flip_winner) != "human":
                continue
            assert _post(sid, "coin_flip_choose", hand_index=0).status_code == 200
        info = _pregame(sid)
        if info and info["phase"] == "mulligan" and info["is_my_turn"]:
            return sid
    raise AssertionError("no seed in range reached the host's offer")


def _mulligan_until_refused(sid: str) -> list[dict]:
    """Take mulligans as the host until the server refuses one, returning
    every offer the host was served on the way (the first included)."""
    offers = [_pregame(sid)]
    for _ in range(12):
        taken = _post(sid, "mulligan_take")
        if taken.status_code != 200:
            assert "hand would be 0 cards" in taken.text, taken.text
            return offers
        info = _pregame(sid)
        assert info["phase"] == "mulligan" and info["is_my_turn"], info
        offers.append(info)
    raise AssertionError("the server never refused a mulligan")


@pytest.mark.parametrize("label, body, free", [
    ("two seats", {"mode": "human_vs_ai"}, 0),
    ("three seats", {"mode": "free_for_all", "seats": _THREE}, 1),
    ("three seats, simultaneous", {
        "mode": "free_for_all", "seats": _THREE, "simultaneous_mulligan": True,
    }, 1),
    ("two-seat Brawl", {"mode": "human_vs_ai", "format": "brawl"}, 1),
])
def test_every_offer_says_what_a_keep_owes_and_whether_another_may_be_taken(label, body, free):
    sid = _host_at_the_keep(body)
    game = store.get(sid).game
    offers = _mulligan_until_refused(sid)
    # CR 103.5 stops at a hand of zero cards: seven counted mulligans, and
    # CR 103.5c's free first one buys an eighth.
    assert len(offers) == 8 + free, (label, len(offers))
    for taken, info in enumerate(offers):
        assert info["mulligans_taken"] == taken, label
        assert info["bottom_owed"] == max(0, taken - free), (label, info)
        assert info["may_mulligan"] is (taken < 7 + free), (label, info)
    assert offers[-1]["bottom_owed"] == game.mulligan_effective_count(0) == 7


@pytest.mark.parametrize("simultaneous", [False, True])
def test_the_bottom_choice_carries_the_mulligans_taken_beside_the_cards_owed(simultaneous):
    sid = _host_at_the_keep({
        "mode": "free_for_all", "seats": _THREE, "simultaneous_mulligan": simultaneous,
    })
    for _ in range(2):
        assert _post(sid, "mulligan_take").status_code == 200
    assert _post(sid, "mulligan_keep").status_code == 200
    info = _pregame(sid)
    assert info["phase"] == "bottom_select" and info["is_my_turn"], info
    assert info["mulligans_taken"] == 2
    assert info["required_count"] == 1  # CR 103.5c: the first one was free


_PRELUDE = r"""
var seat = 0;
function makeEl(id) {
  return {
    id, textContent: "", disabled: false, _html: "", onclick: null,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    addEventListener() {},
  };
}
const ELS = {};
function q(id) { if (!ELS[id]) ELS[id] = makeEl(id); return ELS[id]; }
const document = { getElementById: (id) => q(id) };
function escapeHtml(s) { return String(s); }
async function sendAction() {}
"""

_OFFER_BODY = """
applyMulliganPrompt(INPUT.info);
return {
  title: q("promptTitle").textContent,
  body: q("promptBody").textContent,
  steps: q("promptSteps").innerHTML,
};
"""

_BOTTOM_BODY = """
applyMulliganBottomPrompt(INPUT.info);
return {title: q("promptTitle").textContent, body: q("promptBody").textContent};
"""


#: What the offer reads besides the pregame info since Darksteel's wave 2: the
#: hand it counts ("Your hand has N cards") and the Serum Powder pick it may
#: be showing instead (``mulliganExchangePick``, none here).
_OFFER_PRELUDE = _PRELUDE + r"""
var currentState = {players: [{hand: [{}, {}, {}, {}, {}, {}, {}]}]};
var mulliganExchangePick = null;
"""


def _render_offer(info: dict) -> dict:
    return run_app_js(
        ["applyMulliganPrompt", "mulliganViewerHand"], _OFFER_BODY, {"info": info},
        prelude=_OFFER_PRELUDE,
    )


@needs_node
def test_the_offer_s_words_are_the_served_terms_at_a_three_seat_table():
    sid = _host_at_the_keep({"mode": "free_for_all", "seats": _THREE})
    offers = _mulligan_until_refused(sid)

    first = _render_offer(offers[1])  # one mulligan taken: it was free
    assert "You have taken 1 mulligan." in first["body"], first
    assert "put no cards on the bottom — your first mulligan is free" in first["body"], first
    assert "If you keep, you will put no cards on the bottom." in first["steps"], first
    assert "1 card on the bottom" not in first["body"] + first["steps"], first

    second = _render_offer(offers[2])
    assert "you'll put 1 card on the bottom — your first mulligan is free" in second["body"], second
    assert "If you keep, you will put 1 card on the bottom." in second["steps"], second

    # Seven taken, six counted: CR 103.5c leaves one more to take.
    seventh = _render_offer(offers[7])
    assert 'id="mulliganTakeBtn"' in seventh["steps"], seventh
    last = _render_offer(offers[8])
    assert 'id="mulliganTakeBtn"' not in last["steps"], last
    assert 'id="mulliganKeepBtn"' in last["steps"], last


@needs_node
def test_a_two_seat_offer_still_owes_a_card_per_mulligan():
    sid = _host_at_the_keep({"mode": "human_vs_ai"})
    assert _post(sid, "mulligan_take").status_code == 200
    shown = _render_offer(_pregame(sid))
    assert "you'll put 1 card on the bottom)" in shown["body"], shown
    assert "free" not in shown["body"], shown
    assert 'id="mulliganTakeBtn"' in shown["steps"], shown


@needs_node
def test_the_bottom_choice_says_how_many_were_taken_and_how_many_go():
    sid = _host_at_the_keep({"mode": "free_for_all", "seats": _THREE})
    for _ in range(2):
        assert _post(sid, "mulligan_take").status_code == 200
    assert _post(sid, "mulligan_keep").status_code == 200
    shown = run_app_js(
        ["applyMulliganBottomPrompt"], _BOTTOM_BODY, {"info": _pregame(sid)}, prelude=_PRELUDE,
    )
    assert shown["title"] == "Put 1 Card on the Bottom"
    assert shown["body"].startswith(
        "You took 2 mulligans (your first one was free). Click 1 card in your hand"
    ), shown
