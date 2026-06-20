from __future__ import annotations

"""Declare attackers step (CR 508).

The active player declares attackers (and any attacking bands) as a turn-based
action, taps non-vigilance attackers, fires attack triggers, then receives
priority (CR 508.4). Also holds the attack-legality query (``can_attack``),
"must attack if able" enforcement, and the banding-declaration validation.
"""

from ..models import Permanent, PlayerState
from ..oracle import compile_card_oracle


class DeclareAttackersStepMixin:
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
        # CR 508.4: once attackers have been declared (the turn-based action of the
        # declare attackers step), the active player receives priority.
        self.start_priority_window(self.active_player_index)
        return True, "declared attackers"

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

    # ------------------------------------------------------------------
    # Banding declaration (CR 702.22)
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
