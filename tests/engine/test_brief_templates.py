"""The integration briefs' templates and their generator agree.

`scripts/integration/write_briefs.py` fills `brief_templates/common_w1.md` and
`common_w2.md`; a placeholder the generator does not fill would ship as
`{{NAME}}` in a brief nine agents read, and a rule dropped from a template is a
rule every later set loses — Darksteel's own four corrections were nearly lost
that way, because the brief was rewritten from the last one by hand. So the
templates hold the rules once, and this test holds them to the generator.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATES = REPO / "scripts" / "integration" / "brief_templates"
GENERATOR = REPO / "scripts" / "integration" / "write_briefs.py"
PLACEHOLDER = re.compile(r"\{\{[A-Za-z0-9_]+\}\}")


def _filled_by_generator() -> set[str]:
    """Every placeholder the generator writes: the keys of its fill tables."""
    source = GENERATOR.read_text(encoding="utf-8")
    return set(re.findall(r'"(\{\{[A-Za-z0-9_]+\}\})"\s*:', source))


def test_every_template_placeholder_is_one_the_generator_fills():
    filled = _filled_by_generator()
    assert len(filled) >= 15, sorted(filled)
    for template in ("common_w1.md", "common_w2.md"):
        used = set(PLACEHOLDER.findall((TEMPLATES / template).read_text(encoding="utf-8")))
        assert used, template
        assert used <= filled, (template, sorted(used - filled))


def test_the_templates_carry_the_rules_darksteel_corrected():
    """Each of these was learned the hard way and written into the brief:
    a subagent cannot write a report file; both differentials before the first
    edit; never sed -i (CRLF); the base's known reds; the full-marked
    structural guards named."""
    w1 = (TEMPLATES / "common_w1.md").read_text(encoding="utf-8")
    w2 = (TEMPLATES / "common_w2.md").read_text(encoding="utf-8")
    for needle in ("test_face_blind_guards.py", "run_and_wait.sh", "Never `git stash`",
                   'never for "passed"', "oracle_diff.py snapshot"):
        assert needle in w1, needle
    for needle in ("cannot write", "sim_fingerprint.py snapshot", "sed -i", "The reds on your base"):
        assert needle in w2, needle
