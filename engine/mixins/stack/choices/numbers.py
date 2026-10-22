"""How many, how much, which number — and whether to go again.

The numbered prompts: how many cards to draw of "up to N", how much mana to pay
of "any amount", Shapeshifter's chosen number, Goblin Game's secret numbers
(recorded and shown to nobody until the last answer), and the life auction's
rounds of bids. With them, the two unbounded offers to run a printed paragraph
again — a coin flip at double the stake (Game of Chaos) and a process repeated
"any number of times" (Forbidden Ritual) — whose stated default is to stop.
"""

from __future__ import annotations

from ....enter_effects import LIFE_PAID_AS_ENTERED
from ....oracle_types import BIDDING_WINNER, DREW_BY_SEAT, MANA_PAID_BY_SEAT
from ....pending_choices import PendingChoice
from ....mana_payment import generic_cost, plan_payment


class NumberChoicesMixin:
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

    # -- "Each player may pay any amount of mana" -----------------------------

    def confirm_pay_any_amount(self, player_index: int, amount: int) -> bool:
        """Answer "you may pay any amount of mana" with how much (Liege of the
        Hollows)."""
        return self.resolve_pending_choice(
            "pay_any_amount", player_index, amount=amount
        )

    def _resolve_pay_any_amount(self, choice: PendingChoice, amount) -> bool:
        """Spend *amount* generic mana for the seat that was offered any amount.

        **The ceiling is the board, not the card**, which is what makes this
        prompt different from every other numbered one here: "any amount" prints
        no number at all, so what a legal answer is comes from
        ``mana_payment.plan_payment`` over the seat's pool *and* its untapped
        lands — the same reader every other "you may pay" goes through, because
        an effect that says "may pay" gives its player no priority window in
        which to tap for mana. An answer the board cannot cover is a
        **rejection**, not a clamp, for ``_resolve_number_choice``'s reason: a
        silently repaired answer would let a client ask for eight Squirrels off
        four lands and be told it worked.

        The payment goes through ``_pay_planned_cost``, the one writer, so the
        pool and the lands are charged together.
        """
        try:
            value = int(amount)
        except (TypeError, ValueError):
            return False
        if value < 0:
            return False
        seat = choice.player_index
        player = self.players[seat]
        plan = (
            plan_payment(
                player.mana_pool,
                self.payment_lands(seat),
                generic_cost(value),
                produces=self._land_payment_colors, payer=player,
            )
            if value else None
        )
        if value and plan is None:
            return False
        if plan is not None and not self._pay_planned_cost(
            player,
            lambda: plan_payment(
                player.mana_pool,
                self.payment_lands(seat),
                generic_cost(value),
                produces=self._land_payment_colors, payer=player,
            ),
        ):
            return False
        self.log.append(
            f"{player.name} paid {value} mana" if value
            else f"{player.name} paid no mana"
        )
        results = choice.data.get("_results")
        if results is not None:
            # The per-seat record the sentence behind this one reads ("… equal
            # to the amount of mana **they** paid this way"). Written even for a
            # seat that paid nothing, because a seat the map never mentions
            # would read as whatever the last answer was.
            results.setdefault(MANA_PAID_BY_SEAT, {})[seat] = value
        # Off the queue, which every sibling resolver here does and this one did
        # not. ``auto_resolve_pending_choices`` drops a defaulted choice itself,
        # so a headless or AI seat hid it; a *confirmed* one stayed queued with
        # ``_answered`` on it, and ``waiting_prompt`` reads the queue — so after
        # Liege of the Hollows died and both seats had paid, the game went on
        # reporting a decision nobody owed, refusing every action by the seat
        # that had already answered. CR 117.3b: play resumes when the decision is
        # made, and it was.
        self.discard_pending_choice(choice)
        return True

    def _default_pay_any_amount(self, choice: PendingChoice) -> bool:
        """A seat nobody asks pays **nothing**.

        "May" makes declining a real answer, and it is the only one a default
        can take honestly here — the same reading ``_default_bid_life`` states:
        how much a Squirrel is worth is a valuation, and spending a board's mana
        on it is a judgement nobody made. It also keeps the mana where the seat
        left it, which is the answer that changes least.
        """
        return self._resolve_pay_any_amount(choice, 0)

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

        A ``maximum`` of None is a printed range with no ceiling — "choose a
        number **greater than 0**" (Scrying Glass), CR 107.1 — so only the floor
        is enforced. None is the card's own answer and not a missing bound; read
        as zero it would refuse every legal answer there is.

        The number also goes into the **resolution's scratchpad** when the
        arming carried a ``result_key``, which is what a later step of the same
        resolution reads: a permanent's ``chosen_number`` is its standing answer
        and outlives this resolution, and a sentence asking about "the chosen
        number" means the one *this* activation just named.
        """
        try:
            value = int(number)
        except (TypeError, ValueError):
            return False
        low = int(choice.data.get("minimum", 0))
        high = choice.data.get("maximum")
        if value < low or (high is not None and value > int(high)):
            return False
        result_key = choice.data.get("result_key")
        context = choice.data.get("_context")
        if result_key is not None and context is not None:
            context.results[str(result_key)] = value
        permanent = choice.data.get("permanent")
        if permanent is not None:
            if choice.data.get("exile_own_tokens"):
                # Tetravus's second upkeep trigger. Oldest first, and only as
                # many as are still there — a token that died while the prompt
                # was owed is not one this can take.
                from ....tokens import tokens_created_with

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
                from ....pt import remove_plus1_counters

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
                permanent.metadata[LIFE_PAID_AS_ENTERED] = value
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
        else:
            # A spell's number (Void): nothing but the scratchpad keeps it, so
            # the log is the only place the table can read what was named.
            self.log.append(f"{choice.data.get('card_name')}: chose {value}")
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

    # -- "Each player secretly chooses a number" --------------------------------
    #
    # "Each player hides at least one item, then all players reveal them
    # simultaneously." (Goblin Game.) One prompt per seat, all armed together,
    # and the whole of what makes it its own kind is what it does **not** do:
    # an answer is recorded and nothing else happens — no log line, no board
    # change, nothing a state view carries — until the answer that completes
    # the map, which reveals every number in one line.
    #
    # Not a mode of the three numbered prompts beside it, and that was looked
    # at. ``draw_up_to`` and ``pay_any_amount`` are the multi-seat ones, and
    # each *performs* its number as it is answered (the cards are drawn, the
    # mana is spent), in the open — which is the one thing a secret choice
    # must not do. ``number_choice`` only records, but it is one seat's public
    # number: it holds nobody but its own seat (``blocks_every_seat`` is a
    # property of a kind, and that kind's twenty cards want it False) and it
    # stays queued for a seat the engine plays, where this must be answered as
    # it is armed so that seat commits before any other answer exists.

    def confirm_secret_number(self, player_index: int, number) -> bool:
        """Answer "secretly choose a number" with *number* (Goblin Game)."""
        return self.resolve_pending_choice(
            "secret_number", player_index, number=number
        )

    def _resolve_secret_number(self, choice: PendingChoice, number) -> bool:
        """Record this seat's number, and reveal them all if it was the last.

        Below the printed floor is a **rejection**, not a clamp, for
        ``_resolve_number_choice``'s reason: a silently repaired answer would
        tell a seat it had hidden nothing and then take a life for it. There is
        no ceiling — CR 107.1 gives a chosen number none and the card prints
        none — so a number above the seat's own life total is legal, and
        lethal.

        The answer goes into the resolution's scratchpad under the key the
        arming named and **nowhere else**. The log line is the reveal, written
        by whichever answer finds every asked seat in the map; an earlier one
        would tell the seats still choosing what they are choosing against.
        """
        if isinstance(number, bool):
            return False
        try:
            value = int(number)
        except (TypeError, ValueError):
            return False
        if value < int(choice.data.get("minimum", 0)):
            return False
        results = choice.data.get("_results")
        key = choice.data.get("record")
        named = results.setdefault(key, {}) if results is not None and key else {}
        named[choice.player_index] = value
        self.discard_pending_choice(choice)
        asked = [int(seat) for seat in (choice.data.get("seats") or ())]
        if all(seat in named for seat in asked):
            self.log.append(
                f"{choice.data.get('card_name', '')}: "
                + ", ".join(
                    f"{self.players[seat].name} revealed {named[seat]}"
                    for seat in asked
                )
            )
        return True

    def _default_secret_number(self, choice: PendingChoice) -> bool:
        """A seat nobody asks names the number ``ai_policy.choose_secret_number``
        gives it — a policy over the life totals every player can see, which
        is the whole of what this seat is entitled to know. It does not read
        the map this answer goes into."""
        from ....ai_policy import choose_secret_number

        return self._resolve_secret_number(
            choice,
            choose_secret_number(
                self, choice.player_index, int(choice.data.get("minimum", 0))
            ),
        )

    # -- "Each player may bid life for control of ..." -----------------------

    def begin_life_auction(
        self, *, card_name: str, permanent_id: "int | None", opening_bidder: int,
        starting_bid: int, order: list[int], results: "dict | None" = None,
    ) -> None:
        """Open an auction's round of offers (Illicit Auction, Mages' Contest).

        **Two outcomes, one round.** What every printed auction shares is the
        procedure — who is asked, in what order, when it stops, and that the
        high bidder loses the high bid — and that is everything from here to
        ``_settle_life_auction``. What they differ in is the stake, and it is
        data: *permanent_id* is the permanent the winner takes control of
        (Illicit Auction), or None when the auction hands nothing over itself;
        *results* is the resolution's scratchpad, where the winning seat is
        written (``BIDDING_WINNER``) for the step behind the auction to read
        ("If you win the bidding, counter that spell", Mages' Contest). *order*
        is the seats that bid — every seat for "each player", two for "you and
        target spell's controller".

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
            "permanent_id": None if permanent_id is None else int(permanent_id),
            "_results": results,
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
        from ....control import change_control

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
        # Who won, for the step behind the auction ("If you win the bidding,
        # …"). Written after the life is lost and before anything is handed
        # over, so a reader of the record sees the auction finished.
        results = data.get("_results")
        if results is not None:
            results[BIDDING_WINNER] = winner_index
        if data.get("permanent_id") is None:
            # An auction with nothing of its own to hand over (Mages'
            # Contest): what winning buys is the next instruction's business.
            self.log.append(
                f"{card_name}: {winner.name} wins the bidding at {amount}"
            )
            return
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

    # -- Whether a printed process is run again ------------------------------

    def confirm_repeat_process(self, player_index: int, accept: bool = True) -> bool:
        """Answer Forbidden Ritual's "you may repeat this process any number of
        times"."""
        return self.resolve_pending_choice(
            "repeat_process", player_index, accept=accept
        )

    def _resolve_repeat_process(self, choice: PendingChoice, accept: bool) -> bool:
        """Run the printed process again, or stop.

        The next round is the *same* instruction the handler was already
        running, carried here when the question was armed — so this does not
        have to know what the process is or how many rounds there have been,
        which is the handler's business and stays there. The identical shape
        ``_resolve_flip_again`` beside it uses, and for the same reason.
        """
        again = choice.data.get("_again")
        context = choice.data.get("_context")
        self.discard_pending_choice(choice)
        player = self.players[choice.player_index]
        if not accept or again is None or context is None:
            self.log.append(
                f"{player.name} declined to repeat "
                f"({choice.data.get('card_name', 'an effect')})"
            )
            return True
        self._execute_oracle_instruction(again, context)
        return True

    def _default_repeat_process(self, choice: PendingChoice) -> None:
        """The stated policy: **stop after one round**.

        Not a valuation, and not a shortcut. The first round is what the card
        makes its controller do; every round after it is pure choice, and a
        default of "yes" is not a default — it is a loop with no bound at all,
        which "any number of times" is precisely what it says. A seat that
        should press on wants a weight in ``engine/ai_valuation.py`` rather
        than a branch here, exactly as ``_default_flip_again`` records for the
        other unbounded offer in this file.
        """
        self._resolve_repeat_process(choice, False)
