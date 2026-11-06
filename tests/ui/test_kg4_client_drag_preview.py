"""A drag ends the card preview's hover.

The preview is hover-only: shown on a DOM card's ``mouseover``, hidden on its
``mouseout``. HTML5 drag and drop sends neither while a drag lasts, and a
drag-cast re-renders the hand, so the card the preview was showing is gone
without ever being left — after a drag-cast the preview stayed up over the
seat's graveyard and exile piles until another card was hovered (Scourge's
Phase 5). ``initCardPreviewHover`` now hides it on the document's
``dragstart``, ``drop`` and ``dragend`` (captured: the drop lands on the
canvas, and the dragged element may be gone before its own dragend).

Driven in a browser too (kg4): Grizzly Bears hovered (preview up), dragged
onto the battlefield and cast, and the piles left clear.
"""
from __future__ import annotations

import shutil

import pytest

from tests.helpers import run_app_js

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)

_PRELUDE = r"""
const listeners = {};
const documentListeners = {};
const boardEl = {
  addEventListener(type, fn) { listeners[type] = fn; },
  contains() { return true; },
};
globalThis.document = {
  addEventListener(type, fn, capture) { documentListeners[type] = { fn, capture: !!capture }; },
};
let shown = null;
function showCardPreview(card) { shown = card.name; }
function clearCardPreview() { shown = null; }
function scheduleHidePreview() { shown = null; }
function hovered(name) {
  return { target: { closest: () => ({ dataset: { previewCard: JSON.stringify({ name }) } }) } };
}
"""


@needs_node
def test_every_drag_event_hides_the_preview():
    out = run_app_js(
        ["initCardPreviewHover"],
        r"""
        initCardPreviewHover();
        const seen = {};
        for (const type of ["dragstart", "drop", "dragend"]) {
          listeners.mouseover(hovered("Grizzly Bears"));
          const before = shown;
          documentListeners[type].fn({});
          seen[type] = [before, shown, documentListeners[type].capture];
        }
        // The hover itself still works after a drag.
        listeners.mouseover(hovered("Shock"));
        seen.after = shown;
        return seen;
        """,
        prelude=_PRELUDE,
    )
    assert out == {
        "dragstart": ["Grizzly Bears", None, True],
        "drop": ["Grizzly Bears", None, True],
        "dragend": ["Grizzly Bears", None, True],
        "after": "Shock",
    }
