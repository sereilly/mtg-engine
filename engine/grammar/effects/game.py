"""Tokens, and effects on the whole game.

Token creation (the largest single production in the parser — a token's name,
P/T, colours, types and keywords are all printed in one sentence), winning,
drawing the game, extra turns, and the Aura `enchant` line.

Grouped because each is a sentence about the game state rather than about one
permanent's characteristics, and none of them shares vocabulary with another
family.
"""

from ...tokens import PREDEFINED_TOKENS
from .. import ast
from ..amounts import expect_pt, parse_amount
from ..errors import GrammarError
from ..lexer import (QUOTE, SELF, WORD)
from ..nouns import parse_object_filter
from ..references import parse_player_ref, parse_target_spec
from ..phrases import _parse_for_each
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


def _parse_flip_coin(stream: TokenStream) -> ast.Statement | None:
    """``Flip a coin.`` (CR 705.1.)

    Returns None without consuming anything for any other sentence starting
    "flip" — Chaos Orb's "flip it onto the battlefield from a height of at least
    one foot" is a different action, and its card hook must keep getting it.
    """
    mark = stream.mark()
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
        if stream.accept_punct(","):
            stream.accept_word("and")
            continue
        if stream.accept_word("and"):
            continue
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


def _parse_create_token(stream: TokenStream) -> ast.Statement:
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

    power, power_negative, toughness, toughness_negative = expect_pt(stream)
    if power_negative or toughness_negative:
        raise stream.error("a token's printed power/toughness cannot be negative")
    counted_pt = None
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
    )


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


