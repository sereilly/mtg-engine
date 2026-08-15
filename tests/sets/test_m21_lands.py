"""Core Set 2021 (M21) lands.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it. The round each section names is written up in
ROADMAP.md; a round's cards are split across these files by the printed type of
the card each test is about.
"""

from __future__ import annotations

from engine.oracle import compile_card_oracle


def test_temple_of_mystery_etb_scry_is_claimed(set_pool):
    program = compile_card_oracle(set_pool("M21")["Temple of Mystery"])
    assert any(
        t.instruction is not None and t.instruction.kind == "scry"
        for t in program.triggered_abilities
    )
