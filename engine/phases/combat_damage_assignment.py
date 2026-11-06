"""Combat damage assignment (CR 510.1): who divides a creature's combat
damage, what a division may say, and where every point goes.

The half of the combat damage step that can **refuse** (``combat_damage_step``
explains the seam): a negative amount, a trampler holding back lethal, a
blocker dividing less than its power — each is turned down here while nothing
has been dealt. In this mixin: the band and blocker lookups (CR 702.22j/k); who
assigns an attacker's damage (``combat_damage_assigner`` — the defending player
under banding or Defensive Formation, CR 510.1a); the one gate a division is
checked by (``_attacker_division_refusal``, CR 510.1c-e) and the default
division; the defending player's banding and multiblock assignments; the "as
though it weren't blocked" announcement (CR 510.1c); whether a manual
assignment is needed at all, and the automatic one; and
``_assign_attacker_combat_damage``, which records where each attacker's damage
goes and deals none of it. The strike passes (CR 510.4) and the dealing
(CR 510.2) are the step's.

Composed onto :class:`~engine.game.Game` beside ``CombatDamageStepMixin``;
split out of ``combat_damage_step.py`` at the size band (round kg3).
"""

from __future__ import annotations

from ..combat_assignment import (DEFENDER_ANNOUNCED_THIS_STEP,
                                 DEFENDER_ASSIGNS_AS_UNBLOCKED,
                                 MUST_ASSIGN_AS_UNBLOCKED,
                                 combat_damage_assigned_by,
                                 divided_among_defenders_events,
                                 divided_among_defenders_refusal,
                                 may_assign_as_unblocked)
from ..models import Permanent


def _lethal_damage(blocker: Permanent, deathtouch: bool) -> int:
    """Lethal damage for *blocker* in an attacker's assignment (CR 702.19b):
    its toughness less the damage already marked on it — and any nonzero
    amount from a source with deathtouch (CR 702.2c)."""
    need = max(0, blocker.effective_toughness - blocker.damage_marked)
    if deathtouch and need > 0:
        return 1
    return need


class CombatDamageAssignmentMixin:
    def _attacker_band(self, attacker_idx: int) -> list[int] | None:
        for band in self.combat_bands:
            if attacker_idx in band:
                return band
        return None

    def _attacker_all_blockers(self, attacker_idx: int) -> list[int]:
        """Every creature blocking an attacker, including band-propagated blocks."""
        blockers = set(self._combat_blockers_for_attacker(attacker_idx))
        blockers.update(self.combat_band_blocks.get(attacker_idx, []))
        return sorted(blockers)

    def _defender_assigns_attacker_damage(self, attacker_idx: int) -> bool:
        """Whether the **defending** player divides this attacker's damage.

        Two rules give the same answer, and this is the one reader both the
        damage step and ``web/combat_prompts.py`` ask — the property
        :meth:`_attacker_blocked_by_banding` below already documents about
        itself, kept as one question now that a second rule reaches it: what a
        player is offered to divide and what the step then honours must be one
        set of attackers.

        CR 702.22j is the band. CR 510.1a's "rather than the attacking player"
        (Defensive Formation) is the other, and it is not a property of the
        *blockers* at all — it is a permanent the defending player controls, so
        it reaches every attacker aimed at that seat, banded or not.
        """
        if self._attacker_blocked_by_banding(attacker_idx):
            return True
        from ..combat_assignment import defender_assigns_all_damage

        defending_index = self.combat_attackers.get(attacker_idx)
        return (
            isinstance(defending_index, int)
            and defender_assigns_all_damage(self, defending_index)
        )

    def _attacker_blocked_by_banding(self, attacker_idx: int) -> bool:
        """CR 702.22j: does the **defending** player divide this attacker's damage?

        Two ways the rule reaches, and the second is the one "bands with other"
        adds: the attacker is blocked "by a creature with banding, **or** by
        both a [quality] creature with 'bands with other [quality]' and another
        [quality] creature". A pair inside the blocking set, not every blocker —
        a third blocker of some unrelated type does not take the division back.

        One answer for the whole engine and the web layer both: the prompt that
        offers the division reads this, so what a player is asked to divide and
        what the damage step then honours cannot be two different sets of
        attackers.
        """
        from ..banding import bands_with_other_pair

        defending_index = self.combat_attackers.get(attacker_idx)
        if defending_index is None or not (0 <= defending_index < len(self.players)):
            return False
        defender = self.players[defending_index]
        blockers = [
            defender.battlefield[blocker_idx]
            for blocker_idx in self._attacker_all_blockers(attacker_idx)
            if 0 <= blocker_idx < len(defender.battlefield)
        ]
        if any(self._creature_has_banding(blocker) for blocker in blockers):
            return True
        return bands_with_other_pair(self, blockers)

    def combat_damage_assigner(self, attacker_idx: int) -> int | None:
        """The seat that announces how this attacker assigns its combat damage
        (CR 510.1) — or None when the slot is not one of this combat's
        attackers.

        The active player, unless the defending player assigns it instead
        (CR 702.22j, or a printed substitution — see
        :meth:`_defender_assigns_attacker_damage`). **This is the answer the
        client is sent** (``get_combat_state``'s ``damage_assigned_by``): it
        used to work the answer out for itself, from one blocker's keyword
        line, while the server also counted "bands with other" pairs and
        Defensive Formation — so a legendary band's division, or any division
        under that enchantment, was offered to the attacking player by a dialog
        the server then refused.
        """
        if attacker_idx not in self.combat_attackers:
            return None
        if self._defender_assigns_attacker_damage(attacker_idx):
            return self.combat_attackers[attacker_idx]
        return self.active_player_index

    def _attacker_division_refusal(
        self,
        attacker_idx: int,
        requested: dict[int, int],
        *,
        offered: bool = False,
    ) -> str | None:
        """Why *requested* is not a legal division of this blocked attacker's
        combat damage among the creatures blocking it — or None when it is one.

        **One check, three readers**: the damage step, for whichever seat's
        division it is about to deal; :meth:`assign_banding_combat_damage`,
        when a defending player announces theirs; and the question "is the
        division this seat announced earlier still an announcement?", asked
        again when a second combat damage step has changed what it divides
        among. It was written out twice — once per seat — and the two had
        drifted: the defending player's copy required all of the damage to be
        assigned and never asked about trample's lethal damage, and the active
        player's asked about trample and required nothing at all, so a creature
        with three power blocked by two could announce one and none and two
        points of combat damage went nowhere.

        The rules it holds:

        * CR 510.1c — "A blocked creature assigns its combat damage to the
          creatures blocking it": **to them** (an amount on any other creature
          is refused rather than dropped), and **its combat damage** — all of
          it. With two or more blockers it is "divided as its controller
          chooses among them", which chooses the shares and not the total.
        * CR 510.1a — the total is the creature's power, never more.
        * CR 702.19b — trample is the one way some of it may go elsewhere: the
          excess over lethal damage to *each* blocker, to the player or
          planeswalker being attacked. So a trampler may leave a remainder, and
          only once every blocker has been assigned lethal damage.

        *offered* is whether this attacker also had "as though it weren't
        blocked" to choose from, and changes only the sentence: for that
        creature an under-assignment is a third answer its card does not print.

        Nothing here asks whether the creature strikes in the step being
        resolved (CR 510.4) — a creature that is not assigning has announced
        nothing, and its caller skips it.
        """
        defending_index = self.combat_attackers.get(attacker_idx)
        attacker = self.permanent_at(self.active_player_index, attacker_idx)
        if attacker is None or defending_index is None:
            return "that creature is not attacking"
        if not (0 <= defending_index < len(self.players)):
            return "that creature is not attacking a player"
        defender = self.players[defending_index]
        name = attacker.card.name
        assignable = combat_damage_assigned_by(attacker)
        blockers = [
            blocker_idx
            for blocker_idx in self._attacker_all_blockers(attacker_idx)
            if 0 <= blocker_idx < len(defender.battlefield)
        ]
        amounts = {int(slot): int(amount) for slot, amount in requested.items()}
        if any(amount < 0 for amount in amounts.values()):
            return "combat damage assignment cannot be negative"
        has_trample = self._has_keyword(attacker, "trample")
        has_deathtouch = self._has_keyword(attacker, "deathtouch")
        total = 0
        under_lethal = False
        for blocker_idx in blockers:
            amount = amounts.get(blocker_idx, 0)
            blocker = defender.battlefield[blocker_idx]
            lethal = _lethal_damage(blocker, has_deathtouch)
            if amount < lethal:
                under_lethal = True
            total += amount
        if total > assignable:
            return "assigned combat damage exceeds attacker power"
        strays = sorted(
            slot for slot, amount in amounts.items()
            if amount > 0 and slot not in blockers
        )
        if strays:
            return (
                f"{name} assigns its combat damage only to the creatures "
                "blocking it (CR 510.1c)"
            )
        if not blockers:
            # CR 510.1c: "If no creatures are currently blocking it … it
            # assigns no combat damage." Nothing to divide and nothing owed.
            return None
        if total < assignable:
            if not has_trample:
                if offered:
                    return (
                        f"{name} assigns all of its combat damage to the "
                        "creatures blocking it or all of it as though it "
                        "weren't blocked"
                    )
                return (
                    f"{name} assigns all of its combat damage among the "
                    "creatures blocking it (CR 510.1c)"
                )
            if under_lethal:
                return "trample requires lethal damage assigned to each blocker"
        return None

    def _default_attacker_division(self, attacker_idx: int) -> dict[int, int]:
        """The engine's own division of one blocked attacker's combat damage
        among the creatures blocking it — the default a seat that is not asked
        is given, and the only one where there is no choice (CR 510.1c: "If
        exactly one creature is blocking it, it assigns all its combat damage
        to that creature").

        One blocker takes all of it (only lethal from a trampler, so the rest
        can trample over). Several are assigned lethal damage in slot order
        until the power runs out, and what is left goes onto the last one that
        got lethal — which kills as many as the power allows. A heuristic, and
        the attacker's rather than the defender's: any division
        :meth:`_attacker_division_refusal` accepts is as legal.
        """
        attacker = self.permanent_at(self.active_player_index, attacker_idx)
        defending_index = self.combat_attackers.get(attacker_idx)
        if attacker is None or defending_index is None:
            return {}
        defender = (
            self.players[defending_index]
            if 0 <= defending_index < len(self.players)
            else None
        )
        blockers = self._attacker_all_blockers(attacker_idx)
        if not blockers:
            return {}
        has_trample = self._has_keyword(attacker, "trample")
        has_deathtouch = self._has_keyword(attacker, "deathtouch")

        def lethal_for(blocker_idx: int) -> int:
            if defender is None or blocker_idx >= len(defender.battlefield):
                return 0
            return _lethal_damage(defender.battlefield[blocker_idx], has_deathtouch)

        if len(blockers) == 1:
            blocker_idx = blockers[0]
            assign = combat_damage_assigned_by(attacker)
            # For trample assign only lethal to the blocker; the remainder
            # flows to the defending player via the existing trample logic.
            if has_trample:
                assign = min(assign, lethal_for(blocker_idx))
            return {blocker_idx: assign}

        # Multiple blockers: walk them in index order assigning lethal to each
        # until the attacker runs out of power, then dump the remainder on the
        # last blocker that received lethal.
        power_left = combat_damage_assigned_by(attacker)
        per_blocker: dict[int, int] = {}
        last_lethal_idx: int | None = None
        exhausted = False
        for blocker_idx in blockers:
            if exhausted:
                per_blocker[blocker_idx] = 0
                continue
            need = lethal_for(blocker_idx)
            if need <= power_left:
                per_blocker[blocker_idx] = need
                power_left -= need
                last_lethal_idx = blocker_idx
            else:
                # Can't kill this blocker — assign the remainder here (the legal
                # sub-lethal breakpoint) and stop assigning to later blockers.
                per_blocker[blocker_idx] = power_left
                power_left = 0
                exhausted = True
        # Dump any leftover power onto the last blocker we killed (now > lethal,
        # still legal). Tramplers keep the leftover so it spills to the defender.
        if power_left > 0 and not has_trample and last_lethal_idx is not None:
            per_blocker[last_lethal_idx] += power_left
        return per_blocker

    def _defender_assignment_recorded(self, attacker_idx: int) -> bool:
        """Whether the defending player's announcement for this attacker is on
        record **for the combat damage step about to be resolved** — their
        division among its blockers, or "as though it weren't blocked".

        "For this step" is :data:`~engine.combat_assignment.
        DEFENDER_ANNOUNCED_THIS_STEP`: the step that deals an attacker's damage
        clears it, so a double striker's second step (CR 510.4) asks again.

        A division is on record only while it is still a division: if what it
        divides among has changed since it was announced (a blocker left in the
        window between two combat damage steps), it is the announcement of a
        board that no longer exists. Counting it would have the step refuse the
        *active* player's resolution for a fault only the defending player can
        mend, with nothing asking them to.
        """
        attacker = self.permanent_at(self.active_player_index, attacker_idx)
        if attacker is None:
            return False
        if not attacker.metadata.get(DEFENDER_ANNOUNCED_THIS_STEP):
            return False
        if attacker.metadata.get(DEFENDER_ASSIGNS_AS_UNBLOCKED):
            return True
        return self._defender_division_stands(attacker_idx)

    def _defender_division_stands(self, attacker_idx: int) -> bool:
        """Whether the defending player's division for this attacker — the
        last one they gave this combat — is still a legal division of it.

        Asked by the damage step, which deals a standing division in whichever
        step the attacker assigns in: an answer given once is that seat's
        answer until it gives another, so a combat nobody is sitting at
        replays it for a double striker's second step where it still divides
        all of the damage among the creatures still blocking.
        """
        stored = self.combat_banding_damage.get(attacker_idx)
        if stored is None:
            return False
        return self._attacker_division_refusal(attacker_idx, stored) is None

    def defender_assignments_owed(self, defender_index: int | None = None) -> list[int]:
        """The attackers a **defending** player assigns the combat damage of,
        has a decision about, and has not yet announced for this step —
        ascending by battlefield slot, for one defending seat or for all.

        Whether there is a decision is the same test the active player's own
        dialog applies: two or more creatures blocking is a division, and one
        is a decision only for an attacker that "may … assign its combat damage
        as though it weren't blocked", where the choice is this seat's
        (:meth:`unblocked_assignment_chooser`). A single creature with banding
        in front of an ordinary attacker is none — all of the damage goes to
        it whoever says so.

        **Seat-blind, like every other reason the step stops**: whether
        somebody is sitting there to be asked is the web layer's question, and
        :meth:`unblocked_assignments_to_ask` is the one arm that puts it to
        the engine. ``web/combat_prompts.py`` reads this list — it used to
        rebuild it from the wire payload and required two blockers, which is
        how a Thorn Elemental blocked by one Benalish Hero went unasked.

        **A trampler in front of one blocker** (CR 702.19b) is a decision
        too, for every defending seat: lethal to the blocker and the rest to
        this seat, or more of it to the blocker. It was listed only for a
        defending player sitting there, so a seat nobody sits in was handed
        nothing and kept the engine's default — the rest to itself, which is
        the *attacker's* split — while the AI's chooser would keep all of it
        on a blocker that dies of lethal damage anyway
        (``ai_combat.choose_defender_damage_assignment``). Whether the step
        *stops* for it is still only a person's question
        (:meth:`trample_assignments_to_ask`).
        """
        owed: list[int] = []
        for attacker_idx in sorted(self.combat_attackers):
            seat = self.combat_attackers[attacker_idx]
            if defender_index is not None and seat != defender_index:
                continue
            if not self._defender_assigns_attacker_damage(attacker_idx):
                continue
            attacker = self.permanent_at(self.active_player_index, attacker_idx)
            if attacker is None or combat_damage_assigned_by(attacker) <= 0:
                continue
            # Every creature blocking it, the ones its band spread onto it
            # included (CR 702.22h) — what the division is among
            # (:meth:`_attacker_division_refusal`). Counting the declared
            # pairs alone, a band member with one declared blocker and one
            # spread onto it owed this seat nothing, and the default divided
            # it.
            blocking = self._attacker_all_blockers(attacker_idx)
            offered = (
                self.unblocked_assignment_chooser(attacker_idx) == seat
                or self._has_trample_choice(attacker_idx)
            )
            if len(blocking) < (1 if offered else 2):
                continue
            if self._defender_assignment_recorded(attacker_idx):
                continue
            owed.append(attacker_idx)
        return owed

    def assign_banding_combat_damage(
        self,
        defender_index: int,
        attacker_damage: dict[int, dict[int, int]],
        as_though_unblocked=None,
    ) -> tuple[bool, str]:
        """CR 702.22j: the defending player announces how each attacker whose
        combat damage *they* assign — one blocked by a creature with banding,
        or any attacker while they control "rather than the attacking player,
        you assign…" — assigns it.

        Held, and read by :meth:`resolve_combat_damage` in place of the active
        player's assignment for those attackers. The *announcement* is for one
        combat damage step — the step that deals an attacker's damage marks it
        unannounced again (CR 510.4: a second step is a second announcement,
        and a person is asked again) — while the answer itself stands as what
        this seat last said, which is what a seat nobody asks goes on saying.

        Two answers per attacker, the same two the active player has for their
        own:

        * an entry in ``attacker_damage`` — a division among the creatures
          blocking it, held to :meth:`_attacker_division_refusal`;
        * the attacker's ``permanent_id`` in ``as_though_unblocked`` — for a
          creature that "may … assign its combat damage as though it weren't
          blocked", the offer **taken by the defending player**, to whom the
          cards' ruling gives it (2018-04-27; see
          :data:`~engine.combat_assignment.DEFENDER_ASSIGNS_AS_UNBLOCKED`).
          Until this argument existed the answer was always "keep it on the
          blockers" and nobody was asked.

        Some of each for one attacker is refused — "You can't split the damage
        assignment between them." An attacker the announcement does not name
        keeps whatever was recorded for it, so two actions may answer two
        attackers.
        """
        if defender_index not in self.combat_defending_players():
            return False, "only the defending player may assign banding damage"
        divisions = {
            int(attacker_idx): {int(b): int(v) for b, v in (split or {}).items()}
            for attacker_idx, split in (attacker_damage or {}).items()
        }
        active = self.active_player_index
        sent_past: dict[int, Permanent] = {}
        for permanent_id in sorted({int(pid) for pid in (as_though_unblocked or ())}):
            attacker = self.permanent_by_id(permanent_id)
            attacker_idx = (
                self.battlefield_index_of(attacker)
                if attacker is not None and self.controls(active, attacker)
                else None
            )
            if attacker_idx is None or attacker_idx not in self.combat_attackers:
                return False, "that creature is not attacking"
            if self.combat_attackers.get(attacker_idx) != defender_index:
                return False, "that attacker isn't attacking this player"
            name = attacker.card.name
            chooser = self.unblocked_assignment_chooser(attacker_idx)
            if chooser is None:
                return False, (
                    f"{name} can't assign its combat damage as though it "
                    "weren't blocked"
                )
            if chooser != defender_index:
                return False, (
                    f"the attacking player assigns {name}'s combat damage"
                )
            if any(amount > 0 for amount in divisions.get(attacker_idx, {}).values()):
                return False, (
                    f"{name} assigns all of its combat damage to the creatures "
                    "blocking it or all of it as though it weren't blocked, "
                    "not some of each"
                )
            sent_past[attacker_idx] = attacker
        for attacker_idx, split in divisions.items():
            if attacker_idx in sent_past:
                continue
            if self.combat_attackers.get(attacker_idx) != defender_index:
                return False, "that attacker isn't attacking this player"
            if not self._defender_assigns_attacker_damage(attacker_idx):
                return False, (
                    "the attacking player assigns this attacker's damage"
                )
            if self.permanent_at(active, attacker_idx) is None:
                return False, "attacker index out of range"
            refusal = self._attacker_division_refusal(
                attacker_idx, split,
                offered=self.unblocked_assignment_chooser(attacker_idx) == defender_index,
            )
            if refusal is not None:
                return False, refusal
        # Nothing is written until the whole announcement has been accepted
        # (CR 510.1e), and each attacker holds exactly one of the two answers.
        for attacker_idx, split in divisions.items():
            if attacker_idx in sent_past:
                continue
            self.combat_banding_damage[attacker_idx] = dict(split)
            attacker = self.permanent_at(active, attacker_idx)
            if attacker is not None:
                attacker.metadata.pop(DEFENDER_ASSIGNS_AS_UNBLOCKED, None)
                attacker.metadata[DEFENDER_ANNOUNCED_THIS_STEP] = True
        for attacker_idx, attacker in sent_past.items():
            self.combat_banding_damage.pop(attacker_idx, None)
            attacker.metadata[DEFENDER_ASSIGNS_AS_UNBLOCKED] = True
            attacker.metadata[DEFENDER_ANNOUNCED_THIS_STEP] = True
        return True, "banding damage assignment recorded"

    def assign_multiblock_blocker_damage(
        self,
        defender_index: int,
        blocker_damage_split: dict[int, dict[int, int]],
    ) -> tuple[bool, str]:
        """CR 510.1d: the defending player pre-commits how each of their creatures
        that blocks two or more attackers (Two-Headed Giant of Foriys) divides its
        combat damage among them.

        Stored and consumed by :meth:`resolve_combat_damage` when the resolving
        caller supplies no explicit ``blocker_damage_split`` for that blocker.
        """
        if defender_index not in self.combat_defending_players():
            return False, "only the defending player may divide blocker damage"
        defender = self.players[defender_index]
        own_blockers = self.combat_blockers.get(defender_index, {})
        for b_idx, split in blocker_damage_split.items():
            b_idx = int(b_idx)
            if not (0 <= b_idx < len(defender.battlefield)):
                return False, "blocker index out of range"
            attackers = set(own_blockers.get(b_idx, ()))
            if len(attackers) < 2:
                return False, "that creature is not blocking multiple attackers"
            blocker = defender.battlefield[b_idx]
            total = 0
            for a_idx, amount in split.items():
                amount = int(amount)
                if amount < 0:
                    return False, "blocker damage cannot be negative"
                if amount > 0 and int(a_idx) not in attackers:
                    return False, "blocker damage assigned to a creature it isn't blocking"
                total += amount
            power = combat_damage_assigned_by(blocker)
            if total > power:
                return False, "assigned blocker damage exceeds blocker power"
            # CR 510.1d: the blocker assigns ALL its combat damage among the
            # attackers it blocks — dividing less than its power is illegal.
            if total < power:
                return False, "blocker must assign all of its combat damage"
        self.combat_multiblock_damage = {
            int(b): {int(a): int(v) for a, v in split.items()}
            for b, split in blocker_damage_split.items()
        }
        return True, "blocker damage division recorded"

    # -- "as though it weren't blocked" (CR 510.1b in place of CR 510.1c) -----

    def unblocked_assignment_chooser(self, attacker_idx: int) -> int | None:
        """The seat that answers "You may have this creature assign its combat
        damage as though it weren't blocked" for this attacker — or None where
        the sentence offers nothing.

        **One reader for who is asked, who is defaulted and whose announcement
        is believed.** The damage step, the default assignment, the "does the
        game stop here" test and ``web/combat_prompts.py`` all ask this, for the
        reason :meth:`_defender_assigns_attacker_damage` is one reader: an offer
        the prompt shows to one seat and the step takes from another is a
        choice somebody made for somebody else.

        None in four cases, each a reason the printed "may" is not open:

        * the creature is not an attacker, or is not **blocked** — CR 509.1h's
          sense, which a creature keeps after every creature blocking it has
          left, so a blocked creature with nobody in front of it is still
          offered (and CR 510.1c would otherwise have it assign nothing);
        * it carries no such sentence — printed (Lone Wolf, Thorn Elemental,
          Rhox, Pride of Lions) and granted (Garruk, Savage Herald's −7) are
          one question, :func:`~engine.combat_assignment.may_assign_as_unblocked`;
        * it is under the *mandatory* twin (Outmaneuver), which leaves nothing
          to decide.

        **Normally its controller, the active player** — CR 510.1: the active
        player announces how each attacking creature assigns. **The defending
        player instead where that player assigns this attacker's damage**
        (CR 702.22j's banding blocker, or Defensive Formation's printed
        substitution). That is the cards' own ruling rather than an inference:
        "If blocked by a creature with banding, the defending player decides
        whether or not the damage is assigned 'as though it weren't blocked'."
        (Thorn Elemental / Lone Wolf / Pride of Lions, 2018-04-27.) The offer
        is a way of *assigning*, so it travels with whoever assigns.
        """
        if attacker_idx not in self.combat_attackers:
            return None
        attacker = self.permanent_at(self.active_player_index, attacker_idx)
        if attacker is None:
            return None
        if not attacker.blocked and not self._attacker_all_blockers(attacker_idx):
            return None
        if attacker.metadata.get(MUST_ASSIGN_AS_UNBLOCKED):
            return None
        if not may_assign_as_unblocked(attacker):
            return None
        if self._defender_assigns_attacker_damage(attacker_idx):
            return self.combat_attackers[attacker_idx]
        return self.active_player_index

    def unblocked_assignments_to_ask(self, seat: int | None = None) -> list[int]:
        """The attackers whose "as though it weren't blocked" an **interactive**
        seat has to answer before combat damage can be assigned, ascending by
        battlefield slot — every such seat's, or with *seat* given, that
        seat's alone (which is what each seat's own dialog is built from).

        This is what makes the game *stop*. The step used to resolve a single
        block as it was entered, taking the offer on the attacker's behalf — so
        a person at the table could not kill the blocker instead — and stopped
        for two or more blockers only to demand a division among them, so the
        same person could not take the offer at all. One printed sentence, two
        answers, and which one a human was allowed depended on how many
        creatures blocked.

        Narrower than :meth:`unblocked_assignment_chooser` in three ways, each
        the difference between *having* the choice and being *asked* it:

        * **an interactive seat** — every other seat keeps the stated default
          (:meth:`_build_auto_damage_assignment`), which is what keeps an AI or
          headless combat resolving without a stop nobody would answer;
        * **a creature that assigns damage** (CR 510.1a) — one assigning none
          has nothing to send either way;
        * **something still blocking it** — with nobody left in front of it the
          other answer is CR 510.1c's "assigns no combat damage", which the
          default never picks and no table is stopped to be offered.

        **The defending player's version of the question is asked here too**,
        where that player assigns the attacker's damage (CR 702.22j, Defensive
        Formation) and is sitting at the table — the cards' ruling gives them
        the choice in as many words (2018-04-27). It used not to be: their
        unasked answer was "keep it on the blockers", and it was unasked every
        time, so a person defending with one Benalish Hero in front of a Thorn
        Elemental was never offered the seven damage to themself that would
        have kept the Hero alive. Theirs is asked once per step and then held
        (:meth:`assign_banding_combat_damage`), because they announce before
        the active player resolves; the active player's rides the assignment
        itself.
        """
        active = self.active_player_index
        asked: list[int] = []
        for attacker_idx in sorted(self.combat_attackers):
            chooser = self.unblocked_assignment_chooser(attacker_idx)
            if chooser is None or chooser not in self.interactive_seats:
                continue
            if seat is not None and chooser != seat:
                continue
            attacker = self.permanent_at(active, attacker_idx)
            if attacker is None or combat_damage_assigned_by(attacker) <= 0:
                continue
            if not self._attacker_all_blockers(attacker_idx):
                continue
            if chooser != active and self._defender_assignment_recorded(attacker_idx):
                continue
            asked.append(attacker_idx)
        return asked

    # -- trample in front of one blocker (CR 702.19b) --------------------------

    def _has_trample_choice(self, attacker_idx: int) -> bool:
        """Whether this attacker's trample leaves whoever assigns its combat
        damage a choice that CR 510.1c alone would not: it is blocked by
        **exactly one** creature and assigns **more than lethal** damage to it
        (CR 702.19b — lethal first, then "any excess damage is assigned as its
        controller chooses among those blocking creatures and the player,
        planeswalker, or battle the creature is attacking"). Seat-blind.

        Two or more blockers are a division already, owed to every seat;
        lethal or less leaves nothing to choose (all of it to the blocker). A
        deathtouch attacker's lethal is 1 (CR 702.2c). Never a creature whose
        damage goes past its blockers whatever is announced
        (:meth:`assigns_past_its_blockers`), nor one with nothing left to deal
        this combat (a first striker once the first-strike step is done,
        CR 510.4). A creature that deals its damage in the second step is
        still a choice during the first, as a division is: the step is not
        dealt past it unasked, and the second step asks again.
        """
        if self.current_step != "combat_damage" or self.combat_damage_resolved:
            return False
        if attacker_idx not in self.combat_attackers:
            return False
        attacker = self.permanent_at(self.active_player_index, attacker_idx)
        if attacker is None or not self._has_keyword(attacker, "trample"):
            return False
        if self.assigns_past_its_blockers(attacker_idx):
            return False
        blockers = self._attacker_all_blockers(attacker_idx)
        if len(blockers) != 1:
            return False
        defending_index = self.combat_attackers[attacker_idx]
        if not (isinstance(defending_index, int)
                and 0 <= defending_index < len(self.players)):
            return False
        blocker = self.permanent_at(defending_index, blockers[0])
        if blocker is None:
            return False
        if self.combat_first_strike_done and not self._participates_in_second_strike(attacker):
            return False
        lethal = _lethal_damage(blocker, self._has_keyword(attacker, "deathtouch"))
        return combat_damage_assigned_by(attacker) > lethal

    def trample_assignments_to_ask(self, seat: int | None = None) -> list[int]:
        """The tramplers whose combat damage an **interactive** seat assigns,
        with a choice to make (:meth:`_has_trample_choice`) that it has not
        yet announced, ascending by battlefield slot — every such seat's, or
        with *seat* given, that seat's alone.

        This is what makes the game *stop* for a trampler blocked by one
        creature. It resolved as the step was entered — lethal to the blocker,
        the rest to the player — so a person attacking with a 6/6 trampler
        into a 1/1 could not put more than one point on the blocker, though
        CR 702.19b gives them the excess "as its controller chooses among
        those blocking creatures and the player". The assignment gate always
        accepted that answer (``_attacker_division_refusal``); nothing asked.

        Interactive only, like :meth:`unblocked_assignments_to_ask`: every
        other seat keeps the stated default (``_default_attacker_division``,
        lethal to the blocker and the rest past it), which is what keeps an AI
        or headless combat resolving without a stop nobody would answer.

        Whoever **assigns** is asked (:meth:`combat_damage_assigner`): the
        active player, whose answer rides the assignment itself, or a
        defending player under banding or Defensive Formation (CR 702.22j),
        whose answer is held (:meth:`assign_banding_combat_damage`) — once per
        step, so one they have given is not asked again.
        """
        asked: list[int] = []
        for attacker_idx in sorted(self.combat_attackers):
            assigner = self.combat_damage_assigner(attacker_idx)
            if assigner is None or assigner not in self.interactive_seats:
                continue
            if seat is not None and assigner != seat:
                continue
            if not self._has_trample_choice(attacker_idx):
                continue
            if (
                assigner != self.active_player_index
                and self._defender_assignment_recorded(attacker_idx)
            ):
                continue
            asked.append(attacker_idx)
        return asked

    def _validate_unblocked_announcement(
        self,
        attacker_damage: dict[int, dict[int, int]],
        unblocked_ids: frozenset[int],
    ) -> tuple[bool, str]:
        """Hold "these creatures assign as though they weren't blocked" to the
        rule, before a point is dealt (CR 510.1e: an illegal assignment returns
        the game to the moment before it was announced).

        An id names a permanent, so three things can be wrong with one and all
        three used to be unsayable — the wire had no way to announce the offer
        at all, so nothing could announce it wrongly:

        * it is not one of this combat's attackers;
        * the offer is not that creature's, or not the active player's to take
          (:meth:`unblocked_assignment_chooser`) — an ordinary blocked creature
          sent past its blockers would be trample without the lethal damage;
        * it is announced *as well as* damage to the blockers. The sentence is
          all or nothing: "You can't split the damage assignment between
          them." (Thorn Elemental ruling, 2018-04-27.)

        A creature under Outmaneuver's mandatory twin is accepted: it assigns
        that way whatever anybody announces, so naming it is saying what is
        already true.
        """
        active = self.active_player_index
        for permanent_id in sorted(unblocked_ids):
            attacker = self.permanent_by_id(permanent_id)
            attacker_idx = (
                self.battlefield_index_of(attacker)
                if attacker is not None and self.controls(active, attacker)
                else None
            )
            if attacker_idx is None or attacker_idx not in self.combat_attackers:
                return False, "that creature is not attacking"
            name = attacker.card.name
            if attacker.blocked and attacker.metadata.get(MUST_ASSIGN_AS_UNBLOCKED):
                continue
            chooser = self.unblocked_assignment_chooser(attacker_idx)
            if chooser is None:
                return False, (
                    f"{name} can't assign its combat damage as though it "
                    "weren't blocked"
                )
            if chooser != active:
                return False, (
                    f"the defending player assigns {name}'s combat damage"
                )
            if any(int(v) > 0 for v in (attacker_damage.get(attacker_idx) or {}).values()):
                return False, (
                    f"{name} assigns all of its combat damage to the creatures "
                    "blocking it or all of it as though it weren't blocked, "
                    "not some of each"
                )
        return True, ""

    def assigns_past_its_blockers(self, attacker_idx: int) -> bool:
        """Whether this attacker's combat damage goes past the creatures
        blocking it **whatever is announced**: the mandatory "assign their
        combat damage this turn as though they weren't blocked" (Outmaneuver;
        Gurzigost's offer once answered yes, CR 510.1b).

        Such a creature's division among its blockers is no decision at all:
        :meth:`_assign_attacker_combat_damage` sends every point to the player
        or planeswalker it is attacking and discards whatever was announced. So
        it stops nobody (:meth:`_needs_manual_damage_assignment`), and the
        client's damage dialog leaves it out (``assigns_past_blockers`` on the
        combat payload). It did neither: Gurzigost blocked by four creatures
        opened a dialog asking for a division, and the six damage the person
        divided among the blockers went to the defending player.
        """
        attacker = self.permanent_at(self.active_player_index, attacker_idx)
        return bool(
            attacker is not None
            and attacker_idx in self.combat_attackers
            and attacker.metadata.get(MUST_ASSIGN_AS_UNBLOCKED)
        )

    def _needs_manual_damage_assignment(self) -> bool:
        """Return True when combat damage needs a player's assignment choice.

        That is any blocked attacker with 2+ blockers, any attacking band whose
        block propagated (CR 702.22h) so the active player must choose where each
        shared blocker's damage goes (702.22k), or any blocker blocking 2+
        attackers (Two-Headed Giant of Foriys) whose controller may divide its
        damage (CR 510.1d). Pure non-banding combat is unaffected, so AI
        auto-resolution keeps working unchanged.

        And one more, which is the only one that turns on **who is sitting
        there**: a blocked attacker whose "You may have this creature assign
        its combat damage as though it weren't blocked" an interactive active
        player has not answered (:meth:`unblocked_assignments_to_ask`). The
        other four are owed by the rules to whoever the seat is; this one has a
        default every non-interactive seat takes, so only a person stops it.
        A trampler in front of one blocker with more than lethal to assign
        (:meth:`trample_assignments_to_ask`, CR 702.19b) is the same kind.
        """
        if (
            self.unblocked_assignments_to_ask()
            or self.divided_assignments_to_ask()
            or self.trample_assignments_to_ask()
        ):
            return True
        if self.combat_band_blocks:
            return True
        for attacker_idx in self.combat_attackers:
            if self.assigns_past_its_blockers(attacker_idx):
                continue  # nothing to divide: it all goes past them
            if len(self._attacker_all_blockers(attacker_idx)) >= 2:
                return True
        for blocker_map in self.combat_blockers.values():
            for attacker_idxs in blocker_map.values():
                if len(set(attacker_idxs)) >= 2:
                    return True
        return False

    def _manual_assignment_has_declared_multiblock(self) -> bool:
        """True when some attacker is blocked by two or more creatures — the
        case the combat-damage dialog can surface to the active player.

        **Counting the creatures its band spread onto it** (CR 702.22h): the
        dialog groups an attacker's blockers from ``combat.band_blocks`` as well
        as the declared pairs, and the division is among all of them
        (:meth:`_attacker_division_refusal`). This counted the declared pairs
        alone, saying the dialog had no way to present the rest, so a Hill
        Giant banded with a Benalish Hero and blocked by two walls with no
        power — one declared on each member, no CR 702.22k choice to hold the
        step — was dealt the default division when the attacking player moved
        on, never asked. A band whose one shared blocker spread across it still
        leaves each member a single blocker, and nothing to divide.

        **Also True for an attacker the dialog asks about for another reason**:
        "as though it weren't blocked", owed by an interactive active player
        (:meth:`unblocked_assignments_to_ask`), which the dialog presents with
        one blocker as readily as with two. The name says "multiblock" because
        that was the only thing the dialog could show when it was written; what
        the web layer reads it for is the sentence above — *can the dialog
        surface this assignment* — and auto-resolving past an offer the dialog
        is showing is the defect this arm exists to stop.

        **And False for a division that is nobody's dialog's to show.** A
        multi-blocked attacker whose damage the *defending* player assigns
        (CR 702.22j) is not in the active player's dialog, and it is in the
        defending player's only while somebody sits there who has not answered
        yet. This answered True for any two declared blockers, so a person
        attacking into an AI's Benalish Hero and a second blocker reached a
        combat damage step with no dialog on either side and nothing that would
        resolve it — and two people did the moment the defender had answered.
        Where no dialog can surface it, the default stands and the web layer's
        auto-resolve is what this returning False permits.

        A trampler in front of one blocker (:meth:`trample_assignments_to_ask`)
        is surfaced by whichever dialog its assigner answers, with one blocker,
        as the offer is.
        """
        if (
            self.unblocked_assignments_to_ask()
            or self.divided_assignments_to_ask()
            or self.trample_assignments_to_ask()
        ):
            return True
        for attacker_idx in self.combat_attackers:
            if len(self._attacker_all_blockers(attacker_idx)) < 2:
                continue
            if self.assigns_past_its_blockers(attacker_idx):
                continue  # no dialog has anything to ask about it
            assigner = self.combat_damage_assigner(attacker_idx)
            if assigner == self.active_player_index:
                return True
            if (
                assigner in self.interactive_seats
                and not self._defender_assignment_recorded(attacker_idx)
            ):
                return True
        return False

    def _build_auto_damage_assignment(self, declining=()) -> dict[int, dict[int, int]]:
        """Build a sensible default damage assignment for every blocked attacker.

        *declining* is the battlefield slots of attackers whose "as though it
        weren't blocked" offer the caller turns down: each is given the
        division among its blockers any other blocked creature gets, which is
        the other printed answer (CR 510.1c). Empty is every offer taken, as
        it always was — `ai_combat.choose_combat_damage_assignment` is the
        caller that weighs the two.

        Single-blocked attackers assign their full power to that blocker (only
        lethal for tramplers, so the remainder can trample through). Multi-blocked
        attackers assign lethal to each blocker in index order and dump any leftover
        power onto the last blocker that received lethal. This is only a heuristic
        for the AI / auto-resolve path — it maximizes how many blockers die. The
        resolver no longer requires lethal-in-order (CR 510.1c), so a human attacker
        may freely override this with any legal division.

        The division itself is :meth:`_default_attacker_division`, one
        attacker at a time, so that a single attacker's default can be asked
        for on its own (the announcement that does not name it; the second
        combat damage step, where the first changed what it divides among).
        """
        if not self.combat_attackers:
            return {}
        attacker_controller = self.players[self.active_player_index]
        assignment: dict[int, dict[int, int]] = {}
        for attacker_idx in self.combat_attackers:
            if attacker_idx >= len(attacker_controller.battlefield):
                continue
            blockers = self._attacker_all_blockers(attacker_idx)
            if not blockers:
                continue
            # "You may have this creature assign its combat damage as though it
            # weren't blocked." (Lone Wolf; Garruk, Savage Herald's −7.) The
            # default is to **take** the offer, so this builder leaves the
            # attacker out entirely and the step's own branch sends the damage
            # past the blockers.
            #
            # It has to be here rather than only there, because the step reads
            # "no explicit per-blocker assignment" as the offer being accepted
            # and this function *is* an assignment: every caller that passed
            # None — the AI, the auto-resolve path, every test — had the offer
            # silently declined on its behalf. Garruk's grant has been in the
            # pool since M21 and did nothing on any of those paths; a caller
            # that names the blockers still declines, which is the half that
            # was already right.
            #
            # **Only where the offer is the active player's to take.** Where
            # the defending player assigns this attacker's damage (CR 702.22j,
            # Defensive Formation) the choice is theirs — the cards' ruling of
            # 2018-04-27 says so in as many words — and a defender who is not
            # asked keeps the damage on the blockers, so this builder gives the
            # attacker its ordinary division like any other blocked creature.
            # It asked the creature alone until then, and a Thorn Elemental
            # blocked by a Benalish Hero went past it on the attacker's say-so.
            if (
                attacker_idx not in declining
                and self.unblocked_assignment_chooser(attacker_idx) == self.active_player_index
            ):
                continue
            assignment[attacker_idx] = self._default_attacker_division(attacker_idx)
        return assignment

    def _validate_blocker_damage_split(
        self, blocker_damage_split: dict[int, dict[int, int]] | None
    ) -> tuple[bool, str]:
        """CR 702.22j/k: check an explicit division of a blocking creature's
        combat damage among the band members it blocks.

        Checked before a single point is dealt, because the dealing below marks
        damage as it goes: a bad entry has to be refused while there is still
        nothing to take back.

        NOTE(FFA scope gap): banding/multiblock division across 2+ *simultaneous*
        defenders isn't fully modeled (rare combo: banding/Two-Headed Giant of
        Foriys AND attack-multiple-players in the same combat) — the blocker
        index here is resolved against the first defender this combat, matching
        the single-defender behavior this validation always assumed.
        """
        if not blocker_damage_split:
            return True, ""
        split_defender_index = next(iter(self.combat_defending_players()), None)
        split_defender = (
            self.players[split_defender_index]
            if split_defender_index is not None
            else None
        )
        for b_idx, split in blocker_damage_split.items():
            if split_defender is None or not (0 <= b_idx < len(split_defender.battlefield)):
                return False, "blocker index out of range"
            own_blockers = self.combat_blockers.get(split_defender_index, {})
            if b_idx not in own_blockers:
                return False, "that creature is not blocking"
            split_blocker = split_defender.battlefield[b_idx]
            allowed = set(own_blockers.get(b_idx, ()))
            for blocked_attacker in own_blockers.get(b_idx, ()):
                allowed |= set(self._attacker_band(blocked_attacker) or ())
            total = 0
            for member_idx, amount in split.items():
                amount = int(amount)
                if amount < 0:
                    return False, "blocker damage cannot be negative"
                if amount > 0 and member_idx not in allowed:
                    return False, "blocker damage assigned to a creature it isn't blocking"
                total += amount
            power = combat_damage_assigned_by(split_blocker)
            if total > power:
                return False, "assigned blocker damage exceeds blocker power"
            # CR 510.1c/702.22j: the blocker assigns ALL its combat damage —
            # a division totalling less than its power is illegal.
            if total < power:
                return False, "blocker must assign all of its combat damage"
        return True, ""

    def _assign_attacker_combat_damage(
        self,
        attacker_damage: dict[int, dict[int, int]],
        run_first_pass: bool,
        has_first_strike_pass: bool,
        unblocked_ids: frozenset[int] = frozenset(),
        sent_past_blockers: list | None = None,
        divided_among: dict | None = None,
    ) -> tuple[bool, str, list[tuple[int, int, int, int]], list[tuple[int, int, Permanent]]]:
        """CR 510.1: work out where each attacker's combat damage goes, dealing
        none of it.

        Recording first and dealing after is what makes the step one
        simultaneous event (CR 510.2) and what lets an illegal assignment be
        refused before anything has been marked. Returns
        ``(ok, message, to_blockers, to_players)`` — ``(defending_idx,
        blocker_idx, damage, attacker_idx)`` and ``(defending_idx, damage,
        source_attacker, attacked_walker_id)`` respectively, where
        ``attacked_walker_id`` is None for an attack on the player and the
        planeswalker's ``permanent_id`` when the creature is attacking one
        (CR 510.1b: it assigns its damage to what it is attacking).
        """
        attacker_controller = self.players[self.active_player_index]
        to_blockers: list[tuple[int, int, int, int]] = []
        to_players: list[tuple[int, int, Permanent, int | None]] = []
        for attacker_idx in sorted(self.combat_attackers):
            defending_index = self.combat_attackers[attacker_idx]
            if defending_index < 0 or defending_index >= len(self.players):
                continue
            defender = self.players[defending_index]
            if attacker_idx < 0 or attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            # CR 510.1a: how much this creature assigns — its power, unless
            # something says it assigns none (Floral Spuzzem). One rule, read
            # at every site that assigns, because a flag tested at three of
            # four is a card that quietly works in the fourth.
            assignable = combat_damage_assigned_by(attacker)
            if assignable <= 0:
                continue
            if not self._strikes_in_pass(attacker, run_first_pass, has_first_strike_pass):
                continue

            blockers = self._attacker_all_blockers(attacker_idx)
            power_left = assignable
            # CR 510.1b: an unblocked creature assigns its damage to the player,
            # or to the planeswalker, it is attacking — recorded on the event so
            # the dealing half needs no second look at the combat maps.
            attacked_walker_id = self.combat_attacked_planeswalkers.get(attacker_idx)
            # CR 509.1h: a creature stays blocked after every creature blocking
            # it has left, and both sentences below are about a *blocked*
            # creature rather than about one with something in front of it.
            # They asked ``blockers`` until this round, so a blocked attacker
            # whose blocker was removed assigned nothing under either — against
            # Outmaneuver's own ruling (2008-04-01): "Creatures damage the
            # defending player or planeswalker even if the blocking creatures
            # are no longer there at that time."
            is_blocked = bool(blockers) or bool(attacker.blocked)
            # Butcher Orgg's offer taken (``divided_among``, by attacker id),
            # read first: blocked or not (ruling 2004-10-04) its whole damage
            # goes where the division says, held to CR 510.1e by
            # ``combat_assignment``'s gate. Not named is the offer declined.
            division = (divided_among or {}).get(attacker.permanent_id)
            if division is not None:
                refusal = divided_among_defenders_refusal(
                    self, attacker_idx, attacker, division
                )
                if refusal is not None:
                    return False, refusal, [], []
                creatures_hit, player_hit = divided_among_defenders_events(
                    self, attacker_idx, attacker, division
                )
                to_blockers.extend(creatures_hit)
                to_players.extend(player_hit)
                continue
            # "X target blocked creatures **assign their combat damage this
            # turn as though they weren't blocked**." (Outmaneuver.) The
            # CR 510.1b rewrite with no "may" in front of it, so it is read
            # *without* the escape the offer below carries: an explicit
            # per-blocker assignment is how a player declines Garruk's offer,
            # and this card gives them nothing to decline. Whatever the attacker
            # asked for is discarded, which is the restriction doing what it
            # says rather than what the attacker would prefer.
            if is_blocked and attacker.metadata.get(MUST_ASSIGN_AS_UNBLOCKED):
                to_players.append((defending_index, power_left, attacker, attacked_walker_id))
                if sent_past_blockers is not None:
                    sent_past_blockers.append(attacker)
                continue
            # "You may have this creature assign its combat damage as though it
            # weren't blocked." (Lone Wolf, printed; Garruk, Savage Herald's −7,
            # granted for the turn.) Through ``unblocked_assignment_chooser``,
            # which folds the granted mark and the printed static into one
            # offer and says whose it is.
            #
            # **Two announcements and a default**, where there was one reading
            # of an absence. Naming the creature in ``as_though_unblocked`` is
            # the offer taken; an entry for it in ``attacker_damage`` is the
            # other printed answer, CR 510.1c's assignment to the creatures
            # blocking it; and saying neither is the default — the offer taken,
            # as it has been for every seat that is not asked. The first is new:
            # the absence was the *only* way to accept, which is why a dialog
            # that has to say something about every attacker it shows could
            # never say yes.
            #
            # Where the defending player assigns this attacker's damage the
            # offer is theirs (see the chooser). They announce before the
            # active player's assignment is resolved, so their yes is *held* —
            # ``assign_banding_combat_damage`` marks the attacker — and their
            # unsaid answer is no: the damage stays on the creatures blocking
            # it. It used to be taken over their heads (a defender divided
            # seven damage among a band of blockers in a dialog and was then
            # dealt all seven), and then, for one round, could not be taken by
            # them at all.
            chooser = self.unblocked_assignment_chooser(attacker_idx)
            if chooser is not None:
                if chooser == self.active_player_index:
                    takes_offer = (
                        attacker.permanent_id in unblocked_ids
                        or attacker_idx not in attacker_damage
                    )
                else:
                    takes_offer = bool(
                        attacker.metadata.get(DEFENDER_ASSIGNS_AS_UNBLOCKED)
                    )
                if takes_offer:
                    to_players.append((defending_index, power_left, attacker, attacked_walker_id))
                    if sent_past_blockers is not None:
                        sent_past_blockers.append(attacker)
                    continue
            if not blockers:
                # A creature that was declared blocked (e.g. its blocker died to
                # first-strike damage) is still "blocked" — it cannot deal damage
                # to the defending player unless it has trample.
                if attacker.blocked and not self._has_keyword(attacker, "trample"):
                    continue
                to_players.append((defending_index, power_left, attacker, attacked_walker_id))
                continue

            # Whose division this is, in the order the rules settle it:
            #
            # * the **defending** player's, where that player assigns this
            #   attacker's damage (CR 702.22j, Defensive Formation) and has
            #   announced a division that is still one;
            # * the entry the **active** player's announcement gives it;
            # * and for an attacker the announcement does not name, the
            #   engine's default — CR 510.1c leaves a creature with one blocker
            #   no choice at all, and a seat that is not asked about several
            #   keeps the default every seat that is not asked keeps.
            #
            # The last arm read an absent entry as "assigns nothing", which is
            # not something a blocked creature with a creature in front of it
            # can do. ``web/action_combat.py`` had to fill the default in
            # itself before calling this (the dialog names only the attackers
            # it shows), and every other caller that named one attacker
            # silently unassigned the rest.
            if (
                self._defender_assigns_attacker_damage(attacker_idx)
                and self._defender_division_stands(attacker_idx)
            ):
                requested = self.combat_banding_damage[attacker_idx]
            elif attacker_idx in attacker_damage:
                requested = attacker_damage[attacker_idx]
            else:
                requested = self._default_attacker_division(attacker_idx)
            # CR 510.1e: the assignment is checked before any of it is dealt,
            # and an illegal one returns the game to the moment before it was
            # announced. One check for either seat's division — all of the
            # creature's combat damage, to the creatures blocking it, a
            # trampler's excess only past lethal damage — where the active
            # player's used to be asked for no total at all.
            refusal = self._attacker_division_refusal(
                attacker_idx, requested, offered=chooser is not None
            )
            if refusal is not None:
                return False, refusal, [], []
            # CR 510.1c: a creature blocked by two or more creatures assigns its
            # combat damage divided among them however its controller chooses.
            # There is no damage-assignment order and no requirement to assign
            # lethal to one blocker before another — that pre-2017 rule is gone.
            for blocker_idx in sorted(blockers):
                if blocker_idx >= len(defender.battlefield):
                    continue
                requested_damage = int(requested.get(blocker_idx, 0))
                power_left -= requested_damage
                if requested_damage > 0:
                    to_blockers.append((defending_index, blocker_idx, requested_damage, attacker_idx))
            if power_left > 0 and self._has_keyword(attacker, "trample"):
                # CR 702.19b: the excess goes to the player *or planeswalker*
                # the creature is attacking. Without trample over planeswalkers
                # none of it may go to the defending player instead (702.19c) —
                # carrying the walker id through is what enforces that.
                to_players.append((defending_index, power_left, attacker, attacked_walker_id))
        return True, "", to_blockers, to_players
