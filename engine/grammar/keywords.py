"""Reading a keyword-ability list off a printed line.

Split out of ``phrases`` at the thousand-line guard, reusing the name
``lowering/keywords.py`` has carried since it left the same family one package
over — the mirror re-forming rather than forking, which is what these names are
for. The boundary is the one that side already drew: everything here answers
"which keyword abilities does this phrase name?", where the rest of ``phrases``
answers "what does this noun phrase, duration, cost or zone mean?". (The cost
and the duration have since left it the same way, for ``prices`` and
``durations``.)

Which keywords the engine implements is **not** decided here. That is
``vocabulary.IMPLEMENTED_KEYWORDS``, one frozenset, read by this module and by
``engine/oracle.py``'s keyword-line classifier alike — a second list would be a
second answer, and CLAUDE.md's lifelink precedent is what it costs.
"""



from .lexer import NUMBER, QUOTE, WORD
from .stream import TokenStream
from .vocabulary import (KEYWORD_FAMILIES, KEYWORD_INDEX, NUMERIC_ARGUMENT_KEYWORDS,
                         match_longest)


#: "Protection from the color of your choice" — the keyword whose argument is
#: not known until the effect resolves (CR 608.2d). Named once here because the
#: parser writes it, the grant gate reads it and the handler resolves it, and a
#: third spelling of the same string is how those three come apart.
PROTECTION_FROM_CHOSEN_COLOR = "protection from the color of your choice"

#: "…protection from the color of **its controller's** choice" (Wishmonger).
#: Its own keyword string beside the one above, and the difference is *who is
#: asked*: "your choice" is the controller of the spell or ability doing the
#: granting (CR 109.5 — for an activated ability, the player who activated it),
#: and this one is the controller of the creature being granted to. On this card
#: that is a third player: "Any player may activate this ability" is CR 602.2's
#: "unless the object specifically says otherwise", so the activator need not
#: control the permanent the ability is on either.
#:
#: A second string rather than a flag beside the first, for the reason the first
#: is a string rather than a flag on the node: the grant handler has to know
#: **which channel to read the answer off**, and one name with a rider beside it
#: has a state where the two disagree and nothing to say which the handler
#: should believe.
PROTECTION_FROM_TARGETS_CONTROLLERS_CHOSEN_COLOR = (
    "protection from the color of its controller's choice"
)

#: "…protection from **the chosen color**" (Prismatic Boon, Reverent Mantra).
#: The third string, and the difference from the first is *which sentence
#: asks*. "The color of your choice" is its own question (CR 608.2d), so its
#: grant lowers with a choosing step in front of it; "the chosen color" asks
#: nothing — it reads back the answer a "Choose a color." sentence earlier in
#: the same effect recorded, and refuses where nothing did. One string for both
#: was right while the colour rode the announcement and both read it there; it
#: stopped being right when the choice moved to the resolution, because the
#: lowering has to know whether to put the question in.
PROTECTION_FROM_THE_CHOSEN_COLOR = "protection from the chosen color"

#: All three, for the reader that answers them alike: every one is granted from
#: the colour this resolution's choosing step recorded
#: (``oracle_types.CHOSEN_COLOR_THIS_WAY``), and they differ only in who asked.
CHOSEN_COLOR_PROTECTIONS = frozenset({
    PROTECTION_FROM_CHOSEN_COLOR,
    PROTECTION_FROM_TARGETS_CONTROLLERS_CHOSEN_COLOR,
    PROTECTION_FROM_THE_CHOSEN_COLOR,
})


def _accept_bands_with_other(stream: TokenStream) -> str | None:
    """One "bands with other [quality]" item of a keyword list, or None.

    Its own reader rather than a ``KEYWORD_INDEX`` entry because the ability's
    name is not a word: CR 702.22b's keyword carries a printed **noun phrase**
    ("legendary creatures", "creatures named Wolves of the Hunt"), and the
    vocabulary index matches fixed word sequences. Magic prints it in quotes for
    exactly that reason — the quotes are where the quality ends.

    Two printed shapes, and they mean different things:

    * ``"bands with other <quality>"`` — one ability, granted or held.
    * ``all "bands with other" abilities`` — the **family**, which is what a
      removal names (Shelkin Brownie, Tolaria). It is not an ability anything
      has; :func:`engine.banding.expand_ability_removal` is what turns it into
      the ones a permanent actually has, and lowering is what refuses it as a
      *grant*.

    A quality the engine cannot test raises rather than returning None: the
    phrase *is* a bands-with-other ability, so falling back to another
    production would read the card as something else. Loud, with the clause
    named, is the answer this parser gives everywhere else.
    """
    from ..banding import BANDS_WITH_OTHER, is_implemented

    mark = stream.mark()
    stream.accept_word("all")
    if stream.accept_kind(QUOTE) is None:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("bands", "with", "other"):
        stream.reset(mark)
        return None
    words: list[str] = []
    while not stream.exhausted and not stream.at_kind(QUOTE):
        token = stream.next()
        # The sentence-ending period Magic prints *inside* the quotes is
        # punctuation of the quoted ability, not part of the quality.
        if token.kind == WORD:
            words.append(token.text)
    if stream.accept_kind(QUOTE) is None:
        raise stream.error("unterminated quoted banding ability")
    # "all \"bands with other\" **abilities**" — the plural head noun belongs to
    # the family form and is consumed here, or the caller would be left a word
    # no production reads and would refuse the whole line.
    stream.accept_word("abilities", "ability")
    if not words:
        return BANDS_WITH_OTHER
    name = f"{BANDS_WITH_OTHER} " + " ".join(words)
    if not is_implemented(name):
        raise stream.error(f"unimplemented banding quality {' '.join(words)!r}")
    return name


def _at_keyword_item(stream: TokenStream) -> bool:
    """Whether another keyword-list item starts here, without consuming it.

    The lookahead the list's joining words need: a conjunction belongs to the
    keyword list only when a keyword follows it, and the two spellings of an
    item — an indexed word and CR 702.22b's printed noun phrase — have to be
    asked about together, or "and bands with other legendary creatures" would
    read as the end of the list.
    """
    mark = stream.mark()
    try:
        if _accept_bands_with_other(stream) is not None:
            return True
    finally:
        stream.reset(mark)
    return match_longest(stream.words_from(), 0, KEYWORD_INDEX) is not None


def _protection_quality_name(stream: TokenStream) -> str | None:
    """The protection keyword a quality after "from" names, or None, unmoved.

    A colour word, a card-type word, or one of the two printed *choices* — read
    before the bare word, which would otherwise consume "the" and grant
    protection from a colour called "the".
    """
    if stream.accept_phrase(
        "the", "color", "of", "its", "controller", "'s", "choice"
    ):
        return PROTECTION_FROM_TARGETS_CONTROLLERS_CHOSEN_COLOR
    if stream.accept_phrase("the", "color", "of", "your", "choice"):
        return PROTECTION_FROM_CHOSEN_COLOR
    if stream.accept_phrase("the", "chosen", "color"):
        return PROTECTION_FROM_THE_CHOSEN_COLOR
    colour = stream.peek_word()
    if colour is None:
        return None
    stream.advance()
    return f"protection from {colour}"


def _parse_keywords(stream: TokenStream) -> tuple[str, ...]:
    """The keyword list alone, for the readers that do not care how it was
    joined — a condition asking whether a creature *has* one, a delayed grant's
    fixed option list. A **grant** does care and calls
    :func:`parse_keyword_list`."""
    return parse_keyword_list(stream)[0]


def parse_keyword_list(stream: TokenStream) -> tuple[tuple[str, ...], bool]:
    """The keyword list, and whether the card joined it with "**or**".

    "gains flying and first strike" grants both; "gains banding, first strike,
    **or** trample" (Nature's Blessing) grants one of the three, chosen as the
    effect resolves (CR 608.2d). One word apart and two different cards, so the
    joining word is *read* rather than normalised away — which it was, and the
    "or" spelling silently granted every keyword in the list. Nothing in the
    pool printed one, so nothing was broken; it was the shape one word away from
    being broken, and Nature's Blessing is the card that prints it.

    Only the boolean travels, not the joins themselves: a mixed list ("A, B, or
    C") punctuates its inner joins with commas alone, so "was any join an
    'or'?" is the whole of what the connectives say. A list that genuinely mixed
    the two words is not English anybody prints.
    """
    # "all **landwalk** abilities" (Hammerheim) — a card naming a keyword
    # *family* rather than listing its members. CR 702.14a makes landwalk a
    # family of "[type]walk" abilities, so the phrase means every member and the
    # member list is what everything above this production wants: the loss then
    # lowers, targets and dispatches as the ordinary keyword list it is, with no
    # second notion of "a family" for the layer-6 channel to learn.
    #
    # Read first and whole, because "all" is not a keyword and the loop below
    # would stop on it — which is how Hammerheim's second ability refused with
    # "expected a keyword ability" for a family the engine implements six
    # members of.
    family_mark = stream.mark()
    if stream.accept_word("all"):
        family = stream.peek_word()
        if family in KEYWORD_FAMILIES and stream.peek_word(1) in ("ability", "abilities"):
            stream.advance(2)
            return KEYWORD_FAMILIES[str(family)], False
    stream.reset(family_mark)

    keywords: list[str] = []
    disjunctive = False
    while True:
        banded = _accept_bands_with_other(stream)
        if banded is not None:
            name = banded
            keywords.append(name)
            if stream.accept_word("and"):
                continue
            if stream.accept_word("or"):
                disjunctive = True
                continue
            break
        matched = match_longest(stream.words_from(), 0, KEYWORD_INDEX)
        if matched is None:
            break
        name, consumed = matched
        stream.advance(consumed)
        # "protection from red" — the argument belongs to the keyword.
        if name == "protection" and stream.accept_word("from"):
            # "…from **the color of your choice**" (Feat of Resistance). CR
            # 608.2d: the colour is chosen as the effect resolves, so the
            # keyword cannot name it — it names the *choice*, and the lowering
            # puts the step that asks it in front of the grant.
            # Read before the bare colour word, which would otherwise consume
            # "the" and grant protection from a colour called "the".
            # "…from **the chosen color**" (Prismatic Boon), the same question
            # asked by the sentence in front of it rather than by this clause:
            # "Choose a color. X target creatures gain protection from the
            # chosen color until end of turn." CR 608.2d puts both choices in
            # the same resolution, so they name one colour and read one channel
            # — but the *lowering* has to know which sentence asked, because
            # only "of your choice" puts a choosing step in front of its grant.
            # So it is its own string (``PROTECTION_FROM_THE_CHOSEN_COLOR``)
            # read off the same record by the same handler.
            # "…from **the color of its controller's choice**" (Wishmonger).
            # The same CR 608.2d choice asked of a different seat — the
            # controller of the creature the grant lands on, not the controller
            # of the ability granting it. Read before the two below because all
            # three open on "the color of", and the lexer splits the possessive
            # into two words ("controller" + "'s"), so the phrase is seven
            # tokens rather than six.
            name = _protection_quality_name(stream) or name
            # "…protection from black **and from** red" (Questing Phelddagrif).
            # CR 702.16g: "protection from [A] and from [B]" is shorthand for
            # two protection abilities, so the list holds two items and the
            # keyword word is simply left unprinted on the second — the "or
            # from" spelling below with the other connective, and granting
            # both rather than one. The keyword *line* and the Aura grant
            # already read it (`oracle._protection_qualities`, `auras.py`);
            # this is the list every one-shot grant reads, which did not, so
            # the tail was unconsumed text and the whole ability refused.
            while True:
                both = stream.mark()
                if not stream.accept_phrase("and", "from"):
                    break
                another = _protection_quality_name(stream)
                if another is None:
                    stream.reset(both)
                    break
                keywords.append(name)
                name = another
            # "…protection from artifacts **or from** the color of your choice"
            # (Jeweled Spirit). The list's own "or" with the keyword word left
            # unprinted: two protection abilities, one of which is chosen as the
            # effect resolves (CR 608.2d) — Nature's Blessing's disjunction, so
            # it travels as that list and that flag.
            either = stream.mark()
            if stream.accept_phrase("or", "from"):
                other = _protection_quality_name(stream)
                if other is not None:
                    keywords.append(name)
                    name = other
                    disjunctive = True
                else:
                    stream.reset(either)
        # "rampage 2" — CR 702.23a's "Rampage N". The number is the whole of
        # this keyword's argument, exactly as a colour word is protection's, so
        # it is read here and carried on the keyword string; which keywords take
        # one is `NUMERIC_ARGUMENT_KEYWORDS`, and the value is payload.
        #
        # Optional here, because the two readers of a keyword word want
        # different things: a *test* asks whether the creature has rampage at
        # all ("if it doesn't have rampage") and the number would be no part of
        # the question, while a *grant* has to name the N it grants. So the
        # parser reads what is printed and `_lower_gain_keyword` is what refuses
        # a grant with no number — the refusal belongs where the number is
        # needed, not where the word is read.
        if name in NUMERIC_ARGUMENT_KEYWORDS:
            amount = stream.accept_kind(NUMBER)
            if amount is not None:
                name = f"{name} {amount.text}"
        keywords.append(name)
        # "deathtouch or lifelink" (two items) and "banding, flying, first
        # strike, or trample" (four) — English punctuates a list of four
        # differently from a list of two and the card means the same thing
        # either way, which is the same reason the subtype parser reads both.
        # A conjunction is consumed only when a keyword follows it, so a line
        # that ends its keyword list and goes on keeps the joining word for
        # whatever reads the rest.
        #
        # That rule used to hold for the comma alone: "and" and "or" were taken
        # unconditionally, which swallowed the word joining the keyword list to
        # the *next clause* of the same sentence. "Target creature gains trample
        # **and** gets +2/+0 until end of turn" is the shape, and the branch in
        # `_parse_gains` written for it had been unreachable ever since — it
        # asks for an "and" that was already gone, rewinds, and the line fails
        # on unconsumed text. A quoted grant behind the same conjunction
        # ("gains haste **and** "{0}: Untap this creature."", Touch of Vitae)
        # was refused the same way.
        joined = stream.mark()
        if stream.accept_word("and"):
            if _at_keyword_item(stream):
                continue
            stream.reset(joined)
        elif stream.accept_word("or"):
            if _at_keyword_item(stream):
                disjunctive = True
                continue
            stream.reset(joined)
        comma = stream.mark()
        if stream.accept_punct(","):
            # The last item of a list carries the joining word after the comma:
            # "banding, first strike, **or** trample" and its "and" twin. Both
            # are read, because which one it is decides whether the card grants
            # one keyword or all of them — and reading only "or" left an "and"
            # list ending one item short, with the tail unconsumed and the whole
            # line refused.
            if stream.accept_word("or"):
                disjunctive = True
            else:
                stream.accept_word("and")
            if match_longest(stream.words_from(), 0, KEYWORD_INDEX) is not None:
                continue
            stream.reset(comma)
        break
    if not keywords:
        raise stream.error("expected a keyword ability")
    return tuple(keywords), disjunctive
