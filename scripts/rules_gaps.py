"""Report Comprehensive Rules coverage gaps and rank which rules to test next.

``scripts/rules_progress.py`` records which tracked CR rules have at least one
``@pytest.mark.cr`` citation in ``tests/rules``; this script reads the same
data and reports the *gaps*, ranked by evidence that closing a gap matters:

- **Implemented but untested.** ``engine/`` and ``web/`` cite the rules they
  implement in comments and docstrings (``CR 614.7`` style). An uncovered rule
  the source cites is live behaviour nothing verifies — the strongest signal,
  because a regression there ships silently.
- **Section momentum.** A rule in a mostly-covered section is cheap to test:
  the test file, fixtures and patterns already exist.
- **Breadth.** A rule with many subrules covers more behaviour per test.
- **Definitional text.** Rules about tournaments, sideboards, or printed-card
  physicality are deprioritized — they define terms, not game behaviour the
  engine could exhibit.

A gap with *no* engine reference and operational text can mean the behaviour
itself is unimplemented rather than merely untested — the report flags those
separately, because the next step there is engine work, not a test.

Advisory only: nothing fails and nothing is snapshotted. The ratchets stay in
``rules_progress.py --check`` and its guard test.

Usage:
    python scripts/rules_gaps.py                 # ranked report to stdout
    python scripts/rules_gaps.py --top 30        # longer recommendation list
    python scripts/rules_gaps.py --section 614   # every gap in one section
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rules_progress as rp

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = (REPO_ROOT / "engine", REPO_ROOT / "web")

# "CR 614.7c" / "CR 614.7" / bare "CR 614" in engine and web source. The
# subrule letter is captured, not discarded: a citation of a subrule that does
# not exist names a real rule at the rule level, so folding the letter in early
# is exactly what hides the error (CR 603.8 has no subrules, and "CR 603.8b"
# read as "603.8" looks perfectly valid).
CITE_RE = re.compile(r"\bCR\s+(\d{3})(?:\.(\d+)([a-z])?)?\b")

# Rule text that defines vocabulary or out-of-game process rather than
# behaviour the engine could exhibit in a game.
DEFINITIONAL_RE = re.compile(
    r"tournament|sideboard|Magic Online|silver-bordered|acorn|abbreviat|"
    r"supplementary product|physically",
    re.IGNORECASE,
)


@dataclass
class Gap:
    rule: rp.Rule
    section: rp.Section
    refs: int                 # rule-level engine/web citations (subrules fold in)
    section_covered: int
    section_total: int
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


def collect_source_citations() -> tuple[Counter, Counter, list[tuple[str, str]]]:
    """Count CR citations in engine/ and web/ source.

    Returns (rule_refs, section_refs, subrule_cites): rule-level counts keyed
    "614.7" (a subrule citation counts toward its parent rule, matching how
    rules_progress tracks coverage), bare-section counts keyed "614", and every
    subrule citation as (location, "614.7c") so the caller can check the letter
    against the CR — the rule-level fold would otherwise hide a bad one.
    """
    rule_refs: Counter = Counter()
    section_refs: Counter = Counter()
    subrule_cites: list[tuple[str, str]] = []
    for base in SOURCE_DIRS:
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            body = path.read_text(encoding="utf-8")
            for match in CITE_RE.finditer(body):
                if match.group(2):
                    rule = f"{match.group(1)}.{match.group(2)}"
                    rule_refs[rule] += 1
                    if match.group(3):
                        line = body.count(chr(10), 0, match.start()) + 1
                        subrule_cites.append((f"{rel}:{line}", rule + match.group(3)))
                else:
                    section_refs[match.group(1)] += 1
    return rule_refs, section_refs, subrule_cites


def score_gap(gap: Gap, bare_section_refs: int) -> None:
    """Fill in gap.score and gap.reasons (mutates the gap)."""
    if gap.refs:
        gap.score += 8 * min(gap.refs, 5)
        gap.reasons.append(f"cited {gap.refs}x in engine/web source")
    elif bare_section_refs:
        gap.score += min(bare_section_refs, 5)

    pct = 100 * gap.section_covered // gap.section_total
    gap.score += pct / 10
    if gap.section_covered and pct >= 50:
        gap.reasons.append(f"section already {pct}% covered")

    subrules = len(gap.rule.subrules)
    if subrules:
        gap.score += 2 * min(subrules, 5)
        if subrules >= 3:
            gap.reasons.append(f"{subrules} subrules")

    if DEFINITIONAL_RE.search(gap.rule.text):
        gap.score -= 15
        gap.reasons.append("definitional/out-of-game text")
    if gap.rule.text.startswith("See rule"):
        gap.score -= 10
        gap.reasons.append("cross-reference only")
    if not gap.refs and not bare_section_refs and gap.score > 0:
        gap.reasons.append("no engine reference - behaviour may be unimplemented")


def snippet(text: str, width: int = 72) -> str:
    return text if len(text) <= width else text[: width - 3] + "..."


def build_gaps() -> tuple[list[Gap], dict, Counter, Counter, list, int, int]:
    sections, _ = rp.parse_comprehensive_rules(rp.CR_PATH)
    tests = rp.collect_tests(rp.TESTS_DIR)
    coverage, _, _, _ = rp.map_citations(sections, tests)
    rule_refs, section_refs, subrule_cites = collect_source_citations()

    gaps: list[Gap] = []
    total = covered_total = 0
    for number in sorted(sections, key=int):
        section = sections[number]
        rules = rp.tracked_rules(section)
        if not rules:
            continue
        covered = sum(1 for r in rules if r.number in coverage)
        total += len(rules)
        covered_total += covered
        for rule in rules:
            if rule.number in coverage:
                continue
            gap = Gap(rule, section, rule_refs.get(rule.number, 0), covered, len(rules))
            score_gap(gap, section_refs.get(number, 0))
            gaps.append(gap)
    gaps.sort(key=lambda g: (-g.score, tuple(int(p) for p in g.rule.number.split("."))))
    return gaps, sections, rule_refs, section_refs, subrule_cites, covered_total, total


def print_report(top: int, section_filter: str | None) -> None:
    (gaps, sections, rule_refs, section_refs, subrule_cites,
     covered_total, total) = build_gaps()
    out = print

    out(f"Comprehensive Rules coverage gaps - {len(gaps)} of {total} tracked "
        f"rules untested ({100 * covered_total // total}% covered).")
    out("Signals: engine/web source citations, section momentum, subrule "
        "breadth; see the script docstring.")
    out("")

    if section_filter:
        chosen = [g for g in gaps if g.section.number == section_filter]
        if not chosen:
            section = sections.get(section_filter)
            title = f" ({section.title})" if section else ""
            out(f"No gaps in section {section_filter}{title} - "
                "fully covered, or not in rules_progress.SCOPE.")
            return
        out(f"== Gaps in {section_filter}. {chosen[0].section.title} "
            f"({chosen[0].section_covered}/{chosen[0].section_total} covered) ==")
        for gap in chosen:
            refs = f"{gap.refs} refs" if gap.refs else "no refs"
            out(f"  {gap.rule.number:<8} {refs:>8}  {snippet(gap.rule.text)}")
        return

    implemented = sorted(
        (g for g in gaps if g.refs),
        key=lambda g: (-g.refs, tuple(int(p) for p in g.rule.number.split("."))),
    )
    out("== Implemented but untested (engine/web cites the rule; no test does) ==")
    for gap in implemented[:20]:
        out(f"  {gap.rule.number:<8} {gap.refs:>2} refs  "
            f"[{gap.section.number} {gap.section.title}, "
            f"{gap.section_covered}/{gap.section_total}]  {snippet(gap.rule.text, 60)}")
    if len(implemented) > 20:
        out(f"  ... and {len(implemented) - 20} more")
    out("")

    nearly = sorted(
        {(g.section.number, g.section.title, g.section_covered, g.section_total)
         for g in gaps if 60 <= 100 * g.section_covered // g.section_total < 100},
        key=lambda s: -(100 * s[2] // s[3]),
    )
    out("== Nearly-complete sections (cheapest to finish) ==")
    for number, title, covered, sec_total in nearly:
        missing = ", ".join(g.rule.number for g in gaps if g.section.number == number)
        out(f"  {number} {title} ({covered}/{sec_total}) - missing {missing}")
    out("")

    untouched = sorted(
        {(g.section.number, g.section.title, g.section_total) for g in gaps
         if g.section_covered == 0},
        key=lambda s: int(s[0]),
    )
    out("== Untouched sections (no rule covered) ==")
    for number, title, sec_total in untouched:
        refs = sum(rule_refs.get(g.rule.number, 0) for g in gaps
                   if g.section.number == number) + section_refs.get(number, 0)
        hint = f"{refs} engine refs" if refs else "no engine refs"
        out(f"  {number} {title} - {sec_total} rules, {hint}")
    out("")

    out(f"== Top {top} recommended next rules ==")
    for rank, gap in enumerate(gaps[:top], start=1):
        why = "; ".join(gap.reasons) if gap.reasons else "low signal"
        out(f"  {rank:>2}. {gap.rule.number:<8} ({gap.section.title}, score "
            f"{gap.score:.0f}) - {why}")
        out(f"      {snippet(gap.rule.text)}")
    out("")

    tracked = {r.number for s in sections.values() for r in rp.tracked_rules(s)}
    known = {r.number for s in sections.values() for r in s.rules.values()}
    outside = [(num, cnt) for num, cnt in rule_refs.most_common()
               if num in known and num not in tracked]
    if outside:
        out("== Engine cites outside tracked scope (consider widening SCOPE) ==")
        for num, cnt in outside[:10]:
            out(f"  {num:<8} {cnt:>2} refs  {sections[num.split('.', 1)[0]].title}")
        out("")
    phantom = [(num, cnt) for num, cnt in rule_refs.most_common() if num not in known]
    if phantom:
        out("== Engine cites rule numbers not in MagicCompRules.txt (stale comments?) ==")
        for num, cnt in phantom:
            out(f"  {num:<8} {cnt:>2} refs")
        out("")

    bad_subrules = []
    for location, citation in subrule_cites:
        rule, letter = citation[:-1], citation[-1]
        section = sections.get(rule.split(".", 1)[0])
        if section is None or rule not in section.rules:
            continue  # already reported as a phantom rule
        if letter not in section.rules[rule].subrules:
            bad_subrules.append((location, citation, rule, letter))
    if bad_subrules:
        out("== Engine cites subrules that do not exist (though the rule does) ==")
        for location, citation, rule, letter in bad_subrules:
            out(f"  {citation:<10} {location}  ({rule} has no subrule {letter!r})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=20,
                        help="length of the ranked recommendation list (default 20)")
    parser.add_argument("--section", metavar="NNN",
                        help="list every gap in one section instead of the full report")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print_report(args.top, args.section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
