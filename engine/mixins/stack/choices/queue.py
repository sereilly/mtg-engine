"""The queue every pending choice waits on: arming, waiting, answering.

One list holds every decision a seat owes (``Game.pending_choices``), and this
is the half of the package that knows nothing about what any particular prompt
is. ``arm_pending_choice`` queues a choice — or, for a seat nobody is asking
and a ``default_at_arm`` kind, takes its default on the spot — and stamps the
stack object and the seat whose resolution armed it. ``resolve_pending_choice``
and ``take_choice_default`` answer it through the kind's one registered
resolver, take the answered choice off the queue (``_close_answered_choice``)
and resume the loop it suspended. ``effect_suspended``,
``stack_item_is_waiting``, ``iter_pending_prompts`` and ``waiting_prompt`` are
what the rest of the engine asks about time: whether a loop has to stop, whether
an object is still resolving, whether anybody may receive priority (CR 608.2,
CR 117.3b). Both queues are read here — a replacement suspended on a decision
(``engine/replacement_choices.py``) is a prompt like any other: it holds the
object it was offered during, suspends the loop its event was a step of, and is
answered inside the same envelope (``_answer_pending_choice``).

The families of prompt are the mixins beside this one; the package docstring
lists them, and ``table.py`` registers every kind.
"""

from __future__ import annotations

from ....destruction_events import destruction_finished
from ....entry_awaiting import ENTRY_EVENT, awaited_entries
from ....pending_choices import CHOICE_SPECS, PendingChoice, spec_for
from ....replacement_choices import (CAUSE_SEAT, RESOLVING_TARGETS, pending_choices_for,
                                     stamp_draw_of, stamp_resolving)
from ....resumption import resume_after_answer


class PendingChoicesMixin:
    # -- The queue ----------------------------------------------------------
    #
    # One list holds every decision a seat owes. ``kind`` selects the spec that
    # says how to answer it; nothing here knows what any particular prompt is.

    def arm_pending_choice(self, kind: str, player_index: int, **data) -> PendingChoice | None:
        """Queue a choice for *player_index*, or take its default now.

        Returns the queued choice, or None when the seat is not interactive and
        the kind is one whose default is taken at once (``default_at_arm``) —
        the prompts that interrupt a resolution which has to finish. Every other
        kind stays queued for every seat and is drained by
        ``auto_resolve_pending_choices``."""
        spec = spec_for(kind)
        choice = PendingChoice(kind=kind, player_index=player_index, data=dict(data))
        # A prompt being armed has not been answered, whatever its data was
        # copied from. A chain of prompts carries one payload forward from
        # answer to answer (the auction's round, ``_offer_next_bid``), and the
        # answer path stamps ``_answered`` on a choice *before* its resolver
        # runs — so the copy the resolver took carried the stamp into the next
        # prompt, which then did not suspend. Nothing read that while an
        # auction was the last step of its spell (Illicit Auction); Mages'
        # Contest has a step behind it, and "if you win the bidding" ran after
        # the first raise, before anybody had won.
        choice.data.pop("_answered", None)
        if not self.asks_a_person(player_index) and (
            spec.default_at_arm or self._an_entry_nobody_waits_for()
        ):
            spec.default(self, choice)
            return None
        # Which stack object is still resolving because of this prompt. Stamped
        # here rather than by each arming site, because the sites are handlers
        # that know nothing about the stack — and because the prompt that keeps
        # a resolution open is often armed by the *answer* to an earlier one.
        # A prompt that blocks nothing is a notification the game carries on
        # around (`hand_reveal`), so it never holds an object on the stack.
        if (
            self.resolving_stack_item is not None
            and spec.holds_priority
            and "_stack_item" not in choice.data
        ):
            choice.data["_stack_item"] = self.resolving_stack_item
        # Which seat's spell or ability armed this prompt (CR 109.5). Stamped
        # here for the same two reasons `_stack_item` is: the arming sites are
        # handlers that know nothing about the stack, and the prompt that a
        # resolution owes is often armed by the *answer* to an earlier one.
        #
        # Read at arm time and not at answer time, because by the time a seat
        # answers, the resolution that armed the prompt has returned and
        # `resolving_seats` is empty — which reads as "nothing caused this".
        # Psychic Purge is the card that notices: "when a spell or ability an
        # opponent controls causes you to discard this card" is a question about
        # the seat that armed the discard, asked from inside the answer.
        #
        # What the resolving object targets is stamped beside it, for the same
        # reason: Bronze Horse's "spells that target it" is asked inside the
        # answer too (``replacement_choices.stamp_resolving``).
        stamp_resolving(self, choice)
        # A queued choice of a ``suspends`` kind is itself the suspension: the
        # steps behind it in this resolution have not run, and running them now
        # would let them see a board the answer has not shaped yet (Opt drawing
        # the card its own scry has not arranged). ``effect_suspended`` reads the
        # queue, so appending here is what stops the loop and nothing sets a
        # flag. Nothing is waiting on a default taken inline above — that already
        # happened.
        #
        # A prompt a *draw* armed says so (CR 121.2): the draws behind that one
        # wait for it, whichever queue it sits on — see
        # ``DrawsAndDiscardsMixin._draw_prompt_open``.
        stamp_draw_of(self, choice)
        self.pending_choices.append(choice)
        return choice

    # -- Whether a loop has to stop ----------------------------------------

    @property
    def effect_suspended(self) -> bool:
        """Whether some loop mid-event has to stop and wait (engine/resumption.py).

        Derived from the queue rather than stored, because a stored boolean can
        only say *that* something is owed, not *how many*. "Each opponent
        discards two cards" arms one prompt per opponent; the first answer
        cleared the flag and the resolution ran on past opponents who had not
        discarded yet. Every queued choice of a ``suspends`` kind that has not
        been answered holds the suspension, so the last answer is what lifts it.

        ``_answered`` is stamped by the answer paths below for the span of the
        resolver: the choice stays *queued* while its answer is applied — the
        stack object it holds is still resolving (CR 608.2), and a resolver may
        still read its payload — but it no longer suspends, because applying the
        answer is exactly the work the suspension was waiting for.

        The question about the whole queue: whether *anything* is owed. A loop
        deciding whether its own step stopped asks :meth:`suspended_beyond`
        instead.

        **Both queues.** A replacement suspended on a decision (CR 614,
        ``engine/replacement_choices.py``) has taken its event away until the
        answer — the draw is not drawn, the damage not dealt, the discarded
        card in no zone — so the steps behind that event wait for it exactly
        as they wait for a scry. Every offer on that queue suspends, and none
        needs ``_answered``: its answer path takes it off the queue before
        applying it. Left out, "draw two cards, then discard a card" (Catalog)
        under Obstinate Familiar asked for the discard with the draw still
        undecided.

        **And an entry waiting for its "as it enters" choice** (CR 614.12a,
        ``engine/entry_awaiting.py``), whatever kind its prompt is: the
        permanent is not on the battlefield until the answer, so the steps
        behind the one that put it there — "…return it to the battlefield.
        It gains haste" — wait for it as they wait for a scry, and resume once
        the answer has completed the entry (``_finish_answered_entries``)."""
        return bool(self.owed_suspensions())

    def owed_suspensions(self) -> tuple:
        """The suspending choices owed right now, on either queue, as a
        snapshot a loop takes before running one of its steps
        (``engine/resumption.run_resumable``)."""
        return tuple(
            choice for choice in self.pending_choices
            if spec_for(choice.kind).suspends and not choice.data.get("_answered")
        ) + tuple(self.pending_replacement_choices) + awaited_entries(self)

    def suspended_beyond(self, owed: tuple) -> bool:
        """Whether a suspending choice is owed that was **not** in *owed* — a
        decision the step just run asked for, which is what stops its loop.

        Not :attr:`effect_suspended`, which is every decision owed anywhere. A
        loop that starts while some *other* resolution is waiting on an answer
        is not a step of that resolution: a mana ability tapped to pay an
        offer resolves immediately (CR 605.3a), and on a table nothing holds a
        resolution for (``_settle`` with no seat to wait for) the next object
        on the stack resolves while the last one's prompt is still queued. Read
        through the whole queue, either one stopped after its first step and
        left the rest of itself to run whenever the *other* prompt was answered
        — a painland's damage dealt after the offer it paid for, and Tranquil
        Path's "Draw a card." and trip to the graveyard waiting on Ice Cave's
        offer about it. Identity, not equality: two seats can owe look-alike
        choices."""
        return any(
            not any(choice is earlier for earlier in owed)
            for choice in self.owed_suspensions()
        )

    def permanent_is_entering(self, permanent) -> bool:
        """Whether *permanent* still owes somebody a choice that is part of it
        entering the battlefield (CR 614.1c).

        Stamped by ``_initialize_permanent_state``, read by the state-based
        sweep: a permanent that has not finished entering has no settled
        characteristics, so CR 704.5f has nothing to test yet. Identity, not
        equality — two look-alike permanents entering together are two
        permanents (CR 400.7)."""
        return any(
            choice.data.get("_entering_permanent") is permanent
            and spec_for(choice.kind).open_for(self, choice)
            for choice in self.pending_choices
        )

    def pending_choices_of(self, kind: str, player_index: int | None = None) -> list[PendingChoice]:
        """Queued choices of *kind*, oldest first, optionally for one seat."""
        return [
            choice
            for choice in self.pending_choices
            if choice.kind == kind
            and (player_index is None or choice.player_index == player_index)
        ]

    def pending_choice_of(self, kind: str, player_index: int | None = None) -> PendingChoice | None:
        """The oldest queued choice of *kind*, or None."""
        found = self.pending_choices_of(kind, player_index)
        return found[0] if found else None

    def discard_pending_choice(self, choice: PendingChoice) -> None:
        """Drop *choice* from the queue — the answer has been applied, or the
        thing it was about is gone. Identity, not equality: two seats can owe
        the same-looking choice."""
        before = len(self.pending_choices)
        self.pending_choices = [c for c in self.pending_choices if c is not choice]
        # A prompt an event stamped, dropped without an answer re-joining it
        # (CR 603.6a): if it was the last thing the event waited on, the
        # event closes now. Inert inside the answer — the re-join closes it.
        event = choice.data.get(ENTRY_EVENT)
        if event is not None and len(self.pending_choices) != before:
            self.close_entry_event_if_settled(event)

    def clear_pending_choices(self, kind: str, player_index: int | None = None) -> None:
        for choice in self.pending_choices_of(kind, player_index):
            self.discard_pending_choice(choice)

    # -- The stack object a prompt belongs to -------------------------------
    #
    # A prompt armed while something was resolving carries that stack object
    # (``_stack_item``, stamped in ``arm_pending_choice``). The object stays on
    # the stack until nothing it armed is queued any more, which is what makes
    # "the ability is still resolving" a property of the queue instead of three
    # kinds named by hand in ``pass_priority``.

    def choices_for_stack_item(self, item) -> list[PendingChoice]:
        """Queued prompts belonging to *item*'s resolution, oldest first on
        each queue — the prompt queue's, then the CR 614 queue's (a replacement
        suspended on a decision is stamped the same way, in
        ``replacement_choices.offer_replacement_choice``).

        Identity, not equality: two stack objects can look alike (two copies of
        one spell), and a resolution that answered to a look-alike's prompts
        would leave the wrong one on the stack."""
        return [
            c for c in (*self.pending_choices, *self.pending_replacement_choices)
            if c.data.get("_stack_item") is item
        ]

    def announcement_choice_for(self, item):
        """The choice *item* made as it was **announced**, still unanswered.

        The other half of the pair above, and separate from it on purpose. A
        prompt armed while an object resolved carries ``_stack_item`` and means
        "the resolution is not finished"; a mode (CR 601.2b, CR 603.3c) and a
        target (CR 601.2c, CR 603.3d) are chosen *before* the object is
        announced, carry ``_trigger_item``, and mean something stronger — the
        object has not finished being put on the stack and must not resolve at
        all.

        One reader for both kinds that carry ``_trigger_item``, so a third
        added later is covered by the data it arms with rather than by an edit
        here.
        """
        for choice in self.pending_choices:
            if choice.data.get("_trigger_item") is item:
                return choice
            # …and CR 603.3b's, which is one choice about several objects:
            # the order a seat puts its simultaneous triggers on the stack in
            # (``engine/trigger_order.py``). Until it is made, none of them has
            # finished being put there. Only while it is still a choice — two
            # of them on the stack — or an object left alone by the others
            # leaving would be held for a question nobody can answer.
            if any(
                member is item for member in choice.data.get("_trigger_items") or ()
            ) and spec_for(choice.kind).open_for(self, choice):
                return choice
        return None

    def stack_item_is_waiting(self, item) -> bool:
        """Whether *item*'s resolution still owes somebody a decision."""
        return any(
            spec_for(c.kind).open_for(self, c) for c in self.choices_for_stack_item(item)
        )

    def holds_for_answers(self) -> bool:
        """Whether a resolution that stops to ask holds its object on the
        stack at this table (CR 608.2) — the ``pause_for_choices`` every loop
        that resolves the stack passes, derived here once.

        Two tables have somebody to hold for. One with an interactive seat,
        whose answer arrives on a later request (the web). And one with a
        ``prompt_driver`` (the AI simulator), whose answer is taken before
        anything else happens: the object waits on the stack, the driver
        answers, the answer releases it (``_release_stack_item``: the
        state-based check, priority, the abilities its destructions set off)
        — the same road the web's answer takes. The simulator used to resolve
        straight through and answer afterwards, so the object had left the
        stack, a state-based check had been made and the destruction triggers
        announced before the driver answered: 154 of 1,260 driven resolutions
        across eight seeded Legions/Onslaught games armed a prompt that held
        nothing, and in 3 the check acted first.

        A bare headless ``Game`` (no driver, nobody interactive) holds nothing:
        its prompts stay queued for the caller to drain once the engine call
        returns, which is what the tests reading that queue are written
        against (``_settle``)."""
        return bool(self.interactive_seats) or self.prompt_driver is not None

    def _an_entry_nobody_waits_for(self) -> bool:
        """Whether a prompt armed now is an "as it enters" choice (CR 614.1c)
        at a table that holds nothing (:meth:`holds_for_answers`) — which
        takes its default as it is armed, whatever its kind.

        CR 614.12a: "that choice is made before the permanent enters the
        battlefield." At a table that holds for answers the entry waits on its
        way until the last one (``engine/entry_awaiting.py``); here nothing
        waits, and the permanent enters the moment its entry state is done.
        Every entry prompt kind of its own is ``default_at_arm`` already
        (``enter_choice``, ``body_choice``, ``entry_exile``, ``entry_reveal``);
        a kind shared with a resolution (``number_choice``: Shapeshifter's
        number and the life Phyrexian Processor and Minion of the Wastes pay,
        beside Tetravus's counters) stayed queued, so the permanent entered
        with the stamped default and a prompt still owed about it — answered
        afterwards, it changed the permanent after it had entered.

        ``entries_in_progress`` holds a record only while an entry state is
        being performed, at a table like this one (``_enter_battlefield``)."""
        return bool(self.entries_in_progress) and not self.holds_for_answers()

    def resolution_waiting(self) -> bool:
        """Whether some object on the stack is part-way through resolving and
        waiting on an answer (CR 608.2) — in which case nothing else resolves,
        nobody receives priority and no state-based check is made until the
        answer is in (CR 704.3 names no moment inside a resolution). Asked of
        the whole stack, not its top: an answer that sets off a trigger puts
        it above the object still waiting on the next answer."""
        return any(
            getattr(item, "resolution_held", False)
            and self.stack_item_is_waiting(item)
            for item in self.stack
        )

    def _release_stack_item(self, item, force: bool = False) -> None:
        """Take a held stack object off the stack once its resolution is done.

        No-op while any prompt it armed is still queued — an answer can arm the
        next step's prompt (Sanctum of All's "you may search" arms the search),
        and popping between the two would report the ability as resolved with
        the player still owing a decision. Word of Command keeps its prompt
        queued past the answer on purpose (``is_open``), so it is *queued*, not
        *open*, that holds the object here; the ability that finishes it removes
        it itself. ``force`` is the priority path's backstop, releasing an object
        whose prompts went away without releasing it — and, for the same
        reason, completing an entry whose last "as it enters" prompt went away
        unanswered (``_finish_answered_entries``), which would otherwise leave
        its permanent on its way for ever."""
        if force:
            self._finish_answered_entries()
        if item is None or (not force and self.choices_for_stack_item(item)):
            return
        for index, entry in enumerate(self.stack):
            if entry is item:
                del self.stack[index]
                item.resolution_held = False
                # The end of the resolution's unit of play (CR 603.3b, 117.5):
                # one trigger window around the last step, the state-based
                # check and the destruction triggers, which takes back what the
                # resolution set off while it was held (``held_triggers``) —
                # so every one of them chooses its targets after the check.
                with self.putting_triggers_on_stack():
                    # An event this resolution opened whose loop never came
                    # back for it (CR 603.6a): what it was handed enters now,
                    # as the resolution ends, rather than never.
                    self.close_entry_events_of(item)
                    self._rejoin_held_triggers(item)
                    # The step the resolution handed over (a spell's CR 608.2n
                    # bin) — run after the object has left the stack, so the
                    # card is in exactly one zone at every moment a client can
                    # see.
                    tail, item.finish_resolution = item.finish_resolution, None
                    if tail is not None:
                        tail()
                    # A spell's bin says the resolution finished and where the
                    # card went ("… finished resolving and moved to
                    # graveyard", ``StackItem.ending_logged``), so it is the
                    # one line, not a second.
                    if not getattr(item, "ending_logged", False):
                        self.log.append(f"{item.card.name} finished resolving")
                    # The resolution is over *now*, so what ``pass_priority``
                    # does after one that ran straight through happens here for
                    # one that stopped to ask: CR 704.3's check before anyone
                    # receives priority, and CR 117.3b's priority to the active
                    # player. The seat that owed the answer was holding the
                    # window only because it owed it.
                    self.check_state_based_actions()
                    if self.priority_player_index is not None:
                        self.priority_player_index = self.active_player_index
                        self.priority_pass_count = 0
                    # …and CR 603.3b's: the abilities this object's
                    # destructions triggered were waiting for it to finish, and
                    # it has. After the state-based check, which is the order
                    # the rule gives. See engine/destruction_events.py.
                    destruction_finished(self)
                return

    def _answer_pending_choice(self, choice: PendingChoice, apply):
        """Run one answer with the resolution it belongs to still in progress.

        Both halves matter. Keeping ``resolving_stack_item`` set means a prompt
        the answer arms inherits the same object, so a chain of decisions is one
        resolution rather than a first step that resolved and a remainder that
        happens with nothing on the stack. Releasing afterwards is the only
        place the object leaves: every answer path — a player's confirm, an AI
        seat's default — goes through here.

        **An answer is a unit of play** (``putting_triggers_on_stack``): what
        it sets off chooses its targets once it is done — after the release's
        state-based check when it was the last answer, or, while the object
        still waits on another, with that object (``held_triggers``)."""
        with self._answer_window():
            return self._answer_inside_its_window(choice, apply)

    def _answer_window(self):
        """The trigger window an answer is (:meth:`_answer_pending_choice`)."""
        return self.putting_triggers_on_stack()

    def _answer_inside_its_window(self, choice: PendingChoice, apply):
        item = choice.data.get("_stack_item")
        previous = self.resolving_stack_item
        if item is not None:
            self.resolving_stack_item = item
        # …and with the seat whose spell or ability armed it still the one
        # resolving (CR 109.5): the answer re-runs the event that asked and the
        # loop behind it (``engine/resumption.py``), and a spell reaches the
        # damage paths as its bare card, whose seat is read off
        # ``resolving_seats`` (``damage_events.damage_source_seat``). Empty by
        # the time anyone answers, so a divided Fireball that stopped to ask
        # dealt the rest of its damage as nobody's: Justice ("…deals that much
        # damage to that creature's or spell's controller") found no
        # controller, a spell's lifelink gained nobody, and "a source an
        # opponent controls" answered no. The seat the arming stamped
        # (``_cause_seat``), pushed for the answer and popped after it.
        cause_seat = choice.data.get(CAUSE_SEAT)
        pushed = isinstance(cause_seat, int) and not isinstance(cause_seat, bool)
        if pushed:
            self.resolving_seats.append(cause_seat)
        # And what that object targets (CR 115.1), for the same reason: "by
        # spells that target it" (Bronze Horse) is asked of the re-run event,
        # and with nothing pushed a Horse whose own static its controller had
        # just chosen to apply first was dealt the Bolt's damage.
        targets = choice.data.get(RESOLVING_TARGETS)
        pushed_targets = isinstance(targets, tuple)
        if pushed_targets:
            self.resolving_targets.append(targets)
        try:
            # A prompt a draw armed is answered inside that draw (CR 121.2):
            # the draws parked behind it are released here, with the object
            # they belong to still resolving, so a prompt one of *them* arms
            # holds the same object. Inert for every other prompt.
            #
            # …and a prompt armed while an event was putting permanents onto
            # the battlefield is answered inside that event (CR 603.6a): what
            # the answer puts down joins the rest, and the event closes at its
            # last answer (``ZoneFunnelsMixin.rejoining_entry_event``).
            with self.rejoining_entry_event(choice), self.answering_draw_prompt(choice):
                answered = apply()
        finally:
            if pushed:
                self.resolving_seats.pop()
            if pushed_targets:
                self.resolving_targets.pop()
            self.resolving_stack_item = previous
        # An answer is a step of a resolution (CR 608.2), so the resolution
        # seam's recompute (``resolve_top_of_stack``) is owed here too: the
        # colour a player has just named for Prismatic Lace decides which
        # colour-scoped statics reach the permanent, and the next reader may
        # be the next prompt of the same resolution, on screen. The release
        # below ends in a state-based check — which recomputes — only for the
        # *last* answer of an object the priority path was holding.
        if answered:
            self._recompute_continuous_effects()
        if item is not None:
            self._release_stack_item(item)
        if item is None or not item.resolution_held:
            # The resolution this answer belonged to is over — or no object
            # was held for it (a headless table arms its prompts against an
            # empty stack) — so what its destructions triggered goes on the
            # stack (CR 603.3b). While the object is still held on a later
            # prompt they keep waiting with it. See
            # engine/destruction_events.py.
            destruction_finished(self)
        return answered

    def resolve_pending_choice(self, kind: str, player_index: int, **response) -> bool:
        """Answer the oldest pending choice of *kind* owed by *player_index*.

        False means there was nothing to answer or the answer was rejected; a
        rejected answer leaves the prompt queued, so a malformed request can
        never silently drop one."""
        choice = self.pending_choice_of(kind, player_index)
        if choice is None:
            return False
        return self._answer_pending_choice(
            choice, lambda: self._apply_choice_answer(choice, response)
        )

    def _apply_choice_answer(self, choice: PendingChoice, response: dict) -> bool:
        spec = spec_for(choice.kind)
        if not spec.suspends:
            accepted = bool(spec.resolve(self, choice, response))
            if accepted:
                self._close_answered_choice(choice)
                self._after_an_entry_answer()
            return accepted
        # This choice stops suspending *before* the answer is applied, never
        # after: applying it can arm the next prompt, and lifting afterwards
        # would resume straight through that one.
        choice.data["_answered"] = True
        try:
            accepted = bool(spec.resolve(self, choice, response))
        except Exception:
            choice.data.pop("_answered", None)
            raise
        if not accepted:
            # Rejected — the prompt is owed exactly as it was, suspension and all.
            choice.data.pop("_answered", None)
            return False
        self._close_answered_choice(choice)
        # The entry this answer completes goes onto the battlefield *before*
        # the loop behind it resumes (CR 614.12a, ``engine/entry_awaiting.py``).
        self._finish_answered_entries()
        resume_after_answer(self)
        self._settle_resumed_resolution()
        return True

    def _after_an_entry_answer(self) -> None:
        """For an answer of a kind that does not suspend: complete the entry
        it was the last choice of, and — since a waiting entry is itself an
        owed suspension — resume the loop that put the permanent there."""
        if self._finish_answered_entries():
            resume_after_answer(self)

    def _close_answered_choice(self, choice: PendingChoice) -> None:
        """Take an answered *choice* off the queue, if its resolver did not.

        An answer that was accepted has been applied, so the seat no longer
        owes it — and a choice left queued says it does. ``waiting_prompt`` and
        ``blocking_prompt`` read the queue, so the game refused every further
        action by the seat that had just answered (CR 117.3b), and
        ``_release_stack_item`` reads it too, so the object the prompt held
        never left the stack (CR 608.2). ``_resolve_pay_any_amount`` was that
        resolver (Urza's Destiny); AI and headless play never showed it,
        because ``auto_resolve_pending_choices`` drops a defaulted choice
        itself.

        Here, once, rather than trusted to each resolver: every resolver still
        drops its own choice where its own steps need it gone, and this is the
        guarantee behind them. It runs after the resolver and **before** the
        steps behind the answer resume and before the object is released —
        a discard any later (in ``resolve_pending_choice``, after
        ``_answer_pending_choice`` returns) comes after the release has already
        declined to let the object go.

        Only a choice still *open*: Word of Command records its caster's answer
        and keeps the closed choice queued on purpose (``is_open``), which is
        what holds its spell on the stack until the ability that finishes it
        removes it. The CR 614 queue needs nothing here — its answer path
        (``resolve_replacement_choice``) takes the choice off before applying
        it. ``tests/regressions/test_kg_prompts_answered_choice_leaves_queue.py``
        is the census over every kind.
        """
        if spec_for(choice.kind).open_for(self, choice):
            self.discard_pending_choice(choice)

    def take_choice_default(self, choice: PendingChoice) -> None:
        """Apply the deterministic answer a non-interactive seat gives."""
        self._answer_pending_choice(choice, lambda: self._apply_choice_default(choice))

    def _apply_choice_default(self, choice: PendingChoice) -> bool:
        spec = spec_for(choice.kind)
        if not spec.suspends:
            spec.default(self, choice)
            self._close_answered_choice(choice)
            self._after_an_entry_answer()
            return True
        choice.data["_answered"] = True
        try:
            spec.default(self, choice)
        except Exception:
            choice.data.pop("_answered", None)
            raise
        self._close_answered_choice(choice)
        self._finish_answered_entries()
        resume_after_answer(self)
        self._settle_resumed_resolution()
        return True

    def _settle_resumed_resolution(self) -> None:
        """CR 704.3 for a resolution that finished on an *answer*.

        State-based actions are checked before a player would receive priority
        after a spell or ability resolves. The priority pass does that for a
        resolution that runs straight through — but one that stops to ask
        (a scry, a search) ran that check at the suspension point, and the
        steps behind the answer had nowhere to be checked at all. "Scry 1. Draw
        a card." (Opt) is the shape that showed it: the draw is in the resumed
        tail, the draw record grew, and the sweep that turns the record into
        "whenever you draw a card" (Tolarian Kraken) never ran, so the trigger
        waited for whatever next happened to check state. Nothing to do while
        the resumption suspended again — the next answer settles it — nor
        while the object is still held waiting on another decision it armed
        (``resolution_waiting``): that resolution is not over, and its release
        makes the check (``_release_stack_item``).
        """
        if self.effect_suspended or self.resolution_waiting():
            return
        self.check_state_based_actions()

    def auto_resolve_pending_choices(
        self, only_player_index: int | None = None, kinds=None
    ) -> None:
        """Take the default for queued choices — the AI / headless path.

        ``kinds`` restricts and *orders* the drain. Order is load-bearing where
        a default consumes randomness (a library search shuffles), so the
        seeded simulator names the kinds it drains rather than taking queue
        order. Draining repeats while it makes progress, because answering one
        choice can arm the next."""
        wanted = tuple(kinds) if kinds is not None else None
        for _ in range(self.MAX_SETTLE_ITERS):
            progressed = False
            for kind in wanted if wanted is not None else self._queued_kinds():
                for choice in self.pending_choices_of(kind, only_player_index):
                    # Answered already, by a drain *inside* an earlier answer
                    # of this very loop: a default can resolve something, and
                    # at a table with a `prompt_driver` the engine drains
                    # again from in there. The list being walked is a
                    # snapshot, so without this the choice's default would be
                    # applied a second time.
                    if not any(queued is choice for queued in self.pending_choices):
                        continue
                    self.take_choice_default(choice)
                    # The answer funnel has taken the choice off the queue
                    # (``_close_answered_choice``) unless it is one kept queued
                    # closed on purpose; dropping it here as well is what
                    # guarantees this loop terminates whatever a default does.
                    self.discard_pending_choice(choice)
                    progressed = True
            if not progressed:
                return

    def drive_owed_prompts(self) -> bool:
        """Hand every queued prompt to ``prompt_driver``; True when it answered any.

        The seam a driver with no interactive seat answers through, called by
        the engine at the two places it decides what happens next on the stack
        (``_resolve_priority_window``, ``_settle``) — so the answer to a prompt
        is taken before the next object resolves and before the step that
        armed it ends, rather than whenever the driver's own loop next comes
        round, and with the object that armed it still held on the stack
        (``holds_for_answers``, CR 608.2): the answer is what releases it.
        Inert without a driver, and inert at a table with a human at it: there
        the web layer's own loops decide who is asked.

        "Answered any" is read off the queue rather than reported by the
        driver, so a driver that declines a kind it does not know is seen as
        having made no progress and the caller's loop ends instead of spinning.
        """
        driver = self.prompt_driver
        if driver is None or self.interactive_seats or not self.pending_choices:
            return False
        # Not re-entrant: an answer can itself resolve something (a default
        # that casts, a search that triggers), which comes back through here
        # with the outer drain half-way down its list. The outer one finishes.
        if self.driving_prompts:
            return False
        before = [id(choice) for choice in self.pending_choices]
        self.driving_prompts = True
        try:
            driver(self)
        finally:
            self.driving_prompts = False
        return [id(choice) for choice in self.pending_choices] != before

    def iter_pending_prompts(self):
        """Every decision anyone currently owes, as ``(spec, choice)`` pairs in
        registration order.

        Spans both queues: a replacement effect suspended on a decision (CR 614)
        is a prompt like any other, and ``ReplacementChoice`` carries the same
        kind / player_index / data attributes, so nothing downstream needs to
        know which queue an entry came from."""
        for kind, spec in CHOICE_SPECS.items():
            for choice in self.pending_choices_of(kind):
                yield spec, choice
            for choice in pending_choices_for(self, kind):
                yield spec, choice

    def waiting_prompt(self, player_index: int | None = None):
        """The first open decision the game is waiting on, or None.

        The question about *time*, where ``iter_pending_prompts`` is the whole
        queue and ``blocking_prompt`` is about one action: while this answers,
        no step advances and nobody receives priority (CR 117.3b). A prompt that
        refuses nothing is a notification play carries on around
        (``hand_reveal``), which is what ``holds_priority`` reads.
        """
        return next(
            (
                choice
                for spec, choice in self.iter_pending_prompts()
                if spec.holds_priority
                and spec.open_for(self, choice)
                and (player_index is None or choice.player_index == player_index)
            ),
            None,
        )

    def auto_resolve_choice(self, choice) -> None:
        """Take one queued choice's default, whichever queue it came from."""
        self.take_choice_default(choice)
        self.discard_pending_choice(choice)

    def _queued_kinds(self) -> list[str]:
        """The kinds currently queued, in first-queued order."""
        seen: list[str] = []
        for choice in self.pending_choices:
            if choice.kind not in seen:
                seen.append(choice.kind)
        return seen

    # -- Legacy views -------------------------------------------------------
    #
    # The shapes the web layer and the tests read. Each derives its seat from
    # the queued choice rather than storing it twice, so the two cannot drift.

    @property
    def pending_search_library(self) -> dict | None:
        return self._choice_view("search_library", "caster_index")

    @property
    def pending_reorder_library(self) -> dict | None:
        return self._choice_view("reorder_library", "caster_index")

    @property
    def pending_scry(self) -> dict | None:
        return self._choice_view("scry", "caster_index")

    @property
    def pending_discard(self) -> dict | None:
        return self._choice_view("discard", "player_index")

    @property
    def pending_sacrifice(self) -> dict | None:
        return self._choice_view("sacrifice", "player_index")

    @property
    def pending_hand_reveal(self) -> dict | None:
        return self._choice_view("hand_reveal", "viewer_index")

    @property
    def pending_land_type_choice(self) -> dict | None:
        return self._choice_view("land_type_choice", "player_index")

    @property
    def pending_land_type_swap(self) -> dict | None:
        return self._choice_view("land_type_swap", "player_index")

    @property
    def pending_card_type_choice(self) -> dict | None:
        return self._choice_view("card_type_choice", "player_index")

    @property
    def pending_exiled_pile_claim(self) -> dict | None:
        return self._choice_view("exiled_pile_claim", "player_index")

    @property
    def pending_mana_payment(self) -> dict | None:
        return self._choice_view("mana_payment", "player_index")

    @property
    def pending_face_down_cast(self) -> dict | None:
        return self._choice_view("face_down_cast", "player_index")

    @property
    def pending_word_of_command(self) -> dict | None:
        return self._choice_view("word_of_command", "caster_index")

    @property
    def pending_opponent_damage(self) -> dict | None:
        return self._choice_view("opponent_damage", "chooser_index")

    @property
    def pending_enter_choice(self) -> dict | None:
        return self._choice_view("enter_choice", "controller_index")

    @property
    def pending_body_choice(self) -> dict | None:
        return self._choice_view("body_choice", "controller_index")

    @property
    def pending_optional_pays(self) -> list[dict]:
        return [
            {**choice.data, "player_index": choice.player_index}
            for choice in self.pending_choices_of("optional_pay")
        ]

    @property
    def pending_balance(self) -> dict | None:
        """Balance is owed by several seats at once, so it is several queued
        choices; the legacy view is the plan table they add up to."""
        choices = self.pending_choices_of("balance")
        if not choices:
            return None
        return {"plans": {choice.player_index: choice.data["plan"] for choice in choices}}

    def _choice_view(self, kind: str, seat_key: str) -> dict | None:
        choice = self.pending_choice_of(kind)
        if choice is None:
            return None
        return {**choice.data, seat_key: choice.player_index}

    # Upper bound on resolve/SBA cycles in one _settle() call. A genuine infinite
    # loop (a pathological card pool) is bounded here so the seeded simulator can
    # never hang; we log and break rather than raise.
    MAX_SETTLE_ITERS = 2000
