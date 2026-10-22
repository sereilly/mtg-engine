"""A spell's additional costs (CR 601.2b, CR 601.2f–h): announced, checked
and paid.

Three sources of them, one shape. The printed ones ("As an additional cost to
cast this spell, sacrifice a creature"); the optional ones a cast announces it
is paying (kicker, buyback — read off the announcement by
``_optional_cost_announcement`` and charged through ``optional_cost_taken``,
the one reader the gate, the payment and the picker share); and the
sacrifices a board tax adds (Drought — ``_sacrifice_tax_victims``, which the
activation path asks too, CR 602.2b being the same announcement step).

Each has the moments every cost the cast path pays has: whether the board can
pay it at all (``_unpayable_additional_cost``), whether what the caster
*named* to pay it can (``_named_cast_cost_refusal``,
``_named_graveyard_cost_refusal`` — CR 601.2h: a named payer pays, or the
spell is not cast), and the payment, which returns what it ate for the
resolution to read back (``_pay_additional_costs``).

Split out of ``casting.py`` at the 2,000-line cap, and composed onto ``Game``
with the other parts of ``SpellCastingMixin``, directly after it.
"""

from __future__ import annotations

import random

from ...cast_costs import AdditionalCost, OptionalManaCost, graveyard_card_noun
from ...models import CardDefinition, Permanent
from ...oracle import compile_card_oracle
from ...subject_filters import card_matches_any, filter_head_noun, subject_matches


def _optional_cost_offers(
    costs: "tuple[AdditionalCost, ...]",
) -> dict[str, OptionalManaCost]:
    """Every CR 601.2b optional mana offer *costs* prints, by its canonical
    spelling.

    One dict for the whole cast rather than a walk per question, because the
    read-back at resolution is keyed the same way: "for each additional {1}{R}
    you paid" names the offer by its symbols, and two sentences of one card must
    not disagree about which offer that is.
    """
    return {
        offer.symbols: offer
        for cost in costs
        for offer in cost.optional_mana
    }


def _optional_cost_keys(
    costs: "tuple[AdditionalCost, ...]",
) -> dict[str, bool]:
    """Every CR 601.2b optional price announceable for this cast, mapped to
    whether it is repeatable.

    Two kinds, one namespace, because the announcement carries one map: a run of
    mana symbols the cast folds into its payment ("you may pay {1}{R}") and a
    non-mana price ``_pay_additional_costs`` collects ("Buyback—Sacrifice a
    land"). A caster names either by the same key, so the check that a named
    offer exists has to see both — a check that saw only the mana ones would
    refuse Constant Mists' buyback as a cost the card does not print.
    """
    keys = {
        offer.symbols: offer.repeatable
        for cost in costs
        for offer in cost.optional_mana
    }
    for cost in costs:
        if cost.optional_key is not None:
            # A printed non-mana price is taken once or declined; there is no
            # "any number of times" spelling of one in the pool, and admitting a
            # count would charge a sacrifice the payment collects once.
            keys.setdefault(cost.optional_key, False)
    return keys


def optional_cost_taken(cost: "AdditionalCost", taken: dict | None) -> bool:
    """Whether *cost* is charged on this cast (CR 601.2b).

    True for every mandatory cost, which is all but one card in the pool, and
    for an optional one exactly when the announcement took it. The one reader
    the gate, the payment and the picker share — an offer the gate refused for
    and the payment then declined to collect would be a spell uncastable for a
    price it never charges.
    """
    if cost.optional_key is None:
        return True
    try:
        return int((taken or {}).get(cost.optional_key, 0) or 0) > 0
    except (TypeError, ValueError):
        return False


def _optional_cost_announcement(
    card: CardDefinition,
    costs: "tuple[AdditionalCost, ...]",
    announced: dict[str, int] | None,
) -> tuple[dict[str, int], str | None]:
    """How many times each optional additional cost is being paid, or a refusal.

    CR 601.2b: the caster announces this as the spell is cast, before targets
    and long before payment, and the announcement is *checked* here — an
    announcement naming an offer the card does not print, or taking a
    non-repeating offer twice, is an illegal proposal that CR 601.2e rewinds
    rather than a payment to clamp. Nothing has been spent at this point, so a
    refusal costs the caster exactly nothing.

    An absent or empty announcement declines every offer, which is what
    *optional* means and the only default that cannot charge a player for a
    price they did not accept.
    """
    offers = _optional_cost_keys(costs)
    taken: dict[str, int] = {}
    for symbols, times in (announced or {}).items():
        count = int(times or 0)
        if count <= 0:
            continue
        key = str(symbols)
        if key not in offers:
            printed = ", ".join(sorted(offers)) or "none"
            return {}, (
                f"{card.name} prints no additional cost of {symbols} "
                f"(it offers: {printed}) (CR 601.2b)"
            )
        if count > 1 and not offers[key]:
            return {}, (
                f"{card.name}'s additional cost of {key} may be paid "
                f"once, not {count} times (CR 601.2b)"
            )
        taken[key] = count
    return taken, None


def _taken_offers(announced: dict | None) -> dict[str, int]:
    """The optional additional costs an announcement **took**, by key — the
    half of :func:`_optional_cost_announcement` that does not judge them.

    For a reader that needs CR 601.2b's answer before that gate has run: the
    bare-cast default asks which slot the cast owes (CR 702.33g — a
    kicked-only target is a target of a kicked cast alone), and an
    announcement the gate goes on to refuse has cost nothing by then.
    """
    taken: dict[str, int] = {}
    for symbols, times in (announced or {}).items():
        try:
            count = int(times or 0)
        except (TypeError, ValueError):
            continue
        if count > 0:
            taken[str(symbols)] = count
    return taken


def _optional_cost_totals(
    costs: "tuple[AdditionalCost, ...]", taken: dict[str, int]
) -> "list[tuple[OptionalManaCost, int]]":
    """The offers actually taken, paired with how many times.

    Read back off the printed offers rather than off the announcement's keys, so
    the mana charged is the mana the *card* prints — a caller that sent a
    canonical-looking key nothing prints was already refused above, and this
    keeps the charge and the record derived from one list.
    """
    offers = _optional_cost_offers(costs)
    return [
        (offers[symbols], times)
        for symbols, times in taken.items()
        if symbols in offers
    ]


class AdditionalCastCostsMixin:
    # ------------------------------------------------------------------
    # Printed additional costs (CR 601.2b)
    # ------------------------------------------------------------------

    #: Which field of a printed cost each verb spends. A table rather than a
    #: chain, because the two cost classes carry different subsets of it: an
    #: alternative cost has a sacrifice and no exile, so the arm that is *not*
    #: taken must not be evaluated.
    _COST_CANDIDATE_FIELDS = {
        "sacrifice": "sacrifice_filter",
        "sacrifice_all": "sacrifice_all_filter",
        "return": "return_filter",
        "exile": "exile_filter",
        # CR 118.9's alternative cost prints a *tap* where no additional cost in
        # this pool does ("you may tap an untapped creature you control rather
        # than pay this spell's mana cost", Orim's Cure). The verb differs and
        # the question does not: which permanents on the payer's own
        # battlefield the printed noun phrase names. ``untapped_only`` rides on
        # the payload, so the scan below needs no branch for it.
        "tap": "tap_filter",
    }

    def _additional_cost_candidates(
        self, caster_index: int, cost: AdditionalCost, *, giving_up: str = "sacrifice",
    ) -> list[Permanent]:
        """The permanents that could pay *cost*'s sacrifice or exile, by identity.

        Never by index: an index would be held across the removal that paying
        performs, and would then name whichever permanent slid into the slot.

        One enumeration for both verbs, because they ask one question — which
        permanents on the payer's own battlefield the printed noun phrase names
        (CR 601.2b). What differs is where the object goes afterwards, which is
        the payment's business and not the candidate list's.
        """
        # ``getattr``, and lazily: an :class:`AlternativeCost` carries the
        # sacrifice fields and none of the others, so a table whose *default*
        # arm reads ``cost.exile_filter`` raises on the very cost this is most
        # often asked about. That is what the Fireblast tests caught.
        described = getattr(cost, self._COST_CANDIDATE_FIELDS[giving_up], None)
        if described is None:
            return []
        return [
            perm
            for perm in self.controlled_by(caster_index)
            # The observer is the payer: "a creature **you control**" is a
            # seat comparison, and a payload carrying one with no observer to
            # compare against refuses every candidate.
            if subject_matches(self, perm, described, observer=caster_index)
        ]

    def _sacrifice_tax_victims(
        self, payer_index: int, demands: tuple
    ) -> "list[Permanent] | str":
        """The permanents that will pay every imposed sacrifice, or the reason
        they cannot (CR 601.2h).

        Picked once, across *all* the demands together: two Droughts want two
        Swamps each and one Swamp cannot pay both, which is what asking each
        demand its own question would have said. The picks are removed from the
        pool as they are made, and the payer's own deterministic order is the
        one every other sacrifice cost uses.

        Shared by the cast path and the activation path, because CR 601.2b and
        CR 602.2b are the same announcement step — the same reason
        ``AdditionalCost.sacrifice_filter`` is one vocabulary.
        """
        chosen: list[Permanent] = []
        for demand in demands:
            for _ in range(demand.count):
                available = [
                    perm
                    for perm in self.controlled_by(payer_index)
                    if subject_matches(
                        self, perm, demand.described, observer=payer_index
                    )
                    and not any(taken is perm for taken in chosen)
                ]
                if not available:
                    return (
                        f"no {demand.noun.title()} left to sacrifice for "
                        f"{demand.source_name}"
                    )
                chosen.append(self.default_sacrifice_pick(available))
        return chosen

    def _pay_sacrifice_tax(self, victims: "list[Permanent]", why: str) -> None:
        """Sacrifice what ``_sacrifice_tax_victims`` picked. By identity, never
        by slot: each removal renumbers the battlefield behind it."""
        for victim in victims:
            name = victim.card.name
            if self.sacrifice_permanent(victim) is not None:
                self.log.append(f"{name} was sacrificed {why}")

    def _unpayable_additional_cost(
        self,
        caster_index: int,
        card: CardDefinition,
        costs: tuple[AdditionalCost, ...],
        *,
        spell_hand_index: int | None,
        from_zone: str,
        x_value: int | None = None,
        life_already_owed: int = 0,
        taken: dict[str, int] | None = None,
        spell_graveyard_slot: int | None = None,
    ) -> str | None:
        """Why *card*'s printed additional costs can't be paid, or None.

        CR 601.2h: "Unpayable costs can't be paid" — and CR 601.2 makes the
        whole casting a rewind, so the answer is that the spell is not cast,
        never that it is cast without the cost. Asked before any mana leaves the
        pool, so a refusal costs the caster nothing.

        *x_value* is the announced X (CR 601.2b), for the one cost whose amount
        is not printed: Fire Covenant's "pay X life". It reaches both this and
        the payment through ``AdditionalCost.life_charged``, so the gate and the
        charge cannot come to disagree about the number.

        *spell_graveyard_slot* is where the spell itself sits in the caster's
        graveyard when it is being cast from there (CR 601.2a: it is on the
        stack before a cost is paid, so it is not a card a graveyard exile can
        take). Without it Skeletal Scrying cast out of a graveyard of five for
        X = 5 counted itself, was admitted, and then found four.
        """
        caster = self.players[caster_index]
        for cost in costs:
            # CR 601.2b's *optional* price (Constant Mists' buyback). An offer
            # nobody took costs nothing, so it cannot make the spell
            # uncastable -- and one that *was* taken is a price like any other
            # from here down, gated on the same board this reads for the
            # mandatory ones.
            if not optional_cost_taken(cost, taken):
                continue
            # "…, **choose a number between 0 and 5**." (Liquid Fire.) The
            # number is the cast's announced X (CR 601.2b: a variable defined
            # by a choice made in the announcement is chosen then), so a number
            # outside the printed range is not a choice the card offers — and
            # CR 601.2e returns the game to before a proposal that made one.
            # Here with the other gates, before anything is spent. A mana cost
            # that prints {X} would make one announcement both a price and a
            # choice from a range; no card prints the pair, and it refuses
            # rather than charge the chosen number in mana.
            if cost.choose_number is not None:
                refused = cost.number_refusal(x_value)
                if refused is None and "{X}" in (card.mana_cost or "").upper():
                    refused = "its {X} is already the number its mana cost charges"
                if refused is not None:
                    return (
                        f"{card.name} can't be cast: {refused} "
                        f"(CR 601.2b)"
                    )
            if cost.sacrifice_filter is not None:
                # "…, sacrifice **two** creatures." (Phyrexian Tribute.) The
                # *count* is what makes such a cost unpayable: one creature is
                # no more a payment than none, and a gate that asked only
                # whether one existed would admit the cast and then charge one
                # -- a spell cast for less than it prints. The same question
                # `activate_permanent_ability` asks of Goblin Warrens, because
                # CR 601.2b and CR 602.2b are one announcement step.
                available = self._additional_cost_candidates(caster_index, cost)
                wanted = max(1, cost.sacrifice_count)
                if len(available) < wanted:
                    noun = filter_head_noun(cost.sacrifice_filter)
                    shortfall = (
                        f"no {noun}" if wanted == 1 else f"not enough {noun}s"
                    )
                    return (
                        f"{card.name} can't be cast: {shortfall} to "
                        f"sacrifice for its additional cost (CR 601.2h)"
                    )
            # "…, **return X Swamps you control to their owner's hand**."
            # (Infernal Harvest.) Gated on the *announced* count (CR 107.3a),
            # which is the whole of what makes this unpayable: three Swamps is
            # no payment for an X of four, and a gate that asked only whether
            # one existed would admit the cast and then return whatever the
            # board had — a spell cast for less than the caster announced, with
            # its damage still sized by the announcement.
            if cost.return_filter is not None:
                wanted = cost.returned_count(x_value)
                available = self._additional_cost_candidates(
                    caster_index, cost, giving_up="return"
                )
                if len(available) < wanted:
                    noun = filter_head_noun(cost.return_filter)
                    return (
                        f"{card.name} can't be cast: {caster.name} controls "
                        f"{len(available)} {noun}(s) and its additional cost "
                        f"returns {wanted} (CR 601.2h)"
                    )
            # "…, **exile a creature you control**." (Soul Exchange.) Gated
            # beside the sacrifice and for the same rule: CR 601.2h makes an
            # unpayable cost an uncastable spell, never a free one.
            if cost.exile_filter is not None:
                if not self._additional_cost_candidates(
                    caster_index, cost, giving_up="exile"
                ):
                    return (
                        f"{card.name} can't be cast: no "
                        f"{filter_head_noun(cost.exile_filter)} to "
                        f"exile for its additional cost (CR 601.2h)"
                    )
            # "…, **exile X creature cards from your graveyard**." (Haunting
            # Misery.) The same rule one zone over, and the *count* is the whole
            # of it: CR 107.3a has the caster announce X as part of casting, so
            # a graveyard holding two creature cards cannot pay an announced
            # three — and a gate that asked only whether one existed would admit
            # the cast and then charge what it found, a spell cast for a
            # fraction of its price. Through the same enumeration the payment
            # picks from, so the two cannot count different sets.
            if cost.exile_graveyard_filter is not None:
                wanted = cost.exiled_from_graveyard(x_value)
                available = self._graveyard_exile_candidates(
                    caster_index, cost, spell_slot=spell_graveyard_slot,
                )
                if len(available) < wanted:
                    noun = graveyard_card_noun(cost.exile_graveyard_filter)
                    return (
                        f"{card.name} can't be cast: {caster.name}'s graveyard "
                        f"holds {len(available)} {noun}(s) and its "
                        f"additional cost exiles {wanted} (CR 601.2h)"
                    )
            # CR 119.4: a player may pay life only down to 0, and CR 601.2h then
            # makes an unpayable cost an uncastable spell rather than a free
            # one. Checked with the others, before anything is spent.
            life = cost.life_charged(x_value)
            # Against what the cost increases have already claimed, not against
            # the raw total: CR 601.2f's increases and CR 601.2b's printed cost
            # are paid out of one life total, and a gate reading it twice would
            # admit a pair of prices the caster can meet only one at a time.
            available = caster.life - max(0, life_already_owed)
            if life and available < life:
                return (
                    f"{card.name} can't be cast: {caster.name} cannot pay "
                    f"{life} life with {available} remaining "
                    f"(CR 601.2h)"
                )
            if cost.discard_cards:
                # The spell itself is still in the zone it is being cast from,
                # and it is about to be on the stack — so it cannot be one of
                # the cards discarded to pay for itself.
                #
                # Counted over the cards the printed phrase *names* rather than
                # over the whole hand ("discard a **red or green** card", Surge
                # of Strength), through the same matcher the payment picks with
                # — a gate that counted the hand would admit a cast the payment
                # then could not collect, and the payment would fall back to
                # discarding whatever was first.
                payable = self._discard_cost_payers(
                    caster_index, cost,
                    spell_hand_index=(
                        spell_hand_index if from_zone == "hand" else None
                    ),
                )
                # "…, discard **X** cards." (Firestorm.) Gated on the
                # *announced* count (CR 107.3a) for the reason the return and
                # the graveyard exile above are: a hand of two is no payment
                # for an announced three, and a gate that asked only whether one
                # card existed would admit the cast and then discard what it
                # found — a spell cast for less than the caster announced, with
                # its damage still sized by the announcement.
                if len(payable) < cost.discarded_count(x_value):
                    shortfall = (
                        "no card in hand answers this cost"
                        if cost.discard_filters
                        else "not enough cards in hand to discard"
                    )
                    return (
                        f"{card.name} can't be cast: {shortfall} "
                        f"for its additional cost (CR 601.2h)"
                    )
        return None

    @staticmethod
    def _chosen_cast_cost_demands(
        costs: tuple[AdditionalCost, ...],
        *,
        x_value: int | None,
        taken: dict[str, int] | None,
    ) -> "list[tuple[str, AdditionalCost, int]]":
        """Every chosen-permanent price this cast charges, as ``(verb, cost,
        how many)`` in the order :meth:`_pay_additional_costs` collects them.

        One list for the gate that checks a named payment and the payment that
        takes it, so the two cannot count different prices: an offer nobody
        took is not in it (CR 601.2b), and an X is the announced one
        (CR 107.3a). "Sacrifice **all** permanents you control" is not in it
        either — a quantifier leaves nothing to choose.
        """
        demands: list[tuple[str, AdditionalCost, int]] = []
        for cost in costs:
            if not optional_cost_taken(cost, taken):
                continue
            if cost.exile_filter is not None:
                demands.append(("exile", cost, 1))
            if cost.sacrifice_filter is not None:
                demands.append(("sacrifice", cost, max(1, cost.sacrifice_count)))
            if cost.return_filter is not None:
                demands.append(("return", cost, cost.returned_count(x_value)))
        return demands

    def _named_cast_cost_payers(
        self,
        caster_index: int,
        cost_permanent_ids: "list[int] | None",
        cost_permanent_index: "int | None",
    ) -> "list[Permanent | None]":
        """Whom the caster named to pay, in the order they named them; ``None``
        stands for a name that finds no permanent.

        Two channels because a counted cost needs several names and
        ``cost_permanent_index`` can carry one: the id list is the channel
        every chosen cost permanent arrives on for an activation, and the
        single slot — counted into the **caster's** battlefield — is what every
        caller written before a counted cast cost existed still sends. The ids
        win where both arrive, which is what the wire sends for one click.
        """
        named: "list[Permanent | None]" = [
            self.permanent_by_id(permanent_id) if isinstance(permanent_id, int) else None
            for permanent_id in (cost_permanent_ids or ())
            if permanent_id is not None
        ]
        if not named and isinstance(cost_permanent_index, int) and not isinstance(
            cost_permanent_index, bool
        ):
            named.append(
                self.permanent_at(self.players[caster_index], cost_permanent_index)
            )
        return named

    def _named_cast_cost_refusal(
        self,
        caster_index: int,
        card: CardDefinition,
        costs: tuple[AdditionalCost, ...],
        *,
        cost_permanent_ids: "list[int] | None",
        cost_permanent_index: "int | None",
        x_value: int | None = None,
        taken: dict[str, int] | None = None,
    ) -> str | None:
        """Why the permanents the caster **named** to pay *card*'s additional
        costs cannot pay them, or None.

        CR 601.2h: "Partial payments are not allowed. Unpayable costs can't be
        paid" — and CR 601.2e sends a cast that cannot be completed as proposed
        back to the moment before it. A caster who names what they will
        sacrifice, exile or return has *announced* that payment; if what they
        named cannot make it, the cast is illegal. It is not a different cast
        paid with something else.

        The cast-side twin of ``_named_cost_refusal`` (the activation path's,
        which is CR 601.2h reached through CR 602.2b). Every charger in
        :meth:`_pay_additional_costs` honoured a named permanent "where it is
        legal" and otherwise took ``default_sacrifice_pick`` — right for a seat
        that named nothing and wrong for one that did. Diabolic Intent ("…,
        sacrifice a creature") told to sacrifice a Forest sacrificed a
        creature; Gaea's Balance ("…, sacrifice five lands") told to sacrifice
        four lands and a creature sacrificed five lands; a creature named on
        the other side of the table cost its caster one of their own. All 43
        spells in the pool whose additional cost hands its payer a choice did
        it, the eleven kicker and buyback ones included.

        Asked beside ``_unpayable_additional_cost`` and before anything is
        spent, over the same candidate lists the payment claims from, in the
        payment's own order:

        * a name that finds no permanent, or a permanent no price of this cast
          could take, refuses;
        * so does a permanent named twice — one creature is not two;
        * so does a list **shorter** than a counted price ("five lands", an
          announced X of Swamps). Topping it up from the default is the same
          substitution as replacing it: the caster pays with a land they did
          not name;
        * and so does a list longer than the cast charges.

        A cast that names **nobody** is not asked — every price then takes its
        deterministic default, the headless convention the AI and the test
        corpus stand on. Nor is a cast that charges no chosen permanent at all
        (an offer declined, a spell with no such cost): a stray cost field
        there names nothing and substitutes nothing.
        """
        demands = self._chosen_cast_cost_demands(costs, x_value=x_value, taken=taken)
        if not demands:
            return None
        named = self._named_cast_cost_payers(
            caster_index, cost_permanent_ids, cost_permanent_index
        )
        if not named:
            return None
        claimable = [
            (verb, wanted, self._additional_cost_candidates(caster_index, cost, giving_up=verb))
            for verb, cost, wanted in demands
        ]
        seen: list[Permanent] = []
        for found in named:
            if found is None:
                return (
                    f"{card.name} can't be cast: a permanent named to pay its "
                    f"additional cost is not on the battlefield (CR 601.2h)"
                )
            # By identity: `in` compares Permanents by value and would accept a
            # look-alike on the wrong battlefield.
            if not any(
                found is option for _verb, _wanted, options in claimable for option in options
            ):
                return (
                    f"{card.name} can't be cast: {found.card.name} cannot pay "
                    f"its additional cost (CR 601.2h)"
                )
            if any(found is earlier for earlier in seen):
                return (
                    f"{card.name} can't be cast: {found.card.name} is named "
                    f"twice and can pay its additional cost once (CR 601.2h)"
                )
            seen.append(found)
        # Claimed the way the payment claims them: each price takes, of what
        # is still unclaimed, the names its own candidates contain.
        unclaimed = list(named)
        for verb, wanted, options in claimable:
            claimed = [
                found for found in unclaimed
                if any(found is option for option in options)
            ][:wanted]
            if len(claimed) < wanted:
                return (
                    f"{card.name} can't be cast: its additional cost takes "
                    f"{wanted} permanent(s) to {verb} and {len(claimed)} "
                    f"were named (CR 601.2h)"
                )
            unclaimed = [
                found for found in unclaimed
                if not any(found is taken_one for taken_one in claimed)
            ]
        if unclaimed:
            return (
                f"{card.name} can't be cast: {unclaimed[0].card.name} is named "
                f"beyond what its additional cost takes (CR 601.2h)"
            )
        return None

    def _discard_cost_payers(
        self,
        caster_index: int,
        cost: AdditionalCost,
        *,
        spell_hand_index: int | None,
    ) -> list["CardDefinition"]:
        """The cards in hand that may pay *cost*'s discard, in hand order.

        One enumeration for the gate, the named-card check and the payment, so
        what is admitted and what is collected cannot disagree — the same
        arrangement ``_additional_cost_candidates`` makes for the sacrifice and
        the exile one zone over. The narrowing is read through
        ``card_matches_any``, which is what the activation path's identical
        discard cost is matched with (CR 601.2b and CR 602.2b are one
        announcement step).

        The spell is excluded **by index**, never by identity: a deck repeats
        one immutable ``CardDefinition`` per copy, so a second copy of the spell
        in hand is the *same object* and an identity filter would refuse the
        card that may legitimately pay.
        """
        return [
            held
            for position, held in enumerate(self.players[caster_index].hand)
            if position != spell_hand_index
            and card_matches_any(held, cost.discard_filters)
        ]

    def _resolve_discard_cost_cards(
        self,
        caster_index: int,
        card: CardDefinition,
        costs: tuple[AdditionalCost, ...],
        *,
        cost_hand_index: int | None,
        cost_other_hand_indices: "list[int] | None" = None,
        spell_hand_index: int | None,
        x_value: int | None = None,
    ) -> tuple["list[CardDefinition]", str | None]:
        """The cards a named ``cost_hand_index`` (and, for a cost that discards
        more than one, ``cost_other_hand_indices``) pick, or why they pick none.

        CR 601.2b's choices are announced while the spell is still being cast,
        so the index is into the hand the caster can see — the one that still
        holds the spell. Resolving it to a *card* here is what makes the answer
        survive the spell leaving that hand: an index is only meaningful
        alongside the list it was read from, which is the instability this
        engine addresses with ids on the battlefield and cannot here, because a
        hand holds ``CardDefinition``s and two copies of a card are one object.

        "Buyback—Discard **two** cards" (Forbid) is two choices, and the second
        rode the default until the "others" list existed: the same shape the
        alternative cost's "and another card" (Foil) announces on and the
        activation path's "Discard two cards" reads. Naming fewer than the cost
        takes leaves the rest to the default; naming more, or one twice, is a
        refusal.

        The spell itself is refused: CR 601.2a puts it on the stack before its
        costs are paid, so it is not in the hand to be discarded. Nothing named
        means the deterministic default, which keeps AI and headless play
        unblocked.
        """
        discarding = next((cost for cost in costs if cost.discard_cards), None)
        named = (
            [cost_hand_index] if cost_hand_index is not None else []
        ) + list(cost_other_hand_indices or ())
        if not named or discarding is None:
            return [], None
        hand = self.players[caster_index].hand
        # How many the cost takes is ``discarded_count`` -- the reader the gate
        # and the payment share -- and not the printed ``discard_cards``, which
        # is 1 for "discard **X** cards" (the Dreams, Firestorm): the field says
        # *that* there is a discard, the announced X says how many. Compared
        # with the field alone, an X of two could name one card and was refused
        # for naming two, so every discard past the first rode the default.
        #
        # The field stays a floor on what may be *named*: the browser's discard
        # picker is sized by it (one card) whatever X is, and a card named at an
        # X of zero is simply not charged — the payment loops ``owed`` times.
        owed = discarding.discarded_count(x_value)
        if len(set(named)) != len(named) or len(named) > max(
            owed, discarding.discard_cards
        ):
            return [], (
                f"{card.name} can't be cast: its additional cost discards "
                f"{owed} card(s), each named once (CR 601.2b)"
            )
        chosen: "list[CardDefinition]" = []
        for position in named:
            if not 0 <= position < len(hand):
                return [], (
                    f"{card.name} can't be cast: no card at hand position "
                    f"{position} to discard for its additional cost"
                )
            if position == spell_hand_index:
                return [], (
                    f"{card.name} can't be cast: it is on the stack (CR 601.2a) "
                    "and cannot be discarded to pay for itself"
                )
            # A named card that does not answer the printed phrase is an error,
            # not a cheaper cost — refused rather than quietly slid onto a legal
            # one, which is the same answer the activation path gives the
            # identical cost.
            if not card_matches_any(hand[position], discarding.discard_filters):
                return [], (
                    f"{card.name} can't be cast: {hand[position].name} does "
                    f"not answer its additional cost (CR 601.2b)"
                )
            chosen.append(hand[position])
        return chosen, None

    def _graveyard_exile_candidates(
        self, caster_index: int, cost: "AdditionalCost", *,
        spell_slot: int | None = None,
    ) -> list[int]:
        """Which cards in the caster's own graveyard could pay *cost*'s exile,
        as **indices** in pile order.

        One enumeration for the gate and the payment, the arrangement
        ``_alternative_cost_payers`` and ``_additional_cost_candidates`` both
        make and for their reason: a gate counting a different set from the one
        the payment takes from would admit a cast the payment cannot collect.

        Indices rather than cards, which is ``engine/graveyard_order.py``'s own
        rule: ``load_cards`` dedupes by ``oracle_id``, so two copies of one card
        in one graveyard are the same Python object and a caller handed only the
        card cannot say which copy it named — an identity filter would remove
        both.

        Through ``_card_matches_filter``, never the permanent matcher: a card in
        a graveyard has no computed characteristics (CR 613.1), and the charger
        that admitted this clause gated it on exactly the keys that function can
        answer.
        """
        from ...handlers._filters import _card_matches_filter

        described = dict(cost.exile_graveyard_filter or {})
        return [
            index
            for index, held in enumerate(self.players[caster_index].graveyard)
            # *spell_slot*: the spell being cast out of this pile, withheld by
            # position (CR 601.2a) — a second copy beside it is another card.
            if index != spell_slot and _card_matches_filter(held, described)
        ]

    def _named_graveyard_cost_refusal(
        self,
        caster_index: int,
        card: CardDefinition,
        costs: tuple[AdditionalCost, ...],
        named_slots: "list[int] | None",
        *,
        x_value: int | None = None,
        taken: dict[str, int] | None = None,
        spell_graveyard_slot: int | None = None,
    ) -> str | None:
        """Why the graveyard cards the caster **named** to pay "exile X cards
        from your graveyard" cannot pay it, or None.

        CR 601.2b lets the caster choose which cards leave (Skeletal Scrying,
        Haunting Misery) and CR 601.2h holds them to it: "Partial payments are
        not allowed." The pile half of :meth:`_named_cast_cost_refusal`, for a
        cost whose objects have no id to be named by — a card in a graveyard
        is a position, and a deck repeats one immutable ``CardDefinition`` per
        copy, so only the position tells two copies apart.

        The whole set or a refusal: every slot a card this cost could take
        (``_graveyard_exile_candidates``, the list the CR 601.2h gate counted
        and the payment takes from), none named twice, and exactly as many as
        the cost exiles — a short list topped up from the default is the
        caster paying with a card they did not name.

        A cast that names **no set** (``None``) is not asked and takes the
        deterministic pick, the headless convention. Nor is one that charges
        no graveyard exile at all: a stray field there names nothing.
        """
        if named_slots is None:
            return None
        demands = [
            (cost, cost.exiled_from_graveyard(x_value))
            for cost in costs
            if cost.exile_graveyard_filter is not None
            and optional_cost_taken(cost, taken)
        ]
        if not demands:
            return None
        slots = list(named_slots)
        cost, wanted = demands[0]
        candidates = self._graveyard_exile_candidates(
            caster_index, cost, spell_slot=spell_graveyard_slot,
        )
        for slot in slots:
            if (
                not isinstance(slot, int) or isinstance(slot, bool)
                or slot not in candidates
            ):
                return (
                    f"{card.name} can't be cast: no card at graveyard position "
                    f"{slot} that can be exiled for its additional cost "
                    f"(CR 601.2h)"
                )
        if len(set(slots)) != len(slots):
            return (
                f"{card.name} can't be cast: graveyard positions {slots} name "
                f"one card more than once for its additional cost (CR 601.2h)"
            )
        if len(slots) != wanted:
            return (
                f"{card.name} can't be cast: its additional cost exiles "
                f"{wanted} card(s) from the graveyard and {len(slots)} were "
                f"named (CR 601.2h)"
            )
        return None

    def _pay_additional_costs(
        self,
        caster_index: int,
        card: CardDefinition,
        costs: tuple[AdditionalCost, ...],
        *,
        cost_permanent_index: int | None,
        cost_hand_cards: "list[CardDefinition] | None" = None,
        x_value: int | None = None,
        cost_permanent_ids: list[int] | None = None,
        taken: dict[str, int] | None = None,
        cost_graveyard_indices: list[int] | None = None,
    ) -> dict:
        """Perform *card*'s printed additional costs, returning what they ate.

        A record rather than one permanent, keyed by the same channel names the
        activation path records its costs on (``sacrificed_for_cost``,
        ``exiled_for_cost``) — so a spell reading back what its cost consumed
        asks the same question whether a cast or an activation paid it. Soul
        Exchange's "if the exiled creature was a Thrull" is the first reader on
        the cast side.

        The payer chooses (CR 601.2b), and the choice arrives with the action
        rather than through the pending-choice queue — a queued prompt would put
        the spell on the stack before its cost was collected, which is the
        reasoning ``activate_permanent_ability`` already records for the
        identically-shaped activation costs. A seat that names nothing gets a
        deterministic pick so AI and headless play stay unblocked.
        """
        caster = self.players[caster_index]
        sacrificed: Permanent | None = None
        exiled: Permanent | None = None
        # Every card a printed discard took, in the order it took them — the
        # channel an activation's discard cost has recorded on since Land's
        # Edge, written here for the first spell that reads it back: "…where X
        # is **the discarded card's mana value**" (Dralnu's Pet).
        discarded_cards: list[CardDefinition] = []
        # The named discards, in the order they were named; each pays one card.
        named_discards = list(cost_hand_cards or ())
        # The permanents the caster named, each claimed once by the first
        # price below whose candidates contain it. ``_named_cast_cost_refusal``
        # has already held a named list to exactly what these prices take, so
        # a default pick beneath a named one is reached only where the board
        # changed between the gate and here — the half-step this engine cannot
        # rewind.
        named_payers: list = [
            found for found in self._named_cast_cost_payers(
                caster_index, cost_permanent_ids, cost_permanent_index
            )
            if found is not None
        ]

        def claim(candidates: list) -> "Permanent":
            """The next named payer *candidates* contains, else the default."""
            nonlocal named_payers
            # `in` compares Permanents by value and would match a look-alike;
            # membership is by identity.
            chosen = next(
                (
                    claimed for claimed in named_payers
                    if any(perm is claimed for perm in candidates)
                ),
                None,
            )
            if chosen is None:
                return self.default_sacrifice_pick(candidates)
            named_payers = [perm for perm in named_payers if perm is not chosen]
            return chosen

        for cost in costs:
            # CR 601.2b's *optional* price, collected only when the
            # announcement took it -- the same reader ``_unpayable_additional_cost``
            # skips it by, so a cost the gate priced and one the payment
            # collects cannot come apart.
            if not optional_cost_taken(cost, taken):
                continue
            # "…, **exile X creature cards from your graveyard**." (Haunting
            # Misery.) A *card* payment, so nothing leaves the battlefield and
            # `exiled` above — which carries the Permanent a battlefield exile
            # ate — is deliberately not touched.
            #
            # **The cards the caster named** (CR 601.2b: the choice is
            # theirs), by graveyard slot — ``cost_graveyard_indices``, checked
            # whole by ``_named_graveyard_cost_refusal`` before anything was
            # spent and re-counted by the caller for a spell that left this
            # pile. Resolved to cards before the first one leaves and removed
            # highest slot first, so no removal renumbers a slot still owed;
            # each ``pop`` takes exactly one copy.
            #
            # A cast that named no set takes the top of the pile down, the
            # deterministic pick every unnamed cost here has — least valuable
            # first where the cards are a plain price
            # (``ai_valuation.graveyard_price_order``): Haunting Misery and
            # Skeletal Scrying read how many went, not which.
            if cost.exile_graveyard_filter is not None:
                owed = cost.exiled_from_graveyard(x_value)
                if cost_graveyard_indices is not None:
                    # Only slots this cost could take, each once, and no more
                    # than it charges: the gate has already held the set to
                    # exactly that, and the payment does not lean on it — a
                    # caller that reached here past the gate still cannot
                    # exile a card the cost does not name, and whatever the
                    # set falls short by is taken by the default below rather
                    # than left unpaid.
                    payable = self._graveyard_exile_candidates(caster_index, cost)
                    named = [
                        slot for slot in dict.fromkeys(cost_graveyard_indices)
                        if slot in payable
                    ][:owed]
                    cards_by_slot = {slot: caster.graveyard[slot] for slot in named}
                    for slot in sorted(named, reverse=True):
                        caster.graveyard.pop(slot)
                    for slot in named:
                        caster.exile.append(cards_by_slot[slot])
                        self.log.append(
                            f"{caster.name} exiled {cards_by_slot[slot].name} "
                            f"from their graveyard to cast {card.name}"
                        )
                    owed -= len(named)
                for _ in range(owed):
                    candidates = self._graveyard_exile_candidates(
                        caster_index, cost
                    )
                    if not candidates:
                        break  # gated above; a pile that changed since is a no-op
                    from ...ai_valuation import (graveyard_price_order,
                                                 reads_what_its_cost_exiled)

                    index = candidates[-1]
                    if not reads_what_its_cost_exiled(
                        compile_card_oracle(card).instructions
                    ):
                        index = graveyard_price_order(
                            self, caster_index, list(reversed(candidates)),
                        )[0]
                    paid = caster.graveyard.pop(index)
                    caster.exile.append(paid)
                    self.log.append(
                        f"{caster.name} exiled {paid.name} from their graveyard "
                        f"to cast {card.name}"
                    )
            # "…, **exile a creature you control**." (Soul Exchange.) Paid
            # before the sacrifice beside it only in source order; both are one
            # payment moment (CR 601.2h), and no card in the pool prints both.
            if cost.exile_filter is not None:
                candidates = self._additional_cost_candidates(
                    caster_index, cost, giving_up="exile"
                )
                if candidates:
                    # Named by id or by the legacy slot, like every price
                    # here. This charger read the slot alone, so a creature
                    # named by id — the only way the wire names one — was not
                    # read at all and the default went instead.
                    chosen = claim(candidates)
                    owner_index = self.owner_index_of(chosen)
                    exiled_card = chosen.card
                    self.remove_from_battlefield(chosen)
                    self.players[
                        owner_index if owner_index is not None else caster_index
                    ].exile.append(exiled_card)
                    exiled = chosen
                    self.log.append(
                        f"{caster.name} exiled {exiled_card.name} to cast {card.name}"
                    )
            if cost.sacrifice_filter is not None:
                # Whom the payer named, in the order they named them
                # (``_named_cast_cost_payers`` says why there are two
                # channels).
                #
                # Re-enumerated per victim, never sliced off one list: each
                # sacrifice removes a permanent, and a list held across that
                # holds an object the board no longer has.
                for _ in range(max(1, cost.sacrifice_count)):
                    candidates = self._additional_cost_candidates(caster_index, cost)
                    if not candidates:
                        break  # gated above; a board that changed since is a no-op
                    chosen = claim(candidates)
                    name = chosen.card.name
                    if self.sacrifice_permanent(chosen) is not None:
                        # The **first**, which is "the sacrificed creature" a
                        # spell reads back (Soul Exchange). No card in the pool
                        # reads one back out of a counted cost, and recording
                        # the last would answer a different question than the
                        # singular cost has always answered.
                        sacrificed = sacrificed or chosen
                        self.log.append(
                            f"{caster.name} sacrificed {name} to cast {card.name}"
                        )
            if cost.return_filter is not None:
                # "…return **X** Swamps you control to their owner's hand."
                # (Infernal Harvest.) Re-enumerated per victim, never sliced
                # off one list: each return takes a permanent off the
                # battlefield, and a list held across that holds an object the
                # board no longer has. Through the same
                # ``return_permanent_to_owners_hand`` every bounce effect uses,
                # so CR 903.9b and the leaves-the-battlefield replacements see
                # a cost payment exactly as they see a spell's bounce.
                from ...handlers._common import return_permanent_to_owners_hand

                for _ in range(cost.returned_count(x_value)):
                    candidates = self._additional_cost_candidates(
                        caster_index, cost, giving_up="return"
                    )
                    if not candidates:
                        break  # gated above; a board that changed since is a no-op
                    chosen = claim(candidates)
                    name = chosen.card.name
                    return_permanent_to_owners_hand(self, chosen, caster)
                    self.log.append(
                        f"{caster.name} returned {name} to hand to cast {card.name}"
                    )
            if cost.sacrifice_all_filter is not None:
                # "…, sacrifice **all** permanents you control." (Kaervek's
                # Spite.) Snapshotted by identity before the loop, never
                # re-enumerated per victim as the *counted* sacrifice above is:
                # the counted one asks "which of these do I pick next", and this
                # one has already picked every permanent the phrase named. A
                # re-enumeration would be a second reading of a board the first
                # sacrifice has begun changing — a token that ceased to exist,
                # an Aura that fell off — and would then charge whatever was
                # left rather than what was announced (CR 601.2b).
                #
                # A board of nothing pays this cost in full, which is why it is
                # not in the CR 601.2h gate: there is no shortfall to have.
                victims = self._additional_cost_candidates(
                    caster_index, cost, giving_up="sacrifice_all"
                )
                for victim in victims:
                    name = victim.card.name
                    if self.sacrifice_permanent(victim) is not None:
                        self.log.append(
                            f"{caster.name} sacrificed {name} to cast {card.name}"
                        )
            life = cost.life_charged(x_value)
            if life:
                caster.life -= life
                self.log.append(
                    f"{caster.name} paid {life} life to cast {card.name}"
                )
            if cost.discard_whole_hand:
                # "…, and **discard your hand**." (Kaervek's Spite.) Every
                # card, snapshotted before the loop because `_discard_card` may
                # itself put something into the hand (Library of Leng's
                # replacement offers the top of the library instead) —
                # iterating the live list would then skip or revisit a card.
                # The same shape `activate_permanent_ability` pays the
                # identically printed activation cost with.
                #
                # The spell is on the stack by now (CR 601.2a), so it is not
                # among the cards this bins.
                emptied = list(caster.hand)
                caster.hand = []
                for cost_card in emptied:
                    self._discard_card(caster, cost_card)
                self.log.append(
                    f"{caster.name} discarded their hand "
                    f"({len(emptied)} card(s)) to cast {card.name}"
                )
            if cost.discard_cards:
                for _ in range(cost.discarded_count(x_value)):
                    if not caster.hand:
                        break
                    # The chosen card was resolved before the spell left the
                    # hand; find it by identity now. Two copies of one card are
                    # the same object, which is fine — either pays the cost, and
                    # discarding "the first equal one" is the whole choice.
                    #
                    # The default is the first card the printed phrase *names*,
                    # never a bare index 0: "discard a red or green card" paid
                    # with the first card in hand is a different, cheaper cost.
                    # The spell has already left the hand by now (it is on the
                    # stack, CR 601.2a), so nothing needs excluding here.
                    index = next(
                        (
                            i for i, held in enumerate(caster.hand)
                            if card_matches_any(held, cost.discard_filters)
                        ),
                        None,
                    )
                    if index is None:
                        break  # gated above; a hand that changed since is a no-op
                    if cost.discard_at_random:
                        # "…, discard a card **at random**." (Sonic Burst,
                        # Flowstone Flood's buyback.) The payer names nothing —
                        # a cost the payer picks is a strictly better cost than
                        # one chance picks, which is the whole difference
                        # between these cards and one printing "discard a card".
                        # Any card a caller named is ignored rather than
                        # honoured, because honouring it hands the choice back;
                        # the activation path answers the identical clause the
                        # same way.
                        #
                        # Through the module RNG, like every other randomiser in
                        # this engine, so a seeded run reproduces the discard.
                        index = random.choice(
                            [
                                i for i, held in enumerate(caster.hand)
                                if card_matches_any(held, cost.discard_filters)
                            ]
                        )
                        named_discards = []
                    if named_discards:
                        # One named card pays once: the next one named, found
                        # by identity in the hand as it now stands.
                        named_card = named_discards.pop(0)
                        index = next(
                            (
                                i for i, held in enumerate(caster.hand)
                                if held is named_card
                            ),
                            index,
                        )
                    discarded = caster.hand.pop(index)
                    self._discard_card(caster, discarded)
                    discarded_cards.append(discarded)
                    self.log.append(
                        f"{caster.name} discarded {discarded.name} to cast {card.name}"
                    )
                    # One named index pays one card; the rest take the default.
                    cost_hand_index = None
        return {
            "sacrificed_for_cost": sacrificed, "exiled_for_cost": exiled,
            "discarded_for_cost": discarded_cards,
        }
