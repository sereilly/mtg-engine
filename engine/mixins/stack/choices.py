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
from ...grammar.lowering._events import EVENT_SUBJECT_PLAYER
from ...grammar.phrases import BASIC_LAND_WORDS
from ...land_types import CHOSEN_LAND_TYPES, change_land_type
from ...linked_exile import link_exiled_card, shuffle_linked_pile
from ...models import CardDefinition, Permanent
from ...oracle_types import (DISCARDED_BY_SEAT, DREW_BY_SEAT, EXILED_THIS_WAY,
                             EXILED_THIS_WAY_OBJECTS)
from ...grammar.lowering._events import PUT_FROM_HAND_PERMANENTS
from ... import land_mana_swaps
from ...pending_choices import (CHOICE_SPECS, PendingChoice,
                                optional_pay_options, register_choice,
                                spec_for)
from ...replacement_choices import pending_choices_for
from ...resumption import resume_after_answer, run_resumable
from ...mana_payment import (generic_cost, mana_cost_label, plan_payment,
                            untapped_mana_lands)
from ...oracle_types import SEARCHED_PERMANENTS
from ...search_filters import landing_seat, search_matches, searched_seat
from ...handlers.zones import FORGOTTEN_PICKS
from ...oracle_types import OracleInstruction
from ...subject_filters import subject_matches


def _entry_choice_option_allowed(choice: PendingChoice, answer: str) -> bool:
    """Whether *answer* is one of the options the entering permanent's own
    sentence printed (CR 614.1c).

    "As this enchantment enters, choose **black or red**" (Mangara's Equity),
    "…choose **Island or Swamp**" (Roots of Life). Most entry choices name a
    *catalog* and are bounded by it; these name their options outright, and the
    list travels on the choice so the picker offers exactly what this refuses
    to go outside (idiom 9).

    An arming with no list is unbounded by anything but its catalog, which is
    every other shape of this prompt — so an absent key is a pass rather than a
    refusal, and the six older armings are untouched.

    A free function rather than a method for the reason the two call sites give:
    both branches of ``_resolve_enter_choice`` ask it about the same choice, and
    it needs nothing off the game.
    """
    options = choice.data.get("entry_choice_options")
    if not options:
        return True
    return str(answer).strip().lower() in {
        str(option).strip().lower() for option in options
    }


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
        if not search_matches(
            card, choice.data, game=self, owner=choice.player_index
        ):
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
            # "…put that card onto the battlefield, then shuffle. **That
            # Dragon** gains haste until end of turn. Exile **it** at the
            # beginning of the next end step." (Zirilan of the Claw.) The
            # sentences behind a search name the permanent it put down, and
            # this is the only moment anything can say which one that is: the
            # search suspends on a prompt, so by the time the rest of the
            # resolution runs the card is one permanent among many.
            #
            # Written to the resolution's scratchpad under the key
            # ``lowering/_records._PRODUCES`` declares for this kind, which
            # is the same channel a reanimation already uses — one record
            # shape, so a sentence reading "that creature" cannot care which
            # step put the permanent there.
            record = choice.data.get("record")
            if record is not None:
                record.setdefault(SEARCHED_PERMANENTS, [])
                record[SEARCHED_PERMANENTS].append(found.permanent_id)
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
        elif destination == "library_top":
            # "…then shuffle and put that card on top." (Enlightened Tutor,
            # Mystical Tutor, Worldly Tutor.) The **order** is the effect: the
            # library is shuffled first and the find placed after, so it is on
            # top rather than somewhere random. That is why this branch shuffles
            # itself and returns rather than falling through to the shared
            # shuffle below — reaching that one would put the card on top and
            # then shuffle it back in, which is the card doing nothing.
            if zone == "library":
                random.shuffle(caster.library)
            self.put_card_into_library(caster, card, "top")
            self.log.append(
                f"{caster.name} searched {zone} and put {card.name} "
                "on top of their library"
            )
            self._record_search_reveal(choice)
            self.discard_pending_choice(choice)
            return True
        elif destination == "exile":
            # CR 400.3: the card goes to its owner's exile, and its owner is the
            # player whose library it came out of — which is `caster` here, the
            # *searched* seat rather than the searching one.
            caster.exile.append(card)
            self._record_search_exile(choice.data, card)
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
            if not search_matches(
                card, working, game=self, owner=choice.player_index
            ):
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
            # "…put those cards on top **in any order**" (Goblin Recruiter):
            # the finder named them in the order they want, and each placement
            # goes *on top* of the last — so the list is walked backwards and
            # the first card named ends up first from the top. Every other
            # destination is order-blind, which is why this is one `reversed`
            # rather than a branch.
            ordered = (
                list(reversed(cards)) if slots[0][0] == "library_top" else cards
            )
            for card in ordered:
                destination, tapped = slots[0]
                self._place_found_card(landing, card, destination, tapped, data)
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
            # And the resolution's scratchpad, for the same reason: a find that
            # is about to be *exiled* has to be written down where "you may play
            # that card" reads it, and this prompt is where the exile happens
            # once the slots differ. Absent on every search that records
            # nothing, which is what `_record_search_exile` answers to.
            record=data.get("record"),
        )

    def _record_search_exile(self, data: dict, card) -> None:
        """Write down a card this search **exiled**, for the sentence behind it.

        "…and exile it. … Until the beginning of your next upkeep, you may play
        that card." (Grinning Totem.) The permission names the card the search
        put in exile, and nothing else can say which one that is: the zone holds
        whatever else has gone there, and two copies of a card in a deck are the
        same immutable object, so a name match would find the wrong one.

        Under the one key every "cards exiled this way" in this engine reads
        (`lowering/_records._PRODUCES`), so a sentence saying it needs no reader
        of its own — and only the *exile* destination writes it, because a
        search that put its find in a hand exiled nothing.
        """
        record = data.get("record")
        if record is None:
            return
        record.setdefault("exiled_cards", []).append(card)

    def _place_found_card(
        self, seat: int, card, destination: str, tapped: bool, data: dict | None = None
    ) -> None:
        """One found card landing where the print sent it.

        *seat* is whose zone receives it, which is not always the seat that
        chose — "Search target player's library for three cards and exile
        them" (Jester's Cap) puts them in that player's exile, because CR 400.3
        sends an object to its **owner's** zone and the owner is the player
        whose library it came out of.

        *data* is the prompt's own dict, carried only so an exile can be
        recorded through the same seam the single-find path uses; a caller with
        nothing to record passes none.
        """
        caster = self.players[seat]
        if destination == "battlefield":
            from ...models import Permanent as _Permanent

            self._put_permanent_onto_battlefield(
                seat, _Permanent(card=card, tapped=tapped), None
            )
        elif destination == "exile":
            caster.exile.append(card)
            if data is not None:
                self._record_search_exile(data, card)
        elif destination == "library_top":
            # "…then shuffle and put those cards on top in any order."
            # (Goblin Recruiter.) The counted twin of the single-find branch in
            # `_resolve_search_library`, and it had no branch here at all — a
            # counted search sent to the top of a library fell through to the
            # `else` and put every find in the finder's **hand**, which is a
            # different card. The shuffle already happened, up in the picks
            # resolver, so a card placed here stays on top.
            self.put_card_into_library(caster, card, "top")
        else:
            self.put_card_into_hand(caster, card)
        where = (
            "onto the battlefield tapped" if destination == "battlefield" and tapped
            else "onto the battlefield" if destination == "battlefield"
            else "into exile" if destination == "exile"
            else "on top of their library" if destination == "library_top"
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
                landing, card, slot["destination"], bool(slot.get("tapped")),
                choice.data,
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

    def confirm_opponent_mode_choice(self, player_index: int, mode_index: int) -> bool:
        return self.resolve_pending_choice(
            "opponent_mode_choice", player_index, mode_index=mode_index
        )

    def _resolve_opponent_mode_choice(self, choice, mode_index) -> bool:
        """CR 700.2e: record the mode the *other* player picked onto the spell
        that is already on the stack.

        Recorded rather than performed. The spell has not resolved — the cast is
        what this decision is part of (CR 601.2b) — so the answer goes onto the
        stack item exactly where an ordinary caster's announcement would have
        put it, and resolution reads one field however the mode was chosen.
        """
        from ...game_types import ChosenMode

        item = choice.data.get("_item")
        labels = choice.data.get("labels") or []
        if item is None or not isinstance(mode_index, int):
            return False
        if not 0 <= mode_index < len(labels):
            return False
        item.chosen_mode_index = mode_index
        item.chosen_modes = (ChosenMode(index=mode_index),)
        # **Who chose** is a fact about this cast that nothing on a board can
        # answer, and the mode's own text refers back to it: "…each creature
        # **that player** controls", "…deals 4 damage to **that player**"
        # (Misfortune), "**That player** draws up to three cards" (Fatal Lore).
        # Frozen here, under the key every fire site freezes a seat under, so
        # `handlers/_common.frozen_that_player_seat` and the damage/draw
        # recipients read one answer rather than three. In a duel it happens to
        # equal the resolution's default opposing seat; with three players it
        # does not, which is why it is recorded rather than re-derived.
        item.trigger_context = {
            **(item.trigger_context or {}),
            EVENT_SUBJECT_PLAYER: choice.player_index,
        }
        self.discard_pending_choice(choice)
        self.log.append(
            f"{self.players[choice.player_index].name} chose "
            f"{labels[mode_index]!r} for {choice.data.get('card_name')}"
        )
        # CR 601.2c comes after 601.2b, and on these three cards the two steps
        # belong to different players — so the caster names the mode's targets
        # here, knowing at last which mode they are naming them for. Armed by
        # the answer, the way a chain of decisions inside one announcement is
        # (CR 601.2i: nobody has priority until the cast is finished, and both
        # prompts block every seat).
        self.arm_modal_mode_targets(item, choice.player_index)
        return True

    def _default_opponent_mode_choice(self, choice) -> None:
        """The first printed mode — a stated policy, not a valuation.

        The same answer ``mode_choice`` takes one screen down, and for its
        reason: an unanswered prompt inside an announcement would hold the cast
        open forever, and the seat that owes this one is by definition not the
        caster, so there is nobody else to ask.
        """
        if not self._resolve_opponent_mode_choice(choice, 0):
            self.discard_pending_choice(choice)

    def confirm_modal_mode_targets(self, player_index: int, permanent_ids: list) -> bool:
        """Name the targets of the mode an opponent chose. An empty list is a
        legal answer wherever the mode says "up to"."""
        return self.resolve_pending_choice(
            "modal_mode_targets", player_index, permanent_ids=permanent_ids
        )

    def _resolve_modal_mode_targets(self, choice, permanent_ids) -> bool:
        """Record the caster's targets onto the mode already on the stack.

        Checked against the list that was **offered**, never against the board:
        targets are chosen once, at announcement (CR 601.2c), so a permanent
        that became legal a moment later is not a legal answer — the rule
        ``_resolve_trigger_target`` states one screen up and for the same
        reason.

        Validated whole before anything is recorded, which is the two
        list-shaped pickers' rule: one bad id rejects the answer and leaves the
        prompt queued, so a malformed request cannot record half an
        announcement.
        """
        from dataclasses import replace as _replace

        item = choice.data.get("_item")
        if item is None or not item.chosen_modes:
            return False
        offered = {
            entry["permanent_id"]: entry
            for entry in (choice.data.get("targets") or ())
        }
        ids = [pid for pid in (permanent_ids or []) if isinstance(pid, int)]
        if len(ids) != len(permanent_ids or []) or len(set(ids)) != len(ids):
            return False
        if len(ids) > int(choice.data.get("max_targets", 1)):
            return False
        if any(pid not in offered for pid in ids):
            return False
        mode = item.chosen_modes[0]
        seats = {offered[pid]["seat"] for pid in ids}
        item.chosen_modes = (
            _replace(
                mode,
                target_permanent_id=list(ids),
                target_permanent_index=[offered[pid]["permanent_index"] for pid in ids],
                # One seat when every target sits on one battlefield, which is
                # every card in the pool that reaches here; several leaves the
                # mode's seat alone and the ids do the addressing, which is what
                # `StackItem` records about its own pair.
                target_player_index=(
                    next(iter(seats)) if len(seats) == 1 else mode.target_player_index
                ),
            ),
        )
        self.discard_pending_choice(choice)
        names = ", ".join(offered[pid]["name"] for pid in ids) if ids else "nothing"
        self.log.append(
            f"{self.players[choice.player_index].name} targets {names} "
            f"({choice.data.get('card_name')})"
        )
        return True

    def _default_modal_mode_targets(self, choice) -> None:
        """The offered candidates in board order, up to the printed ceiling.

        A stated policy rather than a valuation, and the same one
        ``_default_permanent_set_choice`` states: seed-determinism is what AI
        and headless play need, and a card that should choose cleverly wants a
        weight in ``engine/ai_valuation.py`` rather than a branch here. There is
        no *side* to decide — the printed noun phrase already narrowed the
        candidates to one player's board — so board order is the whole policy.
        """
        offered = list(choice.data.get("targets") or ())
        ceiling = int(choice.data.get("max_targets", 1))
        ids = [entry["permanent_id"] for entry in offered[:ceiling]]
        if not self._resolve_modal_mode_targets(choice, ids):
            self.discard_pending_choice(choice)

    def confirm_look_top_pick(self, player_index: int, keep_index: int) -> bool:
        return self.resolve_pending_choice(
            "look_top_pick", player_index, keep_index=keep_index
        )

    def look_top_pile_index(self, choice: PendingChoice) -> int:
        """Whose library this prompt is looking through.

        The seat answering, except where the card separates the two: "Look at
        the top X cards of **target opponent's** library. Exile one of those
        cards…" (Sealed Fate) puts every decision with the caster and the pile
        with the opponent. One reader for all three callers — what is offered,
        what an answer moves, and what the client draws — because a second
        would be free to show one library and empty another.
        """
        pile = choice.data.get("pile_index")
        if isinstance(pile, int) and 0 <= pile < len(self.players):
            return pile
        return choice.player_index

    def live_look_top_candidates(self, choice: PendingChoice) -> list[int]:
        """Which of the looked-at positions may be taken, in library order.

        Public because the prompt renderer is the second legitimate caller: what
        is offered and what an answer is checked against have to be one rule
        rather than two copies of it — the arrangement ``live_discard_candidates``
        already makes, and for the same reason.
        """
        from ...subject_filters import card_matches_any

        caster = self.players[self.look_top_pile_index(choice)]
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
        # The pile, which is the seat answering except on Sealed Fate — see
        # ``look_top_pile_index``. Everything below moves cards in *this*
        # player's library; who answers the prompt is ``choice.player_index``
        # and is used only to arm what comes next.
        caster = self.players[self.look_top_pile_index(choice)]
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
                    self.put_card_into_graveyard(caster, card)
                return
            # "…and **exile the rest**." (Browse.) The cards leave the game
            # rather than the library, which is why the same ability may be
            # activated again and again: the pile it looks at is a pile it has
            # already shortened. No order is asked for — exile is unordered
            # (CR 406.2 orders no zone but the library and the graveyard).
            if choice.data.get("rest_destination") == "exile":
                for card in rest:
                    caster.exile.append(card)
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
                    # Whose library is reordered, and **who orders it**: one
                    # seat everywhere but Sealed Fate, where the cards go back
                    # on the opponent's library in an order the caster chooses
                    # (CR 608.2 makes the spell's controller the actor).
                    self.arm_pending_choice(
                        "reorder_library", choice.player_index,
                        target_index=self.seat_index(caster),
                        top_count=len(rest), may_shuffle=False,
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
        # "Put **two** of them into your hand and the rest into your graveyard."
        # (Ancestral Memories.) A chain of one-card prompts rather than one
        # multi-select, for `_rearm_revealed_hand_pick`'s reason exactly: taking
        # a card renumbers the pile behind it, so a set of indices answered all
        # at once against the pile as it *was* addresses the wrong cards. Only
        # the taken card leaves; the rest stay where they are and the next
        # prompt looks at one fewer.
        remaining = int(choice.data.get("remaining", 1))
        if remaining > 1 and top_count > 1:
            caster.library.pop(keep_index)
            self.put_card_into_hand(caster, kept)
            self.discard_pending_choice(choice)
            self.log.append(
                f"{caster.name} put {kept.name} into their hand "
                f"({remaining - 1} more to take)"
            )
            # The keys are listed rather than the whole ``data`` dict passed
            # back, for `_rearm_revealed_hand_pick`'s reason: ``arm_pending_choice``
            # stamps its own bookkeeping into ``data`` (which stack object is
            # waiting, which seat caused the prompt), and handing those back as
            # arguments would re-arm the next link with a stale stamp.
            self.arm_pending_choice(
                "look_top_pick", choice.player_index,
                top_count=top_count - 1,
                amount=choice.data.get("amount", top_count - 1),
                card_name=choice.data.get("card_name", ""),
                filter=dict(choice.data.get("filter") or {}),
                filters=tuple(choice.data.get("filters") or ()),
                optional=bool(choice.data.get("optional")),
                rest_order=choice.data.get("rest_order", "any"),
                rest_destination=choice.data.get("rest_destination", "library_bottom"),
                pick_destination=choice.data.get("pick_destination", "hand"),
                remaining=remaining - 1,
            )
            return True
        del caster.library[:top_count]
        _bottom_the_rest([card for i, card in enumerate(looked) if i != keep_index])
        # "**Exile** one of those cards…" (Sealed Fate). The third printed
        # destination for the taken card, beside the hand and the library's
        # top, and the only one that takes it out of the game — read rather
        # than defaulted, exactly as the other two are.
        if choice.data.get("pick_destination") == "exile":
            caster.exile.append(kept)
            self.discard_pending_choice(choice)
            self.log.append(
                f"{self.players[choice.player_index].name} exiled a card from "
                f"{caster.name}'s library"
            )
            return True
        # Where the *kept* card goes, read the same way the rest's destination
        # is. "Puts one of them **back on top of their library**" (Ashnod's
        # Cylix) is this prompt's other printed answer: the card is not drawn,
        # it is the next card that player draws — a difference nothing else in
        # the sentence states and nobody can see until the draw step.
        if choice.data.get("pick_destination") == "library_top":
            self.put_card_into_library(caster, kept, position="top")
            self.discard_pending_choice(choice)
            self.log.append(
                f"{caster.name} put a card back on top of their library"
            )
            return True
        # "**If you don't**, put one of those cards on the bottom of your
        # library." (Preferred Selection.) The fourth printed destination for
        # the taken card, and the one that is a *cost* rather than a gain: the
        # card the player names is the one they are burying, and the rest of the
        # pile goes back where it was. Read rather than folded into the bottoming
        # of "the rest" — those are different cards and the sentence says which.
        if choice.data.get("pick_destination") == "library_bottom":
            self.put_card_into_library(caster, kept, position="bottom")
            self.discard_pending_choice(choice)
            self.log.append(
                f"{caster.name} put a card on the bottom of their library"
            )
            return True
        self.put_card_into_hand(caster, kept)
        self.discard_pending_choice(choice)
        self.log.append(
            f"{caster.name} put {kept.name} into their hand and the rest away"
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
        """The permanents this seat may still tap.

        Public because the prompt renderer is the second legitimate caller: the
        list offered and the list an answer is checked against have to be one
        rule rather than two copies of it.

        Through ``subject_matches`` rather than the pure matcher, which is the
        same correction ``_resolve_untap_up_to`` already carries: "untapped
        **white** creatures **they control**" narrows by a colour (layer 5) and
        by a seat, and the pure matcher — which has no game — would answer
        neither and offer a strictly larger set than the card names. The whole
        board rather than one seat's battlefield for the other half of the same
        reason: whose permanents may be tapped is what the printed filter says,
        not what this prompt assumes.
        """
        from ...subject_filters import subject_matches

        described = dict(choice.data.get("filter") or {})
        untapped_only = bool(choice.data.get("untapped_only"))
        observer = choice.data.get("observer")
        return [
            perm
            for perm in self.all_permanents()
            if subject_matches(
                self, perm, described,
                observer=observer if isinstance(observer, int) else choice.player_index,
            )
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
        self._record_tapped_this_way(choice, chosen)
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

    def _record_tapped_this_way(self, choice: PendingChoice, chosen: list) -> None:
        """Append what this seat tapped to the resolution's "tapped this way".

        Only where the arming handler passed a context, which is what says a
        later sentence of the same effect reads the answer. Siege Striker's
        pump is applied by this very resolver and passes none, so it records
        nothing — a producer declared for a kind that sometimes writes it would
        be a back-reference the lowering admits and the handler leaves at zero.

        Appended rather than assigned, and that is the whole of why this is a
        method: "Each player may tap …" arms one prompt per seat and the
        sentence behind it walks **every** creature every seat tapped. The
        per-object controller map is written beside the set, because that
        sentence asks whose each of them was and by then the board says only
        that they are tapped.
        """
        from ...oracle_types import (PER_OBJECT_SEAT_RECORDS, TAPPED_THIS_WAY,
                                     TAPPED_THIS_WAY_OBJECTS)

        context = choice.data.get("_context")
        if context is None:
            return
        context.results.setdefault(TAPPED_THIS_WAY_OBJECTS, []).extend(chosen)
        context.results[TAPPED_THIS_WAY] = len(
            context.results[TAPPED_THIS_WAY_OBJECTS]
        )
        seats = context.results.setdefault(PER_OBJECT_SEAT_RECORDS["controller"], {})
        for perm in chosen:
            seat = self.controller_index_of(perm)
            if seat is not None:
                seats[perm.permanent_id] = seat

    def _default_tap_any_number(self, choice: PendingChoice) -> None:
        """The stated policy: **tap everything eligible that is not attacking**.

        A decision rather than a fallback, and the argument is the same for
        both cards that arm this. Every creature tapped buys something the card
        prints — Siege Striker's boost, Raiding Party's two Plains apiece — and
        the only cost is losing a blocker, which a creature already attacking
        was not going to be. A card that should choose otherwise needs a
        valuation in ``engine/ai_valuation.py``, not a branch here.
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
        # "Search your library for **three** cards" (Foresight). A printed
        # ceiling, checked before anything moves like every other part of this
        # answer — CR 701.23b lets a search find fewer, so there is no floor,
        # but a fourth pick is a card the effect never named.
        maximum = choice.data.get("maximum")
        if maximum is not None and len(cleaned) > int(maximum):
            return False
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
        # "…exile them **in a face-down pile**, and shuffle that pile."
        # (Mangara's Tome.) The finds become one linked pile on the exiling
        # permanent (CR 610.3), which is what the artifact's second ability
        # names — without the record the cards are in exile and nothing on the
        # board can say which exile they are.
        #
        # ``ends_on`` is empty and that is the card: Mangara's Tome never gives
        # them back, so nothing ends the link and the pile outlives the
        # artifact in exile, exactly as Knowledge Vault's does.
        source = getattr(ctx, "source_permanent", None) if ctx is not None else None
        if choice.data.get("face_down_pile") and source is not None:
            for card in exiled:
                link_exiled_card(
                    source, card, choice.player_index, face_down=True
                )
            if choice.data.get("shuffle_pile"):
                # Through the module RNG the AI simulator seeds, like every
                # other shuffle here, so a seed still replays a run exactly.
                shuffle_linked_pile(source, random.shuffle)
        if ctx is not None:
            ctx.results["exiled_cards"] = exiled
        self.discard_pending_choice(choice)
        self.log.append(
            f"{caster.name} searched {' and '.join(zones)} and exiled "
            + (", ".join(card.name for card in exiled) if exiled else "nothing")
        )
        return True

    def _default_search_exile(self, choice: PendingChoice) -> None:
        """A non-interactive seat takes everything that matches: "any number"
        is a may per card, and the cards come back castable, so the maximum is
        the only default that never leaves value on the table.

        Where a ceiling is printed the default takes that many — the same
        "as much as the card allows" reading, bounded. Without the trim the
        picks would be refused whole and the seat would take *nothing*, which
        is the opposite default."""
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
        maximum = choice.data.get("maximum")
        if maximum is not None:
            picks = picks[: int(maximum)]
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
        # Whose library, which is not always the chooser's: "look at the top
        # card of **defending player's** library. You may put that card on the
        # bottom of that player's library" (Coral Fighters) is this same
        # decision over somebody else's pile. Absent means the chooser's, which
        # is every scry (CR 701.22a is about your own library) and every payload
        # written before the key existed.
        owner = self.players[choice.data.get("library_index", choice.player_index)]
        top_count = choice.data["top_count"]
        if sorted(card_order) != list(range(top_count)):
            return False
        if not 0 <= bottom_count <= top_count:
            return False
        looked = owner.library[:top_count]
        rest = owner.library[top_count:]
        kept = [looked[i] for i in card_order[: top_count - bottom_count]]
        bottomed = [looked[i] for i in card_order[top_count - bottom_count :]]
        # The bottomed cards go under everything that was already below the
        # looked-at ones, which is why `rest` sits between the two slices.
        owner.library = kept + rest + bottomed
        self.log.append(
            f"{self.players[choice.player_index].name} looked at the top "
            f"{top_count} of {owner.name}'s library ({bottom_count} to the bottom)"
        )
        self.discard_pending_choice(choice)
        return True

    def _default_scry(self, choice: PendingChoice) -> None:
        from ...ai_policy import choose_scry_arrangement

        card_order, bottom_count = choose_scry_arrangement(
            self, choice.player_index, choice.data["top_count"],
            library_index=choice.data.get("library_index"),
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
        if fate == "library_top":
            # "Put that card on top of that player's library." (Painful
            # Memories.) Both seams, and both for the reason they exist: a hand
            # holds the *same object* for every copy of a card, so the removal
            # goes through `take_card_from_hand` or it deletes every copy; and
            # CR 903.9b can divert a card headed for a library, so the arrival
            # goes through `put_card_into_library`.
            victim = self.players[victim_index]
            if not 0 <= hand_index < len(victim.hand):
                return False
            card = victim.hand[hand_index]
            if not self.take_card_from_hand(victim, card):
                return False
            self.put_card_into_library(victim, card, position="top")
            self.log.append(
                f"{card.name} went on top of {victim.name}'s library"
            )
            return True
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

    def confirm_hand_to_library(
        self, player_index: int, hand_indices: list[int], to_bottom: bool = False
    ) -> bool:
        """Resolve a pending "put N cards from your hand on top of your library"
        (Brainstorm, Stunted Growth) with the player's chosen cards.

        The order of *hand_indices* is the order the card gives them ("in any
        order"): the first named ends up on top.

        *to_bottom* is the second half of Dream Cache's answer — "both on top of
        your library **or both on the bottom**". It is refused on every other
        card rather than ignored: a bottomed Brainstorm is a strictly different
        spell, and nothing on the board would show it.
        """
        return self.resolve_pending_choice(
            "hand_to_library", player_index,
            hand_indices=hand_indices, to_bottom=to_bottom,
        )

    def _resolve_hand_to_library(
        self, choice: PendingChoice, hand_indices: list[int],
        to_bottom: bool = False,
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
        # "…both on top of your library **or both on the bottom of your
        # library**" (Dream Cache). Which end is part of the answer, and only
        # where the card offers it: a bottoming answer on Brainstorm is refused
        # rather than ignored, because ignoring it would put the cards on top
        # while the client believed it had bottomed them.
        offers_either_end = choice.data.get("destination") == "either_end"
        if to_bottom and not offers_either_end:
            return False
        position = "bottom" if to_bottom else "top"
        player = self.players[choice.player_index]
        cards = [hand[index] for index in chosen]
        # On the bottom the printed order is the order they are named, because
        # the first named goes down first; on top it is reversed, so the first
        # named ends up on top. Both are the same sentence read from the
        # library's own end.
        for card in (cards if position == "bottom" else reversed(cards)):
            if self.take_card_from_hand(player, card):
                self.put_card_into_library(player, card, position=position)
        # "**Shuffle** a card from your hand into your library."
        # (Lat-Nam's Legacy.) CR 701.19 makes the shuffle part of the move
        # rather than a rider on it, so it happens here rather than as a step
        # after — and where in the library the cards were put stops meaning
        # anything, which is why the two sentences can share one prompt.
        #
        # Through the module-level RNG every other shuffle in this engine uses,
        # so a seeded run stays reproducible.
        if choice.data.get("shuffle"):
            import random

            random.shuffle(player.library)
            self.log.append(
                f"{player.name} shuffled {len(cards)} card(s) into their library"
            )
        else:
            self.log.append(
                f"{player.name} put {len(cards)} card(s) on the {position} of "
                f"their library"
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
        """CR 609.3's choice, made: the land's type is recorded now.

        Two armings reach here. Phantasmal Terrain's names the land by its
        owner's seat and its battlefield slot, and keys the contribution on the
        **Aura**, so the change ends when the Aura does. Jinx's names it by
        ``permanent_id`` and keys the contribution on a duration label, because
        an instant has no permanent for the change to hang on and the cleanup
        step is what ends it. Which land and which source are therefore both
        read off the choice rather than assumed — the Aura's spelling is kept
        exactly as it was so its behaviour does not move.
        """
        land_type = str(land_type or "").strip().lower()
        if land_type not in self._BASIC_LAND_TYPES:
            return False
        permanent_id = choice.data.get("land_permanent_id")
        if permanent_id is not None:
            # An id, not a slot: anything leaving the battlefield renumbers
            # every later index, and this answer arrives after the handler that
            # armed it has returned (ROADMAP idiom 11). A land that has left
            # resolves to None, which is a fizzle and not a fall back to
            # whichever permanent inherited the slot.
            land = self.permanent_by_id(permanent_id)
        else:
            owner = self.players[choice.data["land_owner_index"]]
            idx = choice.data["land_index"]
            land = (
                owner.battlefield[idx]
                if 0 <= idx < len(owner.battlefield) else None
            )
        if land is not None:
            # Keyed on the Aura, so the change ends when the Aura does — and
            # ends only its own contribution. Jinx passes its own label instead.
            change_land_type(
                land, land_type,
                source=choice.data.get("land_type_source", choice.data.get("_aura")),
                label=choice.data["card_name"],
            )
            self.log.append(
                f"{choice.data['card_name']}: "
                + (
                    "enchanted land" if permanent_id is None
                    else land.card.name
                )
                + f" becomes a {land_type.title()}"
            )
        self.discard_pending_choice(choice)
        return True

    # -- "You may draw up to N cards" ----------------------------------------

    def confirm_draw_up_to(self, player_index: int, number: int) -> bool:
        """Answer "you may draw up to N cards" with how many (Truce)."""
        return self.resolve_pending_choice(
            "draw_up_to", player_index, number=number
        )

    def _resolve_draw_up_to(self, choice: PendingChoice, number) -> bool:
        """Draw *number* cards for the seat that was offered up to N.

        Out of range is a **rejection**, not a clamp, exactly as it is for
        ``number_choice``: the prompt names the ceiling the card prints, and
        repairing an answer silently would let a client ask for four cards off a
        card that offers two and be told it worked.

        The draw goes through ``_draw_with_replacements`` like every other draw
        in the engine — a ceiling is not a reason to skip CR 614 — and what is
        recorded is what was actually drawn, which is what the sentence behind
        it counts.
        """
        try:
            value = int(number)
        except (TypeError, ValueError):
            return False
        ceiling = int(choice.data.get("amount", 0))
        if not (0 <= value <= ceiling):
            return False
        player = self.players[choice.player_index]
        drawn = self._draw_with_replacements(player, value) if value else 0
        if value:
            self.log.append(f"{player.name} drew {drawn} card(s)")
        else:
            self.log.append(f"{player.name} drew no cards")
        results = choice.data.get("_results")
        if results is not None:
            # "**For each card less than two** a player draws this way…"
            # (Truce.) What was drawn, per seat, under the key the sentence
            # behind this one reads. Written even for a seat that drew none —
            # a shortfall is a number for every player, and a seat the record
            # never mentions has to read as zero rather than as a missing key.
            by_seat = results.setdefault(DREW_BY_SEAT, {})
            by_seat[choice.player_index] = drawn
        self.discard_pending_choice(choice)
        return True

    def _default_draw_up_to(self, choice: PendingChoice) -> bool:
        """The stated policy for an "up to N": take the maximum (a free draw is
        a gift), **capped by the library**.

        The cap is not a valuation, it is the same rule
        ``default_sacrifice_pick`` states one prompt over — a default never
        picks the answer that loses the game. CR 704.5b makes drawing from an
        empty library a loss at the next state-based check, so "take the
        maximum" over a two-card library is a seat choosing to die for a card
        it was offered the choice of declining.
        """
        player = self.players[choice.player_index]
        return self._resolve_draw_up_to(
            choice, min(int(choice.data.get("amount", 0)), len(player.library))
        )

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

    # -- "Each player may bid life for control of ..." -----------------------

    def begin_life_auction(
        self, *, card_name: str, permanent_id: int, opening_bidder: int,
        starting_bid: int, order: list[int],
    ) -> None:
        """Open Illicit Auction's round of offers.

        The whole auction is a **chain of prompts**, not a loop inside a
        handler, and that is what makes it work at all: a bid is a decision one
        seat owes, and the only way this engine holds a resolution open across a
        decision is the pending-choice queue (CR 608.2, CR 117.3b). The spell
        stays on the stack until the last offer is answered, because
        ``arm_pending_choice`` stamps the object each prompt belongs to and
        ``_release_stack_item`` will not pop it while one is queued.

        *order* is CR 101.4's turn order, computed once by the handler and
        carried unchanged from prompt to prompt -- the round-robin only ever
        rotates it, so who bids after whom cannot change halfway through.
        """
        self._offer_next_bid({
            "card_name": card_name,
            "permanent_id": int(permanent_id),
            "high_bid": int(starting_bid),
            "high_bidder": int(opening_bidder),
            "order": [int(seat) for seat in order],
            "to_ask": self._bidders_after(order, opening_bidder),
        })

    @staticmethod
    def _bidders_after(order, high_bidder: int) -> list[int]:
        """Everyone who still has to be asked before the high bid stands.

        *order* read as a cycle from the seat after *high_bidder*, with the high
        bidder himself left out: "each player may **top** the high bid" is an
        offer to beat somebody else's number, and nobody tops their own. Rebuilt
        from scratch after every raise, which is exactly what "the bidding ends
        if the high bid stands" means -- a raise puts everyone else back in.
        """
        seats = [int(seat) for seat in order]
        if high_bidder not in seats:
            return seats
        start = seats.index(high_bidder)
        return [seats[(start + offset) % len(seats)] for offset in range(1, len(seats))]

    def _offer_next_bid(self, data: dict) -> None:
        """Ask the next seat in the round, or settle the auction.

        The one place the round advances, so a pass, a raise and the opening all
        reach the same three lines. A seat that has left the game since the
        round began is skipped rather than asked (CR 800.4a).
        """
        to_ask = [int(seat) for seat in data.get("to_ask") or ()]
        while to_ask:
            seat = to_ask[0]
            if not (0 <= seat < len(self.players)) or self.players[seat].lost:
                to_ask = to_ask[1:]
                continue
            self.arm_pending_choice(
                "bid_life", seat, **{**data, "to_ask": to_ask}
            )
            return
        self._settle_life_auction(data)

    def confirm_bid_life(self, player_index: int, number: int | None = None) -> bool:
        """Answer the auction with a bid, or with ``None`` to pass."""
        return self.resolve_pending_choice("bid_life", player_index, number=number)

    def _resolve_bid_life(self, choice: PendingChoice, number) -> bool:
        """Record one seat's answer and move the round on.

        ``None`` is a pass -- the printed "**may**". Anything else has to *top*
        the high bid, and a number that does not is a **rejection** rather than
        a clamp, for ``_resolve_number_choice``'s reason one prompt over: the
        offer names what a legal answer is, and repairing one silently would let
        a client bid 2 against a standing 5 and be told it worked.

        No ceiling. The card prints none, and CR 118.3's "a player can't pay a
        cost without the resources" does not apply -- the winner **loses** life
        rather than paying it, so bidding more than a life total is legal and
        simply fatal. The prompt offers the survivable bids; the rule is here.
        """
        data = dict(choice.data)
        seat = choice.player_index
        high_bid = int(data.get("high_bid", 0))
        player = self.players[seat]
        if number is None:
            self.log.append(f"{data.get('card_name')}: {player.name} passes")
            data["to_ask"] = [
                int(other) for other in (data.get("to_ask") or ()) if int(other) != seat
            ]
        else:
            try:
                value = int(number)
            except (TypeError, ValueError):
                return False
            if value <= high_bid:
                return False
            data["high_bid"] = value
            data["high_bidder"] = seat
            data["to_ask"] = self._bidders_after(data.get("order") or (), seat)
            self.log.append(
                f"{data.get('card_name')}: {player.name} bids {value} life"
            )
        self.discard_pending_choice(choice)
        self._offer_next_bid(data)
        return True

    def _default_bid_life(self, choice: PendingChoice) -> bool:
        """A seat nobody asks **passes**.

        "May" makes declining a real answer, and it is the only one a default
        can take honestly here: what a creature is worth in life is a valuation,
        and an automatic bid is a seat choosing to lose life -- at a high enough
        standing bid, choosing to lose the game -- for a judgement nobody made.
        The same reading ``_default_draw_up_to`` states from the other side: a
        default never picks the answer that loses the game.
        """
        return self._resolve_bid_life(choice, None)

    def _settle_life_auction(self, data: dict) -> None:
        """The last printed sentence: the high bidder pays and takes it.

        Both halves happen here rather than in the handler, because until the
        last offer is answered nobody knows which seat either applies to.

        The life is **lost**, not paid (CR 118.3b's payment is the other thing),
        so it goes through the ordinary subtraction every other loss in this
        engine makes and the state-based check that follows the resolution can
        end the game on it.

        The control change is a CR 613 layer-2 contribution with no duration --
        the printed "(This effect lasts indefinitely.)" is CR 611.2a's default
        said out loud -- so nothing ever ends it and there is nothing to put
        back. A permanent that left while the bidding ran is simply gone
        (CR 400.7): the bid is still owed, which is the honest reading of a
        sentence whose two halves are joined by "and".
        """
        from ...control import change_control

        card_name = str(data.get("card_name") or "")
        winner_index = int(data.get("high_bidder", 0))
        amount = int(data.get("high_bid", 0))
        winner = self.players[winner_index]
        if amount:
            before = winner.life
            winner.life -= amount
            self.log.append(
                f"{card_name}: {winner.name} loses {amount} life "
                f"({before} -> {winner.life})"
            )
        permanent = self.permanent_by_id(int(data.get("permanent_id", -1)))
        if permanent is None:
            self.log.append(f"{card_name}: the creature is no longer there")
            return
        if self.cant_gain_control(permanent, winner):
            self.log.append(
                f"{card_name}: {permanent.card.name} can't change controllers"
            )
            return
        change_control(permanent, winner_index, source=card_name)
        self._sync_control()
        self.log.append(
            f"{card_name}: {winner.name} wins the bidding at {amount} and gains "
            f"control of {permanent.card.name}"
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

    def confirm_choose_card_name(self, player_index: int, card_name: str) -> bool:
        """Answer Foreshadow's "choose a card name"."""
        return self.resolve_pending_choice(
            "choose_card_name", player_index, card_name=card_name
        )

    def _resolve_choose_card_name(
        self, choice: PendingChoice, card_name: str
    ) -> bool:
        """Record the name for the sentences behind this step.

        CR 202.1 lets a player name any card, and this card prints no
        restriction, so no name is refused — including one no card in the game
        bears, which simply never matches. An empty name is the honest answer
        for a seat with nothing to go on and matches nothing either.
        """
        record = choice.data.get("record")
        if record is not None:
            record["chosen_card_name"] = (card_name or "").strip()
        self.discard_pending_choice(choice)
        self.log.append(
            f"{self.players[choice.player_index].name} named "
            + ((card_name or "").strip() or "nothing")
        )
        return True

    def _default_choose_card_name(self, choice: PendingChoice) -> None:
        self._resolve_choose_card_name(choice, choice.data.get("default_name", ""))

    def _default_name_then_reveal_top(self, choice: PendingChoice) -> None:
        if not self._resolve_name_then_reveal_top(
            choice, choice.data.get("default_name", "")
        ):
            self.discard_pending_choice(choice)

    # -- An opponent picking out of your graveyard, again for each payment ---

    def confirm_graveyard_pick_for_price(
        self, player_index: int, graveyard_index: int
    ) -> bool:
        """Answer Forgotten Lore's "target opponent chooses a card"."""
        return self.resolve_pending_choice(
            "graveyard_pick_for_price", player_index,
            graveyard_index=graveyard_index,
        )

    def _resolve_graveyard_pick_for_price(
        self, choice: PendingChoice, graveyard_index: int
    ) -> bool:
        """Record the pick, then offer its price to the *other* seat.

        Two seats answer alternately, which is why the loop is a chain of
        prompts and not a Python loop: the payment is the caster's decision and
        the pick is the opponent's, and neither is available while the other is
        being asked.

        The legal indices are re-checked against the record armed with the
        choice rather than trusted from the wire — a client offering the whole
        graveyard would otherwise let one card be chosen twice, which is the
        exclusion clause deleted.
        """
        if graveyard_index not in (choice.data.get("legal_indices") or []):
            return False
        owner = self.players[int(choice.data["owner_index"])]
        if not 0 <= graveyard_index < len(owner.graveyard):
            return False
        context = choice.data.get("_context")
        instruction = choice.data.get("_instruction")
        if context is None or instruction is None:
            return False
        chosen = owner.graveyard[graveyard_index]
        context.results.setdefault(FORGOTTEN_PICKS, []).append(chosen)
        self.discard_pending_choice(choice)
        self.log.append(
            f"{self.players[choice.player_index].name} chose {chosen.name} "
            f"({choice.data.get('card_name', '')})"
        )
        # "You may pay {G}. **If you do**, repeat this process." The offer goes
        # to the caster through the ordinary optional-cost prompt, with the same
        # instruction as its accept branch — so paying re-arms the pick with the
        # exclusion set the shared context has just grown, and declining runs
        # the sentence that ends the process.
        cost = dict(choice.data.get("cost") or {})
        self.arm_pending_choice(
            "optional_pay", self.players.index(context.caster),
            card_name=choice.data.get("card_name", ""),
            cost=cost,
            life=0,
            prompt=f"Pay {mana_cost_label(cost)} to repeat?",
            _on_accept=(instruction,),
            _on_decline=(
                OracleInstruction("finish_repeated_graveyard_pick", "", {}),
            ),
            _context=context,
        )
        return True

    def _default_graveyard_pick_for_price(self, choice: PendingChoice) -> None:
        """A non-interactive opponent gives up the cheapest card there is.

        A stated policy, like every other default here: mana value is the one
        ranking every card in the pool answers, and the chooser is the player
        who does *not* want the caster to get anything back.
        """
        legal = list(choice.data.get("legal_indices") or [])
        owner = self.players[int(choice.data["owner_index"])]
        if not legal:
            self.discard_pending_choice(choice)
            return
        legal.sort(key=lambda i: ((owner.graveyard[i].cmc or 0), i))
        if not self._resolve_graveyard_pick_for_price(choice, legal[0]):
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
                self.put_card_into_graveyard(target, zone.pop(index))
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
        land_types: "tuple[str, str] | list[str] | None" = None,
        creature_type: str | None = None,
        land_type: str | None = None,
    ) -> bool:
        """Resolve a pending "as this enters, choose an opponent [and a color]"
        prompt (Black Vise / Jihad), overwriting the provisional defaults
        stamped on the permanent at ETB."""
        return self.resolve_pending_choice(
            "enter_choice", player_index, opponent_index=opponent_index,
            mana_color=mana_color, card_name=card_name, land_types=land_types,
            creature_type=creature_type, land_type=land_type,
        )

    def _resolve_enter_choice(
        self, choice: PendingChoice, opponent_index: int | None = None,
        mana_color: str | None = None, card_name: str | None = None,
        land_types: "tuple[str, str] | list[str] | None" = None,
        creature_type: str | None = None,
        land_type: str | None = None,
    ) -> bool:
        player_index = choice.player_index
        # "…choose **a creature type**." (An-Zerrin Ruins.) A fifth shape of
        # this one prompt and the fourth that names no seat, so it answers and
        # returns rather than falling through to the opponent check.
        #
        # CR 205.3m: the answer must be a creature type — checked against the
        # same catalog the picker offers, so the two cannot disagree (idiom 9)
        # — and anything else is refused rather than repaired, because quietly
        # keeping the default would tell the player they had chosen something
        # they had not. An empty answer keeps the default, which is a choice
        # already recorded rather than none at all.
        # "…choose **a land type**." (Shimmer.) The sixth shape of this one
        # prompt and the fifth that names no seat, so it answers and returns
        # like the creature type below it.
        #
        # CR 205.3i: the answer must be a land type — and the *whole* catalog,
        # not the five basics: Shimmer may name Desert. Checked against the
        # same vocabulary the picker offers, so the two cannot disagree
        # (idiom 9), and anything else is refused rather than repaired. The
        # static beside the choice reads the record, so the board is
        # recomputed once it changes.
        if choice.data.get("needs_land_type"):
            from ...grammar.vocabulary import LAND_TYPES

            permanent = choice.data["permanent"]
            if land_type:
                word = str(land_type).strip().lower()
                # "…choose **Island or Swamp**." (Roots of Life.) The sentence
                # printed the offer, so the catalog is not what bounds the
                # answer — the two words are. Asked of the same list the picker
                # was handed (idiom 9), and refused rather than repaired: a
                # third land type here is a strictly better card.
                if not _entry_choice_option_allowed(choice, word):
                    return False
                if word not in LAND_TYPES:
                    return False
                if self.is_on_battlefield(permanent):
                    permanent.metadata["chosen_land_type"] = word
                    self.log.append(
                        f"{choice.data['card_name']}: chose {word}"
                    )
                    self._recalculate_lord_buffs()
            self.discard_pending_choice(choice)
            return True
        if choice.data.get("needs_creature_type"):
            from ...grammar.vocabulary import CREATURE_TYPES

            permanent = choice.data["permanent"]
            if creature_type:
                word = str(creature_type).strip().lower()
                if word not in CREATURE_TYPES:
                    return False
                if self.is_on_battlefield(permanent):
                    permanent.metadata["chosen_creature_type"] = word
                    self.log.append(
                        f"{choice.data['card_name']}: chose {word}"
                    )
            self.discard_pending_choice(choice)
            return True
        # "…choose **two basic land types**." (Illusionary Terrain.) A fourth
        # shape of this one prompt, and the third that names no seat — so it
        # answers and returns like the two below rather than falling through to
        # the opponent check. The pair is **ordered**: the static reads "the
        # first chosen type" and "the second chosen type", so a reversed answer
        # is a different, legal choice and not a normalization to apply.
        #
        # An answer naming anything but two distinct basic land types is
        # refused rather than repaired: quietly keeping the default would tell
        # the player they had chosen something they had not.
        if choice.data.get("needs_land_types"):
            permanent = choice.data["permanent"]
            if land_types is not None:
                pair = tuple(str(word).strip().lower() for word in land_types)
                if len(pair) != 2 or pair[0] == pair[1]:
                    return False
                if any(word not in BASIC_LAND_WORDS for word in pair):
                    return False
                if self.is_on_battlefield(permanent):
                    permanent.metadata[CHOSEN_LAND_TYPES] = pair
                    self.log.append(
                        f"{choice.data['card_name']}: chose {pair[0]} and {pair[1]}"
                    )
                    self._refresh_dynamic_creatures()
            self.discard_pending_choice(choice)
            return True
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
            from ...cast_restrictions import CHOSEN_CARD_NAMES

            permanent = choice.data["permanent"]
            # "…**you and an opponent each** choose a card name other than a
            # basic land card name." (Null Chamber.) Two seats answering into
            # one record, so the slot says whose answer this is — read as a set
            # by the ban, but written by index, because a prompt answering into
            # the wrong slot would swap the two players' choices.
            slot = choice.data.get("card_name_slot")
            if slot is not None:
                # ``BASIC_LAND_WORDS`` is the module-level import. A local one
                # here would shadow it for the *whole* function — Python binds
                # a name by function, not by block — and Illusionary Terrain's
                # branch above would raise reading it before this line ran.
                if card_name:
                    # The one restriction the sentence prints. CR 201.2 leaves
                    # the choice otherwise unbounded, so a name off the offered
                    # list is legal — this is the only answer that is not, and
                    # it is refused rather than repaired: quietly keeping the
                    # default would tell the player they had chosen something
                    # they had not.
                    if str(card_name).strip().lower() in BASIC_LAND_WORDS:
                        return False
                    names = list(
                        permanent.metadata.get(CHOSEN_CARD_NAMES) or ["", ""]
                    )
                    while len(names) <= int(slot):
                        names.append("")
                    names[int(slot)] = card_name
                    permanent.metadata[CHOSEN_CARD_NAMES] = names
                self.discard_pending_choice(choice)
                self.log.append(
                    f"{self.players[player_index].name} named "
                    f"{card_name or 'nothing'} for {choice.data['card_name']}"
                )
                return True
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
            # "…choose **black or red**." (Mangara's Equity.) The land-type
            # branch's rule one characteristic over: where the sentence printed
            # the offer, the five colours are not what bounds the answer.
            if color is not None and not _entry_choice_option_allowed(choice, color):
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
            # "…equal to 1 plus the number of creatures **the chosen player**
            # controls." (Lost Order of Jarkeld.) A characteristic-defining P/T
            # counting a board the answer just named, so the answer has to be
            # what it counts: the default stamped at entry was a different seat,
            # and the refresh that ran then measured that one. The land-types
            # branch above already recomputes for the same reason.
            self._refresh_dynamic_creatures()
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

    @classmethod
    def _mana_payment_costs(cls, data: dict) -> list[dict[str, int]]:
        """Every way the payer may cover this offer, in printed order —
        "…unless that spell's controller pays {B} **or {3}**" (Thrull Wizard).

        Through the same reader ``optional_pay`` uses, and stating the same
        policy CR 118.8 leaves to the engine: the alternatives are two ways to
        buy *one* consequence, so there is nothing for the payer to choose
        between and the first the board can cover is the one spent. A card whose
        alternatives bought different things would be the graded offer next
        door, which asks.
        """
        return [
            cls._mana_payment_cost(data),
            *(dict(alt) for alt in (data.get("cost_alternatives") or ())),
        ]

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
        self._resolve_mana_payment(
            choice, self._counter_payment_plan_any(controller, choice.data) is not None
        )

    def _counter_payment_plan_any(self, player, data: dict):
        """The first of the offer's printed costs *player* can cover, as a plan,
        or None when they can cover none of them."""
        for cost in self._mana_payment_costs(data):
            plan = self._counter_payment_plan(player, cost)
            if plan is not None:
                return cost, plan
        return None

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
        chosen = self._counter_payment_plan_any(controller, data) if pay else None
        cost, plan = chosen if chosen is not None else (cost, None)
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
        remainder_key: str | None = None,
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
            # "Put a -1/-1 counter on **the other**." (Retribution.) Which
            # scratchpad key the *unchosen* candidates are recorded under. It
            # rides the prompt because the answer is what decides them, and the
            # only place the answer and the offered set are both in hand is
            # where the answer is recorded.
            remainder_key=remainder_key,
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
        results = choice.data["_context"].results
        results[choice.data["result_key"]] = permanent_id
        remainder_key = choice.data.get("remainder_key")
        if remainder_key is not None:
            # "That player chooses and sacrifices one of those creatures. Put a
            # -1/-1 counter on **the other**." (Retribution.) The offered
            # candidates minus the one taken, by id — resolved here because
            # this is the only moment both the set and the answer exist, and by
            # the next step of the resolution one of them is in a graveyard.
            #
            # A bare id rather than a list, and refused above one: "the other"
            # is a phrase about a pair, and a two-member answer to it would be
            # read by the single-permanent channel as whichever came first.
            others = [
                perm.permanent_id
                for perm in (choice.data.get("_candidates") or ())
                if perm.permanent_id != permanent_id
            ]
            results[str(remainder_key)] = others[0] if len(others) == 1 else None
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

    # -- Several permanents chosen as an effect resolves ---------------------
    #
    # The plural of the pick above, and the same rule underneath it: the
    # candidates come from ``permanent_choice_candidates`` so the list offered
    # and the list an answer is checked against cannot drift.

    def arm_permanent_set_choice(
        self,
        player_index: int,
        *,
        card_name: str,
        prompt: str,
        result_key: str,
        payload: dict,
        context,
        candidates,
        up_to: int,
    ) -> PendingChoice | None:
        """Queue "choose up to *up_to* of these permanents" for *player_index*."""
        return self.arm_pending_choice(
            "permanent_set_choice", player_index,
            card_name=card_name,
            prompt=prompt,
            result_key=result_key,
            up_to=int(up_to),
            _payload=dict(payload),
            _context=context,
            _candidates=tuple(candidates),
        )

    def live_permanent_set_choices(self, choice: PendingChoice) -> list:
        """The armed candidates that are still legal answers."""
        from ...handlers.permanent_choices import permanent_choice_candidates

        return permanent_choice_candidates(
            self,
            choice.data.get("_payload") or {},
            choice.data["_context"],
            among=choice.data.get("_candidates") or (),
        )

    def confirm_permanent_set_choice(
        self, player_index: int, permanent_ids: list
    ) -> bool:
        """*permanent_ids* addresses the chosen permanents by stable id. An empty
        list is a legal answer — "up to two" includes none."""
        return self.resolve_pending_choice(
            "permanent_set_choice", player_index, permanent_ids=permanent_ids
        )

    def _resolve_permanent_set_choice(
        self, choice: PendingChoice, permanent_ids: list
    ) -> bool:
        """Validated whole before anything is recorded, matching the two
        list-shaped pickers beside it: one bad id rejects the answer and leaves
        the prompt queued, so a malformed request cannot record half a choice.

        The picks are **appended**. This prompt is armed once per iteration of a
        loop and once per seat inside it, and the sentence that reads the record
        asks about every answer at once ("chosen this way **by any player**").
        """
        ids = [pid for pid in (permanent_ids or []) if isinstance(pid, int)]
        if len(ids) != len(permanent_ids or []) or len(set(ids)) != len(ids):
            return False
        if len(ids) > int(choice.data.get("up_to", 1)):
            return False
        live = self.live_permanent_set_choices(choice)
        chosen = []
        for pid in ids:
            perm = self.permanent_by_id(pid)
            if perm is None or not any(perm is candidate for candidate in live):
                return False
            chosen.append(perm)
        results = choice.data["_context"].results
        results.setdefault(choice.data["result_key"], []).extend(chosen)
        card_name = choice.data.get("card_name", "Effect")
        names = ", ".join(perm.card.name for perm in chosen) if chosen else "nothing"
        self.log.append(
            f"{self.players[choice.player_index].name} chose {names} ({card_name})"
        )
        self.discard_pending_choice(choice)
        return True

    def _default_permanent_set_choice(self, choice: PendingChoice) -> None:
        """The stated policy: **the seat's own permanents, in board order, up to
        the ceiling — and nothing else, even when the ceiling is unspent.**

        Board order rather than a valuation, which is the singular pick's rule
        beside it and for its reason: seed-determinism is what AI and headless
        play need, and a card that should choose cleverly wants a weight in
        ``engine/ai_valuation.py`` rather than a branch here.

        Own-only is the half that is a *decision*, and it is deliberately not
        "own first, then others to fill". A sentence that lets a seat pick from
        any battlefield is a sentence where the pick is worth something to
        whoever is picking — Raiding Party's chosen Plains are the ones that
        survive — so a leftover pick spent on an opponent's permanent is a gift
        the card never asked anyone to make. Leaving the ceiling unspent is the
        neutral answer; taking it is a valuation this has no basis for.
        """
        limit = int(choice.data.get("up_to", 1))
        picks = [
            self.permanent_id_of(perm)
            for perm in self.live_permanent_set_choices(choice)
            if self.controls(choice.player_index, perm)
        ][:limit]
        chosen = [pid for pid in picks if pid is not None]
        if not self._resolve_permanent_set_choice(choice, chosen):
            self._resolve_permanent_set_choice(choice, [])

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

    # -- The new target of a spell being re-aimed (CR 115.7a) ----------------

    def arm_retarget_choice(
        self,
        player_index: int,
        *,
        card_name: str,
        prompt: str,
        result_key: str,
        options,
        context,
    ) -> PendingChoice | None:
        """Queue "choose the new target" for *player_index* (Deflection).

        Its own kind rather than ``player_choice`` because the candidates are
        **heterogeneous**: "Change the target of target spell with a single
        target" offers whatever that spell could legally have chosen, which for
        a Lightning Bolt is every creature *and* every face. A seat-shaped
        prompt cannot say "that Grizzly Bears", and one that could only say a
        seat would silently drop half the card.

        Answered by **position in the offered list**, the shape ``cast_choice``
        uses, because a target descriptor is not a JSON scalar and the list is
        the one thing both ends already agree on. Each option carries its
        ``permanent_id`` rather than a slot: the prompt suspends the resolution
        but the id is what survives a board that moved anyway (CR 400.7).
        """
        offered = [dict(option) for option in options]
        return self.arm_pending_choice(
            "retarget_choice", player_index,
            card_name=card_name,
            prompt=prompt,
            result_key=result_key,
            options=offered,
            names=[str(option.get("name", "")) for option in offered],
            _context=context,
        )

    def live_retarget_choices(self, choice: PendingChoice) -> list[int]:
        """The offered positions still legal to answer with (CR 800.4a).

        A face drops out when its player has left the game; an object drops out
        when it has left the battlefield. Both are re-asked here rather than
        remembered, because the whole reason this prompt exists is that the
        answer arrives later than the question.
        """
        live: list[int] = []
        for position, option in enumerate(choice.data.get("options") or ()):
            if option.get("kind") == "player":
                seat = option.get("seat")
                if isinstance(seat, int) and 0 <= seat < len(self.players) and not self.players[seat].lost:
                    live.append(position)
            elif self.permanent_by_id(option.get("permanent_id")) is not None:
                live.append(position)
        return live

    def _record_retarget_choice(self, choice: PendingChoice, value) -> None:
        choice.data["_context"].results[choice.data["result_key"]] = value
        self.discard_pending_choice(choice)

    def confirm_retarget_choice(self, player_index: int, target_index) -> bool:
        return self.resolve_pending_choice(
            "retarget_choice", player_index, target_index=target_index
        )

    def _resolve_retarget_choice(self, choice: PendingChoice, target_index) -> bool:
        live = self.live_retarget_choices(choice)
        if not live:
            # Everything the effect offered has gone. CR 115.7a: the original
            # target is then unchanged, which the step behind this reads off a
            # ``None`` rather than staying owed a prompt nobody can answer.
            self._record_retarget_choice(choice, None)
            return True
        if not isinstance(target_index, int) or target_index not in live:
            return False
        option = dict((choice.data.get("options") or ())[target_index])
        self._record_retarget_choice(choice, option)
        self.log.append(
            f"{choice.data.get('card_name', 'Effect')}: chose "
            f"{option.get('name', 'a new target')}"
        )
        return True

    def _default_retarget_choice(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** live candidate offered, in board
        order. Deterministic rather than clever, for ``_default_player_choice``'s
        reason."""
        live = self.live_retarget_choices(choice)
        if not live or not self._resolve_retarget_choice(choice, live[0]):
            self._record_retarget_choice(choice, None)

    # -- Whether a coin flip happens again, and at what stake ----------------

    def confirm_flip_again(self, player_index: int, accept: bool = True) -> bool:
        """Answer Game of Chaos's "…decides whether to flip again"."""
        return self.resolve_pending_choice(
            "flip_again", player_index, accept=accept
        )

    def _resolve_flip_again(self, choice: PendingChoice, accept: bool) -> bool:
        """Run the paragraph again, or stop.

        The next round is the *same* instruction with the next stake already on
        its payload, carried here when the offer was armed — so this does not
        have to know what the card doubles or who decides next, which is the
        handler's business and stays there.
        """
        again = choice.data.get("_again")
        context = choice.data.get("_context")
        self.discard_pending_choice(choice)
        player = self.players[choice.player_index]
        if not accept or again is None or context is None:
            self.log.append(
                f"{player.name} declined to flip again "
                f"({choice.data.get('card_name', 'an effect')})"
            )
            return True
        self._execute_oracle_instruction(again, context)
        return True

    def _default_flip_again(self, choice: PendingChoice) -> None:
        """The stated policy: **stop**.

        Not a valuation. The offer doubles the stake every round and the flip is
        even money, so there is no number a seat with no policy can be right
        about — and a default of "yes" is not a default, it is a game that never
        ends. A seat that should press its luck needs a weight in
        ``engine/ai_valuation.py``, not a branch here.
        """
        self._resolve_flip_again(choice, False)

    # -- A card exiled out of a hand -----------------------------------------

    def live_exile_from_hand_choices(self, choice: PendingChoice) -> list[int]:
        """The hand slots still eligible, from the engine's own rule.

        Re-run rather than stored, for ``live_put_from_hand_choices``' reason:
        the list the seat is offered and the list its answer is checked against
        have to be one list.
        """
        from ...handlers.zones import exile_from_hand_candidates

        return exile_from_hand_candidates(
            self, choice.data.get("_payload") or {}, self.players[choice.player_index]
        )

    def confirm_exile_from_hand_choice(self, player_index: int, hand_index) -> bool:
        """Answer the pending pick. ``hand_index`` of None declines, which is an
        answer only where the sentence made an offer: "You **may** exile a
        nonland card from your hand" (Ice Cauldron). The bare printing — "Exile
        a card from your hand face down" (Gustha's Scepter) — is mandatory and
        refuses it, because a decline there is an ability that resolves having
        moved nothing."""
        return self.resolve_pending_choice(
            "exile_from_hand_choice", player_index, hand_index=hand_index
        )

    def _resolve_exile_from_hand_choice(self, choice: PendingChoice, hand_index) -> bool:
        """Exile the chosen card, and record it for the sentence behind this one.

        Two records, both needed and both about the same card:

        * ``exiled_cards`` on the resolution's scratchpad is what "you may cast
          **that card**" reads (`_PRODUCES`);
        * the linked-exile entry on the artifact is what "the last card exiled
          with **this artifact**" reads, long after this resolution is over
          (CR 610.3) — and it lives on the permanent rather than on the game
          because the permanent is what the phrase names.
        """
        from ...linked_exile import link_exiled_card

        player = self.players[choice.player_index]
        live = self.live_exile_from_hand_choices(choice)
        name = choice.data.get("card_name", "Effect")
        payload = choice.data.get("_payload") or {}
        if hand_index is None:
            # Only an *offer* may be declined. True by default because the
            # offered printing is the one that shipped first; the mandatory
            # printing says so in its payload.
            if not payload.get("optional", True):
                return False
            self.log.append(f"{player.name} exiled no card ({name})")
            self.discard_pending_choice(choice)
            return True
        if hand_index not in live:
            return False
        card = player.hand[hand_index]
        # Through the hand seam: a deck repeats one immutable definition per
        # copy, so an identity filter over the hand would remove every copy
        # where this removes exactly one.
        self.take_card_from_hand(player, card)
        player.exile.append(card)
        source = choice.data.get("_source_permanent")
        if source is not None:
            # CR 406.3's rider travels on the *entry*, not on the card: two
            # copies of one card in a deck are the same ``CardDefinition``
            # object, so the record of the exiling is the only thing that can
            # say which one is hidden. The *look* permission that may follow it
            # ("You may look at it for as long as it remains exiled", Gustha's
            # Scepter) is a sentence of its own and writes its own key onto
            # this entry once this prompt has been answered.
            link_exiled_card(
                source, card, choice.player_index,
                face_down=bool(payload.get("face_down")),
            )
        context = choice.data.get("_context")
        if context is not None:
            context.results.setdefault("exiled_cards", []).append(card)
        self.log.append(f"{player.name} exiled {card.name} from their hand ({name})")
        self.discard_pending_choice(choice)
        return True

    def _default_exile_from_hand_choice(self, choice: PendingChoice) -> None:
        """The stated policy: **decline**.

        The opposite of the put-onto-the-battlefield pick beside it, and for the
        same kind of reason stated the other way round. That offer trades a card
        in hand for a permanent on the battlefield, which is more board; this
        one trades a card in hand for a card in exile plus a charge counter, and
        the permission to cast it is only worth anything to a seat that then
        spends the noted mana on it. A headless seat that took the offer would
        bury a card every time the artifact was activated.

        **A mandatory exile has no decline to take**, so the policy there is the
        one ``_default_discard`` states: the lowest-index eligible card. Which
        cards are eligible at all is the printed phrase's business and is read
        off the same list the interactive seat is offered, never a second copy.
        """
        if not (choice.data.get("_payload") or {}).get("optional", True):
            live = self.live_exile_from_hand_choices(choice)
            if live and self._resolve_exile_from_hand_choice(choice, live[0]):
                return
            # Nothing eligible: the offer was never made rather than declined,
            # which is the rule ``exile_chosen_card_from_hand`` states, and the
            # prompt has to come off the queue or the resolution never finishes.
            self.discard_pending_choice(choice)
            return
        self._resolve_exile_from_hand_choice(choice, None)

    # -- The two face-down piles (Phyrexian Portal) --------------------------

    def confirm_library_pile_split(self, player_index: int, first_pile) -> bool:
        """Answer the division. *first_pile* is the positions - into the ten
        cards as they were shown - that go into the first pile; everything else
        goes into the second. Either pile may be empty, which is a legal
        division and a real one: it forces the controller to choose between
        searching everything and searching nothing."""
        return self.resolve_pending_choice(
            "library_pile_split", player_index, first_pile=first_pile
        )

    def _resolve_library_pile_split(self, choice: PendingChoice, first_pile) -> bool:
        cards = list(choice.data.get("_cards") or ())
        positions = [int(i) for i in (first_pile or [])]
        if len(set(positions)) != len(positions):
            return False
        if any(not 0 <= i < len(cards) for i in positions):
            return False
        chosen = set(positions)
        piles = [
            [card for i, card in enumerate(cards) if i in chosen],
            [card for i, card in enumerate(cards) if i not in chosen],
        ]
        self.discard_pending_choice(choice)
        self.log.append(
            f"{self.players[choice.player_index].name} divided "
            f"{len(cards)} cards into piles of {len(piles[0])} and {len(piles[1])}"
        )
        # The controller's decision, armed by answering this one - and it is a
        # *different seat's*, which is the whole design of the card.
        self.arm_pending_choice(
            "pile_exile_choice", int(choice.data["owner_index"]),
            card_name=choice.data.get("card_name", ""),
            owner_index=int(choice.data["owner_index"]),
            _piles=piles,
            _source_permanent=choice.data.get("_source_permanent"),
        )
        return True

    def _default_library_pile_split(self, choice: PendingChoice) -> None:
        """The stated policy: **split as evenly as possible**, in the order the
        cards came off the library.

        Neutral rather than optimal, and deliberately so. The division is the
        one decision in this card that is genuinely adversarial - a divider who
        knows the pile can make both halves bad - and there is no valuation
        here that would not be a guess about what the *other* seat wants. An
        even split is the answer that neither hands the controller their pick
        nor denies it.
        """
        cards = list(choice.data.get("_cards") or ())
        half = len(cards) // 2
        if not self._resolve_library_pile_split(choice, list(range(half))):
            self.discard_pending_choice(choice)

    def confirm_pile_exile_choice(self, player_index: int, pile_index: int) -> bool:
        """Answer which of the two face-down piles is exiled (0 or 1). The
        other is the one searched."""
        return self.resolve_pending_choice(
            "pile_exile_choice", player_index, pile_index=pile_index
        )

    def _resolve_pile_exile_choice(self, choice: PendingChoice, pile_index) -> bool:
        """Exile the named pile face down, and hand the other to the search.

        Face down is not decoration: the piles were divided face down and this
        choice was made blind, so a pile that arrived in exile face up would
        tell every player at the table what the decision had cost. It goes on
        the linked-exile record for that record's own reason - two copies of
        one card in a deck are the same object, so the record of the exiling is
        the only thing that can say which one is hidden.
        """
        from ...linked_exile import link_exiled_card

        piles = list(choice.data.get("_piles") or ())
        if pile_index not in (0, 1) or len(piles) != 2:
            return False
        owner = self.players[int(choice.data["owner_index"])]
        exiled = piles[int(pile_index)]
        kept = piles[1 - int(pile_index)]
        source = choice.data.get("_source_permanent")
        for card in exiled:
            owner.exile.append(card)
            if source is not None:
                link_exiled_card(
                    source, card, int(choice.data["owner_index"]), face_down=True
                )
        self.discard_pending_choice(choice)
        self.log.append(
            f"{owner.name} exiled a face-down pile of {len(exiled)} card(s)"
        )
        self.arm_pending_choice(
            "pile_search", int(choice.data["owner_index"]),
            card_name=choice.data.get("card_name", ""),
            owner_index=int(choice.data["owner_index"]),
            _pile=list(kept),
        )
        return True

    def _default_pile_exile_choice(self, choice: PendingChoice) -> None:
        """The stated policy: **exile the smaller pile**, and on a tie the
        first.

        The only thing this seat knows about the piles is how many cards are in
        each - that is what "face down" means - and of the two facts available,
        keeping more cards to search through is the one that is never worse.
        """
        piles = list(choice.data.get("_piles") or ())
        if len(piles) != 2:
            self.discard_pending_choice(choice)
            return
        smaller = 0 if len(piles[0]) <= len(piles[1]) else 1
        if not self._resolve_pile_exile_choice(choice, smaller):
            self.discard_pending_choice(choice)

    def confirm_pile_search(self, player_index: int, pile_index) -> bool:
        """Answer the search of the kept pile. ``pile_index`` of None is
        CR 701.23b's fail-to-find, which a search always allows."""
        return self.resolve_pending_choice(
            "pile_search", player_index, pile_index=pile_index
        )

    def _resolve_pile_search(self, choice: PendingChoice, pile_index) -> bool:
        """Take one card to hand and shuffle the rest of the pile into the
        library.

        Both moves go through the CR 903.9b seams (``put_card_into_hand`` /
        ``put_card_into_library``) rather than appending, because the rule has
        no single fire site and this is one more place that would have
        forgotten it - a commander found this way must reach the command zone.
        """
        import random

        pile = list(choice.data.get("_pile") or ())
        if pile_index is not None and not 0 <= int(pile_index) < len(pile):
            return False
        player = self.players[int(choice.data["owner_index"])]
        found = pile.pop(int(pile_index)) if pile_index is not None else None
        if found is not None:
            self.put_card_into_hand(player, found)
        for card in pile:
            self.put_card_into_library(player, card)
        random.shuffle(player.library)
        self.discard_pending_choice(choice)
        self.log.append(
            (f"{player.name} took {found.name} " if found is not None
             else f"{player.name} found nothing and ")
            + f"and shuffled {len(pile)} card(s) back into their library"
        )
        return True

    def _default_pile_search(self, choice: PendingChoice) -> None:
        """The stated policy: take the **first** card in the pile.

        Lowest index is the house policy for a pick with no printed
        restriction, and failing to find is deliberately not the default here:
        the search is the whole reason the ability was activated, and a seat
        that declined it would have paid a cost for a shuffle.
        """
        pile = list(choice.data.get("_pile") or ())
        if not self._resolve_pile_search(choice, 0 if pile else None):
            self.discard_pending_choice(choice)

    # -- The repeated look-and-bottom offer (Lim-Dul's Vault) ----------------

    def confirm_library_cycle_offer(self, player_index: int, accept: bool) -> bool:
        """Answer one round of "as many times as you choose, you may pay N
        life": accepting bottoms the cards just looked at, looks at the next
        lot and asks again; declining ends the loop and does the shuffle."""
        return self.resolve_pending_choice(
            "library_cycle_offer", player_index, accept=bool(accept)
        )

    def _library_cycle_finish(self, choice: PendingChoice) -> None:
        """"Then shuffle and put the last cards you looked at this way on top
        in any order."

        The order of the two halves is the whole card. The kept cards come out
        *first*, the rest of the library is shuffled (CR 701.24), and only then
        do they go back on top - shuffling with them still in it would lose
        them, and stacking before shuffling would shuffle them away again.

        The final ordering is chained onto this answer rather than done here:
        ``reorder_library`` is a prompt that already exists with its own UI, AI
        default and action, and a decision armed by answering another stays
        inside the same resolution.
        """
        import random

        player = self.players[choice.player_index]
        count = min(int(choice.data.get("count", 0)), len(player.library))
        kept = player.library[:count]
        rest = player.library[count:]
        random.shuffle(rest)
        player.library = kept + rest
        self.log.append(f"{player.name} shuffled their library")
        if count > 1:
            self.arm_pending_choice(
                "reorder_library", choice.player_index,
                target_index=choice.player_index, top_count=count,
                may_shuffle=False,
            )

    def _resolve_library_cycle_offer(self, choice: PendingChoice, accept: bool) -> bool:
        """One round of the loop.

        An accept that cannot be paid for is a decline, not a refused answer:
        CR 119.4 lets a player pay N life only with N or more life to pay it
        from, and a seat that says yes without the life has simply not paid -
        so the loop ends and the card still shuffles. Refusing the answer
        instead would leave the prompt queued with no answer that could ever
        clear it.
        """
        player = self.players[choice.player_index]
        life_cost = int(choice.data.get("life_cost", 0))
        count = int(choice.data.get("count", 0))
        self.discard_pending_choice(choice)
        if not accept or player.life < life_cost:
            self._library_cycle_finish(choice)
            self._release_stack_item(choice.data.get("_stack_item"))
            return True
        player.life -= life_cost
        name = choice.data.get("card_name", "Effect")
        self.log.append(f"{player.name} paid {life_cost} life ({name})")
        # "…put those cards on the bottom of your library **in any order**".
        # They go down as they lay: the order is the player's by rule, the
        # cards are at the bottom of a library that is about to be shuffled,
        # and nothing in the game can ask what it was.
        moved = player.library[:count]
        del player.library[:count]
        for card in moved:
            self.put_card_into_library(player, card, position="bottom")
        looked = min(count, len(player.library))
        self.log.append(
            f"{player.name} looks at the top {looked} card(s) of their library"
        )
        # The next round, armed by answering this one - the ability is still
        # resolving until the loop ends (CR 608.2).
        self.arm_pending_choice(
            "library_cycle_offer", choice.player_index,
            card_name=name, count=count, life_cost=life_cost,
        )
        return True

    def _default_library_cycle_offer(self, choice: PendingChoice) -> None:
        """The stated policy: **decline at once**.

        Not ``_default_optional_pay``'s "pay tolls" - that policy is written for
        an offer made once, and this one is made again every time it is taken.
        A headless seat that paid whenever it could afford to would pay its life
        total down to 1 for a shuffle it has no way to evaluate, which is a
        worse outcome than never having cast the spell. An unbounded optional
        payment has no stopping rule anybody can compute for the player, so the
        engine takes the only answer that cannot be wrong by an unbounded
        amount.
        """
        self._resolve_library_cycle_offer(choice, False)

    # -- One card out of a permanent's linked-exile pile ---------------------

    def live_linked_exile_return_choices(self, choice: PendingChoice) -> list[int]:
        """The positions in the source's linked-exile record this pick admits.

        Positions into ``linked_entries``, not into a player's exile list: the
        record is what CR 610.3 names, and two copies of one card in a deck are
        the same ``CardDefinition`` object, so an index into the pile could not
        tell one entry from another.

        Re-run rather than stored, for ``live_exile_from_hand_choices``' reason:
        the list the seat is offered and the list its answer is checked against
        have to be one list.
        """
        from ...linked_exile import linked_entries

        source = choice.data.get("_source_permanent")
        chooser = choice.player_index
        owned_only = bool(choice.data.get("owned_by_chooser"))
        live: list[int] = []
        for index, entry in enumerate(linked_entries(source)):
            owner_index = int(entry.get("owner_index", -1))
            if owned_only and owner_index != chooser:
                continue
            if not (0 <= owner_index < len(self.players)):
                continue
            # A card that has already left exile by some other route is not a
            # card this can return (CR 608.2b: as much as possible, and no card
            # created from nowhere).
            if entry["card"] not in self.players[owner_index].exile:
                continue
            live.append(index)
        return live

    def confirm_linked_exile_return(self, player_index: int, entry_index) -> bool:
        """Answer the pending pick with a position from
        :meth:`live_linked_exile_return_choices`. There is no decline: "Return a
        card you own exiled with this artifact to your hand" is mandatory, and
        the only thing that ends it without moving a card is an empty pile."""
        return self.resolve_pending_choice(
            "linked_exile_return", player_index, entry_index=entry_index
        )

    def _resolve_linked_exile_return(self, choice: PendingChoice, entry_index) -> bool:
        """Move the chosen entry's card, and drop that one entry.

        Exactly one entry, where the sweep beside it drains the whole record:
        the cards left behind are still exiled with the permanent, and its
        lose-control trigger still names them.
        """
        from ...linked_exile import RECORD_KEY, linked_entries

        source = choice.data.get("_source_permanent")
        if source is None:
            self.discard_pending_choice(choice)
            return True
        if entry_index not in self.live_linked_exile_return_choices(choice):
            return False
        held = list(linked_entries(source))
        entry = held.pop(int(entry_index))
        if held:
            source.metadata[RECORD_KEY] = held
        else:
            source.metadata.pop(RECORD_KEY, None)
        zone = str(choice.data.get("zone", "hand"))
        self.leave_linked_exile(
            entry, zone,
            controller_index=(
                choice.player_index
                if choice.data.get("under_control_of_chooser") else None
            ),
        )
        self.log.append(
            f"{self.players[choice.player_index].name} returned "
            f"{entry['card'].name} to their {zone}"
        )
        self.discard_pending_choice(choice)
        return True

    def _default_linked_exile_return(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** eligible entry.

        Lowest position is the same policy ``_default_discard`` takes, and for
        the same reason — which entries are eligible at all is the printed
        phrase's business and is read off the list the interactive seat is
        offered, and anything past "one of them" is AI valuation rather than
        rules. A pile this seat owns nothing in is a prompt with no answer, so
        it simply comes off the queue.
        """
        live = self.live_linked_exile_return_choices(choice)
        if live and self._resolve_linked_exile_return(choice, live[0]):
            return
        self.discard_pending_choice(choice)

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
        arrival = Permanent(card=card)
        self._put_permanent_onto_battlefield(
            choice.player_index, arrival, None
        )
        # "If you do, sacrifice **it** …" (Flash). By id, like every other
        # producer of a permanent this engine records: the permanent may leave
        # between two steps of one resolution, and a returning one is a new
        # object (CR 400.7). Written here rather than in the handler that armed
        # the prompt, because the permanent does not exist until the answer
        # arrives — the same reason the reanimation is the only step that can
        # name what it reanimated.
        #
        # Set rather than appended: a repeated round (Eureka) offers the seats
        # in turn and each answer replaces the last, which is right for a
        # sentence naming "it" — a card printing "each of them" would want the
        # list, and there is none in the pool.
        choice.data["_context"].results[PUT_FROM_HAND_PERMANENTS] = (
            arrival.permanent_id
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

    # -- Exiling cards out of a named player's graveyard ---------------------

    def arm_graveyard_exile_pick(
        self, player_index: int, owner_index: int, payload: dict, context
    ) -> None:
        """Queue "exile up to N <type> cards from <player>'s graveyard".

        The whole payload travels rather than the candidate list, for the reason
        ``arm_choose_cards_in_hand`` gives: it is the *rule* the candidates came
        from, and re-running it is what keeps the list offered and the list an
        answer is checked against from being two lists.
        """
        self.arm_pending_choice(
            "graveyard_exile_pick", player_index,
            card_name=context.card.name,
            owner_index=int(owner_index),
            count=int(payload.get("count", 1)),
            up_to=bool(payload.get("up_to")),
            _payload=dict(payload),
            _context=context,
        )

    def live_graveyard_exile_candidates(self, choice: PendingChoice) -> list[int]:
        """The positions in that pile the printed noun phrase admits.

        Through ``graveyard_card_matches``, the one predicate the single-card
        graveyard exile, its picker and its re-check already share (idiom 9):
        a second reading here would offer a card the resolution then refuses,
        or refuse one it would have taken.
        """
        from ...handlers._common import graveyard_card_matches

        owner = self.players[int(choice.data["owner_index"])]
        spec = dict(choice.data.get("_payload") or {})
        return [
            index for index, card in enumerate(owner.graveyard)
            if graveyard_card_matches(spec, card)
        ]

    def _how_many_graveyard_cards(self, choice: PendingChoice) -> int:
        """The **ceiling**, not the floor: "up to two" out of a pile holding one
        is one, and out of a pile holding three is still two (CR 608.2)."""
        return min(
            int(choice.data.get("count", 1)),
            len(self.live_graveyard_exile_candidates(choice)),
        )

    def confirm_graveyard_exile_pick(
        self, player_index: int, graveyard_indices
    ) -> bool:
        return self.resolve_pending_choice(
            "graveyard_exile_pick", player_index,
            graveyard_indices=graveyard_indices,
        )

    def _record_graveyard_exile(self, choice: PendingChoice, cards: list) -> None:
        context = choice.data.get("_context")
        if context is not None:
            # Both keys the sweep that exiles a board writes, because the
            # sentences behind this one ask the same two questions: how many,
            # and which. Written even for an empty pick — an *absent* key is a
            # back-reference with no producer, which is a different thing from
            # a producer that took nothing.
            context.results[EXILED_THIS_WAY_OBJECTS] = list(cards)
            context.results[EXILED_THIS_WAY] = len(cards)
        self.discard_pending_choice(choice)

    def _resolve_graveyard_exile_pick(
        self, choice: PendingChoice, graveyard_indices
    ) -> bool:
        """Take the chosen cards out of that pile and into their owner's exile.

        Every pick is validated before anything moves, the shape the two-zone
        exile search already takes: a single bad entry rejects the whole answer
        and leaves the prompt queued, so a malformed request cannot exile half
        a selection. "Up to" is what makes an empty answer legal; a fixed count
        owes exactly what the pile can supply.

        Highest index first, because a graveyard is a list and taking one
        renumbers everything behind it — the same reason the counted hand pick
        re-computes its candidates between picks.
        """
        owner = self.players[int(choice.data["owner_index"])]
        live = set(self.live_graveyard_exile_candidates(choice))
        wanted = self._how_many_graveyard_cards(choice)
        picks = list(graveyard_indices or [])
        if len(picks) != len(set(picks)):
            return False
        if len(picks) > wanted or (
            not choice.data.get("up_to") and len(picks) != wanted
        ):
            return False
        if any(index not in live for index in picks):
            return False
        taken = [owner.graveyard[index] for index in picks]
        for index in sorted(picks, reverse=True):
            owner.exile.append(owner.graveyard.pop(index))
        self._record_graveyard_exile(choice, taken)
        self.log.append(
            f"{self.players[choice.player_index].name} exiled "
            + (", ".join(card.name for card in taken) or "nothing")
            + f" from {owner.name}'s graveyard "
            f"({choice.data.get('card_name', 'an effect')})"
        )
        return True

    def _default_graveyard_exile_pick(self, choice: PendingChoice) -> None:
        """The stated "up to N" policy: the maximum, in pile order.

        Taking cards out of an opponent's graveyard costs the seat nothing —
        this is a gift under "take gifts, pay tolls, make no trades" — and pile
        order is seed-deterministic, which is what AI and headless play need. A
        seat that should pick cleverly needs a weight in
        ``engine/ai_valuation.py``, not a branch here.
        """
        live = self.live_graveyard_exile_candidates(choice)
        wanted = self._how_many_graveyard_cards(choice)
        if not self._resolve_graveyard_exile_pick(choice, live[:wanted]):
            self._record_graveyard_exile(choice, [])

    # -- Which vocabulary a text change replaces a word from -----------------

    def live_text_change_vocabularies(self, permanent, old_symbol: str) -> list[str]:
        """The vocabularies whose printed word is actually on *permanent*.

        A text change that rewrites a word the permanent does not have is a
        legal choice (CR 612.1 puts no such condition on it) and changes
        nothing, so offering it would be a question one of whose answers is
        "do nothing" — the shortcut every other picker here takes when a choice
        has one real answer. The *written* text, not the printed card: a second
        text change rewrites what the first wrote.
        """
        # `text_changes`' own tables, both keyed by mana **symbol**. The
        # grammar's `COLOR_WORDS` is the same pairs the other way round (word →
        # symbol) and reading it here would look up "U" and find nothing, which
        # is a vocabulary silently never offered.
        from ...text_changes import COLOR_WORDS, LAND_TYPE_WORDS

        symbol = (old_symbol or "").upper()
        effective = permanent.effective_card
        written = " ".join(
            (effective.type_line, effective.oracle_text, *effective.keywords)
        ).lower()
        found = []
        colour = COLOR_WORDS.get(symbol)
        if colour and colour in written:
            found.append("color_word")
        land = LAND_TYPE_WORDS.get(symbol)
        if land and land in written:
            found.append("land_type")
        return found

    def arm_text_change_vocabulary(
        self, player_index: int, permanent, old_symbol: str, new_symbol: str,
        card_name: str,
    ) -> None:
        """Queue "a colour word, or a basic land type?" for Mind Bend.

        One vocabulary that could do anything is not a decision, and none at all
        is not a prompt: the swap is performed straight away in the first case
        and nothing happens in the second, exactly as the pile choice one file
        over decides whether to ask at all.
        """
        live = self.live_text_change_vocabularies(permanent, old_symbol)
        if not live:
            self.log.append(
                f"{card_name} had no effect: {permanent.card.name} has no such "
                "word in its text"
            )
            return
        if len(live) == 1:
            self._apply_text_change_vocabulary(
                permanent, live[0], old_symbol, new_symbol, card_name
            )
            return
        self.arm_pending_choice(
            "text_change_vocabulary", player_index,
            card_name=card_name,
            permanent_name=permanent.card.name,
            options=list(live),
            old_symbol=(old_symbol or "").upper(),
            new_symbol=(new_symbol or "").upper(),
            _permanent=permanent,
        )

    def _apply_text_change_vocabulary(
        self, permanent, mode: str, old_symbol: str, new_symbol: str,
        card_name: str,
    ) -> None:
        """Perform the swap the seat named, through the same two writers the
        single-vocabulary cards use — a third copy here would be a third answer
        to what a text change records."""
        from ...text_changes import (LAND_TYPE_WORDS, change_color_word,
                                     change_land_word)

        if mode == "color_word":
            if change_color_word(
                permanent, old_symbol, new_symbol, label=card_name
            ):
                self.log.append(
                    f"{card_name} changed {old_symbol} text to {new_symbol} on "
                    f"{permanent.card.name}"
                )
            return
        old_type = LAND_TYPE_WORDS.get((old_symbol or "").upper())
        new_type = LAND_TYPE_WORDS.get((new_symbol or "").upper())
        if old_type and new_type and change_land_word(
            permanent, old_type, new_type, label=card_name
        ):
            self.log.append(
                f"{card_name} changed {old_type} to {new_type} in "
                f"{permanent.card.name}'s text"
            )
            # A land word inside a lord's grant line ("Other Goblins have
            # mountainwalk") is part of a buff the board caches, so the swap has
            # to be re-derived — the same call the single-vocabulary handler
            # makes for the same reason.
            self._recalculate_lord_buffs()

    def confirm_text_change_vocabulary(self, player_index: int, mode) -> bool:
        return self.resolve_pending_choice(
            "text_change_vocabulary", player_index, mode=mode
        )

    def _resolve_text_change_vocabulary(self, choice: PendingChoice, mode) -> bool:
        permanent = choice.data.get("_permanent")
        if mode not in (choice.data.get("options") or ()):
            return False
        if permanent is None or not self.is_on_battlefield(permanent):
            # It left while the prompt was owed (CR 608.2b): nothing to rewrite,
            # and the decision is over either way.
            self.discard_pending_choice(choice)
            return True
        self.discard_pending_choice(choice)
        self._apply_text_change_vocabulary(
            permanent, str(mode), str(choice.data.get("old_symbol") or ""),
            str(choice.data.get("new_symbol") or ""),
            str(choice.data.get("card_name") or ""),
        )
        return True

    def _default_text_change_vocabulary(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** offered vocabulary, which is the
        colour word.

        Not a valuation — the order is the one
        ``live_text_change_vocabularies`` builds and is seed-deterministic. A
        seat that should weigh a type-line rewrite against a colour one needs a
        weight in ``engine/ai_valuation.py``, not a branch here.
        """
        options = list(choice.data.get("options") or ())
        if not options or not self._resolve_text_change_vocabulary(
            choice, options[0]
        ):
            self.discard_pending_choice(choice)

    # -- A sacrifice priced by an aggregate rather than by a count -----------

    def aggregate_sacrifice_candidates(self, seat: int, payload: dict) -> list:
        """The permanents *seat* controls that the printed noun phrase names.

        Through ``subject_matches``, the one predicate the picker, the
        takeability gate and the answer's re-check all ask — three readings of
        "which creatures may be given up" is three chances to offer one the
        resolution then refuses.
        """
        from ...subject_filters import subject_matches

        described = dict(payload.get("filter") or {})
        source = payload.get("_source")
        return [
            perm for perm in self.controlled_by(seat)
            if subject_matches(self, perm, described, observer=seat, source=source)
            and not (payload.get("exclude_self") and perm is source)
        ]

    def aggregate_sacrifice_total(self, permanents, characteristic: str) -> int:
        """What a chosen set totals, through CR 613's layers.

        ``effective_power`` rather than the printed number, so a pumped creature
        counts for what it is now — the same accessor every other reader of a
        creature's power in this engine goes through.
        """
        return sum(
            int(
                (perm.effective_power if characteristic == "power"
                 else perm.effective_toughness) or 0
            )
            for perm in permanents
        )

    def arm_aggregate_sacrifice(self, player_index: int, payload: dict, context) -> None:
        """Queue "sacrifice any number of <noun> with total <X> N or greater".

        The whole payload travels rather than the candidate list, for
        ``arm_choose_cards_in_hand``'s reason: it is the *rule* the candidates
        came from, and re-running it is what keeps the list offered and the list
        an answer is checked against from being two lists.
        """
        self.arm_pending_choice(
            "aggregate_sacrifice", player_index,
            card_name=context.card.name,
            characteristic=str(payload.get("characteristic") or "power"),
            at_least=int(payload.get("at_least", 0)),
            _payload=dict(payload),
            _context=context,
        )

    def confirm_aggregate_sacrifice(self, player_index: int, permanent_ids) -> bool:
        return self.resolve_pending_choice(
            "aggregate_sacrifice", player_index, permanent_ids=permanent_ids
        )

    def _resolve_aggregate_sacrifice(self, choice: PendingChoice, permanent_ids) -> bool:
        """Sacrifice exactly the set named, once it clears the printed floor.

        Validated whole before anything is sacrificed, the shape every
        list-shaped picker here takes: one bad id rejects the answer and leaves
        the prompt queued, so a malformed request cannot sacrifice half a
        selection. **The floor is the whole of the price** — an answer under it
        is not a cheaper payment, it is no payment at all, so it is refused
        rather than applied.
        """
        payload = dict(choice.data.get("_payload") or {})
        live = self.aggregate_sacrifice_candidates(choice.player_index, payload)
        ids = [pid for pid in (permanent_ids or []) if isinstance(pid, int)]
        if len(ids) != len(permanent_ids or []) or len(set(ids)) != len(ids):
            return False
        chosen = []
        for pid in ids:
            perm = self.permanent_by_id(pid)
            if perm is None or not any(perm is candidate for candidate in live):
                return False
            chosen.append(perm)
        characteristic = str(choice.data.get("characteristic") or "power")
        if self.aggregate_sacrifice_total(chosen, characteristic) < int(
            choice.data.get("at_least", 0)
        ):
            return False
        self.discard_pending_choice(choice)
        for perm in chosen:
            self.sacrifice_permanent(perm)
        self.log.append(
            f"{choice.data.get('card_name', 'An effect')}: "
            + (", ".join(perm.card.name for perm in chosen) or "nothing")
            + " sacrificed"
        )
        return True

    def _default_aggregate_sacrifice(self, choice: PendingChoice) -> None:
        """The stated policy: the **fewest** permanents that clear the floor,
        taking the largest first.

        A toll rather than a gift — "take gifts, pay tolls, make no trades" —
        and the cheapest way to pay a toll counted in power is to spend as few
        bodies as possible. Ties break by battlefield order, which is
        seed-deterministic; a seat that should value the creatures themselves
        needs a weight in ``engine/ai_valuation.py``, not a branch here.

        **The ability's own source is a candidate** unless the sentence printed
        "another": nothing in CR 701.17a excludes it, and Phyrexian Dreadnought
        really can be sacrificed to its own trigger. So the largest-first rule
        usually pays with the source — which is the *same board state* as
        declining, and therefore the "make no trades" answer rather than an
        accident of the ordering.
        """
        payload = dict(choice.data.get("_payload") or {})
        characteristic = str(choice.data.get("characteristic") or "power")
        wanted = int(choice.data.get("at_least", 0))
        live = self.aggregate_sacrifice_candidates(choice.player_index, payload)
        ordered = sorted(
            live,
            key=lambda perm: -int(
                (perm.effective_power if characteristic == "power"
                 else perm.effective_toughness) or 0
            ),
        )
        taken, total = [], 0
        for perm in ordered:
            if total >= wanted:
                break
            taken.append(perm)
            total = self.aggregate_sacrifice_total(taken, characteristic)
        if total < wanted or not self._resolve_aggregate_sacrifice(
            choice, [perm.permanent_id for perm in taken]
        ):
            # Nothing the seat controls can cover the price. The offer should
            # never have been made — ``_action_is_takeable`` asks the same
            # question first — so this is the defensive half, and it declines
            # rather than sacrificing a set that does not pay.
            self.discard_pending_choice(choice)

    # -- Which end of a library a tuck puts its card on ----------------------

    def arm_library_end_choice(
        self, player_index: int, permanent, owner_index: int, context
    ) -> None:
        """Queue "top or bottom?" for a tuck whose card qualifies for the swap.

        The **permanent** travels rather than the card, so the answer moves the
        object this resolution resolved: two copies of one card in a library are
        the same ``CardDefinition``, and a card is not addressable while a
        permanent still is (CR 400.7).
        """
        self.arm_pending_choice(
            "library_end_choice", player_index,
            card_name=context.card.name,
            moved_name=permanent.card.name,
            owner_index=int(owner_index),
            owner_name=self.players[int(owner_index)].name,
            _permanent=permanent,
            _context=context,
        )

    def confirm_library_end_choice(self, player_index: int, to_bottom) -> bool:
        return self.resolve_pending_choice(
            "library_end_choice", player_index, to_bottom=to_bottom
        )

    def _resolve_library_end_choice(self, choice: PendingChoice, to_bottom) -> bool:
        """Move the permanent to the end the seat named.

        The move happens **here** rather than before the prompt, because "put it
        on the bottom **instead**" is one zone change with two possible ends: a
        version that tucked on top and then moved the card would be two zone
        changes, which is one more than the card describes and one more than any
        watcher should see.
        """
        permanent = choice.data.get("_permanent")
        if permanent is None or not self.is_on_battlefield(permanent):
            # It left while the prompt was owed. CR 608.2b: the effect does as
            # much as it can, which here is nothing.
            self.discard_pending_choice(choice)
            return True
        owner = self.players[int(choice.data["owner_index"])]
        self.remove_from_battlefield(permanent)
        self._remove_aura_effects(permanent)
        position = "bottom" if to_bottom else "top"
        self.put_card_into_library(
            owner, permanent.card, position, from_battlefield=permanent
        )
        self.discard_pending_choice(choice)
        self.log.append(
            f"{choice.data.get('card_name', 'An effect')}: "
            f"{permanent.card.name} put on {position} of {owner.name}'s library"
        )
        return True

    def _default_library_end_choice(self, choice: PendingChoice) -> None:
        """The stated policy: the **bottom**.

        The offer costs its controller nothing and buries the card deeper, so
        it is a gift under "take gifts, pay tolls, make no trades" — and it is
        deterministic, which is what AI and headless play need. A seat that
        should weigh the two ends needs a weight in ``engine/ai_valuation.py``,
        not a branch here.
        """
        self._resolve_library_end_choice(choice, True)

    # -- Which graveyard "a single graveyard" means --------------------------

    def graveyard_piles_with_a_legal_card(self, payload: dict) -> list[int]:
        """The seats whose graveyard holds a card the printed phrase admits.

        The rule rather than the list, for ``arm_graveyard_exile_pick``'s
        reason: a pile offered here is a pile the pick will then be re-checked
        against, and two readings of "which cards does this phrase name" is
        exactly the drift ``graveyard_card_matches`` exists to stop.
        """
        from ...handlers._common import graveyard_card_matches

        return [
            seat for seat, player in enumerate(self.players)
            if any(graveyard_card_matches(payload, card)
                   for card in player.graveyard)
        ]

    def arm_graveyard_pile_choice(
        self, player_index: int, payload: dict, context
    ) -> None:
        """Queue "which graveyard?" for "exile … from **a single** graveyard".

        A prompt of its own rather than a wider ``graveyard_exile_pick``,
        because the two questions have different answers and different
        candidate rules — and because answering this one *arms* that one, which
        is how a chain of decisions stays a single resolution (CR 608.2): the
        stack object stays put until the last prompt of the chain is answered.
        """
        self.arm_pending_choice(
            "graveyard_pile_choice", player_index,
            card_name=context.card.name,
            seats=self.graveyard_piles_with_a_legal_card(payload),
            _payload=dict(payload),
            _context=context,
        )

    def live_graveyard_pile_choices(self, choice: PendingChoice) -> list[int]:
        """The offered piles that are still legal answers.

        Recomputed rather than trusted: a card can leave a graveyard between the
        offer and the answer (another player's effect in response), and a pile
        that no longer holds a card the phrase names is a pile the pick behind
        this would find empty.
        """
        offered = set(choice.data.get("seats") or ())
        return [
            seat
            for seat in self.graveyard_piles_with_a_legal_card(
                dict(choice.data.get("_payload") or {})
            )
            if seat in offered
        ]

    def confirm_graveyard_pile_choice(self, player_index: int, seat) -> bool:
        return self.resolve_pending_choice(
            "graveyard_pile_choice", player_index, seat=seat
        )

    def _resolve_graveyard_pile_choice(self, choice: PendingChoice, seat) -> bool:
        live = self.live_graveyard_pile_choices(choice)
        context = choice.data.get("_context")
        if not live:
            # Every offered pile has been emptied of legal cards while this was
            # owed. The sentence carries on having exiled nothing rather than
            # staying owed a prompt with no answer — and both record keys are
            # written, because an *absent* key is a back-reference with no
            # producer, a different thing from a producer that took nothing.
            if context is not None:
                context.results[EXILED_THIS_WAY_OBJECTS] = []
                context.results[EXILED_THIS_WAY] = 0
            self.discard_pending_choice(choice)
            return True
        if not isinstance(seat, int) or seat not in live:
            return False
        payload = dict(choice.data.get("_payload") or {})
        self.discard_pending_choice(choice)
        self.log.append(
            f"{choice.data.get('card_name', 'An effect')}: chose "
            f"{self.players[seat].name}'s graveyard"
        )
        # The second half of the chain, armed by the answer to the first. The
        # prompt this queues stamps the same resolving stack object, so the
        # object stays on the stack and no step advances until it too is
        # answered.
        self.arm_graveyard_exile_pick(
            choice.player_index, seat, payload, context
        )
        return True

    def _default_graveyard_pile_choice(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** live pile, in seat order.

        Not a valuation — seat order is seed-deterministic, which is what AI and
        headless play need, and ``_default_player_choice`` states the same rule
        for the same reason. A seat that should choose cleverly needs a weight
        in ``engine/ai_valuation.py``, not a branch here.
        """
        live = self.live_graveyard_pile_choices(choice)
        if not live or not self._resolve_graveyard_pile_choice(choice, live[0]):
            context = choice.data.get("_context")
            if context is not None:
                context.results[EXILED_THIS_WAY_OBJECTS] = []
                context.results[EXILED_THIS_WAY] = 0
            self.discard_pending_choice(choice)

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
            self.put_card_into_graveyard(player, player.hand.pop(i))
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

    def _optional_pay_plan(self, player, entry: dict, option: int | None = None):
        """How *player* would pay this entry's cost, or None if they cannot.

        The cost is the whole printed one — ``{1}{B}`` is a dict of symbols, not
        the number 2 — and it is collected from the board rather than from the
        pool alone, because an effect that says "you may pay" gives its player no
        priority window in which to tap for mana. ``engine/mana_payment.py``
        holds both halves of that question; asking it once here is what makes
        "can they pay?" and "pay it" the same answer.
        """
        # "…unless they pay {B} **or {3}**" (Lim-Dûl's Hex). CR 118.8's
        # alternatives are readings of the *same* offer, so they are tried
        # here rather than at a second prompt — in printed order, which is the
        # stated policy the life alternative below already takes.
        #
        # *option* names one of them instead, and that is a different question:
        # where each way of covering the offer buys something different
        # (Winter's Chill), the payer is *choosing* rather than finding the
        # first they can afford, so only the option they chose may be planned.
        lands = untapped_mana_lands(self.controlled_by(player))
        options = optional_pay_options(entry)
        if option is not None:
            options = options[option:option + 1]
        for cost in options:
            plan = plan_payment(
                player.mana_pool, lands, cost,
                produces=self._land_payment_colors,
            )
            if plan is not None:
                return plan
        return None

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
            if player.life < life_cost:
                return False
            # "You may pay {4} **and** 2 life." (Purgatory.) Both prices, so
            # the life half answering yes is no longer the whole answer: with a
            # mana half printed beside it the board has to cover that too. An
            # offer with no mana half (Bronze Tablet) falls through to a plan
            # over an empty cost, which is always payable — so one path answers
            # both spellings without having to ask which it is.
            if not entry.get("cost"):
                return True
        if self._optional_pay_plan(player, entry) is not None:
            return True
        alternative = int(entry.get("life_alternative", 0) or 0)
        return bool(alternative) and player.life >= alternative

    def graded_pay_options(self, entry: dict) -> list[dict] | None:
        """The costs a **graded** offer asks the payer to choose between, or None.

        Graded means each way of covering the offer buys something different —
        "its controller may pay {1} or {2}. If that player doesn't, destroy that
        creature … If that player pays only {1}, prevent …" (Winter's Chill).
        CR 118.8's ordinary alternative is not graded: {B} or {3} (Lim-Dûl's
        Hex) are two ways to buy one consequence, and which one the board covers
        is the engine's to state. Here the payer is choosing, so the prompt has
        to ask *which* — and the answer has to come back, because it decides
        what happens next.

        Answered off ``_option_effects`` rather than off a flag, so "the payer
        chooses" and "the choice buys something" cannot come apart.
        """
        if not entry.get("_option_effects"):
            return None
        return optional_pay_options(entry)

    def _graded_option_taken(
        self, player, entry: dict, option: int | None,
    ) -> int | None:
        """Which option a graded offer is being paid with, or None if none can be.

        A named option is honoured when the payer can cover it and refused when
        they cannot — an offer answered with a cost they cannot pay buys nothing
        rather than falling through to a cheaper one they did not choose.

        With no option named (a non-interactive seat, or a client that sent a
        bare "yes"), the **stated policy** is the last option the board can
        cover. A graded toll prints its options in increasing order and the
        extra payment is what buys off the extra consequence, so taking the
        first would pay *and* take the penalty — which is the one answer no
        payer would give.
        """
        options = optional_pay_options(entry)
        if option is not None:
            if not 0 <= option < len(options):
                return None
            return option if self._optional_pay_plan(
                player, entry, option=option
            ) is not None else None
        for index in reversed(range(len(options))):
            if self._optional_pay_plan(player, entry, option=index) is not None:
                return index
        return None

    def _pay_optional(
        self, player_index: int, entry: dict, option: int | None = None,
    ) -> None:
        """Collect the entry's mana cost from its player and run what accepting
        buys. A cost that turns out to be unpayable buys nothing.

        *option* is which of a graded offer's costs the payer chose; None
        everywhere else, and on a graded offer means "take the stated policy".
        """
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
            # "You may pay {4} **and** 2 life." (Purgatory.) Both halves or
            # neither: the mana is planned *before* the life is spent, because
            # a payer charged the life and then unable to cover the mana would
            # have paid for nothing — CR 601.2h is asked of the whole price,
            # and the board can have changed since the offer was made.
            if entry.get("cost") and self._optional_pay_plan(player, entry) is None:
                return
            player.life -= life_cost
            self.log.append(
                f"{player.name} paid {life_cost} life ({entry.get('card_name', '')})"
            )
        if not life_cost or entry.get("cost"):
            # A graded offer is paid with the option that was chosen and with no
            # other: falling back through the alternatives would charge a cost
            # the payer did not pick and then run the consequence that cost
            # buys.
            if self.graded_pay_options(entry) is not None:
                option = self._graded_option_taken(player, entry, option)
                if option is None:
                    return
            plan = self._optional_pay_plan(player, entry, option=option)
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
        # What *this* option bought (Winter's Chill's {1}). Beside the accept
        # branch rather than instead of it: a card could print both, and the
        # accept branch is what every option has in common.
        graded = entry.get("_option_effects")
        if graded and option is not None and 0 <= option < len(graded):
            ran = self._run_optional_steps(entry, list(graded[option])) or ran
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
        return self._run_optional_steps(entry, entry.get(key) or ())

    def _run_optional_steps(self, entry: dict, steps) -> bool:
        """Run *steps* against the entry's frozen resolution context.

        Split from :meth:`_run_optional_branch` because a graded offer's branch
        is not a fixed payload key — which option was taken is only known once
        the payment is made — and the two must run the same way: through
        ``run_resumable``, against the context the offer was armed with.
        """
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
        if option["spec"].get("requires_target") and not choice.data.get("_keep_targets"):
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

    def _offered_mode_instructions(self, choice: PendingChoice) -> tuple:
        """The instruction behind each offered mode, whichever site armed it.

        ``_resolve_mode_choice`` already distinguishes the two by the data on
        the prompt rather than by a list of kinds; this reads the same two keys
        so a third arming site is a data question there and here alike.
        """
        if choice.data.get("_trigger_item") is None:
            return tuple(choice.data.get("_modes") or ())
        return tuple(
            getattr(option, "instruction", None)
            for option in (choice.data.get("_options") or ())
        )

    def _first_unpriced_mode(self, choice: PendingChoice) -> int:
        """The first offered mode that does not spend the chooser's own
        resources, or 0 when every one of them does.

        ``_default_optional_pay``'s policy one layer in: "pay 4 life **or** put
        the card on top of your library" (Sylvan Library) offers a price beside
        a free alternative, and printed order put the price first. A seat
        nobody asked drew two extra cards every draw step and paid 8 life for
        them — dead on the third one, out of a card whose whole design is that
        the player decides how much life it is worth.

        All-priced alternatives keep printed order: "sacrifice a creature or
        discard a creature card" (Crypt Lurker) is a choice between two prices
        and picking the smaller is valuation, exactly as it is for a toll.
        """
        from ...ai_valuation import offered_action_is_a_payment

        seat = self.players[choice.player_index]
        context = choice.data.get("_context")
        # The printed player references that resolve to the chooser. With no
        # resolution context — the modal-trigger site — the chooser *is* the
        # ability's controller, which is what "caster" names.
        self_recipients = {"caster"}
        if context is not None:
            if getattr(context, "caster", None) is not seat:
                self_recipients.discard("caster")
            if getattr(context, "target", None) is seat:
                self_recipients.update(("target", "target_player"))
        for index, instruction in enumerate(self._offered_mode_instructions(choice)):
            if instruction is None:
                continue
            if not offered_action_is_a_payment((instruction,), self_recipients):
                return index
        return 0

    def _default_mode_choice(self, choice: PendingChoice) -> bool:
        """What a non-interactive seat answers a "Choose one —" prompt with:
        the first *offered* mode that is not a price paid out of its own
        resources, and the first offered mode when they all are.

        A stated policy, not a valuation, and "offered" rather than "printed"
        because CR 700.2b has already removed from the list any mode whose
        targets could not be chosen. The target inside that mode is
        ``_default_trigger_mode_target``'s, which is derived from the mode's
        own effect family rather than named per card.

        It was plain printed order, which is a policy nobody chose for the one
        card in the pool where the alternatives are not alike — see
        ``_first_unpriced_mode``.
        """
        return self._resolve_mode_choice(choice, self._first_unpriced_mode(choice))

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

    def confirm_optional_pay(
        self, player_index: int, card_name: str | None = None,
        accept: bool = True, option: int | None = None,
    ) -> bool:
        """Resolve the first pending optional "pay {N}" trigger for a player (the
        color rods' gain-life riders, Hasran Ogress' pay-or-take-damage).
        ``accept`` pays it; otherwise the decline consequence (if any) applies.

        *option* is which of a **graded** offer's printed costs is being paid
        (:meth:`graded_pay_options`) — ignored on every other offer, where the
        alternatives are two ways to buy one thing and the engine states which
        it spends."""
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
            choice, lambda: self._resolve_optional_pay(choice, accept, option)
        )

    def _resolve_optional_pay(
        self, choice: PendingChoice, accept: bool, option: int | None = None,
    ) -> bool:
        player_index = choice.player_index
        entry = choice.data
        # CR 601.2b: a player chooses among the options they are **able** to
        # take. A named option they cannot cover is not an answer, so the prompt
        # stands rather than being consumed — the alternative is an answer that
        # pays nothing, buys nothing and does not decline either, which on
        # Winter's Chill is a creature that is neither shielded nor destroyed.
        # A graded offer answered with no option at all is not this case: that
        # is the stated policy, and `_graded_option_taken` supplies it.
        if (
            accept
            and option is not None
            and self.graded_pay_options(entry) is not None
            and self._graded_option_taken(
                self.players[player_index], entry, option
            ) is None
        ):
            return False
        self.discard_pending_choice(choice)
        if (
            accept
            and self._player_can_pay_optional(self.players[player_index], entry)
            and self._optional_action_still_takeable(player_index, entry)
        ):
            self._pay_optional(player_index, entry, option)
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

    def _optional_action_still_takeable(self, player_index: int, entry: dict) -> bool:
        """Whether the accept branch's *action* can still be performed.

        CR 601.2b: a player chooses among the alternatives they are **able** to
        take, and able is measured when the choice is made rather than when the
        prompt was armed. ``handlers/control_flow._offer_to_seat`` already asks
        this before offering, and asking it once was enough while one offer was
        armed at a time — Oath of Lim-Dûl arms one per point of life lost, all
        of them before any is answered, so a hand with one card in it offered
        two discards and the second accept discarded nothing and skipped the
        sacrifice the card prints for not paying.

        The same predicate the offer narrows through, so what may be accepted
        and what may be offered cannot come apart.
        """
        from ...handlers.control_flow import _narrow_to_takeable_actions

        context = entry.get("_context")
        steps = tuple(entry.get("_on_accept") or ())
        if context is None or not steps:
            return True
        _, offerable = _narrow_to_takeable_actions(
            self, self.players[player_index], steps, context
        )
        return offerable

    def _offer_is_an_unpriced_trade(self, choice: PendingChoice) -> bool:
        """Whether this offer's price is paid out of the offered seat's own
        resources while the card prices refusing it at nothing.

        Three questions, each read off the entry the offer was armed with:

        1. is it free *as the entry states it* — no mana cost, no life cost, no
           CR 118.8 alternative? A printed cost is already answered above, and
           correctly: the seat spends what is floating and no more.
        2. does taking it spend something of the seat's own
           (``ai_valuation.offered_action_is_a_payment``)?
        3. is refusing it free — no "if you don't" branch and no legacy damage
           field, which are the two spellings of a printed penalty?

        Only all three together make refusing the strictly cheaper answer. Drop
        (3) and Season of the Witch sacrifices itself rather than pay 2 life and
        Elder Spawn takes 6 damage rather than sacrifice one Island; drop (2)
        and Sylvan Library stops drawing.

        The player references are resolved to seats *here* because only the
        resolution knows them: "that player" is whoever the offer was rebound
        to, and CR 601.2b's chooser is the seat holding the prompt.
        """
        from ...ai_valuation import offered_action_is_a_payment

        entry = choice.data
        if (
            entry.get("cost")
            or entry.get("life_cost")
            or entry.get("cost_alternatives")
        ):
            return False
        if entry.get("_on_decline") or int(entry.get("damage", 0) or 0):
            return False
        return offered_action_is_a_payment(
            entry.get("_on_accept") or (), self._offer_self_recipients(choice)
        )

    def _offer_self_recipients(self, choice: PendingChoice) -> frozenset[str]:
        """The printed player references in this offer's branches that resolve
        to the offered seat ("caster", "target_player"), for the readers whose
        answer depends on who a step lands on
        (``ai_valuation.offered_action_is_a_payment``, ``toll_branch_loss``).

        Resolved here because only the resolution knows the bindings: "that
        player" is whoever the offer was rebound to, and CR 601.2b's chooser is
        the seat holding the prompt. A trigger's own "that player" compiles to
        an ``event_subject_*`` reference resolved off the seat the fire site
        froze in ``trigger_context`` (Curse Artifact's decline damage), so
        those references answer for the offered seat the same way.
        """
        entry = choice.data
        seat = self.players[choice.player_index]
        context = entry.get("_context")
        self_recipients: set[str] = set()
        if context is not None:
            if getattr(context, "caster", None) is seat:
                self_recipients.add("caster")
            if getattr(context, "target", None) is seat:
                self_recipients.update(("target", "target_player"))
            trigger = getattr(context, "trigger_context", None) or {}
            for reference in ("event_subject_player", "event_subject_controller"):
                if trigger.get(reference) == choice.player_index:
                    self_recipients.add(reference)
        return frozenset(self_recipients)

    def _default_optional_pay(self, choice: PendingChoice) -> None:
        """Pay when the floating mana is already there; an unpayable "unless you
        pay" entry applies its decline consequence (Hasran Ogress' damage).

        A *stated policy*, not the payability test: the non-interactive default
        spends mana it already has and never taps a land for an optional cost,
        because tapping is a real decision about the rest of the turn.
        ``_player_can_pay_optional`` is the wider question and belongs to the
        seat that was actually asked.

        **The whole policy in one line: take gifts, pay tolls, make no trades.**
        A cost this could not see was one it charged nothing for, so every
        *free* offer was accepted — and "free" was read off the ``cost`` field
        alone, which is only where the grammar puts a price printed as mana or
        as life. A price printed as a deed ("you may **sacrifice another
        creature**", "you may **ante the top card of your library**") is lowered
        into the offered action instead, where the affordability test could not
        find it, so it read as free and was taken every time — the AI sacrificed
        a creature at the beginning of every combat and anteed away a card it
        was never asked about. ``_offer_is_an_unpriced_trade`` asks the same
        question of that half, and refusing is the same answer this already
        gives an offer it cannot afford."""
        entry = choice.data
        player = self.players[choice.player_index]
        # A life cost has no "already floating" reading — nothing is held in
        # reserve to spend — so the stated policy is the one a player at a
        # healthy life total would take: pay, unless it would be lethal.
        life_cost = int(entry.get("life_cost", 0) or 0)
        mana_covered = next(
            (
                plan
                for cost in (
                    entry.get("cost") or {},
                    *(entry.get("cost_alternatives") or ()),
                )
                for plan in (plan_payment(player.mana_pool, (), cost),)
                if plan is not None
            ),
            None,
        )
        if not life_cost:
            floating = mana_covered
        elif not entry.get("cost"):
            # A life cost with no mana half (Bronze Tablet). No "already
            # floating" reading — nothing is held in reserve to spend — so the
            # policy is the one a player at a healthy life total would take.
            floating = True if player.life > life_cost else None
        else:
            # "You may pay {4} **and** 2 life." (Purgatory.) One offer with two
            # prices, so neither branch above answers it: the life is judged the
            # way the branch above judges it, and the mana still has to clear
            # the floating-mana rule — otherwise the policy would tap four lands
            # for an offer it has just said it would not tap one for.
            floating = (
                True
                if player.life > life_cost and mana_covered is not None
                else None
            )
        # A graded offer needs the policy to say *which* option as well as
        # whether to pay, because each buys something different (Winter's
        # Chill). The same policy one step further: the last option the floating
        # mana covers — a graded toll prints its options in increasing order and
        # the extra payment is what buys off the extra consequence, so paying
        # the cheapest would spend mana *and* take the penalty.
        option = None
        graded = self.graded_pay_options(entry)
        if graded is not None:
            option = next(
                (
                    index for index in reversed(range(len(graded)))
                    if plan_payment(player.mana_pool, (), graded[index]) is not None
                ),
                None,
            )
            floating = None if option is None else True
        # The same policy for CR 118.8's alternative: floating mana first, and
        # the life only when there is none — and never down to zero, which is
        # the reading the life-cost branch above already takes.
        alternative = int(entry.get("life_alternative", 0) or 0)
        if floating is None and alternative and player.life > alternative:
            floating = True
        # Take gifts, pay tolls, make no trades: an offer whose price is a deed
        # rather than a payment, and whose refusal the card prices at nothing,
        # is refused. A *toll* — an offer with a printed "if you don't" — is
        # still paid by default, because refusing it is not free either.
        if floating is not None and self._offer_is_an_unpriced_trade(choice):
            floating = None
            self.log.append(
                f"{player.name} declined {entry['card_name']} "
                "(declining costs nothing)"
            )
        # …unless the toll's two losses are both priceable off the compiled
        # program and the penalty is the smaller one — "2 damage" against
        # "sacrifice that artifact" (Curse Artifact). The comparison and its
        # weights are `ai_policy.toll_decline_is_smaller_loss` with the
        # magnitudes derived in `ai_valuation.toll_branch_loss`; a side the
        # program cannot price answers False and the pay-tolls policy stands.
        elif floating is not None:
            from ...ai_policy import toll_decline_is_smaller_loss

            if toll_decline_is_smaller_loss(
                self, choice.player_index, entry, self._offer_self_recipients(choice)
            ):
                floating = None
                self.log.append(
                    f"{player.name} declined {entry['card_name']} "
                    "(the penalty is the smaller loss)"
                )
        self.discard_pending_choice(choice)
        if floating is not None and self._optional_action_still_takeable(
            choice.player_index, entry
        ):
            self._pay_optional(choice.player_index, entry, option)
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

    # -- Becoming the colour or colours of your choice (Shyft) --------------

    def arm_color_set_choice(
        self, player_index: int, *, permanent, card_name: str, several: bool
    ) -> None:
        """Ask *player_index* which colour or colours *permanent* becomes.

        The colour a *triggered* ability sets has nowhere else to come from: an
        activated one carries it on the activation (``choices["new_color"]``),
        and nothing announces a trigger. So the question is put here, on the
        standing queue, and CR 609.3 is why it is put at resolution rather than
        when the trigger goes on the stack.

        A deterministic default is stamped before the prompt, the discipline
        every entry choice follows: the colour the *opponents* hold least of
        among nontoken permanents, which is the choice a player makes with this
        card — a creature that shares a colour with the board is the one every
        colour-hoser reaches. The same reasoning ``_default_terrain_land_types``
        writes down, one card over.
        """
        colors = ["W", "U", "B", "R", "G"]
        default = self._least_common_opponent_color(player_index)
        self.arm_pending_choice(
            "color_set_choice", player_index,
            card_name=card_name,
            permanent=permanent,
            several=bool(several),
            colors=colors,
            default_colors=[default],
        )

    def _least_common_opponent_color(self, seat: int) -> str:
        """The colour *seat*'s opponents control fewest of, among nontoken
        permanents. Ties break on the printed WUBRG order, so a seeded run
        reproduces."""
        counts = {color: 0 for color in ("W", "U", "B", "R", "G")}
        for other, player in enumerate(self.players):
            if other == seat or player.lost:
                continue
            for perm in self.controlled_by(other):
                if perm.metadata.get("is_token"):
                    continue
                for color in self._effective_colors(perm):
                    if color in counts:
                        counts[color] += 1
        order = list(counts)
        return min(order, key=lambda color: (counts[color], order.index(color)))

    def confirm_color_set_choice(self, player_index: int, colors) -> bool:
        """Answer "become the color or colors of your choice"."""
        return self.resolve_pending_choice(
            "color_set_choice", player_index, colors=colors
        )

    def _resolve_color_set_choice(self, choice: PendingChoice, colors) -> bool:
        """Write the chosen set as this permanent's colour (CR 613 layer 5).

        Refused rather than silently narrowed when the card offered one colour
        and the answer names several — "the color of your choice" is one, and a
        prompt that took two would be a card nobody printed.
        """
        data = choice.data
        wanted = list(colors) if isinstance(colors, (list, tuple)) else [colors]
        symbols = []
        for entry in wanted:
            try:
                symbol = self._normalize_mana_color(entry)
            except ValueError:
                return False
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        if not symbols:
            return False
        if len(symbols) > 1 and not data.get("several"):
            return False
        permanent = data["permanent"]
        self.discard_pending_choice(choice)
        if not self.is_on_battlefield(permanent):
            # It left while the prompt was owed; there is nothing to recolour
            # and the prompt still clears.
            return True
        # A tuple whenever the card offered a set, so layer 5 writes every
        # colour rather than the first — the shape `collect_color_effects`
        # already reads, and a bare symbol otherwise.
        permanent.metadata["color_override"] = (
            tuple(symbols) if data.get("several") else symbols[0]
        )
        self._recalculate_lord_buffs()
        self.log.append(
            f"{permanent.card.name} became {'/'.join(symbols)} "
            f"({data.get('card_name', '')})"
        )
        return True

    def _default_color_set_choice(self, choice: PendingChoice) -> None:
        self._resolve_color_set_choice(choice, choice.data.get("default_colors") or [])

    # -- Buying a revealed draw out of a hand (Zur's Weirding) --------------

    def offer_revealed_draw_buyout(
        self,
        drawing_seat: int,
        *,
        card_name: str,
        source_name: str,
        queued_draws: int,
        exclude_sources: tuple[int, ...],
        queued_exclude_sources: tuple[int, ...] = (),
        remaining_seats: list[int] | None = None,
    ) -> None:
        """Put "any other player may pay 2 life" to the next seat that owes an
        answer, or finish the replaced draw when nobody is left.

        CR 101.4: the offer goes round **every other player** in turn order
        starting with the active player, and the first to pay ends the round.
        The rest of the round rides in the prompt's own data rather than in a
        loop here, because a human seat's answer arrives on a later request and
        a loop would have to survive that; the resolver arms the next seat.

        A seat that has left the game is nobody (CR 800.4a), and it is filtered
        on every pass rather than once, so a player who lost while the poll was
        open is not asked.
        """
        from ...replacements import REVEAL_DRAW_LIFE_COST

        if remaining_seats is None:
            count = len(self.players)
            active = self.active_player_index or 0
            remaining_seats = sorted(
                (
                    index for index, player in enumerate(self.players)
                    if index != drawing_seat and not player.lost
                ),
                key=lambda index: ((index - active) % count, index),
            )
        live = [
            seat for seat in remaining_seats
            if 0 <= seat < len(self.players) and not self.players[seat].lost
        ]
        if not live:
            self._finish_revealed_draw(
                drawing_seat, bought=False,
                queued_draws=queued_draws,
                exclude_sources=exclude_sources,
                queued_exclude_sources=queued_exclude_sources,
                source_name=source_name,
            )
            return
        self.arm_pending_choice(
            "revealed_draw_buyout", live[0],
            card_name=source_name,
            revealed_name=card_name,
            drawing_seat=drawing_seat,
            drawing_player=self.players[drawing_seat].name,
            life=REVEAL_DRAW_LIFE_COST,
            _remaining_seats=live[1:],
            _queued_draws=int(queued_draws),
            _exclude_sources=tuple(exclude_sources),
            _queued_exclude_sources=tuple(queued_exclude_sources),
        )

    def confirm_revealed_draw_buyout(self, player_index: int, accept: bool = True) -> bool:
        """Answer "any other player may pay 2 life" for the revealed card."""
        return self.resolve_pending_choice(
            "revealed_draw_buyout", player_index, accept=bool(accept)
        )

    def _resolve_revealed_draw_buyout(self, choice: PendingChoice, accept: bool) -> bool:
        """Pay and bin the revealed card, or decline and pass the offer on."""
        data = choice.data
        player = self.players[choice.player_index]
        life = int(data.get("life", 2))
        drawing_seat = int(data["drawing_seat"])
        self.discard_pending_choice(choice)
        # CR 119.4: a player may pay N life only with at least N to pay. Down to
        # exactly 0 is legal and the state-based check that follows ends the
        # game -- this is a refusal to pay what is not there.
        if accept and player.life >= life:
            player.life -= life
            self.log.append(
                f"{player.name} paid {life} life ({data.get('card_name', '')})"
            )
            self._finish_revealed_draw(
                drawing_seat, bought=True,
                queued_draws=int(data.get("_queued_draws", 0)),
                exclude_sources=tuple(data.get("_exclude_sources") or ()),
                queued_exclude_sources=tuple(
                    data.get("_queued_exclude_sources") or ()
                ),
                source_name=str(data.get("card_name", "")),
            )
            return True
        self.log.append(
            f"{player.name} declined to pay {life} life "
            f"({data.get('card_name', '')})"
        )
        self.offer_revealed_draw_buyout(
            drawing_seat,
            card_name=str(data.get("revealed_name", "")),
            source_name=str(data.get("card_name", "")),
            queued_draws=int(data.get("_queued_draws", 0)),
            exclude_sources=tuple(data.get("_exclude_sources") or ()),
            queued_exclude_sources=tuple(data.get("_queued_exclude_sources") or ()),
            remaining_seats=list(data.get("_remaining_seats") or ()),
        )
        return True

    def _default_revealed_draw_buyout(self, choice: PendingChoice) -> None:
        """The stated policy for a seat nobody is asking: **decline**.

        Not a valuation (``engine/ai_valuation.py`` is where one would go) but a
        policy, and one the shape of the offer forces: this is put to every
        other player on *every* draw for as long as the enchantment is on the
        battlefield, so a default that paid would spend a seat's whole life
        total inside a few turns of somebody else's draw steps. Declining costs
        nothing and leaves the card doing to a table of humans what it does.
        """
        self._resolve_revealed_draw_buyout(choice, False)

    def _finish_revealed_draw(
        self, drawing_seat: int, *, bought: bool, queued_draws: int,
        exclude_sources: tuple[int, ...],
        queued_exclude_sources: tuple[int, ...],
        source_name: str,
    ) -> None:
        """The two branches the poll ends in, plus the draws queued behind it.

        "If a player does, put that card into its owner's graveyard. Otherwise,
        that player draws a card." The card has been on top of the library all
        along (see the interceptor), so the payment moves it and a declined
        offer simply lets the draw happen -- through the seam, carrying this
        source in ``exclude_sources``, because CR 614.5 gives a replacement one
        opportunity per event and the draw this one just created must not be
        replaced by it again.
        """
        player = self.players[drawing_seat]
        if bought and player.library:
            card = player.library.pop(0)
            self.put_card_into_graveyard(player, card)
            self.log.append(
                f"{card.name} was put into {player.name}'s graveyard "
                f"({source_name})"
            )
        elif not bought:
            self._draw_with_replacements(
                player, 1, exclude_sources=exclude_sources
            )
        if queued_draws > 0:
            # CR 121.2: the draws behind this one are their own events and get
            # their own trip through the seam -- including this replacement
            # again, which is what a two-card draw under Zur's Weirding is.
            self._draw_with_replacements(
                player, queued_draws, exclude_sources=queued_exclude_sources
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
        choice, r["hand_indices"], bool(r.get("to_bottom")),
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
    blocked_detail="choose which permanents to tap before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # "For each creature tapped this way, that player chooses…" (Raiding Party)
    # is a later step of the same resolution, and what it walks is exactly what
    # this prompt records — so the loop it is a step of has to stop until every
    # seat has answered (CR 608.2, CR 608.2e).
    #
    # Siege Striker, the other card that arms this, needs neither: its boost is
    # applied by this choice's own resolver, which is why the two printed
    # sentences fuse into one instruction there. Suspending costs it nothing —
    # the prompt is the last step of what armed it — and one prompt shared by
    # both cards is cheaper than two that differ by a flag.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish
    # before the sentence behind it can read what was tapped, and the stated
    # default is taken where the effect stands.
    default_at_arm=True,
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
    "color_set_choice",
    resolve=lambda game, choice, r: game._resolve_color_set_choice(
        choice, r.get("colors")
    ),
    default=lambda game, choice: game._default_color_set_choice(choice),
    action="color_set_choice_confirm",
    prompt_key="color_set_choice",
    blocked_detail="choose the colour or colours before other actions",
    spectator_visible=True,
    hidden_for_ai=False,
    # The colour is the whole of what this resolution does; nothing after it in
    # the same trigger reads the answer, so the loop has nothing to wait for.
    default_at_arm=True,
)

register_choice(
    "revealed_draw_buyout",
    resolve=lambda game, choice, r: game._resolve_revealed_draw_buyout(
        choice, r["accept"]
    ),
    default=lambda game, choice: game._default_revealed_draw_buyout(choice),
    action="revealed_draw_buyout_confirm",
    prompt_key="revealed_draw_buyout",
    blocked_detail="answer the revealed-card offer before other actions",
    spectator_visible=True,
    hidden_for_ai=False,
    # The answer decides what happens to the card the drawing player is about to
    # draw -- and whether the seat behind you is asked at all -- so the replaced
    # draw genuinely stops here.
    suspends=True,
    # A non-interactive seat never queues it: the draw it replaced has to
    # finish, so the stated default is taken where the offer stands.
    default_at_arm=True,
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
    resolve=lambda game, choice, r: game._resolve_optional_pay(
        choice, r["accept"], r.get("option"),
    ),
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
    "draw_up_to",
    resolve=lambda game, choice, r: game._resolve_draw_up_to(choice, r["number"]),
    default=lambda game, choice: game._default_draw_up_to(choice),
    action="draw_up_to_confirm",
    prompt_key="draw_up_to",
    blocked_detail="say how many cards you draw before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    # "Each player may draw up to two cards. **For each card less than two a
    # player draws this way**, that player gains 2 life." (Truce.) The sentence
    # behind this one is sized from every seat's answer, so nothing in the
    # resolution may run until the last of them is given — the same reason the
    # discard prompt beside it suspends (CR 608.2).
    suspends=True,
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
    "bid_life",
    resolve=lambda game, choice, r: game._resolve_bid_life(choice, r.get("number")),
    default=lambda game, choice: game._default_bid_life(choice),
    action="bid_life_confirm",
    # Passing is a second *answer*, not a way around the prompt -- the same
    # shape a search's "fail to find" takes. It has to be an action of its own
    # because the bid is a number and there is no number that means "no".
    also_answers=("bid_life_pass",),
    prompt_key="bid_life",
    blocked_detail="answer the bidding before other actions",
    # The spell is resolving and the board is mid-effect: whoever wins has not
    # lost the life or taken the creature yet, so nobody should be acting on
    # what they can see (CR 608.2).
    blocks_every_seat=True,
    # The offer is made in the open -- every seat can see what the standing bid
    # is, which is the whole of what makes the next offer a decision.
    spectator_visible=True,
    # A non-interactive seat never queues it: the auction is one resolution and
    # it has to finish, so the stated default (pass) is taken where the offer
    # stands. Without this an AI or headless seat would hold the spell on the
    # stack for the rest of the game.
    default_at_arm=True,
    # The two printed sentences behind the bidding -- the life loss and the
    # control change -- are performed by the *last* answer, so no later step of
    # this resolution may run before it (CR 608.2).
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
    "retarget_choice",
    resolve=lambda game, choice, r: game._resolve_retarget_choice(
        choice, r.get("target_index")
    ),
    default=lambda game, choice: game._default_retarget_choice(choice),
    action="retarget_choice_confirm",
    prompt_key="retarget_choice",
    blocked_detail="choose the spell's new target before other actions",
    # The step behind this one in the same sentence writes the answer onto the
    # stack item, so Deflection's resolution is not over until it exists
    # (CR 608.2).
    suspends=True,
    # A non-interactive seat never queues it, for ``player_choice``'s reason:
    # the resolution has to finish, and the stated default is taken where the
    # effect stands.
    default_at_arm=True,
    # What a spell on the stack targets is public (CR 601.2c is announced in
    # the open), so a seatless viewer may see the question.
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
    "permanent_set_choice",
    resolve=lambda game, choice, r: game._resolve_permanent_set_choice(
        choice, r.get("permanent_ids") or []
    ),
    default=lambda game, choice: game._default_permanent_set_choice(choice),
    action="permanent_set_choice_confirm",
    prompt_key="permanent_set_choice",
    blocked_detail="choose the permanents for the resolving effect before other actions",
    # "Then destroy all Plains that weren't chosen this way by any player" is a
    # later step of the same resolution and reads exactly what this records, so
    # nothing may run past it (CR 608.2). The iteration behind it arms the next
    # one, which is how a chain of decisions stays one resolution.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands.
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    "flip_again",
    resolve=lambda game, choice, r: game._resolve_flip_again(
        choice, bool(r.get("accept", True))
    ),
    default=lambda game, choice: game._default_flip_again(choice),
    action="flip_again_confirm",
    prompt_key="flip_again",
    blocked_detail="decide whether to flip again before other actions",
    # The answer is whether the *rest of this resolution* happens at all, so
    # nothing may run past it (CR 608.2) — and the round it starts arms the next
    # offer, which is how a chain of decisions stays one resolution.
    suspends=True,
    # A non-interactive seat never queues it: the stated default is to stop, and
    # taking it where the offer stands is what keeps AI and headless play from
    # holding a resolution open on a decision nobody will make.
    default_at_arm=True,
    # Both players' life totals are public, and so is whose decision it is.
    hidden_for_ai=False,
    spectator_visible=True,
)

register_choice(
    "exile_from_hand_choice",
    resolve=lambda game, choice, r: game._resolve_exile_from_hand_choice(
        choice, r.get("hand_index")
    ),
    default=lambda game, choice: game._default_exile_from_hand_choice(choice),
    action="exile_from_hand_confirm",
    prompt_key="exile_from_hand_choice",
    blocked_detail="choose a card to exile before other actions",
    # The sentence behind this one reads what was exiled ("you may cast that
    # card for as long as it remains exiled"), so nothing after it may run
    # until it is answered (CR 608.2).
    suspends=True,
    # …and a non-interactive seat therefore never queues it: the rest of the
    # activation — the charge counter and the mana note — has to finish, which
    # is the same reason `cast_choice` and `pay_life_to_save` take their default
    # where the offer stands.
    default_at_arm=True,
    # A hand is hidden (CR 400.2), so the options are the chooser's alone.
    hidden_for_ai=False,
)

register_choice(
    "library_pile_split",
    resolve=lambda game, choice, r: game._resolve_library_pile_split(
        choice, r.get("first_pile")
    ),
    default=lambda game, choice: game._default_library_pile_split(choice),
    action="library_pile_split_confirm",
    prompt_key="library_pile_split",
    blocked_detail="divide the piles before other actions",
    # Answering arms the controller's choice, which is a later step of this
    # same resolution (CR 608.2).
    suspends=True,
    # …and a non-interactive divider answers at once, or the resolution stops
    # on a prompt nobody owes an answer to.
    default_at_arm=True,
)

register_choice(
    "pile_exile_choice",
    resolve=lambda game, choice, r: game._resolve_pile_exile_choice(
        choice, r.get("pile_index")
    ),
    default=lambda game, choice: game._default_pile_exile_choice(choice),
    action="pile_exile_confirm",
    prompt_key="pile_exile_choice",
    blocked_detail="choose a pile to exile before other actions",
    suspends=True,
    default_at_arm=True,
)

register_choice(
    "pile_search",
    resolve=lambda game, choice, r: game._resolve_pile_search(
        choice, r.get("pile_index")
    ),
    default=lambda game, choice: game._default_pile_search(choice),
    action="pile_search_confirm",
    prompt_key="pile_search",
    blocked_detail="search the pile before other actions",
    suspends=True,
    default_at_arm=True,
)

register_choice(
    "library_cycle_offer",
    resolve=lambda game, choice, r: game._resolve_library_cycle_offer(
        choice, bool(r.get("accept"))
    ),
    default=lambda game, choice: game._default_library_cycle_offer(choice),
    action="library_cycle_confirm",
    prompt_key="library_cycle_offer",
    blocked_detail="answer the library cycle before other actions",
    # Answering arms either the next round or the shuffle that ends the card,
    # so nothing after it may run until it is answered (CR 608.2).
    suspends=True,
    # …and a non-interactive seat therefore takes its default the moment the
    # offer is armed, or the resolution would stop on a prompt nobody answers.
    default_at_arm=True,
)

register_choice(
    "linked_exile_return",
    resolve=lambda game, choice, r: game._resolve_linked_exile_return(
        choice, r.get("entry_index")
    ),
    default=lambda game, choice: game._default_linked_exile_return(choice),
    action="linked_exile_return_confirm",
    prompt_key="linked_exile_return",
    blocked_detail="choose a card to return before other actions",
    # The prompt refuses every other action, so a seat that never answers it
    # freezes the game. A non-interactive seat therefore takes its default the
    # moment it is armed, exactly as the exile that filled the pile does —
    # ``auto_resolve_pending_choices`` drains only the kinds a caller lists,
    # and a blocking prompt left off that list is a headless run that stops.
    default_at_arm=True,
    # The pile is face down (CR 406.3) and only its owner may look, so the
    # options are the chooser's alone — exactly the hand pick's reason.
    hidden_for_ai=False,
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
    "text_change_vocabulary",
    resolve=lambda game, choice, r: game._resolve_text_change_vocabulary(
        choice, r.get("mode")
    ),
    default=lambda game, choice: game._default_text_change_vocabulary(choice),
    action="text_change_vocabulary_confirm",
    prompt_key="text_change_vocabulary",
    blocked_detail="choose which kind of word to replace before other actions",
    # **Not** ``suspends``: the rewrite *is* the answer and it is the last step
    # of the spell, so nothing behind it reads a record. ``blocked_detail`` is
    # what makes the game wait (CR 608.2).
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands.
    default_at_arm=True,
    # A text change is a public change to a public object (CR 612), so a
    # seatless viewer may see the question.
    spectator_visible=True,
)

register_choice(
    "aggregate_sacrifice",
    resolve=lambda game, choice, r: game._resolve_aggregate_sacrifice(
        choice, r.get("permanent_ids") or []
    ),
    default=lambda game, choice: game._default_aggregate_sacrifice(choice),
    action="aggregate_sacrifice_confirm",
    prompt_key="aggregate_sacrifice",
    blocked_detail="choose what to sacrifice before other actions",
    # **Not** ``suspends``: the sacrifice *is* the answer and it is the last
    # step of the offer's accept branch, so nothing behind it reads a record.
    # ``blocked_detail`` is what makes the game wait (CR 608.2), which it must —
    # the creatures are still on the battlefield until the answer arrives.
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands.
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    "library_end_choice",
    resolve=lambda game, choice, r: game._resolve_library_end_choice(
        choice, bool(r.get("to_bottom"))
    ),
    default=lambda game, choice: game._default_library_end_choice(choice),
    action="library_end_confirm",
    prompt_key="library_end_choice",
    blocked_detail="choose which end of the library before other actions",
    # **Not** ``suspends``: the move *is* the answer and it is the last step of
    # the sentence, so nothing behind it reads the record — which is the whole
    # of what that field claims. ``blocked_detail`` is what makes the game wait
    # (CR 608.2), and the permanent is still on the battlefield until the answer
    # arrives, which is why no action may run in between.
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands.
    default_at_arm=True,
    # Which end of a library a card went to is public (both ends of CR 401.1's
    # ordered zone are announced), so a seatless viewer may see the question.
    spectator_visible=True,
)

register_choice(
    "graveyard_pile_choice",
    resolve=lambda game, choice, r: game._resolve_graveyard_pile_choice(
        choice, r.get("seat")
    ),
    default=lambda game, choice: game._default_graveyard_pile_choice(choice),
    action="graveyard_pile_confirm",
    prompt_key="graveyard_pile_choice",
    blocked_detail="choose which graveyard to exile from before other actions",
    # The pick this arms is a later step of the same resolution and reads the
    # answer, so nothing may run past it (CR 608.2). The chain is what makes
    # both prompts one resolution.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands.
    default_at_arm=True,
    # Whose graveyard holds what is public (CR 400.2 makes a graveyard an open
    # zone), so a seatless viewer may see the question.
    spectator_visible=True,
)

register_choice(
    "graveyard_exile_pick",
    resolve=lambda game, choice, r: game._resolve_graveyard_exile_pick(
        choice, r.get("graveyard_indices")
    ),
    default=lambda game, choice: game._default_graveyard_exile_pick(choice),
    action="graveyard_exile_confirm",
    prompt_key="graveyard_exile_pick",
    blocked_detail="choose the cards to exile from that graveyard before other actions",
    blocks_every_seat=True,
    # "…**If you do**, you gain 1 life for each card exiled this way" is a
    # later step of the same resolution and reads what this answer records, so
    # that step must not run before the answer exists.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands. That is also what
    # keeps AI and headless play free of the suspension above.
    default_at_arm=True,
    # A graveyard is a public zone (CR 400.2), so a seatless viewer sees the
    # pile the chooser is looking at — unlike every hand pick in this file.
    spectator_visible=True,
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
    "choose_card_name",
    resolve=lambda game, choice, r: game._resolve_choose_card_name(
        choice, r["card_name"]
    ),
    default=lambda game, choice: game._default_choose_card_name(choice),
    action="choose_card_name_confirm",
    prompt_key="choose_card_name",
    blocked_detail="name a card before other actions",
    # The sentences behind this read the name, and one of them mills: a seat
    # that saw the milled card before naming would be choosing with information
    # the card does not give them (CR 608.2, CR 117.3b).
    suspends=True,
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
    "graveyard_pick_for_price",
    resolve=lambda game, choice, r: game._resolve_graveyard_pick_for_price(
        choice, r["graveyard_index"]
    ),
    default=lambda game, choice: game._default_graveyard_pick_for_price(choice),
    action="graveyard_pick_for_price_confirm",
    prompt_key="graveyard_pick_for_price",
    blocked_detail="choose a card in that graveyard before other actions",
    # A graveyard is a public zone (CR 400.2), so a spectator sees the offer
    # exactly as the choosing seat does.
    spectator_visible=True,
    hidden_for_ai=False,
    # The sentence after this one reads the pick, and the one after that reads
    # the whole set of them: nothing behind this prompt may run until it is
    # answered (CR 608.2).
    suspends=True,
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
        choice, r.get("opponent_index"), r.get("mana_color"), r.get("card_name"),
        r.get("land_types"), r.get("creature_type"), r.get("land_type"),
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
    "modal_mode_targets",
    resolve=lambda game, choice, r: game._resolve_modal_mode_targets(
        choice, r.get("permanent_ids")
    ),
    default=lambda game, choice: game._default_modal_mode_targets(choice),
    action="modal_mode_targets_confirm",
    prompt_key="modal_mode_targets",
    blocked_detail=(
        "name the targets for the mode your opponent chose before other actions"
    ),
    # The other half of `opponent_mode_choice` below, and every flag on it is
    # here for that flag's own reason: this is still inside CR 601.2i's
    # announcement, so nobody acts until it is answered, and a non-interactive
    # caster takes the stated default where the offer stands rather than
    # holding the cast open forever.
    blocks_every_seat=True,
    default_at_arm=True,
    # A spell's targets are announced in the open (CR 601.2c).
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "opponent_mode_choice",
    resolve=lambda game, choice, r: game._resolve_opponent_mode_choice(
        choice, r.get("mode_index")
    ),
    default=lambda game, choice: game._default_opponent_mode_choice(choice),
    action="opponent_mode_choice_confirm",
    prompt_key="opponent_mode_choice",
    blocked_detail=(
        "an opponent is choosing that spell's mode; wait for the answer"
    ),
    # CR 601.2i finishes the cast before anyone may respond, and CR 700.2e puts
    # this choice inside that announcement — so **nobody** acts until it is
    # answered, the caster included. That is what `blocks_every_seat` says, and
    # it is stronger than the priority hold the detail above already implies.
    blocks_every_seat=True,
    # **Not** ``suspends``. That flag stops the resumable loop an effect was a
    # step of, and this prompt is armed inside an *announcement*: no effect is
    # running, the spell has not resolved, and there is no loop behind it. What
    # holds the game is the block above — CR 601.2i finishes the cast, and then
    # nobody has priority until the mode is known.
    # A non-interactive chooser never queues it: the cast has to finish, and the
    # stated default (the first printed mode) is taken where the offer stands.
    # Without this an AI or headless seat would hold a cast open forever.
    default_at_arm=True,
    # A spell's modes are announced in the open (CR 601.2b), and so is whose
    # choice this is.
    spectator_visible=True,
    hidden_for_ai=False,
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

register_choice(
    "return_from_graveyard_instead_of_draw",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="graveyard_return_draw_confirm",
    prompt_key="return_from_graveyard_instead_of_draw",
    blocked_detail=(
        "choose which card comes back from your graveyard (Forbidden Crypt) "
        "before other actions"
    ),
    # The draw that armed this was consumed so that both the answer and the
    # default run through one resolver, and the draws queued behind it are the
    # resolver's own business - so nothing is waiting on the answer to carry on,
    # exactly as for the four offers above.
    default_at_arm=True,
    spectator_visible=True,
    hidden_for_ai=False,
)
