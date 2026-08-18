"""Resolving the top of the stack (CR 608), and putting triggered abilities
onto it (CR 603).

The other end of the pipeline: whatever ``casting`` and ``activation`` queued
comes back here to be executed, its targets re-checked for legality
(CR 608.2b — a spell whose every target is illegal is countered), and its card
put wherever it goes afterwards.
"""

from __future__ import annotations

from contextlib import contextmanager

from ...auras import aura_enchant_clause
from ...classifier import CardClassification, classify_card
from ...game_types import OracleExecutionContext, OracleStateMachine, StackItem
from ...handlers.control_flow import evaluate_condition
from ...models import CardDefinition, Permanent
from ...oracle import OracleInstruction, compile_card_oracle
from ...resumption import run_resumable

class StackResolutionMixin:
    def _bin_spell_card(
        self, owner, card: CardDefinition, *, exile_instead: bool, verb: str
    ) -> None:
        """Where a spell's card goes as it leaves the stack (CR 608.2n): the
        owner's graveyard, unless the cast carried the "if that spell would be
        put into your graveyard, exile it instead" rider — which covers
        resolving and being countered alike, so every leave-the-stack site
        routes through here rather than deciding for itself."""
        if exile_instead:
            owner.exile.append(card)
            self.log.append(f"{card.name} {verb} and was exiled instead of going to the graveyard")
        else:
            owner.graveyard.append(card)
            self.log.append(f"{card.name} {verb} and moved to graveyard")

    def _default_opposing_seat(self, caster_index: int) -> int:
        """The seat a triggered ability affects when nothing chose one.

        This engine picks a trigger's target at its fire site or not at all — a
        standing approximation of CR 603.3d, which chooses it as the ability
        goes on the stack. Where nothing chose, the ability still has to resolve
        against *someone*, and that someone was ``1 - caster_index``: right for
        two players, and at seat 2 of a three-handed game ``players[-1]``, which
        is the caster itself. A player is never their own opponent (CR 102.3),
        so Vito would have drained himself.

        The first living opponent in seat order instead. The old answer is kept
        as the fallback for a table with no living opponent left, so nothing
        that reaches here mid-teardown changes.
        """
        opponents = self.opponents_of(caster_index)
        if opponents:
            return opponents[0]
        fallback = 1 - caster_index
        return fallback if 0 <= fallback < len(self.players) else caster_index

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
        # A trigger that acts on the object its event was about ("destroy that
        # planeswalker") is stamped with that object's id by the fire site. The
        # index is unstable across a removal; the id is the identity (CR 400.7).
        target_permanent_id: int | None = None,
        trigger_context: dict | None = None,
        hook_key: str | None = None,
        hook_event: dict | None = None,
    ) -> None:
        """Put a single triggered ability onto the stack as a StackItem (CR 603.3).

        Mirrors the attack/block trigger model (declare_attackers_step._fire_attack_triggers).
        The trigger resolves later through resolve_top_of_stack — never inline at the
        moment it fires. ``card`` defaults to the source permanent's card (used as the
        stack object's display name).

        Mid-cast, it is *held* instead — see ``deferring_triggers``. The check
        belongs on this end rather than on the batch above it because the batch
        is not the only fire site: a dies-trigger enqueues from
        ``_permanent_to_graveyard`` one ability at a time, and a creature
        sacrificed to pay a cost dies exactly there."""
        if self.deferred_triggers is not None:
            self.deferred_triggers.append(dict(
                controller_index=controller_index,
                source_permanent=source_permanent,
                card=card,
                instruction=instruction,
                effect_kind=effect_kind,
                ability_text=ability_text,
                target_player_index=target_player_index,
                target_permanent_index=target_permanent_index,
                target_permanent_id=target_permanent_id,
                trigger_context=trigger_context,
                hook_key=hook_key,
                hook_event=hook_event,
            ))
            return
        stack_card = card if card is not None else (source_permanent.card if source_permanent is not None else None)
        if stack_card is None:
            return
        self._stack_push(
            StackItem(
                card=stack_card,
                caster_index=controller_index,
                target_player_index=target_player_index,
                target_permanent_index=target_permanent_index,
                target_permanent_id=target_permanent_id,
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

    @contextmanager
    def deferring_triggers(self):
        """Hold triggers fired inside this block until the block ends.

        CR 601.2a puts a spell on the stack **first** and CR 601.2h pays its
        costs afterwards; CR 602.2a/602.2b say the same of an activated ability.
        A trigger that fires while a cost is being paid therefore belongs
        *above* the object being cast — and CR 601.2c's parenthetical spells out
        the mechanism: such abilities "wait to be put on the stack until the
        spell has finished being cast".

        This engine pays first and pushes second, because a payment that cannot
        be made has to leave nothing behind — the rewind CR 601.2 describes,
        done by never having built the stack item. That inverted the order for
        every trigger a cost fires. Holding them here restores it without
        touching the rewind: the buffer is flushed after the push, so the
        observable sequence is the rule's, whatever the internal order was.

        Nothing in the pool could see this until the sacrifice seam gave
        "whenever you sacrifice a permanent" a fire site — Havoc Jester's ping
        resolved *after* Witch's Cauldron's draw, and after Village Rites'.

        Re-entrant by design: an inner block joins the outer buffer rather than
        starting a second one, so a nested announcement still flushes exactly
        once, at the point the outermost object is on the stack.
        """
        if self.deferred_triggers is not None:
            yield
            return
        self.deferred_triggers = []
        try:
            yield
        finally:
            held, self.deferred_triggers = self.deferred_triggers, None
            for event in held:
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
        waiting_woc = self.pending_choice_of("word_of_command")
        if waiting_woc is not None and waiting_woc.data.get("_stack_item") is self.stack[-1]:
            if "chosen_hand_index" not in waiting_woc.data:
                return False
            self.discard_pending_choice(waiting_woc)
            self._finish_word_of_command(
                waiting_woc.data, waiting_woc.data["chosen_hand_index"],
                auto_resolve_forced=False, caster_index=waiting_woc.player_index,
            )
            return True

        item = self.stack.pop()
        pays_before = len(self.pending_choices_of("optional_pay"))
        woc_before = self.pending_choice_of("word_of_command")
        self._run_stack_item_resolution(item)
        # Power Sink armed a pending "pay {X} or be countered" for the targeted
        # spell's controller. On the human priority path leave it for the prompt;
        # headless/AI resolves it deterministically (pay if able, else countered).
        payment = self.pending_choice_of("mana_payment")
        if payment is not None and payment.data.get("_new"):
            payment.data.pop("_new", None)
            if not pause_for_choices:
                self._auto_resolve_mana_payment()
        new_pays = self.pending_choices_of("optional_pay")[pays_before:]
        if pause_for_choices and new_pays:
            # The ability raised an optional pay/draw choice — keep it on the stack
            # until the choice is submitted (the only effect so far is registering the
            # prompt; the life gain / draw happens on confirm). Link each new prompt
            # entry to this stack item so confirming it removes the ability.
            self.stack.append(item)
            for pay in new_pays:
                pay.data["_stack_item"] = item
        # Word of Command pauses mid-resolution for the caster's card choice
        # (CR 608.2: the spell is still resolving). Keep it on the stack until
        # confirm_word_of_command finishes the resolution and removes it.
        woc_after = self.pending_choice_of("word_of_command")
        if (
            woc_after is not None
            and woc_after is not woc_before
            and "_stack_item" not in woc_after.data
        ):
            self.stack.append(item)
            woc_after.data["_stack_item"] = item
        return True
    def _run_stack_item_resolution(self, item: StackItem) -> None:
        # **An index is not an identity** (ROADMAP idiom #11) and a graveyard is
        # the zone with no identity to fall back on, so what ``_stack_push``
        # stamped is turned back into a slot *here* — once, at the top, so every
        # reader below (a spell, an ability, an Aura's reanimation, an
        # enters-the-battlefield trigger) sees a live index without knowing this
        # happened. The stamp itself is never overwritten: an item pushed back
        # on for a pending choice re-locates from the same name next time.
        if item.target_graveyard_card is not None:
            item.target_permanent_index = self.chosen_graveyard_index(
                item.target_graveyard_card, item.target_permanent_index
            )
            # And which pile the slot counts into. For a graveyard target that
            # *is* what `target_player_index` means, and leaving it to be
            # re-derived below is how the two halves of one choice came apart:
            # every reader defaults it differently (`1 - caster` here, the
            # caster there), so a spell was validated against one graveyard and
            # resolved against another.
            first = (
                item.target_graveyard_card[0]
                if isinstance(item.target_graveyard_card, list)
                else item.target_graveyard_card
            )
            if first is not None:
                item.target_player_index = first.seat
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
            target_idx = (
                item.target_player_index
                if item.target_player_index is not None
                else self._default_opposing_seat(item.caster_index)
            )
            target = self.players[target_idx]
            context = OracleExecutionContext(
                caster=caster,
                target=target,
                card=item.card,
                target_permanent_index=item.target_permanent_index,
                target_permanent_id=item.target_permanent_id,
                x_value=item.x_value,
                source_permanent=item.source_permanent,
                stack_target=item.target_stack_item,
                trigger_context=item.trigger_context,
                choices=item.choices,
            )
            # CR 603.4: an intervening-if is checked *again* as the ability
            # resolves, and the ability does nothing if it is false. The grammar
            # has lowered that condition onto the payload since it learned to
            # parse one and nothing read it — so a conditional trigger would
            # have fired unconditionally, which is the silent wrongness the
            # compiler comment claims to have fixed one layer earlier. This is
            # the read. No card in the shipped pool produces the key (the
            # conditional triggers there are gated at their fire site instead),
            # so nothing changes behaviour today; it is armed for the first card
            # that needs it.
            gate = (item.ability_instruction.payload or {}).get("intervening_if")
            if gate is not None and not evaluate_condition(self, context, gate):
                self.log.append(
                    f"{item.card.name} ability did nothing: its condition is no longer true"
                )
                return
            state_machine = OracleStateMachine(self, context)
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
                target_permanent_id=item.target_permanent_id,
                x_value=item.x_value,
                new_color=item.choices.get("new_color"),
                stack_target=item.target_stack_item,
                mode_index=item.chosen_mode_index,
                old_color=item.choices.get("old_color"),
                choices=item.choices,
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
            target_permanent_id=item.target_permanent_id,
            x_value=item.x_value,
            new_color=item.choices.get("new_color"),
            stack_target=item.target_stack_item,
            chosen_mode_index=item.chosen_mode_index,
            old_color=item.choices.get("old_color"),
            divided_targets=item.choices.get("divided_targets"),
            exile_instead_of_graveyard=item.exile_instead_of_graveyard,
            cast_from_zone=item.cast_from_zone,
            choices=item.choices,
        )
        return
    def _resolve_card(
        self,
        caster_index: int,
        card: CardDefinition,
        classification: CardClassification,
        target_player_index: int | None,
        target_permanent_index: int | None = None,
        target_permanent_id: int | list[int | None] | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        stack_target=None,
        chosen_mode_index: int | None = None,
        old_color: str | None = None,
        divided_targets: list[tuple[int, int | None]] | None = None,
        exile_instead_of_graveyard: bool = False,
        cast_from_zone: str = "hand",
        choices: dict | None = None,
    ) -> None:
        caster = self.players[caster_index]
        primary_type = card.primary_type

        if primary_type in {"land", "creature", "artifact", "enchantment", "planeswalker"}:
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
            # The one entry site in the engine that *is* a cast (CR 701.5a):
            # a permanent spell resolving. Every other path puts a permanent
            # onto the battlefield without casting it, which is what
            # Containment Priest reads.
            # "…or you cast it **from your graveyard**" (Archfiend's Vessel).
            # The zone the spell was cast from, which for a permanent spell is
            # also the zone the permanent came from — one call, two records,
            # because a later card may ask either question and they are not the
            # same one: a reanimation stamps the first and not the second.
            permanent.metadata["cast_from_zone"] = cast_from_zone
            self._put_permanent_onto_battlefield(
                caster_index, permanent, target_player_index,
                was_cast=True, from_zone=cast_from_zone,
            )
            self.log.append(f"{caster.name} put {card.name} onto battlefield")
            self._apply_global_buff(caster, card)
            is_aura = "Aura" in card.type_line
            if not is_aura:
                self._apply_self_enters_battlefield_triggers(
                    caster_index, permanent, target_player_index,
                    target_permanent_index, target_permanent_id,
                )
            ran_entry_text = self._apply_aura_effect(
                caster_index,
                permanent,
                target_player_index,
                target_permanent_index,
                target_permanent_id,
            )
            # An Aura's own "when this Aura enters" trigger, for every Aura whose
            # entry text `_apply_aura_effect` did *not* perform itself.
            #
            # This used to be skipped for all of them, on the strength of the two
            # it does perform bespokely (Animate Dead's reanimation, Earthbind's
            # conditional damage) — so an Aura whose entry trigger compiled to an
            # ordinary instruction did nothing at all while reporting supported.
            # Three cards were in that state.
            #
            # After the attach rather than before it, which is the order the rest
            # of the engine already keeps: "when this Aura enters, tap enchanted
            # creature" has nothing to tap until the Aura is attached.
            if is_aura and not ran_entry_text:
                self._apply_self_enters_battlefield_triggers(
                    caster_index, permanent, target_player_index,
                    target_permanent_index, target_permanent_id,
                )
            # An Aura that failed to attach (its target left the battlefield while the
            # spell was on the stack) goes to its owner's graveyard instead of
            # remaining on the battlefield unattached (MTG Rule 303.4g)
            if (
                "Aura" in card.type_line
                and aura_enchant_clause(card.oracle_text) is not None
                and permanent.metadata.get("attached_to") is None
            ):
                holder = self.controller_index_of(permanent)
                if holder is not None:
                    self.remove_from_battlefield(permanent)
                caster.graveyard.append(card)
                self.log.append(f"{card.name} had no legal target and was put into {caster.name}'s graveyard")
                self._refresh_dynamic_creatures()
                return
            self._refresh_dynamic_creatures()
            if primary_type == "land":
                if self.enforce_mana_costs:
                    self.lands_played_this_turn[caster_index] = self.lands_played_this_turn.get(caster_index, 0) + 1
                    if self.lands_played_this_turn.get(caster_index, 0) > 1:
                        # "…if it wasn't the first land you played this turn,
                        # ~ deals N damage to you". The rider is read off each
                        # source's own text alongside the allowance it came
                        # with, so the sources name themselves in the log
                        # instead of the engine naming one of them.
                        sources = [
                            (permanent, allowance)
                            for permanent, allowance in self._land_play_allowances(caster_index)
                            if allowance.damage_per_extra_land
                        ]
                        if sources:
                            total = sum(a.damage_per_extra_land for _, a in sources)
                            names = ", ".join(
                                dict.fromkeys(permanent.card.name for permanent, _ in sources)
                            )
                            self._deal_damage_to_player(
                                caster, total,
                                then=lambda damage: self.log.append(
                                    f"{names} dealt {damage} damage to {caster.name}"
                                ),
                            )
                self._process_land_enters(caster_index)
            return

        # Sorceries and instants resolve immediately in this basic engine.
        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        target = self.players[target_idx]

        def apply_text() -> None:
            self._apply_spell_text(
                caster,
                target,
                card,
                target_permanent_index=target_permanent_index,
                target_permanent_id=target_permanent_id,
                x_value=x_value,
                new_color=new_color,
                stack_target=stack_target,
                mode_index=chosen_mode_index,
                old_color=old_color,
                divided_targets=divided_targets,
                cast_from_zone=cast_from_zone,
                choices=choices,
            )

        def finish() -> None:
            self._apply_self_resolved_hook(caster_index, card, target_idx, target_permanent_index)
            pending_woc = self.pending_choice_of("word_of_command")
            if (
                pending_woc is not None
                and "_spell_card" not in pending_woc.data
                and pending_woc.data.get("card_name") == card.name
            ):
                # Word of Command is still resolving while the caster chooses a
                # card from the target's hand; it goes to the graveyard only when
                # confirm_word_of_command finishes the resolution.
                pending_woc.data["_spell_card"] = card
                pending_woc.data["_spell_caster_index"] = caster_index
                pending_woc.data["_spell_exile_instead"] = exile_instead_of_graveyard
                return
            # CR 724.1b: "End the turn" exiles every object on the stack
            # *including the object that's resolving*. That object was popped
            # before its handler ran, so the process flags it here instead of
            # reaching back into a list it is no longer in.
            ends_turn = getattr(self, "exile_resolving_spell", False)
            self.exile_resolving_spell = False
            self._bin_spell_card(
                caster, card,
                exile_instead=exile_instead_of_graveyard or ends_turn,
                verb="resolved",
            )

        # CR 608.2n puts the card into the graveyard as the *last* part of
        # resolution, which matters once a spell's effect can stop to ask the
        # player something: finishing here regardless would bin the card while
        # its damage was still waiting on an answer. Word of Command already
        # needed the same care for its own reason, and is the reason `finish`
        # was a separable step to begin with.
        run_resumable(self, [apply_text, finish], lambda step: step())
    def _apply_self_enters_battlefield_triggers(
        self,
        controller_index: int,
        permanent: Permanent,
        target_player_index: int | None,
        target_permanent_index: int | None,
        target_permanent_id: int | list[int | None] | None = None,
    ) -> None:
        """Fire a just-entered permanent's own "when this enters the
        battlefield" triggered abilities (e.g. Oubliette). This engine doesn't
        model a separate priority window for choosing the trigger's own
        target, so the caster's cast-time target choice is reused directly —
        the same convention an Aura's enchant target already follows.

        The id travels with the index because an index is unstable: anything
        leaving the battlefield renumbers every later slot, so a trigger that
        picked slot 2 at cast time and resolves after something died in response
        hits whichever permanent slid into that slot. This context was built
        without the id, so every targeting ETB trigger in the pool resolved by
        index alone — Oubliette among them. ``chosen_permanent`` prefers the id
        and only falls back to the index when there is none."""
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
                target_permanent_id=target_permanent_id,
                source_permanent=permanent,
            )
            # CR 603.4: an intervening-if gates the trigger. This inline path
            # is both fire and resolution for an ETB trigger, so the one read
            # here is the same check the stack path makes at line ~223 —
            # without it, Turret Ogre would ping with no big creature in play.
            gate = (trig.instruction.payload or {}).get("intervening_if")
            if gate is not None and not evaluate_condition(self, context, gate):
                self.log.append(
                    f"{permanent.card.name}'s trigger did nothing: its condition is not met"
                )
                continue
            self._execute_oracle_instruction(trig.instruction, context)
    def _select_executable_instruction(
        self, card: CardDefinition, mode_index: int | None = None
    ) -> OracleInstruction | None:
        """What the stack runs for one spell — **all** of its effect lines, in
        the order written (CR 608.2c).

        This took the *first* non-``spell_pattern`` instruction and stopped,
        which is only ever right by accident. A card that prints its clauses on
        one line already compiles to a single ``sequence``; a card that prints
        them on two gets one instruction per line
        (``oracle._noncreature_line_instructions``), and every line after the
        first was silently dropped. Opt scried and never drew, Revitalize gained
        life and never drew — supported cards playing as a strictly smaller card,
        which is the first standing invariant. It survived because no shipped
        instant or sorcery has two effect lines.

        Fusing here rather than in the compiler is deliberate: for a *permanent*
        that same list is a mirror of everything the card does, scanned by kind
        by the layer bridge and the AI, and fusing it would make the mirror
        unreadable. Only an instant or sorcery reaches this function, and only
        for it is the list a program.

        Composing through ``sequence`` also buys the resumption behaviour for
        free — a step that stops to ask (a scry, a search) takes the steps behind
        it with it, which is exactly what "Scry 1. Draw a card." needs.
        """
        program = compile_card_oracle(card)
        # A modal spell resolves the player's chosen mode; fall back to the first
        # instruction (mode 0) when no mode was chosen (e.g. AI casts).
        if mode_index is not None and program.modes and 0 <= mode_index < len(program.modes):
            mode = program.modes[mode_index]
            if mode.instruction is not None:
                return mode.instruction
        # ``spell_pattern`` is a marker recording that a whitelist substring
        # matched, not an effect; everything else in an instant's list is one.
        steps = tuple(
            instruction for instruction in program.instructions
            if instruction.kind != "spell_pattern"
        )
        if not steps:
            return None
        if len(steps) == 1:
            return steps[0]
        return OracleInstruction("sequence", "", {"steps": steps})
