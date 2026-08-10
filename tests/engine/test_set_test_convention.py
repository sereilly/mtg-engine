"""The per-set test convention, enforced (tests/sets/README.md).

The pool is going from 5 sets to 137, and the two things that do not survive
that are a `conftest.py` growing three fixtures per set and card filenames
spelled out wherever someone needed one. Both are cheap to check and expensive
to unwind later, so they are checked.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from engine.card_loader import manifest_set_codes, manifest_set_path

REPO = Path(__file__).resolve().parents[2]
TESTS = REPO / "tests"
CONFTEST = TESTS / "conftest.py"

# Every fixture conftest.py is expected to define. Spelled out rather than
# pattern-matched: the first draft of this guard only flagged fixtures named
# after a set already in the manifest, which is backwards — a new set's fixture
# and its manifest entry arrive together, so that check could never fire on the
# case it existed for. An exact set fires on *any* addition, which is the point:
# adding a fixture here should take a decision, not a reflex.
EXPECTED_FIXTURES = {
    # The factory. A new set needs nothing beyond these.
    "set_cards", "set_pool", "set_codes",
    # The whole pool, for pool-wide guards.
    "all_set_paths", "catalog", "catalog_by_name",
    # Grandfathered per-set aliases — thousands of call sites between them.
    "all_cards", "cards", "arn_cards", "arn_by_name",
}


def _fixture_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and any(
            "fixture" in ast.dump(decorator) for decorator in node.decorator_list
        )
    }


def test_conftest_has_no_new_per_set_fixtures():
    """A new set must need no change to conftest.py at all.

    ``set_pool("ATQ")`` is the whole mechanism. A fixture named after a set is
    the pattern this replaced, and it is only invisible until there are a
    hundred of them.
    """
    actual = _fixture_names(CONFTEST)
    added = actual - EXPECTED_FIXTURES
    assert not added, (
        f"new fixtures in conftest.py: {sorted(added)}. A per-set fixture is the "
        "pattern set_pool(code) / set_cards(code) replaced — see "
        "tests/sets/README.md. If this one is genuinely generic, add it to "
        "EXPECTED_FIXTURES."
    )
    assert not EXPECTED_FIXTURES - actual, (
        f"EXPECTED_FIXTURES is stale: {sorted(EXPECTED_FIXTURES - actual)} no "
        "longer exist"
    )


def test_no_test_spells_out_a_card_filename():
    """``cards/manifest.json`` is the registry. A hardcoded filename is a second
    list to keep in step, and the one that broke this before was the catalog
    sweep reading LEA directly — which is why Arabian Nights went unswept.

    A path prefix is allowed between the opening quote and the set code,
    because the form that actually shipped was a quoted `cards/LEA_cards.json`
    — path prefix and all — and
    the pattern used to anchor on the quote sitting immediately before the
    code — so it matched no path-prefixed spelling, which is to say none of
    the ones anyone writes. The closing quote must follow ``.json`` directly,
    which is what keeps prose naming a file (a docstring, a comment recording
    why the sweep moved) from reading as a second registry."""
    pattern = re.compile(r"""["'][\w/\\.-]*[A-Za-z0-9]+_cards\.json["']""")
    offenders = [
        f"{path.relative_to(REPO)}:{i}"
        for path in TESTS.rglob("*.py")
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert not offenders, (
        f"card filenames spelled out in tests: {offenders}. "
        "Use manifest_set_path(code)."
    )


@pytest.mark.parametrize("code", manifest_set_codes())
def test_every_manifest_set_is_reachable_by_code(code):
    """The factory must cover the whole manifest, so a newly ingested set is
    usable from a test the moment it is registered."""
    assert manifest_set_path(code).exists()


def test_an_unknown_set_code_raises_rather_than_resolving_to_nothing():
    """The failure that matters. An empty pool makes every test over that set
    pass without testing anything, which is the silent-wrongness the engine
    refuses everywhere else."""
    with pytest.raises(KeyError, match="no set 'ZZZ'"):
        manifest_set_path("ZZZ")


def test_per_set_files_stay_readable():
    """A per-set file past this size is due a split by card type. LEA reached
    9,402 lines, which is the reason this convention exists."""
    limit = 2_600
    too_big = {
        path.name: len(path.read_text(encoding="utf-8").splitlines())
        for path in (TESTS / "sets").glob("test_*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > limit
    }
    assert not too_big, (
        f"per-set test files over {limit} lines: {too_big}. "
        "Split by the printed type of the card each test names — "
        "see tests/sets/README.md."
    )
