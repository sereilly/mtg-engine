"""Text-keyed immunity to being *chosen* (CR 115.1, CR 303.4).

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
* "This creature can't be the target of spells that can target only Walls or of
  abilities that can target only Walls" (Wall of Shadows) — a narrowed shroud
  again, but narrowed along a **different axis**. The two clauses above name a
  class the source *belongs to* (an Aura spell, an artifact source), readable
  off the source object alone. This one names what the source's own target
  description *admits*: Tunnel is stopped because "target Wall" can be answered
  by nothing else, while Terror's "target creature" is fine however many Walls
  it could hit. So it is answered from the source's derived target spec
  (``targeting.spec_only_subtype``) rather than from the source's own
  characteristics, and the printed subtype is payload like every other.

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
115.1a and CR 115.1c/d make a spell and an ability separately targeted objects,
so a card can stop one and not the other — Artifact Ward stops only abilities,
Anti-Magic Aura only spells. (This paragraph cited rule 115.6 — written
without the "CR" so it is not counted as a citation of it — until a rules-test
round read that rule: it is the zero-targets permission and says nothing about
the two kinds. A citation naming a rule that exists is invisible to
`rules_gaps.py`, which checks that the number and its subrule letter are real,
not that the sentence beside it is what the rule says.)

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

#: Which of the two things a card may be immune to separately (CR 115.1a for
#: a spell, CR 115.1c/d for an ability). A printed line may name one, the
#: other, or both, so the answer is asked per kind and never once for both.
SPELL_SOURCE = "spell"
ABILITY_SOURCE = "ability"

#: The printed plural for each, as the "…that can target only X" clause spells
#: it. Data rather than a branch: the clause reads identically either side.
_SOURCE_KIND_WORDS: dict[str, str] = {
    "spells": SPELL_SOURCE,
    "abilities": ABILITY_SOURCE,
}

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
    # "…**unless it attacked or blocked this turn**" (Lurker). CR 611.2's "as
    # long as" clause on a static ability, printed the other way round: the
    # immunity exists only while the creature has stayed out of combat, and it
    # is rechecked whenever a target is chosen rather than latched, because a
    # creature that attacks stops being protected in the middle of a turn.
    #
    # A flag rather than a second spell class, because it narrows *when* the
    # restriction holds and not *what* it stops - and a dropped condition would
    # be a creature untargetable all game, which is strictly more protection
    # than the card prints.
    unless_combatant: bool = False


@dataclass(frozen=True)
class NarrowSourceImmunity:
    """One printed "can't be the target of <sources> that can target only <Type>s".

    *only_subtype* is singular ("wall"), because that is what a permanent's
    subtypes are asked for; the printed plural is the clause's, not the rule's.
    """

    subject: str
    source_kind: str
    only_subtype: str


@dataclass(frozen=True)
class EnchantImmunity:
    """One printed "can't be enchanted by other Auras" clause."""

    subject: str


_TARGET_IMMUNITY = re.compile(
    rf"^(?P<who>{_SELF}|{_ATTACHED}) can't be the target of (?P<spell_class>[a-z ]+?)"
    r"(?P<unless> unless it attacked or blocked this turn)?$"
)
_ENCHANT_IMMUNITY = re.compile(
    rf"^(?P<who>{_SELF}|{_ATTACHED}) can't be enchanted by other auras$"
)

#: The head of a narrowed-source clause, and one of the things it conjoins.
#: Two patterns rather than one alternation because the printed sentence names
#: the subject once and the source kinds twice — "…of spells that can target
#: only Walls **or of** abilities that can target only Walls" — and every half
#: has to be read or the card is a dropped rider away from a silent hole.
_NARROW_SOURCE_HEAD = re.compile(
    rf"^(?P<who>{_SELF}|{_ATTACHED}) can't be the target of (?P<body>.+)$"
)
_NARROW_SOURCE_PART = re.compile(
    r"^(?:of )?(?P<kinds>[a-z]+) that can target only (?P<subtype>[a-z-]+)s$"
)


def _subject_of(who: str) -> str:
    return ATTACHED_SUBJECT if who.startswith("enchanted") else SELF_SUBJECT


#: "<subject> gets +0/+2 and <restriction>" — the P/T half another reader owns.
_PT_PREFIX = re.compile(r"^(.+?) gets [+-]\d+/[+-]\d+ and ")


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
    # "Enchanted creature **gets +0/+2 and** can't be the target of spells"
    # (Spectral Shield). The P/T half belongs to `auras.aura_static_pt_grant`
    # and is read there; dropped here, what is left is the restriction this file
    # implements, printed exactly as every other card prints it.
    #
    # The same split `auras._KEYWORD_GRANT` makes with its optional "gets
    # ±N/±N and" prefix, and in the one place both the support gate and the
    # runtime reader go through — a prefix stripped in only one of them is a
    # card that compiles supported and protects nobody.
    text = _PT_PREFIX.sub(lambda m: m.group(1) + " ", text)
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
        found.append(
            TargetImmunity(
                _subject_of(match.group("who")),
                spell_class,
                unless_combatant=match.group("unless") is not None,
            )
        )
    return tuple(found)


def narrow_source_immunities(line: str) -> tuple[NarrowSourceImmunity, ...]:
    """Every "can't be the target of <sources> that can target only <Type>s" *line* prints.

    **All or nothing.** The clause conjoins one restriction per source kind, and
    a half this cannot read is a half that would be dropped — so an unreadable
    conjunct withdraws the whole clause and the card is reported unsupported
    naming it, rather than admitted with the abilities half silently absent.
    """
    match = _NARROW_SOURCE_HEAD.match(line)
    if match is None:
        return ()
    subject = _subject_of(match.group("who"))
    found = []
    for part in match.group("body").split(" or "):
        part_match = _NARROW_SOURCE_PART.match(part.strip())
        if part_match is None:
            return ()
        source_kind = _SOURCE_KIND_WORDS.get(part_match.group("kinds"))
        if source_kind is None:
            return ()
        found.append(
            NarrowSourceImmunity(subject, source_kind, part_match.group("subtype"))
        )
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
        bool(
            target_immunities(clause)
            or enchant_immunities(clause)
            or narrow_source_immunities(clause)
        )
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
        if immunity.subject == SELF_SUBJECT and _immunity_holds(immunity, permanent)
    }
    classes |= {
        immunity.spell_class
        for aura in auras_attached_to(permanent)
        for line in _lines_of(aura.effective_card)
        for immunity in target_immunities(line)
        if immunity.subject == ATTACHED_SUBJECT
        and _immunity_holds(immunity, permanent)
    }
    return frozenset(classes)


def _immunity_holds(immunity: TargetImmunity, permanent) -> bool:
    """Whether *immunity*'s "unless" clause leaves it standing right now.

    Asked here, where the protected permanent is in hand, and asked on every
    choice rather than latched: "unless it attacked or blocked this turn"
    (Lurker) becomes false the moment the creature is declared, and a latched
    answer would keep protecting an attacker for the rest of the turn.

    Whichever line carried the clause, the subject is the protected permanent -
    an Aura printing it would be saying it about the creature it enchants - so
    there is one record to read and no second reading of "it".
    """
    if not immunity.unless_combatant:
        return True
    return not _was_in_combat_this_turn(permanent)


def _was_in_combat_this_turn(permanent) -> bool:
    """Whether *permanent* attacked or blocked this turn (CR 508.1, CR 509.1).

    Both halves come from records the declaration steps already stamp - the
    attacker flag and the list of attackers a blocker was declared against - so
    there is no new bookkeeping and nothing to forget to clear: both are swept
    with the turn.
    """
    metadata = getattr(permanent, "metadata", None)
    if not metadata:
        return False
    return bool(
        metadata.get("attacked_this_turn")
        or metadata.get("blocked_attacker_ids_this_turn")
    )


def narrow_source_immunity_subtypes(permanent, source_kind: str) -> frozenset[str]:
    """The subtypes a *source_kind* may not be restricted to when aiming at *permanent*.

    The sibling of :func:`spell_target_immunity_classes`, gathering the
    permanent's own lines and the Auras attached to it for the same reason: one
    question, one answer, however the restriction reached the creature. Asked
    per source kind because a spell and an ability are separately targeted
    (CR 115.1a, CR 115.1c/d) so a card can stop one and not the other, and
    Wall of Shadows printing both is not permission to answer for both at once.
    """
    from .auras import auras_attached_to

    subtypes = {
        immunity.only_subtype
        for line in _lines_of(permanent.effective_card)
        for immunity in narrow_source_immunities(line)
        if immunity.subject == SELF_SUBJECT and immunity.source_kind == source_kind
    }
    subtypes |= {
        immunity.only_subtype
        for aura in auras_attached_to(permanent)
        for line in _lines_of(aura.effective_card)
        for immunity in narrow_source_immunities(line)
        if immunity.subject == ATTACHED_SUBJECT and immunity.source_kind == source_kind
    }
    return frozenset(subtypes)


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
    "ABILITY_SOURCE",
    "ANY_SPELL",
    "ATTACHED_SUBJECT",
    "CLAIM",
    "SELF_SUBJECT",
    "SPELL_SOURCE",
    "cannot_be_enchanted",
    "enchant_immunities",
    "immunity_claims_line",
    "narrow_source_immunities",
    "narrow_source_immunity_subtypes",
    "spell_is_in_class",
    "spell_target_immunity_classes",
    "target_immunities",
]
