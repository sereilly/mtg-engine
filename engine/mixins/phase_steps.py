from __future__ import annotations

from ._constants import _PHASE_STEPS, phases_after

class PhaseStepsMixin:
    def _resolve_priority_window(self) -> None:
        """Drain the stack for a step nobody is holding priority through.

        500.2 simplified: both players pass in succession once the stack is
        empty. CR 608.2 still applies *inside* that — a resolution that stops to
        ask an interactive seat something is not finished, so it holds its object
        on the stack and this returns with it there rather than draining the
        step's remaining triggers into a board the answer has not shaped yet. The
        caller resumes once the prompt is answered.

        With no interactive seat there is nobody to stop for: headless and AI
        play queue the same prompts and drain them deterministically afterwards,
        so those runs resolve exactly as they did. That is also what keeps a
        seeded simulation reproducible.
        """
        pause_for_choices = bool(self.interactive_seats)
        while True:
            self.resolve_stack(pause_for_choices=pause_for_choices)
            if not self.stack:
                return
            top = self.stack[-1]
            # Two ways the top can refuse to resolve, and both end this loop:
            # its resolution is held pending a decision it armed, or it is
            # still owed the mode/target it should have chosen as it was
            # announced (``announcement_choice_for``). Only the first was
            # asked, so an unanswered announcement prompt turned this into a
            # spin — `resolve_stack` returning at once, the stack never
            # shrinking, the condition never true.
            if top.resolution_held or self.announcement_choice_for(top) is not None:
                return

    def _close_or_defer_step(self, phase: str, step: str, defer_priority: bool) -> None:
        """End a step, or — when defer_priority is set — leave a priority window open
        for the active player so a caller can hand priority to another player."""
        if not self._receives_priority(step):
            self._on_step_or_phase_end(phase, step)
            return
        if defer_priority:
            self.start_priority_window(self.active_player_index)
            return
        self._resolve_priority_window()
        self._on_step_or_phase_end(phase, step)

    def start_priority_window(self, starting_player_index: int | None = None) -> None:
        player_index = self.active_player_index if starting_player_index is None else starting_player_index
        if player_index < 0 or player_index >= len(self.players):
            self.priority_player_index = None
            self.priority_pass_count = 0
            return
        self.priority_player_index = player_index
        self.priority_pass_count = 0

    def clear_priority_window(self) -> None:
        self.priority_player_index = None
        self.priority_pass_count = 0

    def has_priority(self, player_index: int) -> bool:
        return self.priority_player_index == player_index

    def note_priority_action_taken(self, player_index: int) -> None:
        if self.priority_player_index is None:
            self.start_priority_window(player_index)
            return
        if self.priority_player_index != player_index:
            raise ValueError("player does not have priority")
        # 117.3c: after casting/activating, that player gets priority again.
        self.priority_pass_count = 0

    def _next_player_index(self, player_index: int) -> int:
        """The next player in turn order — skipping any player who has left the
        game (CR 800.4h: priority/choices pass to the next player still in it).

        Only applied in multiplayer (3+ players): CR 800.4 is explicitly a
        multiplayer concept ("unlike two-player games, multiplayer games can
        continue after one or more players have left the game") — a 2-player
        game just ends instead, so this is a no-op there, identical to before."""
        n = len(self.players)
        if n <= 1:
            return player_index
        candidate = (player_index + 1) % n
        if n < 3:
            return candidate
        for _ in range(n):
            if not self.players[candidate].lost:
                return candidate
            candidate = (candidate + 1) % n
        # Defensive: every player has left (is_game_over() should already be true).
        return player_index

    def pass_priority(self, player_index: int) -> str:
        if self.priority_player_index is None:
            raise ValueError("no active priority window")
        if self.priority_player_index != player_index:
            raise ValueError("player does not have priority")

        self.priority_pass_count += 1
        self.log.append(f"{self.players[player_index].name} passed priority")

        # CR 800.4h: a player who has left the game is skipped for priority, so
        # "everyone passed in succession" means every player still IN the game —
        # not the raw seat count. Multiplayer-only (see _next_player_index); a
        # 2-player game behaves exactly as before.
        living_count = (
            sum(1 for p in self.players if not p.lost)
            if len(self.players) >= 3
            else len(self.players)
        )
        if self.priority_pass_count < living_count:
            self.priority_player_index = self._next_player_index(player_index)
            return "passed"

        # All players have passed in succession.
        self.priority_pass_count = 0
        if self.stack:
            self.resolve_top_of_stack(pause_for_choices=True)
            # CR 117.3b gives the active player priority "after a spell or
            # ability resolves" — a resolution that stopped to ask somebody
            # something has not, so nobody gets priority yet and the seat that
            # owes the decision gets the window instead. This used to name three
            # kinds (the optional pay, Power Sink's payment, Word of Command) and
            # so every other prompt armed mid-resolution fell straight through to
            # the active player: Sanctum of All's "search your library" was
            # armed, the game moved on, and only the action gate — which refuses
            # by *seat*, not by whose turn it is — kept the board from being
            # played around. Asking the queue covers every prompt instead, this
            # card and the next one.
            waiting = self.waiting_prompt()
            if waiting is not None:
                self.priority_player_index = waiting.player_index
                return "awaiting_choice"
            # 704.3: state-based actions are checked before any player would
            # receive priority after a spell or ability resolves (e.g. an Aura
            # now illegally attached is put into its owner's graveyard).
            self.check_state_based_actions()
            # 117.3b: active player gets priority after a spell/ability resolves.
            self.priority_player_index = self.active_player_index
            return "resolved_top"

        self.priority_player_index = self.active_player_index
        return "all_passed_empty"

    def add_extra_turn(self, player_index: int) -> None:
        # 500.7: extra turns are added one at a time and the most recently
        # created turn is taken first (LIFO via pop()). When a single effect
        # grants extra turns to multiple players, the caller must add them in
        # APNAP order so the last-added (final in APNAP order) is taken first.
        self.extra_turn_queue.append(player_index)
        self.extra_turns[player_index] = self.extra_turns.get(player_index, 0) + 1

    # ------------------------------------------------------------------
    # The turn's phase plan (CR 500.1's order, CR 500.8's extras)
    #
    # One list, read by every driver that asks "what comes next": the headless
    # ``start_turn`` / ``advance_combat_phase`` flow and the web layer's
    # ``_advance_phase``. Before this the answer was hard-coded three times over
    # and ``add_extra_phase`` recorded a phase nothing ever entered.
    # ------------------------------------------------------------------

    def _remaining_turn_phases(self) -> list[str]:
        """The phases still to come this turn, in order - planning if needed.

        ``None`` (a fresh ``Game``, or one a test drove straight into the middle
        of a turn) means nobody has planned this turn, so the plan is derived
        from CR 500.1's order behind whatever phase is in progress. That is
        exactly the successor the hard-coded chains used to compute, which is
        what makes the loop behaviour-preserving for every card in the pool.
        """
        if self.turn_phases_remaining is None:
            self.turn_phases_remaining = phases_after(self.current_turn_phase)
        return self.turn_phases_remaining

    def extra_phases_remaining(self) -> list[str]:
        """The phases still to come that CR 500.1's order did not put there.

        The plan starts as ``phases_after(current)`` and is only ever *inserted*
        into, by CR 500.8's extra phases — so whatever the plan holds beyond
        that remainder is what an effect added and has not happened yet.
        Relentless Assault's "there is an additional combat phase followed by an
        additional main phase" is two entries here until they are spent.

        Derived rather than recorded, for the reason the plan itself is: a
        second list of "what was added" would be a second answer, and the one
        that goes stale is always the one nobody reads on the path that
        matters. Empty on an ordinary turn, which is every turn no card has
        touched.

        The reader is the web layer's End Turn button, which jumps to the ending
        phase from wherever it is and so discards these — a skip worth naming in
        the log, because unlike the turn's own combat phase somebody paid a card
        for it.
        """
        remaining = list(self._remaining_turn_phases())
        for phase in phases_after(self.current_turn_phase):
            if phase in remaining:
                remaining.remove(phase)
        return remaining

    def _enter_planned_phase(self, phase: str) -> None:
        """Spend *phase* out of the plan as it is entered.

        Called from :meth:`_set_phase_and_step` whenever the phase changes, so
        every way into a phase - a main phase, a combat step, the ending phase,
        CR 724.1's jump - spends the plan without any of them knowing there is
        one. Two cases and no third:

        * the plan's next entry **is** this phase: spend it, and whatever the
          plan still holds behind it (an extra phase, the turn's own remainder)
          stays;
        * anything else is an out-of-band jump - a test entering a phase
          directly, ``end_the_turn`` skipping to the ending phase - and the plan
          is re-derived from CR 500.1's order, which is what the engine did
          before a plan existed.
        """
        remaining = self._remaining_turn_phases()
        if remaining and remaining[0] == phase:
            remaining.pop(0)
            return
        self.turn_phases_remaining = phases_after(phase)

    def add_extra_phase(
        self,
        after_phase: str,
        phase_name: str,
        controller_index: int | None = None,
        only_on_controllers_turn: bool = False,
    ) -> bool:
        """CR 500.8: add *phase_name* directly after *after_phase* this turn.

        Returns whether a phase was added - CR 500.10a's "no steps or phases are
        added" is a real answer rather than an error, and so is naming a phase
        this turn has already taken.

        "Directly after the specified phase" is an insertion into the plan, and
        the two positions are the only two a printed card can name: the phase in
        progress ("After this main phase...", Relentless Assault) or one still
        to come. Inserting *at* that position rather than appending is
        CR 500.8's last sentence - "the most recently created phase will occur
        first" - because each new insertion lands in front of the one before it.
        """
        # 500.10a
        if only_on_controllers_turn and controller_index is not None and controller_index != self.active_player_index:
            return False
        remaining = self._remaining_turn_phases()
        if after_phase == self.current_turn_phase:
            position = 0
        elif after_phase in remaining:
            position = remaining.index(after_phase) + 1
        else:
            # A phase this turn has already taken, or no phase at all. CR 500.8
            # has nowhere to put it, so nothing is added and the caller is told.
            return False
        remaining.insert(position, phase_name)
        return True

    def enter_turn_phase(self, phase: str) -> None:
        """Begin *phase*, whichever of CR 500.1's phases it is.

        The completeness assertion this needs is in
        ``tests/rules/test_turn_phases.py``: every phase a plan can hold must be
        enterable here, or an extra phase would be recorded, chosen, and then
        silently not entered - which is the failure this block exists to end.
        ``beginning`` is deliberately not enterable: it is the phase a *turn*
        opens with (``start_turn``, the web layer's ``_begin_turn``), never one
        another phase hands over to, and no effect in the pool adds one
        (CR 500.10's Obeka does, and would need a driver able to run an upkeep
        step outside the start of a turn).
        """
        if phase in ("precombat_main", "postcombat_main"):
            self._enter_main_phase(precombat=(phase == "precombat_main"))
            return
        if phase == "combat":
            if self.current_turn_phase == "combat":
                # Back-to-back combat phases ("After this combat phase, there is
                # an additional combat phase"): ``advance_combat_phase`` would
                # read the step being left and try to leave it again, so the
                # first step is entered directly. The plan entry is spent here
                # because ``_set_phase_and_step`` only spends one when the phase
                # *name* changes, and this one does not.
                remaining = self._remaining_turn_phases()
                if remaining and remaining[0] == "combat":
                    remaining.pop(0)
                self._enter_combat_step(self._phase_steps("combat")[0])
                return
            self.advance_combat_phase()
            return
        if phase == "ending":
            self.resolve_end_step(self.active_player_index)
            return
        raise ValueError(f"no entry point for turn phase {phase!r}")

    def enter_next_turn_phase(self, after: str | None = None) -> str | None:
        """Enter whatever follows *after* (default: the phase in progress).

        The single seam every driver goes through instead of naming its own
        successor. Returns the phase entered, or None when the turn has none
        left.
        """
        phase = self.next_unskipped_phase_after(
            self.current_turn_phase if after is None else after
        )
        if phase is None:
            return None
        self.enter_turn_phase(phase)
        return phase

    def skip_next_turn(self, player_index: int, count: int = 1) -> None:
        # 500.11
        self.skip_turn_counts[player_index] = self.skip_turn_counts.get(player_index, 0) + max(0, count)

    def skip_next_step(self, step_name: str, count: int = 1, *, seat=None) -> None:
        """CR 500.7 / CR 614.10: skip the next *step_name*, once per *count*.

        *seat* makes it **that player's** next such step ("you skip your next
        draw step", Ivory Gargoyle). Keyed by step name alone the record is
        consumed by whichever seat's step comes round first, which on an
        opponent's turn is the wrong player's — so a seated skip gets its own
        key and the two live in the same bucket, read by the same
        :meth:`_consume_skip`.
        """
        key = step_name if seat is None else (self.seat_index(seat), step_name)
        self.skip_step_counts[key] = self.skip_step_counts.get(key, 0) + max(0, count)

    def _consume_step_skip(self, step: str, seat) -> bool:
        """Whether *seat*'s *step* is skipped, spending one record if so.

        The seated key first, then the unseated one: a skip aimed at this player
        is more specific than a skip of everyone's step, and spending the wrong
        one leaves the other to eat a step nobody named. Both consumers of the
        bucket ask through here, so "who is skipped" has one answer.
        """
        if seat is not None and self._consume_skip(
            self.skip_step_counts, (self.seat_index(seat), step)
        ):
            return True
        return self._consume_skip(self.skip_step_counts, step)

    def _consume_skip(self, bucket: dict[object, int], key: object) -> bool:
        amount = bucket.get(key, 0)
        if amount <= 0:
            return False
        if amount == 1:
            bucket.pop(key, None)
        else:
            bucket[key] = amount - 1
        return True

    def _phase_steps(self, phase: str) -> tuple[str, ...]:
        """The steps *phase* runs this turn, CR 500.11's step skips spent."""
        expanded: list[str] = []
        for step in _PHASE_STEPS.get(phase, (phase,)):
            if not self._consume_step_skip(step, self.active_player_index):
                expanded.append(step)
        return tuple(expanded)

    def _next_phase_after(self, phase: str) -> str | None:
        """The phase that follows *phase* this turn (CR 500.1, plus CR 500.8).

        A **peek**, not a pop: the plan is spent as a phase is *entered*
        (:meth:`_enter_planned_phase`), so a driver that asks what comes next
        and then declines to go there has changed nothing. Asked about a phase
        other than the one in progress - or about one whose plan has run out -
        it answers from CR 500.1's fixed order, which is what every caller of
        this used to compute by hand.
        """
        if phase == self.current_turn_phase:
            remaining = self._remaining_turn_phases()
            if remaining:
                return remaining[0]
        order = phases_after(phase)
        return order[0] if order else None

    def next_unskipped_phase_after(self, phase: str) -> str | None:
        """:meth:`_next_phase_after`, with CR 500.11's phase skips spent.

        Nothing in the pool writes ``skip_phase_counts`` yet - the engine's
        skips are per *step* (Ivory Gargoyle) and per *turn* (Chronatog). This
        is the consumer, and it sits on the live path, so the card that prints
        "skip your next combat phase" needs only the producer. That is the
        opposite of what the extra-phase machinery here used to be: a recorder
        with no consumer, which reads as a feature and is not one.
        """
        candidate = self._next_phase_after(phase)
        while candidate is not None and self._consume_skip(self.skip_phase_counts, candidate):
            remaining = self._remaining_turn_phases()
            if remaining and remaining[0] == candidate:
                # CR 500.11: proceed past it as though it did not exist.
                remaining.pop(0)
                candidate = remaining[0] if remaining else None
                continue
            candidate = self._next_phase_after(candidate)
        return candidate

    def _compute_next_active_player(self) -> int:
        # 500.7: an extra turn is inserted directly after the current turn and
        # does not advance the normal rotation. If the turn that just ended was
        # a *normal* turn, its active player anchors where the rotation resumes
        # once every inserted extra turn has been taken.
        if not self.current_turn_is_extra:
            self.normal_rotation_anchor = self.active_player_index

        if self.extra_turn_queue:
            # LIFO: the most recently created extra turn is taken first (500.7).
            chosen = self.extra_turn_queue.pop()
            pending = self.extra_turns.get(chosen, 0)
            if pending > 0:
                self.extra_turns[chosen] = pending - 1
            self.current_turn_is_extra = True
            return chosen

        self.current_turn_is_extra = False
        player_count = len(self.players)
        candidate = (self.normal_rotation_anchor + 1) % player_count
        # CR 800.4k (multiplayer only — see _next_player_index): a player who has
        # left the game never begins a turn — skip them without consuming a
        # skip-turn charge (that's a distinct effect). A 2-player game just ends
        # when someone loses, so this never needs to trigger there.
        multiplayer = player_count >= 3
        for _ in range(player_count + 1):
            if multiplayer and self.players[candidate].lost:
                candidate = (candidate + 1) % player_count
                continue
            if self.skip_turn_counts.get(candidate, 0) > 0:
                self._consume_skip(self.skip_turn_counts, candidate)
                candidate = (candidate + 1) % player_count
                continue
            break
        return candidate

    def _close_current_priority_step(self) -> None:
        phase = self.current_turn_phase
        step = self.current_step
        if self._receives_priority(step):
            self._resolve_priority_window()
            self.clear_priority_window()
        self._on_step_or_phase_end(phase, step)

    def end_the_turn(self) -> None:
        """CR 724.1 — the expedited process "End the turn." performs.

        Deliberately not "advance to the ending phase": 724.1 differs from
        ordinary turn structure at every step, and each difference is a way a
        card could otherwise cheat the process.

        * **724.1a** is vacuous in this engine and said so rather than skipped:
          a trigger here is announced straight onto the stack, so there is no
          window in which one has triggered and is waiting to be put there.
          The moment that stops being true this comment is the bug report.
        * **724.1b** exiles every object on the stack, *including the object
          that is resolving*. The resolving item was popped before its handler
          ran, so it is not in the list — it is flagged instead, and the
          resolution tail bins it to exile through the one site that decides
          where a spell's card goes (CR 608.2n).
        * **724.1c** checks state-based actions with no player receiving
          priority, which is why the window is cleared before the check rather
          than after: a check that opened a priority window would hand a player
          the response 724.1 exists to deny them.
        * **724.1d** ends the current phase and step, removes every creature and
          planeswalker from combat, and skips to the cleanup step. Marked
          damage is *not* cleared here — CR 514.2 does that in the cleanup step
          the game is now heading for, and clearing it twice would wipe damage
          dealt by a trigger that fires during this process.
        * **724.1e** falls out of where this leaves the game rather than needing
          code: the position is the end of the *end step*, so the next
          advance resolves cleanup and ``resolve_end_step`` — which is what
          fires "at the beginning of the end step" — is never called.
        """
        exiled = []
        for item in self.stack:
            owner = self.players[item.caster_index]
            self._bin_spell_card(owner, item.card, exile_instead=True, verb="was exiled")
            exiled.append(item.card.name)
        self.stack.clear()
        # The resolving object is the one the list cannot hold.
        self.exile_resolving_spell = True

        self.clear_priority_window()
        self.check_state_based_actions()

        self._reset_combat_state(clear_damage_marked=False)
        self._set_phase_and_step("ending", "end")
        self.log.append(
            "The turn ends" + (f"; exiled from the stack: {', '.join(exiled)}" if exiled else "")
        )

    def _set_phase_and_step(self, phase: str, step: str) -> None:
        # Entering a phase spends it out of the turn's plan (CR 500.8). Here
        # rather than at each entry point for ``remove_from_battlefield``'s
        # stated reason one package over: there are several ways into a phase
        # and this is the line every one of them already passes through.
        if phase != self.current_turn_phase:
            self._enter_planned_phase(phase)
        self.current_turn_phase = phase
        self.current_step = step
        self.current_phase = self._public_phase_name(phase, step)
