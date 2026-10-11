"""``A. If <condition>, B instead.`` — what the replaced *sentence* may be.

``tests/engine/test_grammar_parser.py`` holds the rider to its rule about
**whom** the second sentence is done to. These hold it to what Apocalypse's
Sanctuaries added about **what** it may replace:

* a sentence of two actions joined by "then" ("draw a card, then discard a
  card … **instead** draw two cards, then discard a card", Ceta Sanctuary) —
  replaced whole, by the same actions in the same order;
* a life loss and a draw, each naming its player ("…**that player** loses 3
  life instead", Necra Sanctuary);
* a damage sentence that names **nobody** ("…this enchantment deals 3 damage
  instead", Raka Sanctuary), whose recipient is the replaced sentence's — and
  which, read alone, is refused rather than compiled to nothing.

Invented lines, because the pool prints one card per cell.
"""

from __future__ import annotations

import pytest

from engine.grammar import ast, compile_line
from engine.grammar.errors import GrammarError
from engine.grammar.parser import parse_line


def _pair(line: str) -> ast.Conditional:
    node = parse_line(line)
    statement = node.statement
    assert isinstance(statement, ast.Conditional) and statement.otherwise is not None, statement
    return statement


def test_a_then_sentence_is_replaced_whole():
    """The upgrade replaces the *sentence*, both actions of it: one loot of
    one size, never the first sentence and then the second."""
    pair = _pair(
        "Draw a card, then discard a card. If you control a Swamp, instead "
        "draw two cards, then discard a card."
    )
    assert isinstance(pair.then, ast.Sequence) and isinstance(pair.otherwise, ast.Sequence)
    assert [type(step) for step in pair.then.steps] == [ast.Draw, ast.Discard]
    assert [type(step) for step in pair.otherwise.steps] == [ast.Draw, ast.Discard]
    assert pair.then.steps[0].count == ast.Fixed(2)
    assert pair.otherwise.steps[0].count == ast.Fixed(1)

    compiled = compile_line(
        "Draw a card, then discard a card. If you control a Swamp, instead "
        "draw two cards, then discard a card."
    )
    assert compiled.usable
    (instruction,) = compiled.instructions
    assert instruction.kind == "if_then"
    assert instruction.payload["then"] and instruction.payload["else"]


@pytest.mark.parametrize("line", [
    # A sequence replaced by one action, and by a longer sequence.
    "Draw a card, then discard a card. If you control a Swamp, instead draw "
    "two cards.",
    "Draw a card, then discard a card. If you control a Swamp, instead draw "
    "two cards, then discard a card, then you gain 1 life.",
    # The same actions in another order are another sentence.
    "Draw a card, then discard a card. If you control a Swamp, instead "
    "discard a card, then draw two cards.",
    # One step of another kind.
    "Draw a card, then discard a card. If you control a Swamp, instead draw "
    "two cards, then you gain 1 life.",
    # A step the rider does not replace alone is not replaced in a sequence.
    "Draw a card, then sacrifice a creature. If you control a Swamp, instead "
    "draw two cards, then sacrifice a creature.",
])
def test_a_then_sentence_is_replaced_only_by_itself_said_again(line):
    with pytest.raises(GrammarError):
        parse_line(line)


@pytest.mark.parametrize("line, kind", [
    ("Target player loses 1 life. If you control a Swamp, that player loses 3 "
     "life instead.", ast.LoseLife),
    ("Target player draws a card. If you control a Swamp, that player draws "
     "two cards instead.", ast.Draw),
])
def test_a_life_loss_and_a_draw_keep_their_player_across_the_pair(line, kind):
    """CR 601.2c: one player is announced whichever arm resolves, so "that
    player" in the replacement is the replaced sentence's target."""
    pair = _pair(line)
    assert isinstance(pair.then, kind) and isinstance(pair.otherwise, kind)
    assert pair.then.player == pair.otherwise.player
    assert pair.then.player.kind == "target_player"


def test_a_damage_replacement_naming_nobody_takes_the_replaced_recipient():
    """"…deals 1 damage to target creature. If …, this creature deals 3 damage
    instead." The second sentence is the first with one number changed."""
    line = (
        "This creature deals 1 damage to target creature. If you control a "
        "Swamp, this creature deals 3 damage instead."
    )
    pair = _pair(line)
    assert pair.then.recipients == pair.otherwise.recipients
    assert pair.then.recipients[0].targeted
    assert (pair.then.amount, pair.otherwise.amount) == (ast.Fixed(3), ast.Fixed(1))

    (instruction,) = compile_line(line).instructions
    (upgraded,), (printed,) = instruction.payload["then"], instruction.payload["else"]
    assert (upgraded.kind, printed.kind) == ("deal_damage", "deal_damage")
    assert upgraded.payload["targets"] == printed.payload["targets"]
    assert (upgraded.payload["amount"], printed.payload["amount"]) == (3, 1)


def test_a_recipient_less_replacement_keeps_the_replaced_sentences_riders():
    """It *is* the replaced sentence with the printed number in it, so a rider
    the first sentence carries is on both arms."""
    pair = _pair(
        "This creature deals 1 damage to target creature and the damage can't "
        "be prevented. If you control a Swamp, this creature deals 3 damage "
        "instead."
    )
    assert pair.otherwise.riders.cant_be_prevented
    assert pair.then.riders == pair.otherwise.riders
    assert pair.then.recipients == pair.otherwise.recipients


def test_a_recipient_less_replacement_from_another_source_is_refused():
    """"…**that creature** deals 3 damage instead" is not the first sentence
    with its number changed: the damage comes from somewhere else, and there
    is no reading of whom it is dealt to."""
    with pytest.raises(GrammarError):
        parse_line(
            "This creature deals 1 damage to target creature. If you control "
            "a Swamp, that creature deals 3 damage instead."
        )


def test_a_damage_sentence_naming_nobody_is_refused_alone():
    """Outside a pair there is no sentence to take a recipient from, and a
    damage clause with none lowered to **no instruction**: the line compiled
    and dealt nothing. It refuses now, naming what is missing."""
    compiled = compile_line("This creature deals 3 damage.")
    assert not compiled.usable
    assert "names no recipient" in (compiled.lowering_error or "")

    # …and a recipient-less replacement of something that is not damage is no
    # pair at all.
    with pytest.raises(GrammarError):
        parse_line(
            "You gain 1 life. If you control a Swamp, this creature deals 3 "
            "damage instead."
        )
