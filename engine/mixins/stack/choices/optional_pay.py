""""You may pay": an offer, its price, and what buying it runs.

An optional-pay entry carries its price (mana, life, or a graded choice between
printed costs), what accepting runs and what declining costs ("…unless you
pay", which deals its damage instead). ``_player_can_pay_optional`` is CR 601.2h for
an optional cost; ``_collect_optional_price`` charges all of it or none; and a
paid offer may create a reflexive ability ("when you do", CR 603.12) whose
target is a prompt of its own. The default a seat nobody asks takes is a
valuation, and its reasons are written beside it. Paying life to save one
permanent out of a sweep (Cleansing) is the same offer with a life price.
"""

from __future__ import annotations

from dataclasses import replace
from ....pending_choices import PendingChoice, optional_pay_options
from ....resumption import run_resumable
from ....mana_payment import plan_payment
from ....oracle_types import OracleInstruction


class OptionalPayChoicesMixin:
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
        lands = self.payment_lands(player)
        options = optional_pay_options(entry)
        if option is not None:
            options = options[option:option + 1]
        for cost in options:
            plan = plan_payment(
                player.mana_pool, lands, cost,
                produces=self._land_payment_colors,
                # What the payer may spend that mana *as* (CR 609.4b): white as
                # any colour under Celestial Dawn or False Dawn, where no land
                # "produces" the pip an effect is charging.
                payer=player,
            )
            if plan is not None:
                return plan
        return None

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

    def payment_may_be_offered(self, player, entry: dict) -> bool:
        """Whether an offer priced in mana is put to *player* at all.

        ``_player_can_pay_optional`` for every seat the engine answers for: a
        price its plan cannot collect is a price that seat does not pay, so
        the offer is not made and the "if they don't" follows at once.

        **A person is asked whenever they might pay by their own hand.** The
        same gate used to stand in front of them, so "sacrifice it unless you
        pay {2}" with a Sol Ring untapped sacrificed it without a word: the
        plan taps free land abilities only, said "cannot pay", and the offer
        was never armed. CR 118.12a makes "unless" a choice the player has,
        and CR 605.3a lets them activate mana abilities to make it. What they
        are shown says whether "pay" would be accepted as the board stands
        (``payable``), and an answer it would not be is refused rather than
        read as a decline (:meth:`seat_answers_for_itself`).

        Still not made where nothing they control could change the answer —
        no mana source beyond the plan, or a life half they cannot cover
        (CR 119.4) — so a person is not asked a question with one answer.
        """
        if self._player_can_pay_optional(player, entry):
            return True
        seat = self.seat_index(player)
        if not entry.get("cost") or not self.seat_answers_for_itself(seat):
            return False
        if player.life < int(entry.get("life_cost", 0) or 0):
            return False
        return self.mana_beyond_the_plan(seat)

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
    ) -> bool:
        """Collect the entry's price from its player and run what accepting
        buys; True when it was paid. A price that turns out to be unpayable
        buys nothing, and the caller is told so — an "unless they pay" that
        was not paid has its other half to carry out (CR 118.12a).

        *option* is which of a graded offer's costs the payer chose; None
        everywhere else, and on a graded offer means "take the stated policy".
        """
        paid, option = self._collect_optional_price(player_index, entry, option)
        if paid:
            self._run_optional_purchase(player_index, entry, option)
        return paid

    def _collect_optional_price(
        self, player_index: int, entry: dict, option: int | None = None,
    ) -> "tuple[bool, int | None]":
        """Charge the whole price of an optional offer, or none of it.

        ``(paid, option)`` — the option a graded offer was paid with comes
        back because the purchase reads it. Separate from the purchase so a
        caller can learn that the price was *not* paid before anything it
        buys has run, and before the prompt that asked is given up: a
        person's "pay" that cannot be collected leaves the question standing
        (:meth:`seat_answers_for_itself`).

        The mana is collected **before** any life is charged. A plan can fail
        part-way — a land it counted makes nothing this payment can spend —
        and a payer charged the life first would have paid it for nothing
        (CR 601.2h: no partial payment).
        """
        player = self.players[player_index]
        # A free optional "you may draw a card" rider (Verduran Enchantress): no
        # cost to pay; the draw is what accepting buys.
        if entry.get("draw"):
            return True, option
        # "That player may pay 10 life." (Bronze Tablet.) A life cost rather
        # than a mana one — or both, "You may pay {4} **and** 2 life."
        # (Purgatory): both halves or neither, and CR 601.2h is asked of the
        # whole price as the board stands now, which can have changed since
        # the offer was made.
        life_cost = int(entry.get("life_cost", 0) or 0)
        if life_cost and player.life < life_cost:
            return False, option
        if not life_cost or entry.get("cost"):
            # A graded offer is paid with the option that was chosen and with no
            # other: falling back through the alternatives would charge a cost
            # the payer did not pick and then run the consequence that cost
            # buys.
            if self.graded_pay_options(entry) is not None:
                option = self._graded_option_taken(player, entry, option)
                if option is None:
                    return False, None
            plan = self._optional_pay_plan(player, entry, option=option)
            if plan is None:
                if life_cost:
                    return False, option
                # CR 118.8's alternative ("…pays {1} **or 1 life**", Erosion).
                # A *stated policy* rather than a second prompt: the mana is
                # spent whenever the board can cover it, and the life only when
                # it cannot. The offer is one decision and the web prompt asks
                # it once, so which half pays for it is the engine's to state —
                # and stating "mana first" is the reading that keeps a life
                # total for the alternatives that have no other currency.
                alternative = int(entry.get("life_alternative", 0) or 0)
                if not alternative or player.life < alternative:
                    return False, option
                player.life -= alternative
                self.log.append(
                    f"{player.name} paid {alternative} life "
                    f"({entry.get('card_name', '')})"
                )
            elif not self._pay_planned_cost(
                player,
                lambda: self._optional_pay_plan(player, entry, option=option),
            ):
                # Could not be met after all (CR 601.2h): nothing is bought.
                return False, option
        if life_cost:
            player.life -= life_cost
            self.log.append(
                f"{player.name} paid {life_cost} life ({entry.get('card_name', '')})"
            )
        return True, option

    def _run_optional_purchase(
        self, player_index: int, entry: dict, option: int | None = None,
    ) -> None:
        """What a paid optional offer buys (the price is already collected)."""
        player = self.players[player_index]
        if entry.get("draw"):
            drawn = self._draw_with_replacements(player, int(entry["draw"]))
            self.log.append(f"{player.name} drew {drawn} card(s) from {entry['card_name']}")
            return
        # A grammar-lowered "may" carries its consequence as instructions rather
        # than as one of the three fixed fields above, so any effect can sit
        # behind an optional cost.
        ran = self._run_optional_branch(entry, "_on_accept")
        # What the payment buys when it is not the payer's own action: "Then if
        # any player pays {2}, discard three cards" (Rhystic Scrying) — the
        # controller discards, whoever paid (`handlers/offers
        # .unless_player_pays`).
        ran = self._run_optional_branch(entry, "_on_paid") or ran
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
        from ....targeting import derive_instruction_spec

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

    def _run_optional_branch(self, entry: dict, key: str) -> bool:
        """Execute an optional-pay entry's instruction branch, if it has one.

        Returns whether anything ran, so the legacy life/draw/damage fields stay
        the fallback for entries that predate instruction branches.

        **"If you do" is asked of the doing, where taking the offer is not
        it.** An accept branch whose action is a pick out of a hidden zone
        carries ``_then_if`` — the record that pick writes when it happens —
        and the steps from ``_then_from`` on wait behind it: "You may exile a
        card from your hand. If you do, untap this land" (Forsaken City)
        untapped for a seat that accepted and then exiled nothing. Applied
        here, as the branch runs, rather than baked into the branch: the pick
        suspends the resolution, so the condition has to be an instruction in
        the sequence for it to be asked after the answer.
        """
        steps = tuple(entry.get(key) or ())
        gate = entry.get("_then_if") if key == "_on_accept" else None
        if gate is not None:
            start = int(entry.get("_then_from", 0))
            if steps[start:]:
                steps = steps[:start] + (OracleInstruction("if_then", "", {
                    "condition": dict(gate), "then": steps[start:], "else": (),
                }),)
        return self._run_optional_steps(entry, steps)

    def _run_optional_steps(self, entry: dict, steps) -> bool:
        """Run *steps* against the entry's frozen resolution context.

        Split from :meth:`_run_optional_branch` because a graded offer's branch
        is not a fixed payload key — which option was taken is only known once
        the payment is made — and the two must run the same way: through
        ``run_resumable``, against the context the offer was armed with.
        """
        from ....handlers.control_flow import _role_scoped

        context = entry.get("_context")
        if not steps or context is None:
            return False

        # Each step scoped to the announced **role** it spends, exactly as
        # ``handlers/control_flow._run`` scopes the steps of a sequence. This
        # path ran them against the frozen context as it stood, so a branch
        # answered through the prompt spent whichever target the announcement
        # listed first: Crooked Scales' "destroy target creature you control
        # unless you pay {3}", declined by a seat that *could* pay, read the
        # opponent's creature, found it was not "you control", and destroyed
        # nothing. A step whose object has gone is skipped (CR 608.2b).
        def run_step(step) -> None:
            scoped = _role_scoped(self, step, context)
            if scoped is not None:
                self._execute_oracle_instruction(step, scoped)

        # Through ``run_resumable`` for the same reason ``handlers/control_flow``'s
        # sequence is: a step may stop to ask its controller something, and the
        # steps behind it have to be recorded or they are silently lost.
        # Tetravus is the card that needed it — "remove any number of +1/+1
        # counters. **If you do, create that many … tokens**" ran the removal,
        # suspended on the count, and never made the tokens.
        run_resumable(self, steps, run_step)
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
            choice,
            lambda: self._resolve_optional_pay(choice, accept, option, asked=True),
        )

    def _resolve_optional_pay(
        self, choice: PendingChoice, accept: bool, option: int | None = None,
        *, asked: bool = False,
    ) -> bool:
        """Apply one answer to an optional offer.

        *asked* is whether this is a seat's own answer (the registered
        ``resolve``) rather than a default taken for it. With it, a person's
        "yes" to a price that cannot be collected — up front, or part-way
        through the plan — is **refused** and the offer stands; it used to be
        carried out as a "no", so "Pay" on an "unless you pay" took the
        penalty. See :meth:`seat_answers_for_itself`.
        """
        player_index = choice.player_index
        entry = choice.data
        held = bool(accept) and asked and self.seat_answers_for_itself(player_index)
        if held and not self._player_can_pay_optional(
            self.players[player_index], entry
        ):
            return False
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
        if (
            accept
            and self._player_can_pay_optional(self.players[player_index], entry)
            and self._optional_action_still_takeable(player_index, entry)
        ):
            # The price first, with the prompt still owed: a plan can fail
            # part-way (a land it counted made nothing the payment can
            # spend), and then nothing was bought. A person is told so and
            # asked again; for any other seat the price was not paid, which
            # for an "unless" is the other half (CR 118.12a) — it used to be
            # neither, and a toll failed that way was simply forgiven.
            paid, option = self._collect_optional_price(player_index, entry, option)
            if not paid and held:
                return False
            self.discard_pending_choice(choice)
            if paid:
                self._run_optional_purchase(player_index, entry, option)
            else:
                self._apply_optional_pay_decline(player_index, entry)
        else:
            self.discard_pending_choice(choice)
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
        from ....handlers.offers import _narrow_to_takeable_actions

        # "…may pay **that spell's mana cost**" (Ice Cave). The price was read
        # off a spell, and a spell that has since left the stack has no mana
        # cost to pay (CR 118.6) and nothing left to buy — so the offer is one
        # that can no longer be taken, exactly as an action with nothing left
        # to act on is. Asked here because both answer paths ask here, and a
        # seat charged for a counter of nothing has paid a cost for no effect.
        priced_spell = entry.get("_priced_spell")
        if priced_spell is not None and not any(
            item is priced_spell for item in self.stack
        ):
            return False
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
        from ....ai_prompt_readers import offered_action_is_a_payment

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

    def _weighed_offer_trade(self, choice: PendingChoice) -> "bool | None":
        """`ai_policy.offer_trade_is_worth_taking` for a **free, untolled**
        offer — the only kind whose accept branch is the whole of its price —
        or None for every other, which the standing policy answers."""
        from ....ai_prompts import offer_trade_is_worth_taking

        entry = choice.data
        if (
            entry.get("cost") or entry.get("life_cost")
            or entry.get("cost_alternatives") or entry.get("_on_decline")
            or int(entry.get("damage", 0) or 0)
        ):
            return None
        return offer_trade_is_worth_taking(self, choice.player_index, entry)

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
        """Pay when the seat can and should; an unpayable "unless you pay"
        entry applies its decline consequence (Hasran Ogress' damage).

        A *stated policy*, not the payability test. Floating mana is always
        spent; an untapped land only when ``ai_policy.optional_pay_may_tap_lands``
        says the tap is worth it — a toll always, a gift only with mana nothing
        else this turn would spend — because tapping is a real decision about
        the rest of the turn. ``_player_can_pay_optional`` is the wider question
        and belongs to the seat that was actually asked.

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
        # **Which mana the seat may spend**, and it is no longer always the
        # pool. "Never taps a land" was the whole of this policy's mana half,
        # and at the moments these offers arrive — an upkeep, a combat damage
        # step, the opponent's turn — the pool is empty, so the AI declined
        # every mana-priced offer it was ever made: Vaporous Djinn's "unless
        # you pay {U}{U}" sacrificed the Djinn at its first upkeep with two
        # Islands untapped, and Rootwater Thief never paid its {2}. Whether
        # tapping a land is worth it is a *weight* — pay tolls always, take
        # gifts only with mana nothing else this turn will spend — and it lives
        # with the other weights (`ai_policy.optional_pay_may_tap_lands`).
        # Paying is then the plan `_pay_optional` already spends, lands and all.
        from ....ai_prompts import optional_pay_may_tap_lands

        may_tap: list[bool] = []  # asked once, and only when the pool falls short

        def payable(cost) -> bool:
            if plan_payment(player.mana_pool, (), cost, payer=player) is not None:
                return True
            if not may_tap:
                may_tap.append(
                    optional_pay_may_tap_lands(self, choice.player_index, entry)
                )
            return may_tap[0] and plan_payment(
                player.mana_pool, self.payment_lands(player),
                cost, produces=self._land_payment_colors, payer=player,
            ) is not None

        # A life cost has no "already floating" reading — nothing is held in
        # reserve to spend — so the stated policy is the one a player at a
        # healthy life total would take: pay, unless it would be lethal.
        life_cost = int(entry.get("life_cost", 0) or 0)
        mana_covered = next(
            (
                True
                for cost in (
                    entry.get("cost") or {},
                    *(entry.get("cost_alternatives") or ()),
                )
                if payable(cost)
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
                    if payable(graded[index])
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
        # One link of an "unless any player pays" chain asks the effect's own
        # controller too, and paying is only right for the seat the unpaid
        # branch hurts (`ai_policy.chained_toll_declined`).
        from ....ai_prompts import (chained_toll_declined,
                                    offer_buys_own_drawback)

        if floating is not None and chained_toll_declined(
            self, choice.player_index, entry
        ):
            floating = None
            self.log.append(
                f"{player.name} declined to pay for {entry['card_name']}"
            )
        # The per-seat offer's version of the same question: what taking it
        # buys is a drawback to the seat's own permanent (Carrion Rats).
        elif floating is not None and offer_buys_own_drawback(
            self, choice.player_index, entry
        ):
            floating = None
            self.log.append(
                f"{player.name} declined {entry['card_name']} "
                "(it buys a drawback to their own permanent)"
            )
        # **A trade this policy can price on both sides is weighed, not
        # refused or taken by rule** (`ai_policy.offer_trade_is_worth_taking`:
        # a draw step for a land card, a card from hand for the source
        # untapped). Asked before the two constants below because each was
        # wrong about one of them: "make no trades" declined Forsaken City at
        # every upkeep, and "take gifts" took Elfhame Sanctuary's search at
        # every upkeep and with it the seat's every draw step.
        elif floating is not None and (
            weighed := self._weighed_offer_trade(choice)
        ) is not None:
            if not weighed:
                floating = None
                self.log.append(
                    f"{player.name} declined {entry['card_name']} "
                    "(the price is worth more than what it buys)"
                )
        # Take gifts, pay tolls, make no trades: an offer whose price is a deed
        # rather than a payment, and whose refusal the card prices at nothing,
        # is refused. A *toll* — an offer with a printed "if you don't" — is
        # still paid by default, because refusing it is not free either.
        elif floating is not None and self._offer_is_an_unpriced_trade(choice):
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
            from ....ai_prompts import toll_decline_is_smaller_loss

            if toll_decline_is_smaller_loss(
                self, choice.player_index, entry, self._offer_self_recipients(choice)
            ):
                floating = None
                self.log.append(
                    f"{player.name} declined {entry['card_name']} "
                    "(the penalty is the smaller loss)"
                )
        self.discard_pending_choice(choice)
        penalised = int(entry.get("damage", 0) or 0) > 0 or bool(entry.get("_on_decline"))
        if floating is not None and self._optional_action_still_takeable(
            choice.player_index, entry
        ):
            # A price the policy meant to pay and the board then could not
            # collect (a planned land that made nothing spendable) was not
            # paid — so an "unless" carries out its other half (CR 118.12a)
            # instead of being forgiven.
            if not self._pay_optional(choice.player_index, entry, option) and penalised:
                self._apply_optional_pay_decline(choice.player_index, entry)
        elif penalised:
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
