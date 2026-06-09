from __future__ import annotations

from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import compile_card_oracle
from ._constants import _EOT_METADATA_KEYS

class EndingPhaseMixin:
    def resolve_end_step(self, player_index: int) -> None:
        phase = "ending"
        step = "end"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        destroyed_names: list[str] = []
        for controller in self.players:
            survivors: list[Permanent] = []
            for permanent in controller.battlefield:
                if permanent.metadata.get("destroy_at_next_end_step"):
                    controller.graveyard.append(permanent.card)
                    destroyed_names.append(permanent.card.name)
                else:
                    survivors.append(permanent)
            controller.battlefield = survivors

        for name in destroyed_names:
            self.log.append(f"{name} was destroyed at end step")

        # Pestilence-style: "At the beginning of the end step, if no creatures on the battlefield, sacrifice"
        all_perms = [p for pl in self.players for p in pl.battlefield]
        has_creatures = any(p.card.primary_type == "creature" for p in all_perms)
        if not has_creatures:
            for controller in self.players:
                to_sacrifice: list[Permanent] = []
                for permanent in controller.battlefield:
                    prog = compile_card_oracle(permanent.card)
                    if any(
                        t.condition.kind == "end_step" and t.instruction is not None and t.instruction.kind == "sacrifice_if_no_creatures"
                        for t in prog.triggered_abilities
                    ):
                        to_sacrifice.append(permanent)
                for permanent in to_sacrifice:
                    controller.battlefield.remove(permanent)
                    controller.graveyard.append(permanent.card)
                    self.log.append(f"{permanent.card.name} sacrificed at end step (no creatures)")

        if self._receives_priority(step):
            self.start_priority_window(self.active_player_index)

    def close_end_step(self) -> None:
        if self.current_turn_phase != "ending" or self.current_step != "end":
            return
        if self._receives_priority(self.current_step):
            self.clear_priority_window()
        self._on_step_or_phase_end("ending", "end")

    def resolve_cleanup_step(
        self,
        player_index: int,
        discard_hand_indices: list[int] | None = None,
        defer_discard_selection: bool = False,
    ) -> bool:
        phase = "ending"
        step = "cleanup"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)

        active_player = self.players[player_index]
        cleanup_completed = True
        if not active_player.has_no_max_hand_size:
            max_hand_size = 7
            excess = max(0, len(active_player.hand) - max_hand_size)
            if excess:
                if discard_hand_indices is not None:
                    unique_indices = sorted(set(discard_hand_indices))
                    if len(unique_indices) != excess:
                        raise ValueError(f"expected {excess} cleanup discards, got {len(unique_indices)}")
                    if any(index < 0 or index >= len(active_player.hand) for index in unique_indices):
                        raise ValueError("cleanup discard index out of range")
                    for hand_index in sorted(unique_indices, reverse=True):
                        discarded = active_player.hand.pop(hand_index)
                        active_player.graveyard.append(discarded)
                    self.log.append(f"{active_player.name} discarded {excess} card(s) in cleanup")
                elif defer_discard_selection:
                    cleanup_completed = False
                else:
                    for _ in range(excess):
                        discarded = active_player.hand.pop(0)
                        active_player.graveyard.append(discarded)
                    self.log.append(f"{active_player.name} discarded {excess} card(s) in cleanup")

        self.combat_damage_prevented_until_eot = False
        for player in self.players:
            player.damage_prevention_pool = 0
            player.combat_damage_cap_one_charges = 0
            player.channel_active_until_eot = False
            for permanent in player.battlefield:
                permanent.damage_marked = 0
                temp_power = int(permanent.metadata.pop("temporary_power_bonus_until_eot", 0))
                temp_toughness = int(permanent.metadata.pop("temporary_toughness_bonus_until_eot", 0))
                if temp_power:
                    permanent.power_bonus -= temp_power
                if temp_toughness:
                    permanent.toughness_bonus -= temp_toughness
                for key in _EOT_METADATA_KEYS:
                    permanent.metadata.pop(key, None)
        # 610.3: return all creatures exiled "until end of turn" to their owners' battlefields
        returned_from_exile = list(self.exile_until_eot)
        self.exile_until_eot.clear()
        for owner_idx, card_def in returned_from_exile:
            owner = self.players[owner_idx]
            if card_def in owner.exile:
                owner.exile.remove(card_def)
                new_perm = Permanent(card=card_def)
                self._put_permanent_onto_battlefield(owner_idx, new_perm, None)
                self.log.append(f"{card_def.name} returned from exile to {owner.name}'s battlefield")
        self._reset_combat_state(clear_damage_marked=False)
        self._on_step_or_phase_end(phase, step)
        return cleanup_completed
