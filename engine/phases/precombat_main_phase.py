from __future__ import annotations

"""Precombat main phase (CR 505).

The first main phase of the turn. The active player may play a land and cast
sorcery-speed spells while they have priority. Both main phases share the same
entry logic (``_enter_main_phase``); ``precombat=True`` distinguishes this one.
See ``postcombat_main_phase`` for the second main phase.

"At the beginning of your first main phase, …" (the M21 Shrine cycle) is put on
the stack here, and only from the precombat entry — the second main phase is not
a first one, and the same method serves both.

"At the beginning of **each of your main phases**, …" (Carpet of Flowers) is put
on the stack from **both**, which is the whole difference and the reason it is a
separate condition kind. The brief for this work called those "two fire sites";
they are one method with a flag, so the announcement goes beside the flag rather
than into ``postcombat_main_phase``, which has no code of its own and should
keep none.
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
        # Both entries, on the active player's own permanents: "your main
        # phases" are the ones on your turn, and CR 505.1 is what makes the
        # postcombat one of them — "the precombat and postcombat main phases
        # are individually and collectively known as the main phase".
        self._fire_each_main_phase_triggers()
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

    def _fire_each_main_phase_triggers(self) -> None:
        """CR 603.2: every "at the beginning of each of your main phases" trigger.

        The precombat scan's twin, announced from **both** main-phase entries
        rather than the first — which is the whole content of the printed
        difference and the reason the compiler gives it a kind of its own. A
        scope the fire site did not read would be an enchantment that only ever
        worked before combat.

        "Your" is the turn's active player, for `_fire_first_main_phase_triggers`'
        reason exactly: a permanent's controller only has a main phase on their
        own turn, so the scan is that seat's own permanents.

        **CR 603.4's first check lives here.** "…if you haven't added mana with
        this ability this turn" is an intervening-if, and a trigger whose
        condition is false does not trigger at all — it does not go on the
        stack, hold priority or answer to anything in response. Asked through
        the payload rather than through a list of instruction kinds, which is
        the same reading the end step takes and for the reason recorded there:
        a list of kinds is only ever as complete as the last card to touch it.
        """
        from ..game_types import OracleExecutionContext
        from ..handlers.control_flow import evaluate_condition

        active = self.active_player_index
        events = []
        for controller_index, permanent, trig in iter_triggered_abilities(
            self,
            condition_kinds={"main_phase_each_yours"},
            players=[self.players[active]],
        ):
            if not trig.supported or trig.instruction is None:
                continue
            gate = (trig.instruction.payload or {}).get("intervening_if")
            if gate is not None and not evaluate_condition(
                self,
                OracleExecutionContext(
                    caster=self.players[controller_index],
                    target=self.players[controller_index],
                    card=permanent.card,
                    source_permanent=permanent,
                    trigger_context={"event_subject_player": active},
                ),
                gate,
            ):
                continue
            events.append(make_trigger_event(controller_index, permanent, trig))
        if events:
            self._enqueue_triggered_batch(events)

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

        Two conditions, two scopes. "**Your** first main phase" is the turn's
        controller, so the scan is that seat's own permanents — a permanent's
        controller only has a first main phase on their own turn. "**Each
        player's** first main phase" (Eladamri's Vineyard) is every permanent on
        every battlefield, on every turn, and the seat it names is the active
        player — frozen onto the trigger's context under the key every "that
        player" in this engine reads, because which seat it is varies per firing
        and by resolution the only one still readable off the board is the
        source's controller.

        The narrowing inside that second condition is payload
        (``main_phase_scope``), the way ``upkeep_scope`` is one step of the turn
        earlier: "each **opponent's**" is the same event asked of a narrower set
        of seats, and whose opponents is CR 109.5's answer — the source's
        controller — so its own turn is not one of them.
        """
        active = self.active_player_index
        events = [
            make_trigger_event(controller_index, permanent, trig)
            for controller_index, permanent, trig in iter_triggered_abilities(
                self,
                condition_kinds={"main_phase_first"},
                players=[self.players[active]],
            )
            if trig.supported and trig.instruction is not None
        ]
        events += [
            make_trigger_event(
                controller_index, permanent, trig,
                trigger_context={"event_subject_player": active},
            )
            for controller_index, permanent, trig in iter_triggered_abilities(
                self, condition_kinds={"main_phase_first_each"}
            )
            if trig.supported and trig.instruction is not None
            and not (
                trig.condition.payload.get("main_phase_scope") == "opponent"
                and controller_index == active
            )
        ]
        if events:
            self._enqueue_triggered_batch(events)
