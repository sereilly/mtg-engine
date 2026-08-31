from __future__ import annotations

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

from ..delayed_triggers import fire_delayed_triggers
from ..models import Permanent
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
END_STEP_DID_NOT_ATTACK_KINDS = frozenset({"end_step_damage_if_not_attacked"})

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
END_STEP_DISPATCHED_KINDS = (
    END_STEP_DEATH_COUNTER_KINDS
    | END_STEP_DID_NOT_ATTACK_KINDS
)

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
    def resolve_end_step(self, player_index: int) -> None:
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

        def _delayed_eot_removal(permanent: Permanent) -> bool:
            # Nettling Imp / Siren's Call: destroy creatures that were
            # required to attack this turn but didn't.
            did_not_attack = permanent.metadata.get(
                "destroy_if_did_not_attack_eot"
            ) and not permanent.metadata.get("attacked_this_turn")
            # Berserk: "destroy that creature if it attacked this turn."
            berserk_attacked = permanent.metadata.get(
                "destroy_if_attacked_eot"
            ) and permanent.metadata.get("attacked_this_turn")
            # Dragon Whelp / Berserk set a delayed end-of-turn destruction.
            return bool(
                permanent.metadata.get("destroy_at_next_end_step")
                or permanent.metadata.get("sacrifice_at_next_end_step")
                or did_not_attack
                or berserk_attacked
            )

        # Regeneration is deliberately not offered here: the flags conflate
        # sacrifices (not destruction, so no replacement effect applies —
        # CR 701.21a) with destructions; separating them is a rules feature,
        # not cleanup.
        destroyed_names: list[str] = []
        for controller in self.players:
            for permanent in self._destroy_swept_permanents(
                controller, _delayed_eot_removal,
                allow_regeneration=False, respect_indestructible=False,
            ):
                destroyed_names.append(permanent.card.name)

        for name in destroyed_names:
            self.log.append(f"{name} was destroyed at end step")

        # "Return this artifact to its owner's hand at the beginning of the
        # next end step." (Rakalite.) The bounce twin of the destruction sweep
        # above, and beside it rather than folded in: a delayed *removal* and a
        # delayed *return* end in different zones, and the sweep above is
        # explicitly the one that does not offer regeneration because its flags
        # conflate sacrifice with destruction. Nothing about that reasoning
        # extends to a bounce.
        for controller in list(self.players):
            for permanent in list(self.controlled_by(controller)):
                if not permanent.metadata.pop("bounce_at_next_end_step", False):
                    continue
                owner_index = self.owner_index_of(permanent)
                owner = (
                    self.players[owner_index] if owner_index is not None else controller
                )
                self.remove_from_battlefield(permanent)
                self.put_card_into_hand(owner, permanent.card)
                self.log.append(
                    f"{permanent.card.name} returned to {owner.name}'s hand at end step"
                )

        # "At the beginning of the end step" triggered abilities go on the stack
        # (CR 603.3) and resolve through the end-step priority window opened below.
        events: list[dict] = []

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

        # Erg Raiders: "at the beginning of YOUR end step" — scoped to this
        # end step's own player only, unlike the two blocks above (which don't
        # yet distinguish "your" from "each"/"the"). The "didn't attack" /
        # "came under your control this turn" guards are re-checked at
        # resolution (matching the Pestilence intervening-if precedent).
        for controller_index, permanent, trig in iter_triggered_abilities(
            self,
            condition_kinds={END_STEP_SELF_CONDITION},
            instruction_kinds=END_STEP_DID_NOT_ATTACK_KINDS,
            players=[self.players[player_index]],
        ):
            events.append(make_trigger_event(controller_index, permanent, trig))

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
            )
            if not evaluate_condition(self, fire_context, gate):
                continue
            events.append(make_trigger_event(controller_index, permanent, trig))

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
            events.append(make_trigger_event(controller_index, permanent, trig))

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

        if self._receives_priority(step):
            self.start_priority_window(self.active_player_index)

    def close_end_step(self) -> None:
        if self.current_turn_phase != "ending" or self.current_step != "end":
            return
        if self._receives_priority(self.current_step):
            self.clear_priority_window()
        self._on_step_or_phase_end("ending", "end")
