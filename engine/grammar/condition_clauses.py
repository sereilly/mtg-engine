"""The printed *clauses* a condition is built from.

Split out of ``conditions.py`` at the guard, along the boundary that module
already had in its own shape: ``_parse_single_condition`` is a dispatcher over
the whole vocabulary of conditions, and these are the readers it hands a
sentence to - one printed clause each, read to its end, non-consuming on
refusal so the dispatcher's next branch keeps its say.

The name is ``sentence_clauses``' one layer over, and for the same reason: that
module holds the clauses ``parse_statement`` reads around a body, and this one
holds the clauses ``_parse_condition`` reads inside one. Below ``conditions``,
which calls into it and is never imported back.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .amounts import parse_amount
from .errors import GrammarError
from .nouns import parse_object_filter
from .stream import TokenStream
from .vocabulary import CARD_TYPES, NUMBER_WORDS


def _parse_self_in_graveyard_above(
    stream: TokenStream,
) -> "ast.SelfInGraveyardWithCardsAbove | None":
    """``this card is in your graveyard with <N> <type> card(s) [directly] above
    it``, or None without consuming when the sentence is something else.

    Non-consuming on refusal, like every other tried-first production in this
    package: a clause that read "this card is in your graveyard" and then failed
    on the words after it would take the whole line's refusal site with it.

    "Above" is CR 404.3's order — a graveyard is an ordered zone and a card put
    there later sits on top — so the count and the "directly" are both about
    *positions*, which is why they are separate fields rather than one number.
    """
    if not stream.accept_phrase("this", "card", "is", "in", "your", "graveyard"):
        return None
    if not stream.accept_word("with"):
        raise stream.error("expected 'with' after the graveyard clause")
    at_least = False
    if stream.accept_word("a", "an"):
        count = 1
    else:
        word = stream.peek_word()
        if word not in NUMBER_WORDS:
            raise stream.error("expected a number of cards above it")
        stream.advance()
        count = NUMBER_WORDS[word]
        # "three **or more**". Without it the clause is an exact count, which is
        # a different question and one no card in the pool prints — so it is
        # read rather than assumed, and the lowering carries whichever was
        # printed.
        at_least = bool(stream.accept_phrase("or", "more"))
    card_type = stream.peek_word()
    if card_type not in CARD_TYPES:
        raise stream.error("expected a card type above it")
    stream.advance()
    if not stream.accept_word("card", "cards"):
        raise stream.error("expected 'card' or 'cards' above it")
    directly = bool(stream.accept_word("directly"))
    if not stream.accept_phrase("above", "it"):
        raise stream.error("expected 'above it'")
    return ast.SelfInGraveyardWithCardsAbove(
        card_type=card_type, count=count, at_least=at_least, directly=directly,
    )


def _parse_blockers_of_bound_creature(
    stream: TokenStream,
) -> ast.BlockersOfBoundCreature | None:
    """"<quantifier> <noun phrase> is/are blocking that creature".

    The quantifier is what the clause *counts*, and every spelling the pool
    prints is read here rather than being split across productions: "no" is a
    zero, "at least N" and "N or more" are the same minimum written two ways,
    and a bare "a"/"an" is that minimum with the one left implicit. None of
    them is baked into a kind — the number rides the comparison, so a card
    printed "at least two" needs no code.

    Returns None (rather than raising) when the words parse as a noun phrase
    that is simply not followed by this relation, so the caller's reset hands
    the sentence back to the productions after it.
    """
    negated = bool(stream.accept_word("no"))
    at_least: int | None = None
    if not negated:
        if stream.accept_phrase("at", "least"):
            amount = parse_amount(stream)
            if not isinstance(amount, ast.Fixed):
                # The evaluator compares an integer; an X or a board count
                # would be compared against a node. Refused rather than
                # coerced, exactly as `SubjectPowerIs` refuses one.
                raise stream.error("the blocker count is a printed number")
            at_least = amount.value
        else:
            count_mark = stream.mark()
            try:
                amount = parse_amount(stream)
            except GrammarError:
                amount = None
            if isinstance(amount, ast.Fixed) and stream.accept_phrase("or", "more"):
                at_least = amount.value
            else:
                stream.reset(count_mark)
                # "a Wall is blocking that creature" — the minimum left
                # implicit. Accepted with the article consumed so the noun
                # parser below reads the same phrase either way; the article is
                # not required, because "creatures blocking that creature" is
                # the same clause with the plural doing the work.
                stream.accept_word("a", "an")
                at_least = 1
    other = bool(stream.accept_word("other"))
    filt = parse_object_filter(stream)
    if other:
        # "at least one **other** Wall creature": the asking permanent never
        # satisfies its own condition — it is already blocking that creature,
        # which is why the trigger fired at all.
        filt = dataclasses.replace(filt, other_than_source=True)
    if not (stream.accept_word("is") or stream.accept_word("are")):
        return None
    if not stream.accept_phrase("blocking", "that", "creature"):
        return None
    comparison = (
        ast.Comparison("eq", ast.Fixed(0))
        if negated
        else ast.Comparison("ge", ast.Fixed(at_least or 1))
    )
    return ast.BlockersOfBoundCreature(filt, comparison)


def _accept_it_is(stream: TokenStream, *, negated: bool) -> bool:
    """``it isn't`` / ``it is not`` — the negative spelling of "it's".

    Its own reader because the negation is printed three ways and the
    contraction is one token to the lexer's eye in only one of them; a branch
    that read "isn't" alone would leave "is not" unread, and an unread negation
    is the condition answering the opposite of what the card says.
    """
    mark = stream.mark()
    if stream.accept_word("it") and (
        stream.accept_word("isn't")
        or (stream.accept_word("is") and stream.accept_word("not"))
    ):
        return negated
    stream.reset(mark)
    return False
