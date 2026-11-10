from __future__ import annotations

from ..game_over_guard import goes_no_further

"""End step (CR 513).

"At the beginning of the end step" triggered abilities are put on the stack here:
delayed end-of-turn destruction (e.g. creatures forced to attack that didn't),
Scavenging Ghoul corpse counters, and Pestilence-style "sacrifice if no
creatures" triggers. The active player then receives priority.

Delayed abilities that name **the next end step** (CR 603.7) are announced here
too — Rukh Egg's token, Infinite Authority's counter. They belong to whoever
created them and fire at the next end step there is, so the announcement takes
no seat.
"""

from ..delayed_triggers import delayed_mark_events, fire_delayed_triggers
from ..turn_state import (DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY,
                          marked_for_this_turn)
from ..trigger_utils import iter_triggered_abilities, make_trigger_event

# Instruction kinds this step enqueues under the ``end_step`` trigger condition,
# grouped by the board question that gates each scan.
#
# Hoisted out of ``resolve_end_step`` so the dispatch surface is *data*. Nothing
# else fires an ``end_step`` trigger, so a compiler that lowers one of these
# lines onto any other kind produces a card that reports as supported and never
# fires — the failure mode the equivalent upkeep guard was built for after it
# shipped twice. ``tests/engine/test_grammar_lowering.py`` reads these sets and
# checks every end-step trigger the grammar executes against them.
END_STEP_DEATH_COUNTER_KINDS = frozenset({
    "add_corpse_counters_for_each_creature_died",
    "add_plus1_counters_for_each_creature_died",
})

#: The two condition kinds this step dispatches, and the only difference between
#: them: ``end_step_self`` is "at the beginning of **your** end step" and fires
#: for the player whose end step this is; ``end_step`` is "the"/"each" and fires
#: for everyone. The scope used to be inferred per *instruction kind* — the two
#: death-counter scans happened to hold "each" cards and the gated scan happened
#: to hold only "your" cards — so the first "each end step" card to reach the
#: gated scan (Liliana's Scrounger) would have fired on its controller's turn
#: alone.
END_STEP_SELF_CONDITION = "end_step_self"
END_STEP_EACH_CONDITION = "end_step"

#: "At the beginning of the end step of **enchanted creature's controller**"
#: (Aggression). A third scope, and one no seat comparison on the *source* can
#: answer: the seat is whoever controls the permanent the Aura is attached to,
#: which is on the attachment record. The upkeep step's
#: ``upkeep_enchanted_controller`` is the same clause one step earlier and is
#: scoped the same way — see :func:`end_step_trigger_seat_matches`.
END_STEP_ENCHANTED_CONTROLLER_CONDITION = "end_step_enchanted_controller"
END_STEP_CONDITIONS = frozenset({
    END_STEP_SELF_CONDITION,
    END_STEP_EACH_CONDITION,
    END_STEP_ENCHANTED_CONTROLLER_CONDITION,
})


def end_step_trigger_seat_matches(game, permanent, cond: str, player_index: int) -> bool:
    """Whether a trigger of *cond* on *permanent* fires on *player_index*'s end step.

    Only the attached scope answers anything here; the two ordinary conditions
    were already scoped by the scan that found them. One reader for the loop
    below and for the support gate in ``engine/auras.py``, so what the engine
    claims it can fire and what it actually fires cannot drift — which is the
    pairing ``upkeep_trigger_seat_matches`` keeps one step earlier.
    """
    if cond != END_STEP_ENCHANTED_CONTROLLER_CONDITION:
        return True
    attached = permanent.metadata.get("attached_to")
    return (
        attached is not None
        and game.controller_index_of(attached) == player_index
    )

#: Every instruction kind an ``end_step`` trigger can be dispatched on *by kind*.
#: The fourth scan below is keyed on a payload **shape** instead and so has no
#: entry here — see ``END_STEP_INTERVENING_IF``.
#:
#: One set today. A second, ``end_step_damage_if_not_attacked``, was Erg
#: Raiders' name-keyed line and its own scan; the card's sentence is two
#: conditions the grammar reads now ("if this creature didn't attack this
#: turn, … unless it came under your control this turn"), so it arrives
#: through the gated scan like every other intervening-if.
END_STEP_DISPATCHED_KINDS = END_STEP_DEATH_COUNTER_KINDS

#: The payload key that makes a trigger fire through the CR 603.4 intervening-if
#: scan, whatever its instruction kind. It used to be a list of kinds holding
#: exactly ``draw_controller_cards`` (Barrin, Tolarian Archmage), and Liliana's
#: Devotee is what that list cost: "at the beginning of your end step, **if a
#: creature died this turn**, you may pay {1}{B}…" lowers onto ``may``, was in no
#: list, and would have compiled clean and never fired. The gate lives on the
#: payload, so "does it have one" is the whole question — and a list of kinds is
#: only ever as complete as the last card that touched it (round 45).
END_STEP_INTERVENING_IF = "intervening_if"


class EndStepMixin:
    @goes_no_further()
    def resolve_end_step(self, player_index: int) -> None:
        """Begin the end step: its delayed sweeps, then everything "at the
        beginning of the end step" sets off, as one window for CR 603.3b
        (``putting_triggers_on_stack``) — a seat that put two or more
        triggers on the stack here orders them.
        """
        with self.putting_triggers_on_stack():
            self._begin_end_step(player_index)

    def _begin_end_step(self, player_index: int) -> None:
        phase = "ending"
        step = "end"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)

        # "At the beginning of **the next end step**, …" (Infinite Authority).
        # CR 513.1 gives every turn one end step, and the ability names the next
        # one there is rather than one of its controller's — so no seat narrows
        # this, unlike the upkeep announcement, which names "your" next upkeep.
        fire_delayed_triggers(self, "next_end_step")
        # "At the beginning of **your** next end step, …" (Necropotence). The
        # controller's own, so this one is seated where the line above is not.
        fire_delayed_triggers(self, "controllers_next_end_step", seat=player_index)
        # "At the beginning of the end step of **that player's next turn**, …"
        # (Suppress.) Seated by the player the creating effect named rather
        # than by the ability's controller (`EVENTS_SEATED_BY_BOUND_PLAYER`),
        # and an entry armed during this very turn waits for the next one
        # (`EVENTS_AFTER_THIS_TURN`).
        fire_delayed_triggers(
            self, "bound_players_next_turns_end_step", seat=player_index
        )
        # "At the beginning of **that turn's** end step, you lose the game."
        # (Final Fortune.) The end step of the extra turn the creating spell
        # queued, so it is announced only on an extra turn and only for the
        # seat taking it — and `EVENTS_AFTER_THIS_TURN` keeps an entry armed
        # during an extra turn from answering to that same turn's announcement,
        # which is exactly what a chain of Final Fortunes does.
        if self.current_turn_is_extra:
            fire_delayed_triggers(
                self, "granted_extra_turns_end_step", seat=player_index
            )

        # "At the beginning of the end step" triggered abilities go on the stack
        # (CR 603.3) and resolve through the end-step priority window opened below.
        #
        # **The delayed abilities recorded as marks first** — Dragon Whelp's
        # sacrifice, Berserk's, Nettling Imp's and Rocket Launcher's
        # destructions, Rakalite's return (``_end_step_mark_firings``). Each is
        # a delayed triggered ability (CR 603.7) that triggers as the step
        # begins and goes on the stack with the rest, controlled by whoever
        # created it (CR 603.7d–e). They were carried out here inline, as three
        # sweeps, before anybody had priority: nothing could answer them (a
        # regeneration shield made in response, the creature bounced first),
        # every one ran before the step's other triggers whatever the seats'
        # order, and "sacrifice it" was performed by whoever controlled the
        # permanent then.
        events: list[dict] = delayed_mark_events(
            self, self._end_step_mark_firings()
        )

        # Scavenging Ghoul: "...put a corpse counter on this creature for each
        # creature that died this turn." Khabál Ghoul: same trigger shape but
        # +1/+1 counters. The death count is captured now (it resets next turn)
        # and read by the handler at resolution.
        died = getattr(self, "creatures_died_this_turn", 0)
        if died:
            for controller_index, permanent, trig in iter_triggered_abilities(
                self,
                condition_kinds={END_STEP_EACH_CONDITION},
                instruction_kinds=END_STEP_DEATH_COUNTER_KINDS,
            ):
                events.append(make_trigger_event(
                    controller_index, permanent, trig, trigger_context={"count": died}
                ))

        # A trigger whose whole gate is a CR 603.4 intervening-if (Barrin,
        # Tolarian Archmage; Liliana's Devotee). Scoped like Erg Raiders to this
        # end step's own player — the printed condition says "your". Keyed on
        # the payload's *shape* rather than on a list of instruction kinds: a
        # trigger with no gate is not enqueued here at all, because this block
        # exists because of the condition, and one that has a gate is enqueued
        # whatever its effect turned out to be.
        from ..game_types import OracleExecutionContext
        from ..handlers.control_flow import evaluate_condition

        # The three scans above are by kind, so a trigger they already enqueued
        # must not be enqueued a second time by this one. None of their kinds
        # carries a gate today; the check is here rather than as a comment
        # because "today" is the part that expires.
        already = {
            (id(event["source_permanent"]), id(event["instruction"]))
            for event in events
        }
        # Two scans, because the printed scope decides who fires: "your end
        # step" is this step's own player, "the"/"each" is everyone.
        gated = list(iter_triggered_abilities(
            self,
            condition_kinds={END_STEP_SELF_CONDITION},
            players=[self.players[player_index]],
        )) + list(iter_triggered_abilities(
            self,
            condition_kinds={END_STEP_EACH_CONDITION},
        )) + [
            # The attached scope, scanned over every seat and then narrowed by
            # the attachment: the Aura's controller and the enchanted
            # permanent's controller need not be the same player (Aggression is
            # printed to be put on an *opponent's* creature), so the seat this
            # trigger answers to is not the one holding the Aura.
            found for found in iter_triggered_abilities(
                self,
                condition_kinds={END_STEP_ENCHANTED_CONTROLLER_CONDITION},
            )
            if end_step_trigger_seat_matches(
                self, found[1],
                END_STEP_ENCHANTED_CONTROLLER_CONDITION, player_index,
            )
        ]
        for controller_index, permanent, trig in gated:
            if trig.instruction is None:
                continue
            gate = (trig.instruction.payload or {}).get(END_STEP_INTERVENING_IF)
            if gate is None or (id(permanent), id(trig.instruction)) in already:
                continue
            # CR 603.4: a gated trigger whose condition is false **does not
            # trigger**. So it is marked seen here, before the gate is asked,
            # rather than only on the path that fires it — the catch-all scan
            # below enqueues every end-step trigger it has not already seen, so
            # a failing gate used to put the ability on the stack anyway and
            # leave the resolution re-check to say it "did nothing". An ability
            # that never triggered is not an ability that resolves to nothing:
            # it holds no priority, it cannot be countered, and nothing in
            # response sees it.
            already.add((id(permanent), id(trig.instruction)))
            fire_context = OracleExecutionContext(
                caster=self.players[controller_index],
                target=self.players[controller_index],
                card=permanent.card,
                source_permanent=permanent,
                # Whose end step this firing is, stamped here as well as on the
                # enqueued event below — a gate naming "that player" (Razor
                # Pendulum's "if that player has 5 or less life") is asked
                # *before* the event exists, so without it the seat resolved to
                # nobody and the condition read false on every end step. The
                # same key and the same value the enqueue stamps, so the check
                # and the resolution ask about one seat.
                trigger_context={"event_subject_player": player_index},
            )
            if not evaluate_condition(self, fire_context, gate):
                continue
            events.append(make_trigger_event(
                controller_index, permanent, trig,
                # The same stamp the catch-all scan below makes, and this path
                # was missing it: CR 603.4 checks the gate **again** as the
                # ability resolves, so a trigger enqueued without the seat its
                # condition names passed the first check and failed the second.
                # Razor Pendulum's "if that player has 5 or less life" fired at
                # 5 life and then logged that its condition was no longer true.
                trigger_context={"event_subject_player": player_index},
            ))

        # Everything else with an end-step condition. The scans above are keyed
        # to *instruction kinds*, which made this step a cascade: Gadrak's
        # "create a Treasure token for each nontoken creature that died this
        # turn" compiled to a perfectly good `create_token` and fired nowhere,
        # because `create_token` was on none of the lists. A trigger's condition
        # is what says when it fires; its effect is not a second condition.
        #
        # Deduped against everything above by the same `already` set, so a kind
        # a specific scan handles (with its own trigger context, or its own
        # re-checked guard) is not enqueued twice.
        for controller_index, permanent, trig in gated:
            if trig.instruction is None:
                continue
            if (id(permanent), id(trig.instruction)) in already:
                continue
            events.append(make_trigger_event(
                controller_index, permanent, trig,
                # Whose end step this firing is, frozen now (CR 603.10). "At the
                # beginning of each player's end step, tap all untapped Islands
                # **that player** controls and this enchantment deals X damage
                # **to the player**" (Monsoon) is one ability with a different
                # seat each time it fires, and by the time the stack resolves it
                # the only seat still readable off the board is the source's
                # controller — which is the wrong one on every end step but
                # their own. The upkeep announcement has stamped the same key
                # for the same reason since Mana Vortex.
                trigger_context={"event_subject_player": player_index},
            ))

        # Emblems (CR 114.4): "At the beginning of your end step, …" (Garruk,
        # Unleashed's emblem) fires from the command zone — scoped to this end
        # step's own player, which is what "your" means here.
        from ..events import emblem_trigger_events, graveyard_trigger_events

        events.extend(
            emblem_trigger_events(
                self, END_STEP_SELF_CONDITION, [self.players[player_index]]
            )
        )
        events.extend(emblem_trigger_events(self, END_STEP_EACH_CONDITION))

        # And from a graveyard (CR 113.6m; Silversmote Ghoul). Scoped like the
        # emblem scan above: "your end step" is this step's own player, and for a
        # card nobody controls "your" is its owner (CR 108.4a). The intervening-if
        # is checked here — the same CR 603.4 check the gated battlefield scan
        # above makes — and again as the ability resolves.
        for _kind, _scope in (
            (END_STEP_SELF_CONDITION, [self.players[player_index]]),
            (END_STEP_EACH_CONDITION, None),
        ):
            for grave_event in graveyard_trigger_events(self, _kind, _scope):
                grave_gate = (grave_event["instruction"].payload or {}).get(
                    END_STEP_INTERVENING_IF
                )
                if grave_gate is not None:
                    grave_seat = grave_event["controller_index"]
                    if not evaluate_condition(
                        self,
                        OracleExecutionContext(
                            caster=self.players[grave_seat],
                            target=self.players[grave_seat],
                            card=grave_event["card"],
                        ),
                        grave_gate,
                    ):
                        continue
                events.append(grave_event)

        self._enqueue_triggered_batch(events)

        # CR 704.3 checks before anyone has priority. The step's delayed
        # removals used to be carried out inline above, so a lord could be
        # gone before the window opened; they are stack objects now, and the
        # check stays because the upkeep, whose inline effects are the same
        # shape, has always made it here, and the step's state triggers want
        # it (CR 117.5).
        self._check_after_turn_based_actions()
        if self._receives_priority(step):
            self.start_priority_window(self.active_player_index)

    def _end_step_mark_firings(self) -> list:
        """Every delayed ability recorded as a mark that triggers as this end
        step begins, as ``(permanent, mark, rider)`` for
        ``delayed_triggers.delayed_mark_events``.

        * "…at the beginning of the next end step" — destroy (Dragon Whelp's
          kin through ``destroy_at_next_end_step``, Glyph of Destruction),
          sacrifice (Krovikan Elementalist, Celestial Sword), return
          (Rakalite) — fires at the next end step there is.
        * "Destroy it at the beginning of the next end step **if it didn't
          attack this turn**" (Nettling Imp, Maddening Imp) and "…**if it
          attacked this turn**" (Berserk): the condition is the ability's
          effect, asked as it resolves (``if_attacked``), not whether it
          triggers. These marks are this turn's (cleanup sweeps them).
        * "At the beginning of **that turn's** end step, …" (Oracle en-Vec):
          the seat-turn stamp fires only at the end step of the turn it names
          and stays inert at every other.

        Over each seat's permanents through the control seam, so a phased-out
        permanent's mark waits (CR 702.26d), as the sweeps it replaces did.
        """
        firings: list = []
        for controller in self.players:
            for permanent in self.controlled_by(controller):
                metadata = permanent.metadata
                if metadata.get("destroy_at_next_end_step"):
                    firings.append((permanent, "destroy_at_next_end_step",
                                    {"action": "destroy"}))
                if metadata.get("destroy_if_did_not_attack_eot"):
                    firings.append((permanent, "destroy_if_did_not_attack_eot",
                                    {"action": "destroy", "if_attacked": False}))
                if marked_for_this_turn(
                    self, permanent, DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY
                ):
                    firings.append((permanent, DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY,
                                    {"action": "destroy", "if_attacked": False}))
                if metadata.get("destroy_if_attacked_eot"):
                    firings.append((permanent, "destroy_if_attacked_eot",
                                    {"action": "destroy", "if_attacked": True}))
                if metadata.get("sacrifice_at_next_end_step"):
                    firings.append((permanent, "sacrifice_at_next_end_step",
                                    {"action": "sacrifice"}))
                if metadata.get("bounce_at_next_end_step"):
                    firings.append((permanent, "bounce_at_next_end_step",
                                    {"action": "bounce"}))
        return firings

    @goes_no_further(True)
    def close_end_step(self) -> bool:
        """End the end step; True when it ended.

        **What is on the stack resolves here, in the step** (CR 500.2: a step
        ends when the stack is empty and all players pass). This only cleared
        the priority window, so an end-step trigger nobody had passed priority
        over — every one on an AI's turn at a table with a human, 37 of the 57
        permanents in the pool with one — rode into the cleanup step and
        resolved in its ``_settle`` instead, after the hand-size discard.

        Drained only when something is there: a caller that has already
        drained the window (the simulator's ``_drain_step``) gave the players
        their last priority on an empty stack, and a second offer would be a
        priority window CR 513 does not have. False when the window stops on a
        question (CR 608.2): the step is held open and cleanup must wait.
        """
        if self.current_turn_phase != "ending" or self.current_step != "end":
            return True
        self.resume_held_step()
        if self._receives_priority(self.current_step):
            if self.stack:
                self._resolve_priority_window()
            if self.window_left_unfinished():
                self.hold_step_open()
                return False
            self.clear_priority_window()
        self._on_step_or_phase_end("ending", "end")
        return True
