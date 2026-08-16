from __future__ import annotations

"""End step (CR 513).

"At the beginning of the end step" triggered abilities are put on the stack here:
delayed end-of-turn destruction (e.g. creatures forced to attack that didn't),
Scavenging Ghoul corpse counters, and Pestilence-style "sacrifice if no
creatures" triggers. The active player then receives priority.
"""

from ..models import Permanent
from ..tokens import make_token_card
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
END_STEP_EMPTY_BOARD_KINDS = frozenset({"sacrifice_if_no_creatures"})
END_STEP_DID_NOT_ATTACK_KINDS = frozenset({"end_step_damage_if_not_attacked"})

#: Every instruction kind an ``end_step`` trigger can be dispatched on *by kind*.
#: The fourth scan below is keyed on a payload **shape** instead and so has no
#: entry here — see ``END_STEP_INTERVENING_IF``.
END_STEP_DISPATCHED_KINDS = (
    END_STEP_DEATH_COUNTER_KINDS
    | END_STEP_EMPTY_BOARD_KINDS
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

        # Rukh Egg: tokens armed by a "dies" trigger appear now, regardless of
        # whose turn it is (CR 603.3 delayed triggers use their own fixed
        # timing, not "your end step").
        pending_tokens = self.pending_end_step_tokens
        self.pending_end_step_tokens = []
        for spec in pending_tokens:
            controller_index = spec["controller_index"]
            if not (0 <= controller_index < len(self.players)):
                continue
            token_card = make_token_card(
                spec["name"], spec["power"], spec["toughness"], spec["type_line"],
                colors=spec.get("colors", ()), keywords=spec.get("keywords", ()),
            )
            self._put_permanent_onto_battlefield(
                controller_index, Permanent(card=token_card, metadata={"is_token": True}), None
            )
            self.log.append(f"{self.players[controller_index].name}'s {token_card.name} token entered the battlefield")

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
                condition_kinds={"end_step"},
                instruction_kinds=END_STEP_DEATH_COUNTER_KINDS,
            ):
                events.append(make_trigger_event(
                    controller_index, permanent, trig, trigger_context={"count": died}
                ))

        # Pestilence-style: "...if there are no creatures on the battlefield,
        # sacrifice this." The intervening-if is re-checked when the trigger resolves.
        all_perms = list(self.all_permanents())
        has_creatures = any(p.is_creature for p in all_perms)
        if not has_creatures:
            for controller_index, permanent, trig in iter_triggered_abilities(
                self,
                condition_kinds={"end_step"},
                instruction_kinds=END_STEP_EMPTY_BOARD_KINDS,
            ):
                events.append(make_trigger_event(controller_index, permanent, trig))

        # Erg Raiders: "at the beginning of YOUR end step" — scoped to this
        # end step's own player only, unlike the two blocks above (which don't
        # yet distinguish "your" from "each"/"the"). The "didn't attack" /
        # "came under your control this turn" guards are re-checked at
        # resolution (matching the Pestilence intervening-if precedent).
        for controller_index, permanent, trig in iter_triggered_abilities(
            self,
            condition_kinds={"end_step"},
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
        for controller_index, permanent, trig in iter_triggered_abilities(
            self,
            condition_kinds={"end_step"},
            players=[self.players[player_index]],
        ):
            if trig.instruction is None:
                continue
            gate = (trig.instruction.payload or {}).get(END_STEP_INTERVENING_IF)
            if gate is None or (id(permanent), id(trig.instruction)) in already:
                continue
            fire_context = OracleExecutionContext(
                caster=self.players[controller_index],
                target=self.players[controller_index],
                card=permanent.card,
                source_permanent=permanent,
            )
            if not evaluate_condition(self, fire_context, gate):
                continue
            events.append(make_trigger_event(controller_index, permanent, trig))

        # Emblems (CR 114.4): "At the beginning of your end step, …" (Garruk,
        # Unleashed's emblem) fires from the command zone — scoped to this end
        # step's own player, which is what "your" means here.
        from ..events import emblem_trigger_events

        events.extend(
            emblem_trigger_events(self, "end_step", [self.players[player_index]])
        )

        self._enqueue_triggered_batch(events)

        if self._receives_priority(step):
            self.start_priority_window(self.active_player_index)

    def close_end_step(self) -> None:
        if self.current_turn_phase != "ending" or self.current_step != "end":
            return
        if self._receives_priority(self.current_step):
            self.clear_priority_window()
        self._on_step_or_phase_end("ending", "end")
