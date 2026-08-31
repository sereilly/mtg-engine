"""The `…, where X is …` clause: what defines a spell's X.

Split out of `phrases` at the thousand-line guard, the round two branches both
added a definition to it. A family rather than an arbitrary cut, and the name
re-forms a mirror the lowering side already had: `lowering/where_x.py` has
existed since round 23, when this clause was the piece that could be lifted out
of `lower.py`. One home per template per side, findable from the family name.

Everything here reads a *definition* — a count, a characteristic, an offset, a
multiplier — and hands back an `Amount` for the sentence around it to carry.
The sentence itself is read a layer up; nothing in this file knows what the X
is for.
"""

from . import ast
from .amounts import (
    accept_added_base, accept_counters_on_source, accept_damage_dealt_this_turn,
    accept_exiled_for_cost, accept_sacrificed_for_cost,
)
from .lexer import NUMBER
from .nouns import parse_object_filter
from .stream import TokenStream
from .vocabulary import NUMBER_WORDS
from .phrases import NUMBER_SLOT, _accept_literal, _parse_duration


_BOARD_COUNTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Black Vise: the excess of a hand over the threshold.
    (
        "cards_in_hand_over_base",
        ("the", "number", "of", "cards", "in", "their", "hand", "minus",
         NUMBER_SLOT),
    ),
    # The Rack, Storm World: the shortfall of a hand below it. The mirror of
    # the row above and the same handler, which has computed both directions
    # since Black Vise landed — this phrase is what finally reaches the
    # deficit branch from the grammar rather than from a card hook.
    (
        "base_over_cards_in_hand",
        (NUMBER_SLOT, "minus", "the", "number", "of", "cards", "in", "their",
         "hand"),
    ),
    # Mind Bomb: the shortfall of what a player *chose to discard* below the
    # printed number. Beside the two hand rows above because it is the same
    # arithmetic with the same constant-as-payload — what differs is the pile
    # counted, and that is what the name is for. Not a board state: "this way"
    # is the count an earlier step of this same effect recorded, which is why
    # the lowering below refuses the phrase with no discard in front of it.
    (
        "base_over_discarded_this_way",
        (NUMBER_SLOT, "minus", "the", "number", "of", "cards", "they",
         "discarded", "this", "way"),
    ),
    (
        "untapped_lands_at_turn_start",
        ("the", "number", "of", "untapped", "lands", "they", "controlled",
         "at", "the", "beginning", "of", "this", "turn"),
    ),
)


#: The characteristics a "where X is **its** …" clause may name, as the printed
#: words that spell each one. A table rather than three branches: they differ in
#: which accessor the resolution reads and in nothing else, so a card printing
#: the next one is data.
_SUBJECT_CHARACTERISTICS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("mana", "value"), "mana_value"),
    (("power",), "power"),
    (("toughness",), "toughness"),
)


#: The printed words that add or subtract a constant from a quantity, and the
#: sign each one carries.
_OFFSET_WORDS: dict[str, int] = {"minus": -1, "plus": 1}


#: What a printed multiplier word is worth. A table rather than a literal for
#: the reason every other printed number in this file is payload: "twice" and
#: "three times" are one shape, and a card printing the other one must not need
#: a second production.
_MULTIPLIER_WORDS: dict[str, int] = {"twice": 2}


def accept_board_count(stream: TokenStream) -> ast.BoardCount | None:
    """The named count at the cursor, or None with nothing consumed.

    One reader for the two front ends that print these phrases — the
    ", where X is …" trailer below, and ``amounts.parse_equal_to``'s "equal to
    …". They read the same phrases about the same counts, so a row added for
    one and missing from the other would be the same printed sentence meaning a
    count on one card and nothing at all on the next.
    """
    for name, phrase in _BOARD_COUNTS:
        matched, base = _accept_literal(stream, *phrase)
        if matched:
            return ast.BoardCount(name, base)
    return None


def _parse_where_x_is(stream: TokenStream) -> ast.BoardCount | None:
    """", where X is <board-state count>" — the trailer that says what the X of
    the preceding clause counts.

    Returning None on an unrecognized count leaves its tokens unconsumed, so the
    line fails the full-consumption invariant and falls back. That is the whole
    value of the production: the alternative — consuming "where X is …" and
    whatever follows — would make every card written this way compile onto
    whichever count the caller happened to assume.
    """
    mark = stream.mark()
    stream.accept_punct(",")
    if not stream.accept_phrase("where", "x", "is"):
        stream.reset(mark)
        return None
    count = accept_board_count(stream)
    if count is not None:
        return count
    stream.reset(mark)
    return None


def _accept_offset(stream: TokenStream) -> int:
    """``minus 1`` / ``plus 2`` after a quantity — the signed constant, or 0.

    The number is payload for the reason every printed number in this file is:
    "minus 1" and "minus 4" are one arithmetic, and spelling either into the
    phrase makes the other a non-match.
    """
    word = stream.peek_word()
    sign = _OFFSET_WORDS.get(word) if word else None
    if sign is None:
        return 0
    mark = stream.mark()
    stream.advance()
    token = stream.peek()
    if token is not None and token.kind == NUMBER:
        stream.advance()
        return sign * int(token.text)
    number = NUMBER_WORDS.get(stream.peek_word() or "")
    if number is not None:
        stream.advance()
        return sign * number
    stream.reset(mark)
    return 0


def parse_where_x_definition(stream: TokenStream) -> "ast.Amount | None":
    """``[,] where X is <definition>`` — or None when the clause is absent.

    **One parser**, because there were two. `statements._parse_where_x` read the
    sentence-level clause and `effects/characteristics._parse_gets` read the
    pump's own, and the two accepted different definitions: only the pump knew
    "the greatest power among", only the sentence knew "that died under your
    control". Which alternatives a card could use therefore depended on which
    sentence it was printed in, which is not a rule Magic has. Adding "its mana
    value" to one of them would have made a third such difference, so the fork
    is closed instead.

    Refuses anything it cannot read rather than skipping the clause: an
    undefined X silently reads as the *cast's* X, and a permanent's triggered
    ability has no cast at all.
    """
    mark = stream.mark()
    stream.accept_punct(",")
    if not stream.accept_word("where"):
        stream.reset(mark)
        return None
    if not (stream.accept_word("x") and stream.accept_word("is")):
        raise stream.error("expected 'X is' after 'where'")
    # "…where X is **its** mana value" / "…where X is **its toughness minus
    # 1**". A characteristic of the object the sentence already named rather
    # than an aggregate over a set, so it carries no filter — read first
    # because it does not open with "the".
    #
    # Which characteristic and which printed offset are both payload: the three
    # words are one production, and "minus 1" is the same arithmetic "minus 4"
    # is on Black Vise. A clause that named a characteristic and then printed
    # words this cannot read refuses through the ordinary path below rather
    # than dropping them, which is what keeps Blood Lust's -X from becoming the
    # whole toughness.
    if stream.at_word("its"):
        its_mark = stream.mark()
        stream.advance()
        for phrase, name in _SUBJECT_CHARACTERISTICS:
            if stream.accept_phrase(*phrase):
                return ast.CharacteristicOfSubject(name, _accept_offset(stream))
        stream.reset(its_mark)
    # "…where X is **the power of that blocked creature**" (Glyph of Delusion).
    # The same reading as "its" one branch up, with the referent spelled out
    # instead of pronominalised — which is what a sentence does when it named
    # more than one object and "its" would not say which. The phrase is carried
    # on the node and matched against the sentence's target roles by the
    # lowering, where the sentence is in hand; refusing to guess is the point,
    # since a mismatched referent would read a characteristic off the wrong
    # target and the card would still look supported.
    named_mark = stream.mark()
    if stream.accept_word("the"):
        for phrase, name in _SUBJECT_CHARACTERISTICS:
            phrase_mark = stream.mark()
            if stream.accept_phrase(*phrase) and stream.accept_phrase("of", "that"):
                referent = parse_object_filter(stream)
                return ast.CharacteristicOfSubject(
                    name, _accept_offset(stream), referent
                )
            stream.reset(phrase_mark)
    stream.reset(named_mark)
    # "…where X is **that creature's mana value**" (Living Armor). The same
    # named back-reference one branch up, in English's other word order: a
    # possessive rather than an "of" phrase. One production for both, because
    # what they mean is identical — the referent travels on the same node and
    # is matched against the sentence's target roles by the same lowering — and
    # two would be two answers to which characteristics a card may name.
    possessive_mark = stream.mark()
    if stream.accept_word("that"):
        referent = parse_object_filter(stream)
        if stream.accept_word("'s"):
            for phrase, name in _SUBJECT_CHARACTERISTICS:
                if stream.accept_phrase(*phrase):
                    return ast.CharacteristicOfSubject(
                        name, _accept_offset(stream), referent
                    )
    stream.reset(possessive_mark)
    # "…where X is **twice** the number of white creatures that player
    # controls" (Jovial Evil). A multiplier in front of whatever definition
    # follows, read here so it scales every one of them rather than only the
    # count: "twice the greatest power among …" would mean the same thing and
    # needs no second production. The factor is payload — see ``ast.Times``.
    factor = _accept_multiplier(stream)
    if factor is not None:
        scaled = parse_where_x_definition_body(stream)
        return ast.Times(factor, scaled)
    # "…where X is **3 plus** the amount of damage dealt …" (Blazing Effigy).
    # A constant added to whatever definition follows, read here beside the
    # multiplier and for its reason: the sum is not a property of any one
    # alternative below, and folding it into one would leave every other
    # definition unable to carry a base the card printed.
    base = accept_added_base(stream)
    if base is not None:
        return ast.Plus(ast.Fixed(base), parse_where_x_definition_body(stream))
    return parse_where_x_definition_body(stream)


def _accept_multiplier(stream: TokenStream) -> int | None:
    """``twice`` / ``three times`` in front of a quantity, or None.

    Two spellings because English has two: a single word for 2 and an
    ``<n> times`` phrase for everything above it. Both produce a factor, so
    nothing downstream can tell which one the card printed.
    """
    word = stream.peek_word()
    if word in _MULTIPLIER_WORDS:
        stream.advance()
        return _MULTIPLIER_WORDS[word]
    mark = stream.mark()
    if word in NUMBER_WORDS and stream.peek_word(1) == "times":
        stream.advance(2)
        return NUMBER_WORDS[word]
    stream.reset(mark)
    return None


def parse_where_x_definition_body(stream: TokenStream) -> "ast.Amount":
    """The definition itself, once any multiplier in front of it is consumed.

    Split from :func:`parse_where_x_definition` so the multiplier scales every
    alternative below rather than being wired into one of them; refuses, never
    returns None, because by here "where X is" has been read and the clause owes
    a definition.
    """
    stream.accept_word("the")
    # "…the **amount of damage dealt to this creature this turn by other
    # sources named ~**" (Blazing Effigy). A history rather than an aggregate
    # over a noun phrase, so it is read before the three below: what it names
    # is over by the time the clause is asked, and none of them could see it.
    dealt = accept_damage_dealt_this_turn(stream)
    if dealt is not None:
        return dealt
    # "…where X is **the exiled card's mana value**" (Necropolis). A
    # characteristic of what the ability's own *cost* ate rather than an
    # aggregate over anything a zone still holds, so it is read beside the
    # damage history above and through the same reader `parse_amount` uses.
    exiled = accept_exiled_for_cost(stream)
    if exiled is not None:
        return exiled
    # "…where X is **the sacrificed creature's mana value**" (Burnt Offering).
    # The exile above one zone over: what the *spell's* own additional cost ate
    # (CR 601.2b), read through the one reader both front ends share so the
    # where-clause and an "equal to" amount cannot come to name different
    # channels.
    sacrificed = accept_sacrificed_for_cost(stream)
    if sacrificed is not None:
        return sacrificed
    # Three aggregates over one noun phrase, and the words are what tell them
    # apart: "the number of" counts the objects, "the greatest power among"
    # takes a maximum over them (Carrion Grub).
    if stream.accept_phrase("greatest", "power", "among"):
        return ast.GreatestPowerAmong(parse_object_filter(stream))
    # "…the **total power of the creatures sacrificed this way**" (Sword of the
    # Ages). A fourth aggregate over a noun phrase, and the words are again what
    # tell it apart: a *sum* of powers, over the set the ability's own cost ate
    # rather than over anything a zone still holds.
    if stream.accept_phrase("total", "power", "of"):
        stream.accept_word("the")
        filt = parse_object_filter(stream)
        if stream.accept_phrase("sacrificed", "this", "way"):
            return ast.TotalPowerSacrificedThisWay(filt)
        raise stream.error(
            "a total power is only read off what was sacrificed this way"
        )
    if not stream.accept_phrase("number", "of"):
        raise stream.error("expected 'the number of' in a where-clause")
    # "…the number of **+1/+1 counters on it**" (Primordial Ooze). In front of
    # the noun parser for the reason `_parse_counted_amount` puts it there: a
    # counter is not an object, so ``parse_object_filter`` would refuse the
    # words and take the whole line with it.
    counters = accept_counters_on_source(stream)
    if counters is not None:
        return counters
    filt = parse_object_filter(stream)
    # "…the number of creatures **that died this way**" (Hellfire). Neither the
    # board nor the turn's history: the objects one earlier step of this same
    # effect destroyed. Read before the turn-history spelling below because the
    # two share their first two words and differ only in what follows them.
    if stream.accept_phrase("that", "died", "this", "way"):
        return ast.CountOfDeathsThisWay(filt)
    # "…the number of creatures **that died under your control this turn**"
    # (Liliana's Standard Bearer). A history, and the opposite set from the one
    # the bare filter names: these are exactly the creatures the battlefield no
    # longer holds.
    if stream.accept_phrase("that", "died", "under", "your", "control"):
        _parse_duration(stream)
        return ast.CountOfDeaths(filt)
    return ast.CountOf(filt)
