"""What the "instead" rider and the conditional-choice fold admit, and what
they still refuse (JUD W1G7).

Judgment widened two readers in ``engine/grammar``: the rider that folds
"A. If <cond>, B instead." into one ``Conditional``
(``conditional_instead.py`` — token pairs, return pairs, and another verb done
to the replaced sentence's one target), and the branch reader that hangs the
sentence reading "the chosen color" on the conditional arm that chose it
(``control_flow._attach_to_conditional_choice``). Each widening is one card's
worth of words; these are the neighbouring sentences each must keep
refusing, checked on invented text so no card has to print them.

Pool-wide and about the grammar, which is why it is not a per-set test.
"""

from __future__ import annotations

import pytest

from engine.grammar import ast, compile_line, parse_line
from engine.grammar.errors import GrammarError

_THRESHOLD = "there are seven or more cards in your graveyard"


def _statement(line: str):
    return parse_line(line).statement


def test_another_verb_on_the_replaced_target_folds_into_one_conditional():
    """Toxic Stench's shape: one announced creature, pumped or destroyed."""
    node = _statement(
        "Target nonblack creature gets -1/-1 until end of turn. "
        f"If {_THRESHOLD}, instead destroy that creature. It can't be regenerated."
    )
    assert isinstance(node, ast.Conditional)
    assert isinstance(node.then, ast.Destroy) and node.then.no_regen
    assert isinstance(node.otherwise, ast.Pump)
    assert node.then.subject == node.otherwise.subject
    assert node.then.subject.targeted


@pytest.mark.parametrize(
    "replacement",
    [
        # A target of its own: an announcement only one arm could use.
        "instead destroy target creature",
        # A noun the replaced target need not be.
        "instead destroy that artifact",
        # Another kind of object entirely — a spell is not the creature.
        "instead counter that spell",
    ],
)
def test_another_verb_refuses_what_is_not_the_same_target(replacement):
    with pytest.raises(GrammarError):
        parse_line(
            "Target creature gets -1/-1 until end of turn. "
            f"If {_THRESHOLD}, {replacement}."
        )


def test_a_token_pair_folds_and_keeps_the_casters_tokens():
    """Grizzly Fate's shape: the two counts are one effect, the bigger only
    with threshold, and no recipient appears in either arm."""
    node = _statement(
        "Create two 2/2 green Bear creature tokens. Create four 2/2 green Bear "
        f"creature tokens instead if {_THRESHOLD}."
    )
    assert isinstance(node, ast.Conditional)
    assert node.then.count == ast.Fixed(4) and node.otherwise.count == ast.Fixed(2)
    assert node.then.recipient is None and node.otherwise.recipient is None


def test_a_return_pair_names_the_one_card_target():
    """Stitch Together's "that card" restates the card the first sentence
    targeted, so both arms move that card."""
    node = _statement(
        "Return target creature card from your graveyard to your hand. Return "
        f"that card from your graveyard to the battlefield instead if {_THRESHOLD}."
    )
    assert isinstance(node, ast.Conditional)
    assert node.then.subject == node.otherwise.subject
    assert node.then.subject.targeted and node.then.subject.filter.zone == "graveyard"
    assert node.then.to.name == "battlefield" and node.otherwise.to.name == "hand"


def test_a_choice_arm_takes_the_sentence_that_reads_it():
    """Aven Warcraft's threshold paragraph: the grant of protection from the
    chosen colour is inside the arm that chose it, and lowers inside it."""
    line = (
        f"If {_THRESHOLD}, choose a color. Creatures you control also gain "
        "protection from the chosen color until end of turn."
    )
    node = _statement(line)
    assert isinstance(node, ast.Conditional)
    assert isinstance(node.then, ast.Sequence)
    assert [type(step).__name__ for step in node.then.steps] == [
        "ChooseColor", "GainKeyword",
    ]
    (instruction,) = compile_line(line).instructions
    assert instruction.kind == "if_then"
    assert [step.kind for step in instruction.payload["then"]] == [
        "choose_color", "grant_team_keyword_until_eot",
    ]
    assert instruction.payload["else"] == ()


def test_a_choice_arm_does_not_take_a_sentence_that_reads_nothing_it_chose():
    """"Draw a card" after the same choice is a step of its own: it reads no
    chosen value, so it happens whether or not the condition held."""
    node = _statement(f"If {_THRESHOLD}, choose a color. Draw a card.")
    assert isinstance(node, ast.Sequence)
    assert isinstance(node.steps[0], ast.Conditional)
    assert isinstance(node.steps[0].then, ast.ChooseColor)
    assert isinstance(node.steps[1], ast.Draw)


def test_also_is_read_only_in_front_of_a_grant_verb():
    """"also" adds nothing in front of "gain"/"get", and is not consumed in
    front of any other verb, where it would be a word left unread."""
    assert parse_line("Creatures you control also gain flying until end of turn.")
    with pytest.raises(GrammarError):
        parse_line("Target player also draws a card.")
