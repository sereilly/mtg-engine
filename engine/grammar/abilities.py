"""What a printed phrase says about an **ability on the stack** (CR 113.7a).

Its own module, below `nouns`, because an ability on the stack shares no
vocabulary with the filter parser above it: it has no card, no type line and no
permanent behind it, so every adjective `parse_object_filter` collects would be
a question with no object to ask it of. `nouns` returns the moment one of these
matches, for exactly that reason.

Split out when `nouns` reached the thousand-line guard a second time — the same
cut `names` made, and the same test: what does this production share with the
one beside it? Nothing here reads a filter, and nothing in the filter parser
reads an ability.
"""

from __future__ import annotations

from .stream import TokenStream
from .vocabulary import CARD_TYPES, singular

#: The printed kinds of ability a spell may name on the stack, longest first so
#: "activated or triggered" is read whole rather than as its first half.
_ABILITY_KIND_PHRASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("activated", "or", "triggered"), ("activated", "triggered")),
    (("triggered", "or", "activated"), ("activated", "triggered")),
    (("activated",), ("activated",)),
    (("triggered",), ("triggered",)),
)


def _accept_ability_noun(stream: TokenStream) -> tuple[str, ...]:
    """The ability kinds a phrase like "activated or triggered ability" names,
    or () when the cursor is not at one.

    The word "ability" is required. Without it "triggered" is an adjective
    looking for a noun and the phrase is somebody else's — and a phrase that
    consumed "activated" and then found no "ability" would have eaten a word
    the rest of the parse needs.
    """
    for phrase, kinds in _ABILITY_KIND_PHRASES:
        mark = stream.mark()
        if not stream.accept_phrase(*phrase):
            stream.reset(mark)
            continue
        if stream.accept_word("ability", "abilities"):
            return kinds
        stream.reset(mark)
    return ()


def _accept_ability_source(stream: TokenStream) -> tuple[str, ...]:
    """``from an <card type> source`` after an ability noun, or () if absent.

    The one adjective an ability on the stack can carry: it has no card and no
    type line (CR 113.7a), so "artifact" here describes the *permanent the
    ability came from*, not the ability. Consumed here rather than by the
    adjective loop below for the same reason the ability noun returns early —
    that loop asks questions of a card.

    A word that is not a card type leaves the cursor where it was, so the line
    fails full-token consumption and the card falls back, rather than the
    narrowing being dropped and the counter reaching every ability.
    """
    mark = stream.mark()
    if not stream.accept_word("from"):
        stream.reset(mark)
        return ()
    stream.accept_word("a", "an")
    word = stream.peek_word()
    if word is None or singular(word) not in CARD_TYPES:
        stream.reset(mark)
        return ()
    stream.advance()
    types = [singular(word)]
    # "…from an **artifact, creature, enchantment, or land**" (Interdict). A
    # list of the types the source may have, and the list is what ends the
    # phrase: Interdict prints no "source" after it, where the one-type
    # spelling (Rust, Brown Ouphe) always does. Read as an alternation rather
    # than as four productions because the permanent is one permanent and the
    # types are alternatives about it — the payload is already a tuple the
    # handler asks `any` of.
    while True:
        item = stream.mark()
        if not (stream.accept_punct(",") or stream.at_word("or")):
            break
        stream.accept_word("or")
        stream.accept_word("a", "an")
        following = stream.peek_word()
        if following is None or singular(following) not in CARD_TYPES:
            stream.reset(item)
            break
        stream.advance()
        types.append(singular(following))
    # The trailing noun is required of the **one-type** spelling and only of it.
    # A bare "from an artifact" with nothing after it is a phrase this reader
    # cannot tell from the opening of a longer clause, so it keeps refusing;
    # a list of two or more has already said where it ends.
    if not stream.accept_word("source") and len(types) < 2:
        stream.reset(mark)
        return ()
    return tuple(types)
