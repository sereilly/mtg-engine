from __future__ import annotations

from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import compile_card_oracle

class CombatMixin:
    def _has_any_legal_attacker(self, attacker_index: int, defender_index: int) -> bool:
        if attacker_index < 0 or attacker_index >= len(self.players):
            return False
        if defender_index < 0 or defender_index >= len(self.players):
            return False
        if attacker_index == defender_index:
            return False

        attacker_player = self.players[attacker_index]
        for attacker in attacker_player.battlefield:
            if attacker.card.primary_type != "creature":
                continue
            if attacker.tapped:
                continue
            if self.can_attack(attacker, defender_index):
                return True
        return False

    def _has_any_legal_block(self, defender_index: int) -> bool:
        if defender_index < 0 or defender_index >= len(self.players):
            return False
        if self.active_player_index < 0 or self.active_player_index >= len(self.players):
            return False

        self._prune_combat_state()
        if not self.combat_attackers:
            return False

        defender = self.players[defender_index]
        attacker_controller = self.players[self.active_player_index]
        for blocker in defender.battlefield:
            if blocker.card.primary_type != "creature" or blocker.tapped:
                continue
            for attacker_idx in self.combat_attackers:
                if attacker_idx < 0 or attacker_idx >= len(attacker_controller.battlefield):
                    continue
                attacker = attacker_controller.battlefield[attacker_idx]
                if self._can_block_attacker(blocker, attacker):
                    return True
        return False

    def advance_combat_phase(self) -> None:
        combat_steps = list(self._phase_steps("combat"))
        if self.current_turn_phase != "combat":
            self._enter_combat_step(combat_steps[0])
            return

        try:
            idx = combat_steps.index(self.current_step)
        except ValueError:
            self._enter_combat_step(combat_steps[0])
            return

        if self.current_step == "end_of_combat":
            self.end_combat(step_already_started=True)
            self._enter_main_phase(precombat=False)
            return
        if self.current_step == "declare_attackers" and not self.combat_attackers_locked:
            defender_index = self.combat_defending_player_index
            if not isinstance(defender_index, int):
                defender_index = 1 - self.active_player_index
                self.combat_defending_player_index = defender_index

            if self._has_any_legal_attacker(self.active_player_index, defender_index):
                return

            self.combat_attackers = {}
            self.combat_blockers = {}
            self.combat_attackers_locked = True
            self.combat_blockers_locked = True
            self._prune_combat_state()
            attacker_name = self.players[self.active_player_index].name
            self.log.append(f"{attacker_name} has no valid attackers; declare attackers step skipped")
        if self.current_step == "declare_blockers" and not self.combat_blockers_locked:
            defender_index = self.combat_defending_player_index
            if isinstance(defender_index, int) and not self._has_any_legal_block(defender_index):
                self.combat_blockers = {}
                self.combat_blockers_locked = True
                self._prune_combat_state()
                defender_name = self.players[defender_index].name
                self.log.append(f"{defender_name} has no valid blockers; declare blockers step skipped")
            else:
                return
        if self.current_step == "declare_blockers" and self.combat_blockers_locked and not self.combat_attackers:
            defender_index = self.combat_defending_player_index
            if isinstance(defender_index, int):
                defender_name = self.players[defender_index].name
                self.log.append(f"{defender_name} has no valid blockers; declare blockers step skipped")
        if self.current_step == "combat_damage" and not self.combat_damage_resolved:
            return  # Awaiting manual damage assignment

        if self.current_step == "declare_attackers":
            self.log.append(
                f"Declare attackers step complete: {len(self.combat_attackers)} attacker(s) declared"
            )
        if self.current_step == "declare_blockers":
            self.log.append(
                f"Declare blockers step complete: {len(self.combat_blockers)} blocker(s) declared"
            )

        # Close current combat step, then enter the next one.
        if self._receives_priority(self.current_step):
            self._resolve_priority_window()
        self._on_step_or_phase_end("combat", self.current_step)

        next_idx = idx + 1
        if next_idx >= len(combat_steps):
            self._enter_main_phase(precombat=False)
            return
        if combat_steps[next_idx] == "combat_damage":
            self.combat_damage_resolved = False
            self.combat_first_strike_done = False
        self._enter_combat_step(combat_steps[next_idx])

        # Auto-resolve and skip combat_damage when no manual assignment is needed.
        if combat_steps[next_idx] == "combat_damage" and not self._needs_manual_damage_assignment():
            auto = self._build_auto_damage_assignment()
            self.resolve_combat_damage(self.active_player_index, attacker_damage=auto)
            if not self.combat_damage_resolved:  # first-strike pass; do second
                self.resolve_combat_damage(self.active_player_index, attacker_damage=auto)
            if self._receives_priority("combat_damage"):
                self._resolve_priority_window()
            self._on_step_or_phase_end("combat", "combat_damage")
            eoc_idx = next_idx + 1
            if eoc_idx >= len(combat_steps):
                self._enter_main_phase(precombat=False)
                return
            self._enter_combat_step(combat_steps[eoc_idx])

    def _reset_combat_state(self, clear_damage_marked: bool) -> None:
        self.combat_attackers = {}
        self.combat_blockers = {}
        self.combat_defending_player_index = None
        self.combat_damage_resolved = False
        self.combat_first_strike_done = False
        self.combat_attackers_locked = False
        self.combat_blockers_locked = False
        for player in self.players:
            for permanent in player.battlefield:
                permanent.attacking = False
                permanent.defending_player_index = None
                permanent.blocked = False
                permanent.blocking_attacker_controller = None
                permanent.blocking_attacker_index = None
                if clear_damage_marked:
                    permanent.damage_marked = 0
        # Clearing attacking status can change dynamic P/T (e.g. Gaea's Liege
        # reverts from the defender's Forest count to its controller's).
        self._refresh_dynamic_creatures()

    def _prune_combat_state(self) -> None:
        if self.active_player_index < 0 or self.active_player_index >= len(self.players):
            self._reset_combat_state(clear_damage_marked=False)
            return
        active = self.players[self.active_player_index]
        if self.combat_defending_player_index is None:
            if self.combat_attackers or self.combat_blockers:
                self._reset_combat_state(clear_damage_marked=False)
            return
        if self.combat_defending_player_index < 0 or self.combat_defending_player_index >= len(self.players):
            self._reset_combat_state(clear_damage_marked=False)
            return
        defender = self.players[self.combat_defending_player_index]

        valid_attackers: dict[int, int] = {}
        for attacker_idx, defending_idx in self.combat_attackers.items():
            if defending_idx != self.combat_defending_player_index:
                continue
            if attacker_idx < 0 or attacker_idx >= len(active.battlefield):
                continue
            attacker = active.battlefield[attacker_idx]
            if attacker.card.primary_type != "creature":
                continue
            valid_attackers[attacker_idx] = defending_idx
        self.combat_attackers = valid_attackers

        valid_blockers: dict[int, int] = {}
        for blocker_idx, attacker_idx in self.combat_blockers.items():
            if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                continue
            blocker = defender.battlefield[blocker_idx]
            if blocker.card.primary_type != "creature":
                continue
            if attacker_idx not in self.combat_attackers:
                continue
            valid_blockers[blocker_idx] = attacker_idx
        self.combat_blockers = valid_blockers

        # Preserve "was ever blocked" state: once a creature is blocked it stays
        # blocked through the entire combat damage phase even if its blocker dies
        # (e.g. killed by first-strike damage in the first pass).
        was_blocked = {
            idx: perm.blocked
            for idx, perm in enumerate(active.battlefield)
            if perm.blocked
        }

        for player in self.players:
            for permanent in player.battlefield:
                permanent.attacking = False
                permanent.defending_player_index = None
                permanent.blocked = False
                permanent.blocking_attacker_controller = None
                permanent.blocking_attacker_index = None

        for attacker_idx, defending_idx in self.combat_attackers.items():
            attacker = active.battlefield[attacker_idx]
            attacker.attacking = True
            attacker.defending_player_index = defending_idx
            attacker.blocked = was_blocked.get(attacker_idx, False) or any(
                value == attacker_idx for value in self.combat_blockers.values()
            )

        for blocker_idx, attacker_idx in self.combat_blockers.items():
            blocker = defender.battlefield[blocker_idx]
            blocker.blocking_attacker_controller = self.active_player_index
            blocker.blocking_attacker_index = attacker_idx

        # Attacking/defending status can change a creature's power and toughness
        # (e.g. Gaea's Liege uses the defending player's Forests while attacking),
        # so recompute dynamic P/T now that combat flags have settled.
        self._refresh_dynamic_creatures()

    def _can_block_attacker(self, blocker: Permanent, attacker: Permanent) -> bool:
        if attacker.metadata.get("cant_be_blocked_until_eot"):
            return False

        attacker_program = compile_card_oracle(attacker.card)
        attacker_kinds = {i.kind for i in attacker_program.instructions}

        if "cant_be_blocked" in attacker_kinds:
            return False

        attacker_has_flying = self._has_keyword(attacker, "flying")
        blocker_has_flying = self._has_keyword(blocker, "flying")
        blocker_has_reach = self._has_keyword(blocker, "reach")
        if attacker_has_flying and not (blocker_has_flying or blocker_has_reach):
            return False

        # Fear: attacker can't be blocked except by artifact creatures and/or black creatures
        attacker_has_fear = self._has_keyword(attacker, "fear")
        if attacker_has_fear:
            # artifact creatures can block (type_line contains 'artifact' and primary_type is creature)
            is_artifact_creature = blocker.card.primary_type == "creature" and "artifact" in blocker.card.type_line.lower()
            # black creatures can block (color contains 'B')
            is_black_creature = "B" in blocker.card.colors
            if not (is_artifact_creature or is_black_creature):
                return False

        if "cant_be_blocked_by_walls" in attacker_kinds and "wall" in blocker.card.type_line.lower():
            return False

        # Invisibility: attacker can only be blocked by Walls
        if attacker.metadata.get("only_blockable_by_walls") and "wall" not in blocker.card.type_line.lower():
            return False

        # Ironclaw Orcs: blocker can't block creatures with power 2 or greater
        blocker_program = compile_card_oracle(blocker.card)
        if any(i.kind == "cant_block_power_2_or_greater" for i in blocker_program.instructions):
            if attacker.effective_power >= 2:
                return False

        return True

    def _destroy_marked_creatures(self) -> None:
        any_died = False
        for player in self.players:
            survivors: list[Permanent] = []
            for permanent in player.battlefield:
                if permanent.card.primary_type != "creature":
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
                if permanent.regeneration_shield > 0:
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

    def declare_attackers(
        self,
        controller_index: int,
        attacker_indices: list[int],
        defending_player_index: int | None = None,
    ) -> tuple[bool, str]:
        if self.current_turn_phase != "combat" or self.current_step != "declare_attackers":
            return False, "attackers can only be declared during declare_attackers"
        if controller_index != self.active_player_index:
            return False, "only the active player may declare attackers"

        defender_idx = defending_player_index if defending_player_index is not None else 1 - controller_index
        if defender_idx < 0 or defender_idx >= len(self.players) or defender_idx == controller_index:
            return False, "invalid defending player"

        controller = self.players[controller_index]
        unique_indices = sorted(set(attacker_indices))
        required_attackers: list[str] = []
        for idx, attacker in enumerate(controller.battlefield):
            if attacker.card.primary_type != "creature" or attacker.tapped:
                continue
            if idx in unique_indices:
                continue
            if self.can_attack(attacker, defender_idx) and self._must_attack_if_able(attacker):
                required_attackers.append(attacker.card.name)
        if required_attackers:
            if len(required_attackers) == 1:
                return False, f"{required_attackers[0]} must attack if able"
            names = ", ".join(required_attackers)
            return False, f"{names} must attack if able"

        for idx in unique_indices:
            if idx < 0 or idx >= len(controller.battlefield):
                return False, "attacker index out of range"
            attacker = controller.battlefield[idx]
            if attacker.card.primary_type != "creature":
                return False, "only creatures can attack"
            if attacker.tapped:
                return False, f"{attacker.card.name} is tapped"
            if not self.can_attack(attacker, defender_idx):
                return False, f"{attacker.card.name} cannot attack"

        self.combat_defending_player_index = defender_idx
        self.combat_attackers = {idx: defender_idx for idx in unique_indices}
        self.combat_blockers = {}
        self.combat_damage_resolved = False
        self.combat_first_strike_done = False
        self.combat_attackers_locked = True
        self.combat_blockers_locked = False
        self._prune_combat_state()

        for idx in unique_indices:
            attacker = controller.battlefield[idx]
            attacker.tapped = True
            attacker.metadata["attacked_this_turn"] = True

        self._prune_combat_state()
        self.log.append(f"{controller.name} declared {len(unique_indices)} attacker(s)")
        if unique_indices:
            self._fire_attack_triggers(controller_index)
        return True, "declared attackers"

    def _fire_attack_triggers(self, controller_index: int) -> None:
        """Fire "whenever one or more creatures you control attack" triggers.

        Covers Raging River and similar enchantments whose ability triggers once
        when the controller declares one or more attackers (Rule 508.1, 603.2).
        """
        from ..game_types import OracleExecutionContext, OracleStateMachine

        controller = self.players[controller_index]
        defender_index = self.combat_defending_player_index
        defender = (
            self.players[defender_index]
            if isinstance(defender_index, int) and 0 <= defender_index < len(self.players)
            else controller
        )
        for permanent in list(controller.battlefield):
            program = compile_card_oracle(permanent.card)
            for trig in program.triggered_abilities:
                if trig.condition.kind != "one_or_more_attack" or trig.instruction is None:
                    continue
                context = OracleExecutionContext(
                    caster=controller,
                    target=defender,
                    card=permanent.card,
                    source_permanent=permanent,
                )
                OracleStateMachine(self, context).run(trig.instruction)
                self.log.append(f"{permanent.card.name} triggered on attack")

    def declare_blockers(self, controller_index: int, blocker_to_attacker: dict[int, int]) -> tuple[bool, str]:
        if self.current_turn_phase != "combat" or self.current_step != "declare_blockers":
            return False, "blockers can only be declared during declare_blockers"
        if self.combat_defending_player_index is None:
            return False, "no defending player set"
        if controller_index != self.combat_defending_player_index:
            return False, "only defending player may declare blockers"

        self._prune_combat_state()
        defender = self.players[controller_index]
        attacker_controller = self.players[self.active_player_index]
        assignments: dict[int, int] = {}

        for blocker_idx, attacker_idx in blocker_to_attacker.items():
            if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                return False, "blocker index out of range"
            if attacker_idx not in self.combat_attackers:
                return False, "blocker assigned to non-attacker"
            blocker = defender.battlefield[blocker_idx]
            attacker = attacker_controller.battlefield[attacker_idx]
            if blocker.card.primary_type != "creature":
                return False, "only creatures can block"
            if blocker.tapped:
                return False, f"{blocker.card.name} is tapped"
            if not self._can_block_attacker(blocker, attacker):
                return False, f"{blocker.card.name} cannot block {attacker.card.name}"
            assignments[blocker_idx] = attacker_idx

        # Lure enforcement: every creature that can block a Lure attacker must do so
        for attacker_idx in self.combat_attackers:
            if attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            if not attacker.metadata.get("lure_active"):
                continue
            for blocker_idx, blocker in enumerate(defender.battlefield):
                if blocker.card.primary_type != "creature" or blocker.tapped:
                    continue
                if not self._can_block_attacker(blocker, attacker):
                    continue
                if blocker_idx not in assignments:
                    return False, f"{blocker.card.name} must block {attacker.card.name} due to Lure"

        self.combat_blockers = assignments
        self.combat_blockers_locked = True
        self._prune_combat_state()
        self.log.append(f"{defender.name} declared {len(assignments)} blocker(s)")
        return True, "declared blockers"

    def _combat_blockers_for_attacker(self, attacker_idx: int) -> list[int]:
        return [blocker_idx for blocker_idx, a_idx in self.combat_blockers.items() if a_idx == attacker_idx]

    def _needs_manual_damage_assignment(self) -> bool:
        """Return True when any blocked attacker has 2+ blockers, requiring player input."""
        for attacker_idx in self.combat_attackers:
            if len(self._combat_blockers_for_attacker(attacker_idx)) >= 2:
                return True
        return False

    def _build_auto_damage_assignment(self) -> dict[int, dict[int, int]]:
        """Build a sensible default damage assignment for every blocked attacker.

        Single-blocked attackers assign their full power to that blocker (only
        lethal for tramplers, so the remainder can trample through). Multi-blocked
        attackers assign lethal to each blocker in declared order and dump any
        leftover power onto the last blocker that received lethal — this keeps the
        assignment legal (the resolver rejects a positive-but-sub-lethal amount)
        while still killing as many blockers as the attacker can.
        """
        if not self.combat_attackers:
            return {}
        attacker_controller = self.players[self.active_player_index]
        defending_index = self.combat_defending_player_index
        defender = (
            self.players[defending_index]
            if isinstance(defending_index, int) and 0 <= defending_index < len(self.players)
            else None
        )
        assignment: dict[int, dict[int, int]] = {}
        for attacker_idx in self.combat_attackers:
            if attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            blockers = sorted(self._combat_blockers_for_attacker(attacker_idx))
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

            # Multiple blockers: assign lethal in declared order while affordable.
            power_left = max(0, attacker.effective_power)
            per_blocker: dict[int, int] = {}
            last_lethal_idx: int | None = None
            for blocker_idx in blockers:
                need = lethal_for(blocker_idx)
                if need <= power_left:
                    per_blocker[blocker_idx] = need
                    power_left -= need
                    last_lethal_idx = blocker_idx
                else:
                    per_blocker[blocker_idx] = 0
            # Dump leftover power onto the last blocker we killed (now > lethal, still
            # legal). Tramplers keep the leftover so it spills to the defender instead.
            if power_left > 0 and not has_trample and last_lethal_idx is not None:
                per_blocker[last_lethal_idx] += power_left
            assignment[attacker_idx] = per_blocker
        return assignment

    def resolve_combat_damage(self, controller_index: int, attacker_damage: dict[int, dict[int, int]] | None = None) -> tuple[bool, str]:
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
        defending_index = self.combat_defending_player_index
        if defending_index is None:
            return False, "no defending player"
        defender = self.players[defending_index]

        def participates_in_first_strike(perm: Permanent) -> bool:
            return self._has_keyword(perm, "first strike") or self._has_keyword(perm, "double strike")

        def participates_in_second_strike(perm: Permanent) -> bool:
            return self._has_keyword(perm, "double strike") or (
                not self._has_keyword(perm, "first strike") and not self._has_keyword(perm, "double strike")
            )

        if attacker_damage is None:
            attacker_damage = {}

        attacker_passes: list[int] = []
        blocker_passes: list[int] = []
        for attacker_idx in self.combat_attackers:
            if attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            blockers = self._combat_blockers_for_attacker(attacker_idx)
            if blockers:
                for blocker_idx in blockers:
                    if blocker_idx < len(defender.battlefield):
                        blocker = defender.battlefield[blocker_idx]
                        if participates_in_first_strike(attacker) or participates_in_first_strike(blocker):
                            attacker_passes.append(attacker_idx)
                            blocker_passes.append(blocker_idx)
                            break

        has_first_strike_pass = bool(attacker_passes)
        run_first_pass = has_first_strike_pass and not self.combat_first_strike_done

        # (defending_idx, blocker_idx, damage, attacker_idx)
        attacker_damage_events: list[tuple[int, int, int, int]] = []
        defender_damage_events: list[tuple[int, int]] = []

        for attacker_idx in sorted(self.combat_attackers):
            if attacker_idx < 0 or attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            if attacker.effective_power <= 0:
                continue
            if run_first_pass and not participates_in_first_strike(attacker):
                continue
            if not run_first_pass and has_first_strike_pass and not participates_in_second_strike(attacker):
                continue

            blockers = self._combat_blockers_for_attacker(attacker_idx)
            power_left = attacker.effective_power
            if not blockers:
                if self.combat_damage_prevented_until_eot:
                    continue
                # A creature that was declared blocked (e.g. its blocker died to
                # first-strike damage) is still "blocked" — it cannot deal damage
                # to the defending player unless it has trample.
                if attacker.blocked and not self._has_keyword(attacker, "trample"):
                    continue
                damage = self._prevent_damage(defender, power_left)
                if damage > 0:
                    defender_damage_events.append((defending_index, damage))
                continue

            requested = attacker_damage.get(attacker_idx, {})
            assigned_total = 0
            block_order = sorted(blockers)
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
                if not self._has_keyword(attacker, "trample") and requested_damage > 0 and requested_damage < lethal:
                    return False, "must assign lethal to each blocker in order"
                assigned_total += requested_damage
                power_left -= requested_damage
                if requested_damage > 0:
                    attacker_damage_events.append((defending_index, blocker_idx, requested_damage, attacker_idx))

            if assigned_total > attacker.effective_power:
                return False, "assigned combat damage exceeds attacker power"
            if self._has_keyword(attacker, "trample") and power_left > 0 and not self.combat_damage_prevented_until_eot:
                trample_damage = self._prevent_damage(defender, power_left)
                if trample_damage > 0:
                    defender_damage_events.append((defending_index, trample_damage))

        for blocker_idx, attacker_idx in sorted(self.combat_blockers.items()):
            if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                continue
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
            attacker.damage_marked += blocker.effective_power
            self._fire_dealt_damage_triggers(attacker)
            # 704.5h: mark attacker if blocker has deathtouch
            if self._has_keyword(blocker, "deathtouch") and blocker.effective_power > 0:
                attacker.metadata["received_deathtouch"] = True

        for defending_idx, blocker_idx, damage, a_idx in attacker_damage_events:
            if defending_idx >= len(self.players):
                continue
            defending_player = self.players[defending_idx]
            if blocker_idx < 0 or blocker_idx >= len(defending_player.battlefield):
                continue
            defending_player.battlefield[blocker_idx].damage_marked += damage
            if damage > 0:
                self._fire_dealt_damage_triggers(defending_player.battlefield[blocker_idx])
            # 704.5h: mark blocker if attacker has deathtouch
            if a_idx < len(attacker_controller.battlefield) and damage > 0:
                atk = attacker_controller.battlefield[a_idx]
                if self._has_keyword(atk, "deathtouch"):
                    defending_player.battlefield[blocker_idx].metadata["received_deathtouch"] = True

        total_player_damage = sum(dmg for _, dmg in defender_damage_events)
        for _, damage in defender_damage_events:
            # Prevention was already applied when the event was recorded.
            defender.life -= damage
            self._on_player_dealt_damage(defender, damage)

        self._destroy_marked_creatures()
        self.check_state_based_actions()
        self._prune_combat_state()

        if total_player_damage > 0:
            self.log.append(
                f"{defender.name} took {total_player_damage} combat damage (life: {defender.life + total_player_damage} → {defender.life})"
            )

        if run_first_pass:
            self.combat_first_strike_done = True
            self.log.append("Resolved first strike combat damage")
            return True, "resolved first strike combat damage"

        self.combat_damage_resolved = True
        self.log.append("Resolved combat damage")
        return True, "resolved combat damage"

    def get_combat_state(self) -> dict[str, object]:
        self._prune_combat_state()
        return {
            "defending_player_index": self.combat_defending_player_index,
            "attackers": [{"attacker_index": k, "defending_player_index": v} for k, v in sorted(self.combat_attackers.items())],
            "blockers": [{"blocker_index": k, "attacker_index": v} for k, v in sorted(self.combat_blockers.items())],
            "damage_resolved": self.combat_damage_resolved,
            "first_strike_done": self.combat_first_strike_done,
            "attackers_locked": self.combat_attackers_locked,
            "blockers_locked": self.combat_blockers_locked,
        }

    def can_attack(self, attacker: Permanent, defending_player_index: int) -> bool:
        if self._is_summoning_sick(attacker):
            return False

        program = compile_card_oracle(attacker.card)
        instr_kinds = {i.kind for i in program.instructions}

        if "cant_attack_without_island" in instr_kinds:
            defending = self.players[defending_player_index]
            has_island = any("island" in perm.card.type_line.lower() for perm in defending.battlefield)
            return has_island

        if "cant_attack" in instr_kinds:
            return False

        if "Defender" in attacker.card.keywords and not attacker.metadata.get("can_attack_as_though_no_defender"):
            return False

        # Island Sanctuary: defending player is protected from non-flying, non-islandwalk attackers
        defending = self.players[defending_player_index]
        if defending.island_sanctuary_protected:
            has_flying = self._has_keyword(attacker, "flying")
            has_islandwalk = attacker.metadata.get("has_islandwalk") or "Islandwalk" in attacker.card.keywords
            if not (has_flying or has_islandwalk):
                return False

        return True

    def _must_attack_if_able(self, attacker: Permanent) -> bool:
        if attacker.metadata.get("must_attack_until_eot"):
            return True
        program = compile_card_oracle(attacker.card)
        return any(i.kind == "must_attack_each_combat" for i in program.instructions)

    def end_combat(self, step_already_started: bool = False) -> None:
        phase = "combat"
        step = "end_of_combat"
        if not step_already_started:
            self._set_phase_and_step(phase, step)
            self._on_step_or_phase_begin(phase, step)
        for player in self.players:
            for permanent in player.battlefield:
                if permanent.metadata.get("animate_until_end_of_combat"):
                    permanent.metadata.pop("animate_until_end_of_combat", None)
                    permanent.metadata.pop("absolute_power", None)
                    permanent.metadata.pop("absolute_toughness", None)
        self.combat_damage_prevented_until_eot = False
        for player in self.players:
            player.combat_damage_cap_one_charges = 0
        self._reset_combat_state(clear_damage_marked=False)
        if self._receives_priority(step):
            self._resolve_priority_window()
        self._on_step_or_phase_end(phase, step)
