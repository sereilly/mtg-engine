"""Guard: the share of the pool supported by its *name* may only fall.

``scripts/hook_reliance.py`` measures how much of the card pool is carried by
``engine/card_hooks.py`` — the one sanctioned place to key behaviour on a card
name — and stores the ceilings in ``scripts/hook_reliance_ratchet.json``.

Every individual entry in that file is defensible, and two other guards hold
each one to its bar: ``test_card_lines.py`` checks a key names a real printed
line and still supplies a live instruction, and ``test_front_end_safety.py``
checks the grammar never quietly does less than the hook it superseded. Neither
looks at the size of the pile, and the pile is what decides whether this scales:
a name-keyed entry buys one card, a grammar production buys every card printed
with that template. At the full release line, today's rate is several thousand
hand-written rules.

**This ratchet runs the opposite way to ``test_grammar_ratchet.py``** — ceilings,
not floors — because the hazard points the other way: there the general reader
must not lose ground, here the special-case readers must not gain it.

That inversion brings a failure mode a floor does not have, and
``test_the_measure_is_not_vacuous`` is the answer to it. A floor breaks loudly
when its measurement breaks: a miscount reads as zero coverage and fails. A
ceiling breaks *silently* — a measurement that stops finding registries reports
0% reliance and passes forever, while the pile grows underneath. So the
measure's own machinery is asserted here, not assumed.

Raise the ceilings with ``python scripts/hook_reliance.py --accept``, after
deciding the rise was worth what it bought.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import hook_reliance  # noqa: E402


@pytest.fixture(scope="module")
def analysis():
    return hook_reliance.analyze()


@pytest.fixture(scope="module")
def measures(analysis):
    per_set, overall, _registries, measured_codes = analysis
    return hook_reliance._measures(per_set, overall, measured_codes)


def test_ratchet_baseline_exists():
    assert hook_reliance.RATCHET_PATH.exists(), (
        "missing scripts/hook_reliance_ratchet.json — run "
        "`python scripts/hook_reliance.py --accept`"
    )


def test_hook_reliance_has_not_risen(measures):
    failures = hook_reliance.check(measures)
    assert not failures, (
        "the pool became more dependent on name-keyed hooks:\n  "
        + "\n  ".join(failures)
        + "\n\nA card supported by writing its name down buys one card; a "
        "grammar production buys every card printed the same way. If the rise "
        "is genuinely the right call for these cards, re-snapshot with "
        "`python scripts/hook_reliance.py --accept`."
    )


def test_every_ratcheted_scope_is_in_the_baseline(measures):
    """Renamed off "measured": that word now names the *unshipped* sets in
    `cards/manifest.json`, which are precisely the scopes this must NOT
    require — they are reported and never ratcheted."""
    baseline = json.loads(hook_reliance.RATCHET_PATH.read_text(encoding="utf-8"))
    missing = set(measures) - set(baseline.get("ceilings", {}))
    assert not missing, (
        f"scopes ratcheted but not in the baseline: {sorted(missing)} — run "
        "`python scripts/hook_reliance.py --accept`"
    )


def test_measured_sets_are_reported_but_never_ratcheted(analysis):
    """A measured set is ingested and unimplemented by definition. Ratcheting it
    would fail on the day it arrived and stay failing until the work was done,
    which is how a ratchet becomes something people pass rather than read."""
    per_set, overall, _registries, measured_codes = analysis
    if not measured_codes:
        pytest.skip("no measured sets in the manifest")

    assert measured_codes <= set(per_set), (
        f"measured sets missing from the report: {measured_codes - set(per_set)}"
    )
    ratcheted = set(hook_reliance._measures(per_set, overall, measured_codes))
    assert not (ratcheted & measured_codes), (
        f"measured sets leaked into the ceilings: {ratcheted & measured_codes}"
    )
    # And they stay out of the shipped total, or the ALL ceiling would move
    # when an unimplemented set is ingested.
    assert overall.cards == sum(
        stats.cards for code, stats in per_set.items() if code not in measured_codes
    ) - _reprint_overlap(per_set, measured_codes), (
        "the ALL row must cover the shipped, deduped pool"
    )


def _reprint_overlap(per_set, measured_codes) -> int:
    """Shipped per-set card counts sum over reprints; ALL is deduped. The
    difference is not something this test should re-derive, so it reads it from
    the loader rather than assuming a number."""
    from engine.card_loader import load_catalog

    shipped_sum = sum(
        stats.cards for code, stats in per_set.items() if code not in measured_codes
    )
    return shipped_sum - len(load_catalog())


def test_the_measure_is_not_vacuous(analysis):
    """A ceiling that measures nothing passes forever. Assert it still measures.

    ``discover_registries`` finds the name-keyed tables by introspection, which
    is what keeps a registry added tomorrow from going unmeasured — and is also
    the part that could silently stop finding anything (a rename, a container
    type it does not recognize, a threshold that stops matching). Nothing
    downstream would notice: the report would read 0% and every ceiling would
    hold.
    """
    _per_set, overall, registries, *_ = analysis

    assert registries, "no name-keyed registries discovered — introspection broke"
    by_name = {registry.name: registry for registry in registries}
    assert "CARD_LINE_INSTRUCTIONS" in by_name, (
        "the largest name-keyed registry was not discovered; every measure "
        f"below it is meaningless. Found: {sorted(by_name)}"
    )
    assert by_name["CARD_LINE_INSTRUCTIONS"].entries > 0
    assert overall.hooked_cards > 0 and overall.hooked_lines > 0
    assert overall.cards > 0 and overall.lines > 0


def test_trigger_hooks_is_not_counted_as_name_keyed(analysis):
    """``TRIGGER_HOOKS`` is keyed by trigger condition, not by card name.

    The introspection rule is "most keys name cards in the pool", and this is
    the container that pins which side of it is which — without it, a threshold
    loose enough to sweep in condition-keyed tables would inflate every measure
    and the ceilings would be re-snapshotted around noise.
    """
    _per_set, _overall, registries, *_ = analysis
    assert "TRIGGER_HOOKS" not in {registry.name for registry in registries}


def test_no_registry_key_names_a_card_outside_the_pool(analysis):
    """A hook keyed on a misspelling can never fire, and nothing else notices.

    ``test_card_lines.py`` makes this check for ``CARD_LINE_INSTRUCTIONS``. The
    smaller registries had no equivalent: a dead key there looks exactly like a
    card nobody hooked, so the card silently loses the behaviour.
    """
    _per_set, _overall, registries, *_ = analysis
    dead = {
        registry.name: registry.dead_keys
        for registry in registries
        if registry.dead_keys
    }
    assert not dead, (
        f"name-keyed hook entries matching no card in the pool: {dead}"
    )


def test_measures_are_internally_consistent(analysis):
    """Hooked counts are subsets, so a percentage over 100 means a miscount."""
    per_set, overall, _registries, *_ = analysis
    for scope, stats in [*per_set.items(), ("ALL", overall)]:
        assert stats.supported_cards <= stats.cards, scope
        assert stats.hooked_cards <= stats.supported_cards, scope
        assert stats.hooked_lines <= stats.lines, scope


def test_the_ratcheted_denominator_is_supported_cards():
    """The ceiling is over cards the engine *plays*, not cards in the pool.

    This is a synthetic ``Stats`` rather than a read of the live numbers, and it
    has to be: every card in the pool is currently supported, so the two
    denominators are the same number and no assertion over real data can tell
    them apart. The distinction only becomes visible when a set lands at partial
    support — which is the exact moment this instrument is meant to be read, and
    too late to discover the measure was denominated wrong.

    The failure it pins: with ``cards`` as the denominator, ingesting a set
    supported at 30% inflates the divisor with cards no hook is carrying, the
    numerator does not follow, reliance *falls*, and the ceiling passes. A
    harder pool would read as an architectural win.
    """
    stats = hook_reliance.Stats(
        cards=100,
        supported_cards=50,
        hooked_cards=25,
        lines=200,
        hooked_lines=40,
        entries=30,
    )
    values = stats.as_dict()

    assert values["hooked_cards_pct_of_supported"] == 50.0, (
        "hooked cards must be a share of supported cards (25/50), not of the "
        f"pool (25/100): {values}"
    )
    assert values["entries_per_100_supported_cards"] == 60.0, (
        f"entries must be per supported card (30/50), not per pool card: {values}"
    )
    # Lines are already restricted to supported cards on both sides, so this one
    # is a straight ratio — recorded so a later change to `lines` has to decide
    # what it means rather than drift.
    assert values["hooked_lines_pct_of_supported"] == 20.0, values
    # Pool reach is the number that *is* over all cards, and is never ratcheted.
    assert stats.support_pct() == 50.0


def test_unsupported_cards_stay_out_of_the_denominators():
    """An unsupported card raises pool reach's divisor and nothing else.

    The counting half of the guard above: ``_count_card`` must return before it
    touches `supported_cards`, `hooked_cards` or the line counts. Driven through
    a stub card so it holds regardless of whether the live pool has an
    unsupported card in it today (it does not).
    """

    class _Unsupported:
        name = "Nonesuch"
        primary_type = "Enchantment"
        oracle_text = "Zzyzx blargh, then blargh zzyzx."
        keywords = ()
        layout = "normal"

    card = _Unsupported()
    assert not hook_reliance.oracle.compile_card_oracle(card).supported, (
        "the stub card was supposed to be unparseable; pick different text"
    )

    stats = hook_reliance.Stats()
    hook_reliance._count_card(card, {"Nonesuch"}, stats)

    assert stats.cards == 1, "an unsupported card still counts toward pool reach"
    assert stats.supported_cards == 0
    assert stats.hooked_cards == 0, (
        "a card the engine cannot play is not a card a hook is carrying"
    )
    assert stats.lines == 0 and stats.hooked_lines == 0
