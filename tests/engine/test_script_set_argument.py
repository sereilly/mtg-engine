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

import ast
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from engine.card_loader import (
    MANIFEST_PATH,
    manifest_measured_codes,
    manifest_set_codes,
    manifest_set_path,
    manifest_set_paths,
)

import ingest_set  # noqa: E402
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
def test_a_measured_set_is_reachable_by_code(module, base):
    """`--set M21` has to work, because that is the tool you implement a set with.

    A measured set is by definition one nobody has implemented, so
    `support_report.py` naming its unsupported cards and their reasons is the
    whole point of having ingested it. Before this it exited "no set 'M21' in
    the manifest", and the only way through was `--cards cards/M21_cards.json` —
    the spelled-out filename every guard in this file exists to forbid.
    """
    for code in manifest_measured_codes():
        selection = _resolve(module, [*base, "--set", code])
        assert len(selection.paths) == 1
        assert selection.paths[0].name.upper().startswith(code.upper())
        assert code in selection.label


@pytest.mark.parametrize("module,base", SCRIPTS_UNDER_TEST)
def test_a_measured_set_says_so_in_its_label(module, base):
    """Reachable is not the same as shipped, and the output has to carry that.

    Every one of these scripts prints the label, and "104/285 supported" read as
    a shipped-pool number is a regression report rather than a to-do list. The
    label is where the difference survives, which is the same reason it exists
    at all — the original bug was not only that `support_report.py` read one
    set, it was that nothing in the output said which.
    """
    for code in manifest_measured_codes():
        assert "measured" in _resolve(module, [*base, "--set", code]).label.lower()

    for code in manifest_set_codes():
        assert "measured" not in _resolve(module, [*base, "--set", code]).label.lower()


@pytest.mark.parametrize("module,base", SCRIPTS_UNDER_TEST)
def test_all_still_means_the_shipped_pool_only(module, base):
    """Nameable individually, still excluded from the aggregate.

    `--all` describes the pool the guarantees are about. Folding an
    unimplemented set into it is how "the pool is 100% supported" quietly stops
    meaning anything — the same reason `grammar_coverage.py`'s floors and
    `hook_reliance.py`'s ceilings cover the shipped pool alone.
    """
    selection = _resolve(module, [*base, "--all"])
    measured_paths = {
        REPO / "cards" / f"{code}_cards" for code in manifest_measured_codes()
    }
    assert selection.paths == manifest_set_paths()
    for path in selection.paths:
        assert path.with_suffix("") not in measured_paths

    # And the label must not advertise them either. Naming a measured set in the
    # description of a run that did not read it is the same failure the label
    # exists to prevent — output describing a pool other than the one covered —
    # with the error moved from which set to which list.
    for code in manifest_measured_codes():
        assert code not in selection.label, (
            f"--all names {code} in its label but does not cover it: {selection.label!r}"
        )


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


# ---------------------------------------------------------------------------
# The registry is parsed once
# ---------------------------------------------------------------------------
#
# The test above catches a spelled-out *card* file. It does not catch the other
# way a second copy of the registry gets in: a module that opens
# `cards/manifest.json` and walks it itself. `ingest_set.py` did exactly that,
# and the copy read only the `sets` key — so the day M21 was ingested under
# `measured`, `--all` silently stopped covering it. Nobody edited the script;
# the registry grew a role its private reader did not know about, which is the
# same failure as the stale filename and is invisible for the same reason: the
# output is a successful run over a smaller pool than it appears to describe.

# The vocabulary manifest (`data/vocabulary/manifest.json`) is a different file
# with a different registry, and its two readers are named here so that this
# guard is about the card pool rather than about the string.
_MANIFEST_READERS = {
    Path("engine/card_loader.py"),      # the one reader of cards/manifest.json
    Path("engine/grammar/vocabulary.py"),
    Path("scripts/fetch_vocabulary.py"),
}


def test_the_manifest_is_parsed_in_one_place():
    """Only `engine/card_loader.py` may open the card registry.

    A string constant is the test rather than an import, because the way this
    goes wrong is a module building its own path to the file — prose about
    `cards/manifest.json` in a docstring is a mention, and `MANIFEST_PATH`
    imported from the loader is the sanctioned route. Neither trips this.

    The filename comes from `MANIFEST_PATH` rather than being spelled here: a
    guard that hardcoded it would be the fourteenth copy of the thing it exists
    to forbid, and it would stop matching if the registry were ever renamed.
    """
    filename = Path(MANIFEST_PATH).name
    offenders = []
    for directory in ("engine", "web", "scripts", "tests"):
        for path in sorted((REPO / directory).rglob("*.py")):
            relative = path.relative_to(REPO)
            if Path(*relative.parts) in _MANIFEST_READERS:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            offenders += [
                f"{relative.as_posix()}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and node.value == filename
            ]

    assert not offenders, (
        f"a second reader of the manifest: {offenders}. Import the helpers from "
        "engine.card_loader (manifest_sets / manifest_measured_sets / "
        "manifest_set_paths) — a private copy goes stale when the registry grows."
    )


def test_ingest_all_covers_both_manifest_roles():
    """`--all` is about card *files*, so it covers measured sets too.

    Everywhere else the shipped/measured split is load-bearing and the default
    has to stay narrow — `load_catalog` reaching a measured set is how an
    unsupported card lands in a player's deck. This script is the exception,
    and it is the exception for a reason that is about format rather than
    support: an ingested file that no `--all` slims is a file no size or format
    check is looking at.
    """
    covered = [entry["code"] for entry in ingest_set._registered_entries()]

    assert covered == manifest_set_codes() + manifest_measured_codes()
    for code in manifest_measured_codes():
        assert code in covered, (
            f"ingest_set --all skips the measured set {code}; its card file is "
            "committed like any other and nothing else measures its format"
        )


def test_ingest_resolves_a_registered_set_through_the_manifest():
    """The composed filename is the fallback, not the route."""
    for entry in ingest_set._registered_entries():
        assert ingest_set._set_path(entry["code"]) == REPO / "cards" / entry["file"]


def test_ingest_composes_a_name_only_for_a_set_being_added():
    """The one honest reason to compose a card filename: there is no entry yet.

    This is the exemption `test_no_script_spells_out_a_card_filename` names, and
    it stays narrow — a code the manifest *does* know resolves above, so the
    fallback can never quietly answer for a registered set.

    Asserted as a *shape* rather than as the exact string, because the sibling
    guard `test_no_test_spells_out_a_card_filename` forbids a quoted card
    filename in a test for the same reason this whole file exists. The shape is
    the better claim anyway: what matters is not which name gets composed but
    that it names the code, stays in `cards/`, and cannot collide with a set
    the manifest already knows.
    """
    unregistered = "ZZZ"
    assert unregistered not in manifest_set_codes() + manifest_measured_codes()

    fallback = ingest_set._set_path(unregistered)
    registered = {
        REPO / "cards" / entry["file"] for entry in ingest_set._registered_entries()
    }

    assert fallback.parent == REPO / "cards"
    assert fallback.stem.startswith(unregistered)
    assert fallback not in registered
