"""Drawing is one seam, and so is discarding.

``_draw_with_replacements`` is where a draw becomes a CR 614 event:
``PlayerState.draw`` is the library operation underneath, and reaching for
it skips every armed draw replacement (``tests/engine/test_draw_seam.py``).
Draws are made **one at a time** (CR 121.2): a prompt armed while a seat's
draw is being made is stamped with that seat, and a later draw for it is
parked until the answer (``_park_draw``, ``answering_draw_prompt``,
``_DrawPromptAnswer``), because CR 616.1f finishes one event before the next
begins. Beside it, what a draw can turn into: a revealed draw (Rowen, Booby
Trap), a commander going to the command zone instead (CR 903.9b), and the
completions of Aladdin's Lamp's and Ring of Ma'rûf's replaced draws.

``_discard_card`` raises the CR 614 ``discard`` event and announces the
discard (CR 701.9a, ``announce_discard``), and the event says who caused it
(``discard_cause_seat``), because "a spell or ability an opponent controls
causes you to discard this card" is a question about the cause - and a seat
answering a prompt is no longer resolving anything. Library of Leng's "you
may put it on top of your library" is offered up front by the chosen-discard
flow (``_controls_top_of_library_discard``), and to a forced discard by the
``discard`` replacement.
"""

from __future__ import annotations

import random

from ..ante import is_ante_card
from ..events import emit
from ..models import PlayerState
from ..pending_choices import spec_for
from ..replacement_choices import DRAW_OF
from ..replacements import TOP_OF_LIBRARY_DISCARD_TEXT, apply_replacements
from ..oracle import compile_card_oracle
from ..trigger_utils import make_trigger_event, matching_triggers


class _DrawPromptAnswer:
    """The span of one answer to a prompt a draw armed (CR 121.2).

    ``DrawsAndDiscardsMixin.answering_draw_prompt`` is the way in and says what the
    span means; this is only its bookkeeping. Inert when no draw armed the
    prompt, so every other answer in the engine passes straight through.
    """

    __slots__ = ("game", "seat", "frame")

    def __init__(self, game, choice) -> None:
        self.game = game
        self.seat = choice.data.get(DRAW_OF)
        self.frame = [choice, 0]

    def __enter__(self) -> "_DrawPromptAnswer":
        if self.seat is not None:
            self.game.draw_answer_frames.append(self.frame)
            self.game.draw_scopes.append(self.seat)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if self.seat is None:
            return False
        game = self.game
        game.draw_scopes.pop()
        game.draw_answer_frames = [
            frame for frame in game.draw_answer_frames if frame is not self.frame
        ]
        if exc_type is None:
            # The draw this prompt belonged to has had its answer. If it is
            # finished — the answer armed nothing further — the draws parked
            # behind it are made now, inside whatever resolution this answer
            # is part of.
            game._release_parked_draws()
        return False


class DrawsAndDiscardsMixin:
    def _controls_top_of_library_discard(self, player: PlayerState) -> bool:
        """Whether *player* controls a Library of Leng-style permanent that lets
        them redirect a discard to the top of their library (CR 701.9c).

        Used by the *chosen*-discard flow, where the player picks which card to
        discard and where it goes in one prompt, so the offer has to be known
        before the discard happens. A forced discard instead routes through the
        ``discard`` replacement in engine/replacements.py, which reads the same
        text."""
        return self._player_controls_text(player, TOP_OF_LIBRARY_DISCARD_TEXT)

    # ------------------------------------------------------------------
    # One draw at a time (CR 121.2)
    # ------------------------------------------------------------------
    #
    # "If a player is instructed to draw multiple cards, that player performs
    # that many individual card draws." Each is its own event: CR 616.1 runs
    # over it to the end (616.1f: apply the chosen effect, then ask again
    # among those still applicable) before the next one exists, and CR 614.5
    # gives each replacement one opportunity *per event*.
    #
    # A replacement that needs an answer suspends its draw and carries the
    # draws behind it on its own prompt (``remaining_draws``, ``queued_draws``).
    # What that arrangement could not carry is a draw the *answer* suspends
    # again: an optional replacement declined remakes its draw through the
    # seam, a second replacement asks about that draw — and the resolver went
    # straight on to the draws queued behind, with the first still unanswered.
    # Abundance and Pursuit of Knowledge on one battlefield, three cards drawn:
    # the second draw's Pursuit offer and the third draw's CR 616.1e order
    # were both owed, each refused every action but its own answer, and the
    # game could not be continued by any click or any request.
    #
    # So the rule is kept by the seam rather than by each of the dozen tails
    # that make "the draws behind": a draw does not begin while a prompt an
    # earlier draw of the same seat armed is still owed.

    def _draw_prompt_open(self, seat: int) -> bool:
        """Whether a decision one of *seat*'s draws armed is still owed.

        Read off both queues by the stamp a prompt is given as it is queued
        (``replacement_choices.DRAW_OF``), so this knows no kind by name: a
        replacement's own offer, CR 616.1e's order, Chains of Mephistopheles'
        discard, Zur's Weirding's poll of the *other* players (the stamp is
        the drawing seat, not the answering one) and whatever the next set
        prints are one test.

        The choice being answered right now holds nothing — its answer is the
        work the draw was waiting for — whether or not its resolver has taken
        it off the queue yet (``draw_answer_frames``). A notification that
        blocks no action (``holds_priority``) never held a draw either.
        """
        for choice in self.pending_replacement_choices:
            if choice.data.get(DRAW_OF) == seat:
                return True
        answering = [frame[0] for frame in self.draw_answer_frames]
        for choice in self.pending_choices:
            if choice.data.get(DRAW_OF) != seat:
                continue
            if choice.data.get("_answered") or any(choice is one for one in answering):
                continue
            spec = spec_for(choice.kind)
            if spec.holds_priority and spec.open_for(self, choice):
                return True
        return False

    def _park_draw(
        self, seat: int, count: int, turn_based: bool, exclude_sources: tuple
    ) -> None:
        """Hold a draw behind the one still waiting on its player.

        In order. A draw parked from inside an answer is a later step of *that*
        prompt's draw, so it goes ahead of anything an outer answer parked,
        after its own earlier ones (the frame's cursor); a draw parked from
        anywhere else is a later instruction and goes to the back.
        """
        entry = {
            "seat": seat,
            "count": int(count),
            "turn_based": bool(turn_based),
            "exclude_sources": tuple(exclude_sources),
        }
        if self.draw_answer_frames:
            frame = self.draw_answer_frames[-1]
            self.parked_draws.insert(frame[1], entry)
            frame[1] += 1
        else:
            self.parked_draws.append(entry)

    def _release_parked_draws(self) -> None:
        """Make the parked draws whose seat owes nothing any more, in order.

        Called when an answer to a draw's prompt has been applied, and stops
        the moment a released draw suspends in its turn — the next answer
        comes back here. Not re-entered: a released draw goes through the
        seam, and the seam must not release the draws parked *behind* it
        before it has drawn.
        """
        if self.releasing_parked_draws or self.draw_scopes:
            return
        self.releasing_parked_draws = True
        try:
            # Each pass makes one draw or finds none it may make.
            for _ in range(len(self.parked_draws) + 1):
                entry = next(
                    (
                        parked for parked in self.parked_draws
                        if not self._draw_prompt_open(parked["seat"])
                    ),
                    None,
                )
                if entry is None:
                    return
                self.parked_draws = [
                    parked for parked in self.parked_draws if parked is not entry
                ]
                self._draw_with_replacements(
                    self.players[entry["seat"]],
                    entry["count"],
                    turn_based=entry["turn_based"],
                    exclude_sources=entry["exclude_sources"],
                )
        finally:
            self.releasing_parked_draws = False

    def answering_draw_prompt(self, choice):
        """A context manager around applying the answer to *choice*.

        Inert for a prompt no draw armed. For one that a draw did arm, the
        answer is part of that seat's draw: a prompt it arms in turn is
        stamped the same way (the order of the cards Abundance puts on the
        bottom, CR 903.9b's offer about a commander it put into a hand), the
        draws its resolver asks for behind an unfinished one are parked, and
        when it has been applied the parked draws are released.
        """
        return _DrawPromptAnswer(self, choice)

    def _draw_with_replacements(
        self,
        player: PlayerState,
        count: int,
        *,
        turn_based: bool = False,
        exclude_sources: tuple[int, ...] = (),
    ) -> int:
        """Draw ``count`` cards for *player*, letting an armed draw replacement
        take the first of them (CR 614) — Aladdin's Lamp, Ring of Ma'rûf — or
        change how many there are (Teferi's Ageless Insight).

        A replacement that needs the player to choose suspends the draw and
        reports 0 drawn; the cards arrive when the choice is answered, along
        with any draws queued behind it. Which replacements exist lives in
        engine/replacements.py.

        This is the *only* way an effect should draw. CR 121.2 makes a
        multi-card instruction that many individual draws, each replaceable on
        its own, so the draws queued behind a replaced one come back through
        here rather than being taken off the library — and a draw an effect
        *creates* (Lich turning a life gain into one, CR 616.2) is a draw like
        any other. `player.draw` is the library operation underneath; reaching
        for it directly is how a second armed replacement gets skipped.

        ``turn_based`` marks CR 504.1's draw-step draw. Only the draw step
        passes it, and it exists for the rider on every draw-doubler ever
        printed — "except the first one you draw in each of your draw steps".
        The engine cannot derive it: any later draw in the same step is also
        made by the active player during their draw step, and it is not the
        first one.

        ``exclude_sources`` is CR 614.5 — "a replacement effect gets only one
        opportunity to affect an event or any modified events resulting from
        that event". A replacement that *creates* a draw (Chains of
        Mephistopheles' "if the player discards a card this way, they draw a
        card") passes the ``permanent_id`` of the source that created it, so
        that source does not replace its own replacement into a loop. It is a
        set of ids rather than a boolean because a *second* copy of the same
        card is a different effect and does apply (CR 614.5 is about one
        effect, not one wording), and it is carried on the payload so the
        exclusion survives the restart CR 616.1e's prompt re-runs.
        """
        if count <= 0:
            return player.draw(count)
        # One draw at a time (CR 121.2). A draw this seat made earlier in the
        # same instruction may still be waiting on its player — an optional
        # replacement's offer, CR 616.1e's order, the card a discard takes —
        # and this one does not begin until that one is finished: it is
        # parked, and the answer releases it. See ``_draw_prompt_open``.
        seat = self.seat_index(player)
        if not self.draw_scopes and not self.releasing_parked_draws:
            # Nothing of a draw's is running, so anything still parked for
            # this seat is owed first (a prompt taken off the queue by a road
            # that is not an answer leaves its draws here).
            self._release_parked_draws()
        if self._draw_prompt_open(seat):
            self._park_draw(seat, count, turn_based, tuple(exclude_sources))
            return 0
        self.draw_scopes.append(seat)
        try:
            consumed, payload = apply_replacements(
                self,
                "draw",
                {
                    "player": player,
                    "count": count,
                    "drawn": 0,
                    "turn_based": turn_based,
                    "exclude_sources": tuple(exclude_sources),
                },
                # A draw can suspend: "the replacement took it, the cards arrive
                # when you answer" is already this method's contract, so CR
                # 616.1e's choice can be put to the player here. Re-running this
                # call is what the answer resumes, which is why the thunk is the
                # call itself.
                restart=lambda: self._draw_with_replacements(
                    player, count, turn_based=turn_based,
                    exclude_sources=exclude_sources,
                ),
            )
        finally:
            self.draw_scopes.pop()
        if consumed:
            return int(payload["drawn"])
        # `payload["count"]`, not `count`: a replacement may have changed how
        # many draws this event is (Teferi's Ageless Insight) without consuming
        # it, exactly as `place_plus1_counters` reads back a raised counter
        # count. Reading the local instead is why a *modifying* draw
        # replacement could not be written at all — the interceptor would run,
        # the number would change, and the draw would take the old one.
        before = len(player.cards_drawn_this_turn)
        drawn = player.draw(max(0, int(payload.get("count", count))))
        self._divert_drawn_commanders(player)
        self._reveal_first_draw_of_turn(player, before)
        self._reveal_every_draw(player, before)
        return drawn

    def _reveal_first_draw_of_turn(self, player, drawn_before: int) -> None:
        """"Reveal the first card you draw each turn." (Rowen.) CR 701.20.

        Here rather than at a fire site per card-drawing effect, for the reason
        this whole seam exists: a draw is a draw whether the draw step, a
        cantrip, an upkeep trigger or a replacement made it, and a list of the
        places one happens goes stale the way every fire-site list in this
        engine has.

        *drawn_before* is how many cards this seat had already drawn this turn,
        read before the draw so the "first" is settled by the record rather than
        by which call site got here — CR 121.2 makes a multi-card draw that many
        individual draws, so a two-card draw on an empty turn reveals exactly the
        first of them.

        The reveal is *announced* as well as recorded: "Whenever you reveal a
        basic land card this way, draw a card" is the sentence behind it, and it
        is an ordinary triggered ability over this event. Announced after the
        card is in hand, which is where CR 701.20a says a revealed card is.
        """
        if drawn_before != 0 or not player.cards_drawn_this_turn:
            return
        from ..draw_reveals import reveals_first_draw
        from ..events import emit

        seat = self.players.index(player)
        if not reveals_first_draw(self, seat):
            return
        card = player.cards_drawn_this_turn[0]
        self.record_reveal(seat, [card.name])
        self.log.append(f"{player.name} revealed {card.name} (first draw this turn)")
        emit(
            self, "revealed_drawn_card", subject=card,
            players=[player], event_subject_player=seat,
        )

    def _reveal_every_draw(self, player, drawn_before: int) -> None:
        """"The chosen player reveals each card they draw." (Booby Trap.)
        CR 701.20.

        :meth:`_reveal_first_draw_of_turn`'s sibling, on the same seam and for
        the same reason — a draw is a draw whatever made it. What differs is
        that this one has no "first" to settle, so every card this call added is
        shown: CR 121.2 makes a multi-card draw that many individual draws, and
        *drawn_before* is where this event's share of the record starts.

        The reveal is recorded and logged and **not** announced as
        ``revealed_drawn_card``: that event is Rowen's "whenever you reveal a
        basic land card **this way**", which names the reveal *its own card*
        asks for. Announcing this one would fire Rowen's trigger on a reveal
        another player's artifact caused, which is a card nobody printed.
        """
        from ..draw_reveals import reveals_every_draw

        added = player.cards_drawn_this_turn[drawn_before:]
        if not added:
            return
        seat = self.players.index(player)
        if not reveals_every_draw(self, seat):
            return
        self.record_reveal(seat, [card.name for card in added])
        self.log.append(
            f"{player.name} revealed {', '.join(card.name for card in added)} "
            "(each card they draw)"
        )

    def _divert_drawn_commanders(self, player) -> None:
        """CR 903.9b over a draw: drawing a commander puts it into its owner's
        hand from their library, so its owner may put it into the command zone
        instead.

        Applied just after ``PlayerState.draw`` rather than inside it, which is
        the one place the two halves of a draw can be told apart: ``draw`` is
        the library operation (it must move the card to know a card was there
        at all), and this is the replacement over its destination. The card
        never becomes castable or discardable in between, since nothing gets
        priority between the two lines.
        """
        if not self.is_commander_game:
            return
        seat = self.players.index(player)
        for card in [c for c in player.hand if self.is_commander_card(seat, c)]:
            index = next((i for i, held in enumerate(player.hand) if held is card), None)
            if index is None:  # pragma: no cover - the list was just read
                continue
            player.hand.pop(index)
            if not self.commander_zone_change(seat, card, "hand"):  # pragma: no cover
                player.hand.insert(index, card)

    def _finish_lamp_draw(self, player_index: int, chosen_index: int, x: int) -> int:
        """Complete a lamp-replaced draw: the chosen card of the top ``x`` goes
        to hand, the rest go to the bottom of the library in a random order."""
        player = self.players[player_index]
        top = list(player.library[:x])
        chosen = top.pop(chosen_index)
        del player.library[:x]
        random.shuffle(top)
        player.library.extend(top)
        self.put_card_into_hand(player, chosen)
        # The replacement still ends in "then draw a card", so the chosen card is
        # the last card drawn this turn (Jandor's Ring's cost can discard it).
        player.cards_drawn_this_turn.append(chosen)
        self.log.append(
            f"{player.name} drew 1 card (Aladdin's Lamp) and put {len(top)} card(s) "
            "on the bottom of their library in a random order"
        )
        return 1

    def _outside_game_choices(self, player_index: int) -> list[int]:
        """Sideboard indices this player may bring into the game (CR 100.4).
        Ante cards are excluded unless the game is played for ante (CR 407.3);
        in a Commander game CR 903.11a's name and colour-identity bars apply
        on top (`outside_the_game_problem` is None outside one)."""
        player = self.players[player_index]
        return [
            i for i, card in enumerate(player.sideboard)
            if (self.playing_for_ante or not is_ante_card(card))
            and self.outside_the_game_problem(player_index, card) is None
        ]

    def _finish_outside_game_draw(self, player_index: int, chosen_index: int) -> None:
        """Move the chosen sideboard card into hand."""
        player = self.players[player_index]
        if not (0 <= chosen_index < len(player.sideboard)):
            return
        card = player.sideboard.pop(chosen_index)
        if self.put_card_into_hand(player, card):
            self.log.append(
                f"{player.name} put {card.name} into their hand from outside the game (Ring of Ma'rûf)"
            )

    def discard_cause_seat(self, cause_seat: int | None = None) -> int | None:
        """Which seat's spell or ability is causing a discard happening *now*
        (CR 109.5), or None when nothing is — a cleanup-step discard, a cost
        the player chose to pay.

        One reader, because two cards ask and must agree: Psychic Purge's
        "**when** a spell or ability an opponent controls causes you to discard
        this card" is a trigger and Dodecapod's "**if** …, put it onto the
        battlefield … instead" is a replacement, on the same condition.

        *cause_seat* is the seat a **prompt** recorded when it was armed
        (``arm_pending_choice``'s ``_cause_seat``): by the time a seat answers,
        the resolution that asked has returned and ``resolving_seats`` is
        empty, which would read as "nothing caused this".
        """
        if isinstance(cause_seat, int):
            return cause_seat if 0 <= cause_seat < len(self.players) else None
        return self.resolving_seats[-1] if self.resolving_seats else None

    def _discard_card(
        self, player: PlayerState, card, *, cause_seat: int | None = None
    ) -> None:
        """Move a discarded card to the graveyard, or let a discard replacement
        take it instead (Library of Leng, CR 701.9c; Dodecapod, onto the
        battlefield).

        Use for random/forced discards (combat damage, "discards X cards at
        random", cleanup) where the player can't pick the card but a
        replacement may still redirect it.

        The event carries **who caused it** (``discard_cause_seat``), because a
        replacement may turn on that and the card itself cannot say: it is the
        seat resolving right now, or *cause_seat* when the caller is finishing
        a discard some earlier resolution armed.
        """
        cause = self.discard_cause_seat(cause_seat)
        consumed, _ = apply_replacements(
            self, "discard",
            {"player": player, "card": card, "cause_seat": cause},
        )
        if not consumed:
            self.put_card_into_graveyard(player, card)
        self._announce_discard_triggers(player, card, cause_seat=cause_seat)
        self.announce_discard(player, card)

    def announce_discard(self, player: PlayerState, card) -> None:
        """CR 701.9a: a discard happened, for the permanents that watch one.

        "Whenever **you** discard a card, exile that card from your graveyard."
        (Necropotence.) "Whenever **an opponent** discards a card, this
        enchantment deals 2 damage to that player." (Megrim.) Separate from
        ``_announce_discard_triggers`` beside it, which is CR 113.6's ability
        *of the discarded card* and asks a different question of a different
        object — this one walks the board.

        Both discard seams call it, and that is the whole point: a discard is
        either taken from the player (``_discard_card``) or chosen by them
        (``_resolve_one_discard``), and a watcher announced on one path only
        fires for half the cards that discard.

        **Which seat the card printed is a narrowing, not a second event**, the
        same reading ``land_played`` and ``draws_card`` record: "you" is the
        ability's controller (CR 109.5) and "an opponent" is any *other* seat,
        which is what makes the unnarrowed reading wrong in a three-player game
        rather than merely inverted. So the board is walked in full and each
        watcher's own payload decides, instead of the loop skipping every
        permanent whose controller did not discard.

        The card itself rides the context, because "**that** card" is the one
        just discarded and a graveyard is a list of ``CardDefinition`` where two
        copies of a card are the same object — a name match would find whichever
        entry came first. The discarding **seat** rides it too, under the one
        ``event_subject_player`` key every "that player" reader asks for
        (CR 603.10): the seat varies per firing and by resolution nothing on a
        board says who discarded.
        """
        seat = next(
            (i for i, seated in enumerate(self.players) if seated is player), None
        )
        if seat is None:
            return
        events: list[dict] = []
        for controller_index, observer in self.permanents_with_controller():
            for trig in matching_triggers(
                observer.effective_card, condition_kinds={"discards_card"},
            ):
                if trig.instruction is None:
                    continue
                discarder = trig.condition.payload.get("discarder")
                if discarder == "a player":
                    # "Whenever **a player** discards a card" (Confessor):
                    # nobody is narrowed away, the watcher's controller
                    # included.
                    pass
                elif discarder == "an opponent":
                    if controller_index == seat:
                        continue
                elif controller_index != seat:
                    continue
                events.append(make_trigger_event(
                    controller_index, observer, trig,
                    trigger_context={
                        "discarded_card": card,
                        "discarded_name": card.name,
                        "event_subject_player": seat,
                        # "That card" / "the discarded card" in a graveyard,
                        # under the key every ``BOUND_CARD_EVENTS`` reader asks
                        # (Pitchstone Wall).
                        "dead_card": card,
                    },
                ))
        self._enqueue_triggered_batch(events)

    def _announce_discard_triggers(
        self, player: PlayerState, card, cause_seat: int | None = None
    ) -> None:
        """CR 113.6: a triggered ability of the discarded card itself.

        Psychic Purge is a *sorcery*, so CR 113.6's default would have its
        abilities function only on the stack. This one is an exception no
        lettered subrule names: the trigger condition can be met only while the
        card is in a hand, so that is where it functions. Not CR 113.6d, which
        is about an alternative or modified cost to cast the object.

        "When a spell or ability an opponent controls causes you to discard this
        card, that player loses 5 life." (Psychic Purge.) The ability functions
        from the **hand**, so nothing on the battlefield carries it and no
        board scan would find it — the card being discarded is the source, and
        this seam is the only place it is in view.

        Announced whether or not a replacement consumed the move: Library of
        Leng changes where a discarded card goes (CR 701.9c), it does not stop
        the card being discarded.

        "A spell or ability an opponent controls" is CR 109.5's question, and
        `resolving_seats` is the engine's answer to it — the same stack the
        damage seam derives `damage_source_seat` from. An empty stack means the
        discard was not caused by a spell or ability at all (a cleanup-step
        discard, a cost the player paid themselves), which is exactly when this
        trigger must not fire.

        *cause_seat* is for the discard that happens when a **prompt** is
        answered: the resolution that armed it has already returned, so
        `resolving_seats` is empty by then and the caller passes the seat it
        read off the choice's own stack item instead.
        """
        causer = self.discard_cause_seat(cause_seat)
        if causer is None:
            return
        # By identity, not `players.index`: PlayerState is a value-compared
        # dataclass, so two seats holding the same cards match each other.
        seat = next(
            (i for i, seated in enumerate(self.players) if seated is player), None
        )
        if seat is None or seat == causer:
            return
        for trig in compile_card_oracle(card).triggered_abilities:
            if trig.condition.kind != "discarded_by_opponent_effect":
                continue
            if trig.condition.payload.get("discarded_any_card"):
                # The board-scoped printing, handled by the scan below. The
                # discarded card is not a permanent, so it can never be its own
                # observer here — but a card that printed both sentences would
                # otherwise be announced twice for one discard.
                continue
            if not trig.supported or trig.instruction is None:
                continue
            self._enqueue_triggered_ability(
                controller_index=seat,
                card=card,
                instruction=trig.instruction,
                effect_kind=trig.effect_kind,
                ability_text=trig.source_line,
                target_player_index=causer,
                trigger_context={"event_subject_player": causer},
            )
        # "Whenever a spell or ability an opponent controls causes you to
        # discard a card, you gain 2 life and you may draw a card."
        # (Spiritual Focus.) The **second dispatch scope** for this condition:
        # an observer on the battlefield rather than the card being discarded,
        # so the loop above cannot reach it — the card in the hand is the only
        # object that one has in view.
        #
        # "**You**" is the ability's own controller (CR 109.5), which is the
        # seat doing the discarding, so the scan is that seat's battlefield.
        # The causer test above already established that a spell or ability an
        # *opponent* of that seat controls is what caused it, which is the whole
        # of the condition's other half — asked once, here, rather than a second
        # time per observer.
        for observer in self.controlled_by(seat):
            for trig in compile_card_oracle(
                observer.effective_card
            ).triggered_abilities:
                if trig.condition.kind != "discarded_by_opponent_effect":
                    continue
                if not trig.condition.payload.get("discarded_any_card"):
                    continue
                if not trig.supported or trig.instruction is None:
                    continue
                self._enqueue_triggered_ability(
                    controller_index=seat,
                    card=observer.effective_card,
                    instruction=trig.instruction,
                    effect_kind=trig.effect_kind,
                    ability_text=trig.source_line,
                    source_permanent=observer,
                    target_player_index=causer,
                    trigger_context={
                        "event_subject_player": causer,
                        "discarded_name": getattr(card, "name", None),
                    },
                )
