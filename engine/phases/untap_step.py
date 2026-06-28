from __future__ import annotations

"""Untap step (CR 502).

The active player untaps their permanents as a turn-based action. No player
receives priority during this step in this engine (CR 502.4). Handles the
replacement/skip effects that constrain untapping: Stasis, Winter Orb, Smoke,
Meekstone, Time Vault-style "doesn't untap" text, and Island Sanctuary cleanup.
"""


class UntapStepMixin:
    def get_untap_land_selection_options(self, player_index: int) -> dict[str, object] | None:
        """Untap-step selection constraints the controller must resolve: Winter Orb
        limits untapping to one *land*, Smoke to one *creature*. Returns combined
        candidate battlefield indices and the total number that may be untapped
        among the constrained types, or None if nothing is constrained."""
        player = self.players[player_index]
        all_permanents = [perm for pl in self.players for perm in pl.battlefield]

        if any(perm.card.name == "Stasis" for perm in all_permanents):
            return None

        max_untap_lands = 999
        if any(perm.card.name == "Winter Orb" and not perm.tapped for perm in all_permanents):
            max_untap_lands = 1
        max_untap_creatures = 999
        if any(perm.card.name == "Smoke" for perm in all_permanents):
            max_untap_creatures = 1

        land_candidates = [
            idx for idx, p in enumerate(player.battlefield)
            if p.card.primary_type == "land" and p.tapped
        ]
        creature_candidates = [
            idx for idx, p in enumerate(player.battlefield)
            if p.card.primary_type == "creature" and p.tapped
        ]
        land_constrained = max_untap_lands < 999 and len(land_candidates) > max_untap_lands
        creature_constrained = max_untap_creatures < 999 and len(creature_candidates) > max_untap_creatures
        if not land_constrained and not creature_constrained:
            return None

        candidate_indices: list[int] = []
        max_count = 0
        if land_constrained:
            candidate_indices += land_candidates
            max_count += max_untap_lands
        if creature_constrained:
            candidate_indices += creature_candidates
            max_count += max_untap_creatures

        return {
            "max_count": max_count,
            "candidate_indices": sorted(candidate_indices),
            "land_max": max_untap_lands if land_constrained else None,
            "creature_max": max_untap_creatures if creature_constrained else None,
        }

    def resolve_untap_step(
        self,
        player_index: int,
        selected_land_indices: list[int] | None = None,
        selected_creature_indices: list[int] | None = None,
    ) -> int:
        phase = "beginning"
        step = "untap"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        player = self.players[player_index]
        self._advance_summoning_sickness(player_index)
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

        # Smoke: the controller chooses which creature(s) to untap (CR 502 with a
        # "can't untap more than one" constraint). Absent a choice (AI/headless),
        # the loop below untaps the first eligible creatures up to the cap.
        selected_creatures: set[int] | None = None
        if selected_creature_indices is not None:
            selected_creatures = set()
            for idx in selected_creature_indices:
                if idx < 0 or idx >= len(player.battlefield):
                    raise ValueError("selected creature index out of range")
                permanent = player.battlefield[idx]
                if permanent.card.primary_type != "creature":
                    raise ValueError("selected permanent is not a creature")
                if not permanent.tapped:
                    continue
                selected_creatures.add(idx)

            if max_untap_creatures < 999 and len(selected_creatures) > max_untap_creatures:
                raise ValueError(f"cannot untap more than {max_untap_creatures} creature(s)")

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
                # Honor the controller's Smoke selection when one was supplied.
                if selected_creatures is not None and idx not in selected_creatures:
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
