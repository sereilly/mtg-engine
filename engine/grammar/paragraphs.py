"""Printed paragraphs that are one effect.

Every production here reads *several sentences* and returns a single statement,
because on these cards the sentences are not effects that happen to follow one
another. Necromentia's three name one card and then strip it from four zones;
Idol of Endurance's exile records the pile its other ability casts from;
Tawnos's Coffin notes counters nothing else would read and gives them back;
Transmute Artifact compares two objects neither of which exists until a choice
has been made. Parsed sentence by sentence, each of these would produce one
statement that does something and several that have nothing to read.

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
from .amounts import expect_pt, parse_amount
from .errors import GrammarError
from .lexer import (MANA, SELF)
from .nouns import parse_object_filter
from .references import parse_player_ref, parse_recipient
from .stream import TokenStream
from .vocabulary import CARD_TYPES, COLOR_WORDS, CREATURE_TYPES


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


def _parse_ownership_exchange_unless_paid(stream: TokenStream) -> ast.Statement | None:
    """Bronze Tablet's whole ability, as one statement.

    ``Exile this <noun> and target <phrase>. That player may pay <N> life. If
    they do, put this card into its owner's graveyard. Otherwise, that player
    owns this card and you own the other exiled card.``

    Every sentence is required and each one is load-bearing: without the exile
    there is nothing to exchange, without the payment the exchange is
    unconditional, and without *both* branches the card either always trades or
    never does. The life total and the target's noun phrase are payload.
    """
    if not stream.accept_phrase("exile", "this"):
        return None
    if stream.accept_kind(SELF) is None:
        if not stream.accept_word(
            "artifact", "creature", "enchantment", "permanent", "land"
        ):
            return None
    if not stream.accept_phrase("and", "target"):
        return None
    try:
        target = parse_object_filter(stream)
    except GrammarError:
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("that", "player", "may", "pay"):
        return None
    token = stream.peek()
    if token is None or not str(token.text).isdigit():
        return None
    life = int(token.text)
    stream.advance()
    if not stream.accept_word("life"):
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("if", "they", "do"):
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "put", "this", "card", "into", "its", "owner", "'s", "graveyard",
    ):
        return None
    stream.accept_punct(".")
    if not stream.accept_word("otherwise"):
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "that", "player", "owns", "this", "card", "and",
        "you", "own", "the", "other", "exiled", "card",
    ):
        return None
    return ast.OwnershipExchangeUnlessPaid(life, target)


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


def _parse_cast_from_exiled_with(stream: TokenStream) -> ast.Statement | None:
    """``Until end of turn, you may cast a <filter> spell from among cards
    exiled with this <permanent> without paying its mana cost.``
    (Idol of Endurance.)

    The cost waiver is required: without it the permission is a different one
    and strictly weaker, and a card that dropped the words would be cheaper to
    misread than to notice.
    """
    if not stream.accept_phrase("until", "end", "of", "turn"):
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("you", "may", "cast", "a"):
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        return None
    # ``parse_object_filter`` reads "creature spell" whole, marking the zone as
    # the stack. Requiring the word back would be asking it twice; requiring the
    # *zone* is what actually distinguishes "cast a creature spell" from a card
    # filter that would name some other zone.
    if filt.zone != "stack":
        return None
    if not stream.accept_phrase("from", "among", "cards", "exiled", "with", "this"):
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
    if not stream.accept_phrase(
        "without", "paying", "its", "mana", "cost",
    ):
        return None
    return ast.CastFromExiledWith(filt)


def _parse_name_and_strip(stream: TokenStream) -> ast.Statement:
    """Necromentia's whole three-sentence effect.

    Every word is required. The zone list is what the search reaches and the
    token clause names which of those zones the count comes from — "each card
    exiled from their **hand** this way" is a strict subset of what was exiled,
    and a card counting the whole pile would make far more Zombies.

    "other than a basic land card name" is consumed and *honoured*: it is the
    one restriction on the choice, and a name it forbids has to be refused where
    the choice is made rather than dropped here.
    """
    for word in ("choose", "a", "card", "name", "other", "than", "a", "basic",
                 "land", "card", "name"):
        stream.expect_word(word)
    if not stream.accept_punct("."):
        raise stream.error("expected the search sentence after the choice")
    for word in ("search", "target", "opponent", "'s"):
        stream.expect_word(word)
    zones: list[str] = []
    while True:
        word = stream.peek_word()
        if word not in ("graveyard", "hand", "library"):
            break
        stream.advance()
        zones.append(word)
        if stream.accept_punct(","):
            stream.accept_word("and")
            continue
        if stream.accept_word("and"):
            continue
        break
    if len(zones) < 2:
        raise stream.error("expected the zones the search reaches")
    for word in ("for", "any", "number", "of", "cards", "with", "that", "name",
                 "and", "exile", "them"):
        stream.expect_word(word)
    if not stream.accept_punct("."):
        raise stream.error("expected the shuffle sentence after the search")
    for word in ("that", "player", "shuffles"):
        stream.expect_word(word)
    stream.accept_punct(",")
    for word in ("then", "creates", "a"):
        stream.expect_word(word)
    power, _, toughness, _ = expect_pt(stream)
    colors: list[str] = []
    while (word := stream.peek_word()) in COLOR_WORDS:
        colors.append(COLOR_WORDS[word])
        stream.advance()
    subtypes: list[str] = []
    while (word := stream.peek_word()) and word in CREATURE_TYPES:
        subtypes.append(word)
        stream.advance()
    for word in ("creature", "token", "for", "each", "card", "exiled", "from", "their"):
        stream.expect_word(word)
    token_zone = stream.peek_word()
    if token_zone not in ("hand", "graveyard", "library"):
        raise stream.error("expected the zone the token count comes from")
    stream.advance()
    for word in ("this", "way"):
        stream.expect_word(word)
    if not (isinstance(power, ast.Fixed) and isinstance(toughness, ast.Fixed)):
        raise stream.error("the token's printed power/toughness is a number")
    return ast.NameAndStrip(
        zones=tuple(zones), token_zone=token_zone,
        token_power=power.value, token_toughness=toughness.value,
        token_colors=tuple(colors), token_subtypes=tuple(subtypes),
    )


#: Where a revealed card may be printed to go. A closed list because each of
#: these is a zone the mover below actually knows how to reach; a word outside
#: it refuses the line rather than lowering onto a destination nothing moves to.
_REVEAL_DESTINATIONS: tuple[str, ...] = ("hand", "graveyard")

#: The hidden zones a "reveals N cards at random from their <zone>" clause may
#: name. A *list* rather than the word "hand" spelled into the production: the
#: randomness is only meaningful over a zone whose contents are hidden, and the
#: two of those are what this names.
_RANDOM_REVEAL_ZONES: tuple[str, ...] = ("hand", "library")


def _parse_name_then_random_reveal(stream: TokenStream) -> "ast.Statement | None":
    """Nebuchadnezzar's whole three-sentence effect.

    ``Choose a card name. Target opponent reveals X cards at random from their
    hand. Then that player discards all cards with that name revealed this
    way.``

    Refuses without consuming, so every other sentence opening with "choose"
    keeps the reading it has — Necromentia's naming paragraph is tried after
    this one and its first sentence differs from the fourth word on.

    "**revealed this way**" is read and is the whole reason the three sentences
    are one production: it narrows the discard to the cards the random reveal
    turned up, where a discard of "all cards with that name" would take every
    copy in the hand and make the randomness decoration.
    """
    mark = stream.mark()
    for word in ("choose", "a", "card", "name"):
        if not stream.accept_word(word):
            stream.reset(mark)
            return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    who = parse_player_ref(stream)
    if who is None or who.kind != "target_opponent":
        stream.reset(mark)
        return None
    if not stream.accept_word("reveals"):
        stream.reset(mark)
        return None
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    for word in ("cards", "at", "random", "from", "their"):
        if not stream.accept_word(word):
            stream.reset(mark)
            return None
    zone = stream.peek_word()
    if zone not in _RANDOM_REVEAL_ZONES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    for word in ("then", "that", "player", "discards", "all", "cards", "with",
                 "that", "name", "revealed", "this", "way"):
        if not stream.accept_word(word):
            stream.reset(mark)
            return None
    return ast.NameAndRandomReveal(who, count, zone)


def _parse_name_then_reveal_top(
    stream: TokenStream, who: ast.PlayerRef
) -> ast.Statement:
    """Petra Sphinx's whole three-sentence guess.

    The subject has already been read — "target player" — so this starts at the
    verb and reads to the end of the third sentence. Every word is required,
    and the two destinations are the only things that vary: "into their hand"
    on a hit and "into their graveyard" on a miss are read where they are
    printed rather than assumed, because the same guess with the miss going to
    the bottom of the library is a card this production should read too.

    "If it doesn't" is consumed rather than treated as decoration. It is the
    *complement* of the sentence before it, so nothing here has to model a
    second condition — but a line that omits it is a card whose miss does
    nothing, and dropping the words would make the two indistinguishable.
    """
    for word in ("chooses", "a", "card", "name"):
        stream.expect_word(word)
    if not stream.accept_punct(","):
        raise stream.error("expected the comma before the reveal")
    for word in ("then", "reveals", "the", "top", "card", "of", "their", "library"):
        stream.expect_word(word)
    if not stream.accept_punct("."):
        raise stream.error("expected the hit sentence after the reveal")
    for word in ("if", "that", "card", "has", "the", "chosen", "name"):
        stream.expect_word(word)
    if not stream.accept_punct(","):
        raise stream.error("expected the comma before the hit's destination")
    for word in ("that", "player", "puts", "it", "into", "their"):
        stream.expect_word(word)
    match_zone = stream.peek_word()
    if match_zone not in _REVEAL_DESTINATIONS:
        raise stream.error("expected the zone a matching card goes to")
    stream.advance()
    if not stream.accept_punct("."):
        raise stream.error("expected the miss sentence after the hit")
    for word in ("if", "it", "doesn't"):
        stream.expect_word(word)
    if not stream.accept_punct(","):
        raise stream.error("expected the comma before the miss's destination")
    for word in ("the", "player", "puts", "it", "into", "their"):
        stream.expect_word(word)
    miss_zone = stream.peek_word()
    if miss_zone not in _REVEAL_DESTINATIONS:
        raise stream.error("expected the zone a non-matching card goes to")
    stream.advance()
    return ast.NameThenRevealTop(who, match_zone, miss_zone)


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


def _parse_random_reveal_ownership_exchange(
    stream: TokenStream,
) -> ast.Statement | None:
    """Tempest Efreet's whole ability, as one statement.

    ``Target opponent may pay <N> life. If that player doesn't, they reveal a
    card at random from their hand. Exchange ownership of the revealed card and
    this creature. Put the revealed card into your hand and this creature from
    anywhere into that player's graveyard. This change in ownership is
    permanent.``

    Every sentence is required. Without the payment the exchange is
    unconditional; without the reveal there is no card to exchange; without the
    two moves the exchange has no effect this engine can see, since ownership
    *is* which player's zone a card is in; and without the last sentence the
    change would be an ordinary until-end-of-turn one. The life total is
    payload.

    Refuses without consuming, so every other sentence opening "Target
    opponent …" keeps the reading it has today.
    """
    mark = stream.mark()
    if not stream.accept_phrase("target", "opponent", "may", "pay"):
        stream.reset(mark)
        return None
    token = stream.peek()
    if token is None or not str(token.text).isdigit():
        stream.reset(mark)
        return None
    life = int(token.text)
    stream.advance()
    if not stream.accept_word("life"):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("if", "that", "player", "doesn't"):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "they", "reveal", "a", "card", "at", "random", "from", "their", "hand"
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase(
        "exchange", "ownership", "of", "the", "revealed", "card", "and"
    ) or stream.accept_kind(SELF) is None:
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase(
        "put", "the", "revealed", "card", "into", "your", "hand", "and"
    ) or stream.accept_kind(SELF) is None:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "from", "anywhere", "into", "that", "player", "'s", "graveyard"
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase(
        "this", "change", "in", "ownership", "is", "permanent"
    ):
        stream.reset(mark)
        return None
    return ast.RandomRevealOwnershipExchange(life)
