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
