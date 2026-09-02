"""Small printed readers a noun phrase needs — and so does everything above it.

Below `nouns` rather than inside it, because these are the pieces `nouns` shares
*upward*: `conditions` reads a comparison ("power 3 or greater"), and `amounts`
and `conditions` both read a self-reference. Their home in the filter parser was
incidental — nothing about a comparison is about a filter — and keeping them
there is what made a module that shares two readers with two callers grow past
the guard while the readers themselves stayed still.

`nouns` re-exports them under the names it used, so its own body and every
caller of `nouns.parse_comparison` are untouched.

**The four leaf readers of a postmodifier came down here** the round
`postmodifiers` crossed the thousand-line guard, on that module's own stated
boundary rather than a new one: it says a postmodifier names a *relation*, and
these four read a seat, a keyword list or a zone owner and touch no filter and
no draft at all. Each already documented itself as living below `references`
"so the recursion can run one way" — which is the same argument for living
here, one layer further down, where nothing can recurse at all.
`postmodifiers` re-exports them under the names it used.
"""

from __future__ import annotations

from . import ast
from .lexer import SELF
from .stream import TokenStream
from .vocabulary import (CARD_TYPES, CREATURE_TYPES, KEYWORD_INDEX,
                         match_longest, singular as _singular)

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


def accept_source_reference_spec(stream: TokenStream):
    """The same reference, as the spec that says **which word was printed**.

    :func:`accept_source_reference` collapses the three spellings, which is
    right for a caller asking only about identity. A caller building a
    condition node needs one thing more: a bare "it" is a *pronoun*, and after
    a trigger whose condition named an object it means that object rather than
    the source (``rebinding.rebind_pronoun_to_event_subject``, which finds a
    pronoun by its quantifier). "This creature" and the card's own name are not
    pronouns and keep ``"this"``, so nothing rebinds them.

    Returns None with the cursor untouched when no reference was there.
    """
    if stream.at_word("it"):
        stream.advance()
        return ast.TargetSpec("it", ast.ObjectFilter(is_source=True))
    mark = stream.mark()
    if accept_source_reference(stream):
        return ast.TargetSpec("this", ast.ObjectFilter(is_source=True))
    stream.reset(mark)
    return None


def _accept_back_referenced_controller(stream: TokenStream) -> bool:
    """``that player|opponent [or that <type>'s controller] control[s]`` — True
    with the phrase consumed, or False with the cursor unmoved.

    One reader for both spellings, because they are one referent. Goblin Lyre
    targets "target opponent **or planeswalker**" (CR 115.4 without the creature
    half) and then counts "the number of creatures **that opponent or that
    planeswalker's controller** controls" — a seat either way, and the same seat
    the earlier sentence chose. So the disjunction is a *spelling* of
    `that_player`, the way `references.py` already reads Chain Lightning's "that
    player or that permanent's controller"; a kind of its own would be one
    card's private address for a referent every consumer already has.

    Read inline rather than through `parse_player_ref`: that reader is in
    `references`, two layers above this file, which sits below `nouns` so the
    recursion can run one way.
    """
    mark = stream.mark()
    if stream.accept_phrase("that", "player") or stream.accept_phrase(
        "that", "opponent"
    ):
        _accept_same_seat_disjunct(stream)
        if stream.accept_word("controls", "control"):
            return True
    stream.reset(mark)
    return False


def _accept_same_seat_disjunct(stream: TokenStream) -> None:
    """The optional ``or that <type>'s controller`` arm, consumed only when it
    really names the same seat as the arm in front of it.

    Any other "or" is left where it is, for whatever production reads a
    disjunction of two *different* things — consuming it here would silently
    merge them.
    """
    mark = stream.mark()
    if not stream.accept_word("or"):
        return
    if stream.accept_word("that", "this", "the"):
        noun = stream.peek_word()
        if noun is not None and _singular(noun) in CARD_TYPES:
            stream.advance()
            if stream.accept_phrase("'s", "controller"):
                return
    stream.reset(mark)


def _parse_keyword_list(stream: TokenStream) -> tuple[str, ...]:
    """Parse one or more keyword names ("flying", "first strike and trample").

    The conjunction is only consumed when a keyword actually follows it:
    "each creature without flying and each player" continues with a second
    *recipient*, not a second keyword, and eating that "and" would strand the
    rest of the clause.
    """
    keywords: list[str] = []
    while True:
        matched = match_longest(stream.words_from(), 0, KEYWORD_INDEX)
        if matched is None:
            break
        name, consumed = matched
        keywords.append(name)
        stream.advance(consumed)
        conjunction = stream.mark()
        if not (stream.accept_word("and") or stream.accept_word("or")):
            break
        if match_longest(stream.words_from(), 0, KEYWORD_INDEX) is None:
            stream.reset(conjunction)
            break
    if not keywords:
        raise stream.error("expected a keyword ability")
    return tuple(keywords)


def _parse_zone_owner_of(stream: TokenStream) -> "ast.PlayerRef | None":
    """The player named after "from the <zone> **of** …", or None.

    Its own small reader rather than a call into ``references.parse_player_ref``
    because that module sits *above* this one — it reads noun phrases, which are
    built from what this file parses — and the phrases printed in this position
    are not the ones a recipient clause prints. Widening it means adding a
    spelling here, and a spelling nothing lists refuses the whole noun phrase
    rather than silently naming some other player's graveyard.

    "…the graveyard of **the player who controlled that creature the last time
    it became blocked by that Wall**" (Glyph of Reincarnation) is a seat no read
    of the board can answer: control is CR 613 layer 2 and moves, and by the
    time the sentence is read the creature is a card in a graveyard with no
    controller at all. The block seam freezes the seat as the block happens, and
    this referent names that record — "the last time" being exactly the
    overwrite-on-each-block that seam performs. Every word is required, and the
    noun after "by that" is checked rather than skipped: a dropped word here
    leaves a phrase naming some other player, and a reanimation out of the wrong
    graveyard is a different card.
    """
    probe = stream.mark()
    if stream.accept_phrase(
        "the", "player", "who", "controlled", "that", "creature",
        "the", "last", "time", "it", "became", "blocked", "by", "that",
    ):
        noun = stream.peek_word()
        if noun is not None and (
            _singular(noun) in CARD_TYPES or _singular(noun) in CREATURE_TYPES
        ):
            stream.advance()
            return ast.PlayerRef("controller_when_blocked")
    stream.reset(probe)
    return None
