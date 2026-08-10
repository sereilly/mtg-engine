from __future__ import annotations

import re

"""Draw step (CR 504).

The active player draws a card as a turn-based action. Bonus draws granted to
every player are derived from oracle text by engine/draw_step_modifiers.py;
the skip-your-draw-for-protection behavior stays name-keyed in
engine/card_hooks.py:DRAW_STEP_MODIFIERS because the protection quality it
grants is card-specific. Either way this module only aggregates and enforces,
so a new bonus-draw card never touches it.
"""

from ..card_hooks import DRAW_STEP_MODIFIERS
from ..draw_step_modifiers import draw_step_bonus_for


class DrawStepMixin:
    def get_draw_step_life_loss_choices(self, player_index: int) -> list[dict]:
        """Nafs Asp obligations armed against *player_index*, as pay-or-consequence
        choices shaped like ``get_upkeep_pay_triggers`` entries.

        The card says the payment happens "before that draw step", so these are
        offered during the player's upkeep alongside the other pay-or-else
        prompts; the answers come back to ``resolve_draw_step(pay_life_loss=...)``
        keyed by source name. Obligations from several copies of the same source
        collapse into one prompt (they share a name and a cost).
        """
        choices: list[dict] = []
        seen: set[str] = set()
        for obligation in self.pending_draw_step_life_loss:
            if obligation["player_index"] != player_index:
                continue
            name = obligation["source_name"]
            if name in seen:
                continue
            seen.add(name)
            choices.append({
                "card_name": name,
                "mana": {"generic": int(obligation["cost"])},
                "kind": "draw_step_life_loss_unless_pay",
                "damage": 0,
                "life_loss": int(obligation["amount"]),
            })
        return choices

    _COUNTER_DAMAGE_RE = re.compile(
        r"at the beginning of your draw step, this \w+ deals damage equal to "
        r"the number of (?P<kind>\w+) counters on it to each player"
    )

    def _resolve_draw_step_counter_damage(self, player_index: int) -> None:
        """Armageddon Clock's draw-step damage.

        Only the *controller's* draw step fires it ("your draw step"), and the
        damage goes to every player including them.
        """
        controller = self.players[player_index]
        for permanent in list(controller.battlefield):
            text = " ".join(permanent.effective_card.oracle_text.lower().split())
            match = self._COUNTER_DAMAGE_RE.search(text)
            if match is None:
                continue
            amount = int(permanent.metadata.get(f"{match.group('kind')}_counters", 0))
            if amount <= 0:
                continue
            for victim in self.players:
                self._deal_damage_to_player(victim, amount, source=permanent)
            self.log.append(
                f"{permanent.card.name} dealt {amount} damage to each player"
            )

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

        # "At the beginning of your draw step, this artifact deals damage equal
        # to the number of <kind> counters on it to each player." (Armageddon
        # Clock.) Derived from the source's own text and its current counter
        # count, so the amount is never stored anywhere that could drift from
        # the counters.
        self._resolve_draw_step_counter_damage(player_index)

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
            for perm in self.controlled_by(player)
        )
        if has_sanctuary and sanctuary_choice is not False:
            player.island_sanctuary_protected = True
            self.log.append(f"{player.name} skipped draw (Island Sanctuary active)")
            self._close_or_defer_step(phase, step, defer_priority)
            return 0

        bonus = 0
        for permanent in self.all_permanents():
            extra = draw_step_bonus_for(permanent.effective_card.oracle_text)
            if extra is None:
                continue
            if extra.requires_untapped and permanent.tapped:
                continue
            bonus += extra.count
        drawn = self._draw_with_replacements(player, 1 + bonus)
        self.log.append(f"{player.name} drew {drawn} card(s) in draw step")
        self._close_or_defer_step(phase, step, defer_priority)
        return drawn
