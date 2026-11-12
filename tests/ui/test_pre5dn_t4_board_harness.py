"""The browser harness a client group drives with (pre5dn T4).

Darksteel's client group lost most of its time to two things, and each has a
half here:

* **No handle for a card's place on the canvas.** ``window.__boardPositions()``
  (``app.js``) and ``BattlefieldCanvas.debugPositions`` report every drawn
  card's page rectangle and a point a real click lands on, found by sending
  candidate points back through the press path itself (``_pressTarget``, which
  ``_handleMouseDown`` now asks). Run here for real: the whole of
  ``battlefield-canvas.js`` in node over a fake page, laid out from a state
  the server sent for a Darksteel board — a creature carrying two Equipment,
  a pile of lands — and every reported point pressed through the real
  ``_handleMouseDown``.
* **A server-side edit lost the board.** ``serve_board.py --reload`` pickles
  every session (``scripts/integration/board_pickle.py``) and loads them into
  the new process. What is held here: a played session reads back to the same
  payload, a resolution suspended for an answer (its loop's rest a closure)
  survives and finishes when answered, the identity sentinels stay
  themselves, and a field the new code added is filled.

Driven in a browser too (port 8024): a creature and an attached Equipment
clicked by id on a Darksteel board, and the board kept across an edit to a
server-side message string — the report says what was clicked.
"""
from __future__ import annotations

import pickle
import shutil
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.equipment import attach_equipment
from engine.models import CardDefinition, Permanent
from tests.helpers import _mk_creature_card, run_app_js
from web.app import app, store
from web.events import _session_revisions
from web.runtime import session_lock
from web.state_view import build_state

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "integration"))
import board_pickle  # noqa: E402

client = TestClient(app)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


# ---------------------------------------------------------------------------
# The board a reload keeps
# ---------------------------------------------------------------------------


def _payloads(session) -> list:
    out = []
    for seat in [None, *range(len(session.game.players))]:
        state = build_state(session, viewer_seat=seat)
        state.pop("revision", None)
        out.append(state)
    return out


def test_a_played_session_reads_back_to_the_same_payload_for_every_seat():
    sid = client.post("/api/sessions", json={
        "mode": "ai_vs_ai", "use_custom_seed": True, "custom_seed": 4024,
    }).json()["session_id"]
    for _ in range(4):
        client.post(f"/api/sessions/{sid}/run-ai?steps=1")
    session = store.get(sid)
    assert session.game.turn >= 3 and session.game.log
    restored = board_pickle.loads(board_pickle.dumps(session))
    assert restored is not session and restored.game is not session.game
    assert _payloads(restored) == _payloads(session)


def _scry_then_draw():
    """``tests/rules/test_resumption.py``'s Opt shape: "Scry 2. Draw a card."
    cast by an interactive seat stops at the scry with the draw owed — the
    rest of the loop a closure on ``game.resume_stack``."""
    card = CardDefinition(
        name="Probe", mana_cost="{U}", cmc=1.0, type_line="Instant",
        oracle_text="Scry 2. Draw a card.", colors=("U",), color_identity=("U",),
        keywords=(), produced_mana=(), raw={"name": "Probe", "type_line": "Instant"},
    )
    caster = PlayerState(
        name="P0", hand=[card],
        library=[_mk_creature_card(name, 1, 1) for name in ("A", "B", "C", "D")],
    )
    game = Game(players=[caster, PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.cast_from_hand(0, card.name, target_player_index=1)
    assert game.pending_choices_of("scry", 0) and game.resume_stack
    return game


def test_plain_pickle_refuses_a_suspended_resolution():
    """Why the board needs its own pickler: the rest of a suspended loop is a
    lambda, and plain pickle names functions by where they are defined."""
    with pytest.raises((pickle.PicklingError, AttributeError, TypeError)):
        pickle.dumps(_scry_then_draw(), protocol=pickle.HIGHEST_PROTOCOL)


def test_a_suspended_resolution_survives_and_finishes_when_answered():
    restored = board_pickle.loads(board_pickle.dumps(_scry_then_draw()))
    caster = restored.players[0]
    assert caster.hand == [] and restored.pending_choices_of("scry", 0)
    # Bottom A, keep B on top: the draw the restored loop still owes must see B.
    assert restored.confirm_scry(0, card_order=[1, 0], bottom_count=1) is True
    assert [c.name for c in caster.hand] == ["B"]
    assert [c.name for c in caster.library] == ["C", "D", "A"]
    assert any(c.name == "Probe" for c in caster.graveyard), "and the resolution finished"
    assert restored.resume_stack == [] and not restored.effect_suspended


def test_an_identity_sentinel_reads_back_as_itself():
    from engine import entry_awaiting, resumption

    held = [resumption._THEN, entry_awaiting.ENTRY_SUSPENDED, resumption._THEN]
    back = board_pickle.loads(board_pickle.dumps(held))
    assert back[0] is resumption._THEN and back[2] is resumption._THEN
    assert back[1] is entry_awaiting.ENTRY_SUSPENDED


def test_a_closure_shared_by_two_functions_keeps_one_cell():
    def counter():
        count = 0

        def bump():
            nonlocal count
            count += 1
            return count

        def read():
            return count

        return bump, read

    bump, read = board_pickle.loads(board_pickle.dumps(counter()))
    bump()
    bump()
    assert read() == 2


@dataclass
class _Grown:
    kept: int = 1
    added: list = field(default_factory=lambda: ["fresh"])


def test_a_dataclass_field_the_new_code_added_is_filled_from_its_default():
    old = _Grown()
    del old.__dict__["added"]  # pickled before the field existed
    holder = {"deep": [types.SimpleNamespace(inner=old)]}
    assert board_pickle.fill_new_fields(holder) == 1
    assert old.added == ["fresh"] and old.kept == 1


def test_save_and_restore_carry_every_session_and_its_revision(tmp_path):
    sid = client.post("/api/sessions", json={
        "mode": "ai_vs_ai", "use_custom_seed": True, "custom_seed": 4025,
    }).json()["session_id"]
    client.post(f"/api/sessions/{sid}/run-ai?steps=1")
    board = tmp_path / "board.pickle"
    saved, message = board_pickle.save_board(store, session_lock, _session_revisions, board)
    try:
        assert saved, message
    finally:
        # A save keeps every session's lock (its process exits holding them).
        for each in list(store._sessions):
            session_lock(each).release()
    fresh = types.SimpleNamespace(_sessions={})
    revisions = {}
    message = board_pickle.restore_board(fresh, revisions, board)
    assert "not restored" not in message, message
    assert list(fresh._sessions) == list(store._sessions)
    assert revisions[sid] == _session_revisions[sid] + 1
    assert _payloads(fresh._sessions[sid]) == _payloads(store.get(sid))


# ---------------------------------------------------------------------------
# A card's place on the page
# ---------------------------------------------------------------------------


def _darksteel_board(set_pool):
    """Leonin Shikari carrying Skullclamp and Vulshok Morningstar, Viridian
    Zealot beside it and three Plains (a pile) for seat 0; Grimclaw Bats for
    seat 1 — the state seat 0's client is sent."""
    dst = set_pool("DST")
    lea = set_pool("LEA")
    sid = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "use_custom_seed": True, "custom_seed": 4026,
    }).json()["session_id"]
    game = store.get(sid).game
    for player in game.players:
        player.battlefield = []

    def put(seat, card):
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        return permanent

    shikari = put(0, dst["Leonin Shikari"])
    clamp = put(0, dst["Skullclamp"])
    star = put(0, dst["Vulshok Morningstar"])
    put(0, dst["Viridian Zealot"])
    for _ in range(3):
        put(0, lea["Plains"])
    put(1, dst["Grimclaw Bats"])
    assert attach_equipment(game, clamp, shikari) and attach_equipment(game, star, shikari)
    game._sync_control()
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    ids = {
        "shikari": shikari.permanent_id, "clamp": clamp.permanent_id,
        "star": star.permanent_id,
    }
    return state, ids


#: A page for the canvas file to run on in node: a 1400x700 stage at the
#: page's top-left, nothing over it unless INPUT.cover names a page x past
#: which a DOM panel takes the click (the prompt dock at narrow widths).
_PAGE = r'''
const STAGE = { left: 0, top: 0, width: 1400, height: 700 };
const noop = () => {};
const ctx2d = new Proxy({}, { get: () => noop });
const canvasEl = {
  getContext: () => ctx2d, style: {}, width: 0, height: 0,
  classList: { add: noop, remove: noop }, addEventListener: noop, removeEventListener: noop,
  parentElement: { style: {}, getBoundingClientRect: () => STAGE },
};
const panel = { id: "promptDock" };
globalThis.window = { devicePixelRatio: 1, matchMedia: () => ({ matches: false }), addEventListener: noop, removeEventListener: noop };
globalThis.document = {
  documentElement: {},
  elementFromPoint: (x, y) => (INPUT.cover != null && x >= INPUT.cover ? panel : canvasEl),
};
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "" });
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = noop;
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
const BattlefieldCanvas = eval(src + "\n;BattlefieldCanvas");
'''

#: Lay the state out, read the positions, and press every reported point
#: through the real mouse-down handler.
_PRESS_EVERY_POINT = r'''
const bc = new BattlefieldCanvas(canvasEl, {});
bc.updateState(INPUT.state, 0);
for (let i = 0; i < 400; i++) bc._tick();
const positions = bc.debugPositions();
const pressed = {};
for (const p of positions.permanents) {
  if (!p.click) continue;
  bc.pressState = null;
  bc._handleMouseDown({ button: 0, clientX: p.click.x, clientY: p.click.y, preventDefault: noop });
  const item = bc.cardItems.find((it) => it.key === bc.pressState?.key);
  pressed[p.id] = item ? item.pid : null;
}
bc.pressState = null;
return { positions, pressed };
'''


def _press_every_point(state, cover=None):
    return run_app_js(
        [], _PRESS_EVERY_POINT, {"state": state, "cover": cover},
        prelude=_PAGE, scripts=("battlefield-canvas.js",),
    )


@needs_node
def test_every_reported_click_point_presses_its_own_permanent(set_pool):
    state, ids = _darksteel_board(set_pool)
    out = _press_every_point(state)
    positions, pressed = out["positions"], out["pressed"]
    assert positions["settled"] is True and positions["mana_fan_open"] is False
    on_board = [p["id"] for player in state["players"] for p in player["battlefield"]]
    by_id = {p["id"]: p for p in positions["permanents"]}
    assert sorted(by_id) == sorted(on_board)
    for pid, landed in pressed.items():
        assert landed == int(pid), f"the point reported for {by_id[int(pid)]['name']} pressed {landed}"
    # Every creature and both Equipment can be clicked.
    for key in ("shikari", "clamp", "star"):
        assert by_id[ids[key]]["click"] is not None, key


@needs_node
def test_an_attached_equipment_is_clicked_on_its_visible_strip(set_pool):
    state, ids = _darksteel_board(set_pool)
    by_id = {p["id"]: p for p in _press_every_point(state)["positions"]["permanents"]}
    host, clamp, star = by_id[ids["shikari"]], by_id[ids["clamp"]], by_id[ids["star"]]
    for equipment in (clamp, star):
        assert equipment["attached_to_id"] == ids["shikari"]
        assert equipment["group"]["kind"] == "aura" and equipment["group"]["position"] > 0
        # Tucked behind the creature it fans up from: only a strip shows, and
        # the point is on it — above the creature's own top edge.
        assert 0 < equipment["share"] < host["share"]
        assert equipment["click"]["y"] < host["rect"]["y"]
    assert host["group"] == {"kind": "aura", "position": 0, "size": 3}
    assert host["share"] == 1.0


@needs_node
def test_a_point_a_dom_panel_covers_is_never_reported(set_pool):
    state, ids = _darksteel_board(set_pool)
    uncovered = {p["id"]: p for p in _press_every_point(state)["positions"]["permanents"]}
    host = uncovered[ids["shikari"]]
    # A panel over the right half of the creature: the point moves left of it.
    cover = host["rect"]["x"] + host["rect"]["w"] // 2
    out = _press_every_point(state, cover=cover)
    covered = {p["id"]: p for p in out["positions"]["permanents"]}
    assert covered[ids["shikari"]]["click"]["x"] < cover
    assert covered[ids["shikari"]]["share"] < host["share"]
    for pid, landed in out["pressed"].items():
        assert landed == int(pid)
    # Anything wholly under the panel has no point at all.
    for entry in covered.values():
        if entry["rect"]["x"] >= cover:
            assert entry["click"] is None, entry["name"]
