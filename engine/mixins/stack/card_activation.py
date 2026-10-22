"""Activating an ability of a card that is not a permanent: in a hand
(cycling, CR 702.29a) or in a graveyard (Ashen Ghoul).

CR 113.6: an ability functions only from the battlefield unless something
says otherwise, and these two entry points are where that is read —
``engine/activation_zones.py``'s answer, shared with the battlefield path so
the same ability stays off a permanent's list. ``hand_activation_cost`` is
what a hand ability costs right now (CR 601.2f), asked by the payment, the
web layer's button and the AI alike; ``_graveyard_cost_refusal`` names a
cost a card in a graveyard cannot pay.

Split out of ``activation.py`` at the 2,000-line cap, and composed onto
``Game`` with the other parts of ``AbilityActivationMixin``, directly after
it.
"""

from __future__ import annotations

from ...activation_prohibitions import activation_prohibition
from ...restricted_mana import ACTIVATE, PaymentPurpose
from ...bare_announcements import (announced_fields, default_activation_target,
                                   names_an_object)
from ...cost_modifiers import ability_cost_reduction, ability_cost_tax
from ...activation_zones import GRAVEYARD, HAND, ability_functions_from
from ...targeting import usable_activated_abilities
from ...mana_payment import is_mana_ability
from ...game_types import (OracleExecutionContext, OracleStateMachine,
                           SimulationResult, StackItem)
from ...oracle import compile_card_oracle
from ...subject_filters import filter_head_noun, subject_matches


def hand_activation_cost(game, controller_index: int, card, ability):
    """What activating *ability* off *card* **in a hand** costs right now, and
    the log lines the modifiers earned: ``(symbol dict, notes)``.

    CR 601.2f computes a cost as the ability is activated, and nothing in that
    rule is about where the ability's source is — "Activated abilities of
    creatures cost {1} more to activate" taxes a cycling ability in a hand
    exactly as it taxes one on the battlefield. ``activate_from_hand`` charged
    ``ability.cost.mana`` flat until Fluctuator arrived, so a tax on a
    hand-activated ability was **unenforced** and a reduction reached nothing.

    A function rather than a block inside that method because three other
    readers ask the same question and must get the same number: the web layer's
    ``payable`` flag on the hand-ability button, the AI's hand-activation loop,
    and the payment itself. A button that reports a Cycling {2} unaffordable
    while the engine would let it through is the Roots class with the sign
    flipped.

    **Which modifiers reach it is narrower than on the battlefield**, and by a
    rule rather than by a scope: CR 109.2 makes "activated abilities of
    creatures" (Heartstone) a sentence about creature *permanents*, so it says
    nothing about a creature card in a hand — while Fluctuator's subject is the
    **ability** and reaches both zones. Read the other way, a Heartstone made
    Waker of Waves' hand ability cheaper than the card.

    Increases before reductions (CR 601.2f), and the floor is measured over the
    **whole** remaining cost — "the mana in that cost", coloured pips included
    — which is why it is applied after the subtraction rather than as a clamp
    inside it. The Aura reduction the battlefield path also folds in is
    deliberately absent: an Aura enchants a permanent, and there is none here.
    """
    required = dict(ability.cost.mana)
    notes: list[str] = []
    tax, taxing_names = ability_cost_tax(
        game, controller_index, card, ability, on_battlefield=False,
    )
    if tax:
        required["generic"] = required.get("generic", 0) + tax
        notes.append(
            f"{card.name}'s ability is taxed by {', '.join(taxing_names)}"
        )
    discount, reducing_names, floor = ability_cost_reduction(
        game, controller_index, card, ability, on_battlefield=False,
    )
    if discount:
        before_total = sum(required.values())
        generic = required.get("generic", 0)
        coloured = before_total - generic
        reduced_generic = max(0, generic - discount)
        if reduced_generic + coloured < floor:
            reduced_generic = max(0, floor - coloured)
        required["generic"] = reduced_generic
        if before_total != reduced_generic + coloured:
            notes.append(
                f"{card.name}'s ability costs "
                f"{{{before_total - reduced_generic - coloured}}} less to "
                f"activate ({', '.join(reducing_names)})"
            )
    return required, notes


def _graveyard_cost_refusal(cost) -> str | None:
    """Why this activation cost cannot be charged from a graveyard, or None.

    Written as a *deny list over every field* rather than an allow list of the
    two shapes charged, because ``ActivatedAbilityCost`` grows: a field added
    later and not listed here would be a cost silently waived, which is the
    failure `engine/activation_restrictions.py` exists to prevent wearing
    another hat. Anything this names refuses the activation entirely.
    """
    if cost.requires_tap:
        # The tap symbol names the source permanent, and a card in a graveyard
        # is not one (CR 107.5).
        return "a tap symbol cannot be paid by a card in a graveyard"
    for field, label in (
        ("discard_last_drawn", "a discard cost"),
        ("exile_self", "an exile-this cost"),
        ("sacrifice_self", "a sacrifice-this cost"),
        ("return_self_to_hand", "a return-this-to-hand cost"),
        ("exile_filter", "a chosen exile cost"),
        ("discard_cards", "a discard cost"),
        ("discard_at_random", "a random discard cost"),
        ("discard_whole_hand", "a discard-your-hand cost"),
        ("discard_self", "a discard-this cost"),
        ("put_counter", "a counter cost"),
        ("put_counter_filter", "a counter cost on a chosen permanent"),
        ("sacrifice_also_filter", "a conjoined sacrifice cost"),
        ("remove_counter", "a counter-removal cost"),
        ("remove_counter_filter", "a counter-removal cost on a chosen permanent"),
        ("tap_count", "a tap-other-permanents cost"),
        ("return_to_hand_count", "a return-other-permanents-to-hand cost"),
        ("untap_filter", "an untap-another-permanent cost"),
        ("tap_attached", "a tap-the-attached-permanent cost"),
        ("sacrifice_attached", "a sacrifice-the-attached-permanent cost"),
        ("mana_from_attached", "a cost read off an attached permanent"),
        ("exile_top_of_library", "a library-exile cost"),
        ("mill_cards", "a mill cost"),
        ("hand_to_library_top", "a put-a-card-on-your-library cost"),
        ("pay_life", "a life cost"),
        ("loyalty", "a loyalty cost"),
        ("loyalty_x_sign", "a loyalty cost"),
    ):
        if getattr(cost, field, None):
            return f"{label} is not charged from a graveyard"
    if cost.sacrifice_filter is not None and cost.sacrifice_count != 1:
        return "only a one-permanent sacrifice cost is charged from a graveyard"
    return None


class CardActivationMixin:
    def activate_from_hand(
        self,
        controller_index: int,
        card_name: str,
        ability_index: int = 0,
        hand_index: int | None = None,
    ) -> SimulationResult:
        """Activate an ability of a card **in hand** — cycling (CR 702.29a),
        Waker of Waves.

        CR 113.6: an ability functions only from the battlefield unless
        something says otherwise, and a cost the card can only pay from hand —
        "Discard this card" — is what says otherwise (CR 113.6j through
        CR 701.9a). So this refuses any ability without that cost rather than
        opening the hand generally: an ability activatable from anywhere would
        let a creature card tap for its own {T} ability before it was ever cast.

        The read is ``engine/activation_zones.py``'s, shared with the negative
        half — ``usable_activated_abilities``, which is what keeps the *same*
        ability off a permanent's list once the card is in play. This gate used
        to ask ``cost.discard_self`` here and nothing asked anywhere else, so
        Waker of Waves on the battlefield could discard a card that was not in
        anybody's hand.

        *ability_index* indexes the hand-activatable abilities, not the card's
        printed ones: a cycling land prints a mana ability first, and an index
        into the raw list would name it.

        A parallel entry point rather than a branch in
        ``activate_permanent_ability``, because almost everything that function
        does is about a permanent — the controller check, the summoning
        sickness, the "loses all abilities" read, the tap. None of it applies to
        a card in a hand, and threading a None permanent through all of it would
        make every one of those reads answer a question about nothing.
        """
        controller = self.players[controller_index]
        matches = [
            index for index, card in enumerate(controller.hand)
            if card.name == card_name
        ]
        if hand_index is not None and hand_index in matches:
            matches = [hand_index]
        if not matches:
            details = f"{card_name} is not in {controller.name}'s hand"
            self.log.append(details)
            return SimulationResult(card_name, False, "unsupported", details)
        index = matches[0]
        card = controller.hand[index]

        program = compile_card_oracle(card)
        from_hand = usable_activated_abilities(program, zone=HAND)
        if not from_hand:
            details = f"{card.name}'s ability can only be activated from the battlefield"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)
        if not 0 <= ability_index < len(from_hand):
            details = f"{card.name} has no ability {ability_index}"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)
        ability = from_hand[ability_index]

        # CR 602.5, before anything is paid: the prohibitions that reach an
        # ability whose source is a card in a hand — a turn-long record on the
        # seat (Abeyance), "players can … activate abilities only during their
        # own turns" (City of Solitude), "during combat, players can't …
        # activate abilities that aren't mana abilities" (Hand to Hand). This
        # door asked none of them: it is a parallel entry point, so nothing
        # the permanent's road checks was ever on it, and a card was cycled on
        # an opponent's turn under a City of Solitude.
        prohibited = activation_prohibition(self, controller_index, card, ability)
        if prohibited is not None:
            self.log.append(prohibited.details)
            return SimulationResult(
                card.name, False, "unsupported", prohibited.details
            )

        # CR 601.2f: the cost is computed as the ability is activated, and
        # that includes every increase and reduction on any battlefield —
        # "Activated abilities of creatures cost {1} more" (Gloom's family)
        # taxes an ability activated from a hand exactly as it taxes one
        # activated from the battlefield, because nothing in CR 601.2f is about
        # where the ability's source is.
        #
        # This whole block was missing: the hand path charged
        # ``ability.cost.mana`` flat, so a tax on a hand-activated ability was
        # **unenforced** and a reduction reached nothing. It is the same pass
        # the battlefield path runs above, in the same order (increases first,
        # then reductions, CR 601.2f), against the *card* rather than a
        # permanent — an ability in a hand has none, which is what
        # ``modified_ability_source_card`` answers.
        #
        # The Aura reduction beside it on the battlefield path is deliberately
        # absent: an Aura enchants a permanent, and there is none here.
        required_cost, cost_notes = hand_activation_cost(
            self, controller_index, card, ability
        )
        self.log.extend(cost_notes)
        # CR 601.2h: an unpayable cost makes the ability unactivatable, checked
        # before anything is spent — the same order every other activation keeps.
        # The source is the *card* in hand, not a permanent: an ability
        # activated from a hand has no permanent, and its card is what a
        # restriction narrowing by type would be asking about.
        if self.enforce_mana_costs and not self._pay_mana_cost(
            controller, required_cost,
            purpose=PaymentPurpose(ACTIVATE, source=card),
        ):
            details = f"{controller.name} cannot pay for {card.name}'s ability"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)

        # The card leaves the hand as the cost is paid (CR 602.2b), before the
        # ability is on the stack — so an effect that looks at the hand during
        # resolution does not see the card that paid for it.
        del controller.hand[index]
        if ability.cost.exile_self and not ability.cost.discard_self:
            # "**Exile this card from your hand**: Add {G}." (Elvish Spirit
            # Guide.) The other cost that names a hand, and not a discard: the
            # card goes to exile, so nothing watching a discard sees one and
            # nothing can bring it back from a graveyard.
            controller.exile.append(card)
            self.log.append(
                f"{controller.name} exiled {card.name} from their hand to "
                "activate its ability"
            )
        else:
            self._discard_card(controller, card)
            self.log.append(f"{controller.name} discarded {card.name} to activate its ability")

        if is_mana_ability(ability):
            # CR 605.3b: an activated mana ability does not use the stack,
            # wherever its source is — the battlefield path's own rule, asked
            # through the same predicate. The Guide's {G} arrives now, which
            # is what lets it pay for the spell being cast.
            supported, details = OracleStateMachine(
                self,
                OracleExecutionContext(
                    # A mana ability targets nothing (CR 605.1a), so the
                    # context's player slot names nobody; it is the activator
                    # rather than None so a handler reading it meets a seat.
                    caster=controller, target=controller, card=card,
                    source_permanent=None,
                ),
            ).run(ability.instruction)
            return SimulationResult(card.name, supported, ability.effect_kind, details)

        self._stack_push(
            # CR 602.2b: an activated ability's targets were chosen when it
            # was activated, so it does not choose again here.
            targets_already_chosen=True,
            item=StackItem(
                activated=True,
                card=card,
                caster_index=controller_index,
                target_player_index=None,
                target_permanent_index=None,
                x_value=None,
                ability_instruction=ability.instruction,
                ability_effect_kind=ability.effect_kind,
                # No source permanent: the object is a card in a graveyard by
                # now, and an ability activated from hand has none by
                # construction. A handler that needs one refuses on its own.
                source_permanent=None,
                ability_text=ability.source_line,
            )
        )
        self.log.append(f"{card.name} ability added to stack")
        return SimulationResult(card.name, True, ability.effect_kind, "queued")

    def activate_from_graveyard(
        self,
        controller_index: int,
        card_name: str,
        ability_index: int = 0,
        graveyard_index: int | None = None,
        cost_permanent_id: int | None = None,
        # What the ability aims at (CR 602.2b: an activated ability's targets
        # are chosen as it is activated, not when it resolves). Carrionette is
        # the first card here that needs them — "Exile this card and **target
        # creature** unless that creature's controller pays {2}" — and without
        # them the ability went on the stack with no target and exiled itself
        # for nothing. The same three keys the permanent path takes, spelled
        # the same way, because they end up in the same ``StackItem``.
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        target_permanent_ids: "list[int | None] | None" = None,
    ) -> SimulationResult:
        """Activate an ability of a card **in a graveyard** (Ashen Ghoul,
        Whiteout).

        CR 113.6m: an ability whose effect moves the card it is on out of a
        zone functions **only** from that zone. So the gate is not a list of
        cards and not a cost shape -- it is the compiled instruction's own
        ``functions_from`` key, the same derived fact ``engine/events.py`` reads
        to decide which graveyard triggers may fire. An ability without it is
        refused here, because opening the graveyard generally would let a
        creature card in the pile tap for its own {T} ability.

        A parallel entry point rather than a branch in
        ``activate_permanent_ability``, for ``activate_from_hand``'s reason:
        almost everything that function does -- the controller check, summoning
        sickness, the "loses all abilities" read, the tap -- is about a
        permanent, and a card in a graveyard is not one.

        **Two cost shapes, and any third is refused rather than waived.** Mana
        (Ashen Ghoul's {B}) and one sacrificed permanent named by a printed noun
        phrase (Whiteout's "Sacrifice a snow land"). A cost this cannot charge
        makes the ability unactivatable (CR 602.5c) -- the alternative is an
        ability activated for free, which is the silent direction.
        """
        controller = self.players[controller_index]
        matches = [
            index for index, card in enumerate(controller.graveyard)
            if card.name == card_name
        ]
        if graveyard_index is not None and graveyard_index in matches:
            matches = [graveyard_index]
        if not matches:
            details = f"{card_name} is not in {controller.name}'s graveyard"
            self.log.append(details)
            return SimulationResult(card_name, False, "unsupported", details)
        index = matches[0]
        card = controller.graveyard[index]

        program = compile_card_oracle(card)
        if not 0 <= ability_index < len(program.activated_abilities):
            details = f"{card.name} has no ability {ability_index}"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)
        ability = program.activated_abilities[ability_index]
        if not ability.supported or ability.instruction is None:
            details = f"{card.name}: ability not implemented"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)
        if ability_functions_from(ability) != GRAVEYARD:
            details = (
                f"{card.name}'s ability does not function from a graveyard "
                "(CR 113.6)"
            )
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)

        # Every printed "Activate only ..." clause on this line (CR 602.5), read
        # from the one table the support gate reads. The *card* is the source:
        # there is no permanent, and "three or more creature cards are above
        # this card" is a question about the card's place in the pile.
        #
        # …and every other CR 602.5 prohibition that reaches an ability whose
        # source is a card rather than a permanent — the table's rows that
        # bind one (``engine/activation_prohibitions.py``). This door asked
        # the printed clause alone, so "players can … activate abilities only
        # during their own turns" (City of Solitude) and Hand to Hand's
        # "during combat" stopped nothing activated from a graveyard.
        prohibited = activation_prohibition(self, controller_index, card, ability)
        if prohibited is not None:
            self.log.append(prohibited.details)
            return SimulationResult(
                card.name, False, "unsupported", prohibited.details
            )

        # CR 602.2b sends an activation through CR 601.2c, so the target is
        # checked **before** any cost is paid and against the same
        # ``_enumerate_targets`` list the picker is handed. Read here for the
        # reason the permanent path reads it there: an ability with a mandatory
        # object target it cannot fill is refused with nothing spent, rather
        # than activated to no effect — and on this card "nothing spent" also
        # means the card is not exiled out of the graveyard for free.
        target_refusal = self.activation_target_refusal(
            controller_index, card, ability,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
        )
        if target_refusal is not None:
            self.log.append(target_refusal)
            return SimulationResult(card.name, False, "unsupported", target_refusal)
        # …and an owed target left unnamed is the picker's first entry, named
        # here as on the permanent path and for its reason
        # (`engine/bare_announcements.py`): the object this builds is an
        # announced one, and its resolver looks for nothing it was not given.
        if not names_an_object(target_permanent_index, target_permanent_ids, None):
            default = default_activation_target(
                self, controller_index, card, ability,
                named_seat=target_player_index,
            )
            named = announced_fields(self, default) if default is not None else {}
            target_player_index = named.get("target_player_index", target_player_index)
            target_permanent_index = named.get(
                "target_permanent_index", target_permanent_index
            )
            target_permanent_ids = (
                named.get("target_permanent_ids") or target_permanent_ids
            )

        cost = ability.cost
        unchargeable = _graveyard_cost_refusal(cost)
        if unchargeable is not None:
            details = f"{card.name}: {unchargeable}"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)

        # CR 601.2h/602.5c: the whole cost is checked before any of it is spent,
        # so an ability with an unpayable half does not pay the other half.
        sacrifice_victim = None
        if cost.sacrifice_filter is not None:
            candidates = [
                perm
                for perm in self.controlled_by(controller_index)
                if subject_matches(
                    self, perm, cost.sacrifice_filter, observer=controller_index,
                )
            ]
            if not candidates:
                details = (
                    f"{card.name}: no {filter_head_noun(cost.sacrifice_filter)} "
                    "available to sacrifice"
                )
                self.log.append(details)
                return SimulationResult(card.name, False, "unsupported", details)
            # The same announcement an ability on the battlefield makes, so the
            # same check: a permanent named to pay that cannot is a refusal,
            # not a request for the default (CR 601.2h).
            named_cost_refusal = self._named_cost_refusal(
                card, controller, candidates,
                [cost_permanent_id] if cost_permanent_id is not None else None,
                None,
            )
            if named_cost_refusal is not None:
                self.log.append(named_cost_refusal)
                return SimulationResult(
                    card.name, False, "unsupported", named_cost_refusal
                )
            named = (
                self.permanent_by_id(cost_permanent_id)
                if cost_permanent_id is not None else None
            )
            sacrifice_victim = (
                named if any(perm is named for perm in candidates)
                else self.default_sacrifice_pick(candidates)
            )

        if self.enforce_mana_costs and not self._pay_mana_cost(
            controller, cost.mana, purpose=PaymentPurpose(ACTIVATE, source=card),
        ):
            details = f"{controller.name} cannot pay for {card.name}'s ability"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)
        if sacrifice_victim is not None:
            self.sacrifice_permanent(sacrifice_victim)
            self.log.append(
                f"{controller.name} sacrificed {sacrifice_victim.card.name} "
                f"to activate {card.name}"
            )

        # The card leaves the graveyard only when the *effect* moves it
        # (CR 608.2), not as the cost is paid -- so it stays in the pile while
        # the ability is on the stack, which is what lets a second Ashen Ghoul
        # count it as a card above.
        self._stack_push(
            targets_already_chosen=True,
            item=StackItem(
                activated=True,
                card=card,
                caster_index=controller_index,
                target_player_index=target_player_index,
                target_permanent_index=target_permanent_index,
                target_permanent_id=target_permanent_ids,
                x_value=None,
                ability_instruction=ability.instruction,
                ability_effect_kind=ability.effect_kind,
                # No source permanent: the object is a card in a graveyard.
                source_permanent=None,
                ability_text=ability.source_line,
            )
        )
        self.log.append(f"{card.name} ability added to stack from the graveyard")
        return SimulationResult(card.name, True, ability.effect_kind, "queued")
