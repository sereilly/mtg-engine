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
from ..back_references import _parse_that_object
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
    # "…becomes **the color of your choice**" (Alchor's Tomb). CR 608.2d makes
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
    # "…becomes **a copy of that creature**, except it has this ability."
    # (Unstable Shapeshifter.) Read last, because every branch above starts on
    # a word this one does not: the article is shared with the animation and the
    # gained type, and those two decline before the noun.
    copied = _parse_become_copy(stream, subject)
    if copied is not None:
        return copied
    raise stream.error("expected a colour or a creature body after 'becomes'")


def _parse_becomes_aura_enchantment(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.BecomeAura | None":
    """``This creature loses this ability and becomes an Aura enchantment with
    enchant <noun>.`` (Tempest's five Licids.)

    Returns None with the cursor untouched for every other "loses …", so
    ``_parse_loses`` next door keeps life, keywords and the game.

    **One node for the whole sentence**, and the conjunction is why. CR 205.1a
    replaces the permanent's card types, so a Licid stops being a creature; CR
    613 layer 6 takes the ability away, so it cannot be activated again from
    the enchantment it has become. Those are two layers, but they are one
    printed thing the permanent *becomes* — split into two steps the second
    would apply to a permanent the first had already made into an Aura with no
    ability on it to lose, and a card that printed only one of them would be
    read as this one.

    The enchant clause is Necromancy's, read by
    ``quoted_lines._parse_becomes_aura_line`` from inside quotation marks and
    here from the bare words. Same node, same handler, same
    ``auras.BECAME_AURA_ENCHANT`` record — a Licid's "enchant creature" is not a
    printed ``Enchant`` line, so it cannot be read off the card's text and has
    to be a record either way.

    The subject must be the ability's own source. "This creature loses this
    ability" is CR 201.5's self-reference; a sentence saying it of anything else
    would be taking an ability away from a permanent whose text this node does
    not name, and the handler has only its own source to act on.
    """
    mark = stream.mark()
    stream.expect_word("loses", "lose")
    if not stream.accept_phrase("this", "ability"):
        stream.reset(mark)
        return None
    if not stream.accept_word("and"):
        stream.reset(mark)
        return None
    if not stream.accept_word("becomes", "become"):
        stream.reset(mark)
        return None
    if not stream.accept_word("an", "a"):
        stream.reset(mark)
        return None
    if not stream.accept_word("aura"):
        stream.reset(mark)
        return None
    # "…an Aura **enchantment**". The card type the sentence sets, read rather
    # than assumed: "Aura" alone is a subtype, and a permanent given the subtype
    # without the type is a creature the CR 704.5m sweep would start policing
    # while combat still counted it. A word this parser cannot place refuses,
    # for the reason every branch above it does.
    card_types: tuple[str, ...] = ()
    if stream.at_word(*CARD_TYPES):
        card_types = (str(stream.peek_word()),)
        stream.advance()
    if not stream.accept_phrase("with", "enchant"):
        stream.reset(mark)
        return None
    noun = stream.peek_word()
    if noun is None:
        stream.reset(mark)
        return None
    stream.advance()
    if not isinstance(subject, ast.TargetSpec) or not subject.filter.is_source:
        raise stream.error(
            "only a permanent's own ability can turn it into an Aura"
        )
    return ast.BecomeAura(
        noun=noun, card_types=card_types, loses_own_ability=True
    )

def _parse_become_copy(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.BecomeCopy | None":
    """``<subject> becomes a copy of <object>[, except it has this ability]``.

    Refuses without consuming, so the error the branches above raise is still
    what a sentence that is none of these gets.

    The exception clause is read **whole** or not at all: a comma after "a copy
    of that creature" that opens anything else leaves the tail unconsumed and
    the line refuses, which is the full-consumption invariant doing its job —
    "except it doesn't copy that creature's color" is a different modification
    and belongs to ``copies.copy_exceptions``, not here.
    """
    mark = stream.mark()
    if not stream.accept_phrase("a", "copy", "of"):
        stream.reset(mark)
        return None
    of = _parse_that_object(stream)
    if of is None:
        stream.reset(mark)
        return None
    keeps_own_ability = False
    if stream.accept_punct(","):
        if not stream.accept_phrase("except", "it", "has", "this", "ability"):
            stream.reset(mark)
            return None
        keeps_own_ability = True
    return ast.BecomeCopy(subject, of, keeps_own_ability=keeps_own_ability)


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
    # (Jinx.) CR 608.2d makes the choice part of resolving the spell, so the
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
    # "…**becomes an enchantment**." (Opal Acrolith, Hidden Stag's second line,
    # Soul Sculptor's target.) No tail at all, which CR 205.1a makes the
    # default rather than an omission: "the new card type(s) replaces any
    # existing card types". So the permanent stops being whatever it was —
    # which is the entire content of Opal Acrolith's ``{0}``, an enchantment
    # turning itself back from the creature its own trigger made it.
    #
    # Refused when the list names **creature**, and that is the boundary rather
    # than a convenience: a permanent that becomes a creature needs a size, and
    # the two sentences that give it one — a printed P/T and CR 604.3's
    # "power and toughness each equal to …" — are :func:`_parse_become_creature`
    # above and the mana-value branch two clauses up. A bare "becomes a
    # creature" would compile a 0/0 that CR 704.5f bins on the next check.
    if "creature" not in types:
        return ast.GainType(
            subject, tuple(types), _parse_duration(stream), replaces_types=True
        )
    stream.reset(mark)
    return None


def _pt_value(amount: ast.Amount) -> "int | str":
    """One half of a creature body's printed size, as the node carries it.

    A number stays a number and an X becomes the string the whole engine spells
    a variable amount with (``handlers/_common.resolve_amount``) — so a body
    that prints "X/X" reaches the handler in the shape every other amount does,
    rather than as a second vocabulary only the animation understands.
    """
    return amount.name if isinstance(amount, ast.Var) else amount.value


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
    # **Optional**, because one body in the pool prints no size at all: "…it
    # becomes an Illusion creature with power and toughness each equal to that
    # spell’s mana value." (Veiled Sentry.) A body with neither a printed P/T
    # nor that clause is refused below — a creature with no size is a 0/0 the
    # next state-based check bins (CR 704.5f).
    pt_mark = stream.mark()
    power = toughness = None
    try:
        power, power_negative, toughness, toughness_negative = expect_pt(stream)
    except GrammarError:
        stream.reset(pt_mark)
        power = toughness = None
    else:
        # "…becomes an **X/X** Construct artifact creature" (Chimeric Staff).
        # The lexer already reads "X/X" as one P/T token and ``parse_pt_pair``
        # already produces ``Var``s from it; what refused was this gate. A
        # *negative* one still refuses — a creature body states a size and
        # never a delta, so a sign here would be a sentence this production has
        # not understood.
        if power_negative or toughness_negative or not (
            isinstance(power, (ast.Fixed, ast.Var))
            and isinstance(toughness, (ast.Fixed, ast.Var))
        ):
            stream.reset(mark)
            return None
    # "…becomes a 2/2 **green** creature that's still a land." (Quirion Druid.)
    # CR 613 layer 5, printed inside the creature body between the P/T and the
    # subtypes, which is where the templating puts it. Read here rather than
    # dropped: a colourless land animated green is a permanent Circle of
    # Protection: Green does not stop, and a word this production consumed and
    # threw away is the dropped-rider bug the grammar refuses by construction.
    colors: list[str] = []
    while True:
        colour = stream.peek_word()
        if colour is None or colour not in COLOR_WORDS:
            break
        stream.advance()
        colors.append(COLOR_WORDS[colour])
        # "…a 2/2 black and green creature" — CR 105.2's multicoloured object,
        # one object with two colours rather than two effects. Accepted because
        # the conjunction is how the templating joins them; a run of one is the
        # only spelling the pool prints today.
        if not stream.accept_word("and"):
            break
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
    # "…with **power and toughness each equal to that spell’s mana value**"
    # (Veiled Sentry) and "…with **protection from each of that spell’s
    # colors**" (Opal Titan). Two halves of one body read off the *event* the
    # trigger fired on rather than off the printed line, which is why they are
    # flags: the words carry no value at all, and the handler asks the trigger
    # context for the spell.
    pt_from_spell = False
    protection_from_spell = False
    if stream.accept_word("with"):
        # Both before the keyword loop. "power" is not a keyword and would end
        # the loop with nothing consumed; "protection" **is** one, so the loop
        # would take that word and strand "from each of that spell’s colors" —
        # which is the reading Opal Titan actually got.
        if stream.accept_phrase("power", "and", "toughness", "each", "equal", "to"):
            # Only the *triggering spell*’s mana value. "…each equal to **its**
            # mana value" is the same words about the permanent itself and is
            # ``_parse_gain_type``’s sentence (Xenic Poltergeist, Karn) — read
            # here it would take those two cards over and animate the wrong
            # object’s size. A body that printed a P/T as well states the size
            # twice and is a sentence nobody prints. Anything else refuses.
            if power is not None or not stream.accept_phrase(
                "that", "spell", "'s", "mana", "value"
            ):
                stream.reset(mark)
                return None
            pt_from_spell = True
        elif stream.accept_phrase("protection", "from", "each", "of"):
            # "…**protection from each of that spell’s colors**" (Opal Titan).
            # CR 702.16g’s shorthand for one protection ability per colour, and
            # which colours is not on the card — it is a characteristic of the
            # spell the trigger fired on (CR 105.2), so nothing here can carry
            # it and the handler reads the event.
            if not stream.accept_phrase("that", "spell", "'s", "colors"):
                stream.reset(mark)
                return None
            protection_from_spell = True
        else:
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
    if power is None and not pt_from_spell:
        # A creature body with no size at all — "becomes a Beast creature" —
        # is a 0/0 the next state-based check bins (CR 704.5f). Refusing keeps
        # it a sentence nobody has read rather than a card that animates and
        # dies.
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
    # …and the fourth spelling, which is **no clause at all**: "Until end of
    # turn, this artifact becomes a 2/1 Construct **artifact** creature with
    # flying." (Chimeric Sphere, Xanthic Statue, Jade Statue.)
    #
    # CR 205.1b names this case out loud, which is why it is an *addition* here
    # rather than the replacement the rule's first sentence describes: "Some
    # effects state that an object becomes an 'artifact creature'; these effects
    # also allow the object to retain all of its prior card types and subtypes."
    # So the missing clause is not an omission the card gets away with — the
    # rule supplies it.
    #
    # Two conditions, and both are that sentence rather than convenience:
    #
    # * the body must name every card type the printed subject names, which is
    #   what makes it the "becomes an artifact creature" case rather than the
    #   general type change above it. That is also why Mishra's Factory prints
    #   "It's still a land" and these three do not — a land becoming an artifact
    #   creature is outside the rule's exception and loses the word;
    # * the subject must not already be a creature, because the rule's next
    #   sentence is narrower: "…becomes a '[creature type] artifact creature';
    #   these effects also allow the object to retain all of its prior card
    #   types and subtypes **other than creature types**, but replace any
    #   existing creature types." The record this lowers to *adds* subtypes, so
    #   a creature animated into a Construct would keep the types the rule
    #   replaces. Nothing in the pool prints it; refusing keeps it that way
    #   rather than admitting it silently.
    #
    # "Target land becomes a 4/4 creature until end of turn" fails the first and
    # keeps refusing, which is the point: admitting it under an adding record is
    # the silent half of a type replacement this engine has not built.
    if not in_addition and isinstance(subject, ast.TargetSpec):
        printed = set(subject.filter.card_types)
        if (
            printed
            and "creature" not in printed
            and printed <= set(card_types) | {"creature"}
        ):
            in_addition = True
    # **Read, not required.** A sentence printing no duration is CR 611.2b's
    # default — the animation lasts indefinitely (Mishra's Groundbreaker) — and
    # the two lower to different instruction kinds, so the absence is carried
    # rather than defaulted. It is only optional once the addition clause has
    # already been consumed: the third spelling puts that clause *after* the
    # duration, so it has no sentence to find without one.
    until_eot = stream.accept_phrase("until", "end", "of", "turn")
    if not in_addition:
        tail = stream.mark()
        stream.accept_punct(".")
        # "**They're still lands.**" (Thelonite Druid) is the plural of "It's
        # still a land." — the same sentence agreeing with a subject that names
        # a set, and the article goes with the number.
        if stream.accept_phrase("it", "'s", "still", "a"):
            plural_kept = False
        elif stream.accept_phrase("they're", "still"):
            plural_kept = True
        else:
            plural_kept = None
            stream.reset(tail)
        if plural_kept is not None:
            # The type the sentence names is one the permanent already has, so
            # nothing reads it — the animation keeps every type either way. It
            # is still required to *be* a card type, because a sentence naming
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
            in_addition = True
    # …and the fifth spelling, which says none of the three and means the
    # opposite: "it becomes a 2/2 Gargoyle creature with flying." (Opal
    # Gargoyle, and the fifteen other Hidden / Opal / Veiled enchantments.)
    #
    # CR 205.1a is the default this production used to refuse — "in most such
    # cases, the new card type(s) **replaces** any existing card types" — and
    # the cycle turns on it: the enchantment stops being an enchantment, which
    # is what makes its own intervening-if ("if this permanent is an
    # enchantment") false the second time an opponent casts a creature spell.
    # An animation that added the type instead would re-fire for ever, and for
    # the two cards whose trigger is a *state* trigger (CR 603.8) that is not a
    # cosmetic difference but an unbounded loop.
    #
    # ``in_addition`` stays the four printed spellings above; this is their
    # absence, carried on the node as its own field rather than as
    # ``not in_addition`` so the two claims are separable at every reader.
    return ast.BecomeCreature(
        subject,
        0 if power is None else _pt_value(power),
        0 if toughness is None else _pt_value(toughness),
        tuple(subtypes), tuple(keywords),
        tuple(card_types), tuple(colors), until_eot,
        replaces_types=not in_addition,
        pt_from_triggering_spell=pt_from_spell,
        protection_from_triggering_spell=protection_from_spell,
    )


def parse_land_type_swap(stream: TokenStream) -> "ast.LandTypeSwap | None":
    """``Choose a land type and a basic land type. Each land of the first
    chosen type becomes the second chosen type until end of turn.``
    (Vision Charm's third mode.)

    Both sentences, because neither is one on its own — see the node. Read in
    ``parse_imperative`` ahead of every other production that opens on "choose",
    and refusing without consuming so each of them keeps the sentence it owns.

    The ordinals are structure rather than payload: "the first chosen type" and
    "the second chosen type" are the *only* way this sentence can name what the
    sentence before it produced, so a production that let them vary would be
    reading a sentence nobody prints.
    """
    mark = stream.mark()
    if not stream.accept_word("choose"):
        return None

    def _a_land_type() -> bool | None:
        """Consume "a [basic] land type", answering whether it said "basic"."""
        if not stream.accept_word("a", "an"):
            return None
        basic = stream.accept_word("basic")
        if not stream.accept_phrase("land", "type"):
            return None
        return bool(basic)

    first = _a_land_type()
    if first is None or not stream.accept_word("and"):
        stream.reset(mark)
        return None
    second = _a_land_type()
    if second is None:
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "each", "land", "of", "the", "first", "chosen", "type",
        "becomes", "the", "second", "chosen", "type",
    ):
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    if duration.kind != "until_end_of_turn":
        # Read rather than defaulted, and refused rather than widened: with no
        # words the change would last as long as the game does (CR 611.2), which
        # is a different card and one no sweep would ever end.
        stream.reset(mark)
        return None
    return ast.LandTypeSwap(first, second, duration)
