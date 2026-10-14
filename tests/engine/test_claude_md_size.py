"""CLAUDE.md is the short form, and it stays short.

It is loaded into every session and every subagent before anything else is
read. In October 2026 it was 133 KB — some thirty thousand tokens, paid by each
of a wave's groups, each closer and the integrator before its brief, on an
account whose weekly limit is what caps a wave at five agents. Most of it was
not instruction: a 24 KB opening section of set history, and for every seam the
incident that found it, card by card, beside the one sentence saying what to do.

So the file was split along that line. CLAUDE.md keeps each rule and the guard
that holds it; the reasoning went, verbatim, to the documents nobody loads until
they need them:

* ``engine/ARCHITECTURE.md``, "The long form of CLAUDE.md" — every seam in full,
  the web layer, the tests, instruments and AI simulator;
* ``SET_PLAYBOOK.md``, "The pool and its manifest, set by set" and "The
  verification tracker, set by set".

**New history goes there.** What a set found is a paragraph under the entry it
belongs to, and the rule it changes is changed here in a sentence. If this test
fails, that is what it is asking for; raise the ceiling only after deciding the
new lines are ones every agent has to read before every task.

A ceiling passes when the thing it measures breaks, so the file is also held to
still being there and still being the file the long form points back to.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: 38.5 KB on the day of the split, measured with LF endings so a checkout's
#: line-ending setting does not move it. Room for some forty more seam lines.
CEILING_BYTES = 44_000
FLOOR_BYTES = 20_000


def _text(name: str) -> str:
    return (REPO / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


def test_claude_md_stays_the_short_form():
    size = len(_text("CLAUDE.md").encode("utf-8"))
    assert size <= CEILING_BYTES, (
        f"CLAUDE.md is {size:,} bytes, over its {CEILING_BYTES:,} ceiling. It is "
        "loaded into every session and every subagent. Keep the rule and its "
        "guard here in a sentence; the incident, the cards and the numbers go in "
        "engine/ARCHITECTURE.md (\"The long form of CLAUDE.md\") or, for a set's "
        "history, SET_PLAYBOOK.md (\"The pool and its manifest, set by set\")."
    )


def test_the_ceiling_is_measuring_the_real_file():
    text = _text("CLAUDE.md")
    assert len(text.encode("utf-8")) >= FLOOR_BYTES
    for section in (
        "## What this is", "## Commands", "## Engine architecture",
        "### Extension points", "## Web layer", "## Card verification tracker",
    ):
        assert f"\n{section}\n" in text, section


def test_the_long_form_is_where_the_short_form_says_it_is():
    architecture = _text("engine/ARCHITECTURE.md")
    for heading in (
        "## The long form of CLAUDE.md",
        "## Extension points, in full",
        "## Tests, instruments and the AI simulator, in full",
        "## Web layer, in full",
    ):
        assert f"\n{heading}\n" in architecture, heading
    playbook = _text("SET_PLAYBOOK.md")
    for heading in (
        "## The pool and its manifest, set by set",
        "## The verification tracker, set by set",
    ):
        assert f"\n{heading}\n" in playbook, heading
    short = _text("CLAUDE.md")
    assert "engine/ARCHITECTURE.md" in short and "SET_PLAYBOOK.md" in short
