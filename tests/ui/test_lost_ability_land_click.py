"""A land that lost its printed abilities can still be **clicked for mana**.

CR 305.7: a land whose subtype an effect set to a basic land type "loses all
abilities generated from its rules text … and it gains the appropriate mana
ability for each new basic land type." A Maze of Ith or a Mishra's Factory
under Blood Moon is a Mountain: nothing to activate, and it taps for {R}.

The round that taught the client the first half (``abilities_lost`` on the
payload, read by ``activatedAbilityText``) broke the second. Both click
handlers in ``app.js`` open with ``if (!hasActivatedAbility(card))``, and a
land only ever passed that gate because its text printed "{T}:" — a basic
Mountain passes on its *reminder* text. With the text read as empty the click
stopped at "… has no activated ability to use." and the land could not be
tapped by a person at all. A Mishra's Factory under Blood Moon, which had
tapped fine the day before, was one of them. The engine, the route and the
payload were all right, so no engine-side or API-side test could see it; it
was found by clicking the land in a browser.

Three things are held here, in the order a click passes through them:

* **the payload** — the three fields the client's question reads
  (``abilities_lost``, ``taps_for_mana``, ``produced_mana``) for a land with no
  printed mana ability and for one with;
* **the client's own decision, run for real in bare node** over that very
  payload: ``landTapsOnlyAsItsNewType`` says yes, ``hasActivatedAbility`` says
  no, and ``tapLandAsItsNewType`` builds a body;
* **the wire** — that body, posted as built, taps the land for the colour the
  server reported.

And one thing that can only be text-level, because the two click handlers are
closures inside DOM-bound functions: each asks the new question *before* its
``hasActivatedAbility`` gate. What a browser showed is in the G1 report.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import app_js_function_body
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}
APP_JS = Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

# The functions under test are lifted out of app.js by name (it is one
# DOM-bound script and cannot be loaded whole); everything they call that
# touches the page is a stub that records what it was handed.
_DRIVER = r'''
const fs = require("fs");
const CR = String.fromCharCode(13);
const src = fs.readFileSync(process.argv[2], "utf8").split(CR).join("");
function grab(name) {
  const i = src.indexOf("function " + name + "(");
  if (i < 0) throw new Error("app.js no longer defines " + name);
  const end = src.indexOf("\n}\n", i);
  return src.slice(i, end + 2);
}
const seat = 0;
const battlefieldCanvas = null;
let pendingManaColor = null;
const MANA_COLOR_OPTIONS = ["W", "U", "B", "R", "G", "C"].map((symbol) => ({ symbol }));
const sent = [];
const hints = [];
function normalizeCardName(card) { return card.name; }
function withPermanentId(body, field, seatIndex, permanentIndex) {
  body[field] = PERMANENT_ID; return body;
}
function sendAction(body) { sent.push(body); return Promise.resolve(); }
function updateActionHint(message) { hints.push(message); }
function renderActivationPrompt() {}
let PERMANENT_ID = null;
eval(["activatedAbilityText", "hasActivatedAbility", "landTapsOnlyAsItsNewType",
  "tapLandAsItsNewType", "noActivatedAbilityHint"].map(grab).join("\n")
  + ";globalThis.T={hasActivatedAbility,landTapsOnlyAsItsNewType,"
  + "tapLandAsItsNewType,noActivatedAbilityHint,"
  + "pending:()=>pendingManaColor}");
const cards = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const out = {};
for (const [label, entry] of Object.entries(cards)) {
  const card = entry.card;
  PERMANENT_ID = card.id;
  sent.length = 0;
  const tapsAsNewType = T.landTapsOnlyAsItsNewType(card);
  if (tapsAsNewType) T.tapLandAsItsNewType(card, entry.index);
  out[label] = {
    tapsAsNewType,
    hasActivatedAbility: T.hasActivatedAbility(card),
    hint: T.noActivatedAbilityHint(card, card.name),
    sent: sent.slice(),
    fan: T.pending() ? T.pending().colorOptions.map((o) => o.symbol) : null,
  };
}
process.stdout.write(JSON.stringify(out));
'''


def _session(*names):
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host",
        "host_colors": 2, "guest_colors": 2, "seed": 4104,
        "host_deck_cards": [{"name": "Forest", "count": 40}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
    })
    assert response.status_code == 200, response.text
    sid = response.json()["session_id"]
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.enforce_mana_costs = False
    permanents = []
    for name in names:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        permanents.append(permanent)
    game._recompute_continuous_effects()
    game.start_priority_window(0)
    return sid, game, permanents


def _payload(sid, permanent) -> tuple[int, dict]:
    """``(slot, payload)`` of *permanent* as seat 0's client is sent it."""
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    for slot, entry in enumerate(state["players"][0]["battlefield"]):
        if entry["id"] == permanent.permanent_id:
            return slot, entry
    raise AssertionError(f"{permanent.card.name} is not on the payload")


#: label -> the board it stands on; the first name is the permanent clicked.
_BOARDS = {
    "maze_under_moon": ("Maze of Ith", "Blood Moon"),
    "factory_under_moon": ("Mishra's Factory", "Blood Moon"),
    "painland_under_moon": ("Karplusan Forest", "Blood Moon"),
    "basic_under_moon": ("Mountain", "Blood Moon"),
    "factory_alone": ("Mishra's Factory",),
    "maze_alone": ("Maze of Ith",),
    "tome_under_song": ("Jayemdae Tome", "Titania's Song"),
}


@pytest.fixture(scope="module")
def boards():
    """Every board, live: ``label -> (sid, game, clicked permanent, slot,
    payload)``."""
    built = {}
    for label, names in _BOARDS.items():
        sid, game, permanents = _session(*names)
        slot, payload = _payload(sid, permanents[0])
        built[label] = (sid, game, permanents[0], slot, payload)
    return built


@pytest.fixture(scope="module")
def clicks(boards, tmp_path_factory):
    """What the client's own functions decide for each board's payload."""
    folder = tmp_path_factory.mktemp("lost-ability-land-click")
    payload = folder / "cards.json"
    payload.write_text(
        json.dumps({
            label: {"card": entry[4], "index": entry[3]}
            for label, entry in boards.items()
        }),
        encoding="utf-8",
    )
    driver = folder / "driver.js"
    driver.write_text(_DRIVER, encoding="utf-8")
    raw = subprocess.run(
        ["node", str(driver), str(APP_JS), str(payload)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    return json.loads(raw)


@pytest.mark.parametrize("label", ["maze_under_moon", "factory_under_moon", "painland_under_moon"])
def test_the_payload_carries_what_the_click_asks(boards, label):
    """The three fields, for a land with no printed mana ability (Maze of Ith)
    and for two with (Mishra's Factory, Karplusan Forest): why its abilities
    are gone, that the tap seam will take it, and what its new type makes —
    one colour, not the three a Karplusan Forest prints."""
    _sid, _game, permanent, _slot, payload = boards[label]

    assert "CR 305.7" in payload["abilities_lost"]
    assert payload["taps_for_mana"] is True
    assert payload["produced_mana"] == ["R"]
    assert "land" in payload["type"].lower()
    # …and the wire's text is empty: a land whose type was set has no ability
    # of its own for any reader (CR 305.7, `Permanent.effective_card`), so an
    # empty text box is what the client is sent - which is why none of those
    # three may be read off it. (When this test was written the wire still
    # printed the lost abilities; the two changes met at the merge, and this
    # line is the one place they disagreed.)
    assert permanent.card.oracle_text, "the printed card does have text"
    assert payload["oracle_text"] == ""


@needs_node
@pytest.mark.parametrize("label", ["maze_under_moon", "factory_under_moon", "painland_under_moon"])
def test_the_client_taps_a_lost_ability_land_and_the_server_agrees(boards, clicks, label):
    """The whole click: the client's question says "tap it", the body it
    builds names no ability and the server's colour, and that body — posted
    exactly as built — taps the land for {R}."""
    sid, game, permanent, slot, _payload_ = boards[label]
    decided = clicks[label]

    assert decided["tapsAsNewType"] is True
    # The gate the click used to die at: there is no ability text left.
    assert decided["hasActivatedAbility"] is False
    assert decided["fan"] is None
    assert decided["sent"] == [{
        "seat": 0, "action": "activate", "permanent_name": permanent.card.name,
        "permanent_index": slot, "mana_color": "R",
        "permanent_id": permanent.permanent_id,
    }]

    response = client.post(f"/api/sessions/{sid}/action", json=decided["sent"][0])

    assert response.status_code == 200, response.text
    assert permanent.tapped and not permanent.is_creature
    assert game.players[0].mana_pool.get("R") == 1
    assert game.players[0].life == 20    # no painland damage: that text is gone
    assert game.log[-1] == f"Host tapped {permanent.card.name} for mana"


@needs_node
@pytest.mark.parametrize("label", ["basic_under_moon", "factory_alone", "maze_alone"])
def test_a_land_that_kept_its_abilities_takes_the_ordinary_path(clicks, label):
    """Nothing else moved: a basic Mountain (Blood Moon names nonbasic lands),
    and a Factory and a Maze with no Blood Moon, are not this path's — they
    pass the old gate and go through the activation prompt as before."""
    decided = clicks[label]

    assert decided["tapsAsNewType"] is False
    assert decided["hasActivatedAbility"] is True
    assert decided["sent"] == []


@needs_node
def test_a_permanent_with_nothing_left_says_why(clicks):
    """"Each noncreature artifact loses all abilities …" (Titania's Song.) Not
    a land and nothing to tap: the click is refused with the server's own
    sentence instead of "has no activated ability to use", which is what the
    text in front of the player contradicts."""
    decided = clicks["tome_under_song"]

    assert decided["tapsAsNewType"] is False
    assert decided["hasActivatedAbility"] is False
    assert decided["hint"] == "Jayemdae Tome has lost all abilities"
    assert clicks["maze_alone"]["hint"] == "Maze of Ith has no activated ability to use."


def test_both_click_handlers_ask_before_the_gate():
    """Text-level, because the two handlers are closures inside DOM-bound
    functions and cannot be run here. Every ``hasActivatedAbility(card)`` gate
    in app.js — there are two, the DOM card's and the canvas's — has the
    lost-ability question asked just ahead of it. A third gate added without
    it fails the count."""
    source = APP_JS.read_text(encoding="utf-8")
    gates = []
    cursor = 0
    while True:
        found = source.find("hasActivatedAbility(card)", cursor)
        if found < 0:
            break
        gates.append(found)
        cursor = found + 1
    # The definition's own signature is `hasActivatedAbility(card) {`.
    gates = [at for at in gates if not source.startswith("function ", at - len("function "))]

    assert len(gates) == 2, f"{len(gates)} click gates in app.js; this test knows two"
    for at in gates:
        ahead = source[max(0, at - 900):at]
        assert "landTapsOnlyAsItsNewType(card)" in ahead, source[at - 200:at + 60]


def test_the_activation_funnel_routes_the_land_before_it_reads_any_text():
    """``startActivationPrompt`` is where every activation starts — both click
    handlers, a permanent dragged onto the board, a prompt resuming — and
    everything in it reads the printed text for what to ask (a painland's
    colour fan, "any color", a timing line). The lost-ability land is sent
    down its own path before the first of those readers."""
    body = app_js_function_body("startActivationPrompt")

    routed = body.index("landTapsOnlyAsItsNewType(card)")
    assert "tapLandAsItsNewType(card, permanentIndex)" in body
    for reader in (
        "getActivatedAbilityOptions(card)", "card?.oracle_text",
        "cardRequiresManaColorChoice(card)", "getDualLandColors(card)",
    ):
        assert routed < body.index(reader), reader


def test_the_question_reads_the_servers_fields_and_not_the_text():
    body = app_js_function_body("landTapsOnlyAsItsNewType")

    for field in ("card.abilities_lost", "card.taps_for_mana", "card.produced_mana"):
        assert field in body
    assert "oracle_text" not in body


def test_the_hover_preview_says_the_abilities_are_gone():
    """The preview prints the oracle text, which still lists the abilities; it
    is shown struck through under the server's sentence."""
    body = app_js_function_body("showCardPreview")

    assert "card.abilities_lost" in body
    assert body.index("abilitiesLost") < body.index("renderOracleTextWithChanges(previewText")
