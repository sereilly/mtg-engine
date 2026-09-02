"""Guard: `sets` is what the engine plays; `measured` is what it only counts.

`cards/manifest.json` carries two lists. `sets` is the shipped pool — the web
app offers those cards to players, and two guards
(`tests/engine/test_front_end_safety.py`, `tests/engine/test_card_format.py`)
fail if a single card in it is unsupported. `measured` is a set that has been
ingested so its numbers can be read *before* the work of supporting it is done;
only the coverage instruments load it.

The split exists because ingesting M21 forced the choice. Without it the options
were shipping a set the app can play 37% of, or not measuring a modern set at
all — and the second is the one that leaves the scaling question unanswered.

What has to hold for the split to mean anything:

* **the two lists stay disjoint**, or a set would be both shipped and exempt
  from the guarantee that shipping implies;
* **the catalog never loads a measured set** — this is the one that reaches a
  player. `load_catalog` and `manifest_set_paths()` are the seam, and the
  default on `include_measured` is what keeps every existing caller meaning
  "what the engine plays";
* **the instruments do load them**, or the registry buys nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.card_loader import (
    MANIFEST_PATH,
    load_catalog,
    manifest_measured_codes,
    manifest_measured_sets,
    manifest_set_codes,
    manifest_set_paths,
    manifest_sets,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(Path(MANIFEST_PATH).read_text(encoding="utf-8"))


def test_shipped_and_measured_are_disjoint():
    """A set in both lists would be shipped to players *and* exempt from the
    support guarantee that shipping is supposed to carry."""
    both = set(manifest_set_codes()) & set(manifest_measured_codes())
    assert not both, f"sets listed as both shipped and measured: {sorted(both)}"


def test_every_measured_entry_has_its_file(manifest):
    base = Path(MANIFEST_PATH).parent
    missing = [
        entry["code"]
        for entry in manifest_measured_sets()
        if not (base / entry["file"]).exists()
    ]
    assert not missing, f"measured sets with no card file: {missing}"


def test_measured_entries_have_the_same_shape_as_shipped(manifest):
    """So promoting a set to `sets` is a move, not a rewrite."""
    required = {"code", "name", "released", "file"}
    for entry in manifest_measured_sets():
        assert required <= set(entry), f"{entry.get('code')}: missing {required - set(entry)}"


def test_the_catalog_does_not_load_measured_sets():
    """The one that reaches a player: a measured set's cards must not be
    deck-buildable, searchable, or castable."""
    measured_paths = {
        Path(MANIFEST_PATH).parent / entry["file"] for entry in manifest_measured_sets()
    }
    if not measured_paths:
        pytest.skip("no measured sets in the manifest")

    shipped = set(manifest_set_paths())
    assert not (shipped & measured_paths), (
        "manifest_set_paths() returned a measured set by default — every caller "
        "that means 'what the engine plays' would silently widen, load_catalog "
        "above all"
    )

    # What a measured set contributes to a catalog that wrongly loaded it is a
    # *printing*, and that is true of every shape of set. Card names are not:
    # 4ED is entirely reprints, so it shares every name with the shipped pool
    # and a name-difference probe has nothing to compare. This assertion is
    # also the stronger one for the sets where the old probe did work — a
    # widened `load_catalog()` would have added 368 `4ed` printings to cards
    # whose names were already there, and the name check would have passed.
    measured_codes = {code.lower() for code in manifest_measured_codes()}
    leaked = {
        card.name: card.printings
        for card in load_catalog()
        if measured_codes & {code.lower() for code in card.printings}
    }
    assert not leaked, (
        f"load_catalog() carries printings from a measured set: "
        f"{dict(list(leaked.items())[:5])}"
    )


def test_include_measured_widens_the_pool():
    """The other direction: the instruments have to be able to see them, or the
    registry is a list nobody reads."""
    if not manifest_measured_codes():
        pytest.skip("no measured sets in the manifest")

    narrow = manifest_set_paths()
    wide = manifest_set_paths(include_measured=True)
    assert len(wide) == len(narrow) + len(manifest_measured_codes())
    assert set(narrow) < set(wide)


def test_shipped_sets_are_still_the_default_everywhere():
    """`include_measured` is keyword-only and defaults off. Positional callers
    (there are several, passing a manifest path) must be unaffected."""
    assert manifest_set_paths(MANIFEST_PATH) == manifest_set_paths()


def test_the_shipped_sets_are_in_printing_order():
    """CLAUDE.md calls the manifest's order load-bearing, and until 4ED nothing
    asserted it. What existed was
    `test_card_format.test_appending_a_set_never_changes_an_existing_original_printing`,
    which checks the *consequence* — no card's origin moves — and that guard is
    structurally silent for a set whose every card already has an earlier
    printing. Probed at the 4ED promotion by appending it after M21: the whole
    suite stayed green with the set four positions out of place.

    A reprint set is exactly where the consequence cannot bite and the
    convention still has to hold, because the next set inserted near it is not
    necessarily a reprint set. So assert the order itself, which is one
    comparison over data the entries already carry rather than a second list
    someone has to maintain."""
    entries = manifest_sets()
    dates = [(entry["code"], entry["released"]) for entry in entries]
    assert dates == sorted(dates, key=lambda pair: pair[1]), (
        f"cards/manifest.json is not in printing order: {dates}. Insert a set "
        "between the sets it was printed between — appending it makes "
        "CardDefinition.original_printing wrong for every card it shares with "
        "a set already present."
    )


# ---------------------------------------------------------------------------
# register_measured_set — the one sanctioned write of the manifest
# ---------------------------------------------------------------------------


@pytest.fixture()
def manifest_copy(tmp_path):
    import shutil

    copy = tmp_path / "manifest_copy.json"
    shutil.copy(MANIFEST_PATH, copy)
    return copy


def _entry(code, released):
    return {
        "code": code,
        "name": f"Test Set {code}",
        "released": released,
        "file": f"{code}_cards.json",
    }


def test_registration_inserts_in_release_order(manifest_copy):
    """`measured` carries release dates like `sets` does, and the printing
    order is load-bearing there — a helper that appended would hand Phase 4's
    promotion an entry already out of order."""
    from engine.card_loader import register_measured_set

    register_measured_set(_entry("ZZB", "1996-06-01"), manifest_path=manifest_copy)
    register_measured_set(_entry("ZZA", "1995-01-01"), manifest_path=manifest_copy)
    register_measured_set(_entry("ZZC", "1997-01-01"), manifest_path=manifest_copy)
    entries = manifest_measured_sets(manifest_copy)
    # The copy starts from the real manifest, which may already carry measured
    # sets — asserting the list *equals* the three fakes baked in "measured is
    # empty", which broke the day 5ED was ingested. The invariant is the order.
    released = [e["released"] for e in entries]
    assert released == sorted(released)
    codes = [e["code"] for e in entries]
    assert [c for c in codes if c.startswith("ZZ")] == ["ZZA", "ZZB", "ZZC"]


def test_registration_refuses_a_code_in_either_role(manifest_copy):
    """A set holds one role at a time. Re-registering a measured set is a
    plain duplicate; registering a *shipped* one would quietly demote it."""
    from engine.card_loader import register_measured_set

    register_measured_set(_entry("ZZZ", "1996-01-01"), manifest_path=manifest_copy)
    with pytest.raises(ValueError, match="already registered"):
        register_measured_set(_entry("ZZZ", "1996-01-01"), manifest_path=manifest_copy)
    shipped = manifest_sets(manifest_copy)[0]["code"]
    with pytest.raises(ValueError, match="already registered"):
        register_measured_set(_entry(shipped, "1993-08-05"), manifest_path=manifest_copy)


def test_registration_preserves_everything_else_byte_for_byte(manifest_copy):
    """The write is json.dumps of the manifest it read, so the descriptions,
    the shipped list and the key order must survive untouched — undoing the
    insertion must reproduce the original file exactly."""
    import json

    from engine.card_loader import register_measured_set

    before = manifest_copy.read_text(encoding="utf-8")
    register_measured_set(_entry("ZZZ", "1996-01-01"), manifest_path=manifest_copy)
    manifest = json.loads(manifest_copy.read_text(encoding="utf-8"))
    assert list(manifest) == ["description", "sets", "measured_description", "measured"]
    manifest["measured"] = [
        e for e in manifest["measured"] if e["code"] != "ZZZ"
    ]
    assert json.dumps(manifest, indent=2, ensure_ascii=False) + chr(10) == before


def test_registration_requires_the_entry_shape(manifest_copy):
    from engine.card_loader import register_measured_set

    with pytest.raises(ValueError, match="missing"):
        register_measured_set({"code": "ZZZ"}, manifest_path=manifest_copy)
