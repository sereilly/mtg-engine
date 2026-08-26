from __future__ import annotations

"""Precombat main phase (CR 505).

The first main phase of the turn. The active player may play a land and cast
sorcery-speed spells while they have priority. Both main phases share the same
entry logic (``_enter_main_phase``); ``precombat=True`` distinguishes this one.
See ``postcombat_main_phase`` for the second main phase.

"At the beginning of your first main phase, …" (the M21 Shrine cycle) is put on
the stack here, and only from the precombat entry — the second main phase is not
a first one, and the same method serves both.
"""

from ..delayed_triggers import fire_delayed_triggers
from ..trigger_utils import iter_triggered_abilities, make_trigger_event


class PrecombatMainPhaseMixin:
    def _enter_main_phase(self, *, precombat: bool) -> None:
        phase = "precombat_main" if precombat else "postcombat_main"
        step = phase
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        if precombat:
            self._fire_first_main_phase_triggers()
        # "At the beginning of your next main phase, …" (Mana Drain). Both main
        # phases, because "next" means the next one there is — and scoped to
        # the entry's own controller, which is what "your" says: a main phase
        # belongs to the active player, so an ability an opponent created is
        # not waiting for this one.
        fire_delayed_triggers(
            self, "controllers_next_main_phase", seat=self.active_player_index
        )
        if self._receives_priority(step):
            self.start_priority_window(self.active_player_index)

    def _fire_first_main_phase_triggers(self) -> None:
        """CR 603.2: every "at the beginning of your first main phase" trigger.

        **No whitelist of instruction kinds.** The end step gates its scans on
        one, because each was added by the card that needed it; round 45 is the
        record of what that costs — a fire site enumerating kinds can only be as
        complete as the last card to touch it, and Onulet went its whole life
        without gaining a point of life because its kind was not in the list.
        Here every trigger the compiler produced an instruction for is put on
        the stack, and a trigger with no instruction is not a trigger this
        engine can run.

        Scoped to the active player: "your" is the turn's controller, and a
        permanent's controller only has a first main phase on their own turn.
        """
        events = [
            make_trigger_event(controller_index, permanent, trig)
            for controller_index, permanent, trig in iter_triggered_abilities(
                self,
                condition_kinds={"main_phase_first"},
                players=[self.players[self.active_player_index]],
            )
            if trig.supported and trig.instruction is not None
        ]
        if events:
            self._enqueue_triggered_batch(events)
