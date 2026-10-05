"""``<subject> A, B, and C`` — one noun phrase and a list of things said about it.

Invasion's Defiling Tears is the pool's first effect sentence printed this way
("Until end of turn, target creature becomes black, gets +1/-1, and gains
"{B}: Regenerate this creature.""), and the spelling is the ordinary one in
every set after it. The production is ``conjuncts._with_predicate_list``; these
tests are about the *production*, on sentences no card in the pool prints, so a
second card gets the reading the first one bought.
"""

from __future__ import annotations

import pytest

from engine.grammar import ast
from engine.grammar.errors import GrammarError
from engine.grammar.parser import parse_line


def _list_members(line: str) -> tuple:
    node = parse_line(line, card_name="Probe")
    statement = node.statement
    assert isinstance(statement, ast.Conjunction), statement
    return statement.effects


def test_a_three_member_list_is_one_conjunction_about_one_subject():
    members = _list_members(
        "Target creature gets +2/+2, gains trample, and becomes blue until end of turn."
    )
    assert [type(member) for member in members] == [
        ast.Pump, ast.GainKeyword, ast.BecomeColor,
    ]
    # One printed subject: every member is about the same noun phrase.
    assert len({member.subject for member in members}) == 1


def test_a_trailing_duration_governs_every_member_of_the_list():
    """CR 611.2a: the window is printed once, behind the last member, and the
    whole effect ends together. A member left without it would be permanent."""
    members = _list_members(
        "Target creature gets +2/+2, gains trample, and becomes blue until end of turn."
    )
    assert [member.duration.kind for member in members] == ["until_end_of_turn"] * 3


def test_a_fronted_duration_reaches_every_member_of_the_list():
    members = _list_members(
        "Until end of turn, target creature becomes black, gets +1/-1, and gains flying."
    )
    assert [type(member) for member in members] == [
        ast.BecomeColor, ast.Pump, ast.GainKeyword,
    ]
    assert [member.duration.kind for member in members] == ["until_end_of_turn"] * 3


def test_a_quoted_ability_is_a_list_member():
    members = _list_members(
        'Until end of turn, target creature gets +1/-1, gains flying, and gains "{B}: Regenerate this creature."'
    )
    assert isinstance(members[-1], ast.GainAbilityText)
    assert members[-1].abilities == ("{B}: Regenerate this creature",)


@pytest.mark.parametrize("line", [
    # The list never closes with ", and": two members and a stranded third.
    "Target creature gets +2/+2, gains trample, becomes blue until end of turn.",
    # The verb is the list's and the sentence is about a player: a permanent's
    # noun phrase cannot be the subject of a life gain.
    "Target creature gets +2/+2, gains trample, and gains 3 life.",
    # A member the list cannot read takes the whole line down rather than
    # leaving the first two as the card.
    "Target creature gets +2/+2, gains trample, and becomes a frog.",
])
def test_a_list_that_does_not_close_is_refused_whole(line: str):
    with pytest.raises(GrammarError):
        parse_line(line, card_name="Probe")


def test_a_comma_that_continues_into_another_subject_is_not_a_list():
    """", and you gain 1 life" is a second clause about a player, not a third
    predicate of the creature — the list reader declines without consuming and
    the sentence keeps the reading it already had."""
    node = parse_line(
        "Target creature gets +1/+1 until end of turn, and you gain 1 life.",
        card_name="Probe",
    )
    steps = node.statement.steps
    assert [type(step) for step in steps] == [ast.Pump, ast.GainLife]
    assert steps[1].player == ast.PlayerRef("you")


def test_a_pump_joined_to_a_quoted_grant_shares_the_window_either_way_round():
    """"gets +1/-1 and gains "…"" — the quote arm of the pump's own join, the
    same reader ``_parse_gains`` uses on the other side of the conjunction."""
    trailing = _list_members(
        'Target creature gets +1/-1 and gains "{B}: Regenerate this creature." until end of turn.'
    )
    fronted = _list_members(
        'Until end of turn, target creature gets +1/-1 and gains "{B}: Regenerate this creature."'
    )
    for members in (trailing, fronted):
        assert [type(member) for member in members] == [
            ast.Pump, ast.GainAbilityText,
        ]
        assert [member.duration.kind for member in members] == [
            "until_end_of_turn"
        ] * 2
