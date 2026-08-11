"""Generate HOOK_RELIANCE.md — how much of the pool is supported by its name.

`engine/card_hooks.py` is the one sanctioned place to key behaviour on a card
name, and each entry there is individually defensible: the bar is that no second
card, real or plausibly printable, shares the shape, and two guards
(`tests/engine/test_card_lines.py`, `tests/engine/test_front_end_safety.py`)
hold each entry to it. What no guard measured was the **aggregate**.

That is the number that decides whether this architecture reaches the full
release line. A name-keyed entry costs one hand-written rule and buys exactly
one card; a grammar production costs one and buys every card printed with that
template, now and forever. So the fraction of the pool carried by names is the
engine's marginal cost per card, and at 26,113 cards a fraction that looks
tolerable at 388 is several thousand hand-written entries — which is the failure
mode the whole registry-based design exists to avoid, wearing a different hat.

Three measures, per set and over the deduped pool:

- **hooked cards** — cards with at least one name-keyed entry in any registry.
  The headline: what share of the pool needs its name written down somewhere.
- **hooked lines** — printed rules lines read by `CARD_LINE_INSTRUCTIONS`
  rather than by the grammar. The complement of the *executed* measure in
  `GRAMMAR_COVERAGE.md`, over the same denominator, so the two can be read
  together.
- **entries per 100 cards** — name-keyed entries divided by cards. The one that
  extrapolates: multiply by the release line to price the approach.

**All three are ceilings, not floors** — the opposite direction to
`scripts/grammar_coverage.py`, and for the same reason. There the hazard is the
general reader losing ground; here it is the special-case readers gaining it.
A rise means the pool got more expensive per card. The ceilings live in
`scripts/hook_reliance_ratchet.json` and `tests/engine/test_hook_reliance.py`
fails when one is exceeded; raise them with `--accept` after deciding the rise
was worth it.

**A new set will move the ALL row and that is the point.** The four base sets in
the pool are near-identical reprint lists, so their rows are one data point
wearing four hats; ARN is the only independent one, and it sits at more than
twice their rate. Whether that is early-Magic weirdness or the real rate is a
question only ingesting a modern, heavily-templated set answers — and this
report is the instrument that reads the answer.

Registries are discovered by introspection rather than listed here, so a new
name-keyed registry is measured the day it is added instead of the day someone
remembers to add it. A container counts as name-keyed when most of its keys
name cards in the pool, which is also how `TRIGGER_HOOKS` (keyed by trigger
condition) correctly stays out.

Usage::

    python scripts/hook_reliance.py            # regenerate the report
    python scripts/hook_reliance.py --check    # fail if any measure rose
    python scripts/hook_reliance.py --accept   # re-snapshot the ceilings
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine.card_hooks as card_hooks
import engine.oracle as oracle
from engine.card_loader import (
    load_cards,
    load_catalog,
    manifest_measured_codes,
    manifest_set_paths,
)
from engine.grammar import compile_line

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "HOOK_RELIANCE.md"
RATCHET_PATH = REPO_ROOT / "scripts" / "hook_reliance_ratchet.json"

# The size of the release line this pool is a sample of. Used only to render the
# projection — how many hand-written entries the current rate implies at full
# scale — which is the whole reason the aggregate is worth measuring.
RELEASE_LINE_CARDS = 26_113

# A container whose keys are *mostly* card names is a name-keyed registry. The
# threshold rather than "all" leaves room for a registry that mixes a card name
# with a sentinel, while still excluding TRIGGER_HOOKS (keyed by the trigger
# condition, so zero of its keys are cards).
_NAME_KEYED_THRESHOLD = 0.5


@dataclass
class Registry:
    """One name-keyed registry in ``engine/card_hooks.py``."""

    name: str
    cards: set[str]
    # Entries, which is not the same as cards: CARD_LINE_INSTRUCTIONS nests a
    # dict of lines under each name, and a card needing two hand-written lines
    # costs two. Entries is what extrapolates; cards is what the headline reads.
    entries: int
    # Keys naming no card in the pool. For CARD_LINE_INSTRUCTIONS this is
    # already a test failure; for the other registries nothing else checks it,
    # and a hook keyed on a misspelling is a hook that can never fire.
    dead_keys: list[str] = field(default_factory=list)
    # name -> how many entries that card costs in this registry. One for a flat
    # registry; one per hand-written line for CARD_LINE_INSTRUCTIONS.
    per_card: dict[str, int] = field(default_factory=dict)

    def entries_for(self, names: set[str]) -> int:
        """Entries this registry spends on *names* — a set's share of the pile."""
        return sum(count for name, count in self.per_card.items() if name in names)


@dataclass
class Stats:
    """Counts for one scope.

    **Every ratcheted denominator is supported cards**, and the measure names
    say so, because an implicit denominator is what made the first version of
    this script wrong. It counted every card in the pool, and while 388 of 388
    are supported that is invisible — the two denominators are the same number.
    It stops being invisible the moment a set lands at partial support: the
    denominator inflates with cards the engine does not play, the hooked
    numerator does not follow, and reliance *falls*. The ratchet would pass, and
    a set supported at 30% would read as an architectural improvement. Since
    this instrument exists to be read across exactly that event, the denominator
    has to be the cards the engine actually plays.

    ``cards`` is still counted, and reported beside the rest as pool reach — how
    much of a set is in scope at all is a real number, it is just a different
    question and not one a *reliance* ceiling should answer.
    """

    cards: int = 0
    supported_cards: int = 0
    hooked_cards: int = 0
    # Lines, and hooked lines, of *supported* cards only. An unsupported card's
    # text is not text the engine reads, so counting it would dilute the ratio
    # the same way its card dilutes the card count.
    lines: int = 0
    hooked_lines: int = 0
    # Every name-keyed entry touching this scope, supported or not — this
    # numerator is deliberately *not* restricted. Entries are what was
    # hand-written; supported cards are what it bought. An entry on a card that
    # ends up unsupported cost a rule and bought nothing, and the measure should
    # charge for it rather than let it disappear along with its card.
    entries: int = 0

    def _pct(self, value: int, total: int) -> float:
        return 0.0 if not total else round(100.0 * value / total, 1)

    def as_dict(self) -> dict[str, float]:
        return {
            "hooked_cards_pct_of_supported": self._pct(
                self.hooked_cards, self.supported_cards
            ),
            "hooked_lines_pct_of_supported": self._pct(self.hooked_lines, self.lines),
            "entries_per_100_supported_cards": self._pct(
                self.entries, self.supported_cards
            ),
        }

    def support_pct(self) -> float:
        """Pool reach — reported, never ratcheted. See the class docstring."""
        return self._pct(self.supported_cards, self.cards)


def discover_registries(pool_names: set[str]) -> list[Registry]:
    """Every name-keyed registry in ``engine/card_hooks.py``, by introspection.

    Listing them here instead would be a second registry of registries, and the
    failure mode of one is that a name-keyed table added tomorrow goes unmeasured
    — which is precisely the blind spot this script exists to close.
    """
    found: list[Registry] = []
    for attribute in sorted(dir(card_hooks)):
        if attribute.startswith("_"):
            continue
        value = getattr(card_hooks, attribute)
        if not isinstance(value, (dict, frozenset, set)) or not value:
            continue
        keys = set(value)
        named = keys & pool_names
        if len(named) < _NAME_KEYED_THRESHOLD * len(keys):
            continue
        # A nested dict is per-line, so a card needing three hand-written lines
        # costs three; every other registry is one entry per card.
        per_card = {
            name: (
                len(value[name])
                if isinstance(value, dict) and isinstance(value.get(name), dict)
                else 1
            )
            for name in named
        }
        found.append(
            Registry(
                name=attribute,
                cards=named,
                entries=sum(per_card.values()),
                dead_keys=sorted(keys - named),
                per_card=per_card,
            )
        )
    return found


def _printed_lines(card) -> list[str]:
    """The card's rules lines as the compiler sees them, modal bullets expanded."""
    text = oracle.expand_modal_activated_lines(card.oracle_text or "")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _hooked_line_keys(card_name: str) -> set[str]:
    """Normalized lines of *card_name* that ``CARD_LINE_INSTRUCTIONS`` supplies."""
    return set(card_hooks.CARD_LINE_INSTRUCTIONS.get(card_name, {}))


def _count_card(card, hooked_names: set[str], stats: Stats) -> None:
    stats.cards += 1
    if not oracle.compile_card_oracle(card).supported:
        # Counted in `cards` (pool reach) and nowhere else. A card the engine
        # cannot play is not a card a hook is carrying, and letting it into the
        # denominators is how ingesting a barely-supported set would read as
        # falling reliance. See Stats' docstring.
        return
    stats.supported_cards += 1
    if card.name in hooked_names:
        stats.hooked_cards += 1
    keys = _hooked_line_keys(card.name)
    for line in _printed_lines(card):
        result = compile_line(line, card_name=card.name)
        if result.blank:
            # Reminder-text-only: no rules text to claim, and excluded from
            # GRAMMAR_COVERAGE.md's denominator too, so the two stay comparable.
            continue
        stats.lines += 1
        if oracle.normalize_creature_line(line) not in keys:
            continue
        if result.usable:
            # The grammar reads this line, so the compiler never reaches the
            # hook — the entry is dead weight, not reliance. Counting it would
            # overstate the number the ratchet guards. `test_card_lines.py`
            # fails on such an entry separately; this is measured rather than
            # assumed so the report stays true while that guard is red.
            continue
        stats.hooked_lines += 1


def analyze() -> tuple[dict[str, Stats], Stats, list[Registry], set[str]]:
    """Per-set stats (shipped *and* measured), the shipped-pool total, and which
    codes are measured-only.

    The asymmetry is the design. Per-set rows cover measured sets, because
    reading their numbers is the entire reason they were ingested. **ALL covers
    the shipped pool only**, because it is the row the ceiling ratchets, and a
    ratchet over a pool the engine does not play would fire on the composition
    of a set nobody has implemented yet rather than on anything anyone did.
    """
    catalog = load_catalog()
    shipped_names = {card.name for card in catalog}

    measured_codes: set[str] = set(manifest_measured_codes())
    # Registries are discovered against the *whole* ingested pool: a hook
    # written for a measured set's card is a real hand-written entry, and
    # discovering against the shipped pool alone would file it as a dead key.
    all_paths = manifest_set_paths(include_measured=True)
    pool_names = {
        card.name for path in all_paths if path.exists() for card in load_cards(str(path))
    }
    registries = discover_registries(pool_names)
    hooked_names: set[str] = set().union(*(r.cards for r in registries)) if registries else set()

    per_set: dict[str, Stats] = {}
    for path in all_paths:
        if not path.exists():
            continue
        code = path.stem.replace("_cards", "")
        stats = Stats()
        cards = load_cards(str(path))
        for card in cards:
            _count_card(card, hooked_names, stats)
        names = {card.name for card in cards}
        stats.entries = sum(registry.entries_for(names) for registry in registries)
        per_set[code] = stats

    overall = Stats()
    for card in catalog:
        _count_card(card, hooked_names, overall)
    # Shipped cards' share of the pile, not every entry in it — the ALL row is
    # about the pool the engine plays.
    overall.entries = sum(registry.entries_for(shipped_names) for registry in registries)

    return per_set, overall, registries, measured_codes


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def render(
    per_set: dict[str, Stats],
    overall: Stats,
    registries: list[Registry],
    measured_codes: set[str] = frozenset(),
) -> str:
    lines: list[str] = []
    add = lines.append

    add("# Hook Reliance")
    add("")
    add(
        "How much of the card pool is supported by having its **name** written "
        "down — `engine/card_hooks.py`, the one sanctioned place to key "
        "behaviour on a card name — rather than by having its text read."
    )
    add("")
    add(
        "Every individual entry there is defensible and guarded; this is the "
        "measure of the pile. A name-keyed entry costs one hand-written rule "
        "and buys one card. A grammar production costs one and buys every card "
        "printed with that template. So this fraction is the engine's marginal "
        "cost per card, and it is the number that decides whether the "
        "architecture reaches the full release line."
    )
    add("")
    add("**Generated** — run `python scripts/hook_reliance.py` to refresh.")
    add("")
    add(
        "The measures are **ceilings**, the opposite direction to "
        "`GRAMMAR_COVERAGE.md`'s floors and for the same reason: there the "
        "hazard is the general reader losing ground, here it is the "
        "special-case readers gaining it."
    )
    add("")
    add(
        "**Every percentage below is over *supported* cards**, and the measure "
        "names say so. A card the engine cannot play is not a card a hook is "
        "carrying, so counting it would mean that ingesting a set supported at "
        "30% inflates the denominator, leaves the numerator behind, and reports "
        "*falling* reliance — a ceiling passing because the pool got harder. "
        "Support rate is reported beside the measures as pool reach, which is a "
        "real number and a different question."
    )
    add("")

    add("## The headline")
    add("")
    measures = overall.as_dict()
    add(
        f"**{overall.hooked_cards} of {overall.supported_cards} supported cards "
        f"({measures['hooked_cards_pct_of_supported']}%)** carry at least one "
        f"name-keyed entry, across **{overall.entries} entries** in "
        f"{len(registries)} registries. The pool is {overall.cards} cards, "
        f"{overall.support_pct()}% supported."
    )
    add("")
    per_card = overall.entries / overall.supported_cards
    projected_entries = round(per_card * RELEASE_LINE_CARDS)
    projected_cards = round(
        overall.hooked_cards / overall.supported_cards * RELEASE_LINE_CARDS
    )
    add(
        f"Held at this rate, supporting the {RELEASE_LINE_CARDS:,}-card release "
        f"line would need about **{projected_entries:,} hand-written entries** "
        f"covering **{projected_cards:,} cards**. That projection is the point "
        "of the number, not a forecast: it is the cost of assuming the current "
        "sample is representative, and the sample is five sets from 1993–94."
    )
    add("")

    add("## By set")
    add("")
    header = (
        "| Set | Cards | Supported | Hooked cards | Rules lines | Hooked lines "
        "| Entries | Entries/100 supported |"
    )
    add(header)
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")

    def row(label: str, stats: Stats, bold: bool) -> str:
        values = stats.as_dict()
        mark = "**" if bold else ""
        return (
            f"| {mark}{label}{mark} "
            f"| {mark}{stats.cards}{mark} "
            f"| {mark}{stats.supported_cards} ({stats.support_pct()}%){mark} "
            f"| {mark}{stats.hooked_cards} "
            f"({values['hooked_cards_pct_of_supported']}%){mark} "
            f"| {mark}{stats.lines}{mark} "
            f"| {mark}{stats.hooked_lines} "
            f"({values['hooked_lines_pct_of_supported']}%){mark} "
            f"| {mark}{stats.entries}{mark} "
            f"| {mark}{values['entries_per_100_supported_cards']}{mark} |"
        )

    for code, stats in per_set.items():
        label = f"{code} *(measured)*" if code in measured_codes else code
        add(row(label, stats, bold=False))
    add(row("ALL (shipped, deduped)", overall, bold=True))
    add("")
    if measured_codes:
        add(
            f"*(measured)* — {', '.join(sorted(measured_codes))} are ingested for "
            "measurement and **not shipped**: `cards/manifest.json` lists them "
            "under `measured`, the engine's catalog does not load them, and no "
            "player can put one in a deck. They are reported here and excluded "
            "from the ALL row and from the ceilings, because a ratchet over a "
            "set nobody has implemented would fire on its composition rather "
            "than on anything anyone did. A measured set moves up to `sets` "
            "when it is fully supported."
        )
        add("")
    add(
        "**Read the rows, not the average.** The base sets are near-identical "
        "reprint lists, so four of these rows are one data point wearing four "
        "hats — and the ALL row, deduped across reprints, is dominated by it. "
        "The independent comparison is between that block and the sets printed "
        "to a different brief."
    )
    add("")

    add("## Registries")
    add("")
    add("| Registry | Cards | Entries |")
    add("| --- | ---: | ---: |")
    for registry in sorted(registries, key=lambda r: -r.entries):
        add(f"| `{registry.name}` | {len(registry.cards)} | {registry.entries} |")
    add("")
    dead = [(r.name, key) for r in registries for key in r.dead_keys]
    if dead:
        add(
            "**Keys naming no card in the pool** — a hook keyed on a "
            "misspelling can never fire, and looks exactly like a card nobody "
            "hooked:"
        )
        add("")
        for name, key in dead:
            add(f"- `{name}` → `{key}`")
        add("")

    add("## Cards carried by a name")
    add("")
    by_card: dict[str, list[str]] = {}
    for registry in registries:
        for name in registry.cards:
            by_card.setdefault(name, []).append(registry.name)
    for name in sorted(by_card):
        registry_names = ", ".join(f"`{r}`" for r in sorted(by_card[name]))
        count = len(card_hooks.CARD_LINE_INSTRUCTIONS.get(name, {}))
        suffix = f" — {count} line{'s' if count != 1 else ''}" if count else ""
        add(f"- **{name}** ({registry_names}){suffix}")
    add("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ratchet
# ---------------------------------------------------------------------------


def _measures(
    per_set: dict[str, Stats],
    overall: Stats,
    measured_codes: set[str] = frozenset(),
) -> dict[str, dict[str, float]]:
    """What the ratchet compares — **shipped scopes only**.

    A measured set is reported and not ratcheted. Its numbers describe a set
    nobody has implemented, so a ceiling over them would fire on the day it was
    ingested and every day after, which is how a ratchet becomes a thing people
    pass rather than read.
    """
    measures = {
        code: stats.as_dict()
        for code, stats in per_set.items()
        if code not in measured_codes
    }
    measures["ALL"] = overall.as_dict()
    return measures


def check(measures: dict[str, dict[str, float]]) -> list[str]:
    """Compare current measures against the committed ceilings.

    Ceilings, so the comparison is ``>``: a *rise* is the regression.
    """
    if not RATCHET_PATH.exists():
        return [f"missing ratchet baseline: {RATCHET_PATH}"]
    baseline = json.loads(RATCHET_PATH.read_text(encoding="utf-8"))
    failures: list[str] = []
    for scope, ceilings in baseline.get("ceilings", {}).items():
        current = measures.get(scope)
        if current is None:
            failures.append(f"{scope}: no longer measured (was in the ratchet)")
            continue
        for measure, ceiling in ceilings.items():
            value = current.get(measure, 0.0)
            if value > ceiling:
                failures.append(
                    f"{scope}.{measure} rose: {value} > ceiling {ceiling}"
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if any measure rose")
    parser.add_argument("--accept", action="store_true", help="re-snapshot the ceilings")
    args = parser.parse_args()

    per_set, overall, registries, measured_codes = analyze()
    measures = _measures(per_set, overall, measured_codes)

    if args.check:
        failures = check(measures)
        if failures:
            print("FAIL: hook reliance rose")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        print(
            f"OK: {measures['ALL']['hooked_cards_pct_of_supported']}% of "
            "supported cards name-keyed, "
            f"{measures['ALL']['entries_per_100_supported_cards']} entries per "
            "100 supported cards"
        )
        return 0

    if args.accept:
        RATCHET_PATH.write_text(
            json.dumps({"ceilings": measures}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote ratchet ceilings to {RATCHET_PATH}")

    OUTPUT_PATH.write_text(
        render(per_set, overall, registries, measured_codes), encoding="utf-8"
    )
    print(f"Wrote {OUTPUT_PATH}")
    print(
        f"hooked cards {measures['ALL']['hooked_cards_pct_of_supported']}% | "
        f"hooked lines {measures['ALL']['hooked_lines_pct_of_supported']}% | "
        f"entries/100 supported "
        f"{measures['ALL']['entries_per_100_supported_cards']} "
        f"(pool {overall.support_pct()}% supported)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
