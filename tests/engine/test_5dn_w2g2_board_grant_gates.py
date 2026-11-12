"""Both support gates ask one question of a board-wide grant: does the quoted
text compile?

"Each creature has "…"" is ``global_statics``' board-wide grant, claimed by
two gates — ``derived_static_claims`` for a noncreature card and
``static_line_support._is_supported_static_creature_line`` for a creature.
Fifth Dawn's wave 1 (W1G3) made the first ask ``granted_ability_supported``
after Endless Whispers reported supported with a grant that compiled to
nothing; the creature gate still took the template's word. So a creature
printing an uncompilable grant reported supported, and ``probe_line`` — which
asks the creature gate of every static line — called Endless Whispers' line
accepted while the compiler refused it (the promotion rehearsal's
``test_the_probe_agrees_with_the_compiler_across_the_pool`` red, "the reason
quotes an accepted line"). Both gates now ask
``global_statics.global_static_implemented``.

Validated backwards: with ``static_line_support`` as it was, the invented
creature below reports "simple creature support" with the probe saying
"accepted (static-line tables)", and the invented enchantment's probe verdict
is "accepted (static text, read outside the compile)" against the compiler's
refusal.
"""

from __future__ import annotations

from engine.global_statics import global_static_implemented
from engine.oracle import compile_card_oracle
from scripts import probe_line
from tests.helpers import _mk_card, _mk_creature_card

_UNREAD = 'Each creature has "When this creature dies, frobnicate the gribble until morning."'
_READ = 'Each creature has "When this creature dies, you gain 1 life."'


def test_an_uncompilable_board_wide_grant_is_not_implemented():
    assert global_static_implemented(_READ)
    assert not global_static_implemented(_UNREAD)
    assert not global_static_implemented("Frobnicate the gribble.")


def test_a_creature_printing_an_uncompilable_grant_is_refused():
    creature = _mk_creature_card("W2G2 Whisperer", 1, 1, _UNREAD)
    program = compile_card_oracle(creature)
    assert not program.supported, program.reason
    assert compile_card_oracle(_mk_creature_card("W2G2 Chanter", 1, 1, _READ)).supported


def test_the_probe_agrees_with_both_gates_on_a_board_wide_grant():
    for unit in (
        _mk_creature_card("W2G2 Whisperer", 1, 1, _UNREAD),
        _mk_card("W2G2 Hymn", "{2}{B}", "Enchantment", _UNREAD),
    ):
        program = compile_card_oracle(unit)
        with probe_line.observing():
            report = probe_line.probe_unit(unit)
        assert report.supported == program.supported is False
        assert [line.verdict.accepted for line in report.lines] == [False]
