"""What a **cast** trigger's clause narrows on.

Every production here reads one printed shape — "…casts a <colour> spell",
"…casts an <type> spell", "…you cast your first <type> spell each turn" — and
they are one family by the thing that makes a family here: they read the same
words in the same order and differ only in which narrowing the sentence hangs
on the verb. Split out of ``triggers`` at the thousand-line guard, along the
boundary that module already had in its own shape; the two helpers came with
them because the cast chain is their only caller.

The trigger *word* is a parameter rather than a literal. CR 603.1 makes "when"
and "whenever" one kind of ability — the difference is how often it triggers
while it exists, not what triggers it — and every fire site in this engine
reads the kind. Straw Golem is the card that proved the literal wrong: printed
"**When** an opponent casts a creature spell", it was refused while the same
clause one word longer was read.

Below ``triggers``, which imports it, and above ``nouns``, whose object parser
the unshared-colour clause reads. It reaches no word table ``triggers`` owns.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .errors import GrammarError
from .nouns import parse_object_filter
from .stream import TokenStream
from .vocabulary import (CARD_TYPES, COLOR_WORDS, CREATURE_TYPES,
                         IMPLEMENTED_KEYWORDS, ORDINAL_WORDS)
from .trigger_tables import _CAST_TYPE_FILTERS, _CAST_TYPE_UNIONS


_REFUSED = object()


def _accept_ordinal_exclusion(stream: TokenStream, type_word: str):
    """"…other than the **first** <type> spell that player casts each turn".

    The ordinal an opponent-cast trigger exempts, or None when no such clause
    is printed. The type word is repeated by the printed clause and must be the
    one already read: a card exempting a *different* type is not this trigger
    narrowed, it is a trigger this production cannot express, so it refuses.
    """
    mark = stream.mark()
    if not stream.accept_phrase("other", "than", "the"):
        stream.reset(mark)
        return None
    ordinal = stream.peek_word()
    if ordinal is None or ordinal not in ORDINAL_WORDS:
        stream.reset(mark)
        return _REFUSED
    stream.advance()
    if not stream.accept_phrase(
        type_word, "spell", "that", "player", "casts", "each", "turn"
    ):
        stream.reset(mark)
        return _REFUSED
    return ordinal


def _accept_unshared_colour(stream: TokenStream) -> ast.ObjectFilter | None:
    """``that doesn't share a color with <noun phrase>``, or None.

    CR 105.2's question asked of two objects at once. The set on the far side is
    read with the ordinary noun parser, so "a creature you control" needs no
    words of its own here and the next card comparing against something else
    gets the phrase for free.
    """
    mark = stream.mark()
    if stream.accept_phrase(
        "that", "doesn't", "share", "a", "color", "with"
    ):
        stream.accept_word("a", "an")
        try:
            return parse_object_filter(stream)
        except GrammarError:
            stream.reset(mark)
            return None
    stream.reset(mark)
    return None


def _accept_colour_union(stream: TokenStream) -> tuple[str, ...]:
    """The colour word or printed union at the cursor, or ``()``.

    "…casts a **blue** spell" (Leshrac's Sigil) and "…casts a **green or
    white** spell" (Putrefaction) are one narrowing over a set of colours
    (CR 105.2b), so one reader answers both rather than the union getting a
    branch that duplicates the single word's. Nothing is consumed when the
    cursor is not on a colour.

    The separators are the ones the pool prints — "or", and the comma list
    Quirion Dryad's clause reads one screen down — so a card naming three
    colours needs no words of its own here.
    """
    mark = stream.mark()
    colours: list[str] = []
    while True:
        word = stream.peek_word()
        if word not in COLOR_WORDS:
            break
        stream.advance()
        colours.append(COLOR_WORDS[word])
        joint = stream.mark()
        if stream.accept_punct(","):
            stream.accept_word("or")
            continue
        if stream.accept_word("or"):
            # A trailing "or" with no colour behind it is not this clause:
            # rewind to the last colour so the caller sees a clean union and
            # the word is left for whatever production reads it.
            if stream.peek_word() in COLOR_WORDS:
                continue
            stream.reset(joint)
        break
    if not colours:
        stream.reset(mark)
    return tuple(colours)


def _parse_cast_event(
    stream: TokenStream, trigger_word: str
) -> "ast.TriggerEvent | None":
    """The narrowed cast conditions, or None with the cursor where it started.

    Read **before** ``_WHENEVER_EVENTS``, whose bare "a player casts a spell" /
    "an opponent casts a spell" / "you cast a spell" entries are strict
    prefixes of every phrase here: matching one of those first would claim the
    shorter reading and strand the type word, which is the failure the whole
    trigger family orders longest-first to avoid.

    Every branch resets on refusal, so a clause this cannot read leaves the
    stream untouched for the productions behind it.
    """
    # "…casts a *blue* spell" (the Rod/Cup/Sphere cycle, Freyalise's Charm,
    # Leshrac's Sigil). The colour is part of the condition rather than a
    # per-card hook, which is what lets one dispatcher serve every card
    # written this way — and both printed scopes are read here for the
    # reason the type-word loop below reads both: a scope with no colour
    # reading is a card whose colour word strands the line, and the
    # narrowing itself is already one helper on the dispatch side.
    for scope, opener in (
        ("spell_cast", ("a", "player", "casts", "a")),
        ("opponent_casts_spell", ("an", "opponent", "casts", "a")),
    ):
        mark = stream.mark()
        if stream.accept_phrase(*opener):
            colours = _accept_colour_union(stream)
            if colours and stream.accept_word("spell"):
                return ast.TriggerEvent(
                    scope, trigger_word,
                    subject=ast.ObjectFilter(colors=colours),
                )
        stream.reset(mark)
    # "…casts an **artifact** spell" (Urza's Chalice, Citanul Druid). The
    # type narrowing beside the colour one above, and for the same reason:
    # one dispatcher for every card printed this way. Both scopes are read
    # here because both are printed, and the bare spellings in the phrase
    # table below are strict prefixes of these — so a table entry would
    # claim the shorter reading and strand the type word, which is the
    # failure this whole file orders longest-first to avoid.
    for scope, opener in (
        ("spell_cast", ("a", "player", "casts")),
        ("opponent_casts_spell", ("an", "opponent", "casts")),
    ):
        mark = stream.mark()
        if stream.accept_phrase(*opener) and (
            stream.accept_word("a") or stream.accept_word("an")
        ):
            type_word = stream.peek_word()
            # "…casts a **noncreature** spell" (Mystic Remora). The negated
            # spellings are not card types, so they live in the same table
            # the "you cast" productions below read — asked first, because
            # a scope that knew only `CARD_TYPES` refused the printed word
            # and took the whole line with it. `CARD_TYPES` still answers
            # for the words that table does not carry ("enchantment",
            # "land"), which is why both are consulted rather than one.
            narrowed = _CAST_TYPE_FILTERS.get(type_word or "")
            if narrowed is None and type_word in CARD_TYPES:
                narrowed = ast.ObjectFilter(card_types=(type_word,))
            if narrowed is not None:
                stream.advance()
                if stream.accept_word("spell"):
                    # "…**that doesn't share a color with a creature you
                    # control**" (Invoke Prejudice). A narrowing that
                    # compares the cast spell's colours against a set of
                    # *permanents*, so what follows is a whole noun phrase
                    # naming a different object than the one the trigger
                    # fires on — which is why it rides `narrowings` rather
                    # than the subject. Optional, because the bare form
                    # above is a real card (Citanul Druid); the words are
                    # consumed either way, or the line fails the
                    # full-consumption invariant.
                    # "…casts a creature spell **with flying**" (Hidden
                    # Spider). A narrowing on an ability of the spell rather
                    # than on its type line, read here so the words are
                    # consumed — left to the effect parser they fail the line,
                    # which is where the Spider stopped. Checked against the
                    # implemented keywords rather than any word, so "a creature
                    # spell with an activated ability" keeps refusing instead
                    # of compiling a trigger that fires on every creature.
                    keyword_mark = stream.mark()
                    if stream.accept_word("with"):
                        keyword = stream.peek_word()
                        if keyword is not None and keyword in IMPLEMENTED_KEYWORDS:
                            stream.advance()
                            narrowed = dataclasses.replace(
                                narrowed, with_keywords=(keyword,)
                            )
                        else:
                            stream.reset(keyword_mark)
                    unshared = _accept_unshared_colour(stream)
                    # "…**other than the first <type> spell that player
                    # casts each turn**" (Ichneumon Druid). The ordinal
                    # exclusion, read here so the words are consumed —
                    # left to the effect parser they would fail the line,
                    # and skipped they would be a narrowing this front end
                    # dropped while the other kept it.
                    # The clause is *consumed* and not carried: the
                    # condition — this narrowing included — comes from
                    # `engine/oracle.py`'s table, and this side only has to
                    # read the whole line rather than choke on it. The same
                    # split the "if it wasn't sacrificed" qualifier makes
                    # below. A clause it cannot read refuses the line, so
                    # the two front ends cannot end up watching different
                    # sets.
                    if _accept_ordinal_exclusion(stream, type_word) is _REFUSED:
                        stream.reset(mark)
                        break
                    return ast.TriggerEvent(
                        scope, trigger_word,
                        subject=narrowed,
                        narrowings=(
                            () if unshared is None
                            else (("unshared_color", unshared),)
                        ),
                    )
        stream.reset(mark)
    # "…you cast a spell that's white, blue, black, or red" (Quirion
    # Dryad): a colour-list narrowing of you_cast_spell. Read before the
    # phrase table, whose bare "you cast a spell" entry is its prefix.
    mark = stream.mark()
    if stream.accept_phrase("you", "cast", "a", "spell", "that", "'s"):
        colors: list[str] = []
        while True:
            word = stream.peek_word()
            if word not in COLOR_WORDS:
                break
            stream.advance()
            colors.append(COLOR_WORDS[word])
            if stream.accept_punct(","):
                stream.accept_word("or")
                continue
            if stream.accept_word("or"):
                continue
            break
        if len(colors) >= 2:
            return ast.TriggerEvent(
                "you_cast_spell", trigger_word,
                subject=ast.ObjectFilter(colors=tuple(colors)),
            )
    stream.reset(mark)
    # "…you cast a noncreature spell" (Spellgorger Weird): a type
    # narrowing of the same condition. The word list mirrors the oracle
    # table's — only what the cast filter tests may be consumed, so a
    # subtype word ("Dog spell") keeps refusing the line rather than
    # compiling a trigger that fires on every spell. Read before the
    # phrase table, whose bare "you cast a spell" entry is its prefix.
    # "Whenever you cast **your first** instant or sorcery spell **each
    # turn**" (Double Vision). An ordinal: the trigger fires on the first
    # such spell of the turn and on no other, so the count is part of the
    # condition rather than of the effect. Read before the bare forms, whose
    # phrases are its strict prefixes.
    mark = stream.mark()
    if stream.accept_phrase("you", "cast", "your", "first"):
        for phrase, narrowed in _CAST_TYPE_UNIONS:
            if stream.accept_phrase(*phrase):
                if stream.accept_phrase("spell", "each", "turn"):
                    return ast.TriggerEvent(
                        "you_cast_first_spell_each_turn", trigger_word,
                        subject=narrowed,
                    )
                break
        word = stream.peek_word()
        narrowed = _CAST_TYPE_FILTERS.get(word or "")
        if narrowed is not None:
            stream.advance()
            if stream.accept_phrase("spell", "each", "turn"):
                return ast.TriggerEvent(
                    "you_cast_first_spell_each_turn", trigger_word,
                    subject=narrowed,
                )
    stream.reset(mark)
    mark = stream.mark()
    if stream.accept_phrase("you", "cast", "an"):
        for phrase, narrowed in _CAST_TYPE_UNIONS:
            if stream.accept_phrase(*phrase) and stream.accept_word("spell"):
                return ast.TriggerEvent(
                    "you_cast_spell", trigger_word, subject=narrowed,
                )
    stream.reset(mark)
    mark = stream.mark()
    if stream.accept_phrase("you", "cast", "a"):
        word = stream.peek_word()
        narrowed = _CAST_TYPE_FILTERS.get(word or "")
        if narrowed is not None:
            stream.advance()
            if stream.accept_word("spell"):
                return ast.TriggerEvent(
                    "you_cast_spell", trigger_word, subject=narrowed,
                )
        # "…you cast a **Dog** spell" (Rin and Seri, Inseparable). A
        # creature subtype, which this production refused until the cast
        # filter learned to test one. Read from the vocabulary rather than a
        # literal list, and *after* the type words above so a card type
        # keeps its own narrowing — "creature" is both a type word and, in
        # no set, a subtype, but the ordering is what guarantees it.
        if word in CREATURE_TYPES:
            stream.advance()
            if stream.accept_word("spell"):
                return ast.TriggerEvent(
                    "you_cast_spell", trigger_word,
                    subject=ast.ObjectFilter(subtypes=(word,)),
                )
    stream.reset(mark)
    return None
