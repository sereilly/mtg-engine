"""For every line of every group's work card that the compiler refuses: the
layer that refused it, and — for a grammar refusal — how far the parse got and
through which grammar functions.

    furthest.py CODE <groups.json> <out-dir>     run from a tree with CODE ingested

<groups.json> is `{group: {"cards": [...], ...}}`; writes
<out-dir>/<group>/furthest.txt. Each card is read by `scripts/probe_line.py`,
which runs the compiler with every line reader observed and names the layer
each refused line met first (`probe_line.census_site`). Lines are the ones the
compiler reads (after ``line_rewrites.expand_ability_lines``).

**The site is a layer, and only a grammar refusal gets a production.** This
used to watch the grammar alone, so a line a *table* refused — a trigger
condition the pattern table has no row for, a card gate, the Aura gate, a line
reader that does not take what the grammar lowered — was pointed at whatever
grammar production happened to accept furthest, in the wrong layer; and a line
the grammar cannot parse but a text-keyed table claims was listed as refused at
all. Both are corrected: the first names its layer, the second is not listed.

The furthest production that *accepted* is the best lead a brief can give —
"the parse passed through" overcounts — and it is still a lead: it names where
the parser stopped, not where the sentence will be taught. It is also what a
Phase 0 pre-split asks: which modules two groups will reach.
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))

from engine.card_loader import load_cards, manifest_set_path  # noqa: E402
from engine.oracle import compiled_faces  # noqa: E402
from probe_line import (census_site, observing, origin_label,  # noqa: E402
                        probe_unit)


def card_block(card) -> list[str]:
    """The ``furthest.txt`` lines for one card: each refused line, its site,
    and the furthest production for a grammar refusal."""
    out = [f"## {card.name}"]
    for face, _program in compiled_faces(card):
        unit = probe_unit(face, origin_label(card))
        for line in unit.lines:
            status, detail = census_site(line)
            if status == "clean":
                continue
            out.append(f"  line: {line.text}")
            out.append(f"    {line.verdict}")
            if line.round > 1:
                out.append(f"    (read with printed line(s) removed: {line.removed})")
            # Wherever the grammar refused the line, how far it got — beside a
            # gate's own site as much as for a grammar site.
            furthest = line.grammar.furthest
            if furthest is not None:
                out.append(f"    grammar: {line.grammar.parse_error}; furthest token "
                           f"{furthest.token} of {furthest.total}; "
                           f"unread: {furthest.unread[:110]!r}")
                for path, lineno, name in furthest.frames[-6:]:
                    out.append(f"      {path}:{lineno} {name}")
    out.append("")
    return out


def main(argv: list[str]) -> int:
    code, groups_path, out_dir = argv[0].upper(), argv[1], argv[2]
    groups = json.load(io.open(groups_path, encoding="utf-8"))
    cards = {c.name: c for c in load_cards([manifest_set_path(code, include_measured=True)])}
    with observing():
        for group, spec in groups.items():
            out: list[str] = []
            for name in spec["cards"]:
                out.extend(card_block(cards[name]))
            path = os.path.join(out_dir, group, "furthest.txt")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            io.open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
            print(group, "->", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
