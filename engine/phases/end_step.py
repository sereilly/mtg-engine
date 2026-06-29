from __future__ import annotations

"""End step (CR 513).

"At the beginning of the end step" triggered abilities are put on the stack here:
delayed end-of-turn destruction (e.g. creatures forced to attack that didn't),
Scavenging Ghoul corpse counters, and Pestilence-style "sacrifice if no
creatures" triggers. The active player then receives priority.
"""

from ..models import Permanent
from ..oracle import compile_card_oracle


class EndStepMixin:
    def resolve_end_step(self, player_index: int) -> None:
        phase = "ending"
        step = "end"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        destroyed_names: list[str] = []
        for controller in self.players:
            survivors: list[Permanent] = []
            for permanent in controller.battlefield:
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
                if (
                    permanent.metadata.get("destroy_at_next_end_step")
                    or permanent.metadata.get("sacrifice_at_next_end_step")
                    or did_not_attack
                    or berserk_attacked
                ):
                    controller.graveyard.append(permanent.card)
                    destroyed_names.append(permanent.card.name)
                else:
                    survivors.append(permanent)
            controller.battlefield = survivors

        for name in destroyed_names:
            self.log.append(f"{name} was destroyed at end step")

        # "At the beginning of the end step" triggered abilities go on the stack
        # (CR 603.3) and resolve through the end-step priority window opened below.
        events: list[dict] = []

        # Scavenging Ghoul: "...put a corpse counter on this creature for each
        # creature that died this turn." The death count is captured now (it resets
        # next turn) and read by the handler at resolution.
        died = getattr(self, "creatures_died_this_turn", 0)
        if died:
            for controller in self.players:
                controller_index = self.players.index(controller)
                for permanent in controller.battlefield:
                    prog = compile_card_oracle(permanent.card)
                    for trig in prog.triggered_abilities:
                        if (
                            trig.condition.kind == "end_step"
                            and trig.instruction is not None
                            and trig.instruction.kind == "add_corpse_counters_for_each_creature_died"
                        ):
                            events.append({
                                "controller_index": controller_index,
                                "source_permanent": permanent,
                                "instruction": trig.instruction,
                                "effect_kind": trig.effect_kind,
                                "ability_text": trig.source_line,
                                "trigger_context": {"count": died},
                            })
                            break

        # Pestilence-style: "...if there are no creatures on the battlefield,
        # sacrifice this." The intervening-if is re-checked when the trigger resolves.
        all_perms = [p for pl in self.players for p in pl.battlefield]
        has_creatures = any(p.card.primary_type == "creature" for p in all_perms)
        if not has_creatures:
            for controller in self.players:
                controller_index = self.players.index(controller)
                for permanent in controller.battlefield:
                    prog = compile_card_oracle(permanent.card)
                    for trig in prog.triggered_abilities:
                        if (
                            trig.condition.kind == "end_step"
                            and trig.instruction is not None
                            and trig.instruction.kind == "sacrifice_if_no_creatures"
                        ):
                            events.append({
                                "controller_index": controller_index,
                                "source_permanent": permanent,
                                "instruction": trig.instruction,
                                "effect_kind": trig.effect_kind,
                                "ability_text": trig.source_line,
                            })
                            break

        self._enqueue_triggered_batch(events)

        if self._receives_priority(step):
            self.start_priority_window(self.active_player_index)

    def close_end_step(self) -> None:
        if self.current_turn_phase != "ending" or self.current_step != "end":
            return
        if self._receives_priority(self.current_step):
            self.clear_priority_window()
        self._on_step_or_phase_end("ending", "end")
