from __future__ import annotations

"""Combat damage step (CR 510).

Resolves combat damage assignment and dealing, including the separate
first-strike/double-strike damage step (CR 510.5), trample, deathtouch, lifelink,
protection, and the defending player's banding damage assignment (CR 702.22j/k).
Also holds the auto-assignment helpers used to skip manual assignment, the
post-damage lethal-damage destruction, and the band/blocker lookup helpers.
"""

from ..models import Permanent


class CombatDamageStepMixin:
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
        """CR 702.22j: is this attacker blocked by at least one creature with banding?"""
        defending_index = self.combat_attackers.get(attacker_idx)
        if defending_index is None or not (0 <= defending_index < len(self.players)):
            return False
        defender = self.players[defending_index]
        for blocker_idx in self._attacker_all_blockers(attacker_idx):
            if 0 <= blocker_idx < len(defender.battlefield):
                if self._creature_has_banding(defender.battlefield[blocker_idx]):
                    return True
        return False

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

    def _destroy_marked_creatures(self) -> None:
        any_died = False
        for player in self.players:
            survivors: list[Permanent] = []
            for permanent in player.battlefield:
                if not permanent.is_creature:
                    survivors.append(permanent)
                    continue
                # 704.5g: lethal damage; 704.5h: any damage from deathtouch source
                has_lethal = permanent.damage_marked >= permanent.effective_toughness
                has_deathtouch_hit = (
                    permanent.metadata.get("received_deathtouch", False)
                    and permanent.damage_marked > 0
                    and permanent.effective_toughness > 0
                )
                if not has_lethal and not has_deathtouch_hit:
                    survivors.append(permanent)
                    continue
                if permanent.regeneration_shield > 0 and not permanent.metadata.get(
                    "cant_be_regenerated_this_turn"
                ):
                    permanent.regeneration_shield -= 1
                    permanent.damage_marked = 0
                    permanent.tapped = True
                    permanent.metadata.pop("received_deathtouch", None)
                    survivors.append(permanent)
                    continue
                self._permanent_to_graveyard(player, permanent)
                self.log.append(f"{permanent.card.name} died from combat damage")
                self._trigger_aura_death_effects(permanent, player)
                any_died = True
            player.battlefield = survivors
        # Clear deathtouch flags from surviving creatures
        for player in self.players:
            for perm in player.battlefield:
                perm.metadata.pop("received_deathtouch", None)
        # 611.3b: recalculate lord buffs in case a lord died
        if any_died:
            self._recalculate_lord_buffs()

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

    def resolve_combat_damage(
        self,
        controller_index: int,
        attacker_damage: dict[int, dict[int, int]] | None = None,
        blocker_damage: dict[int, int] | None = None,
        blocker_damage_split: dict[int, dict[int, int]] | None = None,
    ) -> tuple[bool, str]:
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

        def participates_in_first_strike(perm: Permanent) -> bool:
            return self._has_keyword(perm, "first strike") or self._has_keyword(perm, "double strike")

        def participates_in_second_strike(perm: Permanent) -> bool:
            return self._has_keyword(perm, "double strike") or (
                not self._has_keyword(perm, "first strike") and not self._has_keyword(perm, "double strike")
            )

        # None means "no explicit assignment given" — fall back to the engine's
        # default assignment (full power to blockers). An empty dict, by contrast,
        # is an explicit "assign nothing". This lets a caller supply only
        # blocker_damage (CR 702.22k) and still have attackers deal normally.
        if attacker_damage is None:
            attacker_damage = self._build_auto_damage_assignment()

        # CR 702.22j/k: the active player may DIVIDE a band-blocking creature's
        # damage among the band members it blocks (blocker_damage_split maps
        # blocker_idx -> {band member -> damage}). Validate every split up front —
        # the blocker loop below mutates state as it goes, so a bad entry must be
        # rejected before any damage is marked.
        # NOTE(FFA scope gap): banding/multiblock division across 2+ *simultaneous*
        # defenders isn't fully modeled (rare combo: banding/Two-Headed Giant of
        # Foriys AND attack-multiple-players in the same combat) — the blocker
        # index here is resolved against the first defender this combat, matching
        # the single-defender behavior this validation always assumed.
        if blocker_damage_split:
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

        # CR 510.5: there is a separate first-strike combat damage step if any
        # attacking or blocking creature has first strike or double strike — this
        # includes an *unblocked* first/double striker dealing to the player, not
        # only creatures locked in a block.
        attacker_passes: list[int] = []
        blocker_passes: list[int] = []
        for attacker_idx in self.combat_attackers:
            if attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            blockers = self._attacker_all_blockers(attacker_idx)
            if blockers:
                defending_index = self.combat_attackers[attacker_idx]
                defender = self.players[defending_index] if 0 <= defending_index < len(self.players) else None
                for blocker_idx in blockers:
                    if defender is not None and blocker_idx < len(defender.battlefield):
                        blocker = defender.battlefield[blocker_idx]
                        if participates_in_first_strike(attacker) or participates_in_first_strike(blocker):
                            attacker_passes.append(attacker_idx)
                            blocker_passes.append(blocker_idx)
                            break
            elif participates_in_first_strike(attacker):
                attacker_passes.append(attacker_idx)

        has_first_strike_pass = bool(attacker_passes)
        run_first_pass = has_first_strike_pass and not self.combat_first_strike_done

        # (defending_idx, blocker_idx, damage, attacker_idx)
        attacker_damage_events: list[tuple[int, int, int, int]] = []
        # (defending_idx, damage, source_attacker)
        defender_damage_events: list[tuple[int, int, Permanent]] = []
        # CR 702.15b: damage dealt by a source with lifelink gains its controller
        # that much life. Accumulated per controller and applied after all combat
        # damage is dealt this step (the life-gain events happen simultaneously).
        lifelink_gain: dict[int, int] = {}

        def add_lifelink(controller_index: int, amount: int) -> None:
            if amount > 0:
                lifelink_gain[controller_index] = lifelink_gain.get(controller_index, 0) + amount

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
            if run_first_pass and not participates_in_first_strike(attacker):
                continue
            if not run_first_pass and has_first_strike_pass and not participates_in_second_strike(attacker):
                continue

            blockers = self._attacker_all_blockers(attacker_idx)
            power_left = attacker.effective_power
            if not blockers:
                if self.combat_damage_prevented_until_eot:
                    continue
                # A creature that was declared blocked (e.g. its blocker died to
                # first-strike damage) is still "blocked" — it cannot deal damage
                # to the defending player unless it has trample.
                if attacker.blocked and not self._has_keyword(attacker, "trample"):
                    continue
                damage = self._prevent_damage(defender, power_left, source=attacker)
                if damage > 0:
                    defender_damage_events.append((defending_index, damage, attacker))
                    if self._has_keyword(attacker, "lifelink"):
                        add_lifelink(self.active_player_index, damage)
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
                    return False, "combat damage assignment cannot be negative"
                if requested_damage > power_left:
                    return False, "assigned combat damage exceeds attacker power"
                # CR 702.19e: a trampler may assign excess to the defending player
                # only once each blocker has been assigned at least lethal damage.
                if has_trample and requested_damage < lethal:
                    trample_underlethal = True
                assigned_total += requested_damage
                power_left -= requested_damage
                if requested_damage > 0:
                    attacker_damage_events.append((defending_index, blocker_idx, requested_damage, attacker_idx))

            if assigned_total > attacker.effective_power:
                return False, "assigned combat damage exceeds attacker power"
            if has_trample and power_left > 0 and trample_underlethal:
                return False, "trample requires lethal damage assigned to each blocker"
            if has_trample and power_left > 0 and not self.combat_damage_prevented_until_eot:
                trample_damage = self._prevent_damage(defender, power_left, source=attacker)
                if trample_damage > 0:
                    defender_damage_events.append((defending_index, trample_damage, attacker))
                    if self._has_keyword(attacker, "lifelink"):
                        add_lifelink(self.active_player_index, trample_damage)

        for defending_idx, blocker_map in sorted(self.combat_blockers.items()):
            if defending_idx < 0 or defending_idx >= len(self.players):
                continue
            defender = self.players[defending_idx]
            for blocker_idx, attacker_idxs in sorted(blocker_map.items()):
                if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                    continue
                if not attacker_idxs:
                    continue
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
                        continue
                    if run_first_pass and not participates_in_first_strike(blocker):
                        continue
                    if not run_first_pass and has_first_strike_pass and not participates_in_second_strike(blocker):
                        continue
                    for member_idx, amount in sorted(split.items()):
                        amount = int(amount)
                        if amount <= 0 or not (0 <= member_idx < len(attacker_controller.battlefield)):
                            continue
                        member = attacker_controller.battlefield[member_idx]
                        if self._is_protected_from(member, blocker):
                            continue
                        dealt = self._mark_damage_on_permanent(member, amount, source=blocker)
                        if dealt > 0:
                            self._record_damage_source(member, blocker)
                            self._fire_dealt_damage_triggers(member)
                            if self._has_keyword(blocker, "lifelink"):
                                add_lifelink(defending_idx, dealt)
                        if self._has_keyword(blocker, "deathtouch"):
                            member.metadata["received_deathtouch"] = True
                    continue
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
                    continue
                blocker = defender.battlefield[blocker_idx]
                attacker = attacker_controller.battlefield[attacker_idx]
                if blocker.effective_power <= 0:
                    continue
                if run_first_pass and not participates_in_first_strike(blocker):
                    continue
                if not run_first_pass and has_first_strike_pass and not participates_in_second_strike(blocker):
                    continue
                # CR 702.16e: damage from a source of the protected quality is prevented.
                if self._is_protected_from(attacker, blocker):
                    continue
                dealt = self._mark_damage_on_permanent(attacker, blocker.effective_power, source=blocker)
                if dealt > 0:
                    self._record_damage_source(attacker, blocker)
                    self._fire_dealt_damage_triggers(attacker)
                    if self._has_keyword(blocker, "lifelink"):
                        add_lifelink(defending_idx, dealt)
                # 704.5h: mark attacker if blocker has deathtouch
                if self._has_keyword(blocker, "deathtouch") and blocker.effective_power > 0:
                    attacker.metadata["received_deathtouch"] = True

        for defending_idx, blocker_idx, damage, a_idx in attacker_damage_events:
            if defending_idx >= len(self.players):
                continue
            defending_player = self.players[defending_idx]
            if blocker_idx < 0 or blocker_idx >= len(defending_player.battlefield):
                continue
            blocker_perm = defending_player.battlefield[blocker_idx]
            source_attacker = (
                attacker_controller.battlefield[a_idx]
                if 0 <= a_idx < len(attacker_controller.battlefield)
                else None
            )
            # CR 702.16e: protection prevents damage from the protected quality.
            if source_attacker is not None and self._is_protected_from(blocker_perm, source_attacker):
                continue
            dealt = self._mark_damage_on_permanent(blocker_perm, damage, source=source_attacker)
            if dealt > 0:
                if source_attacker is not None:
                    self._record_damage_source(blocker_perm, source_attacker)
                self._fire_dealt_damage_triggers(blocker_perm)
                if source_attacker is not None and self._has_keyword(source_attacker, "lifelink"):
                    add_lifelink(self.active_player_index, dealt)
            # 704.5h: mark blocker if attacker has deathtouch
            if source_attacker is not None and damage > 0:
                if self._has_keyword(source_attacker, "deathtouch"):
                    blocker_perm.metadata["received_deathtouch"] = True

        total_player_damage = sum(dmg for _, dmg, _ in defender_damage_events)
        damage_by_defender: dict[int, int] = {}
        for defending_idx, damage, _ in defender_damage_events:
            damage_by_defender[defending_idx] = damage_by_defender.get(defending_idx, 0) + damage
        for defending_idx, damage, source_attacker in defender_damage_events:
            if defending_idx < 0 or defending_idx >= len(self.players):
                continue
            defender = self.players[defending_idx]
            # Prevention was already applied when the event was recorded.
            # Veteran Bodyguard: "As long as this creature is untapped, all damage
            # that would be dealt to you by unblocked creatures is dealt to this
            # creature instead." Redirect the whole event to it (CR 614 replacement).
            bodyguard = next(
                (
                    p
                    for p in defender.battlefield
                    if not p.tapped
                    and "all damage that would be dealt to you by unblocked creatures is dealt to this creature instead"
                    in p.card.oracle_text.lower()
                ),
                None,
            )
            if bodyguard is not None:
                self._mark_damage_on_permanent(bodyguard, damage, source=source_attacker)
                self.log.append(
                    f"{bodyguard.card.name} takes {damage} damage instead of {defender.name} (redirect)"
                )
                continue
            defender.life -= damage
            self._on_player_dealt_damage(defender, damage)
            # Attacker "deals damage to a player/opponent" triggers (Hypnotic Specter).
            if source_attacker is not None:
                self._fire_combat_damage_to_player_triggers(source_attacker, defender, damage)

        # CR 702.15b: apply lifelink life gain for damage dealt this step.
        for controller_index, amount in lifelink_gain.items():
            if 0 <= controller_index < len(self.players):
                self._gain_life(self.players[controller_index], amount, source_name="lifelink")

        self._destroy_marked_creatures()
        self.check_state_based_actions()
        self._prune_combat_state()

        if total_player_damage > 0:
            for defending_idx, damage in sorted(damage_by_defender.items()):
                if not (0 <= defending_idx < len(self.players)) or damage <= 0:
                    continue
                defender = self.players[defending_idx]
                self.log.append(
                    f"{defender.name} took {damage} combat damage (life: {defender.life + damage} → {defender.life})"
                )

        if run_first_pass:
            self.combat_first_strike_done = True
            self.log.append("Resolved first strike combat damage")
            return True, "resolved first strike combat damage"

        self.combat_damage_resolved = True
        self.log.append("Resolved combat damage")
        return True, "resolved combat damage"
