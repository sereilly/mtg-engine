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
from ...extra_triggers import additional_triggers
from ...game_types import OracleExecutionContext, OracleStateMachine, StackItem
from ...handlers.control_flow import evaluate_condition
from ...models import CardDefinition, Permanent
from ...oracle import OracleInstruction, compile_card_oracle
from ...modal_triggers import INLINE_TRIGGER_CONDITIONS, modal_trigger_modes
from ...resumption import run_resumable

#: How a printed controller narrowing reaches the target spec. A key here is a
#: narrowing `legality._enumerate_targets` performs; a controller word absent
#: from it is one the enumerator cannot answer, and
#: `_choose_trigger_targets` declines rather than offering a wider list than
#: the card prints.
_CONTROLLER_SPEC_FLAGS = {
    "you": "own_only",
    "opponent": "opponent_only",
    "defending_player": "defending_player_only",
}


def _target_filter_controller(payload) -> str | None:
    """The ``controller`` word of an instruction's printed target phrase.

    Walked rather than read off one key because the phrase is carried in two
    shapes: a destroy lifts it to the payload's top level, while a damage
    instruction keeps it under ``targets.filter`` — and a ``may`` or a
    ``sequence`` wraps either of them. One walk rather than a list of the
    kinds, for the reason every registry in this engine gives.
    """
    if isinstance(payload, dict):
        described = payload.get("filter")
        if isinstance(described, dict) and described.get("controller"):
            return described["controller"]
        if payload.get("controller"):
            return payload["controller"]
        for value in payload.values():
            found = _target_filter_controller(value)
            if found is not None:
                return found
        return None
    if isinstance(payload, (list, tuple)):
        for entry in payload:
            found = _target_filter_controller(entry)
            if found is not None:
                return found
        return None
    inner = getattr(payload, "payload", None)
    return None if inner is None else _target_filter_controller(inner)


def _controller_narrowing_is_in(spec: dict, instruction) -> bool:
    """Whether *spec* carries the controller narrowing *instruction* prints."""
    controller = _target_filter_controller(getattr(instruction, "payload", None))
    if controller is None:
        return True
    flag = _CONTROLLER_SPEC_FLAGS.get(controller)
    return bool(flag and spec.get(flag))


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
        # CR 603.2d: "rather than simply determining that such an ability has
        # triggered, determine how many times it should trigger, then that
        # ability triggers that many times" (Sanctum of All). Counted here
        # because this is the moment an ability triggers — one site, so a fire
        # site added later is covered by construction, and counting once rather
        # than recursing is what the rule's "doesn't invoke itself repeatedly"
        # asks for. Each instance is its own stack object and so chooses its own
        # targets; it is not a copy (CR 707), which would inherit them.
        for _ in range(1 + additional_triggers(
            self, source_permanent, controller_index,
            delayed=effect_kind == "triggered_delayed",
        )):
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

    def _choose_trigger_mode(
        self, item: StackItem, *, targets_already_chosen: bool = False
    ) -> None:
        """Choose *item*'s mode and that mode's targets, as it goes on the
        stack (CR 700.2b / CR 603.3c-d).

        The rule is explicit about **when**: the modes of a modal triggered
        ability are chosen "as part of putting that ability on the stack", and
        CR 603.3d then routes the rest through CR 601.2c, which is where the
        targets are chosen. So the two decisions are one decision, made here,
        at the one moment they are allowed — and not, as this engine did until
        now, at resolution, where nothing collects a target and a targeted mode
        would run against a target nobody picked.

        CR 700.2b's other half is the empty case: "If no mode is chosen, the
        ability is removed from the stack." A mode with no legal target can't
        be chosen, so an ability whose every mode is in that state never
        resolves — it is taken back off the stack here rather than resolving
        into a no-op, which is a different observable game state (nothing
        responds to it, and nothing counts it as having resolved).

        The offered list is ``legality.trigger_mode_options``, which is also
        what decides the empty case one line above: the gate and the picker are
        one call, not two tables.
        """
        instruction = item.ability_instruction
        if not modal_trigger_modes(instruction):
            return
        options = self.trigger_mode_options(
            item.caster_index, item.card, instruction, item.source_permanent,
        )
        if not options:
            self.stack = [existing for existing in self.stack if existing is not item]
            self.log.append(
                f"{item.card.name}'s triggered ability was removed from the stack: "
                "no mode could be chosen (700.2b)"
            )
            return
        self.arm_pending_choice(
            "mode_choice", item.caster_index,
            card_name=item.card.name,
            labels=[option["label"] for option in options],
            _options=tuple(options),
            _trigger_item=item,
            # An **activated** modal ability chose its targets when it was
            # activated (CR 602.2b), so the mode picker must keep them.
            # Dwarven Armorer is the card that shows why: "Put a +0/+1 counter
            # or a +1/+0 counter on target creature" is one target shared by
            # both modes, named at activation — and choosing again handed the
            # counter to whichever creature the default picker found first,
            # which was the Armorer itself. Same rule as the twin flag one
            # method up: asking again replaces a choice a player has made with
            # one they have not.
            _keep_targets=targets_already_chosen,
        )

    #: Target kinds :meth:`_choose_trigger_targets` picks for. Objects on the
    #: battlefield only, and deliberately: those are the kinds whose printed
    #: noun phrase can *narrow* ("target artifact defending player controls"),
    #: so a fire site that names one by position rather than by choice is
    #: naming something the card may not permit. A player, a spell on the
    #: stack and a card in a zone reach the resolution through their own paths
    #: and are left exactly as they were.
    _CHOOSABLE_TRIGGER_TARGET_KINDS = frozenset({
        "permanent", "creature", "artifact", "enchantment", "land",
        "planeswalker",
    })

    def _choose_trigger_targets(self, item: StackItem) -> None:
        """Choose *item*'s target as it goes on the stack (CR 603.3d/601.2c).

        The non-modal twin of :meth:`_choose_trigger_mode`, and it exists for
        the same reason at the same moment: a triggered ability chooses its
        targets as it is put on the stack, not when it resolves.

        Most fire sites in this engine already name the object their event was
        about — "destroy **that Wall**" (Battering Ram) is bound by the block
        that fired it, and CR 603.3d has nothing to choose. This is for the
        ability whose printed noun phrase is a *choice* the event does not
        make: Floral Spuzzem's "target artifact defending player controls" is
        any of the defender's artifacts, and the fire site had been stamping
        the attacking creature's own slot into the target field — so the
        ability resolved against whatever permanent sat at that index on the
        *controller's* battlefield.

        Three ways out, all of them the safe direction:

        * the ability names no object target — nothing to choose;
        * the fire site already bound one (``target_permanent_id``) — the event
          made the choice and CR 603.3d has none left to make;
        * no legal target exists — CR 603.3c removes the ability from the
          stack rather than resolving it into a no-op, which is the same rule
          :meth:`_choose_trigger_mode` applies to a mode that cannot be chosen.

        The candidates come from ``_enumerate_targets``, the one list the web
        picker is handed and the one list the answer is checked against.
        """
        from ...targeting import derive_instruction_spec

        instruction = item.ability_instruction
        if instruction is None or modal_trigger_modes(instruction):
            return
        if item.target_permanent_id is not None or item.target_stack_item is not None:
            return
        spec = derive_instruction_spec([instruction])
        if spec is None or spec.get("kind") not in self._CHOOSABLE_TRIGGER_TARGET_KINDS:
            return
        # **Only pick what the enumerator can narrow.** A printed noun phrase's
        # controller reaches the spec as a flag ("you control" → `own_only`,
        # "an opponent controls" → `opponent_only`, "defending player controls"
        # → `defending_player_only`); one that did not is one the enumerator
        # would ignore, and offering a wider list than the card prints is the
        # single thing a picker must never do.
        #
        # "…that **that player** controls" (Chandra's Incinerator) is that
        # case, and deliberately so: the seat is one the *event* picked, known
        # only to the handler holding the trigger's context, which does the
        # narrowing itself as it resolves. Left to this picker it would offer
        # every permanent on the board and stamp the first.
        if not _controller_narrowing_is_in(spec, instruction):
            return
        spec = dict(spec)
        # "Defending player controls" is a seat the *combat* knows and the
        # enumerator does not, so it travels with the spec. The fire site froze
        # it into the trigger's context when the ability triggered (CR 603.10),
        # which is the same key the attack triggers already use.
        defending = (item.trigger_context or {}).get("trigger_defending_player_index")
        if isinstance(defending, int):
            spec["defending_player_index"] = defending
        candidates = self._enumerate_targets(
            item.caster_index, item.card, spec, for_cast=False,
            ability_instruction=instruction,
            source_permanent=item.source_permanent,
            ability_source=item.source_permanent,
        )
        offered = []
        for candidate in candidates:
            if candidate.get("kind") != "permanent":
                continue
            perm = self.permanent_at(candidate["seat"], candidate["index"])
            if perm is None:
                continue
            offered.append({
                "seat": candidate["seat"],
                "permanent_index": candidate["index"],
                "permanent_id": perm.permanent_id,
                "name": perm.card.name,
            })
        if not offered:
            self.stack = [existing for existing in self.stack if existing is not item]
            self.log.append(
                f"{item.card.name}'s triggered ability was removed from the stack: "
                "it has no legal target (603.3c)"
            )
            return
        self.arm_pending_choice(
            "trigger_target", item.caster_index,
            card_name=item.card.name,
            targets=offered,
            _trigger_item=item,
        )

    def _default_trigger_mode_target(self, option: dict, controller_index: int) -> dict | None:
        """Which candidate a non-interactive seat takes for *option*.

        A stated policy, like the "first printed mode" beside it, and derived
        rather than named: ``ai_valuation.activation_target_side`` reads the
        mode's own instruction kind through ``INSTRUCTION_CATEGORIES`` and says
        whether an effect of that family wants an opponent's side or its own.
        A family with no answer falls back to the first candidate offered,
        which is what every prompt in this engine does when nothing
        distinguishes the options.
        """
        from ...ai_valuation import activation_target_side

        candidates = option.get("valid_targets") or []
        if not candidates:
            return None
        side = activation_target_side(option["instruction"])
        if side is not None:
            opponents = set(self.opponents_of(controller_index))
            wanted = opponents if side == "opponent" else {controller_index}
            for candidate in candidates:
                if candidate.get("seat") in wanted:
                    return candidate
        return candidates[0]

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
    def resolve_stack(self, pause_for_choices: bool = False) -> None:
        while self.stack:
            if not self.resolve_top_of_stack(pause_for_choices=pause_for_choices):
                # The top item is paused on a decision somebody owes; it finishes
                # when the choice is confirmed.
                break
    def resolve_top_of_stack(self, pause_for_choices: bool = False) -> bool:
        """Resolve (and remove) the top stack object. Returns True if an object was
        resolved, False if the stack was empty or its top is mid-resolution.

        ``pause_for_choices`` is used by the human priority path (pass_priority).
        CR 608.2 — a resolution is not over until its last instruction is done —
        and CR 117.3b — nobody receives priority until then. So a resolution that
        stops to ask somebody something ("you may search your library …",
        Sanctum of All; "you may pay {2}", the colour Rods) keeps its object on
        the stack, with every prompt it armed recording that object
        (``_stack_item``, stamped in ``arm_pending_choice``). The object leaves
        through ``_release_stack_item`` when the last of those prompts is
        answered — and *only* then, because answering one prompt is how the next
        step of the same resolution arms its own.

        Headless/auto paths leave this False, so the object resolves and pops
        immediately and the caller drains the prompts deterministically,
        preserving seeded behaviour."""
        if not self.stack:
            return False
        top = self.stack[-1]
        # **A choice made as the object went on the stack, not yet answered.**
        # CR 601.2b-c and CR 603.3c-d put a modal trigger's mode and a targeted
        # ability's targets *before* the object is announced, so an object with
        # one of those still owed has not finished being put on the stack and
        # cannot resolve. Those prompts record the object as ``_trigger_item``
        # rather than ``_stack_item``, because nothing was resolving when they
        # were armed — which is exactly why the two checks below, which read
        # ``_stack_item``, never saw them.
        #
        # Only an interactive seat can ever be here: every announcement prompt
        # is registered ``default_at_arm``, so a headless or AI seat has already
        # answered by the time this runs and nothing waits.
        if self.announcement_choice_for(top) is not None:
            return False
        # A Word of Command paused mid-resolution stays on the stack until its
        # card choice is confirmed. Once the choice has been recorded (deferred
        # confirm), releasing priority lands here and finishes the resolution:
        # the forced card is played and the spell heads to the graveyard. The
        # forced spell is left on the stack on the interactive path
        # (pause_for_choices) so it gets its own priority round; headless loops
        # drain it on their next iteration. It is the one prompt that outlives
        # its own answer, which is why it finishes here rather than through the
        # generic release below.
        waiting_woc = self.pending_choice_of("word_of_command")
        if waiting_woc is not None and waiting_woc.data.get("_stack_item") is top:
            if "chosen_hand_index" not in waiting_woc.data:
                return False
            self.discard_pending_choice(waiting_woc)
            self._finish_word_of_command(
                waiting_woc.data, waiting_woc.data["chosen_hand_index"],
                auto_resolve_forced=False, caster_index=waiting_woc.player_index,
            )
            return True
        # Anything else that has already run its instructions is never run
        # again: it waits while it still owes somebody a decision, and otherwise
        # simply leaves. The second half is the backstop — an answer path that
        # returns without releasing the object strands it here, and re-resolving
        # it would apply the whole ability twice.
        if top.resolution_held:
            if self.stack_item_is_waiting(top):
                return False
            self._release_stack_item(top, force=True)
            return True

        item = self.stack.pop()
        woc_before = self.pending_choice_of("word_of_command")
        previous_resolving = self.resolving_stack_item
        self.resolving_stack_item = item if pause_for_choices else None
        # `resolving_items` is which *cast* is running (see Game), pushed here
        # for the same reason `resolving_seats` is pushed around an instruction:
        # this is the one place that knows, and everything below reaches the
        # damage paths with a bare CardDefinition that cannot say.
        self.resolving_items.append(item)
        try:
            self._run_stack_item_resolution(item)
        finally:
            self.resolving_items.pop()
            self.resolving_stack_item = previous_resolving
        # Power Sink armed a pending "pay {X} or be countered" for the targeted
        # spell's controller. On the human priority path leave it for the prompt;
        # headless/AI resolves it deterministically (pay if able, else countered).
        payment = self.pending_choice_of("mana_payment")
        if payment is not None and payment.data.get("_new"):
            payment.data.pop("_new", None)
            if not pause_for_choices:
                self._auto_resolve_mana_payment()
        # Still resolving: hold the object on the stack until every prompt it
        # armed has been answered.
        if self.choices_for_stack_item(item):
            item.resolution_held = True
            self.stack.append(item)
            return True
        # Word of Command pauses mid-resolution for the caster's card choice
        # (CR 608.2: the spell is still resolving). Keep it on the stack until
        # confirm_word_of_command finishes the resolution and removes it. The
        # headless path gets no stamp above, so this is where it is linked there.
        woc_after = self.pending_choice_of("word_of_command")
        if (
            woc_after is not None
            and woc_after is not woc_before
            and "_stack_item" not in woc_after.data
        ):
            self.stack.append(item)
            woc_after.data["_stack_item"] = item
        return True
    def _chosen_trigger_instruction(self, item: StackItem):
        """What a triggered ability actually runs — its chosen mode, if it had
        one to choose.

        The mode was picked as the object went on the stack (CR 700.2b), so by
        the time it resolves there is nothing left to ask: the ability behaves
        exactly like an unmodal one whose targets were chosen at the same
        moment. This is where that recorded index is spent.

        A modal item that reaches here with no recorded mode falls through to
        the ``choose_one`` instruction itself, which asks at resolution the way
        the engine used to. That is a backstop for a prompt discarded by
        something other than an answer, not a second policy: it cannot happen
        through the arming path, because the prompt blocks the seat until it is
        answered, and it does the only safe thing if it ever does.
        """
        instruction = item.ability_instruction
        modes = modal_trigger_modes(instruction)
        if not modes or item.chosen_mode_index is None:
            return instruction
        if not 0 <= item.chosen_mode_index < len(modes):
            return instruction
        return modes[item.chosen_mode_index]["instruction"]

    def _log_ability_outcome(self, item: StackItem, supported: bool, details: str) -> None:
        """What the game log says an ability's resolution did.

        "Resolved" is a claim about a resolution that is *over*. One that armed a
        prompt is not — the search has not been made, the life has not been
        gained — and saying so anyway was the visible half of the bug this link
        fixes: Sanctum of All read "ability resolved" in the log with its "you
        may search your library" prompt still unanswered on screen. The
        completion line is ``_release_stack_item``'s to write, once the last
        answer arrives."""
        if not supported:
            self.log.append(f"{item.card.name} ability fizzled: {details}")
        elif self.choices_for_stack_item(item):
            self.log.append(f"{item.card.name} ability is resolving, awaiting a choice")
        else:
            self.log.append(f"{item.card.name} ability resolved")

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
        # CR 608.2b, asked once for the whole object before any of it runs.
        # This module's docstring has claimed since it was written that a
        # resolution re-checks its targets, and until now nothing did: each
        # handler checked its *own* target and skipped its own effect, so the
        # sentences printed after the targeted one carried on regardless.
        # The gate is `legality.illegal_targets_refusal` — the sibling of the
        # announcement gate, so the same identities decide both ends.
        illegal = self.illegal_targets_refusal(item)
        if illegal is not None:
            self.log.append(illegal)
            if item.ability_instruction is None and not item.is_copy:
                # CR 608.2b: removed from the stack and, if it is a spell, put
                # into its owner's graveyard — the ordinary destination, so it
                # goes through the same binning as a resolved spell. An ability
                # and a token copy have no card to put anywhere.
                self._bin_spell_card(
                    self.players[item.caster_index], item.card,
                    exile_instead=item.exile_instead_of_graveyard,
                    verb="was countered by the rules",
                )
            return
        # A triggered ability with a name-keyed resolve-time hook (Rod/Cup/Sphere,
        # Verduran Enchantress, Guardian Angel deferred onto the stack).
        if item.hook_key is not None:
            from ...card_hooks import TRIGGER_HOOKS

            handler = TRIGGER_HOOKS.get(item.hook_key)
            if handler is not None:
                handler(self, item)
                self._log_ability_outcome(item, True, "")
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
            supported, details = state_machine.run(
                self._chosen_trigger_instruction(item)
            )
            self._log_ability_outcome(item, supported, details)
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
            chosen_modes=item.chosen_modes,
            old_color=item.choices.get("old_color"),
            divided_targets=item.choices.get("divided_targets"),
            exile_instead_of_graveyard=item.exile_instead_of_graveyard,
            cast_from_zone=item.cast_from_zone,
            choices=item.choices,
            trigger_context=item.trigger_context,
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
        # Every chosen mode of a "Choose one or more —" spell, each with its own
        # targets, in printed order (CR 608.2c). Empty for every other spell,
        # which is what keeps the single-mode path below untouched.
        chosen_modes: tuple = (),
        old_color: str | None = None,
        divided_targets: list[tuple[int, int | None]] | None = None,
        exile_instead_of_graveyard: bool = False,
        cast_from_zone: str = "hand",
        choices: dict | None = None,
        # What the *announcement* froze that this spell's own text refers back
        # to. A trigger's context (CR 603.10) has always ridden the stack item;
        # a spell had none to carry until CR 700.2e gave one a seat nobody on a
        # board can name — "**an opponent** chooses one —", and then "that
        # player" in the mode they chose. Same key, same reader
        # (`handlers/_common.frozen_that_player_seat`), so the phrase has one
        # answer whether a trigger or a mode choice bound it.
        trigger_context: dict | None = None,
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
            # CR 614: an entry replacement may have consumed the event, and then
            # the permanent is on no battlefield at all - Frankenstein's Monster
            # cast for an X its graveyard cannot pay goes to its owner's
            # graveyard "instead of onto the battlefield".
            #
            # Everything below this line is something that watches a permanent
            # *enter*: the log line, the global buff, the enters-the-battlefield
            # trigger, the Aura's attach. Running any of them for an entry that
            # did not happen is the "when it enters, do X instead" reading that
            # engine/replacements.py exists to avoid, one layer up from the
            # interceptor - and the log line saying the permanent was put onto
            # the battlefield is the same claim in the one place a player reads.
            if not self.is_on_battlefield(permanent):
                return
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
            # "Choose one **or more** —" (Sublime Epiphany, CR 700.2d). Each
            # chosen mode is its own application, with the targets it chose
            # (CR 601.2c) and the seat those targets sit on — two modes may name
            # objects on two different boards, which the spell's single
            # ``target_player_index`` cannot say. Printed order, because
            # CR 608.2c resolves the modes in the order the card writes them
            # rather than the order the caster named them; the list arrives
            # sorted from ``_resolve_chosen_modes``.
            #
            # Any non-empty list takes this path, one mode included: a caller
            # that named modes named their targets on them, and the branch below
            # reads the *item's* target fields, which such a cast never sets.
            # A cast that named no modes at all — the legacy `mode_index=`
            # spelling, and every non-modal spell — leaves the list empty and
            # takes the branch below exactly as it always has.
            if chosen_modes:
                for mode in chosen_modes:
                    seat = (
                        mode.target_player_index
                        if mode.target_player_index is not None else target_idx
                    )
                    if not 0 <= seat < len(self.players):
                        seat = target_idx
                    self._apply_spell_text(
                        caster,
                        self.players[seat],
                        card,
                        target_permanent_index=mode.target_permanent_index,
                        target_permanent_id=mode.target_permanent_id,
                        x_value=x_value,
                        new_color=new_color,
                        stack_target=mode.target_stack_item,
                        mode_index=mode.index,
                        old_color=old_color,
                        divided_targets=divided_targets,
                        cast_from_zone=cast_from_zone,
                        choices=choices,
                        trigger_context=trigger_context,
                    )
                return
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
                trigger_context=trigger_context,
            )

        # ``finish`` may run twice: once at the end of the resolution, and — if
        # a prompt this resolution armed was still queued then — again from
        # ``_release_stack_item`` when the last answer lands. The hook and the
        # end-the-turn flag are read on the first pass only.
        first_pass = {"ends_turn": None}

        def finish() -> None:
            if first_pass["ends_turn"] is None:
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
                first_pass["ends_turn"] = bool(getattr(self, "exile_resolving_spell", False))
                self.exile_resolving_spell = False
            # CR 608.2n makes the graveyard the *last* step, and a resolution
            # that armed a prompt still queued is not at its last step: a
            # discard, a Power Sink payment, Balance's removals. Binning here
            # put the card in two zones at once — held on the stack and in the
            # graveyard, with the log already reading "moved to graveyard" while
            # the decision was owed. The step is handed to the held object
            # instead, and ``_release_stack_item`` runs it with the last answer.
            # A suspending prompt (a search, a scry) never reaches here early —
            # ``run_resumable`` holds this step back for it — so this is the
            # non-suspending half of the same rule.
            held = self.resolving_stack_item
            if held is not None and held.card is card and self.choices_for_stack_item(held):
                held.finish_resolution = finish
                self._log_spell_awaiting_choice(card)
                return
            self._bin_spell_card(
                caster, card,
                exile_instead=exile_instead_of_graveyard or first_pass["ends_turn"],
                verb="resolved",
            )

        # CR 608.2n puts the card into the graveyard as the *last* part of
        # resolution, which matters once a spell's effect can stop to ask the
        # player something: finishing here regardless would bin the card while
        # its damage was still waiting on an answer. Word of Command already
        # needed the same care for its own reason, and is the reason `finish`
        # was a separable step to begin with.
        run_resumable(self, [apply_text, finish], lambda step: step())
        # The one thing that may legitimately follow a resumable loop: a note
        # that it *stopped*. ``finish`` is where a held spell says so, and a
        # suspending prompt (a scry, a search, and since discards suspend, a
        # Mind Rot) never reaches ``finish`` — ``run_resumable`` holds it back
        # until the answer lands. Without this the log went quiet exactly where
        # the player is being asked something. It runs only on the suspended
        # path, so it cannot double up with ``finish``'s line, and it records
        # nothing the resumption needs to redo.
        if self.effect_suspended:
            held = self.resolving_stack_item
            if held is not None and held.card is card and self.choices_for_stack_item(held):
                self._log_spell_awaiting_choice(card)

    def _log_spell_awaiting_choice(self, card) -> None:
        """CR 608.2: the spell is still resolving while a prompt it armed is
        owed. The ability half of this line is ``_log_ability_outcome``; both
        exist so "resolved" is never claimed of a resolution that has not
        finished."""
        self.log.append(f"{card.name} is resolving, awaiting a choice")

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
            if (
                trig.condition.kind not in INLINE_TRIGGER_CONDITIONS
                or not trig.supported
                or trig.instruction is None
            ):
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
                # The cast's X, stamped on the permanent by `_stack_push`.
                # "When this Aura enters, … put X sleep counters on it"
                # (Venarian Gold) reads it, and without it every amount in an
                # ETB trigger resolved "x" to zero.
                x_value=permanent.metadata.get("cast_x_value"),
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
