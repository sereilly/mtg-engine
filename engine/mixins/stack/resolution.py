"""Resolving the top of the stack (CR 608), and putting triggered abilities
onto it (CR 603).

The other end of the pipeline: whatever ``casting`` and ``activation`` queued
comes back here to be executed, its targets re-checked for legality
(CR 608.2b — a spell whose every target is illegal is countered), and its card
put wherever it goes afterwards.
"""

from __future__ import annotations

from ...classifier import CardClassification, classify_card
from ...game_types import OracleExecutionContext, OracleStateMachine, StackItem
from ...models import CardDefinition, Permanent
from ...oracle import OracleInstruction, compile_card_oracle

class StackResolutionMixin:
    def _enqueue_triggered_ability(
        self,
        *,
        controller_index: int,
        source_permanent: Permanent | None = None,
        card: CardDefinition | None = None,
        instruction: OracleInstruction | None = None,
        effect_kind: str | None = None,
        ability_text: str | None = None,
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        trigger_context: dict | None = None,
        hook_key: str | None = None,
        hook_event: dict | None = None,
    ) -> None:
        """Put a single triggered ability onto the stack as a StackItem (CR 603.3).

        Mirrors the attack/block trigger model (declare_attackers_step._fire_attack_triggers).
        The trigger resolves later through resolve_top_of_stack — never inline at the
        moment it fires. ``card`` defaults to the source permanent's card (used as the
        stack object's display name)."""
        stack_card = card if card is not None else (source_permanent.card if source_permanent is not None else None)
        if stack_card is None:
            return
        self.stack.append(
            StackItem(
                card=stack_card,
                caster_index=controller_index,
                target_player_index=target_player_index,
                target_permanent_index=target_permanent_index,
                x_value=None,
                ability_instruction=instruction,
                ability_effect_kind=effect_kind,
                source_permanent=source_permanent,
                ability_text=ability_text,
                trigger_context=trigger_context,
                hook_key=hook_key,
                hook_event=hook_event,
            )
        )
    def _enqueue_triggered_batch(self, events: list[dict]) -> None:
        """Put a batch of triggered abilities that fired from one event onto the stack
        in APNAP order (CR 603.3b): the active player's triggers are enqueued first
        (so they resolve last), then each other player's in turn order. Each player's
        own triggers keep their collection (battlefield-scan) order. The sort key is
        total and index-tie-broken, so enqueue order is fully seed-deterministic."""
        if not events:
            return
        n = len(self.players)
        active = self.active_player_index if self.active_player_index is not None else 0

        def _key(indexed):
            order, event = indexed
            controller = int(event["controller_index"])
            turn_distance = (controller - active) % n if n else 0
            return (turn_distance, controller, order)

        for _, event in sorted(enumerate(events), key=_key):
            self._enqueue_triggered_ability(**event)
    def _settle(self) -> None:
        """Run state-based actions, then resolve the stack one item at a time,
        re-checking SBAs between each resolution (CR 704.3 + 603.3). Triggers that
        fire during an SBA check are enqueued (never resolved) there, so this loop
        is what actually drains them in the headless/AI path. Terminates when the
        stack is empty and SBAs report no further change."""
        iterations = 0
        while True:
            self.check_state_based_actions()
            if not self.stack:
                break
            if not self.resolve_top_of_stack():
                # Top item is paused on a pending choice (Word of Command).
                break
            iterations += 1
            if iterations > self.MAX_SETTLE_ITERS:
                self.log.append(
                    f"_settle aborted after {self.MAX_SETTLE_ITERS} iterations (possible loop)"
                )
                break
    def resolve_stack(self) -> None:
        while self.stack:
            if not self.resolve_top_of_stack():
                # The top item is paused on a pending choice (Word of Command);
                # it resolves when the choice is confirmed.
                break
    def resolve_top_of_stack(self, pause_for_choices: bool = False) -> bool:
        """Resolve (and remove) the top stack object. Returns True if an object was
        resolved, False if the stack was empty.

        ``pause_for_choices`` is used by the human priority path (pass_priority): when
        a triggered ability resolves into an optional "you may pay {N} / draw" choice
        (Soul Net, the color Rods, Verduran Enchantress), the ability is kept on the
        stack and its pay-prompt is linked to it, so the ability stays visible on the
        stack until the player submits the prompt (CR 603.3 — the choice is made as the
        ability resolves). confirm_optional_pay / auto_resolve_pending_optional_pays
        then removes the ability from the stack. Headless/auto paths leave this False,
        so the ability resolves and pops immediately (the pending pay is auto-resolved
        by the caller, preserving deterministic behavior)."""
        if not self.stack:
            return False
        # A Word of Command paused mid-resolution stays on the stack until its
        # card choice is confirmed; it can't be resolved a second time. Once the
        # choice has been recorded (deferred confirm), releasing priority lands
        # here and finishes the resolution: the forced card is played and the
        # spell heads to the graveyard. The forced spell is left on the stack on
        # the interactive path (pause_for_choices) so it gets its own priority
        # round; headless loops drain it on their next iteration.
        if (
            self.pending_word_of_command is not None
            and self.pending_word_of_command.get("_stack_item") is self.stack[-1]
        ):
            pending = self.pending_word_of_command
            if "chosen_hand_index" not in pending:
                return False
            self.pending_word_of_command = None
            self._finish_word_of_command(
                pending, pending["chosen_hand_index"], auto_resolve_forced=False
            )
            return True

        item = self.stack.pop()
        pays_before = len(self.pending_optional_pays)
        woc_before = self.pending_word_of_command
        self._run_stack_item_resolution(item)
        # Power Sink armed a pending "pay {X} or be countered" for the targeted
        # spell's controller. On the human priority path leave it for the prompt;
        # headless/AI resolves it deterministically (pay if able, else countered).
        if self.pending_mana_payment is not None and self.pending_mana_payment.get("_new"):
            self.pending_mana_payment.pop("_new", None)
            if not pause_for_choices:
                self._auto_resolve_mana_payment()
        if pause_for_choices and len(self.pending_optional_pays) > pays_before:
            # The ability raised an optional pay/draw choice — keep it on the stack
            # until the choice is submitted (the only effect so far is registering the
            # prompt; the life gain / draw happens on confirm). Link each new prompt
            # entry to this stack item so confirming it removes the ability.
            self.stack.append(item)
            for entry in self.pending_optional_pays[pays_before:]:
                entry["_stack_item"] = item
        # Word of Command pauses mid-resolution for the caster's card choice
        # (CR 608.2: the spell is still resolving). Keep it on the stack until
        # confirm_word_of_command finishes the resolution and removes it.
        woc_after = self.pending_word_of_command
        if woc_after is not None and woc_after is not woc_before and "_stack_item" not in woc_after:
            self.stack.append(item)
            woc_after["_stack_item"] = item
        return True
    def _run_stack_item_resolution(self, item: StackItem) -> None:
        # A triggered ability with a name-keyed resolve-time hook (Rod/Cup/Sphere,
        # Verduran Enchantress, Guardian Angel deferred onto the stack).
        if item.hook_key is not None:
            from ...card_hooks import TRIGGER_HOOKS

            handler = TRIGGER_HOOKS.get(item.hook_key)
            if handler is not None:
                handler(self, item)
                self.log.append(f"{item.card.name} ability resolved")
            return
        if item.ability_instruction is not None:
            caster = self.players[item.caster_index]
            target_idx = item.target_player_index if item.target_player_index is not None else (1 - item.caster_index)
            target = self.players[target_idx]
            state_machine = OracleStateMachine(
                self,
                OracleExecutionContext(
                    caster=caster,
                    target=target,
                    card=item.card,
                    target_permanent_index=item.target_permanent_index,
                    x_value=item.x_value,
                    source_permanent=item.source_permanent,
                    stack_target=item.target_stack_item,
                    trigger_context=item.trigger_context,
                    choices=item.choices,
                ),
            )
            supported, details = state_machine.run(item.ability_instruction)
            if supported:
                self.log.append(f"{item.card.name} ability resolved")
            else:
                self.log.append(f"{item.card.name} ability fizzled: {details}")
            return

        # A copy of an instant/sorcery (Fork) resolves like the original but is a
        # token spell: it ceases to exist afterward (no graveyard) and was never
        # cast, so it skips the cast/graveyard bookkeeping in _resolve_card.
        if item.is_copy and item.card.primary_type in ("instant", "sorcery"):
            caster = self.players[item.caster_index]
            target_idx = item.target_player_index if item.target_player_index is not None else (1 - item.caster_index)
            target = self.players[target_idx] if 0 <= target_idx < len(self.players) else caster
            self._apply_spell_text(
                caster,
                target,
                item.card,
                target_permanent_index=item.target_permanent_index,
                x_value=item.x_value,
                new_color=item.choices.get("new_color"),
                stack_target=item.target_stack_item,
                mode_index=item.chosen_mode_index,
                old_color=item.choices.get("old_color"),
            )
            self.log.append(f"{item.card.name} (copy) resolved")
            return

        classification = classify_card(item.card)
        self._resolve_card(
            caster_index=item.caster_index,
            card=item.card,
            classification=classification,
            target_player_index=item.target_player_index,
            target_permanent_index=item.target_permanent_index,
            x_value=item.x_value,
            new_color=item.choices.get("new_color"),
            stack_target=item.target_stack_item,
            chosen_mode_index=item.chosen_mode_index,
            old_color=item.choices.get("old_color"),
            divided_targets=item.choices.get("divided_targets"),
        )
        return
    def _resolve_card(
        self,
        caster_index: int,
        card: CardDefinition,
        classification: CardClassification,
        target_player_index: int | None,
        target_permanent_index: int | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        stack_target=None,
        chosen_mode_index: int | None = None,
        old_color: str | None = None,
        divided_targets: list[tuple[int, int | None]] | None = None,
    ) -> None:
        caster = self.players[caster_index]
        primary_type = card.primary_type

        if primary_type in {"land", "creature", "artifact", "enchantment"}:
            permanent = Permanent(card=card)
            if x_value is not None:
                permanent.metadata["cast_x_value"] = x_value
            # A "copy as it enters" permanent (Clone) records the chosen copy
            # target so initialization can copy the player-selected creature
            # rather than an arbitrary one.
            if target_permanent_index is not None:
                permanent.metadata["copy_target"] = (
                    target_player_index if target_player_index is not None else caster_index,
                    target_permanent_index,
                )
            self._put_permanent_onto_battlefield(caster_index, permanent, target_player_index)
            self.log.append(f"{caster.name} put {card.name} onto battlefield")
            self._apply_global_buff(caster, card)
            # Auras resolve their own "when this Aura enters" text through
            # _apply_aura_effect's bespoke matching (Animate Dead, Earthbind) —
            # skip the generic ETB-trigger path for them to avoid firing twice.
            if "Aura" not in card.type_line:
                self._apply_self_enters_battlefield_triggers(
                    caster_index, permanent, target_player_index, target_permanent_index
                )
            self._apply_aura_effect(caster_index, permanent, target_player_index, target_permanent_index)
            # An Aura that failed to attach (its target left the battlefield while the
            # spell was on the stack) goes to its owner's graveyard instead of
            # remaining on the battlefield unattached (MTG Rule 303.4g)
            if (
                "Aura" in card.type_line
                and card.oracle_text.lower().split("\n")[0].strip().startswith("enchant")
                and permanent.metadata.get("attached_to") is None
            ):
                for player in self.players:
                    if permanent in player.battlefield:
                        player.battlefield.remove(permanent)
                        break
                caster.graveyard.append(card)
                self.log.append(f"{card.name} had no legal target and was put into {caster.name}'s graveyard")
                self._refresh_dynamic_creatures()
                return
            self._refresh_dynamic_creatures()
            if primary_type == "land":
                if self.enforce_mana_costs:
                    self.lands_played_this_turn[caster_index] = self.lands_played_this_turn.get(caster_index, 0) + 1
                    if self.lands_played_this_turn.get(caster_index, 0) > 1:
                        fastbond_count = self._fastbond_count(caster_index)
                        if fastbond_count > 0:
                            damage = self._deal_damage_to_player(caster, fastbond_count)
                            self.log.append(f"Fastbond dealt {damage} damage to {caster.name}")
                self._process_land_enters(caster_index)
            return

        # Sorceries and instants resolve immediately in this basic engine.
        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        target = self.players[target_idx]

        self._apply_spell_text(
            caster,
            target,
            card,
            target_permanent_index=target_permanent_index,
            x_value=x_value,
            new_color=new_color,
            stack_target=stack_target,
            mode_index=chosen_mode_index,
            old_color=old_color,
            divided_targets=divided_targets,
        )
        self._apply_self_resolved_hook(caster_index, card, target_idx, target_permanent_index)
        pending_woc = self.pending_word_of_command
        if (
            pending_woc is not None
            and "_spell_card" not in pending_woc
            and pending_woc.get("card_name") == card.name
        ):
            # Word of Command is still resolving while the caster chooses a card
            # from the target's hand; it goes to the graveyard only when
            # confirm_word_of_command finishes the resolution.
            pending_woc["_spell_card"] = card
            pending_woc["_spell_caster_index"] = caster_index
            return
        caster.graveyard.append(card)
        self.log.append(f"{card.name} resolved and moved to graveyard")
    def _apply_self_enters_battlefield_triggers(
        self,
        controller_index: int,
        permanent: Permanent,
        target_player_index: int | None,
        target_permanent_index: int | None,
    ) -> None:
        """Fire a just-entered permanent's own "when this enters the
        battlefield" triggered abilities (e.g. Oubliette). This engine doesn't
        model a separate priority window for choosing the trigger's own
        target, so the caster's cast-time target choice is reused directly —
        the same convention an Aura's enchant target already follows."""
        program = compile_card_oracle(permanent.card)
        for trig in program.triggered_abilities:
            if trig.condition.kind != "enters_battlefield" or not trig.supported or trig.instruction is None:
                continue
            caster = self.players[controller_index]
            target_idx = target_player_index if target_player_index is not None else controller_index
            if not (0 <= target_idx < len(self.players)):
                target_idx = controller_index
            target = self.players[target_idx]
            context = OracleExecutionContext(
                caster=caster,
                target=target,
                card=permanent.card,
                target_permanent_index=target_permanent_index,
                source_permanent=permanent,
            )
            self._execute_oracle_instruction(trig.instruction, context)
    def _select_executable_instruction(
        self, card: CardDefinition, mode_index: int | None = None
    ) -> OracleInstruction | None:
        program = compile_card_oracle(card)
        # A modal spell resolves the player's chosen mode; fall back to the first
        # instruction (mode 0) when no mode was chosen (e.g. AI casts).
        if mode_index is not None and program.modes and 0 <= mode_index < len(program.modes):
            mode = program.modes[mode_index]
            if mode.instruction is not None:
                return mode.instruction
        return next((instruction for instruction in program.instructions if instruction.kind != "spell_pattern"), None)
