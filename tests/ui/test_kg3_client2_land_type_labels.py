"""A text change's land-type words are labelled as land types.

Known-gaps leftover from kg3/client (cosmetic): Magical Hack ("replacing all
instances of one basic land type with another") offered its words as colour
buttons — "White {W}" for Plains — on both its permanent and its spell path,
because the wire addresses a basic land type by its colour letter
(``old_color`` / ``mana_color``: W = Plains, …) and the picker drew the letter's
colour. The word being replaced is "Plains". The letters on the wire are
unchanged; the buttons and the hint name the land type
(``textChangeWordLabel``), and a colour word (Sleight of Mind) keeps its colour.
Since kg4, which words is the server's (``text_change.mode``), and a mode
offering both (Mind Bend) names both.

Backwards on ``f6c44277``: ``textChangeWordLabel`` does not exist and the
renderer drew ``label`` (the colour name) for every text-change button.
"""

from __future__ import annotations

import shutil

import pytest

from tests.helpers import app_js_function_body, run_app_js

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_CONSTANTS = (
    'const MANA_COLOR_OPTIONS = [{symbol: "W", label: "White"}, {symbol: "U", label: "Blue"},'
    ' {symbol: "B", label: "Black"}, {symbol: "R", label: "Red"}, {symbol: "G", label: "Green"}];'
    ' const LAND_TYPE_BY_SYMBOL = { W: "plains", U: "island", B: "swamp", R: "mountain", G: "forest" };'
)


@needs_node
def test_each_letter_is_named_as_a_land_type_or_as_a_colour():
    labels = run_app_js(
        ["textChangeWordLabel"],
        """
        const letters = ["W", "U", "B", "R", "G"];
        return {
          land: letters.map((s) => textChangeWordLabel(s, "land_type")),
          color: letters.map((s) => textChangeWordLabel(s, "color_word")),
          either: letters.map((s) => textChangeWordLabel(s, "color_word_or_land_type")),
        };
        """,
        prelude=_CONSTANTS,
    )

    assert labels == {
        "land": ["Plains", "Island", "Swamp", "Mountain", "Forest"],
        "color": ["White", "Blue", "Black", "Red", "Green"],
        "either": [
            "White / Plains", "Blue / Island", "Black / Swamp", "Red / Mountain",
            "Green / Forest",
        ],
    }


def test_the_picker_and_the_hint_read_the_label_on_both_paths():
    """Both of Magical Hack's paths — a permanent target and a spell target —
    open one picker (``pendingManaColor`` of kind "cast" with its ``textMode``),
    so the renderer is the one place the buttons are drawn, and the cast's
    hint the one place the words are echoed."""
    panel = app_js_function_body("renderActivationPrompt")
    branch = panel.index('pendingManaColor.kind === "cast" && pendingManaColor.textMode === "land_type"')
    assert 'textChangeWordLabel(symbol, "land_type")' in panel[branch:branch + 400]
    assert "textChangeWordLabel(symbol, pendingManaColor.textMode)" in panel
    resolve = app_js_function_body("resolvePendingManaColor")
    assert "textChangeWordLabel(pending.fromColor, pending.textMode)" in resolve
    assert "textChangeWordLabel(manaColor, pending.textMode)" in resolve
    assert "replaced ${fromWord} with ${toWord}" in resolve
