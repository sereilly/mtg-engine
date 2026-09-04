"""Tokens, and effects on the whole game.

Token creation (the largest single production in the parser — a token's name,
P/T, colours, types and keywords are all printed in one sentence), winning,
drawing the game, extra turns, and the Aura `enchant` line.

Grouped because each is a sentence about the game state rather than about one
permanent's characteristics, and none of them shares vocabulary with another
family.
"""

import dataclasses

from ...tokens import PREDEFINED_TOKENS
from .. import ast
from ..amounts import expect_pt, parse_amount
from ..errors import GrammarError
from ..lexer import (PT, PUNCT, QUOTE, SELF, WORD)
from ..nouns import parse_object_filter
from ..references import parse_player_ref, parse_target_spec
from ..phrases import _parse_for_each, _parse_per_each_objects
from ..stream import TokenStream
from ..vocabulary import (CARD_TYPES, COLOR_WORDS, KEYWORD_INDEX, SUBTYPE_INDEX,
                          TYPE_LINE_SUPERTYPES, match_longest, singular)


def _parse_wins(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> wins the game`` (CR 104.2b)."""
    stream.expect_word("wins", "win")
    stream.expect_word("the")
    stream.expect_word("game")
    player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
    return ast.WinGame(player)


def _parse_game_is_a_draw(stream: TokenStream) -> ast.Statement | None:
    """``The game is a draw.`` (CR 104.4c.)

    The one game-outcome sentence with no subject, so it cannot go through
    ``_parse_subject_verb``'s noun phrase. Returns None without consuming
    anything when the line merely *starts* with "the", so every other production
    beginning that way is unaffected.
    """
    mark = stream.mark()
    if stream.accept_phrase("the", "game", "is", "a", "draw"):
        return ast.DrawGame()
    stream.reset(mark)
    return None


def _parse_coin_flip_stakes_loop(stream: TokenStream) -> ast.Statement | None:
    """``Flip a coin. If you win the flip, you gain N life and target opponent
    loses N life, and you decide whether to flip again. If you lose the flip,
    you lose N life and that opponent gains N life, and that player decides
    whether to flip again. [Double the life stakes with each flip.]``
    (Game of Chaos.)

    Read whole, for the reason Mana Clash's flip loop is: every sentence after
    the first reads a flip only the first produces, and the offer that repeats
    the paragraph is answered by whichever player the *result* names — which no
    sentence read on its own can say.

    It lives with the `game` family rather than in `paragraphs`, where the pool's
    other whole-paragraph productions sit, because that module is at the size
    guard and this paragraph's node and lowering are `ast/game.py`'s and
    `lowering/game.py`'s: putting it here re-forms the mirror instead of
    forking it, and ``_parse_flip_coin`` beside it already reads the first
    sentence on its own.

    Every fixed word is *expected* once the second sentence has been entered,
    not accepted, for that production's stated reason: each is a way the
    paragraph could mean something smaller and still parse. The four printed
    amounts must be the one quantity they are printed as — a production that let
    them differ would compile a card nobody printed — and the closing sentence
    is genuinely optional, so that reading it changes what happens rather than
    being consumed and dropped.
    """
    mark = stream.mark()
    if not stream.accept_phrase("flip", "a", "coin"):
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("if", "you", "win", "the", "flip"):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("you", "gain"):
        stream.reset(mark)
        return None
    stake = parse_amount(stream)
    if not stream.accept_phrase("life", "and", "target", "opponent", "loses"):
        stream.reset(mark)
        return None
    amounts = [stake, parse_amount(stream)]
    if not stream.accept_word("life"):
        raise stream.error("expected the life the opponent loses")
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "and", "you", "decide", "whether", "to", "flip", "again"
    ):
        raise stream.error("expected the offer to flip again")
    stream.accept_punct(".")
    if not stream.accept_phrase("if", "you", "lose", "the", "flip"):
        raise stream.error("expected the losing half of the flip")
    stream.accept_punct(",")
    if not stream.accept_phrase("you", "lose"):
        raise stream.error("expected the life you lose")
    amounts.append(parse_amount(stream))
    if not stream.accept_phrase("life", "and", "that", "opponent", "gains"):
        raise stream.error("expected the life that opponent gains")
    amounts.append(parse_amount(stream))
    if not stream.accept_word("life"):
        raise stream.error("expected the life the opponent gains")
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "and", "that", "player", "decides", "whether", "to", "flip", "again"
    ):
        raise stream.error("expected the losing half's offer to flip again")
    stream.accept_punct(".")
    doubling = stream.accept_phrase(
        "double", "the", "life", "stakes", "with", "each", "flip"
    )
    if any(other != stake for other in amounts[1:]):
        raise stream.error("the four printed stakes must be one quantity")
    return ast.CoinFlipStakesLoop(stake, bool(doubling))


def _parse_flip_coin(stream: TokenStream) -> ast.Statement | None:
    """``Flip a coin.`` (CR 705.1.)

    Returns None without consuming anything for any other sentence starting
    "flip" — Chaos Orb's "flip it onto the battlefield from a height of at least
    one foot" is a different action, and its card hook must keep getting it.
    """
    mark = stream.mark()
    # "**You** flip a coin." (Amulet of Quoz.) CR 705.1 gives the flip a
    # flipper, and both spellings name the same one: the controller of the
    # effect, which is who ``flip_coin`` records the result for and who "if you
    # win the flip" then asks about. So the subject is a spelling, read here
    # rather than as a second production — two readers of one sentence is how
    # the two come to disagree about whose flip it is.
    stream.accept_word("you")
    if stream.accept_phrase("flip", "a", "coin"):
        return ast.FlipCoin()
    stream.reset(mark)
    return None


def _parse_choose_number(stream: TokenStream) -> ast.Statement | None:
    """``Choose a number between 0 and 7.`` (Shapeshifter.)

    Returns None without consuming anything for any other "choose" sentence, so
    the naming and modal productions beside it keep the ones they own. Both
    bounds must be printed numbers: a range with a word in it would be a
    different sentence, and reading only the first would silently halve the card.
    """
    mark = stream.mark()
    if stream.accept_phrase("choose", "a", "number", "between"):
        low = parse_amount(stream)
        if isinstance(low, ast.Fixed) and stream.accept_word("and"):
            high = parse_amount(stream)
            if isinstance(high, ast.Fixed) and low.value <= high.value:
                return ast.ChooseNumber(low.value, high.value)
    stream.reset(mark)
    return None


def _parse_count_objects(stream: TokenStream) -> "ast.CountObjects | None":
    """``Count the number of permanents.`` (Chaos Moon.)

    CR 107.1's number, taken once and named for the sentences behind it — see
    :class:`ast.CountObjects` for why the card prints this instead of a third
    "if", and why reading it as a sentence rather than folding it into the two
    conditions is what keeps both branches reachable.

    The noun phrase is read rather than assumed. "Permanents" is every object on
    every battlefield (CR 110.1), and a card counting something narrower is this
    same sentence with a different phrase — which is what makes the count
    payload rather than a kind.

    Refuses without consuming for anything else opening "count", and requires
    the sentence to *end* there: "count the number of permanents **and** …" is a
    sentence this has not read, and a reader that stopped early would leave the
    rest to be dropped.
    """
    mark = stream.mark()
    if not stream.accept_phrase("count", "the", "number", "of"):
        return None
    try:
        counted = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if counted.zone not in (None, "battlefield"):
        # A count out of a hand or a library is a different question with a
        # different answer, and nothing reads one back yet. Refusing keeps the
        # line's refusal rather than recording a number off the wrong zone.
        stream.reset(mark)
        return None
    if not (stream.exhausted or stream.at_punct(".", ";")):
        stream.reset(mark)
        return None
    return ast.CountObjects(counted)


def _parse_choose_color(stream: TokenStream) -> ast.Statement | None:
    """``Choose a color.`` (Chromatic Armor's activated ability.)

    Beside :func:`_parse_choose_number` and refusing the same way: None with the
    cursor untouched for every other "choose" sentence, so the naming, modal and
    player productions keep the ones they own.

    Exactly three words and nothing after them. "Choose a color **and**…" and
    "choose a color of your choice" are sentences this has not read, and a
    reader that stopped at "color" would leave the rest to be dropped.
    """
    mark = stream.mark()
    if stream.accept_phrase("choose", "a", "color") and (
        stream.exhausted or stream.at_punct(".", ",")
    ):
        return ast.ChooseColor()
    stream.reset(mark)
    return None


def _parse_choose_player_who_cast(stream: TokenStream) -> "ast.Statement | None":
    """``Choose a player who cast one or more sorcery spells this turn.``
    (Backdraft.)

    Returns None without consuming anything for any other "choose" sentence,
    exactly as the number and hand-pick productions beside it do, so the naming
    productions behind them keep their readings.

    The type and the minimum are both read off the words. "One or more" is the
    ordinary way Magic prints "at least one" and a card printing "two or more"
    is the same sentence with one number changed — so it is a quantity, not a
    phrase to match. The type must be a real card type: "a player who cast one
    or more **spells**" is a wider set, and reading it as this one would offer a
    choice the card never allowed.
    """
    mark = stream.mark()
    if not stream.accept_phrase("choose", "a", "player", "who", "cast"):
        stream.reset(mark)
        return None
    minimum = parse_amount(stream)
    if not (isinstance(minimum, ast.Fixed) and stream.accept_phrase("or", "more")):
        stream.reset(mark)
        return None
    card_type = stream.peek_word()
    if card_type is None or singular(card_type) not in CARD_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("spells", "this", "turn"):
        stream.reset(mark)
        return None
    return ast.ChoosePlayerWhoCast(singular(card_type), minimum.value)


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


def _parse_enchant(stream: TokenStream) -> ast.Statement:
    """``Enchant creature`` — an Aura's attachment restriction (CR 702.5).

    Not an effect: it declares what the Aura can be attached to. Parsed so the
    line is accounted for; the engine's attachment handling is driven elsewhere.
    """
    stream.expect_word("enchant")
    filt = parse_object_filter(stream, allow_bare=True)
    # "Enchant creature card in a graveyard" (Animate Dead).
    if stream.accept_word("card"):
        if stream.accept_word("in"):
            stream.accept_word("a", "an", "the")
            stream.expect_word("graveyard")
    return ast.RawEffect(f"enchant:{filt}")


def _parse_extra_turn(stream: TokenStream) -> ast.Statement:
    """``Take an extra turn after this one.`` (Time Walk, Time Vault.)

    The count is the article or a written-out number ("Take two extra turns
    after this one.", Teferi, Master of Time) — never defaulted, so a quantity
    the amount parser cannot read fails the line instead of quietly granting
    one turn. "after this one" is required for the same reason — it is what
    says the turns are taken immediately, and a card that placed it elsewhere
    would be a different effect.
    """
    stream.expect_word("take")
    if stream.accept_word("an"):
        count = 1
    else:
        amount = parse_amount(stream)
        if not isinstance(amount, ast.Fixed) or amount.value < 1:
            raise stream.error("expected a fixed number of extra turns")
        count = amount.value
    stream.expect_word("extra")
    stream.expect_word("turn", "turns")
    if not stream.accept_phrase("after", "this", "one"):
        raise stream.error("expected 'after this one'")
    return ast.ExtraTurn(ast.PlayerRef("you"), count)


def _parse_end_the_turn(stream: TokenStream) -> ast.Statement:
    """``End the turn.`` (Discontinuity.)

    Three words and every one of them required. "End the turn" is CR 724.1's
    expedited process; "end of turn" is a *duration* and "at the beginning of
    the end step" is a trigger, and both are read elsewhere. Consuming only
    "end" would let either of those reach this production and lower into a
    process that exiles the stack.
    """
    stream.expect_word("end")
    stream.expect_word("the")
    stream.expect_word("turn")
    return ast.EndTheTurn()


def _parse_ante(
    stream: TokenStream, subject: ast.PlayerRef | None = None
) -> ast.Statement | None:
    """``[<player>] ante[s] the top card of <possessive> library`` (CR 407).

    Two printed shapes, one production. Demonic Attorney prints the subject
    ("Each player antes the top card of their library"); Rebirth's offer prints
    none, because the offering player is the one the ``may`` in front of it
    named ("Each player may ante the top card of their library").

    So **who antes is the printed subject where there is one, and the possessive
    where there is not**. That is not a fallback: with no subject the only word
    naming the player is "your"/"their", and reading it is reading the card.
    "Their" back-refers exactly the way ``references.parse_player_ref`` reads
    "they" — as ``that_player`` — so the offer binds it per seat and Demonic
    Attorney's every-seat loop never sees it.

    Refuses without consuming anything else, so any other sentence opening with
    the word keeps the refusal it has today.
    """
    mark = stream.mark()
    if not stream.accept_word("antes", "ante"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("the", "top", "card", "of"):
        stream.reset(mark)
        return None
    if stream.accept_word("your"):
        possessive = ast.PlayerRef("you")
    elif stream.accept_word("their") or stream.accept_phrase("his", "or", "her"):
        possessive = ast.PlayerRef("that_player")
    else:
        stream.reset(mark)
        return None
    if not stream.accept_word("library"):
        stream.reset(mark)
        return None
    return ast.Ante(subject if subject is not None else possessive)


def _parse_exchange_life_totals(stream: TokenStream) -> ast.Statement:
    """``Exchange life totals with <player>.`` (Mirror Universe.)

    Filed with the game family rather than beside ``_parse_exchange_control``
    in ``board``: what is exchanged is a life total, and the family a
    production belongs to is the family of what it acts on. The two share only
    the printed verb, and the dispatcher branches on the word after it.

    The other party goes through ``parse_player_ref``, so "target opponent",
    "target player" and "each opponent" are read by the same noun phrase every
    other sentence about a player uses; what the handler can actually exchange
    with is the lowering's question.
    """
    stream.expect_word("exchange")
    if not stream.accept_phrase("life", "totals"):
        raise stream.error("expected 'life totals' after 'exchange'")
    if not stream.accept_word("with"):
        raise stream.error("expected 'with' after 'exchange life totals'")
    player = parse_player_ref(stream)
    if player is None:
        raise stream.error("expected the player to exchange life totals with")
    return ast.ExchangeLifeTotals(player)


def _parse_life_total_becomes(stream: TokenStream) -> ast.Statement | None:
    """``<player>'s life total becomes <N>`` / ``your life total becomes <N>``.

    CR 119.5: this is a gain or a loss of the difference, but the printed number
    is the *result*, so the sentence cannot be read as either one until the
    handler knows the current total. Its own node for that reason rather than a
    ``GainLife`` with a flag.

    Read before ``_parse_subject_verb``'s noun phrase because the subject is a
    possessive *of a player* — "that player's life total" — which the recipient
    parser reads down to the player and then chokes on. Refuses without
    consuming, so every other possessive sentence keeps its reading.
    """
    mark = stream.mark()
    if stream.accept_word("your"):
        player = ast.PlayerRef("you")
    else:
        player = parse_player_ref(stream)
        if player is None or not stream.accept_word("'s"):
            stream.reset(mark)
            return None
    if not stream.accept_phrase("life", "total"):
        stream.reset(mark)
        return None
    if not stream.accept_word("becomes", "become"):
        stream.reset(mark)
        return None
    try:
        amount = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    return ast.SetLifeTotal(player, amount)




#: The steps a printed "skip your next <step>" may name, mapped to the internal
#: step name ``Game.skip_next_step`` is keyed by. A table rather than a free
#: word, because a step this engine does not run would be a skip that never
#: fires and a card that reports supported.
_SKIPPABLE_STEPS: dict[str, str] = {
    "draw": "draw",
    "untap": "untap",
    "combat": "combat",
}


def _parse_skip_step(stream: TokenStream, subject) -> ast.Statement:
    """``<player> skip[s] their next <step> step.`` (Ivory Gargoyle.)

    CR 500.7: a skipped step never begins, and CR 614.10 makes the skip a
    replacement effect. **Whose** step is half the sentence — a skip stored
    against the step's name alone eats whichever seat's draw step comes round
    first, which on an opponent's turn is the wrong player's — so the seat rides
    the node and the lowering carries it into the payload.

    Only "your next" today. "Skip your next turn" is a different rule (CR
    500.11's turn counter) with its own handler, and an unbounded "skip your
    draw steps" is a continuous effect rather than a one-shot; both refuse here
    rather than borrowing this one's arithmetic.
    """
    stream.expect_word("skips", "skip")
    if not (stream.accept_phrase("your", "next") or stream.accept_phrase("their", "next")):
        raise stream.error("expected 'your next' after 'skip'")
    word = stream.peek_word()
    step = _SKIPPABLE_STEPS.get(word or "")
    if step is None:
        raise stream.error(f"no skippable step named {word!r}")
    stream.advance()
    if not stream.accept_word("step"):
        raise stream.error("expected 'step' after the step's name")
    return ast.SkipStep(subject, step)
