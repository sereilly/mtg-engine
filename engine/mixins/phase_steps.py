from __future__ import annotations

from ._constants import _TURN_PHASES, _PHASE_STEPS, _NO_PRIORITY_STEPS

class PhaseStepsMixin:
    def _resolve_priority_window(self) -> None:
        # 500.2 simplified: both players pass in succession once the stack is empty.
        while True:
            self.resolve_stack()
            if not self.stack:
                return

    def _close_or_defer_step(self, phase: str, step: str, defer_priority: bool) -> None:
        """End a step, or — when defer_priority is set — leave a priority window open
        for the active player so a caller can hand priority to another player."""
        if not self._receives_priority(step):
            self._on_step_or_phase_end(phase, step)
            return
        if defer_priority:
            self.start_priority_window(self.active_player_index)
            return
        self._resolve_priority_window()
        self._on_step_or_phase_end(phase, step)

    def close_beginning_step(self) -> None:
        """Close a deferred upkeep/draw step (counterpart to close_end_step)."""
        phase = self.current_turn_phase
        step = self.current_step
        if phase != "beginning" or step not in ("upkeep", "draw"):
            return
        if self._receives_priority(step):
            self.clear_priority_window()
        self._on_step_or_phase_end(phase, step)

    def start_priority_window(self, starting_player_index: int | None = None) -> None:
        player_index = self.active_player_index if starting_player_index is None else starting_player_index
        if player_index < 0 or player_index >= len(self.players):
            self.priority_player_index = None
            self.priority_pass_count = 0
            return
        self.priority_player_index = player_index
        self.priority_pass_count = 0

    def clear_priority_window(self) -> None:
        self.priority_player_index = None
        self.priority_pass_count = 0

    def has_priority(self, player_index: int) -> bool:
        return self.priority_player_index == player_index

    def note_priority_action_taken(self, player_index: int) -> None:
        if self.priority_player_index is None:
            self.start_priority_window(player_index)
            return
        if self.priority_player_index != player_index:
            raise ValueError("player does not have priority")
        # 117.3c: after casting/activating, that player gets priority again.
        self.priority_pass_count = 0

    def _next_player_index(self, player_index: int) -> int:
        if len(self.players) <= 1:
            return player_index
        return (player_index + 1) % len(self.players)

    def pass_priority(self, player_index: int) -> str:
        if self.priority_player_index is None:
            raise ValueError("no active priority window")
        if self.priority_player_index != player_index:
            raise ValueError("player does not have priority")

        self.priority_pass_count += 1
        self.log.append(f"{self.players[player_index].name} passed priority")

        if self.priority_pass_count < len(self.players):
            self.priority_player_index = self._next_player_index(player_index)
            return "passed"

        # All players have passed in succession.
        self.priority_pass_count = 0
        if self.stack:
            self.resolve_top_of_stack()
            # 117.3b: active player gets priority after a spell/ability resolves.
            self.priority_player_index = self.active_player_index
            return "resolved_top"

        self.priority_player_index = self.active_player_index
        return "all_passed_empty"

    def add_extra_turn(self, player_index: int) -> None:
        # 500.7 most recently created turn occurs first.
        self.extra_turn_queue.append(player_index)
        self.extra_turns[player_index] = self.extra_turns.get(player_index, 0) + 1

    def add_extra_phase(
        self,
        after_phase: str,
        phase_name: str,
        steps: tuple[str, ...] | None = None,
        controller_index: int | None = None,
        only_on_controllers_turn: bool = False,
    ) -> bool:
        # 500.10a
        if only_on_controllers_turn and controller_index is not None and controller_index != self.active_player_index:
            return False
        self.extra_phases_after.setdefault(after_phase, []).insert(0, phase_name)
        if steps is not None:
            self.custom_phase_steps[phase_name] = tuple(steps)
        return True

    def add_extra_step(
        self,
        step_name: str,
        *,
        after_step: str | None = None,
        before_step: str | None = None,
        controller_index: int | None = None,
        only_on_controllers_turn: bool = False,
    ) -> bool:
        # 500.9 and 500.10a
        if only_on_controllers_turn and controller_index is not None and controller_index != self.active_player_index:
            return False
        if after_step is None and before_step is None:
            raise ValueError("either after_step or before_step must be provided")
        anchor = after_step if after_step is not None else f"before:{before_step}"
        self.extra_steps_after.setdefault(anchor, []).insert(0, step_name)
        return True

    def add_additional_step_after_phase(
        self,
        after_phase: str,
        step_name: str,
        *,
        controller_index: int | None = None,
        only_on_controllers_turn: bool = False,
    ) -> bool:
        # 500.10: create the containing phase with only the specified step.
        phase_name = f"extra_phase_for_{step_name}_{len(self.custom_phase_steps)}"
        return self.add_extra_phase(
            after_phase=after_phase,
            phase_name=phase_name,
            steps=(step_name,),
            controller_index=controller_index,
            only_on_controllers_turn=only_on_controllers_turn,
        )

    def skip_next_turn(self, player_index: int, count: int = 1) -> None:
        # 500.11
        self.skip_turn_counts[player_index] = self.skip_turn_counts.get(player_index, 0) + max(0, count)

    def skip_next_phase(self, phase_name: str, count: int = 1) -> None:
        self.skip_phase_counts[phase_name] = self.skip_phase_counts.get(phase_name, 0) + max(0, count)

    def skip_next_step(self, step_name: str, count: int = 1) -> None:
        self.skip_step_counts[step_name] = self.skip_step_counts.get(step_name, 0) + max(0, count)

    def _consume_skip(self, bucket: dict[object, int], key: object) -> bool:
        amount = bucket.get(key, 0)
        if amount <= 0:
            return False
        if amount == 1:
            bucket.pop(key, None)
        else:
            bucket[key] = amount - 1
        return True

    def _phase_steps(self, phase: str) -> tuple[str, ...]:
        base = list(self.custom_phase_steps.get(phase, _PHASE_STEPS.get(phase, (phase,))))
        expanded: list[str] = []
        for step in base:
            expanded.extend(self.extra_steps_after.pop(f"before:{step}", []))
            if not self._consume_skip(self.skip_step_counts, step):
                expanded.append(step)
            expanded.extend(self.extra_steps_after.pop(step, []))
        return tuple(expanded)

    def _next_phase_after(self, phase: str) -> str | None:
        extras = self.extra_phases_after.get(phase, [])
        if extras:
            candidate = extras.pop(0)
            if not extras:
                self.extra_phases_after.pop(phase, None)
            return candidate

        if phase not in _TURN_PHASES:
            return None
        idx = _TURN_PHASES.index(phase)
        if idx + 1 >= len(_TURN_PHASES):
            return None
        return _TURN_PHASES[idx + 1]

    def next_unskipped_phase_after(self, phase: str) -> str | None:
        candidate = self._next_phase_after(phase)
        while candidate is not None and self._consume_skip(self.skip_phase_counts, candidate):
            candidate = self._next_phase_after(candidate)
        return candidate

    def _compute_next_active_player(self) -> int:
        if self.extra_turn_queue:
            chosen = self.extra_turn_queue.pop()
            pending = self.extra_turns.get(chosen, 0)
            if pending > 0:
                self.extra_turns[chosen] = pending - 1
            return chosen

        # Legacy extra turn effects can still increment this map directly.
        pending_legacy = self.extra_turns.get(self.active_player_index, 0)
        if pending_legacy > 0:
            self.extra_turns[self.active_player_index] = pending_legacy - 1
            return self.active_player_index

        candidate = 1 - self.active_player_index
        while self.skip_turn_counts.get(candidate, 0) > 0:
            self._consume_skip(self.skip_turn_counts, candidate)
            candidate = 1 - candidate
        return candidate

    def _enter_main_phase(self, *, precombat: bool) -> None:
        phase = "precombat_main" if precombat else "postcombat_main"
        step = phase
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        if self._receives_priority(step):
            self.start_priority_window(self.active_player_index)

    def _close_current_priority_step(self) -> None:
        phase = self.current_turn_phase
        step = self.current_step
        if self._receives_priority(step):
            self._resolve_priority_window()
            self.clear_priority_window()
        self._on_step_or_phase_end(phase, step)

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
        if self._receives_priority(step):
            self.start_priority_window(self.active_player_index)

    def _set_phase_and_step(self, phase: str, step: str) -> None:
        self.current_turn_phase = phase
        self.current_step = step
        self.current_phase = self._public_phase_name(phase, step)
