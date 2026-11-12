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


# ---------------------------------------------------------------------------
# A new defaulted field is not a move (Darksteel W1G2: 9 real moves read as
# 2,407 when ActivatedAbilityCost gained ``unattach_granter_id=None``)
# ---------------------------------------------------------------------------

def _entry(od, **components):
    entry = {component: "()" for component in od.COMPONENTS}
    entry.update(components)
    return entry


def _pool(od, **cards):
    return {name: _entry(od, **components) for name, components in cards.items()}


def test_a_card_moved_only_by_a_new_defaulted_field_is_counted_on_its_line_not_listed(od):
    old = _pool(
        od,
        Quiet={"activated_abilities": "(Ability(cost=Cost(tap=True, pay_life=0)),)"},
        Moved={"activated_abilities": "(Ability(cost=Cost(tap=False, pay_life=2)),)"},
        Valued={"activated_abilities": "(Ability(cost=Cost(tap=True, pay_life=1)),)"},
        Quoted={"reason": "'a reason quoting Cost(tap=True, pay_life=0)'",
                "activated_abilities": "(Ability(cost=Cost(tap=True, pay_life=3)),)"},
        Still={"instructions": "(Other(x=1),)"},
    )
    new = _pool(
        od,
        Quiet={"activated_abilities": "(Ability(cost=Cost(tap=True, pay_life=0, unattach=None)),)"},
        Moved={"activated_abilities": "(Ability(cost=Cost(tap=False, pay_life=4, unattach=None)),)"},
        Valued={"activated_abilities": "(Ability(cost=Cost(tap=True, pay_life=1, unattach='granter')),)"},
        # The repr inside a string is text: it neither gains the field nor rules the class out.
        Quoted={"reason": "'a reason quoting Cost(tap=True, pay_life=0)'",
                "activated_abilities": "(Ability(cost=Cost(tap=True, pay_life=3, unattach=None)),)"},
        Still={"instructions": "(Other(x=1),)"},
    )
    _, _, changed = od.compare_snapshots(old, new)
    assert set(changed) == {"Quiet", "Moved", "Valued", "Quoted"}

    real, by_field, fields = od.split_defaulted(old, new, changed)
    assert [item.label for item in fields] == ["Cost.unattach=None"]
    assert fields[0].others == (("'granter'", 1),)
    assert by_field == {"Cost.unattach=None": ["Quiet", "Quoted"]}
    # A real move keeps its diff, without the new field's spelling; a card
    # carrying the field at another value is a real move.
    assert set(real) == {"Moved", "Valued"}
    ((component, before, after),) = real["Moved"]
    assert component == "activated_abilities" and "unattach" not in after
    assert after == "(Ability(cost=Cost(tap=False, pay_life=4)),)"
    assert "unattach='granter'" in real["Valued"][0][2]

    text = od.render_compare([], [], real, len(old), by_field, fields)
    assert text.splitlines()[0] == "0 added / 0 removed / 2 changed of 5 cards"
    assert "2  Cost.unattach=None (other values, read as moves: 'granter' ×1)" in text


def test_a_class_seen_in_a_component_that_did_not_move_has_gained_no_field(od):
    """A repr that did not move either lacks the field or had it before; both
    mean the field is not new to every repr, so nothing is struck."""
    old = _pool(od, A={"instructions": "(Step(n=1),)"}, B={"modes": "((Step(n=2),), False)"})
    new = _pool(od, A={"instructions": "(Step(n=1, extra=None),)"}, B={"modes": "((Step(n=2),), False)"})
    _, _, changed = od.compare_snapshots(old, new)
    real, by_field, fields = od.split_defaulted(old, new, changed)
    assert fields == [] and by_field == {} and real == changed


def test_the_struck_spelling_is_exactly_the_field_wherever_it_sits(od):
    struck = {("Cost", "z", "None")}
    assert od._strike("Cost(z=None, a=1)", struck)[0] == "Cost(a=1)"
    assert od._strike("Cost(a=1, z=None)", struck)[0] == "Cost(a=1)"
    assert od._strike("Cost(z=None)", struck)[0] == "Cost()"
    assert od._strike("Cost(a=Cost(z=None, a=2), z=None)", struck)[0] == "Cost(a=Cost(a=2))"
    # Another class's field of the same name, and another value, stay.
    assert od._strike("Other(z=None)", struck)[0] == "Other(z=None)"
    assert od._strike("Cost(z=0)", struck)[0] == "Cost(z=0)"


def test_compare_against_a_second_snapshot_exits_on_real_moves_only(od, tmp_path, capsys):
    old = _pool(od, A={"instructions": "(Step(n=1),)"})
    only_default = _pool(od, A={"instructions": "(Step(n=1, extra=None),)"})
    real_move = _pool(od, A={"instructions": "(Step(n=2, extra=None),)"})
    paths = {}
    for label, snapshot in (("old", old), ("default", only_default), ("real", real_move)):
        paths[label] = tmp_path / f"{label}.json"
        od.write_snapshot(snapshot, paths[label])

    assert od.main(["compare", "--snapshot", str(paths["old"]), "--against", str(paths["default"])]) == 0
    out = capsys.readouterr().out
    assert out.startswith("0 added / 0 removed / 0 changed of 1 cards\n1 more moved only")
    assert "    1  Step.extra=None" in out

    assert od.main(["compare", "--snapshot", str(paths["old"]), "--against", str(paths["real"])]) == 1
    out = capsys.readouterr().out
    assert "1 changed of 1 cards" in out and "    -(Step(n=1),)" in out and "    +(Step(n=2),)" in out
