"""The colour-census conditions consume their whole clause or refuse.

"The most common color among all permanents" is printed with a tail that says
what a level board means — "or is tied for most common" on the Invasion Djinns,
"or a color tied for most common" on Barrin's Unmaking and Tsabo's Assassin,
"but isn't tied for most common" on Call to Arms' narrower clause — and with a
scope that says what is counted. A reader that stopped at the superlative would
be choosing both for the card, so each half is required and what the production
does with a sentence missing one is asserted here rather than left to the cards
that happen to print all of it.

The seat-negated controls clause ("no opponent controls …") is held the same
way: it is `each_opponent` with a count of zero and nothing else.
"""

from __future__ import annotations

import pytest

from engine.grammar import compile_line


def _lowered(line: str):
    result = compile_line(line, card_name="Census Probe")
    assert not result.parse_error, result.parse_error
    assert not result.lowering_error, result.lowering_error
    return result.instructions


def _refused(line: str) -> str:
    result = compile_line(line, card_name="Census Probe")
    assert not result.instructions, f"admitted: {result.instructions}"
    return result.parse_error or result.lowering_error


@pytest.mark.parametrize(
    "tail, tied",
    [("or is tied for most common", True), ("but isn't tied for most common", False)],
)
def test_the_printed_tail_decides_what_a_tie_means(tail, tied):
    (instruction,) = _lowered(
        "This creature gets -2/-2 as long as green is the most common color "
        f"among all permanents {tail}."
    )
    assert instruction.kind == "conditional_static"
    assert instruction.payload["condition"] == {
        "kind": "color_is_most_common", "color": "G", "tied": tied,
    }
    assert (instruction.payload["power"], instruction.payload["toughness"]) == (-2, -2)


@pytest.mark.parametrize(
    "line",
    [
        # No tail: nothing says whether a level board counts.
        "This creature gets -2/-2 as long as green is the most common color "
        "among all permanents.",
        # A narrower scope is a different count; this reader takes the whole
        # battlefield or nothing.
        "This creature gets -2/-2 as long as green is the most common color "
        "among creatures or is tied for most common.",
        # The spells' clause without its second half.
        "Destroy target creature if it shares a color with the most common "
        "color among all permanents.",
    ],
)
def test_a_census_clause_missing_a_half_is_refused(line):
    assert _refused(line)


def test_the_shares_clause_asks_about_a_targeted_permanent_only():
    """The pronoun is the guarded effect's target. With a spell for a target
    the referent is on the stack, and under a trigger "it" names the event's
    subject — neither is a permanent this clause may be answered about."""
    (bounce,) = _lowered(
        "Return target permanent to its owner's hand if that permanent shares "
        "a color with the most common color among all permanents or a color "
        "tied for most common."
    )
    assert bounce.kind == "if_then"
    assert bounce.payload["condition"] == {
        "kind": "target_shares_most_common_color", "target": "permanent",
    }
    assert bounce.payload["else"] == ()

    assert "targeted permanent" in _refused(
        "Counter target spell if it shares a color with the most common color "
        "among all permanents or a color tied for most common."
    )


def test_no_opponent_controls_is_every_opponent_with_a_zero():
    (instruction,) = _lowered(
        "This creature has haste as long as no opponent controls a white or "
        "blue creature."
    )
    assert instruction.payload["condition"] == {
        "kind": "controls",
        "who": "each_opponent",
        "filter": {"type_filter": "creature", "any_colors": ["W", "U"]},
        "count": 0,
        "op": "eq",
    }
    # The negation is on the seat, so a comparison that carries none of its
    # own would consume the word and drop it.
    assert _refused(
        "This creature has haste as long as no opponent controls more "
        "creatures than you."
    )


def test_a_colour_disjunction_is_one_test_per_printed_colour():
    """"If that creature is white or blue" is two colour tests under the
    disjunction the clause-level "or" already builds — no second shape for any
    evaluator to learn — and both arms of the "instead" pair name one target.
    """
    (dart,) = _lowered(
        "Census Probe deals 1 damage to target creature. If that creature is "
        "white or blue, Census Probe deals 4 damage to it instead."
    )
    condition = dart.payload["condition"]
    assert condition["kind"] == "any_of"
    assert [part["color"] for part in condition["conditions"]] == ["W", "U"]
    assert {part["kind"] for part in condition["conditions"]} == {"target_is_color"}
    (then,), (otherwise,) = dart.payload["then"], dart.payload["else"]
    assert (then.payload["amount"], otherwise.payload["amount"]) == (4, 1)
    assert then.payload["targets"] == otherwise.payload["targets"]

    # "It" after two targets names neither, and a "that <noun>" naming a
    # different kind of object is not a restatement — both refuse.
    assert _refused(
        "Census Probe deals 1 damage to target creature. If that creature is "
        "white or blue, Census Probe deals 4 damage to that artifact instead."
    )
