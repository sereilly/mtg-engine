"""Paying a cost an effect collects, from the pool and the board.

An effect that says "you may pay {1}{B}" gives its player no priority window,
so a payment here taps lands **for mana** through the planner
(``engine/mana_payment.plan_payment``) rather than spending only the pool:
``payment_lands`` is what may be planned over, ``_pay_planned_cost`` the tapping,
``_land_payment_colors`` what a land's tap really puts in the pool here. Power
Sink's "counter it unless its controller pays {X}" is the prompt built on them,
and the optional offers, the untap and the any-amount payment reuse the same
helpers from their own families.
"""

from __future__ import annotations

from .... import land_mana_swaps
from ....pending_choices import PendingChoice
from ....mana_payment import (generic_cost, mana_cost_label, plan_payment,
                              untapped_mana_lands)


class PaymentChoicesMixin:
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
            player.mana_pool, self.payment_lands(player), cost,
            produces=self._land_payment_colors, payer=player,
        )

    def narrowed_land_mana_colors(self, land) -> "tuple[str, ...] | None":
        """What *land*'s tap makes **here**, where the rest of the battlefield
        decides it, or None for a land that says what it makes.

        The ability the tap seam will run (``_land_mana_abilities``' free one),
        asked of ``mana_could_produce.ability_colors_on_offer`` — the handler's
        own reading of the two board-narrowed shapes. Empty is "this land makes
        nothing on this board", which the payment planner, the AI's tap plan
        and the client's colour picker must all be able to hear.
        """
        from ....mana_could_produce import ability_colors_on_offer

        free, _priced = self._land_mana_abilities(land)
        if free is None:
            return None
        return ability_colors_on_offer(self, land, free)

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
        # "A color of your choice" (Harvest Mage) is all five colours here,
        # which ``payment_colors`` answers so the client's colour prompt asks
        # the same question.
        swapped = land_mana_swaps.payment_colors(self, land)
        if swapped:
            return swapped
        # A land whose colours the *board* defines (Reflecting Pool, Meteor
        # Crater) answers with what that board offers now. Its printed summary
        # is every colour it could ever make, which this hook used to hand the
        # planner: a cost with a {B} in it read as payable off a Reflecting
        # Pool beside a Forest, the Pool was tapped, made {G}, and the payment
        # came up short.
        narrowed = self.narrowed_land_mana_colors(land)
        if narrowed is not None:
            return narrowed
        # A land whose own mana ability costs more than the tap and which a
        # gained land type gave a free one (a depletion land under Blanket of
        # Night): the tap makes the gained type's symbol and nothing else,
        # whatever the summary lists.
        gained_only = self._tap_alone_makes_only_gained_mana(land)
        if gained_only:
            return gained_only
        own = tuple(land.effective_produced_mana or ())
        # "Lands you control have "{T}: Add two mana of any one color.""
        # (Overlaid Terrain.) A *granted* mana ability, which the printed
        # ``produced_mana`` summary knows nothing about — so a Forest carrying
        # it would read as green-only and neither the planner nor the client
        # would ever ask for another colour. Asked of the ability the tap seam
        # will actually run (``_land_mana_abilities``), and only where the
        # summary does not already name all five, so a City of Brass keeps the
        # answer and the order it has always had.
        if not set(land_mana_swaps.COLORS) <= set(own):
            free, _priced = self._land_mana_abilities(land)
            if free is not None and (free.payload or {}).get("any_color"):
                return land_mana_swaps.COLORS
        # **Per ability, not per land** (CR 605: each mana ability is its
        # own). ``own`` is the printed summary — every symbol *any* ability
        # of the land makes, whatever that ability costs — and this hook is
        # asked what **a tap** would add. So a land with compiled tap-alone
        # abilities answers with what those make
        # (``board_payment.tap_alone_symbols``): a School of the Unseen is
        # {C}, not five colours behind a {2} nobody is paying, and a Tinder
        # Farm is {G}, not the {R}{W} of a sacrifice. A painland still
        # answers both its colours, because both its abilities are the tap
        # alone — and the seam runs the one that makes the colour asked for
        # (``tap_land_for_mana``), which is what keeps this answer true.
        #
        # A land with no compiled tap-alone ability is the summary path's (a
        # basic, a dual), and one whose ability's shape is not read keeps the
        # summary too: both come back None.
        from ....board_payment import tap_alone_symbols

        tapped_for = tap_alone_symbols(self, land)
        if tapped_for is not None:
            return tapped_for
        return own

    def _default_mana_payment(self, choice: PendingChoice) -> None:
        controller = self.players[choice.player_index]
        self._resolve_mana_payment(
            choice, self._counter_payment_plan_any(controller, choice.data) is not None
        )

    def _counter_payment_plan_any(self, player, data: dict):
        """The first of the offer's printed costs *player* can cover, as a plan,
        or None when they can cover none of them.

        "…unless its controller pays {1} **and 1 life**" (Mundungu) is one
        offer with two prices, so a payer who can meet only one of them can
        meet neither: CR 119.4 lets life be paid only down to 0, and a plan
        returned without checking it would spend the mana and then charge life
        the player does not have. The life is not an *alternative* — CR 118.8's
        "or 1 life" is the opposite word — so it gates every printed cost
        rather than standing beside them.
        """
        if int(data.get("life", 0) or 0) > player.life:
            return None
        for cost in self._mana_payment_costs(data):
            plan = self._counter_payment_plan(player, cost)
            if plan is not None:
                return cost, plan
        return None

    def seat_answers_for_itself(self, player_index: int) -> bool:
        """Whether *player_index* is a seat somebody is asking (a person at the
        table), as against one the engine answers for.

        The line "pay" is read across. A seat the engine answers for that
        cannot pay has declined — there is nobody to tell and nothing else it
        would have done. A person who says "pay" and cannot be paid for has
        **not** said "don't": CR 608.2d lets a player choose only an option
        that is possible, and CR 118.3 makes a cost they cannot pay fully one
        they cannot pay, so the answer is not one and the question stands —
        for them to tap what they like (CR 605.3a; activating a mana ability
        is theirs to decide, CR 118.3c) and answer again, or to decline.
        """
        return player_index in self.interactive_seats

    def mana_payment_is_payable(self, choice: PendingChoice) -> bool:
        """Whether "pay" would be accepted for this counter-unless price right
        now: the pool, plus the lands the payer the engine plans for would tap.

        One reader for the prompt's ``payable`` and for the refusal below, so
        what a client is shown before the click and what the click is told
        cannot be two answers.
        """
        return self._counter_payment_plan_any(
            self.players[choice.player_index], choice.data
        ) is not None

    def _resolve_mana_payment(
        self, choice: PendingChoice, pay: bool, *, asked: bool = False,
    ) -> bool:
        """Pay the price or have the object countered.

        *asked* is whether this is a seat's own answer (the registered
        ``resolve``) rather than the default taken for it. With it, a person's
        "pay" that cannot be collected is **refused** and the prompt stays
        owed — it used to be read as a decline: Mana Leak on a human's
        Lightning Bolt with an Island, a filter land and a Sol Ring untapped,
        "Pay", and the Bolt was countered with nothing tapped and no word
        said, because the planner taps free land abilities only. See
        :meth:`seat_answers_for_itself`.
        """
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
        held = bool(pay) and asked and self.seat_answers_for_itself(choice.player_index)
        if held and chosen is None:
            return False
        cost, plan = chosen if chosen is not None else (cost, None)
        if plan is not None:
            # The planned lands are tapped **for mana** (CR 605.3a), through
            # the one payer every effect-collected cost shares: this is the
            # payment Price of Glory is printed for, and it used to tap the
            # lands without anything hearing that they had made mana. A price
            # that cannot be met after all is a price not paid, and the spell
            # is countered below as if it had been declined.
            paid_cost = cost
            if not self._pay_planned_cost(
                controller,
                lambda: self._counter_payment_plan(controller, paid_cost),
            ):
                if held:
                    # Part-way: a land the plan counted made nothing it could
                    # spend. What was tapped stays tapped and its mana stays
                    # in the pool, as for any player who tapped and came up
                    # short — and the question is still theirs to answer.
                    return False
                plan = None
        if plan is not None:
            # "…and 1 life" (Mundungu). Charged after the mana and before the
            # object is left alone, because the two are one payment: the plan
            # above is only returned when both halves can be met, so nothing
            # here can leave a spell half-paid for.
            life = int(data.get("life", 0) or 0)
            if life:
                controller.life -= life
            name = target.card.name if target is not None else "the spell"
            self.log.append(
                f"{controller.name} paid {mana_cost_label(cost)}"
                + (f" and {life} life" if life else "")
                + f"; {name} is not countered"
            )
        else:
            # Declined or unable to pay: the spell is countered and Power Sink's rider
            # (tap all the controller's lands, drain their mana) applies.
            if target is not None and any(obj is target for obj in self.stack):
                # CR 701.6a through the one seam, which is also what announces
                # it: a spell countered for an unpaid cost is countered exactly
                # as one countered by a Counterspell is.
                self.counter_stack_object(target)
                if data.get("countered_object") == "ability":
                    # An ability on the stack has no card (CR 113.7a): removing
                    # it from the stack is the whole of CR 701.6a for it, and
                    # binning `target.card` would put the *source permanent's*
                    # card in a graveyard it never left.
                    self.log.append(
                        f"{data['card_name']} countered {target.card.name}'s ability"
                    )
                elif target.is_copy:
                    # 704.5e: a countered copy of a spell ceases to exist.
                    self.log.append(f"{data['card_name']} countered {target.card.name} (copy), which ceases to exist")
                elif self._redirect_unpaid_countered_card(data, target):
                    # "…If that spell is countered this way, exile it instead
                    # of putting it into its owner's graveyard." (Syncopate.)
                    pass
                else:
                    # The payer is the spell's *controller*; the card goes to
                    # its *owner's* graveyard (CR 701.6a, CR 108.3), and the
                    # two are different seats for a spell cast out of another
                    # player's zone.
                    self._bin_spell_card(
                        self.players[target.owner_index], target.card,
                        exile_instead=target.exile_instead_of_graveyard,
                        verb=f"was countered by {data['card_name']}",
                    )
                if counter_card is not None:
                    from ....card_hooks import ON_SPELL_COUNTERED
                    hook = ON_SPELL_COUNTERED.get(data["card_name"])
                    if hook is not None:
                        hook(self, counter_card, target)
        self.discard_pending_choice(choice)
        return True

    def _redirect_unpaid_countered_card(self, data: dict, target) -> bool:
        """Send a spell countered for an unpaid price where its counterspell
        prints, and say whether one did (CR 614.1 over CR 701.6a).

        "Counter target spell unless its controller pays {X}. If that spell is
        countered this way, exile it instead of putting it into its owner's
        graveyard." (Syncopate.) The hard counter redirects in its own
        handler; a priced one counters *here*, after the payer declined, so
        the destination rides the prompt. Through the handler's own
        ``_redirect_countered_card`` - one mover for both roads - and with its
        class test ("if an artifact or creature spell is countered this way",
        Desertion's narrowing) asked of the card exactly as it is there.
        """
        destination = data.get("countered_destination")
        counter_card = data.get("counter_card")
        if not destination or counter_card is None:
            return False
        from ....handlers._filters import _card_matches_filter
        from ....handlers.stack import _redirect_countered_card

        described = data.get("countered_filter")
        if described and not _card_matches_filter(target.card, described):
            return False
        seat = data.get("counterer_index")
        _redirect_countered_card(
            self, counter_card, target, str(destination),
            counterer=self.players[seat] if isinstance(seat, int) else None,
        )
        return True

    # -- Planning and tapping for a cost an effect collects -------------------

    def payment_lands(self, seat) -> list:
        """The lands a cost an effect collects may be planned over: *seat*'s
        untapped mana lands **whose tap would pay**.

        ``mana_payment.untapped_mana_lands`` is the pure half — a land, not
        tapped, with a free mana ability. Whether tapping it puts mana in the
        pool that this payment can spend is the game's to answer, and two
        readers already answer it for the AI's cast plan: the tap seam's own
        gate (``land_mana_tap_refusal`` — a summoning-sick land creature, a
        land under Interdict) and ``ai_policy._land_mana_is_unplannable``
        (mana that may be spent only on something else, CR 106.6; an amount or
        a colour the board decides and decides at nothing). A plan that
        counted such a land said "can pay", tapped it, and failed part-way —
        twelve cases in the tap census — which every payer then had to
        survive: the counterspell countered, the upkeep logged "paid".

        One reader for every payment with no priority window behind it — the
        optional offer, counter-unless, pay-any-amount, the upkeep prices,
        the attack and block tolls, the special actions — so "can pay" and
        "pay it" are asked of one list. A land left out is not lost to a
        person: it is mana beyond the plan (:meth:`mana_beyond_the_plan`),
        theirs to tap before they answer.
        """
        from ....ai_mana_sources import _land_mana_is_unplannable

        return [
            land
            for land in untapped_mana_lands(self.controlled_by(seat))
            if self.land_mana_tap_refusal(land) is None
            and not _land_mana_is_unplannable(self, land)
        ]

    def _pay_planned_cost(self, player, planner, *, spend=None) -> bool:
        """Pay a cost an effect collects, and say whether it was paid.

        *planner* answers ``mana_payment.plan_payment`` for the cost **against
        the board as it stands** each time it is called (None: cannot be
        paid). One writer for every such cost — an optional "you may pay", a
        counterspell's "unless its controller pays", an upkeep price, an
        attack or block toll, a special action — because a plan is *how* a
        cost is paid and a second spelling of it is a second answer.

        **A planned land is tapped for mana, not merely tapped.** CR 605.3a:
        a player may activate a mana ability "whenever a rule or effect asks
        for a mana payment, even if it's in the middle of … resolving a
        spell", and that is the only thing this payment can be — the payer
        has no priority window, so the engine activates the mana abilities on
        their behalf. It used to stop short of doing so: the planned lands
        were tapped with ``become_tapped`` and the cost was deemed paid. No
        mana ability ran, so nothing that follows from one happened either —
        a painland dealt no damage, an Ancient Tomb neither hurt nor made its
        second mana, a depletion land took no counter, and no "whenever a
        player taps a land for mana" heard a thing: an opponent paying a
        Force Spike on your turn kept the land Price of Glory should have
        destroyed, and Manabarbs, Mana Flare, Storm Cauldron and Wild Growth
        were silent for every cost an effect charged.

        So each planned land goes through ``tap_land_for_mana`` — the tap
        seam, whose event is the one every other road announces — **one at a
        time, and the plan is asked again after each**. Asking again is what
        makes the mana the tap really made count: under Mana Flare one land
        makes two and the second planned land stays untapped; an Ancient
        Tomb's second mana pays the next generic; and a tap a watcher answered
        by changing the board (Mana Web tapping the rest) is planned around
        rather than assumed. When the pool alone covers the cost it is spent,
        through *spend* where a caller draws on more than the open pool (the
        upkeep's restricted bucket).

        False when the cost could not be met — up front, or part-way, in
        which case the lands already tapped stay tapped and what they made
        stays in the pool, exactly as for a player who tapped and then could
        not pay. Callers treat it as the cost not having been paid.
        """
        seat = next(
            (index for index, found in enumerate(self.players) if found is player),
            None,
        )
        if seat is None:
            return False
        # Each pass taps one land or finishes, so the bound is the board.
        for _ in range(2 + sum(1 for _perm in self.controlled_by(seat))):
            plan = planner()
            if plan is None:
                return False
            if not plan.tapped:
                if spend is not None:
                    spend(plan)
                else:
                    for symbol, amount in plan.from_pool.items():
                        player.mana_pool[symbol] = (
                            int(player.mana_pool.get(symbol, 0)) - amount
                        )
                return True
            land = plan.tapped[0]
            wanted = plan.tapped_for[0] if plan.tapped_for else None
            color = self._planned_tap_color(land, wanted)
            if not self.tap_land_for_mana(
                seat, land.card.name, color,
                permanent_id=land.permanent_id,
                # Which of the land's mana abilities makes that colour
                # (CR 605): a painland's first is "{T}: Add {C}".
                ability_index=self.land_mana_ability_for(land, color),
            ):
                # The seam refused a land the planner counted (a summoning-
                # sick land creature, a land under Interdict). Refused is not
                # paid: tapping it anyway is the free mana this used to make.
                return False
        return False

    def _planned_tap_color(self, land, wanted: "str | None") -> str:
        """The symbol a payment plan asks *land* for.

        The pip the plan matched it to, when the land makes that symbol; else
        the first symbol it makes — a land the generic part took, or one whose
        mana pays the pip only *as* another colour (CR 106.6: white as any
        colour under Celestial Dawn, where no land "produces" the pip).
        """
        from ....ai_valuation import mana_ability_symbols

        offered = [str(symbol).upper() for symbol in self._land_payment_colors(land)]
        if wanted is not None and str(wanted).upper() in offered:
            return str(wanted).upper()
        # Nothing in particular is wanted of it, so it is asked for what its
        # **default** ability makes: a painland pays a generic pip with the
        # {C} that costs it nothing, never with the colour that hurts.
        free, _priced = self._land_mana_abilities(land)
        default = mana_ability_symbols(free) if free is not None else frozenset()
        for symbol in offered:
            if symbol in default:
                return symbol
        return offered[0] if offered else "C"

    def mana_beyond_the_plan(self, seat) -> bool:
        """Whether *seat* controls an untapped source of mana the payment
        planner does not tap for it.

        The planner taps a land's free mana ability and nothing else
        (``mana_payment.untapped_mana_lands``): a Sol Ring, a Mox, a Llanowar
        Elves, a filter land's "{1}, {T}: Add {U}{B}" and a storage land are
        all the player's own to activate (CR 605.3a), and all are mana a plan
        over this board says is not there. So "the plan cannot pay" is "this
        seat cannot pay" only where this answers no.

        Read off what the permanent makes (CR 106.1, through the layers) and
        not off why the planner left it out — the planner's reasons are a list
        that grows, and the question here is only whether anything is left.
        """
        mine = list(self.controlled_by(seat))
        planned = self.payment_lands(seat)
        return any(
            not perm.tapped
            and perm.effective_produced_mana
            and not any(perm is land for land in planned)
            for perm in mine
        )
