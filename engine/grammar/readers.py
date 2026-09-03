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
from .lexer import PT, SELF, WORD
from .stream import TokenStream
from .vocabulary import (CARD_TYPES, KEYWORD_INDEX, NUMBER_WORDS,
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


def _parse_entering_counters(stream: TokenStream) -> tuple[tuple[str, int], ...]:
    """``with two scream counters on it`` — counters an object carries into a zone.

    "Exile All Hallow's Eve **with two scream counters on it**." The counters
    are put on as part of the move (CR 121.2), so they are a property of the
    exiling rather than a second sentence, and reading them here is what stops
    the phrase being shed as unconsumed text — the whole card is those counters
    coming back off one per upkeep.

    The counter word and the number are both payload. Nothing about "scream"
    reaches this production: any word followed by "counter"/"counters" is a
    counter of that name (CR 122.1), which is the same open vocabulary
    ``engine/named_counters.py`` stores.

    Returns an empty tuple with the cursor untouched when the phrase is not
    there, so an exile that prints no counters is unaffected and a "with" this
    production cannot finish falls back to whatever else the line says.

    **Here rather than in `imperatives`**, where the exile production that first
    needed it lives. Sand Golem prints the same phrase after a *return* — "…to
    the battlefield **with a +1/+1 counter on it**" — and `effects/board.py`
    reads that sentence from below `imperatives` in the parse layering, so it
    cannot reach up for the reader. This module's own rule settles where it
    goes: a small printed reader shared upward, about no filter and no relation.
    One reader for the two verbs, because CR 121.2 puts the counters on as part
    of either move and a second copy is how the two come to read different
    words.
    """
    mark = stream.mark()
    if not stream.accept_word("with"):
        return ()
    if stream.accept_word("a", "an"):
        count = 1
    else:
        word = stream.peek_word()
        count = NUMBER_WORDS.get(word) if word is not None else None
        if count is None:
            stream.reset(mark)
            return ()
        stream.advance()
    # The counter's name, which is a **word** for a card-invented kind ("scream")
    # and a `PT` token for a CR 122.1a pair ("+1/+1", Sand Golem). Both are read
    # here rather than through `phrases._expect_counter_kind`, which this module
    # sits below: what the two spellings have in common is that they are the one
    # token in front of "counter", and telling them apart is the lexer's job
    # already done.
    token = stream.peek()
    if token is None or token.kind not in (WORD, PT):
        stream.reset(mark)
        return ()
    name = token.text
    if name in ("counter", "counters"):
        stream.reset(mark)
        return ()
    stream.advance()
    if not (stream.accept_word("counters") or stream.accept_word("counter")):
        stream.reset(mark)
        return ()
    # "on it" is required, not optional: the phrase names *which* object the
    # counters go on, and an exile that dropped it would be reading a sentence
    # nobody printed.
    if not stream.accept_phrase("on", "it"):
        stream.reset(mark)
        return ()
    return ((name, count),)
