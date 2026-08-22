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
from ..lexer import (QUOTE, WORD)
from ..nouns import (parse_object_filter, parse_target_spec)
from ..phrases import _parse_for_each
from ..stream import TokenStream
from ..vocabulary import (CARD_TYPES, COLOR_WORDS, KEYWORD_INDEX, SUBTYPE_INDEX, match_longest)


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
    stated_colour = False
    while True:
        word = stream.peek_word()
        if word in COLOR_WORDS:
            colors.append(COLOR_WORDS[word])
            stated_colour = True
            stream.advance()
            stream.accept_punct(",")
            stream.accept_word("and")
            continue
        if word == "colorless":
            stated_colour = True
            stream.advance()
            continue
        break
    if not stated_colour:
        # Every token spec the pool prints states a colour, "colorless"
        # included, and the word has to stay load-bearing: an empty ``colors``
        # tuple already means colourless, so a production that let the word be
        # absent would also let it be *deleted* with no change to the payload —
        # which is precisely what the parse-coverage deletion probe flags as a
        # dropped rider. Refusing keeps the failure loud and keeps the grammar
        # off wordings no card in the pool carries.
        raise stream.error("expected the token's colour, or 'colorless'")

    subtypes: list[str] = []
    card_types: list[str] = []
    while not stream.at_word("token", "tokens"):
        word = stream.peek_word()
        if word is None:
            raise stream.error("expected 'token' after a token's characteristics")
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
    name = ""
    if stream.accept_word("named"):
        parts: list[str] = []
        while stream.peek() is not None and stream.at_kind(WORD):
            parts.append(stream.next().text)
        if not parts:
            raise stream.error("expected a token name after 'named'")
        name = " ".join(parts)

    return ast.CreateToken(
        count=count,
        power=power.value if power is not None else None,
        toughness=toughness.value if toughness is not None else None,
        counted_pt=counted_pt,
        granted_lines=granted_lines,
        name=name,
        colors=tuple(colors),
        types=tuple(card_types),
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
