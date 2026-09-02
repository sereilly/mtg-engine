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
