from __future__ import annotations

"""Draw step (CR 504).

The active player draws a card as a turn-based action. Bonus draws granted to
every player are derived from oracle text by engine/draw_step_modifiers.py;
the skip-your-draw-for-protection behavior stays name-keyed in
engine/card_hooks.py:DRAW_STEP_MODIFIERS because the protection quality it
grants is card-specific. Either way this module only aggregates and enforces,
so a new bonus-draw card never touches it.

"At the beginning of your draw step" triggered abilities are put on the stack
here (CR 603.3), the same way the upkeep and end steps do it. Until round 140
this step had no trigger dispatch at all: Armageddon Clock's damage was a regex
over the permanent's oracle text sitting in this file, and Mana Vault's
"if this artifact is tapped, it deals 1 damage to you" — which no regex here
matched — did nothing whatsoever.
"""

from ..card_hooks import DRAW_STEP_MODIFIERS
from ..delayed_triggers import fire_delayed_triggers
from ..draw_step_modifiers import (draw_step_bonus_for, draw_step_skip_for,
                                   skips_own_draw_step)
from ..game_types import OracleExecutionContext
from ..handlers.control_flow import evaluate_condition
from ..mana_payment import generic_cost
from ..pt import BASE_PT_REVERT_KEY, clear_base_pt
from ..upkeep_costs import UpkeepCost, cost_prompt_fields
from ..trigger_utils import iter_triggered_abilities, make_trigger_event

#: The two draw-step conditions and the only difference between them, the same
#: pair the upkeep and end steps carry: ``draw_step_self`` is "at the beginning
#: of **your** draw step" and fires for the permanent's own controller,
#: ``draw_step_each`` is "each player's" and fires for whoever's step it is.
DRAW_STEP_SELF_CONDITION = "draw_step_self"
DRAW_STEP_EACH_CONDITION = "draw_step_each"

#: The payload key holding a CR 603.4 intervening-if, checked as the trigger
#: would fire and again as it resolves. Keyed on the payload's *shape* rather
#: than on a list of instruction kinds, for the reason end_step.py gives: a list
#: of kinds is only ever as complete as the last card that touched it.
DRAW_STEP_INTERVENING_IF = "intervening_if"


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
                **cost_prompt_fields(UpkeepCost(mana=generic_cost(int(obligation["cost"])))),
                "kind": "draw_step_life_loss_unless_pay",
                "damage": 0,
                "life_loss": int(obligation["amount"]),
            })
        return choices

    def _enqueue_draw_step_triggers(self, player_index: int) -> None:
        """Put this draw step's triggered abilities on the stack (CR 603.3).

        Two scans, because the printed scope decides who fires: "your draw step"
        is the source's own controller, "each player's" is everyone. Keyed on
        the *condition* alone and not on a list of instruction kinds — a
        trigger's condition is what says when it fires, and its effect is not a
        second condition (the lesson end_step.py records at length).
        """
        events: list[dict] = []
        scoped = list(iter_triggered_abilities(
            self,
            condition_kinds={DRAW_STEP_SELF_CONDITION},
            players=[self.players[player_index]],
        )) + list(iter_triggered_abilities(
            self,
            condition_kinds={DRAW_STEP_EACH_CONDITION},
        ))
        for controller_index, permanent, trig in scoped:
            if trig.instruction is None:
                continue
            gate = (trig.instruction.payload or {}).get(DRAW_STEP_INTERVENING_IF)
            if gate is not None and not evaluate_condition(
                self,
                OracleExecutionContext(
                    caster=self.players[controller_index],
                    target=self.players[controller_index],
                    card=permanent.card,
                    source_permanent=permanent,
                ),
                gate,
            ):
                continue
            events.append(make_trigger_event(controller_index, permanent, trig))
        self._enqueue_triggered_batch(events)

    def resolve_draw_step(
        self,
        player_index: int,
        sanctuary_choice: bool | None = None,
        draw_skip_choice: bool | None = None,
        defer_priority: bool = False,
        pay_life_loss: dict[str, bool] | None = None,
    ) -> int:
        phase = "beginning"
        step = "draw"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        player = self.players[player_index]

        # "…until the end of your next upkeep" (Halfdane): a base-P/T rewrite
        # stamped to revert when this seat's upkeep ends — which is now, the
        # moment the draw step begins. Before the skip checks below, because a
        # skipped *draw* (CR 103.8a, Island Sanctuary) is still a step whose
        # upkeep has ended. A stamp written during THIS turn's upkeep is the
        # trigger re-applying itself and survives to the next one; an older
        # stamp is an effect whose time is up, and clearing the base restores
        # the printed values underneath (engine/pt.py documents the key).
        for perm in self.all_permanents():
            stamp = perm.metadata.get(BASE_PT_REVERT_KEY)
            if (
                isinstance(stamp, dict)
                and stamp.get("seat") == player_index
                and stamp.get("turn") != self.turn
            ):
                clear_base_pt(perm)
                self.log.append(
                    f"{perm.card.name}'s base power and toughness revert "
                    f"({player.name}'s upkeep has ended)"
                )

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
        if self._consume_step_skip(step, player_index):
            self.log.append(f"{player.name} skipped draw step")
            self._close_or_defer_step(phase, step, defer_priority)
            return 0

        # CR 603.3: the step is happening, so its triggers trigger. Enqueued
        # before the turn-based draw below and after the skip-step check above,
        # which is exactly the line CR 614.10 draws — a *skipped step* never
        # begins, so nothing triggers, while the three "skip the draw" paths
        # below (CR 103.8a's first turn, Island Sanctuary) skip a turn-based
        # action inside a step that did begin. Nothing observes the position
        # relative to the draw: the batch sits on the stack until the priority
        # window at the end of the step drains it.
        self._enqueue_draw_step_triggers(player_index)

        # "…at the beginning of **each of your draw steps**, put a -1/-1
        # counter on that creature." (Giant Oyster.) A delayed ability
        # (CR 603.7) belongs to no permanent, so the scan above cannot reach it
        # — it is announced here, at the same moment as the battlefield's own
        # draw-step triggers, and scoped to the entry's own controller because
        # that is what "your" says: a draw step belongs to one player, so an
        # ability an opponent created is not waiting for this one.
        fire_delayed_triggers(self, "controllers_draw_step", seat=player_index)

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

        # "Skip your draw step." (Necropotence.) CR 614.10's mandatory skip,
        # asked before the offer below because there is nothing to offer: a step
        # a static ability already skips is not a step anybody may choose to
        # take. Derived from the permanent's own text, so a source that has left
        # stops skipping with no flag to clear.
        for permanent in self.controlled_by(player_index):
            if not skips_own_draw_step(permanent.effective_card.oracle_text):
                continue
            self.log.append(
                f"{player.name} skips their draw step ({permanent.card.name})"
            )
            self._close_or_defer_step(phase, step, defer_priority)
            return 0

        # CR 504 with CR 614: "If you would begin your draw step, you may skip
        # that step instead. If you do, you gain 2 life." (Fasting.) Asked of
        # the *step*, before the turn-based draw below, because that is what the
        # card replaces — Island Sanctuary above replaces the draw inside a step
        # that did begin, which is why the two are separate checks rather than
        # one flag.
        #
        # A non-interactive seat takes the skip, which is the stated policy for
        # every "you may" the engine answers for a player (ROADMAP idiom 8):
        # the alternative is a default that silently declines whatever the card
        # was for. `draw_skip_choice=False` is a seat that chose to draw.
        for permanent in self.controlled_by(player):
            skip = draw_step_skip_for(permanent.effective_card.oracle_text)
            if skip is None or draw_skip_choice is False:
                continue
            self.log.append(
                f"{player.name} skipped their draw step ({permanent.card.name})"
            )
            if skip.life_gain:
                self._gain_life(player, skip.life_gain, permanent.card.name)
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
        # CR 504.1's turn-based draw, marked as such: "the first one you draw in
        # each of your draw steps" (Teferi's Ageless Insight) is exempt from a
        # draw-doubling rider, and this is the only call in the engine that can
        # say which draw that is. The bonus draws that ride along (Howling Mine)
        # are *not* the first one, which the flag gets right for free — the
        # exemption is one draw, not one event.
        drawn = self._draw_with_replacements(player, 1 + bonus, turn_based=True)
        self.log.append(f"{player.name} drew {drawn} card(s) in draw step")
        self._close_or_defer_step(phase, step, defer_priority)
        return drawn
