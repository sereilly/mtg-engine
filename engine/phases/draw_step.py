from __future__ import annotations

"""Draw step (CR 504).

The active player draws a card as a turn-based action. Draw-step behaviors
(skip-for-protection, bonus draws) are declared per card in
engine/card_hooks.py:DRAW_STEP_MODIFIERS — this module only aggregates and
enforces them, so a new draw-modifier card never touches it.
"""

from ..card_hooks import DRAW_STEP_MODIFIERS


class DrawStepMixin:
    def resolve_draw_step(
        self,
        player_index: int,
        sanctuary_choice: bool | None = None,
        defer_priority: bool = False,
        pay_life_loss: dict[str, bool] | None = None,
    ) -> int:
        phase = "beginning"
        step = "draw"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        player = self.players[player_index]

        # Nafs Asp: obligations armed against this player resolve now, before
        # the draw itself — "before that draw step" (a human is prompted via
        # pay_life_loss keyed by source name; AI/headless pays when able).
        still_pending = []
        for obligation in self.pending_draw_step_life_loss:
            if obligation["player_index"] != player_index:
                still_pending.append(obligation)
                continue
            source_name = obligation["source_name"]
            cost = obligation["cost"]
            if pay_life_loss is not None and source_name in pay_life_loss:
                paid = pay_life_loss[source_name] and self.can_pay_upkeep_mana(
                    player, {"generic": cost}
                )
            else:
                paid = self.can_pay_upkeep_mana(player, {"generic": cost})
            if paid:
                self._spend_upkeep_mana(player, {"generic": cost})
                self.log.append(f"{player.name} paid {{{cost}}} to avoid losing life ({source_name})")
            else:
                amount = obligation["amount"]
                player.life -= amount
                self.log.append(f"{player.name} lost {amount} life ({source_name})")
        self.pending_draw_step_life_loss = still_pending

        # 614.1b/614.10: skip step is a replacement effect
        if self._consume_skip(self.skip_step_counts, step):
            self.log.append(f"{player.name} skipped draw step")
            self._close_or_defer_step(phase, step, defer_priority)
            return 0

        # CR 103.8a: in a two-player game, the player who plays first skips
        # the draw step of their first turn. game.turn is 1 exactly during the
        # game's first turn in every flow (headless start_turn, AI simulator
        # half-turn counter, web _start_next_turn). 103.8c: multiplayer games
        # don't skip.
        if self.turn == 1 and len(self.players) == 2:
            self.log.append(f"{player.name} skips the first turn's draw step (CR 103.8a)")
            self._close_or_defer_step(phase, step, defer_priority)
            return 0

        # Island Sanctuary: sanctuary_choice=None means auto-skip (AI); True=skip (human chose);
        # False=draw normally (human chose to draw instead of gaining protection)
        has_sanctuary = any(
            (modifier := DRAW_STEP_MODIFIERS.get(perm.card.name)) is not None
            and modifier.optional_skip_grants_protection
            for perm in player.battlefield
        )
        if has_sanctuary and sanctuary_choice is not False:
            player.island_sanctuary_protected = True
            self.log.append(f"{player.name} skipped draw (Island Sanctuary active)")
            self._close_or_defer_step(phase, step, defer_priority)
            return 0

        bonus = 0
        for controller in self.players:
            for permanent in controller.battlefield:
                modifier = DRAW_STEP_MODIFIERS.get(permanent.card.name)
                if modifier is None or not modifier.extra_draws:
                    continue
                if modifier.requires_untapped and permanent.tapped:
                    continue
                bonus += modifier.extra_draws
        drawn = player.draw(1 + bonus)
        self.log.append(f"{player.name} drew {drawn} card(s) in draw step")
        self._close_or_defer_step(phase, step, defer_priority)
        return drawn
