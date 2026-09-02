"""The whole-pool row's key must not be a name a set can take.

`grammar_coverage.py` and `hook_reliance.py` each report one row per manifest
entry plus one aggregate row over the pool, in a single dict the ratchets are
keyed by. Both keyed the aggregate ``"ALL"``, which held for as long as no set
was called ALL — and Alliances is.

The collision has two faces and only the loud one fires. While ALL is
*measured*, `_measures` drops it from the per-set rows and then re-adds the
string as the aggregate, so the guard proving a measured set is never ratcheted
reports a leak that is really the aggregate wearing the set's code. Once ALL
ships, nothing fails at all: the per-set entry is computed and immediately
overwritten by the aggregate, `"ALL"` is genuinely in the baseline, and
Alliances' own floor and ceiling are simply gone.

So the assertions here are about the *shape* of the key and the *count* of the
rows, never about which sets exist today.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import grammar_coverage  # noqa: E402
import hook_reliance  # noqa: E402
from set_argument import POOL_SCOPE  # noqa: E402

from engine.card_loader import (  # noqa: E402
    manifest_measured_codes,
    manifest_sets,
)

INSTRUMENTS = (grammar_coverage, hook_reliance)


def _manifest_codes() -> set[str]:
    return {entry["code"] for entry in manifest_sets()} | set(manifest_measured_codes())


def test_the_pool_scope_is_not_a_possible_set_code():
    """A set code is alphanumeric; the angle brackets are what make this safe.

    Asserted against the code *shape* rather than against a list of the codes
    in use, because the list is what goes stale — ``"ALL"`` was not a set code
    either, right up until it was.
    """
    assert not POOL_SCOPE.isalnum(), (
        f"the whole-pool scope key {POOL_SCOPE!r} has the shape of a set code, "
        "so a set printed with that code would silently overwrite its own row"
    )


def test_the_pool_scope_collides_with_no_manifest_entry():
    assert POOL_SCOPE not in _manifest_codes(), (
        f"a manifest set is called {POOL_SCOPE!r}, which is the key both "
        "coverage instruments give the whole-pool row"
    )


def test_both_instruments_key_the_aggregate_row_by_the_pool_scope():
    for module in INSTRUMENTS:
        assert POOL_SCOPE in module._measures({}, module.Stats()), (
            f"{module.__name__} does not key its aggregate row by POOL_SCOPE"
        )


def test_every_shipped_set_keeps_its_own_ratcheted_row():
    """The failure this file exists for, stated as the count.

    A per-set row overwritten by the aggregate leaves the dict one entry short
    and every other guard green, so the assertion has to be that the shipped
    sets and the aggregate are *all* present and distinct — not that some
    particular scope is.
    """
    shipped = [entry["code"] for entry in manifest_sets()]
    measured = set(manifest_measured_codes())
    for module in INSTRUMENTS:
        per_set = {code: module.Stats() for code in shipped + sorted(measured)}
        measures = module._measures(per_set, module.Stats(), measured)
        assert set(measures) == {*shipped, POOL_SCOPE}, (
            f"{module.__name__}: expected one row per shipped set plus the "
            f"aggregate, got {sorted(measures)}"
        )


def test_the_committed_baselines_carry_the_pool_scope():
    """Both baselines were migrated off ``"ALL"``; neither may carry it again."""
    for module, key in ((grammar_coverage, "floors"), (hook_reliance, "ceilings")):
        baseline = json.loads(module.RATCHET_PATH.read_text(encoding="utf-8"))[key]
        assert POOL_SCOPE in baseline, f"{module.RATCHET_PATH.name} lost its aggregate row"
        assert set(baseline) - {POOL_SCOPE} <= _manifest_codes(), (
            f"{module.RATCHET_PATH.name} ratchets a scope that is neither a "
            "manifest set nor the whole pool"
        )
