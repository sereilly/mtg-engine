"""The object an *earlier step of the same effect* chose: "that creature".

Split out of ``references`` at Tempest's Phase 0, along the line that module's
own docstring already draws:

    "**The back-references came down here** the round ``phrases`` crossed the
    thousand-line guard, and on this module's own subject rather than a new
    one: 'that creature', 'those creatures', 'the other creature' and 'that
    Wall' all answer CR 115's question — what does this phrase point at — with
    the referent being *an earlier step of the same effect* instead of a choice
    a player makes."

That last clause is the seam, and it is the CR's own. What stays in
``references`` reads a phrase a **player** answers as the spell resolves — the
quantifier table (CR 115.1), the three player forms (CR 102), the recipient
union over them — where nothing here is answered by anybody: the trigger, or
the sentence in front of this one, already bound the object. Every production
below is a way English names an object that is *already chosen* — the bare
"that <type>", the plural "those <type>s", the older definite article, a
subtype ("that Wall"), the untyped "that permanent", and the two ordinals a
**pair** of bound objects is named by.

**It is the half that grows with the pool**, which is the playbook's tiebreak
when both halves of a split are productions. The quantifiers and the player
forms are closed vocabularies a set adds to once in five; a back-reference
gains a spelling whenever a card restates its own bound noun a new way — the
subtype arrived with Zirilan of the Claw, the untyped noun with Amber Prison,
the ordinals with Infinite Authority, the definite article with Glyph of
Delusion.

There is no mirror name to re-form. The ``that``/``those`` quantifiers are read
by eighteen lowering modules and owned by none, so no lowering family carries
this subject to rejoin — and ``rebinding``, further up this side, is the *other*
question: which object a bare "it" names, answered by a walk over the AST rather
than by a production. ``references`` re-exports every name defined here, so
``phrases`` and the effect families that read one are untouched — the
arrangement ``prices`` and ``readers`` already have further down.
"""

from __future__ import annotations

from . import ast
from .errors import GrammarError
from .nouns import parse_object_filter
from .stream import TokenStream
from .vocabulary import CARD_TYPES, CREATURE_TYPES, SUBTYPE_INDEX, match_longest


#: The two positions a printed *pair* of bound objects is named by. A trigger
#: that bound one object is referred to as "that creature"; one that bound two
#: — the halves of a block — names them by order, and the ordinal is the
#: quantifier rather than a word to skip. Each keeps its own, for the reason
#: "that" and "those" do: a lowering written for one must fail by name rather
#: than silently receive the other.


PAIR_ORDINALS = ("other", "first")


#: The two **combat roles** a printed sentence names a member of a combat pair
#: by: "the attacking creature", "the blocking creature" (No Quarter, Farrel's
#: Mantle). Beside :data:`PAIR_ORDINALS` because it is the same vocabulary
#: answering the same question — which of two bound objects does this phrase
#: point at — with the role printed instead of the position.
#:
#: A role is a **quantifier**, exactly as an ordinal is, and for that constant's
#: reason: nothing accepts one unless it says so, so a sentence naming a role no
#: event established fails *by name* rather than resolving to whatever object
#: happened to be at hand. That is not a hypothetical. Before Tempest's third
#: wave "the attacking creature" was read as the bare pronoun and "the blocking
#: creature" refused to parse at all — two halves of one vocabulary, one of them
#: answering, and answering with the **ability's own source**. No card printed
#: the pair, so nothing failed; No Quarter prints both, and would have destroyed
#: itself.
#:
#: ``rebinding.rebind_combat_role_to_event_subject`` is the one place a role
#: becomes an object, because the trigger event is the only thing that can say
#: whether the role was established at all.
COMBAT_ROLES = ("attacking", "blocking")


def accept_combat_role(stream: TokenStream) -> str | None:
    """``attacking`` / ``blocking`` at the cursor, consumed, or None."""
    word = stream.peek_word()
    if word in COMBAT_ROLES:
        stream.advance()
        return word
    return None


def _accept_pair_ordinal(stream: TokenStream) -> str | None:
    """``other`` / ``first`` at the cursor, consumed, or None."""
    word = stream.peek_word()
    if word in PAIR_ORDINALS:
        stream.advance()
        return word
    return None


def parse_pair_ordinal_subject(stream: TokenStream) -> "ast.TargetSpec | None":
    """``the other <card type>`` / ``the first <card type>``, or None.

    The ordinal half of :func:`parse_bound_subject`, reachable on its own
    because the productions that read a bound object do **not** share one
    reader: :func:`_parse_that_object` is reached only where a production calls
    it, never from the shared noun parser, so that "that creature" cannot leak
    into every line printing the phrase. (It lived in ``effects/board.py`` until
    the damage family needed it too; the copy left behind there shadowed this
    one for a round.) The ordinals are named in two families all the same (Infinite
    Authority destroys one member of the pair and puts a counter on the other),
    and a second spelling of them is how the two halves of one printed sentence
    would come to disagree about which creature they meant.
    """
    mark = stream.mark()
    if not stream.accept_word("the"):
        return None
    ordinal = _accept_pair_ordinal(stream)
    if ordinal is None:
        stream.reset(mark)
        return None
    noun = stream.peek_word()
    if noun is None or noun not in CARD_TYPES:
        # "Put a -1/-1 counter on **the other**." (Retribution.) The bare
        # ordinal, with the noun left to the sentence that named the pair —
        # which is the only place it could come from, since the pair is a set an
        # earlier sentence chose rather than anything this phrase describes.
        #
        # Admitted only at the end of its clause: "the other" followed by a word
        # this reader has no noun for is a phrase it has not understood, and
        # consuming two words of it would be the dropped-rider shape the
        # full-consumption rule exists to make loud.
        if stream.exhausted or stream.at_punct(".", ",", ";"):
            return ast.TargetSpec(ordinal, ast.ObjectFilter())
        stream.reset(mark)
        return None
    stream.advance()
    return ast.TargetSpec(ordinal, ast.ObjectFilter(card_types=(noun,)))


#: The two printed relative clauses that say *which* of an effect's own choices
#: a definite noun phrase names, and the quantifier each becomes.
#:
#: "If you win the flip, destroy **the creature you chose**. If you lose the
#: flip, destroy **the creature your opponent chose**." (Mogg Assassin.) A
#: sentence whose effect made two picks has two back-references, and English
#: distinguishes them by *who chose* — the same rule ``_accept_pair_ordinal``
#: above follows for a pair distinguished by position, and the same reason it is
#: the quantifier rather than a word to skip: nothing accepts either unless it
#: says so, so a lowering written for one must fail by name rather than receive
#: the other.
_CHOOSER_RELATIVES: dict[tuple[str, ...], str] = {
    ("you", "chose"): "chosen_by_you",
    ("your", "opponent", "chose"): "chosen_by_opponent",
}


def _accept_chooser_relative(stream: TokenStream) -> str | None:
    """The quantifier a trailing "you chose" / "your opponent chose" names.

    None with the cursor untouched when the noun phrase carries no such clause,
    which is every other card in the pool.
    """
    for words, quantifier in _CHOOSER_RELATIVES.items():
        mark = stream.mark()
        if stream.accept_phrase(*words):
            return quantifier
        stream.reset(mark)
    return None


def parse_bound_subject(stream: TokenStream) -> "ast.TargetSpec | None":
    """``that <card type>`` / ``those <card type>s``, or None if that is not
    what is at the cursor.

    The plural is a *different quantifier*, not the singular with a count: "that
    creature" is the one object the previous sentence chose and "those creatures"
    is however many it chose — which for an "up to N" may be two, one or none.
    Keeping them apart is what stops a lowering written for one bound object
    receiving a list.

    Both are refused by default everywhere, which is what makes reading them
    safe: no lowering accepts "that" or "those" unless it says so
    (``_is_target`` and ``_names_several_targets`` both answer False), so a
    sentence reaching one fails **by name** rather than failing to parse. A
    parse error would blame the subject for a missing production.

    Here rather than in ``statements.py``, where it began, because two families
    read it now: the sentence subject position, and the *object* position of
    "prevent all combat damage that would be dealt by **that creature** this
    turn" (Telekinesis). A fragment two families need is not an effect.
    """
    mark = stream.mark()
    if stream.accept_word("those"):
        noun = stream.peek_word()
        singular = noun[:-1] if noun and noun.endswith("s") else noun
        if singular is None or singular not in CARD_TYPES:
            stream.reset(mark)
            return None
        stream.advance()
        return ast.TargetSpec("those", ast.ObjectFilter(card_types=(singular,)))
    # "**The** creature gains …" (Glyph of Delusion) is the same back-reference
    # as "**that** creature", in the older templating that used the definite
    # article for it. One production for both, because the referent, the
    # quantifier and every lowering that accepts one are identical — and because
    # a sentence whose subject is a bare definite noun phrase has nothing else
    # it could mean: an effect that acts on "a creature" says so.
    if not stream.accept_word("that", "the"):
        return None
    # "…destroy **the other** creature … put a +1/+1 counter on **the first**
    # creature." (Infinite Authority.) A sentence under a trigger that bound a
    # *pair* of objects has two back-references rather than one, and English
    # names them by position — so the ordinal is the quantifier, not a word to
    # skip. Each gets its own, for the reason "that" and "those" have separate
    # ones: a lowering written for one of them must fail by name rather than
    # receive the other. Nothing accepts either unless it says so, and today
    # only the block-pair lowerings do.
    ordinal = _accept_pair_ordinal(stream)
    noun = stream.peek_word()
    if noun is None:
        stream.reset(mark)
        return None
    # "**That permanent** doesn't untap during its controller's untap step…"
    # (Amber Prison, after "Tap target artifact, creature, or land"). The
    # generic noun is the restatement with *no* narrowing in it, which is what
    # a sentence back-referencing a choice across three card types has to
    # print — "that artifact" would name one of them. It carries no card type
    # for exactly that reason, and a lowering that reads the field sees the
    # empty tuple the phrase means rather than a word it would have to test.
    #
    # Written on `phrases.parse_bound_subject` by one branch of this wave while
    # another moved the whole production down here; carried across the move at
    # integration, which is the hazard SET_PLAYBOOK names as "ours: nothing,
    # theirs: the whole block".
    if noun == "permanent":
        stream.advance()
        return ast.TargetSpec(
            _accept_chooser_relative(stream) or ordinal or "that",
            ast.ObjectFilter(),
        )
    if noun in CARD_TYPES:
        stream.advance()
        # "…destroy the creature **you chose**" — read after the noun, where
        # English puts it, and it wins over the ordinal for the reason both are
        # quantifiers at all: it is the more specific of the two, and no printed
        # card carries both.
        return ast.TargetSpec(
            _accept_chooser_relative(stream) or ordinal or "that",
            ast.ObjectFilter(card_types=(noun,)),
        )
    # "…**That Dragon** gains haste until end of turn." (Zirilan of the
    # Claw.) English names a back-reference by whatever noun distinguishes
    # it, and a *subtype* is as good a one as a card type — Zirilan's search
    # found a Dragon, so "that Dragon" is the same reference "that creature"
    # would have been on a card that searched for one.
    #
    # Read here rather than through the shared noun parser for that parser's
    # own reason, stated above: nothing accepts the ``that`` quantifier
    # unless it says so, which is what makes reading the phrase safe. The
    # narrowing rides the spec so a lowering can refuse one it cannot honour
    # rather than dropping the word.
    if noun in CREATURE_TYPES:
        stream.advance()
        return ast.TargetSpec(
            ordinal or "that", ast.ObjectFilter(subtypes=(noun,))
        )
    stream.reset(mark)
    return None


def _parse_that_object(stream: TokenStream) -> ast.TargetSpec | None:
    """``that <card type>`` — the object a trigger already named.

    Not a target: the trigger bound it when it fired, so nothing is chosen on
    resolution. It gets its own quantifier rather than being read as an ordinary
    noun phrase, so a lowering written for "target creature" can never receive
    it — the two reach completely different handlers, and the ones that take a
    bound object read it out of the trigger's context instead of the payload.

    A fragment two effect families ask for by name -- the board family's
    "destroy that land" and the damage family's "unless they sacrifice that
    artifact" -- so it lives here rather than in either of them. That is the
    *only* thing that changed when it moved: it is still reached only where a
    production calls it, never from the shared noun parser, because the phrase
    turns up all over the pool ("tap that creature", "that player discards")
    and letting `parse_recipient` claim it would lower every one of those lines
    through a filter naming a card type nobody bound.
    """
    # "destroy **the other** creature" (Infinite Authority) — the second member
    # of a pair the trigger bound, read through the shared ordinal production
    # so the counter clause in the same sentence names it the same way.
    ordinal = parse_pair_ordinal_subject(stream)
    if ordinal is not None:
        return ordinal
    # "destroy **the creature you chose**" / "**…your opponent chose**" (Mogg
    # Assassin) — the definite article plus the relative clause that says which
    # of this effect's own picks the words name, read through the same table the
    # subject position reads it through.
    #
    # The **whole phrase or nothing**: a bare "the creature" is the definite
    # back-reference ``parse_bound_subject`` handles and it means something else
    # entirely, so a partial match rewinds and this production declines, exactly
    # as ``parse_target_spec``'s spelled-out "any target" union does.
    mark = stream.mark()
    if stream.accept_word("the"):
        noun = stream.peek_word()
        if noun is not None and noun in CARD_TYPES:
            stream.advance()
            chosen = _accept_chooser_relative(stream)
            if chosen is not None:
                return ast.TargetSpec(
                    chosen, ast.ObjectFilter(card_types=(noun,))
                )
        stream.reset(mark)
    if not stream.accept_word("that"):
        return None
    noun = stream.peek_word()
    if noun is not None and noun in CARD_TYPES:
        stream.advance()
        return ast.TargetSpec("that", ast.ObjectFilter(card_types=(noun,)))
    # "destroy that **Wall**" (Battering Ram). A subtype names the bound object
    # just as a card type does — the trigger that fired required it, so the word
    # is describing what was bound rather than narrowing a fresh choice. Read
    # through the vocabulary, so a made-up noun still refuses.
    matched = match_longest(stream.words_from(), 0, SUBTYPE_INDEX)
    if matched is not None and matched[0] in CREATURE_TYPES:
        stream.advance(matched[1])
        return ast.TargetSpec(
            "that",
            ast.ObjectFilter(card_types=("creature",), subtypes=(matched[0],)),
        )
    # "destroy that **non-Wall** creature" (Acidic Dagger). The restated noun
    # phrase again, with the negation the trigger's own phrase carried — the
    # words describe the object that was bound rather than narrowing a fresh
    # choice, exactly as the subtype above does. Read through the noun parser so
    # every shape of phrase reaches one reader, and only where a card type ends
    # it: "that" followed by anything the noun parser cannot finish is not this.
    phrase = stream.mark()
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        described = None
    if described is not None and described.card_types:
        return ast.TargetSpec("that", described)
    stream.reset(phrase)
    stream.reset(mark)
    return None
