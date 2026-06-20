from __future__ import annotations

"""End of combat step (CR 511).

Fires "at end of combat" triggered abilities (Clockwork Beast counter removal,
Cockatrice/Thicket Basilisk delayed destruction) while "attacked or blocked this
combat" is still known, then clears until-end-of-combat effects and combat state.
"""

from ..models import Permanent
from ..oracle import compile_card_oracle


class EndOfCombatStepMixin:
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
