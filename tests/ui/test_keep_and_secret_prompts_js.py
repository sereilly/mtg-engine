"""The two client prompts W2G1 touched, run for real in bare ``node``.

``web/static/app.js`` is one DOM-bound script, so — the arrangement
``test_ability_cost_js_parity.py`` set up — the functions under test are lifted
out by name and evaluated against a few lines of stand-in DOM. What is checked
is what a player can *do*, which no reading of the source can say:

* **the keep modal** (Cataclysm, Global Ruin, Planar Overlay). One permanent
  may be chosen for several printed slots, so the answer is a range, and the
  confirm button has to open on one Tropical Island for Forest *and* Island
  while staying shut on a Forest alone. The payload fed in is the server's own
  — rendered by ``web/prompts.py`` from a real game — so the two halves are
  tested against each other and not against a hand-written copy.
* **the secret number** (Goblin Game). One button per number the server
  offered, and a click sends that number on the action the engine answers to.

Skipped when node is not on PATH; the engine's half is pinned regardless
(``tests/regressions/test_one_permanent_chosen_for_several_slots.py``,
``tests/ui/test_secret_number_ui_api.py``).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from web.prompts import PromptContext, render_prompts

REPO = Path(__file__).resolve().parents[2]
APP_JS = REPO / "web" / "static" / "app.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the JS half cannot run",
)

# A stand-in DOM with exactly what the two functions touch: elements by id
# with a class list, text, a disabled flag and one listener per event; and
# `querySelectorAll`, which rebuilds its tiles from the HTML the function just
# wrote — keyed on the attribute the function reads back off each tile.
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
const job = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const sent = [];
function makeElement(id) {
  const classes = new Set();
  const node = {
    id, dataset: {}, textContent: "", innerHTML: "", disabled: false,
    listeners: {},
    classList: {
      add: (c) => classes.add(c), remove: (c) => classes.delete(c),
      toggle: (c) => (classes.has(c) ? classes.delete(c) : classes.add(c)),
      contains: (c) => classes.has(c),
    },
    addEventListener(type, fn) { node.listeners[type] = fn; },
    querySelectorAll() {
      const tiles = [];
      const re = /data-(id|secret-number)="([^"]*)"/g;
      let found;
      while ((found = re.exec(node.innerHTML)) !== null) {
        const tile = makeElement(id + ":" + found[2]);
        const key = found[1] === "id" ? "id" : "secretNumber";
        tile.dataset[key] = found[2];
        tiles.push(tile);
      }
      node.tiles = tiles;
      return tiles;
    },
  };
  return node;
}
const elements = {};
const byId = (id) => (elements[id] = elements[id] || makeElement(id));
const document = { getElementById: byId };
const q = byId;
const escapeHtml = (text) => String(text);
const sendAction = async (body) => { sent.push(body); };
let seat = 0;
let currentState = null;
eval(
  "let keepPermanentsSelected = new Set();\n"
  + grab("renderKeepPermanentsModal") + "\n" + grab("applySecretNumberPrompt")
  + ";globalThis.T={renderKeepPermanentsModal,applySecretNumberPrompt}"
);
(async () => {
  const out = {};
  if (job.keep) {
    T.renderKeepPermanentsModal(job.keep);
    const tiles = byId("keepPermanentsList").tiles;
    const button = byId("keepPermanentsConfirmBtn");
    out.subtitle = byId("keepPermanentsSubtitle").textContent;
    out.labels = byId("keepPermanentsList").innerHTML;
    out.steps = [{ clicked: null, disabled: button.disabled }];
    for (const id of job.clicks) {
      const tile = tiles.find((t) => t.dataset.id === String(id));
      tile.listeners.click();
      out.steps.push({ clicked: id, disabled: button.disabled });
    }
    if (!button.disabled) await button.listeners.click();
  }
  if (job.secret) {
    T.applySecretNumberPrompt(job.secret);
    const tiles = byId("promptSteps").tiles;
    out.title = byId("promptTitle").textContent;
    out.body = byId("promptBody").textContent;
    out.buttons = tiles.map((t) => t.dataset.secretNumber);
    await tiles.find((t) => t.dataset.secretNumber === String(job.pick)).listeners.click();
  }
  out.sent = sent;
  process.stdout.write(JSON.stringify(out));
})();
'''


def _run(job: dict, tmp_path) -> dict:
    driver = tmp_path / "driver.js"
    driver.write_text(_DRIVER, encoding="utf-8")
    job_file = tmp_path / "job.json"
    job_file.write_text(json.dumps(job), encoding="utf-8")
    done = subprocess.run(
        ["node", str(driver), str(APP_JS), str(job_file)],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _table(set_pool, code, spell, mine):
    game = Game(players=[
        PlayerState(name="W2G1-A", hand=[set_pool(code)[spell]]),
        PlayerState(name="W2G1-B"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = {0, 1}
    for player in game.players:
        player.library = [set_pool("LEA")["Grizzly Bears"]] * 20
    board = []
    for name in mine:
        perm = Permanent(card=set_pool("LEA")[name])
        game._put_permanent_onto_battlefield(0, perm, None)
        board.append(perm)
    assert game.cast_from_hand(0, spell).supported
    return game, board


def _prompt(game, key):
    return render_prompts(PromptContext(
        game=game, viewer_seat=0,
        serialize_card=lambda card: {"name": card.name},
        seat_type=lambda seat: "human",
    ))[key]


@pytest.mark.parametrize("code, spell", [("INV", "Global Ruin"), ("PLS", "Planar Overlay")])
def test_w2g1_the_keep_modal_confirms_one_dual_land_for_both_types(
    set_pool, tmp_path, code, spell,
):
    """A Tropical Island, a Forest and an Island. The button is shut with
    nothing chosen, **open** on the Tropical Island alone (it answers Island
    and Forest), still open with the Forest beside it, and what is sent is what
    was clicked. The tile says what the land may stand for."""
    game, (tropical, forest, _island) = _table(
        set_pool, code, spell, ["Tropical Island", "Forest", "Island"],
    )
    payload = _prompt(game, "keep_permanents")
    out = _run(
        {"keep": payload, "clicks": [tropical.permanent_id, forest.permanent_id]},
        tmp_path,
    )
    assert [step["disabled"] for step in out["steps"]] == [True, False, False]
    assert out["sent"] == [{
        "seat": 0, "action": "keep_permanents_confirm",
        "target_permanent_ids": [tropical.permanent_id, forest.permanent_id],
    }]
    assert "choose 1 to 2" in out["subtitle"]
    assert "One permanent may be chosen for more than one of these" in out["subtitle"]
    assert " as Island / Forest" in out["labels"]
    # And the engine takes that answer.
    assert game.confirm_keep_permanents(0, out["sent"][0]["target_permanent_ids"])


def test_w2g1_the_keep_modal_stays_shut_on_an_answer_that_skips_a_type(
    set_pool, tmp_path,
):
    """The Forest alone leaves the Island unanswered, so the button stays
    shut and nothing is sent; adding the Island opens it."""
    game, (_tropical, forest, island) = _table(
        set_pool, "INV", "Global Ruin", ["Tropical Island", "Forest", "Island"],
    )
    payload = _prompt(game, "keep_permanents")
    shut = _run({"keep": payload, "clicks": [forest.permanent_id]}, tmp_path)
    assert [step["disabled"] for step in shut["steps"]] == [True, True]
    assert shut["sent"] == []

    both = _run(
        {"keep": payload, "clicks": [forest.permanent_id, island.permanent_id]},
        tmp_path,
    )
    assert [step["disabled"] for step in both["steps"]] == [True, True, False]


def test_w2g1_the_keep_modal_is_unchanged_for_one_counted_slot(set_pool, tmp_path):
    """"Five lands" is one slot: the range is a single number, the subtitle
    says so with no mention of sharing, the tiles carry no "as …", and the
    button opens at exactly five."""
    game = Game(players=[PlayerState(name="W2G1-A"), PlayerState(name="W2G1-B")])
    game.interactive_seats = {0}
    board = []
    for _ in range(7):
        perm = Permanent(card=set_pool("LEA")["Forest"])
        game._put_permanent_onto_battlefield(0, perm, None)
        board.append(perm)
    game.arm_keep_permanents(
        0, pool={"type_filter": "land"},
        slots=[{"count": 5, "filter": {"type_filter": "land"}}],
        reason="Limited Resources",
    )
    payload = _prompt(game, "keep_permanents")
    assert (payload["keep_fewest"], payload["keep_count"]) == (5, 5)
    out = _run(
        {"keep": payload, "clicks": [perm.permanent_id for perm in board[:5]]},
        tmp_path,
    )
    assert [step["disabled"] for step in out["steps"]] == [True] * 5 + [False]
    assert "choose 5." in out["subtitle"]
    assert "more than one of these" not in out["subtitle"]
    assert " as " not in out["labels"]


def test_w2g1_the_secret_number_prompt_offers_the_servers_numbers_and_sends_one(
    set_pool, tmp_path,
):
    """Goblin Game at 6 life: six buttons, 1 to 6, the body says nobody sees
    the number until every player has chosen, and clicking 4 sends 4 on the
    action that answers the prompt."""
    game = Game(players=[
        PlayerState(name="W2G1-A", hand=[set_pool("PLS")["Goblin Game"]]),
        PlayerState(name="W2G1-B"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = {0, 1}
    game.players[0].life = 6
    assert game.cast_from_hand(0, "Goblin Game").supported
    payload = _prompt(game, "secret_number")
    out = _run({"secret": payload, "pick": 4}, tmp_path)
    assert out["buttons"] == ["1", "2", "3", "4", "5", "6"]
    assert out["title"] == "Choose a number in secret"
    assert "at least 1" in out["body"] and "until every player has chosen" in out["body"]
    assert out["sent"] == [
        {"seat": 0, "action": "secret_number_confirm", "number": 4}
    ]
    assert game.confirm_secret_number(0, out["sent"][0]["number"])
