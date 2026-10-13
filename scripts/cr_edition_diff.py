"""What a Comprehensive Rules bump moved, and who in this repo cites it.

A new edition renumbers. Rules are inserted mid-section, the ones behind them
shift, and a citation written against the old numbering goes on naming a rule
that exists and is about something else — ``CR 506.7`` was "cast this spell
only before/after a point in combat" in April 2026 and is "had to attack" in
September. ``tests/engine/test_cr_citation_subjects.py`` catches that inside
the 701 block, where each rule is headed by one keyword; everywhere else the
headings are prose and nothing could check them. This does, by text::

    python scripts/cr_edition_diff.py <old-edition.txt>            # against MagicCompRules.txt
    python scripts/cr_edition_diff.py <old-edition.txt> <new.txt>
    python scripts/cr_edition_diff.py --install <download.txt>     # write MagicCompRules.txt

It reads both editions rule by rule and reports, for every rule the repo
**cites**:

* **moved** — the old rule's text now sits, unchanged, under another number
  (the citation has to follow it);
* **changed** — same number, different text (re-read it: the claim the
  citation makes may no longer be the rule's);
* **gone** — the number no longer exists and no rule carries its text.

Citations are read from ``engine/``, ``web/``, ``tests/``, ``scripts/`` and the
three living documents, in both spellings a citation takes: dotted (``CR
506.7c``, a marker's ``"506.7c"``) and the underscored one inside a test's
name (``test_506_7c_…``).

Advisory, stdout only, exit 0: it finds what to read and decides nothing. The
old edition is whatever the bump is replacing — ``git show
HEAD:MagicCompRules.txt > old.txt`` before the new file goes in.

``--install`` writes a download in the convention this repo's file has always
had. Wizards' text marks blank lines with a NO-BREAK SPACE and soft breaks
with U+2028 in some editions and not in others; left alone, a bump's diff is
four thousand whitespace lines with the hundred real ones somewhere inside.
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CR_PATH = REPO_ROOT / "MagicCompRules.txt"

_RULE = re.compile(r"^(\d{3}\.\d+[a-z]*)\.?\s+(.*)$")
_CITING_DIRS = ("engine", "web", "tests", "scripts")
_CITING_DOCS = ("CLAUDE.md", "ROADMAP.md", "SET_PLAYBOOK.md")
#: Generated from the citations themselves, the rules file, or this script
#: (whose docstring names rules as examples).
_NOT_A_CITER = {"RULES_PROGRESS.md", "MagicCompRules.txt", "cr_edition_diff.py"}

#: How alike two texts must be to be one rule that was edited as it moved. A
#: rule that cross-references a renumbered neighbour changes by a digit when
#: the block shifts ("…described in rule 506.7" -> "…506.8"), which is a move.
_SAME_RULE = 0.9


def normalized(raw: bytes) -> str:
    """An edition's text with one convention for blank lines and line breaks."""
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" ", "\n").replace(" ", " ")
    return "\n".join(line.rstrip() for line in text.split("\n"))


def rules_of(text: str) -> dict[str, str]:
    """``number -> text`` for every numbered rule. The table of contents
    repeats the section headings; the body comes later and wins."""
    rules: dict[str, str] = {}
    for line in text.split("\n"):
        match = _RULE.match(line.strip())
        if match:
            rules[match.group(1)] = match.group(2)
    return rules


def classify(old: dict[str, str], new: dict[str, str]) -> dict[str, tuple[str, str]]:
    """``old number -> (verdict, detail)`` for every rule that is not where and
    what it was. *detail* is the new number for ``moved``, else a similarity."""
    by_text: dict[str, list[str]] = {}
    for number, text in new.items():
        by_text.setdefault(text, []).append(number)
    verdicts: dict[str, tuple[str, str]] = {}
    for number, text in old.items():
        if new.get(number) == text:
            continue
        homes = by_text.get(text) or _edited_homes(number, text, old, new)
        if homes:
            verdicts[number] = ("moved", homes[0])
        elif number in new:
            ratio = difflib.SequenceMatcher(None, text, new[number]).ratio()
            verdicts[number] = ("changed", f"{ratio:.2f}")
        else:
            verdicts[number] = ("gone", "")
    return verdicts


def _edited_homes(number: str, text: str, old: dict[str, str], new: dict[str, str]) -> list[str]:
    """Where *text* went when it was lightly edited on the way: the most alike
    rule of the same section that the old edition did not have under that
    number with that text. Empty when the rule only changed in place."""
    section = number.split(".")[0]
    best, home = _SAME_RULE, None
    for candidate, other in new.items():
        if candidate == number or not candidate.startswith(section + "."):
            continue
        if old.get(candidate) == other or other[:24] != text[:24]:
            continue
        ratio = difflib.SequenceMatcher(None, text, other).ratio()
        if ratio > best:
            best, home = ratio, candidate
    return [home] if home else []


def citing_files() -> list[Path]:
    files = [REPO_ROOT / name for name in _CITING_DOCS]
    for directory in _CITING_DIRS:
        for suffix in ("py", "md", "js"):
            files.extend((REPO_ROOT / directory).rglob(f"*.{suffix}"))
    return [
        path for path in files
        if path.is_file() and path.name not in _NOT_A_CITER and "__pycache__" not in path.parts
    ]


def citations(numbers) -> dict[str, list[tuple[str, int]]]:
    """Every place the repo cites one of *numbers*: ``number -> [(file, line)]``."""
    ordered = sorted(numbers, key=len, reverse=True)
    if not ordered:
        return {}
    dotted = re.compile(
        r"(?<![\d.])(" + "|".join(re.escape(n) for n in ordered) + r")(?![\da-z])"
    )
    named = re.compile(
        r"(?<=test_)(" + "|".join(re.escape(n.replace(".", "_")) for n in ordered) + r")(?=_)"
    )
    found: dict[str, list[tuple[str, int]]] = {}
    for path in citing_files():
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        relative = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for pattern, restore in ((dotted, False), (named, True)):
            for match in pattern.finditer(text):
                number = match.group(1).replace("_", ".", 1) if restore else match.group(1)
                # ``506_7c`` -> ``506.7c``; only the first underscore is the dot.
                found.setdefault(number, []).append((relative, text.count("\n", 0, match.start()) + 1))
    return found


def report(old: dict[str, str], new: dict[str, str], out=print) -> int:
    verdicts = classify(old, new)
    cited = citations(verdicts)
    counts = {kind: sum(1 for verdict, _ in verdicts.values() if verdict == kind)
              for kind in ("moved", "changed", "gone")}
    out(f"{len(old)} rules -> {len(new)}: {counts['moved']} moved, "
        f"{counts['changed']} changed in place, {counts['gone']} gone; "
        f"{len(set(new) - set(old))} new numbers. {len(cited)} of them are cited here.")
    for kind, heading in (
        ("moved", "MOVED - the citation has to follow the text"),
        ("gone", "GONE - no rule carries this text any more"),
        ("changed", "CHANGED IN PLACE - re-read; the closer to 1.00, the smaller the edit"),
    ):
        rows = sorted(n for n in cited if verdicts[n][0] == kind)
        if not rows:
            continue
        out(f"\n== {heading} ==")
        for number in rows:
            detail = verdicts[number][1]
            arrow = f" -> {detail}" if kind == "moved" else (f" [{detail}]" if detail else "")
            out(f"{number}{arrow}: {old[number][:96]}")
            places: dict[str, list[int]] = {}
            for file, line in cited[number]:
                places.setdefault(file, []).append(line)
            for file, lines in sorted(places.items()):
                out(f"    {file}: {', '.join(str(line) for line in sorted(lines)[:12])}"
                    + (" …" if len(lines) > 12 else ""))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("old", nargs="?", help="the edition being replaced")
    parser.add_argument("new", nargs="?", help="the new edition (default: MagicCompRules.txt)")
    parser.add_argument("--install", metavar="DOWNLOAD",
                        help="write DOWNLOAD to MagicCompRules.txt in this repo's convention")
    args = parser.parse_args(argv)
    if args.install:
        text = normalized(Path(args.install).read_bytes())
        if not text.startswith("Magic: The Gathering Comprehensive Rules"):
            parser.error(f"{args.install} does not look like the Comprehensive Rules")
        # BOM and CRLF as the working copy has them; git normalizes the blob.
        CR_PATH.write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))
        print(f"wrote {CR_PATH.name}: {text.splitlines()[2]}")
        return 0
    if not args.old:
        parser.error("name the edition being replaced (or use --install)")
    old = rules_of(normalized(Path(args.old).read_bytes()))
    new = rules_of(normalized(Path(args.new).read_bytes() if args.new else CR_PATH.read_bytes()))
    return report(old, new)


if __name__ == "__main__":
    sys.exit(main())
