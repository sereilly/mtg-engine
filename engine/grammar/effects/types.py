"""What a permanent **becomes**: the ``becomes`` verb and its five branches.

CR 205 is the spine of it — an animation ("becomes a 3/3 creature"), a gained
card type ("becomes an artifact in addition to its other types"), a supertype
("becomes snow") and a basic land type ("becomes a Swamp") — with CR 105's
colour change ("becomes white until end of turn") riding along because it is a
*branch of the same production*: the word is the same and only what follows it
tells the five apart, so splitting the colour out would fork one production into
two that each have to decline the other's sentence.

The mirror of ``lowering/types.py``, whose own docstring predicted this file
would be near-empty and therefore not worth making. That was true when the
split it describes was taken and it is not true now: the ``becomes`` cluster is
316 lines on its own, and ``effects/characteristics.py`` had reached 985 of the
thousand-line cap with the P/T family — ``gets``/``gains``/``loses``/``has``,
the base-P/T rewrites and the counters — which shares no helper with anything
here. Two families, one file, and the cap is the signal that said so.

``_parse_no_longer_supertype`` comes with them: it is the mirror sentence of
``becomes snow`` with the same vocabulary lookup and the same node, and its only
caller is the same dispatcher.
"""

from .. import ast
from ..amounts import expect_pt
from ..errors import GrammarError
from ..phrases import _parse_duration
from ..stream import TokenStream
from ..vocabulary import (CARD_TYPES, COLOR_WORDS, IMPLEMENTED_KEYWORDS,
                          LAND_TYPES, SUBTYPE_INDEX, TYPE_LINE_SUPERTYPES,
                          match_longest, singular as _singular_type)


def _parse_becomes(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """"<subject> becomes <colour>" or "<subject> becomes a P/T <types> creature
    …". One production, because the word is the same and what follows it is what
    tells the two apart — a colour word, or a P/T.

    The colour form is a *replacement* and the creature form is an *addition*,
    which is the whole reason they are different nodes; both are the sentence's
    entire effect, so a word after "becomes" that starts neither must fail
    rather than be skipped.
    """
    # "…**become** a 3/3 Sphinx creature" is the same verb after the "you may
    # have" wrapper has taken its subject; English changes the inflection and
    # the card does not change what it does.
    stream.expect_word("becomes", "become")
    # "…becomes **the color of your choice**" (Alchor's Tomb). CR 609.3 makes
    # the choice part of the resolution, so the sentence names no colour and the
    # node carries the sentinel instead. Read before the colour-word branch,
    # which would see "the" and refuse — and read here rather than as a separate
    # production, because it is the same verb with the same duration tail.
    # "…becomes **the color or colors of your choice**" (Dream Coat). Read
    # before the singular, which shares its first three words and would leave
    # "or colors of your choice" unconsumed — the refusal Dream Coat's ability
    # met. The plural is a different offer (a set of colours, CR 105.2), so it
    # carries its own sentinel rather than collapsing into the singular's.
    if stream.accept_phrase("the", "color", "or", "colors", "of", "your", "choice"):
        return ast.BecomeColor(subject, ast.CHOSEN_COLORS, _parse_duration(stream))
    if stream.accept_phrase("the", "color", "of", "your", "choice"):
        return ast.BecomeColor(subject, ast.CHOSEN_COLOR, _parse_duration(stream))
    token = stream.peek()
    word = str(token.text).lower() if token is not None else ""
    # "…becomes **colorless** until end of turn." (Raging Spirit, Ersatz
    # Gnomes.) Read before the colour table, which cannot hold it: CR 105.2c
    # makes colourless the absence of colour, and `COLOR_WORDS`' values are mana
    # symbols. The duration is read the same way and for the same reason.
    if word == "colorless":
        stream.advance()
        return ast.BecomeColor(subject, ast.COLORLESS, _parse_duration(stream))
    if word in COLOR_WORDS:
        stream.advance()
        # The duration is read rather than assumed. Without it the four words
        # of "until end of turn" would be unconsumed text and the line would
        # refuse — which is the *safe* failure, but it costs five cards; and
        # skipping them instead would turn a turn-long colour change into the
        # Lace cycle's indefinite one.
        return ast.BecomeColor(subject, COLOR_WORDS[word], _parse_duration(stream))
    animated = _parse_become_creature(stream, subject)
    if animated is not None:
        return animated
    gained = _parse_gain_type(stream, subject)
    if gained is not None:
        return gained
    # "…**becomes snow**." (Arcum's Weathervane.) Read after the type form,
    # whose "becomes an artifact" opens with an article this branch does not
    # accept, so the two cannot claim each other's sentence.
    supertype = _parse_becomes_supertype(stream, subject)
    if supertype is not None:
        return supertype
    land_type = _parse_becomes_land_type(stream, subject)
    if land_type is not None:
        return land_type
    raise stream.error("expected a colour or a creature body after 'becomes'")


def _parse_becomes_land_type(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.ChangeLandType | None":
    """``… becomes a Swamp until its controller's next untap step.``
    (Orcish Farmer.)

    Last of the ``becomes`` branches, because it is the one that accepts a bare
    noun after the article and would otherwise claim "becomes an artifact
    creature" — the animation and the gained-type forms both open the same way
    and both say more than a land type. Read against the land-type catalog
    (`data/vocabulary/`) rather than a list of the five basics, so a set
    printing a new one needs `scripts/fetch_vocabulary.py` and nothing here.
    """
    mark = stream.mark()
    # "…becomes **the basic land type of your choice** until end of turn."
    # (Jinx.) CR 609.3 makes the choice part of resolving the spell, so the
    # sentence names no type and the node carries the sentinel — the same shape
    # "becomes the color of your choice" takes two branches up, and read before
    # the article branch below, which would see "the" and refuse.
    if stream.accept_phrase("the", "basic", "land", "type", "of", "your", "choice"):
        return ast.ChangeLandType(
            subject, ast.CHOSEN_LAND_TYPE, _parse_duration(stream)
        )
    if not (stream.accept_word("a") or stream.accept_word("an")):
        stream.reset(mark)
        return None
    word = stream.peek_word()
    if word is None or word not in LAND_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    return ast.ChangeLandType(subject, word, _parse_duration(stream))


def _parse_becomes_supertype(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.ChangeSupertype | None":
    """``… becomes snow.`` (Arcum's Weathervane.)

    A bare supertype word, with no "in addition to its other types" tail:
    CR 205.4a puts supertypes in front of the card types, so adding one
    displaces nothing and the printed sentence has nothing more to say. The word
    is checked against the vocabulary catalog rather than a literal — a set
    printing a new supertype needs `scripts/fetch_vocabulary.py` and nothing
    here.
    """
    word = stream.peek_word()
    if word is None or word not in TYPE_LINE_SUPERTYPES:
        return None
    stream.advance()
    return ast.ChangeSupertype(subject, word, True, _parse_duration(stream))


def _parse_no_longer_supertype(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.ChangeSupertype | None":
    """``<subject> is no longer snow.`` (Arcum's Weathervane's other ability.)

    The mirror of :func:`_parse_becomes_supertype`, and non-consuming on
    refusal: "is" opens sentences this production has no business claiming, so
    anything it cannot finish keeps the refusal it already had.

    A **quantified** subject is declined here, in the parse rather than in the
    lowering. "All lands are no longer snow" (Melting) is a static ability of a
    permanent rather than a one-shot effect, and its home is
    `engine/land_types.py`'s derivation table beside the other board-wide land
    statics — exactly as "All Mountains are Plains" sits beside
    `change_land_type`. `derived.py` is consulted only where the grammar refuses
    the line *in full*, so a production that parsed the sentence and left the
    lowering to raise would take the table's line away and give it back to
    nobody: parsed-but-unlowered is still parsed.
    """
    mark = stream.mark()
    if not stream.accept_word("is", "are"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("no", "longer"):
        stream.reset(mark)
        return None
    word = stream.peek_word()
    if word is None or word not in TYPE_LINE_SUPERTYPES:
        stream.reset(mark)
        return None
    if not (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier in ("target", "that", "it", "this")
    ):
        stream.reset(mark)
        return None
    stream.advance()
    return ast.ChangeSupertype(subject, word, False, _parse_duration(stream))


def _parse_gain_type(
    stream: TokenStream, subject: ast.Recipient
) -> ast.GainType | None:
    """``… becomes an artifact in addition to its other types.`` (Ashnod's
    Transmogrant.) ``… becomes an artifact creature with power and toughness
    each equal to its mana value.`` (Xenic Poltergeist.)

    Read after the creature-body form, whose "becomes a 3/3 …" opens with a
    P/T and cannot be confused with this. Every tail is required: without "in
    addition to its other types" or the mana-value P/T clause the sentence says
    something this does not implement, and consuming the type word alone would
    claim it.
    """
    mark = stream.mark()
    if not (stream.accept_word("a") or stream.accept_word("an")):
        stream.reset(mark)
        return None
    types: list[str] = []
    while True:
        word = stream.peek_word()
        if word is None or word not in CARD_TYPES:
            break
        types.append(word)
        stream.advance()
    if not types:
        stream.reset(mark)
        return None
    if stream.accept_phrase("with", "power", "and", "toughness", "each", "equal", "to"):
        if not stream.accept_phrase("its", "mana", "value"):
            stream.reset(mark)
            return None
        duration = _parse_duration(stream)
        return ast.GainType(subject, tuple(types), duration, pt_from_mana_value=True)
    if stream.accept_phrase("in", "addition", "to", "its", "other", "types"):
        return ast.GainType(subject, tuple(types), _parse_duration(stream))
    stream.reset(mark)
    return None


def _parse_become_creature(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.BecomeCreature | None":
    """``a <P>/<T> <subtypes> creature [with <keywords>] in addition to its
    other types until end of turn`` (Riddleform).

    Every clause after the P/T is required, and each one is a way the sentence
    would otherwise be silently narrowed:

    * **"in addition to its other types"** is the difference between animating
      the permanent and *replacing* what it is — an enchantment that stopped
      being an enchantment is a different card;
    * **"until end of turn"** is the difference between this and a permanent
      animation, which is everything that happens after the turn ends.
    """
    mark = stream.mark()
    stream.accept_word("a", "an")
    try:
        power, power_negative, toughness, toughness_negative = expect_pt(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if power_negative or toughness_negative or not (
        isinstance(power, ast.Fixed) and isinstance(toughness, ast.Fixed)
    ):
        stream.reset(mark)
        return None
    subtypes: list[str] = []
    while True:
        matched = match_longest(stream.words_from(), 0, SUBTYPE_INDEX)
        if matched is None:
            break
        subtypes.append(matched[0])
        stream.advance(matched[1])
    # "…a 2/2 Assembly-Worker **artifact** creature" (Mishra's Factory). A card
    # type between the subtypes and the head noun, which the animation adds
    # alongside "creature" (CR 205.1b). Recorded rather than skipped: an
    # animated land that is not also an artifact is a different permanent, and
    # a word consumed and dropped is the rider bug this grammar refuses by
    # construction.
    card_types: list[str] = []
    while True:
        word = stream.peek_word()
        if word is None or word == "creature" or word not in CARD_TYPES:
            break
        card_types.append(word)
        stream.advance()
    # "…become 2/3 **creatures**" (Thelonite Druid). The plural head noun, for
    # a subject that names a set rather than one permanent. Read here rather
    # than as a second production: it is the same sentence with the noun
    # agreeing, and which subjects the animation can actually reach is the
    # lowering's question.
    if not stream.accept_word("creature", "creatures"):
        stream.reset(mark)
        return None
    keywords: list[str] = []
    if stream.accept_word("with"):
        while True:
            keyword = stream.peek_word()
            if keyword is None or keyword not in IMPLEMENTED_KEYWORDS:
                break
            keywords.append(keyword)
            stream.advance()
            if not (stream.accept_word("and") or stream.accept_punct(",")):
                break
        if not keywords:
            stream.reset(mark)
            return None
    # The addition clause, in any of the three places the pool prints it:
    # before the duration ("…in addition to its other types until end of turn",
    # Riddleform), as a relative clause on the noun itself ("…a 3/3 artifact
    # creature **that's still a land**", Mishra's Groundbreaker) or as its own
    # sentence after the duration ("…until end of turn. It's still a land.",
    # Mishra's Factory). One of the three is **required** — it is the difference
    # between animating the permanent and replacing what it is, and a production
    # that let it be absent would also let it be deleted.
    in_addition = stream.accept_phrase("in", "addition", "to", "its", "other", "types")
    if not in_addition:
        relative = stream.mark()
        if stream.accept_phrase("that", "'s", "still", "a"):
            kept = stream.peek_word()
            if kept is not None and _singular_type(kept) in CARD_TYPES:
                stream.advance()
                in_addition = True
            else:
                stream.reset(relative)
    # **Read, not required.** A sentence printing no duration is CR 611.2b's
    # default — the animation lasts indefinitely (Mishra's Groundbreaker) — and
    # the two lower to different instruction kinds, so the absence is carried
    # rather than defaulted. It is only optional once the addition clause has
    # already been consumed: the third spelling puts that clause *after* the
    # duration, so it has no sentence to find without one.
    until_eot = stream.accept_phrase("until", "end", "of", "turn")
    if not until_eot and not in_addition:
        stream.reset(mark)
        return None
    if not in_addition:
        stream.accept_punct(".")
        # "**They're still lands.**" (Thelonite Druid) is the plural of "It's
        # still a land." — the same sentence agreeing with a subject that names
        # a set, and the article goes with the number.
        if stream.accept_phrase("it", "'s", "still", "a"):
            plural_kept = False
        elif stream.accept_phrase("they're", "still"):
            plural_kept = True
        else:
            stream.reset(mark)
            return None
        # The type the sentence names is one the permanent already has, so
        # nothing reads it — the animation keeps every type either way. It is
        # still required to *be* a card type, because a sentence naming
        # something else is one this production has not understood.
        kept = stream.peek_word()
        if kept is None or _singular_type(kept) not in CARD_TYPES:
            stream.reset(mark)
            return None
        if plural_kept and kept == _singular_type(kept):
            # "They're still land" is not English and is not a sentence this
            # production has read; the plural subject takes the plural noun.
            stream.reset(mark)
            return None
        stream.advance()
    return ast.BecomeCreature(
        subject, power.value, toughness.value, tuple(subtypes), tuple(keywords),
        tuple(card_types), until_eot,
    )


