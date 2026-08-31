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
        "[UNCLAIMED] supported cards with oracle text nothing parses or claims — fix the "
        "parser, add the implementing channel to CHANNELS, or acknowledge the "
        f"simplification in ACKNOWLEDGED: {unclaimed}"
    )
    assert not stale_ack, (
        f"[STALE-ACK] ACKNOWLEDGED entries that no longer occur — remove them: {stale_ack}"
    )
    assert not new_probe, (
        "[PROBE] a parse rule matched these clauses while ignoring words it used to "
        "consume (or the clause is new) — review for silently-dropped riders, "
        "then fix the rule or run scripts/parse_coverage.py --accept-probe: "
        f"{dict(list(new_probe.items())[:5])}"
    )
    assert not stale_probe, (
        "[STALE-PROBE] probe-baseline entries that no longer occur — rerun "
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
        # Two lines, not two sentences on one line. With both on one line the
        # trailing nonsense stops the first clause parsing at all, so the card
        # compiles to a bare `spell_pattern` marker — and the compiler now
        # refuses to call such a spell supported, which would make this
        # self-test unreachable rather than failing. Separate lines give the
        # shape it means to test: a card that really is supported and really
        # does carry a sentence nothing claims.
        oracle_text="Destroy target creature.\nFlurble the wumbus.",
        colors=("B",),
        color_identity=("B",),
        keywords=(),
        produced_mana=(),
        raw={"name": "Coverage Self-Test", "type_line": "Sorcery"},
    )
    coverage = pc.analyze_card(fake, hooked=set())
    assert coverage.unclaimed == ["flurble the wumbus"]
    assert any("destroy_target_permanent" in channel for _, channel in coverage.claims)


def test_deletion_probe_flags_a_word_the_parse_does_not_carry():
    """Self-test: the probe must still find a word whose deletion changes nothing.

    Its old self-test appended nonsense to a clause ("…when the wumbus
    flurbles") and checked that a substring rule swallowed it. That shape is
    **gone**, not merely unused: with one full-consumption parser a trailing
    word nothing accounts for fails the line outright, so the probe returns
    nothing and the assertion could never fire again. A self-test that cannot
    fail is worse than none.

    The bug class that survives is narrower and real: a word the parser
    *consumes* but whose meaning never reaches the payload. "Destroy all
    creatures" is one — the sweep comes from the plural noun, so deleting "all"
    lowers identically. That is benign here, and it is the same probe result a
    dropped rider would produce, which is what makes it a fair exercise of the
    machinery.

    If a production ever makes "all" load-bearing this fails, and the
    replacement is any live entry in
    ``scripts/parse_coverage_probe_baseline.json``.
    """
    pc = _load_parse_coverage()
    assert "all" in pc._probe("destroy all creatures", activated=False)


def test_deletion_probe_is_silent_when_every_word_is_load_bearing():
    """The other direction, without which the test above proves only that the
    probe returns *something*."""
    pc = _load_parse_coverage()
    assert pc._probe("destroy target black creature", activated=False) == ()


def test_grammar_refuses_the_rider_shape_instead_of_swallowing_it():
    """The structural half of the same guarantee.

    The probe detects a swallowed rider after the fact; the grammar's
    full-token-consumption rule prevents one. A clause whose trailing words the
    grammar cannot account for is refused, so there is nothing for the probe to
    find.

    The refusal moved one layer down when Erosion printed this shape about a
    seat the offer *can* name ("…unless **that player** pays {1} or 1 life"):
    the destroy family reads the tail now, and what refuses an unresolvable
    payer is ``lowering/control_flow.OFFERABLE_ACTORS`` — the references
    ``handlers/control_flow._offered_seats`` can actually resolve. That is a
    strictly better refusal for the bug class this file guards, because it names
    the payer rather than reporting unconsumed text, and it claims nothing:
    ``scripts/parse_coverage.py`` reads ``usable``, which a lowering refusal
    leaves False. So both halves are asserted — the line is unusable, and the
    reason says which word it could not honour.

    The example is "an opponent" rather than "its controller", which used to
    stand here: Essence Vortex made the controller resolvable, by reading the
    seat off the targeted permanent through the control seam. The refusal is the
    point, not which word triggers it, and the assertion below keeps both — the
    payer this engine *can* name lowers, and the one it cannot still refuses.

    The word the refusal names changed from ``target_opponent`` to ``opponent``
    when Amulet of Quoz printed "**target** opponent may …": the reference
    reader had been giving both spellings one kind, so admitting the chosen seat
    would have admitted the article too. "An opponent" chooses nobody
    (CR 601.2c) and still has no offerable seat, which is why the refusal is
    unchanged in everything but the word it quotes.
    """
    from engine.grammar import compile_line

    result = compile_line("Destroy target creature unless an opponent pays {4}.")
    assert not result.usable
    assert not result.lowered
    assert "'opponent'" in (result.lowering_error or ""), result.lowering_error

    resolvable = compile_line(
        "Destroy target creature unless its controller pays {4}."
    )
    assert resolvable.usable
    assert resolvable.instructions[0].payload["actor"] == "controller"


def test_the_gate_is_the_shipped_pool_and_measured_sets_are_reported():
    """The instrument reads every supported card; only the shipped half gates.

    It used to read `manifest_set_paths()` — the shipped pool — so a *supported*
    card in a measured set was outside the one check that fails when a card
    compiles with a printed line nothing implements. Ice Age's Snowfall was
    counted done on the strength of its cumulative upkeep alone, with a whole
    paragraph compiling to nothing at all, and no instrument in the repo could
    see it: `--hollow-lines` finds only lines that produced an *ability part*.

    Gating on a measured set instead would make every ingest red on arrival,
    which is why `GRAMMAR_COVERAGE.md`'s floors and `HOOK_RELIANCE.md`'s
    ceilings exclude the same sets. So both halves are asserted: the instrument
    reads the measured role, and nothing in that role reaches the gate.

    **The first half is asserted directly rather than through a measured card**,
    because the `measured` role is legitimately empty between sets — it was
    empty before Ice Age was ingested and it is empty again now that Ice Age
    ships. This guard used to look for a card that is not shipped and fail when
    it found none, which reads "the instrument stopped watching" when the truth
    is "there is nothing to watch". That is the proxy trap SET_PLAYBOOK.md
    records from the 4ED promotion: a guard that checks a symptom needs the
    symptom's availability asserted too, and the fix is to assert the invariant
    instead. The invariant is that `CARD_PATHS` is built over both manifest
    roles, which is checkable whatever those roles contain.
    """
    from engine.card_loader import manifest_set_paths

    pc = _load_parse_coverage()

    assert set(pc.CARD_PATHS) == set(manifest_set_paths(include_measured=True)), (
        "parse coverage stopped reading both manifest roles — CARD_PATHS lost "
        "include_measured=True, and the instrument is back to watching only "
        "the shipped pool"
    )

    coverages = pc.analyze_pool(run_probe=False)
    measured = [c for c in coverages if not c.shipped]
    if not measured:
        # No set is being measured right now. The invariant above still holds,
        # and the assertions below have nothing to range over.
        return

    unclaimed, _stale_ack, _new_probe, _stale_probe = pc.collect_findings(coverages)
    gated = {name for name, _ in unclaimed}
    measured_names = {c.name for c in measured}
    assert not (gated & measured_names), (
        f"measured cards reached the gate: {sorted(gated & measured_names)}"
    )

    backlog = pc.collect_measured_findings(coverages)
    assert all(name in measured_names for name, _ in backlog)
