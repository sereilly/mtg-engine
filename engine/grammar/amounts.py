"""Quantity sub-parser: numbers, X, counts, and back-references.

The legacy rules re-derived quantities inline in every regex, and used a
lenient number parse that turned an unrecognized word into a silent ``0``
("deals <n> damage" with an unparsed n dealt nothing). Quantities parse in one
place here and an unknown quantity word is an error, not a zero.
"""

from __future__ import annotations

from . import ast
from .lexer import NUMBER, PT, SELF, WORD
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
            # "…, rounded down" (Backdraft) prints a comma in front of the
            # rider; "half X rounded up" does not. One reader for both, and the
            # comma is put back when what follows it is a different clause —
            # eating it unconditionally would take the separator a later
            # production needs.
            comma = stream.mark()
            had_comma = stream.accept_punct(",")
            if stream.accept_word("rounded"):
                rounding = "up" if stream.accept_word("up") else (
                    "down" if stream.accept_word("down") else "down"
                )
            elif had_comma:
                stream.reset(comma)
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
            # "remove **any number of** +1/+1 counters" (Tetravus). A different
            # node from "any amount of" beside it: that one is unbounded and
            # nobody chooses it, this one is a choice with a ceiling.
            if stream.accept_phrase("number", "of"):
                return ast.AnyNumber()
            stream.reset(mark)

    raise stream.error("expected a quantity")


def accept_counters_on_source(stream: TokenStream) -> "ast.CountersOnSource | None":
    """``<word> counters on <the source>`` — the count of a named counter the
    ability's own source is carrying, or None when the words are something else.

    Sits in front of the noun parser in both readers of "the number of …",
    because a counter kind is a bare word and ``parse_object_filter`` would
    refuse it as an unknown noun — so without this the whole line falls, which
    is what left Armageddon Clock's draw-step damage to a regex in a phase
    mixin.

    The kind is whatever word the card invented (CR 122.1), matching
    ``engine/named_counters.py``'s open key space — **or** a P/T counter, which
    the lexer reads as a ``pt`` token rather than a word ("the number of +1/+1
    counters on it", Primordial Ooze). Both spellings are one production because
    the sentence is one sentence: what is being counted is what is sitting on
    the source, and CR 122.1 makes a +1/+1 counter a counter like any other. The
    reader that resolves the count is what knows the difference between a store
    the card invented and the P/T channel.
    """
    mark = stream.mark()
    pt = stream.accept_kind(PT)
    kind = pt.text if pt is not None else stream.peek_word()
    if kind is not None:
        if pt is None:
            stream.advance()
        if stream.accept_word("counter", "counters") and stream.accept_word("on"):
            # Late import for the reason the noun imports below give: nouns
            # depends on this module for comparisons, so the cycle is broken at
            # call time.
            from .nouns import accept_source_reference

            if accept_source_reference(stream):
                return ast.CountersOnSource(kind)
    stream.reset(mark)
    return None


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
        counters = accept_counters_on_source(stream)
        if counters is not None:
            return counters
        # Late import for the reason `parse_equal_to` gives: nouns depends on
        # this module for comparisons, so the cycle is broken at call time.
        from .nouns import parse_object_filter

        return ast.CountOf(parse_object_filter(stream))
    stream.reset(mark)
    # "half **the damage dealt by one of those sorcery spells this turn**"
    # (Backdraft). A history narrowed by a choice, not a count of anything, so
    # it is read here where "half" can take it — the same position "the number
    # of" is read from, for the same reason.
    chosen = accept_damage_dealt_by_chosen_cast(stream)
    if chosen is not None:
        return chosen
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
        counters = accept_counters_on_source(stream)
        if counters is not None:
            return counters
        # Late import: nouns depends on this module for comparisons, so the
        # cycle is broken at call time rather than import time.
        from .nouns import parse_object_filter

        filt = parse_object_filter(stream)
        return ast.CountOf(filt)

    # "equal to **the sacrificed creature's toughness**" (Life Chisel, Diamond
    # Valley) — a characteristic of the permanent the ability's own *cost* ate,
    # not of anything a step of the effect touched. Read before the
    # back-references below because it names its own channel and needs no
    # producer: CR 601.2h pays the cost before the ability is on the stack, so
    # by the time this resolves the creature is a memory the activation path
    # recorded (`sacrificed_for_cost`).
    #
    # The noun and the characteristic are both read as printed, so "the
    # sacrificed **artifact's** mana value" is the same production. Which of
    # them a handler can actually answer is the lowering's question.
    sacrificed_mark = stream.mark()
    if stream.accept_word("sacrificed"):
        noun = stream.peek_word()
        if noun is not None:
            stream.advance()
            if stream.accept_word("'s"):
                if stream.accept_phrase("mana", "value"):
                    return ast.SacrificedForCost("mana_value")
                characteristic = stream.peek_word()
                if characteristic in ("power", "toughness"):
                    stream.advance()
                    return ast.SacrificedForCost(str(characteristic))
    stream.reset(sacrificed_mark)

    if stream.accept_phrase("damage", "dealt"):
        # "…equal to the damage dealt **this way**" (Syphon Soul). "This way"
        # says the number is the one *this effect* produced rather than any
        # damage dealt elsewhere in the turn — which is exactly what the
        # back-reference already means: `_back_reference_payload` resolves it
        # against the steps of this same effect and refuses when no step
        # produced one. So the words are consumed, not dropped: the reading
        # they ask for is the only reading available.
        stream.accept_phrase("this", "way")
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

    # "equal to **its** mana value" (Divine Offering: "Destroy target artifact.
    # You gain life equal to its mana value."). "It" is the object the
    # *preceding step of this same effect* acted on, which by the time the gain
    # runs is in a graveyard — so the step records the number and this reads the
    # record. Named for the words rather than for one producer, because the
    # question is the same whichever verb the sentence in front of it printed;
    # the producer gate in ``_back_reference_payload`` is what makes the words
    # legal, so a card whose first sentence records nothing refuses by name
    # instead of gaining zero life.
    if stream.accept_phrase("its", "mana", "value"):
        return ast.ThatMuch("its_mana_value")

    # "equal to **that creature's** power" (Terror of the Peaks) — the power of
    # the creature the *trigger's event* was about, not of the ability's source.
    # A different referent from "its power" above and so a different key: read
    # as that one it would deal the Dragon's own power, which is a number the
    # card never mentions.
    if stream.accept_phrase("that", "creature", "'s", "power"):
        return ast.ThatMuch("event_subject_power")

    # "equal to **that creature's mana value**" (Niambi, Esteemed Speaker) — the
    # creature the *preceding step* moved, not the trigger's event object and not
    # the ability's source. A third referent and so a third key: the step records
    # what it bounced and this reads that record, which is why the producer check
    # in ``_back_reference_payload`` is what makes the words legal rather than a
    # phrase table. Mana value is the printed cost of the card that left the
    # battlefield (CR 202.3, CR 400.7 — it is a new object in the hand, but its
    # mana value is a printed characteristic and does not change).
    if stream.accept_phrase("that", "creature", "'s", "mana", "value"):
        return ast.ThatMuch("returned_mana_value")

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


# A printed comparison is a bound on an amount — "power **3 or greater**" —
# so it lives with the amounts it compares rather than with the filter that
# happens to carry one. It was in `nouns` only because a filter was its first
# caller, and it could not follow `accept_source_reference` down to `readers`:
# it reads `parse_amount`, and `amounts` reads `readers`.
_COMPARISON_WORDS = {
    "less": "le",       # "2 or less"
    "greater": "ge",    # "3 or greater"
    "more": "ge",
}

def parse_comparison(stream: TokenStream) -> ast.Comparison:
    """Parse "N or less" / "N or greater" / "N" following power/toughness."""
    amount = parse_amount(stream)
    if stream.accept_word("or"):
        token = stream.peek()
        word = token.text if token is not None and token.kind == WORD else None
        if word in _COMPARISON_WORDS:
            stream.advance()
            return ast.Comparison(_COMPARISON_WORDS[word], amount)
        raise stream.error("expected 'less' or 'greater'")
    return ast.Comparison("eq", amount)


def accept_damage_dealt_this_turn(
    stream: TokenStream,
) -> "ast.DamageDealtThisTurn | None":
    """``amount of damage dealt to <the source> this turn by [other] sources
    named <this card>`` — or None, cursor unmoved, when the words are not this.

    Blazing Effigy's where-clause. Called with the leading "the" already
    consumed, from the one reader of a where-clause definition, so the phrase
    means the same wherever a card prints it.

    Every narrowing is read rather than assumed, and the production refuses the
    moment one of them is missing. "This turn" is the ledger's window and a
    clause without it is asking about a different one; "other" is CR 109.5's
    identity exclusion and dropping it would count the creature's own damage to
    itself; and the name must be the SELF token — the card naming itself — so a
    clause comparing against some *other* printed name refuses here instead of
    quietly being read as this one. That last refusal is the dropped-rider bug
    with a card name on it.
    """
    mark = stream.mark()
    if not stream.accept_phrase("amount", "of", "damage", "dealt", "to"):
        stream.reset(mark)
        return None
    # Late import for the reason `_parse_counted_amount` gives: the noun-side
    # modules depend on this one, so the cycle is broken at call time.
    from .readers import accept_source_reference

    if not accept_source_reference(stream):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("this", "turn", "by"):
        stream.reset(mark)
        return None
    others_only = bool(stream.accept_word("other"))
    if not (stream.accept_word("sources", "source") and stream.accept_word("named")):
        stream.reset(mark)
        return None
    if stream.accept_kind(SELF) is None:
        stream.reset(mark)
        return None
    return ast.DamageDealtThisTurn(others_only=others_only)


def accept_added_base(stream: TokenStream) -> int | None:
    """``<number> plus`` in front of a quantity — the constant it is added to.

    "…where X is **3 plus** the amount of damage dealt …" (Blazing Effigy). The
    number is payload for the reason every other printed number in this file is:
    a card printing "2 plus" is the same shape with one digit changed, and
    spelling the 3 into the phrase would make every other one a non-match.

    Returns None with the cursor where it found it, so a definition that does
    not open with a sum keeps the refusal it already had.
    """
    mark = stream.mark()
    token = stream.peek()
    if token is not None and token.kind == NUMBER:
        stream.advance()
        if stream.accept_word("plus"):
            return int(token.text)
    stream.reset(mark)
    return None


def accept_damage_dealt_by_chosen_cast(
    stream: TokenStream,
) -> "ast.DamageDealtByChosenCast | None":
    """``the damage dealt by one of those <type> spells this turn`` — or None,
    cursor unmoved, when the words are not this.

    Backdraft's amount. "One of those" is a back-reference to the set an earlier
    sentence described, and it is a *choice* rather than a sum: the whole point
    of the words is that the spells are several and one of them is picked. The
    lowering is where that choice becomes a step, and where the missing
    producer is refused.
    """
    mark = stream.mark()
    if not stream.accept_phrase("the", "damage", "dealt", "by", "one", "of", "those"):
        stream.reset(mark)
        return None
    # Late import for the reason every other reader in this module gives: the
    # vocabulary side depends on this one, so the cycle is broken at call time.
    from .vocabulary import CARD_TYPES, singular

    word = stream.peek_word()
    if word is None or singular(word) not in CARD_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("spells", "this", "turn"):
        stream.reset(mark)
        return None
    return ast.DamageDealtByChosenCast(singular(word))
