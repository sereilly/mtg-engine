"""How much combat damage a creature assigns (CR 510.1).

Ordinarily the answer is its power, and every site in the combat damage step
read ``permanent.effective_power`` to get it. "This creature assigns no combat
damage this turn" (Floral Spuzzem) is the first printed sentence that makes the
answer something else, and it is *not* any of the three mechanisms it resembles:

* not a prevention shield (CR 615) — nothing is prevented, because nothing is
  ever assigned, so no shield counter is spent and no "if damage would be
  dealt" replacement ever sees an event;
* not a P/T change (CR 613 layer 7) — the creature keeps its power for what a
  lord counts, for what "power 3 or greater" matches, and for the noncombat
  damage its own abilities deal;
* not a combat restriction (CR 506) — the creature still attacks, is still
  blocked, and still *receives* combat damage.

So the rule is one function with four callers rather than a flag tested at each
of the four sites the step assigns from — an attacker to its blockers, an
attacker to the player it is attacking, a blocker to the creature it blocks, and
a blocker to one member of a band. A flag read at three of four is the shape
this repo keeps finding: the card works everywhere anyone tested and quietly
does nothing at the fourth.

The mark is per-turn, held on the permanent's metadata and swept with the rest
of the turn's marks by the cleanup step (``engine/mixins/_constants.py``). It
travels with the permanent and dies with it, which CR 400.7 gives for free.
"""

from __future__ import annotations

#: "This creature assigns no combat damage this turn." (Floral Spuzzem.)
ASSIGNS_NO_COMBAT_DAMAGE = "assigns_no_combat_damage_until_eot"


def combat_damage_assigned_by(permanent) -> int:
    """How much combat damage *permanent* assigns this step (CR 510.1a).

    Its power, or zero while it is marked as assigning none. Never negative:
    CR 510.1a assigns damage equal to power and a creature with negative power
    assigns none, which every caller already relied on by testing ``<= 0``.
    """
    if permanent.metadata.get(ASSIGNS_NO_COMBAT_DAMAGE):
        return 0
    return max(0, permanent.effective_power)


__all__ = ["ASSIGNS_NO_COMBAT_DAMAGE", "combat_damage_assigned_by"]
