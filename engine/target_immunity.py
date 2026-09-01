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


#: The prefix that makes a colour word a *class of source*. "White spells" is a
#: class of spell exactly as "Aura spells" is, and "abilities from white
#: sources" narrows the same way one printed clause over — so a colour travels
#: down the same channel as a subtype rather than as a second field beside it.
#:
#: Namespaced because the channel really is shared and the two axes would
#: otherwise be indistinguishable strings: an unprefixed "artifact" is a card
#: type read off the source's type line, and an unprefixed "white" would be
#: asked of the same reader as a subtype no card has — which answers False and
#: drops the restriction in silence.
COLOR_CLASS_PREFIX = "color:"

#: The printed colour words, mapped to the symbols every colour reader uses.
#: Data rather than a branch, exactly as ``_SOURCE_KIND_WORDS`` above is.
_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}

#: The card types "abilities from <type> sources" names. The list Artifact Ward
#: was read with when this clause lived in ``auras.py``, carried across whole so
#: no printing that used to be read stops being read.
_SOURCE_CARD_TYPES = ("artifact", "creature", "enchantment", "land")


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


@dataclass(frozen=True)
class SourceClassImmunity:
    """One printed "can't be the target of <a class of source>" conjunct.

    "This enchantment can't be the target of white spells **or** abilities from
    white sources." (Raiding Party.) / "Enchanted creature can't be the target
    of abilities from artifact sources." (Artifact Ward.)

    The third axis a narrowed shroud can be narrowed along, and the one the two
    above could not carry. :class:`TargetImmunity` names a class of *spell* by
    its card type; :class:`NarrowSourceImmunity` names what the source's own
    target description admits. This one names what the **source** is —
    a colour or a card type — and it is asked per source kind, because a spell
    and an ability are separately targeted (CR 115.1a, CR 115.1c/d) and one
    printed line may name one, the other, or both.

    *source_class* is a card type ("artifact") or a colour under
    :data:`COLOR_CLASS_PREFIX` ("color:W"), which is the same string the two
    readers behind it dispatch on.
    """

    subject: str
    source_kind: str
    source_class: str


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

#: One conjunct of a source-class clause: either a coloured spell ("white
#: spells") or an ability from a class of source ("abilities from white
#: sources", "abilities from artifact sources").
#:
#: Its head is :data:`_NARROW_SOURCE_HEAD`, shared rather than copied: both
#: readers are the same sentence split on the same " or ", and the only thing
#: that tells them apart is which conjunct shape matches. A second head regex
#: would be the same sentence spelled twice.
_SOURCE_CLASS_PART = re.compile(
    r"^(?:of )?(?:"
    rf"(?P<spell_color>{'|'.join(_COLOR_WORDS)}) spells"
    rf"|abilities from (?P<ability_class>{'|'.join((*_COLOR_WORDS, *_SOURCE_CARD_TYPES))}) sources"
    r")$"
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


def source_class_immunities(line: str) -> tuple[SourceClassImmunity, ...]:
    """Every "can't be the target of <class of source>" conjunct *line* prints.

    "This enchantment can't be the target of white spells or abilities from
    white sources." (Raiding Party.) One printed subject and two conjuncts
    joined by "or", which is the same shape :func:`narrow_source_immunities`
    reads one clause over — so it shares that clause's head and its rule.

    **All or nothing**, for that function's reason: a conjunct this cannot read
    is a conjunct that would be dropped, and half a narrowed shroud is strictly
    more permissive than the card prints. An unreadable conjunct withdraws the
    whole clause, and the card is reported unsupported naming it.

    Returns ``()`` for a clause that names no source class at all — "…of
    spells" (Anti-Magic Aura), "…of Aura spells" (Bartel Runeaxe), "…of spells
    that can target only Walls" (Wall of Shadows) — so each of those keeps the
    reader written for it rather than being claimed twice.
    """
    match = _NARROW_SOURCE_HEAD.match(line)
    if match is None:
        return ()
    subject = _subject_of(match.group("who"))
    found = []
    for part in match.group("body").split(" or "):
        part_match = _SOURCE_CLASS_PART.match(part.strip())
        if part_match is None:
            return ()
        colour = part_match.group("spell_color")
        if colour is not None:
            found.append(
                SourceClassImmunity(
                    subject, SPELL_SOURCE, COLOR_CLASS_PREFIX + _COLOR_WORDS[colour]
                )
            )
            continue
        printed = part_match.group("ability_class")
        source_class = (
            COLOR_CLASS_PREFIX + _COLOR_WORDS[printed]
            if printed in _COLOR_WORDS else printed
        )
        found.append(SourceClassImmunity(subject, ABILITY_SOURCE, source_class))
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
            or source_class_immunities(clause)
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


def printed_about(permanent, reader):
    """Every clause *reader* finds that is printed **about** *permanent*.

    The permanent's own lines, where the clause's subject is the card itself,
    plus the lines of every Aura attached to it, where the subject is the
    enchanted permanent. One question, one answer, however the restriction
    reached the creature — which is why this file answers for both and
    ``auras.py`` no longer answers for one of them.

    Read off the **effective** card, so a copied or text-changed permanent is
    asked what it says now (CR 613 layers 1 and 3), and read at the moment a
    target is chosen, so the immunity ends when the Aura does.
    """
    from .auras import auras_attached_to

    for line in _lines_of(permanent.effective_card):
        for found in reader(line):
            if found.subject == SELF_SUBJECT:
                yield found
    for aura in auras_attached_to(permanent):
        for line in _lines_of(aura.effective_card):
            for found in reader(line):
                if found.subject == ATTACHED_SUBJECT:
                    yield found


def spell_target_immunity_classes(permanent) -> frozenset[str]:
    """Every class of spell that may not target *permanent*.

    Two readers, one answer. :func:`target_immunities` names a class by the
    spell's *card type* ("Aura spells") or by nothing at all ("spells");
    :func:`source_class_immunities` names it by the spell's **colour** ("white
    spells", Raiding Party). Both are classes of spell asked at the same
    moment, so a caller sees one set — and :func:`spell_is_in_class` is the one
    reader that decides what each string in it means.
    """
    classes = {
        immunity.spell_class
        for immunity in printed_about(permanent, target_immunities)
        if _immunity_holds(immunity, permanent)
    }
    classes |= {
        immunity.source_class
        for immunity in printed_about(permanent, source_class_immunities)
        if immunity.source_kind == SPELL_SOURCE
    }
    return frozenset(classes)


def ability_source_immunity_classes(permanent) -> frozenset[str]:
    """Every class of source whose **abilities** may not target *permanent*.

    "Enchanted creature can't be the target of abilities from artifact
    sources." (Artifact Ward.) / "…or abilities from white sources." (Raiding
    Party.) The sibling of :func:`spell_target_immunity_classes`, separate from
    it because CR 115.1a and CR 115.1c/d make a spell and an ability separately
    targeted objects — a card can stop one and not the other, and Artifact Ward
    stops only abilities.

    This lived in ``auras.py`` and answered only for an Aura's attachment,
    which is half the question: Raiding Party prints the clause about
    **itself**, and a reader keyed to the attachment cannot see it. One reader
    for both subjects and both axes, so there is no second copy free to
    disagree about which sources a clause names.
    """
    return frozenset(
        immunity.source_class
        for immunity in printed_about(permanent, source_class_immunities)
        if immunity.source_kind == ABILITY_SOURCE
    )


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
    return frozenset(
        immunity.only_subtype
        for immunity in printed_about(permanent, narrow_source_immunities)
        if immunity.source_kind == source_kind
    )


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
    if spell_class.startswith(COLOR_CLASS_PREFIX):
        # "**White** spells" (Raiding Party). CR 105.2 — a spell's colours,
        # through the one reader every colour question in this engine uses, so
        # a laced or copied source answers with what it is now rather than with
        # what it was printed as.
        from .damage_source_colors import source_colors

        return spell_class[len(COLOR_CLASS_PREFIX):] in source_colors(card)
    from .search_filters import card_has_type

    return card_has_type(card, spell_class)


def source_is_in_class(game, source, source_class: str) -> bool:
    """Whether the object whose **ability** is choosing belongs to *source_class*.

    :func:`spell_is_in_class`'s twin for the other half of CR 115.1, separate
    from it for the reason the two halves are separate everywhere in this file:
    the same question, asked of a different kind of object. A spell is a card
    on the stack; an ability's source is a permanent, and an animated artifact
    land is an artifact source however its printed type line reads — which is
    why the card-type half goes through ``prevention.source_has_type`` rather
    than through the printed line.
    """
    if source_class.startswith(COLOR_CLASS_PREFIX):
        from .damage_source_colors import source_colors

        return source_class[len(COLOR_CLASS_PREFIX):] in source_colors(source)
    from .prevention import source_has_type

    return source_has_type(game, source, source_class)


__all__ = [
    "ABILITY_SOURCE",
    "ANY_SPELL",
    "ATTACHED_SUBJECT",
    "CLAIM",
    "COLOR_CLASS_PREFIX",
    "SELF_SUBJECT",
    "SPELL_SOURCE",
    "SourceClassImmunity",
    "ability_source_immunity_classes",
    "cannot_be_enchanted",
    "enchant_immunities",
    "immunity_claims_line",
    "narrow_source_immunities",
    "narrow_source_immunity_subtypes",
    "printed_about",
    "source_class_immunities",
    "source_is_in_class",
    "spell_is_in_class",
    "spell_target_immunity_classes",
    "target_immunities",
]
