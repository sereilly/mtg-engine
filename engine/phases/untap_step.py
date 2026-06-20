from __future__ import annotations

"""Untap step (CR 502).

The active player untaps their permanents as a turn-based action. No player
receives priority during this step in this engine (CR 502.4). Handles the
replacement/skip effects that constrain untapping: Stasis, Winter Orb, Smoke,
Meekstone, Time Vault-style "doesn't untap" text, and Island Sanctuary cleanup.
"""


class UntapStepMixin:
    def get_untap_land_selection_options(self, player_index: int) -> dict[str, object] | None:
        player = self.players[player_index]
        all_permanents = [perm for pl in self.players for perm in pl.battlefield]

        if any(perm.card.name == "Stasis" for perm in all_permanents):
            return None

        max_untap_lands = 999
        if any(perm.card.name == "Winter Orb" and not perm.tapped for perm in all_permanents):
            max_untap_lands = 1

        if max_untap_lands >= 999:
            return None

        candidate_indices = [
            idx
            for idx, permanent in enumerate(player.battlefield)
            if permanent.card.primary_type == "land" and permanent.tapped
        ]
        if len(candidate_indices) <= max_untap_lands:
            return None

        return {
            "max_count": max_untap_lands,
            "candidate_indices": candidate_indices,
        }

    def resolve_untap_step(self, player_index: int, selected_land_indices: list[int] | None = None) -> int:
        phase = "beginning"
        step = "untap"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        player = self.players[player_index]
        # Record untapped lands at the beginning of the turn — i.e. *before* the
        # untap step untaps anything (Power Surge: X = "the number of untapped lands
        # they controlled at the beginning of this turn"). Lands tapped going into
        # the turn don't count, so tapping out before your turn avoids the damage.
        self.untapped_lands_at_turn_start[player_index] = sum(
            1 for perm in player.battlefield
            if perm.card.primary_type == "land" and not perm.tapped
        )
        # Island Sanctuary protection lasts until the player's next turn begins
        player.island_sanctuary_protected = False
        all_permanents = [perm for pl in self.players for perm in pl.battlefield]

        if any(perm.card.name == "Stasis" for perm in all_permanents):
            self.log.append(f"{player.name} skipped untap due to Stasis")
            return 0

        max_untap_creatures = 999
        if any(perm.card.name == "Smoke" for perm in all_permanents):
            max_untap_creatures = 1

        max_untap_lands = 999
        if any(perm.card.name == "Winter Orb" and not perm.tapped for perm in all_permanents):
            max_untap_lands = 1

        selected_lands: set[int] | None = None
        if selected_land_indices is not None:
            selected_lands = set()
            for idx in selected_land_indices:
                if idx < 0 or idx >= len(player.battlefield):
                    raise ValueError("selected land index out of range")
                permanent = player.battlefield[idx]
                if permanent.card.primary_type != "land":
                    raise ValueError("selected permanent is not a land")
                if not permanent.tapped:
                    continue
                selected_lands.add(idx)

            if max_untap_lands < 999 and len(selected_lands) > max_untap_lands:
                raise ValueError(f"cannot untap more than {max_untap_lands} land(s)")

        meekstone_active = any(perm.card.name == "Meekstone" for perm in all_permanents)

        untapped = 0
        creatures_untapped = 0
        lands_untapped = 0
        for idx, permanent in enumerate(player.battlefield):
            if not permanent.tapped:
                continue

            # Permanents that read "doesn't untap during your untap step" (e.g.
            # Time Vault, Basalt Monolith) stay tapped (Rule 502.4, 702 self-text).
            if "doesn't untap during your untap step" in permanent.card.oracle_text.lower():
                continue

            if permanent.card.primary_type == "creature":
                if meekstone_active and permanent.effective_power >= 3:
                    continue
                if creatures_untapped >= max_untap_creatures:
                    continue
                if permanent.metadata.get("aura_prevents_untap"):
                    continue
                creatures_untapped += 1

            if permanent.card.primary_type == "land":
                if selected_lands is not None and idx not in selected_lands:
                    continue
                if lands_untapped >= max_untap_lands:
                    continue
                lands_untapped += 1

            permanent.tapped = False
            untapped += 1

        self.log.append(f"{player.name} untapped {untapped} permanent(s)")
        self._on_step_or_phase_end(phase, step)
        return untapped
