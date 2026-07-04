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
    def combat_defending_players(self) -> set[int]:
        """CR 802.2: every player currently a defending player this combat — i.e.
        named as the target of at least one declared attacker. Empty before
        attackers are declared."""
        return set(self.combat_attackers.values())

    def _resolve_defending_player_index(self) -> int | None:
        """The single-scalar ``combat_defending_player_index`` convenience value
        (kept for 2-player back-compat and simple single-target UI reads).

        In a 2-player game this is always unambiguous — the other seat — even
        before any attacker has been declared, matching every existing 2-player
        caller/test that reads it at any point during combat. In FFA (3+
        players) it's only meaningful once exactly one distinct defender is
        under attack; the authoritative source there is
        ``combat_defending_players()``."""
        if len(self.players) == 2:
            return 1 - self.active_player_index
        defenders = self.combat_defending_players()
        return next(iter(defenders)) if len(defenders) == 1 else None

    def _pending_block_declarer(self) -> int | None:
        """CR 802.4: the next defending player, in APNAP order starting with the
        player after the active player, who still needs to declare blocks (or be
        auto-skipped) this declare-blockers step. None once every defender has."""
        defenders = self.combat_defending_players()
        if not defenders:
            return None
        n = len(self.players)
        for offset in range(1, n + 1):
            idx = (self.active_player_index + offset) % n
            if idx in defenders and idx not in self.combat_blockers_declared_by:
                return idx
        return None

    def _has_any_legal_attacker(self, attacker_index: int, defender_index: int) -> bool:
        if attacker_index < 0 or attacker_index >= len(self.players):
            return False
        if defender_index < 0 or defender_index >= len(self.players):
            return False
        if attacker_index == defender_index:
            return False

        attacker_player = self.players[attacker_index]
        for attacker in attacker_player.battlefield:
            if not attacker.is_creature:
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
            if not blocker.is_creature or blocker.tapped:
                continue
            # CR 802.4a: this defender can only block attackers aimed at them.
            for attacker_idx, defending_idx in self.combat_attackers.items():
                if defending_idx != defender_index:
                    continue
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
            # CR 802.2: under attack-multiple-players there's no single pre-picked
            # defender to check before attackers are even declared — each attacker
            # names its own when declared. The active player just needs SOME legal
            # attacker against ANY living opponent for this step not to auto-skip.
            living_opponents = self.opponents_of(self.active_player_index)
            if any(
                self._has_any_legal_attacker(self.active_player_index, opp)
                for opp in living_opponents
            ):
                return

            self.combat_attackers = {}
            self.combat_blockers = {}
            self.combat_attackers_locked = True
            self.combat_blockers_locked = True
            self._prune_combat_state()
            attacker_name = self.players[self.active_player_index].name
            self.log.append(f"{attacker_name} has no valid attackers; declare attackers step skipped")
        # Camouflage replaces the declare-blockers step: the defending player
        # divides their creatures into piles (assign_camouflage_piles), which are
        # then matched to attackers at random. Wait for that choice like a normal
        # blocker declaration; with no untapped creatures there is nothing to
        # divide, so resolve the (empty) piles immediately. Camouflage's spell text
        # names one specific defending player, so this stays single-defender.
        if (
            self.current_step == "declare_blockers"
            and not self.combat_blockers_locked
            and self.combat_attackers
            and self.is_camouflage_active()
        ):
            defender_index = self.combat_defending_player_index
            if defender_index is None:
                defender_index = next(iter(self.combat_defending_players()), None)
            if isinstance(defender_index, int):
                defender = self.players[defender_index]
                if any(p.is_creature and not p.tapped for p in defender.battlefield):
                    return  # awaiting the defender's pile assignment
                self.resolve_camouflage_blocking(defender_index)
            return
        if self.current_step == "declare_blockers" and not self.combat_blockers_locked:
            # CR 802.4: each defending player declares blocks in APNAP order,
            # starting with the player after the active player. Auto-skip any
            # defender (in turn) who has no legal blocks; stop and wait once we
            # reach one who has a real choice to make.
            while True:
                pending = self._pending_block_declarer()
                if pending is None:
                    self.combat_blockers_locked = True
                    self._prune_combat_state()
                    break
                if self._has_any_legal_block(pending):
                    return
                self.combat_blockers_declared_by.add(pending)
                self._prune_combat_state()
                defender_name = self.players[pending].name
                self.log.append(f"{defender_name} has no valid blockers; declare blockers step skipped")
        if self.current_step == "declare_blockers" and self.combat_blockers_locked and not self.combat_attackers:
            defender_index = self.combat_defending_player_index
            if isinstance(defender_index, int) and 0 <= defender_index < len(self.players):
                defender_name = self.players[defender_index].name
                self.log.append(f"{defender_name} has no valid blockers; declare blockers step skipped")
            else:
                self.log.append("No attackers; declare blockers step skipped")
        if self.current_step == "combat_damage" and not self.combat_damage_resolved:
            return  # Awaiting manual damage assignment

        if self.current_step == "declare_attackers":
            self.log.append(
                f"Declare attackers step complete: {len(self.combat_attackers)} attacker(s) declared"
            )
        if self.current_step == "declare_blockers":
            total_blockers = sum(len(m) for m in self.combat_blockers.values())
            self.log.append(
                f"Declare blockers step complete: {total_blockers} blocker(s) declared"
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
            self.combat_defending_player_index = self._resolve_defending_player_index()
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
        self.combat_blockers_declared_by = set()
        self.combat_bands = []
        self.combat_band_blocks = {}
        self.combat_banding_damage = {}
        self.combat_multiblock_damage = {}
        self.combat_left_right_active = False
        self.combat_left_right_defender_index = None
        self.combat_defender_piles = {}
        self.combat_attacker_piles = {}
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
        n = len(self.players)

        valid_attackers: dict[int, int] = {}
        for attacker_idx, defending_idx in self.combat_attackers.items():
            if not (0 <= defending_idx < n) or defending_idx == self.active_player_index:
                continue
            if attacker_idx < 0 or attacker_idx >= len(active.battlefield):
                continue
            attacker = active.battlefield[attacker_idx]
            # is_creature, not the printed type: pruning by printed type silently
            # removed animated lands (Kormus Bell / Living Lands) from combat
            # right after they were legally declared as attackers.
            if not attacker.is_creature:
                continue
            valid_attackers[attacker_idx] = defending_idx
        self.combat_attackers = valid_attackers

        # Populated only when every remaining attacker shares one defender
        # (2-player back-compat / simple single-target UI reads); the authoritative
        # source of "who's under attack" is combat_defending_players().
        defenders_now = self.combat_defending_players()
        self.combat_defending_player_index = self._resolve_defending_player_index()
        self.combat_blockers_declared_by &= defenders_now

        # CR 702.22f: an attacking creature removed from combat is removed from its
        # band. Drop departed members; a band that falls below two members is no
        # longer a band (it leaves no banding interaction for the rest of combat).
        if self.combat_bands:
            pruned_bands = [
                [m for m in band if m in self.combat_attackers] for band in self.combat_bands
            ]
            self.combat_bands = [band for band in pruned_bands if len(band) >= 2]

        # combat_blockers is nested by defender (CR 802: 2+ defenders may each have
        # declared blocks in the same combat, and blocker battlefield indices are
        # only unambiguous within one defender's own battlefield).
        pruned_blockers: dict[int, dict[int, list[int]]] = {}
        for defending_idx, blocker_map in self.combat_blockers.items():
            if not (0 <= defending_idx < n):
                continue
            defender = self.players[defending_idx]
            kept_for_defender: dict[int, list[int]] = {}
            for blocker_idx, attacker_idxs in blocker_map.items():
                if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                    continue
                blocker = defender.battlefield[blocker_idx]
                if not blocker.is_creature:
                    continue
                # Keep only attackers still valid AND still aimed at this defender.
                kept = [
                    a for a in attacker_idxs
                    if self.combat_attackers.get(a) == defending_idx
                ]
                if kept:
                    kept_for_defender[blocker_idx] = kept
            if kept_for_defender:
                pruned_blockers[defending_idx] = kept_for_defender
        self.combat_blockers = pruned_blockers

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

        all_blocked_attacker_idxs: set[int] = {
            a for blocker_map in self.combat_blockers.values() for atks in blocker_map.values() for a in atks
        }
        for attacker_idx, defending_idx in self.combat_attackers.items():
            attacker = active.battlefield[attacker_idx]
            attacker.attacking = True
            attacker.defending_player_index = defending_idx
            attacker.blocked = was_blocked.get(attacker_idx, False) or attacker_idx in all_blocked_attacker_idxs

        for defending_idx, blocker_map in self.combat_blockers.items():
            defender = self.players[defending_idx]
            for blocker_idx, attacker_idxs in blocker_map.items():
                blocker = defender.battlefield[blocker_idx]
                blocker.blocking_attacker_controller = self.active_player_index
                # `blocking_attacker_index` holds a single representative attacker
                # (the first) for the common one-block case; multi-block uses
                # combat_blockers.
                blocker.blocking_attacker_index = attacker_idxs[0] if attacker_idxs else None

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
            # CR 802: every player currently under attack (may be 2+ in FFA).
            "defending_player_indices": sorted(self.combat_defending_players()),
            "attackers": [{"attacker_index": k, "defending_player_index": v} for k, v in sorted(self.combat_attackers.items())],
            "blockers": [
                {"blocker_index": blocker_idx, "attacker_index": a, "defending_player_index": defending_idx}
                for defending_idx, blocker_map in sorted(self.combat_blockers.items())
                for blocker_idx, atks in sorted(blocker_map.items())
                for a in atks
            ],
            "damage_resolved": self.combat_damage_resolved,
            "first_strike_done": self.combat_first_strike_done,
            "attackers_locked": self.combat_attackers_locked,
            "blockers_locked": self.combat_blockers_locked,
            # Camouflage (cast during this turn's declare-attackers step): the
            # defender assigns piles instead of declaring blockers.
            "camouflage_active": self.is_camouflage_active(),
            # Banding (CR 702.22): declared attacking bands and the per-attacker
            # blockers added by band propagation (702.22h).
            "bands": [list(band) for band in self.combat_bands],
            "band_blocks": {k: list(v) for k, v in self.combat_band_blocks.items()},
            # Raging River (CR 702 left/right division). Exposed for the UI so it can
            # draw each creature's pile and rearrange the board into left/right sides.
            # ``defender_piles`` keys are battlefield indices of the defending player;
            # ``attacker_piles`` keys are battlefield indices of the active player.
            "left_right_active": self.combat_left_right_active,
            "left_right_defender_index": self.combat_left_right_defender_index,
            "defender_piles": {int(k): v for k, v in self.combat_defender_piles.items()},
            "attacker_piles": {int(k): v for k, v in self.combat_attacker_piles.items()},
            "defender_piles_locked": self.combat_left_right_defender_locked,
            "attacker_piles_locked": self.combat_left_right_attacker_locked,
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
