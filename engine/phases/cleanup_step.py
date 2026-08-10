from __future__ import annotations

"""Cleanup step (CR 514).

The active player discards down to maximum hand size, then all damage is removed
and "until end of turn" effects end (CR 514.2): regeneration shields, temporary
P/T buffs, damage prevention pools, and the EOT metadata flags. Creatures exiled
"until end of turn" return here (CR 610.3). No player normally receives priority.
"""

from ..models import Permanent
from ..keywords import clear_until_eot_keywords
from ..mixins._constants import _EOT_METADATA_KEYS
from ..shields import clear_shields


class CleanupStepMixin:
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

        # CR 514.2: "until end of turn" effects end. A global static whose
        # source has left the battlefield but whose effect continued (Titania's
        # Song) stops here — dropping it from the list is the whole removal,
        # because the effect was only ever derived from that list.
        if self.lingering_global_statics:
            self.lingering_global_statics.clear()
            self._refresh_dynamic_creatures()

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
                        self._discard_card(active_player, discarded)
                    self.log.append(f"{active_player.name} discarded {excess} card(s) in cleanup")
                elif defer_discard_selection:
                    cleanup_completed = False
                else:
                    for _ in range(excess):
                        discarded = active_player.hand.pop(0)
                        self._discard_card(active_player, discarded)
                    self.log.append(f"{active_player.name} discarded {excess} card(s) in cleanup")

        self.combat_damage_prevented_until_eot = False
        for player in self.players:
            # CR 615.3: every prevention shield lasts until it is used up or its
            # duration expires, and "until end of turn" expires here. One sweep
            # over the collection rather than a line per card-named field —
            # which is also why a new kind of shield needs no line here.
            clear_shields(player)
            player.mirror_damage_charges = 0
            player.mirror_damage_sources = []
            player.channel_active_until_eot = False
            player.prevent_one_damage_emblems = []
            for permanent in self.controlled_by(player):
                permanent.damage_marked = 0
                clear_shields(permanent)
                # 614.8 / 701.19a: an unused regeneration shield lasts only until
                # the end of the turn it was created.
                permanent.regeneration_shield = 0
                temp_power = int(permanent.metadata.pop("temporary_power_bonus_until_eot", 0))
                temp_toughness = int(permanent.metadata.pop("temporary_toughness_bonus_until_eot", 0))
                if temp_power:
                    permanent.power_bonus -= temp_power
                if temp_toughness:
                    permanent.toughness_bonus -= temp_toughness
                for key in _EOT_METADATA_KEYS:
                    permanent.metadata.pop(key, None)
                # Layer 6: until-end-of-turn ability grants and removals expire
                # together, in one place, rather than needing a metadata key per
                # keyword listed in _EOT_METADATA_KEYS.
                clear_until_eot_keywords(permanent)
                # Sandals of Abdallah: the linked "when that creature dies this
                # turn" destruction expires with the islandwalk grant above.
                permanent.metadata.pop("on_death_destroy_permanents", None)
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
