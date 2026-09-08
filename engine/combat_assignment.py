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

#: "X target blocked creatures assign their combat damage this turn **as
#: though they weren't blocked**." (Outmaneuver.) CR 510.1a's assignment to
#: the blocking creatures replaced, for a turn, by CR 510.1b's assignment to
#: the player being attacked.
#:
#: Named here beside the mark above because both are answers to "how does this
#: creature assign?" and the combat damage step reads them at the same moment —
#: but they are not the same answer and this one is not read by
#: :func:`combat_damage_assigned_by`, because the *amount* is unchanged. What
#: changes is where it goes, which only the step knows.
#:
#: **Its own key beside the "may" one** Garruk, Savage Herald grants
#: (``assign_combat_damage_as_unblocked_until_eot``). The two look identical at
#: the damage step and are not: that one is an offer, and the step answers it
#: yes only where no explicit per-blocker assignment was given — which is how
#: a player declines it. This is a *restriction*, so declining is exactly what
#: must not be possible, and one key for both would make Outmaneuver optional
#: for whoever bothered to assign.
#:
#: Swept with the turn by ``engine/mixins/_constants.py``.
MUST_ASSIGN_AS_UNBLOCKED = "must_assign_combat_damage_as_unblocked_until_eot"

#: "Target unblocked attacking creature **becomes blocked**." (Dazzling Beauty;
#: CR 509.1h.) Named here rather than beside the combat maps because the maps
#: record *who blocks whom*, and this is precisely the state CR 509.1h says a
#: creature can be in with no blockers at all — the one an attacker is left in
#: when its blockers leave combat.
#:
#: A mark on the permanent, not an entry in a combat map. The maps are keyed by
#: battlefield slot and have to be renumbered whenever anything leaves; this
#: travels with the permanent and dies with it, which CR 400.7 gives for free.
#:
#: Swept by the **end of combat** step, not by cleanup: a turn may hold a second
#: combat phase (Relentless Assault), and a creature this blocked in the first
#: one is a fresh attacker in the second.
BLOCKED_WITHOUT_BLOCKERS = "blocked_without_blockers_this_combat"


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
