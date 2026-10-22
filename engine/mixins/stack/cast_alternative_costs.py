"""A spell's alternative cost (CR 118.9): which one is announced, what pays
it, and paying it.

"You may … rather than pay this spell's mana cost" (Force of Will, Fireblast,
Foil). CR 601.2b announces the alternative and the caster names what pays it
(``_resolve_alternative_cost`` and its ``_permanents`` / ``_others`` twins);
``_unpayable_alternative_cost`` refuses one the board cannot cover before
anything is spent, and ``_pay_alternative_cost`` performs it (CR 601.2h). A
cost that pays no mana still owes what a tax adds (CR 118.9d —
``alternative_cost_mana``, ``_mana_still_owed_refusal``).

Split out of ``casting.py`` at the 2,000-line cap, and composed onto ``Game``
with the other parts of ``SpellCastingMixin``, directly after it.
"""

from __future__ import annotations

from ...alternative_costs import (AlternativeCost, alternative_costs,
                                  board_noun)
from ...cost_modifiers import (CostReduction, cost_reduction_for_cast,
                               keyword_cost_modifiers, reduce_cost,
                               spell_cost_tax, spell_symbol_tax)
from ...models import CardDefinition, Permanent
from ...subject_filters import card_matches_any, filter_head_noun


class AlternativeCastCostsMixin:
    # ------------------------------------------------------------------
    # The printed alternative cost (CR 118.9)
    # ------------------------------------------------------------------

    def applicable_alternative_costs(
        self, caster_index: int, card: CardDefinition
    ) -> tuple[AlternativeCost, ...]:
        """Every CR 118.9 alternative cost this cast of *card* may be paid with.

        Two sources, one list, because CR 118.9a limits how many may be
        *applied* and says nothing about where they come from: the costs the
        card prints on itself (Force of Will) and the costs a permanent on some
        battlefield grants every spell (Dream Halls). One reader, because the
        offer, the announcement's check, the CR 601.2h gate and the payment all
        ask this same question -- and a source only some of them knew about
        would be an offer the cast refuses, or worse, a price the gate never
        measured.

        The board is scanned through the control seam and read off each
        permanent's *effective* card, the rule ``cost_modifiers._tax`` follows
        one file over: a permanent whose text an effect has changed grants what
        it currently says.
        """
        from ...alternative_costs import condition_holds, granted_alternative_cost

        found = list(alternative_costs(card))
        for _seat, permanent in self.permanents_with_controller():
            granted = granted_alternative_cost(
                permanent.effective_card.oracle_text or ""
            )
            if granted is not None:
                found.append(granted)
        # "**If you control a Swamp**, you may pay 4 life rather than pay this
        # spell's mana cost." (Snuff Out, and seven more in Mercadian Masques.)
        # CR 601.2b announces the intention to pay an alternative cost, and a
        # cost whose printed condition does not hold is not one this caster may
        # announce — so it is filtered *here*, in the one reader, rather than
        # refused later as unpayable. The two are different answers: unpayable
        # is a price the caster cannot meet, and this is an offer that does not
        # exist, which is what the picker must not show and the AI must not
        # take.
        #
        # Asked of the board every time rather than resolved once at compile:
        # the condition is a live question (CR 601.2b checks it as the spell is
        # cast), and a Legate that was free last turn is not free now.
        return tuple(
            cost for cost in found
            if condition_holds(self, caster_index, cost.condition)
        )

    def _shares_a_color(self, one, other, seat: int) -> bool:
        """Whether two cards *seat* owns share a colour (CR 105.2, CR 202.2).

        Through ``object_colors`` rather than off ``CardDefinition.colors``, so
        a card whose colour an effect has changed (Celestial Dawn: "nonland
        cards you own that aren't on the battlefield") answers with the colour
        it *has* — the same reader ``search_filters.card_colors`` asks, and the
        reason the seat is a parameter rather than inferred: the override is
        per-player.

        A colourless card shares a colour with nothing, which is why this is an
        intersection and not a "no restriction" default: Dream Halls cannot cast
        an artifact, and a reading that let it would be a strictly better card
        than the one printed.
        """
        from ...object_colors import card_colors

        return bool(
            frozenset(card_colors(self, one, seat))
            & frozenset(card_colors(self, other, seat))
        )

    def _alternative_cost_payers(
        self,
        caster_index: int,
        cost: AlternativeCost,
        *,
        spell_hand_index: int | None,
        spell: "CardDefinition | None" = None,
    ) -> list["CardDefinition"]:
        """The cards in hand that could pay *cost*'s exile or discard, in hand
        order.

        One enumeration for the gate, the named-card check and the payment, the
        arrangement ``_discard_cost_payers`` and ``_additional_cost_candidates``
        both make and for the same reason: a gate that counted a different set
        from the one the payment picks from would admit a cast the payment
        cannot collect.

        The spell is withheld **by index**, never by identity. CR 601.2a puts it
        on the stack before costs are paid, so it cannot pay for itself — but a
        *second copy* in hand is a different card that legitimately can, and a
        deck repeats one immutable ``CardDefinition`` per copy, so an identity
        filter would refuse it along with the spell.
        """
        # Whichever half of the hand this cost reaches for. ``None`` on both is
        # a cost that takes no card at all, and the empty tuple is "any card" --
        # two different things, which is why the choice is on the field being
        # None rather than on the tuple being empty.
        wanted = (
            cost.exile_from_hand if cost.exile_from_hand is not None
            else cost.discard_from_hand
        )
        payers = [
            held
            for position, held in enumerate(self.players[caster_index].hand)
            if position != spell_hand_index
            and card_matches_any(held, wanted or ())
        ]
        if cost.shares_color_with_spell:
            # "…a card **that shares a color with that spell**" (Dream Halls).
            # A relation between two objects, so it is answered here where both
            # are in hand rather than in the filter, which describes one.
            if spell is None:
                # No spell to compare against is no shared colour, which is the
                # direction a dropped narrowing has to fail in: a caller that
                # forgot to say which spell offers nothing rather than
                # everything.
                return []
            payers = [
                held for held in payers
                if self._shares_a_color(held, spell, caster_index)
            ]
        return payers

    def _resolve_alternative_cost(
        self,
        caster_index: int,
        card: CardDefinition,
        *,
        taking_it: bool | None,
        named_hand_index: int | None,
        spell_hand_index: int | None,
        required: "AlternativeCost | None" = None,
    ) -> "tuple[AlternativeCost | None, CardDefinition | None, str | None]":
        """CR 601.2b's announcement: ``(cost taken, card that pays it, refusal)``.

        *required* is the alternative cost the **permission** this cast is
        made under demands (CR 118.9b; flashback, CR 702.34a). It is not an
        offer and is not looked up among the card's printed ones: it *is* the
        cost of this cast, so ``taking_it`` has nothing to decide, and the
        card's own printed alternative cost is not also available (CR 118.9a:
        "only one alternative cost can be applied to any one spell").

        Three answers rather than a boolean, because the announcement decides
        three things at once and every one of them has to survive the spell
        leaving the hand: *which* alternative cost is being paid (CR 118.9a
        allows one), *which card* pays its exile half (an index is only
        meaningful beside the list it was read from, so it is resolved to a card
        here), and whether the announcement is legal at all.

        ``taking_it`` is None for "pay the mana cost", which is the default and
        the behaviour every caller had before this existed. CR 118.9b makes an
        alternative cost optional, so nothing is inferred: a caster who did not
        ask pays the printed cost even when they could not afford it, because the
        alternative is the engine spending a life total the player never offered.

        The affordability question is **not** asked here. It belongs beside the
        additional costs' gate at CR 601.2h, after X and the targets are
        announced, and asking it twice would be two answers to one question.
        """
        if required is not None:
            cost = required
        else:
            printed = self.applicable_alternative_costs(caster_index, card)
            if not taking_it:
                return None, None, None
            if not printed:
                return None, None, (
                    f"{card.name} can't be cast that way: it prints no alternative "
                    f"cost (CR 118.9)"
                )
            if len(printed) > 1:
                # CR 118.9a: only one alternative cost may be applied. No card
                # in the pool prints two, so rather than invent a choice nobody
                # has to make, the cast is refused and names the rule — a
                # silent "take the first" would be this engine picking which
                # price the player pays.
                return None, None, (
                    f"{card.name} prints more than one alternative cost and only "
                    f"one may be applied (CR 118.9a)"
                )
            cost = printed[0]
        if cost.exile_from_hand is None and cost.discard_from_hand is None:
            return cost, None, None
        payable = self._alternative_cost_payers(
            caster_index, cost, spell_hand_index=spell_hand_index, spell=card,
        )
        if named_hand_index is None:
            # Nothing named is the deterministic default, which keeps AI and
            # headless play unblocked — the same answer every other cost choice
            # on this path gives. An empty list is not a refusal here: the gate
            # at CR 601.2h says so, in one place, with the rule's own wording.
            return cost, (payable[0] if payable else None), None
        hand = self.players[caster_index].hand
        if not 0 <= named_hand_index < len(hand):
            return None, None, (
                f"{card.name} can't be cast: no card at hand position "
                f"{named_hand_index} to pay its alternative cost"
            )
        if named_hand_index == spell_hand_index:
            return None, None, (
                f"{card.name} can't be cast: it is on the stack (CR 601.2a) and "
                "cannot pay for itself"
            )
        if not any(held is hand[named_hand_index] for held in payable):
            # A named card that does not answer the printed phrase is an error,
            # not a cheaper cost: refused rather than quietly slid onto a legal
            # one, so a stale click cannot exile the card the player meant to
            # keep. The same answer the discard cost beside it gives.
            return None, None, (
                f"{card.name} can't be cast: {hand[named_hand_index].name} does "
                f"not answer its alternative cost (CR 118.9)"
            )
        return cost, hand[named_hand_index], None

    @staticmethod
    def alternative_cost_permanent_payment(
        cost: "AlternativeCost | None",
    ) -> "tuple[str, int] | None":
        """The one battlefield payment *cost* names, as ``(verb, count)``.

        "Sacrifice a creature" (Mind Swords), "tap an untapped creature you
        control" (Lashknife), "return two Islands you control to their owner's
        hand" (Gush): the verb keys ``_COST_CANDIDATE_FIELDS``, so the offer,
        the announcement's check and the payment enumerate one candidate list.

        None when the cost takes no permanent — and when it prints **two**
        such verbs, a shape no card in the pool has: one list of ids could not
        say which permanent pays which verb, so such a cost offers no choice
        and takes the deterministic pick, which is what every one of these
        costs did before the choice existed.
        """
        if cost is None:
            return None
        found = [
            (verb, count)
            for verb, present, count in (
                ("sacrifice", cost.sacrifice_filter is not None,
                 max(1, cost.sacrifice_count)),
                ("return", cost.return_filter is not None,
                 max(1, cost.return_count)),
                ("tap", bool(cost.tap_count), cost.tap_count),
            )
            if present
        ]
        return found[0] if len(found) == 1 else None

    def _resolve_alternative_cost_permanents(
        self,
        caster_index: int,
        card: CardDefinition,
        cost: "AlternativeCost | None",
        named_ids: "list[int] | None",
    ) -> "tuple[list[Permanent], str | None]":
        """CR 601.2b: which permanents the caster named to pay *cost*.

        A cost that names an object owes a **choice** — which creature is
        tapped for Lashknife, which is sacrificed for Mind Swords, which
        Mountain goes to Fireblast — and every one of these was paid by
        ``default_sacrifice_pick`` whatever the player wanted, because the
        announcement had nowhere to carry the answer. The choice is made here,
        as the spell is announced, out of the same candidate list the CR 601.2h
        gate counts and the payment re-enumerates.

        Nothing named is the deterministic default, which keeps AI and headless
        play unblocked. A named id that is not a candidate — another seat's
        creature, an already-tapped one, a land the phrase does not name — is a
        refusal with nothing spent, never a slide onto a legal neighbour; so is
        an id named twice, or more ids than the cost takes — **or fewer**.
        CR 601.2h: "Partial payments are not allowed." A caster who names one
        of Gush's two Islands has announced half a payment, and filling the
        other half from the default pick returns an Island they did not name:
        the same substitution as replacing the one they did. This path topped a
        short list up until the counted *additional* cost's twin
        (``_named_cast_cost_refusal``) had been refusing one for a set.
        """
        if not named_ids:
            return [], None
        payment = self.alternative_cost_permanent_payment(cost)
        if payment is None:
            return [], (
                f"{card.name} can't be cast that way: its alternative cost "
                f"names no permanent to choose (CR 601.2b)"
            )
        verb, count = payment
        if len(set(named_ids)) != len(named_ids) or len(named_ids) > count:
            return [], (
                f"{card.name} can't be cast: its alternative cost takes "
                f"{count} permanent(s), each named once (CR 601.2b)"
            )
        if len(named_ids) < count:
            return [], (
                f"{card.name} can't be cast: its alternative cost takes "
                f"{count} permanent(s) to {verb} and {len(named_ids)} "
                f"were named (CR 601.2h)"
            )
        candidates = self._additional_cost_candidates(
            caster_index, cost, giving_up=verb
        )
        named: list[Permanent] = []
        for permanent_id in named_ids:
            found = self.permanent_by_id(permanent_id)
            # By identity: `in` compares Permanents by value and would accept
            # a look-alike on the wrong battlefield.
            if found is None or not any(perm is found for perm in candidates):
                return [], (
                    f"{card.name} can't be cast: the permanent named to "
                    f"{verb} for its alternative cost cannot pay it (CR 601.2b)"
                )
            named.append(found)
        return named, None

    def _alternative_cost_first_position(
        self,
        caster_index: int,
        card: CardDefinition,
        cost: "AlternativeCost",
        *,
        named_hand_index: int | None,
        spell_hand_index: int | None,
    ) -> int | None:
        """The hand position paying the narrowed half of *cost*'s discard.

        The named one when the caster named it, else the position the
        deterministic pick in :meth:`_resolve_alternative_cost` takes — the
        first payer in hand order — so "another card" is never the same card.
        """
        if named_hand_index is not None:
            return named_hand_index
        payers = self._alternative_cost_payers(
            caster_index, cost, spell_hand_index=spell_hand_index, spell=card,
        )
        return next(
            (
                position
                for position, held in enumerate(self.players[caster_index].hand)
                if position != spell_hand_index
                and any(held is payer for payer in payers)
            ),
            None,
        )

    def _alternative_cost_other_positions(
        self,
        caster_index: int,
        card: CardDefinition,
        cost: "AlternativeCost",
        *,
        named_hand_index: int | None,
        spell_hand_index: int | None,
    ) -> list[int]:
        """The hand positions that may pay *cost*'s "and another card" (Foil).

        Every card but the spell (CR 601.2a) and the one paying the narrowed
        half — "another" is CR 109.5's other object, not a second copy of the
        word. By position, because two copies of one card in hand are the same
        Python object and only the position tells them apart. One enumeration
        for the offer, the announcement's check, the CR 601.2h gate and the
        default pick.
        """
        first = self._alternative_cost_first_position(
            caster_index, card, cost,
            named_hand_index=named_hand_index, spell_hand_index=spell_hand_index,
        )
        return [
            position
            for position in range(len(self.players[caster_index].hand))
            if position not in (spell_hand_index, first)
        ]

    def _resolve_alternative_cost_others(
        self,
        caster_index: int,
        card: CardDefinition,
        cost: "AlternativeCost | None",
        *,
        named_hand_index: int | None,
        named_others: "list[int] | None",
        spell_hand_index: int | None,
    ) -> "tuple[list[CardDefinition], str | None]":
        """CR 601.2b: which further cards pay "and another card" (Foil).

        Resolved to cards at the announcement, while the positions still mean
        the hand the caster is looking at — the arrangement the narrowed half's
        card already has. A named position that cannot pay (the spell itself,
        the card paying the narrowed half, one named twice, more than the cost
        takes) is a refusal with nothing spent, never a slide onto a neighbour;
        nothing named, or fewer than the cost takes, is filled by the
        deterministic pick in hand order. A short hand is not refused here: the
        CR 601.2h gate says so, in one place.
        """
        if cost is None or not cost.discard_others:
            if named_others:
                return [], (
                    f"{card.name} can't be cast that way: its alternative cost "
                    f"discards no further card (CR 601.2b)"
                )
            return [], None
        hand = self.players[caster_index].hand
        allowed = self._alternative_cost_other_positions(
            caster_index, card, cost,
            named_hand_index=named_hand_index, spell_hand_index=spell_hand_index,
        )
        named = list(named_others or ())
        if len(set(named)) != len(named) or len(named) > cost.discard_others:
            return [], (
                f"{card.name} can't be cast: its alternative cost discards "
                f"{cost.discard_others} further card(s), each named once "
                f"(CR 601.2b)"
            )
        if any(position not in allowed for position in named):
            return [], (
                f"{card.name} can't be cast: a card named to pay its "
                f"alternative cost is the spell or is already paying it "
                f"(CR 601.2a)"
            )
        positions = named + [
            position for position in allowed if position not in named
        ][: cost.discard_others - len(named)]
        return [hand[position] for position in positions], None

    def _unpayable_alternative_cost(
        self,
        caster_index: int,
        card: CardDefinition,
        cost: "AlternativeCost | None",
        *,
        spell_hand_index: int | None,
    ) -> str | None:
        """Why the announced alternative cost can't be paid, or None.

        CR 601.2h: "Unpayable costs can't be paid", and CR 601.2e makes the
        whole casting a rewind — so the answer is that the spell is not cast,
        never that it is cast without the cost. Which for an *alternative* cost
        is the sharper version of the same rule: a dropped additional cost is a
        spell cast for less than it prints, and a dropped alternative cost is a
        spell cast for **nothing at all**, because the mana payment has already
        been replaced by whatever this was supposed to collect.

        Asked beside ``_unpayable_additional_cost`` and at the same moment, so a
        refusal here costs the caster exactly what a refusal there does: nothing.
        """
        if cost is None:
            return None
        caster = self.players[caster_index]
        # CR 119.4: a player may pay life only down to 0.
        if cost.pay_life and caster.life < cost.pay_life:
            return (
                f"{card.name} can't be cast: {caster.name} cannot pay "
                f"{cost.pay_life} life with {caster.life} remaining (CR 601.2h)"
            )
        if (
            cost.exile_from_hand is not None
            or cost.discard_from_hand is not None
        ) and not self._alternative_cost_payers(
            caster_index, cost, spell_hand_index=spell_hand_index, spell=card,
        ):
            return (
                f"{card.name} can't be cast: no card in hand answers its "
                f"alternative cost, {cost.describe()} (CR 601.2h)"
            )
        # "…discard an Island card **and another card**" (Foil). The Island
        # alone is no more a payment than none: the gate counts the cards left
        # once the spell and the Island are set aside, through the enumeration
        # the default pick and the offer read.
        if cost.discard_others and len(
            self._alternative_cost_other_positions(
                caster_index, card, cost,
                named_hand_index=None, spell_hand_index=spell_hand_index,
            )
        ) < cost.discard_others:
            return (
                f"{card.name} can't be cast: not enough other cards in hand "
                f"for its alternative cost, {cost.describe()} (CR 601.2h)"
            )
        # "You may **sacrifice two Mountains** rather than pay this spell's
        # mana cost." (Fireblast.) The *count* is what makes this unpayable:
        # one Mountain is no more a payment than none, and a gate that asked
        # only whether one existed would admit the announcement and then charge
        # one — a spell cast for nothing, because the mana payment has already
        # been skipped. The same question ``_unpayable_additional_cost`` asks
        # of the identically printed additional cost, through the same
        # candidate enumeration.
        if cost.sacrifice_filter is not None:
            available = self._additional_cost_candidates(caster_index, cost)
            wanted = max(1, cost.sacrifice_count)
            if len(available) < wanted:
                noun = filter_head_noun(cost.sacrifice_filter)
                shortfall = f"no {noun}" if wanted == 1 else f"not enough {noun}s"
                return (
                    f"{card.name} can't be cast: {shortfall} to sacrifice for "
                    f"its alternative cost (CR 601.2h)"
                )
        # "You may **return two Islands you control to their owner's hand**
        # rather than pay this spell's mana cost." (Gush, Thwart, Tidal Bore.)
        # The *count* is what makes this unpayable, exactly as it is for the
        # sacrifice above: one Island is no more a payment of a two-Island cost
        # than none (CR 118.3 — a cost may be paid only in full), and a gate
        # that asked only whether one existed would admit the announcement and
        # then charge one, which for an alternative cost is a spell cast for
        # nothing because the mana payment has already been skipped.
        if cost.return_filter is not None:
            available = self._additional_cost_candidates(
                caster_index, cost, giving_up="return"
            )
            wanted = max(1, cost.return_count)
            if len(available) < wanted:
                # ``board_noun``, not ``filter_head_noun``: every noun phrase
                # this cost prints is a land *subtype* ("two Islands"), and the
                # head noun answers "permanent" for all of them — so five
                # different refusals would read identically and none would name
                # the price. The gate is unaffected either way; what changes is
                # whether the player is told what they are short of.
                noun = board_noun(cost.return_filter)
                shortfall = f"no {noun}" if wanted == 1 else f"not enough {noun}s"
                return (
                    f"{card.name} can't be cast: {shortfall} to return for its "
                    f"alternative cost (CR 601.2h)"
                )
        # "You may **tap an untapped creature you control** rather than pay this
        # spell's mana cost." (Orim's Cure, Ramosian Rally.) The same count
        # question one verb over, through the same candidate scan — which is
        # what keeps the gate and the payment counting one list. "Untapped" is
        # in the payload, so a board of tapped creatures is a shortfall here
        # rather than a payment that taps nothing.
        if cost.tap_count:
            available = self._additional_cost_candidates(
                caster_index, cost, giving_up="tap"
            )
            if len(available) < cost.tap_count:
                noun = board_noun(cost.tap_filter or {})
                shortfall = (
                    f"no untapped {noun}" if cost.tap_count == 1
                    else f"not enough untapped {noun}s"
                )
                return (
                    f"{card.name} can't be cast: {shortfall} to tap for its "
                    f"alternative cost (CR 601.2h)"
                )
        # "…you may **have an opponent gain 3 life** rather than pay this
        # spell's mana cost." (Invigorate.) CR 119.7's last sentence, in as many
        # words: "a cost that involves having that player gain life can't be
        # paid". Without this the gate would admit the announcement, the
        # payment's ``_gain_life`` would log the prohibition and change nothing,
        # and the spell would be cast for **nothing** — the mana payment having
        # already been skipped, which is the exact failure this whole gate
        # exists to prevent.
        #
        # Asked of *every* opponent rather than the first, because CR 601.2b
        # lets the caster choose which one gains and the payment picks the same
        # way: one banned seat is not an unpayable cost while another can pay.
        if cost.opponent_gains_life and self._life_gain_cost_payer(
            caster_index
        ) is None:
            return (
                f"{card.name} can't be cast: no opponent may gain life, so its "
                f"alternative cost cannot be paid (CR 119.7)"
            )
        # "…you may **have each other player gain 6 life**." (Reverent
        # Silence.) The same CR 119.7 sentence asked the other way round: every
        # other seat is "that player", so **one** that cannot gain life is an
        # unpayable cost, where Invigorate's caster could have handed the life
        # to someone else. Admitted, the payment below would skip the banned
        # seat and the spell would be cast for less than it prints.
        if cost.others_gain_life:
            from ...life_prohibitions import life_gain_banned

            banned = [
                self.players[seat].name
                for seat in self._other_living_seats(caster_index)
                if life_gain_banned(self, self.players[seat])
            ]
            if banned:
                return (
                    f"{card.name} can't be cast: {', '.join(banned)} can't gain "
                    f"life, so its alternative cost cannot be paid (CR 119.7)"
                )
        # "You may **exile the top three black cards of your graveyard** rather
        # than pay this spell's mana cost." (Spinning Darkness.) The *count*
        # again, and the scan with it: CR 118.3 lets a cost be paid only in
        # full, so a pile holding two black cards pays nothing at all — and a
        # gate that asked only whether one existed would admit the announcement
        # and then charge less, which for an alternative cost is a spell cast
        # for nothing, the mana payment having already been skipped.
        #
        # Through the same scan the effect and the activation cost run
        # (``graveyard_order.positions_named``), so what the gate counts and
        # what the payment takes are one answer.
        if cost.exile_graveyard_position is not None:
            from ...graveyard_order import positions_named

            if not positions_named(
                caster.graveyard, cost.exile_graveyard_position
            ):
                return (
                    f"{card.name} can't be cast: {caster.name}'s graveyard "
                    f"cannot pay its alternative cost, {cost.describe()} "
                    f"(CR 601.2h)"
                )
        return None

    def alternative_cost_mana(
        self,
        caster_index: int,
        card: CardDefinition,
        cost: "AlternativeCost | None" = None,
        *,
        extra_generic: int = 0,
    ) -> dict[str, int]:
        """CR 118.9d, for a reader that **prices** a cast before making it: the
        mana a cast of *card* owes when it is paid for with *cost* rather than
        with its mana cost.

        The cost's own mana (a flashback cost) or none (a pitched card, a life
        payment, a sacrifice), plus every cost increase in force and less every
        reduction, in CR 601.2f's order — the total ``_cast_onto_stack`` hands
        ``_pay_cast_cost`` for the same announcement, with every optional cost
        declined and nothing aimed at. *cost* None is a waiver ("without paying
        its mana cost"), which CR 118.9 calls an alternative cost too.
        *extra_generic* is what the zone adds — CR 903.8's commander tax.

        Three readers price a cast and all three used to read an alternative
        cost as costing no mana, because the cast path charged none: the offer's
        ``payable`` (``legality.cast_cost_offers``), the castable highlight's
        fallback behind it, and the AI's ``_alternative_cost_is_payable``. One
        reader so the day the cast path began charging the taxes was not the day
        the other three began offering casts it refuses.
        """
        tax, _taxing = spell_cost_tax(self, caster_index, card)
        pips, _pip_taxing = spell_symbol_tax(self, caster_index, card)
        reduction, _reducing = cost_reduction_for_cast(self, caster_index, card)
        more, less, _by = keyword_cost_modifiers(
            self, caster_index, cost.keyword if cost is not None else None
        )
        return reduce_cost(
            self._parse_mana_cost(
                (cost.mana if cost is not None else None) or "",
                x_value=0,
                extra_generic=max(0, extra_generic) + tax + more,
                extra_pips=pips,
            ),
            CostReduction(reduction.generic + less, reduction.colored),
        )

    def _mana_still_owed_refusal(
        self, card: CardDefinition, how: str, extra_generic: int,
        extra_pips: "dict[str, int] | None", reduction: "CostReduction | None",
    ) -> str:
        """The refusal for a cast whose mana cost is not being paid and whose
        pool cannot pay what CR 118.9d leaves owing.

        *how* is the cost that replaced the mana cost, as the log should name
        it. The amount is this cast's own total — its taxes and the optional
        costs it announced, after its reductions — so the line says what to
        float, which "insufficient mana" alone would not: the card's mana cost
        is exactly what the caster is not paying.
        """
        from ...mana_payment import mana_cost_label

        owed = reduce_cost(
            self._parse_mana_cost(
                "", x_value=0, extra_generic=extra_generic, extra_pips=extra_pips,
            ),
            reduction or CostReduction(),
        )
        return (
            f"insufficient mana for {card.name}: {how} still owes "
            f"{mana_cost_label(owed)} in additional costs and cost increases "
            f"(CR 118.9d)"
        )

    def _life_gain_cost_payer(self, caster_index: int) -> "int | None":
        """The seat an "have an opponent gain N life" cost will hand its life to.

        One reader for the CR 601.2h gate and the payment, the arrangement every
        other cost on this path makes and for its reason: a gate that counted a
        different set from the one the payment picks from would admit a cast the
        payment cannot collect — and here "cannot collect" means the spell is
        cast for nothing.

        A seat that cannot gain life is skipped rather than refused (CR 119.7),
        because CR 601.2b lets the caster choose *which* opponent gains: one
        Forsaken Wastes does not make Invigorate uncastable while a second
        opponent is at the table. None when no opponent can take it at all,
        which is the gate's refusal.
        """
        from ...life_prohibitions import life_gain_banned

        return next(
            (
                seat for seat in range(len(self.players))
                if seat != caster_index and not self.players[seat].lost
                and not life_gain_banned(self, self.players[seat])
            ),
            None,
        )

    def _other_living_seats(self, caster_index: int) -> list[int]:
        """Every seat but *caster_index* still in the game, in turn order from
        the active player (CR 101.4).

        "Have **each other player** gain 6 life" (Reverent Silence) is paid to
        all of them, so the gate and the payment walk one list -- the
        arrangement ``_life_gain_cost_payer`` makes for the one-seat price
        beside it, for its reason.
        """
        count = len(self.players)
        active = self.active_player_index or 0
        return sorted(
            (
                seat for seat in range(count)
                if seat != caster_index and not self.players[seat].lost
            ),
            key=lambda seat: ((seat - active) % count, seat),
        )

    def _pay_alternative_cost(
        self,
        caster_index: int,
        card: CardDefinition,
        cost: "AlternativeCost | None",
        chosen: "CardDefinition | None",
        *,
        named_permanents: "list[Permanent] | None" = None,
        other_cards: "list[CardDefinition] | None" = None,
    ) -> None:
        """Perform the announced alternative cost (CR 601.2h).

        *other_cards* is what ``_resolve_alternative_cost_others`` settled at
        the announcement for "and another card" (Foil), discarded after the
        card paying the narrowed half and through the same seams.

        Called once the spell is off the hand and on the stack (CR 601.2a), so
        the spell itself cannot pay and a second copy of it still can — which is
        the whole reason the *choice* was resolved to a card upstream while the
        index still meant something.

        The card leaves through ``Game.take_card_from_hand``: a deck repeats one
        immutable ``CardDefinition`` per copy, so every copy in a hand is the
        same Python object and the obvious identity filter would exile all of
        them while this puts exactly one into exile.

        *named_permanents* is what ``_resolve_alternative_cost_permanents``
        checked at the announcement: the permanents the caster chose to pay the
        sacrifice / return / tap half, taken first and by identity, with the
        deterministic pick filling whatever the caster left unnamed.
        """
        if cost is None:
            return
        caster = self.players[caster_index]
        named = list(named_permanents or ())

        def pick(candidates: "list[Permanent]") -> "Permanent":
            # The caster's own choice while one of theirs is still a candidate
            # (each payment renumbers the board, so the list is re-asked per
            # permanent), and the default rule for the rest.
            claimed = next(
                (
                    perm for perm in named
                    if any(candidate is perm for candidate in candidates)
                ),
                None,
            )
            if claimed is None:
                return self.default_sacrifice_pick(candidates)
            named[:] = [perm for perm in named if perm is not claimed]
            return claimed

        if cost.pay_life:
            caster.life -= cost.pay_life
            self.log.append(
                f"{caster.name} paid {cost.pay_life} life to cast {card.name}"
            )
        if cost.sacrifice_filter is not None:
            # Re-enumerated per victim, never sliced off one list: each
            # sacrifice removes a permanent, and a list held across that holds
            # an object the board no longer has. The same loop the additional
            # cost's counted sacrifice runs, and the same deterministic pick,
            # because CR 601.2b and CR 118.9 make one announcement.
            #
            # ``victim``, never ``chosen``: that name is this method's
            # *parameter*, the card in hand the announcement picked to pay an
            # exile half, and rebinding it here would hand a ``Permanent`` to
            # the exile below on any card that ever prints both.
            for _ in range(max(1, cost.sacrifice_count)):
                candidates = self._additional_cost_candidates(caster_index, cost)
                if not candidates:
                    break  # gated above; a board that changed since is a no-op
                victim = pick(candidates)
                name = victim.card.name
                if self.sacrifice_permanent(victim) is not None:
                    self.log.append(
                        f"{caster.name} sacrificed {name} to cast {card.name}"
                    )
        if cost.return_filter is not None:
            # "…return **two Islands you control** to their owner's hand."
            # (Gush.) Re-enumerated per permanent, never sliced off one list:
            # each return takes a permanent off the battlefield, and a list
            # held across that holds an object the board no longer has — the
            # same loop the identically printed additional cost runs, through
            # the same ``return_permanent_to_owners_hand`` every bounce effect
            # uses, so CR 903.9b and the leaves-the-battlefield replacements
            # see a cost payment exactly as they see a spell's bounce.
            from ...handlers._common import return_permanent_to_owners_hand

            for _ in range(max(1, cost.return_count)):
                candidates = self._additional_cost_candidates(
                    caster_index, cost, giving_up="return"
                )
                if not candidates:
                    break  # gated above; a board that changed since is a no-op
                giving = pick(candidates)
                name = giving.card.name
                return_permanent_to_owners_hand(self, giving, caster)
                self.log.append(
                    f"{caster.name} returned {name} to hand to cast {card.name}"
                )
        if cost.tap_count:
            # "…**tap an untapped creature you control**…" (Orim's Cure.)
            # Through ``Game.tap_permanent``, never a metadata poke: tapping is
            # an event other permanents watch, and a cost payment is not
            # exempt (CR 701.26a is the action; CR 118.11 is why paying a
            # cost is still an ordinary one). Re-enumerated per permanent
            # for the return's
            # reason above — each tap takes its permanent out of the candidate
            # list, since ``untapped_only`` rides on the filter.
            for _ in range(cost.tap_count):
                candidates = self._additional_cost_candidates(
                    caster_index, cost, giving_up="tap"
                )
                if not candidates:
                    break  # gated above; a board that changed since is a no-op
                tapping = pick(candidates)
                self.become_tapped(tapping)
                self.log.append(
                    f"{caster.name} tapped {tapping.card.name} to cast "
                    f"{card.name}"
                )
        if cost.reveal_hand:
            # "…**reveal your hand**…" (Land Grant.) The payment moves nothing;
            # what it costs is the information. Through ``record_reveal`` --
            # the one feed the web layer reads, the same seam the ``reveal_hand``
            # *effect* uses -- rather than a log line alone: a reveal the client
            # cannot show is a reveal the player has to take on trust, and here
            # it is the entire price of the spell.
            #
            # The spell is already off the hand (CR 601.2a) when this runs, so
            # what is shown is the hand the card asks about: Land Grant's own
            # condition is "no land cards in hand", and revealing the card that
            # is on the stack would be showing a hand the player no longer has.
            names = [held.name for held in caster.hand]
            self.record_reveal(caster_index, names)
            self.log.append(
                f"{caster.name} revealed their hand to cast {card.name}: "
                + (", ".join(names) or "(empty)")
            )
        if cost.opponent_gains_life:
            # "…**have an opponent gain 3 life**…" (Invigorate.) The gain lands
            # on somebody else, so it goes through ``Game._gain_life`` like
            # every other life gain — CR 614's ``life_gain`` replacements are
            # armed on the *gaining* seat, CR 119.7's prohibition is asked
            # there, and a cost payment is not exempt from either (CR 118.11).
            # That seam announces the gain itself, so nothing is logged here.
            opponent = self._life_gain_cost_payer(caster_index)
            if opponent is not None:
                self._gain_life(
                    self.players[opponent], cost.opponent_gains_life, card.name
                )
        if cost.others_gain_life:
            # "…**have each other player gain 6 life**…" (Reverent Silence.)
            # Every other seat, through ``_gain_life`` for the reason the
            # one-seat price above goes through it -- a cost payment is still a
            # life gain the replacements and prohibitions see (CR 118.11) --
            # and over the seats the gate just cleared.
            for seat in self._other_living_seats(caster_index):
                self._gain_life(
                    self.players[seat], cost.others_gain_life, card.name
                )
        if cost.exile_graveyard_position is not None:
            from ...graveyard_order import positions_named

            taken = positions_named(
                caster.graveyard, cost.exile_graveyard_position
            )
            paid = [caster.graveyard[index] for index in taken]
            # Highest index first: the positions were found against the pile as
            # it stands, and removing a lower one renumbers every position
            # above it — the same removal order the activation cost and the
            # effect handler use.
            for index in sorted(taken, reverse=True):
                del caster.graveyard[index]
            caster.exile.extend(paid)
            if paid:
                self.log.append(
                    f"{caster.name} exiled "
                    + ", ".join(held.name for held in paid)
                    + f" from their graveyard to cast {card.name}"
                )
        if cost.discard_from_hand is not None:
            # "…its controller may **discard** a card…" (Dream Halls.) The
            # hand's other destination, and the one card leaves through
            # ``take_card_from_hand`` for the exile's reason below: a deck
            # repeats one immutable ``CardDefinition`` per copy, so every copy
            # in a hand is the same Python object and an identity filter would
            # bin all of them.
            paying = chosen
            if paying is None or not any(held is paying for held in caster.hand):
                return
            self.take_card_from_hand(caster, paying)
            # Through ``_discard_card``, never straight to the graveyard: a
            # discard is CR 701.9a's event whether it pays a cost or not, so
            # Library of Leng's replacement (CR 701.9c) still redirects it and
            # every watcher of "whenever you discard a card" still fires. The
            # additional cost's discard one file over goes through the same
            # seam, for the same reason.
            self._discard_card(caster, paying)
            self.log.append(
                f"{caster.name} discarded {paying.name} to cast {card.name}"
            )
            # "…**and another card**" (Foil). One card per entry and by
            # identity through the seam, which removes exactly one copy — so a
            # second Island chosen as the "another card" leaves as the second
            # copy rather than taking both with the first.
            for other in other_cards or ():
                if not any(held is other for held in caster.hand):
                    continue  # gated above; a hand that changed since is a no-op
                self.take_card_from_hand(caster, other)
                self._discard_card(caster, other)
                self.log.append(
                    f"{caster.name} discarded {other.name} to cast {card.name}"
                )
            return
        if cost.exile_from_hand is None:
            return
        paying = chosen
        if paying is None or not any(held is paying for held in caster.hand):
            # The announcement's pick is re-checked rather than trusted: a hand
            # that changed between announcement and payment is a board this
            # engine cannot rewind, and re-picking is the honest half-step.
            paying = next(
                (
                    held for held in caster.hand
                    if card_matches_any(held, cost.exile_from_hand)
                ),
                None,
            )
        if paying is None:
            return  # gated above; a hand that changed since is a no-op
        self.take_card_from_hand(caster, paying)
        caster.exile.append(paying)
        self.log.append(
            f"{caster.name} exiled {paying.name} to cast {card.name}"
        )
