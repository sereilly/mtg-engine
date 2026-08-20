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
from ...pending_choices import CHOICE_SPECS, PendingChoice, register_choice, spec_for
from ...replacement_choices import pending_choices_for
from ...resumption import resume_after_answer
from ...mana_payment import plan_payment, untapped_mana_lands
from ...search_filters import search_matches
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
        self.pending_choices.append(choice)
        if spec.suspends:
            # Nothing is waiting on a default taken inline above — it already
            # happened. A queued choice is different: the steps behind it in this
            # resolution have not run, and running them now would let them see a
            # board the answer has not shaped yet (Opt drawing the card its own
            # scry has not arranged). Stop the loop; answering resumes it.
            self.effect_suspended = True
        return choice

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

    def resolve_pending_choice(self, kind: str, player_index: int, **response) -> bool:
        """Answer the oldest pending choice of *kind* owed by *player_index*.

        False means there was nothing to answer or the answer was rejected; a
        rejected answer leaves the prompt queued, so a malformed request can
        never silently drop one."""
        choice = self.pending_choice_of(kind, player_index)
        if choice is None:
            return False
        spec = spec_for(kind)
        if not spec.suspends:
            return bool(spec.resolve(self, choice, response))
        # The suspension ends *before* the answer is applied, never after:
        # applying it can arm the next prompt, and clearing afterwards would
        # resume straight through that one.
        self.effect_suspended = False
        if not spec.resolve(self, choice, response):
            self.effect_suspended = True  # rejected — still owed, still waiting
            return False
        resume_after_answer(self)
        return True

    def take_choice_default(self, choice: PendingChoice) -> None:
        """Apply the deterministic answer a non-interactive seat gives."""
        spec = spec_for(choice.kind)
        if not spec.suspends:
            spec.default(self, choice)
            return
        self.effect_suspended = False
        spec.default(self, choice)
        resume_after_answer(self)

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
        caster = self.players[choice.player_index]
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
        # "…, reveal it/those cards, …" (CR 701.20): a search armed with the
        # printed word shows each find's face to every player. Accumulated on
        # the choice and recorded once when the search ends, because "those
        # cards" is one showing — a Cultivate that finds twice is one reveal.
        if choice.data.get("reveal"):
            choice.data.setdefault("revealed_names", []).append(card.name)
        # "a card named A **and/or** a card named B" (Alpine Houndmaster): each
        # printed name is one find. The name just used is dropped, so a library
        # holding two copies of the first card cannot answer both finds with it
        # — the union is what the *picker* may offer, not what one search may
        # take twice.
        among = list((choice.data.get("restrictions") or {}).get("named_among") or ())
        if among:
            from ...search_filters import name_key

            remaining_names = [n for n in among if name_key(n) != name_key(card.name)]
            choice.data["restrictions"] = {
                **(choice.data.get("restrictions") or {}),
                "named_among": remaining_names,
            }
        # "…put it onto the battlefield, then shuffle" (Garruk, Unleashed's
        # emblem) — the found card enters play instead of the hand. The
        # destination was fixed when the search was armed; the wire cannot
        # promote a tutor-to-hand into a tutor-to-battlefield.
        # A counted search consumes its destinations in the printed order; a
        # single-find one has the fixed `destination` it has always had.
        remaining = list(choice.data.get("destinations") or ())
        tapped_flags = list(choice.data.get("tapped") or ())
        if remaining:
            destination = remaining.pop(0)
            enters_tapped = bool(tapped_flags.pop(0)) if tapped_flags else False
        else:
            destination = choice.data.get("destination", "hand")
            # The single-find spelling of the same fact the destination list
            # carries per entry (Fabled Passage).
            enters_tapped = bool(choice.data.get("enters_tapped"))
        if destination == "battlefield":
            from ...models import Permanent as _Permanent

            found = _Permanent(card=card, tapped=enters_tapped)
            self._put_permanent_onto_battlefield(choice.player_index, found, None)
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
        else:
            self.put_card_into_hand(caster, card)
        self.log.append(
            f"{caster.name} searched {zone} and put {card.name} "
            + ("onto the battlefield" if destination == "battlefield" else "into hand")
        )
        # More finds owed: the prompt stays, minus the destination just used, and
        # the library is *not* shuffled yet — CR 701.23h shuffles when the search
        # is over, and shuffling between two finds of one search would hide the
        # second from the player who is still looking.
        if remaining:
            choice.data["destinations"] = remaining
            choice.data["tapped"] = tapped_flags
            return True
        # Only a library search shuffles (CR 701.23h, and the printed "If you
        # search your library this way, shuffle"): a graveyard is an open zone,
        # and randomising a library the player did not search would destroy
        # information they were entitled to keep.
        if zone == "library":
            random.shuffle(caster.library)
        self._record_search_reveal(choice)
        self.discard_pending_choice(choice)
        return True

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
        from ...ai_policy import choose_search_card

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
        answer and leaves the prompt queued, matching the exile search."""
        amount = int(choice.data.get("amount", 0))
        filt = dict(choice.data.get("filter") or {})
        ids = [pid for pid in (permanent_ids or []) if isinstance(pid, int)]
        if len(ids) != len(permanent_ids or []) or len(set(ids)) != len(ids):
            return False
        if len(ids) > amount:
            return False
        chosen = []
        for pid in ids:
            perm = self.permanent_by_id(pid)
            if perm is None or not permanent_matches_filter(perm, filt):
                return False
            chosen.append(perm)
        for perm in chosen:
            self.become_untapped(perm)
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
        and tapped ones because untapping an untapped land is a wasted pick."""
        amount = int(choice.data.get("amount", 0))
        filt = dict(choice.data.get("filter") or {})
        own = [
            perm for perm in self.controlled_by(choice.player_index)
            if perm.tapped and permanent_matches_filter(perm, filt)
        ]
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
        return [
            index for index, card in enumerate(hand)
            if card_matches_any(card, alternatives)
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
        self._draw_that_many_after_discard(choice, len(chosen))
        return True

    def _draw_that_many_after_discard(self, choice: PendingChoice, discarded: int) -> None:
        """"…then draw that many cards" — the follow-on the discard prompt was
        armed with (Kinetic Augur).

        Here rather than in a later instruction because "that many" is the
        prompt's own answer: nothing downstream of a queued choice can read a
        number the player has not given yet. Discarding nothing draws nothing,
        which is what "that many" says.
        """
        if not choice.data.get("draw_that_many") or discarded <= 0:
            return
        player = self.players[choice.player_index]
        drawn = self._draw_with_replacements(player, discarded)
        self.log.append(f"{player.name} drew {drawn} card(s) for the cards discarded")

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
        return True

    def _default_revealed_hand_pick(self, choice: PendingChoice) -> None:
        """A non-interactive caster takes the costliest legal card.

        A stated policy, like the up-to-N maximum and the modal first mode: mana
        value is the one ranking every card in the pool answers, and a card that
        wants a cleverer pick needs a valuation rather than a special case here.
        """
        legal = list(choice.data.get("legal_indices") or [])
        victim_index = int(choice.data["victim_index"])
        if legal and 0 <= victim_index < len(self.players):
            hand = self.players[victim_index].hand
            legal.sort(key=lambda i: (-(hand[i].cmc if i < len(hand) else 0), i))
            self._apply_revealed_hand_fate(choice, victim_index, legal[0])
        self.discard_pending_choice(choice)

    def _apply_revealed_hand_fate(
        self, choice: PendingChoice, victim_index: int, hand_index: int
    ) -> bool:
        """What happens to the chosen card. One place, because the family varies
        only here — Duress discards it, and the exile ending arrives with the
        card that needs it."""
        from ...handlers.zones import _resolve_one_discard

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
        held = list(source.metadata.get("exiled_until_leaves") or ())
        held.append({"owner_index": victim_index, "card": card})
        source.metadata["exiled_until_leaves"] = held
        self.log.append(
            f"{card.name} is exiled until {source.card.name} leaves the battlefield"
        )
        return True

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
        self._draw_that_many_after_discard(choice, discarded)

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

    def _default_mana_payment(self, choice: PendingChoice) -> None:
        controller = self.players[choice.player_index]
        available = sum(controller.mana_pool.get(s, 0) for s in controller.mana_pool)
        self._resolve_mana_payment(choice, available >= int(choice.data["amount"]))

    def _resolve_mana_payment(self, choice: PendingChoice, pay: bool) -> bool:
        controller = self.players[choice.player_index]
        data = choice.data
        amount = int(data["amount"])
        target = data.get("stack_item")
        counter_card = data.get("counter_card")
        available = sum(controller.mana_pool.get(s, 0) for s in controller.mana_pool)
        if pay and available >= amount:
            remaining = amount
            for sym in list(controller.mana_pool):
                while remaining > 0 and controller.mana_pool.get(sym, 0) > 0:
                    controller.mana_pool[sym] -= 1
                    remaining -= 1
            name = target.card.name if target is not None else "the spell"
            self.log.append(f"{controller.name} paid {{{amount}}}; {name} is not countered")
        else:
            # Declined or unable to pay: the spell is countered and Power Sink's rider
            # (tap all the controller's lands, drain their mana) applies.
            if target is not None and target in self.stack:
                self.stack.remove(target)
                if target.is_copy:
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

    def _balance_remove(self, player_index: int, land_indices, creature_indices, hand_indices) -> bool:
        """Remove the chosen lands/creatures (to graveyard) and hand cards (discard)
        for one player's Balance plan. Validates the counts against the plan."""
        choice = self.pending_choice_of("balance", player_index)
        if choice is None:
            return False
        return self._resolve_balance(choice, land_indices, creature_indices, hand_indices)

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
        )

    def _player_can_pay_optional(self, player, entry: dict) -> bool:
        """CR 601.2h, for an optional cost: whether it *could* be paid."""
        return self._optional_pay_plan(player, entry) is not None

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
        plan = self._optional_pay_plan(player, entry)
        if plan is None:
            return
        for symbol, amount in plan.from_pool.items():
            player.mana_pool[symbol] = int(player.mana_pool.get(symbol, 0)) - amount
        for land in plan.tapped:
            self.become_tapped(land)
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
        candidates = self._enumerate_targets(
            player_index, card, spec, for_cast=False,
            source_permanent=getattr(context, "source_permanent", None),
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

    def _run_optional_branch(self, entry: dict, key: str) -> bool:
        """Execute an optional-pay entry's instruction branch, if it has one.

        Returns whether anything ran, so the legacy life/draw/damage fields stay
        the fallback for entries that predate instruction branches.
        """
        steps = entry.get(key) or ()
        context = entry.get("_context")
        if not steps or context is None:
            return False
        for step in steps:
            self._execute_oracle_instruction(step, context)
        return True

    def _resolve_mode_choice(self, choice: PendingChoice, mode_index: int) -> bool:
        """Run the chosen mode of a modal triggered ability (Trufflesnout,
        Elder Gargaroth). The modes travel as instructions with the resolution
        context they belong to, the optional-pay shape — an index outside the
        list is refused and the prompt stays owed."""
        modes = tuple(choice.data.get("_modes") or ())
        context = choice.data.get("_context")
        if not (0 <= mode_index < len(modes)) or context is None:
            return False
        self.discard_pending_choice(choice)
        labels = choice.data.get("labels") or ()
        if 0 <= mode_index < len(labels):
            self.log.append(
                f"{choice.data.get('card_name', 'Ability')}: chose \"{labels[mode_index]}\""
            )
        self._execute_oracle_instruction(modes[mode_index], context)
        self.check_state_based_actions()
        return True

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
            self.log.append(f"{player.name} declined {entry['card_name']}'s pay-for-life trigger")

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
        return self._resolve_optional_pay(choice, accept)

    def _resolve_optional_pay(self, choice: PendingChoice, accept: bool) -> bool:
        player_index = choice.player_index
        entry = choice.data
        self.discard_pending_choice(choice)
        if accept and self._player_can_pay_optional(self.players[player_index], entry):
            self._pay_optional(player_index, entry)
        else:
            self._apply_optional_pay_decline(player_index, entry)
        # The trigger ability that raised this prompt was held on the stack (human
        # priority path); now that the choice is made, it leaves the stack.
        self._remove_optional_pay_stack_item(entry)
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
        floating = plan_payment(player.mana_pool, (), entry.get("cost") or {})
        self.discard_pending_choice(choice)
        if floating is not None:
            self._pay_optional(choice.player_index, entry)
        elif int(entry.get("damage", 0) or 0) > 0:
            self._apply_optional_pay_decline(choice.player_index, entry)
        self._remove_optional_pay_stack_item(entry)

    def _remove_optional_pay_stack_item(self, entry: dict) -> None:
        """Remove the triggered-ability stack object an optional-pay prompt was linked
        to, now that the prompt has been answered. No-op for entries created on the
        headless/auto path (where the ability already left the stack)."""
        stack_item = entry.get("_stack_item")
        if stack_item is not None and stack_item in self.stack:
            self.stack.remove(stack_item)

    def auto_resolve_pending_optional_pays(self, only_player_index: int | None = None) -> None:
        """Pay every pending optional "pay {N}" trigger when able — the
        deterministic default used for AI players and headless simulation."""
        self.auto_resolve_pending_choices(only_player_index=only_player_index, kinds=("optional_pay",))

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

    def _resolve_sacrifice_inline(self, player_index: int, count: int, filter: dict | None, exclude, reason: str, on_short) -> None:
        """Sacrifice ``count`` of the player's permanents with the deterministic
        heuristic (permanents whose death loses the game are kept for last)."""
        player = self.players[player_index]
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
    ) -> None:
        """Force a player to sacrifice ``count`` permanents matching the filter
        payload ``filter``. A human seat is prompted to choose which; AI /
        headless play resolves it inline. Multiple calls to the same player
        during one step accumulate onto the existing prompt (e.g. two
        combat-damage events feeding Lich).

        ``filter`` has no default. An empty payload is a legal value meaning "any
        permanent", but it has to be written down: a caller that simply forgot
        the noun phrase would otherwise sacrifice more widely than the card
        prints, and defaulting is how that stays invisible."""
        player = self.players[player_index]
        if not self._sacrifice_candidate_indices(player, filter, exclude):
            self._apply_sacrifice_shortfall(player_index, count, on_short, reason)
            return
        queued = self.pending_choice_of("sacrifice", player_index)
        if queued is not None:
            if queued.data["filter"] == filter and queued.data["exclude"] is exclude:
                queued.data["count"] += count
            else:
                # A differently-shaped sacrifice is already owed; this one can't be
                # folded into that prompt, so it resolves inline.
                self._resolve_sacrifice_inline(player_index, count, filter, exclude, reason, on_short)
            return
        self.arm_pending_choice(
            "sacrifice", player_index,
            count=count, filter=filter, exclude=exclude, reason=reason, on_short=on_short,
        )

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
        if len(chosen) != need or any(i not in valid for i in chosen):
            return False
        reason = data["reason"]
        # Resolved before any removal, so no index is held across one.
        removed: list[str] = []
        for perm in [self.permanent_at(player, i) for i in sorted(chosen, reverse=True)]:
            self.sacrifice_permanent(perm)
            removed.append(perm.card.name)
        for name in reversed(removed):
            self.log.append(f"{player.name} sacrificed {name} ({reason})")
        self.discard_pending_choice(choice)
        if count > len(valid):
            self._apply_sacrifice_shortfall(player_index, count - len(valid), data["on_short"], reason)
        self.check_state_based_actions()
        return True

    def _default_sacrifice(self, choice: PendingChoice) -> None:
        self.discard_pending_choice(choice)
        data = choice.data
        self._resolve_sacrifice_inline(
            choice.player_index, int(data["count"]), data["filter"],
            data["exclude"], data["reason"], data["on_short"],
        )

    def auto_resolve_pending_sacrifice(self, only_player_index: int | None = None) -> None:
        """Resolve a pending forced sacrifice inline with the deterministic
        heuristic. Used for AI seats and headless simulation."""
        self.auto_resolve_pending_choices(only_player_index=only_player_index, kinds=("sacrifice",))

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
    "search_library",
    # `zone` defaults so a caller written before the graveyard existed — and the
    # web action, which sends it only when the client picked one — still names
    # the library.
    resolve=lambda game, choice, r: game._resolve_search_library(
        choice, r["library_index"], r.get("zone", "library")
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
)

register_choice(
    "optional_pay",
    resolve=lambda game, choice, r: game._resolve_optional_pay(choice, r["accept"]),
    default=lambda game, choice: game._default_optional_pay(choice),
    action="resolve_optional_pay",
    prompt_key="optional_pay",
    blocked_detail="resolve the pay-for-life trigger before other actions",
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
    "land_type_choice",
    resolve=lambda game, choice, r: game._resolve_land_type(choice, r["land_type"]),
    # The provisional default stamped when the Aura attached is an Island, so
    # taking it again is what a non-interactive controller does.
    default=lambda game, choice: game._resolve_land_type(choice, "island"),
    action="land_type_confirm",
    prompt_key="land_type_choice",
)

register_choice(
    "mana_payment",
    resolve=lambda game, choice, r: game._resolve_mana_payment(choice, r["pay"]),
    default=lambda game, choice: game._default_mana_payment(choice),
    action="confirm_mana_payment",
    prompt_key="mana_payment",
)

register_choice(
    "kudzu_reattach",
    resolve=lambda game, choice, r: game._resolve_kudzu_reattach(choice, r["land_index"]),
    default=lambda game, choice: game._default_kudzu_reattach(choice),
    action="kudzu_reattach_confirm",
    prompt_key="kudzu_reattach",
    # Whether the controller is asked at all is the caller's ``defer_choice``,
    # not the seat's interactivity: a tap that already names the land re-attaches
    # inline. So an armed Kudzu choice queues for every seat and is drained by
    # the auto-resolver, rather than defaulting the moment it is armed.
)

register_choice(
    "face_down_cast",
    resolve=lambda game, choice, r: game._resolve_face_down_cast(choice, r["hand_index"]),
    default=lambda game, choice: game._default_face_down_cast(choice),
    action="face_down_cast_confirm",
    prompt_key="face_down_cast",
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
    resolve=lambda game, choice, r: game._resolve_mode_choice(choice, r["mode_index"]),
    # The first printed mode — a stated policy (like the up-to-N maximum), not
    # a valuation; a card whose AI should ever pick otherwise needs one.
    default=lambda game, choice: game._resolve_mode_choice(choice, 0),
    action="mode_choice_confirm",
    prompt_key="mode_choice",
    blocked_detail="choose a mode for the triggered ability before other actions",
    default_at_arm=True,
    spectator_visible=True,
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
