from __future__ import annotations

"""Precombat main phase (CR 505).

The first main phase of the turn. The active player may play a land and cast
sorcery-speed spells while they have priority. Both main phases share the same
entry logic (``_enter_main_phase``); ``precombat=True`` distinguishes this one.
See ``postcombat_main_phase`` for the second main phase.
"""


class PrecombatMainPhaseMixin:
    def _enter_main_phase(self, *, precombat: bool) -> None:
        phase = "precombat_main" if precombat else "postcombat_main"
        step = phase
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        if self._receives_priority(step):
            self.start_priority_window(self.active_player_index)
