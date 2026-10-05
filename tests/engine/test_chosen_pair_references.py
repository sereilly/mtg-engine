"""A chosen pair and the three ways a later sentence names its members.

"Choose two target creatures controlled by the same player. **Their
controller** chooses and sacrifices **one of them**. Return **the other** to
its owner's hand." (Barrin's Spite.) Retribution (HML) and Cannibalize (STH)
print the same resolution as "that player", "one of those creatures" and "put a
counter on the other". Each back-reference reads a *record* an earlier step of
the same resolution wrote, and each is refused by name where no step wrote it —
these tests hold both halves, on sentences no card prints.
"""

from __future__ import annotations

import pytest

from engine.grammar import ast
from engine.grammar.errors import GrammarError, LoweringError
from engine.grammar.parser import parse_line
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card

_PAIR = "Choose two target creatures controlled by the same player."


def _kinds(text: str) -> list[str]:
    program = compile_card_oracle(
        _mk_card(name="Probe", mana_cost="{1}", type_line="Sorcery", oracle_text=text)
    )
    assert program.supported, text
    (sequence,) = program.instructions
    return [step.kind for step in sequence.payload["steps"]]


def _refused(text: str) -> bool:
    return not compile_card_oracle(
        _mk_card(name="Probe", mana_cost="{1}", type_line="Sorcery", oracle_text=text)
    ).supported


@pytest.mark.parametrize("seat", ["That player", "Their controller"])
@pytest.mark.parametrize("member", ["one of those creatures", "one of them"])
def test_both_names_for_the_seat_and_both_for_the_member_are_one_reading(seat, member):
    kinds = _kinds(
        f"{_PAIR} {seat} chooses and sacrifices {member}. Put a -1/-1 counter on the other."
    )
    assert kinds == [
        "choose_target_permanents", "choose_permanent",
        "sacrifice_recorded_permanent", "add_counter_to_target",
    ]


def test_one_of_them_carries_no_noun_and_is_the_same_quantifier():
    node = parse_line("That player chooses and sacrifices one of them.", card_name="Probe")
    subject = node.statement.subject
    assert subject.quantifier == "one_of_those"
    assert subject.filter == ast.ObjectFilter()
    assert not subject.targeted


def test_the_other_is_bounced_from_the_record_the_pick_left():
    program = compile_card_oracle(_mk_card(
        name="Probe", mana_cost="{1}", type_line="Sorcery",
        oracle_text=f"{_PAIR} That player chooses and sacrifices one of those "
                    "creatures. Return the other to its owner's hand.",
    ))
    (sequence,) = program.instructions
    last = sequence.payload["steps"][-1]
    assert last.kind == "return_recorded_permanents_to_hand"
    assert last.payload == {"permanents_from": "other_chosen_permanent"}


@pytest.mark.parametrize("text", [
    # No step chose a pair: "the other" and "one of them" name nothing.
    "Return the other to its owner's hand.",
    "Their controller chooses and sacrifices one of them.",
    # A seat the choosing sentence did not name. This fell through to the
    # generic sacrifice, which read the quantifier as "a" and offered the whole
    # board — a wider sacrifice than any card printing the phrase could mean.
    f"{_PAIR} Target player sacrifices one of those creatures.",
    "Sacrifice one of them.",
    # The other half of the pair goes to its owner's hand and nowhere else.
    f"{_PAIR} Their controller chooses and sacrifices one of them. Return the other to the battlefield.",
    f"{_PAIR} Their controller chooses and sacrifices one of them. Return the other to your hand.",
])
def test_a_reference_nothing_recorded_is_refused_by_name(text: str):
    assert _refused(text)


def test_one_of_them_is_only_the_end_of_its_clause():
    """"Put one of them into your hand" is the library family's sentence; the
    shared reader must not take three words of it."""
    with pytest.raises((GrammarError, LoweringError)):
        parse_line("Their controller sacrifices one of them into your hand.", card_name="Probe")
