"""Flanking (CR 702.25), the keyword and the triggered ability it *is*.

CR 702.25a does not describe flanking, it **defines** it: "Flanking" means
"Whenever this creature becomes blocked by a creature without flanking, the
blocking creature gets -1/-1 until end of turn." So this module is the rewrite
``engine/rampage.py`` and ``engine/cumulative_upkeep.py`` established — the
printed keyword line becomes the ability the rules say it already is, and from
there the existing becomes-blocked dispatcher in
``engine/phases/declare_blockers_step.py`` fires it, the stack carries it, and
one handler resolves it. Nothing downstream of the compiler knows the word.

**The "without flanking" half is a filter, not a special case.** It lowers to
the ordinary ``blocker_filter`` payload every printed "becomes blocked by a
<noun>" already produces, with ``without_keywords``, which
``subject_filters.subject_matches`` answers through ``Game._has_keyword`` —
CR 613 layer 6, so a creature that *gained* flanking this turn is exempt and one
that lost it is not. That is also what makes the dispatcher fire this per
blocking creature rather than once for the block (CR 509.3d): the narrowing is
printed, so the per-creature half of CR 509.3c/d applies.

**Flanking is line-derived, and unusually it needs the word too.** Three Mirage
cards read it three different ways — Agility *grants* it to the enchanted
creature, Barbed Foliage *removes* it from an attacker, and Telim'Tor buffs
"attacking creatures **with** flanking" — so the ability and the word have to
travel together. They do, and the mechanism is already built: a grant of a
line-derived keyword grants the printed *line*
(``keywords.LINE_DERIVED_KEYWORDS``, because layer 6's word set holds no
triggered ability), ``Permanent.effective_card`` folds that line into the rules
text, the compiler makes the trigger out of it — and ``layer_bridge``'s
``_TEXT_KEYWORDS`` scan over the compiled keyword lines puts "flanking" back in
the ability set, so the *next* flanker's filter sees it. Rampage takes the same
two channels for the same reason; what is new here is that a card in the pool
exercises all three directions of it.

CR 702.25b — several instances of flanking each trigger separately — is why
:func:`flanking_instances` counts them rather than collapsing them to a flag.
Two abilities go on the stack and each may be responded to on its own, and the
second one's -1/-1 is applied to a creature the first has already shrunk.
"""

from __future__ import annotations

from .oracle_types import (OracleInstruction, ParsedTriggeredAbility,
                           TriggerCondition)

#: The instruction one instance of flanking lowers to. Its payload is the
#: -1/-1 CR 702.25a prints, carried as data rather than baked into the handler
#: so the handler is the general "that creature gets +N/+N" for the block pair.
FLANKING_KIND = "pump_block_pair"

#: The bucket the support report puts it in. Carried here rather than added to
#: ``effect_labels.TRIGGERED_LABELS`` for the reason ``rampage.RAMPAGE_LABEL``
#: is: that table describes the abilities the **grammar** reads, and this one is
#: derived from a keyword line the grammar never sees, so an entry there would
#: read as dead to the guard that holds the table to the pool.
FLANKING_LABEL = "triggered_pump"

#: The word as it survives ``normalize_creature_line`` — lowercased, with the
#: reminder text already stripped. No argument, so the whole part is the word.
_FLANKING_PART = "flanking"


def is_flanking(part: str) -> bool:
    """Whether one normalized keyword-line part is flanking."""
    return part.strip() == _FLANKING_PART


def flanking_instances(keyword_line: str) -> int:
    """How many instances of flanking one comma-joined keyword line names.

    CR 702.25b makes each instance a separate triggered ability, so this counts
    rather than answering yes or no. "Flying, flanking" is one; a line naming
    the word twice is two, and each gets its own ability.
    """
    return sum(1 for part in keyword_line.split(",") if is_flanking(part))


def flanking_triggers(keyword_line: str) -> tuple[ParsedTriggeredAbility, ...]:
    """The triggered abilities CR 702.25a says *are* the flanking on this line.

    The condition is the same ``creature_becomes_blocked`` a printed "whenever
    this creature becomes blocked by a <noun>" produces, carrying the noun as
    ``blocker_filter`` — which is what makes the dispatcher fire it once per
    blocking creature (CR 509.3d) and bind that creature as the ability's
    target, so ``block_pair_permanents`` finds it at resolution.
    """
    return tuple(
        ParsedTriggeredAbility(
            source_line="flanking",
            condition=TriggerCondition(
                kind="creature_becomes_blocked",
                trigger="whenever",
                raw_text="whenever this creature becomes blocked by a creature without flanking",
                payload={
                    "blocker_filter": {
                        "type_filter": "creature",
                        "without_keywords": ["flanking"],
                    }
                },
            ),
            instruction=OracleInstruction(
                FLANKING_KIND, "flanking", {"power": -1, "toughness": -1}
            ),
            supported=True,
            effect_kind=FLANKING_LABEL,
        )
        for _ in range(flanking_instances(keyword_line))
    )


__all__ = [
    "FLANKING_KIND",
    "FLANKING_LABEL",
    "flanking_instances",
    "flanking_triggers",
    "is_flanking",
]
