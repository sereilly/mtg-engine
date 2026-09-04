"""Printed paragraphs that change a card's **owner** (CR 108.3).

Split out of ``paragraphs.py`` at Mirage's third wave, when Natural Balance's
paragraph took that module past the thousand-line guard. The seam is the one
the three cards here already share and no other paragraph touches: Bronze
Tablet, Timmerian Fiends and Tempest Efreet each end with a card belonging to
somebody else, permanently. CR 108.3 makes ownership fixed for the whole game
and the ante rules (CR 407) are where the exception lives, which is why these
are the only three paragraphs in the pool that can be about it — and why they
are a family rather than three cards filed together.

Juxtapose stayed behind on purpose. It reads the same way, sentence for
sentence, and exchanges **control** (CR 613 layer 2) rather than ownership —
which is a different rule, a different duration and a different engine module.
Two paragraphs that look alike are not a family; what they change is.

The name is not a mirror re-forming, and that is stated rather than glossed
over. These three lower in ``lowering/zones.py``, so ``zones`` is the name the
rule would ask for — but ``engine/grammar/zones.py`` already exists on this side
of the package and means something else (which zone an object is *already* in),
so reusing it would fork a name rather than re-form one. ``ownership`` is what
CR 108.3 calls the thing, and nothing on either side is called that today.

**Nothing here calls back into the sentence parser**, which is ``paragraphs.py``'s
own rule and the reason both modules sit below ``statements.py``: each
production reads its own words to the end.
"""

from __future__ import annotations

from . import ast
from .errors import GrammarError
from .lexer import SELF
from .nouns import parse_object_filter
from .stream import TokenStream
from .vocabulary import CARD_TYPES


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
def _parse_ante_offer_ownership_exchange(
    stream: TokenStream,
) -> ast.Statement | None:
    """Timmerian Fiends' whole ability, as one statement.

    ``The owner of target <type> may ante the top card of their library. If
    that player doesn't, exchange ownership of that <type> and this permanent.
    Put the <type> card into your graveyard and this permanent from anywhere
    into that player's graveyard. This change in ownership is permanent.``

    The sibling of :func:`_parse_random_reveal_ownership_exchange` below, and
    every sentence is required for that production's reasons: without the offer
    the exchange is unconditional, without the two moves the exchange has no
    effect this engine can see, and without the last sentence the change would
    be an ordinary until-end-of-turn one.

    The printed **type** is payload and is required to be the same word in all
    three places it appears. A paragraph that says "target artifact" and then
    "put the creature card into your graveyard" is not describing one object,
    and reading it as though it were would bin something the card never named.

    Refuses without consuming, so every other sentence opening "The owner of …"
    keeps the reading it has today.
    """
    mark = stream.mark()
    if not stream.accept_phrase("the", "owner", "of", "target"):
        stream.reset(mark)
        return None
    type_word = stream.peek_word()
    if type_word is None or type_word not in CARD_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase(
        "may", "ante", "the", "top", "card", "of", "their", "library"
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("if", "that", "player", "doesn't"):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if (
        not stream.accept_phrase("exchange", "ownership", "of", "that", type_word)
        or not stream.accept_word("and")
        or stream.accept_kind(SELF) is None
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase(
        "put", "the", type_word, "card", "into", "your", "graveyard", "and"
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
    return ast.AnteOfferOwnershipExchange(type_word)


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
