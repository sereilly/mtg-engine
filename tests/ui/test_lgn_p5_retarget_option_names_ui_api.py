"""Willbender's "choose the new target" names each option so it can be told apart.

Found in Legions' post-promotion pass, in the browser: a face-down Willbender
turned face up over a Shock aimed at the opponent's face-down creature, and the
"Choose a new target" panel offered **two buttons both reading "Face-down
creature"** — the player's own face-down Dermoplasm and face-down Willbender.
The person answering could not tell which was which (nor, at a table where both
sides played a Goblin Grappler, whose Grappler was whose). The trigger-target
dialog already names a face-down tile by the card its controller is sent
(``candidatePermanentName``, CR 708.5) and says whose it is; the retarget
prompt's options carried only a name, so the client had nothing to name it by.

The options now carry a permanent's ``id`` and its controller's ``seat`` (both
public), and the button reads as a tile does: "Face-down creature (Dermoplasm) —
yours" to the controller, "Face-down creature — Host's" to anyone else. Driven
here from the payload the server sends, through the client's own renderer, to
the body it sends back, which the server takes. The same path was clicked in a
browser (``scratch/lgn/p5``).
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.face_down import FACE_DOWN_NAME, face_down_card
from engine.models import Permanent
from tests.helpers import run_app_js
from web.app import app, store

client = TestClient(app)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _hvh(seed: int = 5114):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": seed,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.interactive_seats = {0, 1}
    game.enforce_mana_costs = False
    for player in game.players:
        player.battlefield.clear()
        player.hand.clear()
        player.graveyard.clear()
    game.stack.clear()
    game.pending_choices.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, session, game


def _put(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return permanent


def _state(sid: str, seat: int) -> dict:
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def _post(sid: str, body: dict):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _willbender_over_a_shock(set_pool):
    """Seat 0 Shocks seat 1's face-down Chromeshell Crab, turns its face-down
    Willbender face up, aims the trigger at the Shock, and both seats pass: the
    retarget prompt is open for seat 0, with two of its own face-down creatures
    and a Goblin Grappler on each side among the options."""
    sid, _session, game = _hvh()
    lgn = set_pool("LGN")
    shock = next(card for card in load_catalog() if card.name == "Shock")
    willbender = _put(game, 0, face_down_card(lgn["Willbender"]))
    dermoplasm = _put(game, 0, face_down_card(lgn["Dermoplasm"]))
    weaver = _put(game, 0, face_down_card(lgn["Weaver of Lies"]))
    my_grappler = _put(game, 0, lgn["Goblin Grappler"])
    crab = _put(game, 1, face_down_card(lgn["Chromeshell Crab"]))
    their_grappler = _put(game, 1, lgn["Goblin Grappler"])
    game.players[0].hand.append(shock)

    cast = _post(sid, {
        "seat": 0, "action": "cast", "card_name": "Shock", "target_seat": 1,
        "target_permanent_id": crab.permanent_id,
    })
    assert cast.status_code == 200, cast.text
    assert [item.card.name for item in game.stack] == ["Shock"]
    # Morph {1}{U}: a special action is paid even with costs relaxed.
    game.players[0].mana_pool["U"] += 2
    turned = _post(sid, {
        "seat": 0, "action": "special_action",
        "permanent_id": willbender.permanent_id, "special_action_kind": "turn_face_up",
    })
    assert turned.status_code == 200, turned.text
    (candidate,) = _state(sid, 0)["trigger_target"]["candidates"]
    assert candidate["name"] == "Host's Shock"
    aimed = _post(sid, {
        "seat": 0, "action": "trigger_target_confirm",
        "target_stack_index": candidate["stack_index"],
    })
    assert aimed.status_code == 200, aimed.text
    for passer in (0, 1, 0, 1):
        if game.pending_choice_of("retarget_choice", 0) is not None:
            break
        _post(sid, {"seat": passer, "action": "pass_priority"})
    assert game.pending_choice_of("retarget_choice", 0) is not None
    return sid, game, {
        "dermoplasm": dermoplasm, "weaver": weaver, "my_grappler": my_grappler,
        "crab": crab, "their_grappler": their_grappler,
    }


def test_a_permanent_option_carries_its_id_and_its_controller(set_pool):
    sid, game, board = _willbender_over_a_shock(set_pool)

    options = _state(sid, 0)["retarget_choice"]["options"]
    by_id = {option.get("id"): option for option in options if option["kind"] == "permanent"}

    # The Shock's own target is not offered (CR 115.7a: another legal target).
    assert board["crab"].permanent_id not in by_id
    for key, seat in (("dermoplasm", 0), ("weaver", 0), ("my_grappler", 0), ("their_grappler", 1)):
        option = by_id[board[key].permanent_id]
        assert option["seat"] == seat, option
    # A face-down option is still named only as the blank (CR 708.2): the card it
    # hides is not on the option, for any viewer.
    face_down = [by_id[board[k].permanent_id] for k in ("dermoplasm", "weaver")]
    assert [option["name"] for option in face_down] == [FACE_DOWN_NAME, FACE_DOWN_NAME]
    assert all(set(option) == {"index", "name", "kind", "id", "seat"} for option in face_down)
    # Players and the like keep the three fields they always had.
    assert all(
        set(option) == {"index", "name", "kind"}
        for option in options if option["kind"] != "permanent"
    )


_PRELUDE = r"""
var seat = INPUT.seat;
let currentState = INPUT.state;
const SENT = [];
function makeEl(id) {
  return {
    id, textContent: "", disabled: false, _html: "",
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    querySelectorAll() { return []; },
  };
}
const ELS = {};
function q(id) { if (!ELS[id]) ELS[id] = makeEl(id); return ELS[id]; }
function escapeHtml(s) { return String(s); }
async function sendAction(body) { SENT.push(body); }
"""

_BODY = r"""
applyRetargetChoicePrompt(INPUT.info);
const html = q("promptSteps").innerHTML;
return [...html.matchAll(/data-choice-value="([^"]*)">([^<]*)<\/button>/g)]
  .map((m) => [Number(m[1]), m[2]]);
"""

_FUNCTIONS = [
    "applyChoiceButtonPrompt", "applyRetargetChoicePrompt", "retargetOptionLabel",
    "retargetOptionLabels", "candidatePermanentName", "candidateOwnerLabel",
]


@needs_node
def test_each_button_says_which_permanent_it_is_and_whose_and_the_answer_is_taken(set_pool):
    sid, game, board = _willbender_over_a_shock(set_pool)
    state = _state(sid, 0)
    info = state["retarget_choice"]

    buttons = run_app_js(_FUNCTIONS, _BODY, {"info": info, "state": state, "seat": 0}, prelude=_PRELUDE)
    labels = [label for _, label in buttons]

    assert f"{FACE_DOWN_NAME} (Dermoplasm) — yours" in labels
    assert f"{FACE_DOWN_NAME} (Weaver of Lies) — yours" in labels
    assert "Goblin Grappler — yours" in labels
    assert "Goblin Grappler — Joiner's" in labels
    assert "Joiner (player)" in labels
    assert len(set(labels)) == len(labels), labels

    # The answer the button sends is the position the server offered, and the
    # server takes it: the Shock now aims at the other side's Grappler.
    index = next(value for value, label in buttons if label == "Goblin Grappler — Joiner's")
    answered = _post(sid, {"seat": 0, "action": "retarget_choice_confirm", "target_index": index})
    assert answered.status_code == 200, answered.text
    assert game.pending_choice_of("retarget_choice", 0) is None
    shock = next(item for item in game.stack if item.card.name == "Shock")
    assert shock.target_permanent_id == [board["their_grappler"].permanent_id]


@needs_node
def test_another_viewer_is_not_told_what_a_face_down_option_is(set_pool):
    """The same options drawn for the other seat: its own payload carries no
    ``hidden_card`` for seat 0's face-down creatures, so each is the blank's
    name and whose it is — nothing of the card under it."""
    sid, _game, _board = _willbender_over_a_shock(set_pool)
    info = _state(sid, 0)["retarget_choice"]
    theirs = _state(sid, 1)

    buttons = run_app_js(_FUNCTIONS, _BODY, {"info": info, "state": theirs, "seat": 1}, prelude=_PRELUDE)
    labels = [label for _, label in buttons]

    # Told apart by where each sits (kg3 `client`: two same-named options
    # read the same), and by nothing of the card under it.
    assert [label for label in labels if label.startswith(f"{FACE_DOWN_NAME} — Host's")] == [
        f"{FACE_DOWN_NAME} — Host's (1st from the left)",
        f"{FACE_DOWN_NAME} — Host's (2nd from the left)",
    ], labels
    assert not any("Dermoplasm" in label or "Weaver" in label for label in labels), labels
