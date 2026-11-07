"""A permanent, a set of permanents, or a player chosen as an effect resolves.

The general form every new card uses: the effect names a set, one seat picks
from it, and the answer is written into the resolution's ``results`` for the
steps behind it to read (``engine/handlers/permanent_choices.py``). One
permanent, up to N of them, a player, one of a player's casts this turn, and
which permanent receives a loyalty counter — each with the same arm / live /
record / resolve / default shape, the live list re-read at answer time so a
candidate that left in between is no longer an answer. And the two board-wide
pickers: tap any number of creatures, untap up to N permanents.
"""

from __future__ import annotations

from ....handlers._common import apply_temp_pt_boost
from ....handlers._filters import permanent_matches_filter
from ....pending_choices import ChoiceSpec, PendingChoice
from ....pt import pt_change_text
from ....mana_payment import plan_payment
from ....subject_filters import subject_matches


class PermanentChoicesMixin:
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
        from ....subject_filters import subject_matches

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
                f"{source.card.name} gets {pt_change_text(power, toughness)} until end of turn "
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
        from ....oracle_types import (PER_OBJECT_SEAT_RECORDS, TAPPED_THIS_WAY,
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
        from ....subject_filters import subject_matches

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
            # Paid from the board the plan was made over — before anything is
            # untapped, so a permanent this answer untaps is never what pays
            # for its own untapping.
            if not self._pay_planned_cost(
                payer, lambda: self._optional_pay_plan(payer, {"cost": total})
            ):
                return False
        # Untapped together: what the untaps give back (Tawnos's Coffin, CR 610.3)
        # enters in one event (CR 610.3d, 603.6a).
        with self.entering_together():
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
        the dearest first (``ai_prompt_picks.untap_up_to_order``, board order
        between equals) — its own because untapping an opponent's land is a
        gift, and tapped ones because untapping an untapped land is a wasted
        pick. Board order was the order, so Mudslide's {2} untapped whichever
        creature had been on the battlefield longest.

        With a price on each pick (Mudslide), the count is capped by what the
        *floating* mana covers — the same stated policy `_default_optional_pay`
        takes, and for its reason: tapping a land for an optional cost is a
        real decision about the rest of the turn, and it belongs to the seat
        that was actually asked.
        """
        amount = int(choice.data.get("amount", 0))
        filt = dict(choice.data.get("filter") or {})
        from ....ai_prompt_picks import untap_up_to_order

        own = untap_up_to_order(self, choice.player_index, [
            perm for perm in self.controlled_by(choice.player_index)
            if perm.tapped and permanent_matches_filter(perm, filt)
        ])
        cost_each = {k: v for k, v in (choice.data.get("cost_each") or {}).items() if v}
        if cost_each:
            payer = self.players[choice.player_index]
            affordable = 0
            while affordable < min(amount, len(own)):
                total = {s: c * (affordable + 1) for s, c in cost_each.items()}
                if plan_payment(payer.mana_pool, (), total, payer=payer) is None:
                    break
                affordable += 1
            amount = affordable
        picks = [self.permanent_id_of(perm) for perm in own[:amount]]
        if not self._resolve_untap_up_to(choice, [p for p in picks if p is not None]):
            self._resolve_untap_up_to(choice, [])

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
        from ....handlers.permanent_choices import permanent_choice_candidates

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

        The one ordering a *payload* may ask for is ``default_prefers``: a
        permanent state the step behind the pick would change. "That player
        untaps a land they control" (Rising Waters) offers every land and an
        untapped one is a legal answer that does nothing, so the default takes
        a tapped one first. Stable, so board order still breaks every tie, and
        a preference rather than a filter: the interactive prompt is unchanged.
        """
        live = self.live_permanent_choices(choice)
        prefers = (choice.data.get("_payload") or {}).get("default_prefers")
        if prefers == "decline_unless_lethal" and choice.data.get("optional"):
            # "That player … may choose a creature they control and have
            # Flaming Gambit deal that damage to it instead." The offer is the
            # damaged seat's, and giving up a creature to spare life is worth
            # it only when the life is all there is: a seat nobody asks keeps
            # its creatures unless the damage would be lethal to it. A
            # planeswalker target is not that question, and is declined.
            from ....handlers._amounts import resolve_amount

            context = choice.data.get("_context")
            amount = resolve_amount(
                (choice.data.get("_payload") or {}).get("amount", 0),
                getattr(context, "x_value", None),
            )
            at_a_permanent = getattr(context, "target_permanent_id", None) is not None
            life = self.players[choice.player_index].life
            if not live or at_a_permanent or amount < life:
                self._resolve_permanent_choice(choice, None)
                return
        if prefers == "tapped":
            live = sorted(live, key=lambda perm: not perm.tapped)
        elif prefers == "not_the_choosers":
            # "That player attaches this Aura to a land of their choice."
            # (Steam Vines, Kudzu.) The Aura destroys the land it is on, so a
            # seat nobody asks puts it on somebody else's first. A preference,
            # like the one above: with only its own lands to choose from, the
            # seat still has to choose one.
            live = sorted(
                live,
                key=lambda perm: self.controller_index_of(perm) == choice.player_index,
            )
        elif prefers == "returning_aura_host" and live:
            # "Return all enchantment cards from your graveyard to the
            # battlefield." (Replenish.) What each returning Aura enchants is
            # its controller's choice (CR 303.4f), and a seat nobody asks
            # already takes ``ai_policy``'s pick without being armed — so the
            # prompt's own default is that pick too, and an interactive seat
            # answered for (a test's drain, a timed-out seat) lands where an AI
            # seat would.
            from ....ai_targets import choose_returning_aura_host

            aura_card = (choice.data.get("_payload") or {}).get("legal_host_for_card")
            if aura_card is not None:
                pick = choose_returning_aura_host(
                    self, choice.player_index, aura_card, live
                )
                live = [pick, *(perm for perm in live if perm is not pick)]
        # …and the one ordering a *later sentence* asks for: "Prevent all combat
        # damage target creature would deal this turn **if it shares a color
        # with that permanent**" (Guard Dogs). The pick decides whether the
        # ability does anything, and board order's first answer is a land. So
        # a candidate that shares a colour with the effect's target goes first
        # — the relation the condition itself will ask, through the reader it
        # asks it with (CR 105.2, layer 5 on both sides). Which cards print
        # such a test is `ai_prompt_readers.pick_is_tested_for_a_shared_color`, off
        # the compiled program; stable, so board order still breaks every tie.
        context = choice.data.get("_context")
        if live and getattr(context, "card", None) is not None:
            from ....ai_prompt_readers import pick_is_tested_for_a_shared_color

            if pick_is_tested_for_a_shared_color(
                context.card, str(choice.data.get("result_key") or "")
            ):
                from ....handlers._targets import resolve_target_permanent
                from ....object_colors import share_a_color

                target = resolve_target_permanent(
                    self, context,
                    predicate=lambda perm: True,
                    fallback_players=(),
                    fallback_on_invalid_choice=False,
                )
                if target is not None:
                    wanted = self._effective_colors(target)
                    live = sorted(
                        live,
                        key=lambda perm: not share_a_color(
                            wanted, self._effective_colors(perm)
                        ),
                    )
        # **And a pick that takes the permanent from somebody else.** "…an
        # opponent chooses a permanent you control other than this creature and
        # exiles it" (Wormfang Crab): the chooser controls none of the
        # candidates and the step behind the pick takes the one chosen away
        # (`ai_prompt_readers.pick_is_taken_from_its_controller`, off the
        # compiled program), so its pick is the one that costs their
        # controller most — the dearest by ``ai_standing.permanent_worth``,
        # board order between equals. Board order's first answer was the
        # Crab's controller's first land.
        #
        # **And its mirror: a pick the chooser makes among its own.** "…choose
        # a creature you control and an opponent. Flip a coin. If you lose the
        # flip, that opponent gains control of that creature." (Risky Move);
        # "…gain control of target creature of an opponent's choice they
        # control" (Preacher, the opponent choosing). The step behind takes
        # the one chosen from the seat choosing it, so the seat gives up the
        # one that costs it least — the cheapest by the same worth, board order
        # between equals. Board order risked a Butcher Orgg over a Festering
        # Goblin (Onslaught's W2G5: 5 of 24 Risky Move picks).
        if live and getattr(context, "card", None) is not None:
            from ....ai_prompt_readers import pick_is_taken_from_its_controller

            if pick_is_taken_from_its_controller(
                context.card, str(choice.data.get("result_key") or "")
            ):
                from ....ai_standing import permanent_worth

                controllers = {self.controller_index_of(perm) for perm in live}
                if choice.player_index not in controllers:
                    live = sorted(live, key=lambda perm: -permanent_worth(perm))
                elif controllers == {choice.player_index}:
                    live = sorted(live, key=permanent_worth)
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
        at_least: int = 0,
    ) -> PendingChoice | None:
        """Queue "choose up to *up_to* of these permanents" for *player_index*.

        *at_least* is the **floor**, and it is what makes this prompt able to
        ask a printed count rather than only a ceiling. "Chooses up to two
        Plains" (Raiding Party) has none — none is a legal answer — but "return
        **two** Forests you control to their owner's hand" (Bull Elephant) is
        indivisible: returning one Forest is not paying the price, and a prompt
        that took it would leave the Elephant on the battlefield for half of
        what it costs. CR 601.2h asks what a player is *able* to do, and a
        partial answer is not one of them.

        Zero is every prompt that existed before the floor did, so nothing that
        does not ask for one is changed by it.
        """
        return self.arm_pending_choice(
            "permanent_set_choice", player_index,
            card_name=card_name,
            prompt=prompt,
            result_key=result_key,
            up_to=int(up_to),
            at_least=int(at_least),
            _payload=dict(payload),
            _context=context,
            _candidates=tuple(candidates),
        )

    def live_permanent_set_choices(self, choice: PendingChoice) -> list:
        """The armed candidates that are still legal answers."""
        from ....handlers.permanent_choices import permanent_choice_candidates

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
        if len(ids) < int(choice.data.get("at_least", 0) or 0):
            # A printed count is indivisible (see ``arm_permanent_set_choice``).
            # Rejected rather than truncated, so the prompt stays queued and the
            # seat answers the question the card actually asked.
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
        floor = int(choice.data.get("at_least", 0) or 0)
        live = self.live_permanent_set_choices(choice)
        own = [perm for perm in live if self.controls(choice.player_index, perm)]
        payload = choice.data.get("_payload") or {}
        if payload.get("default_none") or payload.get("same_number_as") is not None:
            # "Choose any number of creatures target player controls. Choose
            # the same number of creatures another target player controls.
            # Those players exchange control of those creatures." (Cultural
            # Exchange.) The own-first rule above is written for a pick that
            # *keeps* what it names; these give away one side for the other,
            # so board order would hand a seat's creatures across for
            # whatever stood first opposite. The pick is the exchange that
            # favours the seat (``ai_prompts.exchange_picks``: its cheapest
            # given for the dearest taken, while each pair gains), and none
            # where nothing gains — the lowering says which picks are this
            # kind (``default_none``, ``same_number_as``), never a card.
            from ....ai_prompts import exchange_picks

            picks = exchange_picks(
                self, choice.player_index, live, payload, choice.data.get("_context"),
            )
            chosen = [pid for pid in (self.permanent_id_of(perm) for perm in picks)
                      if pid is not None]
            if not self._resolve_permanent_set_choice(choice, chosen):
                if not self._resolve_permanent_set_choice(choice, []):
                    self.discard_pending_choice(choice)
            return
        # **The one place board order is not the answer: the permanent that is
        # asking is itself on the list.** "When this creature enters, return a
        # red or green creature you control to its owner's hand" (Planeshift's
        # gating; Shrieking Drake) is a forced pick that the entering creature
        # satisfies, and board order has no opinion about that -- it returned
        # whichever creature had been on the battlefield longest, which in six
        # simulated games was a seat's 7/7 while a 1/1 stood beside it. Asked
        # of the valuation the docstring above points at
        # (``ai_cast_gates.given_back_first``): the asking permanent last, the
        # cheapest loss first, board order between equals.
        #
        # Keyed on that structural fact and on a floor, never on a card: every
        # other user of this prompt -- a Karoo's Plains, Bull Elephant's
        # Forests, Raiding Party's survivors -- does not offer its own source
        # and keeps the order it has always had.
        asking = getattr(choice.data.get("_context"), "source_permanent", None)
        if floor and asking is not None and any(perm is asking for perm in own):
            from ....ai_cast_gates import given_back_first

            own = given_back_first(own, asking)
        # "…then untaps those permanents." (Mist of Stagnation.) The singular
        # pick's ``default_prefers: "tapped"`` (Rising Waters), honoured the
        # same way: stable, so board order still breaks every tie, and over
        # the same candidates — a preference, never a narrowing.
        tapped_first = (
            (choice.data.get("_payload") or {}).get("default_prefers") == "tapped"
        )
        if tapped_first:
            own = sorted(own, key=lambda perm: not perm.tapped)
        picks = own[:limit]
        if len(picks) < floor:
            # **A floor is not a ceiling, and the own-only rule is about the
            # ceiling.** "Choose a land that player controls" (Equipoise) is a
            # pick made from somebody *else's* battlefield and the card says how
            # many, so a seat that offered nothing would not be leaving a
            # ceiling unspent — it would be declining an instruction. Filled in
            # board order from whatever is left, which is this policy's
            # determinism one step further rather than a valuation.
            rest = [perm for perm in live if perm not in picks]
            if tapped_first:
                rest = sorted(rest, key=lambda perm: not perm.tapped)
            picks = picks + rest[: floor - len(picks)]
        chosen = [pid for pid in (self.permanent_id_of(perm) for perm in picks)
                  if pid is not None]
        if not self._resolve_permanent_set_choice(choice, chosen):
            # The empty answer is the fallback only where it is a *legal*
            # answer. Under a floor it is not, and re-offering it twice would
            # leave the prompt queued forever with nobody left to answer it —
            # so the choice is discarded, which is the outcome a seat that
            # cannot meet the floor has anyway. `_default_loyalty_recipient`
            # takes the same last step for the same reason.
            if not self._resolve_permanent_set_choice(choice, []):
                self.discard_pending_choice(choice)

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
        announcing=None,
    ) -> PendingChoice | None:
        """Queue "choose one of these players" for *player_index*.

        The seats are carried rather than the rule that produced them, unlike
        ``arm_permanent_choice``: what a seat *is* cannot stop qualifying
        mid-resolution the way a permanent can leave the battlefield, because
        "cast one or more sorcery spells this turn" is a fact about a turn that
        is already over. A seat that has *lost* is the one exception, and it is
        re-checked when the answer arrives.

        *announcing* is the stack object this choice is part of the
        announcement of — "which opponent chooses this spell's mode" (CR
        700.2e) is asked after CR 601.2i has put the spell on the stack, and
        the spell must not resolve before it is answered. Carried as
        ``_trigger_item``, the key every announcement-time prompt holds its
        object with (``announcement_choice_for``).
        """
        extra = {} if announcing is None else {"_trigger_item": announcing}
        return self.arm_pending_choice(
            "player_choice", player_index,
            card_name=card_name,
            prompt=prompt,
            result_key=result_key,
            seats=[int(seat) for seat in seats],
            names=[self.players[int(seat)].name for seat in seats],
            _context=context,
            **extra,
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
        """The seat that benefits the chooser
        (``ai_prompt_picks.player_choice_pick``): an opponent the card then
        damages, the one it would damage most (Backdraft, read off the
        program), and otherwise — "which opponent", at a table of three or
        more — the opponent least ahead. The first live seat offered was the
        answer, so Backdraft named its own caster whenever the caster sat
        first.
        """
        from ....ai_prompt_picks import player_choice_pick

        live = self.live_player_choices(choice)
        pick = player_choice_pick(self, choice, live)
        if pick is None or not self._resolve_player_choice(choice, pick):
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
        from ....damage_ledger import damage_dealt_by_cast

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
        from ....damage_ledger import cast_by_index, damage_dealt_by_cast

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
        """Where the number recorded becomes damage to the named cast's caster
        (Backdraft's "…equal to half the damage dealt by one of those sorcery
        spells", read off the program: ``ai_prompt_picks.
        result_is_damage_dealt``), the cast that dealt most when its caster is
        somebody else and least when it is the chooser
        (``cast_choice_pick``); otherwise the first cast offered, in the order
        they were cast. The first was the answer whatever it had dealt."""
        from ....ai_prompt_picks import cast_choice_pick, result_is_damage_dealt

        options = list(choice.data.get("options") or ())
        context = choice.data.get("_context")
        pick = options[0] if options else None
        if options and result_is_damage_dealt(
            getattr(context, "card", None), str(choice.data.get("result_key") or ""),
        ):
            pick = cast_choice_pick(self, choice.player_index, options)
        if pick is None or not self._resolve_cast_choice(choice, pick):
            self._record_cast_choice(choice, 0)

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
        from ....handlers.counters import place_loyalty_counters

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

    # -- Counters moved from the source onto any of a set (Forgotten Ancient)

    def arm_counter_distribution(
        self, player_index: int, *, card_name: str, source, counter: str,
        filter: dict, candidates: list,
    ) -> PendingChoice | None:
        """Ask *player_index* how many *counter* counters to move off *source*
        and onto which of *candidates* (CR 608.2d, CR 122.5).

        "…you may move any number of +1/+1 counters from this creature onto
        other creatures." (Forgotten Ancient.) Nothing is targeted — the card's
        2022-12-08 ruling: "You choose how many +1/+1 counters will be moved
        (and onto which creatures) as the ability resolves" — so the set is the
        printed noun phrase enumerated now and asked again at the answer.
        """
        return self.arm_pending_choice(
            "counter_distribution", player_index,
            card_name=card_name,
            counter=counter,
            source_id=self.permanent_id_of(source),
            filter=dict(filter or {}),
            _source=source,
            _candidates=list(candidates),
        )

    def counter_distribution_maximum(self, choice: PendingChoice) -> int:
        """How many counters the source still has to give — the ceiling of
        the answer, read now: a counter that came off in between is not one
        the seat can move (CR 122.5: a move takes what is there)."""
        from ....named_counters import counters_on

        source = choice.data.get("_source")
        if source is None or not self.is_on_battlefield(source):
            return 0
        return counters_on(source, str(choice.data.get("counter") or "+1/+1"))

    def live_counter_distribution(self, choice: PendingChoice) -> list:
        """The armed candidates still on the battlefield and still matching the
        printed noun phrase ("other creatures"), by identity.

        Public because the prompt renderer is the second legitimate caller: the
        list offered and the list an answer is held to are one rule. The source
        is never one of them — "other" (CR 109.1's identity, ``exclude_self``)
        is asked against it, and a move onto itself is no move (CR 122.5).
        """
        described = dict(choice.data.get("filter") or {})
        source = choice.data.get("_source")
        return [
            perm
            for perm in (choice.data.get("_candidates") or ())
            if perm is not source
            and self.is_on_battlefield(perm)
            and subject_matches(
                self, perm, described,
                observer=choice.player_index, source=source,
            )
        ]

    def confirm_counter_distribution(
        self, player_index: int, permanent_ids: list, amounts: list,
    ) -> bool:
        """*permanent_ids* names each receiving creature by stable id and
        *amounts* how many counters it gets, position by position. Two empty
        lists are a legal answer: "any number" includes none."""
        return self.resolve_pending_choice(
            "counter_distribution", player_index,
            permanent_ids=permanent_ids, amounts=amounts,
        )

    def _resolve_counter_distribution(
        self, choice: PendingChoice, permanent_ids: list, amounts: list,
    ) -> bool:
        """Move the counters the seat named, as one action (CR 122.5).

        Validated whole before anything moves, so one bad entry rejects the
        answer and leaves the prompt queued: the two lists pair up, every id is
        a live candidate named once, every amount is a whole number of one or
        more, and together they ask for no more counters than the source still
        has. Then the total comes off the source and each share goes on its
        creature, through the counter seams (``named_counters.remove_counters``,
        ``Game.place_pt_counters``) so a P/T counter takes its layer-7d
        contribution with it in both directions (CR 122.1a).
        """
        from ....named_counters import remove_counters

        ids = list(permanent_ids or [])
        shares = list(amounts or [])
        if len(ids) != len(shares):
            return False
        if not all(isinstance(pid, int) and not isinstance(pid, bool) for pid in ids):
            return False
        if len(set(ids)) != len(ids):
            return False
        if not all(
            isinstance(share, int) and not isinstance(share, bool) and share >= 1
            for share in shares
        ):
            return False
        live = self.live_counter_distribution(choice)
        chosen = []
        for pid in ids:
            perm = self.permanent_by_id(pid)
            if perm is None or not any(perm is candidate for candidate in live):
                return False
            chosen.append(perm)
        total = sum(shares)
        if total > self.counter_distribution_maximum(choice):
            return False
        self.discard_pending_choice(choice)
        card_name = choice.data.get("card_name", "")
        counter = str(choice.data.get("counter") or "+1/+1")
        if not chosen:
            self.log.append(f"{card_name}: no {counter} counters moved")
            return True
        source = choice.data.get("_source")
        remove_counters(source, counter, total)
        for perm, share in zip(chosen, shares):
            self.place_pt_counters(perm, counter, share)
        self.log.append(
            f"{card_name}: moved "
            + ", ".join(
                f"{share} {counter} counter(s) onto {perm.card.name}"
                for perm, share in zip(chosen, shares)
            )
        )
        self.check_state_based_actions()
        return True

    def _default_counter_distribution(self, choice: PendingChoice) -> None:
        """The stated policy: **every counter onto the seat's own strongest
        other creature** — the greatest power, then toughness, ties broken by
        board order — and **none** when the seat controls no candidate.

        The "may" in front has already been answered yes (Tetravus's reason,
        ``remove_any_number_of_counters_from_self``), so moving nothing would
        make accepting the offer do nothing; and a counter put on another
        seat's creature is a gift to that seat, which no stated policy makes.
        A card whose AI should choose otherwise needs a valuation, not a
        branch here.
        """
        maximum = self.counter_distribution_maximum(choice)
        own = [
            perm for perm in self.live_counter_distribution(choice)
            if self.controller_index_of(perm) == choice.player_index
        ]
        if maximum <= 0 or not own:
            self._resolve_counter_distribution(choice, [], [])
            return
        pick = max(
            own,
            key=lambda perm: (perm.effective_power, perm.effective_toughness,
                              -own.index(perm)),
        )
        if not self._resolve_counter_distribution(
            choice, [self.permanent_id_of(pick)], [maximum]
        ):
            self._resolve_counter_distribution(choice, [], [])

    # -- Face-down permanents looked at (CR 708.5; Aven Soulgazer, Spy Network)

    def arm_face_down_look(
        self, viewer_index: int, permanents, *, source_name: str,
    ) -> None:
        """Show *viewer_index* what the face-down *permanents* are.

        CR 708.5 lets only a face-down permanent's controller look at it; an
        effect that says "look at" is the exception, and what it shows is the
        looker's alone (Spy Network, 2004-10-04: "Only you get to look. You
        can't show them to others."). So the cards ride a prompt owed by the
        looker — the one channel ``web/prompts.visible_choices`` sends to that
        seat and nobody else — addressed by ``permanent_id``, and never a log
        line. A notification like ``hand_reveal``: nothing waits on it, and a
        newer look replaces an older one rather than queueing behind it.

        The seat learns nothing that outlasts the prompt: there is no record of
        what a seat has been shown, so ``ai_scratch_copy.conceal_from`` redeals
        the looked-at card on the looker's own rehearsal copies — the limit the
        hidden-hand looks (Glasses of Urza) already have.
        """
        self.clear_pending_choices("face_down_look", viewer_index)
        self.arm_pending_choice(
            "face_down_look", viewer_index,
            permanent_ids=[permanent.permanent_id for permanent in permanents],
            source_name=source_name,
        )

    def live_face_down_look(self, choice: PendingChoice) -> list:
        """The looked-at permanents that are still face down on the battlefield.

        One that has been turned face up or has left is public now (CR 708.8,
        708.9), so the look has nothing left to show about it — and dropping it
        here is what keeps the prompt from pointing at a permanent id that no
        longer names anything.
        """
        from ....face_down import is_face_down

        live = []
        for permanent_id in choice.data.get("permanent_ids") or ():
            permanent = self.permanent_by_id(permanent_id)
            if permanent is not None and is_face_down(permanent):
                live.append(permanent)
        return live

    def dismiss_face_down_look(self, viewer_index: int) -> bool:
        """The looker has seen the face-down cards; take the prompt down."""
        return self.resolve_pending_choice("face_down_look", viewer_index)

    def _dismiss_face_down_look(self, choice: PendingChoice) -> bool:
        self.discard_pending_choice(choice)
        return True


# ---------------------------------------------------------------------------
# This family's rows of the prompt table
# ---------------------------------------------------------------------------
#
# One ``ChoiceSpec`` per prompt kind of this family, in the table's order
# (``engine/pending_choices.py`` says what each field means). ``table.py``
# registers them, in the one list ``Game.iter_pending_prompts`` reads.

TAP_ANY_NUMBER_SPEC = ChoiceSpec(
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

UNTAP_UP_TO_SPEC = ChoiceSpec(
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

FACE_DOWN_LOOK_SPEC = ChoiceSpec(
    "face_down_look",
    resolve=lambda game, choice, r: game._dismiss_face_down_look(choice),
    default=lambda game, choice: game._dismiss_face_down_look(choice),
    action="dismiss_face_down_look",
    prompt_key="face_down_look",
    # "Look at target face-down creature" (Aven Soulgazer, Spy Network): a
    # notification like ``hand_reveal`` — nothing waits on it. Unlike
    # it, never shown to a seatless viewer: what a face-down permanent is
    # belongs to its controller and to this looker alone (CR 708.5).
    blocked_detail=None,
)

PLAYER_CHOICE_SPEC = ChoiceSpec(
    "player_choice",
    resolve=lambda game, choice, r: game._resolve_player_choice(choice, r.get("seat")),
    default=lambda game, choice: game._default_player_choice(choice),
    action="player_choice_confirm",
    prompt_key="player_choice",
    blocked_detail="choose a player for the resolving spell or ability before other actions",
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

CAST_CHOICE_SPEC = ChoiceSpec(
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

PERMANENT_CHOICE_SPEC = ChoiceSpec(
    "permanent_choice",
    resolve=lambda game, choice, r: game._resolve_permanent_choice(choice, r["permanent_id"]),
    default=lambda game, choice: game._default_permanent_choice(choice),
    action="permanent_choice_confirm",
    prompt_key="permanent_choice",
    blocked_detail="choose a permanent for the resolving spell or ability before other actions",
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

PERMANENT_SET_CHOICE_SPEC = ChoiceSpec(
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

OPPONENT_DAMAGE_SPEC = ChoiceSpec(
    "opponent_damage",
    resolve=lambda game, choice, r: game._resolve_opponent_damage_choice(
        choice, r["target_seat"], r["target_permanent_index"],
        r.get("permanent_id"),
    ),
    default=lambda game, choice: game._default_opponent_damage_choice(choice),
    action="opponent_damage_choose",
    prompt_key="opponent_damage_choice",
    blocked_detail="choose a target for the opponent-choice damage before other actions",
    default_at_arm=True,
    # The answer deals the second half of the sentence's one dealing
    # (``handlers/damage.deal_damage_and_opponent_choice``), whose finish is the
    # loop's later step: it waits for the answer rather than closing the
    # dealing before the opponent's half is dealt.
    suspends=True,
)

LOYALTY_RECIPIENT_SPEC = ChoiceSpec(
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


COUNTER_DISTRIBUTION_SPEC = ChoiceSpec(
    "counter_distribution",
    resolve=lambda game, choice, r: game._resolve_counter_distribution(
        choice, r.get("permanent_ids") or [], r.get("amounts") or []
    ),
    default=lambda game, choice: game._default_counter_distribution(choice),
    action="counter_distribution_confirm",
    prompt_key="counter_distribution",
    blocked_detail=(
        "choose how many counters to move and onto which creatures before "
        "other actions"
    ),
    # The ability has to finish resolving, so a non-interactive seat never
    # queues it — it takes the stated default where it stands. "No player may
    # take actions until the ability has finished resolving" (the card's
    # ruling) is the hold a person's answer gets from ``blocked_detail``.
    default_at_arm=True,
    # Which creatures got counters is public (no CR 400.2 hidden zone).
    spectator_visible=True,
    # Nothing later in the same resolution reads the answer: the move is the
    # last thing the ability does.
)
