"""The combat damage step's wait for Butcher Orgg's division (CR 510.1).

"You may assign this creature's combat damage divided as you choose among
defending player and/or any number of creatures they control." The division
itself — its gate, its events, its carrying over to a second step — is
``engine/combat_assignment.py``'s and the damage step's
(``_assign_attacker_combat_damage`` reads ``divided_among``). This module is
the one thing that was missing: **a person who controls such an attacker is
asked before the damage is dealt**. Without it the step resolved as it was
entered for an unblocked or single-blocked Orgg — the offer declined over the
head of the only player allowed to take it — and stopped for a double-blocked
one only because two blockers already demanded a division.

A twin of :meth:`~engine.phases.combat_damage_assignment.CombatDamageAssignmentMixin.unblocked_assignments_to_ask`,
and read by the same two questions that one is
(``_needs_manual_damage_assignment``, which stops the step, and
``_manual_assignment_has_declared_multiblock``, which tells the web layer a
dialog can surface it). Like that one it turns on **who is sitting there**:
a seat nobody asks is answered as the step resolves, by the one chooser the
simulator, the engine's auto-resolve and the web's AI seat share
(``ai_combat.choose_combat_damage_announcement``, which takes the division
where the creatures it kills are worth more than the damage to the player),
so an AI or headless combat resolves without a stop nobody would answer.

Kept beside the damage step rather than in it: that module is at the band
under the 2,000-line cap, and this is a subject of its own — which attackers
a person is asked about, not how damage is dealt.
"""

from __future__ import annotations

from ..combat_assignment import (DEFENDING_PLAYER_SHARE,
                                 combat_damage_assigned_by,
                                 divided_among_defenders_refusal,
                                 may_divide_among_defenders)


class DividedDamageWaitMixin:
    def divided_assignment_offers(self) -> list[int]:
        """The attackers whose controller may divide their combat damage among
        the defending player and that player's creatures **right now**,
        ascending by battlefield slot — seat-blind.

        "Right now" is the gate's own answer
        (``combat_assignment.divided_among_defenders_refusal``) to the plainest
        division there is, all of it to the player: so never an attacker the
        defending player assigns (CR 702.22j), one blocked with nothing left
        blocking it ("it won't be able to deal combat damage and you won't be
        able to use its ability", ruling 2004-10-04), or one that assigns no
        combat damage. The gate is the one reader of the rulings; this list
        asks it rather than restating them, so the dialog never offers a
        division the step refuses.
        """
        if self.current_step != "combat_damage" or self.combat_damage_resolved:
            return []
        active = self.active_player_index
        offered: list[int] = []
        for attacker_idx in sorted(self.combat_attackers):
            attacker = self.permanent_at(active, attacker_idx)
            if attacker is None or not may_divide_among_defenders(attacker):
                continue
            damage = combat_damage_assigned_by(attacker)
            if damage <= 0:
                continue
            if divided_among_defenders_refusal(
                self, attacker_idx, attacker, {DEFENDING_PLAYER_SHARE: damage}
            ) is not None:
                continue
            offered.append(attacker_idx)
        return offered

    def divided_assignments_to_ask(self, seat: int | None = None) -> list[int]:
        """The attackers of :meth:`divided_assignment_offers` that an
        **interactive** active player has to answer before combat damage can
        be assigned — or, with *seat* given, that seat's alone (the active
        player's or nobody's: the offer is the attacking player's, CR 510.1).

        The answer rides the assignment itself (``resolve_combat_damage``'s
        ``divided_among_defenders``): the attacker named there is the offer
        taken, left out is the offer declined. So, like the active player's
        "as though it weren't blocked", nothing is recorded in between and the
        list empties when the step (or its first-strike half) is dealt — and
        fills again for a second combat damage step (CR 510.4), which is
        assigned afresh.
        """
        active = self.active_player_index
        if not self.asks_a_person(active):
            return []
        if seat is not None and seat != active:
            return []
        return self.divided_assignment_offers()


__all__ = ["DividedDamageWaitMixin"]
