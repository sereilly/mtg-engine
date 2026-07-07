"""Guards for the oracle-text parse-coverage tracker (scripts/parse_coverage.py).

Every sentence of every supported card's oracle text must be claimed by a
known consumer (parse rules, compiler tables, text-keyed engine channels,
card hooks) or explicitly acknowledged as a simplification. The deletion-probe
baseline ratchets word-level attribution: a rule change that starts silently
ignoring MORE words (the Hasran Ogress / Army of Allah / Piety bug class)
fails here until the rule is fixed or the finding is reviewed and accepted
via ``scripts/parse_coverage.py --accept-probe``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_parse_coverage():
    spec = importlib.util.spec_from_file_location(
        "parse_coverage", REPO_ROOT / "scripts" / "parse_coverage.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_supported_card_text_is_claimed_or_acknowledged():
    pc = _load_parse_coverage()
    coverages = pc.analyze_pool()
    unclaimed, stale_ack, new_probe, stale_probe = pc.collect_findings(coverages)

    assert not unclaimed, (
        "supported cards with oracle text nothing parses or claims — fix the "
        "parser, add the implementing channel to CHANNELS, or acknowledge the "
        f"simplification in ACKNOWLEDGED: {unclaimed}"
    )
    assert not stale_ack, (
        f"ACKNOWLEDGED entries that no longer occur — remove them: {stale_ack}"
    )
    assert not new_probe, (
        "a parse rule matched these clauses while ignoring words it used to "
        "consume (or the clause is new) — review for silently-dropped riders, "
        "then fix the rule or run scripts/parse_coverage.py --accept-probe: "
        f"{dict(list(new_probe.items())[:5])}"
    )
    assert not stale_probe, (
        "probe-baseline entries that no longer occur — rerun "
        f"scripts/parse_coverage.py --accept-probe: {stale_probe[:5]}"
    )


def test_validator_detects_a_silently_dropped_sentence():
    """Self-test: the machinery must flag a card whose text only half-parses,
    otherwise the green guard above proves nothing."""
    pc = _load_parse_coverage()
    from engine.models import CardDefinition

    fake = CardDefinition(
        name="Coverage Self-Test",
        mana_cost="{1}",
        cmc=1.0,
        type_line="Sorcery",
        oracle_text="Destroy target creature. Flurble the wumbus.",
        colors=("B",),
        color_identity=("B",),
        keywords=(),
        produced_mana=(),
        raw={"name": "Coverage Self-Test", "type_line": "Sorcery"},
    )
    coverage = pc.analyze_card(fake, hooked=set())
    assert coverage.unclaimed == ["flurble the wumbus"]
    assert any("destroy_target_permanent" in channel for _, channel in coverage.claims)


def test_deletion_probe_flags_ignored_rider_words():
    """Self-test: the probe must catch a rider a broad rule swallows — the
    exact Hasran Ogress bug shape."""
    pc = _load_parse_coverage()
    ignored = pc._probe("destroy target creature unless its controller pays {4}", activated=False)
    assert "unless" in ignored
    assert "pays" in ignored
