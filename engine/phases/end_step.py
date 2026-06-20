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
                if permanent.metadata.get("destroy_at_next_end_step") or did_not_attack:
                    controller.graveyard.append(permanent.card)
                    destroyed_names.append(permanent.card.name)
                else:
                    survivors.append(permanent)
            controller.battlefield = survivors

        for name in destroyed_names:
            self.log.append(f"{name} was destroyed at end step")

        # Scavenging Ghoul: "At the beginning of each end step, put a corpse
        # counter on this creature for each creature that died this turn."
        died = getattr(self, "creatures_died_this_turn", 0)
        if died:
            for controller in self.players:
                for permanent in controller.battlefield:
                    prog = compile_card_oracle(permanent.card)
                    if any(
                        t.condition.kind == "end_step"
                        and t.instruction is not None
                        and t.instruction.kind == "add_corpse_counters_for_each_creature_died"
                        for t in prog.triggered_abilities
                    ):
                        permanent.metadata["corpse_counters"] = (
                            int(permanent.metadata.get("corpse_counters", 0)) + died
                        )
                        self.log.append(f"{permanent.card.name} gets {died} corpse counter(s)")

        # Pestilence-style: "At the beginning of the end step, if no creatures on the battlefield, sacrifice"
        all_perms = [p for pl in self.players for p in pl.battlefield]
        has_creatures = any(p.card.primary_type == "creature" for p in all_perms)
        if not has_creatures:
            for controller in self.players:
                to_sacrifice: list[Permanent] = []
                for permanent in controller.battlefield:
                    prog = compile_card_oracle(permanent.card)
                    if any(
                        t.condition.kind == "end_step" and t.instruction is not None and t.instruction.kind == "sacrifice_if_no_creatures"
                        for t in prog.triggered_abilities
                    ):
                        to_sacrifice.append(permanent)
                for permanent in to_sacrifice:
                    controller.battlefield.remove(permanent)
                    controller.graveyard.append(permanent.card)
                    self.log.append(f"{permanent.card.name} sacrificed at end step (no creatures)")

        if self._receives_priority(step):
            self.start_priority_window(self.active_player_index)

    def close_end_step(self) -> None:
        if self.current_turn_phase != "ending" or self.current_step != "end":
            return
        if self._receives_priority(self.current_step):
            self.clear_priority_window()
        self._on_step_or_phase_end("ending", "end")
