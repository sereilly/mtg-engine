"""What a cast announces about the spell itself (CR 601.2a–c): where it is
cast from, the costs it announces, its modes, and each mode's targets.

``_spell_source`` finds the card in the zone it is cast from and the
permission that lets it be (CR 601.3). ``_announced_cast_costs`` is the
announcement CR 601.2b makes of the costs — the printed additional costs, the
optional offers taken (kicker, buyback) folded into the price, an offer's X —
and of the choices made beside them (a creature type, a declined copy, the
cards a discard names), before any target is judged. The mode methods carry
CR 601.2b's choice of modes, and CR 700.2e's when an opponent makes it
(``_arm_opponent_mode_choice``, ``arm_modal_mode_targets``);
``_mode_announcements`` is every announcement a cast makes, one per chosen
mode, and ``_mode_target_refusal`` asks CR 601.2c's target gates of each.

Split out of ``casting.py`` at the 2,000-line cap (``_announced_cast_costs``
at the pre-Fifth-Dawn split), and composed onto ``Game`` with the other parts
of ``SpellCastingMixin``; the steps of ``_cast_onto_stack`` here are moved out
of it whole and called from it in its order.
"""

from __future__ import annotations

from ...cast_permissions import permission_for
from ...classifier import classify_card
from ...faces import holds_spell_named, spell_named
from ...hand_locks import hand_lock_reason, playable_hand_index
from ...oracle import compile_card_oracle
from ...refusals import refuse
from ...target_keywords import announced_slot, cast_target_zone
from ...cast_costs import (
    additional_costs, buyback_cost, cast_announces_x, optional_x_offers,
)
from ...cost_modifiers import (
    buyback_cost_reduction, CostReduction, reduce_cost,
)
from ...enter_effects import copy_on_enter_type
from ...game_types import first_target_id
from .cast_additional_costs import (
    _optional_cost_announcement, _optional_cost_totals, optional_cost_taken,
)


def _mode_announcements(
    chosen_modes, mode_index, target_player_index, target_permanent_index,
    target_permanent_ids, target_stack_item,
) -> list[tuple]:
    """``(mode_index, seat, slot, ids, stack_item)`` for every announcement a
    cast makes (CR 601.2b–c).

    One row for an ordinary spell and for the single-mode ``mode_index=``
    spelling, read off the cast's own target fields. One row **per chosen
    mode** for a "choose one or more" cast (``mode_choices``), read off the
    mode that named them: two modes of Sublime Epiphany may name two objects
    on two boards, and the cast's own fields name neither. A mode's targets
    travel as a slot beside its seat, never as ids — ``ChosenMode`` is stamped
    with ids only as it reaches the stack.

    A mode holds its slots in the channel's one shape (a list); the gates are
    handed them in the announcement's arity — one slot bare, several as the
    list — which is the shape every caller's own announcement arrives in.
    """
    if chosen_modes:
        return [
            (
                mode.index, mode.target_player_index,
                _announced_arity(mode.target_permanent_index),
                # …and its identities where the caller sent them (a mode's
                # several targets across two boards), read by the gate as the
                # cast's own ``target_permanent_ids`` are.
                mode.target_permanent_id,
                mode.target_stack_item,
            )
            for mode in chosen_modes
        ]
    return [(
        mode_index, target_player_index, target_permanent_index,
        target_permanent_ids, target_stack_item,
    )]


def _announced_arity(slots):
    """The slot channel *slots* (None or a list) as an announcement names it:
    None, one slot bare, or several as a list."""
    if slots is None:
        return None
    return slots[0] if len(slots) == 1 else list(slots)


class CastAnnouncementMixin:
    def _spell_source(
        self, *, alternative_cost, card_name, caster, caster_index, from_zone,
    ):
        """Where the spell is cast from, and under what (CR 601.2a, CR 601.3).

        A hand is the rule — the first copy that may be played (Firestorm
        Phoenix's held copy is not); a command zone is CR 903.8's, for the
        caster's own commander; a graveyard, an exile or a library top needs an
        effect, asked of the permission seam across every seat's pile (Grinning
        Totem leaves the card in the searched player's exile), the permission
        an announced alternative cost requires looked for first (CR 118.9b).

        A step of ``_cast_onto_stack``, moved out of it whole and called from
        it in its place: "above" and "below" in its comments are places in the
        cast as that method runs it.

        Returns the refusal, or ``(hand_index, permission, source_seat,
        source_zone)``.
        """
        # Casting from the hand is a rule; casting from anywhere else is an
        # effect (CR 601.3), asked of the permission seam. The lookup prefers a
        # covered occurrence so a duplicate without permission cannot shadow
        # the copy that has it.
        permission = None
        # Whose pile ``source_zone`` turns out to be. The caster's on every
        # path but one — Grinning Totem leaves the card in the *searched*
        # player's exile — and the departure below needs the seat, not just the
        # list, because leaving exile goes through a seam that takes one.
        source_seat = caster_index
        if from_zone == "hand":
            source_zone = caster.hand
            # A card in hand can be *held* and not playable — Firestorm Phoenix
            # returns itself "revealed in their hand and can't play it" until
            # its owner's next turn. The lookup asks for the first copy that may
            # be played rather than the first copy at all, the same preference
            # the permission lookup below makes and for the same reason: two
            # copies of one card are indistinguishable, so a restriction on one
            # of them is a restriction on how *many* may be played.
            hand_index = playable_hand_index(self, caster_index, card_name)
            if hand_index is None:
                if not any(holds_spell_named(card, card_name) for card in caster.hand):
                    raise ValueError(f"Card not in hand: {card_name}")
                denial = hand_lock_reason(self, caster_index, card_name) or (
                    f"{card_name} can't be played"
                )
                return refuse(card_name, None, denial)
        elif from_zone == "command":
            # CR 903.8 is a *rule*, not an effect: "a player may cast a
            # commander they own from the command zone". So it needs no
            # CastPermission — the permission seam is CR 601.3's "an effect
            # allows it", and asking it here would refuse the one cast the rules
            # themselves grant. What it does need is the ownership test, which
            # is the whole of the rule's restriction.
            source_zone = caster.command_zone
            hand_index = next(
                (
                    i for i, card in enumerate(source_zone)
                    if holds_spell_named(card, card_name)
                ),
                None,
            )
            if hand_index is None:
                raise ValueError(f"Card not in command zone: {card_name}")
            if not self.may_cast_from_command_zone(caster_index, source_zone[hand_index]):
                details = (
                    f"{card_name} is not {caster.name}'s commander and cannot be cast "
                    f"from the command zone (CR 903.8)"
                )
                return refuse(
                    card_name, classify_card(source_zone[hand_index]).effect_kind, details,
                )
        else:
            if from_zone not in ("graveyard", "exile", "library"):
                raise ValueError(f"cannot cast from {from_zone!r}")
            # "You may cast Goblin spells from the top of your library."
            # (Conspicuous Snoop, since M21.) The permission seam has answered
            # for the library since that card landed and this gate refused it,
            # so the grant existed and nothing could ever spend it — the loud
            # half of the same hole ``playable_from_zones`` had on the quiet
            # side. The loop below needs no library branch of its own: every
            # library permission is scoped to one card by identity
            # (``library_top.top_castable`` compares ``library[0]``), so only
            # the top card can match and the seat scan finds nothing in anybody
            # else's deck.
            # Whose copy of the zone. The caster's own on every grant but one:
            # "Search target opponent's library for a card and exile it. … you
            # may play that card" (Grinning Totem) leaves the card in the
            # *searched* player's exile (CR 400.3) and gives the permission to
            # the searcher, so the pile and the player come apart. Own pile
            # first, so a card the caster could already play is still found in
            # the order it was found before.
            seats = [caster_index] + [
                seat for seat in range(len(self.players)) if seat != caster_index
            ]
            source_zone = getattr(caster, from_zone)
            hand_index = None
            # **Which permission**, when a card is covered by more than one
            # (CR 601.2b). A flashback card under Yawgmoth's Will may be cast
            # for its mana cost under the Will or for its flashback cost under
            # its own keyword, and those are two casts: the caster who
            # announces an alternative cost is asking for the permission that
            # *requires* one (CR 118.9b, `CastPermission.cost`), so that kind
            # is looked for first and across every pile. Finding none, the
            # announcement is about the card's own printed alternative cost
            # (Force of Will out of an opened graveyard) and the ordinary
            # lookup stands. A caster who announces nothing gets the first
            # permission of either kind, which for a card only its own
            # flashback covers is the flashback — there is no other way to
            # cast it, so there is nothing to choose.
            for wanted in ((True, None) if alternative_cost else (None,)):
                for seat in seats:
                    pile = getattr(self.players[seat], from_zone)
                    for i, candidate in enumerate(pile):
                        if not holds_spell_named(candidate, card_name):
                            continue
                        if hand_index is None and seat == caster_index:
                            # The fallback that names the refusal below, and
                            # only out of the caster's own pile: "no effect
                            # allows playing that card from *your* exile" is
                            # what the player asked about.
                            hand_index = i
                        grant = permission_for(
                            self, caster_index, candidate, from_zone,
                            as_land=candidate.primary_type == "land",
                            # Judged as the spell it is being cast as — the
                            # named half of a split card (CR 709.3a).
                            spell=spell_named(candidate, card_name),
                            costed=wanted,
                        )
                        if grant is not None and grant.zone_seat == seat:
                            source_zone, hand_index, permission = pile, i, grant
                            source_seat = seat
                            break
                    if permission is not None:
                        break
                if permission is not None:
                    break
            if hand_index is None:
                raise ValueError(f"Card not in {from_zone}: {card_name}")
            if permission is None:
                details = (
                    f"no effect allows playing {card_name} from "
                    f"{caster.name}'s {from_zone} (CR 601.3)"
                )
                return refuse(
                    card_name, classify_card(source_zone[hand_index]).effect_kind, details,
                )
        return hand_index, permission, source_seat, source_zone

    def _announced_cast_costs(
        self, *, card, caster, caster_index, chosen_creature_type,
        classification, cost_hand_index, cost_other_hand_indices, decline_copy,
        extra_generic_tax, extra_pip_tax, from_zone, hand_index,
        optional_cost_payments, target_permanent_ids, target_permanent_index,
        x_value,
    ):
        """The costs a cast announces (CR 601.2b), and the choices it makes
        beside them, before any of its targets is judged and before anything is
        paid.

        The printed additional costs the zone it is cast from charges; the
        optional offers it takes (kicker, buyback), folded into the price with
        buyback's own reduction (CR 601.2f), an offer's X and the colours that
        X may be paid in; the creature type a cost or a graveyard target's
        narrowing has the caster choose; a declined copy-as-it-enters
        (CR 707.5); and the cards a discard cost names, resolved while the hand
        still holds the spell.

        A step of ``_cast_onto_stack``, moved out of it whole and called from
        it in its place: "above" and "below" in its comments are places in the
        cast as that method runs it.

        Returns the refusal, or ``(cast_costs, chosen_type_word, copy_declined,
        cost_hand_cards, extra_generic_tax, offer_x_colorings, optional_paid,
        x_value)``.
        """
        # A printed additional cost (CR 601.2b). Only the costs this *zone*
        # charges: Demonic Embrace prints one card with two prices —
        # {1}{B}{B} from the hand and {1}{B}{B} plus 3 life plus a card from the
        # graveyard — so a cost naming a zone applies to that zone alone, and
        # an unmarked cost ("as an additional cost to cast this spell") applies
        # wherever the spell is cast from.
        #
        # Gathered here and *checked* below, once X has been announced. See the
        # gate's own note for why the check moved.
        cast_costs = tuple(
            cost for cost in additional_costs(card)
            if cost.from_zone is None or cost.from_zone == from_zone
        )

        # CR 601.2b's optional additional costs, announced now and folded into
        # the mana below. **Not** part of `_unpayable_additional_cost`: an offer
        # is not a price, so declining one cannot make a spell uncastable, and
        # taking one past what the pool holds is refused by the mana payment
        # itself — which is where CR 601.2h puts an unpayable mana cost, and
        # which spends nothing on the way to refusing.
        optional_paid, optional_denial = _optional_cost_announcement(
            card, cast_costs, optional_cost_payments,
        )
        if optional_denial is not None:
            return refuse(
                card.name, classification.effect_kind, optional_denial,
            )
        # CR 601.2b's choice-shaped price, announced here — beside the optional
        # offers above and before any mana is spent, which is where CR 601.2b
        # puts every choice a cast makes. It charges nothing, so there is no
        # CR 601.2h gate to pass: every creature type is a legal answer.
        #
        # Refused rather than repaired when the word is not a creature type
        # (idiom 9): a picker's list is only true if the engine declines what is
        # not on it, and a silently-corrected answer would make the spell's own
        # P/T disagree with what the player chose.
        #
        # The same announcement with no price behind it, for a spell whose
        # *targets* are of the type chosen (Aphetto Dredging: "the creature
        # type before the targets", its ruling). Made here, before the target
        # gates below judge what was named under it.
        chosen_type_word: str | None = None
        if any(
            cost.choose_creature_type for cost in cast_costs
        ) or self._cast_type_narrows_graveyard_targets(card):
            from ...grammar.vocabulary import CREATURE_TYPES, display_type_word

            if chosen_creature_type is not None:
                chosen_type_word = str(chosen_creature_type).strip().lower()
                if chosen_type_word not in CREATURE_TYPES:
                    denial = (
                        f"{chosen_creature_type} is not a creature type "
                        f"(CR 601.2b, CR 205.3m)"
                    )
                    return refuse(
                        card.name, classification.effect_kind, denial,
                    )
            else:
                chosen_type_word = self._default_cast_creature_type(
                    caster_index, card
                )
            self.log.append(
                f"{caster.name} chose "
                f"{display_type_word(chosen_type_word) if chosen_type_word else 'no creature type'} "
                f"to cast {card.name}"
            )

        # The copy-as-it-enters "may" declined (``decline_copy``), announced
        # with the copy target it replaces and checked here, before anything
        # is paid. Naming a permanent to copy *and* declining to copy is two
        # answers to one question, refused rather than ranked.
        copy_declined = bool(decline_copy) and copy_on_enter_type(
            compile_card_oracle(card).normalized_text or ""
        ) is not None
        if copy_declined and (
            target_permanent_index is not None
            or first_target_id(target_permanent_ids) is not None
        ):
            return refuse(
                card.name, classification.effect_kind,
                "a cast cannot both name a permanent to copy and decline "
                "to copy (CR 707.5)",
            )

        # "Buyback costs cost {2} less." (Memory Crystal.) CR 601.2f applied to
        # CR 702.27a's offer, so it is read here — where the offer's symbols
        # become mana this cast owes — and nowhere near the spell's own mana
        # cost, which this modifier says nothing about.
        #
        # Only the buyback offer is reduced, never every optional cost this
        # spell prints: Primitive Justice's "you may pay {1}{R} and/or {1}{G}"
        # is CR 601.2b's repeated offer and no keyword at all, and reducing it
        # would be a card Memory Crystal does not print. The offer is picked out
        # by asking ``cast_costs.buyback_cost`` for this card's key — the same
        # reader ``buyback_paid`` uses at resolution, so the offer this
        # discounts is exactly the offer that buys the card back.
        buyback_key = buyback_cost(card.oracle_text or "")
        buyback_off, buyback_by = (
            buyback_cost_reduction(self) if buyback_key is not None else (0, [])
        )
        # "Kicker {X}" (Verdeloth the Ancient), "Kicker {X}{2}" (Kangee). An X
        # that lives in an *offer* (CR 107.3a's "additional cost with an {X} in
        # it"), so CR 601.2b's two announcements depend on each other: a caster
        # who took the offer names a number and pays for it just below, and one
        # who declined names none. The number is settled here, before anything
        # reads it, so a stray X sent with a declined kicker cannot reach the
        # permanent ("create X Saprolings") by another road -- and an X nobody
        # announced for a kicker that *was* taken is the 0 it reads as.
        if optional_x_offers(card, from_zone=from_zone):
            if cast_announces_x(card, from_zone=from_zone, taken=optional_paid):
                x_value = max(0, int(x_value or 0))
            else:
                x_value = None
        # "Spend only colored mana on X. No more than one mana of each color
        # may be spent this way." (Emblazoned Golem's "Kicker {X}".) The X of
        # such an offer is not generic mana: it is one unit of each of X
        # colours, and *which* colours is the payer's CR 601.2h choice. So the
        # offer contributes only its non-X part to the taxes below, and the
        # candidate colourings travel to the payment, which takes the first
        # the pool can pay with real units of those colours.
        #
        # ``((),)`` -- one choice, of nothing -- for every other cast, so the
        # payment below makes exactly one pass and sets nothing aside.
        offer_x_colorings: tuple[tuple[str, ...], ...] = ((),)
        for offer, times in _optional_cost_totals(cast_costs, optional_paid):
            colorings = offer.x_colorings(x_value)
            if colorings is None:
                charged = offer.cost_at(x_value)
            elif not colorings:
                # There are five colours, so no X above five can be paid one
                # mana of each. Refused here -- before any cost is paid, and
                # whether or not this game charges mana -- because the sentence
                # bounds the announcement itself: an X the cost cannot be paid
                # at is not one the caster may name (CR 601.2h, CR 601.2e).
                refusal = (
                    f"{card.name}: X can't be {x_value} -- no more than one "
                    f"mana of each color may be spent on X"
                )
                return refuse(
                    card.name, classification.effect_kind, refusal,
                )
            else:
                charged = offer.cost_at(0)
                offer_x_colorings = colorings
            if buyback_off and offer.symbols == buyback_key:
                # Through ``reduce_cost``, the one place CR 118.7's arithmetic
                # lives: a generic reduction touches only the generic component
                # and clamps at zero, so a buyback of {1} under two Crystals is
                # free rather than negative.
                charged = reduce_cost(charged, CostReduction(generic=buyback_off))
                self.log.append(
                    f"{card.name}'s buyback costs {{{buyback_off}}} less "
                    f"({', '.join(sorted(set(buyback_by)))})"
                )
            for symbol, count in charged.items():
                if symbol == "generic":
                    extra_generic_tax += count * times
                else:
                    extra_pip_tax[symbol] = (
                        extra_pip_tax.get(symbol, 0) + count * times
                    )
        # "Kicker—**{2}{B}**, Discard a creature card." (Dralnu's Pet.) The
        # mana clause of an optional price that is not only mana: folded into
        # the same payment as the offers above, and only for the caster who
        # took the price — through the one reader the gate and the collector
        # below skip an untaken offer by, so the mana and the discard are
        # charged together or not at all.
        for cost in cast_costs:
            if cost.mana_symbols and optional_cost_taken(cost, optional_paid):
                for symbol, count in cost.mana_cost.items():
                    if symbol == "generic":
                        extra_generic_tax += count
                    else:
                        extra_pip_tax[symbol] = extra_pip_tax.get(symbol, 0) + count

        # Resolve the named discard **here**, while `cost_hand_index` still
        # indexes the hand the caster was looking at. The spell leaves that hand
        # further down, and every card after it slides up a slot — so an index
        # read afterwards names the neighbour, and one past the shortened end
        # fell through to a bare `0` and discarded the *first* card in hand. A
        # cast that names a card it cannot pay with is refused rather than
        # silently repointed, before any mana is spent.
        cost_hand_cards, cost_denial = self._resolve_discard_cost_cards(
            caster_index, card, cast_costs,
            cost_hand_index=cost_hand_index,
            cost_other_hand_indices=cost_other_hand_indices,
            spell_hand_index=hand_index if from_zone == "hand" else None,
            x_value=x_value,
        )
        if cost_denial is not None:
            return refuse(card.name, classification.effect_kind, cost_denial)
        return (
            cast_costs, chosen_type_word, copy_declined, cost_hand_cards,
            extra_generic_tax, offer_x_colorings, optional_paid, x_value,
        )

    def _resolve_chosen_modes(
        self, card, mode_choices: list[dict] | None, *,
        optional_paid: dict | None = None,
    ) -> tuple[tuple, str | None]:
        """The ``ChosenMode`` list for this cast, or a refusal naming the fault.

        CR 601.2b: the modes are chosen as the spell is cast, and how many is
        what the head printed. Three things are checked, because each is a way a
        caller could otherwise get a spell the card does not describe:

        * a card whose head is not "one **or more**" gets at most one mode —
          otherwise any modal spell would perform every bullet;
        * every index names a real mode of *this* card;
        * no mode is chosen twice (CR 700.2d: the same mode may be chosen again
          only if the card says so, and none in this pool does).

        The list comes back in **printed** order whatever order it arrived in,
        because that is the order the modes resolve in (CR 608.2c) — sorting
        once here is what lets the resolution loop be a loop rather than a sort.

        **Entwine** (CR 702.42a) is the one way a "choose one" card takes more:
        *optional_paid* is the cast's CR 601.2b answer, and a paid entwine is
        every mode (``entwine.entwine_mode_refusal`` holds the two together).
        A headless cast that paid it and named no mode was given every mode
        before this ran (``entwine.entwined_mode_choices``).
        """
        from ...entwine import entwine_cost, entwine_mode_refusal, entwined
        from ...game_types import ChosenMode, as_target_ids, as_target_slots

        program = compile_card_oracle(card)
        entwine_paid = entwined(card, {"additional_costs_paid": optional_paid or {}})
        # "**An opponent** chooses one —" (CR 700.2e). The choice is made at the
        # same moment (CR 601.2b) but by somebody else, so an announcement that
        # names a mode is not a legal announcement — it is the caster taking the
        # half of the card that suits them, which on all three cards printing
        # this head is the opposite of what the card does. Refused rather than
        # ignored: a dropped mode choice is a client quietly getting a different
        # spell from the one it asked for.
        if program.mode_chooser is not None:
            if mode_choices:
                return (), (
                    f"{card.name}: an opponent chooses this spell's mode"
                )
            return (), None
        if not mode_choices:
            return (), None
        if not program.modes:
            return (), f"{card.name} has no modes to choose"
        if entwine_cost(card.oracle_text or "") is not None:
            refusal = entwine_mode_refusal(
                card, len(program.modes),
                [entry.get("index") for entry in mode_choices], entwine_paid,
            )
            if refusal is not None:
                return (), refusal
        elif len(mode_choices) > 1 and not program.modes_at_least:
            return (), f"{card.name} chooses one mode, not {len(mode_choices)}"
        seen: set[int] = set()
        chosen: list[ChosenMode] = []
        for entry in mode_choices:
            index = entry.get("index")
            if not isinstance(index, int) or not 0 <= index < len(program.modes):
                return (), f"{card.name}: no mode {index!r}"
            if index in seen:
                return (), f"{card.name}: mode {index} was chosen twice"
            seen.add(index)
            stack_index = entry.get("target_stack_index")
            stack_item = (
                self.stack[stack_index]
                if isinstance(stack_index, int) and 0 <= stack_index < len(self.stack)
                else None
            )
            # The mode's targets in each zone's own keyword, as the cast's are
            # (``engine/target_keywords``): its permanents by id, a graveyard
            # card by its place in the pile.
            seat, slot, refusal = announced_slot(
                self, cast_target_zone(card, mode_index=index), name=card.name,
                target_player_index=entry.get("target_player_index"),
                target_permanent_index=entry.get("target_permanent_index"),
                target_permanent_ids=entry.get("target_permanent_ids"),
                target_graveyard_indices=entry.get("target_graveyard_indices"),
            )
            if refusal is not None:
                return (), refusal
            chosen.append(ChosenMode(
                index=index,
                target_player_index=seat,
                target_permanent_index=as_target_slots(slot),
                # A mode's targets by identity, where the caller resolved
                # them: "Tap two target creatures" (Blinding Beam, entwined)
                # may name creatures on two battlefields, which slots beside
                # one ``target_player_index`` cannot say — the spell's own
                # ``target_permanent_ids`` channel, per mode.
                # ``_stamp_stack_targets`` keeps a mode that arrives stamped.
                target_permanent_id=as_target_ids(entry.get("target_permanent_ids")),
                target_stack_item=stack_item,
            ))
        chosen.sort(key=lambda mode: mode.index)
        return tuple(chosen), None

    def _mode_target_refusal(
        self, *, card, caster_index, chosen_modes, classification,
        divided_targets, from_zone, mode_index, no_target_answers_x,
        optional_paid, role_seats, target_permanent_ids,
        target_permanent_index, target_player_index, target_stack_item,
        x_value, chosen_creature_type=None, role_graveyard_stamps=None,
    ):
        """CR 601.2c, asked once per announced mode (CR 601.2b chooses the
        modes first): the per-kind target gate, whether any legal target exists
        at all, the target the caster named, a target on the stack, and a stack
        target named for an announcement that has none there. Nothing has been
        spent.

        A step of ``_cast_onto_stack``, moved out of it whole and called from
        it in its place: "above" and "below" in its comments are places in the
        cast as that method runs it.

        Returns the refusal, or None.
        """
        # **Once per announced mode** (CR 601.2b chooses the modes, then
        # CR 601.2c chooses each mode's targets). An ordinary spell and the
        # `mode_index=` spelling make one announcement, on the cast's own
        # target fields; a "choose one or more" cast (`mode_choices`) makes one
        # per chosen mode, each carrying the targets it named — which were
        # checked by nobody, because every gate below was handed the cast's
        # own (empty) fields beside the first chosen mode's index.
        for (
            announced_mode, mode_seat, mode_slot, mode_ids, mode_stack_item,
        ) in _mode_announcements(
            chosen_modes, mode_index, target_player_index,
            target_permanent_index, target_permanent_ids, target_stack_item,
        ):
            target_ok, target_reason = self._validate_cast_targets(
                card, caster_index, mode_seat, mode_slot, mode_stack_item,
                mode_index=announced_mode, x_value=x_value,
                target_permanent_ids=mode_ids,
                # CR 601.2b is answered above; CR 702.33g makes the targets this
                # gate counts depend on it.
                optional_cost_payments=optional_paid,
                # The cast's own announcement only: a "choose one or more"
                # mode names its targets on the mode, which has one seat.
                target_role_seats=None if chosen_modes else role_seats,
                chosen_creature_type=chosen_creature_type,
                # …and its graveyard slots, for the same reason.
                target_role_stamps=(
                    None if chosen_modes else role_graveyard_stamps
                ),
            )
            if not target_ok:
                return refuse(card.name, classification.effect_kind, target_reason)

            # CR 601.2c's other half, asked before what was *named*: a spell that
            # must announce a target cannot be cast while no legal target exists.
            # The arms above ask it of the kinds they name; this asks it of every
            # spell, through the list the picker is handed — so "Destroy target
            # artifact or enchantment. Draw two cards." on an empty board is an
            # illegal announcement rather than a two-mana cantrip. Nothing has been
            # spent yet.
            #
            # **And of every mode**, by the mode announced: Chaos Charm's "deals
            # 1 damage to target creature" was castable at an empty board, and
            # Treva's Charm's "exile target attacking creature" outside combat.
            unaimed = self.no_legal_cast_target_refusal(
                caster_index, card,
                optional_cost_payments=optional_paid, x_value=x_value,
                mode_index=announced_mode,
                # A spell cast out of a graveyard is not a card in it by the
                # time targets are chosen (CR 601.2a), so it cannot be the
                # legal target that lets itself be cast.
                from_zone=from_zone,
            )
            if unaimed is None and no_target_answers_x:
                # …and the one shape of "nothing to name" that list cannot
                # show: entries, and an announced X none of them answers
                # ("destroy target artifact with mana value X", Detonate, cast
                # bare for an X no artifact has — `bare_announcements.
                # default_cast_target`). It was accepted, paid for and
                # resolved onto nothing.
                unaimed = f"no valid target for {card.name}"
            if unaimed is not None and mode_stack_item is None:
                return refuse(card.name, classification.effect_kind, unaimed)

            # CR 601.2c for the target the caller *named*, beside the per-kind arms
            # above rather than inside them: a spell whose primary instruction is a
            # `sequence` wrapper reaches no arm at all, so "Destroy target artifact.
            # You gain life equal to its mana value" could be cast on a Grizzly
            # Bears — the destroy then found nothing and the life was gained anyway.
            # Still before any mana leaves the pool.
            named_refusal = self.cast_target_refusal(
                caster_index, card,
                target_player_index=mode_seat,
                target_permanent_index=mode_slot,
                target_permanent_ids=mode_ids,
                from_zone=from_zone,
                # CR 601.2b is announced above; CR 601.2c's target count follows
                # from it for a spell that prints "for each additional <cost> you
                # paid, … another target …". The gate is the only reader that can
                # see both announcements at once.
                optional_cost_payments=optional_paid,
                mode_index=announced_mode,
                # CR 601.2d's list, whose every entry is a target too — and it
                # is the cast's own, never one mode's: a "choose one or more"
                # mode names its targets on the mode (`_mode_announcements`).
                divided_targets=None if chosen_modes else divided_targets,
                # …and the two things that say whether a cast naming no player
                # named *nothing* (a spell on the stack is a target) and whether
                # it owed a target at all ("X target …" at an announced X).
                target_stack_item=mode_stack_item,
                x_value=x_value,
                chosen_creature_type=chosen_creature_type,
            )
            if named_refusal is not None:
                return refuse(card.name, classification.effect_kind, named_refusal)
            # …and the same rule for a target **on the stack**, which the gate
            # above does not read (its slots are battlefield slots). One call
            # where Invasion's first wave left two: see
            # `legality_stack.cast_stack_target_refusal`. Without it "counter target
            # creature spell" was announceable at any spell, paid for, and then
            # declined by its own handler — and a bare cast was accepted with
            # nothing on the stack its phrase admits.
            stack_refusal = self.cast_stack_target_refusal(
                caster_index, card, mode_stack_item, from_zone=from_zone,
                mode_index=announced_mode,
            )
            if stack_refusal is not None:
                return refuse(card.name, classification.effect_kind, stack_refusal)
            # …and the rule's other side: a stack object named for an
            # announcement that has no target there (a Lightning Bolt, a Terror,
            # a Wrath of God), or beside a permanent for "target spell **or**
            # permanent". It was accepted, recorded and ignored.
            stray_refusal = self.stray_stack_target_refusal(
                caster_index, card, mode_stack_item, from_zone=from_zone,
                mode_index=announced_mode,
                optional_cost_payments=optional_paid,
                names_a_permanent=bool(
                    [pid for pid in (mode_ids or ()) if isinstance(pid, int)]
                    or mode_slot is not None
                ),
            )
            if stray_refusal is not None:
                return refuse(card.name, classification.effect_kind, stray_refusal)

    def _arm_opponent_mode_choice(self, caster_index: int, card, spell_item) -> None:
        """CR 700.2e: hand the mode choice to a player other than the caster.

        Nothing is armed for an ordinary modal spell — the caster already named
        its mode as part of the announcement — so this is a no-op for every card
        but the three that print the head.

        **Which opponent** is the caster's choice when there is more than one
        (CR 700.2e's second sentence, CR 601.7a): asked first, through the one
        seam every unnamed "an opponent" goes through
        (``handlers/player_choices.ask_which_opponent``), and the mode prompt
        is armed for the seat named. A caster nobody asks takes the stated
        default, the first living opponent; in a duel the rule's "if there is
        more than one" clause never applies and nobody is asked.
        """
        from ...game_types import OracleExecutionContext
        from ...handlers.player_choices import ask_which_opponent

        program = compile_card_oracle(card)
        if program.mode_chooser is None or not program.modes:
            return

        def arm_for(chooser: int | None) -> None:
            if chooser is None:
                # CR 700.2e names a player who has to exist; with none left the
                # spell has nobody to ask and the first printed mode stands,
                # which is the same stated policy the non-interactive default
                # takes.
                from ...game_types import ChosenMode

                spell_item.chosen_mode_index = 0
                spell_item.chosen_modes = (ChosenMode(index=0),)
                return
            self.arm_pending_choice(
                "opponent_mode_choice", chooser,
                card_name=card.name,
                labels=[mode.label for mode in program.modes],
                _item=spell_item,
                # Part of the spell's announcement (CR 601.2b), so it holds the
                # spell on the stack until answered — the key every
                # announcement-time prompt holds its object with.
                _trigger_item=spell_item,
            )
            self.log.append(
                f"{self.players[chooser].name} chooses a mode for {card.name}"
            )

        # No resolution is running, so the naming gets a scratchpad of its own
        # to record the seat in — the same one a resolution's ``choose_opponent``
        # step writes, read back by ``arm_for`` as the naming's last step.
        ask_which_opponent(
            self,
            OracleExecutionContext(
                caster=self.players[caster_index], target=None, card=card,
            ),
            card_name=card.name,
            prompt=f"Choose the opponent who chooses {card.name}'s mode.",
            then=arm_for,
            announcing=spell_item,
        )

    def arm_modal_mode_targets(self, spell_item, chooser_seat: int) -> None:
        """CR 601.2c for a mode somebody else chose (CR 700.2e).

        The rules order is modes (601.2b) then targets (601.2c), and for these
        spells the two belong to different players — so the caster cannot name a
        target while casting: they do not yet know which mode they are naming it
        for, and a mode the opponent then declines to pick would have published
        the caster's intentions for nothing.

        So the targets are asked for *after* the answer, and the prompt is armed
        by that answer. The spell is on the stack by then, which is a departure
        from the rules' internal order and not from anything observable:
        `opponent_mode_choice` and this prompt both block every seat, so no
        player has had priority between CR 601.2i and this — the whole
        announcement is still one uninterruptible moment.

        The picker is the one `legality_enumeration._enumerate_targets` builds for every
        other spell, with the chooser's seat supplied beside the
        ``that_player_only`` flag the mode's own noun phrase produced ("up to
        two target creatures **that player** controls"). Nothing else can supply
        it: the seat came into existence when the mode was chosen.

        A mode that targets nothing arms nothing, which is every mode of every
        other card that prints this head.
        """
        from ...targeting import _from_instructions

        program = compile_card_oracle(spell_item.card)
        index = spell_item.chosen_mode_index
        if index is None or not 0 <= index < len(program.modes):
            return
        instruction = program.modes[index].instruction
        if instruction is None:
            return
        spec = _from_instructions((instruction,))
        if spec is None:
            return
        if spec.get("that_player_only"):
            spec = {**spec, "that_player_index": chooser_seat}
        candidates = self._enumerate_targets(
            spell_item.caster_index, spell_item.card, spec, for_cast=True,
        )
        offered = []
        for candidate in candidates:
            if candidate.get("kind") != "permanent":
                continue
            perm = self.permanent_at(candidate["seat"], candidate["index"])
            if perm is None:
                continue
            offered.append({
                "seat": candidate["seat"],
                "permanent_index": candidate["index"],
                "permanent_id": perm.permanent_id,
                "name": perm.effective_card.name,
            })
        if not offered:
            # CR 601.2c names as many targets as the spell requires and no more.
            # "**Up to** two" requires none, so a board with nothing to destroy
            # is a legal announcement and not a refusal — the mode simply
            # destroys nothing. A mode with a *mandatory* target and no legal
            # one could not have been chosen at all (CR 700.2a), which is a
            # gate on the choice rather than on this prompt; no card in the pool
            # prints one, and the refusal it would need is named in ROADMAP.md.
            self.log.append(
                f"{spell_item.card.name}: the chosen mode has no legal target"
            )
            return
        self.arm_pending_choice(
            "modal_mode_targets", spell_item.caster_index,
            card_name=spell_item.card.name,
            mode_label=program.modes[index].label,
            targets=offered,
            max_targets=int(spec.get("max_targets") or 1),
            _item=spell_item,
            # Still the announcement (CR 601.2c): held like the mode before it.
            _trigger_item=spell_item,
        )
