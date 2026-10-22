"""Putting triggered abilities onto the stack (CR 603.3).

``_enqueue_triggered_ability`` puts one there, once CR 603.4's first check
(``trigger_condition_holds``) says it triggered at all. Two windows decide
*when*: ``putting_triggers_on_stack`` gathers what one unit of play sets off
so each controller can order theirs (CR 603.3b, ``engine/trigger_order.py``),
and ``deferring_triggers`` holds what an announcement's own costs set off
until the announcement is finished (CR 601.2i). A permanent's own entry
triggers go on the stack the same way, on every road onto the battlefield
(``_apply_self_enters_battlefield_triggers``).

Split out of ``resolution.py`` at the 2,000-line cap, and composed onto
``Game`` with the other parts of ``StackResolutionMixin``, directly after it.
"""

from __future__ import annotations

from contextlib import contextmanager

from ...extra_triggers import additional_triggers
from ...game_types import StackItem
from ...handlers.control_flow import evaluate_condition
from ...models import CardDefinition, Permanent
from ...oracle import OracleInstruction, compile_card_oracle
from ...modal_triggers import ENTRY_TRIGGER_CONDITIONS, modal_trigger_modes
from ...trigger_order import offer_trigger_order, restore_apnap


class TriggeredAbilitiesMixin:
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
        # CR 603.7d's frozen scratchpad -- see ``StackItem.captured_results``.
        captured_results: dict | None = None,
        hook_key: str | None = None,
        hook_event: dict | None = None,
        # CR 107.3m: an entry trigger that refers to X uses the X chosen for
        # the spell that became its permanent. None for every other trigger.
        x_value: int | None = None,
        # The target fields above were announced by the permanent spell this
        # trigger's source was cast as, not chosen for this object -- see
        # ``_stack_push``.
        announced_at_cast: bool = False,
        # …and the one such announcement that is not a permanent or a player:
        # the **spell** a permanent spell named for its entry trigger ("When
        # this creature enters, counter target spell", Mystic Snake). By
        # identity, as ``StackItem.target_stack_item`` always is.
        target_stack_item: StackItem | None = None,
        # The target fields above are a **choice** its controller made out of
        # the ability's own list before the object existed — the upkeep step's
        # target prompt, answered ahead of ``resolve_upkeep`` and held there to
        # ``_upkeep_trigger_legal_targets``. See ``StackItem.targets_chosen``;
        # False for every fire site that stamps what its event was about.
        targets_chosen: bool = False,
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
                captured_results=captured_results,
                hook_key=hook_key,
                hook_event=hook_event,
                x_value=x_value,
                announced_at_cast=announced_at_cast,
                target_stack_item=target_stack_item,
                targets_chosen=targets_chosen,
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
        #
        # **Which is the one thing the loop did not do.** It built every
        # instance from the same target fields and pushed every one
        # ``announced_at_cast`` — so where those fields were a permanent
        # spell's announcement for its entry trigger (this engine's
        # convention), the additional instance was held to the cast's answer
        # too, as a copy would be. A cast names a target for **the** trigger
        # it will cause; nobody named one for the ability that triggered an
        # additional time, and that instance is put on the stack as one nobody
        # chose for (CR 603.3d): asked for where its seat can be, the picker's
        # default where it cannot, removed where nothing is legal.
        #
        # Only an announcement is dropped. Fields a **fire site** bound are
        # what the event was about ("destroy that Wall"), and the event is the
        # same event however many times the ability triggers.
        for instance in range(1 + additional_triggers(
            self, source_permanent, controller_index,
            delayed=effect_kind == "triggered_delayed",
        )):
            from_the_cast = announced_at_cast and instance == 0
            if announced_at_cast and not from_the_cast:
                target_player_index = target_permanent_index = target_permanent_id = None
            self._stack_push(
                StackItem(
                    card=stack_card,
                    caster_index=controller_index,
                    target_player_index=target_player_index,
                    target_permanent_index=target_permanent_index,
                    target_permanent_id=target_permanent_id,
                    target_stack_item=target_stack_item,
                    x_value=x_value,
                    ability_instruction=instruction,
                    ability_effect_kind=effect_kind,
                    source_permanent=source_permanent,
                    ability_text=ability_text,
                    trigger_context=trigger_context,
                    captured_results=dict(captured_results or {}),
                    hook_key=hook_key,
                    hook_event=hook_event,
                    targets_chosen=targets_chosen,
                ),
                announced_at_cast=from_the_cast,
            )

    def trigger_condition_holds(self, item: StackItem) -> bool:
        """CR 603.4's **first** check: does this ability trigger at all?

        "When/Whenever/At [trigger event], **if [condition]**, [effect]" is
        asked when the trigger event occurs, and the ability "triggers only if
        it is [true]; otherwise it does nothing" — it never reaches the stack.
        The rule then asks the same condition again on resolution, which is the
        read in ``_resolve_ability``.

        Only that second half existed, which made the outcome right for the
        wrong reason: a false condition produced an ability that went on the
        stack, sat there and then removed itself. That is observable rather
        than untidy — the object can be countered, every player has to pass
        priority on it, and anything watching for an ability being put onto the
        stack sees one that never triggered. Spectral Bears and Wall of
        Caltrops are the two it is easiest to watch happen on.

        Asked at ``_stack_push``, which is *the* one place an object goes on
        the stack, rather than at a fire site: five fire sites (the upkeep,
        draw and end steps, and the two delayed-trigger scans) had each grown
        their own copy of the check and the rest had none — which is why Chrome
        Replicator's entry trigger correctly never announced while Spectral
        Bears' attack trigger always did. The seam is the only place the next
        fire site cannot forget.

        Scoped by the **payload key**, which is a trigger's alone: no activated
        ability and no spell instruction in the pool carries ``intervening_if``
        because the grammar lowers it only under a trigger, so the presence of
        the key is itself the discriminator and no second list of kinds is
        needed. A **copy** is exempt (CR 707.10: copying an ability on the
        stack is not that ability triggering, so 603.4's first check either has
        already happened or never applied).
        """
        if item is None or item.is_copy:
            return True
        instruction = item.ability_instruction
        if instruction is None:
            return True
        gate = (instruction.payload or {}).get("intervening_if")
        if gate is None:
            return True
        if evaluate_condition(self, self._ability_execution_context(item), gate):
            return True
        self.log.append(
            f"{item.card.name} didn't trigger: its condition wasn't met (CR 603.4)"
        )
        return False

    def _enqueue_triggered_batch(self, events: list[dict]) -> None:
        """Put a batch of triggered abilities that fired from one event onto the stack
        in APNAP order (CR 603.3b): the active player's triggers are enqueued first
        (so they resolve last), then each other player's in turn order. Each player's
        own triggers keep their collection (battlefield-scan) order. The sort key is
        total and index-tie-broken, so enqueue order is fully seed-deterministic.

        That collection order is the **default** of CR 603.3b's choice, not the
        choice: the batch is a window (:meth:`putting_triggers_on_stack`), so a
        seat that put two or more on the stack here is asked to order them when
        the outermost window closes."""
        if not events:
            return
        n = len(self.players)
        active = self.active_player_index if self.active_player_index is not None else 0

        def _key(indexed):
            order, event = indexed
            controller = int(event["controller_index"])
            turn_distance = (controller - active) % n if n else 0
            return (turn_distance, controller, order)

        with self.putting_triggers_on_stack():
            for _, event in sorted(enumerate(events), key=_key):
                self._enqueue_triggered_ability(**event)

    @contextmanager
    def putting_triggers_on_stack(self):
        """A window around one unit of the game that sets triggers off
        (CR 603.3b; ``engine/trigger_order.py``).

        Every triggered object ``_stack_push`` puts on the stack while it is
        open is collected, and when the **outermost** window closes they are
        regrouped active player first (``restore_apnap``) and each seat
        that put two or more distinguishable ones there is asked their order
        (``order_triggers``; a seat nobody is asking keeps the order they were
        pushed in, the registry's at-arm default). Re-entrant the way
        :meth:`deferring_triggers` is: an inner window joins the outer one, so
        a batch inside a resolution is one question with the resolution's other
        triggers rather than a question of its own.

        Opened around a batch, a permanent's own entry triggers, a resolution,
        a state-based sweep, the turn-based actions that fire triggers and the
        triggers a cast held back — and closed **before** anything that could
        resolve them, so what is ordered is still on the stack to order. A
        window that raises asks nothing.
        """
        if self.collected_triggers is not None:
            yield
            return
        self.collected_triggers = []
        try:
            yield
        except BaseException:
            self.collected_triggers = None
            raise
        collected, self.collected_triggers = self.collected_triggers, None
        if len(collected) >= 2:
            # Between players first (APNAP), then within each player (their
            # choice) — the rule's two halves, in its order.
            restore_apnap(self, collected)
            offer_trigger_order(self, collected)

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
            # Everything the cast set off goes on the stack together, at the
            # moment the spell has finished being cast (CR 601.2i) — one
            # window, so its controller orders them (CR 603.3b).
            with self.putting_triggers_on_stack():
                for event in held:
                    self._enqueue_triggered_ability(**event)

    def _apply_self_enters_battlefield_triggers(
        self,
        controller_index: int,
        permanent: Permanent,
        target_player_index: int | None,
        target_permanent_index: int | None,
        target_permanent_id: int | list[int | None] | None = None,
        *,
        targets_announced: bool = True,
        target_stack_item: StackItem | None = None,
    ) -> None:
        """Put a just-entered permanent's own "when this enters" triggered
        abilities on the stack (CR 603.6a, CR 603.3).

        **Each one is a stack object, and nothing of it happens here.** CR 603.3:
        "Once an ability has triggered, its controller puts it on the stack as
        an object that's not a card the next time a player would receive
        priority." Until Planeshift this method *executed* the trigger, inside
        the event that put the permanent onto the battlefield — an
        approximation that went in with Arabian Nights (Oubliette), whose stated
        reason was that the engine had no window in which a trigger's target
        could be chosen. ``_choose_trigger_targets`` has been that window since,
        and the approximation outlived its reason by eleven sets: 265 of the
        pool's 278 entry triggers resolved with no object on the stack, so
        nothing could respond to one. Cavern Harpy ("When this creature enters,
        return a blue or black creature you control to its owner's hand. / Pay
        1 life: Return this creature to its owner's hand.") could not be
        returned in response to its own gate, which is the best-known play with
        the card.

        Measured before it was changed: run both ways over every entry trigger
        in both manifest roles on three roads onto the battlefield (807
        scenarios), the two paths ended in the same game state everywhere but
        four cards, and three of those were the inline path being wrong — see
        the seat below. ``tests/engine/test_entry_trigger_stack_census.py``
        holds the invariant.

        **Order.** The triggers of one permanent trigger together, and CR
        603.3b lets their controller put them on the stack in any order. They
        are pushed in one window (``putting_triggers_on_stack``), so a seat
        that is asked chooses (``order_triggers``); the order a seat nobody
        asks keeps is the printed one: the *first printed resolves first*,
        which is the order they ran in inline, and so the last printed is
        pushed first. Each resolves alone — Sawtooth Loon's
        gate is asked, answered and finished before its "draw two cards, then
        put two cards … on the bottom" begins, where inline the second ran into
        the first's unanswered prompt.

        **The cast's announcement rides the object.** This engine names an
        entry trigger's target as the permanent is cast (the standing
        approximation ``targeting._cast_target_spec`` documents; CR 603.3d
        would choose it here), so the seat, slot and id the cast handed in are
        stamped on the stack object, flagged ``announced_at_cast`` so the push
        neither asks again nor announces the same choice twice — **provided
        the announcement is one the trigger could have made**: the push asks
        :meth:`cast_announcement_fault`, and a target the trigger could not
        choose (protection from this permanent, a creature that left while the
        spell waited) is set aside there, the trigger then choosing as one
        nobody announced for. The id travels
        with the index because an index is unstable: anything leaving the
        battlefield renumbers every later slot, and the trigger now waits
        through a priority round of its own.

        **The seat is the one the cast named, or none.** Inline, a trigger
        nobody named a player for ran with its *controller* as "the target
        player"; every other trigger in the engine defaults that to the first
        opponent (``_ability_execution_context``), and the stack object takes
        that default like the rest. The difference was three shipped cards,
        all wrong inline: Rishadan Brigand, Cutpurse and Footpad ("each
        opponent sacrifices a permanent of their choice unless they pay {N}")
        charged the toll to their own controller.

        **Whose triggers** is what the permanent *has*, which is
        ``effective_card`` and not ``card``. CR 707.5: an object that enters as
        a copy "becomes a copy as it enters the battlefield", and "any
        enters-the-battlefield triggered abilities of the copy will have a
        chance to trigger"; CR 603.6d checks an entering permanent as it exists
        after the event. Reading the printed card, every copy in the pool —
        Clone, Vesuvan Doppelganger, Copy Artifact and the token copies of
        Dance of Many, Dual Nature, Echo Chamber and Sublime Epiphany — fired
        nothing on arrival. The death half of the same question
        (``_permanent_to_graveyard``) already read the effective card.

        *targets_announced* says whether the targets handed in were chosen
        *for these triggers*. True for a cast whose picker was derived from the
        entry trigger (``targeting._cast_target_spec``'s last branch). False
        for an entry nothing cast (a token, a reanimation), for a cast that
        announced nothing, and for a copy, whose cast announced the object to
        copy instead: nothing chose a target for the trigger at all, so one
        that has a target to choose chooses it as it is put on the stack
        (CR 603.3d; a non-interactive seat takes the picker's stated default).

        **An announcement is spent by the one trigger it was made for.** The
        cast's picker is derived from the *first* entry trigger that describes
        a target (``targeting._first_described_slot``, over the triggers a cast
        kicked this way will fire -- CR 702.33g), so that trigger is the only
        one anybody chose for. A second trigger with a target of its own was
        announced by nobody, exactly as on an entry nothing cast, and handing
        it the first one's target is two wrong answers: "destroy target land"
        handed two creatures finds its target gone and does nothing, and
        "destroy target enchantment" handed a *player* falls to the handler's
        fallback scan and destroys whichever enchantment that seat controls.
        So once a choosing trigger has taken the announcement, every later
        choosing trigger chooses for itself (CR 603.3d). Planeshift's
        Battlemages ("Kicker {2}{U} and/or {2}{R}", one trigger per cost) are
        the cards that reach it.

        **A modal trigger takes nothing from the cast.** CR 603.3c: its mode,
        and then that mode's targets, are chosen as it is put on the stack —
        ``_choose_trigger_mode`` — and the cast's picker derives nothing for a
        bulleted head, so there is no announcement that could be its.
        """
        program = compile_card_oracle(permanent.effective_card)
        if target_player_index is not None and not (
            0 <= target_player_index < len(self.players)
        ):
            target_player_index = None
        handed_over = any(
            value is not None
            for value in (
                target_player_index, target_permanent_index, target_permanent_id,
                target_stack_item,
            )
        )
        announcement_spent = False
        triggered: list[dict] = []
        for trig in program.triggered_abilities:
            if (
                trig.condition.kind not in ENTRY_TRIGGER_CONDITIONS
                or not trig.supported
                or trig.instruction is None
            ):
                continue
            event = dict(
                controller_index=controller_index,
                source_permanent=permanent,
                card=permanent.card,
                instruction=trig.instruction,
                effect_kind=trig.effect_kind,
                ability_text=trig.source_line,
                # CR 107.3m: the cast's X, stamped on the permanent by
                # `_resolve_card`. "When this Aura enters, … put X sleep
                # counters on it" (Venarian Gold) reads it, and without it
                # every amount in an entry trigger resolved "x" to zero.
                x_value=permanent.metadata.get("cast_x_value"),
            )
            chooses = self._entry_trigger_chooses_a_target(
                trig.instruction, trig.source_line
            )
            chooses_on_the_stack = bool(modal_trigger_modes(trig.instruction)) or (
                chooses and (not targets_announced or announcement_spent)
            )
            if handed_over and not chooses_on_the_stack:
                event.update(
                    target_player_index=target_player_index,
                    target_permanent_index=target_permanent_index,
                    target_permanent_id=target_permanent_id,
                    announced_at_cast=True,
                )
                if target_stack_item is not None:
                    event["target_stack_item"] = target_stack_item
            # CR 603.4: an ability whose "if" is false as the event occurs does
            # not trigger at all. Asked here as well as at the push, because
            # only a trigger that *fired* spends the announcement: one whose
            # "if" was false (a Battlemage kicked with its second cost alone)
            # was never the trigger the picker described.
            if not self._entry_trigger_triggers(event):
                continue
            if not chooses_on_the_stack:
                announcement_spent = announcement_spent or chooses
            triggered.append(event)
        # Last printed first, so the first printed is on top and resolves
        # first — the order a seat nobody is asking keeps. One window, so a
        # seat that is asked chooses its own (CR 603.3b).
        with self.putting_triggers_on_stack():
            for event in reversed(triggered):
                self._enqueue_triggered_ability(**event)

    def _entry_trigger_triggers(self, event: dict) -> bool:
        """CR 603.4's first check for one entry trigger, before it is queued.

        Asked through :meth:`trigger_condition_holds`, of an object built the
        way the push will build it, so the answer is the one ``_stack_push``
        will reach a moment later: the rule's two checks, and this early read
        of the first, all go through the one context builder
        (:meth:`_ability_execution_context`). Nothing is put on the stack here.
        """
        if (event["instruction"].payload or {}).get("intervening_if") is None:
            return True
        return self.trigger_condition_holds(StackItem(
            card=event["card"],
            caster_index=event["controller_index"],
            target_player_index=event.get("target_player_index"),
            target_permanent_index=event.get("target_permanent_index"),
            x_value=event.get("x_value"),
            target_permanent_id=event.get("target_permanent_id"),
            ability_instruction=event["instruction"],
            ability_effect_kind=event["effect_kind"],
            source_permanent=event["source_permanent"],
            ability_text=event["ability_text"],
        ))
