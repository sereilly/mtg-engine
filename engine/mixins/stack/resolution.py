"""Resolving the top of the stack (CR 608).

The other end of the pipeline: whatever ``casting`` and ``activation`` queued
comes back here to be executed, its targets re-checked for legality
(CR 608.2b — a spell whose every target is illegal is countered), and its card
put wherever it goes afterwards.

Putting triggered abilities onto the stack (CR 603) is
``triggered_abilities``, and the choices a trigger makes on the way — its
mode and its targets (CR 603.3c–d) — are ``trigger_targets``. Both are
composed onto ``Game`` directly after this one.
"""

from __future__ import annotations

from ...bare_announcements import resolving_slots
from ...auras import aura_enchant_clause
from ...cast_costs import (CAST_COST_DISCARD_MANA_VALUE, KICKED,
                           KICKED_WITH, buyback_paid, kicked,
                           kickers_paid)
from ...cast_timing import CAST_AT_INSTANT_SPEED
from ...classifier import CardClassification, classify_card
from ...color_changes import carry_spell_color_change
from ...destruction_events import destruction_finished
from ...enter_effects import copy_on_enter_type
from ...events import emit
from ...faces import whole_card
from ...flashback import leaves_stack_to_exile
from ...game_types import OracleExecutionContext, OracleStateMachine, StackItem
from ...handlers.control_flow import evaluate_condition
from ...models import CardDefinition, Permanent
from ...oracle import OracleInstruction, compile_card_oracle
from ...modal_triggers import modal_trigger_modes
from ...resumption import run_resumable
from ...state_triggers import release_latch


class StackResolutionMixin:
    def counter_stack_object(self, item: StackItem) -> None:
        """CR 701.6a: cancel *item*, taking it off the stack, and announce it.

        The one place a spell or an ability is **countered**. It was three —
        ``handlers/stack.counter_top_stack_spell``, ``counter_stack_ability``
        and the pay-or-be-countered prompt's declined branch — each spelling out
        its own ``stack.remove``, which is the ``become_tapped`` problem again:
        anything that has to happen when an object is countered had three places
        to be forgotten, and "whenever a spell you've cast is countered" was
        forgotten in all three.

        **Removal by identity.** ``StackItem`` is a plain dataclass and a deck
        repeats one immutable ``CardDefinition`` per copy, so two casts of the
        same card with the same target compare **equal** — ``list.remove`` would
        take whichever sits lower on the stack. The same look-alike the control
        seam bans ``battlefield.remove`` for, and ``exile_target_spell`` one
        module over already walks the stack by ``is`` for it.

        **What is not a counter.** Two neighbouring paths cancel a resolution
        and deliberately do not come here, because CR does not call either one
        countering: a spell **exiled** off the stack (``exile_target_spell`` —
        "can't be countered" does not stop it), and CR 608.2b's spell whose
        every target has become illegal, which "doesn't resolve" and is
        "removed from the stack and, if it's a spell, put into its owner's
        graveyard" without the word ever appearing. That second one reads
        "countered by the rules" in this engine's log, which is the pre-M2010
        wording; the log line is left alone and the announcement is not made,
        because Multani's Presence must not draw off a fizzle.

        The announcement is made for a **spell** only. ``is_ability`` is CR
        113.3's question and the pool prints no trigger watching a countered
        ability; a copy is excluded because CR 707.10 puts it on the stack
        without it ever having been *cast*, which is the word the only condition
        watching this event prints.

        Where the card goes afterwards stays the caller's business: CR 701.6a's
        graveyard, an "exile it instead" rider, Memory Lapse's library. This is
        the cancel, not the destination.
        """
        for index, obj in enumerate(self.stack):
            if obj is item:
                del self.stack[index]
                break
        # CR 603.8: a state-triggered ability "doesn't trigger again until the
        # ability has resolved, **has been countered**, or has otherwise left
        # the stack" — and then does, if its state still holds. The latch key
        # rides the object for exactly this.
        release_latch(item)
        if item.is_ability or item.is_copy:
            return
        emit(
            self, "your_spell_countered",
            seat=item.caster_index, subject=item.card,
        )

    def _bin_spell_card(
        self, owner, card: CardDefinition, *, exile_instead: bool, verb: str,
        hand_instead: bool = False, exile_is_final: bool = False,
        chooser_index: int | None = None,
    ) -> None:
        """Where a spell's card goes as it leaves the stack (CR 608.2n): the
        owner's graveyard, unless the cast carried the "if that spell would be
        put into your graveyard, exile it instead" rider — which covers
        resolving and being countered alike, so every leave-the-stack site
        routes through here rather than deciding for itself.

        *hand_instead* is CR 702.27a's second static ability: "If the buyback
        cost was paid, put this spell into its owner's hand instead of into that
        player's graveyard **as it resolves**." A parameter rather than a
        question this function asks, because the seam is shared with the
        countering path and that rule's "as it resolves" excludes it — a bought
        back spell that is countered goes to the graveyard like any other. Only
        the resolution site passes it, off ``cast_costs.buyback_paid``.

        Through ``put_card_into_hand``, so CR 903.9b is asked at the one place
        it has to be asked (CLAUDE.md's "every put this card into a hand goes
        through" seam) — a commander bought back returns to the command zone if
        its owner says so.

        **Order when two of these apply**, which is why ``exile_instead`` is
        not asked alone: it is true for three different reasons and buyback
        stands differently to each. *exile_is_final* says which.

        * CR 702.34a's flashback exile is "instead of putting it **anywhere
          else**", and CR 724.1b's end-the-turn exile is not a replacement at
          all — it removes the object from the stack, so the resolution
          buyback's clause is about never finishes. Against either the hand is
          not on offer: *exile_is_final*.
        * The rider "if that spell would be put into your graveyard, exile it
          instead" (Bösium Strip; Chandra, Flame's Catalyst) replaces exactly
          the event buyback replaces, and so does a board-wide "if a card would
          be put into your graveyard from anywhere, exile that card instead"
          (Forbidden Crypt, Yawgmoth's Will). Two replacement effects over one
          event are CR 616.1's, and the choice is the affected object's
          controller's — *chooser_index*, the spell's controller. Yawgmoth's
          Will's own ruling says it in as many words: "there will be two
          effects trying to replace where the card goes. You get to choose if
          the Buyback returns the card to your hand or the card gets exiled."
          See :meth:`_bin_bought_back_spell`.

        This function used to answer the second case two ways and ask about
        neither: the rider always won (a Capsize bought back off a Bösium Strip
        was exiled, its {3} paid for nothing) and the board-wide effect always
        lost.
        """
        # CR 709.4: the *spell* was one half of a split card and the card that
        # leaves the stack is the whole of it. ``card`` stays the half for the
        # log lines — that is the spell that resolved — and ``leaving`` is what
        # lands in a zone. The hand and graveyard seams ask the same question
        # themselves; exile has no seam, so it is asked here.
        leaving = whole_card(card)
        if hand_instead and not (exile_instead and exile_is_final):
            self._bin_bought_back_spell(
                owner, card, leaving, rider=exile_instead, verb=verb,
                chooser_index=chooser_index,
            )
            return
        if exile_instead:
            owner.exile.append(leaving)
            self.log.append(f"{card.name} {verb} and was exiled instead of going to the graveyard")
        elif self.put_card_into_graveyard(owner, leaving):
            self.log.append(f"{card.name} {verb} and moved to graveyard")
        else:
            # A CR 614 replacement sent it somewhere else (Forbidden Crypt's
            # exile, Legacy Weapon's shuffle) and has said where. The seam's
            # False is "the card did not arrive", and this line used to
            # announce an arrival regardless.
            self.log.append(f"{card.name} {verb}")

    #: The event a bought-back spell's last step is, for CR 616.1e's record
    #: (``Game.effect_order_answers``) and the ``effect_order`` prompt's
    #: ``event_kind``.
    BOUGHT_BACK_EVENT = "bought_back_spell"

    def _bin_bought_back_spell(
        self, owner, card: CardDefinition, leaving, *, rider: bool, verb: str,
        chooser_index: int | None,
    ) -> None:
        """CR 616.1 over the last step of a spell whose buyback cost was paid.

        CR 608.2n puts a resolved instant or sorcery into its owner's
        graveyard, and CR 702.27a's second static ability replaces that: "put
        this spell into its owner's hand instead of into that player's
        graveyard as it resolves". It is one contender. The others are whatever
        else would replace the same move — the *rider* this cast was made under
        ("if that spell would be put into your graveyard, exile it instead")
        and each board-wide effect the graveyard seam would apply to this card
        (``replacements`` kind ``put_into_graveyard``: Forbidden Crypt,
        Yawgmoth's Will), asked through the registry's own pure predicates
        over the event that seam would raise.

        With nothing else in contention the card goes to the hand, which is
        every bought-back spell on an ordinary board. Otherwise CR 616.1e gives
        the choice to the spell's controller: an interactive seat is asked
        through the ``effect_order`` prompt every other contended event uses
        (the spell stays on the stack until it is answered — CR 608.2n is the
        *last* part of the resolution), and every other seat takes the lowest
        order, which is the buyback: the payer has just paid for the return.

        One application ends it (CR 616.1f): once the card is headed for a
        hand it is no longer headed for a graveyard, so nothing that replaces
        "would be put into a graveyard" still applies, and once it is exiled
        buyback's "instead of into that player's graveyard" has nothing to
        replace. Declining the buyback in favour of a board-wide effect is the
        card going where it was going — through ``put_card_into_graveyard``,
        which is where that effect lives.

        Nothing has moved when the prompt is armed, so answering re-runs this
        step whole (``engine/effect_ordering.py``): the restart is
        :meth:`_bin_spell_card` with the arguments it was first handed.
        """
        from ...effect_ordering import Candidate, apply_in_order
        from ...replacements import order_prompt_asker, replacement_candidates

        seat = chooser_index if chooser_index is not None else self._owner_seat(owner)
        kind = self.BOUGHT_BACK_EVENT
        # The event the graveyard seam would raise for this card, for the
        # registry's predicates: the card as it lands (CR 709.4), bound for its
        # owner's pile, from no zone a card names.
        bound_for_graveyard = {
            "player": owner, "card": leaving, "from_zone": None, "permanent": None,
        }

        def unsettled(_game, event: dict) -> bool:
            return not event.get("settled")

        def to_hand(game, event: dict) -> None:
            event["settled"] = True
            if game.put_card_into_hand(owner, leaving):
                game.log.append(
                    f"{card.name} {verb} and returned to its owner's hand "
                    "(buyback) instead of going to the graveyard"
                )

        def to_exile(game, event: dict) -> None:
            event["settled"] = True
            owner.exile.append(leaving)
            game.log.append(
                f"{card.name} {verb} and was exiled instead of going to the graveyard"
            )

        def to_graveyard(game, event: dict) -> None:
            event["settled"] = True
            if game.put_card_into_graveyard(owner, leaving):
                game.log.append(f"{card.name} {verb} and moved to graveyard")
            else:
                game.log.append(f"{card.name} {verb}")

        contenders = [
            Candidate(
                key="buyback", order=0, applies=unsettled, apply=to_hand,
                label=f"Buyback: return {card.name} to its owner's hand",
            )
        ]
        if rider:
            contenders.append(Candidate(
                key="cast_rider_exile", order=1, applies=unsettled, apply=to_exile,
                label=(
                    f"Exile {card.name} instead (the effect it was cast under)"
                ),
            ))
        for position, registered in enumerate(
            replacement_candidates("put_into_graveyard")
        ):
            contenders.append(Candidate(
                key=registered.key, order=2 + position,
                applies=lambda game, event, registered=registered: (
                    not event.get("settled")
                    and registered.applies(game, bound_for_graveyard)
                ),
                apply=to_graveyard,
                label=(
                    f"Put {card.name} into the graveyard, as replaced there "
                    f"({registered.label or registered.key})"
                ),
            ))

        def restart() -> None:
            self._bin_spell_card(
                owner, card, exile_instead=rider, verb=verb, hand_instead=True,
                chooser_index=chooser_index,
            )

        trace = apply_in_order(
            self, {}, contenders, chooser_index=seat,
            ask=order_prompt_asker(kind, restart),
        )
        if not trace.suspended:
            self.effect_order_answers.pop((kind, seat), None)

    def _default_opposing_seat(self, caster_index: int) -> int:
        """The seat a triggered ability affects when nothing chose one.

        A trigger that prints "target player" now chooses one where CR 603.3d
        puts the choice — :meth:`_choose_trigger_targets`, as the ability goes
        on the stack — and this is what is left underneath: an ability whose
        seat the *firing event* named rather than its controller, and one whose
        printed line names no player at all but whose effect still has to reach
        somebody ("target opponent loses that much life" on Vito, whose lowering
        records no target description for the picker to narrow).

        Where nothing chose, that someone was ``1 - caster_index``: right for
        two players, and at seat 2 of a three-handed game ``players[-1]``, which
        is the caster itself. A player is never their own opponent (CR 102.3),
        so Vito would have drained himself.

        It is also the **answer a non-interactive seat gives the new picker**
        (``_default_trigger_target``), which is what makes announcing a target a
        change to what a player is asked and to nothing else.

        The first living opponent in seat order instead. The old answer is kept
        as the fallback for a table with no living opponent left, so nothing
        that reaches here mid-teardown changes.
        """
        opponents = self.opponents_of(caster_index)
        if opponents:
            return opponents[0]
        fallback = 1 - caster_index
        return fallback if 0 <= fallback < len(self.players) else caster_index

    def _spell_default_seat(self, caster_index: int) -> int:
        """The seat an instant or sorcery that named no player resolves at.

        ``1 - caster``: the opposing seat of a two-player game, which is the
        arithmetic :meth:`_resolve_card` has always done and the default the
        web route sends for a cast with no ``target_seat``. A method so that
        the announcement gate (``legality._cast_player_target_refusal``,
        CR 601.2c) and the resolution gate (``illegal_targets_refusal``,
        CR 608.2b) ask about the very seat the resolution will read — the
        default is a target like any other, and a gate that guessed it
        differently would be judging a player the spell never reaches.

        Not range-checked here: at three seats it can name no seat at all, and
        each reader decides what that means (the gates decline to judge).
        """
        return 1 - caster_index

    def _ability_execution_context(self, item: StackItem) -> OracleExecutionContext:
        """The context an ability on the stack runs in.

        One builder because CR 603.4 asks its condition **twice** — once as the
        ability triggers (:meth:`trigger_condition_holds`, from ``_stack_push``)
        and once as it resolves — and the two answers have to be about the same
        reading of the same object. A second construction here would be two
        contexts that can disagree about what "you" and "that creature" mean,
        which is exactly the shape of bug the rule's own wording invites: it is
        the *same* condition, asked at two moments.
        """
        # An ability whose every target is a spell on the stack is about that
        # spell's controller, whatever seat rode beside it — see
        # ``Game.stack_target_seat``.
        target_idx = self.stack_target_seat(item)
        if target_idx is None:
            target_idx = (
                item.target_player_index
                if item.target_player_index is not None
                else self._default_opposing_seat(item.caster_index)
            )
        target_permanent_index = item.target_permanent_index
        if item.activated:
            # CR 602.2b: an activated ability's slot is re-read off the ids
            # its announcement stamped, as a spell's is
            # (`bare_announcements.resolving_slots`). Not for a triggered
            # ability, whose fire site threads other things through these
            # fields.
            target_permanent_index = resolving_slots(
                self, self.players[target_idx], target_permanent_index,
                item.target_permanent_id, card=item.card,
                mode_index=item.chosen_mode_index,
                instruction=item.ability_instruction,
            )
        return OracleExecutionContext(
            caster=self.players[item.caster_index],
            target=self.players[target_idx],
            card=item.card,
            target_permanent_index=target_permanent_index,
            target_permanent_id=item.target_permanent_id,
            # The graveyard half of the same announcement, for a roles
            # instruction whose slots sit in two zones (Goblin Welder). Every
            # other graveyard target reads the index this method has already
            # re-located; that one needs the stamp itself, because the index
            # cannot say whose pile a slot counts into.
            target_graveyard_card=item.target_graveyard_card,
            x_value=item.x_value,
            source_permanent=item.source_permanent,
            ability_text=item.ability_text,
            stack_target=item.target_stack_item,
            trigger_context=item.trigger_context,
            choices=item.choices,
            # CR 603.7d: a delayed ability resolves with the scratchpad
            # its creating effect had, because the step that recorded
            # what "that creature" names ran a turn ago. Empty for every
            # other trigger, which is the scratchpad they already had.
            results=dict(item.captured_results),
            # CR 602.2b: an activated ability's targets are its announcement's.
            # A triggered ability's are its fire site's, and stay unmarked.
            announced=bool(item.activated),
        )
    def _settle(self) -> None:
        """Run state-based actions, then resolve the stack one item at a time,
        re-checking SBAs between each resolution (CR 704.3 + 603.3). Triggers that
        fire during an SBA check are enqueued (never resolved) there, so this loop
        is what actually drains them in the headless/AI path. Terminates when the
        stack is empty and SBAs report no further change.

        **Whether a resolution may stop to ask is derived, not assumed.** This
        loop is reached from the two "do the whole thing now" entry points
        (``cast_from_hand``, ``activate_permanent_ability``), and it resolved
        with ``pause_for_choices`` left False whoever was playing — so a prompt
        armed part-way through a resolution was queued against an *empty
        stack*: nothing recorded the object (``_stack_item`` is stamped from
        ``resolving_stack_item``, which only the pausing path sets), so the
        object never came back, ``_release_stack_item`` never ran, and CR 704.3's
        sweep and CR 117.3b's priority hand-off were applied to a resolution
        that had not finished. Measured over the shipped pool: of the 296
        prompt-armings a resolution makes on this path, **267 across 255 cards**
        had nothing holding them. The other 29 structurally cannot have one — a
        mana ability uses no stack (CR 605.3a), a mode chosen at announcement
        records ``_trigger_item`` instead, and a land play puts no object on the
        stack at all — and those same 29, and only those, are what the priority
        path leaves unheld. That is what named this loop as the seam.

        The condition is ``bool(self.interactive_seats)`` — the same derivation
        ``_resolve_priority_window`` already makes, and for the same reason: with
        nobody to stop for, headless and AI play queue the same prompts and drain
        them deterministically afterwards, so a seeded run resolves exactly as it
        did.

        **What it does not do is answer anything.** A prompt owed by a seat the
        engine plays still holds the object here, exactly as it does on the
        priority path, and the caller drains it — ``_auto_resolve_ai_pending``
        in the web layer, ``auto_resolve_pending_choices`` in a test. Draining
        inside this loop was tried and is a *different* change: it takes the
        AI's answer before the caller can see what was asked, which is what
        forty tests read the queue for.

        Power Sink's payment is where that shows on a shipped card. It used to
        be answered from inside ``resolve_top_of_stack`` on the ``not
        pause_for_choices`` branch, so ``cast_from_hand`` finished it; now it is
        queued like every other prompt, held with its object, and answered by
        whoever drains. Invoke Prejudice ("counter that spell unless that player
        pays {X}{X}") is the card that reaches it in an ordinary duel.
        """
        # CR 608.2 / CR 117.3b, only where there is somebody to wait for.
        pause_for_choices = bool(self.interactive_seats)
        iterations = 0
        while True:
            self.check_state_based_actions()
            # A table whose prompts a driver answers (`Game.prompt_driver`, the
            # AI simulator): what the object just resolved asked is answered
            # *here*, before the next object resolves, rather than after this
            # whole loop has returned. Inert for every other game, so the
            # sentence above about not answering anything still holds for them.
            if self.drive_owed_prompts():
                iterations += 1
                if iterations > self.MAX_SETTLE_ITERS:
                    break
                continue
            if not self.stack:
                break
            # CR 117.4: the top resolves once every player has passed in
            # succession — asked of a table whose seats a driver plays
            # (`Game.priority_driver`, the AI simulator), so a spell cast here
            # can be answered before it resolves. Inert for every other game,
            # and in the untap step, where nobody receives priority (CR 502.4).
            if self.current_step != "untap":
                self.offer_priority()
            if not self.resolve_top_of_stack(pause_for_choices=pause_for_choices):
                # Top item is paused on a pending choice (Word of Command).
                break
            # A resolution that stopped to ask holds its object on the stack
            # (CR 608.2). Break *here* rather than letting the loop come round:
            # the next iteration's SBA check would run mid-resolution, which is
            # a sweep at a moment CR 704.3 does not name. The caller resumes
            # when the last of the object's prompts is answered — the answer
            # path releases it (`_release_stack_item`).
            if (
                pause_for_choices
                and self.stack
                and self.stack[-1].resolution_held
                and self.stack_item_is_waiting(self.stack[-1])
            ):
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
            # Everything this resolution sets off goes on the stack together
            # once it is over (CR 603.3, CR 603.3b): one window, whichever fire
            # sites — a sweep's deaths, an entry, a batch — put them there.
            with self.putting_triggers_on_stack():
                self._run_stack_item_resolution(item)
        finally:
            self.resolving_items.pop()
            self.resolving_stack_item = previous_resolving
        # **The resolution seam** (CR 611.3a: a static ability's effect applies
        # at any given moment to whatever its text indicates). Whatever this
        # object just did — recoloured a creature, changed a type, moved a
        # permanent, put a counter on one — the board-wide statics are judged
        # again here, once, before anything else reads the board: the prompt
        # the resolution may have armed, the next object down the stack, a
        # client polling the state.
        #
        # There was no recompute here. A handler that knew its effect could
        # move a static's reach did its own (eight of the type-changing ones,
        # after last round), and every other resolution left the board as its
        # last handler happened to leave it until a state-based check came by:
        # a Bears laced black under Breath of Dreams kept the green creatures'
        # upkeep, and one laced white under a Crusade was not pumped.
        self._recompute_continuous_effects()
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
            # …and what it has destroyed so far keeps waiting with it: the
            # abilities that triggered go on the stack when the last answer
            # arrives (`_answer_pending_choice`), not under an object that is
            # still resolving.
            return True
        # The resolution is over, so the abilities its destructions triggered
        # stop waiting for it (CR 603.3b). See engine/destruction_events.py.
        destruction_finished(self)
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

    def _intervening_if_is_no_longer_true(self, item: StackItem) -> bool:
        """CR 608.2a / CR 603.4: whether *item* is a triggered ability whose
        intervening-if condition is false as it resolves.

        False for everything that has none — a spell, an activated ability, a
        hook-keyed object (which resolves through its hook and never asked),
        and a trigger whose line prints no "if". Scoped by the payload key,
        as :meth:`trigger_condition_holds` is at the other end of the rule.
        """
        instruction = item.ability_instruction
        if instruction is None or item.hook_key is not None:
            return False
        gate = (instruction.payload or {}).get("intervening_if")
        if gate is None:
            return False
        return not evaluate_condition(self, self._ability_execution_context(item), gate)

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
            # ``[]`` is a real announcement, not a missing one: "Return **up
            # to X** target cards…" with X counted at 0 (Reap against an
            # opponent with no black permanents) names no target and is a legal
            # cast, and so is any "up to" spell announced empty. Indexing a
            # stamp list without asking whether it has one raised IndexError
            # from inside the resolution, which is a crash where CR 601.2c has
            # an answer.
            stamps = item.target_graveyard_card
            first = (
                (stamps[0] if stamps else None)
                if isinstance(stamps, list)
                else stamps
            )
            if first is not None:
                item.target_player_index = first.seat
        # CR 608.2a, which the rule puts **before** 608.2b ("The steps
        # described in rules 608.2a and 608.2b are followed first"): CR 603.4's
        # **second** check. An intervening-if is asked again as the ability
        # resolves, and the ability is removed from the stack and does nothing
        # if it is false. 102 supported cards compile the key; the comment that
        # stood beside this check said no card in the shipped pool did, which
        # was the reason the rule's *first* check went unbuilt for as long as
        # it did.
        #
        # It stood *below* the target gates, which did not matter while those
        # gates answered for spells (no spell has an intervening-if) and
        # matters now that a trigger's chosen target is asked too: Ana
        # Sanctuary's only blue permanent leaving is "its condition is no
        # longer true" whether or not that permanent was also what it targeted.
        if self._intervening_if_is_no_longer_true(item):
            self.log.append(
                f"{item.card.name} ability did nothing: its condition is no longer true"
            )
            return
        # CR 608.2b, asked once for the whole object before any of it runs.
        # This module's docstring has claimed since it was written that a
        # resolution re-checks its targets, and until now nothing did: each
        # handler checked its *own* target and skipped its own effect, so the
        # sentences printed after the targeted one carried on regardless.
        # The gate is `legality.illegal_targets_refusal` — the sibling of the
        # announcement gate, so the same identities decide both ends.
        illegal = self.illegal_targets_refusal(item)
        if illegal is None:
            # ...and the same rule for the one restriction that is not about a
            # target still *existing* but about it still *answering what the
            # card printed*: "target opponent who has more life than you do".
            # A second call rather than a branch inside the gate above, because
            # that gate is CR 608.2b for spells and this is CR 608.2b for one
            # printed clause — folding them would advertise a cover over
            # abilities that does not exist. `legality.stale_comparison_refusal`
            # states its own bounds.
            illegal = self.stale_comparison_refusal(item)
        if illegal is None:
            # …and the third, for the same reason a second call was made
            # rather than a branch: CR 608.2b for an *activated* ability whose
            # only targets were graveyard cards that have all left. The
            # handlers behind it read a vanished stamp as "nothing was
            # announced" and returned a different card.
            illegal = self.vanished_graveyard_target_refusal(item)
        if illegal is None:
            # …and the fourth: an ability whose one target is a card in a
            # graveyard that its *handler* would find for itself (a trigger
            # has no picker for one), while the board says no card in a
            # graveyard may be targeted (Ground Seal). Inert unless such a
            # permanent is on the battlefield.
            illegal = self.sealed_graveyard_target_refusal(item)
        if illegal is not None:
            self.log.append(illegal)
            # CR 603.8's "or has otherwise left the stack": an ability removed
            # here did not resolve, so a state trigger may trigger again.
            release_latch(item)
            if item.ability_instruction is None and not item.is_copy:
                # CR 608.2b: removed from the stack and, if it is a spell, put
                # into its owner's graveyard — the ordinary destination, so it
                # goes through the same binning as a resolved spell. An ability
                # and a token copy have no card to put anywhere.
                self._bin_spell_card(
                    self.players[item.owner_index], item.card,
                    exile_instead=item.exile_instead_of_graveyard,
                    verb="was countered by the rules",
                )
            return
        # …and the rule's last sentences, for the object that does resolve:
        # "Illegal targets, if any, won't be affected by parts of a resolving
        # spell's effect for which they're illegal." Asked of the announcement,
        # once, here — each slot the gate above judged illegal is rewritten to
        # name nothing before any instruction runs, so every handler meets it
        # as the departed target it already knows how to leave alone, and none
        # of them has to re-ask whether a permanent it found can still be
        # *targeted* (which none of them did).
        self.blank_illegal_resolution_targets(item)
        # …and what is left is found where it now is. A permanent that changed
        # controller while this object waited is still its target where its
        # description says so (CR 608.2b judges the description, and most say
        # nothing of a controller), so the seat beside each surviving id is
        # settled from the id again — the announcement's own query, asked a
        # second time — and the resolvers below, which look an id up on that
        # seat on purpose, find it.
        self.resettle_announced_target_seats(item)
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
            # CR 603.4's second check was made at the top of this method (CR
            # 608.2a); the context is built here, after the illegal slots were
            # blanked, so the instructions read the announcement as it stands.
            context = self._ability_execution_context(item)
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
            target_idx = self.stack_target_seat(item)
            if target_idx is None:
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
                # CR 707.10: a copy has the targets chosen for the original,
                # and a spell with several of them carries them on this
                # channel, not in the two fields above. The copy *had* the
                # list (``_copy_of_spell`` copies ``choices``) and this arm
                # did not pass it, so a Forked Shower of Coals aimed at two
                # creatures resolved as a spell with no target named - at the
                # opponent's face.
                divided_targets=item.choices.get("divided_targets"),
                choices=item.choices,
                trigger_context=item.trigger_context,
            )
            self.log.append(f"{item.card.name} (copy) resolved")
            return

        classification = classify_card(item.card)
        # "Counter target spell. **Its controller** loses 3 life." (Undermine.)
        # An instant or sorcery whose every target is a spell on the stack is
        # about that spell's controller — the seat the announcement already
        # names (``Game.stack_target_seat``), read here rather than written
        # onto the item so a target changed in response (CR 115.7) is followed.
        # A permanent spell is left alone: its seat field is an Aura's board or
        # an entry trigger's, and that trigger asks for itself
        # (``_ability_execution_context``) — so the seat rides beside the
        # item's own and only the instant-and-sorcery arm of ``_resolve_card``
        # reads it.
        self._resolve_card(
            caster_index=item.caster_index,
            card=item.card,
            classification=classification,
            target_player_index=item.target_player_index,
            stack_target_seat=self.stack_target_seat(item),
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
            owner_index=item.owner_index,
            leaves_to_exile=leaves_stack_to_exile(item),
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
        # (`handlers/_targets.frozen_that_player_seat`), so the phrase has one
        # answer whether a trigger or a mode choice bound it.
        trigger_context: dict | None = None,
        # CR 108.3: who owns the card, when that is not its caster — see
        # ``StackItem.owner_index``. The spell's card goes to *this* seat's
        # zones as it leaves the stack (CR 400.3, CR 608.2n), and a permanent
        # it becomes is this seat's card under the caster's control.
        owner_index: int | None = None,
        # CR 702.34a: the flashback cost was paid, so this card is exiled
        # "instead of putting it anywhere else" as it leaves the stack. Beside
        # ``exile_instead_of_graveyard`` (which a flashback cast carries too)
        # because the two are different sentences and one reader has to tell
        # them apart: a paid buyback contends with the graveyard rider
        # (CR 616.1) and loses to this (``_bin_spell_card``).
        leaves_to_exile: bool = False,
        # The controller of the spell(s) this one targeted, where it targeted
        # nothing else (``Game.stack_target_seat``): the player an instant or
        # sorcery is about, ahead of whatever seat rode in
        # ``target_player_index``. None for every other spell.
        stack_target_seat: int | None = None,
    ) -> None:
        caster = self.players[caster_index]
        owner_seat = caster_index if owner_index is None else owner_index
        owner = self.players[owner_seat]
        primary_type = card.primary_type

        if primary_type in {"land", "creature", "artifact", "enchantment", "planeswalker"}:
            permanent = Permanent(card=card)
            if x_value is not None:
                permanent.metadata["cast_x_value"] = x_value
            # A "copy as it enters" permanent (Clone) records the chosen copy
            # target so initialization can copy the player-selected creature
            # rather than an arbitrary one — with the id the stack stamped
            # beside the slot, because the slot is a position the board may
            # have renumbered since the cast (``_resolve_copy_target``).
            if target_permanent_index is not None:
                chosen_id = (
                    target_permanent_id[0]
                    if isinstance(target_permanent_id, list) and target_permanent_id
                    else target_permanent_id
                )
                permanent.metadata["copy_target"] = (
                    target_player_index if target_player_index is not None else caster_index,
                    target_permanent_index,
                    chosen_id if isinstance(chosen_id, int) else None,
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
            # CR 400.7a: an effect that changed this spell's colour on the
            # stack "continue[s] to apply to the permanent that spell
            # becomes". The spell's record ended with the spell, so a Lace cast
            # at a Grizzly Bears spell logged "became R" and put a green Bears
            # onto the battlefield (the five Laces and Ersatz Gnomes). Carried
            # here for the reason the kicked stamp below is: before the
            # permanent enters, so whatever reads its colour as it arrives
            # reads the colour it arrives with — and with the effect's own
            # duration and timestamp (``color_changes``).
            carry_spell_color_change(choices, permanent)
            # "If this creature **was kicked**, it enters with …" / "When this
            # creature enters, **if it was kicked**, …" / "…if this creature
            # **wasn't kicked**, sacrifice it" (Skizzik, turns later). CR
            # 702.33d settled the answer at the announcement and the stack item
            # carried it; it is copied onto the permanent here because the
            # permanent is what all three sentences are asked of and the stack
            # item is gone by the time the last of them is.
            #
            # Stamped **before** the permanent enters, for the creature type's
            # reason below: an entry replacement (CR 614.1c) reads it as the
            # permanent arrives. And only here, the one entry that is a cast
            # (CR 701.5a) -- a reanimated, blinked or token-copied permanent
            # never passes this line, which is the rule rather than an
            # omission: it was not cast, so it was not kicked.
            if kicked(card, choices):
                permanent.metadata[KICKED] = True
                # ...and **which** of its kicker costs paid for it
                # (CR 702.33b: a Battlemage prints two). "If it was kicked with
                # its {1}{G} kicker" is CR 702.33f's question about one of
                # them, asked of the permanent for the same reason the flag
                # above is. A tuple of the recorded keys, so the entry trigger
                # and the announcement that paid name a cost by one string.
                permanent.metadata[KICKED_WITH] = kickers_paid(card, choices)
            # "…where X is **the discarded card's mana value**." (Dralnu's
            # Pet.) What the spell's cost discarded, as the one number an entry
            # replacement may read back — see
            # ``cast_costs.CAST_COST_DISCARD_MANA_VALUE`` for why it is the
            # number and why it is stamped here. Exactly one card, or no
            # stamp: "the discarded card" names nothing else.
            cost_discards = (choices or {}).get("discarded_for_cost") or ()
            if len(cost_discards) == 1:
                permanent.metadata[CAST_COST_DISCARD_MANA_VALUE] = int(
                    getattr(cost_discards[0], "cmc", 0) or 0
                )
            # "…the controller of **the permanent it becomes** sacrifices it at
            # the beginning of the next cleanup step" (Mirage's flash Auras).
            # The answer was frozen as the spell was announced, because that is
            # the only moment CR 601.3d's timing can be read; carried onto the
            # permanent here because the permanent is what the sentence acts on
            # and the stack item is gone by the time the cleanup step looks.
            if (choices or {}).get(CAST_AT_INSTANT_SPEED):
                permanent.metadata[CAST_AT_INSTANT_SPEED] = True
            # "As an additional cost to cast this spell, choose a creature
            # type." (Caller of the Hunt.) The word was chosen at CR 601.2b and
            # rode the stack item; it is copied onto the permanent here because
            # the permanent is what the card's other line reads it off
            # ("creatures of the chosen type"), through the same
            # ``chosen_creature_type`` metadata key An-Zerrin Ruins' *entry*
            # choice writes — one key, so `subject_filters` has one reader
            # whichever step of CR 601 or CR 614 made the choice.
            #
            # Stamped **before** the permanent enters, which is the whole of
            # what makes this a cast-time cost rather than an entry effect: the
            # characteristic-defining P/T is computed from the moment the
            # permanent is on the battlefield (CR 604.3, CR 613.1), and a
            # creature that arrived without its word would be a 0/0 that
            # CR 704.5f bins before anyone could answer a prompt. It is also
            # why a Caller of the Hunt put onto the battlefield *without being
            # cast* is that 0/0 — correctly: no cast, no CR 601.2b, no type.
            chosen_creature_type = (choices or {}).get("chosen_creature_type")
            if chosen_creature_type:
                permanent.metadata["chosen_creature_type"] = chosen_creature_type
            # CR 108.3: a permanent spell cast out of another seat's zone
            # (Grinning Totem) enters under its caster's control and is still
            # its owner's card. ``owner_index_of`` otherwise answers with the
            # seat it entered under, so it would die into the caster's
            # graveyard (CR 400.3). The channel reanimation and Desertion
            # already write for the same reason; stamped before the entry so an
            # entry replacement that sends it "to its owner's graveyard instead"
            # reads the right owner too.
            if owner_seat != caster_index:
                permanent.metadata["owner_player_index"] = owner_seat
            self._put_permanent_onto_battlefield(
                caster_index, permanent, target_player_index,
                was_cast=True, from_zone=cast_from_zone,
                # …and a land that came down this road was played, not cast
                # (CR 305.1) — the same road, so the same flag, and this one
                # beside it for the two readers that mean a *spell*.
                played_as_land=primary_type == "land",
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
            if not is_aura and copy_on_enter_type(
                compile_card_oracle(card).normalized_text or ""
            ) is not None:
                # **The cast's target was the object to copy.** A permanent
                # that offers a copy choice as it enters (Clone, Vesuvan
                # Doppelganger, Copy Artifact — CR 707.5's "as a copy", a
                # CR 614.1c replacement) announces *that* at cast:
                # ``targeting._cast_target_spec`` raises the copy picker in
                # place of an entry trigger's. So whatever entry trigger the
                # copied object brings (CR 707.5) was announced by nobody, and
                # handing it the cast's target would aim it at the creature
                # that was copied — a Clone of Man-o'-War bouncing the
                # Man-o'-War. It chooses its own as it is put on the stack
                # (CR 603.3d), exactly as the same trigger does on an entry
                # nothing cast.
                self._apply_self_enters_battlefield_triggers(
                    caster_index, permanent, None, None, None,
                    targets_announced=False,
                )
            elif not is_aura:
                # ...and a cast that announced **nothing** — a headless or
                # scripted cast with no picker in front of it — is the same
                # "nobody chose" as an entry nothing cast. Handed in as if it
                # were an announcement, the inline path fell back to scanning
                # the *caster's* board: a bare Nekrataal destroyed its
                # caster's Savannah Lions and a bare Ravenous Rats made its
                # caster discard.
                announced = any(
                    value is not None
                    for value in (
                        target_player_index, target_permanent_index,
                        target_permanent_id, stack_target,
                    )
                )
                self._apply_self_enters_battlefield_triggers(
                    caster_index, permanent, target_player_index,
                    target_permanent_index, target_permanent_id,
                    targets_announced=announced,
                    # "When this creature enters, counter target spell" (Mystic
                    # Snake): the spell the cast named. It was dropped here, so
                    # the trigger named nothing and countered the top of the
                    # stack whichever spell the caster had picked.
                    target_stack_item=stack_target,
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
                self.put_card_into_graveyard(owner, card)
                self.log.append(f"{card.name} had no legal target and was put into {owner.name}'s graveyard")
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
                # "Whenever an opponent **plays** a land" (Dirtcowl Wurm).
                # CR 305.1's special action, announced here because here is
                # where it happens — `_process_land_enters` above is the
                # *entry*, which a land put onto the battlefield by an effect
                # also makes and this one does not.
                #
                # ``event_subject_player`` beside ``seat``: the first is the
                # one key every reader of a printed "**that player**" asks for
                # (CR 603.10) and the second is what this event's own filter
                # compares against the observer. Horn of Greed's "that player
                # draws a card" is a different seat on every land drop, and
                # nothing on a board records who played one — so the freeze has
                # to happen here, where it is known.
                # ``played_permanent_id`` is what "**another** land" (City of
                # Traitors) is compared against. The entry above has already
                # happened, so a land whose own trigger watches land drops is
                # on the battlefield and observing by the time this is
                # announced — and the exclusion cannot be answered from
                # ``card``, because a deck repeats one immutable
                # ``CardDefinition`` per copy and a second printing of the same
                # land would read as the first. CR 400.7's id is the identity.
                emit(
                    self, "land_played", subject=card, seat=caster_index,
                    event_subject_player=caster_index,
                    played_permanent_id=permanent.permanent_id,
                )
                # "When **you play a card**" (Juju Bubble). CR 701.18b's other
                # half: a land is played rather than cast, so the cast
                # announcement never reaches it. Beside `_process_land_enters`
                # rather than beside the `lands_played_this_turn` bump above,
                # because that bump is inside the cost-enforcement branch and
                # a land played in a game with costs off is still a land
                # played.
                emit(self, "you_play_card", subject=card, caster_index=caster_index)
            return

        # Sorceries and instants resolve immediately in this basic engine.
        target_idx = (
            stack_target_seat if stack_target_seat is not None
            else target_player_index if target_player_index is not None
            else self._spell_default_seat(caster_index)
        )
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
                    # The seat the card is binned to: its owner's (CR 608.2n),
                    # under the key the finishing step has always read.
                    pending_woc.data["_spell_caster_index"] = owner_seat
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
            # CR 608.2n: "into its **owner's** graveyard" — the caster's only
            # when the caster owns it.
            self._bin_spell_card(
                owner, card,
                exile_instead=exile_instead_of_graveyard or first_pass["ends_turn"],
                verb="resolved",
                # CR 702.27a's second static ability, asked here because "as it
                # resolves" is exactly this step and nowhere else. The answer is
                # the announcement this cast made, which by now survives only on
                # the stack item's own record (CR 500.5 emptied the pool).
                hand_instead=buyback_paid(card, choices),
                # Which exile this is, for the one case where it matters: a
                # flashback cast and a turn that ended take the card whatever
                # was paid; a graveyard rider is one of two replacements over
                # the same move, and the spell's controller chooses (CR 616.1).
                exile_is_final=bool(leaves_to_exile or first_pass["ends_turn"]),
                chooser_index=caster_index,
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
