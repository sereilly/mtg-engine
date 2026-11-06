"""Provoke (CR 702.39), the keyword and the triggered ability it *is*.

CR 702.39a does not describe provoke, it **defines** it: "Provoke" means
"Whenever this creature attacks, you may choose to have target creature
defending player controls block this creature this combat if able. If you do,
untap that creature." So this module is the rewrite ``engine/flanking.py`` and
``engine/rampage.py`` established — the printed keyword line becomes the
ability the rules say it already is, and from there the existing attack
dispatcher (``declare_attackers_step._fire_creature_attacks_triggers``) fires
it, CR 603.3d's announcement chooses its target, the stack carries it, and
ordinary instructions resolve it. Nothing downstream of the compiler knows the
word.

**Built from instructions the grammar already lowers**, so no handler here is
new:

* ``may`` — the "you may choose" (CR 702.39a), offered to the ability's
  controller as it resolves: the target is chosen as the ability is put on the
  stack (CR 603.3d) and the choice whether to use it is made on resolution;
* ``untap_target_permanent`` — the target, "target creature **defending player
  controls**", whose narrowing is the seat CR 506.2 names and the attack fire
  site freezes on the trigger (``trigger_defending_player_index``), so in a
  multi-defender game it is the player *this* creature attacks (CR 802);
* ``force_bound_to_block_until_eot`` aimed at the ability's source and scoped
  to **this combat** (``combat_permissions.PROVOKE_DURATION``) — "that
  creature" is the target the untap resolved (``bound_permanent``), and the
  requirement is CR 509.1c's, read with every other requirement by
  ``phases/block_requirements.py`` and swept by the end of combat step
  (``combat_permissions.MUST_BLOCK_ATTACKERS_THIS_COMBAT``).

The untap is written first and the requirement second, where the CR's
sentence names them the other way round ("…block this creature … If you do,
untap that creature"). Both happen in one resolution exactly when the "may" is
taken and nothing can observe the moment between them, so the order is the
one the bound-pronoun step needs: "that creature" reads the object the untap
recorded.

**Provoke is line-derived** (``keywords.LINE_DERIVED_KEYWORDS``), because
Hunter Sliver grants it: a grant of the word grants the printed line, the line
is folded into ``Permanent.effective_card``, and the compiler builds this
trigger out of it — the channel Agility's flanking already travels. The word
comes back through ``printed_characteristics._TEXT_KEYWORDS``.

CR 702.39b — several instances of provoke each trigger separately — is why
:func:`provoke_instances` counts rather than answering yes or no. Two Hunter
Slivers give every Sliver two provokes: two abilities go on the stack, each
chooses its own target, and each that is taken is its own requirement.
"""

from __future__ import annotations

from .combat_permissions import PROVOKE_DURATION
from .oracle_types import (OracleInstruction, ParsedTriggeredAbility,
                           TriggerCondition)

#: The bucket the support report puts it in. Carried here rather than added to
#: ``triggered_labels.TRIGGERED_LABELS`` for the reason
#: ``rampage.RAMPAGE_LABEL`` is: that table describes the abilities the
#: **grammar** reads, and this one is derived from a keyword line the grammar
#: never sees. ``triggered_combat`` is the existing word for a combat trigger
#: the controller may decline (("creature_becomes_blocked", "may") in that
#: module's by-condition table).
PROVOKE_LABEL = "triggered_combat"

#: The word as it survives ``normalize_creature_line`` — lowercased, with the
#: reminder text already stripped. No argument, so the whole part is the word.
_PROVOKE_PART = "provoke"

#: What one instance of provoke says, in the words Legions prints as its
#: reminder (CR 702.39a defines the same ability). For a reader that has to say
#: what the ability does where the card cannot: a provoke Hunter Sliver grants
#: is the bare word on the Sliver ("All Sliver creatures have provoke"), and the
#: offer it makes was worded "Provoke" with nothing after it.
PROVOKE_REMINDER = (
    "Whenever this creature attacks, you may have target creature defending "
    "player controls untap and block it if able."
)

#: "target creature defending player controls" as the grammar lowers it for an
#: untap (probe: "Whenever this creature attacks, you may untap target creature
#: defending player controls."), so the picker, the CR 608.2b gate and the
#: handler read the description every other such trigger carries.
_TARGET_FILTER = {"type_filter": "creature", "controller": "defending_player"}


def is_provoke(part: str) -> bool:
    """Whether one normalized keyword-line part is provoke."""
    return part.strip() == _PROVOKE_PART


def provoke_instances(keyword_line: str) -> int:
    """How many instances of provoke one comma-joined keyword line names.

    CR 702.39b makes each instance a separate triggered ability, so this counts
    rather than answering yes or no.
    """
    return sum(1 for part in keyword_line.split(",") if is_provoke(part))


def provoke_instruction() -> OracleInstruction:
    """The effect one instance of provoke resolves (CR 702.39a)."""
    untap = OracleInstruction(
        "untap_target_permanent", "",
        {
            **_TARGET_FILTER,
            "targets": {
                "quantifier": "target",
                "kind": "object",
                "filter": dict(_TARGET_FILTER),
            },
        },
    )
    compel = OracleInstruction(
        "force_bound_to_block_until_eot", "",
        {"attacker": "source", "duration": PROVOKE_DURATION},
    )
    return OracleInstruction("may", "", {"actor": "you", "action": (untap, compel)})


def provoke_triggers(keyword_line: str) -> tuple[ParsedTriggeredAbility, ...]:
    """The triggered abilities CR 702.39a says *are* the provoke on this line.

    The condition is the ``creature_attacks`` a printed "whenever this creature
    attacks" produces, so the attack fire site puts one on the stack per
    attacking creature that has it, frozen with the seat that creature attacks
    (CR 506.2, CR 603.10).
    """
    return tuple(
        ParsedTriggeredAbility(
            source_line=_PROVOKE_PART,
            condition=TriggerCondition(
                kind="creature_attacks",
                trigger="whenever",
                raw_text="whenever this creature attacks",
                payload={},
            ),
            instruction=provoke_instruction(),
            supported=True,
            effect_kind=PROVOKE_LABEL,
        )
        for _ in range(provoke_instances(keyword_line))
    )


__all__ = [
    "PROVOKE_LABEL",
    "PROVOKE_REMINDER",
    "is_provoke",
    "provoke_instances",
    "provoke_instruction",
    "provoke_triggers",
]
