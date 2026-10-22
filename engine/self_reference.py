"""What a card may call itself by (CR 201.5).

Text that names the object it is on means *that* object, and pre-modern
templating writes that name out where modern templating writes "this creature".
The lexer already collapses the printed name into one ``SELF`` token, and
:func:`_collapse_self_references` below collapses it into the words "this
creature" for the text-keyed rule tables — two readers, one question.

A legendary card is also referred to by a **shortened** name: "Ugin, the Spirit
Dragon" says "Ugin", and "Rasputin Dreamweaver" says "Rasputin". The comma form
both readers already knew; the no-comma form is the one that left five of
Rasputin's six printed lines refusing at their first word.

Why the shortened name is expanded into the full one *here*, in the text, rather
than taught to each reader: there are two readers of a card's lines that see a
name at all, and several more (``engine/enter_effects.py``,
``engine/combat_restrictions.py``, the counter cap beside them) that see the
compiler's stored text and no name whatsoever. Rewriting the text once, in the
rewrite pass every reader of a card's lines already starts from
(``oracle.expand_ability_lines``), is what keeps the gate and the runtime tables
reading the same sentence — the alternative was a ``legendary`` flag threaded
through some thirty signatures, most of which would have carried it only to hand
it on.

**Why the shortening is not just "the first word".** It is the first word *of a
legendary card*, and not one that could be a word about the game. Two probes
over the whole pool say why. Without the legendary test, Black Ward's
"protection from black" collapses its own colour into a self-reference and Mana
Flare loses the word "mana". With it, "The Tabernacle at Pendrell Vale" would
still shorten to "the" — an article, which is a word about something other than
the card. So the first word has to read as a name and nothing else: not an
article, and not a word the game uses to describe objects, which is what the
vocabulary test below asks.

No card in the pool needs that second clause today; it is there for the set that
prints a legend whose first word is a creature type, and
``tests/engine/test_self_reference.py`` ratchets the three cards the rule does
rewrite, so such a set arrives as a failing test to read rather than as a card
quietly talking about itself.
"""

from __future__ import annotations

import re

from .grammar.vocabulary import CREATURE_TYPES
from .line_normalization import normalize_creature_line

#: Words a shortened name may not be. An article opens a noun phrase and a
#: vocabulary word describes objects, so either one standing alone in a card's
#: text is about something other than the card.
_ARTICLES = frozenset({"the", "a", "an"})


def short_self_name(card_name: str | None, *, legendary: bool) -> str | None:
    """The shortened name *card_name* may refer to itself by, or None.

    Only the no-comma form. A name with a comma is shortened at the comma, and
    both readers of a self-reference have always done that themselves — a second
    answer here would be a second copy of a rule that is already right.
    """
    if not legendary or not card_name:
        return None
    name = card_name.strip()
    if "," in name:
        return None
    words = name.split()
    if len(words) < 2:
        return None
    first = words[0]
    lowered = first.lower()
    if lowered in _ARTICLES or _is_vocabulary_word(lowered):
        return None
    return first


def _is_vocabulary_word(word: str) -> bool:
    """Whether *word* is one the game itself uses to describe objects.

    Asked of the grammar's own catalogs rather than a list here, so a set that
    introduces a creature type sharing a legend's first word narrows this
    automatically instead of needing an edit nobody would think to make.
    """
    from .grammar.vocabulary import (
        ALL_SUBTYPES,
        CARD_TYPES,
        COLOR_WORDS,
        KEYWORD_ABILITIES,
        KEYWORD_ACTIONS,
        NUMBER_WORDS,
        SUPERTYPES,
    )

    return (
        word in ALL_SUBTYPES
        or word in CARD_TYPES
        or word in SUPERTYPES
        or word in COLOR_WORDS
        or word in NUMBER_WORDS
        or word in KEYWORD_ABILITIES
        or word in KEYWORD_ACTIONS
    )


def expand_short_self_references(
    oracle_text: str, card_name: str | None, *, legendary: bool
) -> str:
    """*oracle_text* with every shortened self-reference written out in full.

    Whole words only, and never one already sitting inside an occurrence of the
    full name — "Rin and Seri" must not have its own first word rewritten, and a
    card whose text prints both forms must end with one.
    """
    short = short_self_name(card_name, legendary=legendary)
    if short is None or not oracle_text:
        return oracle_text
    full = (card_name or "").strip()
    spans = [
        match.span()
        for match in re.finditer(rf"\b{re.escape(full)}\b", oracle_text)
    ]

    def _replace(match: re.Match[str]) -> str:
        if any(start <= match.start() < end for start, end in spans):
            return match.group(0)
        return full

    return re.sub(rf"\b{re.escape(short)}\b", _replace, oracle_text)


# ---------------------------------------------------------------------------
# The other reader: a name collapsed to "this creature" for the rule tables.
# The compiler's until the 2,000-line split (``engine/oracle.py``).
# ---------------------------------------------------------------------------

def _self_name_forms(card_name: str | None) -> tuple[str, ...]:
    """The lowercase name forms a card may refer to itself by: the full name,
    and — for a name with a comma — the short name before it (CR 201.5c,
    "Ugin, the Spirit Dragon" says "Ugin")."""
    if not card_name:
        return ()
    full = card_name.strip().lower()
    forms = [full]
    if "," in full:
        forms.append(full.split(",", 1)[0].strip())
    return tuple(forms)


#: Words that put the name after them in a **type** position rather than a
#: self-reference position: "each other attacking **Aurochs**" is a creature
#: type, not the card talking about itself.
#:
#: Only reachable for a card whose own name *is* a creature type — four in the
#: pool, and only Aurochs uses it as a type. But the failure is the silent kind:
#: collapsed, the count reads "each other attacking **this creature**", a set of
#: one thing that excludes itself and is therefore always empty, so the pump
#: resolves for +0/+0 on a card reporting itself supported.
_TYPE_POSITION_WORDS = frozenset({
    "a", "an", "another", "any", "attacking", "blocking", "each", "every",
    "other", "target", "untapped", "tapped", "all", "no",
})


def _preceding_word(text: str, index: int) -> str:
    """The word immediately before *index*, lowercased, or "" at the start."""
    before = text[:index].rstrip()
    return before.rsplit(" ", 1)[-1].lower() if before else ""


def _collapse_self_references(normalized: str, card_name: str | None, replacement: str) -> str:
    """*normalized* with whole-word self-references replaced by *replacement*.

    A name that is also a **creature type** is left alone where the sentence
    uses it as one — see :data:`_TYPE_POSITION_WORDS`. Everywhere else it is the
    card naming itself (CR 201.5), the possessive "Lhurgoyf's power" included,
    which is the form the pool's other such cards print.
    """
    for form in _self_name_forms(card_name):
        if form.lower() in CREATURE_TYPES:
            normalized = re.sub(
                rf"\b{re.escape(form)}\b",
                lambda match, text=normalized: (
                    match.group(0)
                    if _preceding_word(text, match.start()) in _TYPE_POSITION_WORDS
                    else replacement
                ),
                normalized,
            )
            continue
        normalized = re.sub(rf"\b{re.escape(form)}\b", replacement, normalized)
    return normalized


def _restriction_line(line: str, card_name: str | None) -> str:
    """*line* normalized with the card's own name collapsed to "this creature".

    Pre-modern templating — and modern legendary templating — writes the
    subject as the card's name: "**Gadrak** can't attack unless…". The combat
    restriction table is anchored on "this creature", so without this the clause
    matched nothing and the card reported "text too complex" for a template the
    engine implements. The lexer already collapses the same references for the
    grammar (CR 201.5c's short name included); this is that rule on the
    static-line path.

    Scoped to this one consult rather than folded into
    ``normalize_creature_line``, whose output is *stored* on the program as
    ``static_lines`` and matched on by several text-keyed readers — rewriting it
    for every card that names itself is a change with its own blast radius and
    no card asking for it.
    """
    return _collapse_self_references(
        normalize_creature_line(line), card_name, "this creature"
    )


__all__ = ["expand_short_self_references", "short_self_name"]
