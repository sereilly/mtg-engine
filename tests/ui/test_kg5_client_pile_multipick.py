"""A click on a grouped stack during a multi-pick picks the stack's next
unpicked member.

8ED's Primeval Force, "sacrifice three Forests", over the canvas's ×3 Forest
stack: identical permanents are drawn as ONE card with the others as thin
strips behind it, and a click on the stack toggled its front card — the
second and third Forests were reached only by finding the strips. "Selected
2/3" said it worked; nothing said where the next card was.

Now (``nextUnpickedPileMember``, over the canvas's ``getPileMembers``) a click
on a member that is already picked picks the next unpicked member the prompt
offers, front to back, while the prompt can take another; an unpicked member
is picked as it always was; and once nothing in the stack is left to pick, or
the prompt is full, the click toggles what it hit, which is how a pick is
taken back. The same walk serves a cast's several targets ("destroy two target
lands", Rain of Salt) and a divided one.

Driven in a browser: Primeval Force over Forest ×4 — four clicks on the
front read 1/3 [12], 2/3 [12, 10], 3/3 [12, 10, 8], then 2/3 (the full
prompt's click took the front back); Confirm sacrificed the three. Rain of
Salt over an opponent's Forest ×3: [22], [22, 20], then [20]; confirmed, two
Forests destroyed.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from tests.helpers import run_app_js

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_CANVAS = Path(__file__).resolve().parents[2] / "web" / "static" / "battlefield-canvas.js"


def _canvas_method(name: str) -> str:
    """One method of the canvas class, as an object-literal member."""
    source = _CANVAS.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.search(r"\n  " + re.escape(name) + r"\([^)]*\) \{\n.*?\n  \}\n", source, re.S)
    assert match is not None, f"battlefield-canvas.js no longer defines {name}"
    return match.group(0)


def _prelude():
    return (
        "const canvasMethods = {" + _canvas_method("getPileMembers") + "};\n"
        "let battlefieldCanvas = null;\n"
    )


@needs_node
def test_the_canvas_names_a_piles_members_front_first_and_no_aura_fan():
    out = run_app_js(
        [],
        """
        const canvas = {
          ...canvasMethods,
          // The front (fully visible) card is a pile's LAST key.
          stacks: [
            { kind: "pile", keys: ["0-1", "0-2", "0-3"] },
            { kind: "aura", keys: ["0-5", "0-6"] },
          ],
          cardItems: ["0-1", "0-2", "0-3", "0-4", "0-5", "0-6"].map((key) => {
            const [seat, idx] = key.split("-").map(Number);
            return { key, seat, idx };
          }),
        };
        return {
          pile: canvas.getPileMembers(0, 2),
          alone: canvas.getPileMembers(0, 4),
          aura: canvas.getPileMembers(0, 5),
        };
        """,
        prelude=_prelude(),
    )
    assert out["pile"] == [{"seat": 0, "idx": 3}, {"seat": 0, "idx": 2}, {"seat": 0, "idx": 1}]
    assert out["alone"] == [] and out["aura"] == []


@needs_node
def test_a_click_on_a_picked_member_picks_the_next_one_until_none_is_left():
    out = run_app_js(
        ["nextUnpickedPileMember"],
        """
        battlefieldCanvas = {
          getPileMembers: (seat, idx) =>
            [3, 2, 1].includes(idx) ? [3, 2, 1].map((i) => ({ seat, idx: i })) : [],
        };
        const all = () => true;
        const never = () => false;
        const pick = (clicked, picked, { offered = all, isFull = never } = {}) =>
          nextUnpickedPileMember(0, clicked, {
            offered, picked: new Set(picked.map((i) => `0-${i}`)), isFull,
          });
        return {
          // The ×3 stack clicked on its front, again and again.
          walk: [pick(3, []), pick(3, [3]), pick(3, [3, 2]), pick(3, [3, 2, 1])],
          // A full prompt's click takes back what it hit.
          full: pick(3, [3], { isFull: () => true }),
          // An unpicked member is picked as it always was (a strip clicked).
          strip: pick(2, [3]),
          // A member the prompt does not offer is passed over.
          skips: pick(3, [3], { offered: (key) => key !== "0-2" }),
          // No pile: the click is the card's.
          alone: pick(9, [9]),
        };
        """,
        prelude="let battlefieldCanvas = null;",
    )
    assert out["walk"] == [3, 2, 1, 3]
    assert out["full"] == 3
    assert out["strip"] == 2
    assert out["skips"] == 1
    assert out["alone"] == 9
