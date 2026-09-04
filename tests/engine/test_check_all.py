"""scripts/check_all.py mirrors ci.yml's guard checks — and only mirrors.

The workflow stays authoritative: this guard extracts the ordered ``--check``
run lines from the guards job and holds the script's ``COMMANDS`` equal to
them, so a gate added to CI without being added here (or vice versa) fails a
test instead of silently drifting. The extraction is a regex rather than a
YAML parse on purpose — the repo carries no yaml dependency, and the shape it
reads ("run: python scripts/<name>.py --check") is the shape the workflow has
always used.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import check_all  # noqa: E402

CI_YML = REPO / ".github" / "workflows" / "ci.yml"

_CHECK_RUN = re.compile(r"run: python (scripts/[a-z_]+\.py) --check")


def test_check_all_runs_exactly_the_ci_guard_checks_in_order():
    workflow = _CHECK_RUN.findall(CI_YML.read_text(encoding="utf-8"))
    assert len(workflow) >= 6, (
        "the ci.yml guards job stopped matching 'run: python scripts/<name>.py "
        "--check' — update the extraction here and COMMANDS in check_all.py "
        "together"
    )
    assert [cmd[0] for _, cmd in check_all.COMMANDS] == workflow, (
        "scripts/check_all.py COMMANDS differ from ci.yml's guard checks — "
        "the workflow is authoritative; mirror it"
    )
    assert all(cmd[1:] == ["--check"] for _, cmd in check_all.COMMANDS)


def test_the_freshness_list_regenerates_what_ci_regenerates():
    """The freshness step's regen list, held the same way. Its run lines are
    plain script invocations (no --check) inside one multi-line step, plus the
    verification-markdown one-liner."""
    workflow = CI_YML.read_text(encoding="utf-8")
    step_match = re.search(
        r"Generated trackers are up to date\s*\n\s*run: \|\n(.*?)\n\s*if ",
        workflow,
        re.S,
    )
    assert step_match, "ci.yml's freshness step moved — update this extraction"
    step = step_match.group(1)
    ci_scripts = re.findall(r"python (scripts/[a-z_]+\.py)", step)
    ours = [cmd[0] for _, cmd in check_all.FRESHNESS_COMMANDS if cmd[0].endswith(".py")]
    assert ours == ci_scripts, (
        "check_all.py FRESHNESS_COMMANDS differ from ci.yml's freshness step"
    )
    assert ("write_verification_markdown" in step) == any(
        "write_verification_markdown" in " ".join(cmd)
        for _, cmd in check_all.FRESHNESS_COMMANDS
    )


STALE_BRANCH = "is stale — rerun the script and commit the result"
TRACKER_SCRIPTS = [
    "grammar_coverage.py",
    "rules_progress.py",
    "behaviour_classes.py",
    "parse_coverage.py",
    "hook_reliance.py",
]


def test_every_tracker_check_carries_the_staleness_branch():
    """ci.yml's freshness step stopped re-running these five scripts because
    each --check now compares its rendered report to the committed file. That
    trade is only safe while the branch exists, so its removal from any of the
    five must fail here — the behavioural proof for the cheapest script is the
    canary below; the other four share the exact code shape and message."""
    for name in TRACKER_SCRIPTS:
        source = (REPO / "scripts" / name).read_text(encoding="utf-8")
        assert STALE_BRANCH in source, (
            f"scripts/{name} --check no longer fails on a stale report — "
            "either restore the branch or return the script to ci.yml's "
            "freshness step and check_all.FRESHNESS_COMMANDS"
        )


def test_a_stale_report_fails_the_check(tmp_path, monkeypatch):
    """The canary: rules_progress --check (the cheapest of the five) must pass
    against its own fresh report and fail once the report drifts."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "rules_progress_stale_canary", REPO / "scripts" / "rules_progress.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    report_path = tmp_path / "RULES_PROGRESS.md"
    monkeypatch.setattr(module, "OUTPUT_PATH", report_path)

    assert module.main([]) == 0          # writes the fresh report
    assert module.main(["--check"]) == 0  # fresh report passes
    report_path.write_text(
        report_path.read_text(encoding="utf-8") + "drift", encoding="utf-8"
    )
    assert module.main(["--check"]) == 1  # stale report fails

# --- the size-guard headroom report -----------------------------------------
#
# `--caps` is advisory and fails nothing, which is exactly why its numbers need
# holding down: a cap it reports against is a *second copy* of the number the
# real guard enforces, and a second copy that nothing checks is the failure
# class this repo keeps finding. So the caps are read back out of the guards
# that own them rather than trusted.

_GRAMMAR_CAP = re.compile(r"splitlines\(\)\) > (\d+)")
_TEST_FILE_CAP = re.compile(r"limit = (\d[\d_]*)")


def _declared_caps() -> dict[str, int]:
    return {label: cap for label, cap, _root, _glob in check_all.SIZE_GUARDS}


def test_the_headroom_report_uses_the_caps_the_guards_enforce():
    """Both numbers, read out of the tests that own them.

    A cap raised in one place and not the other would make the report cheerful
    about a module the guard is about to fail on — advisory output that is
    wrong is worse than none, because it is read *instead* of checking.
    """
    layering = (REPO / "tests" / "engine" / "test_grammar_layering.py").read_text(
        encoding="utf-8"
    )
    convention = (REPO / "tests" / "engine" / "test_set_test_convention.py").read_text(
        encoding="utf-8"
    )

    grammar_caps = {int(n) for n in _GRAMMAR_CAP.findall(layering)}
    assert grammar_caps == {1000}, (
        f"expected one grammar size cap in test_grammar_layering.py, found {grammar_caps}"
    )
    test_caps = {int(n.replace("_", "")) for n in _TEST_FILE_CAP.findall(convention)}
    assert 2600 in test_caps, (
        "test_set_test_convention.py no longer states a 2,600-line limit; "
        f"found {test_caps}"
    )

    declared = _declared_caps()
    assert declared["grammar modules"] == grammar_caps.pop()
    assert declared["per-set test files"] == 2600


def test_the_headroom_report_looks_where_the_guards_look():
    """The globs, too — a report scanning a directory the guard does not (or
    missing one it does) is the same drift wearing a different hat."""
    roots = {label: (root, glob) for label, _cap, root, glob in check_all.SIZE_GUARDS}
    assert roots["grammar modules"] == ("engine/grammar", "**/*.py")
    assert roots["per-set test files"] == ("tests/sets", "test_*.py")
    for _label, _cap, root, glob in check_all.SIZE_GUARDS:
        assert list((REPO / root).glob(glob)), f"{root}/{glob} matches nothing"
