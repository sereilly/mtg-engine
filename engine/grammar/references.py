"""What a printed noun phrase *points at*: a player, or a quantified set of objects.

`nouns.py` answers the other half — what those objects have to be — and this
module reads it. Splitting on that line rather than anywhere else is the CR's
own: CR 109 is what an object is, CR 115 is how a spell chooses one, and a
player (CR 102) is not an object at all. The three player forms, the quantifier
table and the recipient union are the productions that need the second question
and not the first.

Everything a caller used to import from `nouns` still exists; the names simply
moved, so a production that reads "target creature" imports the quantifier from
here and the filter from there.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .amounts import parse_amount
from .lexer import NUMBER, WORD
from .nouns import (
    _GENERIC_NOUNS,
    _SELF_NOUNS,
    _singular,
    parse_object_filter,
)
from .stream import TokenStream
from .vocabulary import CARD_TYPES, NUMBER_WORDS


def parse_player_ref(stream: TokenStream) -> ast.PlayerRef | None:
    """Parse a player reference at the cursor, or return None."""
    mark = stream.mark()

    if stream.accept_word("you"):
        return ast.PlayerRef("you")

    if stream.accept_phrase("each", "player"):
        return ast.PlayerRef("each_player")
    if stream.accept_phrase("each", "opponent"):
        return ast.PlayerRef("each_opponent")
    if stream.accept_phrase("target", "player"):
        return ast.PlayerRef("target_player")
    if stream.accept_phrase("target", "opponent"):
        return ast.PlayerRef("target_opponent")
    if stream.accept_phrase("that", "player"):
        return ast.PlayerRef("that_player")
    if stream.accept_phrase("its", "controller"):
        return ast.PlayerRef("controller")
    if stream.accept_phrase("their", "controller"):
        return ast.PlayerRef("controller")
    if stream.accept_phrase("defending", "player"):
        return ast.PlayerRef("defending_player")
    if stream.accept_phrase("the", "chosen", "player"):
        return ast.PlayerRef("chosen_player")
    if stream.accept_phrase("an", "opponent"):
        return ast.PlayerRef("target_opponent")

    # "that land's controller" / "this creature's controller" — a possessive
    # noun phrase resolving to a player. The lexer split "land's" into
    # "land" + "'s".
    if stream.at_word("that", "this"):
        probe = stream.mark()
        stream.advance()
        noun = stream.peek_word()
        if noun is not None and (
            _singular(noun) in CARD_TYPES or _singular(noun) in _GENERIC_NOUNS
        ):
            stream.advance()
            if stream.accept_word("'s") and stream.accept_word("controller"):
                return ast.PlayerRef("that_player")
        stream.reset(probe)

    stream.reset(mark)
    return None


def _at_counted_target(stream: TokenStream) -> bool:
    """Whether the cursor is at "<number> target …" — a bare count, no "up to".

    Looked ahead rather than tried-and-rewound because the number is also the
    opening of several other phrases ("two or more", "three cards"), and only
    the word after it says which this is.
    """
    word = stream.peek_word()
    token = stream.peek()
    if token is None:
        return False
    is_number = token.kind == NUMBER or word in NUMBER_WORDS or word == "x"
    return bool(is_number) and stream.peek_word(1) == "target"


def parse_target_spec(stream: TokenStream) -> ast.TargetSpec | None:
    """Parse a quantified object reference, or return None if the cursor is not
    at one."""
    mark = stream.mark()

    # CR 115.4 "any target" — creatures, players, planeswalkers, battles.
    if stream.accept_phrase("any", "target"):
        return ast.TargetSpec("any_target", targeted=True)

    # "each of up to two target creatures you control" — a distributive wrapper
    # over the noun phrase rather than a quantifier of its own. It names exactly
    # the objects the phrase behind it names and says the effect applies to each
    # of them, which is already what a per-object effect does with a list, so
    # the count and the filter come from the wrapped phrase. Consumed here so
    # "each" is not mistaken for the sweep quantifier below, which would turn
    # "up to two target creatures" into every creature on the battlefield.
    stream.accept_phrase("each", "of")

    quantifier: str | None = None
    count = 1

    # "up to two **other** target creatures you control" prints "other" between
    # the count and the word "target" — the one position `parse_object_filter`
    # cannot reach, because it reads the filter from after "target". Recorded
    # here and folded into that filter below, so this spelling and the
    # postmodifier one ("target creature other than this creature") set the same
    # field and no lowering has to learn two names for one restriction.
    other_before_target = False
    distinct_from_prior = False
    # "X target lands": the count is the announced X rather than a printed
    # number, so it is not known until the ability is activated.
    exactly_x = False

    # Whether the word "target" is printed — recorded, not merely consumed:
    # "up to four lands" (Rewind) names no targets and is chosen on
    # resolution, where "up to two target creatures" is chosen at cast.
    targeted = False

    # "tap **any number of** untapped creatures you control" (Siege Striker).
    # Its own quantifier rather than an "up to" with a very large count: an "up
    # to" prints a maximum a picker shows and a re-check enforces, and there is
    # none here — the bound is the set itself. Untargeted by construction, like
    # Rewind's "up to four lands": no "target" is printed, so nothing is chosen
    # until the effect resolves (CR 115.1b).
    if stream.accept_phrase("any", "number", "of"):
        return ast.TargetSpec(
            "any_number", parse_object_filter(stream), count=0, targeted=False
        )

    if stream.accept_phrase("up", "to"):
        quantifier = "up_to"
        token = stream.peek()
        if token is not None and (token.kind == NUMBER or token.kind == WORD):
            amount = parse_amount(stream)
            count = amount.value if isinstance(amount, ast.Fixed) else 1
        if stream.at_word("other") and stream.peek_word(1) == "target":
            stream.advance()
            other_before_target = True
        # "up to one target creature", "up to two target creatures" — the word
        # "target" is part of the printed quantifier phrase, not the filter.
        targeted = bool(stream.accept_word("target")) or other_before_target
    elif stream.accept_word("target"):
        quantifier = "target"
        targeted = True
    elif _at_counted_target(stream):
        # "**X** target lands" (Candelabra of Tawnos) / "two target creatures".
        # A bare count where "up to" prints a maximum: the player chooses
        # *exactly* this many, so it is the same several-target shape with a
        # different floor — and reading it as "up to" would let a card that
        # must untap four untap one and report itself supported, which is the
        # bug `_names_several_targets` was written after.
        amount = parse_amount(stream)
        count = amount.value if isinstance(amount, ast.Fixed) else 0
        exactly_x = not isinstance(amount, ast.Fixed)
        stream.expect_word("target")
        quantifier = "exactly"
        targeted = True
    elif stream.at_word("another") and stream.peek_word(1) == "target":
        # "another target creature" (Garruk, Savage Herald) — a second chosen
        # object, distinct from the sentence's earlier choice. Guarded on the
        # following "target" so the sacrifice-cost reading of "another
        # <object>" is untouched.
        stream.advance(2)
        quantifier = "target"
        targeted = True
        distinct_from_prior = True
    elif stream.accept_word("each"):
        quantifier = "each"
    elif stream.accept_word("all"):
        quantifier = "all"
    elif stream.at_word("this"):
        quantifier = "this"
    elif stream.at_word("enchanted"):
        quantifier = "this"
    elif stream.accept_word("a", "an"):
        quantifier = "a"

    if quantifier is None:
        # A bare plural noun phrase ("black creatures get +1/+1") is an
        # implicit "all".
        try:
            filt = parse_object_filter(stream)
        except Exception:
            stream.reset(mark)
            return None
        return ast.TargetSpec("all", filt)

    try:
        filt = parse_object_filter(stream)
    except Exception:
        stream.reset(mark)
        return None
    if other_before_target:
        filt = dataclasses.replace(filt, other_than_source=True)
    return ast.TargetSpec(
        quantifier, filt, count,
        count_from_x=exactly_x,
        distinct_from_prior=distinct_from_prior, targeted=targeted,
    )


def parse_recipient(stream: TokenStream) -> ast.Recipient | None:
    """Parse either a player reference or a quantified object reference."""
    player = parse_player_ref(stream)
    if player is not None:
        return player
    # A bare "it" refers back to the ability's own source ("put a +1/+1 counter
    # on it" on a trigger whose subject was "this creature").
    if stream.at_word("it"):
        stream.advance()
        return ast.TargetSpec("this", ast.ObjectFilter(is_source=True))
    # The card naming itself mid-sentence ("put a loyalty counter on Garruk") —
    # the lexer already collapsed the name to one SELF token.
    token = stream.peek()
    if token is not None and token.kind == "self":
        stream.advance()
        return ast.TargetSpec("this", ast.ObjectFilter(is_source=True))
    return parse_target_spec(stream)


__all__ = ["parse_player_ref", "parse_recipient", "parse_target_spec"]
