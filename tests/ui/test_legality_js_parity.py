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

So is the session-id format encoding (``format_from_session_id`` /
``formatFromSessionId``). It has its own driver because its corpus is ids
rather than cards, and it is worth mirroring for the same reason: the browser
reads the format off the id to tell a joining player what they are about to
play, and a decoder that drifted from the minter would state the wrong format
and then filter the deck list by it.

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
from web.deck_legality import FORMATS, format_from_session_id, session_id_prefix

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


# ── The session-id format encoding ──────────────────────────────────────────

_SESSION_DRIVER = """const fs = require("fs");
globalThis.window = {};
eval(fs.readFileSync(process.argv[2], "utf8"));
const L = globalThis.window.Legality;
const input = JSON.parse(fs.readFileSync(0, "utf8"));
L.setFormats(input.formats);
process.stdout.write(JSON.stringify({
  decoded: input.ids.map((id) => L.formatFromSessionId(id)),
  prefixes: input.keys.map((key) => L.sessionIdPrefix(key)),
}));
"""

_TOKEN = "hQ2v1sK9tWA"
# Every format, then the ways an id names none: the uncoded ids this build's
# predecessor minted, a code no format answers to, an id too short to hold one,
# the code on its own, and the untrimmed paste the input box hands over.
_SESSION_IDS = (
    [f"{fmt['session_code']}{_TOKEN}" for fmt in FORMATS]
    + [_TOKEN, "hQ2-1sK_tWA", "aa" + _TOKEN, "", "k", "kz", "KZ" + _TOKEN]
    + [" kz" + _TOKEN, "kz" + _TOKEN + " "]
)
_FORMAT_KEYS = [fmt["key"] for fmt in FORMATS] + ["pinochle", ""]


@pytest.fixture(scope="module")
def js_session_results(tmp_path_factory):
    driver = tmp_path_factory.mktemp("legality_js_session") / "session_driver.js"
    driver.write_text(_SESSION_DRIVER, encoding="utf-8")
    payload = {"formats": FORMATS, "ids": _SESSION_IDS, "keys": _FORMAT_KEYS}
    proc = subprocess.run(
        ["node", str(driver), str(LEGALITY_JS)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


def test_the_browser_and_the_server_read_the_same_format_off_a_session_id(js_session_results):
    for session_id, js in zip(_SESSION_IDS, js_session_results["decoded"]):
        assert js == format_from_session_id(session_id), session_id


def test_the_browser_and_the_server_mint_the_same_prefix(js_session_results):
    for key, js in zip(_FORMAT_KEYS, js_session_results["prefixes"]):
        assert js == session_id_prefix(key), key


# ── validateDeck / validate_deck ────────────────────────────────────────────
#
# W2G4. The whole-deck validator is the largest hand mirror in the file and was
# the one with no parity test. What prompted it: a split card is one card under
# several spellings (CR 709.2), and both sides have to resolve a typed name to
# the same card *and* count its copies under one key (CR 100.2a). Each deck
# below is run through both validators over the identical payload, with each
# side building its own name lookup from it (``catalog_index`` /
# ``catalogIndex``), and the results are compared whole.

_DECK_DRIVER = """const fs = require("fs");
globalThis.window = {};
eval(fs.readFileSync(process.argv[2], "utf8"));
const L = globalThis.window.Legality;
const input = JSON.parse(fs.readFileSync(0, "utf8"));
L.setFormats(input.formats);
const index = L.catalogIndex(input.catalog);
const lookup = (name) => index.get(String(name).toLowerCase()) || null;
process.stdout.write(JSON.stringify({
  index: [...index.entries()].map(([key, card]) => [key, card.name]),
  results: input.decks.map((deck) => {
    const res = L.validateDeck(deck.cards, deck.format, lookup, deck.sideboard, deck.commander);
    return {
      format: res.format, legal: res.legal, problems: res.problems,
      illegal_names: [...res.illegalNames], ante_names: res.anteNames,
    };
  }),
}));
"""


def _w2g4_entry(name, *, type_line="Creature — Test", oracle_text="", mana_cost="",
                legal="legal", aliases=None, faces=None):
    entry = {
        "name": name, "type_line": type_line, "oracle_text": oracle_text,
        "mana_cost": mana_cost, "color_identity": [],
        "legalities": {fmt["scryfall_key"]: legal for fmt in FORMATS if fmt["scryfall_key"]},
    }
    if aliases is not None:
        entry["aliases"] = aliases
        entry["faces"] = faces or []
    return entry


_W2G4_CATALOG = [
    _w2g4_entry(
        "Left // Right", type_line="Sorcery // Sorcery", mana_cost="{R} // {3}{G}",
        aliases=["Left", "Right", "Left / Right", "Left/Right", "Left//Right"],
        faces=[
            {"name": "Left", "mana_cost": "{R}", "oracle_text": "Left deals 2 damage to any target."},
            {"name": "Right", "mana_cost": "{3}{G}", "oracle_text": "Create a 3/3 green Elephant creature token."},
        ],
    ),
    # A card really called what the second split card's half is called: the
    # real name wins the lookup on both sides.
    _w2g4_entry("Wax", mana_cost="{1}"),
    _w2g4_entry(
        "Wax // Wane", type_line="Instant // Instant", mana_cost="{G} // {W}",
        aliases=["Wax", "Wane", "Wax / Wane", "Wax/Wane", "Wax//Wane"],
        faces=[
            {"name": "Wax", "mana_cost": "{G}", "oracle_text": "Target creature gets +2/+2 until end of turn."},
            {"name": "Wane", "mana_cost": "{W}", "oracle_text": "Destroy target enchantment."},
        ],
    ),
    _w2g4_entry("Test Bears", mana_cost="{1}{G}"),
    _w2g4_entry("Forest", type_line="Basic Land — Forest"),
    _w2g4_entry("Banned Thing", legal="banned"),
    _w2g4_entry("Solo Thing", legal="restricted"),
    _w2g4_entry(
        "Swarm Rats", oracle_text="A deck can have any number of cards named Swarm Rats.",
    ),
]


def _w2g4_deck(cards, fmt="legacy", sideboard=None, commander=None):
    def rows(pairs):
        return [{"name": name, "count": count} for name, count in pairs or ()]

    return {
        "cards": rows(cards), "format": fmt,
        "sideboard": rows(sideboard), "commander": rows(commander),
    }


_W2G4_DECKS = [
    # The defect, in each shape it takes.
    _w2g4_deck([("Left // Right", 4), ("Left", 4)]),
    _w2g4_deck([("Left", 3), ("Right", 3)]),
    _w2g4_deck([("left/right", 2), ("LEFT // RIGHT", 2), ("Right", 1)]),
    _w2g4_deck([("Left", 3)], sideboard=[("Right", 2)]),
    _w2g4_deck([("Left // Right", 4)]),
    _w2g4_deck([("Left", 4)], fmt="casual"),
    # A real name beats an alias: "Wax" is the artifact, "Wane" is the split card.
    _w2g4_deck([("Wax", 4), ("Wax // Wane", 4)]),
    _w2g4_deck([("Wax", 4), ("Wane", 3), ("Wax / Wane", 2)]),
    # The rules around it, so the mirror is held beyond the one fix.
    _w2g4_deck([("Test Bears", 5), ("Forest", 60)]),
    _w2g4_deck([("Test Bears", 4), ("Forest", 56)], sideboard=[("Test Bears", 1), ("Forest", 15)]),
    _w2g4_deck([("Banned Thing", 1), ("Solo Thing", 2), ("Swarm Rats", 30), ("Nonesuch", 9)]),
    _w2g4_deck([("Solo Thing", 1)], fmt="vintage", sideboard=[("Solo Thing", 1)]),
    _w2g4_deck([("Left", 1), ("Left // Right", 1), ("Forest", 97)], fmt="commander",
               commander=[("Test Bears", 1)]),
    _w2g4_deck([("Test Bears", 1)], fmt="commander", commander=[("Left", 1), ("Right", 1)]),
    _w2g4_deck([], fmt="standard"),
]


@pytest.fixture(scope="module")
def js_deck_results(tmp_path_factory):
    driver = tmp_path_factory.mktemp("legality_js_deck") / "deck_driver.js"
    driver.write_text(_DECK_DRIVER, encoding="utf-8")
    payload = {"formats": FORMATS, "catalog": _W2G4_CATALOG, "decks": _W2G4_DECKS}
    proc = subprocess.run(
        ["node", str(driver), str(LEGALITY_JS)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


def test_w2g4_the_browser_and_the_server_index_a_catalog_by_the_same_names(js_deck_results):
    from web.deck_legality import catalog_index

    server = {key: entry["name"] for key, entry in catalog_index(_W2G4_CATALOG).items()}
    assert dict(js_deck_results["index"]) == server
    assert server["left"] == "Left // Right" and server["wane"] == "Wax // Wane"
    assert server["wax"] == "Wax", "a real card's name is never another card's alias"


def test_w2g4_the_browser_and_the_server_judge_a_deck_alike(js_deck_results):
    from web.deck_legality import catalog_index, validate_deck

    cat = catalog_index(_W2G4_CATALOG)
    for deck, js in zip(_W2G4_DECKS, js_deck_results["results"], strict=True):
        server = validate_deck(
            deck["cards"], deck["format"], cat, deck["sideboard"], deck["commander"],
        )
        server.pop("commander_identity", None)
        assert js == server, deck

    # And the answer both give to the question this block exists for.
    first = js_deck_results["results"][0]
    assert first["problems"] == [
        "Left // Right: 8 copies exceed the 4-copy limit in Legacy.",
        "Deck has 8 card(s); Legacy requires at least 60.",
    ]
