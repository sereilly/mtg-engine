"""Generate RULES_PROGRESS.md — Comprehensive Rules test-coverage tracker.

Every test in ``tests/rules`` carries one or more ``@pytest.mark.cr("508.1a")``
markers citing the Comprehensive Rules it verifies (marker registered in
``pytest.ini``). This script parses ``MagicCompRules.txt``, collects those
citations by AST-walking the test files (no pytest run needed), and renders a
per-section coverage report: which numbered rules have at least one test and
which are still uncovered.

Coverage is tracked at the numbered-rule level (``508.1``); a citation of a
subrule (``508.1a``) counts toward its parent rule. Only the sections/rules in
``SCOPE`` below are tracked — the engine grew up on Alpha-era Magic, so rules
for stickers, modern keywords, etc. are deliberately out of scope (edit
``SCOPE`` as the engine grows; 306 Planeswalkers joined with the M21 measured
set's loyalty work). Citations of real rules outside the
scope are listed in an appendix rather than dropped; citations of rule numbers
that don't exist in the CR file are reported as errors.

Usage:
    python scripts/rules_progress.py            # rewrite RULES_PROGRESS.md
    python scripts/rules_progress.py --check    # exit 1 on unannotated tests
                                                # or unknown citations
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CR_PATH = REPO_ROOT / "MagicCompRules.txt"
TESTS_DIR = REPO_ROOT / "tests" / "rules"
OUTPUT_PATH = REPO_ROOT / "RULES_PROGRESS.md"

# Sections tracked by the report. "all" tracks every numbered rule in the
# section; a tuple tracks only the listed rules (used for the keyword
# catalogs, where most entries are for sets far beyond this engine's pool).
SCOPE: dict[str, str | tuple[str, ...]] = {
    # 1xx — Game Concepts (123 Stickers excluded). 114 Emblems joined with
    # M21's planeswalkers: Liliana, Waker of the Dead and Garruk, Unleashed
    # both print "You get an emblem with …", and engine/handlers/board_misc.py
    # creates one.
    **{s: "all" for s in (
        "100", "101", "102", "103", "104", "105", "106", "107", "108", "109",
        "110", "111", "112", "113", "114", "115", "116", "117", "118", "119",
        "120", "121", "122",
    )},
    # 2xx — Parts of a Card (only the parts Alpha-era cards have)
    **{s: "all" for s in ("200", "201", "202", "205", "207", "208")},
    # 3xx — Card Types present in the pool (306 Planeswalkers joined with the
    # M21 measured set's loyalty work)
    **{s: "all" for s in ("300", "301", "302", "303", "304", "305", "306", "307")},
    # 4xx — Zones. 407 Ante and 408 Command are both implemented as opt-in game
    # variations (CR 407, CR 903), so both zones are tracked.
    **{s: "all" for s in (
        "400", "401", "402", "403", "404", "405", "406", "407", "408",
    )},
    # 5xx — Turn Structure
    **{s: "all" for s in (
        "500", "501", "502", "503", "504", "505", "506", "507", "508", "509",
        "510", "511", "512", "513", "514",
    )},
    # 6xx — Spells, Abilities, and Effects
    **{s: "all" for s in (
        "600", "601", "602", "603", "604", "605", "606", "607", "608", "609",
        "610", "611", "612", "613", "614", "615", "616",
    )},
    # 7xx — Additional Rules
    "700": "all",
    "701": (  # keyword actions Alpha/ARN-era cards perform
        "701.2",   # Activate
        "701.3",   # Attach
        "701.5",   # Cast
        "701.6",   # Counter
        "701.7",   # Create
        "701.8",   # Destroy
        "701.9",   # Discard
        "701.12",  # Exchange
        "701.13",  # Exile
        "701.14",  # Fight (M21: Brash Taunter, Primal Might)
        "701.17",  # Mill (M21: Carrion Grub, Teferi's Tutelage)
        "701.18",  # Play
        "701.19",  # Regenerate
        "701.20",  # Reveal
        "701.21",  # Sacrifice
        "701.22",  # Scry
        "701.23",  # Search
        "701.24",  # Shuffle
        "701.26",  # Tap and Untap
    ),
    "702": (  # keyword abilities the engine implements (pool + evergreens)
        "702.1",   # General
        "702.2",   # Deathtouch
        "702.5",   # Enchant (every Aura's attachment restriction)
        "702.6",   # Equip (M21: Short Sword, Malefic Scythe)
        "702.3",   # Defender
        "702.4",   # Double Strike
        "702.7",   # First Strike
        "702.8",   # Flash
        "702.9",   # Flying
        "702.10",  # Haste
        "702.11",  # Hexproof
        "702.12",  # Indestructible
        "702.14",  # Landwalk
        "702.15",  # Lifelink
        "702.16",  # Protection
        "702.17",  # Reach
        "702.18",  # Shroud
        "702.19",  # Trample
        "702.20",  # Vigilance
        "702.22",  # Banding
        "702.26",  # Phasing (M21: Teferi, Master of Time)
        "702.23",  # Rampage
        "702.24",  # Cumulative upkeep (ICE: 24 cards)
        "702.25",  # Flanking
        "702.36",  # Fear
        "702.108", # Prowess
        "702.111", # Menace
    ),
    "703": "all",  # Turn-Based Actions
    "704": "all",  # State-Based Actions
    "705": "all",  # Flipping a Coin (ARN: Bottle of Suleiman, ...)
    "707": "all",  # Copying Objects (LEA: Vesuvan Doppelganger, ...)
    # Ending Turns and Phases. Joined the scope with round 110's
    # "End the turn." (M21: Discontinuity); 724.2's end-the-*phase*
    # half has no card in the pool and shows as untested, which is the
    # honest reading rather than a section trimmed to what passes.
    "724": "all",
    # 8xx — Multiplayer rules the web app's free_for_all mode uses
    "800": "all",
    "802": "all",  # Attack Multiple Players Option
    "806": "all",  # Free-for-All Variant
    # 9xx — Casual variants the engine implements. 903 Commander (with 903.12's
    # Brawl option) joined with engine/commander.py.
    "903": "all",
}

# Rules inside a tracked section whose *mechanic* the engine does not have, each
# a pointer to a subsystem that does not exist here. Listed rather than dropped:
# they are reported in an appendix and left out of the denominator, because a
# permanently-unreachable rule counted as "uncovered" is a target nobody can
# ever close. This is deliberately NOT the same as a rule the engine implements
# that no card in the pool exercises (CR 724.2's end-the-phase half, CR 705.3's
# "an effect may state a coin flip's result") — those stay in the denominator
# and show as untested, which is the honest reading.
EXCLUDED: dict[str, str] = {
    "104.6": "restarting the game (CR 727) — Karn Liberated is not in the pool",
    "117.6": "shared team turns option (CR 805) — the engine has no teams",
    "903.13": "Commander Draft — a draft variant, no in-game behaviour",
}

SECTION_RE = re.compile(r"^(\d{3})\.\s+(.+?)\s*$")
# The period after the rule number is optional: the April 17, 2026 CR file
# prints "606.5 If the total cost..." with no period, and requiring one
# silently dropped that rule from the report.
RULE_RE = re.compile(r"^(\d{3}\.\d+)\.?\s+(.+)$")
SUBRULE_RE = re.compile(r"^(\d{3}\.\d+)([a-z])\s+.+$")
CITATION_RE = re.compile(r"^(\d{3}\.\d+)([a-z])?$|^(\d{3})$")
EFFECTIVE_RE = re.compile(r"effective as of (.+?)\.")


@dataclass
class Rule:
    number: str          # "508.1"
    text: str            # first line of the rule's text
    subrules: list[str] = field(default_factory=list)  # ["a", "b", ...]


@dataclass
class Section:
    number: str          # "508"
    title: str           # "Declare Attackers Step"
    rules: dict[str, Rule] = field(default_factory=dict)


@dataclass
class TestInfo:
    node: str            # "tests/rules/test_x.py::test_y"
    citations: tuple[str, ...]


def parse_comprehensive_rules(path: Path) -> tuple[dict[str, Section], str]:
    """Return ({section number: Section}, edition date string)."""
    sections: dict[str, Section] = {}
    edition = "unknown edition"
    with path.open(encoding="utf-8-sig") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if edition == "unknown edition":
                found = EFFECTIVE_RE.search(line)
                if found:
                    edition = found.group(1)
            if line == "Glossary" and any(s.rules for s in sections.values()):
                break  # body ends (the TOC also has a bare "Glossary" line)
            section_match = SECTION_RE.match(line)
            if section_match and not RULE_RE.match(line):
                number, title = section_match.groups()
                sections.setdefault(number, Section(number, title))
                continue
            rule_match = RULE_RE.match(line)
            if rule_match:
                number, text = rule_match.groups()
                section = sections.get(number.split(".", 1)[0])
                if section is not None and number not in section.rules:
                    section.rules[number] = Rule(number, text)
                continue
            subrule_match = SUBRULE_RE.match(line)
            if subrule_match:
                parent, letter = subrule_match.groups()
                section = sections.get(parent.split(".", 1)[0])
                if section is not None and parent in section.rules:
                    subrules = section.rules[parent].subrules
                    if letter not in subrules:
                        subrules.append(letter)
    return sections, edition


def _mark_citations(node: ast.expr) -> tuple[str, ...] | None:
    """Return citation strings if *node* is a pytest.mark.cr(...) call."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "cr"):
        return None
    value = func.value
    if not (isinstance(value, ast.Attribute) and value.attr == "mark"):
        return None
    return tuple(
        arg.value for arg in node.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    )


_NEVER_RUNS = ("skip", "xfail")


def _never_runs(decorator: ast.expr) -> bool:
    """Whether *decorator* is an unconditional ``pytest.mark.skip`` / ``xfail``.

    A test that cannot pass verifies nothing, so its ``cr`` marker must not
    credit the rule: three ``...``-bodied stubs carried 702.16h/j/k for months
    and an ``xfail`` that said "not implemented" sat on a rule the engine had
    long since implemented and tested elsewhere. ``skipif`` is conditional — the
    test runs when its condition is false — and is left alone.
    """
    node = decorator.func if isinstance(decorator, ast.Call) else decorator
    return (
        isinstance(node, ast.Attribute)
        and node.attr in _NEVER_RUNS
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
    )


def collect_tests(tests_dir: Path) -> list[TestInfo]:
    """AST-walk tests/rules and return every test with its cr citations.

    A test decorated with an unconditional ``skip`` or ``xfail`` is left out
    entirely — it neither credits a rule nor counts as unannotated."""
    tests: list[TestInfo] = []
    for path in sorted(tests_dir.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(REPO_ROOT).as_posix()

        module_marks: list[str] = []
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
            ):
                values = stmt.value.elts if isinstance(stmt.value, (ast.List, ast.Tuple)) else [stmt.value]
                for value in values:
                    module_marks.extend(_mark_citations(value) or ())

        def visit(body: list[ast.stmt], prefix: str) -> None:
            for stmt in body:
                if isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test"):
                    visit(stmt.body, f"{prefix}{stmt.name}::")
                elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name.startswith("test_"):
                    if any(_never_runs(d) for d in stmt.decorator_list):
                        continue
                    citations = list(module_marks)
                    for decorator in stmt.decorator_list:
                        citations.extend(_mark_citations(decorator) or ())
                    tests.append(TestInfo(f"{prefix}{stmt.name}", tuple(citations)))

        visit(tree.body, f"{rel}::")
    return tests


def tracked_rules(section: Section) -> list[Rule]:
    scope = SCOPE.get(section.number)
    if scope == "all":
        rules = list(section.rules.values())
    elif scope is None:
        return []
    else:
        rules = [section.rules[num] for num in scope if num in section.rules]
    return [rule for rule in rules if rule.number not in EXCLUDED]


def map_citations(
    sections: dict[str, Section], tests: list[TestInfo]
) -> tuple[dict[str, list[str]], dict[str, set[str]], list[str], list[str]]:
    """Map test citations onto numbered rules.

    Returns ``(coverage, subrule_hits, unannotated, unknown)``: which tests
    cover each rule, which subrule letters were cited, tests carrying no
    citation, and citations of rules that don't exist in the CR file.
    """
    all_rules = {rule.number for section in sections.values() for rule in section.rules.values()}

    # citation -> rule number it covers; collect problems along the way
    coverage: dict[str, list[str]] = {}          # rule number -> test nodes
    subrule_hits: dict[str, set[str]] = {}       # rule number -> cited letters
    unknown: list[str] = []
    unannotated = [t.node for t in tests if not t.citations]
    for test in tests:
        for citation in test.citations:
            match = CITATION_RE.match(citation)
            rule_num = None
            if match:
                if match.group(3):               # bare section like "506"
                    unknown.append(f"{test.node} cites {citation} (cite a numbered rule, e.g. {citation}.1)")
                    continue
                if match.group(1) in all_rules:
                    rule_num = match.group(1)
                    if match.group(2):
                        section = sections[rule_num.split(".", 1)[0]]
                        if match.group(2) not in section.rules[rule_num].subrules:
                            unknown.append(f"{test.node} cites {citation} (no such subrule)")
                        else:
                            subrule_hits.setdefault(rule_num, set()).add(match.group(2))
            if rule_num is None:
                unknown.append(f"{test.node} cites {citation} (no such rule)")
            else:
                coverage.setdefault(rule_num, []).append(test.node)
    return coverage, subrule_hits, unannotated, unknown


def build_report(
    sections: dict[str, Section], tests: list[TestInfo], edition: str
) -> tuple[str, list[str], list[str]]:
    """Return (markdown, unannotated test nodes, unknown citations)."""
    coverage, subrule_hits, unannotated, unknown = map_citations(sections, tests)

    lines: list[str] = []
    out = lines.append
    out("# Comprehensive Rules Test Coverage")
    out("")
    out(f"Coverage of `tests/rules/` against the Comprehensive Rules ({edition}).")
    out("Tests cite rules with `@pytest.mark.cr(...)`; regenerate this file with")
    out("`python scripts/rules_progress.py`. Tracked scope is defined in that")
    out("script — rules for mechanics outside the Alpha-era pool are omitted.")
    out("")

    total_rules = total_covered = 0
    summary_rows: list[str] = []
    detail_blocks: list[str] = []
    for number in sorted(sections, key=int):
        section = sections[number]
        rules = tracked_rules(section)
        if not rules:
            continue
        covered = [r for r in rules if r.number in coverage]
        uncovered = [r for r in rules if r.number not in coverage]
        total_rules += len(rules)
        total_covered += len(covered)
        pct = f"{100 * len(covered) // len(rules)}%"
        anchor = f"{number}-{section.title.lower().replace(' ', '-').replace('/', '').replace(',', '')}"
        summary_rows.append(
            f"| [{number}. {section.title}](#{anchor}) | {len(covered)}/{len(rules)} | {pct} |"
        )

        block: list[str] = [f"### {number}. {section.title}", ""]
        for rule in sorted(rules, key=lambda r: int(r.number.split(".")[1])):
            tests_for_rule = coverage.get(rule.number, [])
            snippet = rule.text if len(rule.text) <= 100 else rule.text[:97] + "..."
            if tests_for_rule:
                letters = "".join(sorted(subrule_hits.get(rule.number, ())))
                cited = f", subrules {letters}" if letters else ""
                block.append(f"- [x] **{rule.number}** {snippet} *({len(tests_for_rule)} tests{cited})*")
            else:
                block.append(f"- [ ] **{rule.number}** {snippet}")
        block.append("")
        detail_blocks.append("\n".join(block))

    pct_total = f"{100 * total_covered // total_rules}%" if total_rules else "n/a"
    out(f"**{total_covered} / {total_rules} tracked rules covered ({pct_total})** — "
        f"{len(tests)} tests, {len(unannotated)} unannotated.")
    out("")
    out("| Section | Covered | % |")
    out("| --- | --- | --- |")
    lines.extend(summary_rows)
    out("")
    out("## Rule detail")
    out("")
    lines.extend(detail_blocks)

    if unannotated:
        out("## Unannotated tests (add a `@pytest.mark.cr` citation)")
        out("")
        lines.extend(f"- `{node}`" for node in unannotated)
        out("")
    if unknown:
        out("## Bad citations (rule number not in MagicCompRules.txt)")
        out("")
        lines.extend(f"- {entry}" for entry in unknown)
        out("")

    if EXCLUDED:
        out("## Excluded from the denominator (mechanic not in this engine)")
        out("")
        out("Listed rather than dropped — see `EXCLUDED` in "
            "`scripts/rules_progress.py`. A rule the engine *does* implement "
            "that no card exercises is not here; it stays above, untested.")
        out("")
        for number, reason in sorted(
            EXCLUDED.items(), key=lambda kv: tuple(int(p) for p in kv[0].split("."))
        ):
            section = sections.get(number.split(".", 1)[0])
            title = f"{section.title}: " if section else ""
            lines.append(f"- **{number}** {title}{reason}")
        out("")

    # Citations that are real rules but fall outside the tracked scope.
    tracked = {r.number for s in sections.values() for r in tracked_rules(s)}
    outside = sorted(
        {num for num in coverage if num not in tracked},
        key=lambda n: tuple(int(p) for p in n.split(".")),
    )
    if outside:
        out("## Cited outside tracked scope (consider widening SCOPE)")
        out("")
        lines.extend(
            f"- **{num}** {sections[num.split('.', 1)[0]].title} ({len(coverage[num])} tests)"
            for num in outside
        )
        out("")

    return "\n".join(lines).rstrip() + "\n", unannotated, unknown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any test lacks a cr marker or cites a nonexistent rule")
    args = parser.parse_args(argv)

    sections, edition = parse_comprehensive_rules(CR_PATH)
    tests = collect_tests(TESTS_DIR)
    report, unannotated, unknown = build_report(sections, tests, edition)
    if args.check:
        # A check reads; it does not write. Every other tracker's --check
        # returns before touching its file, and SET_PLAYBOOK Phase 0 runs all of
        # them on a tree that has to stay clean — this one used to rewrite
        # RULES_PROGRESS.md on the way to its verdict.
        print(f"{len(tests)} tests, {len(unannotated)} unannotated, "
              f"{len(unknown)} bad citations.")
        if unannotated or unknown:
            for node in unannotated:
                print(f"UNANNOTATED: {node}", file=sys.stderr)
            for entry in unknown:
                print(f"BAD CITATION: {entry}", file=sys.stderr)
            return 1
        return 0
    OUTPUT_PATH.write_text(report, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.name}: {len(tests)} tests, "
          f"{len(unannotated)} unannotated, {len(unknown)} bad citations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
