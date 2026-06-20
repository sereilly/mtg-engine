from __future__ import annotations

"""Declare blockers step (CR 509).

The defending player declares blockers as a turn-based action. This module holds
block legality (``_can_block_attacker`` and its landwalk helper), Lure
enforcement, the block-triggered abilities (Cockatrice/Thicket Basilisk), band
block propagation (CR 702.22h), and the Rampage/Flanking combat buffs that fire
when a creature becomes blocked.
"""

import re

from ..models import Permanent, PlayerState
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


class DeclareBlockersStepMixin:
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
        # CR 509.4: once blockers have been declared (the turn-based action of the
        # declare blockers step), the active player receives priority.
        self.start_priority_window(self.active_player_index)
        return True, "declared blockers"

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

    def _combat_blockers_for_attacker(self, attacker_idx: int) -> list[int]:
        return [blocker_idx for blocker_idx, a_idx in self.combat_blockers.items() if a_idx == attacker_idx]

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
