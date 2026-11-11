"""Open a set's per-set test files with one marked section per wave-1 group.

    open_test_files.py CODE <group> [<group> ...] [--later TYPE[,TYPE...]]

Run from the tree's root, on main before the fan-out. One file per printed
type (`tests/sets/README.md`); refuses to overwrite an existing file. Line
endings follow the repository's (CRLF in this working tree).

``--later creatures,artifacts`` opens a ``_later_groups`` sibling for each
named type and puts the second half of the groups' sections in it — the
playbook's rule for a type more than five groups write into (Scourge's
creatures file reached the cap at its seventh merge). Every group keeps
exactly one section per type, in one of the pair.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())

from engine.card_loader import manifest_measured_sets, manifest_sets  # noqa: E402

args = sys.argv[1:]
later: set[str] = set()
if "--later" in args:
    at = args.index("--later")
    later = {t.strip() for t in args[at + 1].split(",") if t.strip()}
    del args[at:at + 2]
code = args[0].upper()
groups = args[1:]
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
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""
'''

SECTION = '''

# ==== {g} ==========================================================
# {g}'s tests go between this line and the "end {g}" line.

# ==== end {g} ======================================================
'''

unknown = later - set(FILES)
assert not unknown, f"--later names no per-set type: {sorted(unknown)}"


def _open(path: Path, title: str, members: list[str]) -> None:
    assert not path.exists(), f"{path} already exists"
    text = DOC.format(title=title, code=code) + "".join(SECTION.format(g=g) for g in members)
    path.write_text(text, encoding="utf-8", newline="\r\n")
    print("opened", path, len(text.splitlines()), "lines:", ", ".join(members))


for stem, title in FILES.items():
    path = Path(f"tests/sets/test_{code.lower()}_{stem}.py")
    if stem in later:
        half = (len(groups) + 1) // 2
        _open(path, title, groups[:half])
        _open(path.with_name(f"test_{code.lower()}_{stem}_later_groups.py"),
              f"{title} — the later groups' sections", groups[half:])
    else:
        _open(path, title, groups)
