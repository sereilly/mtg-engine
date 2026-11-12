"""``scripts/probe_line.py`` — why is this line refused, layer by layer.

The probe reads every verdict off the compiler's own run (its readers
observed, never re-implemented), so what these tests hold is the reading:
that a line is pinned to the layer that refused it, and that observing the
compile changes nothing about it. Three shapes, one per kind of site — a line
the compiler reads, a line the grammar refuses, and a line a table refuses
while the grammar reads it — and the census rows built from them
(``support_report.refusals_report``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import probe_line  # noqa: E402
import support_report  # noqa: E402

from engine import ability_lines, trigger_conditions  # noqa: E402
from engine import grammar as grammar_package  # noqa: E402
from engine.card_loader import load_cards, manifest_set_paths  # noqa: E402
from engine.grammar import LoweringError, compile_line  # noqa: E402
from engine.line_normalization import normalize_creature_line  # noqa: E402
from engine.oracle import compiled_units  # noqa: E402
from tests.helpers import stable_sample  # noqa: E402


def _only_line(reports):
    (unit,) = reports
    (line,) = unit.lines
    return unit, line


def test_every_reader_the_probe_observes_exists():
    """A reader renamed or moved is a layer the probe silently stops seeing."""
    assert probe_line.resolve_readers()[1] == []


def test_a_supported_card_reads_accepted_with_the_kinds_it_compiled_to(catalog_by_name):
    unit, line = _only_line(probe_line.probe_card(catalog_by_name["Prodigal Sorcerer"]))

    assert unit.supported and unit.trace_matches_cache
    assert line.verdict.accepted
    assert line.verdict.layer == "activated ability"
    assert line.verdict.kinds == ["deal_damage"]
    assert line.handlers == [{"kind": "deal_damage", "handler": True, "category": "damage"}]
    assert probe_line.census_site(line) == ("clean", "")
    # The trace is the compiler's own order: the activated reader handed the
    # line on to the front ends, which asked the grammar.
    readers = [row["reader"] for row in line.consulted]
    assert readers.index("_parse_activated_ability") < readers.index("_line_instruction")


def test_a_raw_line_the_grammar_refuses_is_refused_at_the_grammar_with_its_furthest_production():
    card = probe_line.invented_card(["Frobnicate the gribble until morning."], None, "Probe Grammar Gap")
    unit, line = _only_line(probe_line.probe_card(card))

    assert not unit.supported
    assert line.verdict.layer == "grammar"
    assert line.verdict.reason == line.grammar.parse_error
    assert line.grammar.furthest is not None and line.grammar.furthest.total > 0
    # The census keeps a grammar refusal's message verbatim: the key the
    # refusal rollup has always grouped by.
    assert probe_line.census_site(line) == ("refused", line.grammar.parse_error)


def test_a_line_a_card_gate_refuses_names_the_gate_and_the_rest_is_still_read():
    """A gate refuses before any line is classified, so the line after it is
    read by compiling the card again without the refused one."""
    card = probe_line.invented_card(
        ["As an additional cost to cast this spell, frobnicate a gribble.", "Draw a card."],
        "Sorcery", "Probe Cost Gap",
    )
    (unit,) = probe_line.probe_card(card)
    cost, draw = unit.lines

    assert cost.verdict.layer == "card gate: uncharged cost"
    assert probe_line.census_site(cost)[1].startswith("card gate: uncharged cost: ")
    assert draw.round == 2 and draw.removed == [cost.text]
    assert draw.verdict.accepted and draw.verdict.kinds == ["draw_controller_cards"]


def test_a_line_the_trigger_table_refuses_names_the_table_not_a_production(monkeypatch):
    """The grammar reads the line as a trigger and the trigger-condition table
    has no row for its condition: the census used to call that line clean (the
    grammar reads it) and ``furthest.py`` to skip it. The table is made to
    refuse here, so the test is about the probe's reading rather than about
    which rows the table has today."""
    line = "Whenever this creature attacks, you gain 2 life."
    real = trigger_conditions.trigger_condition_of_line

    def no_row(text, card_name=None):
        if text.strip() == line:
            return None, normalize_creature_line(text)
        return real(text, card_name)

    monkeypatch.setattr(trigger_conditions, "trigger_condition_of_line", no_row)
    monkeypatch.setattr(ability_lines, "trigger_condition_of_line", no_row)
    card = probe_line.invented_card([line], None, "Probe Table Gap")
    unit, report = _only_line(probe_line.probe_card(card))

    assert not unit.supported
    assert report.grammar.node == "TriggeredAbilityNode" and report.grammar.usable
    assert report.verdict.layer == "trigger-condition table"
    status, detail = probe_line.census_site(report)
    assert status == "refused" and detail.startswith("trigger-condition table: ")

    ((name, _type, headline, rows),) = support_report.refusals_report([card])
    assert name == "Probe Table Gap" and "too complex" in headline
    assert rows == [("refused", line, detail)]


def test_observing_the_compiler_leaves_every_binding_as_it_found_it():
    from engine import front_ends, grammar

    before = (ability_lines._parse_triggered_ability, front_ends._line_instruction,
              front_ends.compile_grammar_line, grammar.compile_line)
    with probe_line.observing():
        assert front_ends._line_instruction is not before[1]
    assert (ability_lines._parse_triggered_ability, front_ends._line_instruction,
            front_ends.compile_grammar_line, grammar.compile_line) == before


def test_the_probe_agrees_with_the_compiler_across_the_pool():
    """Both manifest roles, a sixteenth of the units in the quick pass and all
    of them in the full one (~35 s). Observing the compile changes nothing
    (the traced program is the cached one); the probe's card verdict is the
    compiler's; a supported creature, land or planeswalker — whose loops refuse
    the card at any line nothing reads — has every line accepted, which is
    what catches a loop-level reader :data:`probe_line.READERS` does not
    observe; and a line an unsupported card's reason quotes is refused."""
    units = compiled_units(load_cards(manifest_set_paths(include_measured=True)))
    sampled = [(unit, program) for unit, program in units if stable_sample(unit.name, 16)]
    assert len(sampled) > 100
    problems = []
    with probe_line.observing():
        for unit, program in sampled:
            report = probe_line.probe_unit(unit)
            if not report.trace_matches_cache or report.supported != program.supported:
                problems.append(f"{unit.name}: traced compile differs from the compiler's")
            if program.supported and unit.primary_type in ("creature", "land", "planeswalker"):
                problems += [f"{unit.name}: {line.text!r} {line.verdict}"
                             for line in report.refused_lines]
            if not program.supported:
                quoted = probe_line._names_line(program.reason, [l.text for l in report.lines])
                if quoted is not None and report.lines[quoted].verdict.accepted:
                    problems.append(f"{unit.name}: the reason quotes an accepted line")
    assert not problems, problems[:20]


@pytest.mark.parametrize("argv", [
    ["--card", "Prodigal Sorcerer"],
    ["--card", "Prodigal Sorcerer", "--json"],
    ["Frobnicate the gribble until morning.", "--full"],
    ["Draw two cards. You lose 2 life.", "--ast"],
    ["--card", "Prodigal Sorcerer", "--json", "--ast"],
])
def test_the_command_line_runs(argv, capsys):
    assert probe_line.main(argv) == 0
    assert capsys.readouterr().out.strip()


# ---------------------------------------------------------------------------
# Where a lowering refused, and the parsed tree (--ast)
# ---------------------------------------------------------------------------

def _refuse_inside():
    raise LoweringError("the innermost reason")


def test_a_lowering_refusal_names_the_innermost_raise_and_the_chain(monkeypatch):
    """The message ``compile_line`` reports is the outermost refusal's; the
    site is where the innermost was raised — the furthest frame of a parse,
    or the last refusal's message, misled three Darksteel groups."""
    def lowering(node, *, event=None):
        try:
            _refuse_inside()
        except LoweringError:
            raise LoweringError("the reported reason")

    monkeypatch.setattr(grammar_package, "lower_ability", lowering)
    verdict = probe_line.grammar_verdict("Draw a card.", None)

    assert verdict.lowering_error == "the reported reason"
    refusal = verdict.lowering
    assert refusal.chain == ["the reported reason", "the innermost reason"]
    assert refusal.message == "the innermost reason"
    assert refusal.site.startswith("tests/engine/test_probe_line.py:")
    assert refusal.site.endswith("(_refuse_inside)")
    # The watch is gone again: the grammar's name is the patched one, unwrapped.
    assert grammar_package.lower_ability is lowering

    text = probe_line.render_text(probe_line.probe_card(
        probe_line.invented_card(["Draw a card."], "Sorcery", "Probe Lowering Site")))
    assert "lowering: error: the reported reason" in text
    assert f"raised at {refusal.site}" in text
    assert "innermost of 2 chained: 'the innermost reason'" in text


def test_the_watch_sees_compile_line_s_own_call():
    """The watch rebinds ``engine.grammar.lower_ability``; that is only the
    lowering ``compile_line`` runs while it reads the name from its package."""
    from engine.grammar import lower

    assert "lower_ability" in compile_line.__code__.co_names
    assert compile_line.__globals__ is vars(grammar_package)
    assert grammar_package.lower_ability is lower.lower_ability


def test_ast_prints_each_node_with_the_fields_it_sets_and_each_sentence_alone():
    card = probe_line.invented_card(["Draw two cards. You lose 2 life."], "Sorcery", "Probe Ast")
    reports = probe_line.probe_card(card)
    probe_line.attach_ast(reports)
    (line,) = reports[0].lines

    whole, *alone = line.ast
    assert not whole["alone"] and whole["ast"]["node"] == "SpellEffectLine"
    assert [reading["text"] for reading in alone] == ["Draw two cards.", "You lose 2 life."]
    assert all(reading["alone"] and reading["ast"] for reading in alone)

    text = probe_line.render_text(reports)
    assert "      ast:\n        SpellEffectLine\n          statement: " in text
    assert "sentence 2 of 2, asked alone (out of its context: a lead): 'You lose 2 life.'" in text
    (record,) = json.loads(probe_line.render_json(reports))
    assert record["lines"][0]["ast"][0]["ast"] == whole["ast"]


def test_a_field_at_its_default_is_left_out_of_the_tree():
    from dataclasses import dataclass, field as dc_field

    @dataclass(frozen=True)
    class Leaf:
        word: str
        count: int = 0
        tags: tuple = dc_field(default_factory=tuple)

    @dataclass(frozen=True)
    class Root:
        leaves: tuple
        flag: bool = False

    tree = probe_line.ast_dict(Root((Leaf("a"), Leaf("b", 2, ("x",)))))
    assert tree == {"node": "Root", "leaves": [{"node": "Leaf", "word": "a"},
                                               {"node": "Leaf", "word": "b", "count": 2, "tags": ["x"]}]}
    assert probe_line.ast_lines(tree) == [
        "Root", "  leaves: (2)", "    [0] Leaf", "      word: 'a'",
        "    [1] Leaf", "      word: 'b'", "      count: 2", "      tags: ('x',)",
    ]


def test_sentences_are_never_cut_inside_a_quoted_ability_or_reminder_text():
    line = 'Equipped creature has "{T}: Draw a card. Scry 1." (It may. Or not.) Draw a card.'
    assert probe_line.sentences(line) == [
        'Equipped creature has "{T}: Draw a card. Scry 1." (It may. Or not.)', "Draw a card.",
    ]
    # Reminder text after a sentence's full stop stays with that sentence.
    assert probe_line.sentences("Draw a card. (A reminder. Of two.) Scry 1.") == [
        "Draw a card. (A reminder. Of two.)", "Scry 1.",
    ]
