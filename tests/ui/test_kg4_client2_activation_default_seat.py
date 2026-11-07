"""An activation's default target seat is one formal value, not a reading of
the ability's text.

The DOM card's click read every activated line of the permanent for "target
creature gains", "untap target", "regenerate target" or "target creature gets
+" (``activatedAbilityTargetsSelf``) and, on a match, started the activation
at the clicker's own seat; the canvas board's click — every click a person
makes on the board — always started at the opponent. The census below is why
the copy could go: every pool ability whose line the copy matched names its
target through a picker the activation cascade runs from the server's spec
(the cascade's own predicates, run in node over the spec the server derives),
so the seat it guessed was replaced before anything was sent. Both paths now
start at ``activationDefaultSeat``.

Run backwards it fails at the last test (the copy is in the source); the
census holds on the base too — that is what it proves.
"""
from __future__ import annotations

import shutil

import pytest

from engine import faces
from engine.card_loader import load_catalog
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec, usable_activated_abilities
from tests.helpers import app_js_function_body, run_app_js

_CATALOG = load_catalog()
_CARDS = {card.name: card for card in _CATALOG}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)

#: The deleted copy's phrases, quoted from it.
_DELETED_PHRASES = (
    "target creature gains banding", "target creature gains flying", "target creature gains",
    "untap target", "regenerate target", "target creature gets +",
)

#: The activation cascade's target predicates (``startActivationPrompt`` and
#: the click path before it), each over the activation spec.
_PICKERS = (
    "activatedAbilityRequiresTargetLand", "activatedAbilityRequiresTargetCreature",
    "activatedAbilityRequiresTargetPermanent", "activatedAbilityRequiresTargetArtifact",
    "activatedAbilityRequiresTargetAny", "activatedAbilityRequiresTargetPlayer",
    "activatedAbilityRequiresTargetCreatureGrant", "activatedAbilityRequiresTargetStackSpell",
    "activatedAbilityRequiresTargetRoles",
)


def _matched_abilities():
    rows = []
    for unit in faces.compilation_units(_CATALOG):
        if unit is not _CARDS.get(unit.name):
            continue
        for index, ability in enumerate(usable_activated_abilities(compile_card_oracle(unit))):
            line = (ability.source_line or "").lower()
            if any(phrase in line for phrase in _DELETED_PHRASES):
                spec = derive_activation_spec(ability)
                rows.append({"name": unit.name, "index": index, "spec": spec})
    return rows


@needs_node
def test_every_ability_the_copy_matched_names_its_target_through_a_picker():
    rows = _matched_abilities()
    # A census that matched nothing would pass as one that found nothing.
    assert len(rows) >= 40, len(rows)
    picked = run_app_js(
        [*_PICKERS, "specKind", "targetSpecOf"],
        "const pickers = [" + ", ".join(_PICKERS) + "];"
        " return INPUT.map((row) => pickers.some((f) => f({ target_spec: row.spec || {} })));",
        rows,
        prelude='const EMPTY_TARGET_SPEC = { kind: "none", requires_target: false, valid_targets: [] };',
    )
    unpicked = [(row["name"], row["index"], (row["spec"] or {}).get("kind"))
                for row, ok in zip(rows, picked) if not ok]
    assert unpicked == [], unpicked


def test_both_click_paths_start_at_one_default_and_read_no_text():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    assert "activatedAbilityTargetsSelf(" not in source
    assert source.count("activationDefaultSeat(") >= 3  # the definition and both paths
    body = app_js_function_body("activationDefaultSeat")
    assert "oracle_text" not in body
