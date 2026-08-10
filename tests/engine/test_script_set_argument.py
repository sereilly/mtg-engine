"""How the single-set scripts name their set (scripts/set_argument.py).

`cards/manifest.json` is the registry of which sets ship. A script that spells
a filename instead keeps a second copy of that list, and the copy is what goes
stale — `support_report.py` spent four sets' worth of ingestion printing
Alpha's 290 cards and calling the pool fully supported.

The case that matters most here is the *unresolvable* set. A `--set` that
quietly produced an empty pool would make `support_report.py` report perfect
coverage over zero cards and `simulate_ai_games.py` report a clean run it never
had: both exit 0, both say nothing is wrong, and neither ran over anything.
So the tests below care less that a good code works than that a bad one stops.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from engine.card_loader import manifest_set_codes, manifest_set_path, manifest_set_paths

import retrieve_oracle  # noqa: E402
import run_duel  # noqa: E402
import set_argument  # noqa: E402
import simulate_ai_games  # noqa: E402
import support_report  # noqa: E402

# (script module, the extra arguments its parser requires). Every script that
# takes a set is listed: the wiring is the thing under test, and a script that
# grew a hardcoded path again would simply not appear in a registry it was
# never added to.
SCRIPTS_UNDER_TEST = [
    pytest.param(retrieve_oracle, ["Black Lotus"], id="retrieve_oracle"),
    pytest.param(run_duel, [], id="run_duel"),
    pytest.param(simulate_ai_games, [], id="simulate_ai_games"),
    pytest.param(support_report, [], id="support_report"),
]


def _resolve(module, argv):
    parser = module.build_parser()
    return set_argument.resolve_set(parser, parser.parse_args(argv))


@pytest.mark.parametrize("module,base", SCRIPTS_UNDER_TEST)
def test_default_resolves_through_the_manifest(module, base):
    """No script may default to a file the manifest does not list."""
    selection = _resolve(module, base)
    assert selection.paths, f"{module.__name__} defaulted to an empty pool"
    assert set(selection.paths) <= set(manifest_set_paths())


@pytest.mark.parametrize("module,base", SCRIPTS_UNDER_TEST)
def test_a_set_code_selects_that_set(module, base):
    """``--set arn`` is the interface — a code, cased however you typed it."""
    selection = _resolve(module, [*base, "--set", "arn"])
    assert selection.paths == [manifest_set_path("ARN")]
    assert "ARN" in selection.label


@pytest.mark.parametrize("module,base", SCRIPTS_UNDER_TEST)
def test_all_selects_the_whole_manifest_pool(module, base):
    selection = _resolve(module, [*base, "--all"])
    assert selection.paths == manifest_set_paths()


@pytest.mark.parametrize("module,base", SCRIPTS_UNDER_TEST)
def test_an_unknown_set_code_exits_naming_the_codes_that_exist(module, base, capsys):
    """The failure this whole indirection exists for.

    Not "the code was wrong" — the engine would survive that. The one to catch
    is a code that resolves to *nothing*, because every one of these scripts
    reports success over an empty pool.
    """
    with pytest.raises(SystemExit) as exit_info:
        _resolve(module, [*base, "--set", "ZZZ"])

    assert exit_info.value.code == 2
    message = capsys.readouterr().err
    assert "ZZZ" in message
    for code in manifest_set_codes():
        assert code in message, f"{module.__name__} did not name {code} as an option"


@pytest.mark.parametrize("module,base", SCRIPTS_UNDER_TEST)
def test_a_path_that_does_not_exist_exits_too(module, base, capsys):
    """``--cards`` stayed for the invocations people already had; it is held to
    the same standard, since a missing file is an empty pool by another route."""
    with pytest.raises(SystemExit) as exit_info:
        _resolve(module, [*base, "--cards", str(REPO / "cards" / "nope.json")])

    assert exit_info.value.code == 2
    assert "nope.json" in capsys.readouterr().err


@pytest.mark.parametrize("module,base", SCRIPTS_UNDER_TEST)
def test_an_existing_path_still_works(module, base):
    """The old ``--cards <path>`` invocation keeps resolving."""
    arn = manifest_set_path("ARN")
    selection = _resolve(module, [*base, "--cards", str(arn)])
    assert selection.paths == [arn]


def test_every_manifest_set_is_reachable_from_a_script():
    """A newly ingested set is usable from these scripts the moment it is
    registered — no per-set edit in any of them."""
    for code in manifest_set_codes():
        selection = _resolve(support_report, ["--set", code])
        assert selection.paths == [manifest_set_path(code)]


def test_no_script_spells_out_a_card_filename():
    """Same rule the tests are held to (tests/engine/test_set_test_convention.py).

    A literal name is matched, an interpolated one is not: ``ingest_set.py``
    builds ``f"{code}_cards.json"`` for a set that is *being added* and so has
    no manifest entry to look up yet, which is the one honest reason to compose
    the name rather than read it.
    """
    literal_card_file = re.compile(r"[A-Za-z0-9]_cards\.json")
    offenders = [
        f"{path.relative_to(REPO)}:{i}"
        for path in SCRIPTS.glob("*.py")
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if literal_card_file.search(line)
    ]
    assert not offenders, (
        f"card filenames spelled out in scripts: {offenders}. "
        "Use --set CODE (scripts/set_argument.py), which reads cards/manifest.json."
    )
