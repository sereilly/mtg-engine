from __future__ import annotations

"""Draw step (CR 504).

The active player draws a card as a turn-based action. Honors the draw-step skip
replacement effect, Island Sanctuary's "skip your draw step to gain protection"
choice, and the extra-draw bonus from Howling Mine.
"""


class DrawStepMixin:
    def resolve_draw_step(self, player_index: int, sanctuary_choice: bool | None = None, defer_priority: bool = False) -> int:
        phase = "beginning"
        step = "draw"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        player = self.players[player_index]

        # 614.1b/614.10: skip step is a replacement effect
        if self._consume_skip(self.skip_step_counts, step):
            self.log.append(f"{player.name} skipped draw step")
            self._close_or_defer_step(phase, step, defer_priority)
            return 0

        # Island Sanctuary: sanctuary_choice=None means auto-skip (AI); True=skip (human chose);
        # False=draw normally (human chose to draw instead of gaining protection)
        has_sanctuary = any(perm.card.name == "Island Sanctuary" for perm in player.battlefield)
        if has_sanctuary and sanctuary_choice is not False:
            player.island_sanctuary_protected = True
            self.log.append(f"{player.name} skipped draw (Island Sanctuary active)")
            self._close_or_defer_step(phase, step, defer_priority)
            return 0

        bonus = 0
        for controller in self.players:
            for permanent in controller.battlefield:
                if permanent.card.name == "Howling Mine" and not permanent.tapped:
                    bonus += 1
        drawn = player.draw(1 + bonus)
        self.log.append(f"{player.name} drew {drawn} card(s) in draw step")
        self._close_or_defer_step(phase, step, defer_priority)
        return drawn
