"""The queue every pending choice waits on: arming, waiting, answering.

One list holds every decision a seat owes (``Game.pending_choices``), and this
is the half of the package that knows nothing about what any particular prompt
is. ``arm_pending_choice`` queues a choice — or, for a seat nobody is asking
and a ``default_at_arm`` kind, takes its default on the spot — and stamps the
stack object and the seat whose resolution armed it. ``resolve_pending_choice``
and ``take_choice_default`` answer it through the kind's one registered
resolver, resuming the loop it suspended. ``effect_suspended``,
``stack_item_is_waiting``, ``iter_pending_prompts`` and ``waiting_prompt`` are
what the rest of the engine asks about time: whether a loop has to stop, whether
an object is still resolving, whether anybody may receive priority (CR 608.2,
CR 117.3b). Both queues are read here — a replacement suspended on a decision
(``engine/replacement_choices.py``) is a prompt like any other.

The families of prompt are the mixins beside this one; the package docstring
lists them, and ``table.py`` registers every kind.
"""

from __future__ import annotations

from ....destruction_events import destruction_finished
from ....pending_choices import CHOICE_SPECS, PendingChoice, spec_for
from ....replacement_choices import pending_choices_for, stamp_draw_of
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
        if spec.default_at_arm and player_index not in self.interactive_seats:
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
        if self.resolving_seats and "_cause_seat" not in choice.data:
            choice.data["_cause_seat"] = self.resolving_seats[-1]
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
        answer is exactly the work the suspension was waiting for."""
        return any(
            spec_for(choice.kind).suspends and not choice.data.get("_answered")
            for choice in self.pending_choices
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
        self.pending_choices = [c for c in self.pending_choices if c is not choice]

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
        """Queued prompts belonging to *item*'s resolution, oldest first.

        Identity, not equality: two stack objects can look alike (two copies of
        one spell), and a resolution that answered to a look-alike's prompts
        would leave the wrong one on the stack."""
        return [c for c in self.pending_choices if c.data.get("_stack_item") is item]

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

    def _release_stack_item(self, item, force: bool = False) -> None:
        """Take a held stack object off the stack once its resolution is done.

        No-op while any prompt it armed is still queued — an answer can arm the
        next step's prompt (Sanctum of All's "you may search" arms the search),
        and popping between the two would report the ability as resolved with
        the player still owing a decision. Word of Command keeps its prompt
        queued past the answer on purpose (``is_open``), so it is *queued*, not
        *open*, that holds the object here; the ability that finishes it removes
        it itself. ``force`` is the priority path's backstop, releasing an object
        whose prompts went away without releasing it."""
        if item is None or (not force and self.choices_for_stack_item(item)):
            return
        for index, entry in enumerate(self.stack):
            if entry is item:
                del self.stack[index]
                item.resolution_held = False
                # The step the resolution handed over (a spell's CR 608.2n
                # bin) — run after the object has left the stack, so the card
                # is in exactly one zone at every moment a client can see.
                tail, item.finish_resolution = item.finish_resolution, None
                if tail is not None:
                    tail()
                self.log.append(f"{item.card.name} finished resolving")
                # The resolution is over *now*, so what ``pass_priority`` does
                # after one that ran straight through happens here for one that
                # stopped to ask: CR 704.3's check before anyone receives
                # priority, and CR 117.3b's priority to the active player. The
                # seat that owed the answer was holding the window only because
                # it owed it.
                self.check_state_based_actions()
                if self.priority_player_index is not None:
                    self.priority_player_index = self.active_player_index
                    self.priority_pass_count = 0
                # …and CR 603.3b's: the abilities this object's destructions
                # triggered were waiting for it to finish, and it has. After
                # the state-based check, which is the order the rule gives.
                # See engine/destruction_events.py.
                destruction_finished(self)
                return

    def _answer_pending_choice(self, choice: PendingChoice, apply):
        """Run one answer with the resolution it belongs to still in progress.

        Both halves matter. Keeping ``resolving_stack_item`` set means a prompt
        the answer arms inherits the same object, so a chain of decisions is one
        resolution rather than a first step that resolved and a remainder that
        happens with nothing on the stack. Releasing afterwards is the only
        place the object leaves: every answer path — a player's confirm, an AI
        seat's default — goes through here."""
        item = choice.data.get("_stack_item")
        previous = self.resolving_stack_item
        if item is not None:
            self.resolving_stack_item = item
        try:
            # A prompt a draw armed is answered inside that draw (CR 121.2):
            # the draws parked behind it are released here, with the object
            # they belong to still resolving, so a prompt one of *them* arms
            # holds the same object. Inert for every other prompt.
            with self.answering_draw_prompt(choice):
                answered = apply()
        finally:
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
            return bool(spec.resolve(self, choice, response))
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
        resume_after_answer(self)
        self._settle_resumed_resolution()
        return True

    def take_choice_default(self, choice: PendingChoice) -> None:
        """Apply the deterministic answer a non-interactive seat gives."""
        self._answer_pending_choice(choice, lambda: self._apply_choice_default(choice))

    def _apply_choice_default(self, choice: PendingChoice) -> bool:
        spec = spec_for(choice.kind)
        if not spec.suspends:
            spec.default(self, choice)
            return True
        choice.data["_answered"] = True
        try:
            spec.default(self, choice)
        except Exception:
            choice.data.pop("_answered", None)
            raise
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
        the resumption suspended again — the next answer settles it.
        """
        if self.effect_suspended:
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
                    # Every default takes its choice off the queue; dropping it
                    # here as well is what guarantees this loop terminates even
                    # if one ever forgets.
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
        round. Inert without a driver, and inert at a table with a human at
        it: there the object is held on the stack for the answer (CR 608.2)
        and the web layer's own loops decide who is asked.

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
