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
from ...cycling import is_cycling_ability
from ...events import emit
from ...activation_zones import GRAVEYARD, HAND, ability_functions_from
from ...targeting import usable_activated_abilities
from ...mana_payment import is_mana_ability
from ...game_types import (OracleExecutionContext, OracleStateMachine,
                           SimulationResult, StackItem, as_target_ids,
                           as_target_slots)
from ...oracle import compile_card_oracle
from ...stack_targets import names_a_target
from ...subject_filters import card_matches_any, filter_head_noun, subject_matches
from .activation_charges import _named_discard_positions
from ...target_keywords import ability_target_zone, announced_slot
from ...target_requirements import narrow_offer
from ...refusals import noting, refuse, take_back_refused_attempt


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
        ("discard_at_random", "a random discard cost"),
        ("discard_whole_hand", "a discard-your-hand cost"),
        ("discard_self", "a discard-this cost"),
        ("put_counter", "a counter cost"),
        ("put_counter_filter", "a counter cost on a chosen permanent"),
        ("sacrifice_also_filter", "a conjoined sacrifice cost"),
        ("remove_counter", "a counter-removal cost"),
        ("remove_counter_filter", "a counter-removal cost on a chosen permanent"),
        ("return_to_hand_count", "a return-other-permanents-to-hand cost"),
        ("untap_filter", "an untap-another-permanent cost"),
        ("tap_attached", "a tap-the-attached-permanent cost"),
        ("sacrifice_attached", "a sacrifice-the-attached-permanent cost"),
        ("mana_from_attached", "a cost read off an attached permanent"),
        ("exile_top_of_library", "a library-exile cost"),
        ("mill_cards", "a mill cost"),
        ("hand_to_library_top", "a put-a-card-on-your-library cost"),
        ("graveyard_to_library_bottom", "a graveyard-to-library cost"),
        ("pay_life", "a life cost"),
        ("loyalty", "a loyalty cost"),
        ("loyalty_x_sign", "a loyalty cost"),
    ):
        if getattr(cost, field, None):
            return f"{label} is not charged from a graveyard"
    if cost.sacrifice_filter is not None and (
        not isinstance(cost.sacrifice_count, int) or cost.sacrifice_count < 1
    ):
        return "only a counted sacrifice cost is charged from a graveyard"
    return None


class CardActivationMixin:
    def activate_from_hand(self, *args, **kwargs) -> SimulationResult:
        """Activate an ability of a card in hand (``_activate_from_hand``) —
        one announcement, with the battlefield path's two rules around it.

        CR 602.2b routes activation through CR 601.2b–i, so the triggers its
        cost fires wait for the announcement to finish and go on the stack
        *above* the ability (``deferring_triggers``): Megrim's ping off a
        cycled card's discard resolves first. And the cost is a state change
        with no resolution behind it, after which CR 117.3c hands priority
        straight back — so CR 704.3's check is made here, as
        ``queue_permanent_ability`` and ``queue_from_hand`` make it: a Maro
        cycled down to no cards is 0/0 and dies before anybody acts. Neither
        was here, and the playbook's audit of non-resolution state changes had
        never reached a cost paid from a hand.

        A refusal takes back what the attempt wrote to the shared log
        (CR 733.1, ``engine/refusals.py``): the card is in a hand.
        """
        log_mark = len(self.log)
        with self.deferring_triggers():
            result = self._activate_from_hand(*args, **kwargs)
            take_back_refused_attempt(self, log_mark, result)
        if result.supported:
            self.check_state_based_actions()
        return result

    def activate_from_graveyard(self, *args, **kwargs) -> SimulationResult:
        """Activate an ability of a card in a graveyard
        (``_activate_from_graveyard``), wrapped as :meth:`activate_from_hand`
        is and for its two reasons: Havoc Jester's ping off Necrosavant's
        sacrificed creature goes above the ability, and the Wild Growth on the
        snow land Whiteout sacrificed is put into its owner's graveyard
        (CR 704.5m) before priority returns. A refusal is taken back from the
        shared log as theirs are (``engine/refusals.py``)."""
        log_mark = len(self.log)
        with self.deferring_triggers():
            result = self._activate_from_graveyard(*args, **kwargs)
            take_back_refused_attempt(self, log_mark, result)
        if result.supported:
            self.check_state_based_actions()
        return result

    def graveyard_activation_target_spec(self, controller_index: int, card, ability) -> dict:
        """What activating *ability* of *card* in a graveyard targets, as a
        picker is handed it: ``activation_offer`` — the very list
        ``activation_target_refusal`` judges a named target by, here and in
        :meth:`_activate_from_graveyard` — with ``requires_target`` and the
        announcement requirements in force (an opponent's Flagbearer,
        ``narrow_offer``), as ``activation_target_spec`` dresses a
        permanent's.

        Its own method because that one addresses its source by a
        battlefield slot, and a card in a graveyard has none (CR 113.6m:
        Carrionette's "Exile this card and target creature …" functions only
        from there). The browser's graveyard-ability button reads this, so the
        targets it offers and the targets the activation accepts are one list.
        """
        spec = self.activation_offer(controller_index, card, ability)
        spec["requires_target"] = spec.get("kind", "none") != "none"
        if names_a_target(getattr(ability, "source_line", None)):
            narrow_offer(self, controller_index, spec)
        return spec

    def _activate_from_hand(
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
            return refuse(card_name, "unsupported", details)
        index = matches[0]
        card = controller.hand[index]

        program = compile_card_oracle(card)
        from_hand = usable_activated_abilities(program, zone=HAND)
        if not from_hand:
            details = f"{card.name}'s ability can only be activated from the battlefield"
            return refuse(card.name, "unsupported", details)
        if not 0 <= ability_index < len(from_hand):
            details = f"{card.name} has no ability {ability_index}"
            return refuse(card.name, "unsupported", details)
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
            return refuse(
                card.name, "unsupported", prohibited.details,
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
            # The notes logged above go back with the refused attempt (CR
            # 733.1), so the actor's reason carries them.
            details = noting(
                f"{controller.name} cannot pay for {card.name}'s ability",
                cost_notes,
            )
            return refuse(card.name, "unsupported", details)

        # The card leaves the hand as the cost is paid (CR 602.2b), before the
        # ability is on the stack — so an effect that looks at the hand during
        # resolution does not see the card that paid for it.
        del controller.hand[index]
        if ability.cost.exile_self and not ability.cost.discard_self:
            # "**Exile this card from your hand**: Add {G}." (Elvish Spirit
            # Guide.) The other cost that names a hand, and not a discard: the
            # card goes to exile, so nothing watching a discard sees one and
            # nothing can bring it back from a graveyard.
            self.put_card_into_exile(controller, card)
            self.log.append(
                f"{controller.name} exiled {card.name} from their hand to "
                "activate its ability"
            )
        else:
            self._discard_card(controller, card, as_cost=True)
            self.log.append(f"{controller.name} discarded {card.name} to activate its ability")
            if is_cycling_ability(card, ability):
                self._announce_cycle(controller_index, card)

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

    def _announce_cycle(self, controller_index: int, card) -> None:
        """CR 702.29: *card* was just cycled by *controller_index* — the one
        place a cycling ability's discard cost is paid, so the one place a
        cycle is announced.

        Two conditions ride the one announcement. "Whenever **a player** cycles
        a card" (Astral Slide) is a permanent watching every seat, collected
        off the battlefield and narrowed by ``event_filters._cycles_card_filter``.
        "When **you cycle this card**" (Renewed Faith) is the cycled card's
        own, and CR 702.29c has it "trigger from whatever zone the card winds
        up in after it's cycled" — the graveyard, or wherever a discard
        replacement sent it — so it is asked of *card* itself
        (``events.moved_card_trigger_events``), never by scanning a zone: a
        second copy already in the graveyard was not cycled.

        Called inside ``activate_from_hand``'s ``deferring_triggers`` window,
        so both go on the stack **above** the cycling ability once it is
        there (CR 602.2b through CR 601.2i), and resolve before its draw — the
        2022-12-08 rulings on every Onslaught card that prints the trigger.

        A discard by any other means is not a cycle and never reaches here; a
        cycled card is discarded once, so it is announced once. The discard
        itself was announced already, by ``_discard_card`` — cycling *is*
        discarding (CR 702.29a), so Megrim answers a cycled card too.
        """
        self.log.append(f"{self.players[controller_index].name} cycled {card.name}")
        emit(
            self, "cycles_card",
            subject=card,
            # The seat that cycled: the filter's "you" / "an opponent", and
            # CR 108.4a's controller for the card's own trigger — a card in a
            # hand is its owner's (CR 400.3), so the two are one seat.
            seat=controller_index,
            owner_index=controller_index,
            event_subject_player=controller_index,
            cycled_card=card,
        )

    def _activate_from_graveyard(
        self,
        controller_index: int,
        card_name: str,
        ability_index: int = 0,
        graveyard_index: int | None = None,
        cost_permanent_id: int | None = None,
        # "Tap three untapped Clerics you control: Return this card from your
        # graveyard to your hand." (Gangrenous Goliath.) Which permanents pay a
        # several-permanent cost, by id — the battlefield door's spelling.
        cost_permanent_ids: "list[int] | None" = None,
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
        # …and a card in a graveyard by its place in the pile, each zone its
        # own keyword (``engine/target_keywords``).
        target_graveyard_indices: "list[int] | None" = None,
        # "{1}{B}, **Discard a card**: Return this card from your graveyard to
        # your hand." (Undead Gladiator.) Which cards in hand pay a discard
        # cost, by hand position — the battlefield door's spelling
        # (``_named_discard_positions``); None is the deterministic pick.
        cost_hand_index: int | None = None,
        cost_other_hand_indices: "list[int] | None" = None,
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

        **The cost shapes it charges, and any other is refused rather than
        waived.** Mana (Ashen Ghoul's {B}), a counted sacrifice named by a
        printed noun phrase (Whiteout's "Sacrifice a snow land", Coffin
        Puppets' "Sacrifice two lands"), a tap of other permanents (Gangrenous
        Goliath) and a discard from the hand (Undead Gladiator's "Discard a
        card"). A cost this cannot charge makes the ability unactivatable (CR
        602.5c) -- the alternative is an ability activated for free, which is
        the silent direction. Coffin Puppets and Undead Gladiator were
        supported cards whose ability this door refused for anyone until the
        kg3 round: the sacrifice was one permanent only, and a discard was on
        the deny list.
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
            return refuse(card_name, "unsupported", details)
        index = matches[0]
        card = controller.graveyard[index]

        program = compile_card_oracle(card)
        if not 0 <= ability_index < len(program.activated_abilities):
            details = f"{card.name} has no ability {ability_index}"
            return refuse(card.name, "unsupported", details)
        ability = program.activated_abilities[ability_index]
        if not ability.supported or ability.instruction is None:
            details = f"{card.name}: ability not implemented"
            return refuse(card.name, "unsupported", details)
        if ability_functions_from(ability) != GRAVEYARD:
            details = (
                f"{card.name}'s ability does not function from a graveyard "
                "(CR 113.6)"
            )
            return refuse(card.name, "unsupported", details)

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
            return refuse(
                card.name, "unsupported", prohibited.details,
            )

        # CR 602.2b sends an activation through CR 601.2c, so the target is
        # checked **before** any cost is paid and against the same
        # ``_enumerate_targets`` list the picker is handed. Read here for the
        # reason the permanent path reads it there: an ability with a mandatory
        # object target it cannot fill is refused with nothing spent, rather
        # than activated to no effect — and on this card "nothing spent" also
        # means the card is not exiled out of the graveyard for free.
        # The target in its zone's keyword, turned into the slot the gates
        # read beside the ids, as the permanent door does.
        target_player_index, target_permanent_index, keyword_refusal = announced_slot(
            self, ability_target_zone(ability), name=card.name,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
            target_graveyard_indices=target_graveyard_indices,
        )
        if keyword_refusal is not None:
            return refuse(card.name, "unsupported", keyword_refusal)
        target_refusal = self.activation_target_refusal(
            controller_index, card, ability,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
        )
        if target_refusal is not None:
            return refuse(card.name, "unsupported", target_refusal)
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
        # …and CR 602.2b under a requirement an opponent's permanent prints
        # about the announcement ("…must choose at least one Flagbearer on the
        # battlefield if able", Standard Bearer), asked of the whole
        # announcement once the default above has named what it would, and
        # before any cost is paid — the permanent path's gate
        # (``activation_checks``), which this door never asked: with it off, a
        # Carrionette naming a Hill Giant past an opposing bearer was accepted
        # and paid for (``tests/ui/test_kg_client_graveyard_targets.py``).
        required_refusal = self.activation_target_requirement_refusal(
            controller_index, card, ability,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
        )
        if required_refusal is not None:
            return refuse(card.name, "unsupported", required_refusal)

        cost = ability.cost
        unchargeable = _graveyard_cost_refusal(cost)
        if unchargeable is not None:
            details = f"{card.name}: {unchargeable}"
            return refuse(card.name, "unsupported", details)

        # CR 601.2h/602.5c: the whole cost is checked before any of it is spent,
        # so an ability with an unpayable half does not pay the other half.
        sacrifice_victims: list = []
        if cost.sacrifice_filter is not None:
            candidates = [
                perm
                for perm in self.controlled_by(controller_index)
                if subject_matches(
                    self, perm, cost.sacrifice_filter, observer=controller_index,
                )
            ]
            # "Sacrifice **two** lands" (Coffin Puppets): one land is no more
            # a payment than none (CR 601.2h).
            wanted = int(cost.sacrifice_count)
            if len(candidates) < wanted:
                noun = filter_head_noun(cost.sacrifice_filter)
                details = (
                    f"{card.name}: no {noun} available to sacrifice"
                    if not candidates else
                    f"{card.name}: not enough {noun}s to sacrifice for its cost"
                )
                return refuse(card.name, "unsupported", details)
            # The same announcement an ability on the battlefield makes, so the
            # same check: a permanent named to pay that cannot is a refusal,
            # not a request for the default (CR 601.2h). Several are named by
            # ``cost_permanent_ids`` where the cost taps nothing (the tap
            # cost's channel otherwise).
            named_ids = (
                [cost_permanent_id] if cost_permanent_id is not None else []
            ) + (
                list(cost_permanent_ids or ())
                if wanted > 1 and not cost.tap_count else []
            )
            named_cost_refusal = self._named_cost_refusal(
                card, controller, candidates, named_ids or None, None,
            )
            if named_cost_refusal is not None:
                return refuse(
                    card.name, "unsupported", named_cost_refusal,
                )
            # The payer's named permanents first, then the deterministic pick
            # for the rest — the one rule every unnamed sacrifice takes
            # (``sacrifice_preference_key``: a permanent whose death loses the
            # game last, then the smallest).
            for found in (self.permanent_by_id(pid) for pid in named_ids):
                if (
                    found is not None and len(sacrifice_victims) < wanted
                    and any(perm is found for perm in candidates)
                    and not any(perm is found for perm in sacrifice_victims)
                ):
                    sacrifice_victims.append(found)
            for perm in sorted(candidates, key=self.sacrifice_preference_key):
                if len(sacrifice_victims) >= wanted:
                    break
                if not any(perm is chosen for chosen in sacrifice_victims):
                    sacrifice_victims.append(perm)

        # "{1}{B}, **Discard a card**: Return this card from your graveyard to
        # your hand." (Undead Gladiator.) The cards in hand the printed phrase
        # admits (``_discard_cost_payable``): the payer's named positions
        # first, then the payable cards in hand order — the battlefield door's
        # default — resolved to cards before anything leaves the hand.
        discard_cost_cards: list = []
        if cost.discard_cards:
            hand = controller.hand
            if len(self._discard_cost_payable(cost, controller)) < cost.discard_cards:
                details = (
                    f"{card.name}: not enough cards in hand to discard for its cost"
                )
                return refuse(card.name, "unsupported", details)
            named, denial = _named_discard_positions(
                hand, cost, cost_hand_index, cost_other_hand_indices,
                game=self, owner=controller,
            )
            if denial is not None:
                return refuse(card.name, "unsupported", f"{card.name}: {denial}")
            positions = named + [
                index for index, held in enumerate(hand)
                if index not in named and card_matches_any(
                    held, cost.discard_filters, game=self, owner=controller,
                )
            ]
            discard_cost_cards = [
                hand[index] for index in positions[:cost.discard_cards]
            ]

        # "**Tap three untapped Clerics you control**: Return this card from
        # your graveyard to your hand." (Gangrenous Goliath.) The permanents
        # tapped are on the battlefield and the source is not, which is
        # nothing CR 602 minds: the cost is an action the controller performs
        # (CR 118.3) on permanents they control, and the card in the pile is
        # never among them. Chosen before any mana is spent and tapped after,
        # with the battlefield door's chooser — so an Elf that became a Cleric
        # pays, and a Wizard named in error is a refusal rather than the
        # default (CR 601.2h).
        tap_cost_permanents: list = []
        if cost.tap_count:
            candidates = self._tap_cost_candidates(cost, controller_index)
            if len(candidates) < cost.tap_count:
                details = (
                    f"{card.name}: not enough untapped "
                    f"{filter_head_noun(cost.tap_filter or {})}s to tap for its cost"
                )
                return refuse(card.name, "unsupported", details)
            named_cost_refusal = self._named_cost_refusal(
                card, controller, candidates, cost_permanent_ids, None,
            )
            if named_cost_refusal is not None:
                return refuse(
                    card.name, "unsupported", named_cost_refusal,
                )
            tap_cost_permanents = self._choose_tap_cost_permanents(
                cost, candidates, cost_permanent_ids,
            )

        if self.enforce_mana_costs and not self._pay_mana_cost(
            controller, cost.mana, purpose=PaymentPurpose(ACTIVATE, source=card),
        ):
            details = f"{controller.name} cannot pay for {card.name}'s ability"
            return refuse(card.name, "unsupported", details)
        for tapped_for_cost in tap_cost_permanents:
            self.become_tapped(tapped_for_cost)
        if tap_cost_permanents:
            self.log.append(
                f"{card.name}: tapped "
                + ", ".join(p.card.name for p in tap_cost_permanents)
                + " to pay its cost"
            )
        # One cost, one event (CR 603.10a, ``leaving_together``).
        with self.leaving_together():
            for sacrifice_victim in sacrifice_victims:
                self.sacrifice_permanent(sacrifice_victim)
                self.log.append(
                    f"{controller.name} sacrificed {sacrifice_victim.card.name} "
                    f"to activate {card.name}"
                )
        for discarded in discard_cost_cards:
            # Out of the hand by identity (one copy), then discarded — the
            # battlefield door's two lines (``take_card_from_hand``).
            self.take_card_from_hand(controller, discarded)
            self._discard_card(controller, discarded, as_cost=True)
            self.log.append(
                f"{controller.name} discarded {discarded.name} to activate {card.name}"
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
                target_permanent_index=as_target_slots(target_permanent_index),
                target_permanent_id=as_target_ids(target_permanent_ids),
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
