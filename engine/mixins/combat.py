from __future__ import annotations

import re

from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import compile_card_oracle

# Landwalk keyword → the basic land subtype the defender must control for the
# attacker to be unblockable (CR 702.14). Sourced from the attacker's printed
# keywords or a granted "has_<type>walk" metadata flag (e.g. Goblin King).
_LANDWALK_TO_LAND_TYPE = {
    "plainswalk": "plains",
    "islandwalk": "island",
    "swampwalk": "swamp",
    "mountainwalk": "mountain",
    "forestwalk": "forest",
}

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
        self.combat_bands = []
        self.combat_band_blocks = {}
        self.combat_banding_damage = {}
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

        # CR 702.22h: propagate band blocks (no-op when no bands were declared).
        # Recomputed here so the propagated "blocked" status survives every prune.
        self._apply_band_block_propagation()

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

        # Protection (CR 702.16f): an attacking creature with protection from a
        # quality can't be blocked by creatures that have that quality.
        if self._is_protected_from(attacker, blocker):
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

        # Landwalk (CR 702.14): the attacker can't be blocked if the defending
        # player controls a land of the matching basic type. The blocker is one of
        # the defending player's creatures, so its controller is the defender.
        if self._attacker_has_active_landwalk(attacker, blocker):
            return False

        return True

    def _attacker_has_active_landwalk(self, attacker: Permanent, blocker: Permanent) -> bool:
        defender = next((p for p in self.players if blocker in p.battlefield), None)
        if defender is None:
            return False
        for walk, land_type in _LANDWALK_TO_LAND_TYPE.items():
            has_walk = attacker.metadata.get(f"has_{walk}") or any(
                kw.lower() == walk for kw in attacker.card.keywords
            )
            if not has_walk:
                continue
            for perm in defender.battlefield:
                if perm.card.primary_type != "land":
                    continue
                override = str(perm.metadata.get("land_type_override", "")).lower()
                if override:
                    if land_type in override:
                        return True
                elif land_type in perm.card.type_line.lower():
                    return True
        return False

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
        bands: list[list[int]] | None = None,
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

        # CR 702.22c: validate any declared attacking bands before committing.
        validated_bands, band_error = self._validate_attacking_bands(
            bands, unique_indices, controller
        )
        if band_error is not None:
            return False, band_error

        self.combat_defending_player_index = defender_idx
        self.combat_attackers = {idx: defender_idx for idx in unique_indices}
        self.combat_blockers = {}
        self.combat_bands = validated_bands
        self.combat_band_blocks = {}
        self.combat_banding_damage = {}
        self.combat_damage_resolved = False
        self.combat_first_strike_done = False
        self.combat_attackers_locked = True
        self.combat_blockers_locked = False
        self._prune_combat_state()

        for idx in unique_indices:
            attacker = controller.battlefield[idx]
            # CR 702.20b: attacking doesn't cause a creature with vigilance to tap.
            if not self._has_keyword(attacker, "vigilance"):
                attacker.tapped = True
            attacker.metadata["attacked_this_turn"] = True

        self._prune_combat_state()
        self.log.append(f"{controller.name} declared {len(unique_indices)} attacker(s)")
        if validated_bands:
            self.log.append(f"{controller.name} declared {len(validated_bands)} band(s)")
        if unique_indices:
            self._fire_attack_triggers(controller_index)
        return True, "declared attackers"

    # ------------------------------------------------------------------
    # Banding (CR 702.22)
    # ------------------------------------------------------------------

    def _creature_has_banding(self, permanent: Permanent) -> bool:
        """Whether a creature currently has banding (printed or granted)."""
        if permanent.metadata.get("gains_banding_until_eot"):
            return True
        return self._has_keyword(permanent, "banding")

    def _validate_attacking_bands(
        self,
        bands: list[list[int]] | None,
        attacker_indices: list[int],
        controller: PlayerState,
    ) -> tuple[list[list[int]], str | None]:
        """Validate declared attacking bands (CR 702.22c). Returns (bands, error).

        A band is one or more attacking creatures with banding plus up to one
        attacking creature without banding; each creature may join only one band.
        """
        if not bands:
            return [], None
        attacker_set = set(attacker_indices)
        seen: set[int] = set()
        validated: list[list[int]] = []
        for group in bands:
            members = sorted(set(group))
            if len(members) < 2:
                return [], "a band must contain at least two creatures"
            banding_count = 0
            nonbanding_count = 0
            for idx in members:
                if idx not in attacker_set:
                    return [], "every band member must be a declared attacker"
                if idx in seen:
                    return [], "a creature may belong to only one band"
                seen.add(idx)
                if self._creature_has_banding(controller.battlefield[idx]):
                    banding_count += 1
                else:
                    nonbanding_count += 1
            if banding_count < 1:
                return [], "a band needs at least one creature with banding"
            if nonbanding_count > 1:
                return [], "a band may include at most one creature without banding"
            validated.append(members)
        return validated, None

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
        defending_index = self.combat_defending_player_index
        if not isinstance(defending_index, int) or not (0 <= defending_index < len(self.players)):
            return False
        defender = self.players[defending_index]
        for blocker_idx in self._attacker_all_blockers(attacker_idx):
            if 0 <= blocker_idx < len(defender.battlefield):
                if self._creature_has_banding(defender.battlefield[blocker_idx]):
                    return True
        return False

    def _apply_band_block_propagation(self) -> None:
        """CR 702.22h/i: when one band member becomes blocked, every other creature
        in that band becomes blocked by the same blocker(s).

        Recomputed from ``combat_blockers`` so it stays correct as combat state is
        pruned. A no-op when no attacking bands were declared.
        """
        self.combat_band_blocks = {}
        if not self.combat_bands:
            return
        if self.active_player_index < 0 or self.active_player_index >= len(self.players):
            return
        active = self.players[self.active_player_index]
        for band in self.combat_bands:
            band_blockers: set[int] = set()
            for member in band:
                band_blockers.update(self._combat_blockers_for_attacker(member))
            if not band_blockers:
                continue
            for member in band:
                if member < 0 or member >= len(active.battlefield):
                    continue
                extra = sorted(band_blockers - set(self._combat_blockers_for_attacker(member)))
                if extra:
                    self.combat_band_blocks[member] = extra
                active.battlefield[member].blocked = True

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
        if defender_index != self.combat_defending_player_index:
            return False, "only the defending player may assign banding damage"
        for attacker_idx in attacker_damage:
            if not self._attacker_blocked_by_banding(attacker_idx):
                return False, "attacker is not blocked by a creature with banding"
        self.combat_banding_damage = {
            int(a): {int(b): int(v) for b, v in dmg.items()}
            for a, dmg in attacker_damage.items()
        }
        return True, "banding damage assignment recorded"

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

    def _fire_end_of_combat_triggers(self) -> None:
        """Resolve "at end of combat" triggered abilities (Rule 603.2, 508).

        Currently covers Clockwork Beast: "At end of combat, if this creature
        attacked or blocked this combat, remove a +1/+0 counter from it."
        """
        clockwork_line = (
            "at end of combat, if this creature attacked or blocked this combat, "
            "remove a +1/+0 counter from it"
        )
        for player in self.players:
            for permanent in player.battlefield:
                program = compile_card_oracle(permanent.card)
                if not any(clockwork_line == line for line in program.static_lines):
                    continue
                attacked_or_blocked = permanent.metadata.get(
                    "attacked_this_turn"
                ) or permanent.metadata.get("blocked_this_combat")
                if not attacked_or_blocked:
                    continue
                counters = int(permanent.metadata.get("plus_1_0_counters", 0))
                if counters <= 0:
                    continue
                permanent.metadata["plus_1_0_counters"] = counters - 1
                permanent.power_bonus -= 1
                self.log.append(
                    f"{permanent.card.name} removes a +1/+0 counter at end of combat "
                    f"({counters - 1} remaining)"
                )

        self._resolve_end_of_combat_destruction()

    def _resolve_end_of_combat_destruction(self) -> None:
        """Destroy creatures marked by a "destroy at end of combat" trigger.

        Used by Cockatrice / Thicket Basilisk (see _fire_block_triggers). Honors
        regeneration shields like any other destruction.
        """
        any_died = False
        for player in self.players:
            survivors: list[Permanent] = []
            for permanent in player.battlefield:
                if not permanent.metadata.pop("destroy_at_end_of_combat", False):
                    survivors.append(permanent)
                    continue
                if permanent.regeneration_shield > 0:
                    permanent.regeneration_shield -= 1
                    permanent.tapped = True
                    permanent.damage_marked = 0
                    survivors.append(permanent)
                    self.log.append(f"{permanent.card.name} regenerated")
                    continue
                self._permanent_to_graveyard(player, permanent)
                self._trigger_aura_death_effects(permanent, player)
                self.log.append(f"{permanent.card.name} was destroyed at end of combat")
                any_died = True
            player.battlefield = survivors
        if any_died:
            self._recalculate_lord_buffs()

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
        for blocker_idx in assignments:
            if 0 <= blocker_idx < len(defender.battlefield):
                defender.battlefield[blocker_idx].metadata["blocked_this_combat"] = True
        self._prune_combat_state()
        self.log.append(f"{defender.name} declared {len(assignments)} blocker(s)")
        # 509.1i / 509.2a: abilities that trigger on blockers being declared fire now.
        self._fire_block_triggers(controller_index)
        self._apply_rampage_and_flanking(controller_index)
        return True, "declared blockers"

    def _apply_temporary_buff(self, permanent: Permanent, power: int, toughness: int) -> None:
        """Apply an "until end of turn" P/T change that the cleanup step reverts."""
        permanent.metadata["temporary_power_bonus_until_eot"] = (
            int(permanent.metadata.get("temporary_power_bonus_until_eot", 0)) + power
        )
        permanent.metadata["temporary_toughness_bonus_until_eot"] = (
            int(permanent.metadata.get("temporary_toughness_bonus_until_eot", 0)) + toughness
        )
        permanent.power_bonus += power
        permanent.toughness_bonus += toughness

    def _rampage_value(self, permanent: Permanent) -> int:
        """The N of "Rampage N" on this creature, or 0 if it has no rampage."""
        if not self._has_keyword(permanent, "rampage"):
            # Keyword may be printed as "Rampage 2"; _has_keyword won't match that
            # against the bare word, so also scan the keyword list directly.
            if not any("rampage" in kw.lower() for kw in permanent.card.keywords):
                return 0
        for source in (*permanent.card.keywords, permanent.card.oracle_text or ""):
            match = re.search(r"rampage (\d+)", source.lower())
            if match:
                return int(match.group(1))
        return 0

    def _apply_rampage_and_flanking(self, controller_index: int) -> None:
        """Resolve Rampage (CR 702.23) and Flanking (CR 702.25) on declared blocks.

        Both trigger when a creature becomes blocked. Rampage gives the attacker
        +N/+N for each blocker beyond the first; flanking gives each non-flanking
        blocker -1/-1. Applied as until-end-of-turn effects.
        """
        if self.active_player_index < 0 or self.active_player_index >= len(self.players):
            return
        attacker_controller = self.players[self.active_player_index]
        if controller_index < 0 or controller_index >= len(self.players):
            return
        defender = self.players[controller_index]

        for attacker_idx in self.combat_attackers:
            if attacker_idx < 0 or attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            blocker_indices = self._combat_blockers_for_attacker(attacker_idx)
            if not blocker_indices:
                continue

            # CR 702.23a: Rampage N — +N/+N for each blocker beyond the first.
            rampage_n = self._rampage_value(attacker)
            if rampage_n and len(blocker_indices) > 1:
                bonus = rampage_n * (len(blocker_indices) - 1)
                self._apply_temporary_buff(attacker, bonus, bonus)
                self.log.append(
                    f"{attacker.card.name} gets +{bonus}/+{bonus} from rampage "
                    f"({len(blocker_indices)} blockers)"
                )

            # CR 702.25a: Flanking — each non-flanking blocker gets -1/-1 per instance.
            if self._has_keyword(attacker, "flanking"):
                for blocker_idx in blocker_indices:
                    if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                        continue
                    blocker = defender.battlefield[blocker_idx]
                    if self._has_keyword(blocker, "flanking"):
                        continue
                    self._apply_temporary_buff(blocker, -1, -1)
                    self.log.append(
                        f"{blocker.card.name} gets -1/-1 from {attacker.card.name}'s flanking"
                    )
        # Flanking may drop a blocker's toughness to 0; clean it up now.
        self.check_state_based_actions()

    def _fire_block_triggers(self, controller_index: int) -> None:
        """Put abilities that trigger on blockers being declared onto the stack.

        Rule 509.1i / 509.2a: these triggered abilities are placed on the stack
        before the active player gets priority (they don't resolve immediately).
        Covers Cockatrice / Thicket Basilisk: "Whenever this creature blocks or
        becomes blocked by a non-Wall creature, destroy that creature at end of
        combat." Per 509.3a the trigger fires once for the creature that blocks
        (targeting the attacker it blocks) and per 509.3c/509.3d once for the
        attacker that becomes blocked (one per creature blocking it). A Wall
        partner is excluded by the "non-Wall" clause, checked now (509.3f).
        """
        if controller_index < 0 or controller_index >= len(self.players):
            return
        if self.active_player_index < 0 or self.active_player_index >= len(self.players):
            return
        from ..game_types import StackItem

        defender = self.players[controller_index]
        attacker_controller = self.players[self.active_player_index]

        def block_destroy_instruction(perm: Permanent):
            program = compile_card_oracle(perm.card)
            for trig in program.triggered_abilities:
                if (
                    trig.condition.kind == "cockatrice_blocks_or_blocked"
                    and trig.instruction is not None
                    and trig.instruction.kind == "delayed_destroy_blocked_or_blocker"
                ):
                    return trig.instruction, trig.source_line
            return None, None

        def queue_trigger(
            source: Permanent,
            source_controller_index: int,
            victim: Permanent,
            victim_player_index: int,
            victim_index: int,
        ) -> None:
            if "wall" in victim.card.type_line.lower():
                return
            instruction, source_line = block_destroy_instruction(source)
            if instruction is None:
                return
            self.stack.append(
                StackItem(
                    card=source.card,
                    caster_index=source_controller_index,
                    target_player_index=victim_player_index,
                    target_permanent_index=victim_index,
                    x_value=None,
                    ability_instruction=instruction,
                    ability_effect_kind="triggered_delayed_destroy",
                    source_permanent=source,
                    ability_text=source_line,
                )
            )
            self.log.append(
                f"{source.card.name} block trigger added to stack (targeting {victim.card.name})"
            )

        # A blocker that blocks an attacker (509.3a "Whenever this creature blocks").
        for blocker_idx, attacker_idx in self.combat_blockers.items():
            if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                continue
            blocker = defender.battlefield[blocker_idx]
            if 0 <= attacker_idx < len(attacker_controller.battlefield):
                queue_trigger(
                    blocker,
                    controller_index,
                    attacker_controller.battlefield[attacker_idx],
                    self.active_player_index,
                    attacker_idx,
                )

        # An attacker that becomes blocked (509.3c/509.3d "becomes blocked").
        for attacker_idx in self.combat_attackers:
            if attacker_idx < 0 or attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            for blocker_idx in self._combat_blockers_for_attacker(attacker_idx):
                if 0 <= blocker_idx < len(defender.battlefield):
                    queue_trigger(
                        attacker,
                        self.active_player_index,
                        defender.battlefield[blocker_idx],
                        controller_index,
                        blocker_idx,
                    )

    def _combat_blockers_for_attacker(self, attacker_idx: int) -> list[int]:
        return [blocker_idx for blocker_idx, a_idx in self.combat_blockers.items() if a_idx == attacker_idx]

    def _needs_manual_damage_assignment(self) -> bool:
        """Return True when combat damage needs a player's assignment choice.

        That is any blocked attacker with 2+ blockers, or any attacking band whose
        block propagated (CR 702.22h) so the active player must choose where each
        shared blocker's damage goes (702.22k). Pure non-banding combat is
        unaffected, so AI auto-resolution keeps working unchanged.
        """
        if self.combat_band_blocks:
            return True
        for attacker_idx in self.combat_attackers:
            if len(self._attacker_all_blockers(attacker_idx)) >= 2:
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

    def resolve_combat_damage(
        self,
        controller_index: int,
        attacker_damage: dict[int, dict[int, int]] | None = None,
        blocker_damage: dict[int, int] | None = None,
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

        # None means "no explicit assignment given" — fall back to the engine's
        # default assignment (full power to blockers). An empty dict, by contrast,
        # is an explicit "assign nothing". This lets a caller supply only
        # blocker_damage (CR 702.22k) and still have attackers deal normally.
        if attacker_damage is None:
            attacker_damage = self._build_auto_damage_assignment()

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
                for blocker_idx in blockers:
                    if blocker_idx < len(defender.battlefield):
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
        defender_damage_events: list[tuple[int, int]] = []
        # CR 702.15b: damage dealt by a source with lifelink gains its controller
        # that much life. Accumulated per controller and applied after all combat
        # damage is dealt this step (the life-gain events happen simultaneously).
        lifelink_gain: dict[int, int] = {}

        def add_lifelink(controller_index: int, amount: int) -> None:
            if amount > 0:
                lifelink_gain[controller_index] = lifelink_gain.get(controller_index, 0) + amount

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
                damage = self._prevent_damage(defender, power_left)
                if damage > 0:
                    defender_damage_events.append((defending_index, damage))
                    if self._has_keyword(attacker, "lifelink"):
                        add_lifelink(self.active_player_index, damage)
                continue

            # CR 702.22j: when an attacker is blocked by a creature with banding, the
            # defending player (not the active player) assigns that attacker's damage.
            if self._attacker_blocked_by_banding(attacker_idx) and attacker_idx in self.combat_banding_damage:
                requested = self.combat_banding_damage[attacker_idx]
            else:
                requested = attacker_damage.get(attacker_idx, {})
            assigned_total = 0
            block_order = sorted(blockers)
            # CR 510.1c: with multiple blockers ordered by the attacker, a blocker
            # may be assigned combat damage only if every earlier blocker in the
            # order has been assigned lethal damage. A single (or the last) blocker
            # carries no such constraint and may receive any amount, even sub-lethal.
            sublethal_blocker_seen = False
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
                if not self._has_keyword(attacker, "trample"):
                    if sublethal_blocker_seen and requested_damage > 0:
                        return False, "must assign lethal to each blocker in order"
                    if requested_damage < lethal:
                        sublethal_blocker_seen = True
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
                    if self._has_keyword(attacker, "lifelink"):
                        add_lifelink(self.active_player_index, trample_damage)

        for blocker_idx, attacker_idx in sorted(self.combat_blockers.items()):
            if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                continue
            if attacker_idx < 0 or attacker_idx >= len(attacker_controller.battlefield):
                continue
            # CR 702.22k: a blocker blocking a band (which always contains a creature
            # with banding) deals its damage where the *active* player chooses among
            # the band members it blocks. Default: the creature it explicitly blocked.
            band = self._attacker_band(attacker_idx)
            if band and blocker_damage and blocker_idx in blocker_damage:
                chosen = blocker_damage[blocker_idx]
                if chosen in band and 0 <= chosen < len(attacker_controller.battlefield):
                    attacker_idx = chosen
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
            dealt = self._mark_damage_on_permanent(attacker, blocker.effective_power)
            if dealt > 0:
                self._fire_dealt_damage_triggers(attacker)
                if self._has_keyword(blocker, "lifelink"):
                    add_lifelink(defending_index, dealt)
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
            dealt = self._mark_damage_on_permanent(blocker_perm, damage)
            if dealt > 0:
                self._fire_dealt_damage_triggers(blocker_perm)
                if source_attacker is not None and self._has_keyword(source_attacker, "lifelink"):
                    add_lifelink(self.active_player_index, dealt)
            # 704.5h: mark blocker if attacker has deathtouch
            if source_attacker is not None and damage > 0:
                if self._has_keyword(source_attacker, "deathtouch"):
                    blocker_perm.metadata["received_deathtouch"] = True

        total_player_damage = sum(dmg for _, dmg in defender_damage_events)
        for _, damage in defender_damage_events:
            # Prevention was already applied when the event was recorded.
            defender.life -= damage
            self._on_player_dealt_damage(defender, damage)

        # CR 702.15b: apply lifelink life gain for damage dealt this step.
        for controller_index, amount in lifelink_gain.items():
            if 0 <= controller_index < len(self.players):
                self._gain_life(self.players[controller_index], amount, source_name="lifelink")

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
            # Banding (CR 702.22): declared attacking bands and the per-attacker
            # blockers added by band propagation (702.22h).
            "bands": [list(band) for band in self.combat_bands],
            "band_blocks": {k: list(v) for k, v in self.combat_band_blocks.items()},
        }

    def creature_attacking_alone(self, permanent: Permanent) -> bool:
        """CR 506.5: a creature is *attacking alone* if it's attacking but no
        other creatures are. Returns False if the permanent isn't itself
        attacking."""
        if not permanent.attacking:
            return False
        attacking = sum(
            1 for player in self.players for perm in player.battlefield if perm.attacking
        )
        return attacking == 1

    def creature_blocking_alone(self, permanent: Permanent) -> bool:
        """CR 506.5: a creature is *blocking alone* if it's blocking but no
        other creatures are. Returns False if the permanent isn't itself
        blocking."""
        if permanent.blocking_attacker_index is None:
            return False
        blocking = sum(
            1
            for player in self.players
            for perm in player.battlefield
            if perm.blocking_attacker_index is not None
        )
        return blocking == 1

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
        # End-of-combat triggered abilities fire before combat state is cleared,
        # while "attacked or blocked this combat" is still known.
        self._fire_end_of_combat_triggers()
        for player in self.players:
            for permanent in player.battlefield:
                if permanent.metadata.get("animate_until_end_of_combat"):
                    permanent.metadata.pop("animate_until_end_of_combat", None)
                    permanent.metadata.pop("absolute_power", None)
                    permanent.metadata.pop("absolute_toughness", None)
                permanent.metadata.pop("blocked_this_combat", None)
        self.combat_damage_prevented_until_eot = False
        for player in self.players:
            player.combat_damage_cap_one_charges = 0
        self._reset_combat_state(clear_damage_marked=False)
        if self._receives_priority(step):
            self._resolve_priority_window()
        self._on_step_or_phase_end(phase, step)
