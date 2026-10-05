"""Pool-wide: a ``choose_one`` is asked on the stack only when its ability is
printed **modal** (CR 700.2 — a bulleted list), and at resolution otherwise
(CR 608.2d).

Both shapes lower onto the one ``choose_one`` kind, and the push path
(``_choose_trigger_mode``) asks the question its gate answers —
``modal_triggers.modal_trigger_modes`` — at activation or trigger time. That
gate read the kind alone, so every top-level "A or B" in the pool was asked
too early: seven activated abilities and two upkeep triggers (W2G5's census).
This holds the gate to the printed form across the whole pool, both manifest
roles, so a new production that lowers an "or" onto the kind cannot quietly
re-open it — and a new modal head that forgets the mark fails here too.

The floor is the census's own size on the tree it was validated against: run
before the fix it named all nine abilities as asked-at-push and non-modal.
"""

from __future__ import annotations

from engine.faces import compilation_units
from engine.card_loader import load_cards, manifest_set_paths
from engine.modal_triggers import MODAL_INSTRUCTION_KIND, modal_trigger_modes
from engine.oracle import compile_card_oracle


def _w2g5_top_level_choices():
    examined = 0
    rows = []
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for ability in (*program.activated_abilities, *program.triggered_abilities):
            instruction = ability.instruction
            if instruction is None:
                continue
            examined += 1
            if instruction.kind != MODAL_INSTRUCTION_KIND:
                continue
            printed_modal = "•" in (ability.source_line or "")
            asked_at_push = bool(modal_trigger_modes(instruction))
            rows.append((card.name, printed_modal, asked_at_push))
    return examined, rows  # _w2g5_top_level_choices


def test_only_a_bulleted_ability_chooses_as_it_goes_on_the_stack():
    examined, rows = _w2g5_top_level_choices()

    wrong = [
        (name, "modal, asked at resolution" if printed else "not modal, asked on the stack")
        for name, printed, asked in rows
        if printed != asked
    ]
    assert wrong == []
    # The floor: the census examined the pool, and found both shapes.
    assert examined >= 3000, examined
    assert sum(1 for _, printed, _ in rows if not printed) >= 9
    assert sum(1 for _, printed, _ in rows if printed) >= 3
