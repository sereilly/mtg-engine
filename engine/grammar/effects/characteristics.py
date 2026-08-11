"""What a permanent *is*: P/T, keywords, colour, printed text, counters.

The `gets`/`gains`/`loses`/`has` family (CR 613 layers 6 and 7), base-P/T
setting, colour changes, the printed-text swaps of Sleight of Mind and Magical
Hack, and +1/+1-style counters including the "for each creature that died"
repetition.

Counters are here rather than with the board because what a counter does is
change a characteristic; where it sits is incidental.
"""

from .. import ast
from ..amounts import expect_pt, parse_amount, parse_equal_to
from ..errors import GrammarError
from ..lexer import (GToken, PT, WORD)
from ..nouns import (parse_object_filter, parse_recipient)
from ..stream import TokenStream
from ..vocabulary import (COLOR_WORDS)
from ..phrases import _COUNTER_KINDS, _parse_duration, _parse_keywords


def _parse_gets(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> gets +N/+N [duration]``."""
    stream.expect_word("gets", "get")
    power, power_negative, toughness, toughness_negative = expect_pt(stream)
    duration = _parse_duration(stream)
    pump = ast.Pump(subject, power, toughness, duration, power_negative, toughness_negative)

    # "gets +3/+3 and gains flying until end of turn" / "get +1/+1 and have
    # mountainwalk" — the same conjunction in the two persons the templating
    # uses. Accepting only "gains" would leave the lordly form ("Other Goblins
    # get +1/+1 and have mountainwalk") stranding "have mountainwalk", which
    # fails full consumption and takes the whole line down.
    mark = stream.mark()
    if stream.accept_word("and") and stream.at_word("gains", "gain", "has", "have"):
        stream.advance()
        keywords = _parse_keywords(stream)
        keyword_duration = _parse_duration(stream)
        if duration.kind is None and keyword_duration.kind is not None:
            pump = ast.Pump(
                subject, power, toughness, keyword_duration,
                power_negative, toughness_negative,
            )
        return ast.Conjunction((pump, ast.GainKeyword(subject, keywords, keyword_duration)))
    stream.reset(mark)
    return pump


def _parse_gains(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> gains <keywords|life> [duration]``."""
    stream.expect_word("gains", "gain")

    # "you gain 3 life" / "you gain life equal to the damage dealt"
    mark = stream.mark()
    if stream.at_word("life"):
        stream.advance()
        amount = parse_equal_to(stream)
        if amount is None:
            stream.reset(mark)
        else:
            player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
            return ast.GainLife(player, amount)
    else:
        try:
            amount = parse_amount(stream)
            if stream.accept_word("life"):
                player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
                return ast.GainLife(player, amount)
        except GrammarError:
            pass
        stream.reset(mark)

    keywords = _parse_keywords(stream)
    duration = _parse_duration(stream)
    grant = ast.GainKeyword(subject, keywords, duration)

    mark = stream.mark()
    if stream.accept_word("and") and stream.at_word("gets", "get"):
        pump = _parse_gets(stream, subject)
        # Berserk: "gains trample and gets +X/+0 until end of turn" — the shared
        # duration sits at the end and applies to both halves.
        if isinstance(pump, ast.Pump) and duration.kind is None and pump.duration.kind:
            grant = ast.GainKeyword(subject, keywords, pump.duration)
        return ast.Conjunction((grant, pump))
    stream.reset(mark)
    return grant


def _parse_loses(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> loses <the game|keywords|life>``."""
    stream.expect_word("loses", "lose")
    mark = stream.mark()
    # "loses the game" (CR 104.3e) before the life reading: "the" is not an
    # amount, so the amount branch below rejects it anyway, but checking here
    # keeps the two spellings of "lose" visibly separate.
    if stream.accept_phrase("the", "game"):
        player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
        return ast.LoseGame(player)
    stream.reset(mark)
    try:
        amount = parse_amount(stream)
        if stream.accept_word("life"):
            player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
            return ast.LoseLife(player, amount)
    except GrammarError:
        pass
    stream.reset(mark)
    keywords = _parse_keywords(stream)
    duration = _parse_duration(stream)
    return ast.LoseKeyword(subject, keywords, duration)


def _parse_has(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> has <keywords>`` / ``<subject> has base power …``.

    "Has" is the third person of "gains" — "Enchanted creature has flying" and
    "Target creature gains flying until end of turn" grant the same thing and
    differ only in duration, so they share :class:`ast.GainKeyword` rather than
    getting a node apiece. What separates them is exactly what lowering acts on:
    a granted keyword with no duration is a continuous effect (CR 613) and is
    refused there, while one with a duration has a handler.

    "Base power" is checked first and delegated, because it is the one reading
    of "has" that is not a keyword grant. Falling through to the keyword list
    instead would make "has base power and toughness 3/3" fail on "base" — which
    is not a keyword — and take the whole line down with it.
    """
    mark = stream.mark()
    stream.expect_word("has", "have")
    if stream.at_word("base"):
        stream.reset(mark)
        return _parse_has_base_pt(stream, subject)
    keywords = _parse_keywords(stream)
    duration = _parse_duration(stream)
    return ast.GainKeyword(subject, keywords, duration)


def _parse_has_base_pt(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> has base power [and toughness] N[/N] [duration]``."""
    stream.expect_word("has", "have")
    stream.expect_word("base")
    stream.expect_word("power")

    if stream.accept_phrase("and", "toughness"):
        token = stream.peek()
        if token is not None and token.kind == PT:
            power, _, toughness, _ = expect_pt(stream)
        else:
            power = parse_amount(stream)
            toughness = parse_amount(stream)
        duration = _parse_duration(stream)
        return ast.SetBasePT(subject, power, toughness, duration)

    power = parse_amount(stream)
    duration = _parse_duration(stream)
    return ast.SetBasePT(subject, power, None, duration)


def _expect_counter_kind(stream: TokenStream, suffix: str = "") -> GToken:
    """The counter's written name, as its token.

    The kind must be *written out*. Defaulting a bare "put a counter on it" to
    +1/+1 would silently invent the wrong counter for cards that use any other
    kind — the deletion probe flagged exactly this by removing the "+1/+1"
    token and getting the same instruction back — and reading the head noun as
    the kind would invent a counter called "counter".

    A plain word is admitted as well as a P/T token, because CR 122.1 lets a
    counter have any name and the pool prints several ("corpse", "wind",
    "mire"). Which of those anything can actually *do* is a question for the
    caller: the two callers differ precisely there, so the check stays with
    them rather than being frozen into one shared list here.
    """
    token = stream.peek()
    if token is None or token.kind not in (PT, WORD) or token.is_word("counter", "counters"):
        raise stream.error("expected a counter kind" + suffix)
    stream.advance()
    return token


def _parse_for_each(stream: TokenStream) -> ast.DiedThisTurn | None:
    """``for each <objects> that died this turn`` — a trailing iteration clause.

    The set is a *history*, not a board state, which is why it produces
    :class:`ast.DiedThisTurn` rather than the noun phrase's own filter.

    "This turn" is required rather than defaulted, for the reason the deletion
    probe exists: the engine's death tally resets each turn, so a clause
    counting some other window is a different number — and letting the words be
    absent would let them be *deleted* with no change to the parse.

    Returning None leaves the cursor where it was, so a caller that does not
    find the clause still owes the rest of the line to full-token consumption.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("that", "died"):
        stream.reset(mark)
        return None
    if _parse_duration(stream).kind != "this_turn":
        stream.reset(mark)
        return None
    return ast.DiedThisTurn(filt)


def _parse_put_counter(stream: TokenStream) -> ast.Statement:
    """``put [up to] N <counter> counter(s) on <subject> [for each …]``."""
    stream.expect_word("put")
    up_to = stream.accept_phrase("up", "to")
    count = parse_amount(stream)

    token = _expect_counter_kind(stream)
    if token.kind == PT and token.text not in _COUNTER_KINDS:
        raise stream.error(f"unsupported counter kind {token.text!r}")
    counter = token.text
    stream.expect_word("counter", "counters")
    stream.expect_word("on")
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected a permanent to put counters on")
    placement = ast.PutCounter(subject, counter, count, up_to)

    # "…for each creature that died this turn" multiplies the placement; it is
    # not a rider on it. Modelled as an iteration wrapping the placement so a
    # counter put down once and a counter put down per death are *different*
    # ASTs — the legacy registry told them apart only by giving the per-death
    # rule a lower order number than the plain one.
    iterated = _parse_for_each(stream)
    if iterated is None:
        return placement
    return ast.ForEach(iterated, placement)


def _parse_remove_counter(stream: TokenStream) -> ast.RemoveCounter | None:
    """``Remove [a|N] <kind> counter(s) from <subject>`` as an *effect*.

    The mirror of :func:`_parse_counter_removal_cost`, which reads the same
    words left of an ability's colon. Both are needed and neither subsumes the
    other: Armageddon Clock pays {4} and removes a counter as the effect, while
    Scavenging Ghoul removes one *to* activate.

    Returns None — cursor untouched — when what follows "remove" is not a
    counter at all. "Remove target creature defending player controls from
    combat" and "remove all damage marked on it" open the same way and are
    entirely different effects, so they have to keep failing on their own
    missing production instead of on a counter kind they never mentioned.
    """
    mark = stream.mark()
    stream.expect_word("remove")
    if stream.accept_word("a", "an"):
        count: ast.Amount = ast.Fixed(1)
    else:
        try:
            count = parse_amount(stream)
        except GrammarError:
            stream.reset(mark)
            return None
    try:
        counter = _expect_counter_kind(stream, " to remove").text
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_word("counter", "counters"):
        stream.reset(mark)
        return None
    stream.expect_word("from")
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected what to remove a counter from")
    return ast.RemoveCounter(subject, counter, count)


# Vocabularies a printed text change can swap, one literal phrase per mode
# (CR 612.1). Closed on purpose: `mark_text_modified` substitutes exactly these
# two, and a card naming a third — a creature type, a card name — is a text
# change the engine does not perform. Listing the phrases keeps that card
# failing here instead of reaching the handler as a mode it will ignore.
_TEXT_CHANGE_MODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("land_type", ("basic", "land", "type")),
    ("color_word", ("color", "word")),
)


def _parse_change_text(stream: TokenStream) -> ast.ChangeText:
    """``Change the text of <subject> by replacing all instances of one <what>
    with another.`` (Magical Hack, Sleight of Mind.)

    One production for the pair: they are the same sentence with one word
    changed, which is what makes the swapped vocabulary payload rather than part
    of the effect's name. Every word between the subject and the mode is
    required — "all instances of **one**" is what says a single word is
    replaced everywhere, and a card replacing something else, or only the first
    instance, would be a different effect wearing this one's sentence.
    """
    stream.expect_word("change")
    stream.expect_word("the")
    stream.expect_word("text")
    stream.expect_word("of")
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected what to change the text of")
    if not stream.accept_phrase("by", "replacing", "all", "instances", "of", "one"):
        raise stream.error("expected 'by replacing all instances of one'")
    for mode, phrase in _TEXT_CHANGE_MODES:
        if stream.accept_phrase(*phrase):
            if not stream.accept_phrase("with", "another"):
                raise stream.error("expected 'with another'")
            return ast.ChangeText(subject, mode)
    raise stream.error("no text substitution replaces this")


def _parse_become_color(stream: TokenStream, subject: ast.Recipient) -> ast.BecomeColor:
    """"<subject> becomes <colour>." The colour is the whole effect, so an
    unrecognized word after "becomes" must fail rather than be skipped."""
    stream.expect_word("becomes")
    token = stream.peek()
    word = str(token.text).lower() if token is not None else ""
    if word not in COLOR_WORDS:
        raise stream.error("expected a colour after 'becomes'")
    stream.advance()
    return ast.BecomeColor(subject, COLOR_WORDS[word])
