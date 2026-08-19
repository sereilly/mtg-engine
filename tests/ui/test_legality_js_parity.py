"""CR 903.4 is implemented twice — hold the two implementations equal.

``engine.commander.color_identity`` is the authority the server enforces;
``web/static/legality.js``'s ``colorIdentity`` is the browser's preview of the
same rule, hand-mirrored so the deck editor can mark an off-identity card
before a round-trip. A hand mirror drifts silently — a new face shape, mana
symbol or land type lands on one side first — so this test runs **both**
implementations over the identical corpus: ``CATALOG_PAYLOAD``, the exact
dicts the browser holds (``color_identity`` accepts a Mapping for this
reason).

Each card is checked three ways: JS versus Python, and both versus Scryfall's
own ``color_identity`` field riding along in the payload — the same pool-wide
pin ``tests/rules/test_commander.py`` keeps on the Python side alone. The
third leg means a payload gap (say, a ``faces`` field the payload does not
ship) surfaces as a failure against Scryfall the day a pool card needs it,
rather than as agreement between two implementations that are wrong together.

``commanderTypeProblem`` / ``commander_type_problem`` are the same situation —
two hand-mirrored message generators — and share the corpus and the driver.

The JS side runs in bare ``node`` (the file is a DOM-free IIFE onto
``window.Legality``); skipped when node is not on PATH, where the Python-vs-
Scryfall pin in tests/rules keeps the derivation itself covered.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.commander import BRAWL, COMMANDER, color_identity, commander_type_problem
from web.catalog import CATALOG_PAYLOAD

REPO = Path(__file__).resolve().parents[2]
LEGALITY_JS = REPO / "web" / "static" / "legality.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the JS half cannot run "
    "(the Python derivation stays pinned to Scryfall in tests/rules/test_commander.py)",
)

_DRIVER = """\
const fs = require("fs");
globalThis.window = {};
eval(fs.readFileSync(process.argv[2], "utf8"));
const L = globalThis.window.Legality;
const cards = JSON.parse(fs.readFileSync(0, "utf8"));
const out = cards.map((card) => ({
  name: card.name,
  identity: [...L.colorIdentity(card)].sort(),
  commander_problem: L.commanderTypeProblem(card, "commander") || "",
  brawl_problem: L.commanderTypeProblem(card, "brawl") || "",
}));
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js_results(tmp_path_factory):
    driver = tmp_path_factory.mktemp("legality_js") / "driver.js"
    driver.write_text(_DRIVER, encoding="utf-8")
    proc = subprocess.run(
        ["node", str(driver), str(LEGALITY_JS)],
        input=json.dumps(CATALOG_PAYLOAD),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return {row["name"]: row for row in json.loads(proc.stdout)}


def test_the_browser_and_the_engine_derive_the_same_colour_identity(js_results):
    for entry in CATALOG_PAYLOAD:
        js = js_results[entry["name"]]
        derived = sorted(color_identity(entry))
        assert js["identity"] == derived, entry["name"]
        assert set(derived) == set(entry["color_identity"]), (
            f"{entry['name']}: the derivation disagrees with Scryfall"
        )


def test_the_browser_and_the_engine_agree_on_who_may_command(js_results):
    for entry in CATALOG_PAYLOAD:
        js = js_results[entry["name"]]
        assert js["commander_problem"] == (
            commander_type_problem(entry, COMMANDER) or ""
        ), entry["name"]
        assert js["brawl_problem"] == (
            commander_type_problem(entry, BRAWL) or ""
        ), entry["name"]
