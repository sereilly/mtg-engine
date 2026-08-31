"""The browser's activated-ability reader agrees with the compiler about costs.

``web/static/app.js`` parses a card's "{cost}: effect" lines itself
(``getActivatedAbilityOptions``) to build the ability menu, and the cost it
reads (``getActivatedAbilityCost``) is what the insufficient-mana prompt shows
and what the auto-tap flow pays. The engine compiles the same lines through
``engine/oracle.py``. Two readers of one text — and the second one drifted:
for an Equipment the client split ``Equip {1} ({1}: Attach to target creature
you control. Equip only as a sorcery.)`` at its *first* colon, which sits
inside the reminder text, read the cost as ``Equip {1} ({1}`` and asked for two
mana to pay a {1} equip. The engine, which rewrites the line to its CR 702.6a
text first, charged {1}.

So this runs the JS reader over the whole shipped pool in bare ``node`` and
holds it to the compiled program: the two must list the **same number** of
abilities, and each one's mana and {T} cost must match.

The count used to be exempt. "Where the client lists fewer abilities than the
engine, it is a prose-cost line the menu parser has never read; that gap is
pre-existing and reported, not asserted" — 107 cards were in it, and the
exemption was hiding the same defect this file was written for rather than a
cosmetic shortfall. ``option.index`` is the ``ability_index`` the client sends
back, so a dropped line renumbers every ability after it: Balduvian Hydra's
menu asked for {R}{R}{R} and the engine ran the free counter-removal
prevention that really sits at index 0. The cost comparison could not see it,
because it walked the two lists with ``zip`` and both sides agreed about the
one option that survived.

Skipped when node is not on PATH (``tests/rules/test_equipment.py`` keeps the
engine's side pinned regardless).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.card_loader import load_catalog
from engine.oracle import compile_card_oracle

REPO = Path(__file__).resolve().parents[2]
APP_JS = REPO / "web" / "static" / "app.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the JS half cannot run",
)

# app.js is one DOM-bound script, so the functions under test are lifted out by
# name rather than the file being evaluated whole. Each is a top-level
# `function name(` ... `\n}\n` block; the two regex constants they read are
# sliced out beside them. A renamed function fails loudly here.
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
const pieces = ["activatedAbilityText", "activationColonIndex", "expandEquipLine",
  "getActivatedAbilityCost", "getActivatedAbilityOptions", "isPlaneswalkerCard",
  "loyaltyCostOf"].map(grab).join("\n");
const re = src.slice(src.indexOf("const EQUIP_LINE_RE"), src.indexOf("function expandEquipLine"));
const lo = src.slice(src.indexOf("const LOYALTY_COST_RE"), src.indexOf("function isPlaneswalkerCard"));
eval(re + lo + pieces + ";globalThis.T={getActivatedAbilityCost,getActivatedAbilityOptions}");
const cards = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const out = {};
for (const c of cards) {
  out[c.name] = {
    options: T.getActivatedAbilityOptions(c).map(o => o.cost),
    first: T.getActivatedAbilityCost(c),
    byIndex: T.getActivatedAbilityOptions(c).map((_, i) => T.getActivatedAbilityCost(c, i)),
  };
}
process.stdout.write(JSON.stringify(out));
'''

_MANA = re.compile(r"\{(\d+|[WUBRGC]|T)\}")


def _js_symbols(cost: str) -> list[str]:
    """The mana and tap symbols in a client cost string, normalized. ``{0}`` is
    no cost at all, which is how the engine spells it."""
    found = [m.group(0).upper() for m in _MANA.finditer(cost or "")]
    return sorted(s for s in found if s != "{0}")


def _engine_symbols(cost) -> list[str]:
    symbols: list[str] = []
    for symbol, count in cost.mana.items():
        if not count:
            continue
        if symbol == "generic":
            symbols.append("{%d}" % count)
        else:
            symbols += ["{%s}" % symbol] * count
    if cost.requires_tap:
        symbols.append("{T}")
    return sorted(symbols)


@pytest.fixture(scope="module")
def js_readings(tmp_path_factory):
    cards = load_catalog()
    folder = tmp_path_factory.mktemp("ability-cost-parity")
    payload = folder / "cards.json"
    payload.write_text(
        json.dumps([
            {"name": c.name, "oracle_text": c.oracle_text, "type_line": c.type_line}
            for c in cards
        ]),
        encoding="utf-8",
    )
    driver = folder / "driver.js"
    driver.write_text(_DRIVER, encoding="utf-8")
    raw = subprocess.run(
        ["node", str(driver), str(APP_JS), str(payload)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    return cards, json.loads(raw)


def test_the_client_lists_the_same_abilities_the_compiler_does(js_readings):
    """Same *count*, pool-wide — the half a positional comparison cannot see.

    ``option.index`` is what the client sends back as ``ability_index``, and the
    server indexes ``usable_activated_abilities`` with it. So a line the client
    drops does not merely go unlisted: every later ability of that card moves up
    a slot, and the menu and the engine are then talking about different
    abilities under one number. City of Shadows was living that way — the client
    offered its storage-counter mana ability where the engine had "{T}, Exile a
    creature you control" — and the cost comparison below was blind to it,
    because both spell ``{T}`` and it walked the two lists with ``zip``.

    Asserted here rather than left as a reported gap: 107 cards printed a cost
    the menu parser refused, and "the client lists fewer" was the shape of all
    107.
    """
    cards, js = js_readings
    dropped = [
        (card.name, [a.source_line for a in compile_card_oracle(card).activated_abilities],
         js[card.name]["options"])
        for card in cards
        if len(compile_card_oracle(card).activated_abilities) != len(js[card.name]["options"])
    ]
    assert not dropped, (
        "the client's ability list is a different length from the compiler's, "
        "so every index after the difference names a different ability "
        f"(card, compiled lines, client costs):\n" + "\n".join(f"  {d}" for d in dropped)
    )


def test_every_ability_both_sides_list_has_the_same_cost(js_readings):
    cards, js = js_readings
    disagreements = []
    for card in cards:
        program = compile_card_oracle(card)
        engine = list(program.activated_abilities)
        client = js[card.name]["options"]
        for index, (ability, cost) in enumerate(zip(engine, client)):
            if ability.cost.is_loyalty:
                continue
            if _engine_symbols(ability.cost) != _js_symbols(cost):
                disagreements.append(
                    (card.name, index, ability.source_line, cost)
                )
    assert not disagreements, (
        "the client reads a different activation cost than the compiler "
        "charges (card, ability index, compiled line, client cost):\n"
        + "\n".join(f"  {d}" for d in disagreements)
    )


def test_the_indexed_cost_reader_returns_the_listed_option(js_readings):
    """`getActivatedAbilityCost(card, i)` is the cost of option *i* — the
    auto-tap flow pays by it, and a two-ability card (Rock Hydra, Mazemind
    Tome) must not pay the first ability's cost for the second."""
    _, js = js_readings
    wrong = [
        (name, reading["options"], reading["byIndex"])
        for name, reading in js.items()
        if reading["options"] != reading["byIndex"]
        or (reading["options"] and reading["first"] != reading["options"][0])
    ]
    assert not wrong, wrong


def test_the_client_lists_every_equip_ability(js_readings):
    """An Equipment's equip line must reach the menu: the client mirrors the
    CR 702.6a rewrite the compiler applies, so the line is an option with the
    printed cost and nothing from the reminder text."""
    cards, js = js_readings
    equipment = [c for c in cards if "Equipment" in c.type_line]
    assert equipment, "the pool ships Equipment (Short Sword, Malefic Scythe)"
    for card in equipment:
        program = compile_card_oracle(card)
        engine = program.activated_abilities
        client = js[card.name]["options"]
        assert len(client) == len(engine), (
            f"{card.name}: client lists {client}, engine compiled "
            f"{[a.source_line for a in engine]}"
        )
        for ability, cost in zip(engine, client):
            assert "(" not in cost and "quip" not in cost.lower(), (
                f"{card.name}: reminder text leaked into the client cost {cost!r}"
            )
            assert _engine_symbols(ability.cost) == _js_symbols(cost)
