"""Generate GRAMMAR_COVERAGE.md — how much of the pool the parser reads.

``engine/grammar/`` is the parser. This measures its reach over the printed
lines in the pool, in three nested measures per set:

- **parsed** — the grammar consumed every token of the line and produced an AST.
- **lowered** — that AST mapped onto instructions, *or* onto a sidecar registry
  that already runs the line off the card's raw text
  (``engine/grammar/registries.py``), *or* onto a keyword line.
- **executed** — the line produced instructions whose categories are switched on
  in ``GRAMMAR_CATEGORIES``, so the engine dispatches the grammar's output.

``executed <= lowered <= parsed`` always. The gap between *lowered* and
*executed* is mostly the registry and keyword lines, which are accounted for
without an instruction to dispatch.

**What this ratchet means now that there is one parser.** It was a migration
measure — "how much has the grammar taken over from ``engine/parsing/``" — and
that question was answered when the registry was deleted. What it measures
today is the division of labour between the *general* reader and the
special-case ones: the name-keyed hooks in ``engine/card_hooks.py`` and the
text-keyed sidecar tables. A line the grammar parses is one every card printed
the same way gets for free; a line it refuses is one that needed a hook, or an
unsupported card. So a **fall** in these numbers means the pool became more
special-cased than it was — either a production regressed, or a card was
supported by writing its name down instead of by reading its text. That is
worth failing on, and it is the same direction the migration ratchet pointed.

The floors live in ``scripts/grammar_ratchet.json`` and
``tests/engine/test_grammar_ratchet.py`` fails if any of them drops. Raise them
with ``--accept`` after reviewing the diff.

Usage::

    python scripts/grammar_coverage.py            # regenerate the report
    python scripts/grammar_coverage.py --check    # fail if any measure regressed
    python scripts/grammar_coverage.py --accept   # re-snapshot the floors
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.card_loader import load_cards, manifest_measured_codes, manifest_set_paths
from engine.grammar import GRAMMAR_CATEGORIES, compile_line

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "GRAMMAR_COVERAGE.md"
RATCHET_PATH = REPO_ROOT / "scripts" / "grammar_ratchet.json"

# Failure reasons that are expected and not worth chasing: these name whole
# feature areas the roadmap schedules later, so they would otherwise dominate
# the backlog listing and hide the actionable entries.
#
# Keep this honest. Everything static used to be labelled "phase 6", and when
# that claim was finally checked *none* of it was waiting on the layers engine:
# the Aura grants were already derived at layers 6 and 7c, the anthems already
# had a continuous consumer, and the rest belonged to sidecar tables. A schedule
# entry against the wrong phase is worse than none — it makes work look blocked
# that nobody is blocked on, and it hides the real owner.
_ROADMAPPED_REASONS = {
    "static abilities need the CR 613 layers engine": "phase 6 (CR 613 layers)",
    "granted ability in quotes": "phase 3 (quoted abilities)",
    "continuous pump needs the CR 613 layers engine": "phase 6 (CR 613 layers)",
    "continuous keyword grant needs the CR 613 layers engine": "phase 6 (CR 613 layers)",
    # The lord-buff entries that stood here are gone, not rescheduled:
    # engine/lord_buffs.py is that derivation table, and both front ends lower
    # through it. A scheduled reason retires when the code lands, in the same
    # commit — an entry naming work that is done is the stale-comment failure
    # this dict's own docstring warns about.
    #
    # "modal line" went the same way. `engine/grammar/effects/stack.py` reads
    # the head ("Choose one —", with or without an activation cost or a trigger
    # in front of it) and `engine/oracle.py` groups it with the bullets below
    # it, so the reason no longer exists to be scheduled. What is left of it in
    # the backlog is honest: a count the engine cannot carry out refuses at
    # *lowering*, and says so.
}


class Stats:
    __slots__ = ("lines", "parsed", "lowered", "executed", "cards", "cards_executed")

    def __init__(self) -> None:
        self.lines = 0
        self.parsed = 0
        self.lowered = 0
        self.executed = 0
        self.cards = 0
        self.cards_executed = 0

    def pct(self, value: int) -> float:
        return 0.0 if not self.lines else round(100.0 * value / self.lines, 1)

    def as_dict(self) -> dict[str, float]:
        return {
            "parsed_pct": self.pct(self.parsed),
            "lowered_pct": self.pct(self.lowered),
            "executed_pct": self.pct(self.executed),
        }


def analyze() -> tuple[dict[str, Stats], Stats, collections.Counter, list[tuple[str, str]], dict, set[str]]:
    per_set: dict[str, Stats] = {}
    overall = Stats()
    reasons: collections.Counter = collections.Counter()
    distinct_texts: dict[str, set[str]] = {}
    executed_lines: list[tuple[str, str]] = []
    measured_codes: set[str] = set(manifest_measured_codes())

    # Measured sets are reported and not ratcheted, and they stay out of
    # `overall` as well. The floors here answer "is the parser losing ground",
    # and an aggregate that moves when an unimplemented set is ingested answers
    # a different question with the same number: ingesting M21 dropped ALL from
    # 77.2% to 70.7% parsed without a single production changing. A floor that
    # fires on pool composition is a floor that gets lowered without being read.
    for path in manifest_set_paths(include_measured=True):
        if not path.exists():
            continue
        code = path.stem.replace("_cards", "")
        shipped = code not in measured_codes
        stats = Stats()
        per_set[code] = stats
        for card in load_cards(str(path)):
            stats.cards += 1
            if shipped:
                overall.cards += 1
            card_executed = False
            for raw in (card.oracle_text or "").splitlines():
                line = raw.strip()
                if not line:
                    continue
                result = compile_line(line, card_name=card.name)
                if result.blank:
                    # Reminder-text-only line: no rules text to account for, so
                    # counting it either way would distort the percentages.
                    continue
                stats.lines += 1
                if shipped:
                    overall.lines += 1
                if result.parsed:
                    stats.parsed += 1
                    if shipped:
                        overall.parsed += 1
                if result.lowered:
                    stats.lowered += 1
                    if shipped:
                        overall.lowered += 1
                if result.usable:
                    stats.executed += 1
                    if shipped:
                        overall.executed += 1
                    card_executed = True
                    executed_lines.append((card.name, line))
                if result.failure_reason:
                    reasons[result.failure_reason] += 1
                    # Also track the distinct *texts* behind each reason. A
                    # reason covering 30 lines that are 30 different sentences
                    # needs 30 productions; one covering 30 copies of the same
                    # sentence needs one. The line count alone cannot tell
                    # those apart, and reprint sets multiply it by the number
                    # of printings.
                    distinct_texts.setdefault(result.failure_reason, set()).add(
                        " ".join(line.split()).lower()
                    )
            if card_executed:
                stats.cards_executed += 1
                if shipped:
                    overall.cards_executed += 1

    return per_set, overall, reasons, executed_lines, distinct_texts, measured_codes


def render(
    per_set: dict[str, Stats],
    overall: Stats,
    reasons: collections.Counter,
    executed_lines: list[tuple[str, str]],
    distinct_texts: dict[str, set[str]],
    measured_codes: set[str] = frozenset(),
) -> str:
    lines: list[str] = []
    add = lines.append

    add("# Grammar Coverage")
    add("")
    add(
        "How much of the card pool the oracle-text parser (`engine/grammar/`) "
        "reads. It is the engine's only parser; a line it refuses is one that "
        "needed a name-keyed hook, a text-keyed sidecar table, or that leaves "
        "its card unsupported — so these numbers are the division of labour "
        "between the general reader and the special-case ones, and they are "
        "ratcheted so it cannot shift towards the special cases."
    )
    add("")
    add("**Generated** — run `python scripts/grammar_coverage.py` to refresh.")
    add("")
    add("| Measure | Meaning |")
    add("| --- | --- |")
    add("| Parsed | Grammar consumed every token of the line and built an AST |")
    add("| Lowered | That AST mapped onto instructions, a sidecar registry, or a keyword line |")
    add("| Executed | Instructions' categories are switched on, so the grammar's output runs |")
    add("")
    add(
        f"Categories currently switched on: "
        f"`{', '.join(sorted(GRAMMAR_CATEGORIES))}`."
    )
    add("")
    add("## Coverage by set")
    add("")
    add("| Set | Cards | Lines | Parsed | Lowered | Executed | Cards executing |")
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for code, stats in per_set.items():
        label = f"{code} *(measured)*" if code in measured_codes else code
        add(
            f"| {label} | {stats.cards} | {stats.lines} | "
            f"{stats.pct(stats.parsed)}% | {stats.pct(stats.lowered)}% | "
            f"{stats.pct(stats.executed)}% | {stats.cards_executed} |"
        )
    add(
        f"| **All (shipped)** | **{overall.cards}** | **{overall.lines}** | "
        f"**{overall.pct(overall.parsed)}%** | **{overall.pct(overall.lowered)}%** | "
        f"**{overall.pct(overall.executed)}%** | **{overall.cards_executed}** |"
    )
    add("")
    add(
        "**The All row is printing-weighted, not deduped** — it sums the rows "
        "above, so a card printed in five sets is counted five times and the "
        "aggregate is a weighted average of the rows rather than a measure of "
        "the unique pool. `HOOK_RELIANCE.md`'s ALL row is the other choice "
        "(deduped, one entry per card); both are defensible and they answer "
        "different questions, so do not read one against the other. What makes "
        "the difference visible is a reprint set: promoting 4ED — 368 cards, "
        "every one of them already in the pool — moved this row from 2047 cards "
        "and 85.2% parsed to 2415 and 85.7% while hook reliance's ALL row did "
        "not move at all. **That 0.5pp was composition, not a production.** The "
        "floors are re-accepted at every promotion, so this is not a hole in the "
        "ratchet; it is a reason to read a promotion's diff as a change of "
        "membership before reading it as progress."
    )
    add("")
    if measured_codes:
        add(
            f"*(measured)* — {', '.join(sorted(measured_codes))} are ingested for "
            "measurement and **not shipped** (`measured` in "
            "`cards/manifest.json`): the engine's catalog does not load them and "
            "no player can put one in a deck. They are reported here and left "
            "out of the **All** row and the floors, because these floors ask "
            "*is the parser losing ground* — and an aggregate that moves when an "
            "unimplemented set is ingested answers a different question with the "
            "same number. Ingesting M21 would have dropped All from 77.2% to "
            "70.7% parsed without a single production changing, and a floor that "
            "fails on pool composition is a floor that gets lowered without "
            "being read."
        )
        add("")

    add("## Backlog — failure reasons")
    add("")
    add(
        "**Lines** counts every failing line, so a card in four sets counts "
        "four times. **Distinct** counts the different sentences behind the "
        "reason, which is the number that predicts work: a reason covering 30 "
        "copies of one sentence needs one production, and a reason covering 30 "
        "different sentences needs something closer to 30. Sort by the ratio, "
        "not by the first column — a reason whose two columns are nearly equal "
        "is a long tail, not a missing production."
    )
    add("")
    add("| Lines | Distinct | Reason | Scheduled |")
    add("| ---: | ---: | --- | --- |")
    for reason, count in reasons.most_common(25):
        scheduled = _ROADMAPPED_REASONS.get(reason, "")
        distinct = len(distinct_texts.get(reason, ()))
        add(f"| {count} | {distinct} | {reason} | {scheduled} |")
    add("")

    add("## Cards executing through the grammar")
    add("")
    add(f"{overall.cards_executed} cards, {overall.executed} lines.")
    add("")
    by_card: dict[str, list[str]] = {}
    for name, line in executed_lines:
        by_card.setdefault(name, []).append(line)
    for name in sorted(by_card):
        add(f"- **{name}**")
        for line in by_card[name]:
            add(f"  - `{line}`")
    add("")
    return "\n".join(lines)


def _measures(
    per_set: dict[str, Stats],
    overall: Stats,
    measured_codes: set[str] = frozenset(),
) -> dict[str, dict[str, float]]:
    """What the ratchet compares — **shipped scopes only**.

    A measured set is reported and not ratcheted: its numbers describe a set
    nobody has implemented yet, so a floor over them would fail on the day it
    was ingested and stay failing until the work was done.
    """
    measures = {
        code: stats.as_dict()
        for code, stats in per_set.items()
        if code not in measured_codes
    }
    measures["ALL"] = overall.as_dict()
    return measures


def check(measures: dict[str, dict[str, float]]) -> list[str]:
    """Compare current measures against the committed floors."""
    if not RATCHET_PATH.exists():
        return [f"missing ratchet baseline: {RATCHET_PATH}"]
    baseline = json.loads(RATCHET_PATH.read_text(encoding="utf-8"))
    failures: list[str] = []
    for scope, floors in baseline.get("floors", {}).items():
        current = measures.get(scope)
        if current is None:
            failures.append(f"{scope}: no longer measured (was in the ratchet)")
            continue
        for measure, floor in floors.items():
            value = current.get(measure, 0.0)
            if value < floor:
                failures.append(
                    f"{scope}.{measure} regressed: {value}% < floor {floor}%"
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if any measure regressed")
    parser.add_argument("--accept", action="store_true", help="re-snapshot the ratchet floors")
    args = parser.parse_args()

    per_set, overall, reasons, executed_lines, distinct_texts, measured_codes = analyze()
    measures = _measures(per_set, overall, measured_codes)

    if args.check:
        failures = check(measures)
        if failures:
            print("FAIL: grammar coverage regressed")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        rendered = render(
            per_set, overall, reasons, executed_lines, distinct_texts, measured_codes
        )
        if OUTPUT_PATH.read_text(encoding="utf-8") != rendered:
            print(f"FAIL: {OUTPUT_PATH.name} is stale — rerun the script and commit the result")
            return 1
        print(
            f"OK: grammar parses {measures['ALL']['parsed_pct']}% of lines, "
            f"executes {measures['ALL']['executed_pct']}%"
        )
        return 0

    if args.accept:
        RATCHET_PATH.write_text(
            json.dumps({"floors": measures}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote ratchet floors to {RATCHET_PATH}")

    OUTPUT_PATH.write_text(
        render(per_set, overall, reasons, executed_lines, distinct_texts, measured_codes),
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT_PATH}")
    print(
        f"parsed {measures['ALL']['parsed_pct']}% | "
        f"lowered {measures['ALL']['lowered_pct']}% | "
        f"executed {measures['ALL']['executed_pct']}%"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
