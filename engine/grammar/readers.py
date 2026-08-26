"""Small printed readers a noun phrase needs — and so does everything above it.

Below `nouns` rather than inside it, because these are the pieces `nouns` shares
*upward*: `conditions` reads a comparison ("power 3 or greater"), and `amounts`
and `conditions` both read a self-reference. Their home in the filter parser was
incidental — nothing about a comparison is about a filter — and keeping them
there is what made a module that shares two readers with two callers grow past
the guard while the readers themselves stayed still.

`nouns` re-exports them under the names it used, so its own body and every
caller of `nouns.parse_comparison` are untouched.
"""

from __future__ import annotations

from . import ast
from .lexer import NUMBER, SELF
from .stream import TokenStream
from .vocabulary import singular as _singular

# "this <self-word>" refers to the ability's own source.
_SELF_NOUNS = frozenset({
    "creature", "artifact", "enchantment", "land", "permanent", "spell", "aura", "card",
    # "Sacrifice this **token**" — modern templating for a token's own printed
    # ability (the Treasure token). Not a card type: it is what the object is,
    # exactly as "this permanent" is, and it names the same source.
    "token",
    # "Sacrifice this **Equipment**" / "put a soul counter on this Equipment"
    # (Malefic Scythe). An Equipment subtype used as the card's own noun, the
    # same way "this Aura" already is above.
    "equipment",
})




def accept_source_reference(stream: TokenStream) -> bool:
    """Consume a reference to the ability's own source — "it", "this", or
    "this <noun the card calls itself>" — and say whether one was there.

    A predicate rather than a filter, because the callers that need it are
    asking about *identity* and not about characteristics: an intervening-if
    naming the source is answered from ``context.source_permanent``, so an
    ``ObjectFilter`` built here would carry a narrowing nothing consults. The
    three spellings are one production so a card printing "this artifact" is
    read the same way as one printing "it", which is the whole difference
    between Mana Vault's draw-step clause and Basalt Monolith's.
    """
    if stream.accept_word("it"):
        return True
    # The card naming itself ("blocked by Sentinel") — the lexer has already
    # collapsed the name to one SELF token, so this spelling and "this
    # creature" are the same reference here as everywhere else.
    token = stream.peek()
    if token is not None and token.kind == SELF:
        stream.advance()
        return True
    mark = stream.mark()
    if stream.accept_word("this"):
        noun = stream.peek_word()
        if noun is not None and _singular(noun) in _SELF_NOUNS:
            stream.advance()
        return True
    stream.reset(mark)
    return False


