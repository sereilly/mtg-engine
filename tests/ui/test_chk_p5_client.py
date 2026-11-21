"""Champions of Kamigawa's Phase 5: two client wordings a person met in the
browser, each clicked before and after the fix.

* **Splice onto an X host.** Swallowing Plague ({X}{B}{B}, Arcane) with
  Psychic Puppetry and Blessed Breath spliced asked "Choose X" three times: once
  in each spliced text's target step (worded "X is part of this spell's
  additional cost", since the spliced card's displayed cost is its splice
  cost) and once in the host's own step. The server judges each splice offer's
  ``target_spec`` as the host's (``offers.splice_offers``), so an X host hands
  every offer ``announces_x``; the answers given in the spliced steps were
  discarded. ``spliceTargetCard`` now announces no X: it is asked once, in the
  host's step.
* **Shell of the Last Kappa casts the exiled card itself.** Its offer sends
  ``copy: false`` (``web/prompt_board.py``), and the panel still read "Cast a
  copy — Lava Spike" with a "Cast a copy of Lava Spike" button. It now says
  "Cast Lava Spike"; Reversal of Fortune's real copy beside it still says copy.

Each payload is the server's own, read from a web session's state after the
engine armed it; each client function is the real source, lifted out of
``app.js`` by ``run_app_js``.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app

from tests.helpers import run_app_js, seat_plays_first, settle

client = TestClient(app)


def _p5_card(set_pool, name: str):
    for code in ("CHK", "5DN", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _p5_session(seed: int = 7):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
        "guest_colors": 2, "seed": seed,
    })
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    game = seat_plays_first(sid).game
    for player in game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.exile = []
    game._sync_control()
    return sid, game


def _p5_place(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _p5_state(sid: str) -> dict:
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": 0})
    assert response.status_code == 200, response.text
    return response.json()


def test_p5_a_text_spliced_onto_an_x_host_announces_no_x(set_pool):
    """The splice target step asks no X; the host's own step still does."""
    sid, game = _p5_session()
    for name in ("Swamp", "Swamp", "Swamp", "Island", "Grizzly Bears"):
        _p5_place(game, 0, _p5_card(set_pool, name))
    _p5_place(game, 1, _p5_card(set_pool, "Hill Giant"))
    game.players[0].hand = [
        _p5_card(set_pool, "Swallowing Plague"), _p5_card(set_pool, "Psychic Puppetry"),
    ]
    state = _p5_state(sid)
    host = state["players"][0]["hand"][0]
    assert host["name"] == "Swallowing Plague"
    (offer,) = host["splice_offers"]
    assert offer["name"] == "Psychic Puppetry"
    # Why the client has to say it: the offer's spec is judged as the host's.
    assert offer["target_spec"].get("announces_x") is True
    asked = run_app_js(
        ["spliceTargetCard", "spliceOfferCard", "hasXCost", "targetSpecOf", "xLivesInManaCost"],
        """
        currentState = INPUT.state;
        const host = INPUT.state.players[0].hand[0];
        const spliced = spliceTargetCard(host, host.splice_offers[0]);
        return {
          spliced: hasXCost(spliced), host: hasXCost(host),
          targets: (spliced.target_spec.valid_targets || []).length,
          from: spliced.spliced_from,
        };
        """,
        {"state": state},
        prelude=(
            "var seat = 0; var currentState = null; const EMPTY_TARGET_SPEC = {};\n"
            "function normalizeCardName(card) { return (card && card.name) || ''; }\n"
            "function getCurrentPlayerState(state) { return state.players[seat]; }\n"
        ),
    )
    assert asked == {
        "spliced": False, "host": True,
        "targets": len(offer["target_spec"]["valid_targets"]), "from": "Psychic Puppetry",
    }


_P5_PANEL_PRELUDE = r"""
var seat = 0;
var SENT = [];
var currentState = {players: [{name: "Host"}, {name: "AI"}]};
function makeEl(id) {
  return {
    id, textContent: "", disabled: false, _html: "", dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    addEventListener() {}, querySelectorAll() { return []; }, querySelector() { return null; },
    appendChild() {},
  };
}
const ELS = {};
function q(id) { if (!ELS[id]) ELS[id] = makeEl(id); return ELS[id]; }
const document = { getElementById: (id) => q(id), createElement: (tag) => makeEl(tag) };
function escapeHtml(s) { return String(s); }
function normalizeCardName(card) { return card && card.name ? card.name : ""; }
function copyCastExiledCard() { return null; }
function normalizeImageUri() { return null; }
function updateActionHint() {}
async function sendAction(body) { SENT.push(body); }
"""

_P5_PANEL = """
applyCopyCastPrompt(INPUT.info);
return {title: q("promptTitle").textContent, steps: q("promptSteps").innerHTML};
"""


def test_p5_shell_of_the_last_kappa_casts_the_card_and_the_panel_says_no_copy(set_pool):
    """Shell's offer (``copy: false``) reads "Cast Lava Spike"; Reversal of
    Fortune's offer (a real copy) still reads "Cast a copy"."""
    sid, game = _p5_session()
    game.enforce_mana_costs = False
    shell = _p5_place(game, 0, _p5_card(set_pool, "Shell of the Last Kappa"))
    game.players[1].hand = [_p5_card(set_pool, "Lava Spike")]
    assert game.queue_from_hand(1, "Lava Spike", target_player_index=0).supported
    assert game.queue_permanent_ability(
        0, shell.card.name, permanent_index=game.players[0].battlefield.index(shell),
        ability_index=0, target_stack_index=len(game.stack) - 1,
    ).supported
    settle(game)
    assert [c.name for c in game.players[1].exile] == ["Lava Spike"]
    shell.tapped = False
    assert game.activate_permanent_ability(
        0, shell.card.name, permanent_index=game.players[0].battlefield.index(shell),
        ability_index=1,
    ).supported
    shell_info = _p5_state(sid)["copy_cast"]
    assert shell_info["copy"] is False and shell_info["card_name"] == "Lava Spike"
    shown = run_app_js(["applyCopyCastPrompt", "copyCastFromHand"], _P5_PANEL,
                       {"info": shell_info}, prelude=_P5_PANEL_PRELUDE)
    assert shown["title"] == "Cast Lava Spike"
    assert ">Cast Lava Spike</button>" in shown["steps"]
    # What a person reads: the markup's ids (``copyCastBtn``) are not words.
    words = re.sub(r"<[^>]*>", " ", shown["steps"])
    assert "copy" not in (shown["title"] + words).lower()
    assert game.confirm_copy_cast(0, True, card_name="Lava Spike", target_player_index=1)
    settle(game)
    assert game.players[1].life == 17

    # The neighbour: Reversal of Fortune's offer is a copy, and says so.
    game.players[0].hand = [_p5_card(set_pool, "Reversal of Fortune")]
    game.players[1].hand = [_p5_card(set_pool, "Lightning Bolt")]
    assert game.cast_from_hand(0, "Reversal of Fortune", target_player_index=1).supported
    owed = settle(game, defaults=False)
    assert owed is not None and owed.kind == "copy_cast", owed
    reversal_info = _p5_state(sid)["copy_cast"]
    assert "copy" not in reversal_info
    shown = run_app_js(["applyCopyCastPrompt", "copyCastFromHand"], _P5_PANEL,
                       {"info": reversal_info}, prelude=_P5_PANEL_PRELUDE)
    assert shown["title"] == "Cast a copy — Lightning Bolt"
    assert ">Cast a copy of Lightning Bolt</button>" in shown["steps"]
    assert "The copy is made in exile" in shown["steps"]
