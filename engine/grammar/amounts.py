"""Quantity sub-parser: numbers, X, counts, and back-references.

The legacy rules re-derived quantities inline in every regex, and used a
lenient number parse that turned an unrecognized word into a silent ``0``
("deals <n> damage" with an unparsed n dealt nothing). Quantities parse in one
place here and an unknown quantity word is an error, not a zero.
"""

from __future__ import annotations

from . import ast
from .errors import GrammarError
from .lexer import MANA, NUMBER, PT, WORD
# `parse_equal_to` below reads the record-shaped quantities too — one
# printed "equal to …" reaches both families, which is why the split is
# by what the quantity *is* rather than by which reader asks for it.
from .records import (accept_damage_dealt_by_chosen_cast,
                      accept_exiled_for_cost, accept_sacrificed_for_cost)
from .stream import TokenStream
from .vocabulary import ALL_SUBTYPES, CARD_TYPES, NUMBER_WORDS, singular as _singular


def _accept_variable_offset(stream: TokenStream, variable: ast.Var) -> ast.Amount:
    """``X plus <n>`` — the variable with the constant the sentence adds to it.

    "You gain **X plus 1** life, where X is the number of green creatures on the
    battlefield." (An-Havva Inn.) "…deals **X plus 3** damage to you."
    (Hellfire.) One reading, here, because the two cards print the same
    quantity: ``effects/damage.py`` had read its own copy of this since Hellfire
    landed, so the same three words were a quantity in a damage clause and
    unconsumed text everywhere else — the fork that round 8 found in the
    where-clause parsers, one production over. The damage branch still stands
    for its *other* left-hand sides ("half X plus 1"); this one claims the
    variable case first and builds the identical node, so nothing about Hellfire
    changes.

    Only a printed **number** follows, and only after "plus". "X minus 1" is
    left entirely unconsumed rather than read as a negative offset: no card in
    the pool prints it, and an unread word fails the line loudly, which is the
    direction this parser exists to fail in.

    A ``Fixed`` right-hand side is the whole vocabulary for the same reason —
    "X plus the number of …" is a sum of two computed quantities, and the
    resolution reads one X.
    """
    mark = stream.mark()
    if not stream.accept_word("plus"):
        return variable
    token = stream.peek()
    if token is not None and token.kind == NUMBER:
        stream.advance()
        return ast.Plus(variable, ast.Fixed(int(token.text)))
    number = NUMBER_WORDS.get(stream.peek_word() or "")
    if number is not None:
        stream.advance()
        return ast.Plus(variable, ast.Fixed(number))
    stream.reset(mark)
    return variable


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
            return _accept_variable_offset(stream, ast.Var(word))
        # "a third of their life" (Pox). Read **before** the number-word table,
        # which maps a bare "a" onto 1 — without this the fraction parses as the
        # quantity one and the rest of the phrase is unconsumed text.
        fraction = _accept_fraction(stream, back_reference=back_reference)
        if fraction is not None:
            return fraction
        if word in NUMBER_WORDS:
            stream.advance()
            return ast.Fixed(NUMBER_WORDS[word])
        if word == "all":
            stream.advance()
            return ast.AllOf()
        if word == "half":
            stream.advance()
            inner = _parse_counted_amount(stream, back_reference=back_reference)
            # "…, rounded down" (Backdraft) prints a comma in front of the
            # rider; "half X rounded up" does not. `_accept_rounding` reads both,
            # and reads them for the "a <ordinal> of" spelling beside this one.
            return ast.Half(inner, _accept_rounding(stream))
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


#: The denominators the pool spells out. "Half" has its own word and its own
#: branch above; these are the ones printed as "a <ordinal> of". A closed table
#: for the reason every table in this grammar is closed — an ordinal nobody
#: listed would otherwise be read as some other number entirely.
_FRACTION_WORDS: dict[str, int] = {"third": 3, "quarter": 4, "fourth": 4}


def _accept_fraction(
    stream: TokenStream, *, back_reference: str | None = None
) -> "ast.Half | None":
    """``a <ordinal> of <quantity>`` — "a third of their life" (Pox).

    :class:`ast.Half` with a denominator, not a node of its own: see that
    class's own note. The rounding rider is read here as well, in both the
    printed shapes "half" already accepts, so a card printing "a third of their
    life, rounded up" needs nothing further — Pox prints its rounding once at
    the end of the paragraph instead, which ``statements._round_every_half``
    already distributes.

    Nothing is consumed unless the whole opening is there, so a bare "a" keeps
    the number-word reading it has everywhere else.
    """
    mark = stream.mark()
    divisor = _accept_ordinal_head(stream)
    if divisor is None:
        return None
    try:
        inner = _parse_counted_amount(stream, back_reference=back_reference)
    except GrammarError:
        stream.reset(mark)
        return None
    return ast.Half(inner, _accept_rounding(stream), divisor)


def _accept_ordinal_head(stream: TokenStream) -> int | None:
    """``a <ordinal> of`` — the denominator, or None with nothing consumed."""
    mark = stream.mark()
    if not stream.accept_word("a"):
        return None
    ordinal = stream.peek_word()
    divisor = _FRACTION_WORDS.get(ordinal) if ordinal is not None else None
    if divisor is None:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_word("of"):
        stream.reset(mark)
        return None
    return divisor


def accept_fraction_head(stream: TokenStream) -> int | None:
    """``half`` or ``a <ordinal> of`` — the denominator, or None (nothing
    consumed).

    For the positions where the thing being divided is the production's own
    noun rather than a quantity it can hand to :func:`parse_amount`: "loses
    **half their life**", "discards **a third of the cards in their hand**",
    "sacrifices **a third of the creatures they control**". One reader, because
    the two spellings of a fraction are one printed idea and a production that
    knew only "half" is a production Pox refuses.
    """
    if stream.accept_word("half"):
        return 2
    return _accept_ordinal_head(stream)


def accept_rounding(stream: TokenStream) -> str:
    """Public name for :func:`_accept_rounding`, for the productions that read
    a fraction's noun themselves."""
    return _accept_rounding(stream)


def _accept_rounding(stream: TokenStream) -> str:
    """``[,] rounded up|down`` after a fraction, defaulting to down.

    Shared by "half" and by the "a <ordinal> of" reader above, because it is one
    printed rider and reading it twice is two places for the comma handling to
    come apart. The comma is put back when what follows it is a different
    clause: eating it unconditionally would take the separator a later
    production needs.
    """
    comma = stream.mark()
    had_comma = stream.accept_punct(",")
    if stream.accept_word("rounded"):
        if stream.accept_word("up"):
            return "up"
        stream.accept_word("down")
        return "down"
    if had_comma:
        stream.reset(comma)
    return "down"


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
        from .where_x import accept_this_way_count

        filt = parse_object_filter(stream)
        # "…this way" turns the count into a back-reference — see
        # `parse_equal_to`, which reads the identical trailer through the
        # identical shared reader.
        this_way = accept_this_way_count(stream, filt)
        if this_way is not None:
            return this_way
        return ast.CountOf(filt)
    stream.reset(mark)
    # "half **the sacrificed creature's power**, rounded down" (Freyalise
    # Supplicant). A characteristic of what the ability's own cost ate, read
    # here for the reason the count above is read here: `parse_equal_to` asks
    # the same two payment-channel readers, but it hands "half" straight to the
    # quantity parser *before* it reaches them — so a fraction **of** a channel
    # had no reader at all and the line refused at "the sacrificed creature 's
    # power" while the unhalved sentence one card over parsed fine.
    #
    # The leading "the" is this reader's, exactly as it is one function up.
    channel = stream.mark()
    stream.accept_word("the")
    for accept_channel in (accept_sacrificed_for_cost, accept_exiled_for_cost):
        payment = accept_channel(stream)
        if payment is not None:
            return payment
    stream.reset(channel)
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

    # "equal to **3 minus the number of cards they discarded this way**" (Mind
    # Bomb). A named count with a printed constant, and the same table the
    # ", where X is …" trailer reads — the two front ends print the same
    # phrases about the same counts, so they ask one reader rather than keeping
    # a row each. It consumes nothing unless a whole row matches, so every
    # other "equal to …" below keeps the reading it had.
    #
    # Late, and inside the function: `where_x` reads noun phrases, `nouns`
    # reads this module for its comparisons, so the cycle is broken at call
    # time exactly as `parse_object_filter`'s is below.
    from .where_x import accept_board_count

    named = accept_board_count(stream)
    if named is not None:
        return named

    stream.accept_word("the")

    if stream.accept_phrase("number", "of"):
        counters = accept_counters_on_source(stream)
        if counters is not None:
            return counters
        # Late import: nouns depends on this module for comparisons, so the
        # cycle is broken at call time rather than import time.
        from .nouns import parse_object_filter
        from .where_x import accept_this_way_count

        filt = parse_object_filter(stream)
        # "equal to the number of Mountains **put into a graveyard this way**"
        # (Volcanic Eruption). The trailing participle makes the count a
        # back-reference to an earlier step of this same effect, and it is read
        # through the reader the ", where X is …" trailer already uses — the
        # two front ends print the same phrases about the same records, so they
        # ask one function rather than keeping a row each (the same argument
        # `accept_board_count` above states for the named counts).
        this_way = accept_this_way_count(stream, filt)
        if this_way is not None:
            return this_way
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
    # "…where X is **the exiled card's mana value**" (Necropolis) — the same
    # shape one zone over. Its own reader so both front ends (this one and the
    # where-clause in `where_x.py`) ask one function: two copies of a phrase
    # that names a payment channel is how the two come to name different ones.
    exiled = accept_exiled_for_cost(stream)
    if exiled is not None:
        return exiled

    sacrificed = accept_sacrificed_for_cost(stream)
    if sacrificed is not None:
        return sacrificed

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
        # "…equal to its power **plus 2**" (Farrel's Mantle). CR 107.3: the
        # number is the read characteristic plus a printed constant, so the
        # constant rides the same node rather than being a second amount.
        bonus = 0
        mark_bonus = stream.mark()
        if stream.accept_word("plus"):
            token = stream.peek()
            printed = (
                int(token.text) if token is not None and token.kind == NUMBER
                else NUMBER_WORDS.get(token.text) if token is not None else None
            )
            if printed is None:
                stream.reset(mark_bonus)
            else:
                stream.advance()
                bonus = printed
        return ast.ThatMuch("its_power", bonus=bonus)

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

    # "equal to **its** toughness" (Exile: "Exile target nonwhite attacking
    # creature. You gain life equal to its toughness."). The same
    # back-reference "that creature's toughness" reads below, written with the
    # pronoun instead of the noun spelled out — one key, because it is one
    # question about one recorded object, and the producer gate in
    # ``_back_reference_payload`` is what makes the words legal either way.
    # A card whose first sentence records no toughness refuses by name rather
    # than gaining zero life.
    if stream.accept_phrase("its", "toughness"):
        return ast.ThatMuch("its_toughness")

    # "equal to **that creature's** power" (Terror of the Peaks) — the power of
    # the creature the *trigger's event* was about, not of the ability's source.
    # A different referent from "its power" above and so a different key: read
    # as that one it would deal the Dragon's own power, which is a number the
    # card never mentions.
    if stream.accept_phrase("that", "creature", "'s", "power"):
        return ast.ThatMuch("event_subject_power")

    # "…and its toughness is equal to **that creature's toughness**" (Broken
    # Visage) — the same creature, one characteristic over, and a *plain*
    # producer-gated back-reference where the power beside it also has a
    # trigger reading. The asymmetry is the pool's rather than this table's:
    # `_EVENT_QUANTITIES` is keyed by trigger kind and every row of it names a
    # *power* (the entering creature's, the damage dealt), so a toughness read
    # through that channel would silently be handed a power. Under a trigger
    # the words therefore refuse for want of a producer, which is the loud
    # failure; a step of the same effect that records one is what makes them
    # legal.
    if stream.accept_phrase("that", "creature", "'s", "toughness"):
        return ast.ThatMuch("its_toughness")

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

    # "equal to **that Wall's** mana value" (Word of Blasting) — the same
    # back-reference as "its mana value" above, written with the noun the
    # sentence in front of it used instead of a pronoun. One key, because it is
    # one question about one recorded object: the *producer* gate is what makes
    # the words legal, so a sentence with no destroy or bounce in front of it
    # still refuses by name. The noun is required to be one, and is not carried:
    # there is exactly one record to read.
    noun_mark = stream.mark()
    if stream.accept_word("that", "the"):
        noun = stream.peek_word()
        if noun is not None and _singular(noun) in _POSSESSIVE_NOUNS:
            stream.advance()
            if stream.accept_phrase("'s", "mana", "value"):
                return ast.ThatMuch("its_mana_value")
    stream.reset(noun_mark)

    stream.reset(mark)
    return None


#: Nouns a "that <noun>'s mana value" phrase may name. Card types and subtypes
#: both, for the reason ``references.parse_player_ref`` admits both in the same
#: position: "that Wall" names an object exactly as "that creature" does, and
#: which word the card prints is the card's business.
_POSSESSIVE_NOUNS = CARD_TYPES | ALL_SUBTYPES


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
    # "two or **fewer** cards in hand" (Paupers' Cage). English's countable
    # spelling of "less", and the same comparison: Magic prints "fewer" for
    # cards and creatures and "less" for life and mana value, so a reader that
    # knew one of them refused half the pool's thresholds.
    "fewer": "le",
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


#: How a printed clause names the permanent whose ability the sentence is —
#: what ``subject_filters.subject_matches`` is handed as ``source``. Two
#: spellings of one referent, exactly as ``references`` reads "that" and "the"
#: as one back-reference: an Aura says "the enchanted creature's" (Ironclaw
#: Curse) and a creature printing the same sentence about itself says "this
#: creature's". The Aura's line reaches this reader *unrewritten* —
#: ``auras.aura_combat_restriction`` rewrites only the sentence's leading
#: subject — which is why the enchanted spelling has to be here rather than
#: normalized away upstream.
_SOURCE_POSSESSIVES: tuple[tuple[str, ...], ...] = (
    ("the", "enchanted", "creature", "'s"),
    ("this", "creature", "'s"),
)

#: The characteristics a relative bound may name. English rather than a shared
#: rule, on ``combat_restrictions._NUMBER_WORDS``'s argument — and closed, so a
#: clause naming a third one refuses here instead of reaching a comparison with
#: nothing to read.
_RELATIVE_CHARACTERISTICS = ("power", "toughness")


def accept_source_relative_comparison(
    stream: TokenStream, characteristic: str
) -> "ast.SourceRelativeComparison | None":
    """``equal to or {greater,less} than <the source>'s <power|toughness>``.

    Ironclaw Curse's "creatures with power **equal to or greater than the
    enchanted creature's toughness**" — a bound that is a live characteristic
    rather than a printed number, so it is its own node and its own payload key
    (see :class:`ast.SourceRelativeComparison`).

    Returns None with the cursor untouched when the words after the
    characteristic are anything else, so ``parse_comparison``'s printed-number
    reading is left exactly as it was: this is only ever reached on a phrase
    that reading cannot take.

    The comparison word comes from :data:`_COMPARISON_WORDS`, the same table the
    printed-number form reads — one vocabulary, so "equal to or less than"
    cannot come to mean something different from "2 or less".
    """
    mark = stream.mark()
    if not stream.accept_phrase("equal", "to", "or"):
        stream.reset(mark)
        return None
    token = stream.peek()
    word = token.text if token is not None and token.kind == WORD else None
    if word not in _COMPARISON_WORDS:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_word("than"):
        stream.reset(mark)
        return None
    if not any(stream.accept_phrase(*phrase) for phrase in _SOURCE_POSSESSIVES):
        stream.reset(mark)
        return None
    bound = stream.peek_word()
    if bound not in _RELATIVE_CHARACTERISTICS:
        stream.reset(mark)
        return None
    stream.advance()
    return ast.SourceRelativeComparison(
        characteristic, _COMPARISON_WORDS[word], str(bound)
    )




# ---------------------------------------------------------------------------
# Caps on a quantity
# ---------------------------------------------------------------------------

#: The printed terms of a life-gain cap, as word tuples, and what each one is
#: about. Three of them name a *kind of damage recipient* and one names mana
#: spent on X, which is why the node keeps them apart rather than folding them
#: into a single "the cap".
_LIFE_GAIN_CAP_TERMS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("the", "player", "'s", "life", "total", "before", "the", "damage",
      "was", "dealt"), "player"),
    (("the", "planeswalker", "'s", "loyalty", "before", "the", "damage",
      "was", "dealt"), "planeswalker"),
    (("the", "creature", "'s", "toughness"), "creature"),
)


def _accept_life_gain_cap_term(stream: TokenStream) -> "ast.LifeGainCap | None":
    """One term of the cap list, or None with the cursor put back."""
    for phrase, recipient in _LIFE_GAIN_CAP_TERMS:
        if stream.accept_phrase(*phrase):
            return ast.LifeGainCap("recipient_capacity", recipient=recipient)
    mark = stream.mark()
    # "the amount of {B} spent on X" (Soul Burn). The symbol is payload, not
    # part of the term: a card printing {R} here reads the same sentence.
    if stream.accept_phrase("the", "amount", "of"):
        token = stream.peek()
        if token is not None and token.kind == MANA:
            stream.advance()
            if stream.accept_phrase("spent", "on", "x"):
                return ast.LifeGainCap(
                    "mana_spent_on_x", symbol=token.text.strip("{}").upper()
                )
    stream.reset(mark)
    return None


def accept_life_gain_cap(stream: TokenStream) -> tuple["ast.LifeGainCap", ...]:
    """``, but not more [life] than <term>[, <term>]… [, or <term>]``.

    An empty tuple with the cursor put back when the words are not there, so
    the ordinary "you gain N life" is untouched.

    A *list* of terms rather than one, because the card prints a list and only
    one of its members can be the binding one: Drain Life and Soul Burn name a
    term per kind of thing "any target" admits, and Soul Burn names one more
    that is about the cast rather than the target. Any unrecognized term takes
    the whole clause down (the cursor is restored and the line then fails for
    unconsumed text) rather than being dropped -- a cap silently narrowed to
    the terms this table happens to know would make the card gain more life
    than it prints, which is the direction that never fails loudly.
    """
    mark = stream.mark()
    if not stream.accept_punct(","):
        return ()
    if not stream.accept_phrase("but", "not", "more"):
        stream.reset(mark)
        return ()
    # Drain Life prints "but not more **life** than"; Soul Burn drops the noun.
    stream.accept_word("life")
    if not stream.accept_word("than"):
        stream.reset(mark)
        return ()
    terms: list[ast.LifeGainCap] = []
    closed = False
    while True:
        term = _accept_life_gain_cap_term(stream)
        if term is None:
            stream.reset(mark)
            return ()
        terms.append(term)
        if closed or not stream.accept_punct(","):
            break
        # The conjunction is required before the last of several terms, and
        # reading it is what ends the list. Treating "or" as optional
        # punctuation let "A, B, C" — a printed list with a term missing out of
        # the middle of it — parse as happily as the printed "A, B, or C",
        # which is the dropped-rider class the deletion probe watches for.
        closed = stream.accept_word("or")
    if not closed and len(terms) > 1:
        stream.reset(mark)
        return ()
    return tuple(terms)
