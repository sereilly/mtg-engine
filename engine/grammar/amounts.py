"""Quantity sub-parser: numbers, X, counts, and back-references.

The legacy rules re-derived quantities inline in every regex, and used a
lenient number parse that turned an unrecognized word into a silent ``0``
("deals <n> damage" with an unparsed n dealt nothing). Quantities parse in one
place here and an unknown quantity word is an error, not a zero.
"""

from __future__ import annotations

from . import ast
from .lexer import NUMBER, PT, WORD
from .stream import TokenStream
from .vocabulary import NUMBER_WORDS


def parse_amount(stream: TokenStream, *, back_reference: str | None = None) -> ast.Amount:
    """Parse a quantity at the cursor.

    *back_reference* names the result key a bare "that much" refers to, for a
    caller that knows it from the words it has already read. The default is
    None, because in general the sentence does not say: "that much" points at
    the enclosing effect's earlier step or at the event that fired the ability,
    and only lowering can see either. See :class:`ast.ThatMuch`.
    """
    token = stream.peek()
    if token is None:
        raise stream.error("expected a quantity")

    if token.kind == NUMBER:
        stream.advance()
        return ast.Fixed(int(token.text))

    if token.kind == WORD:
        word = token.text
        if word in ("x", "y"):
            stream.advance()
            return ast.Var(word)
        if word in NUMBER_WORDS:
            stream.advance()
            return ast.Fixed(NUMBER_WORDS[word])
        if word == "all":
            stream.advance()
            return ast.AllOf()
        if word == "half":
            stream.advance()
            inner = _parse_counted_amount(stream, back_reference=back_reference)
            rounding = "down"
            if stream.accept_word("rounded"):
                rounding = "up" if stream.accept_word("up") else (
                    "down" if stream.accept_word("down") else "down"
                )
            return ast.Half(inner, rounding)
        if word == "that":
            mark = stream.mark()
            stream.advance()
            # "that much" refers back to a recorded quantity; "that many"
            # (Basri Ket's "create that many … tokens") to a counted set. One
            # node for both — the back-reference names what is counted.
            if stream.accept_word("much", "many"):
                return ast.ThatMuch(back_reference)
            stream.reset(mark)
        if word == "any":
            mark = stream.mark()
            stream.advance()
            if stream.accept_phrase("amount", "of"):
                return ast.AllOf()
            stream.reset(mark)

    raise stream.error("expected a quantity")


def _parse_counted_amount(
    stream: TokenStream, *, back_reference: str | None = None
) -> ast.Amount:
    """``the number of <noun phrase>``, or any ordinary quantity.

    Split out so "half" can take one of either — "half **the number of cards in
    their library**" (Peer into the Abyss) is a half of a count, and
    :func:`parse_amount`'s own recursion could only read the plain quantities.
    Both readers reach the same noun parser, so the count means one thing
    wherever it is printed.
    """
    mark = stream.mark()
    if stream.accept_word("the") and stream.accept_phrase("number", "of"):
        # Late import for the reason `parse_equal_to` gives: nouns depends on
        # this module for comparisons, so the cycle is broken at call time.
        from .nouns import parse_object_filter

        return ast.CountOf(parse_object_filter(stream))
    stream.reset(mark)
    return parse_amount(stream, back_reference=back_reference)


def parse_equal_to(stream: TokenStream) -> ast.Amount | None:
    """Parse an "equal to …" quantity clause, or return None if absent.

    Handles the two shapes the card pool uses: a count of matching objects
    ("equal to the number of Swamps you control") and a back-reference to a
    value produced earlier in the same resolution ("equal to the damage
    dealt").
    """
    mark = stream.mark()
    if not stream.accept_phrase("equal", "to"):
        return None

    # "equal to **half** the number of cards in their library" (Peer into the
    # Abyss). Handed to the quantity parser, which reads the half and the count
    # under it; the shapes below are the ones that are not quantities at all.
    if stream.at_word("half"):
        return parse_amount(stream)

    stream.accept_word("the")

    if stream.accept_phrase("number", "of"):
        # Late import: nouns depends on this module for comparisons, so the
        # cycle is broken at call time rather than import time.
        from .nouns import parse_object_filter

        filt = parse_object_filter(stream)
        return ast.CountOf(filt)

    if stream.accept_phrase("damage", "dealt"):
        return ast.ThatMuch("damage_dealt")

    # "equal to its power" — a characteristic of the object the *preceding*
    # step acted on, not a value in the resolution scratchpad. Nothing records
    # it, so `_PRODUCES` never names it and any lowering that reads a bare
    # occurrence is refused for want of a producer; only a lowering that
    # computes the power itself (the fused exile-and-gain-life handler) accepts
    # it. That is the intended asymmetry: the words are recognized, and what
    # they need is a handler rather than a parse.
    if stream.accept_phrase("its", "power"):
        return ast.ThatMuch("its_power")

    # "equal to **that creature's** power" (Terror of the Peaks) — the power of
    # the creature the *trigger's event* was about, not of the ability's source.
    # A different referent from "its power" above and so a different key: read
    # as that one it would deal the Dragon's own power, which is a number the
    # card never mentions.
    if stream.accept_phrase("that", "creature", "'s", "power"):
        return ast.ThatMuch("event_subject_power")

    stream.reset(mark)
    return None


def parse_pt_pair(text: str) -> tuple[ast.Amount, bool, ast.Amount, bool]:
    """Split a P/T token ("+3/+3", "-0/-2", "+X/+0", "0/2") into
    ``(power, power_negative, toughness, toughness_negative)``."""
    left, _, right = text.partition("/")

    def _one(part: str) -> tuple[ast.Amount, bool]:
        negative = part.startswith("-")
        body = part.lstrip("+-")
        if body in ("x", "y"):
            return ast.Var(body), negative
        return ast.Fixed(int(body)), negative

    power, power_negative = _one(left)
    toughness, toughness_negative = _one(right)
    return power, power_negative, toughness, toughness_negative


def expect_pt(stream: TokenStream) -> tuple[ast.Amount, bool, ast.Amount, bool]:
    token = stream.accept_kind(PT)
    if token is None:
        raise stream.error("expected a power/toughness value")
    return parse_pt_pair(token.text)


__all__ = ["expect_pt", "parse_amount", "parse_equal_to", "parse_pt_pair"]
