"""A printed **bound on a quantity**, parsed beside the quantity it bounds.

Two shapes and one subject. A *comparison* is a threshold the quantity is
tested against — "power **3 or greater**" (Meekstone), "power **less than**
this creature's power" (Bog Rats' relatives) — and a *cap* is a ceiling it may
not exceed — "you gain that much life, **but not more than the creature's
toughness**" (Drain Life, Soul Burn). Neither is a quantity; both are a
sentence's statement about one.

Split out of ``amounts`` when Exodus' wave 1 took that module past the
thousand-line guard, on the seam ``amounts`` had already written down in prose:
its comment above ``_COMPARISON_WORDS`` said a comparison "lives with the
amounts it compares rather than with the filter that happens to carry one", and
the section header below it said "Caps on a quantity". The cut is those two
sections whole.

**Above ``amounts``, not below it**, which is why the names could not follow
``accept_source_reference`` down to ``readers``: a comparison reads
``parse_amount``, so this module imports ``amounts`` and ``amounts`` cannot
re-export what it defines. The callers name this module directly instead, and
``nouns`` keeps re-exporting ``parse_comparison`` under its own name so every
``nouns.parse_comparison`` caller is untouched.

No mirror on the lowering side, and deliberately: a bound is read off the node
by whichever family carries it (``ObjectFilter.power``, ``ast.GainLife
.capped_by``), so there is no lowering module of its own to fork.

**Two more shapes arrived at Urza's Saga**, and both are this module's subject
rather than a widening of it. :func:`accept_cards_in_hand_bound` is a
comparison whose right-hand side is a *hidden zone* — it came up from
`postmodifiers`, where it sat because a filter was its first caller, exactly as
``parse_comparison`` once did. :func:`accept_superlative` is the third shape
beside the comparison and the cap: not a threshold and not a ceiling but an
**extreme**, the end of a range, which is a statement about a set rather than
about any one member of it. It is here rather than in `readers` because the
sentence that reads it back ("…tied for least toughness") is a *bound* on the
same quantity by the same words, and one reader for both is what stops the noun
phrase and its tie-break sentence disagreeing about which characteristic was
printed.
"""

from __future__ import annotations

from . import ast
from .amounts import parse_amount
from .lexer import MANA, WORD
from .stream import TokenStream
from .vocabulary import NUMBER_WORDS

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


#: The comparative adjectives a printed noun phrase states a bound with *no*
#: number and *no* named other object: "a creature with **lesser** power" (No
#: Quarter). The thing compared against is left implicit because English has
#: already supplied it — the sentence is about two creatures and this is the
#: second of them.
#:
#: Strict, and that is the word rather than a convenience: "lesser" is *less
#: than*, where the spelled-out form one production down is "equal to or less
#: than". Reading either as the other changes which creatures a card names by
#: exactly the tie, which for No Quarter is every mirror match.
_COMPARATIVE_ADJECTIVES = {"lesser": "lt", "greater": "gt"}


def accept_comparative_characteristic(
    stream: TokenStream,
) -> "ast.SourceRelativeComparison | None":
    """``lesser power`` / ``greater power`` — a bound stated against the *other*
    object the sentence is about, with neither a number nor a possessive.

    "Whenever a creature becomes blocked by **a creature with lesser power**"
    (No Quarter). The comparison is between the two halves of a combat pair, and
    the phrase names the second half only: which object "lesser" is lesser
    *than* is the one the sentence already named.

    It lowers onto the same ``characteristic_vs_source`` key Ironclaw Curse's
    spelled-out comparison uses, and that is exact rather than convenient: the
    matcher reads that key against the ``source`` its caller supplies, and at
    both block fire sites the source supplied to a subject filter **is** the
    other creature of the pair (``phases/declare_blockers_step.py`` passes the
    attacker when testing a blocker and the blocker when testing an attacker).
    So the two spellings are one question with one answer, and a second key
    would be a second reading of "than what?".

    Returns None with the cursor untouched when the word is not comparative, so
    "with power 2 or less" and every other bound keep their own readings.
    """
    mark = stream.mark()
    word = stream.peek_word()
    if word not in _COMPARATIVE_ADJECTIVES:
        return None
    stream.advance()
    characteristic = stream.peek_word()
    if characteristic not in _RELATIVE_CHARACTERISTICS:
        stream.reset(mark)
        return None
    stream.advance()
    return ast.SourceRelativeComparison(
        str(characteristic), _COMPARATIVE_ADJECTIVES[word], str(characteristic)
    )


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


def accept_target_bound(stream: TokenStream) -> int | None:
    """``one or two`` / ``one, two, or three`` — the ceiling it names.

    CR 601.2c's variable target count, printed as an enumeration rather than as
    a range. The enumeration must run ``1, 2, … n`` with nothing skipped and
    nothing repeated: a card printing "one or three" would mean something this
    returns no room to say, and answering ``3`` for it would let the caster
    name two. Nothing consumed when the words are not an enumeration, so the
    caller can reset and refuse the line whole.

    Here rather than in either family that reads it. It arrived in
    ``effects/counters.py`` with Contagion's distributed counters ("among one or
    two target creatures") and Arc Lightning prints the same clause about
    *damage* ("among one, two, or three targets") — two families, so the
    fragment moved down instead of one importing the other. This module,
    because a printed ceiling on a count is what it is for: its own docstring
    calls a cap "a ceiling it may not exceed", and the count is the quantity.

    Numbers are read straight off ``NUMBER_WORDS``, as ``amounts`` and
    ``condition_clauses`` already do — that table is the single source and
    ``phrases._accept_number`` is one module's thin wrapper over it, not the
    canonical reader, and it sits well above this layer.
    """
    mark = stream.mark()
    numbers: list[int] = []
    while True:
        stream.accept_punct(",")
        stream.accept_word("or")
        word = stream.peek_word()
        value = NUMBER_WORDS.get(word) if word is not None else None
        if value is None:
            break
        stream.advance()
        numbers.append(value)
        if not (stream.at_punct(",") or stream.at_word("or")):
            break
    if numbers != list(range(1, len(numbers) + 1)) or len(numbers) < 2:
        stream.reset(mark)
        return None
    return numbers[-1]


__all__ = [
    "accept_comparative_characteristic", "accept_life_gain_cap",
    "accept_target_bound",
    "accept_source_relative_comparison", "parse_comparison",
]


def accept_cards_in_hand_bound(stream: TokenStream) -> str | None:
    """``greater than the number of cards in your hand`` (Ensnaring Bridge).

    A bound off a **hidden zone**, which is what separates it from the two
    counter bounds beside it: no board holds the number, so neither the pure
    matcher nor a source-relative read can answer it — only a caller holding
    the seat can. Whose hand is returned rather than baked in, so a card
    printing "an opponent's hand" is data here and a matcher branch there.

    Read *before* ``parse_comparison``, whose "N or greater" shape opens on a
    quantity and would refuse these words with "expected a quantity" — a
    refusal naming the one thing the phrase does not contain. Declines without
    consuming, so every other bound keeps the reading it has.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "greater", "than", "the", "number", "of", "cards", "in",
    ):
        stream.reset(mark)
        return None
    if stream.accept_phrase("your", "hand"):
        return "you"
    # "…each creature that player controls **with power greater than the number
    # of cards in their hand**." (Noetic Scales.) The same bound over a
    # different seat, which is the whole of what this function's docstring
    # already promised: whose hand is returned rather than baked in. "Their"
    # agrees with the subject the sentence has already named — "each creature
    # **that player** controls" — so it is the seat the firing event froze, and
    # the matcher refuses it wherever nothing froze one.
    if stream.accept_phrase("their", "hand"):
        return "that_player"
    stream.reset(mark)
    return None


#: The two printed extremes and the three printed characteristics, as the words
#: a card spells them. A table rather than a branch because the whole content of
#: this reader is which two words were printed: Purging Scythe prints "least
#: toughness", Drop of Honey "least power", Tariff and Juxtapose "greatest mana
#: value", and a card printing "greatest toughness" needs no code at all.
#:
#: Mapped to the extreme each word names, because the printed vocabulary is
#: wider than the two answers: "the **lowest** mana value" (Stronghold Gambit)
#: is "the least mana value" said the way older templating said it, and a
#: second extreme word would be a second answer every reader downstream would
#: have to learn.
_EXTREME_WORDS = {
    "least": "least", "greatest": "greatest",
    "lowest": "least", "highest": "greatest",
}

#: The characteristic word, as one or two tokens, mapped to the name
#: ``handlers/permanent_choices`` reads it back under. "Mana value" is two words
#: and has to be tried first for ``parse_comparison``'s standing reason: a
#: single-word probe would take "mana" and strand "value".
_SUPERLATIVE_CHARACTERISTICS = (
    (("mana", "value"), "mana_value"),
    (("power",), "power"),
    (("toughness",), "toughness"),
)


def accept_superlative(
    stream: TokenStream, *, article: bool = True, parse_filter=None,
) -> "ast.Superlative | None":
    """``[the] least|greatest power|toughness|mana value``, or None.

    "…the creature with **the least toughness**" (Purging Scythe) prints the
    article; "…are tied for **least toughness**", the tie-break sentence behind
    it, does not. One reader for both, because the two sentences of that card
    have to agree about which characteristic was named — read by two productions
    they could disagree, and a card whose tie-break named a *different*
    characteristic would be admitted with the mismatch silently resolved in
    favour of whichever was read first.

    Declines without consuming, so every other "with …" phrase keeps its own
    reading — the discipline every probe in ``with_clauses`` follows.
    """
    mark = stream.mark()
    if article and not stream.accept_word("the"):
        stream.reset(mark)
        return None
    extreme = None
    for word, meaning in _EXTREME_WORDS.items():
        if stream.accept_word(word):
            extreme = meaning
            break
    if extreme is None:
        stream.reset(mark)
        return None
    for words, name in _SUPERLATIVE_CHARACTERISTICS:
        if stream.accept_phrase(*words):
            # "…with the greatest power **among creatures on the battlefield**"
            # (Topple). The comparison set, read only where a noun-phrase
            # reader is handed in — `postmodifiers`' own *parse_filter*, passed
            # on by ``with_clauses``, for the reason it takes one: ``nouns``
            # sits above this layer. The
            # tie-break sentence ("…tied for least toughness") passes none, and
            # has to agree with the phrase it breaks the tie of.
            if parse_filter is not None and stream.accept_word("among"):
                return ast.Superlative(extreme, name, among=parse_filter(stream))
            return ast.Superlative(extreme, name)
    # An extreme over a characteristic nothing can read is not this phrase.
    # Refusing without consuming is what makes the line fail loudly at whatever
    # reads it next, rather than describing a set by the half of the phrase
    # this reader happened to understand.
    stream.reset(mark)
    return None
