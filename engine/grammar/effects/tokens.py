"""Parsing token creation (CR 111).

Split out of ``effects/game.py`` when that module crossed 1,000 lines, and the
boundary is the one ``lowering/tokens.py`` already draws one package over: a
token is an **object the game creates** (CR 111.1), where everything left in
``game`` changes the state a *player* is in — life, extra turns, winning,
losing, ante, the coin flips and choices a sentence makes. Reusing that name is
what re-forms the mirror instead of forking a fourth vocabulary for the same
family.

It is a leaf of the ``effects`` family like every other module here: it reads
``nouns``, ``references``, ``amounts`` and ``phrases`` — floors, not families —
and no sibling reads it back. ``statements`` reaches ``_parse_create_token``
through the package's flat re-export, exactly as it did when this code was in
``game``.
"""

from __future__ import annotations

import dataclasses

from ...tokens import PREDEFINED_TOKENS
from ...oracle_types import LAST_TARGET_CONTROLLER
from .. import ast
from ..amounts import expect_pt, parse_amount, parse_equal_to
from ..errors import GrammarError
from ..lexer import PT, PUNCT, QUOTE, SELF, WORD
from ..phrases import _parse_for_each, _parse_per_each_objects
from ..references import parse_target_spec
from ..stream import TokenStream
from ..vocabulary import (CARD_TYPES, COLOR_WORDS, KEYWORD_INDEX, SUBTYPE_INDEX,
                          TYPE_LINE_SUPERTYPES, match_longest)


def _parse_token_quoted_lines(stream: TokenStream) -> tuple[str, ...]:
    """The ``with "<line>"[ and "<line>"]`` tail — printed abilities in quotes.

    Sliced back out of the source through the tokens' own offsets, so the token
    is built from the words the card prints and the compiler reads them exactly
    as it reads any other card's. A line the compiler cannot read is refused
    here (see the lowering), because a token carrying an ability nothing
    implements is a token that silently lacks it.
    """
    lines: list[str] = []
    while True:
        if stream.accept_kind(QUOTE) is None:
            raise stream.error("expected a quoted ability on the token")
        opened = stream.pos
        while not stream.exhausted and not stream.at_kind(QUOTE):
            stream.advance()
        text = stream.text_between(opened, stream.pos)
        if stream.accept_kind(QUOTE) is None:
            raise stream.error("unterminated quoted ability on the token")
        lines.append(text)
        if stream.accept_word("and"):
            continue
        break
    return tuple(lines)


def _parse_token_quoted_lines_one(stream: TokenStream) -> tuple[str, ...]:
    """One quoted ability, without consuming a following "and".

    The list form above owns its own separator; a caller reading a mixed run of
    keywords and quotes has to own it instead, or the two would each consume the
    word and the second item would be lost.
    """
    if stream.accept_kind(QUOTE) is None:
        raise stream.error("expected a quoted ability on the token")
    opened = stream.pos
    while not stream.exhausted and not stream.at_kind(QUOTE):
        stream.advance()
    text = stream.text_between(opened, stream.pos)
    if stream.accept_kind(QUOTE) is None:
        raise stream.error("unterminated quoted ability on the token")
    return (text,)


def _parse_token_keywords(stream: TokenStream) -> tuple[str, ...]:
    """The ``with <keyword>[, <keyword>][ and <keyword>]`` tail of a token spec."""
    keywords: list[str] = []
    while True:
        matched = match_longest(stream.words_from(), 0, KEYWORD_INDEX)
        if matched is None:
            raise stream.error("expected a keyword ability on the token")
        name, consumed = matched
        keywords.append(name)
        stream.advance(consumed)
        # A separator is only a separator when a keyword follows it. "…creature
        # token **with flying, where X is** the number of +1/+1 counters on this
        # creature" (Phantasmal Sphere) ends the list at the comma and carries
        # on with the sentence; consumed unconditionally, the comma made the
        # loop demand a keyword where "where" stands and refused the whole line.
        separator = stream.mark()
        if stream.accept_punct(","):
            stream.accept_word("and")
        elif not stream.accept_word("and"):
            break
        if match_longest(stream.words_from(), 0, KEYWORD_INDEX) is None:
            stream.reset(separator)
            break
    return tuple(keywords)


def _parse_token_colors(stream: TokenStream, colors: list[str]) -> bool:
    """The run of colour words in a token spec, appended to *colors*.

    Returns whether the spec *stated* a colour at all — "colorless" states one
    without adding to the list, and an empty list already means colourless, so
    the two answers cannot be the same value.

    Its own function because the pool prints the run in two places: in front of
    the subtypes ("a 1/1 **white** Soldier creature token") and after the head
    noun ("1/1 Sand Warrior creature tokens **that are red, green, and
    white**"). One reader, called twice.
    """
    stated = False
    while True:
        word = stream.peek_word()
        if word in COLOR_WORDS:
            colors.append(COLOR_WORDS[word])
            stated = True
            stream.advance()
            stream.accept_punct(",")
            stream.accept_word("and")
            continue
        if word == "colorless":
            stated = True
            stream.advance()
            continue
        break
    return stated


def _parse_token_supertypes(stream: TokenStream, supertypes: list[str]) -> bool:
    """The run of supertype words in a token spec, appended to *supertypes*.

    CR 205.4a — a supertype is part of the type line, printed in front of the
    card types, and the legend rule (CR 704.5j) reads it. Dropping the word
    would let two Stangg Twins sit on one battlefield, so it is recorded rather
    than skipped.

    ``TYPE_LINE_SUPERTYPES`` rather than the whole catalog: "token" is itself a
    supertype in Scryfall's data, and the head noun of this very spec.

    Returns whether anything was consumed.
    """
    consumed = False
    while True:
        word = stream.peek_word()
        if word is None or word not in TYPE_LINE_SUPERTYPES:
            break
        supertypes.append(word)
        stream.advance()
        consumed = True
    return consumed


def _parse_token_name_words(stream: TokenStream) -> str | None:
    """A run of words that spells a token's **name**, or None.

    Two printed word orders put a name here, and both reach this one reader:
    the trailing ``…token named Wasp`` and the leading ``Create Stangg Twin, a
    … token`` (Stangg). One reader because the words are the same words — a
    second would be a second answer to what a token may be called.

    The ``SELF`` token is read as part of the name, and this is the whole
    reason the run is read token by token rather than by ``at_kind(WORD)``.
    A token's name may *contain* the creating card's own name, and the lexer
    has already collapsed that name into one ``SELF`` token (it cannot know the
    two words are a name rather than a self-reference) — so "Stangg Twin" would
    otherwise read as the card talking about itself with a stray word after it.
    The printed spelling is recoverable because the token carries its own text,
    which is the same recovery ``_parse_quoted_abilities`` makes.
    """
    parts: list[str] = []
    while True:
        token = stream.peek()
        if token is None or token.kind not in (WORD, SELF):
            break
        # "…token **named Tombspawn** for each creature card in their
        # graveyard" (Tombstone Stairwell). The run is otherwise unbounded, so
        # it swallowed the multiplier and named the token after it — one Zombie
        # per player, called "Tombspawn For Each Creature Card In Their
        # Graveyard", where the card makes a Zombie per creature card. No token
        # Magic prints is named "… for each …", so stopping here costs nothing
        # and the clause reaches the reader that answers it.
        if token.text == "for" and stream.peek_word(1) == "each":
            break
        parts.append(token.text)
        stream.advance()
    return " ".join(parts) if parts else None


#: A token maker's printed **recipient**, by the words in front of the verb.
#: "Each opponent creates a … token" (Pursued Whale), "Target opponent creates a
#: 1/1 green Hippo creature token" (Phelddagrif). Payload rather than a second
#: production, because everything else about the sentence is identical — and a
#: table rather than two branches, because the next such prefix is a row.
_TOKEN_RECIPIENT_PREFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("each", "player"), "each_player"),
    (("each", "opponent"), "each_opponent"),
    (("target", "opponent"), "target_opponent"),
)


def _parse_create_token_for_recipient(
    stream: TokenStream,
) -> "ast.CreateToken | None":
    """``<recipient> creates <token>`` — the token maker with somebody else's
    name in front of it.

    Beside the token production rather than in ``subject_verb``, where the
    "each opponent" spelling used to sit alone: this is one reading of one
    clause of the token grammar, and a second prefix written at the dispatch
    site would have been the same words read in two places.

    Non-consuming on refusal, so every other sentence opening with "each" or
    "target" keeps the reading and the refusal it has today.
    """
    mark = stream.mark()
    for words, who in _TOKEN_RECIPIENT_PREFIXES:
        if stream.accept_phrase(*words) and stream.at_word("creates"):
            token = _parse_create_token(stream)
            assert isinstance(token, ast.CreateToken)
            return dataclasses.replace(token, recipient_players=who)
        stream.reset(mark)
    # "**They** create a 0/2 colorless Wall artifact creature token with
    # defender." (Basalt Golem, inside the branch of "if the player does".)
    # Anaphoric rather than descriptive: the seat is the one the sentence in
    # front named, and nothing on a board says who that is — so the token rides
    # the controller an earlier step recorded, exactly as "**its controller**
    # creates …" does (``riders.py``). That is why it sets ``recipient`` and
    # not ``recipient_players``: those name a *set* the phrase describes, and
    # this names one seat somebody else wrote down.
    #
    # The lowering demands the producer, so with no earlier step recording a
    # seat the words name nobody and the line refuses rather than handing the
    # token to whoever the resolution happened to be carrying.
    if stream.accept_word("they") and stream.at_word("create", "creates"):
        token = _parse_create_token(stream)
        assert isinstance(token, ast.CreateToken)
        return dataclasses.replace(token, recipient=LAST_TARGET_CONTROLLER)
    stream.reset(mark)
    return None


def _parse_create_token(
    stream: TokenStream, *, pt_optional: bool = False
) -> ast.Statement:
    """``Create <N> <P/T> <colours> <subtypes> <types> token(s) [with …] [named …]``.

    One production for the whole family, because ``create_token`` is already
    the engine's one generic token maker (engine/tokens.py): everything that
    varies between token cards — count, P/T, colour, types, keywords, name —
    is payload, so there is nothing per-card left for a rule to encode.

    The printed word order *is* the type line's order (CR 205.1a), so the types
    are recorded as written rather than re-sorted. Every word between the
    quantity and the head noun must land in one of the recorded fields; a
    supertype ("a legendary … token") has nowhere to go on
    :class:`ast.CreateToken`, so it raises instead of being dropped.
    """
    # "creates" is the rider spelling ("Its controller creates …"), consumed
    # by the same production so the token grammar exists exactly once.
    stream.expect_word("create", "creates")

    # "Create **Stangg Twin,** a legendary 3/4 red and green Human Warrior
    # creature token." (Stangg.) The name printed in front of the spec instead
    # of behind it in a `named` tail — the same information in the other word
    # order, so it lands in the same field and the rest of the production is
    # unchanged. Recognised by the comma with a quantity behind it: every other
    # token sentence in the pool puts a quantity right after "create", and a
    # quantity is never a bare run of words followed by a comma.
    leading_name = ""
    mark_leading = stream.mark()
    scanned = _parse_token_name_words(stream)
    if (
        scanned is not None
        and stream.accept_punct(",")
        and stream.at_word("a", "an")
    ):
        leading_name = scanned
    else:
        stream.reset(mark_leading)

    count = parse_amount(stream)

    # "Create a **Treasure** token." (Gadrak.) A token Magic prints by name
    # alone: its characteristics belong to the token and live in
    # `engine/tokens.py`, so the card states nothing but which one. Read before
    # the P/T, which such a token has none of.
    # "Create a token **that's a copy of** target creature you control."
    # (Sublime Epiphany.) Read before the P/T, which a copy has none of: its
    # characteristics come from the permanent it copies (CR 707.2), not from
    # this sentence.
    mark_copy = stream.mark()
    if stream.accept_word("token", "tokens") and stream.accept_phrase(
        "that", "'s", "a", "copy", "of"
    ):
        subject = parse_target_spec(stream)
        if subject is None:
            raise stream.error("expected what the token copies")
        return ast.CreateCopyToken(count, subject)
    stream.reset(mark_copy)

    named = stream.peek_word()
    predefined = PREDEFINED_TOKENS.get(named or "")
    if predefined is not None:
        stream.advance()
        stream.expect_word("token", "tokens")
        return ast.CreateToken(
            count, None, None, predefined["name"],
            colors=tuple(predefined["colors"]),
            types=tuple(predefined["type_line"].split("—")[0].strip().lower().split()),
            subtypes=tuple(
                predefined["type_line"].split("—")[1].strip().lower().split()
            ) if "—" in predefined["type_line"] else (),
            oracle_text=predefined["oracle_text"],
            per_death=_parse_for_each(stream),
        )

    # "a **legendary** 3/4 …" (Stangg): a supertype is printed between the
    # quantity and the P/T, ahead of everything the characteristic loop below
    # reads. Same reader, called twice, for the reason `_parse_token_colors` is
    # — the colours print in two places too, and one reader is what keeps the
    # two spellings meaning the same thing.
    supertypes: list[str] = []
    _parse_token_supertypes(stream, supertypes)

    counted_pt = None
    if pt_optional and not stream.at_kind(PT):
        # "Create a black Spirit creature token. **Its power is equal to …**"
        # (Broken Visage.) The P/T is stated by the sentence behind this one, so
        # there is no number here to read. Only a caller that goes on to read
        # that sentence passes ``pt_optional`` — defaulted off, a token line
        # with no P/T keeps the refusal it has always had rather than compiling
        # to a 0/0 nothing printed.
        return _finish_create_token(
            stream, count, leading_name, supertypes, None, None, None
        )
    power, power_negative, toughness, toughness_negative = expect_pt(stream)
    if power_negative or toughness_negative:
        raise stream.error("a token's printed power/toughness cannot be negative")
    if not (isinstance(power, ast.Fixed) and isinstance(toughness, ast.Fixed)):
        # "Create an **X/X** … token, where X is the number of …" (Experimental
        # Overload). Both halves must be the *same* variable: "X/Y" is two
        # counts and the where-clause that follows defines one, so admitting it
        # would silently give the token the wrong toughness.
        if not (
            isinstance(power, ast.Var) and isinstance(toughness, ast.Var)
            and power.name == toughness.name
        ):
            raise stream.error(
                "a token's printed power/toughness is a number or one variable"
            )
        counted_pt = power
        power = toughness = None
    return _finish_create_token(
        stream, count, leading_name, supertypes, power, toughness, counted_pt
    )


def _finish_create_token(
    stream: TokenStream,
    count,
    leading_name: str,
    supertypes: list[str],
    power,
    toughness,
    counted_pt,
) -> ast.Statement:
    """Everything a token spec states *after* its power and toughness.

    Split out of :func:`_parse_create_token` rather than duplicated, because
    the P/T is the one field that has two printed positions — inline, or in the
    sentence behind the token (Broken Visage) — and everything else reads the
    same either way. Two copies of this tail is how a colour word or a `with`
    clause comes to be honoured on one spelling and dropped on the other.
    """
    colors: list[str] = []
    stated_colour = _parse_token_colors(stream, colors)

    subtypes: list[str] = []
    card_types: list[str] = []
    while not stream.at_word("token", "tokens"):
        word = stream.peek_word()
        if word is None:
            raise stream.error("expected 'token' after a token's characteristics")
        if _parse_token_supertypes(stream, supertypes):
            continue
        if word in CARD_TYPES:
            card_types.append(word)
            stream.advance()
            continue
        matched = match_longest(stream.words_from(), 0, SUBTYPE_INDEX)
        if matched is None:
            raise stream.error(f"unrecognized token characteristic {word!r}")
        name, consumed = matched
        subtypes.append(name)
        stream.advance(consumed)
    stream.expect_word("token", "tokens")

    # "…1/1 Sand Warrior creature tokens **that are red, green, and white**"
    # (Hazezon Tamar). The same colours, printed after the head noun instead of
    # in front of the subtypes — so it is the same reader, called a second
    # time, rather than a second production. Read before the "that are tapped
    # and attacking" entry state below, which opens with the same two words and
    # would otherwise never see a colour word to decline on.
    if not stated_colour:
        mark_trailing_colour = stream.mark()
        if stream.accept_phrase("that", "are") and _parse_token_colors(stream, colors):
            stated_colour = True
        else:
            stream.reset(mark_trailing_colour)
    if not stated_colour:
        # Every token spec the pool prints states a colour, "colorless"
        # included, and the word has to stay load-bearing: an empty ``colors``
        # tuple already means colourless, so a production that let the word be
        # absent would also let it be *deleted* with no change to the payload —
        # which is precisely what the parse-coverage deletion probe flags as a
        # dropped rider. Refusing keeps the failure loud and keeps the grammar
        # off wordings no card in the pool carries.
        raise stream.error("expected the token's colour, or 'colorless'")

    keywords: tuple[str, ...] = ()
    granted_lines: tuple[str, ...] = ()
    if stream.accept_word("with"):
        # A quoted line is a printed *ability*; a bare word is a keyword. The
        # quote decides, which is why the two readers are separate rather than
        # one trying both.
        if stream.at_kind(QUOTE):
            granted_lines = _parse_token_quoted_lines(stream)
        else:
            keywords = _parse_token_keywords(stream)

    # "…**for each time it regenerated this turn**" (Spiny Starfish). A
    # multiplier on how many tokens are made, read here rather than by
    # ``phrases._parse_for_each`` because that clause counts a set of *objects*
    # and this one counts occurrences on one permanent. Both words of the
    # window are required, for the reason the death tally's are: the record is
    # swept each turn, so a clause naming another window is a different number.
    per_source_regeneration = bool(
        stream.accept_phrase(
            "for", "each", "time", "it", "regenerated", "this", "turn"
        )
    )

    # "…**for each untapped Forest they control**" (Waiting in the Weeds). The
    # board-set multiplier, through the fragment every other multiplied number
    # in the grammar reads — never a second copy, which is how two spellings of
    # one clause end up counting different sets. Read after the regeneration
    # window above, which it rewinds off rather than claiming.
    per_each, per_each_beyond_first = _parse_per_each_objects(stream)
    if per_each_beyond_first:
        raise stream.error("no token count discounts the first of the set")

    # "…that are tapped and attacking" (Basri Ket): the tokens' entry state.
    # Both words are recorded — a token entering merely tapped, or merely
    # attacking, would be a different effect wearing the same head.
    tapped = attacking = False
    # Basri Ket prints the plural ("that are"), Falconer Adept the singular
    # contraction ("that's") — one entry state, two spellings.
    if stream.accept_phrase("that", "are", "tapped", "and", "attacking") or stream.accept_phrase(
        "that", "'s", "tapped", "and", "attacking"
    ):
        tapped = attacking = True

    # CR 111.4 — the creating ability may set the token's name. When it does
    # not, the name follows from the subtypes, and lowering (not the parser)
    # decides whether the engine's convention for that is expressible.
    name = leading_name
    if stream.accept_word("named"):
        if name:
            raise stream.error("a token spec names the token once")
        named = _parse_token_name_words(stream)
        if named is None:
            raise stream.error("expected a token name after 'named'")
        name = named
        # "…named Tombspawn **for each creature card in their graveyard**."
        # The same clause at its other printed position, read by the same
        # fragment — a second reader would be a second answer to which sets may
        # multiply a token count, and which one a card got would depend on
        # where it printed the words. (`_parse_token_colors` is called twice for
        # exactly this reason.)
        if per_each is None:
            per_each, per_each_beyond_first = _parse_per_each_objects(stream)
            if per_each_beyond_first:
                raise stream.error("no token count discounts the first of the set")

    # "…tokens. **They each have flying and "This token can't be enchanted.""**
    # (Tetravus.) The tokens' abilities printed as a following sentence rather
    # than as a `with` clause. The same information, so it lands in the same two
    # fields — a statement of its own would have nothing to attach to, because
    # the tokens it describes exist only inside the instruction being built
    # here. Keywords and quoted lines mix freely in the list, which is why this
    # reads one item at a time instead of calling either tail parser on the
    # whole run: `_parse_token_keywords` consumes the "and" itself and would
    # then demand a keyword where a quote stands.
    #
    # "…token. **It has** "Whenever this creature deals damage to a player,
    # that player gets a poison counter."" (Serpent Generator) — the same
    # sentence in the singular a one-token effect prints.
    mark_tail = stream.mark()
    if stream.accept_punct(".") and (
        stream.accept_phrase("they", "each", "have")
        or stream.accept_phrase("it", "has")
    ):
        while True:
            if stream.at_kind(QUOTE):
                granted_lines += _parse_token_quoted_lines_one(stream)
            else:
                matched = match_longest(stream.words_from(), 0, KEYWORD_INDEX)
                if matched is None:
                    raise stream.error(
                        "expected a keyword or a quoted ability on the token"
                    )
                keyword, consumed = matched
                keywords += (keyword,)
                stream.advance(consumed)
            stream.accept_punct(",")
            if not stream.accept_word("and"):
                break
        stream.accept_punct(".")
    else:
        stream.reset(mark_tail)

    granted_lines += _parse_token_trigger_sentences(stream)

    return ast.CreateToken(
        count=count,
        power=power.value if power is not None else None,
        toughness=toughness.value if toughness is not None else None,
        counted_pt=counted_pt,
        granted_lines=granted_lines,
        name=name,
        colors=tuple(colors),
        types=tuple(card_types),
        supertypes=tuple(supertypes),
        subtypes=tuple(subtypes),
        keywords=keywords,
        tapped=tapped,
        attacking=attacking,
        per_source_regeneration=per_source_regeneration,
        per_each=per_each,
    )


def _parse_token_trigger_sentences(stream: TokenStream) -> tuple[str, ...]:
    """Triggered abilities of the token printed as *unquoted* sentences after it.

    "Create a 1/1 green Splinter creature token. It has flying and "Cumulative
    upkeep {G}." **When it leaves the battlefield, it deals 1 damage to you and
    each creature you control.**" (Splintering Wind.)

    The same information ``_parse_token_quoted_lines`` reads, printed without
    the quotation marks — Magic writes a token's ability either way, and the
    difference is typography rather than rules. So it lands in the same field
    and is gated by the same ``token_line_supported`` check in the lowering.

    **The pronoun is rewritten, and that is the whole content of this
    production.** "When **it** leaves the battlefield" is a sentence about the
    token, but the string handed to the compiler becomes the *token's own* text,
    where the same referent is spelled "this creature" — the bare "it" would
    read as the ability's source and mean the same thing here only by accident.
    Rewriting the trigger's subject and nothing else is deliberate: every later
    "it" in the sentence is already the token's own self-reference on a card
    whose text this is.

    Slicing the printed span rather than re-rendering the parsed tokens, for
    :func:`_parse_token_quoted_lines`'s reason: the compiler must read the words
    the card prints.

    Returns an empty tuple and consumes nothing when no such sentence follows,
    so every token spec that parsed before this existed parses identically.
    """
    lines: list[str] = []
    while True:
        mark = stream.mark()
        # The full stop is *optional* because the preceding tail may already
        # have eaten it: the "It has …" run above closes itself with one, and
        # a bare token spec does not. Requiring it here made this production
        # unreachable on exactly the card it was written for.
        stream.accept_punct(".")
        trigger = stream.peek_word()
        if trigger not in ("when", "whenever"):
            stream.reset(mark)
            break
        stream.advance()
        # Only the singular pronoun. "They" over several tokens is a sentence no
        # card in the pool prints here, and admitting it would make one line the
        # text of every token the effect created without anything having said so.
        if not stream.accept_word("it"):
            stream.reset(mark)
            break
        rest_open = stream.pos
        while not stream.exhausted and not (
            stream.at_kind(PUNCT) and stream.peek().text == "."
        ):
            stream.advance()
        rest = stream.text_between(rest_open, stream.pos)
        if not rest:
            stream.reset(mark)
            break
        lines.append(f"{trigger.capitalize()} this creature {rest}.")
    return tuple(lines)


def parse_create_token_with_stated_pt(stream: TokenStream) -> "ast.CreateToken | None":
    """``Create a <colours> <subtypes> creature token. Its power is equal to
    <A> and its toughness is equal to <B>.`` (Broken Visage.)

    Two printed sentences and one effect, for :func:`_parse_choose_then_gain`'s
    reason: the first states a creature token with **no P/T at all**, and
    CR 208.2 makes that no card — the second sentence is where the numbers come
    from. Parsed apart, the first would be a 0/0 nothing printed and the second
    would be a sentence about a token no reader could name.

    Every refusal below leaves the cursor where it found it, so a token line
    that is not this shape keeps the refusal it already had:

    * the token must be a **creature**. A Treasure has no P/T because CR 208.1
      gives none to a noncreature permanent, and that is a finished sentence
      rather than half of this one;
    * both halves must be stated. "Its power is equal to X" alone leaves a
      toughness nobody printed, and defaulting it would invent a number;
    * the amounts are ordinary back-references, so the lowering refuses one
      with no producer in the same effect (idiom 7) rather than reading a zero.
    """
    if not stream.at_word("create"):
        return None
    mark = stream.mark()
    try:
        token = _parse_create_token(stream, pt_optional=True)
    except GrammarError:
        stream.reset(mark)
        return None
    if (
        not isinstance(token, ast.CreateToken)
        or token.power is not None
        or token.toughness is not None
        or token.counted_pt is not None
        or "creature" not in token.types
    ):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("its", "power", "is"):
        stream.reset(mark)
        return None
    power = parse_equal_to(stream)
    if power is None or not stream.accept_word("and"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("its", "toughness", "is"):
        stream.reset(mark)
        return None
    toughness = parse_equal_to(stream)
    if toughness is None:
        stream.reset(mark)
        return None
    return dataclasses.replace(token, pt_from=(power, toughness))
