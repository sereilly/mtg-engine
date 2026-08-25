"""Text-keyed immunity to being *chosen* (CR 115.6, CR 303.4).

The mirror of ``target_restrictions.py`` beside it, and the pair is worth
stating: that file is what a **spell** prints about its own targeting ("You
can't choose an untapped creature as this spell's target"), asked of the spell
being cast; this one is what a **permanent** prints about being aimed at, asked
of the object on the battlefield. Two rules, two subjects, and a card can print
either without the other.

Two sentences here, one subject:

* "Bartel Runeaxe can't be the target of Aura spells" (Bartel Runeaxe, Tetsuo
  Umezawa) and "Enchanted creature can't be the target of spells"
  (Anti-Magic Aura) — a **narrowed shroud**. Shroud (CR 702.18) stops every
  spell and every ability; these stop one class of spell, so neither is shroud
  with a filter bolted on. The class is payload, like the land type in
  ``combat_restrictions.py``.
* "…and can't be enchanted by other Auras" (Anti-Magic Aura) — a separate rule
  about *attachment* rather than targeting, and it has to be separate: an Aura
  spell targets, so the clause above already stops one being cast at the
  creature, but an Aura **moved** onto it by an effect (Enchantment Alteration)
  was never targeted at it and only this clause stops that. Printing both on one
  card is not redundancy, and reading the pair as one restriction would drop
  whichever half was implemented second.

Where the answer is asked from is the point. ``Game._can_be_targeted`` is the
one predicate the cast gate, the target picker and the AI all reach, so a class
listed here is enforced everywhere a target is chosen rather than at whichever
call site remembered. ``auras.ability_target_immunity_classes`` is the sibling
answering the same question for *abilities*; the two are separate because CR
115.6 lets a card stop one and not the other — Artifact Ward stops only
abilities, Anti-Magic Aura only spells.

The support gate reads this file too (``oracle._derived_static_claims``,
``auras.aura_continuous_claim``), so a card whose whole text is one of these
sentences is supported *because* the restriction is implemented — and a wording
this file cannot read makes the card unsupported rather than admitting it with
the protection silently absent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The subject a clause is printed about: the permanent carrying the line, or
#: the one an Aura carrying it is attached to. Named so a caller does not have
#: to know which kind of card it is reading.
SELF_SUBJECT = "self"
ATTACHED_SUBJECT = "attached"

#: The class naming *every* spell, where anything else names a subtype.
ANY_SPELL = "spell"

#: The claim string the support gates use.
CLAIM = "target_immunity"

_SELF = r"this (?:creature|artifact|enchantment|land|permanent)"
_ATTACHED = r"enchanted (?:creature|artifact|enchantment|land|permanent)"

#: The classes of spell a printed phrase can name. A subtype narrows it ("Aura
#: spells"); the bare plural is every spell. A word not listed leaves the
#: sentence unmatched, so the card is reported unsupported naming the clause
#: rather than admitted with a restriction nobody tests.
_SPELL_CLASSES: tuple[tuple[str, str], ...] = (
    ("aura spells", "aura"),
    ("spells", ANY_SPELL),
)


@dataclass(frozen=True)
class TargetImmunity:
    """One printed "can't be the target of <class>" clause."""

    subject: str
    spell_class: str


@dataclass(frozen=True)
class EnchantImmunity:
    """One printed "can't be enchanted by other Auras" clause."""

    subject: str


_TARGET_IMMUNITY = re.compile(
    rf"^(?P<who>{_SELF}|{_ATTACHED}) can't be the target of (?P<spell_class>[a-z ]+?)$"
)
_ENCHANT_IMMUNITY = re.compile(
    rf"^(?P<who>{_SELF}|{_ATTACHED}) can't be enchanted by other auras$"
)


def _subject_of(who: str) -> str:
    return ATTACHED_SUBJECT if who.startswith("enchanted") else SELF_SUBJECT


def _clauses(line: str) -> list[str]:
    """One printed line split into the restrictions it conjoins.

    "Enchanted creature can't be the target of spells **and** can't be enchanted
    by other Auras" is two rules on one line, and the second half prints no
    subject of its own. Splitting on "and can't" and carrying the subject
    forward is what keeps the pair from being read as one restriction whose tail
    is dropped — the bug class this repo calls a dropped rider.
    """
    text = line.strip().rstrip(".").lower()
    if not text:
        return []
    head, sep, tail = text.partition(" and can't ")
    if not sep:
        return [text]
    subject = head.split(" can't ")[0]
    return [head, f"{subject} can't {tail}"]


def target_immunities(line: str) -> tuple[TargetImmunity, ...]:
    """Every "can't be the target of <class>" clause *line* prints."""
    found = []
    for clause in _clauses(line):
        match = _TARGET_IMMUNITY.match(clause)
        if match is None:
            continue
        printed = match.group("spell_class")
        spell_class = next(
            (name for phrase, name in _SPELL_CLASSES if phrase == printed), None
        )
        if spell_class is None:
            continue
        found.append(TargetImmunity(_subject_of(match.group("who")), spell_class))
    return tuple(found)


def enchant_immunities(line: str) -> tuple[EnchantImmunity, ...]:
    """Every "can't be enchanted by other Auras" clause *line* prints."""
    return tuple(
        EnchantImmunity(_subject_of(match.group("who")))
        for clause in _clauses(line)
        for match in (_ENCHANT_IMMUNITY.match(clause),)
        if match is not None
    )


def immunity_claims_line(line: str) -> bool:
    """Whether this file implements *line* in full.

    **Every** clause, not merely one: a line conjoining a restriction this file
    reads with one it does not is a line half of which would be dropped, and the
    card must be reported unsupported for it.
    """
    clauses = _clauses(line)
    if not clauses:
        return False
    return all(
        bool(target_immunities(clause) or enchant_immunities(clause))
        for clause in clauses
    )


def _lines_of(card) -> list[str]:
    """*card*'s printed lines with its own name collapsed to "this creature".

    Pre-modern and legendary templating writes the subject as the card's name —
    "**Bartel Runeaxe** can't be the target of Aura spells" — while the patterns
    above are anchored on the self-reference. Through ``oracle._restriction_line``
    rather than a second collapser here: the *gate* already reads the line that
    way, and a runtime reader normalizing differently is exactly how a card
    compiles supported and then protects nobody, which is what the first run of
    this round's probe showed.
    """
    from .oracle import _restriction_line

    return [
        _restriction_line(line, card.name)
        for line in (card.oracle_text or "").splitlines()
    ]


def spell_target_immunity_classes(permanent) -> frozenset[str]:
    """Every class of spell that may not target *permanent*.

    Gathers the permanent's own printed lines *and* the Auras attached to it,
    which is why this lives here rather than in ``auras.py``: one question, one
    answer, however the restriction reached the creature. Read off the
    **effective** card, so a copied or text-changed permanent is asked what it
    says now (CR 613 layers 1 and 3).

    Asked at the moment a target is chosen, so the immunity ends when the Aura
    does — the same shape ``auras.ability_target_immunity_classes`` has.
    """
    from .auras import auras_attached_to

    classes = {
        immunity.spell_class
        for line in _lines_of(permanent.effective_card)
        for immunity in target_immunities(line)
        if immunity.subject == SELF_SUBJECT
    }
    classes |= {
        immunity.spell_class
        for aura in auras_attached_to(permanent)
        for line in _lines_of(aura.effective_card)
        for immunity in target_immunities(line)
        if immunity.subject == ATTACHED_SUBJECT
    }
    return frozenset(classes)


def cannot_be_enchanted(permanent, *, by_aura=None) -> bool:
    """Whether an Aura may not become attached to *permanent* (CR 303.4).

    *by_aura* is the Aura asking, and "…by **other** Auras" is what makes it
    matter: Anti-Magic Aura's own clause must not detach Anti-Magic Aura, which
    is the reading a bare "can't be enchanted" would give — and the CR 704.5m
    sweep would then act on it every turn.
    """
    from .auras import auras_attached_to

    if any(
        immunity.subject == SELF_SUBJECT
        for line in _lines_of(permanent.effective_card)
        for immunity in enchant_immunities(line)
    ):
        return True
    return any(
        immunity.subject == ATTACHED_SUBJECT
        for aura in auras_attached_to(permanent)
        if aura is not by_aura
        for line in _lines_of(aura.effective_card)
        for immunity in enchant_immunities(line)
    )


def spell_is_in_class(card, spell_class: str) -> bool:
    """Whether a spell being cast belongs to *spell_class*.

    :data:`ANY_SPELL` is every spell; anything else is a subtype, asked through
    the reader every other subtype question uses — a card has every subtype its
    line prints, and picking one off a list is how an "Enchantment — Aura" stops
    being an Aura.
    """
    if spell_class == ANY_SPELL:
        return True
    from .search_filters import card_has_type

    return card_has_type(card, spell_class)


__all__ = [
    "ANY_SPELL",
    "ATTACHED_SUBJECT",
    "CLAIM",
    "SELF_SUBJECT",
    "cannot_be_enchanted",
    "enchant_immunities",
    "immunity_claims_line",
    "spell_is_in_class",
    "spell_target_immunity_classes",
    "target_immunities",
]
