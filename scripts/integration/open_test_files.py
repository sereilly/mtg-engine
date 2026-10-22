"""Open a set's per-set test files with one marked section per wave-1 group.

    open_test_files.py CODE <group> [<group> ...]     e.g. ONS W1G1 W1G2 ...

Run from the tree's root, on main before the fan-out. One file per printed
type (`tests/sets/README.md`); refuses to overwrite an existing file. Line
endings follow the repository's (CRLF in this working tree).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())

from engine.card_loader import manifest_measured_sets, manifest_sets  # noqa: E402

code = sys.argv[1].upper()
groups = sys.argv[2:]
assert groups, "name the wave-1 groups"
entry = next(s for s in manifest_measured_sets() + manifest_sets() if s["code"].upper() == code)
set_name = entry.get("name", code)
FILES = {
    "creatures": f"{set_name} creatures (legendary ones too)",
    "enchantments": f"{set_name} enchantments, Auras included",
    "instants": f"{set_name} instants",
    "sorceries": f"{set_name} sorceries",
    "artifacts": f"{set_name} artifacts",
    "lands": f"{set_name} lands",
}

DOC = '''"""{title}.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("{code}")` / `set_cards("{code}")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""
'''

SECTION = '''

# ==== {g} ==========================================================
# {g}'s tests go between this line and the "end {g}" line.

# ==== end {g} ======================================================
'''

for stem, title in FILES.items():
    path = Path(f"tests/sets/test_{code.lower()}_{stem}.py")
    assert not path.exists(), f"{path} already exists"
    text = DOC.format(title=title, code=code) + "".join(SECTION.format(g=g) for g in groups)
    path.write_text(text, encoding="utf-8", newline="\r\n")
    print("opened", path, len(text.splitlines()), "lines")
