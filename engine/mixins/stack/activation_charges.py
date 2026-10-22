"""Collecting an activated ability's cost (CR 601.2h through CR 602.2b): the
payers chosen, and the payment.

Two steps of ``_activate_onto_stack``, on either side of the mana payment
that is its hinge. ``_choose_activation_cost_payers`` picks what pays every
part of the cost that is not mana, from the candidate lists
``activation_payment`` counts, the payer's named choices first, and refuses a
named payer that cannot pay. ``_pay_activation_costs`` pays all of it at one
moment once the mana is spent, and refuses nothing; the chosen exile is paid
through ``_pay_exile_cost``.

Split out of ``activation.py`` at the 2,000-line cap, and composed onto
``Game`` with the other parts of ``AbilityActivationMixin``; each step is
moved out of ``_activate_onto_stack`` whole and called from it in its order.
"""

from __future__ import annotations

import random
from types import SimpleNamespace

from ...activation_tallies import (
    mark_activated_this_turn, mark_once_only_activation,
    prints_once_only_restriction, reads_activation_tally,
)
from ...cost_tap_records import record_tapped_to_pay
from ...events import emit
from ...game_types import SimulationResult
from ...subject_filters import (
    card_matches_any, filter_head_noun, subject_matches,
)
from ...targeting import graveyard_target_spec
from .activation_payment import COST_PERFORMING_KINDS, activation_cost_choice


def _named_discard_positions(
    hand: list, cost, first: int | None, others: "list[int] | None"
) -> "tuple[list[int], str | None]":
    """The hand positions the payer named for a "Discard N cards" cost, or why
    the naming is refused (CR 602.2b through CR 601.2b).

    *first* is ``cost_hand_index`` and *others* ``cost_other_hand_indices`` —
    the first card and the rest, the shape the cast side's "and another card"
    (Foil, ``alternative_cost_other_hand_indices``) already announces on. A
    named position that cannot pay — off the end of the hand, a card the
    printed phrase does not name, one named twice, or more cards than the cost
    takes — is a refusal with nothing spent, never a slide onto a neighbour.
    Naming fewer than the cost takes is not: the rest are the deterministic
    pick, which is what keeps a seat that names nothing (AI, headless) paying
    exactly what it always did.
    """
    named = ([first] if isinstance(first, int) else []) + list(others or ())
    if not named:
        return [], None
    if len(set(named)) != len(named) or len(named) > cost.discard_cards:
        return [], (
            f"its cost discards {cost.discard_cards} card(s), each named once"
        )
    for position in named:
        if not (isinstance(position, int) and 0 <= position < len(hand)):
            return [], (
                f"no card at hand position {position} to discard for its cost"
            )
        if not card_matches_any(hand[position], cost.discard_filters):
            return [], (
                f"{hand[position].name} does not answer its discard cost"
            )
    return named, None


class ActivationChargesMixin:
    def _choose_activation_cost_payers(
        self, *, ability, announced_target_idx, controller, controller_index,
        cost_graveyard_indices, cost_hand_index, cost_other_hand_indices,
        cost_permanent_ids, cost_permanent_index, counters_removed_for_cost,
        permanent, target_permanent_index, target_role_refs, x_value,
    ):
        """What pays each part of the cost that is not mana (CR 601.2h's
        choices, through CR 602.2b).

        The discarded cards, the life or the mana of a printed "or", the
        sacrificed, tapped, returned, untapped and counter-bearing permanents,
        and the chosen exile — each picked from the candidate list the gate
        counted, the payer's named choices first, and none of it paid yet. A
        permanent the payer named that no list holds is refused rather than
        paid with something else (``_named_cost_refusal``).

        A step of ``_activate_onto_stack``, moved out of it whole and called
        from it in its place: "above" and "below" in its comments are places in
        the activation as that method runs it.

        Returns the refusal, or ``(alternative_mana, cost_hand_index,
        counter_cost_permanent, counter_removal_permanent,
        counters_removed_for_cost, discard_cost_card, discard_cost_cards,
        exile_cost_choice, exiled_for_cost, exiled_set_for_cost,
        graveyard_target_before_cost, graveyard_target_stamp_after_cost,
        life_owed, return_cost_permanents, sacrifice_also_permanent,
        sacrifice_attached_permanent, sacrifice_cost_permanent,
        sacrifice_cost_set, sacrificed_for_cost, tap_cost_permanents,
        untap_cost_permanent)``.
        """
        # Jandor's Ring: "Discard the last card you drew this turn" is an
        # additional cost — the card the gate above found still in hand,
        # discarded below once every cost has been cleared.
        discard_cost_card = None
        if ability.cost.discard_last_drawn:
            discard_cost_card = controller.last_card_drawn_this_turn()

        # "Discard a card" (Seasoned Hallowblade). Resolved to card objects,
        # not indices: the indices shift as each card leaves the hand.
        discard_cost_cards: list = []
        if ability.cost.discard_cards:
            hand = controller.hand
            # "Discard a **land card or Shrine card**" (Sanctum of Shattered
            # Heights): the payment is drawn from the cards the printed phrase
            # names, not from the hand. Matched through the same reader the
            # picker in `engine/legality.py` offers from, so what is offered and
            # what is accepted cannot disagree — and an empty filter list means
            # the unrestricted "Discard a card", where the whole hand pays.
            # Too few of them is the gate's refusal above.
            payable = self._discard_cost_payable(ability.cost, controller)
            # An index that names no card is an error, not a request for a
            # different one. It used to become a bare `0`, so a stale click
            # discarded the first card in hand — the same silent repointing the
            # cast side did, and the reason both now refuse instead. Naming
            # nothing at all is still the deterministic default.
            #
            # A named card that does not answer the phrase is the same error, not
            # a cheaper cost: it is refused rather than quietly slid onto a legal
            # one, so a stale click cannot discard the land the player meant to
            # keep.
            # "Discard a card **at random**" (Coral Helm). The payer names
            # nothing — a cost the payer picks is a strictly better cost than
            # one chance picks, which is the whole difference between this card
            # and one that says "discard a card". Any index a caller sent is
            # ignored rather than honoured, because honouring it would hand the
            # choice back.
            #
            # Through the module RNG, like every other randomiser here, so a
            # seeded run reproduces the discard (the determinism invariant).
            if ability.cost.discard_at_random:
                discard_cost_cards = random.sample(
                    payable, min(ability.cost.discard_cards, len(payable))
                )
                cost_hand_index = None
            elif cost_hand_index is not None and (
                not 0 <= cost_hand_index < len(hand)
                or hand[cost_hand_index] not in payable
            ):
                details = (
                    f"{permanent.card.name}: no card at hand position "
                    f"{cost_hand_index} to discard for its cost"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            if not ability.cost.discard_at_random:
                # Collected by **hand position**, never by identity: a deck
                # repeats one immutable definition per copy, so two Grizzly
                # Bears in a hand are the same object and an `is not named`
                # test skipped the second — "Discard two cards" (the Prophecy
                # spellshapers) out of a hand of two Bears collected one card
                # and was activated for half its price. The named positions
                # first, then the payable positions in hand order.
                #
                # "Discard **two** cards" is two choices, and CR 602.2b gives
                # the payer both: ``cost_hand_index`` names the first and
                # ``cost_other_hand_indices`` the rest — the shape the cast
                # side's "and another card" (Foil) already announces on, so the
                # second card is the player's rather than the default's.
                named, denial = _named_discard_positions(
                    hand, ability.cost, cost_hand_index, cost_other_hand_indices
                )
                if denial is not None:
                    details = f"{permanent.card.name}: {denial}"
                    self.log.append(details)
                    return SimulationResult(
                        permanent.card.name, False, "unsupported", details
                    )
                positions = named + [
                    i for i, held in enumerate(hand)
                    if i not in named
                    and card_matches_any(held, ability.cost.discard_filters)
                ]
                discard_cost_cards = [
                    hand[i] for i in positions[:ability.cost.discard_cards]
                ]

        # "Exile the top card of your library" (Royal Herbalist), "…the top
        # creature card of your graveyard" (Necratog), "Put a card from your
        # hand on top of your library" (Hidden Retreat), "Mill a card"
        # (Millikin), "Pay 3 life" (Tavern Swindler): CR 118.3's shortfalls,
        # each refused by the cost gate above with nothing spent, and each paid
        # below with the rest. "Discard your hand" (Subira) is never unpayable.
        #
        # CR 601.2h's choice between two printed payments ("Pay 2 life or
        # {2}"), made once here and carried to both payment sites below: asked
        # separately they could disagree, and the disagreement that costs
        # nothing to make is paying the mana *and* the life.
        life_owed, alternative_mana = activation_cost_choice(
            controller, ability.cost, permanent
        )

        # "Sacrifice another creature" (Hobblefiend) / "Sacrifice a creature with
        # defender" (Portcullis Vine). The victim is chosen by identity and never
        # by index — an index held across the removals below names whichever
        # permanent slid into the slot — and "another" excludes the source
        # itself, so a lone Hobblefiend has no legal payment and cannot activate
        # at all. That exclusion is `exclude_self` inside the filter, which is
        # why the source is handed to the matcher rather than tested here.
        # **Every permanent a chosen cost of this ability could be paid with**,
        # gathered as each block below builds its own candidate list, for the
        # one check beneath them (``_named_cost_refusal``): a permanent the
        # payer *named* that is in none of these lists is an announcement that
        # cannot be paid (CR 601.2h through CR 602.2b), and the activation is
        # refused rather than paid with something else.
        cost_candidates: list = []
        sacrifice_cost_permanent = None
        sacrifice_cost_set: list = []
        if (
            ability.cost.sacrifice_count == "x"
            and ability.cost.sacrifice_filter is not None
        ):
            # "{T}, Sacrifice **X** lands: Put X +1/+1 counters on this
            # creature." (Copper-Leaf Angel.) CR 107.3a's announced X sizes the
            # payment, so — as for "Remove X counters" above — an X the board
            # cannot cover is an announcement that cannot be paid (CR 601.2h)
            # and is refused with nothing spent (the cost gate above), never
            # clamped to what is there. A seat that announced nothing announced
            # zero, which is payable and sacrifices nothing. The payer's named
            # permanents first, then the board in order, deduplicated by
            # identity.
            wanted = max(0, int(x_value or 0))
            candidates = self._sacrifice_cost_candidates(
                ability.cost, controller_index, permanent, keep_source=True,
            )
            cost_candidates.extend(candidates)
            named = [
                found for found in (
                    self.permanent_by_id(pid) for pid in (cost_permanent_ids or [])
                )
                if found is not None and any(c is found for c in candidates)
            ]
            for perm in [*named, *candidates]:
                if len(sacrifice_cost_set) >= wanted:
                    break
                if not any(perm is already for already in sacrifice_cost_set):
                    sacrifice_cost_set.append(perm)
        elif (
            ability.cost.sacrifice_count == "any"
            and ability.cost.sacrifice_filter is not None
        ):
            # "Sacrifice this artifact **and any number of creatures you
            # control**" (Sword of the Ages). The payer names the set as the
            # ability is activated (CR 601.2b) — through `cost_permanent_ids`,
            # the same channel every other chosen cost permanent arrives on —
            # and naming none is a legal payment, because zero is a number. So
            # there is no default pick here: unlike a "sacrifice a creature"
            # cost, which must eat something or the ability is unactivatable,
            # this one has a legal answer that costs nothing, and choosing
            # creatures for a seat that named none would sacrifice a board to
            # pay a cost of zero.
            described = ability.cost.sacrifice_filter
            cost_candidates.extend(
                perm for perm in self.controlled_by(controller_index)
                if perm is not permanent and subject_matches(
                    self, perm, described,
                    observer=controller_index, source=permanent,
                )
            )
            for permanent_id in cost_permanent_ids or []:
                found = self.permanent_by_id(permanent_id)
                if (
                    found is not None
                    and found is not permanent
                    and self.controls(controller_index, found)
                    and subject_matches(
                        self, found, described,
                        observer=controller_index, source=permanent,
                    )
                    and not any(found is already for already in sacrifice_cost_set)
                ):
                    sacrifice_cost_set.append(found)
        elif ability.cost.sacrifice_filter is not None and ability.instruction is not None and (
            ability.instruction.kind not in COST_PERFORMING_KINDS
        ):
            # "Sacrifice two lands **and this artifact**" (Sandstone
            # Deadfall): the source is its own entry in the printed cost, so
            # it is not one of the chosen ones (``_sacrifice_cost_candidates``).
            # "Sacrifice **two** Goblins" (Goblin Warrens): one Goblin is no
            # more a payment than none (CR 601.2h) — the cost gate above
            # refused a board short of the printed count, with nothing spent.
            candidates = self._sacrifice_cost_candidates(
                ability.cost, controller_index, permanent,
            )
            wanted = ability.cost.sacrifice_count
            wanted = wanted if isinstance(wanted, int) else 1
            cost_candidates.extend(candidates)
            named = [
                found
                for found in (
                    self.permanent_by_id(pid) for pid in (cost_permanent_ids or [])
                )
                if found is not None and any(c is found for c in candidates)
            ]
            # Through the seam, which bounds-checks and turns an index arriving
            # from the wire into a permanent exactly once.
            named_permanent = (
                self.permanent_at(controller, cost_permanent_index)
                if isinstance(cost_permanent_index, int)
                else None
            )
            if any(perm is named_permanent for perm in candidates) and not any(
                perm is named_permanent for perm in named
            ):
                named = [named_permanent, *named]
            if wanted > 1:
                # The payer's own picks first, then the deterministic default
                # for the rest — the same arrangement the tap cost below makes,
                # so a seat that names none is never blocked and a seat that
                # names some has them honoured.
                chosen_victims: list = []
                for perm in [*named, *candidates]:
                    if len(chosen_victims) >= wanted:
                        break
                    if not any(perm is already for already in chosen_victims):
                        chosen_victims.append(perm)
                sacrifice_cost_set = chosen_victims
            else:
                # `in` compares Permanents by value and would match a look-alike, so
                # membership is tested by identity.
                sacrifice_cost_permanent = (
                    named_permanent
                    if any(perm is named_permanent for perm in candidates)
                    # An id names the victim as well as an index does — the wire
                    # carries both — so a seat that named one is honoured rather
                    # than given the deterministic default. The index channel
                    # keeps precedence, because that is the one the sacrifice
                    # picker has always answered on.
                    else named[0] if named
                    # A permanent whose death loses the game is kept for last, then
                    # the smallest — one rule, shared with the cast-side additional
                    # cost and the forced-sacrifice default (`default_sacrifice_pick`).
                    else self.default_sacrifice_pick(candidates)
                )

        # "**Sacrifice enchanted creature**: …" (Betrothed of Fire). The host,
        # collected here with every other cost and paid below in one payment
        # moment (CR 601.2h). Nothing is picked — the attachment record is the
        # whole answer, exactly as it is for the tap-the-host cost further down
        # — so the only two ways this can fail are the Aura having no host and
        # the host having left, and both are the cost gate's refusal above —
        # nothing paid (CR 602.2b), never the Aura sacrificed instead.
        #
        # Its own variable rather than a second writer of
        # ``sacrifice_cost_permanent``: a card printing both clauses owes two
        # sacrifices, and sharing the field would pay one and drop the other
        # silently.
        sacrifice_attached_permanent = None
        if ability.cost.sacrifice_attached:
            sacrifice_attached_permanent = permanent.metadata.get("attached_to")

        # What "**the sacrificed creature**" names once the cost is paid
        # (CR 608.2h). The permanent the payer chose, or — when the cost names
        # no choice at all — the host an Aura ate: "{R}, Sacrifice enchanted
        # creature: This Aura deals damage equal to **the sacrificed creature's
        # power** to each creature." (Bloodfire Infusion.) The host was paid
        # and never recorded, so the effect read an empty channel and dealt 0
        # with the card reporting supported. One record, because one phrase
        # reads it; a card printing both sacrifices would name the chosen one.
        sacrificed_for_cost = (
            sacrifice_cost_permanent if sacrifice_cost_permanent is not None
            else sacrifice_attached_permanent
        )

        # "Tap two untapped Spirits you control" (Shacklegeist). Chosen by the
        # payer through `cost_permanent_ids`, and defaulted deterministically for
        # a seat that names none — the same arrangement the sacrifice cost above
        # makes, and for the same reason: a cost is paid during activation, so a
        # queued prompt would put the ability on the stack before it was
        # collected.
        tap_cost_permanents: list = []
        if ability.cost.tap_count:
            # Untapped by construction — a tap cost can only be paid with a
            # permanent that is not already tapped — and the source is eligible
            # only if the printed phrase names it, which "another" would have
            # excluded. Too few of them is the cost gate's refusal above.
            candidates = self._tap_cost_candidates(ability.cost, controller_index)
            cost_candidates.extend(candidates)
            named = [
                found
                for found in (
                    self.permanent_by_id(pid) for pid in (cost_permanent_ids or [])
                )
                if found is not None and any(c is found for c in candidates)
            ]
            # Deduplicated by identity: two references to one permanent do not
            # pay a two-permanent cost.
            chosen: list = []
            for perm in named:
                if not any(perm is already for already in chosen):
                    chosen.append(perm)
            for perm in candidates:
                if len(chosen) >= ability.cost.tap_count:
                    break
                if not any(perm is already for already in chosen):
                    chosen.append(perm)
            tap_cost_permanents = chosen[:ability.cost.tap_count]

        # "**Return a Forest you control to its owner's hand**: Untap target
        # creature" (Quirion Ranger); "{U}{U}, **Return two Islands you control
        # to their owner's hand**: …" (Flooded Shoreline). The same collection
        # the tap cost above makes, one zone over (CR 118.3): chosen by the
        # payer through `cost_permanent_ids`, defaulted deterministically for a
        # seat that names none, and refused with nothing spent by the cost gate
        # above when the board cannot cover the printed count (CR 601.2h via
        # 602.2b).
        #
        # The printed count is indivisible, which is why the shortfall refuses
        # rather than returning what there is: returning one of Flooded
        # Shoreline's two Islands is not paying its cost, and an ability
        # activated for part of its price is the failure that neither crashes
        # nor goes missing.
        return_cost_permanents: list = []
        if ability.cost.return_to_hand_count:
            candidates = self._return_cost_candidates(ability.cost, controller_index)
            cost_candidates.extend(candidates)
            named = [
                found
                for found in (
                    self.permanent_by_id(pid) for pid in (cost_permanent_ids or [])
                )
                if found is not None and any(c is found for c in candidates)
            ]
            # Deduplicated by identity, for the tap cost's reason: two
            # references to one permanent do not pay a two-permanent cost.
            chosen = []
            for perm in named:
                if not any(perm is already for already in chosen):
                    chosen.append(perm)
            for perm in candidates:
                if len(chosen) >= ability.cost.return_to_hand_count:
                    break
                if not any(perm is already for already in chosen):
                    chosen.append(perm)
            return_cost_permanents = chosen[:ability.cost.return_to_hand_count]

        # "{T}, **Untap a tapped land an opponent controls**: …" (Benthic
        # Explorers). CR 602.1a: a cost is any action, and this is the one this
        # engine charges that is performed on a permanent the payer does **not**
        # control — so the candidates come off `all_permanents` rather than
        # `controlled_by`, and the printed seat clause is what narrows them.
        # Chosen through `cost_permanent_ids` like the sacrifice and tap costs
        # above, and defaulted deterministically for a seat that names none.
        untap_cost_permanent = None
        if ability.cost.untap_filter is not None:
            # Tapped by construction: untapping an untapped permanent is no
            # payment, and the printed phrase says so too — the filter carries
            # `tapped_only`, and the candidate list is the belt to its braces.
            # None at all is the cost gate's refusal above.
            candidates = self._untap_cost_candidates(
                ability.cost, controller_index, permanent,
            )
            cost_candidates.extend(candidates)
            named = next(
                (
                    found
                    for pid in (cost_permanent_ids or [])
                    for found in [self.permanent_by_id(pid)]
                    if found is not None and any(c is found for c in candidates)
                ),
                None,
            )
            untap_cost_permanent = named or candidates[0]

        # "{B}, **Put a -1/-1 counter on a creature you control**: …"
        # (Wandering Mage). The one counter-placing cost that can be *unpayable*
        # — CR 601.2h, and a payer with no creature has nowhere to put it — so
        # unlike Mazemind Tome's marker on its own source this is collected here
        # with the other chosen costs, and a board with nowhere to put it is the
        # cost gate's refusal above. Picked through `cost_permanent_ids`, the
        # same channel the
        # sacrifice and tap costs above arrive on, and defaulted with
        # `default_sacrifice_pick` for a seat that names none: a -1/-1 counter
        # is a shrinking, so "the one you would give up" is the same ranking.
        counter_cost_permanent = None
        if ability.cost.put_counter_filter is not None:
            candidates = self._put_counter_cost_candidates(
                ability.cost, controller_index, permanent,
            )
            cost_candidates.extend(candidates)
            named = [
                found
                for found in (
                    self.permanent_by_id(pid) for pid in (cost_permanent_ids or [])
                )
                if found is not None and any(c is found for c in candidates)
            ]
            counter_cost_permanent = (
                named[0] if named else self.default_sacrifice_pick(candidates)
            )

        # "{2}, **Remove a +1/+1 counter from a creature you control**: …"
        # (Spike Rogue). The exact mirror of the block above — the same chosen
        # noun phrase, the same `cost_permanent_ids` channel — and unpayable in
        # one more way than the placing twin is: the permanent must not merely
        # match the phrase, it must be *holding* the counters (CR 601.2h). A
        # candidate list that ignored the counters would refuse the activation
        # further down with the mana already spent, or pay nothing at all.
        #
        # The default pick is deliberately **not** `default_sacrifice_pick`: the
        # permanent this cost touches is not given up, it is shrunk by one
        # counter, and the honest default is the one with the most to spare —
        # the seat's own answer is what `cost_permanent_ids` carries when there
        # is one.
        counter_removal_permanent = None
        if ability.cost.remove_counter_filter is not None:
            from ...named_counters import counters_on

            kind = ability.cost.remove_counter
            wanted = ability.cost.remove_counter_count
            needed = int(wanted) if isinstance(wanted, int) else 1
            # None holding them is the cost gate's refusal above.
            candidates = self._remove_counter_cost_candidates(
                ability.cost, controller_index, permanent,
            )
            cost_candidates.extend(candidates)
            named = [
                found
                for found in (
                    self.permanent_by_id(pid) for pid in (cost_permanent_ids or [])
                )
                if found is not None and any(c is found for c in candidates)
            ]
            counter_removal_permanent = (
                named[0] if named
                else max(candidates, key=lambda perm: counters_on(perm, str(kind)))
            )
            counters_removed_for_cost = needed

        # "{T}, Sacrifice a creature **and a Swamp**: …" (Viscerid Drone). The
        # second object a conjoined sacrifice names, collected here rather than
        # in the branch above because it is a *different* noun phrase with its
        # own candidate list — and CR 601.2h makes the whole cost unpayable if
        # either half is, so a board with a creature and no Swamp refuses with
        # nothing sacrificed.
        #
        # The two permanents must be distinct: a creature Swamp (an animated
        # land) answers both phrases, and letting it pay both would collect one
        # card for a cost the card prints as two.
        sacrifice_also_permanent = None
        if ability.cost.sacrifice_also_filter is not None:
            described = ability.cost.sacrifice_also_filter
            # The cost gate above asked this of the default first pick; a
            # *named* first sacrifice can still be the only second one there
            # is, which is a named payment this refusal is about.
            candidates = self._sacrifice_also_candidates(
                ability.cost, controller_index, permanent, sacrifice_cost_permanent,
            )
            if not candidates:
                details = (
                    f"{permanent.card.name}: no "
                    f"{filter_head_noun(described)} available to sacrifice"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            cost_candidates.extend(candidates)
            named = [
                found
                for found in (
                    self.permanent_by_id(pid) for pid in (cost_permanent_ids or [])
                )
                if found is not None and any(c is found for c in candidates)
            ]
            sacrifice_also_permanent = (
                named[-1] if named else self.default_sacrifice_pick(candidates)
            )

        # "**Tap enchanted land**: …" (Earthlore). The host, collected beside
        # the picked tap cost above and paid with it below — one payment moment
        # (CR 601.2h). Nothing is picked: the attachment record is the whole
        # answer, so the only way this can fail is the Aura having no host or a
        # host already tapped, and both are the cost gate's refusal above —
        # nothing paid (CR 602.2b), never the Aura tapped for nothing.
        if ability.cost.tap_attached:
            tap_cost_permanents = [
                *tap_cost_permanents, permanent.metadata.get("attached_to"),
            ]

        # "Exile a creature you control" (City of Shadows) / "Exile a creature
        # card from your graveyard" (Necropolis) — a *chosen* object rather than
        # the source. **A cost is not a target** (CR 601.2b, idiom 10), so
        # nothing here consults shroud or protection; what it consults is the
        # printed noun phrase, through the same reader the picker uses.
        #
        # **Chosen here, paid below the mana payment** — the shape every other
        # chosen cost in this function has, and the one this block did not.
        # It used to exile at this point, above five refusals (the attached
        # host's mana cost, a card-defined X, Drought's sacrifice tax, the mana
        # payment, and the {T} checks then beneath it), so Soul Shepherd
        # activated with an empty pool was refused with the creature card
        # already out of its graveyard, and an already-tapped City of Shadows
        # exiled a creature for an activation that never happened (CR 601.2h
        # via 602.2b; CR 733.1 reverses an illegal activation). The choice is
        # resolved to objects now, while the zone still reads the way the
        # payer saw it, and nothing between here and the payment moves a card.
        # It still runs ahead of the source's own exile further down, so a card
        # printing both eats the chosen object while the source is still there.
        exiled_for_cost = None
        exiled_set_for_cost: list = []
        exile_cost_choice = None
        # **A graveyard target is a slot, and a graveyard cost renumbers it.**
        # "{2}{B}{B}, {T}, Exile two cards from your graveyard: Return target
        # creature card from your graveyard to your hand." (Cabal Surgeon.)
        # CR 601.2c names the target before CR 601.2h pays the cost, but the
        # stack object's graveyard stamp (``_stamp_stack_targets``) is taken
        # as it is pushed — after this cost has taken cards out of the very
        # pile the slot counts into. Exiling the two cards above the target
        # moved it two slots, and the ability returned whatever card slid into
        # the slot it had named (a Hill Giant for a Grizzly Bears). So the card
        # is named here, while the slot still means what the activator chose,
        # and re-located below once the cost is paid.
        graveyard_target_before_cost = None
        graveyard_target_stamp_after_cost = None
        if (
            ability.cost.exile_filter is not None
            and ability.cost.exile_zone == "graveyard"
            and not target_role_refs
            and isinstance(target_permanent_index, int)
        ):
            target_spec = graveyard_target_spec(
                permanent.card, None, instruction=ability.instruction,
            )
            if target_spec is not None:
                graveyard_target_before_cost = self.graveyard_target_at(
                    self.graveyard_target_seat(
                        SimpleNamespace(
                            caster_index=controller_index,
                            target_player_index=announced_target_idx,
                        ),
                        target_spec,
                    ),
                    target_permanent_index,
                )
        # Which list ``cost_permanent_index`` counts into. A battlefield slot
        # for every cost above; a slot in a hand or a graveyard for an exile
        # cost paid out of one, which the check below must not read as a
        # permanent.
        cost_index_is_a_pile_slot = (
            ability.cost.exile_filter is not None
            and ability.cost.exile_zone in ("hand", "graveyard")
        )
        if ability.cost.exile_filter is not None:
            if not cost_index_is_a_pile_slot:
                cost_candidates.extend(
                    self._exile_cost_candidates(
                        ability.cost, controller_index, permanent
                    )
                )
            named_slot_refusal = self._named_exile_slot_refusal(
                ability.cost, controller,
                cost_hand_index
                if ability.cost.exile_zone == "hand" and isinstance(cost_hand_index, int)
                else cost_permanent_index,
                named_slots=cost_graveyard_indices,
            )
            if named_slot_refusal is not None:
                details = f"{permanent.card.name}: {named_slot_refusal}"
                self.log.append(details)
                return SimulationResult(
                    permanent.card.name, False, "unsupported", details
                )
        named_cost_refusal = self._named_cost_refusal(
            permanent, controller, cost_candidates, cost_permanent_ids,
            None if cost_index_is_a_pile_slot else cost_permanent_index,
        )
        if named_cost_refusal is not None:
            self.log.append(named_cost_refusal)
            return SimulationResult(
                permanent.card.name, False, "unsupported", named_cost_refusal
            )
        if ability.cost.exile_filter is not None:
            from ...ai_valuation import reads_what_its_cost_exiled

            exile_cost_choice = self._choose_exile_cost(
                ability.cost, controller, controller_index, permanent,
                # A card from hand (Cadaverous Bloom) is named where every
                # other hand-card cost is — ``cost_hand_index``, which its
                # picker answers on since PCY W3G5 — and the slot channel stays
                # the fallback a caller written before then still sends.
                cost_hand_index
                if ability.cost.exile_zone == "hand" and isinstance(cost_hand_index, int)
                else cost_permanent_index,
                cost_permanent_ids=cost_permanent_ids,
                cost_graveyard_indices=cost_graveyard_indices,
                spare_graveyard_slot=(
                    (graveyard_target_before_cost.seat, target_permanent_index)
                    if graveyard_target_before_cost is not None else None
                ),
                # A plain price unless the effect reads what was exiled
                # (Necropolis' "the exiled card's mana value").
                price=not reads_what_its_cost_exiled((ability.instruction,)),
            )
            if exile_cost_choice is None:
                details = (
                    f"{permanent.card.name}: nothing available to exile as a cost"
                )
                self.log.append(details)
                return SimulationResult(
                    permanent.card.name, False, "unsupported", details
                )
        return (
            alternative_mana, cost_hand_index, counter_cost_permanent,
            counter_removal_permanent, counters_removed_for_cost,
            discard_cost_card, discard_cost_cards, exile_cost_choice,
            exiled_for_cost, exiled_set_for_cost, graveyard_target_before_cost,
            graveyard_target_stamp_after_cost, life_owed,
            return_cost_permanents, sacrifice_also_permanent,
            sacrifice_attached_permanent, sacrifice_cost_permanent,
            sacrifice_cost_set, sacrificed_for_cost, tap_cost_permanents,
            untap_cost_permanent,
        )

    def _pay_activation_costs(
        self, *, ability, ability_lower, activation_caps, controller,
        controller_index, cost_hand_index, counter_cost_permanent,
        counter_removal_permanent, counters_removed_for_cost,
        discard_cost_card, discard_cost_cards, exile_cost_choice,
        exiled_for_cost, exiled_set_for_cost, graveyard_target_before_cost,
        graveyard_target_stamp_after_cost, life_owed, loyalty_delta, permanent,
        requires_tap, return_cost_permanents, sacrifice_also_permanent,
        sacrifice_attached_permanent, sacrifice_cost_permanent,
        sacrifice_cost_set, sacrifice_tax_victims, tap_cost_permanents,
        target_permanent_index, untap_cost_permanent,
    ):
        """Every cost but the mana, paid at one moment once the mana payment
        has gone through (CR 601.2h through CR 602.2b), so nothing here
        refuses.

        The chosen exile first, then the counters a cost removes, the {T}
        symbol and the spelled-out taps and untaps, the activation's tallies
        and its loyalty, the discards, the counters a cost puts, the life, the
        sacrifices, the graveyard and library exiles, the source's own exile,
        return or sacrifice, and the mill last.

        A step of ``_activate_onto_stack``, moved out of it whole and called
        from it in its place: "above" and "below" in its comments are places in
        the activation as that method runs it.

        Returns ``(exiled_for_cost, exiled_set_for_cost,
        graveyard_target_stamp_after_cost, milled_for_cost,
        target_permanent_index)``.
        """
        # The chosen exile (City of Shadows, Soul Shepherd, Cadaverous Bloom),
        # paid first among the rest so a card printing it beside the source's
        # own exile eats the chosen object while the source is still there.
        if exile_cost_choice is not None:
            exiled_set_for_cost = self._pay_exile_cost(
                exile_cost_choice, controller, controller_index, permanent
            )
            # The single-object channel every reader of an exile cost already
            # asks (Necropolis' "the exiled card's mana value"), kept as the
            # first of them, so a counted cost adds a record rather than moving
            # one.
            # Absent when "any number of" named none: the cost was paid and ate
            # nothing, and "the exiled card" then names nothing.
            exiled_for_cost = exiled_set_for_cost[0] if exiled_set_for_cost else None
            if graveyard_target_before_cost is not None:
                # The named card, found again in the pile the cost just
                # renumbered. Gone (the payer chose to exile it) is carried as
                # the stamp itself, which ``_stamp_stack_targets`` keeps when
                # the item names no slot — so CR 608.2b removes the ability as
                # it resolves rather than a handler scanning for a stand-in.
                relocated = self.graveyard_index_of(graveyard_target_before_cost)
                target_permanent_index = relocated
                if relocated is None:
                    graveyard_target_stamp_after_cost = graveyard_target_before_cost

        # The counter-removal cost, charged here rather than where it was
        # counted: every gate between the two can still refuse the activation,
        # and a refusal after the counters came off is a cost paid for nothing
        # (CR 602.2b). Through the one removal seam, so a cost that takes the
        # last counter off is the same event as an effect that does.
        #
        # **Below the last refusal, not merely below the counting.** It sat
        # above the mana payment and the {T} checks, so Ancient Hydra's "{1},
        # Remove a fade counter" activated with no mana was refused with the
        # counter already gone — one upkeep of the creature's life paid for
        # nothing. Nothing after this point refuses; the two {T} checks that
        # once sat between the mana and here now sit above every cost.
        # Reading the counters *before* this is also CR 601.2f's order: a cost
        # sized off the counters is determined before any cost is paid.
        if counters_removed_for_cost:
            from ...named_counters import remove_counters

            # The chosen permanent when the card named one (Spike Rogue), and
            # the source otherwise (Scavenging Ghoul). One payment either way:
            # what differs is only which permanent gives the counters up, which
            # is the whole of `remove_counter_filter` — the same arrangement the
            # placing twin makes below with `counter_cost_permanent`.
            payer = counter_removal_permanent or permanent
            remove_counters(
                payer, ability.cost.remove_counter, counters_removed_for_cost
            )
            if payer is not permanent:
                self.log.append(
                    f"{payer.card.name} gave up {counters_removed_for_cost} "
                    f"{ability.cost.remove_counter} counter(s) "
                    f"({permanent.card.name}'s cost)"
                )

        if requires_tap:
            self.become_tapped(permanent)
            # The {T} symbol is a permanent tapped to pay for its *own*
            # ability, which is what the phrase says too — recorded beside the
            # spelled-out cost rather than only there, so the record answers the
            # question the words ask rather than the subset one card needs.
            record_tapped_to_pay(permanent, permanent)

        # The spelled-out tap cost, collected above and paid here — beside the
        # {T} symbol, because both are the same payment and CR 601.2h pays every
        # cost at one moment.
        for tapped_for_cost in tap_cost_permanents:
            self.become_tapped(tapped_for_cost)
            # "…destroy all Merfolk **tapped this turn to pay for its
            # abilities**" (Vodalian War Machine). Nothing on the board can be
            # asked how a permanent came to be tapped, so the answer is written
            # down here, where the cost is paid — the one place an activation
            # cost taps anything other than the source (engine/cost_tap_records.py).
            record_tapped_to_pay(permanent, tapped_for_cost)
        if tap_cost_permanents:
            self.log.append(
                f"{permanent.card.name}: tapped "
                + ", ".join(p.card.name for p in tap_cost_permanents)
                + " to pay its cost"
            )

        # …and the untap cost, paid at the same moment for the same reason
        # (CR 601.2h). Through `become_untapped`, the one tapped→untapped
        # transition, so anything watching for one sees this payment too.
        if untap_cost_permanent is not None:
            self.become_untapped(untap_cost_permanent)
            self.log.append(
                f"{permanent.card.name}: untapped "
                f"{untap_cost_permanent.card.name} to pay its cost"
            )

        # The activation half of "…becomes tapped **or** a player activates an
        # artifact's ability without {T} in its activation cost" (Haunting
        # Wind, Powerleech). "Without {T} in its activation cost" is exactly
        # `requires_tap` being false — an ability that *does* tap has already
        # announced the same condition through `become_tapped` above, so
        # emitting here as well would fire it twice for one activation.
        #
        # Here rather than at the legality gate, which returns early: every
        # guard and cost has passed at this point, so the trigger sees only
        # activations the rules allowed. That is the same placement, and the
        # same reason, as the loyalty event below.
        if not requires_tap:
            emit(
                self, "permanent_tapped_or_ability_activated",
                subject=permanent, seat=controller_index,
                # The other announcement of this condition stamps the same key
                # (``become_tapped``), because "that artifact's controller"
                # (Haunting Wind) reads the subject's seat whichever half of the
                # printed ability fired. It is the *artifact's* controller, not
                # the activating seat above — those differ whenever an ability
                # is activated on a permanent someone else controls.
                event_subject_controller=self.controller_index_of(permanent),
            )

        # All guards/costs passed — tally an activation of a capped ability,
        # and of one whose own effect reads the tally ("If this ability has been
        # activated four or more times this turn, …", Farrelite Priest). Two
        # questions about one ledger: the first is asked of the printed clause,
        # because a cap is a refusal and is enforced before anything is paid;
        # the second is asked of the compiled program, because that sentence is
        # an effect the grammar has already read and a second reader of it would
        # be free to disagree.
        if activation_caps or reads_activation_tally(ability.instruction):
            mark_activated_this_turn(self, permanent)
        # The same stamp for the cap with no turn in it ("Activate only once",
        # Touch of Vitae's granted ability). Beside the per-turn one and in the
        # same position, because both are budgets spent by an activation the
        # rules allowed — and asked of the table rather than of the words here,
        # so the refusal and the stamp read one sentence the same way.
        if prints_once_only_restriction(ability_lower):
            mark_once_only_activation(permanent, ability_lower)

        # CR 606.4: a loyalty symbol is a cost to put on or remove that many
        # loyalty counters, paid as the ability is activated — so the walker's
        # loyalty has already moved while the ability is on the stack, and a
        # minus ability that empties it kills the walker before resolution
        # (704.5i). The sufficiency of a removal was checked above (606.6).
        if ability.cost.is_loyalty:
            loyalty_now = int(permanent.metadata.get("loyalty_counters", 0))
            permanent.metadata["loyalty_counters"] = loyalty_now + loyalty_delta
            permanent.metadata["loyalty_ability_used_turn"] = self.turn
            self.log.append(
                f"{controller.name} activated {permanent.card.name} "
                f"({loyalty_delta:+d} loyalty, now {loyalty_now + loyalty_delta})"
            )
            # "Whenever you activate a loyalty ability of …" (Keral Keep
            # Disciples). CR 606.4's payment *is* the activation, so this is the
            # event — and it is announced here rather than at the legality gate
            # above, which returns early: announcing there would fire the trigger
            # on activations the rules refused. The walker is still on the
            # battlefield at this point, which is what lets a minus ability that
            # bins it (CR 704.5i) still be something the trigger saw.
            # `queue_permanent_ability` holds the batch until the ability is on
            # the stack, so CR 603.3 puts this above it.
            emit(
                self, "you_activate_loyalty_ability",
                subject=permanent, seat=controller_index,
            )

        # Pay the discard additional cost. Costs are paid on activation, before
        # the ability goes on the stack, so the discarded card is the one drawn
        # before this activation rather than the card it draws.
        if discard_cost_card is not None:
            self.take_card_from_hand(controller, discard_cost_card)
            self._discard_card(controller, discard_cost_card)
            self.log.append(
                f"{controller.name} discarded {discard_cost_card.name} "
                f"(the last card they drew this turn) to activate {permanent.card.name}"
            )

        # Pay the chosen discard. Same ordering rule as the Ring's above: the
        # cost is collected before the ability is on the stack, so an ability
        # that draws cannot discard what it drew.
        for cost_card in discard_cost_cards:
            self.take_card_from_hand(controller, cost_card)
            self._discard_card(controller, cost_card)
            self.log.append(
                f"{controller.name} discarded {cost_card.name} "
                f"to activate {permanent.card.name}"
            )

        # "Put a page counter on this artifact" (Mazemind Tome). A cost that
        # *adds* rather than spends, so there was nothing to check above — and
        # paid here with the rest, before the ability is on the stack, because
        # CR 602.2b puts every cost at the same moment.
        if ability.cost.put_counter:
            from ...named_counters import add_counters

            # The chosen permanent when the card named one (Wandering Mage),
            # and the source otherwise (Mazemind Tome). One payment either way:
            # what differs is only which permanent it lands on, which is the
            # whole of `put_counter_filter`.
            from ...pt import pt_counter_deltas

            recipient = counter_cost_permanent or permanent
            if pt_counter_deltas(ability.cost.put_counter) is not None:
                # A P/T counter is CR 122.1a's, and every P/T write in this
                # engine goes through `engine/pt.py` — `add_counters` keeps the
                # *named* markers, which have no layer-7 meaning at all.
                self.place_pt_counters(recipient, ability.cost.put_counter)
                self.log.append(
                    f"{recipient.card.name} gets a "
                    f"{ability.cost.put_counter} counter "
                    f"({permanent.card.name}'s cost)"
                )
            else:
                total = add_counters(recipient, ability.cost.put_counter)
                self.log.append(
                    f"{recipient.card.name} has {total} "
                    f"{ability.cost.put_counter} counter(s)"
                )

        # "Discard your hand" (Subira). Every card, snapshotted before the loop
        # because `_discard_card` may itself put something into the hand (Library
        # of Leng's replacement offers the top of the library instead) — iterating
        # the live list would then skip or revisit a card.
        if ability.cost.discard_whole_hand:
            emptied = list(controller.hand)
            controller.hand = []
            for cost_card in emptied:
                self._discard_card(controller, cost_card)
            self.log.append(
                f"{controller.name} discarded their hand "
                f"({len(emptied)} card(s)) to activate {permanent.card.name}"
            )

        # Pay the life (CR 118.3b: the payment is subtracted from the life total,
        # which CR 119.4 also makes a loss of that much life). Sufficiency was
        # checked above. No `check_state_based_actions()` call: activation's
        # `_settle()` already sweeps, CR 704.3 puts the sweep at the next
        # priority rather than mid-cost, and every other cost payment here omits
        # it — measured, a card activated at exactly 3 life ends at life 0 and
        # lost either way.
        if life_owed:
            controller.life -= life_owed
            self.log.append(
                f"{controller.name} paid {life_owed} life to activate "
                f"{permanent.card.name}"
            )

        # Drought's imposed sacrifices, paid with the printed ones and at the
        # same moment (CR 602.2b). Picked before any mana left the pool, so a
        # board unchanged since pays exactly what the gate measured.
        self._pay_sacrifice_tax(
            sacrifice_tax_victims, f"to activate {permanent.card.name}"
        )
        # Pay the chosen sacrifice (CR 601.2h) — the creature is gone before the
        # ability goes on the stack, so Hobblefiend's counter lands on a board
        # that has already lost it.
        if sacrifice_cost_permanent is not None:
            name = sacrifice_cost_permanent.card.name
            self.sacrifice_permanent(sacrifice_cost_permanent)
            self.log.append(
                f"{controller.name} sacrificed {name} to activate {permanent.card.name}"
            )
        # …and the second half of a conjoined sacrifice (Viscerid Drone), paid
        # at the same moment: CR 602.2b puts every cost of an activation at one
        # point, so a board that changed between the two would not be able to
        # pay half of it.
        if sacrifice_also_permanent is not None:
            name = sacrifice_also_permanent.card.name
            self.sacrifice_permanent(sacrifice_also_permanent)
            self.log.append(
                f"{controller.name} sacrificed {name} to activate {permanent.card.name}"
            )
        # …and the "any number of" set beside it (Sword of the Ages), paid the
        # same way and at the same moment. Each is sacrificed by identity — an
        # index held across the removals would name whichever permanent slid
        # into the slot — and the list survives on the resolution's choices,
        # because by the time the effect reads their total power they are cards
        # in a graveyard (CR 608.2h).
        for victim in sacrifice_cost_set:
            name = victim.card.name
            self.sacrifice_permanent(victim)
            self.log.append(
                f"{controller.name} sacrificed {name} to activate {permanent.card.name}"
            )

        # "Exile the top card of your library" — paid here with the rest
        # (CR 602.2b puts every cost at one moment), and the cards recorded on
        # the two channels every other exile cost already writes: the resolution
        # asks "the exiled card's mana value" (Phyrexian Devourer) and "if the
        # exiled card is a snow land" (Storm Elemental) when the cards are
        # already in exile, so the record is the only sound answer (CR 608.2h).
        #
        # ``exiled_for_cost`` is the single-object channel every existing reader
        # asks and takes the *first* card off the top, with the whole payment
        # beside it under ``exiled_set_for_cost`` — the same pairing the chosen
        # exile above keeps, rather than a third shape for one channel.
        # The graveyard twin of the payment below, paid at the same moment
        # (CR 602.2b puts every cost at one) and recorded on the same two
        # channels. Removed **highest index first**: the positions were found
        # against the pile as it stands, and deleting a lower one renumbers
        # every position above it — which for "the top two creature cards" is
        # the difference between exiling the two the card named and exiling one
        # of them plus whatever slid into the slot.
        if ability.cost.exile_graveyard_position is not None:
            from ...graveyard_order import positions_named

            spec = ability.cost.exile_graveyard_position
            taken = positions_named(controller.graveyard, spec)
            from_graveyard = [controller.graveyard[index] for index in taken]
            for index in sorted(taken, reverse=True):
                del controller.graveyard[index]
            controller.exile.extend(from_graveyard)
            exiled_set_for_cost = [*exiled_set_for_cost, *from_graveyard]
            if exiled_for_cost is None and from_graveyard:
                exiled_for_cost = from_graveyard[0]
            self.log.append(
                f"{controller.name} exiled "
                + ", ".join(card.name for card in from_graveyard)
                + f" from the {spec.get('position', 'top')} of their graveyard "
                f"to activate {permanent.card.name}"
            )

        if ability.cost.hand_to_library_top:
            # The payer chooses which card (CR 601.2b, reached through
            # CR 602.2b), so the choice arrives with the action that pays —
            # ``cost_hand_index``, the same channel the discard cost reads.
            # Naming nothing takes the deterministic first card, which is what
            # keeps AI and headless play unblocked.
            #
            # Through ``take_card_from_hand`` and ``put_card_into_library``, the
            # two seams: a hand repeats one immutable ``CardDefinition`` per
            # copy, so an identity filter over it removes *every* copy where the
            # caller then puts one back, and CR 903.9b's commander check has no
            # single fire site for "put into a library".
            for _ in range(ability.cost.hand_to_library_top):
                index = (
                    cost_hand_index
                    if isinstance(cost_hand_index, int)
                    and 0 <= cost_hand_index < len(controller.hand)
                    else 0
                )
                paid = controller.hand[index]
                self.take_card_from_hand(controller, paid)
                # ``from_battlefield=None`` said out loud: this card comes
                # off a *hand*, so there is no CR 614 leaves-the-battlefield
                # replacement to tell — and the seam guard reads the word
                # rather than guessing from the function around it.
                self.put_card_into_library(
                    controller, paid, position="top", from_battlefield=None,
                )
                cost_hand_index = None
                self.log.append(
                    f"{controller.name} put {paid.name} on top of their library "
                    f"to activate {permanent.card.name}"
                )

        if ability.cost.exile_top_of_library:
            from_library = [
                controller.library.pop(0)
                for _ in range(ability.cost.exile_top_of_library)
            ]
            controller.exile.extend(from_library)
            exiled_set_for_cost = [*exiled_set_for_cost, *from_library]
            if exiled_for_cost is None:
                exiled_for_cost = from_library[0]
            self.log.append(
                f"{controller.name} exiled "
                + ", ".join(card.name for card in from_library)
                + f" from the top of their library to activate {permanent.card.name}"
            )

        # Ring of Ma'rûf: "Exile this artifact" is part of the cost, so the
        # permanent leaves before the ability goes on the stack — and the ability
        # still resolves from exile (CR 603.6 / 608.2: the source leaving doesn't
        # counter it). The stack item keeps its source_permanent reference.
        if ability.cost.exile_self:
            self.remove_from_battlefield(permanent)
            controller.exile.append(permanent.card)
            self.log.append(
                f"{controller.name} exiled {permanent.card.name} to activate its ability"
            )

        # "Return this enchantment to its owner's hand" (Cycle of Life): the
        # same two costs one zone over (CR 118.3), paid now, so the ability
        # resolves with its source in a hand. Through `put_card_into_hand`
        # rather than an append, because CR 903.9b has no single fire site and
        # thirty of them is twenty-nine places to forget it.
        if ability.cost.return_self_to_hand:
            # Whose hand, asked *before* the removal: CR 108.3's owner is
            # derived from the base controller, and a permanent no longer on
            # a battlefield has no seat to derive it from.
            owner_seat = self.owner_index_of(permanent)
            self.remove_from_battlefield(permanent)
            self.put_card_into_hand(
                self.players[
                    owner_seat if owner_seat is not None else controller_index
                ],
                permanent.card,
                # CR 614.6: the object leaving is what a
                # leaves-the-battlefield replacement replaces, and this seam
                # is handed a ``CardDefinition`` a deck shares between every
                # copy. Without the keyword the cost would slip past Dreams
                # of the Dead -- a drawback missed, which is the direction
                # nobody notices.
                from_battlefield=permanent,
            )
            self.log.append(
                f"{controller.name} returned {permanent.card.name} to its "
                "owner's hand to activate its ability"
            )

        # …and the chosen return, paid at the same moment and through the same
        # seam (CR 601.2h): the permanents the payer picked go to their owners'
        # hands before the ability goes on the stack.
        for returned_for_cost in return_cost_permanents:
            owner_seat = self.owner_index_of(returned_for_cost)
            name = returned_for_cost.card.name
            self.remove_from_battlefield(returned_for_cost)
            self.put_card_into_hand(
                self.players[
                    owner_seat if owner_seat is not None else controller_index
                ],
                returned_for_cost.card,
                from_battlefield=returned_for_cost,
            )
            self.log.append(
                f"{controller.name} returned {name} to its owner's hand "
                f"to activate {permanent.card.name}"
            )

        # …and the host of an Aura that eats what it enchants (Betrothed of
        # Fire), paid at the same moment as every other cost and before the
        # source's own sacrifice below, so a card printing both eats the host
        # while the Aura is still attached to it.
        if sacrifice_attached_permanent is not None:
            host_name = sacrifice_attached_permanent.card.name
            self.sacrifice_permanent(sacrifice_attached_permanent)
            self.log.append(
                f"{controller.name} sacrificed {host_name} to activate "
                f"{permanent.card.name}"
            )

        # "Sacrifice this artifact" (Black Lotus, Bottle of Suleiman) is likewise
        # a cost, paid now — the ability still resolves from the graveyard.
        if ability.cost.sacrifice_self:
            self.sacrifice_permanent(permanent)
            self.log.append(
                f"{controller.name} sacrificed {permanent.card.name} to activate its ability"
            )

        # "{T}, **Mill a card**: …" (Millikin, Charmed Pendant). Last of every
        # cost, which is CR 601.2h's order: a cost that moves a card from the
        # library to a public zone is paid after the ones that do not. Through
        # the graveyard seam with its source zone named, so a replacement that
        # diverts the card (CR 614) and a trigger watching a card arrive from a
        # library both see a mill — and only a card that *arrived* is recorded
        # as milled (CR 701.17c finds a milled card in the public zone it
        # moved to).
        milled_for_cost: list = []
        for _ in range(getattr(ability.cost, "mill_cards", 0)):
            milled = controller.library.pop(0)
            self.put_card_into_graveyard(controller, milled, from_zone="library")
            milled_for_cost.append(milled)
        if milled_for_cost:
            self.log.append(
                f"{controller.name} milled "
                + ", ".join(card.name for card in milled_for_cost)
                + f" to activate {permanent.card.name}"
            )
        return (
            exiled_for_cost, exiled_set_for_cost,
            graveyard_target_stamp_after_cost, milled_for_cost,
            target_permanent_index,
        )

    def _pay_exile_cost(
        self, choice, controller, controller_index: int, permanent
    ) -> list:
        """Move what :meth:`_choose_exile_cost` chose into exile, returning the
        cards it ate.

        Called below the activation's last refusal, so a payment here is always
        for an activation that happens. The pile is read back by slot **and**
        checked by identity: nothing between the choice and this call moves a
        card, and if that ever stops being true the slot that no longer holds
        the chosen object is found again rather than trusted, because a slot is
        not an address.
        """
        zone, pile, slots, objects = choice
        if zone == "hand":
            # Through ``take_card_from_hand``, not a filter over the list: a
            # deck repeats one immutable ``CardDefinition`` per copy, so every
            # copy of a card in a hand is the same Python object and an identity
            # filter removes all of them where this cost eats exactly one.
            for card in objects:
                self.take_card_from_hand(controller, card)
                controller.exile.append(card)
            self.log.append(
                f"{controller.name} exiled "
                + ", ".join(card.name for card in objects)
                + f" from their hand to activate {permanent.card.name}"
            )
            return list(objects)
        if zone == "graveyard":
            # Highest slot first: every pop renumbers the slots behind it.
            located = []
            for slot, card in zip(slots, objects):
                if not (0 <= slot < len(pile.graveyard)) or pile.graveyard[slot] is not card:
                    slot = next(
                        index for index, held in enumerate(pile.graveyard)
                        if held is card and index not in located
                    )
                located.append(slot)
            for slot in sorted(located, reverse=True):
                pile.graveyard.pop(slot)
            controller.exile.extend(objects)
            self.log.append(
                f"{controller.name} exiled "
                + ", ".join(card.name for card in objects)
                + f" from the graveyard of {pile.name} to activate "
                f"{permanent.card.name}"
            )
            return list(objects)
        taken = []
        for chosen in objects:
            owner_index = self.owner_index_of(chosen)
            card = chosen.card
            self.remove_from_battlefield(chosen)
            self.players[
                owner_index if owner_index is not None else controller_index
            ].exile.append(card)
            taken.append(card)
        self.log.append(
            f"{controller.name} exiled "
            + ", ".join(card.name for card in taken)
            + f" to activate {permanent.card.name}"
        )
        return taken
