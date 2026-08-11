"""Tokens, and effects on the whole game.

Token creation (the largest single production in the parser — a token's name,
P/T, colours, types and keywords are all printed in one sentence), winning,
drawing the game, extra turns, and the Aura `enchant` line.

Grouped because each is a sentence about the game state rather than about one
permanent's characteristics, and none of them shares vocabulary with another
family.
"""

from .. import ast
from ..amounts import expect_pt, parse_amount
from ..lexer import (WORD)
from ..nouns import (parse_object_filter)
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
    stream.expect_word("create")
    count = parse_amount(stream)

    power, power_negative, toughness, toughness_negative = expect_pt(stream)
    if power_negative or toughness_negative:
        raise stream.error("a token's printed power/toughness cannot be negative")
    if not (isinstance(power, ast.Fixed) and isinstance(toughness, ast.Fixed)):
        # ``CreateToken`` stores printed integers, and ``create_token`` reads
        # them with ``int(...)``. A variable "X/X token" has no representation
        # on either side, so it refuses here rather than resolving to a
        # sentinel that would reach the battlefield as a real creature.
        raise stream.error("a token with a variable power/toughness has no representation")

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
    if stream.accept_word("with"):
        keywords = _parse_token_keywords(stream)

    # "…that are tapped and attacking" (Basri Ket): the tokens' entry state.
    # Both words are recorded — a token entering merely tapped, or merely
    # attacking, would be a different effect wearing the same head.
    tapped = attacking = False
    if stream.accept_phrase("that", "are", "tapped", "and", "attacking"):
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
        power=power.value,
        toughness=toughness.value,
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
