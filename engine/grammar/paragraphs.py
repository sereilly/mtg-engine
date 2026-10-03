"""Printed paragraphs that are one effect.

Every production here but one reads *several sentences* and returns a single
statement, because on these cards the sentences are not effects that happen to
follow one another. Mana Clash's three flip two coins and loop until both come
up heads; Tawnos's Coffin notes counters nothing else would read and gives them
back; Transmute Artifact compares two objects neither of which exists until a
choice has been made; Natural Balance's four printed numbers are one number.
Parsed sentence by sentence, each of these would produce one statement that
does something and several that have nothing to read.

The one is Idol of Endurance's exile, here as half of a pair: it records the
pile the card's other ability casts from, so "until this artifact leaves the
battlefield" is a return as well as a duration. The other half — the cast
permission over that pile — is a CR 601.3 grant, and went home at Prophecy's
Phase 0 to ``effects/permissions``, beside the general permission
``statements`` tries it in front of and opposite ``lowering/permissions.py``,
where it had always lowered.

**Three families have left, each along what its paragraphs are *about* rather
than how they read.** ``ownership`` took the three that change a card's owner
(CR 108.3), ``upkeep`` the ones an upkeep trigger frames, and ``naming`` — at
Prophecy's Phase 0 — the ones that turn on a card name or a card picked from a
hidden hand, a choice no board read can recover and every later sentence
checks. What stays is the remainder, and that is the honest description of
it: a paragraph comes here when no narrower family has claimed it.

They live together rather than in `statements.py` because they are the same kind
of thing and because that file is where every *ordinary* sentence goes — the one
that grows with the card pool. Keeping the paragraph productions there took it
past the thousand-line guard, and the split is along the line the guard asks
for: a sentence goes there, a paragraph goes here.

**Nothing here calls back into the sentence parser.** Every one of these reads
its own words to the end, which is what lets this module sit below
`statements.py` rather than beside it — and the layer order says so.
"""

from __future__ import annotations

from . import ast
from .amounts import parse_amount
from .errors import GrammarError
from .lexer import MANA, SELF
from .nouns import parse_object_filter
from .references import parse_recipient
from .stream import TokenStream
from .vocabulary import CARD_TYPES
from .vocabulary import singular as _singular_type


def _parse_coin_flip_damage_loop(stream: TokenStream) -> ast.Statement | None:
    """``You and target opponent each flip a coin. <source> deals N damage to
    each player whose coin comes up tails. Repeat this process until both
    players' coins come up heads on the same flip.`` (Mana Clash.)

    Read whole, like every paragraph here: the second sentence reads a pair of
    flips only the first produces, and the third is a loop over both of them.

    Returns None without consuming when the words are not this paragraph, so a
    sentence merely opening "You and …" keeps its own reading — the same
    courtesy Juxtapose's production is given, and for the same reason: both are
    tried in front of the subject parser, which would read "You" and choke on
    the conjunction.

    Every fixed word after the first sentence is *expected*, not accepted. Each
    one is a way the paragraph could mean something smaller and still parse:
    damage on "tails" rather than on heads, both coins rather than one, and a
    loop rather than a single round. A production that shrugged at the third
    sentence would compile Mana Clash as one flip.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "you", "and", "target", "opponent", "each", "flip", "a", "coin"
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    source = parse_recipient(stream)
    if source is None or not isinstance(source, ast.TargetSpec) or not source.filter.is_source:
        stream.reset(mark)
        return None
    if not stream.accept_word("deals", "deal"):
        stream.reset(mark)
        return None
    amount = parse_amount(stream)
    if not stream.accept_phrase(
        "damage", "to", "each", "player", "whose", "coin", "comes", "up", "tails"
    ):
        raise stream.error("expected damage to each player whose coin comes up tails")
    stream.accept_punct(".")
    if not stream.accept_phrase(
        # "players'" is one token: the lexer splits a possessive apostrophe off
        # a singular ("player 's") and leaves a plural one attached, so the
        # plural is matched as printed.
        "repeat", "this", "process", "until", "both", "players'", "coins",
        "come", "up", "heads", "on", "the", "same", "flip",
    ):
        raise stream.error("expected the repeat clause that closes the flip loop")
    return ast.CoinFlipDamageLoop(source, amount)



def _parse_exile_graveyard_until_leaves(stream: TokenStream) -> ast.Statement | None:
    """``Exile all <filter> from your graveyard until this <permanent> leaves
    the battlefield.`` (Idol of Endurance.)

    Every word of the duration is required. Without it this is a *permanent*
    exile of a graveyard, which is a different card — and the difference does
    not show until the source leaves.
    """
    if not stream.accept_phrase("exile", "all"):
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        return None
    if not filt.is_card or filt.zone != "graveyard":
        return None
    if filt.zone_owner is None or filt.zone_owner.kind != "you":
        return None
    if not stream.accept_phrase("until", "this"):
        return None
    if stream.accept_kind(SELF) is None:
        # The noun is **required**, not merely accepted: without it the sentence
        # still matched and the word could be deleted with no change to what was
        # lowered, which is exactly what the parse-coverage deletion probe is
        # for. A card naming itself gets the SELF token instead.
        if not stream.accept_word(
            "artifact", "creature", "enchantment", "permanent", "land"
        ):
            return None
    if not stream.accept_phrase("leaves", "the", "battlefield"):
        return None
    return ast.ExileGraveyardUntilLeaves(filt)


def _parse_transmute_by_sacrifice(stream: TokenStream) -> ast.Statement | None:
    """Transmute Artifact's whole seven-sentence effect, as one statement.

    ``Sacrifice an <A>. If you do, search your library for an <B> card. If that
    card's mana value is less than or equal to the sacrificed <A>'s mana value,
    put it onto the battlefield. If it's greater, you may pay {X}, where X is
    the difference. If you do, put it onto the battlefield. If you don't, put it
    into its owner's graveyard. Then shuffle.``

    Both noun phrases are read rather than fixed, so the two words this card
    happens to print are payload. Everything else is required: the comparison,
    the payment, **both** branches of it and the shuffle each name something the
    handler does, and a production that let one be absent would also let it be
    deleted with no change to what was lowered.
    """
    if not stream.accept_word("sacrifice"):
        return None
    if not stream.accept_word("a", "an"):
        return None
    try:
        sacrificed = parse_object_filter(stream)
    except GrammarError:
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("if", "you", "do"):
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("search", "your", "library", "for"):
        return None
    if not stream.accept_word("a", "an"):
        return None
    try:
        found = parse_object_filter(stream)
    except GrammarError:
        return None
    # The printed word "card" is what says the search reads a *library*, not a
    # battlefield (CR 400.1), and dropping it would make the two filters mean
    # different kinds of object while looking identical.
    if not found.is_card:
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase(
        "if", "that", "card", "'s", "mana", "value", "is", "less", "than",
        "or", "equal", "to", "the", "sacrificed",
    ):
        return None
    # "…the sacrificed **artifact's** mana value" names the same noun the
    # sacrifice clause did, so a sentence comparing against something else
    # refuses rather than comparing against whatever went.
    if not stream.accept_word(*(sacrificed.card_types or ("permanent",))):
        return None
    if not stream.accept_phrase("'s", "mana", "value"):
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("put", "it", "onto", "the", "battlefield"):
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("if", "it", "'s", "greater"):
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("you", "may", "pay"):
        return None
    # The cost is {X} and the sentence after it says what X is; any other cost
    # would be a different card and the handler computes only this one.
    paid = stream.accept_kind(MANA)
    if paid is None or paid.text.upper() != "{X}":
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("where", "x", "is", "the", "difference"):
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("if", "you", "do"):
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("put", "it", "onto", "the", "battlefield"):
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("if", "you", "don't"):
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("put", "it", "into", "its", "owner", "'s", "graveyard"):
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("then", "shuffle"):
        return None
    return ast.TransmuteBySacrifice(sacrificed, found)


def _parse_exile_until_leaves_or_untaps(stream: TokenStream) -> ast.Statement | None:
    """Tawnos's Coffin's four sentences, as one statement.

    ``Exile target creature and all Auras attached to it. Note the number and
    kind of counters that were on that creature. When this artifact leaves the
    battlefield or becomes untapped, return that exiled card to the battlefield
    under its owner's control tapped with the noted number and kind of counters
    on it. If you do, return the other exiled cards to the battlefield under
    their owner's control attached to that permanent.``

    **Every word is required**, and each one is load-bearing rather than
    decorative: without the Auras the creature comes back naked, without the
    counters it comes back smaller, without "tapped" it comes back ready, and
    without either half of the two-event return it never comes back at all. A
    production that let any of them be absent would also let it be *deleted*
    with no change to what was lowered.
    """
    if not stream.accept_phrase("exile", "target", "creature"):
        return None
    if not stream.accept_phrase("and", "all", "auras", "attached", "to", "it"):
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase(
        "note", "the", "number", "and", "kind", "of", "counters",
        "that", "were", "on", "that", "creature",
    ):
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("when", "this"):
        return None
    if stream.accept_kind(SELF) is None:
        # The noun is **required**, not merely accepted: without it the sentence
        # still matched and the word could be deleted with no change to what was
        # lowered, which is exactly what the parse-coverage deletion probe is
        # for. A card naming itself gets the SELF token instead.
        if not stream.accept_word(
            "artifact", "creature", "enchantment", "permanent", "land"
        ):
            return None
    if not stream.accept_phrase("leaves", "the", "battlefield"):
        return None
    if not stream.accept_phrase("or", "becomes", "untapped"):
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "return", "that", "exiled", "card", "to", "the", "battlefield",
        "under", "its", "owner", "'s", "control", "tapped",
        "with", "the", "noted", "number", "and", "kind", "of", "counters",
        "on", "it",
    ):
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("if", "you", "do"):
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "return", "the", "other", "exiled", "cards",
        "to", "the", "battlefield", "under", "their", "owner", "'s", "control",
        "attached", "to", "that", "permanent",
    ):
        return None
    return ast.ExileUntilLeavesOrUntaps(
        ast.TargetSpec("target", ast.ObjectFilter(card_types=("creature",)), targeted=True)
    )


def _parse_pay_or_sacrifice_greatest_mana_value(
    stream: TokenStream,
) -> ast.Statement | None:
    """``Each player sacrifices the <type> they control with the greatest mana
    value unless they pay that <type>'s mana cost. If two or more <type>s a
    player controls are tied for greatest, that player chooses one.`` (Tariff.)

    Read whole, for this module's standing reason and for the one
    :func:`_parse_exchange_greatest_mana_value` gives one production down: the
    toll's cost is "**that** creature's mana cost", which names a permanent the
    first half chooses and nothing else knows; and the second sentence is about
    a tie among a set only the first half describes. Sentence by sentence it
    would be a sacrifice of a superlative with no reader, an offer whose cost
    has no referent, and a choice among nothing.

    **One noun, read three times and checked.** The printed type appears in the
    sacrificed noun phrase, in the toll's possessive and in the tie-break
    sentence, and all three are the same card type on any printing of this
    paragraph. Checking that rather than storing the first is what stops a
    printing whose sentences disagreed from being read as one of them.

    Refuses without consuming, so a sentence merely opening "Each player …"
    keeps its own reading.
    """
    mark = stream.mark()

    def _card_type() -> str | None:
        """The next word if it is a card type, else None with the cursor put
        back — a paragraph naming a noun the engine has no type for is not this
        one."""
        word = stream.peek_word()
        if word is None:
            return None
        singular = _singular_type(word)
        if singular not in CARD_TYPES:
            return None
        stream.advance()
        return singular

    if not stream.accept_phrase("each", "player", "sacrifices", "the"):
        stream.reset(mark)
        return None
    card_type = _card_type()
    if card_type is None:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "they", "control", "with", "the", "greatest", "mana", "value",
    ):
        stream.reset(mark)
        return None
    # "**unless they pay that creature's mana cost**" — the toll, whose amount
    # is not printed at all. Every word is required rather than skipped: who
    # pays, whose cost, and that it is the *mana* cost, each of which names
    # something the offer behind this does.
    if not stream.accept_phrase("unless", "they", "pay", "that"):
        stream.reset(mark)
        return None
    if _card_type() != card_type:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("'s", "mana", "cost"):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    # "**If two or more creatures a player controls are tied for greatest, that
    # player chooses one.**" CR 608.2d's answer to a superlative that names
    # several: the seat whose permanents they are picks. Required, because
    # without it the paragraph would have to pick for them — and a tie broken
    # by the engine is a strictly different card on every board with two equal
    # creatures.
    if not stream.accept_phrase("if", "two", "or", "more"):
        stream.reset(mark)
        return None
    if _card_type() != card_type:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "a", "player", "controls", "are", "tied", "for", "greatest",
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("that", "player", "chooses", "one"):
        stream.reset(mark)
        return None
    return ast.PayOrSacrificeGreatestManaValue(card_type)


def _parse_exchange_greatest_mana_value(stream: TokenStream) -> ast.Statement | None:
    """Juxtapose's whole three-sentence effect, as one statement.

    ``You and target player exchange control of the <type> you each control
    with the greatest mana value. Then exchange control of <type>s the same way.
    If two or more permanents a player controls are tied for greatest, their
    controller chooses one of them.``

    Every sentence is required and none of them can be read alone: "the same
    way" is an exchange only the first sentence describes, and the tie-break
    names permanents only the first two have picked out. The types are read
    rather than fixed, so the two words this card happens to print are payload.

    Refuses without consuming, like every production here — a line that merely
    opens with "You" is untouched.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "you", "and", "target", "player", "exchange", "control", "of", "the"
    ):
        stream.reset(mark)
        return None
    first_token = stream.peek()
    if first_token is None or first_token.text not in CARD_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    first = str(first_token.text)
    if not stream.accept_phrase(
        "you", "each", "control", "with", "the", "greatest", "mana", "value"
    ):
        stream.reset(mark)
        return None
    types = [first]
    stream.accept_punct(".")
    # "Then exchange control of <type>s the same way." Repeatable: a card
    # printing a third sentence gets a third type with no code.
    while True:
        loop = stream.mark()
        if not stream.accept_phrase("then", "exchange", "control", "of"):
            stream.reset(loop)
            break
        again = stream.peek()
        singular = (
            str(again.text).rstrip("s") if again is not None else ""
        )
        if singular not in CARD_TYPES:
            stream.reset(loop)
            break
        stream.advance()
        if not stream.accept_phrase("the", "same", "way"):
            stream.reset(loop)
            break
        types.append(singular)
        stream.accept_punct(".")
    if not stream.accept_phrase(
        "if", "two", "or", "more", "permanents", "a", "player", "controls",
        "are", "tied", "for", "greatest",
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "their", "controller", "chooses", "one", "of", "them"
    ):
        stream.reset(mark)
        return None
    return ast.ExchangeGreatestManaValue(tuple(types))



def _parse_reassign_blockers_between_attackers(
    stream: TokenStream,
) -> "ast.ReassignBlockersBetweenAttackers | None":
    """``Choose two target blocked attacking creatures. If each of those
    creatures could be blocked by all creatures that the other is blocked by,
    each creature that's blocking exactly one of those attacking creatures stops
    blocking it and is blocking the other attacking creature.`` (General
    Jarkeld.)

    Two sentences, one effect, for this module's reason: the second names
    "those creatures" and "the other", and only the first supplies them. Read
    apart, the first would announce two targets and do nothing with them and the
    second would have nothing to read at all.

    The noun phrase is *parsed*, not matched as words — "two target blocked
    attacking creatures" is an ordinary counted recipient the filter parser
    already reads — so a card printing the same relation about a narrower kind
    of attacker is payload. Everything after it is fixed, because every word of
    it is a way the sentence could mean something smaller: the hypothetical
    (drop it and the swap happens between creatures that could never have been
    declared that way), "exactly one" (drop it and a creature blocking *both*
    chosen attackers is moved off one of them), and "is blocking the other
    attacking creature" (drop it and the blockers are removed rather than
    reassigned).

    Refuses without consuming when the words are not this paragraph, so every
    other sentence opening "Choose …" keeps its own reading.
    """
    mark = stream.mark()
    if not stream.accept_word("choose"):
        stream.reset(mark)
        return None
    try:
        subject = parse_recipient(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if subject is None or not isinstance(subject, ast.TargetSpec):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "if", "each", "of", "those", "creatures", "could", "be", "blocked",
        "by", "all", "creatures", "that", "the", "other", "is", "blocked", "by",
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "each", "creature", "that", "'s", "blocking", "exactly", "one", "of",
        "those", "attacking", "creatures", "stops", "blocking", "it", "and",
        "is", "blocking", "the", "other", "attacking", "creature",
    ):
        raise stream.error(
            "expected the reassignment that closes the blocked-attacker swap"
        )
    return ast.ReassignBlockersBetweenAttackers(subject)


def _parse_rebalance_lands(stream: TokenStream) -> ast.Statement | None:
    """``Each player who controls six or more lands chooses five lands they
    control and sacrifices the rest. Each player who controls four or fewer
    lands may search their library for up to X basic land cards and put them
    onto the battlefield, where X is five minus the number of lands they
    control. Then each player who searched their library this way shuffles.``
    (Natural Balance.)

    Read whole, like every paragraph here, for the reason each of them is: the
    second sentence's X is defined by the third clause of its own sentence and
    by the first sentence's number, and the third sentence names a set only the
    second produces. Sentence by sentence it would be a player-set narrowing
    nothing implements, an amount with no definition, and a shuffle over
    nobody.

    **Four printed numbers, one number.** "Six or more" is one over the target,
    "four or fewer" is one under it, and "five minus the number of lands they
    control" counts up to it — so the whole card is parameterised by the five it
    keeps, and the production checks that rather than storing four fields. A
    printing whose numbers disagreed would be a different card, and taking any
    one of them as the answer would silently be the wrong one.

    Refuses without consuming, so a sentence merely opening "Each player …"
    keeps its own reading.
    """
    mark = stream.mark()

    def _count() -> int | None:
        """The next printed number, or None — a word that is not one leaves the
        cursor where it was for the caller's own reset."""
        try:
            amount = parse_amount(stream)
        except GrammarError:
            return None
        return amount.value if isinstance(amount, ast.Fixed) else None

    if not stream.accept_phrase("each", "player", "who", "controls"):
        stream.reset(mark)
        return None
    over = _count()
    if over is None or not stream.accept_phrase("or", "more", "lands"):
        stream.reset(mark)
        return None
    if not stream.accept_word("chooses"):
        stream.reset(mark)
        return None
    keep = _count()
    if keep is None or not stream.accept_phrase(
        "lands", "they", "control", "and", "sacrifices", "the", "rest"
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("each", "player", "who", "controls"):
        stream.reset(mark)
        return None
    under = _count()
    if under is None or not stream.accept_phrase("or", "fewer", "lands"):
        stream.reset(mark)
        return None
    # Every word of the second sentence is required rather than skipped, and
    # each names something the handler does: the offer ("may"), whose library,
    # the ceiling ("up to"), what may be found and where it lands. A production
    # that shrugged at one of them would let the same words mean a mandatory
    # search, a search of somebody else's library, or lands put into a hand.
    if not stream.accept_phrase(
        "may", "search", "their", "library", "for", "up", "to", "x", "basic",
        "land", "cards", "and", "put", "them", "onto", "the", "battlefield",
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("where", "x", "is"):
        stream.reset(mark)
        return None
    counted_to = _count()
    if counted_to is None or not stream.accept_phrase(
        "minus", "the", "number", "of", "lands", "they", "control"
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    # CR 701.23h ends a library search with a shuffle, so this sentence is the
    # tail of the search above rather than an effect of its own — consumed here
    # for the reason the conditional-shuffle tail is consumed inside the tutor
    # production, and required, because a printing without it would be claiming
    # a search that leaves a library ordered.
    if not stream.accept_phrase(
        "then", "each", "player", "who", "searched", "their", "library",
        "this", "way", "shuffles"
    ):
        stream.reset(mark)
        return None
    if (over, under, counted_to) != (keep + 1, keep - 1, keep):
        raise stream.error("this rebalancing's four numbers do not agree")
    return ast.RebalanceLands(keep)


def _parse_random_graveyard_card_fate(stream: TokenStream) -> ast.Statement | None:
    """``Reorder your graveyard at random. An opponent chooses a card at random
    in your graveyard. If it's a <type> card, put it onto the battlefield.
    Otherwise, exile it.`` (Search for Survivors.)

    Read whole: "it" is the card the random pick named and nothing else holds
    it, and the type test chooses between two moves of that one card. Every
    word is expected once the opener matches; refuses without consuming before.
    """
    mark = stream.mark()
    if not stream.accept_phrase("reorder", "your", "graveyard", "at", "random"):
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase(
        "an", "opponent", "chooses", "a", "card", "at", "random", "in", "your",
        "graveyard",
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("if", "it", "'s", "a"):
        raise stream.error("expected the type test on the randomly chosen card")
    card_type = _singular_type(stream.peek_word() or "")
    if card_type not in CARD_TYPES:
        raise stream.error("expected a card type in the random pick's test")
    stream.advance()
    stream.expect_word("card")
    stream.accept_punct(",")
    for word in ("put", "it", "onto", "the", "battlefield"):
        stream.expect_word(word)
    stream.accept_punct(".")
    stream.expect_word("otherwise")
    stream.accept_punct(",")
    stream.expect_word("exile")
    stream.expect_word("it")
    return ast.RandomGraveyardCardFate(card_type)
