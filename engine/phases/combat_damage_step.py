from __future__ import annotations

"""Combat damage step (CR 510).

Resolves combat damage assignment and dealing, including the separate
first-strike/double-strike damage step (CR 510.4), trample, deathtouch, lifelink,
protection, and the defending player's banding damage assignment (CR 702.22j/k).
Also holds the auto-assignment helpers used to skip manual assignment, the
post-damage lethal-damage destruction, and the band/blocker lookup helpers.

**The step is in two halves, and the seam matters.** Assignment (CR 510.1) works
out where every point goes and can be *refused* — a negative amount, a trampler
holding back lethal — so it deals nothing while it can still say no. Dealing (CR
510.2) then runs the recorded events through CR 120.4 and can be *suspended*:
any one of them may stop to ask the affected player which effect applies to it
first (CR 616.1e). So the dealing half is a chain of resumable loops
(``engine/resumption.py``) rather than plain ``for`` statements, and this step's
own tail — the lifelink gain, the state-based actions, the log, and the
``combat_first_strike_done`` / ``combat_damage_resolved`` flags that are the
step's idea of how far through it is — is the *last step of the outermost loop*
rather than code written after it. Work after a resumable loop does not run when
one of its steps suspends and nothing records it, which for this step would mean
a combat that half-happened and then declared itself resolved.

Both strike passes go through :meth:`resolve_all_combat_damage` for the same
reason: the "call it, and call it again if that was only the first-strike pass"
idiom every caller used to write is safe only while a pass cannot be
interrupted.
"""

from ..damage_events import deal_damage, lifelink_life_gained
from ..models import Permanent
from ..resumption import run_resumable


class CombatDamageStepMixin:
    def _fire_unblocked_attack_triggers(self) -> None:
        """Put "whenever this creature attacks and isn't blocked" triggers
        (Merchant Ship) on the stack. Deferred from declare-attackers — the
        condition can only be evaluated once blockers are known — and fired at
        the combat damage step, the reliable choke point every combat flow
        passes through."""
        from ..game_types import StackItem
        from ..trigger_utils import matching_triggers

        controller_index = self.active_player_index
        controller = self.players[controller_index]
        for idx in list(self.combat_attackers):
            if not (0 <= idx < len(controller.battlefield)):
                continue
            permanent = controller.battlefield[idx]
            if permanent.blocked or self._attacker_all_blockers(idx):
                continue
            for trig in matching_triggers(
                permanent.effective_card, condition_kinds={"attacks_unblocked"}
            ):
                self._stack_push(
                    StackItem(
                        card=permanent.card,
                        caster_index=controller_index,
                        target_player_index=controller_index,
                        target_permanent_index=idx,
                        x_value=None,
                        ability_instruction=trig.instruction,
                        ability_effect_kind=trig.effect_kind,
                        source_permanent=permanent,
                        ability_text=trig.source_line,
                    )
                )
                self.log.append(
                    f"{permanent.card.name} triggered (attacked and wasn't blocked)"
                )

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

    def assign_banding_combat_damage(
        self,
        defender_index: int,
        attacker_damage: dict[int, dict[int, int]],
    ) -> tuple[bool, str]:
        """CR 702.22j: the defending player pre-commits how each attacker that is
        blocked by a creature with banding assigns its combat damage.

        Stored and consumed by :meth:`resolve_combat_damage` in place of the active
        player's assignment for those attackers.
        """
        if defender_index not in self.combat_defending_players():
            return False, "only the defending player may assign banding damage"
        attacker_controller = self.players[self.active_player_index]
        for attacker_idx, split in attacker_damage.items():
            attacker_idx = int(attacker_idx)
            if self.combat_attackers.get(attacker_idx) != defender_index:
                return False, "that attacker isn't attacking this player"
            if not self._attacker_blocked_by_banding(attacker_idx):
                return False, "attacker is not blocked by a creature with banding"
            if not (0 <= attacker_idx < len(attacker_controller.battlefield)):
                return False, "attacker index out of range"
            attacker = attacker_controller.battlefield[attacker_idx]
            total = 0
            for amount in split.values():
                amount = int(amount)
                if amount < 0:
                    return False, "combat damage assignment cannot be negative"
                total += amount
            power = max(0, attacker.effective_power)
            if total > power:
                return False, "assigned combat damage exceeds attacker power"
            # CR 702.22j: the defender divides ALL the attacker's combat damage
            # among its blockers. Only a trampler may hold some back (the
            # remainder tramples through to the defending player, CR 702.19e).
            if total < power and not self._has_keyword(attacker, "trample"):
                return False, "all of the attacker's combat damage must be assigned"
        self.combat_banding_damage = {
            int(a): {int(b): int(v) for b, v in dmg.items()}
            for a, dmg in attacker_damage.items()
        }
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
            power = max(0, blocker.effective_power)
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

    def _needs_manual_damage_assignment(self) -> bool:
        """Return True when combat damage needs a player's assignment choice.

        That is any blocked attacker with 2+ blockers, any attacking band whose
        block propagated (CR 702.22h) so the active player must choose where each
        shared blocker's damage goes (702.22k), or any blocker blocking 2+
        attackers (Two-Headed Giant of Foriys) whose controller may divide its
        damage (CR 510.1d). Pure non-banding combat is unaffected, so AI
        auto-resolution keeps working unchanged.
        """
        if self.combat_band_blocks:
            return True
        for attacker_idx in self.combat_attackers:
            if len(self._attacker_all_blockers(attacker_idx)) >= 2:
                return True
        for blocker_map in self.combat_blockers.values():
            for attacker_idxs in blocker_map.values():
                if len(set(attacker_idxs)) >= 2:
                    return True
        return False

    def _manual_assignment_has_declared_multiblock(self) -> bool:
        """True when some attacker is blocked by 2+ *declared* blockers — the case
        the combat-damage dialog can surface to the active player. Band-propagated
        blocks (a single shared blocker spread across a band, CR 702.22h) are not
        included: the dialog has no way to present them, so when that is the only
        pending assignment the web layer auto-resolves rather than deadlocking."""
        for attacker_idx in self.combat_attackers:
            if len(self._combat_blockers_for_attacker(attacker_idx)) >= 2:
                return True
        return False

    def _build_auto_damage_assignment(self) -> dict[int, dict[int, int]]:
        """Build a sensible default damage assignment for every blocked attacker.

        Single-blocked attackers assign their full power to that blocker (only
        lethal for tramplers, so the remainder can trample through). Multi-blocked
        attackers assign lethal to each blocker in index order and dump any leftover
        power onto the last blocker that received lethal. This is only a heuristic
        for the AI / auto-resolve path — it maximizes how many blockers die. The
        resolver no longer requires lethal-in-order (CR 510.1c), so a human attacker
        may freely override this with any legal division.
        """
        if not self.combat_attackers:
            return {}
        attacker_controller = self.players[self.active_player_index]
        assignment: dict[int, dict[int, int]] = {}
        for attacker_idx, defending_index in self.combat_attackers.items():
            if attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            # Each attacker resolves its own defender's battlefield — blocker
            # indices are only unambiguous within one defender (CR 802).
            defender = (
                self.players[defending_index]
                if 0 <= defending_index < len(self.players)
                else None
            )
            blockers = self._attacker_all_blockers(attacker_idx)
            if not blockers:
                continue
            has_trample = self._has_keyword(attacker, "trample")
            has_deathtouch = self._has_keyword(attacker, "deathtouch")

            def lethal_for(blocker_idx: int) -> int:
                if defender is None or blocker_idx >= len(defender.battlefield):
                    return 0
                blocker = defender.battlefield[blocker_idx]
                need = max(0, blocker.effective_toughness - blocker.damage_marked)
                if has_deathtouch and need > 0:
                    return 1
                return need

            if len(blockers) == 1:
                blocker_idx = blockers[0]
                assign = max(0, attacker.effective_power)
                # For trample assign only lethal to the blocker; the remainder
                # flows to the defending player via the existing trample logic.
                if has_trample:
                    assign = min(assign, lethal_for(blocker_idx))
                assignment[attacker_idx] = {blocker_idx: assign}
                continue

            # Multiple blockers: walk them in index order assigning lethal to each
            # until the attacker runs out of power, then dump the remainder on the
            # last blocker that received lethal. This kills as many blockers as the
            # attacker's power allows. It's just the default — any non-negative
            # division summing to <= power is legal (CR 510.1c).
            power_left = max(0, attacker.effective_power)
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
            assignment[attacker_idx] = per_blocker
        return assignment

    def _participates_in_first_strike(self, permanent: Permanent) -> bool:
        """CR 510.4: deals its combat damage in the first-strike step."""
        return self._has_keyword(permanent, "first strike") or self._has_keyword(
            permanent, "double strike"
        )

    def _participates_in_second_strike(self, permanent: Permanent) -> bool:
        """CR 510.4: deals its combat damage in the second step — everything
        without first strike, and double strikers again."""
        return self._has_keyword(permanent, "double strike") or not (
            self._has_keyword(permanent, "first strike")
            or self._has_keyword(permanent, "double strike")
        )

    def _strikes_in_pass(
        self, permanent: Permanent, run_first_pass: bool, has_first_strike_pass: bool
    ) -> bool:
        """Whether this creature deals its combat damage in the pass being run.

        With no first-strike step there is only one pass and everything strikes
        in it, which is why "no first strike step" is not the same question as
        "is this the second one" (CR 510.4).
        """
        if run_first_pass:
            return self._participates_in_first_strike(permanent)
        if has_first_strike_pass:
            return self._participates_in_second_strike(permanent)
        return True

    def _first_strike_pass_pending(self) -> bool:
        """CR 510.4: whether this combat has a separate first-strike damage step.

        True if any attacking or blocking creature has first or double strike —
        which includes an *unblocked* first striker dealing to the player, not
        only creatures locked in a block.
        """
        attacker_controller = self.players[self.active_player_index]
        for attacker_idx in self.combat_attackers:
            if attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            blockers = self._attacker_all_blockers(attacker_idx)
            if not blockers:
                if self._participates_in_first_strike(attacker):
                    return True
                continue
            defending_index = self.combat_attackers[attacker_idx]
            defender = (
                self.players[defending_index]
                if 0 <= defending_index < len(self.players)
                else None
            )
            if defender is None:
                continue
            for blocker_idx in blockers:
                if blocker_idx >= len(defender.battlefield):
                    continue
                blocker = defender.battlefield[blocker_idx]
                if self._participates_in_first_strike(
                    attacker
                ) or self._participates_in_first_strike(blocker):
                    return True
        return False

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
            power = max(0, split_blocker.effective_power)
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
            if attacker.effective_power <= 0:
                continue
            if not self._strikes_in_pass(attacker, run_first_pass, has_first_strike_pass):
                continue

            blockers = self._attacker_all_blockers(attacker_idx)
            power_left = attacker.effective_power
            # CR 510.1b: an unblocked creature assigns its damage to the player,
            # or to the planeswalker, it is attacking — recorded on the event so
            # the dealing half needs no second look at the combat maps.
            attacked_walker_id = self.combat_attacked_planeswalkers.get(attacker_idx)
            # "You may have this creature assign its combat damage as though it
            # weren't blocked." (Garruk, Savage Herald's −7.) The "may" is
            # answered yes whenever no explicit per-blocker assignment was
            # given for this attacker — an explicit assignment IS the player
            # choosing to damage the blockers instead.
            if (
                blockers
                and attacker.metadata.get("assign_combat_damage_as_unblocked_until_eot")
                and not attacker_damage.get(attacker_idx)
            ):
                to_players.append((defending_index, power_left, attacker, attacked_walker_id))
                continue
            if not blockers:
                # A creature that was declared blocked (e.g. its blocker died to
                # first-strike damage) is still "blocked" — it cannot deal damage
                # to the defending player unless it has trample.
                if attacker.blocked and not self._has_keyword(attacker, "trample"):
                    continue
                to_players.append((defending_index, power_left, attacker, attacked_walker_id))
                continue

            # CR 702.22j: when an attacker is blocked by a creature with banding, the
            # defending player (not the active player) assigns that attacker's damage.
            if self._attacker_blocked_by_banding(attacker_idx) and attacker_idx in self.combat_banding_damage:
                requested = self.combat_banding_damage[attacker_idx]
            else:
                requested = attacker_damage.get(attacker_idx, {})
            has_trample = self._has_keyword(attacker, "trample")
            assigned_total = 0
            block_order = sorted(blockers)
            # CR 510.1c: a creature blocked by two or more creatures assigns its
            # combat damage divided among them however its controller chooses.
            # There is no damage-assignment order and no requirement to assign
            # lethal to one blocker before another — that pre-2017 rule is gone.
            # The only constraints (CR 510.1e) are non-negative per-blocker amounts
            # whose total doesn't exceed the attacker's power, checked below.
            trample_underlethal = False
            for blocker_idx in block_order:
                if blocker_idx >= len(defender.battlefield):
                    continue
                blocker = defender.battlefield[blocker_idx]
                lethal = max(0, blocker.effective_toughness - blocker.damage_marked)
                if self._has_keyword(attacker, "deathtouch") and lethal > 0:
                    lethal = 1
                requested_damage = int(requested.get(blocker_idx, 0))
                if requested_damage < 0:
                    return False, "combat damage assignment cannot be negative", [], []
                if requested_damage > power_left:
                    return False, "assigned combat damage exceeds attacker power", [], []
                # CR 702.19e: a trampler may assign excess to the defending player
                # only once each blocker has been assigned at least lethal damage.
                if has_trample and requested_damage < lethal:
                    trample_underlethal = True
                assigned_total += requested_damage
                power_left -= requested_damage
                if requested_damage > 0:
                    to_blockers.append((defending_index, blocker_idx, requested_damage, attacker_idx))

            if assigned_total > attacker.effective_power:
                return False, "assigned combat damage exceeds attacker power", [], []
            if has_trample and power_left > 0 and trample_underlethal:
                return False, "trample requires lethal damage assigned to each blocker", [], []
            if has_trample and power_left > 0:
                # CR 702.19b: the excess goes to the player *or planeswalker*
                # the creature is attacking. Without trample over planeswalkers
                # none of it may go to the defending player instead (702.19f) —
                # carrying the walker id through is what enforces that.
                to_players.append((defending_index, power_left, attacker, attacked_walker_id))
        return True, "", to_blockers, to_players

    def resolve_combat_damage(
        self,
        controller_index: int,
        attacker_damage: dict[int, dict[int, int]] | None = None,
        blocker_damage: dict[int, int] | None = None,
        blocker_damage_split: dict[int, dict[int, int]] | None = None,
    ) -> tuple[bool, str]:
        """One combat damage pass — the first-strike step or the regular one
        (CR 510.4). Both halves of the step are here: work out the assignment
        (which can be refused), then deal it (which cannot).

        Every event in the dealing half can stop to ask the affected player
        which effect applies to it first (CR 616.1e), so that half is a chain of
        resumable loops and this step's own tail is the last step of the
        outermost one — see :mod:`engine.resumption`. Use
        :meth:`resolve_all_combat_damage` rather than calling this twice by
        hand: a pass that suspends leaves the other one recorded behind it.
        """
        if self.current_turn_phase != "combat" or self.current_step != "combat_damage":
            return False, "combat damage can only be resolved during combat_damage"
        if controller_index != self.active_player_index:
            return False, "only active player may assign combat damage"
        if self.combat_damage_resolved:
            return False, "combat damage already resolved"

        self._prune_combat_state()
        if not self.combat_attackers:
            self.combat_damage_resolved = True
            return True, "no attackers"

        attacker_controller = self.players[self.active_player_index]

        # "Whenever this creature attacks and isn't blocked" (Merchant Ship):
        # deferred from declare-attackers, fired now that blocks are known. The
        # second-strike pass is the one and only re-entry into this method for a
        # given combat, and combat_first_strike_done is exactly what marks it, so
        # gating on that flag is what keeps the trigger from firing twice.
        if not self.combat_first_strike_done:
            self._fire_unblocked_attack_triggers()

        # None means "no explicit assignment given" — fall back to the engine's
        # default assignment (full power to blockers). An empty dict, by contrast,
        # is an explicit "assign nothing". This lets a caller supply only
        # blocker_damage (CR 702.22k) and still have attackers deal normally.
        if attacker_damage is None:
            attacker_damage = self._build_auto_damage_assignment()

        ok, message = self._validate_blocker_damage_split(blocker_damage_split)
        if not ok:
            return False, message

        has_first_strike_pass = self._first_strike_pass_pending()
        run_first_pass = has_first_strike_pass and not self.combat_first_strike_done

        ok, message, attacker_damage_events, defender_damage_events = (
            self._assign_attacker_combat_damage(
                attacker_damage, run_first_pass, has_first_strike_pass
            )
        )
        if not ok:
            return False, message

        # ------------------------------------------------------------------
        # Nothing below can be refused, and everything below can be suspended.
        #
        # A damage event stops to ask the affected player which effect applies
        # first (CR 616.1e), and while it waits *nothing has happened* — so the
        # blockers, attackers and band members behind it have to be recorded
        # rather than run past, and so does this step's own tail. Each loop here
        # is therefore the last thing its function does, and the tail is
        # `finish`, a step of the outermost loop, rather than code written after
        # it. See engine/resumption.py.
        # ------------------------------------------------------------------

        # CR 702.15b: damage dealt by a source with lifelink gains its controller
        # that much life. Accumulated per controller and applied after all combat
        # damage is dealt this step (the life-gain events happen simultaneously).
        lifelink_gain: dict[int, int] = {}
        # Life lost is accumulated as the events are applied, not summed from the
        # recorded amounts: damage redirected or replaced away never reduced
        # anyone's life, and `finish` reconstructs the before-life total by
        # adding these numbers back.
        life_lost_by_defender: dict[int, int] = {}
        # Which of the attacking side's creatures dealt combat damage to each
        # player this step, for the batched "one or more … deal combat damage"
        # triggers below. Per *player*, because that is what the trigger is once
        # per — and by permanent, because the trigger's subject is a noun phrase
        # tested against each one.
        damagers_by_defender: dict[int, list] = {}
        report: dict[str, str | None] = {"message": None}

        def add_lifelink(controller_index: int, amount: int) -> None:
            if amount > 0:
                lifelink_gain[controller_index] = lifelink_gain.get(controller_index, 0) + amount

        def _dealt_to_creature(victim, source, lifelink_seat: int):
            """What follows one creature being dealt combat damage: fire its
            "dealt damage" triggers and tally the dealer's lifelink. (Deathtouch is stamped by _mark_damage_on_permanent
            itself — CR 702.2b is about damage, not combat damage.)

            Handed to `_mark_damage_on_permanent` as its `then` rather than run
            after it, so it travels with the event — CR 702.2b and 704.5h both
            need damage to have *been dealt*, and damage prevented in full never
            was (CR 615.6)."""

            def dealt(amount: int) -> None:
                if amount <= 0:
                    return
                # The damage-source record is written by
                # ``_mark_damage_on_permanent`` itself now — one seam for
                # combat and non-combat damage alike.
                self._fire_dealt_damage_triggers(victim, amount)
                add_lifelink(lifelink_seat, lifelink_life_gained(source, amount))

            return dealt

        # -- blockers deal, by defender, by blocker, by band member ----------

        def one_band_member(defending_idx: int, blocker, entry) -> None:
            member_idx, amount = entry
            amount = int(amount)
            if amount <= 0 or not (0 <= member_idx < len(attacker_controller.battlefield)):
                return
            member = attacker_controller.battlefield[member_idx]
            if self._is_protected_from(member, blocker):
                return
            self._mark_damage_on_permanent(
                member, amount, source=blocker, combat=True,
                then=_dealt_to_creature(member, blocker, defending_idx), asks=True,
            )

        def one_blocker(defending_idx: int, entry) -> None:
            blocker_idx, attacker_idxs = entry
            defender = self.players[defending_idx]
            if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                return
            if not attacker_idxs:
                return
            # CR 702.22j/k: an explicit division of this blocker's damage among the
            # band members it blocks (validated above) wins over the single-target
            # default. Each portion is dealt separately, honoring protection.
            # Falls back to the defender's pre-committed CR 510.1d division for a
            # creature blocking multiple attackers (Two-Headed Giant of Foriys).
            split = (blocker_damage_split or {}).get(blocker_idx)
            if split is None:
                split = self.combat_multiblock_damage.get(blocker_idx)
            if split:
                blocker = defender.battlefield[blocker_idx]
                if blocker.effective_power <= 0:
                    return
                if not self._strikes_in_pass(blocker, run_first_pass, has_first_strike_pass):
                    return
                run_resumable(
                    self,
                    sorted(split.items()),
                    lambda member: one_band_member(defending_idx, blocker, member),
                )
                return
            # A blocker deals its combat damage to one of the creatures it blocks
            # (CR 510.1c, defender's choice; default the first). A creature blocking
            # several attackers (Two-Headed Giant of Foriys) still deals once.
            attacker_idx = attacker_idxs[0]
            # CR 702.22k: a blocker blocking a band (which always contains a creature
            # with banding) deals its damage where the *active* player chooses among
            # the band members it blocks. Also lets the defender pick which blocked
            # attacker a multi-block creature damages.
            band = self._attacker_band(attacker_idx)
            if blocker_damage and blocker_idx in blocker_damage:
                chosen = blocker_damage[blocker_idx]
                allowed = chosen in attacker_idxs or (band and chosen in band)
                if allowed and 0 <= chosen < len(attacker_controller.battlefield):
                    attacker_idx = chosen
            if attacker_idx < 0 or attacker_idx >= len(attacker_controller.battlefield):
                return
            blocker = defender.battlefield[blocker_idx]
            attacker = attacker_controller.battlefield[attacker_idx]
            if blocker.effective_power <= 0:
                return
            if not self._strikes_in_pass(blocker, run_first_pass, has_first_strike_pass):
                return
            # CR 702.16e: damage from a source of the protected quality is prevented.
            if self._is_protected_from(attacker, blocker):
                return
            self._mark_damage_on_permanent(
                attacker, blocker.effective_power, source=blocker, combat=True,
                then=_dealt_to_creature(attacker, blocker, defending_idx), asks=True,
            )

        def one_defenders_blockers(entry) -> None:
            defending_idx, blocker_map = entry
            if defending_idx < 0 or defending_idx >= len(self.players):
                return
            run_resumable(
                self,
                sorted(blocker_map.items()),
                lambda blocker: one_blocker(defending_idx, blocker),
            )

        def blockers_deal() -> None:
            run_resumable(self, sorted(self.combat_blockers.items()), one_defenders_blockers)

        # -- attackers deal to the creatures blocking them -------------------

        def one_blocker_is_hit(entry) -> None:
            defending_idx, blocker_idx, damage, a_idx = entry
            if defending_idx >= len(self.players):
                return
            defending_player = self.players[defending_idx]
            if blocker_idx < 0 or blocker_idx >= len(defending_player.battlefield):
                return
            blocker_perm = defending_player.battlefield[blocker_idx]
            source_attacker = (
                attacker_controller.battlefield[a_idx]
                if 0 <= a_idx < len(attacker_controller.battlefield)
                else None
            )
            # CR 702.16e: protection prevents damage from the protected quality.
            if source_attacker is not None and self._is_protected_from(blocker_perm, source_attacker):
                return
            self._mark_damage_on_permanent(
                blocker_perm, damage, source=source_attacker, combat=True,
                then=_dealt_to_creature(
                    blocker_perm, source_attacker, self.active_player_index
                ),
                asks=True,
            )

        def attackers_deal_to_blockers() -> None:
            run_resumable(self, attacker_damage_events, one_blocker_is_hit)

        # -- attackers deal to the players they are attacking ----------------

        def one_defender_is_hit(entry) -> None:
            """Each recorded event is run through CR 120.4 here, not where it was
            recorded. That is what makes several attackers work: an effect that
            caps the life loss sees the total the previous attacker left behind,
            which is 616.1f's re-check falling out of the placement. Shields,
            redirects (Veteran Bodyguard) and the life floor are all one sequence
            in engine/damage_events.py — the recorded amount is raw."""
            defending_idx, damage, source_attacker, attacked_walker_id = entry
            if defending_idx < 0 or defending_idx >= len(self.players):
                return
            if attacked_walker_id is not None:
                # The creature is attacking a planeswalker (CR 508.1b). Damage
                # goes to the walker — removing loyalty (CR 120.3c) — and to
                # nothing at all if it has left the battlefield (CR 510.1b).
                walker = self.permanent_by_id(attacked_walker_id)
                if walker is None:
                    return
                if source_attacker is not None and self._is_protected_from(walker, source_attacker):
                    return
                self._mark_damage_on_permanent(
                    walker, damage, source=source_attacker, combat=True,
                    then=_dealt_to_creature(
                        walker, source_attacker, self.active_player_index
                    ),
                    asks=True,
                )
                return
            defender = self.players[defending_idx]

            def hit() -> None:
                # `hit` is its own restart: the whole event *and* everything this
                # step does with it re-runs when the answer arrives, which is why
                # none of the consequences below sit outside it.
                outcome = deal_damage(
                    self,
                    {
                        "recipient": defender,
                        "amount": damage,
                        "source": source_attacker,
                        "combat": True,
                    },
                    restart=hit,
                )
                if outcome.suspended or outcome.dealt <= 0:
                    return
                defender.life -= outcome.result
                life_lost_by_defender[defending_idx] = (
                    life_lost_by_defender.get(defending_idx, 0) + outcome.result
                )
                # CR 702.15b reads the damage *dealt*, which is why lifelink is
                # tallied here rather than where the event was recorded: a result
                # replacement (Ali from Cairo) lowers the life lost without lowering
                # the damage, and the two numbers only exist together at this point.
                add_lifelink(
                    self.active_player_index,
                    lifelink_life_gained(source_attacker, outcome.dealt),
                )
                # CR 903.10a: combat damage from a commander is tallied per
                # commander for the whole game. Here rather than at the event's
                # recording, for the reason lifelink is: the rule counts the
                # damage *dealt* (CR 120.4b), and a result replacement (Ali from
                # Cairo) lowers the life lost without lowering that.
                self.record_commander_combat_damage(
                    defender, source_attacker, outcome.dealt
                )
                self._on_player_dealt_damage(defender, outcome.dealt, source_attacker)
                # Eye for an Eye: combat damage counts too — the attacker's
                # controller takes the same amount. Applied here rather than by
                # routing through _deal_damage_to_player, which would run the event
                # a second time.
                self._apply_mirror_damage(defender, outcome.dealt, source_attacker)
                # "…deals damage to a player/opponent" (Hypnotic Specter) is
                # announced by `damage_events._announce`, from inside the
                # `deal_damage` call above — the one seam every damage event
                # passes through, which is why there is nothing to fire here.
                if source_attacker is not None:
                    # The delayed ones (Subira) belong to no permanent, so no
                    # battlefield scan can find them and they keep their own
                    # site (CR 603.7).
                    self._fire_delayed_combat_damage_triggers(
                        source_attacker, defender, outcome.dealt
                    )
                    # "Whenever **one or more** … deal combat damage to a
                    # player" is one trigger however many creatures dealt it, so
                    # the pairs are recorded here and fired once each at the end
                    # of the step — the per-attacker call above cannot batch
                    # what it is called once per attacker for.
                    if outcome.dealt > 0:
                        damagers_by_defender.setdefault(
                            self.players.index(defender), []
                        ).append(source_attacker)

            hit()

        def attackers_deal_to_players() -> None:
            run_resumable(self, defender_damage_events, one_defender_is_hit)

        # -- the step's own tail, as its last step ---------------------------

        def finish() -> None:
            # The batched "one or more … deal combat damage to a player"
            # triggers, once per player damaged (CR 603.3: the ability triggers
            # once however many creatures dealt the damage). Fired before the
            # state-based check below for the same reason every other trigger in
            # this step is: they go on the stack and resolve in the priority
            # window after it.
            self._fire_batched_combat_damage_triggers(damagers_by_defender)

            # CR 702.15b: apply lifelink life gain for damage dealt this step.
            for controller_index, amount in lifelink_gain.items():
                if 0 <= controller_index < len(self.players):
                    self._gain_life(self.players[controller_index], amount, source_name="lifelink")

            self.check_state_based_actions()
            self._prune_combat_state()

            if sum(life_lost_by_defender.values()) > 0:
                for defending_idx, damage in sorted(life_lost_by_defender.items()):
                    if not (0 <= defending_idx < len(self.players)) or damage <= 0:
                        continue
                    defender = self.players[defending_idx]
                    self.log.append(
                        f"{defender.name} took {damage} combat damage (life: {defender.life + damage} → {defender.life})"
                    )

            if run_first_pass:
                self.combat_first_strike_done = True
                self.log.append("Resolved first strike combat damage")
                report["message"] = "resolved first strike combat damage"
                return

            self.combat_damage_resolved = True
            self.log.append("Resolved combat damage")
            report["message"] = "resolved combat damage"

        run_resumable(
            self,
            [blockers_deal, attackers_deal_to_blockers, attackers_deal_to_players, finish],
            lambda step: step(),
        )
        # `finish` is what writes the message, so an absent one means the step
        # stopped part-way; the answer comes back for the rest of it.
        return True, report["message"] or "combat damage is waiting on a choice (CR 616.1e)"

    def resolve_all_combat_damage(
        self,
        controller_index: int,
        attacker_damage: dict[int, dict[int, int]] | None = None,
        blocker_damage: dict[int, int] | None = None,
        blocker_damage_split: dict[int, dict[int, int]] | None = None,
    ) -> tuple[bool, str]:
        """Every combat damage pass this combat still owes (CR 510.4).

        One pass when nothing has first strike, two when something does. That
        "call it, and call it again if it was only the first-strike pass" used to
        live at each caller, which was safe only while nothing could interrupt a
        pass: a first-strike pass that suspends leaves ``combat_damage_resolved``
        False, so the caller's second call would have re-run the *first* strike
        rather than waiting for it to finish. As a resumable loop the second pass
        is recorded behind the first instead, and runs once the answer arrives.
        """
        report: dict[str, tuple[bool, str]] = {}

        def strike_pass() -> None:
            if self.combat_damage_resolved:
                return
            report["last"] = self.resolve_combat_damage(
                controller_index,
                attacker_damage=attacker_damage,
                blocker_damage=blocker_damage,
                blocker_damage_split=blocker_damage_split,
            )

        run_resumable(self, [strike_pass, strike_pass], lambda step: step())
        return report.get("last", (True, "combat damage already resolved"))
