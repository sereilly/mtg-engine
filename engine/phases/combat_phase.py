from __future__ import annotations

"""Combat phase (CR 506–511).

This module holds the phase-level combat machinery shared across the five combat
steps: stepping through the steps (``advance_combat_phase`` / ``_enter_combat_step``),
combat-state bookkeeping (``_reset_combat_state`` / ``_prune_combat_state`` /
``get_combat_state``), legality probes used to auto-skip empty declaration steps,
and the "attacking/blocking alone" queries. The per-step turn-based actions live
in the sibling step modules (``beginning_of_combat_step``, ``declare_attackers_step``,
``declare_blockers_step``, ``combat_damage_step``, ``end_of_combat_step``).
"""

from ..models import Permanent


class CombatPhaseMixin:
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

    def _enter_combat_step(self, step: str) -> None:
        if step == "beginning_of_combat":
            self._reset_combat_state(clear_damage_marked=False)
        if step == "declare_attackers":
            self.combat_attackers_locked = False
            self.combat_blockers_locked = False
            if self.combat_defending_player_index is None:
                self.combat_defending_player_index = 1 - self.active_player_index
        if step == "declare_blockers":
            self.combat_blockers_locked = not bool(self.combat_attackers)
        self._set_phase_and_step("combat", step)
        self._on_step_or_phase_begin("combat", step)
        # CR 508.1 / 509.1: declaring attackers and declaring blockers are
        # turn-based actions that happen *before* any player receives priority,
        # so no spell or ability can be cast/activated during that assignment.
        # A priority window is opened only once the declaration is made — see
        # declare_attackers / declare_blockers, which grant the active player
        # priority afterward (CR 508.4 / 509.4). Every other combat step opens a
        # priority window immediately on entry.
        if step in ("declare_attackers", "declare_blockers"):
            self.clear_priority_window()
        elif self._receives_priority(step):
            self.start_priority_window(self.active_player_index)

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
