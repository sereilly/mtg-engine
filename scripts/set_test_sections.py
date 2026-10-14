"""Open, measure and move the marked group sections of a set's test files.

A wave's groups all write tests for one set, and its per-set files are where
their branches meet. The convention that made thirteen branches produce no
conflict in a test file (SET_PLAYBOOK.md, "Integration") is one delimited
region per group per file, written only by its owner, with its own imports::

    # ==== W1G3 ==========================================================
    # W1G3's tests go between this line and the "end W1G3" line.

    # ==== end W1G3 ======================================================

This script is the three things an integrator does to those regions, each of
which was a scratch file rewritten for Apocalypse and again for Odyssey:

``open <CODE> --groups W1G1 W1G2 …``
    Before the fan-out: create ``tests/sets/test_<code>_<type>.py`` for each
    printed type with one empty section per group. Run again for wave 2 and it
    appends the new groups' sections, leaving everything already there byte
    for byte — a branch in flight merges against unchanged context.

``report <CODE>``
    Lines per file against the size cap, and per section — which sections to
    move, read rather than guessed. The cap is ``check_all.SIZE_GUARDS``'s.

``move <file> --to <suffix> --sections W1G6 W1G7``
    At integration, when a file crosses its cap on nobody's branch: move whole
    sections to the sibling ``<file stem>_<suffix>.py``, **leaving the marker
    pairs behind** with a note saying where the tests went. Every moved line is
    asserted to be in the old text and in the new file, and the rest of the
    old file is asserted unchanged; line endings are kept.

Nothing here chooses *what* to move: cutting at a section boundary keeps every
group's tests whole and findable from the group that wrote them, which is what
the size guard protects (``tests/sets/README.md``).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_all import SIZE_GUARDS  # noqa: E402
from engine.card_loader import manifest_measured_sets, manifest_sets  # noqa: E402

SETS_DIR = REPO_ROOT / "tests" / "sets"
TYPES = ("creatures", "instants", "sorceries", "enchantments", "artifacts", "lands")
MARKER_WIDTH = 70
GROUP = re.compile(r"W\d+G\d+")
MARKER = re.compile(r"^# ==== (end )?(W\d+G\d+) =+$")


class SectionError(Exception):
    """The request names a section, a file or a set that is not as described."""


def per_set_cap() -> int:
    for label, cap, root, _pattern in SIZE_GUARDS:
        if root == "tests/sets":
            return cap
    raise SectionError("check_all.SIZE_GUARDS no longer names tests/sets")


def marker(group: str, *, end: bool = False) -> str:
    head = f"# ==== {'end ' if end else ''}{group} "
    return head + "=" * (MARKER_WIDTH - len(head))


def placeholder(group: str) -> str:
    return f"# {group}'s tests go between this line and the \"end {group}\" line."


def empty_section(group: str) -> list[str]:
    return [marker(group), placeholder(group), "", marker(group, end=True)]


def set_name(code: str) -> str:
    entries = list(manifest_sets()) + list(manifest_measured_sets())
    for entry in entries:
        if entry["code"].upper() == code.upper():
            return entry["name"]
    known = ", ".join(entry["code"] for entry in entries)
    raise SectionError(f"no set {code!r} in the manifest (shipped or measured). Known: {known}")


def _check_groups(groups: list[str]) -> None:
    for group in groups:
        if not GROUP.fullmatch(group):
            raise SectionError(f"{group!r} is not a group name (W<wave>G<n>, e.g. W1G3)")
    if len(set(groups)) != len(groups):
        raise SectionError("a group is named twice")


# --------------------------------------------------------------------------
# Reading a file's sections
# --------------------------------------------------------------------------

def _split(raw: bytes) -> tuple[list[str], str]:
    """The file's lines without their endings, and the ending it uses."""
    text = raw.decode("utf-8")
    eol = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n").split("\n"), eol


def sections(lines: list[str], name: str = "the file") -> dict[str, tuple[int, int]]:
    """``{group: (index of its opening marker, index of its closing marker)}``.

    Raises on a marker without its pair, a pair out of order, a section inside
    another and a group opened twice — each is a file a merge has damaged.
    """
    found: dict[str, tuple[int, int]] = {}
    open_group: str | None = None
    opened_at = -1
    for index, line in enumerate(lines):
        match = MARKER.match(line)
        if not match:
            continue
        is_end, group = bool(match.group(1)), match.group(2)
        if not is_end:
            if open_group is not None:
                raise SectionError(f"{name}:{index + 1}: {group} opens inside {open_group}")
            if group in found:
                raise SectionError(f"{name}:{index + 1}: {group} is opened twice")
            open_group, opened_at = group, index
        else:
            if open_group != group:
                raise SectionError(f"{name}:{index + 1}: 'end {group}' closes nothing open")
            found[group] = (opened_at, index)
            open_group = None
    if open_group is not None:
        raise SectionError(f"{name}:{opened_at + 1}: {open_group} is never closed")
    return found


def _is_empty_body(body: list[str]) -> bool:
    return all(not line.strip() or line.startswith("#") for line in body)


# --------------------------------------------------------------------------
# open
# --------------------------------------------------------------------------

def _opening_docstring(code: str, name: str, kind: str) -> list[str]:
    return f'''"""{name} {kind}.

Opened on `main` before the fan-out with one marked section per group. **A
group writes only between its own markers and puts its imports at the top of
its own section**, never at the top of the file: a self-contained section
cannot lose an import to a merge, can be moved whole when the file nears its
size cap, and branches editing disjoint regions merge without a conflict.
Every module-level helper, constant and import alias in a section carries
that group's `_w<wave>g<n>_` prefix — the sections share one module namespace.

Cards come from `set_pool("{code}")` / `set_cards("{code}")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""'''.split("\n")


def open_files(
    code: str, groups: list[str], *, types: tuple[str, ...] = TYPES,
    directory: Path = SETS_DIR, name: str | None = None,
) -> dict[Path, list[str]]:
    """Create or extend the set's per-type files. Returns ``{file: groups added}``."""
    _check_groups(groups)
    name = name or set_name(code)
    added: dict[Path, list[str]] = {}
    for kind in types:
        path = directory / f"test_{code.lower()}_{kind}.py"
        if path.exists():
            raw = path.read_bytes()
            lines, eol = _split(raw)
            present = sections(lines, path.name)
            new = [group for group in groups if group not in present]
            if not new:
                added[path] = []
                continue
            while lines and not lines[-1].strip():
                lines.pop()
            kept = len(lines)
        else:
            lines, eol, new, kept = _opening_docstring(code.upper(), name, kind), "\n", list(groups), None
        for group in new:
            lines += ["", "", *empty_section(group)]
        lines.append("")
        if kept is not None:
            before, _ = _split(raw)
            assert lines[:kept] == before[:kept], f"{path.name}: existing lines moved"
        path.write_bytes(eol.join(lines).encode("utf-8"))
        added[path] = new
    return added


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def report(code: str, *, directory: Path = SETS_DIR) -> list[tuple[Path, int, dict[str, int]]]:
    """``(file, line count, {group: body lines})`` for every file of the set."""
    rows = []
    for path in sorted(directory.glob(f"test_{code.lower()}_*.py")):
        lines, _ = _split(path.read_bytes())
        if lines and lines[-1] == "":
            lines = lines[:-1]
        spans = sections(lines, path.name)
        rows.append((path, len(lines), {group: end - start - 1 for group, (start, end) in spans.items()}))
    if not rows:
        raise SectionError(f"no tests/sets/test_{code.lower()}_*.py")
    return rows


# --------------------------------------------------------------------------
# move
# --------------------------------------------------------------------------

def _continued_docstring(source: Path, code_hint: str) -> list[str]:
    return f'''"""Continued from `{source.name}`: whole group sections moved out of it.

`{source.name}` reached the per-set size cap at integration, on no group's
branch. The sections below were moved **whole**, byte for byte, under the
marker pairs they had; a section carries its own imports and its own
`_w<wave>g<n>_` prefix, so nothing here depends on its old neighbours. Their
empty marker pairs stay behind in `{source.name}` so a branch still in flight
merges against unchanged context.

Cards come from `set_pool("{code_hint}")` / `set_cards("{code_hint}")` (`tests/sets/README.md`).
"""'''.split("\n")


def move_sections(source: Path, suffix: str, groups: list[str]) -> Path:
    """Move *groups*' sections from *source* to its ``_<suffix>`` sibling."""
    _check_groups(groups)
    if not re.fullmatch(r"[a-z0-9_]+", suffix):
        raise SectionError(f"--to {suffix!r}: a suffix is lowercase words, e.g. later_groups")
    if not source.is_file():
        raise SectionError(f"{source} does not exist")
    destination = source.with_name(f"{source.stem}_{suffix}.py")
    old_raw = source.read_bytes()
    old, eol = _split(old_raw)
    spans = sections(old, source.name)

    bodies: dict[str, list[str]] = {}
    for group in groups:
        if group not in spans:
            raise SectionError(f"{source.name} has no {group} section")
        start, end = spans[group]
        body = old[start + 1:end]
        if _is_empty_body(body):
            raise SectionError(f"{source.name}: {group} has nothing to move (empty, or moved already)")
        bodies[group] = body

    if destination.exists():
        new, new_eol = _split(destination.read_bytes())
        already = sections(new, destination.name)
        for group in groups:
            if group in already:
                raise SectionError(f"{destination.name} already has a {group} section")
        while new and not new[-1].strip():
            new.pop()
    else:
        code_hint = source.stem.split("_")[1].upper()
        new, new_eol = _continued_docstring(source, code_hint), eol
    for group in groups:
        new += ["", "", marker(group), *bodies[group], marker(group, end=True)]
    new.append("")

    kept: list[str] = []
    cursor = 0
    for group in sorted(groups, key=lambda g: spans[g][0]):
        start, end = spans[group]
        kept += old[cursor:start + 1]
        kept += [
            placeholder(group),
            f"# (moved whole to {destination.name} when this file reached its size cap)",
            "",
        ]
        cursor = end
    kept += old[cursor:]

    # What the playbook asks of this move, asserted rather than trusted.
    new_text = "\n".join(new)
    for group, body in bodies.items():
        assert "\n".join(body) in "\n".join(old), group
        assert "\n".join([marker(group), *body, marker(group, end=True)]) in new_text, group
    moved = sum(len(body) for body in bodies.values())
    assert len(kept) == len(old) - moved + 3 * len(groups), (len(kept), len(old), moved)
    assert [line for line in kept if MARKER.match(line)] == [line for line in old if MARKER.match(line)]
    sections(kept, source.name)
    sections(new, destination.name)

    destination.write_bytes(new_eol.join(new).encode("utf-8"))
    source.write_bytes(eol.join(kept).encode("utf-8"))
    return destination


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    opening = commands.add_parser("open", help="create or extend a set's per-type test files")
    opening.add_argument("code")
    opening.add_argument("--groups", nargs="+", required=True, metavar="W1G1")
    opening.add_argument("--types", nargs="+", default=list(TYPES), choices=TYPES)

    measuring = commands.add_parser("report", help="lines per file and per section against the cap")
    measuring.add_argument("code")

    moving = commands.add_parser("move", help="move whole sections to a sibling file")
    moving.add_argument("file", type=Path)
    moving.add_argument("--to", required=True, metavar="SUFFIX", help="e.g. later_groups")
    moving.add_argument("--sections", nargs="+", required=True, metavar="W1G6")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "open":
            for path, new in open_files(args.code, args.groups, types=tuple(args.types)).items():
                what = ", ".join(new) if new else "nothing to add"
                print(f"  {path.relative_to(REPO_ROOT).as_posix()}: {what}")
        elif args.command == "report":
            cap = per_set_cap()
            for path, count, per_group in report(args.code):
                flag = "OVER" if count > cap else f"{cap - count:>5,} left"
                print(f"{count:6,}  {flag}  {path.name}")
                for group, body in sorted(per_group.items(), key=lambda item: -item[1]):
                    if body > 2:
                        print(f"          {body:5,}  {group}")
        else:
            destination = move_sections(args.file, args.to, args.sections)
            cap = per_set_cap()
            for path in (args.file, destination):
                count = len(path.read_text(encoding="utf-8").splitlines())
                print(f"  {count:6,} lines ({cap - count:,} under the cap)  {path.name}")
    except SectionError as error:
        print(f"set_test_sections: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
