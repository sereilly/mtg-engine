"""`scripts/measured_censuses.py` names the tests an ingest can turn red.

An ingest adds one card file under the manifest's ``measured`` role, so the
tests it can move are the ones whose population walks that set: Darksteel's
full pass read 13 reds in 9 files, 80 minutes into the wave, every one a census
over both manifest roles. `tests_for_diff.py --ingest CODE` names them before
the run. The walk is static: a population drawn through the measured role,
carried through names, returns, fixtures and imports, and *walked* — iterated,
counted, compared, parametrized over, handed to a helper that walks it. An
index read one card at a time is not a walk, which is what keeps the selection
to the censuses (389 test files read both roles; 224 walk them).

The synthetic tree below holds each shape once. The replays (``full``) hold the
selection to history: at Darksteel's and Onslaught's ingest commits it names
every red those full passes read — Onslaught's last one a test that named the
set in prose ("printed in the Onslaught expansion") — under a ceiling on its
size, and over a floor on how much it examined.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import measured_censuses  # noqa: E402
from engine.card_loader import MANIFEST_PATH  # noqa: E402

ZEDSET = measured_censuses.MeasuredSet(
    code="ZZZ", name="Zedset", file="ZZZ" + "_cards.json", card_names=("Zedset Ingot",),
)

CENSUS = '''
import pytest
from engine.card_loader import load_cards, load_catalog, manifest_set_paths

POOL = load_cards(manifest_set_paths(include_measured=True))
BY_NAME = {card.name: card for card in POOL}
SHIPPED = load_catalog()
ROWS = [card.name for card in POOL if "draw" in card.oracle_text]


def _index():
    found = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            found.setdefault(card.name, card)
    return found


def _named(pool, wanted):
    return [pool[name] for name in wanted]


def _census(pool):
    return [card for card in pool.values() if card.oracle_text]


@pytest.fixture
def rows():
    return [card for card in POOL if card.oracle_text]


def test_a_census_walks_the_pool():
    assert all(card.name for card in POOL)


def test_an_index_read_by_name_is_a_lookup():
    assert BY_NAME["Grizzly Bears"].name


def test_an_index_filled_in_a_loop_is_a_lookup():
    assert _index()["Grizzly Bears"]


def test_a_search_by_name_is_a_lookup():
    assert next(card for card in POOL if card.name == "Grizzly Bears")


def test_the_shipped_pool_is_not_the_measured_role():
    assert all(card.name for card in SHIPPED)


def test_a_helper_that_walks_another_argument_is_not_charged():
    assert _named(BY_NAME, ("Grizzly Bears",))


def test_a_helper_that_walks_what_it_is_handed_is():
    assert _census(BY_NAME)


@pytest.mark.parametrize("name", ROWS)
def test_parametrized_over_a_census(name):
    assert name


def test_a_fixture_that_walks_it(rows):
    assert rows


def test_a_count():
    assert len(_index()) > 3


class TestAClass:
    def test_a_method_walks_it(self):
        for card in POOL:
            assert card.name
'''

IMPORTER = '''
from tests.engine.test_census import BY_NAME, POOL


def test_a_population_imported_from_a_census():
    assert sorted(card.name for card in POOL)


def test_an_index_imported_from_a_census():
    assert BY_NAME["Grizzly Bears"]
'''

NAMES = '''
def test_names_the_set_in_prose():
    assert read("a name originally printed in the Zedset expansion") is None


def test_a_card_named_for_the_set_is_not_the_set(set_pool):
    assert set_pool("MRD")["Zedset Ingot"]


def test_names_the_code(set_pool):
    assert set_pool("ZZZ")["Some Card"]


def test_a_docstring_is_prose():
    """Zedset is only mentioned here."""
'''

MODULE_LEVEL = '''
from engine.card_loader import manifest_measured_codes

CODES = [code for code in manifest_measured_codes()]


def test_nothing_reads_it():
    assert True
'''

EXPECTED = {
    "tests/engine/test_census.py::test_a_census_walks_the_pool",
    "tests/engine/test_census.py::test_a_helper_that_walks_what_it_is_handed_is",
    "tests/engine/test_census.py::test_parametrized_over_a_census",
    "tests/engine/test_census.py::test_a_fixture_that_walks_it",
    "tests/engine/test_census.py::test_a_count",
    "tests/engine/test_census.py::TestAClass::test_a_method_walks_it",
    "tests/engine/test_importer.py::test_a_population_imported_from_a_census",
    "tests/sets/test_names.py::test_names_the_set_in_prose",
    "tests/sets/test_names.py::test_names_the_code",
    "tests/engine/test_module_level.py",
}


def _tree(root: Path) -> Path:
    files = {
        "tests/__init__.py": "",
        "tests/engine/__init__.py": "",
        "tests/sets/__init__.py": "",
        "tests/engine/test_census.py": CENSUS,
        "tests/engine/test_importer.py": IMPORTER,
        "tests/sets/test_names.py": NAMES,
        "tests/engine/test_module_level.py": MODULE_LEVEL,
        "tests/engine/test_unrelated.py": "def test_unrelated():\n    assert 1\n",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_each_shape_is_a_walk_or_a_lookup(tmp_path):
    scan = measured_censuses.Scan(_tree(tmp_path), ZEDSET).run()
    selection = scan.selection()
    assert set(selection) == EXPECTED, (
        sorted(set(selection) - EXPECTED), sorted(EXPECTED - set(selection)),
    )
    # Each row says why: the first walk the test makes.
    line, why = selection["tests/engine/test_census.py::test_a_helper_that_walks_what_it_is_handed_is"]
    assert "hands it to test_census._census" in why
    assert "names the set" in selection["tests/sets/test_names.py::test_names_the_set_in_prose"][1]
    assert selection["tests/engine/test_module_level.py"][1].startswith("its import walks it")


def test_a_module_that_names_no_reader_is_not_read(tmp_path):
    scan = measured_censuses.Scan(_tree(tmp_path), ZEDSET)
    assert "tests.engine.test_unrelated" not in scan.modules


def test_the_set_is_named_by_code_file_or_name_outside_a_card_name():
    assert ZEDSET.named_in("ZZZ") and ZEDSET.named_in(" zzz ")
    assert ZEDSET.named_in("cards/" + ZEDSET.file)
    assert ZEDSET.named_in("printed in the Zedset expansion")
    assert not ZEDSET.named_in("Zedset Ingot")
    assert not ZEDSET.named_in("Zedsets")
    assert not ZEDSET.named_in("ZZZZ")


def test_the_measured_set_is_read_off_the_manifest(tmp_path):
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / MANIFEST_PATH.name).write_text(json.dumps({
        "sets": [{"code": "OLD", "name": "Oldset", "released": "2000-01-01",
                  "file": "OLD" + "_cards.json"}],
        "measured": [{"code": "ZZZ", "name": "Zedset", "released": "2001-01-01",
                      "file": ZEDSET.file}],
    }), encoding="utf-8")
    (cards / ("OLD" + "_cards.json")).write_text(json.dumps([
        {"name": "Zedset Ingot"}, {"name": "Zedset"}, {"name": "Grizzly Bears"},
    ]), encoding="utf-8")
    (cards / ZEDSET.file).write_text("[]", encoding="utf-8")
    read = measured_censuses.MeasuredSet.read(tmp_path, "zzz")
    assert (read.code, read.name, read.file) == ("ZZZ", "Zedset", ZEDSET.file)
    # A card called just the set's name (Exodus' Onslaught) is not stripped.
    assert read.card_names == ("Zedset Ingot",)
    with pytest.raises(KeyError, match="measured: ZZZ"):
        measured_censuses.MeasuredSet.read(tmp_path, "OLD")


# ---------------------------------------------------------------------------
# the replays: the ingest commits and the reds their full passes read
# ---------------------------------------------------------------------------

#: Darksteel's ingest (ba705a753): the Phase 1 full pass's 13 reds, in 9 files.
DARKSTEEL_REDS = {
    "tests/engine/test_grammar_lowering.py::test_a_narrowed_trigger_reads_the_same_subject_on_both_sides",
    "tests/engine/test_graveyard_triggers.py::test_every_graveyard_functioning_trigger_reaches_its_zone",
    "tests/engine/test_hidden_cards_stay_out_of_the_log.py::test_no_log_line_names_a_hidden_card",
    "tests/regressions/test_modal_mode_announcements.py::test_w2g2_every_mode_is_held_to_its_own_targets",
    "tests/rules/test_cast_restrictions.py::test_601_3_every_printed_cast_window_in_the_pool_is_claimed_by_the_table",
    "tests/regressions/test_announced_x_target_count.py::test_an_announced_x_caps_the_targets_an_activation_names",
    "tests/ai/test_ai_choice_defaults.py::test_w2g6_where_a_chosen_name_is_looked_for_is_read_off_the_next_sentence",
    "tests/engine/test_scg_p5_trigger_zone_census.py::test_the_population_is_the_one_the_census_drives",
    "tests/engine/test_scg_p5_trigger_zone_census.py::test_no_trigger_that_functions_elsewhere_fires_from_the_battlefield",
    "tests/engine/test_scg_p5_trigger_zone_census.py::test_every_trigger_that_functions_from_a_graveyard_still_fires_there",
    "tests/ai/test_ai_mode_chooser_census.py::test_where_a_sibling_wins_it_is_the_pinned_one",
    "tests/ai/test_ai_mode_chooser_census.py::test_every_mode_is_within_reach",
    "tests/ai/test_ai_mode_chooser_census.py::test_the_modes_with_no_board_are_the_named_ones",
}

#: Onslaught's ingest (bee6eb74b): its 8 reds, the last one naming the set in prose.
ONSLAUGHT_REDS = {
    "tests/ai/test_ai_graveyard_denial.py::test_the_sweep_names_the_defect_with_the_old_defaults_restored",
    "tests/engine/test_graveyard_triggers.py::test_every_graveyard_functioning_trigger_reaches_its_zone",
    "tests/engine/test_self_reference.py::test_no_card_in_the_pool_loses_a_word_to_the_expansion",
    "tests/engine/test_trigger_word_symmetry.py::test_both_front_ends_name_one_condition_over_both_manifest_roles",
    "tests/regressions/test_kg_seats_target_players.py::test_every_printed_target_seat_is_announced",
    "tests/regressions/test_modal_mode_announcements.py::test_w2g2_every_mode_is_held_to_its_own_targets",
    "tests/sets/test_hml_artifacts.py::test_the_expansion_phrase_is_read_once_for_both_cards_that_print_it",
}

#: (commit, code, reds, the fewest modules the walk must read, the most tests it may name).
REPLAYS = [
    ("ba705a753", "DST", DARKSTEEL_REDS, 400, 560),
    ("bee6eb74b", "ONS", ONSLAUGHT_REDS, 280, 420),
]


def _extract(sha: str, root: Path) -> Path:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", sha, "tests", "cards"],
        cwd=REPO, check=True, capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(root, filter="data")
    return root


@pytest.mark.full
@pytest.mark.parametrize("sha, code, reds, floor, ceiling", REPLAYS, ids=[r[1] for r in REPLAYS])
def test_the_ingest_yield_is_named_before_it_runs(tmp_path, sha, code, reds, floor, ceiling):
    present = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=REPO,
                             capture_output=True).returncode == 0
    if not present:
        pytest.skip(f"{sha} is not in this clone's history")
    scan = measured_censuses.scan(_extract(sha, tmp_path), code)
    selection = scan.selection()
    assert reds <= set(selection), sorted(reds - set(selection))
    assert len(scan.modules) >= floor, len(scan.modules)
    assert len(selection) <= ceiling, len(selection)
