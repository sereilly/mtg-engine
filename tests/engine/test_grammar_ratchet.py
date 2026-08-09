"""Guard: grammar coverage may only move forward.

``scripts/grammar_coverage.py`` measures how much of the card pool the grammar
front end accounts for and stores the floors in ``scripts/grammar_ratchet.json``.
This test fails if any measure drops below its floor, so the migration cannot
silently regress while the legacy rules are still there to catch the fallback.

Raise the floors with ``python scripts/grammar_coverage.py --accept`` after
reviewing the diff.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import grammar_coverage  # noqa: E402


@pytest.fixture(scope="module")
def measures():
    # Starred so an added analysis output does not break this fixture: the
    # ratchet only ever wants the first two.
    per_set, overall, *_ = grammar_coverage.analyze()
    return grammar_coverage._measures(per_set, overall)


def test_ratchet_baseline_exists():
    assert grammar_coverage.RATCHET_PATH.exists(), (
        "missing scripts/grammar_ratchet.json — run "
        "`python scripts/grammar_coverage.py --accept`"
    )


def test_coverage_has_not_regressed(measures):
    failures = grammar_coverage.check(measures)
    assert not failures, "grammar coverage regressed:\n  " + "\n  ".join(failures)


def test_measures_are_properly_nested(measures):
    """executed <= lowered <= parsed, by construction. A violation means the
    coverage script is miscounting, which would make the ratchet meaningless."""
    for scope, values in measures.items():
        assert values["executed_pct"] <= values["lowered_pct"] <= values["parsed_pct"], (
            f"{scope}: {values}"
        )


def test_every_measured_set_is_in_the_baseline(measures):
    baseline = json.loads(grammar_coverage.RATCHET_PATH.read_text(encoding="utf-8"))
    missing = set(measures) - set(baseline.get("floors", {}))
    assert not missing, (
        f"sets measured but not ratcheted: {sorted(missing)} — run "
        "`python scripts/grammar_coverage.py --accept`"
    )


def test_grammar_executes_something(measures):
    """A zero floor everywhere would make the ratchet vacuous."""
    assert measures["ALL"]["executed_pct"] > 0
