"""Choices a player has to make part-way through casting or resolving.

Each is the same shape: something *arms* a choice on ``game.pending_choices``,
an interactive seat answers it through a ``confirm_*`` method the web layer
calls, and every other seat takes the kind's recorded default. Both paths
finish through the one registered resolver, so there is a single completion
path to keep correct rather than an inline branch and a ``confirm_`` method
that must agree forever.

The registration table at the bottom of this module is the index of every
prompt in the engine: what answers it, what a non-interactive seat does
instead, and how the web layer renders, gates and refuses around it. See
``engine/pending_choices.py`` for what each field means and why the table
exists. ``tests/engine/test_pending_choices.py`` fails if a kind is armed with
no spec, or registered with a part missing.

Covered here: paying for an optional effect, discarding, sacrificing, naming a
land type, choosing a body as a permanent enters, Balance's removals, Word of
Command's borrowed turn, Kudzu's reattachment, and reordering a library.
"""

from __future__ import annotations

import random
from dataclasses import replace

from ...auras import attach_aura
from ...handlers._common import apply_temp_pt_boost, permanent_matches_filter
from ...land_types import change_land_type
from ...models import CardDefinition, Permanent
from ...oracle_types import DISCARDED_BY_SEAT
from ... import land_mana_swaps
from ...pending_choices import CHOICE_SPECS, PendingChoice, register_choice, spec_for
from ...replacement_choices import pending_choices_for
from ...resumption import resume_after_answer, run_resumable
from ...mana_payment import (generic_cost, mana_cost_label, plan_payment,
                            untapped_mana_lands)
from ...search_filters import landing_seat, search_matches, searched_seat
from ...subject_filters import subject_matches

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
            answered = apply()
        finally:
            self.resolving_stack_item = previous
        if item is not None:
            self._release_stack_item(item)
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
                    self.take_choice_default(choice)
                    # Every default takes its choice off the queue; dropping it
                    # here as well is what guarantees this loop terminates even
                    # if one ever forgets.
                    self.discard_pending_choice(choice)
                    progressed = True
            if not progressed:
                return

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
    def pending_mana_payment(self) -> dict | None:
        return self._choice_view("mana_payment", "player_index")

    @property
    def pending_kudzu_reattach(self) -> dict | None:
        return self._choice_view("kudzu_reattach", "player_index")

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
    def pending_least_power_choice(self) -> dict | None:
        return self._choice_view("least_power_choice", "controller_index")

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

    # -- Library search -----------------------------------------------------

    def confirm_search_library(
        self, caster_index: int, library_index: int, zone: str = "library"
    ) -> bool:
        return self.resolve_pending_choice(
            "search_library", caster_index, library_index=library_index, zone=zone
        )

    def confirm_search_library_picks(self, caster_index: int, picks: list) -> bool:
        """Answer a counted search ("up to two basic land cards") whole: every
        find in one action, each pick naming its zone and index there."""
        return self.resolve_pending_choice(
            "search_library", caster_index, picks=picks
        )

    def confirm_search_destination(self, caster_index: int, assignments: list) -> bool:
        return self.resolve_pending_choice(
            "search_destination", caster_index, assignments=assignments
        )

    def decline_search_library(self, caster_index: int) -> bool:
        """"Fail to find" (CR 701.19b) as an answer rather than an error.

        It is the *only* legal answer when nothing in the searched zones matches
        the restriction — "a card named Teferi, Timeless Voyager" usually finds
        nothing — so a seat that cannot find one still has to be able to leave
        the search. Routed through the same resolver as a find, because the
        library was searched either way and so is shuffled either way.
        """
        return self.resolve_pending_choice(
            "search_library", caster_index, library_index=-1, zone="none"
        )

    def _resolve_search_library(
        self, choice: PendingChoice, library_index: int, zone: str = "library"
    ) -> bool:
        # Who chooses and whose zone is looked in are two questions, and
        # Reincarnation prints them as two players: its controller picks the
        # card (CR 608.2c) out of the graveyard of the dead creature's owner.
        # The default is the chooser's own zone, which is every other card.
        caster = self.players[searched_seat(choice.data, choice.player_index)]
        zones = tuple(choice.data.get("zones", ("library",)))
        if zone == "none":
            # Fail-to-find ends the whole search, not one find of it: CR 701.19b
            # is about the search, and "up to two" makes finding fewer a legal
            # answer the player states by declining the rest.
            if "library" in zones:
                random.shuffle(caster.library)
            self._record_search_reveal(choice)
            self.discard_pending_choice(choice)
            self.log.append(f"{caster.name} searched and found nothing more")
            return True
        # A counted search ("up to two basic land cards") takes its whole
        # answer at once through the picks path below; a per-find answer here
        # would reopen the split flow the atomic answer replaced.
        if len(choice.data.get("destinations") or ()) > 1:
            return False
        # A zone the search was not armed with is not a zone this search may
        # look in: "search your library" is a different card from "search your
        # library and/or graveyard", and the wire must not be able to promote
        # one into the other.
        if zone not in zones:
            return False
        source = caster.library if zone == "library" else caster.graveyard
        if library_index < 0 or library_index >= len(source):
            return False
        card = source[library_index]
        # What the search may *find* is checked here rather than trusted from
        # whoever answered. The web picker is sent the legal indices, but a
        # payload is a hint: a client that offered the whole library would
        # otherwise turn "a creature card with mana value 6 or greater" into
        # Demonic Tutor.
        if not search_matches(card, choice.data):
            return False
        source.pop(library_index)
        # "…, reveal it, …" (CR 701.20): a search armed with the printed word
        # shows the find's face to every player when the search ends.
        if choice.data.get("reveal"):
            choice.data.setdefault("revealed_names", []).append(card.name)
        # "…put it onto the battlefield, then shuffle" (Garruk, Unleashed's
        # emblem) — the found card enters play instead of the hand. The
        # destination was fixed when the search was armed; the wire cannot
        # promote a tutor-to-hand into a tutor-to-battlefield.
        destination = choice.data.get("destination", "hand")
        enters_tapped = bool(choice.data.get("enters_tapped"))
        if destination == "held":
            # "Search your library for an artifact card. **If** that card's mana
            # value… put it onto the battlefield… **If you don't**, put it into
            # its owner's graveyard." (Transmute Artifact.) Where the find goes
            # is a later step's decision, so the search hands it over rather
            # than placing it — the card is out of the library and in nobody's
            # zone for exactly as long as it takes the next step of the same
            # resolution to run, with no priority in between.
            record = choice.data.get("record")
            if record is not None:
                record["found_card"] = card
            self.log.append(f"{caster.name} searched {zone} and found {card.name}")
            if zone == "library":
                random.shuffle(caster.library)
            self._record_search_reveal(choice)
            self.discard_pending_choice(choice)
            return True
        if destination == "battlefield":
            from ...models import Permanent as _Permanent

            found = _Permanent(card=card, tapped=enters_tapped)
            # "…under the control of that creature's owner." Whose battlefield
            # again defaults to the chooser's, which is every other card.
            self._put_permanent_onto_battlefield(
                landing_seat(choice.data, choice.player_index), found, None
            )
            # "Then if you control four or more lands, untap that land."
            # (Fabled Passage.) Counted *after* the land has entered, which is
            # when the printed "then" happens — so the land counts itself. Through
            # `become_untapped`, because anything that must happen when a
            # permanent untaps has one place to be.
            rider = choice.data.get("untap_found_if")
            if rider and found.tapped:
                from ...handlers._common import evaluate_count

                held = evaluate_count(self, caster, rider["filter"])
                if held >= int(rider["threshold"]):
                    self.become_untapped(found)
                    self.log.append(
                        f"{card.name} untaps ({held} counted)"
                    )
        elif destination == "exile":
            # CR 400.3: the card goes to its owner's exile, and its owner is the
            # player whose library it came out of — which is `caster` here, the
            # *searched* seat rather than the searching one.
            caster.exile.append(card)
        else:
            self.put_card_into_hand(caster, card)
        self.log.append(
            f"{caster.name} searched {zone} and put {card.name} "
            + (
                "onto the battlefield" if destination == "battlefield"
                else "into exile" if destination == "exile"
                else "into hand"
            )
        )
        # Only a library search shuffles (CR 701.23h, and the printed "If you
        # search your library this way, shuffle"): a graveyard is an open zone,
        # and randomising a library the player did not search would destroy
        # information they were entitled to keep.
        if zone == "library":
            random.shuffle(caster.library)
        self._record_search_reveal(choice)
        self.discard_pending_choice(choice)
        return True

    def _resolve_search_library_picks(self, choice: PendingChoice, picks: list) -> bool:
        """A counted search's one answer: every find at once (Cultivate).

        The picks are validated together before anything moves — each names a
        zone the search was armed with and a card the restriction admits, no
        card is taken twice, and each printed name is consumed by the find
        that used it (Alpine Houndmaster) — because a half-applied answer
        would leave the library short with the prompt still owed. An empty
        list is the fail-to-find (CR 701.19b): "up to" makes finding fewer a
        legal answer, and the library was searched either way.

        Where the finds land is a separate question the search does not
        answer: `_place_or_ask_destinations` applies the printed slots, and
        asks the finder which card fills which only when the slots differ.
        """
        slots = self._search_destination_slots(choice.data)
        if len(slots) < 2:
            # Not a counted search — the single-find path is its answer.
            return False
        if not picks:
            return self._resolve_search_library(choice, -1, "none")
        if len(picks) > len(slots):
            return False
        # Whose zones are looked in, which is not always the seat answering:
        # Jester's Cap's controller searches the *target's* library. The
        # single-find path beside this one has asked since Reincarnation; this
        # one read `choice.player_index`, which was latent only because no card
        # had yet combined a counted search with somebody else's zone.
        caster = self.players[searched_seat(choice.data, choice.player_index)]
        zones = tuple(choice.data.get("zones", ("library",)))
        working = dict(choice.data)
        seen: set[tuple[str, int]] = set()
        found: list = []
        for pick in picks:
            if not isinstance(pick, dict):
                return False
            zone = pick.get("zone", "library")
            index = pick.get("index", -1)
            if zone not in zones:
                return False
            source = caster.library if zone == "library" else caster.graveyard
            if not isinstance(index, int) or index < 0 or index >= len(source):
                return False
            if (zone, index) in seen:
                return False
            seen.add((zone, index))
            card = source[index]
            if not search_matches(card, working):
                return False
            # "a card named A **and/or** a card named B": each printed name is
            # one find, dropped as it is used, so a library holding two copies
            # of the first card cannot answer both finds with it.
            among = list((working.get("restrictions") or {}).get("named_among") or ())
            if among:
                from ...search_filters import name_key

                working["restrictions"] = {
                    **(working.get("restrictions") or {}),
                    "named_among": [
                        n for n in among if name_key(n) != name_key(card.name)
                    ],
                }
            found.append((zone, index, card))
        # Highest index first so the earlier picks still address the cards
        # they named (the two zones do not renumber each other).
        for zone, index, _card in sorted(found, key=lambda entry: entry[1], reverse=True):
            source = caster.library if zone == "library" else caster.graveyard
            source.pop(index)
        cards = [card for _zone, _index, card in found]
        # "…, reveal those cards, …" (CR 701.20): one showing for the whole
        # search, recorded now — the finds are known even while where each
        # lands is still being asked.
        if choice.data.get("reveal"):
            choice.data["revealed_names"] = [card.name for card in cards]
        self.log.append(
            f"{caster.name} searched " + " and ".join(zones) + " and found "
            + ", ".join(card.name for card in cards)
        )
        # The search is over once the finds are named (CR 701.19d): shuffle
        # before the destination question, which happens after the search.
        if "library" in zones:
            random.shuffle(caster.library)
        self._record_search_reveal(choice)
        self.discard_pending_choice(choice)
        self._place_or_ask_destinations(choice.player_index, cards, slots, choice.data)
        return True


    def _search_destination_slots(self, data: dict) -> list[tuple[str, bool]]:
        """The printed places a counted search's finds go, as (destination,
        enters-tapped) pairs in the printed order."""
        destinations = list(data.get("destinations") or ())
        tapped = list(data.get("tapped") or ())
        tapped += [False] * (len(destinations) - len(tapped))
        return list(zip(destinations, tapped))

    def _place_or_ask_destinations(
        self, seat: int, cards: list, slots: list[tuple[str, bool]], data: dict
    ) -> None:
        """Land the found cards, asking which goes where only when it matters.

        The question exists whenever the printed slots differ at all — with
        fewer finds than slots ("up to two … put one onto the battlefield
        tapped and the other into your hand", finding one), the finder still
        chooses which printed slot the card fills, which is Cultivate's
        ruling. Identical slots (both to hand, Alpine Houndmaster) have
        nothing to ask.
        """
        if not cards:
            return
        # Where a find *lands* is its own seat: "that player puts those cards
        # into their hand" (Jester's Mask) is the searched player's hand, not
        # the searcher's. Defaulted to the chooser, which is every other card.
        landing = landing_seat(data, seat)
        if len(set(slots)) <= 1:
            for card in cards:
                destination, tapped = slots[0]
                self._place_found_card(landing, card, destination, tapped)
            return
        self.arm_pending_choice(
            "search_destination", seat,
            card_name=data.get("card_name", ""),
            cards=[card.name for card in cards],
            slots=[
                {"destination": destination, "tapped": tapped}
                for destination, tapped in slots
            ],
            # Carried onto the next prompt because that prompt's own payload has
            # no zone seats on it, and the seat that answers "which card goes
            # where" is still not necessarily the seat the cards go to.
            landing_seat=landing,
            _cards=list(cards),
        )

    def _place_found_card(self, seat: int, card, destination: str, tapped: bool) -> None:
        """One found card landing where the print sent it.

        *seat* is whose zone receives it, which is not always the seat that
        chose — "Search target player's library for three cards and exile
        them" (Jester's Cap) puts them in that player's exile, because CR 400.3
        sends an object to its **owner's** zone and the owner is the player
        whose library it came out of.
        """
        caster = self.players[seat]
        if destination == "battlefield":
            from ...models import Permanent as _Permanent

            self._put_permanent_onto_battlefield(
                seat, _Permanent(card=card, tapped=tapped), None
            )
        elif destination == "exile":
            caster.exile.append(card)
        else:
            self.put_card_into_hand(caster, card)
        where = (
            "onto the battlefield tapped" if destination == "battlefield" and tapped
            else "onto the battlefield" if destination == "battlefield"
            else "into exile" if destination == "exile"
            else "into hand"
        )
        self.log.append(f"{caster.name} put {card.name} {where}")

    def _resolve_search_destination(self, choice: PendingChoice, assignments: list) -> bool:
        """Apply the finder's answer to "which found card goes where".

        ``assignments`` maps each found card, in the order the prompt listed
        them, to one printed slot. The slots must be distinct — two cards
        cannot both be the "one" put onto the battlefield — but with fewer
        cards than slots some slots go unfilled, which is how finding one
        card under a two-slot printing works.
        """
        cards = choice.data.get("_cards") or []
        slots = choice.data.get("slots") or []
        if len(assignments) != len(cards):
            return False
        if any(
            not isinstance(entry, int) or entry < 0 or entry >= len(slots)
            for entry in assignments
        ):
            return False
        if len(set(assignments)) != len(assignments):
            return False
        landing = int(choice.data.get("landing_seat", choice.player_index))
        for card, slot_index in zip(cards, assignments):
            slot = slots[slot_index]
            self._place_found_card(
                landing, card, slot["destination"], bool(slot.get("tapped"))
            )
        self.discard_pending_choice(choice)
        return True

    def _default_search_destination(self, choice: PendingChoice) -> None:
        """Printed order — the first find fills the first slot. The AI's search
        default picks its best card first, so under Cultivate its best land is
        the one that reaches the battlefield, matching the old split flow."""
        self._resolve_search_destination(
            choice, list(range(len(choice.data.get("_cards") or ())))
        )

    def _record_search_reveal(self, choice: PendingChoice) -> None:
        """The showing a printed "reveal it/those cards" performs, made when the
        search ends (a decline included — the finds already made were shown).
        One event and one log line for the whole search, because "those cards"
        is one showing, not one per find."""
        revealed = list(choice.data.get("revealed_names") or ())
        if not revealed:
            return
        caster = self.players[choice.player_index]
        self.record_reveal(choice.player_index, revealed)
        self.log.append(f"{caster.name} revealed {', '.join(revealed)}")

    def _default_search_library(self, choice: PendingChoice) -> None:
        """The AI's search policy, and a fail-to-find when it declines or when
        its choice turns out not to be legal — the library is searched either
        way (CR 701.19b), which is what the decline path performs."""
        from ...ai_policy import choose_search_card, choose_search_cards

        slots = self._search_destination_slots(choice.data)
        if len(slots) > 1:
            picks = choose_search_cards(
                self, choice.player_index, choice.data, len(slots)
            )
            if not self._resolve_search_library_picks(choice, picks):
                self._resolve_search_library(choice, -1, "none")
            return
        found = choose_search_card(self, choice.player_index, choice.data)
        if found is None or not self._resolve_search_library(choice, found[1], found[0]):
            self._resolve_search_library(choice, -1, "none")

    # -- Look at the top N, keep one, bottom the rest (See the Truth) ---------

    def confirm_look_top_pick(self, player_index: int, keep_index: int) -> bool:
        return self.resolve_pending_choice(
            "look_top_pick", player_index, keep_index=keep_index
        )

    def live_look_top_candidates(self, choice: PendingChoice) -> list[int]:
        """Which of the looked-at positions may be taken, in library order.

        Public because the prompt renderer is the second legitimate caller: what
        is offered and what an answer is checked against have to be one rule
        rather than two copies of it — the arrangement ``live_discard_candidates``
        already makes, and for the same reason.
        """
        from ...subject_filters import card_matches_any

        caster = self.players[choice.player_index]
        top_count = min(int(choice.data.get("top_count", 0)), len(caster.library))
        # "a creature card **or** Garruk planeswalker card" — the alternatives
        # are OR'd, exactly as a narrowed discard cost's are, because the two
        # sides restrict different characteristics and one filter AND's its
        # keys. No alternatives means no narrowing: any looked-at card may be
        # taken, which is See the Truth's shape.
        alternatives = tuple(choice.data.get("filters") or ())
        if not alternatives:
            described = dict(choice.data.get("filter") or {})
            alternatives = (described,) if described else ()
        return [
            index for index in range(top_count)
            if card_matches_any(caster.library[index], alternatives)
        ]

    def _resolve_look_top_pick(
        self, choice: PendingChoice, keep_index: int | None
    ) -> bool:
        caster = self.players[choice.player_index]
        top_count = min(int(choice.data.get("top_count", 0)), len(caster.library))
        looked = caster.library[:top_count]

        def _bottom_the_rest(rest: list) -> None:
            # "…and the other into your **graveyard**" (Waker of Waves). Where
            # the unchosen cards go is the card's own statement, so it is read
            # rather than assumed — a card that bottomed them instead is a
            # different card, and the difference is invisible until the pile is
            # looked at again.
            if choice.data.get("rest_destination") == "graveyard":
                for card in rest:
                    caster.graveyard.append(card)
                return
            # "…and the rest on **top** of your library in any order."
            # (Diabolic Vision.) The same clause as the bottom one word over,
            # and a different kind of sentence: on the bottom "in any order" is
            # a freedom nothing can observe, so this resolver has always just
            # laid them down. On top it *is* the effect — the next N draws —
            # so the order has to be asked for. Chained onto this answer rather
            # than folded into it: `reorder_library` is a prompt that already
            # exists, with its own UI, AI default and action, and CR 608.2 keeps
            # a decision armed by answering another inside the same resolution.
            if choice.data.get("rest_destination") == "library_top":
                caster.library[:0] = list(rest)
                if len(rest) > 1:
                    seat = self.seat_index(caster)
                    self.arm_pending_choice(
                        "reorder_library", seat,
                        target_index=seat, top_count=len(rest), may_shuffle=False,
                    )
                return
            # "…on the bottom of your library **in a random order**." (Garruk's
            # Harbinger.) A stated order, not the player's freedom: the cards
            # go down shuffled, through the module RNG `run_ai_simulation`
            # seeds so a given seed still replays exactly. "In any order" is the
            # other spelling and leaves them as they lay, because there the
            # ordering is the player's by rule and nothing reads it.
            if choice.data.get("rest_order") == "random":
                rest = list(rest)
                random.shuffle(rest)
            caster.library.extend(rest)

        # "**You may** reveal a … card from among them" (Garruk's Harbinger).
        # Declining is a legal answer, and it is not the same as an illegal one:
        # the rest still go to the bottom.
        if keep_index is None:
            if not choice.data.get("optional"):
                return False
            del caster.library[:top_count]
            _bottom_the_rest(looked)
            self.discard_pending_choice(choice)
            self.log.append(f"{caster.name} took nothing and put the rest on the bottom")
            return True

        if not isinstance(keep_index, int) or not (0 <= keep_index < top_count):
            return False
        # A card the printed phrase does not name is not a legal answer, and is
        # refused rather than slid onto one that is.
        if keep_index not in self.live_look_top_candidates(choice):
            return False
        kept = caster.library[keep_index]
        del caster.library[:top_count]
        _bottom_the_rest([card for i, card in enumerate(looked) if i != keep_index])
        self.put_card_into_hand(caster, kept)
        self.discard_pending_choice(choice)
        self.log.append(
            f"{caster.name} put {kept.name} into their hand and the rest on the bottom"
        )
        return True

    def _default_look_top_pick(self, choice: PendingChoice) -> None:
        """A non-interactive seat keeps the first card it *may* keep, and takes
        nothing when the phrase names none of them."""
        eligible = self.live_look_top_candidates(choice)
        keep = eligible[0] if eligible else None
        if not self._resolve_look_top_pick(choice, keep):
            self.discard_pending_choice(choice)

    # -- "Untap up to N <objects>" chosen on resolution (Rewind) --------------

    # -- Tap any number, then grow by however many (Siege Striker) -----------

    def confirm_tap_any_number(self, player_index: int, permanent_ids: list) -> bool:
        """*permanent_ids* addresses the chosen creatures by stable id. An empty
        list is a legal answer — "any number" includes none, and the card says
        "you **may**"."""
        return self.resolve_pending_choice(
            "tap_any_number", player_index, permanent_ids=permanent_ids
        )

    def live_tap_any_number(self, choice: PendingChoice) -> list:
        """The creatures this seat may still tap.

        Public because the prompt renderer is the second legitimate caller: the
        list offered and the list an answer is checked against have to be one
        rule rather than two copies of it.
        """
        described = dict(choice.data.get("filter") or {})
        untapped_only = bool(choice.data.get("untapped_only"))
        return [
            perm
            for perm in self.controlled_by(choice.player_index)
            if permanent_matches_filter(perm, described)
            and not (untapped_only and perm.tapped)
        ]

    def _resolve_tap_any_number(self, choice: PendingChoice, permanent_ids: list) -> bool:
        """Validated whole before anything taps, matching the untap picker: one
        bad id rejects the answer and leaves the prompt queued.

        The boost is applied here rather than by a later instruction, because
        the number *is* the answer — see the handler that armed this.
        """
        ids = [pid for pid in (permanent_ids or []) if isinstance(pid, int)]
        if len(ids) != len(permanent_ids or []) or len(set(ids)) != len(ids):
            return False
        live = self.live_tap_any_number(choice)
        chosen = []
        for pid in ids:
            perm = self.permanent_by_id(pid)
            if perm is None or not any(perm is candidate for candidate in live):
                return False
            chosen.append(perm)
        for perm in chosen:
            self.become_tapped(perm)
        card_name = choice.data.get("card_name", "")
        names = ", ".join(perm.card.name for perm in chosen) if chosen else "nothing"
        self.log.append(
            f"{self.players[choice.player_index].name} tapped {names} ({card_name})"
        )
        source = self.permanent_by_id(choice.data.get("source_id"))
        if source is not None and chosen:
            power = int(choice.data.get("power", 0)) * len(chosen)
            toughness = int(choice.data.get("toughness", 0)) * len(chosen)
            apply_temp_pt_boost(source, power, toughness)
            self.log.append(
                f"{source.card.name} gets {power:+}/{toughness:+} until end of turn "
                f"({len(chosen)} tapped this way)"
            )
        self.discard_pending_choice(choice)
        return True

    def _default_tap_any_number(self, choice: PendingChoice) -> None:
        """The stated policy: **tap everything eligible that is not attacking**.

        Every creature tapped is a permanent boost to the attacker, and this
        ability is printed on an attack trigger — so the only cost is losing a
        blocker, and a creature already attacking is not going to block anyway.
        A card that should choose otherwise needs a valuation, not a branch here.
        """
        picks = [
            self.permanent_id_of(perm)
            for perm in self.live_tap_any_number(choice)
            if not perm.attacking
        ]
        chosen = [pid for pid in picks if pid is not None]
        if not self._resolve_tap_any_number(choice, chosen):
            self._resolve_tap_any_number(choice, [])

    def confirm_untap_up_to(self, player_index: int, permanent_ids: list) -> bool:
        """*permanent_ids* addresses the chosen permanents by stable id — an
        empty list is a legal answer ("up to" includes zero)."""
        return self.resolve_pending_choice(
            "untap_up_to", player_index, permanent_ids=permanent_ids
        )

    def _resolve_untap_up_to(self, choice: PendingChoice, permanent_ids: list) -> bool:
        """Validated whole before anything untaps: one bad id rejects the
        answer and leaves the prompt queued, matching the exile search.

        ``cost_each`` is Mudslide's price per pick — charged once for the whole
        answer, because the payer chose the count and the price together
        (CR 601.2h asks whether they are *able* to pay what they chose). An
        answer they cannot afford is rejected whole, exactly as a bad id is:
        untapping half of it would be a card charging for what it did not do.
        """
        from ...subject_filters import subject_matches

        amount = int(choice.data.get("amount", 0))
        filt = dict(choice.data.get("filter") or {})
        observer = choice.data.get("observer")
        ids = [pid for pid in (permanent_ids or []) if isinstance(pid, int)]
        if len(ids) != len(permanent_ids or []) or len(set(ids)) != len(ids):
            return False
        if len(ids) > amount:
            return False
        chosen = []
        for pid in ids:
            perm = self.permanent_by_id(pid)
            # Through `subject_matches`, not the pure matcher: "tapped
            # creatures **without flying they control**" narrows by a keyword
            # (layer 6) and by a seat, and neither is answerable from the
            # object alone — handed to the pure matcher both keys would be
            # silently ignored, which is a strictly larger set than the card
            # names.
            if perm is None or not subject_matches(
                self, perm, filt,
                observer=observer if isinstance(observer, int) else choice.player_index,
            ):
                return False
            chosen.append(perm)
        payer = self.players[choice.player_index]
        plan = None
        cost_each = dict(choice.data.get("cost_each") or {})
        if cost_each and chosen:
            total = {
                symbol: count * len(chosen)
                for symbol, count in cost_each.items() if count
            }
            plan = self._optional_pay_plan(payer, {"cost": total})
            if plan is None:
                return False
        for perm in chosen:
            self.become_untapped(perm)
        if plan is not None:
            self._spend_payment_plan(payer, plan)
        names = ", ".join(perm.card.name for perm in chosen) if chosen else "nothing"
        self.log.append(
            f"{self.players[choice.player_index].name} untapped {names} "
            f"({choice.data.get('card_name', '')})"
        )
        self.discard_pending_choice(choice)
        return True

    def _default_untap_up_to(self, choice: PendingChoice) -> None:
        """A non-interactive seat untaps its own tapped matching permanents,
        oldest first — its own because untapping an opponent's land is a gift,
        and tapped ones because untapping an untapped land is a wasted pick.

        With a price on each pick (Mudslide), the count is capped by what the
        *floating* mana covers — the same stated policy `_default_optional_pay`
        takes, and for its reason: tapping a land for an optional cost is a
        real decision about the rest of the turn, and it belongs to the seat
        that was actually asked.
        """
        amount = int(choice.data.get("amount", 0))
        filt = dict(choice.data.get("filter") or {})
        own = [
            perm for perm in self.controlled_by(choice.player_index)
            if perm.tapped and permanent_matches_filter(perm, filt)
        ]
        cost_each = {k: v for k, v in (choice.data.get("cost_each") or {}).items() if v}
        if cost_each:
            payer = self.players[choice.player_index]
            affordable = 0
            while affordable < min(amount, len(own)):
                total = {s: c * (affordable + 1) for s, c in cost_each.items()}
                if plan_payment(payer.mana_pool, (), total) is None:
                    break
                affordable += 1
            amount = affordable
        picks = [self.permanent_id_of(perm) for perm in own[:amount]]
        if not self._resolve_untap_up_to(choice, [p for p in picks if p is not None]):
            self._resolve_untap_up_to(choice, [])

    # -- Two-zone exile search (Chandra, Heart of Fire's −9) ------------------

    def confirm_search_exile(self, caster_index: int, picks: list) -> bool:
        """*picks* is any number of ``{"zone": "library"|"graveyard",
        "index": int}`` entries — "any number" includes zero, which is this
        search's fail-to-find (CR 701.23b)."""
        return self.resolve_pending_choice(
            "search_exile_cards", caster_index, picks=picks
        )

    @staticmethod
    def _exile_search_matches(card, data: dict) -> bool:
        card_types = tuple(data.get("card_types") or ())
        colors = tuple(data.get("colors") or ())
        if card_types and card.primary_type not in card_types:
            return False
        if colors and not any(color in card.colors for color in colors):
            return False
        return True

    def _resolve_search_exile(self, choice: PendingChoice, picks: list) -> bool:
        """Every pick is validated before anything moves — a single bad entry
        rejects the whole answer and leaves the prompt queued, so a malformed
        request cannot exile half a selection."""
        caster = self.players[choice.player_index]
        zones = tuple(choice.data.get("zones", ("graveyard", "library")))
        seen: set[tuple[str, int]] = set()
        cleaned: list[tuple[str, int]] = []
        for pick in picks or []:
            zone = pick.get("zone") if isinstance(pick, dict) else None
            index = pick.get("index") if isinstance(pick, dict) else None
            if zone not in zones:
                return False
            source = caster.library if zone == "library" else caster.graveyard
            if not isinstance(index, int) or not (0 <= index < len(source)):
                return False
            if (zone, index) in seen:
                return False
            seen.add((zone, index))
            if not self._exile_search_matches(source[index], choice.data):
                return False
            cleaned.append((zone, index))
        exiled = []
        for zone in ("library", "graveyard"):
            source = caster.library if zone == "library" else caster.graveyard
            for _, index in sorted(
                (pick for pick in cleaned if pick[0] == zone),
                key=lambda pick: -pick[1],
            ):
                card = source.pop(index)
                caster.exile.append(card)
                exiled.append(card)
        # The library was searched whether or not anything was taken from it,
        # and the printed "then shuffle" applies to the search, not the find.
        if "library" in zones:
            random.shuffle(caster.library)
        ctx = choice.data.get("_context")
        if ctx is not None:
            ctx.results["exiled_cards"] = exiled
        self.discard_pending_choice(choice)
        self.log.append(
            f"{caster.name} searched graveyard and library and exiled "
            + (", ".join(card.name for card in exiled) if exiled else "nothing")
        )
        return True

    def _default_search_exile(self, choice: PendingChoice) -> None:
        """A non-interactive seat takes everything that matches: "any number"
        is a may per card, and the cards come back castable, so the maximum is
        the only default that never leaves value on the table."""
        caster = self.players[choice.player_index]
        picks = [
            {"zone": zone, "index": index}
            for zone in ("graveyard", "library")
            if zone in tuple(choice.data.get("zones", ("graveyard", "library")))
            for index, card in enumerate(
                caster.graveyard if zone == "graveyard" else caster.library
            )
            if self._exile_search_matches(card, choice.data)
        ]
        if not self._resolve_search_exile(choice, picks):
            self._resolve_search_exile(choice, [])

    # -- Library reorder ----------------------------------------------------

    def confirm_reorder_library(self, caster_index: int, new_order: list, shuffle: bool = False) -> bool:
        return self.resolve_pending_choice(
            "reorder_library", caster_index, new_order=new_order, shuffle=shuffle
        )

    def _resolve_reorder_library(self, choice: PendingChoice, new_order: list, shuffle: bool) -> bool:
        target = self.players[choice.data["target_index"]]
        top_count = choice.data["top_count"]
        top = target.library[:top_count]
        rest = target.library[top_count:]
        # "Look at the top five cards of target player's library" (Visions) and
        # nothing else — the looker learns the order but never gets to change
        # it. Enforced here rather than by hiding the drag handles: a
        # permission only the client honours is a rule nothing enforces, and
        # this prompt is answered by whatever the wire sends.
        if not choice.data.get("may_reorder", True):
            new_order = list(range(top_count))
        if len(new_order) != top_count or sorted(new_order) != list(range(top_count)):
            return False
        target.library = [top[i] for i in new_order] + rest
        # "You may have that player shuffle" (Natural Selection): only honored when
        # the effect allows it.
        if shuffle and choice.data.get("may_shuffle"):
            random.shuffle(target.library)
            self.log.append(f"{target.name}'s library was shuffled")
        else:
            self.log.append(f"Top {top_count} cards of {target.name}'s library reordered")
        self.discard_pending_choice(choice)
        return True

    def _default_reorder_library(self, choice: PendingChoice) -> None:
        from ...ai_policy import choose_reorder_library_order

        order = choose_reorder_library_order(
            self, choice.player_index, choice.data["target_index"], choice.data["top_count"]
        )
        if not self._resolve_reorder_library(choice, order, shuffle=False):
            self.discard_pending_choice(choice)

    # -- Scry ---------------------------------------------------------------

    def confirm_scry(self, caster_index: int, card_order: list, bottom_count: int) -> bool:
        return self.resolve_pending_choice(
            "scry", caster_index, card_order=card_order, bottom_count=bottom_count
        )

    def _resolve_scry(self, choice: PendingChoice, card_order: list, bottom_count: int) -> bool:
        """CR 701.22a. ``card_order`` is a permutation of the looked-at cards
        reading top-first: the leading ``top_count - bottom_count`` entries go
        back on top in that order, the trailing ``bottom_count`` to the bottom
        in that order.

        One permutation plus a count rather than two lists, so the validation is
        the same total-permutation check ``_resolve_reorder_library`` makes —
        two lists could overlap or omit a card and still look plausible.
        """
        caster = self.players[choice.player_index]
        top_count = choice.data["top_count"]
        if sorted(card_order) != list(range(top_count)):
            return False
        if not 0 <= bottom_count <= top_count:
            return False
        looked = caster.library[:top_count]
        rest = caster.library[top_count:]
        kept = [looked[i] for i in card_order[: top_count - bottom_count]]
        bottomed = [looked[i] for i in card_order[top_count - bottom_count :]]
        # The bottomed cards go under everything that was already below the
        # looked-at ones, which is why `rest` sits between the two slices.
        caster.library = kept + rest + bottomed
        self.log.append(
            f"{caster.name} scried {top_count} ({bottom_count} to the bottom)"
        )
        self.discard_pending_choice(choice)
        return True

    def _default_scry(self, choice: PendingChoice) -> None:
        from ...ai_policy import choose_scry_arrangement

        card_order, bottom_count = choose_scry_arrangement(
            self, choice.player_index, choice.data["top_count"]
        )
        if not self._resolve_scry(choice, card_order, bottom_count):
            self.discard_pending_choice(choice)

    # -- Discard ------------------------------------------------------------

    def confirm_discard(self, player_index: int, hand_indices: list[int], to_library: bool = False) -> bool:
        """Resolve a pending non-random discard (Disrupting Scepter) with the
        player's chosen cards. ``to_library`` puts them on top of the library
        instead of the graveyard, but only if Library of Leng allows it."""
        return self.resolve_pending_choice(
            "discard", player_index, hand_indices=hand_indices, to_library=to_library
        )

    def live_discard_candidates(self, choice: PendingChoice) -> list[int]:
        """The hand positions this seat may still discard, in hand order.

        Public because the prompt renderer is the second legitimate caller: the
        list offered and the list an answer is checked against have to be one
        rule rather than two copies of it — the same arrangement
        ``live_tap_any_number`` makes, and the same failure it prevents.
        """
        from ...subject_filters import card_matches_any

        described = dict(choice.data.get("filter") or {})
        hand = self.players[choice.player_index].hand
        alternatives = (described,) if described else ()
        # "Draw two cards, then discard one **of them**." (Krovikan Sorcerer.)
        # An identity restriction rather than a characteristic one, so it
        # arrives as the hand positions the arming step drew into rather than as
        # a filter: every copy of a card in a hand is the *same* Python object
        # (`web/deck_builder.py` repeats one definition per copy), so "one of
        # the cards you just drew" cannot be told from "another copy of the same
        # card you were already holding" by anything but position.
        only = choice.data.get("only_indices")
        allowed = set(only) if only is not None else None
        return [
            index for index, card in enumerate(hand)
            if (allowed is None or index in allowed)
            and card_matches_any(card, alternatives)
        ]

    def _resolve_discard(self, choice: PendingChoice, hand_indices: list[int], to_library: bool) -> bool:
        from ...handlers.zones import _resolve_one_discard

        count = int(choice.data["count"])
        chosen = [i for i in dict.fromkeys(hand_indices)][:count]
        # "Discard **up to** two cards" (Kinetic Augur): fewer is a legal answer,
        # none included. A ceiling read as an exact count would force the player
        # to pitch cards they were offered the choice of keeping.
        if len(chosen) != count and not choice.data.get("up_to"):
            return False
        # "Discard a **creature** card": a card the phrase does not name is not
        # a legal answer, and is refused rather than slid onto one that is — a
        # stale click must not throw away a card the player meant to keep.
        eligible = set(self.live_discard_candidates(choice))
        if any(index not in eligible for index in chosen):
            return False
        # Remove in descending order so earlier indices stay valid as we pop.
        for hand_index in sorted(chosen, reverse=True):
            if not _resolve_one_discard(self, choice.player_index, hand_index, to_library):
                return False
        self.discard_pending_choice(choice)
        self._after_discard_answered(choice, len(chosen))
        return True

    def _after_discard_answered(self, choice: PendingChoice, discarded: int) -> None:
        """Everything that reads *how many* cards were actually discarded.

        One place, because both answer paths — a seat's own picks and the
        non-interactive default — reach it, and the number is knowable nowhere
        else: nothing downstream of a queued choice can read a count the player
        has not given yet.

        Two readers today. "…then draw that many cards" (Kinetic Augur) is the
        fused shape, whose follow-on the prompt was armed with. The other is the
        ordinary back-reference: a discard that recorded its count into the
        resolution scratchpad lets "…for each card discarded this way" (Recall)
        be a later step of an ordinary ``sequence`` rather than a second fused
        kind. Discarding nothing records a zero, which is what both sentences
        say.
        """
        results = choice.data.get("_results")
        if results is not None:
            results["discarded_count"] = discarded
            # And the per-seat tally, which is the same fact asked the way a
            # sentence about "**they**" asks it. Written beside the single
            # number rather than instead of it: "…then draw that many" reads
            # one seat's answer where "damage to each player equal to 3 minus
            # the number of cards they discarded" reads every seat's, and one
            # key cannot be both.
            by_seat = results.setdefault(DISCARDED_BY_SEAT, {})
            by_seat[choice.player_index] = discarded
        player = self.players[choice.player_index]
        if choice.data.get("draw_that_many") and discarded > 0:
            # CR 614.5: a draw a replacement effect *created* is not replaced
            # again by that same effect. The prompt carries which sources have
            # already had their opportunity (Chains of Mephistopheles), and an
            # ordinary "discard, then draw that many" carries none.
            drawn = self._draw_with_replacements(
                player,
                discarded,
                exclude_sources=tuple(choice.data.get("draw_exclude_sources") or ()),
            )
            self.log.append(f"{player.name} drew {drawn} card(s) for the cards discarded")
        # The draws that were queued *behind* the one this prompt replaced.
        # CR 121.2 makes "draw three cards" three individual draws; a
        # replacement takes one of them and the rest have to wait for the
        # answer, because they are later steps of the same instruction.
        queued = int(choice.data.get("queued_draws", 0) or 0)
        if queued > 0:
            self._draw_with_replacements(player, queued)

    def confirm_revealed_hand_pick(self, player_index: int, hand_index: int) -> bool:
        return self.resolve_pending_choice(
            "revealed_hand_pick", player_index, hand_index=hand_index
        )

    def _resolve_revealed_hand_pick(self, choice: PendingChoice, hand_index: int) -> bool:
        """The caster's pick out of a revealed hand (Duress).

        The legal indices are re-checked against the record armed with the
        choice rather than trusted from the wire: a client offering the whole
        hand would otherwise turn "a noncreature, nonland card" into "any card",
        which is the same hole the search picker closed.
        """
        if hand_index not in (choice.data.get("legal_indices") or []):
            return False
        victim_index = int(choice.data["victim_index"])
        if not self._apply_revealed_hand_fate(choice, victim_index, hand_index):
            return False
        self.discard_pending_choice(choice)
        self._rearm_revealed_hand_pick(choice, victim_index)
        return True

    def _default_revealed_hand_pick(self, choice: PendingChoice) -> None:
        """A non-interactive caster takes the costliest legal card.

        A stated policy, like the up-to-N maximum and the modal first mode: mana
        value is the one ranking every card in the pool answers, and a card that
        wants a cleverer pick needs a valuation rather than a special case here.
        """
        legal = list(choice.data.get("legal_indices") or [])
        victim_index = int(choice.data["victim_index"])
        taken = False
        if legal and 0 <= victim_index < len(self.players):
            hand = self.players[victim_index].hand
            legal.sort(key=lambda i: (-(hand[i].cmc if i < len(hand) else 0), i))
            taken = self._apply_revealed_hand_fate(choice, victim_index, legal[0])
        self.discard_pending_choice(choice)
        if taken:
            self._rearm_revealed_hand_pick(choice, victim_index)

    def _rearm_revealed_hand_pick(self, choice: PendingChoice, victim_index: int) -> None:
        """"…choose **X** cards from it" (Mind Warp) — the picks after the first.

        A chain of one-card prompts rather than one multi-select, because
        taking a card renumbers the hand behind it: the legal indices have to be
        recomputed against the hand as it now stands, and a set answered all at
        once against stale indices is the bug the counted search's atomic answer
        exists to avoid. The pending-choice queue is built for this — a prompt
        armed by *answering* an earlier one keeps the same resolution open.

        The chooser sees the whole hand each time, so nothing is decided with
        less information than the printed simultaneous choice gives.
        """
        remaining = int(choice.data.get("remaining", 1)) - 1
        if remaining <= 0 or not 0 <= victim_index < len(self.players):
            return
        exclude_types = list(choice.data.get("exclude_types") or ())
        victim = self.players[victim_index]
        legal = [
            index
            for index, held in enumerate(victim.hand)
            if search_matches(held, {"exclude_types": exclude_types})
        ]
        if not legal:
            return
        self.arm_pending_choice(
            "revealed_hand_pick", choice.player_index,
            card_name=choice.data.get("card_name", ""),
            victim_index=victim_index,
            legal_indices=legal,
            remaining=min(remaining, len(legal)),
            fate=str(choice.data.get("fate", "discard")),
            exclude_types=exclude_types,
            source_id=choice.data.get("source_id"),
        )

    def _apply_revealed_hand_fate(
        self, choice: PendingChoice, victim_index: int, hand_index: int
    ) -> bool:
        """What happens to the chosen card. One place, because the family varies
        only here — Duress discards it, and the exile ending arrives with the
        card that needs it."""
        from ...handlers.zones import _resolve_one_discard
        from ...linked_exile import LEAVES, link_exiled_card

        fate = str(choice.data.get("fate", "discard"))
        if fate == "discard":
            return _resolve_one_discard(self, victim_index, hand_index, to_library=False)
        if fate != "exile_until_source_leaves":
            return False
        # "Exile that card until this creature leaves the battlefield."
        # (Kitesail Freebooter.) The card is held *by the source*, not by the
        # game: what returns it is the source leaving, and a record on the
        # permanent is a record that goes wherever the permanent does — the
        # linked-exile shape CR 400.7 needs, since the returning card is a new
        # object and nothing may hold a stale reference to it.
        source = self.permanent_by_id(choice.data.get("source_id"))
        victim = self.players[victim_index]
        if source is None or not 0 <= hand_index < len(victim.hand):
            return False
        card = victim.hand.pop(hand_index)
        victim.exile.append(card)
        link_exiled_card(
            source, card, victim_index, to="hand", ends_on=(LEAVES,)
        )
        self.log.append(
            f"{card.name} is exiled until {source.card.name} leaves the battlefield"
        )
        return True

    # -- Hand back onto the library ------------------------------------------

    def confirm_hand_to_library(self, player_index: int, hand_indices: list[int]) -> bool:
        """Resolve a pending "put N cards from your hand on top of your library"
        (Brainstorm, Stunted Growth) with the player's chosen cards.

        The order of *hand_indices* is the order the card gives them ("in any
        order"): the first named ends up on top.
        """
        return self.resolve_pending_choice(
            "hand_to_library", player_index, hand_indices=hand_indices
        )

    def _resolve_hand_to_library(
        self, choice: PendingChoice, hand_indices: list[int]
    ) -> bool:
        """Move the chosen cards, last-named first, so the first is on top.

        Each card is taken through ``take_card_from_hand`` and put through
        ``put_card_into_library`` — the two seams, both of which exist because
        the obvious spelling is wrong: a hand holds the *same object* for every
        copy of a card, and CR 903.9b can divert a card headed for a library.

        The cards are read out **before** any of them move, because taking one
        renumbers the hand behind it — the same reason ``_default_discard``
        re-reads its candidate list each time round, arrived at from the other
        direction.
        """
        count = int(choice.data["count"])
        hand = self.players[choice.player_index].hand
        chosen = [i for i in dict.fromkeys(hand_indices) if 0 <= i < len(hand)][:count]
        if len(chosen) != count:
            return False
        player = self.players[choice.player_index]
        cards = [hand[index] for index in chosen]
        for card in reversed(cards):
            if self.take_card_from_hand(player, card):
                self.put_card_into_library(player, card, position="top")
        self.log.append(
            f"{player.name} put {len(cards)} card(s) on top of their library"
        )
        self.discard_pending_choice(choice)
        return True

    def _default_hand_to_library(self, choice: PendingChoice) -> None:
        """Put the lowest-index cards back, in hand order.

        Lowest-index is the same stated policy ``_default_discard`` takes, and
        for the same reason: which cards are *legal* answers is the card's
        business and there is no restriction here, so anything past "enough of
        them" is AI valuation rather than rules.
        """
        count = min(int(choice.data["count"]), len(self.players[choice.player_index].hand))
        if not self._resolve_hand_to_library(choice, list(range(count))):
            self.discard_pending_choice(choice)

    def _default_discard(self, choice: PendingChoice) -> None:
        """Discard the lowest-index *eligible* cards, keeping them in the
        graveyard.

        Lowest-index is the stated policy; which cards are candidates at all is
        not policy but the card's printed phrase, so it is read from the same
        list the interactive seat is offered. Re-read each time round, because
        each discard renumbers the hand behind it.
        """
        from ...handlers.zones import _resolve_one_discard

        discarded = 0
        for _ in range(int(choice.data["count"])):
            eligible = self.live_discard_candidates(choice)
            if not eligible:
                break
            if not _resolve_one_discard(
                self, choice.player_index, eligible[0], to_library=False
            ):
                break
            discarded += 1
        self.discard_pending_choice(choice)
        # The stated policy for "up to" is to take the whole offer: this pairing
        # only ever prints with a draw behind it, so discarding fewer is
        # strictly less card selection for the same cards.
        self._after_discard_answered(choice, discarded)

    def auto_resolve_pending_discard(self) -> None:
        """Resolve a pending discard with a default choice (the lowest-index cards,
        kept in the graveyard). Used for AI players and headless simulation."""
        self.auto_resolve_pending_choices(kinds=("discard",))

    def confirm_commander_zone_change(self, player_index: int, to_command_zone: bool) -> bool:
        """Resolve the oldest pending CR 903.9 offer for *player_index*: the
        commander goes into the command zone, or on to where it was headed."""
        return self.resolve_replacement_choice(
            player_index, 0 if to_command_zone else 1, kind="commander_zone_change"
        )

    def confirm_optional_damage_redirect(
        self, player_index: int, take_the_damage: bool
    ) -> bool:
        """Resolve the oldest pending CR 614.9 "you may have that damage dealt
        to you instead" offer for *player_index*."""
        return self.resolve_replacement_choice(
            player_index, 0 if take_the_damage else 1, kind="optional_damage_redirect"
        )

    def confirm_leng_discard(self, player_index: int, to_library: bool) -> bool:
        """Resolve the oldest pending Library of Leng destination choice for
        *player_index*: the discarded card goes on top of their library (the
        optional CR 701.9c replacement) or into their graveyard."""
        return self.resolve_replacement_choice(
            player_index, 0 if to_library else 1, kind="leng_discard"
        )

    # -- Phantasmal Terrain's land type -------------------------------------

    _BASIC_LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest")

    def confirm_land_type(self, player_index: int, land_type: str) -> bool:
        """Resolve a pending Phantasmal Terrain choice with the controller's chosen
        basic land type, overriding the provisional default on the enchanted land."""
        return self.resolve_pending_choice("land_type_choice", player_index, land_type=land_type)

    def _resolve_land_type(self, choice: PendingChoice, land_type: str) -> bool:
        land_type = str(land_type or "").strip().lower()
        if land_type not in self._BASIC_LAND_TYPES:
            return False
        owner = self.players[choice.data["land_owner_index"]]
        idx = choice.data["land_index"]
        if 0 <= idx < len(owner.battlefield):
            land = owner.battlefield[idx]
            # Keyed on the Aura, so the change ends when the Aura does — and
            # ends only its own contribution.
            change_land_type(
                land, land_type,
                source=choice.data.get("_aura"), label=choice.data["card_name"],
            )
            self.log.append(
                f"{choice.data['card_name']}: enchanted land becomes a {land_type.title()}"
            )
        self.discard_pending_choice(choice)
        return True

    # -- "Choose a number between N and M" -----------------------------------

    def confirm_number_choice(self, player_index: int, number: int) -> bool:
        """Answer Shapeshifter's "choose a number" prompt with *number*."""
        return self.resolve_pending_choice(
            "number_choice", player_index, number=number
        )

    def _resolve_number_choice(self, choice: PendingChoice, number) -> bool:
        """Record the chosen number on the permanent that asked for it.

        Out of range is a **rejection**, not a clamp: the prompt names the range
        the card prints, and silently repairing an answer would let a caller ask
        for a 12/-5 body and be told it worked.
        """
        try:
            value = int(number)
        except (TypeError, ValueError):
            return False
        low = int(choice.data.get("minimum", 0))
        high = int(choice.data.get("maximum", 0))
        if not (low <= value <= high):
            return False
        permanent = choice.data.get("permanent")
        if permanent is not None:
            if choice.data.get("exile_own_tokens"):
                # Tetravus's second upkeep trigger. Oldest first, and only as
                # many as are still there — a token that died while the prompt
                # was owed is not one this can take.
                from ...tokens import tokens_created_with

                owned = tokens_created_with(self, permanent)[:value]
                for token in owned:
                    owner_index = self.owner_index_of(token)
                    self.remove_from_battlefield(token)
                    # Into exile like any other exiled permanent (CR 400.3,
                    # owner's zone); CR 111.7's sweep in game_ending.py takes
                    # the token card out of it, so nothing here special-cases
                    # the fact that it is a token.
                    if owner_index is not None:
                        self.players[owner_index].exile.append(token.card)
                results = choice.data.get("results")
                if results is not None:
                    results["trigger_count"] = len(owned)
                self.log.append(
                    f"{choice.data.get('card_name')}: exiled {len(owned)} token(s)"
                )
            elif choice.data.get("remove_counters"):
                # Tetravus: the number *is* how many +1/+1 counters come off,
                # and the count that actually came off is what the sentence
                # after it reads — asking for more than are there takes what is
                # there, so the record is the return value and not the request.
                from ...pt import remove_plus1_counters

                removed = remove_plus1_counters(permanent, value)
                results = choice.data.get("results")
                if results is not None:
                    results["trigger_count"] = removed
                self.log.append(
                    f"{choice.data.get('card_name')}: removed {removed} "
                    "+1/+1 counter(s)"
                )
            elif choice.data.get("pay_life_onto"):
                # Nameless Race. The number *is* an amount of life, so it is
                # paid rather than merely recorded - and what is recorded is
                # the payment, which the characteristic-defining P/T reads back
                # off the permanent. Its own branch beside the two above for
                # their reason: the shape is one prompt, and what the answer
                # buys is what differs.
                # Directly, the way every other *cost* payment of life in this
                # engine is made (`mixins/stack/activation.py` charges
                # `cost.pay_life` the same way): CR 118.8 says paying life is
                # not losing life, so this must not go through the life-loss
                # seam and fire a "whenever you lose life" trigger.
                self.players[choice.player_index].life -= value
                permanent.metadata["life_paid_as_entered"] = value
                self.log.append(
                    f"{choice.data.get('card_name')}: paid {value} life"
                )
            else:
                permanent.metadata["chosen_number"] = value
                self.log.append(
                    f"{choice.data.get('card_name')}: chose {value}"
                )
            # The number *defines* a characteristic (CR 604.3), so the P/T that
            # reads it is stale until the layers are recomputed.
            self._refresh_dynamic_creatures()
        self.discard_pending_choice(choice)
        return True

    def _default_number_choice(self, choice: PendingChoice) -> bool:
        """A seat that is not asked keeps the number already stamped — the
        middle of the printed range at entry, and whatever was chosen before at
        an upkeep. "May" means the upkeep default is genuinely *not* to change
        it, so this is the rule rather than a stand-in for one."""
        return self._resolve_number_choice(
            choice, choice.data.get("default_number", choice.data.get("minimum", 0))
        )

    # -- "As this enters, choose an opponent [and a color]" -------------------

    def confirm_name_and_strip(self, player_index: int, card_name: str) -> bool:
        """Answer Necromentia's "choose a card name" prompt."""
        return self.resolve_pending_choice(
            "name_and_strip", player_index, card_name=card_name
        )

    def _resolve_name_and_strip(self, choice: PendingChoice, card_name: str) -> bool:
        """Strip every copy of *card_name* from the named zones and pay the
        Zombies.

        CR 202.1 lets a player name any card; the one printed restriction is
        that it may not be a basic land's name, and that is enforced here rather
        than by the prompt's option list — the list is a convenience, the rule
        is the rule.

        The zones are searched in the printed order, and only the count from
        ``token_zone`` feeds the tokens: "each card exiled from their **hand**
        this way" is a strict subset of what was exiled, and counting the whole
        pile would make far more Zombies than the card promises.
        """
        from ...tokens import make_token_card

        data = choice.data
        target = self.players[data["target_seat"]]
        named = (card_name or "").strip()
        if not named:
            self.discard_pending_choice(choice)
            self.log.append("nothing was named, so nothing was exiled")
            return True
        if any(
            "basic" in (card.type_line or "").lower() and card.name == named
            for zone in data["zones"] for card in getattr(target, zone, [])
        ):
            return False

        taken_from: dict[str, int] = {}
        for zone in data["zones"]:
            cards = getattr(target, zone, [])
            kept = [card for card in cards if card.name != named]
            taken = [card for card in cards if card.name == named]
            if taken:
                taken_from[zone] = len(taken)
                cards[:] = kept
                target.exile.extend(taken)
        # "That player shuffles" — once, after the search, and only their
        # library is disturbed (CR 701.24).
        random.shuffle(target.library)

        spec = data["token"]
        made = taken_from.get(data["token_zone"], 0)
        for _ in range(made):
            token_card = make_token_card(
                " ".join(w.title() for w in spec["subtypes"]) + " Token",
                int(spec["power"]), int(spec["toughness"]),
                "Creature — " + " ".join(w.title() for w in spec["subtypes"]),
                colors=tuple(spec["colors"]),
            )
            self._put_permanent_onto_battlefield(
                data["target_seat"],
                Permanent(card=token_card, metadata={"is_token": True}),
                None,
            )
        self.discard_pending_choice(choice)
        self.log.append(
            f"{target.name} lost {sum(taken_from.values())} copies of {named} "
            f"and made {made} token(s)"
        )
        return True

    def _default_name_and_strip(self, choice: PendingChoice) -> None:
        if not self._resolve_name_and_strip(choice, choice.data.get("default_name", "")):
            self.discard_pending_choice(choice)

    # -- "Target player chooses a card name, then reveals the top card" -------

    def confirm_name_then_reveal_top(self, player_index: int, card_name: str) -> bool:
        """Answer Petra Sphinx's "choose a card name" prompt."""
        return self.resolve_pending_choice(
            "name_then_reveal_top", player_index, card_name=card_name
        )

    def _resolve_name_then_reveal_top(
        self, choice: PendingChoice, card_name: str
    ) -> bool:
        """Reveal the top card and send it where the guess says.

        The reveal happens **here**, after the name is fixed: turning the card
        over while the prompt was open would tell the chooser what to name.

        CR 202.1 lets a player name any card at all and this card prints no
        restriction, so no name is refused — including one no card in the game
        bears, which simply misses. The comparison is against the card's own
        printed name, not an effective one: nothing in a library is a permanent
        and nothing there can be copying anything (CR 706.2).
        """
        data = choice.data
        player = self.players[choice.player_index]
        if not player.library:
            # The library emptied between arming and answering. Nothing to
            # reveal, so nothing moves.
            self.discard_pending_choice(choice)
            self.log.append(f"{player.name} has no card to reveal")
            return True
        named = (card_name or "").strip()
        revealed = player.library.pop(0)
        hit = bool(named) and revealed.name == named
        zone_name = data["match_zone"] if hit else data["miss_zone"]
        # The hand is reached through the CR 614 seam every other "put this card
        # into a hand" in this engine goes through — a commander on its way to a
        # hand goes to the command zone instead (CR 903.9b), and thirty fire
        # sites is twenty-nine places to forget it.
        if zone_name == "hand":
            self.put_card_into_hand(player, revealed)
        else:
            getattr(player, zone_name).append(revealed)
        self.discard_pending_choice(choice)
        self.log.append(
            f"{player.name} named {named or 'nothing'} and revealed "
            f"{revealed.name} — it goes to their {zone_name}"
        )
        # "…and this artifact deals 2 damage to them" (Vexing Arcanix). Only on
        # a miss, and after the card has moved, because that is the printed
        # order. Through the one damage entry point, so the shields, the CR 614
        # replacements and the "dealt damage" triggers all see it.
        miss_damage = 0 if hit else int(data.get("miss_damage", 0) or 0)
        if miss_damage:
            self._deal_damage_to_player(
                player, miss_damage, source=data.get("_damage_source"),
                then=lambda dealt: self.log.append(
                    f"{player.name} is dealt {dealt} damage for the miss"
                ),
            )
        return True

    def _default_name_then_reveal_top(self, choice: PendingChoice) -> None:
        if not self._resolve_name_then_reveal_top(
            choice, choice.data.get("default_name", "")
        ):
            self.discard_pending_choice(choice)

    # -- "Choose a card name, then consult your own library" -----------------

    def confirm_name_then_consult(self, player_index: int, card_name: str) -> bool:
        """Answer Demonic Consultation's "choose a card name" prompt."""
        return self.resolve_pending_choice(
            "name_then_consult", player_index, card_name=card_name
        )

    def _resolve_name_then_consult(
        self, choice: PendingChoice, card_name: str
    ) -> bool:
        """Exile the top N, then reveal down to the named card.

        Everything happens **after** the name is fixed, which is the whole
        card: the six exiled cards are never looked at, so the name may be
        among them and the reveal may then run the library out. That is not a
        failure and not a loss — CR 704.5b only fires when a player actually
        attempts to draw from an empty library, so the spell finishes and the
        next draw step is what kills them.

        CR 202.1 lets a player name any card at all and this spell prints no
        restriction, so no name is refused. The comparison is against the
        card's printed name: nothing in a library is a permanent, so nothing
        there can be copying anything (CR 706.2).
        """
        player = self.players[choice.player_index]
        named = (card_name or "").strip()
        exile_count = int(choice.data.get("exile_count", 0) or 0)
        paid = [player.library.pop(0) for _ in range(min(exile_count, len(player.library)))]
        player.exile.extend(paid)
        revealed: list = []
        found = None
        while player.library:
            card = player.library.pop(0)
            revealed.append(card)
            if named and card.name == named:
                found = card
                break
        # "…and exile all other cards revealed this way" — everything the
        # reveal turned over except the find, in the order it was turned over.
        for card in revealed:
            if card is found:
                continue
            player.exile.append(card)
        if found is not None:
            # Through the CR 614 seam every "put this card into a hand" uses,
            # so a commander headed for a hand goes to the command zone instead
            # (CR 903.9b).
            self.put_card_into_hand(player, found)
        self.discard_pending_choice(choice)
        self.log.append(
            f"{player.name} named {named or 'nothing'}, exiled {len(paid)} card(s) "
            + (
                f"and revealed down to {found.name}"
                if found is not None
                else f"and revealed their whole library ({len(revealed)} card(s)) without finding it"
            )
        )
        return True

    def _default_name_then_consult(self, choice: PendingChoice) -> None:
        if not self._resolve_name_then_consult(
            choice, choice.data.get("default_name", "")
        ):
            self.discard_pending_choice(choice)

    # -- "Choose a card name, then reveal N at random from a hand" -----------

    def confirm_name_and_random_reveal(self, player_index: int, card_name: str) -> bool:
        """Answer Nebuchadnezzar's "choose a card name" prompt."""
        return self.resolve_pending_choice(
            "name_and_random_reveal", player_index, card_name=card_name
        )

    def _resolve_name_and_random_reveal(
        self, choice: PendingChoice, card_name: str
    ) -> bool:
        """Reveal *count* cards at random from the target's zone, then discard
        every revealed card carrying the named name.

        The reveal happens **here**, after the name is fixed: turning cards over
        while the prompt was open would tell the chooser what to name.

        The randomness is over *indices*, so two copies of one card are two
        chances to be revealed, and it draws from the module RNG the rest of the
        engine seeds — a given seed replays the ability exactly.

        "All cards with that name **revealed this way**" is the whole reason
        this is one step: the discard is over the revealed subset, not over the
        hand, so a fourth copy the reveal missed stays put.
        """
        data = choice.data
        target = self.players[data["target_seat"]]
        zone = getattr(target, data.get("zone", "hand"), [])
        named = (card_name or "").strip()
        count = min(max(0, int(data.get("count", 0))), len(zone))
        # By index, not by card: `random.sample` over the objects would collapse
        # two equal cards into one candidate on any implementation that compares
        # by value, and this engine's CardDefinition is shared between copies.
        revealed_indices = sorted(random.sample(range(len(zone)), count)) if count else []
        revealed = [zone[i] for i in revealed_indices]
        discarded = [card for card in revealed if named and card.name == named]
        for index in reversed(revealed_indices):
            if named and zone[index].name == named:
                target.graveyard.append(zone.pop(index))
        self.discard_pending_choice(choice)
        self.log.append(
            f"{target.name} revealed {len(revealed)} card(s) at random from their "
            f"{data.get('zone', 'hand')}"
            + (
                f" and discarded {len(discarded)} named {named}"
                if discarded else f" and discarded nothing named {named or 'nothing'}"
            )
        )
        return True

    def _default_name_and_random_reveal(self, choice: PendingChoice) -> None:
        if not self._resolve_name_and_random_reveal(
            choice, choice.data.get("default_name", "")
        ):
            self.discard_pending_choice(choice)

    def confirm_enter_choice(
        self, player_index: int, opponent_index: int | None = None,
        mana_color: str | None = None, card_name: str | None = None,
    ) -> bool:
        """Resolve a pending "as this enters, choose an opponent [and a color]"
        prompt (Black Vise / Jihad), overwriting the provisional defaults
        stamped on the permanent at ETB."""
        return self.resolve_pending_choice(
            "enter_choice", player_index, opponent_index=opponent_index,
            mana_color=mana_color, card_name=card_name,
        )

    def _resolve_enter_choice(
        self, choice: PendingChoice, opponent_index: int | None = None,
        mana_color: str | None = None, card_name: str | None = None,
    ) -> bool:
        player_index = choice.player_index
        # "…choose a card name" (Runed Halo). A different question from the
        # opponent-and-colour one this prompt was written for, so it answers and
        # returns rather than falling through the seat check below — there is no
        # seat in this choice at all.
        #
        # Any name is legal: CR 202.1 lets a player name any card, and the
        # choice is not bounded by what is on a board. An empty answer keeps the
        # default rather than naming nothing, which would make the protection
        # apply to nothing.
        if choice.data.get("needs_card_name"):
            permanent = choice.data["permanent"]
            if card_name:
                permanent.metadata["chosen_card_name"] = card_name
            self.discard_pending_choice(choice)
            self.log.append(
                f"{self.players[player_index].name} named "
                f"{permanent.metadata.get('chosen_card_name') or 'nothing'}"
            )
            return True
        # "…choose a color." (Psychic Allergy.) A colour and no player, so
        # there is no seat to validate — the same early return the card-name
        # branch above takes, and for the same reason: this prompt asks one
        # question of three different shapes and only two of them name a seat.
        if choice.data["needs_color"] and not choice.data["opponents"]:
            permanent = choice.data["permanent"]
            try:
                color = self._normalize_mana_color(mana_color)
            except ValueError:
                return False
            if color is not None and self.is_on_battlefield(permanent):
                permanent.metadata["chosen_color"] = color
                self.log.append(f"{choice.data['card_name']}: chose {color}")
                self._recalculate_lord_buffs()
            self.discard_pending_choice(choice)
            self.check_state_based_actions()
            return True
        if opponent_index not in choice.data["opponents"]:
            return False
        permanent = choice.data["permanent"]
        color = None
        if choice.data["needs_color"]:
            try:
                color = self._normalize_mana_color(mana_color)
            except ValueError:
                return False
            if color is None:
                return False
        # The permanent may already be gone (e.g. destroyed at instant speed);
        # the choice then has nothing to apply to, but the prompt still clears.
        if self.is_on_battlefield(permanent):
            permanent.metadata["chosen_player_index"] = opponent_index
            chose = f"{self.players[player_index].name} chose {self.players[opponent_index].name}"
            if color is not None:
                permanent.metadata["chosen_color"] = color
                chose += f" and {color}"
            self.log.append(f"{choice.data['card_name']}: {chose}")
            if color is not None:
                # Jihad's anthem is conditioned on the chosen color/player.
                self._recalculate_lord_buffs()
        self.discard_pending_choice(choice)
        self.check_state_based_actions()
        return True

    # -- Power Sink's "unless its controller pays {X}" ----------------------

    def confirm_mana_payment(self, player_index: int, pay: bool) -> bool:
        """Resolve a pending Power Sink payment (CR 701.x / "unless its controller
        pays {X}"). The targeted spell's controller pays {X} from their mana pool to
        keep their spell, or declines (or can't afford it) and the spell is countered
        with Power Sink's rider applied."""
        return self.resolve_pending_choice("mana_payment", player_index, pay=bool(pay))

    def _auto_resolve_mana_payment(self) -> None:
        """Deterministic headless/AI resolution of a pending Power Sink payment: pay
        from the controller's mana pool if able, otherwise let the spell be
        countered. Keeps seeded simulations and the headless resolve path unchanged."""
        choice = self.pending_choice_of("mana_payment")
        if choice is not None:
            self._default_mana_payment(choice)

    @staticmethod
    def _mana_payment_cost(data: dict) -> dict[str, int]:
        """The cost a pending payment owes, as a symbol dict.

        A cost is a symbol dict everywhere in this engine (`engine/mana_payment.py`)
        and this prompt was the last place holding a bare number, which is why
        Ayesha Tanaka's "{W}" had no flow to arrive through. `amount` is still
        written beside it for the wire, so the client keeps rendering a total.
        """
        cost = data.get("cost")
        if isinstance(cost, dict) and cost:
            return {k: int(v) for k, v in cost.items()}
        return generic_cost(int(data.get("amount", 0)))

    def _counter_payment_plan(self, player, cost: dict[str, int]):
        """How *player* can pay a counterspell's "unless you pay", or None.

        Pool **and** untapped lands, which is CR 605.3b: a player may activate a
        mana ability while paying a cost, and this payment happens during the
        counterspell's resolution with no priority window in which to do it any
        other way. The sibling `_optional_pay_plan` has always answered this way
        for "you may pay" — the two are the same question, and this one spent
        only floating mana, so an AI holding untapped lands declined a cost it
        could afford and lost the spell.
        """
        return plan_payment(
            player.mana_pool, untapped_mana_lands(self.controlled_by(player)), cost,
            produces=self._land_payment_colors,
        )

    def _land_payment_colors(self, land) -> tuple[str, ...]:
        """What tapping *land* would actually put in its controller's pool.

        The permanent's own answer, unless a seat-wide swap says otherwise —
        "Until end of turn, if you tap a land you control for mana, it produces
        {U} instead of any other type" (Deep Water). That record hangs off the
        seat, so only a caller with the game can resolve it, which is why the
        planner takes this as a hook rather than reading the permanent itself
        (``engine/land_mana_swaps.py``). Without it the planner would tap a
        Swamp to pay a {B} the tap will not produce, and report a cost payable
        that is not.
        """
        swapped = land_mana_swaps.swapped_symbol(self, land)
        return (swapped,) if swapped else tuple(land.effective_produced_mana or ())

    def _default_mana_payment(self, choice: PendingChoice) -> None:
        controller = self.players[choice.player_index]
        cost = self._mana_payment_cost(choice.data)
        self._resolve_mana_payment(
            choice, self._counter_payment_plan(controller, cost) is not None
        )

    def _resolve_mana_payment(self, choice: PendingChoice, pay: bool) -> bool:
        controller = self.players[choice.player_index]
        data = choice.data
        cost = self._mana_payment_cost(data)
        target = data.get("stack_item")
        counter_card = data.get("counter_card")
        # Which symbols come out, not just how many: paying {W} by draining a
        # red pip is what a bare count could not tell apart, and it is the
        # difference between Ayesha Tanaka's ability working and working for
        # everyone. Lands are tapped as well as pips spent (CR 605.3b) — the
        # plan names both halves, and paying from one without the other would
        # let the same land answer two costs.
        plan = self._counter_payment_plan(controller, cost) if pay else None
        if plan is not None:
            for symbol, spent in plan.from_pool.items():
                controller.mana_pool[symbol] = controller.mana_pool.get(symbol, 0) - spent
            for land in plan.tapped:
                self.become_tapped(land)
            name = target.card.name if target is not None else "the spell"
            self.log.append(
                f"{controller.name} paid {mana_cost_label(cost)}; {name} is not countered"
            )
        else:
            # Declined or unable to pay: the spell is countered and Power Sink's rider
            # (tap all the controller's lands, drain their mana) applies.
            if target is not None and target in self.stack:
                self.stack.remove(target)
                if data.get("countered_object") == "ability":
                    # An ability on the stack has no card (CR 113.7a): removing
                    # it from the stack is the whole of CR 701.5a for it, and
                    # binning `target.card` would put the *source permanent's*
                    # card in a graveyard it never left.
                    self.log.append(
                        f"{data['card_name']} countered {target.card.name}'s ability"
                    )
                elif target.is_copy:
                    # 704.5e: a countered copy of a spell ceases to exist.
                    self.log.append(f"{data['card_name']} countered {target.card.name} (copy), which ceases to exist")
                else:
                    self._bin_spell_card(
                        controller, target.card,
                        exile_instead=target.exile_instead_of_graveyard,
                        verb=f"was countered by {data['card_name']}",
                    )
                if counter_card is not None:
                    from ...card_hooks import ON_SPELL_COUNTERED
                    hook = ON_SPELL_COUNTERED.get(data["card_name"])
                    if hook is not None:
                        hook(self, counter_card, target)
        self.discard_pending_choice(choice)
        return True

    # -- A permanent chosen as an effect resolves -----------------------------
    #
    # The general form of the reattachment below, and the one every new card
    # uses: the effect names a set of permanents, one seat picks one of them,
    # and the answer is a ``permanent_id`` written into the resolution's
    # ``results`` for the steps behind it to read. See
    # ``engine/handlers/permanent_choices.py`` for why that is the whole of it.

    def arm_permanent_choice(
        self,
        player_index: int,
        *,
        card_name: str,
        prompt: str,
        result_key: str,
        payload: dict,
        context,
        candidates,
        optional: bool = False,
    ) -> PendingChoice | None:
        """Queue "choose one of these permanents" for *player_index*.

        *optional* is the printed difference between "chooses a creature" as an
        instruction and as an offer. It is what makes "If the player does …
        If they don't …" two reachable branches: without it the seat always has
        an answer and the second branch is text the card can never take.

        The payload is carried whole rather than the candidate list alone: it is
        the *rule* the candidates came from, and re-running it is what keeps the
        list offered and the list an answer is checked against from drifting
        (CR 608.2b's spirit, applied to a choice rather than to a target).
        """
        return self.arm_pending_choice(
            "permanent_choice", player_index,
            card_name=card_name,
            prompt=prompt,
            result_key=result_key,
            _payload=dict(payload),
            _context=context,
            _candidates=tuple(candidates),
            optional=optional,
        )

    def live_permanent_choices(self, choice: PendingChoice) -> list:
        """The armed candidates that are still legal answers.

        Public because the prompt renderer is a second legitimate caller, for
        the same reason ``live_loyalty_recipients`` is: one rule, asked twice.
        """
        from ...handlers.permanent_choices import permanent_choice_candidates

        return permanent_choice_candidates(
            self,
            choice.data.get("_payload") or {},
            choice.data["_context"],
            among=choice.data.get("_candidates") or (),
        )

    def confirm_permanent_choice(self, player_index: int, permanent_id: int) -> bool:
        """Answer a pending permanent choice with a permanent's stable id."""
        return self.resolve_pending_choice(
            "permanent_choice", player_index, permanent_id=permanent_id
        )

    def _record_permanent_choice(self, choice: PendingChoice, permanent_id) -> None:
        choice.data["_context"].results[choice.data["result_key"]] = permanent_id
        self.discard_pending_choice(choice)

    def _resolve_permanent_choice(self, choice: PendingChoice, permanent_id) -> bool:
        live = self.live_permanent_choices(choice)
        if not live:
            # Everything the effect offered has left or stopped qualifying. The
            # sentence carries on with nothing chosen rather than staying owed a
            # prompt nobody can answer.
            self._record_permanent_choice(choice, None)
            self.log.append(
                f"{choice.data.get('card_name', 'Effect')}: nothing is left to choose"
            )
            return True
        if permanent_id is None and choice.data.get("optional"):
            # The seat declined an offer the card made (Takklemaggot). Recorded
            # as "nothing chosen", which is the same value an empty candidate
            # list produces — one answer for the branch behind it to read,
            # whether nobody could choose or nobody would.
            self._record_permanent_choice(choice, None)
            self.log.append(
                f"{choice.data.get('card_name', 'Effect')}: chose nothing"
            )
            return True
        perm = self.permanent_by_id(permanent_id) if permanent_id is not None else None
        if perm is None or not any(perm is candidate for candidate in live):
            return False
        self._record_permanent_choice(choice, perm.permanent_id)
        self.log.append(
            f"{choice.data.get('card_name', 'Effect')}: chose {perm.card.name}"
        )
        return True

    def _default_permanent_choice(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** live candidate in board order.

        Not a valuation — board order is seed-deterministic, which is what AI
        and headless play need. A card whose choice should be made cleverly
        needs a weight in ``engine/ai_valuation.py``, not a branch here.
        """
        live = self.live_permanent_choices(choice)
        if not live or not self._resolve_permanent_choice(
            choice, live[0].permanent_id
        ):
            self._record_permanent_choice(choice, None)

    # -- A player, and one of their casts this turn --------------------------

    def arm_player_choice(
        self,
        player_index: int,
        *,
        card_name: str,
        prompt: str,
        result_key: str,
        seats,
        context,
    ) -> PendingChoice | None:
        """Queue "choose one of these players" for *player_index*.

        The seats are carried rather than the rule that produced them, unlike
        ``arm_permanent_choice``: what a seat *is* cannot stop qualifying
        mid-resolution the way a permanent can leave the battlefield, because
        "cast one or more sorcery spells this turn" is a fact about a turn that
        is already over. A seat that has *lost* is the one exception, and it is
        re-checked when the answer arrives.
        """
        return self.arm_pending_choice(
            "player_choice", player_index,
            card_name=card_name,
            prompt=prompt,
            result_key=result_key,
            seats=[int(seat) for seat in seats],
            names=[self.players[int(seat)].name for seat in seats],
            _context=context,
        )

    def live_player_choices(self, choice: PendingChoice) -> list[int]:
        """The offered seats that are still legal answers (CR 800.4a)."""
        return [
            seat for seat in choice.data.get("seats") or ()
            if 0 <= seat < len(self.players) and not self.players[seat].lost
        ]

    def confirm_player_choice(self, player_index: int, seat) -> bool:
        return self.resolve_pending_choice("player_choice", player_index, seat=seat)

    def _record_player_choice(self, choice: PendingChoice, value) -> None:
        choice.data["_context"].results[choice.data["result_key"]] = value
        self.discard_pending_choice(choice)

    def _resolve_player_choice(self, choice: PendingChoice, seat) -> bool:
        live = self.live_player_choices(choice)
        if not live:
            # Everyone the effect offered has left the game. The sentence
            # carries on with nobody chosen rather than staying owed a prompt
            # nobody can answer.
            self._record_player_choice(choice, None)
            return True
        if not isinstance(seat, int) or seat not in live:
            return False
        self._record_player_choice(choice, seat)
        self.log.append(
            f"{choice.data.get('card_name', 'Effect')}: chose {self.players[seat].name}"
        )
        return True

    def _default_player_choice(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** live seat offered.

        Not a valuation — seat order is seed-deterministic, which is what AI and
        headless play need. A card whose choice should be made cleverly needs a
        weight in ``engine/ai_valuation.py``, not a branch here.
        """
        live = self.live_player_choices(choice)
        if not live or not self._resolve_player_choice(choice, live[0]):
            self._record_player_choice(choice, None)

    def arm_cast_choice(
        self,
        player_index: int,
        *,
        card_name: str,
        prompt: str,
        result_key: str,
        options,
        context,
    ) -> PendingChoice | None:
        """Queue "choose one of those spells" for *player_index*.

        The options are ledger positions (``engine/damage_ledger.py``), because
        a prompt's answer is JSON and a ``StackItem`` is not — and because the
        spells being chosen between have already resolved and left the stack,
        which is the whole reason the ledger exists.
        """
        from ...damage_ledger import damage_dealt_by_cast

        return self.arm_pending_choice(
            "cast_choice", player_index,
            card_name=card_name,
            prompt=prompt,
            result_key=result_key,
            options=[int(index) for index, _entry in options],
            names=[getattr(entry.card, "name", "") for _index, entry in options],
            # What each one dealt, so the picker is a decision rather than a
            # guess. Public information: damage dealt this turn was dealt in the
            # open, and the choosing player could count it from the log.
            damages=[damage_dealt_by_cast(self, entry.item) for _index, entry in options],
            _context=context,
        )

    def _record_cast_choice(self, choice: PendingChoice, value: int) -> None:
        choice.data["_context"].results[choice.data["result_key"]] = int(value)
        self.discard_pending_choice(choice)

    def confirm_cast_choice(self, player_index: int, cast_index) -> bool:
        return self.resolve_pending_choice(
            "cast_choice", player_index, cast_index=cast_index
        )

    def _resolve_cast_choice(self, choice: PendingChoice, cast_index) -> bool:
        from ...damage_ledger import cast_by_index, damage_dealt_by_cast

        options = list(choice.data.get("options") or ())
        if not isinstance(cast_index, int) or cast_index not in options:
            return False
        entry = cast_by_index(self, cast_index)
        if entry is None:  # pragma: no cover - the ledger is not edited mid-turn
            self._record_cast_choice(choice, 0)
            return True
        dealt = damage_dealt_by_cast(self, entry.item)
        self._record_cast_choice(choice, dealt)
        self.log.append(
            f"{choice.data.get('card_name', 'Effect')}: named {entry.card.name}, "
            f"which dealt {dealt} damage this turn"
        )
        return True

    def _default_cast_choice(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** cast offered, in the order they were
        cast. Deterministic rather than clever, for ``_default_player_choice``'s
        reason."""
        options = list(choice.data.get("options") or ())
        if not options or not self._resolve_cast_choice(choice, options[0]):
            self._record_cast_choice(choice, 0)

    # -- A card put onto the battlefield out of a hand -----------------------

    def arm_put_from_hand_choice(self, player_index: int, payload: dict, context) -> None:
        """Queue "pick a card in your hand to put onto the battlefield" for
        *player_index*.

        The whole payload travels rather than the candidate list, for the reason
        ``arm_permanent_choice`` gives: it is the *rule* the candidates came
        from, and re-running it is what keeps the list offered and the list an
        answer is checked against from being two lists.
        """
        self.arm_pending_choice(
            "put_from_hand_choice", player_index,
            card_name=context.card.name,
            optional=bool(payload.get("optional")),
            _payload=dict(payload),
            _context=context,
        )

    def live_put_from_hand_choices(self, choice: PendingChoice) -> list[int]:
        """The hand slots still eligible, from the engine's own rule."""
        from ...handlers.zones import put_from_hand_candidates

        return put_from_hand_candidates(
            self, choice.data.get("_payload") or {}, self.players[choice.player_index]
        )

    def confirm_put_from_hand_choice(self, player_index: int, hand_index) -> bool:
        """Answer the pending pick. ``hand_index`` of None is declining, which is
        only an answer when the sentence said "may"."""
        return self.resolve_pending_choice(
            "put_from_hand_choice", player_index, hand_index=hand_index
        )

    def _resolve_put_from_hand_choice(self, choice: PendingChoice, hand_index) -> bool:
        from ...repeated_offers import OFFER_TAKEN_RESULTS

        player = self.players[choice.player_index]
        live = self.live_put_from_hand_choices(choice)
        name = choice.data.get("card_name", "Effect")
        if hand_index is None:
            # Declining. Refused outright on a mandatory pick with something
            # legal left, so a client cannot answer a sentence that offered no
            # way out — but allowed once nothing qualifies, because then the
            # decision is over either way (CR 608.2b).
            if live and not choice.data.get("optional"):
                return False
            self.log.append(f"{player.name} put no card onto the battlefield")
            self.discard_pending_choice(choice)
            return True
        if hand_index not in live:
            return False
        card = player.hand[hand_index]
        player.hand = [c for i, c in enumerate(player.hand) if i != hand_index]
        self._put_permanent_onto_battlefield(
            choice.player_index, Permanent(card=card), None
        )
        # The record a repeated round ends on — see engine/repeated_offers.py.
        # Appended rather than set, because every seat of the round shares the
        # one resolution scratchpad.
        choice.data["_context"].results.setdefault(OFFER_TAKEN_RESULTS, []).append(
            card.name
        )
        self.log.append(f"{player.name} put {card.name} onto the battlefield ({name})")
        self.discard_pending_choice(choice)
        return True

    def _default_put_from_hand_choice(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** eligible card in hand order.

        Not a valuation — hand order is seed-deterministic, which is what AI and
        headless play need, and it is the same policy
        ``put_cards_from_hand_onto_battlefield`` already states for the sweep
        beside it: more battlefield is what the AI plays toward. A seat that
        should decline cleverly needs a weight in ``engine/ai_valuation.py``,
        not a branch here.
        """
        live = self.live_put_from_hand_choices(choice)
        if not live or not self._resolve_put_from_hand_choice(choice, live[0]):
            self._resolve_put_from_hand_choice(choice, None)

    # -- Cards picked out of a hand for a later step to act on ---------------

    def arm_choose_cards_in_hand(self, player_index: int, payload: dict, context) -> None:
        """Queue "choose N cards in your hand …" for *player_index*.

        The whole payload travels rather than the candidate list, for the
        reason ``arm_put_from_hand_choice`` gives: it is the *rule* the
        candidates came from, and re-running it is what keeps the list offered
        and the list an answer is checked against from being two lists.
        """
        self.arm_pending_choice(
            "choose_cards_in_hand", player_index,
            card_name=context.card.name,
            count=int(payload.get("count", 1)),
            _payload=dict(payload),
            _context=context,
        )

    def live_choose_cards_in_hand(self, choice: PendingChoice) -> list[int]:
        """The hand slots still eligible, from the engine's own rule."""
        from ...handlers.zones import chosen_hand_card_candidates

        return chosen_hand_card_candidates(
            self, choice.data.get("_payload") or {}, self.players[choice.player_index]
        )

    def _how_many_cards_to_choose(self, choice: PendingChoice) -> int:
        """How many the seat owes: the printed number, or every eligible card
        when the hand holds fewer (CR 608.2, do as much as possible)."""
        return min(int(choice.data.get("count", 1)), len(self.live_choose_cards_in_hand(choice)))

    def confirm_choose_cards_in_hand(self, player_index: int, hand_indices) -> bool:
        return self.resolve_pending_choice(
            "choose_cards_in_hand", player_index, hand_indices=hand_indices
        )

    def _record_chosen_cards_in_hand(self, choice: PendingChoice, cards: list) -> None:
        context = choice.data["_context"]
        key = str((choice.data.get("_payload") or {}).get("result_key") or "chosen_hand_cards")
        # The card objects, not their hand slots: the step that reads this
        # record moves cards out of the hand, and an index stops naming the
        # same card the moment one leaves.
        context.results[key] = list(cards)
        self.discard_pending_choice(choice)

    def _resolve_choose_cards_in_hand(self, choice: PendingChoice, hand_indices) -> bool:
        player = self.players[choice.player_index]
        live = self.live_choose_cards_in_hand(choice)
        wanted = self._how_many_cards_to_choose(choice)
        picks = list(hand_indices or [])
        if len(picks) != wanted or len(set(picks)) != len(picks):
            return False
        if any(index not in live for index in picks):
            return False
        cards = [player.hand[index] for index in picks]
        self._record_chosen_cards_in_hand(choice, cards)
        name = choice.data.get("card_name", "Effect")
        self.log.append(
            f"{player.name} chose {', '.join(c.name for c in cards) or 'no cards'} ({name})"
        )
        return True

    def _default_choose_cards_in_hand(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** eligible cards in hand order.

        Not a valuation — hand order is seed-deterministic, which is what AI
        and headless play need, and it is the same policy every other pick out
        of a hand in this file states. A seat that should choose cleverly needs
        a weight in ``engine/ai_valuation.py``, not a branch here.
        """
        live = self.live_choose_cards_in_hand(choice)
        wanted = self._how_many_cards_to_choose(choice)
        if not self._resolve_choose_cards_in_hand(choice, live[:wanted]):
            self._record_chosen_cards_in_hand(choice, [])

    # -- Kudzu's reattachment ------------------------------------------------

    def confirm_kudzu_reattach(self, player_index: int, land_index: int) -> bool:
        """Resolve a pending Kudzu reattach by moving the detached Aura onto the
        controller's chosen land."""
        return self.resolve_pending_choice("kudzu_reattach", player_index, land_index=land_index)

    def _resolve_kudzu_reattach(self, choice: PendingChoice, land_index: int) -> bool:
        player = self.players[choice.player_index]
        if not (0 <= land_index < len(player.battlefield)):
            return False
        new_land = player.battlefield[land_index]
        if new_land.card.primary_type != "land":
            return False
        attach_aura(choice.data["aura"], new_land)
        self.log.append(f"Kudzu attached to {new_land.card.name}")
        self.discard_pending_choice(choice)
        return True

    def _default_kudzu_reattach(self, choice: PendingChoice) -> None:
        """Re-attach to the first land the controller has, deterministically."""
        player = self.players[choice.player_index]
        index = next(
            (i for i, p in enumerate(player.battlefield) if p.card.primary_type == "land"),
            None,
        )
        if index is None or not self._resolve_kudzu_reattach(choice, index):
            self.discard_pending_choice(choice)

    # -- Illusionary Mask's face-down cast -----------------------------------

    def confirm_face_down_cast(self, player_index: int, hand_index: int | None) -> bool:
        """Resolve a pending Illusionary Mask face-down cast. ``hand_index`` < 0 (or
        None) declines (the choice is "you may"). Otherwise the chosen creature card
        (mana value <= the pending max) is cast face down as a 2/2, keeping the real
        card so it can later be turned face up."""
        return self.resolve_pending_choice("face_down_cast", player_index, hand_index=hand_index)

    def _resolve_face_down_cast(self, choice: PendingChoice, hand_index: int | None) -> bool:
        player_index = choice.player_index
        player = self.players[player_index]
        if hand_index is None or hand_index < 0:
            self.discard_pending_choice(choice)
            return True
        if not (0 <= hand_index < len(player.hand)):
            return False
        creature_card = player.hand[hand_index]
        max_cmc = int(choice.data.get("max_cmc", 0))
        if creature_card.primary_type != "creature" or int(creature_card.cmc or 0) > max_cmc:
            return False
        player.hand.pop(hand_index)
        face_down = CardDefinition(
            name=creature_card.name,
            mana_cost="",
            cmc=0.0,
            type_line="Creature",
            oracle_text="",
            colors=(),
            color_identity=(),
            keywords=(),
            produced_mana=(),
            raw={"name": creature_card.name, "type_line": "Creature", "power": "2", "toughness": "2"},
        )
        perm = Permanent(card=face_down)
        perm.metadata["face_down"] = True
        perm.metadata["face_down_real_card"] = creature_card
        self._put_permanent_onto_battlefield(player_index, perm, None)
        self.log.append(f"Illusionary Mask cast {creature_card.name} face down as a 2/2")
        self.discard_pending_choice(choice)
        return True

    def _default_face_down_cast(self, choice: PendingChoice) -> None:
        """Cast the first eligible hand creature (mana value within X)."""
        player = self.players[choice.player_index]
        max_cmc = int(choice.data.get("max_cmc", 0))
        index = next(
            (i for i, c in enumerate(player.hand)
             if c.primary_type == "creature" and int(c.cmc or 0) <= max_cmc),
            None,
        )
        if not self._resolve_face_down_cast(choice, index if index is not None else -1):
            self.discard_pending_choice(choice)

    # -- Word of Command -----------------------------------------------------

    def confirm_word_of_command(
        self, caster_index: int, hand_index: int | None, defer_resolution: bool = False
    ) -> bool:
        """Record the caster's card choice for a pending Word of Command.
        ``hand_index`` < 0 (or None) declines.

        With ``defer_resolution`` (the interactive priority path) the choice is
        only recorded: the spell stays on the stack and finishes resolving —
        forcing the target to play the chosen card — when priority is next
        released (resolve_top_of_stack). Headless/AI callers leave it False, so
        confirming finishes the resolution immediately.

        MVP: the forced spell defaults its target to the forced player themselves
        (so e.g. their burn/removal is turned on them). Caster-chosen targets for
        the forced spell are a future enhancement."""
        return self.resolve_pending_choice(
            "word_of_command", caster_index,
            hand_index=hand_index, defer_resolution=defer_resolution,
        )

    def _resolve_word_of_command(
        self, choice: PendingChoice, hand_index: int | None, defer_resolution: bool
    ) -> bool:
        pending = choice.data
        caster_index = choice.player_index
        chosen = -1 if hand_index is None or hand_index < 0 else hand_index
        target = self.players[pending["target_index"]]
        if chosen >= 0 and chosen >= len(target.hand):
            return False
        if defer_resolution and pending.get("_stack_item") in self.stack:
            pending["chosen_hand_index"] = chosen
            if chosen >= 0:
                # The target may play cards in response before this resolves, so
                # remember the chosen card by name and re-find it at resolution.
                pending["chosen_card_name"] = target.hand[chosen].name
                self.log.append(
                    f"Word of Command: {self.players[caster_index].name} chose "
                    f"{target.hand[chosen].name}; the spell waits on the stack"
                )
            else:
                self.log.append(f"Word of Command: {self.players[caster_index].name} declined to force a card")
            # The caster just acted mid-resolution; make sure a priority window is
            # open so the spell can be responded to and then resolved by passing.
            if self.priority_player_index is None:
                self.start_priority_window(caster_index)
            return True
        self.discard_pending_choice(choice)
        return self._finish_word_of_command(pending, chosen, caster_index=caster_index)

    def _default_word_of_command(self, choice: PendingChoice) -> None:
        """Force the first card in the target's hand (deterministic)."""
        target = self.players[choice.data["target_index"]]
        if not self._resolve_word_of_command(
            choice, 0 if target.hand else -1, defer_resolution=False
        ):
            self.discard_pending_choice(choice)

    def _finish_word_of_command(
        self, pending: dict, hand_index: int, auto_resolve_forced: bool = True,
        caster_index: int | None = None,
    ) -> bool:
        """Finish a Word of Command's resolution: the spell leaves the stack for
        the graveyard and the target plays the chosen card, if able.
        ``auto_resolve_forced`` immediately resolves the forced spell (headless/AI
        paths); the interactive path leaves it on the stack for a priority round."""
        target_index = pending["target_index"]
        target = self.players[target_index]
        stack_item = pending.get("_stack_item")
        if stack_item is not None and stack_item in self.stack:
            self.stack.remove(stack_item)
        spell_card = pending.get("_spell_card")
        if spell_card is not None:
            spell_caster = self.players[pending.get("_spell_caster_index", caster_index or 0)]
            self._bin_spell_card(
                spell_caster, spell_card,
                exile_instead=bool(pending.get("_spell_exile_instead")),
                verb="resolved",
            )
        if hand_index < 0:
            return True  # declined — nothing is played
        chosen_name = pending.get("chosen_card_name")
        if chosen_name is not None:
            # Deferred choice: the hand may have changed since the caster chose
            # (the target could respond while the spell waited), so locate the
            # chosen card by name; if it left the hand it can't be played.
            hand_index = next(
                (i for i, c in enumerate(target.hand) if c.name == chosen_name), -1
            )
            if hand_index < 0:
                self.log.append(
                    f"Word of Command: {target.name} no longer has {chosen_name} to play"
                )
                return True
        if not (0 <= hand_index < len(target.hand)):
            return False
        card_name = target.hand[hand_index].name
        result = self.queue_from_hand(target_index, card_name, target_player_index=target_index)
        if result.supported and auto_resolve_forced and self.stack:
            self.resolve_stack()
        if result.supported:
            self.log.append(f"Word of Command: {target.name} was forced to play {card_name}")
        else:
            self.log.append(f"Word of Command: {target.name} could not play {card_name} ({result.details})")
        return True

    # -- Glasses of Urza's revealed hand -------------------------------------

    def dismiss_hand_reveal(self, viewer_index: int) -> bool:
        """The viewer has seen the revealed hand; take the prompt down."""
        return self.resolve_pending_choice("hand_reveal", viewer_index)

    def _dismiss_hand_reveal(self, choice: PendingChoice) -> bool:
        self.discard_pending_choice(choice)
        return True

    # -- Balance -------------------------------------------------------------

    def _resolve_balance(self, choice: PendingChoice, land_indices, creature_indices, hand_indices) -> bool:
        player_index = choice.player_index
        plan = choice.data["plan"]
        player = self.players[player_index]
        lands = [i for i in dict.fromkeys(land_indices or [])]
        creatures = [i for i in dict.fromkeys(creature_indices or [])]
        hand = [i for i in dict.fromkeys(hand_indices or [])]
        if len(lands) != plan["lands"] or len(creatures) != plan["creatures"] or len(hand) != plan["hand"]:
            return False
        # Validate the chosen battlefield indices are the right card type.
        for i in lands:
            if not (0 <= i < len(player.battlefield)) or player.battlefield[i].card.primary_type != "land":
                return False
        for i in creatures:
            if not (0 <= i < len(player.battlefield)) or player.battlefield[i].card.primary_type != "creature":
                return False
        for i in hand:
            if not (0 <= i < len(player.hand)):
                return False
        # Resolve every chosen permanent *before* removing any, then remove
        # them together. The old loop went highest-index-first so that removing
        # one could not invalidate the indices behind it — a workaround the
        # single removal choke point makes unnecessary, since nothing here holds
        # an index across a removal any more.
        chosen_perms = [
            self.permanent_at(player, i)
            for i in sorted(set(lands) | set(creatures), reverse=True)
        ]
        for perm in chosen_perms:
            self.sacrifice_permanent(perm)
        for i in sorted(hand, reverse=True):
            player.graveyard.append(player.hand.pop(i))
        self.discard_pending_choice(choice)
        self.log.append(f"{player.name} resolved their Balance sacrifices")
        return True

    def _default_balance(self, choice: PendingChoice) -> None:
        """Keep the lowest-index permanents and cards."""
        plan = choice.data["plan"]
        player = self.players[choice.player_index]
        land_idx = [i for i, p in enumerate(player.battlefield) if p.card.primary_type == "land"][-plan["lands"]:] if plan["lands"] else []
        creature_idx = [i for i, p in enumerate(player.battlefield) if p.card.primary_type == "creature"][-plan["creatures"]:] if plan["creatures"] else []
        hand_idx = list(range(len(player.hand)))[-plan["hand"]:] if plan["hand"] else []
        if not self._resolve_balance(choice, land_idx, creature_idx, hand_idx):
            self.discard_pending_choice(choice)

    def confirm_balance(self, player_index: int, land_indices=None, creature_indices=None, hand_indices=None) -> bool:
        """Resolve one player's Balance plan with their chosen sacrifices/discards."""
        return self.resolve_pending_choice(
            "balance", player_index,
            land_indices=land_indices, creature_indices=creature_indices, hand_indices=hand_indices,
        )

    def auto_resolve_pending_balance(self, only_player_index: int | None = None) -> None:
        """Resolve Balance plans with a default choice (keep the lowest-index
        permanents/cards). Used for AI players and headless simulation. When
        ``only_player_index`` is given, resolve just that player's plan."""
        self.auto_resolve_pending_choices(only_player_index=only_player_index, kinds=("balance",))

    # -- Optional "you may pay {N}" ------------------------------------------

    def _optional_pay_plan(self, player, entry: dict):
        """How *player* would pay this entry's cost, or None if they cannot.

        The cost is the whole printed one — ``{1}{B}`` is a dict of symbols, not
        the number 2 — and it is collected from the board rather than from the
        pool alone, because an effect that says "you may pay" gives its player no
        priority window in which to tap for mana. ``engine/mana_payment.py``
        holds both halves of that question; asking it once here is what makes
        "can they pay?" and "pay it" the same answer.
        """
        return plan_payment(
            player.mana_pool,
            untapped_mana_lands(self.controlled_by(player)),
            entry.get("cost") or {},
            produces=self._land_payment_colors,
        )

    def _spend_payment_plan(self, player, plan) -> None:
        """Carry out a :func:`plan_payment` answer: spend the floating mana it
        names and tap the lands it names.

        One writer, because a plan is *how* a cost is paid and a second
        spelling of it is a second answer — the untap toll (Mudslide) collects
        the same plan the optional-pay prompt does, and a payment that tapped
        the lands but forgot the pool would be a cost half charged.
        """
        for symbol, amount in plan.from_pool.items():
            player.mana_pool[symbol] = int(player.mana_pool.get(symbol, 0)) - amount
        for land in plan.tapped:
            self.become_tapped(land)

    def _player_can_pay_optional(self, player, entry: dict) -> bool:
        """CR 601.2h, for an optional cost: whether it *could* be paid.

        ``life_alternative`` is CR 118.8's second way to cover the *same* offer
        ("…pays {1} **or 1 life**", Erosion), so it widens this answer rather
        than replacing it: a player with the life and not the mana can take the
        offer, and one with neither cannot. It is a different field from
        ``life_cost``, which is a life cost with no mana alternative at all
        (Bronze Tablet) — folding the two would make an unaffordable mana cost
        read as a life one.
        """
        life_cost = int(entry.get("life_cost", 0) or 0)
        if life_cost:
            # CR 119.4: a player may pay N life only with at least N to pay —
            # paying down to exactly 0 is legal, and the state-based check that
            # follows is what ends the game.
            return player.life >= life_cost
        if self._optional_pay_plan(player, entry) is not None:
            return True
        alternative = int(entry.get("life_alternative", 0) or 0)
        return bool(alternative) and player.life >= alternative

    def _pay_optional(self, player_index: int, entry: dict) -> None:
        """Collect the entry's mana cost from its player and run what accepting
        buys. A cost that turns out to be unpayable buys nothing."""
        player = self.players[player_index]
        # A free optional "you may draw a card" rider (Verduran Enchantress): no
        # cost to pay, just draw on accept.
        if entry.get("draw"):
            drawn = self._draw_with_replacements(player, int(entry["draw"]))
            self.log.append(f"{player.name} drew {drawn} card(s) from {entry['card_name']}")
            return
        # "That player may pay 10 life." (Bronze Tablet.) A life cost rather
        # than a mana one, and the two never appear together — a cost of one
        # kind is not payable out of the other.
        life_cost = int(entry.get("life_cost", 0) or 0)
        if life_cost:
            if player.life < life_cost:
                return
            player.life -= life_cost
            self.log.append(
                f"{player.name} paid {life_cost} life ({entry.get('card_name', '')})"
            )
        else:
            plan = self._optional_pay_plan(player, entry)
            if plan is None:
                # CR 118.8's alternative ("…pays {1} **or 1 life**", Erosion).
                # A *stated policy* rather than a second prompt: the mana is
                # spent whenever the board can cover it, and the life only when
                # it cannot. The offer is one decision and the web prompt asks
                # it once, so which half pays for it is the engine's to state —
                # and stating "mana first" is the reading that keeps a life
                # total for the alternatives that have no other currency.
                alternative = int(entry.get("life_alternative", 0) or 0)
                if not alternative or player.life < alternative:
                    return
                player.life -= alternative
                self.log.append(
                    f"{player.name} paid {alternative} life "
                    f"({entry.get('card_name', '')})"
                )
            else:
                self._spend_payment_plan(player, plan)
        # A grammar-lowered "may" carries its consequence as instructions rather
        # than as one of the three fixed fields above, so any effect can sit
        # behind an optional cost.
        ran = self._run_optional_branch(entry, "_on_accept")
        # CR 603.12, and it runs whether or not there was an accept branch: the
        # reflexive ability is created *by the payment*, not by the consequence.
        self._create_reflexive_ability(player_index, entry)
        if ran:
            return
        if int(entry.get("life", 0) or 0) > 0:
            self._gain_life(player, int(entry["life"]), entry["card_name"])

    def _create_reflexive_ability(self, player_index: int, entry: dict) -> None:
        """"When you do, …" — the ability the payment just created (CR 603.12).

        It chooses its targets now, as it is created, which is the whole reason
        it is not an "if you do" branch: the resolution that armed this prompt
        may name no permanent at all (Tolarian Kraken's fired on a card being
        drawn), so running the instructions against its context would point them
        at whatever ``resolve_target_permanent`` fell back to.

        With no legal target the ability is not created — CR 603.7's rule for a
        delayed trigger, which 603.12 defers to. With no target to choose at all
        it simply runs, because then there is nothing to ask.
        """
        from ...targeting import derive_instruction_spec

        steps = entry.get("_on_reflexive") or ()
        context = entry.get("_context")
        if not steps or context is None:
            return
        spec = derive_instruction_spec(steps)
        if spec is None:
            for step in steps:
                self._execute_oracle_instruction(step, context)
            return
        card = getattr(context, "card", None)
        source_permanent = getattr(context, "source_permanent", None)
        candidates = self._enumerate_targets(
            player_index, card, spec, for_cast=False,
            source_permanent=source_permanent,
            # A reflexive trigger is an ability (CR 603.1), so its target choice
            # is one an ability makes. None when a *spell* armed it, which is the
            # honest answer rather than a default.
            ability_source=source_permanent,
        )
        # The enumerator addresses a permanent by its slot, which is unstable —
        # anything leaving the battlefield renumbers every later one, and this
        # prompt sits on the queue across a priority window. So each offered slot
        # is resolved to a stable id *here*, at the moment the ability is created
        # and its targets chosen, and the id is what the answer is checked
        # against.
        offered = []
        for target in candidates:
            seat, index = target.get("seat"), target.get("index")
            perm = self.permanent_at(seat, index)
            if perm is None:
                continue
            offered.append({
                "seat": seat,
                "permanent_index": index,
                "permanent_id": self.permanent_id_of(perm),
                "name": perm.card.name,
            })
        if not offered:
            self.log.append(
                f"{entry.get('card_name', 'Ability')}: no legal target for its "
                "reflexive trigger"
            )
            return
        self.arm_pending_choice(
            "reflexive_target", player_index,
            card_name=entry.get("card_name", ""),
            targets=offered,
            _steps=tuple(steps),
            _context=context,
        )

    def confirm_reflexive_target(self, player_index: int, permanent_id: int) -> bool:
        """Answer a reflexive trigger's target choice with a permanent's id."""
        return self.resolve_pending_choice(
            "reflexive_target", player_index, permanent_id=permanent_id
        )

    def _resolve_reflexive_target(self, choice: PendingChoice, permanent_id: int) -> bool:
        """Run the reflexive ability against the chosen permanent.

        The id is checked against the list that was offered rather than against
        the board, so a permanent that became legal after the prompt was armed is
        still not a legal answer — targets are chosen once, when the ability is
        created.
        """
        offered = {
            target.get("permanent_id")
            for target in (choice.data.get("targets") or ())
            if target.get("permanent_id") is not None
        }
        if permanent_id not in offered:
            return False
        perm = self.permanent_by_id(permanent_id)
        if perm is None:
            return False
        seat = self.controller_index_of(perm)
        if seat is None:
            return False
        context = choice.data["_context"]
        aimed = replace(
            context,
            target=self.players[seat],
            target_permanent_index=self.battlefield_index_of(perm),
            target_permanent_id=permanent_id,
        )
        self.discard_pending_choice(choice)
        self.log.append(
            f"{choice.data.get('card_name', 'Ability')}: reflexive trigger targets "
            f"{perm.card.name}"
        )
        for step in choice.data["_steps"]:
            self._execute_oracle_instruction(step, aimed)
        self.check_state_based_actions()
        return True

    def _default_reflexive_target(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** target offered.

        Not a valuation — the enumerator's order is the board's order and is
        seed-deterministic. A card whose reflexive ability should be aimed
        cleverly needs a valuation in `engine/ai_valuation.py`, not a branch
        here.
        """
        for target in choice.data.get("targets") or ():
            pid = target.get("permanent_id")
            if pid is not None and self._resolve_reflexive_target(choice, pid):
                return
        self.discard_pending_choice(choice)

    # -- "You may choose a new target for that copy" (CR 707.10) ------------

    def arm_copy_spell_target(self, player_index: int, copy_item) -> None:
        """Offer the copy's controller the re-aiming CR 707.10 gives them.

        The candidate list is the *same* one the caster's picker would be shown
        for the card — ``derive_cast_spec`` plus ``_enumerate_targets`` — so the
        engine and the picker cannot disagree about what is a legal target; the
        answer is checked back against this list rather than against the board.

        Nothing is armed when there is nothing to change to: a card with no
        derivable target spec, or a board offering a single candidate, is a
        choice with one answer, and a prompt with one answer is a stall rather
        than a decision.
        """
        from ...legality import cast_spec_of

        # The same one question the caster's own picker asks, through the same
        # helper — so the copy is offered exactly the targets the original was.
        spec = cast_spec_of(copy_item.card)
        if spec.get("kind") in (None, "none"):
            return
        offered: list[dict] = []
        for candidate in self._enumerate_targets(
            player_index, copy_item.card, spec, for_cast=True
        ):
            if candidate.get("kind") == "player":
                seat = candidate.get("seat")
                offered.append({
                    "kind": "player",
                    "seat": seat,
                    "name": self.players[seat].name,
                })
                continue
            # An index is not an identity (CR 400.7): the offer sits on the
            # queue across a priority window, so each slot is resolved to a
            # stable id here and the id is what the answer is checked against.
            perm = self.permanent_at(candidate.get("seat"), candidate.get("index"))
            if perm is None:
                continue
            offered.append({
                "kind": "permanent",
                "seat": candidate.get("seat"),
                "index": candidate.get("index"),
                "permanent_id": self.permanent_id_of(perm),
                "name": perm.card.name,
            })
        if len(offered) < 2:
            return
        self.arm_pending_choice(
            "copy_spell_target", player_index,
            card_name=copy_item.card.name,
            targets=offered,
            _copy=copy_item,
        )

    def confirm_copy_spell_target(
        self, player_index: int, permanent_id: int | None = None,
        target_seat: int | None = None,
    ) -> bool:
        """Answer the copy's target choice with a permanent's id or a seat."""
        return self.resolve_pending_choice(
            "copy_spell_target", player_index,
            permanent_id=permanent_id, seat=target_seat,
        )

    def _resolve_copy_spell_target(self, choice: PendingChoice, response: dict) -> bool:
        """Aim the waiting copy at the answer, if the answer was offered."""
        match = self._select_trigger_mode_target(
            {"valid_targets": choice.data.get("targets") or ()}, response
        )
        copy_item = choice.data.get("_copy")
        if match is None or copy_item is None:
            return False
        if match.get("kind") == "player":
            copy_item.target_player_index = match.get("seat")
            copy_item.target_permanent_index = None
            copy_item.target_permanent_id = None
            label = self.players[match["seat"]].name
        else:
            perm = self.permanent_by_id(match.get("permanent_id"))
            if perm is None:
                return False
            copy_item.target_player_index = self.controller_index_of(perm)
            copy_item.target_permanent_index = self.battlefield_index_of(perm)
            copy_item.target_permanent_id = self.permanent_id_of(perm)
            label = perm.card.name
        self.discard_pending_choice(choice)
        self.log.append(
            f"{choice.data.get('card_name', 'Copy')} (copy) targets {label}"
        )
        return True

    def _default_copy_spell_target(self, choice: PendingChoice) -> None:
        """The stated policy: **decline** — keep the original's target.

        Every other picker in this engine defaults to the first candidate
        offered, and each of those is a target the ability *must* have. This one
        is CR 707.10's *offer*, so it has a real decline, and declining is the
        answer that changes nothing. A copy whose original target has since
        become illegal keeps pointing at it and is countered on resolution
        (CR 608.2b), which is what declining means there too — re-aiming it at
        whatever the enumerator happened to list first would be a decision
        nobody made. A card whose copy should be aimed cleverly needs a
        valuation in `engine/ai_valuation.py`, not a branch here.
        """
        copy_item = choice.data.get("_copy")
        targets = list(choice.data.get("targets") or ())
        if copy_item is None or not targets:
            self.discard_pending_choice(choice)
            return
        if copy_item.target_permanent_index is None:
            current = {"seat": copy_item.target_player_index}
        else:
            # The id is what the answer is checked against, and a cast that
            # never stamped one still has a slot — resolved through the control
            # seam rather than left as None, which would make "keep the
            # original" silently fall through to "take the first offered".
            held = copy_item.target_permanent_id
            if held is None:
                perm = self.permanent_at(
                    copy_item.target_player_index, copy_item.target_permanent_index
                )
                held = self.permanent_id_of(perm) if perm is not None else None
            current = {"permanent_id": held}
        if not self._resolve_copy_spell_target(choice, current):
            self.discard_pending_choice(choice)

    def _run_optional_branch(self, entry: dict, key: str) -> bool:
        """Execute an optional-pay entry's instruction branch, if it has one.

        Returns whether anything ran, so the legacy life/draw/damage fields stay
        the fallback for entries that predate instruction branches.
        """
        steps = entry.get(key) or ()
        context = entry.get("_context")
        if not steps or context is None:
            return False
        # Through ``run_resumable`` for the same reason ``handlers/control_flow``'s
        # sequence is: a step may stop to ask its controller something, and the
        # steps behind it have to be recorded or they are silently lost.
        # Tetravus is the card that needed it — "remove any number of +1/+1
        # counters. **If you do, create that many … tokens**" ran the removal,
        # suspended on the count, and never made the tokens.
        run_resumable(
            self, steps, lambda step: self._execute_oracle_instruction(step, context)
        )
        return True

    def _resolve_mode_choice(
        self, choice: PendingChoice, mode_index: int, target: dict | None = None,
    ) -> bool:
        """Answer a "Choose one —" prompt with the *mode_index*'th offered mode.

        Two arming sites, one answer, and the difference between them is
        **when** rather than what:

        * A **modal triggered ability** (Relic Bind, Trufflesnout, Elder
          Gargaroth) is armed by ``_choose_trigger_mode`` as the ability is put
          on the stack, which is where CR 700.2b and CR 603.3c/603.3d put the
          choice. The answer — the mode *and*, per CR 601.2c, its target — is
          recorded onto that stack object; the ability resolves later, as an
          ability with a mode and a target already chosen.
        * A ``choose_one`` **nested inside a larger effect** ("that creature
          gains flying or first strike") is not a modal ability at all: the
          alternatives are a step of a resolution that is already running, so
          the chosen branch runs against the context it was armed with.

        ``_trigger_item`` is which of the two, and it is on the prompt rather
        than in a list of kinds here for the reason every registry in this
        engine exists: a second arming site added later says which one it is by
        the data it arms with.

        An index outside the offered list is refused and the prompt stays owed,
        the optional-pay shape. So is a mode that needs a target with no legal
        target named — CR 601.2c chooses the targets as part of the same
        announcement, and a mode announced without them was never legally
        chosen.
        """
        item = choice.data.get("_trigger_item")
        options = tuple(choice.data.get("_options") or ())
        legacy_modes = tuple(choice.data.get("_modes") or ())
        count = len(options) if item is not None else len(legacy_modes)
        if not 0 <= mode_index < count:
            return False
        labels = choice.data.get("labels") or ()
        label = labels[mode_index] if 0 <= mode_index < len(labels) else "a mode"
        card_name = choice.data.get("card_name", "Ability")
        if item is None:
            context = choice.data.get("_context")
            if context is None:
                return False
            self.discard_pending_choice(choice)
            self.log.append(f'{card_name}: chose "{label}"')
            self._execute_oracle_instruction(legacy_modes[mode_index], context)
            self.check_state_based_actions()
            return True
        option = options[mode_index]
        if option["spec"].get("requires_target"):
            target = (
                self._select_trigger_mode_target(option, target) if target is not None
                else self._default_trigger_mode_target(option, choice.player_index)
            )
            if target is None:
                return False
        else:
            target = None
        self.discard_pending_choice(choice)
        item.chosen_mode_index = option["index"]
        if target is not None:
            item.target_player_index = target.get("seat")
            if target.get("kind") == "permanent":
                item.target_permanent_index = target.get("index")
                item.target_permanent_id = self.permanent_ids_at(
                    target.get("seat"), target.get("index")
                )
            else:
                item.target_permanent_index = None
                item.target_permanent_id = None
        chosen_for = ""
        if target is not None:
            chosen_for = (
                f" targeting {target['name']}" if target.get("kind") == "permanent"
                else f" targeting {self.players[target['seat']].name}"
            )
        self.log.append(f'{card_name}: chose "{label}"{chosen_for}')
        return True

    def confirm_trigger_target(self, player_index: int, permanent_id: int) -> bool:
        """Answer a triggered ability's target choice with a permanent's id."""
        return self.resolve_pending_choice(
            "trigger_target", player_index, permanent_id=permanent_id
        )

    def _resolve_trigger_target(self, choice: PendingChoice, permanent_id: int) -> bool:
        """Record the chosen target on the stack object that asked (CR 601.2c).

        The ability stays on the stack and resolves later, with a target it now
        names — the same shape as a modal trigger's answer, and different from
        ``_resolve_reflexive_target``, which runs its steps immediately because
        a reflexive ability was never on the stack at all.

        The id is checked against the list that was offered rather than against
        the board: targets are chosen once, at announcement, so a permanent
        that became legal a moment later is not a legal answer.
        """
        offered = {
            target.get("permanent_id")
            for target in (choice.data.get("targets") or ())
        }
        if permanent_id not in offered:
            return False
        perm = self.permanent_by_id(permanent_id)
        if perm is None:
            return False
        seat = self.controller_index_of(perm)
        if seat is None:
            return False
        item = choice.data.get("_trigger_item")
        if item is None:
            return False
        self.discard_pending_choice(choice)
        item.target_player_index = seat
        item.target_permanent_index = self.battlefield_index_of(perm)
        item.target_permanent_id = permanent_id
        self.log.append(
            f"{choice.data.get('card_name', 'Ability')}: targets {perm.card.name}"
        )
        return True

    def _default_trigger_target(self, choice: PendingChoice) -> bool:
        """What a non-interactive seat answers with: the **first** target
        offered.

        The stated policy every other picker in this engine takes when nothing
        distinguishes the candidates, and stated here rather than valued —
        ``_default_trigger_mode_target`` next door is the one that reads an
        effect family, and it can only do so because a mode carries its own
        instruction.
        """
        targets = choice.data.get("targets") or ()
        if not targets:
            self.discard_pending_choice(choice)
            return True
        return self._resolve_trigger_target(choice, targets[0]["permanent_id"])

    def _select_trigger_mode_target(self, option: dict, target: dict) -> dict | None:
        """The offered candidate *target* names, or None if it names none.

        *target* is what a caller could say over a wire: ``permanent_id`` for
        an object (the stable identity, never a battlefield slot - CR 400.7,
        and an index chosen a moment ago can address a different permanent),
        ``seat`` for a player. It is resolved **against the option's own
        candidate list**, so an answer naming something the picker never
        offered is refused rather than quietly performed - the engine and the
        picker agree on what is a legal target because they are reading the
        same list.
        """
        for candidate in option.get("valid_targets") or []:
            if candidate.get("kind") == "permanent":
                if target.get("permanent_id") is None:
                    continue
                permanent = self.permanent_at(candidate["seat"], candidate["index"])
                if permanent is not None and permanent.permanent_id == target["permanent_id"]:
                    return candidate
            elif target.get("permanent_id") is None and candidate.get("seat") == target.get("seat"):
                return candidate
        return None

    def _default_mode_choice(self, choice: PendingChoice) -> bool:
        """What a non-interactive seat answers a "Choose one —" prompt with:
        the first *offered* mode.

        A stated policy, not a valuation — the same one the choice registry has
        always taken — and "offered" rather than "printed" because CR 700.2b
        has already removed from the list any mode whose targets could not be
        chosen. The target inside that mode is
        ``_default_trigger_mode_target``'s, which is derived from the mode's
        own effect family rather than named per card.
        """
        return self._resolve_mode_choice(choice, 0)

    def _apply_optional_pay_decline(self, player_index: int, entry: dict) -> None:
        """The consequence of NOT paying an optional-pay prompt. Plain "may pay"
        riders (the color rods) have none; "unless you pay" entries (Hasran
        Ogress) carry a ``damage`` amount dealt to the player instead."""
        player = self.players[player_index]
        if self._run_optional_branch(entry, "_on_decline"):
            return
        damage = int(entry.get("damage", 0) or 0)
        if damage > 0:
            source = entry.get("_source_permanent")
            self._deal_damage_to_player(
                player, damage, source=source,
                then=lambda dealt: self.log.append(
                    f"{entry['card_name']} dealt {dealt} damage to {player.name}"
                ),
            )
        else:
            self.log.append(f"{player.name} declined {entry['card_name']}")

    def confirm_optional_pay(self, player_index: int, card_name: str | None = None, accept: bool = True) -> bool:
        """Resolve the first pending optional "pay {N}" trigger for a player (the
        color rods' gain-life riders, Hasran Ogress' pay-or-take-damage).
        ``accept`` pays it; otherwise the decline consequence (if any) applies."""
        choice = next(
            (
                c for c in self.pending_choices_of("optional_pay", player_index)
                if card_name is None or c.data["card_name"] == card_name
            ),
            None,
        )
        if choice is None:
            return False
        return self._answer_pending_choice(
            choice, lambda: self._resolve_optional_pay(choice, accept)
        )

    def _resolve_optional_pay(self, choice: PendingChoice, accept: bool) -> bool:
        player_index = choice.player_index
        entry = choice.data
        self.discard_pending_choice(choice)
        if accept and self._player_can_pay_optional(self.players[player_index], entry):
            self._pay_optional(player_index, entry)
        else:
            self._apply_optional_pay_decline(player_index, entry)
        # The trigger ability that raised this prompt was held on the stack (human
        # priority path). Whether it now leaves is `_release_stack_item`'s answer,
        # not this one: accepting can arm the *next* prompt of the same
        # resolution — "you may search your library …" (Sanctum of All) offers
        # the search here — and the ability is still resolving until that is
        # answered too.
        self._release_stack_item(entry.get("_stack_item"))
        return True

    def _default_optional_pay(self, choice: PendingChoice) -> None:
        """Pay when the floating mana is already there; an unpayable "unless you
        pay" entry applies its decline consequence (Hasran Ogress' damage).

        A *stated policy*, not the payability test: the non-interactive default
        spends mana it already has and never taps a land for an optional cost,
        because tapping is a real decision about the rest of the turn.
        ``_player_can_pay_optional`` is the wider question and belongs to the
        seat that was actually asked."""
        entry = choice.data
        player = self.players[choice.player_index]
        # A life cost has no "already floating" reading — nothing is held in
        # reserve to spend — so the stated policy is the one a player at a
        # healthy life total would take: pay, unless it would be lethal.
        life_cost = int(entry.get("life_cost", 0) or 0)
        floating = (
            (True if player.life > life_cost else None)
            if life_cost
            else plan_payment(player.mana_pool, (), entry.get("cost") or {})
        )
        # The same policy for CR 118.8's alternative: floating mana first, and
        # the life only when there is none — and never down to zero, which is
        # the reading the life-cost branch above already takes.
        alternative = int(entry.get("life_alternative", 0) or 0)
        if floating is None and alternative and player.life > alternative:
            floating = True
        self.discard_pending_choice(choice)
        if floating is not None:
            self._pay_optional(choice.player_index, entry)
        elif int(entry.get("damage", 0) or 0) > 0 or entry.get("_on_decline"):
            # A decline is an *answer*, and an answer with a consequence has to
            # have it applied. This read the legacy damage field alone, so a
            # grammar-lowered "if you don't, …" branch was dropped for every
            # non-interactive seat — Transmute Artifact's found card simply
            # vanished instead of going to a graveyard.
            self._apply_optional_pay_decline(choice.player_index, entry)
        self._release_stack_item(entry.get("_stack_item"))

    def auto_resolve_pending_optional_pays(self, only_player_index: int | None = None) -> None:
        """Pay every pending optional "pay {N}" trigger when able — the
        deterministic default used for AI players and headless simulation."""
        self.auto_resolve_pending_choices(only_player_index=only_player_index, kinds=("optional_pay",))

    # -- Paying life to buy one permanent out of a sweep (Cleansing) --------

    def confirm_pay_life_to_save(self, player_index: int, accept: bool = True) -> bool:
        """Answer "…unless any player pays N life" for the land on offer."""
        return self.resolve_pending_choice(
            "pay_life_to_save", player_index, accept=bool(accept)
        )

    def _resolve_pay_life_to_save(self, choice: PendingChoice, accept: bool) -> bool:
        """Pay, or decline and let the sweep have it.

        The saved set is the *loop's own* record, handed in when the prompt was
        armed. It has to be, and not a field here: the offer goes round every
        seat about one permanent, and what the loop needs to know is whether
        anybody has paid yet — a per-seat answer cannot say."""
        data = choice.data
        player = self.players[choice.player_index]
        life = int(data.get("life", 1))
        self.discard_pending_choice(choice)
        # CR 119.4: a player may pay N life only with at least N to pay. Down to
        # exactly 0 is legal, and the state-based check that follows ends the
        # game — so this is a refusal to pay what is not there, not a life
        # total this rule is protecting.
        if not accept or player.life < life:
            self.log.append(
                f"{player.name} declined to pay {life} life for "
                f"{data.get('permanent_name', 'a permanent')}"
            )
            return True
        player.life -= life
        saved = data.get("_saved")
        if saved is not None:
            saved.add(int(data["permanent_id"]))
        self.log.append(
            f"{player.name} paid {life} life to save "
            f"{data.get('permanent_name', 'a permanent')} ({data.get('card_name', '')})"
        )
        return True

    def _default_pay_life_to_save(self, choice: PendingChoice) -> None:
        """The stated policy for a seat nobody is asking: pay for a permanent
        you control, and only while the payment is not your whole life total.

        A policy rather than a valuation, the discipline
        ``_default_optional_pay`` states: a seat pays to keep its own board and
        never pays to keep an opponent's, and it never pays itself to nothing
        for one permanent. A card that should choose otherwise wants a
        valuation in ``engine/ai_valuation.py``, not a branch here."""
        permanent = self.permanent_by_id(choice.data.get("permanent_id"))
        seat = self.controller_index_of(permanent) if permanent is not None else None
        life = int(choice.data.get("life", 1))
        mine = seat == choice.player_index
        self._resolve_pay_life_to_save(
            choice, mine and self.players[choice.player_index].life > life
        )

    # -- Which permanent receives a loyalty counter (Liliana's Scrounger) ----

    def confirm_loyalty_recipient(self, player_index: int, permanent_id: int) -> bool:
        return self.resolve_pending_choice(
            "loyalty_recipient", player_index, permanent_id=permanent_id
        )

    def live_loyalty_recipients(self, choice: PendingChoice) -> list:
        """The armed candidates still on the battlefield and still matching the
        printed noun phrase.

        Public because the prompt renderer is a second legitimate caller: the
        list it offers and the list the answer is checked against have to be the
        same rule, not two copies of it.

        Asked again rather than trusted: the set was enumerated when the ability
        resolved, and a permanent can leave — or stop being what the phrase names
        — before the seat answers. By identity, never index.
        """
        described = dict(choice.data.get("filter") or {})
        return [
            perm
            for perm in (choice.data.get("_candidates") or ())
            if self.is_on_battlefield(perm)
            and subject_matches(
                self, perm, described,
                observer=choice.player_index, source=choice.data.get("_source"),
            )
        ]

    def _resolve_loyalty_recipient(self, choice: PendingChoice, permanent_id) -> bool:
        """Put the counters on the permanent the seat named.

        The offered list is a hint and this is the check: the answer must still
        be one of the live candidates, so a client that offers a whole
        battlefield cannot turn "a Liliana planeswalker you control" into any
        planeswalker at all.
        """
        from ...handlers.pump import place_loyalty_counters

        live = self.live_loyalty_recipients(choice)
        if not live:
            self.discard_pending_choice(choice)
            self.log.append(
                f"{choice.data['card_name']}: nothing is left to receive the counter"
            )
            return True
        perm = self.permanent_by_id(permanent_id) if permanent_id is not None else None
        if perm is None or not any(perm is candidate for candidate in live):
            return False
        self.discard_pending_choice(choice)
        count = int(choice.data.get("count", 1))
        total = place_loyalty_counters(perm, count)
        self.log.append(
            f"{choice.data['card_name']}: {count} loyalty counter(s) on "
            f"{perm.card.name} (now {total})"
        )
        self.check_state_based_actions()
        return True

    def _default_loyalty_recipient(self, choice: PendingChoice) -> None:
        """The stated policy: **the fewest loyalty counters**, ties broken by
        battlefield scan order.

        Loyalty is a planeswalker's life total (CR 306.5c) and CR 704.5i bins one
        that reaches zero, so the counter is worth most on the walker closest to
        dying. A card whose AI should choose otherwise needs a valuation, not a
        branch here.
        """
        live = self.live_loyalty_recipients(choice)
        if not live:
            self.discard_pending_choice(choice)
            return
        pick = min(live, key=lambda perm: int(perm.metadata.get("loyalty_counters", 0)))
        if not self._resolve_loyalty_recipient(choice, self.permanent_id_of(pick)):
            self.discard_pending_choice(choice)

    # -- Forced sacrifice of the player's choice (Lich, Lord of the Pit) ---------
    #
    # A single mechanism drives every "sacrifice a permanent you choose" effect so
    # they behave uniformly. ``arm_forced_sacrifice`` either arms an interactive
    # prompt (human seat) or resolves the sacrifice inline with a deterministic
    # heuristic (AI / headless). The choice's payload is
    #   {"count", "filter", "exclude", "reason", "on_short"}
    # where ``filter`` is the printed noun phrase as a filter payload
    # (``{"nontoken": True}`` for Lich, ``{"type_filter": "creature"}`` for Lord of
    # the Pit, ``{"type_filter": "creature", "with_keywords": ["flying"]}`` for Run
    # Afoul), ``exclude`` is a Permanent that can't be chosen (Lord of the Pit
    # excludes itself), and ``on_short`` is the effect applied when the player owes
    # more sacrifices than they can make (None, {"kind": "lose"}, or
    # {"kind": "damage", "amount": N}).
    #
    # It used to be one of two words, "nontoken" or "creature", tested by two
    # hand-written lines here. That is why a narrowed sacrifice had to be refused
    # at compile time rather than charged: the noun phrase the card prints is a
    # filter, and this was the one reader of it that could not read one.

    def _sacrifice_candidate_indices(self, player, filter: dict | None, exclude=None) -> list[int]:
        """Battlefield indices of ``player``'s permanents eligible for a forced
        sacrifice under the filter payload ``filter`` (excluding ``exclude`` if
        given)."""
        out: list[int] = []
        for i, perm in enumerate(player.battlefield):
            if exclude is not None and perm is exclude:
                continue
            if not subject_matches(self, perm, filter):
                continue
            out.append(i)
        return out

    def _apply_sacrifice_shortfall(self, player_index: int, owed: int, on_short, reason: str) -> None:
        """Apply the consequence for a player who can't sacrifice all they owe."""
        if not on_short or owed <= 0:
            return
        player = self.players[player_index]
        if on_short.get("kind") == "lose":
            player.lost = True
            self.log.append(
                f"{player.name} couldn't sacrifice a nontoken permanent and lost the game ({reason})"
            )
        elif on_short.get("kind") == "damage":
            self._deal_damage_to_player(
                player, int(on_short.get("amount", 0)),
                then=lambda dealt: self.log.append(
                    f"{reason} dealt {dealt} damage to {player.name}"
                ),
            )

    def _resolve_sacrifice_inline(self, player_index: int, count: int, filter: dict | None, exclude, reason: str, on_short, record: dict | None = None, up_to: bool = False, count_onto=None) -> None:
        """Sacrifice ``count`` of the player's permanents with the deterministic
        heuristic (permanents whose death loses the game are kept for last).

        ``up_to`` is a **stated policy**, not a heuristic: a seat merely
        *offered* the chance to give permanents up gives up none. Sacrificing is
        a cost, and a non-interactive seat paying an optional cost nobody asked
        it for is the engine playing that seat's game. Wood Elemental therefore
        enters as a 0/0 and dies to CR 704.5f, which is what the card does when
        its controller declines."""
        player = self.players[player_index]
        if up_to:
            self._record_sacrifice_count(count_onto, 0)
            return
        for _ in range(count):
            valid = self._sacrifice_candidate_indices(player, filter, exclude)
            if not valid:
                self._apply_sacrifice_shortfall(player_index, 1, on_short, reason)
                return
            # `default_sacrifice_pick`'s docstring already named this as one of
            # the three callers of the one rule; it was in fact a fourth copy,
            # carrying the "keep the game-loser for last" half and neither the
            # smallest-first half nor the id tiebreak. Two seats owing the same
            # sacrifice through different paths would have given it up
            # differently, which is what the shared rule exists to stop.
            perm = self.default_sacrifice_pick(
                [self.permanent_at(player, i) for i in valid]
            )
            if record is not None:
                record.setdefault("sacrificed_cards", []).append(perm.card)
            self.sacrifice_permanent(perm)
            self.log.append(f"{player.name} sacrificed {perm.card.name} ({reason})")

    def arm_forced_sacrifice(
        self,
        player_index: int,
        count: int,
        *,
        filter: dict,
        exclude=None,
        reason: str = "Sacrifice",
        on_short=None,
        record: dict | None = None,
        up_to: bool = False,
        count_onto=None,
    ) -> None:
        """Force a player to sacrifice ``count`` permanents matching the filter
        payload ``filter``. A human seat is prompted to choose which; AI /
        headless play resolves it inline. Multiple calls to the same player
        during one step accumulate onto the existing prompt (e.g. two
        combat-damage events feeding Lich).

        ``filter`` has no default. An empty payload is a legal value meaning "any
        permanent", but it has to be written down: a caller that simply forgot
        the noun phrase would otherwise sacrifice more widely than the card
        prints, and defaulting is how that stays invisible.

        ``record`` is a resolution scratchpad the sacrificed *cards* are appended
        to under ``sacrificed_cards``. A later step of the same effect may be
        about what went (Transmute Artifact reads its mana value), and by then
        the permanent is in a graveyard and is a different object (CR 400.7) —
        so it is recorded as it happens, which is CR 608.2h's rule.

        ``up_to`` makes ``count`` a **ceiling** rather than an amount: "sacrifice
        any number of untapped Forests" (Wood Elemental) is answered by any
        subset, none included. A flag on the same prompt rather than a second
        kind for the reason ``discard``'s ``up_to`` is one: what differs is how
        many answers are legal, not what the answer means.

        ``count_onto`` is a permanent that wants to know **how many** were given
        up: the number goes in its ``sacrificed_as_entered`` metadata, which is
        what a characteristic-defining P/T reading "equal to the number of
        <things> sacrificed as it entered" counts (CR 604.3). It is recorded
        where the sacrifice happens because nothing downstream can recover it —
        the permanents are gone, and are different objects (CR 400.7)."""
        player = self.players[player_index]
        if not self._sacrifice_candidate_indices(player, filter, exclude):
            # Nothing matches, so nothing can be given up. An "any number"
            # sacrifice is *answered* by that — zero is a legal answer — so the
            # count it owes is recorded rather than left unset.
            self._record_sacrifice_count(count_onto, 0)
            self._apply_sacrifice_shortfall(player_index, count, on_short, reason)
            return
        queued = self.pending_choice_of("sacrifice", player_index)
        if queued is not None:
            if (
                queued.data["filter"] == filter
                and queued.data["exclude"] is exclude
                # A ceiling and an amount are different questions, so they do not
                # add up: folding "any number of Forests" into "sacrifice two
                # Forests" would let one answer discharge both, at whichever of
                # the two readings the merged prompt happened to keep.
                and bool(queued.data.get("up_to")) == bool(up_to)
                and queued.data.get("_count_onto") is count_onto
            ):
                queued.data["count"] += count
            else:
                # A differently-shaped sacrifice is already owed; this one can't be
                # folded into that prompt, so it resolves inline.
                self._resolve_sacrifice_inline(
                    player_index, count, filter, exclude, reason, on_short, record,
                    up_to=up_to, count_onto=count_onto,
                )
            return
        self.arm_pending_choice(
            "sacrifice", player_index,
            count=count, filter=filter, exclude=exclude, reason=reason,
            on_short=on_short, record=record, up_to=up_to, _count_onto=count_onto,
        )

    def _record_sacrifice_count(self, count_onto, given_up: int) -> None:
        """Stamp how many permanents were sacrificed onto the permanent that
        asked for them (CR 604.3's "…sacrificed as it entered").

        A no-op for every sacrifice nobody is counting, which is all of them but
        one shape — so the three answer paths record unconditionally rather than
        each remembering to ask."""
        if count_onto is None:
            return
        count_onto.metadata["sacrificed_as_entered"] = int(given_up)
        self._refresh_dynamic_creatures()

    def pending_sacrifice_state(self) -> dict | None:
        """The active sacrifice prompt as valid battlefield indices + count, or
        None. Used by the web layer to render/highlight the choice."""
        choice = self.pending_choice_of("sacrifice")
        if choice is None:
            return None
        return self._sacrifice_prompt(choice)

    def _sacrifice_prompt(self, choice: PendingChoice) -> dict:
        player = self.players[choice.player_index]
        valid = self._sacrifice_candidate_indices(
            player, choice.data["filter"], choice.data["exclude"]
        )
        return {
            "player_index": choice.player_index,
            "valid_indices": valid,
            "count": min(int(choice.data["count"]), len(valid)),
            # Whether that count is an amount owed or a ceiling offered. The
            # picker needs the difference: one enables its confirm at exactly
            # that many, the other at any number up to it, none included.
            "up_to": bool(choice.data.get("up_to")),
            "reason": choice.data["reason"],
        }

    def confirm_sacrifice(self, player_index: int, indices: list[int]) -> bool:
        """Resolve the pending forced sacrifice with the player's chosen battlefield
        indices. Requires exactly ``min(count, eligible permanents)`` distinct
        eligible permanents; if the player owed more than they could sacrifice, the
        shortfall consequence applies (Lich loses; Lord of the Pit deals damage)."""
        return self.resolve_pending_choice("sacrifice", player_index, indices=indices)

    def _resolve_sacrifice(self, choice: PendingChoice, indices: list[int]) -> bool:
        player_index = choice.player_index
        player = self.players[player_index]
        data = choice.data
        valid = self._sacrifice_candidate_indices(player, data["filter"], data["exclude"])
        count = int(data["count"])
        need = min(count, len(valid))
        chosen = list(dict.fromkeys(indices or []))
        # "Sacrifice **any number** of untapped Forests" (Wood Elemental): the
        # printed count is a ceiling, and none is a legal answer. Reading a
        # ceiling as an exact count would force a player to give up permanents
        # the card offered them the choice of keeping — the mirror of the same
        # word on `discard`.
        enough = len(chosen) <= need if data.get("up_to") else len(chosen) == need
        if not enough or any(i not in valid for i in chosen):
            return False
        reason = data["reason"]
        # Resolved before any removal, so no index is held across one.
        removed: list[str] = []
        record = data.get("record")
        for perm in [self.permanent_at(player, i) for i in sorted(chosen, reverse=True)]:
            if record is not None:
                record.setdefault("sacrificed_cards", []).append(perm.card)
            self.sacrifice_permanent(perm)
            removed.append(perm.card.name)
        for name in reversed(removed):
            self.log.append(f"{player.name} sacrificed {name} ({reason})")
        self.discard_pending_choice(choice)
        self._record_sacrifice_count(data.get("_count_onto"), len(chosen))
        # A ceiling nobody filled is not a shortfall: "any number" was answered.
        if count > len(valid) and not data.get("up_to"):
            self._apply_sacrifice_shortfall(player_index, count - len(valid), data["on_short"], reason)
        self.check_state_based_actions()
        return True

    def _default_sacrifice(self, choice: PendingChoice) -> None:
        self.discard_pending_choice(choice)
        data = choice.data
        self._resolve_sacrifice_inline(
            choice.player_index, int(data["count"]), data["filter"],
            data["exclude"], data["reason"], data["on_short"], data.get("record"),
            up_to=bool(data.get("up_to")), count_onto=data.get("_count_onto"),
        )

    # Upper bound on resolve/SBA cycles in one _settle() call. A genuine infinite
    # loop (a pathological card pool) is bounded here so the seeded simulator can
    # never hang; we log and break rather than raise.
    MAX_SETTLE_ITERS = 2000

    # ------------------------------------------------------------------
    # CR 616.1e — which of several applicable effects applies first
    # ------------------------------------------------------------------

    def _record_effect_order(self, choice: PendingChoice, option_index: int) -> None:
        """Store the picked effect ahead of the rest, in their default order.

        The answer is one pick, not a full ordering, because that is all CR
        616.1e needs from the player each round — but the process may reach a
        second contended round on its way through, and by then it is past the
        point where it can ask again. Recording the pick *followed by* the
        default order gives every later round an answer that is consistent with
        the one the player gave.
        """
        keys = list(choice.data["_keys"])
        picked = keys[option_index]
        self.effect_order_answers[(choice.data["event_kind"], choice.player_index)] = tuple(
            [picked] + [key for key in keys if key != picked]
        )

    def _resolve_effect_order(self, choice: PendingChoice, option_index: int) -> bool:
        keys = choice.data["_keys"]
        if not (0 <= option_index < len(keys)):
            return False
        self.discard_pending_choice(choice)
        self._record_effect_order(choice, option_index)
        self.log.append(
            f"{self.players[choice.player_index].name} applies "
            f"{choice.data['options'][option_index]} first"
        )
        # Nothing was applied when the prompt was armed, so the event is re-run
        # rather than resumed — and it reaches the same round, finds the
        # recorded answer, and carries on. The suspension was lifted by
        # ``resolve_pending_choice`` before this ran (the kind is ``suspends``),
        # and the loops waiting on the event are unwound by it afterwards.
        choice.data["_restart"]()
        return True

    def _default_effect_order(self, choice: PendingChoice) -> None:
        """The documented default (the first option, which the asker listed in
        default order). Reached when a seat stops being interactive with the
        prompt still queued."""
        self._resolve_effect_order(choice, 0)


# ---------------------------------------------------------------------------
# The prompt table
# ---------------------------------------------------------------------------
#
# One row per interactive decision in the engine. ``resolve`` applies the
# answering seat's response, ``default`` is what every other seat does, and the
# rest is what the web layer needs to render the prompt, gate the actions
# around it and route the action that answers it. A kind whose behaviour lives
# in another mixin is registered here anyway, so this stays the one index.

register_choice(
    "effect_order",
    resolve=lambda game, choice, r: game._resolve_effect_order(choice, r["option_index"]),
    default=lambda game, choice: game._default_effect_order(choice),
    action="effect_order_confirm",
    prompt_key="effect_order",
    blocked_detail="choose which effect applies first before other actions",
    # The event this interrupts has not happened yet — a draw that is waiting on
    # the answer has not drawn, damage waiting on it has not been dealt — so no
    # seat should be acting on a board that is mid-event.
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # The one kind that has always suspended: CR 616.1e stops an event dead, and
    # the loop that event was a step of has to stop with it. The flag it used to
    # set by hand in engine/replacements.py is this field.
    suspends=True,
)

register_choice(
    "hand_to_library",
    resolve=lambda game, choice, r: game._resolve_hand_to_library(
        choice, r["hand_indices"]
    ),
    default=lambda game, choice: game._default_hand_to_library(choice),
    action="hand_to_library_confirm",
    prompt_key="hand_to_library",
    blocked_detail="choose which cards go back on top of your library",
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # Brainstorm draws three and then puts two back, and the two are steps of
    # one resolution: nothing after the prompt may read a hand the answer has
    # not reshaped yet (CR 608.2, CR 117.3b).
    suspends=True,
)

register_choice(
    "search_library",
    # `zone` defaults so a caller written before the graveyard existed — and the
    # web action, which sends it only when the client picked one — still names
    # the library. A counted search ("up to two basic land cards") is answered
    # whole through `picks`; the single-find shape keeps its one index.
    resolve=lambda game, choice, r: (
        game._resolve_search_library_picks(choice, r["picks"])
        if "picks" in r
        else game._resolve_search_library(
            choice, r["library_index"], r.get("zone", "library")
        )
    ),
    default=lambda game, choice: game._default_search_library(choice),
    action="search_library_confirm",
    # "Fail to find" (CR 701.19b) is the second answer, not a way around the
    # prompt — and the only one available when nothing matches the restriction.
    also_answers=("search_library_decline",),
    prompt_key="search_library",
    blocked_detail="complete library search before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    # A search is armed for AI seats too and drained by the auto-resolver; the
    # prompt is rendered for whoever still owes it.
    hidden_for_ai=False,
    # A search takes a card out of the library and shuffles what is left, so any
    # later step of the same resolution reads a library the answer decided.
    suspends=True,
)

register_choice(
    "search_destination",
    # A counted search whose printed slots differ ("put one onto the
    # battlefield tapped and the other into your hand") asks its finder which
    # found card fills which slot. The finds are already made and shown — this
    # is only where each lands, so it works the same over any zone a picker
    # took the cards from.
    resolve=lambda game, choice, r: game._resolve_search_destination(
        choice, r.get("assignments") or []
    ),
    default=lambda game, choice: game._default_search_destination(choice),
    action="search_destination_confirm",
    prompt_key="search_destination",
    blocked_detail="choose where each found card goes before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # The cards land only when the answer is applied, so a later step of the
    # same resolution must not read a board they have not reached yet.
    suspends=True,
)

register_choice(
    "look_top_pick",
    resolve=lambda game, choice, r: game._resolve_look_top_pick(choice, r.get("keep_index", -1)),
    default=lambda game, choice: game._default_look_top_pick(choice),
    action="look_top_pick_confirm",
    prompt_key="look_top_pick",
    blocked_detail="choose a card to keep before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # The answer reshapes the library, and CR 608.2n's move to the graveyard
    # is a later step of the same resolution — the scry discipline exactly.
    suspends=True,
)

register_choice(
    "tap_any_number",
    resolve=lambda game, choice, r: game._resolve_tap_any_number(
        choice, r.get("permanent_ids") or []
    ),
    default=lambda game, choice: game._default_tap_any_number(choice),
    action="tap_any_number_confirm",
    prompt_key="tap_any_number",
    blocked_detail="choose which creatures to tap before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # Deliberately not suspending, and that is the whole reason the two printed
    # sentences fuse into one instruction: the boost is applied by this choice's
    # own resolver, so no value has to survive across a resumption.
)

register_choice(
    "untap_up_to",
    resolve=lambda game, choice, r: game._resolve_untap_up_to(choice, r.get("permanent_ids") or []),
    default=lambda game, choice: game._default_untap_up_to(choice),
    action="untap_up_to_confirm",
    prompt_key="untap_up_to",
    blocked_detail="choose which permanents to untap before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # Deliberately not suspending: the untap is the last step of the effect
    # that armed it, so nothing later in the same resolution reads the answer.
)

register_choice(
    "search_exile_cards",
    resolve=lambda game, choice, r: game._resolve_search_exile(choice, r.get("picks") or []),
    default=lambda game, choice: game._default_search_exile(choice),
    action="search_exile_confirm",
    prompt_key="search_exile",
    blocked_detail="complete your search before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # The picks are what the next step of the same resolution ("You may cast
    # them this turn.") grants permission over, so that step must wait.
    suspends=True,
)

register_choice(
    "reorder_library",
    resolve=lambda game, choice, r: game._resolve_reorder_library(choice, r["new_order"], r["shuffle"]),
    default=lambda game, choice: game._default_reorder_library(choice),
    action="reorder_library_confirm",
    prompt_key="reorder_library",
    blocked_detail="complete library reorder before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    # Same reason as scry: the answer *is* what the next card off the library
    # will be.
    suspends=True,
)

register_choice(
    "scry",
    resolve=lambda game, choice, r: game._resolve_scry(choice, r["card_order"], r["bottom_count"]),
    default=lambda game, choice: game._default_scry(choice),
    action="scry_confirm",
    prompt_key="scry",
    blocked_detail="complete scry before other actions",
    # Same treatment as reorder_library: the scry suspends a resolution, so the
    # whole game waits and a spectator sees that it is waiting. An AI seat stays
    # queued and is drained by the auto-resolver, which keeps ordering
    # deterministic per seed.
    blocks_every_seat=True,
    spectator_visible=True,
    # "Scry 1. Draw a card." is the shape this field exists for: the draw is a
    # later step of the same resolution and must see the library the scry
    # arranged, not the one it was handed.
    suspends=True,
)

register_choice(
    "revealed_hand_pick",
    resolve=lambda game, choice, r: game._resolve_revealed_hand_pick(choice, r["hand_index"]),
    default=lambda game, choice: game._default_revealed_hand_pick(choice),
    action="revealed_hand_pick_confirm",
    prompt_key="revealed_hand_pick",
    blocked_detail="choose a card from the revealed hand before other actions",
    # The revealed hand is public from the moment it is revealed (CR 701.20),
    # so a spectator sees the prompt exactly as the choosing seat does.
    spectator_visible=True,
)

register_choice(
    "discard",
    resolve=lambda game, choice, r: game._resolve_discard(choice, r["hand_indices"], r["to_library"]),
    default=lambda game, choice: game._default_discard(choice),
    action="discard_confirm",
    prompt_key="discard_select",
    blocked_detail="complete discard before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    # "Discard X cards, then <do something for each card discarded this way>"
    # (Recall) is the shape: the step behind the discard has to see the cards
    # that were actually discarded, not the hand as it stood when the prompt was
    # armed. CR 608.2 / CR 117.3b — nothing else in the resolution happens until
    # the last of its prompts is answered.
    suspends=True,
)

register_choice(
    "balance",
    resolve=lambda game, choice, r: game._resolve_balance(
        choice, r["land_indices"], r["creature_indices"], r["hand_indices"]
    ),
    default=lambda game, choice: game._default_balance(choice),
    action="balance_confirm",
    prompt_key="balance_select",
    blocked_detail="complete Balance sacrifices before other actions",
)

register_choice(
    "sacrifice",
    resolve=lambda game, choice, r: game._resolve_sacrifice(choice, r["indices"]),
    default=lambda game, choice: game._default_sacrifice(choice),
    action="sacrifice_confirm",
    prompt_key="sacrifice_select",
    blocked_detail="complete forced sacrifice before other actions",
    default_at_arm=True,
    spectator_visible=True,
    # "Sacrifice an artifact. **If you do**, search your library…" (Transmute
    # Artifact): what the player gives up decides what the rest of the same
    # resolution may find, so the rest has to wait for the answer. Only an
    # interactive seat ever queues this — `default_at_arm` takes the
    # deterministic answer before the flag is set — so headless and AI play run
    # exactly as they did.
    suspends=True,
)

register_choice(
    "pay_life_to_save",
    resolve=lambda game, choice, r: game._resolve_pay_life_to_save(choice, r["accept"]),
    default=lambda game, choice: game._default_pay_life_to_save(choice),
    action="pay_life_to_save_confirm",
    prompt_key="pay_life_to_save",
    blocked_detail="answer the pay-to-save offer before other actions",
    spectator_visible=True,
    hidden_for_ai=False,
    # The answer decides what the *next* step of the same resolution does with
    # this permanent — and, one step later, whether the seat behind you is
    # asked about it at all — so the loop genuinely stops here.
    suspends=True,
    # A non-interactive seat never queues it: the sweep has to finish, and the
    # stated default is taken where the offer stands. That is also what keeps
    # AI and headless play free of the suspension above.
    default_at_arm=True,
)

register_choice(
    "optional_pay",
    resolve=lambda game, choice, r: game._resolve_optional_pay(choice, r["accept"]),
    default=lambda game, choice: game._default_optional_pay(choice),
    action="resolve_optional_pay",
    prompt_key="optional_pay",
    # The kind outgrew its first card: it now carries any optional cost or
    # action, on a trigger or on a whole spell (Twiddle, Rebirth), so the
    # message names the offer rather than the one card it was written for.
    blocked_detail="answer the optional-cost offer before other actions",
)

register_choice(
    "trigger_target",
    resolve=lambda game, choice, r: game._resolve_trigger_target(
        choice, r["permanent_id"]
    ),
    default=lambda game, choice: game._default_trigger_target(choice),
    action="trigger_target_confirm",
    prompt_key="trigger_target",
    blocked_detail="choose the triggered ability's target before other actions",
    # The choice is part of putting the ability on the stack (CR 603.3d), so a
    # non-interactive seat takes it there and then — nothing queues, and
    # headless and AI play run exactly as they did.
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    "reflexive_target",
    resolve=lambda game, choice, r: game._resolve_reflexive_target(
        choice, r["permanent_id"]
    ),
    default=lambda game, choice: game._default_reflexive_target(choice),
    action="reflexive_target_confirm",
    prompt_key="reflexive_target",
    blocked_detail="choose the reflexive trigger's target before other actions",
)

register_choice(
    "copy_spell_target",
    resolve=lambda game, choice, r: game._resolve_copy_spell_target(choice, r),
    default=lambda game, choice: game._default_copy_spell_target(choice),
    action="copy_spell_target_confirm",
    prompt_key="copy_spell_target",
    blocked_detail="choose the copy's target before other actions",
    # CR 707.10: the copy's targets are chosen as the copy is created, which is
    # part of the resolution that created it — so a non-interactive seat answers
    # there and then and nothing queues. That is also what keeps the headless
    # path honest: `_settle()` drains the stack without pausing, and a prompt
    # left queued here would be answered after the copy it was meant to aim.
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    "hand_reveal",
    resolve=lambda game, choice, r: game._dismiss_hand_reveal(choice),
    default=lambda game, choice: game._dismiss_hand_reveal(choice),
    action="dismiss_hand_reveal",
    prompt_key="hand_reveal",
    # Not a decision — the viewer has already seen the hand. Nothing waits on it.
    blocked_detail=None,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "number_choice",
    resolve=lambda game, choice, r: game._resolve_number_choice(choice, r["number"]),
    default=lambda game, choice: game._default_number_choice(choice),
    action="number_choice_confirm",
    prompt_key="number_choice",
    blocked_detail="choose a number before other actions",
    # Tetravus's removal is one step of a sentence whose next step reads the
    # answer ("create **that many** … tokens"), so the loop it is a step of has
    # to stop until the number exists. Shapeshifter's two armings sit at the end
    # of what they are part of, so suspending costs them nothing.
    suspends=True,
)

register_choice(
    "land_type_choice",
    resolve=lambda game, choice, r: game._resolve_land_type(choice, r["land_type"]),
    # The provisional default stamped when the Aura attached is an Island, so
    # taking it again is what a non-interactive controller does.
    default=lambda game, choice: game._resolve_land_type(choice, "island"),
    action="land_type_confirm",
    prompt_key="land_type_choice",
    # Phantasmal Terrain arms this as it enters, and its own comment says "the
    # spell never visibly resolves the land change before the player finishes
    # the choice" — which needs the game to actually wait. The Aura is already
    # on the battlefield (not a spell held on the stack), so it is armed with
    # ``_stack_item=None``: holds priority, holds no finished object.
    blocked_detail="choose the land type before other actions",
)

register_choice(
    "mana_payment",
    resolve=lambda game, choice, r: game._resolve_mana_payment(choice, r["pay"]),
    default=lambda game, choice: game._default_mana_payment(choice),
    action="confirm_mana_payment",
    prompt_key="mana_payment",
    # "…unless its controller pays {X}" (Power Sink) is paid *during* the
    # counterspell's resolution, so the game genuinely waits on it — this used
    # to say so by being named in ``pass_priority`` instead, which is a second
    # place to state one fact and the reason every other prompt was left out of
    # it. Paying means tapping lands and activating mana abilities, so those two
    # answer the prompt as much as the confirm does; everything else waits.
    blocked_detail="pay for the spell on the stack before other actions",
    also_answers=("tap", "activate"),
)

register_choice(
    "player_choice",
    resolve=lambda game, choice, r: game._resolve_player_choice(choice, r.get("seat")),
    default=lambda game, choice: game._default_player_choice(choice),
    action="player_choice_confirm",
    prompt_key="player_choice",
    blocked_detail="choose a player for the resolving spell before other actions",
    # The steps behind this one in the same sentence read the answer - the pick
    # of "one of those spells" is narrowed by it, and the damage lands on the
    # seat it names - so the loop they are part of has to stop until it exists.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands. That is also what
    # keeps AI and headless play free of the suspension above.
    default_at_arm=True,
    # Who cast what this turn is public information (no CR 400.2 hidden zone is
    # involved), so a seatless viewer may see the question.
    spectator_visible=True,
)

register_choice(
    "cast_choice",
    resolve=lambda game, choice, r: game._resolve_cast_choice(choice, r.get("cast_index")),
    default=lambda game, choice: game._default_cast_choice(choice),
    action="cast_choice_confirm",
    prompt_key="cast_choice",
    blocked_detail="choose one of those spells before other actions",
    # Armed by the *answer* to the player choice above, and read by the damage
    # step behind it - the chain of decisions that stays one resolution.
    suspends=True,
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    "permanent_choice",
    resolve=lambda game, choice, r: game._resolve_permanent_choice(choice, r["permanent_id"]),
    default=lambda game, choice: game._default_permanent_choice(choice),
    action="permanent_choice_confirm",
    prompt_key="permanent_choice",
    blocked_detail="choose a permanent for the resolving spell before other actions",
    # The steps behind this one in the same sentence are what read the answer
    # (Enchantment Alteration's attach), so the loop they are part of has to
    # stop until it exists.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands. That is also what
    # keeps AI and headless play free of the suspension above.
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    "put_from_hand_choice",
    resolve=lambda game, choice, r: game._resolve_put_from_hand_choice(
        choice, r.get("hand_index")
    ),
    default=lambda game, choice: game._default_put_from_hand_choice(choice),
    action="put_from_hand_confirm",
    prompt_key="put_from_hand_choice",
    blocked_detail="choose a card to put onto the battlefield before other actions",
    # The round this is a step of counts the answers to decide whether it
    # happens again (Eureka), so the loop genuinely stops here.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands. That is also what
    # keeps AI and headless play free of the suspension above.
    default_at_arm=True,
    # Deliberately *not* spectator_visible, unlike the permanent pick above: the
    # candidates are cards in a hand (CR 400.2, a hidden zone), so rendering them
    # to a seatless viewer would publish the hand. Only the seat that owes the
    # decision is shown it.
)

register_choice(
    "choose_cards_in_hand",
    resolve=lambda game, choice, r: game._resolve_choose_cards_in_hand(
        choice, r.get("hand_indices")
    ),
    default=lambda game, choice: game._default_choose_cards_in_hand(choice),
    action="choose_cards_in_hand_confirm",
    prompt_key="choose_cards_in_hand",
    blocked_detail="choose the cards in your hand before other actions",
    blocks_every_seat=True,
    # The pick is what the next step of the same resolution repeats over, so
    # that step must not run before the answer exists.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands. That is also what
    # keeps AI and headless play free of the suspension above.
    default_at_arm=True,
    # Deliberately *not* spectator_visible, for ``put_from_hand_choice``'s
    # reason: the candidates are cards in a hand (CR 400.2, a hidden zone), so
    # rendering them to a seatless viewer would publish the hand.
)

register_choice(
    "kudzu_reattach",
    resolve=lambda game, choice, r: game._resolve_kudzu_reattach(choice, r["land_index"]),
    default=lambda game, choice: game._default_kudzu_reattach(choice),
    action="kudzu_reattach_confirm",
    prompt_key="kudzu_reattach",
    # Whether the controller is *asked* is the seat's interactivity, read here
    # rather than passed in. It used to be a ``defer_choice`` flag threaded from
    # ``tap_land_for_mana`` down through a name-keyed dispatcher, which is the
    # same question ``interactive_seats`` already answers for every other
    # prompt — and the web layer computed it a second way ("not ai" against this
    # table's "is human"). One answer, so a new seat kind needs no new argument.
    default_at_arm=True,
    blocked_detail="choose where Kudzu moves before other actions",
)

register_choice(
    "face_down_cast",
    resolve=lambda game, choice, r: game._resolve_face_down_cast(choice, r["hand_index"]),
    default=lambda game, choice: game._default_face_down_cast(choice),
    action="face_down_cast_confirm",
    prompt_key="face_down_cast",
    # Illusionary Mask's own comment: "the actual cast happens in
    # confirm_face_down_cast" — armed mid-resolution, so the game waits.
    blocked_detail="choose the face-down creature before other actions",
)

register_choice(
    "word_of_command",
    resolve=lambda game, choice, r: game._resolve_word_of_command(
        choice, r["hand_index"], r["defer_resolution"]
    ),
    default=lambda game, choice: game._default_word_of_command(choice),
    action="word_of_command_confirm",
    prompt_key="word_of_command",
    blocked_detail="choose the Word of Command card before other actions",
    # The caster's answer is recorded while the spell keeps waiting on the
    # stack, so the object outlives the decision it carries.
    is_open=lambda game, choice: "chosen_hand_index" not in choice.data,
)

register_choice(
    "opponent_damage",
    resolve=lambda game, choice, r: game._resolve_opponent_damage_choice(
        choice, r["target_seat"], r["target_permanent_index"]
    ),
    default=lambda game, choice: game._default_opponent_damage_choice(choice),
    action="opponent_damage_choose",
    prompt_key="opponent_damage_choice",
    blocked_detail="choose a target for the opponent-choice damage before other actions",
    default_at_arm=True,
)

register_choice(
    "name_and_strip",
    resolve=lambda game, choice, r: game._resolve_name_and_strip(choice, r["card_name"]),
    default=lambda game, choice: game._default_name_and_strip(choice),
    action="name_and_strip_confirm",
    prompt_key="name_and_strip",
    blocked_detail="name a card for the search before other actions",
)

register_choice(
    "name_then_reveal_top",
    resolve=lambda game, choice, r: game._resolve_name_then_reveal_top(
        choice, r["card_name"]
    ),
    default=lambda game, choice: game._default_name_then_reveal_top(choice),
    action="name_then_reveal_top_confirm",
    prompt_key="name_then_reveal_top",
    blocked_detail="name a card before other actions",
)

register_choice(
    "name_then_consult",
    resolve=lambda game, choice, r: game._resolve_name_then_consult(
        choice, r["card_name"]
    ),
    default=lambda game, choice: game._default_name_then_consult(choice),
    action="name_then_consult_confirm",
    prompt_key="name_then_consult",
    blocked_detail="name a card for the consultation before other actions",
)

register_choice(
    "name_and_random_reveal",
    resolve=lambda game, choice, r: game._resolve_name_and_random_reveal(
        choice, r["card_name"]
    ),
    default=lambda game, choice: game._default_name_and_random_reveal(choice),
    action="name_and_random_reveal_confirm",
    prompt_key="name_and_random_reveal",
    blocked_detail="name a card for the reveal before other actions",
)

register_choice(
    "enter_choice",
    resolve=lambda game, choice, r: game._resolve_enter_choice(
        choice, r.get("opponent_index"), r.get("mana_color"), r.get("card_name")
    ),
    # Black Vise / Jihad stamp their deterministic defaults on the permanent as
    # it enters, so a non-interactive controller has nothing left to apply.
    default=lambda game, choice: game.discard_pending_choice(choice),
    action="enter_choice_confirm",
    prompt_key="enter_choice",
    blocked_detail="choose an opponent (and color) for the entering permanent before other actions",
    default_at_arm=True,
)

register_choice(
    "entry_exile",
    resolve=lambda game, choice, r: game._resolve_entry_exile(choice, r.get("picks")),
    default=lambda game, choice: game._default_entry_exile(choice),
    action="entry_exile_confirm",
    prompt_key="entry_exile",
    blocked_detail="exile the entering permanent's cards before other actions",
    # The resolution that armed this has to finish, so a non-interactive seat
    # never queues it: the stated default is taken where the entry stands, which
    # is also what keeps AI and headless play from waiting on a prompt nobody
    # will answer.
    default_at_arm=True,
    # A graveyard is a public zone (CR 400.2), so there is nothing here a
    # seatless viewer may not already see - unlike `put_from_hand_choice` and
    # `choose_cards_in_hand`, whose candidates would publish a hand.
    spectator_visible=True,
)

register_choice(
    "body_choice",
    resolve=lambda game, choice, r: game._resolve_body_choice(choice, r["option_index"]),
    # Primal Clay's first printed body is applied as it enters, so the default
    # is already in place; the prompt only offers to replace it.
    default=lambda game, choice: game.discard_pending_choice(choice),
    action="body_choice_confirm",
    prompt_key="body_choice",
    blocked_detail="choose the entering creature's body before other actions",
    default_at_arm=True,
)

register_choice(
    "mode_choice",
    resolve=lambda game, choice, r: game._resolve_mode_choice(
        choice, r["mode_index"], r.get("target"),
    ),
    default=lambda game, choice: game._default_mode_choice(choice),
    action="mode_choice_confirm",
    prompt_key="mode_choice",
    blocked_detail="choose a mode for the triggered ability before other actions",
    default_at_arm=True,
    spectator_visible=True,
    # "**For each of those cards**, pay 4 life or put the card on top of your
    # library." (Sylvan Library.) A choice reached inside a repetition, whose
    # branch acts on the object the repetition is *currently* on — so the next
    # iteration must not start before this answer is applied. Without it both
    # iterations armed at once and both answers were applied against whichever
    # card the loop had ended on.
    suspends=True,
)

register_choice(
    "loyalty_recipient",
    resolve=lambda game, choice, r: game._resolve_loyalty_recipient(
        choice, r["permanent_id"]
    ),
    default=lambda game, choice: game._default_loyalty_recipient(choice),
    action="loyalty_recipient_confirm",
    prompt_key="loyalty_recipient",
    blocked_detail="choose which planeswalker gets the loyalty counter before other actions",
    # The trigger that armed this has to finish resolving, so a non-interactive
    # seat never queues it — it takes the stated default where it stands.
    default_at_arm=True,
    # Nothing later in the same resolution reads the answer: the counter is the
    # last thing the ability does.
)

register_choice(
    "least_power_choice",
    resolve=lambda game, choice, r: game._resolve_least_power_choice(
        choice, r["target_seat"], r["target_permanent_index"]
    ),
    default=lambda game, choice: game._default_least_power_choice(choice),
    action="least_power_choice_confirm",
    prompt_key="least_power_choice",
    blocked_detail="choose which creature tied for least power is destroyed before other actions",
    default_at_arm=True,
)

# Replacement effects that suspend on a decision (CR 614) keep their own queue —
# see engine/replacement_choices.py — but they are prompts like any other, so
# they are described here too and the web layer treats both queues alike.
# ``ReplacementChoice`` carries the same kind / player_index / data attributes,
# which is why no adapter is needed.

def _resolve_replacement(game, choice, response) -> bool:
    return bool(game.resolve_replacement_choice(
        choice.player_index, response["option"], kind=choice.kind
    ))


def _default_replacement(game, choice) -> None:
    game.resolve_replacement_choice(
        choice.player_index, choice.default_option, kind=choice.kind
    )


register_choice(
    "commander_zone_change",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="commander_zone_change_confirm",
    prompt_key="commander_zone_change",
    blocked_detail="choose whether your commander goes to the command zone before other actions",
    default_at_arm=True,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "leng_discard",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="leng_discard_confirm",
    prompt_key="leng_discard",
    blocked_detail="choose where the discarded card goes (Library of Leng) before other actions",
    default_at_arm=True,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "optional_damage_redirect",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="optional_damage_redirect_confirm",
    prompt_key="optional_damage_redirect",
    blocked_detail=(
        "choose whether you take the damage headed for that creature before "
        "other actions"
    ),
    # The damage event that armed this is over — it was consumed so that both
    # answers could run through one resolver — so nothing is waiting on the
    # answer to carry on. A non-interactive seat takes the stated policy where
    # it stands, exactly as the three offers above do.
    default_at_arm=True,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "lamp_draw",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="lamp_draw_confirm",
    prompt_key="lamp_draw",
    blocked_detail="choose a card for Aladdin's Lamp before other actions",
    default_at_arm=True,
)

register_choice(
    "outside_game_draw",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="outside_game_draw_confirm",
    prompt_key="outside_game_draw",
    blocked_detail="choose a card from outside the game before other actions",
    default_at_arm=True,
)
