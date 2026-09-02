"""Guards for the whole-pool compiled-program differential (scripts/oracle_diff.py).

The instrument exists because hand-rebuilt versions kept being lossy — keyed on
instruction kinds or ability counts, both blind to the narrowing class it is
for (a trigger narrowed, a `type_filter` dropped from a payload). So the guards
here pin the two properties a lossy rebuild loses: the snapshot round-trips
without spurious changes, and what it stores is the program in full.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def od():
    spec = importlib.util.spec_from_file_location(
        "oracle_diff", REPO_ROOT / "scripts" / "oracle_diff.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def pool_snapshot(od):
    # Cheap despite the name: compile_card_oracle is process-cached, and the
    # suite has already compiled the pool by the time this runs.
    return od.snapshot_pool()


def test_a_snapshot_round_trips_with_zero_changes(od, pool_snapshot, tmp_path):
    """Write → read → compare against a fresh build must report nothing moved.

    A serialization that perturbs even one repr would make every real compare
    unreadable — the tool's whole output is the set of cards that moved."""
    path = tmp_path / "baseline.json"
    od.write_snapshot(pool_snapshot, path)
    added, removed, changed = od.compare_snapshots(
        od.read_snapshot(path), pool_snapshot
    )
    assert added == [] and removed == [] and changed == {}


def test_a_doctored_entry_is_reported_with_its_component(od, pool_snapshot):
    """The other direction, without which the zero-change test proves only
    that compare returns empty."""
    name = next(
        n for n, entry in pool_snapshot.items() if entry["instructions"] != "()"
    )
    doctored = {n: dict(entry) for n, entry in pool_snapshot.items()}
    doctored[name]["instructions"] = doctored[name]["instructions"].replace(
        "(", "(DOCTORED", 1
    )
    added, removed, changed = od.compare_snapshots(doctored, pool_snapshot)
    assert not added and not removed
    assert set(changed) == {name}
    assert [component for component, _, _ in changed[name]] == ["instructions"]

    # A card leaving the pool is reported too, not folded into "changed".
    del doctored[name]
    added, removed, _ = od.compare_snapshots(doctored, pool_snapshot)
    assert added == [name]


def test_the_stored_programs_are_not_lossy(od, pool_snapshot):
    """Full reprs with payloads, never kinds and never counts.

    Keyed on counts the map cannot see a trigger narrowed from "blocks
    anything" to "blocks a black creature"; keyed on kinds it cannot see a
    `type_filter` stripped from a payload. On Homelands two of five groups and
    the integrator each wrote a lossy version, and each hid a real defect —
    so the payload keys themselves are asserted into the stored text."""
    instructions = [entry["instructions"] for entry in pool_snapshot.values()]
    assert any("payload={" in text for text in instructions), (
        "no stored instruction repr carries its payload — the snapshot has "
        "been abbreviated to kinds, which is exactly the lossy rebuild this "
        "script exists to replace"
    )
    assert any("type_filter" in text for text in instructions), (
        "no stored program carries a type_filter payload key — either the "
        "pool lost every filtered effect (implausible) or the snapshot no "
        "longer records payloads in full"
    )
    assert any(
        "payload={" in entry["triggered_abilities"]
        or "TriggerCondition(" in entry["triggered_abilities"]
        for entry in pool_snapshot.values()
    ), "triggered abilities are no longer stored in full"
