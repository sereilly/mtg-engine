"""Storm (CR 702.40), the keyword and the triggered ability it *is*.

CR 702.40a does not describe storm, it **defines** it: *"Storm is a triggered
ability that functions on the stack. 'Storm' means 'When you cast this spell,
copy it for each other spell that was cast before it this turn. If the spell
has any targets, you may choose new targets for any of the copies.'"* So this
module is the rewrite ``engine/provoke.py``, ``engine/flanking.py`` and
``engine/madness.py`` established for a keyword the CR defines as a trigger:
the printed keyword line becomes a compiled
:class:`~engine.oracle_types.ParsedTriggeredAbility`, read by both compiler
front ends through ``keyword_lines.keyword_line_triggers``, and from there the
existing machinery does the rest — nothing downstream of the compiler knows
the word.

**Why a trigger and not a rewrite into a sentence.** Kicker, buyback and
flashback are rewritten (``line_rewrites.expand_ability_lines``) because what
they define is a cost or a permission: static text a registry claims. Storm is
a triggered ability, and a triggered ability is an object on the stack
(CR 603.3) that a player may respond to and counter (Stifle; the 2022-12-08
ruling on every storm card: "The triggered ability that creates the copies can
itself be countered by anything that can counter a triggered ability. If it is
countered, no copies will be put onto the stack."). So it has to be an ability
with an instruction behind it, and the shape that already is one is the
keyword-line trigger.

**Built from what ships:**

* the condition is ``self_cast``, the "when you cast this spell" the grammar
  produces for Mana Vortex and the kicker cast triggers — CR 603.6d's ability
  that triggers from the stack, fired by ``events.cast_trigger_events`` off the
  card being cast, with the spell's own stack object (``cast_item``) frozen on
  the trigger's context;
* the instruction is ``copy_triggering_spell`` (Double Vision's "copy that
  spell"), which copies the frozen object through the one builder
  ``spell_copies._copy_of_spell`` and offers each copy's controller its new
  target (``arm_copy_spell_target``, CR 707.10c). What storm adds is how many:
  the payload's ``for_each`` names :data:`SPELLS_CAST_BEFORE_IT`, and
  :func:`copies_for_each` is the one reader of it.

**The count is fixed by the cast, read at resolution.** "Each other spell that
was cast before it this turn" counts every player's spells (CR 702.40a names no
caster), cast from any zone, countered or not, and **not** the ones cast after
it — a spell cast in response to the storm trigger was cast after the storm
spell, however early it resolves (2019-06-14 ruling on Wing Shards: "Spells cast
after the spell with storm was cast but before the storm ability resolves
aren't counted."). The engine already records every cast this turn in order, by
stack object, at the single site that puts a spell on the stack
(``damage_ledger.record_cast``): the storm spell's own position in that list *is*
the number of spells cast before it. Copies are never in it (CR 707.10: "a copy
of a spell isn't cast"), so a copy neither counts nor storms.

**Only on an instant or a sorcery.** A storm spell's copies are copies of the
spell, and a copy of a *permanent* spell becomes a token as it resolves
(CR 707.10f, 608.3f) — which ``mixins/stack/resolution`` does not build: a
copied creature spell would resolve as a second *card*. No Scourge card prints
storm on a permanent (Aeve, Progenitor Ooze is the first), so a permanent
printing it is refused by :func:`unread_storm_line`, naming the missing piece,
rather than admitted to do the wrong thing. That is also why ``"storm"`` is not
in ``vocabulary.IMPLEMENTED_KEYWORDS``: that set is "a keyword whose behaviour
covers everywhere the CR says it applies", and the permanent half does not
exist yet. The keyword-line gate admits it by its reader (:func:`is_storm`), as
it admits madness and morph by theirs.

CR 702.40b — several instances each trigger separately — is why
:func:`storm_instances` counts rather than answering yes or no.
"""

from __future__ import annotations

from .line_normalization import normalize_creature_line
from .oracle_types import (OracleInstruction, ParsedTriggeredAbility,
                           TriggerCondition)

#: The bucket the support report puts the trigger in: the label
#: ``effect_labels`` already gives ``copy_triggering_spell`` (Double Vision),
#: the instruction this ability resolves. Carried here for
#: ``provoke.PROVOKE_LABEL``'s reason — that table describes the abilities the
#: grammar reads, and this one is derived from a keyword line it never sees.
STORM_LABEL = "triggered_copy"

#: The word as it survives ``normalize_creature_line`` — lowercased, with the
#: reminder text already stripped. No argument, so the whole part is the word.
_STORM_PART = "storm"

#: What ``copy_triggering_spell``'s ``for_each`` names for storm: "for each
#: other spell that was cast before it this turn" (CR 702.40a). A count rather
#: than a set, read by :func:`copies_for_each` and by nothing else.
SPELLS_CAST_BEFORE_IT = "other_spell_cast_before_it_this_turn"

#: What one instance of storm says, in the CR's words (702.40a) rather than the
#: reminder text's: the reminder says "for each spell cast before it", and the
#: rule says "each **other** spell that was cast before it". The rule wins.
STORM_RULES_TEXT = (
    "When you cast this spell, copy it for each other spell that was cast "
    "before it this turn. If the spell has any targets, you may choose new "
    "targets for any of the copies."
)

#: The spell types storm is carried out on. A copy of anything else is a copy
#: of a permanent spell (CR 707.10f), which the stack does not yet build.
_STORM_SPELL_TYPES = frozenset({"instant", "sorcery"})


def is_storm(part: str) -> bool:
    """Whether one normalized keyword-line part is storm."""
    return part.strip() == _STORM_PART


def storm_instances(keyword_line: str) -> int:
    """How many instances of storm one comma-joined keyword line names.

    CR 702.40b makes each instance a separate triggered ability, so this
    counts rather than answering yes or no.
    """
    return sum(1 for part in (keyword_line or "").split(",") if is_storm(part))


def storm_instruction() -> OracleInstruction:
    """The effect one instance of storm resolves (CR 702.40a)."""
    return OracleInstruction(
        "copy_triggering_spell", "storm", {"for_each": SPELLS_CAST_BEFORE_IT},
    )


def storm_triggers(keyword_line: str) -> tuple[ParsedTriggeredAbility, ...]:
    """The triggered abilities CR 702.40a says *are* the storm on this line.

    The condition is the ``self_cast`` a printed "when you cast this spell"
    produces, so ``events.cast_trigger_events`` puts one on the stack per
    instance as the spell becomes cast (CR 601.2i), above the spell, with the
    spell's own stack object frozen on its context.
    """
    return tuple(
        ParsedTriggeredAbility(
            source_line=_STORM_PART,
            condition=TriggerCondition(
                kind="self_cast",
                trigger="when",
                raw_text="when you cast this spell",
                payload={},
            ),
            instruction=storm_instruction(),
            supported=True,
            effect_kind=STORM_LABEL,
        )
        for _ in range(storm_instances(keyword_line))
    )


def unread_storm_line(oracle_text: str, primary_type: str) -> str | None:
    """A storm line on a card storm cannot yet be carried out on, or None —
    the support gate's question.

    A storm spell's copies are copies of *it*, and only an instant's or a
    sorcery's copy is something the stack can resolve: a copy of a permanent
    spell becomes a token (CR 707.10f, 608.3f), and nothing builds that token.
    Admitted on a creature, the line would compile, trigger, and resolve each
    copy as a second card onto the battlefield — supported and wrong.
    """
    if primary_type in _STORM_SPELL_TYPES:
        return None
    for line in (oracle_text or "").split("\n"):
        normalized = normalize_creature_line(line)
        if storm_instances(normalized):
            return normalized
    return None


def spells_cast_before(game, item) -> int | None:
    """How many spells were cast this turn before *item* was — every player's,
    from any zone, countered or not (CR 702.40a), or None when *item*'s cast is
    not on this turn's record.

    The position of *item* in the turn's cast record
    (``damage_ledger.ledger(game).casts``, appended at the one site that puts a
    spell on the stack, oldest first), found by identity: two casts of one card
    are one ``CardDefinition`` and two stack objects. A copy is never on the
    record (CR 707.10: it is not cast), which is why it neither counts nor is
    counted.
    """
    from .damage_ledger import ledger

    if item is None:
        return None
    for position, entry in enumerate(ledger(game).casts):
        if entry.item is item:
            return position
    return None


def copies_for_each(game, counted: str, copied) -> int | None:
    """How many copies a ``copy_triggering_spell`` whose ``for_each`` names
    *counted* makes of *copied*, or None when the count cannot be read.

    One reader for the payload key, so a second count ("for each permanent put
    into a graveyard from the battlefield this turn", Gravestorm) is a row here
    rather than a branch in the handler. A key this does not know is None, and
    the handler copies nothing rather than guessing a number.
    """
    if counted == SPELLS_CAST_BEFORE_IT:
        return spells_cast_before(game, copied)
    return None


__all__ = [
    "SPELLS_CAST_BEFORE_IT",
    "STORM_LABEL",
    "STORM_RULES_TEXT",
    "copies_for_each",
    "is_storm",
    "spells_cast_before",
    "storm_instances",
    "storm_instruction",
    "storm_triggers",
    "unread_storm_line",
]
