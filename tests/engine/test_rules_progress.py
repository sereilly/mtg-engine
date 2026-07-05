"""Guards for the CR test-coverage tracker (scripts/rules_progress.py).

Every test in ``tests/rules`` must carry a ``@pytest.mark.cr(...)`` citation of
a rule that exists in ``MagicCompRules.txt`` — that is what keeps
``RULES_PROGRESS.md`` an honest picture of which rules have coverage.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_rules_progress():
    spec = importlib.util.spec_from_file_location(
        "rules_progress", REPO_ROOT / "scripts" / "rules_progress.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Must be registered before exec: the script's dataclasses resolve their
    # postponed annotations via sys.modules[module.__name__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_rules_test_cites_an_existing_cr_rule():
    rp = _load_rules_progress()
    sections, _ = rp.parse_comprehensive_rules(rp.CR_PATH)
    tests = rp.collect_tests(rp.TESTS_DIR)
    _, unannotated, unknown = rp.build_report(sections, tests, "check")

    assert not unannotated, (
        "tests/rules tests missing a @pytest.mark.cr citation "
        f"(see pytest.ini marker docs): {unannotated}"
    )
    assert not unknown, f"cr markers citing nonexistent rules: {unknown}"


def test_comprehensive_rules_parse_finds_the_body():
    rp = _load_rules_progress()
    sections, edition = rp.parse_comprehensive_rules(rp.CR_PATH)
    assert edition != "unknown edition"
    # Spot-check a stable rule so a format change in the CR file is caught.
    assert "508" in sections
    assert "508.1" in sections["508"].rules
    assert "a" in sections["508"].rules["508.1"].subrules
