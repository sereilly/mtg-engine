from __future__ import annotations

"""Untap step (CR 502).

The active player untaps their permanents as a turn-based action. No player
receives priority during this step in this engine (CR 502.4). Untap
constraints (skip entirely, per-type count limits, power-based blocks) are
derived from oracle text by engine/untap_restrictions.py — this module only
aggregates and enforces them, so new restriction cards never touch it.
"""

from ..auras import aura_restriction_active
from ..handlers._common import permanent_effective_colors
from ..untap_restrictions import (
    SELF_DOESNT_UNTAP_PHRASE,
    SELF_MAY_KEEP_TAPPED_PHRASE,
    untap_restriction_for,
)


class UntapStepMixin:
    def _untap_constraints(self) -> dict[str, object]:
        """Aggregate every active untap restriction on any battlefield into
        effective limits for the current untap step."""
        skip_all_source: str | None = None
        max_lands = 999
        max_creatures = 999
        min_power_block: int | None = None
        blocked_colors: set[str] = set()
        for perm in self.all_permanents():
            # effective_card, so a CR 613 layer-3 text change (Sleight of Mind
            # rewriting the colour word) is applied before the restriction is
            # read — the table itself never learns text can change.
            restriction = untap_restriction_for(perm.effective_card.oracle_text)
            if restriction is None:
                continue
            if restriction.only_while_source_untapped and perm.tapped:
                continue
            if restriction.scope == "all":
                if restriction.limit == 0:
                    skip_all_source = perm.card.name
            elif restriction.scope == "land":
                if restriction.limit is not None:
                    max_lands = min(max_lands, restriction.limit)
            elif restriction.scope == "creature":
                if restriction.limit is not None:
                    max_creatures = min(max_creatures, restriction.limit)
                if restriction.min_power is not None:
                    min_power_block = (
                        restriction.min_power
                        if min_power_block is None
                        else min(min_power_block, restriction.min_power)
                    )
            elif restriction.scope == "creature_color" and restriction.color:
                blocked_colors.add(restriction.color)
        return {
            "skip_all_source": skip_all_source,
            "max_lands": max_lands,
            "max_creatures": max_creatures,
            "min_power_block": min_power_block,
            "blocked_colors": blocked_colors,
        }

    def get_untap_land_selection_options(self, player_index: int) -> dict[str, object] | None:
        """Untap-step selection constraints the controller must resolve: Winter Orb
        limits untapping to one *land*, Smoke to one *creature*. Returns combined
        candidate battlefield indices and the total number that may be untapped
        among the constrained types, or None if nothing is constrained."""
        player = self.players[player_index]
        constraints = self._untap_constraints()

        if constraints["skip_all_source"] is not None:
            return None

        max_untap_lands = constraints["max_lands"]
        max_untap_creatures = constraints["max_creatures"]

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

    def get_optional_untap_permanents(self, player_index: int) -> list[dict]:
        """Tapped permanents whose controller may choose not to untap them
        (Old Man of the Sea: "You may choose not to untap this creature during
        your untap step"). The web layer prompts a human with these; the
        keep-tapped choice is passed back via resolve_untap_step's
        ``keep_tapped_indices``."""
        player = self.players[player_index]
        return [
            {"index": idx, "name": permanent.card.name}
            for idx, permanent in enumerate(player.battlefield)
            if permanent.tapped
            and "you may choose not to untap" in permanent.card.oracle_text.lower()
        ]

    def resolve_untap_step(
        self,
        player_index: int,
        selected_land_indices: list[int] | None = None,
        selected_creature_indices: list[int] | None = None,
        keep_tapped_indices: list[int] | None = None,
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
            1 for perm in self.controlled_by(player)
            if perm.card.primary_type == "land" and not perm.tapped
        )
        # Island Sanctuary protection lasts until the player's next turn begins
        player.island_sanctuary_protected = False
        constraints = self._untap_constraints()

        if constraints["skip_all_source"] is not None:
            self.log.append(f"{player.name} skipped untap due to {constraints['skip_all_source']}")
            return 0

        max_untap_creatures = constraints["max_creatures"]
        max_untap_lands = constraints["max_lands"]
        min_power_block = constraints["min_power_block"]
        blocked_colors = constraints["blocked_colors"]

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

        untapped = 0
        creatures_untapped = 0
        lands_untapped = 0
        for idx, permanent in enumerate(player.battlefield):
            if not permanent.tapped:
                continue

            # Permanents that read "doesn't untap during your untap step" (e.g.
            # Time Vault, Basalt Monolith) stay tapped (Rule 502.4, 702 self-text).
            if SELF_DOESNT_UNTAP_PHRASE in permanent.card.oracle_text.lower():
                continue

            # Old Man of the Sea: "You may choose not to untap this creature
            # during your untap step." A human's explicit keep-tapped choice is
            # honored; AI/headless play keeps it tapped while its linked steal
            # is alive (untapping would end the control effect).
            if SELF_MAY_KEEP_TAPPED_PHRASE in permanent.card.oracle_text.lower():
                if keep_tapped_indices is not None:
                    if idx in keep_tapped_indices:
                        continue
                elif (
                    permanent.metadata.get("stolen_while_tapped_and_weaker")
                    and self.permanents_controlled_via(permanent)
                ):
                    continue

            if permanent.card.primary_type == "creature":
                # Meekstone-style: creatures at or above the power cap stay tapped.
                if min_power_block is not None and permanent.effective_power >= min_power_block:
                    continue
                # Magnetic Mountain: creatures of a blocked color stay tapped
                # (a separate upkeep effect may untap them anyway, for a cost).
                if blocked_colors and permanent_effective_colors(permanent) & blocked_colors:
                    continue
                # Honor the controller's Smoke selection when one was supplied.
                if selected_creatures is not None and idx not in selected_creatures:
                    continue
                if creatures_untapped >= max_untap_creatures:
                    continue
                if aura_restriction_active(permanent, "doesnt_untap"):
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
        # No player receives priority during the untap step (CR 502.3), so the
        # first SBA check after it happens as the upkeep step opens — run it here
        # so untapping is never observable without its consequences. Old Man of
        # the Sea's steal lasts "for as long as this creature remains tapped":
        # untapping it must hand the creature back before anyone sees the board.
        self.check_state_based_actions()
        return untapped
