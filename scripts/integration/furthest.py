"""For every line of every group's work card that the grammar cannot use: how far
did the parse get, and through which grammar functions?

    furthest.py CODE <groups.json> <out-dir>     run from a tree with CODE ingested

<groups.json> is `{group: {"cards": [...], ...}}`; writes
<out-dir>/<group>/furthest.txt. Patches TokenStream.advance to record the
highest cursor reached and the grammar frames on the stack at that moment.
Lines are read the way the compiler reads them (after
``line_rewrites.expand_ability_lines``).

The furthest production that *accepted* is the best lead a brief can give —
"the parse passed through" overcounts — and it is still a lead: it names where
the parser stopped, not where the sentence will be taught. It is also what a
Phase 0 pre-split asks: which modules two groups will reach.
"""
import io
import json
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, os.getcwd())

from engine.card_loader import load_cards, manifest_set_path  # noqa: E402
from engine.grammar import compile_line  # noqa: E402
from engine.grammar import stream as stream_mod  # noqa: E402
from engine.oracle import expand_ability_lines  # noqa: E402

GR = str(Path("engine/grammar").resolve()).lower()
best = {"pos": -1, "frames": None, "stream": None}
orig_advance = stream_mod.TokenStream.advance


def advance(self, count=1):
    orig_advance(self, count)
    if self.pos >= best["pos"]:
        st = [f for f in traceback.extract_stack()[:-1]
              if f.filename.lower().startswith(GR)]
        best["pos"] = self.pos
        best["frames"] = [(f.filename[len(GR) + 1:].replace("\\", "/"), f.lineno, f.name)
                          for f in st]
        best["stream"] = self


stream_mod.TokenStream.advance = advance

code = sys.argv[1].upper()
groups = json.load(io.open(sys.argv[2], encoding="utf-8"))
out_dir = sys.argv[3]
cards = {c.name: c for c in load_cards([manifest_set_path(code, include_measured=True)])}

for group, spec in groups.items():
    out = []
    for name in spec["cards"]:
        card = cards[name]
        out.append(f"## {name}")
        for line in expand_ability_lines(card.oracle_text or "").splitlines():
            if not line.strip():
                continue
            best.update(pos=-1, frames=None, stream=None)
            result = compile_line(line, card_name=name)
            if result.usable or (result.parse_error is None and result.lowering_error is None):
                continue
            s = best["stream"]
            rest = " ".join(t.text for t in s.tokens[best["pos"]:]) if s else ""
            out.append(f"  line: {line}")
            out.append(f"    parse_error={result.parse_error!r} lowering_error={result.lowering_error!r}")
            total = len(s.tokens) if s else "?"
            out.append(f"    furthest token {best['pos']} of {total}; unread: {rest[:110]!r}")
            for frame in (best["frames"] or [])[-6:]:
                out.append(f"      {frame[0]}:{frame[1]} {frame[2]}")
        out.append("")
    path = os.path.join(out_dir, group, "furthest.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(group, "->", path)
