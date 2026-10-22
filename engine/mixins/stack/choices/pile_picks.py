"""Cards picked out of a pile: separated piles, shared piles, and graveyards.

Separating cards into piles (CR 700.3) — Fact or Fiction's face-up piles and
Phyrexian Portal's face-down ones; an opponent's pick out of a pile the
revealer turned up (Thran Tome); each seat in turn claiming a card from a shared
exile pile (Thieves' Auction); one card out of a permanent's linked-exile pile;
and the graveyard as a pile — which graveyard "a single graveyard" means, cards
exiled out of a named player's graveyard, and an opponent's pick out of yours,
offered again for each payment (Forgotten Lore).
"""

from __future__ import annotations

import random
from ....linked_exile import link_exiled_card
from ....models import Permanent
from ....oracle_types import (CLAIMABLE_EXILED_CARDS, EXILED_THIS_WAY,
                              EXILED_THIS_WAY_OBJECTS, OracleInstruction)
from .... import piles
from ....pending_choices import PendingChoice
from ....mana_payment import mana_cost_label
from ....handlers.zones import (FORGOTTEN_PICKS,
                                GRAVEYARD_PICK_TO_LIBRARY_BOTTOM)


class PileChoicesMixin:
    # -- An opponent picks out of a revealed pile (Thran Tome) ---------------

    def confirm_opponent_picks_revealed(self, player_index: int, index: int) -> bool:
        return self.resolve_pending_choice(
            "opponent_picks_revealed", player_index, index=index
        )

    def _resolve_opponent_picks_revealed(self, choice: PendingChoice, index) -> bool:
        """The opponent's pick out of the cards the revealer turned up.

        *index* addresses the **revealed list**, not the library: CR 701.20 left
        the cards where they were, and the list is what the prompt showed. The
        card is then located in the library by identity \u2014 two copies of a card
        in a deck are the same immutable ``CardDefinition``, so ``list.remove``
        would take whichever entry came first \u2014 and moved through the one seam
        a card reaches a graveyard by, naming the library it came out of so a
        card watching for that move sees it.

        A card that has already left is left alone, which is CR 608.2 doing as
        much as it can.
        """
        cards = list(choice.data.get("_cards") or ())
        if not isinstance(index, int) or not (0 <= index < len(cards)):
            return False
        card = cards[index]
        revealer = self.players[int(choice.data.get("revealer_index", 0))]
        from_zone = str(choice.data.get("from_zone", "library"))
        fate = str(choice.data.get("fate", "graveyard"))
        other_fate = choice.data.get("other_fate")
        chooser = self.players[choice.player_index].name
        # "Exile that card and **put the other one into your hand**."
        # (Phyrexian Grimoire.) The pick and what it left behind are one answer,
        # so both halves move here — the pile is only nameable while this prompt
        # is holding it. Absent for every library printing, where CR 701.20b
        # leaves the rest where they were.
        for shown in cards:
            if shown is card:
                target_zone = fate
            elif other_fate:
                target_zone = str(other_fate)
            else:
                continue
            if not self._move_picked_pile_card(
                revealer, shown, from_zone, target_zone
            ):
                self.log.append(f"{shown.name} has already moved")
                continue
            self.log.append(
                f"{chooser} chose {card.name}; {shown.name} goes to the "
                f"{target_zone}"
                if shown is card
                else f"{shown.name} goes to the {target_zone}"
            )
        self.discard_pending_choice(choice)
        return True

    def _move_picked_pile_card(self, owner, card, from_zone: str, to_zone: str) -> bool:
        """Move *card* out of *owner*'s *from_zone* into *to_zone*, by identity.

        By identity and not by value, for the reason every pile read in this
        file gives: two copies of a card in a deck are literally one immutable
        ``CardDefinition``, so ``list.remove`` takes whichever entry comes
        first. A card that has already left is left alone, which is CR 608.2
        doing as much as it can — the False this returns.

        The destinations go through the seams that own them
        (``put_card_into_graveyard``, ``put_card_into_hand``) rather than
        appending to a list, so the graveyard watchers and CR 903.9b both see
        the move.
        """
        if from_zone == "held":
            # "…**and the rest into your graveyard**." (Intuition.) The pile was
            # handed over by the search that found it and is in no zone at all,
            # so there is nothing to take it out of — the move below is the
            # whole of what this card does with it. Its own word rather than a
            # missing ``from_zone``, because "absent" already means the library.
            pile = None
        else:
            pile = getattr(owner, from_zone, None)
            if pile is None:
                return False
            for slot, held in enumerate(pile):
                if held is card:
                    pile.pop(slot)
                    break
            else:
                return False
        # ``from_zone`` is a *library* or a *graveyard* and never an exile — the
        # lowering that writes it offers exactly those two (Thran Tome's reveal
        # and Phyrexian Grimoire's graveyard pick) — so the pop above is not a
        # departure from exile and needs no ``take_card_from_exile``. Listed in
        # `tests/engine/test_exile_removal_seam._COMPUTED_ATTRIBUTE_WRITES`
        # saying so, because a computed attribute name is one the ban cannot
        # read for itself.
        if to_zone == "graveyard":
            # A held card came out of a library and CR 404.1 sends it to its
            # owner's graveyard either way, so the announced source zone is the
            # one it actually left — which is what Gaea's Blessing's "put into
            # your graveyard from your library" answers to.
            self.put_card_into_graveyard(
                owner, card,
                from_zone="library" if from_zone == "held" else from_zone,
            )
        elif to_zone == "hand":
            self.put_card_into_hand(owner, card)
        elif to_zone == "exile":
            owner.exile.append(card)
        elif pile is not None:
            # A destination nobody implements: put it back rather than losing
            # the card. The lowering's closed list is what stops this being
            # reachable, and this is the belt behind it.
            pile.insert(0, card)
            return False
        else:
            # …and with no pile to put it back into, the card is held by the
            # resolution and stays there — the same refusal with nothing to
            # undo.
            return False
        return True

    def _default_opponent_picks_revealed(self, choice: PendingChoice) -> None:
        """A non-interactive chooser takes the **costliest** revealed card.

        The same stated policy as ``_default_revealed_hand_pick``, and for the
        same reason: this seat is an opponent, the card it names is the one the
        revealer loses, and mana value is the one ranking every card in the pool
        answers.
        """
        cards = list(choice.data.get("_cards") or ())
        if not cards:
            self.discard_pending_choice(choice)
            return
        best = max(range(len(cards)), key=lambda i: (cards[i].cmc, -i))
        if not self._resolve_opponent_picks_revealed(choice, best):
            self.discard_pending_choice(choice)

    # -- Each seat in turn taking one card out of a shared exile pile --------

    def confirm_exiled_pile_claim(self, player_index: int, pile_index: int) -> bool:
        """Answer Thieves' Auction's "each player chooses one of the exiled
        cards"."""
        return self.resolve_pending_choice(
            "exiled_pile_claim", player_index, pile_index=pile_index,
        )

    def _resolve_exiled_pile_claim(
        self, choice: PendingChoice, pile_index: int
    ) -> bool:
        """Take the chosen card off the shared pile and put it onto the
        battlefield under the chooser's control (CR 701.3 is not this — nothing
        is attached; this is an ordinary entry from exile).

        The pile is read back out of the **resolution's** scratchpad rather than
        off the choice, and that is what makes the round-robin one pile: every
        seat of every round is looking at the same list, and an answer that
        copied it would let two seats claim one card.

        Ownership is the one fact the entry cannot re-derive (CR 108.3). The
        card came out of somebody's exile and goes onto somebody else's
        battlefield, so the owner is recorded on the arrival — without it the
        card would go to the *thief's* graveyard when it dies, and Thieves'
        Auction would quietly rewrite who owns a deck.

        The index is re-checked against the pile rather than trusted from the
        wire, exactly as every other pick here is: a client offering a stale
        list would otherwise claim a card another seat has already taken.
        """
        context = choice.data.get("_context")
        if context is None:
            return False
        pile = context.results.get(CLAIMABLE_EXILED_CARDS)
        if not pile or not isinstance(pile_index, int):
            return False
        if not 0 <= pile_index < len(pile):
            return False
        owner_index, card = pile.pop(pile_index)
        owner = self.players[owner_index]
        # Through the one transition that takes a card out of exile, which is
        # what retires the exile register with it (CR 400.7, CR 406.7): the card
        # is about to become a new object on a battlefield, and a record left
        # behind is a memory the next effect to exile it would find live.
        self.take_card_from_exile(owner, card)
        seat = choice.player_index
        arrival = Permanent(card=card)
        if seat != owner_index:
            arrival.metadata["owner_player_index"] = owner_index
        self._put_permanent_onto_battlefield(seat, arrival, None)
        if choice.data.get("tapped"):
            arrival.tapped = True
        self.discard_pending_choice(choice)
        self.log.append(
            f"{self.players[seat].name} chose {card.name} from the exiled cards"
            + (" (tapped)" if choice.data.get("tapped") else "")
        )
        self._recompute_continuous_effects()
        return True

    def _default_exiled_pile_claim(self, choice: PendingChoice) -> None:
        """A non-interactive seat takes the **most expensive** card left.

        A stated policy, like every other default here, and the one ranking
        every card in the pool answers: the chooser is picking for themselves
        out of a pile they will not see again, so the biggest thing on it is a
        real answer where "the first one" is only an order of exile. Ties keep
        the pile's order, which is what keeps a seeded simulation reproducible.
        """
        context = choice.data.get("_context")
        pile = (context.results.get(CLAIMABLE_EXILED_CARDS) or []) if context else []
        if not pile:
            self.discard_pending_choice(choice)
            return
        best = max(
            range(len(pile)), key=lambda index: (pile[index][1].cmc or 0, -index)
        )
        if not self._resolve_exiled_pile_claim(choice, best):
            self.discard_pending_choice(choice)

    # -- An opponent picking out of your graveyard, again for each payment ---

    def confirm_graveyard_pick_for_price(
        self, player_index: int, graveyard_index: int
    ) -> bool:
        """Answer Forgotten Lore's "target opponent chooses a card"."""
        return self.resolve_pending_choice(
            "graveyard_pick_for_price", player_index,
            graveyard_index=graveyard_index,
        )

    def _resolve_graveyard_pick_for_price(
        self, choice: PendingChoice, graveyard_index: int
    ) -> bool:
        """Record the pick, then offer its price to the *other* seat.

        Two seats answer alternately, which is why the loop is a chain of
        prompts and not a Python loop: the payment is the caster's decision and
        the pick is the opponent's, and neither is available while the other is
        being asked.

        The legal indices are re-checked against the record armed with the
        choice rather than trusted from the wire — a client offering the whole
        graveyard would otherwise let one card be chosen twice, which is the
        exclusion clause deleted.
        """
        if graveyard_index not in (choice.data.get("legal_indices") or []):
            return False
        owner = self.players[int(choice.data["owner_index"])]
        if not 0 <= graveyard_index < len(owner.graveyard):
            return False
        context = choice.data.get("_context")
        instruction = choice.data.get("_instruction")
        if context is None or instruction is None:
            return False
        chosen = owner.graveyard[graveyard_index]
        context.results.setdefault(FORGOTTEN_PICKS, []).append(chosen)
        self.discard_pending_choice(choice)
        self.log.append(
            f"{self.players[choice.player_index].name} chose {chosen.name} "
            f"({choice.data.get('card_name', '')})"
        )
        # "You may pay {G}. **If you do**, repeat this process." The offer goes
        # to the caster through the ordinary optional-cost prompt, with the same
        # instruction as its accept branch — so paying re-arms the pick with the
        # exclusion set the shared context has just grown, and declining runs
        # the sentence that ends the process.
        cost = dict(choice.data.get("cost") or {})
        self.arm_pending_choice(
            "optional_pay", self.players.index(context.caster),
            card_name=choice.data.get("card_name", ""),
            cost=cost,
            life=0,
            prompt=f"Pay {mana_cost_label(cost)} to repeat?",
            _on_accept=(instruction,),
            _on_decline=(
                OracleInstruction("finish_repeated_graveyard_pick", "", {}),
            ),
            _context=context,
        )
        return True

    def _default_graveyard_pick_for_price(self, choice: PendingChoice) -> None:
        """A non-interactive opponent gives up the cheapest card there is.

        A stated policy, like every other default here: mana value is the one
        ranking every card in the pool answers, and the chooser is the player
        who does *not* want the caster to get anything back.
        """
        legal = list(choice.data.get("legal_indices") or [])
        owner = self.players[int(choice.data["owner_index"])]
        if not legal:
            self.discard_pending_choice(choice)
            return
        legal.sort(key=lambda i: ((owner.graveyard[i].cmc or 0), i))
        if not self._resolve_graveyard_pick_for_price(choice, legal[0]):
            self.discard_pending_choice(choice)

    # -- The two face-down piles (Phyrexian Portal) --------------------------

    def confirm_library_pile_split(self, player_index: int, first_pile) -> bool:
        """Answer the division. *first_pile* is the positions - into the ten
        cards as they were shown - that go into the first pile; everything else
        goes into the second. Either pile may be empty, which is a legal
        division and a real one: it forces the controller to choose between
        searching everything and searching nothing."""
        return self.resolve_pending_choice(
            "library_pile_split", player_index, first_pile=first_pile
        )

    def _resolve_library_pile_split(self, choice: PendingChoice, first_pile) -> bool:
        cards = list(choice.data.get("_cards") or ())
        positions = [int(i) for i in (first_pile or [])]
        if len(set(positions)) != len(positions):
            return False
        if any(not 0 <= i < len(cards) for i in positions):
            return False
        chosen = set(positions)
        piles = [
            [card for i, card in enumerate(cards) if i in chosen],
            [card for i, card in enumerate(cards) if i not in chosen],
        ]
        self.discard_pending_choice(choice)
        self.log.append(
            f"{self.players[choice.player_index].name} divided "
            f"{len(cards)} cards into piles of {len(piles[0])} and {len(piles[1])}"
        )
        # The controller's decision, armed by answering this one - and it is a
        # *different seat's*, which is the whole design of the card.
        self.arm_pending_choice(
            "pile_exile_choice", int(choice.data["owner_index"]),
            card_name=choice.data.get("card_name", ""),
            owner_index=int(choice.data["owner_index"]),
            _piles=piles,
            _source_permanent=choice.data.get("_source_permanent"),
        )
        return True

    def _default_library_pile_split(self, choice: PendingChoice) -> None:
        """The stated policy: **split as evenly as possible**, in the order the
        cards came off the library.

        Neutral rather than optimal, and deliberately so. The division is the
        one decision in this card that is genuinely adversarial - a divider who
        knows the pile can make both halves bad - and there is no valuation
        here that would not be a guess about what the *other* seat wants. An
        even split is the answer that neither hands the controller their pick
        nor denies it.
        """
        cards = list(choice.data.get("_cards") or ())
        half = len(cards) // 2
        if not self._resolve_library_pile_split(choice, list(range(half))):
            self.discard_pending_choice(choice)

    def confirm_pile_exile_choice(self, player_index: int, pile_index: int) -> bool:
        """Answer which of the two face-down piles is exiled (0 or 1). The
        other is the one searched."""
        return self.resolve_pending_choice(
            "pile_exile_choice", player_index, pile_index=pile_index
        )

    def _resolve_pile_exile_choice(self, choice: PendingChoice, pile_index) -> bool:
        """Exile the named pile face down, and hand the other to the search.

        Face down is not decoration: the piles were divided face down and this
        choice was made blind, so a pile that arrived in exile face up would
        tell every player at the table what the decision had cost. It goes on
        the linked-exile record for that record's own reason - two copies of
        one card in a deck are the same object, so the record of the exiling is
        the only thing that can say which one is hidden.
        """
        from ....linked_exile import link_exiled_card

        piles = list(choice.data.get("_piles") or ())
        if pile_index not in (0, 1) or len(piles) != 2:
            return False
        owner = self.players[int(choice.data["owner_index"])]
        exiled = piles[int(pile_index)]
        kept = piles[1 - int(pile_index)]
        source = choice.data.get("_source_permanent")
        for card in exiled:
            owner.exile.append(card)
            if source is not None:
                link_exiled_card(
                    source, card, int(choice.data["owner_index"]), face_down=True
                )
        self.discard_pending_choice(choice)
        self.log.append(
            f"{owner.name} exiled a face-down pile of {len(exiled)} card(s)"
        )
        self.arm_pending_choice(
            "pile_search", int(choice.data["owner_index"]),
            card_name=choice.data.get("card_name", ""),
            owner_index=int(choice.data["owner_index"]),
            _pile=list(kept),
        )
        return True

    def _default_pile_exile_choice(self, choice: PendingChoice) -> None:
        """The stated policy: **exile the smaller pile**, and on a tie the
        first.

        The only thing this seat knows about the piles is how many cards are in
        each - that is what "face down" means - and of the two facts available,
        keeping more cards to search through is the one that is never worse.
        """
        piles = list(choice.data.get("_piles") or ())
        if len(piles) != 2:
            self.discard_pending_choice(choice)
            return
        smaller = 0 if len(piles[0]) <= len(piles[1]) else 1
        if not self._resolve_pile_exile_choice(choice, smaller):
            self.discard_pending_choice(choice)

    def confirm_pile_search(self, player_index: int, pile_index) -> bool:
        """Answer the search of the kept pile. ``pile_index`` of None is
        CR 701.23b's fail-to-find, which a search always allows."""
        return self.resolve_pending_choice(
            "pile_search", player_index, pile_index=pile_index
        )

    def _resolve_pile_search(self, choice: PendingChoice, pile_index) -> bool:
        """Take one card to hand and shuffle the rest of the pile into the
        library.

        Both moves go through the CR 903.9b seams (``put_card_into_hand`` /
        ``put_card_into_library``) rather than appending, because the rule has
        no single fire site and this is one more place that would have
        forgotten it - a commander found this way must reach the command zone.
        """
        import random

        pile = list(choice.data.get("_pile") or ())
        if pile_index is not None and not 0 <= int(pile_index) < len(pile):
            return False
        player = self.players[int(choice.data["owner_index"])]
        found = pile.pop(int(pile_index)) if pile_index is not None else None
        if found is not None:
            self.put_card_into_hand(player, found)
        for card in pile:
            self.put_card_into_library(player, card)
        random.shuffle(player.library)
        self.discard_pending_choice(choice)
        self.log.append(
            (f"{player.name} took {found.name} " if found is not None
             else f"{player.name} found nothing and ")
            + f"and shuffled {len(pile)} card(s) back into their library"
        )
        return True

    def _default_pile_search(self, choice: PendingChoice) -> None:
        """The stated policy: take the **first** card in the pile.

        Lowest index is the house policy for a pick with no printed
        restriction, and failing to find is deliberately not the default here:
        the search is the whole reason the ability was activated, and a seat
        that declined it would have paid a cost for a shuffle.
        """
        pile = list(choice.data.get("_pile") or ())
        if not self._resolve_pile_search(choice, 0 if pile else None):
            self.discard_pending_choice(choice)

    # -- Two face-up piles (CR 700.3: Fact or Fiction and its siblings) ------
    #
    # The procedure and both resolvers are ``engine/piles.py``; these are the
    # two answers an interactive seat gives.

    def confirm_pile_split(self, player_index: int, first_pile) -> bool:
        """Answer the separation. *first_pile* is the positions — into the
        items as the prompt listed them — that go into the first pile;
        everything else goes into the second. Either pile may be empty
        (CR 700.3d)."""
        return self.resolve_pending_choice(
            "pile_split", player_index, first_pile=first_pile
        )

    def confirm_pile_choice(self, player_index: int, pile_index: int) -> bool:
        """Answer which of the two piles (0 or 1) is the chosen one."""
        return self.resolve_pending_choice(
            "pile_choice", player_index, pile_index=pile_index
        )

    # -- One card out of a permanent's linked-exile pile ---------------------

    def live_linked_exile_return_choices(self, choice: PendingChoice) -> list[int]:
        """The positions in the source's linked-exile record this pick admits.

        Positions into ``linked_entries``, not into a player's exile list: the
        record is what CR 610.3 names, and two copies of one card in a deck are
        the same ``CardDefinition`` object, so an index into the pile could not
        tell one entry from another.

        Re-run rather than stored, for ``live_exile_from_hand_choices``' reason:
        the list the seat is offered and the list its answer is checked against
        have to be one list.
        """
        return self.live_linked_exile_positions(
            choice.data.get("_source_permanent"),
            owner_index=(
                choice.player_index
                if choice.data.get("owned_by_chooser") else None
            ),
        )

    def live_linked_exile_positions(
        self, source, *, owner_index: int | None = None
    ) -> list[int]:
        """The positions in *source*'s linked-exile record that still name a
        card in exile — narrowed to one owner's when *owner_index* is given.

        The one answer to "which cards can a one-card return out of this pile
        move", asked by the pick above (Gustha's Scepter) and by the random
        pick that has no prompt to ask it through (Skyship Weatherlight). Two
        scans would be two lists, and the card chance picked has to be one the
        chooser could have been offered.
        """
        from ....linked_exile import linked_entries

        live: list[int] = []
        for index, entry in enumerate(linked_entries(source)):
            entry_owner = int(entry.get("owner_index", -1))
            if owner_index is not None and entry_owner != owner_index:
                continue
            if not (0 <= entry_owner < len(self.players)):
                continue
            # A card that has already left exile by some other route is not a
            # card this can return (CR 608.2b: as much as possible, and no card
            # created from nowhere).
            if entry["card"] not in self.players[entry_owner].exile:
                continue
            live.append(index)
        return live

    def confirm_linked_exile_return(self, player_index: int, entry_index) -> bool:
        """Answer the pending pick with a position from
        :meth:`live_linked_exile_return_choices`. There is no decline: "Return a
        card you own exiled with this artifact to your hand" is mandatory, and
        the only thing that ends it without moving a card is an empty pile."""
        return self.resolve_pending_choice(
            "linked_exile_return", player_index, entry_index=entry_index
        )

    def _resolve_linked_exile_return(self, choice: PendingChoice, entry_index) -> bool:
        """Move the chosen entry's card, and drop that one entry.

        Exactly one entry, where the sweep beside it drains the whole record:
        the cards left behind are still exiled with the permanent, and its
        lose-control trigger still names them.
        """
        from ....linked_exile import take_linked_entry_at

        source = choice.data.get("_source_permanent")
        if source is None:
            self.discard_pending_choice(choice)
            return True
        if entry_index not in self.live_linked_exile_return_choices(choice):
            return False
        entry = take_linked_entry_at(source, int(entry_index))
        zone = str(choice.data.get("zone", "hand"))
        self.leave_linked_exile(
            entry, zone,
            controller_index=(
                choice.player_index
                if choice.data.get("under_control_of_chooser") else None
            ),
        )
        self.log.append(
            f"{self.players[choice.player_index].name} returned "
            f"{entry['card'].name} to their {zone}"
        )
        self.discard_pending_choice(choice)
        return True

    def _default_linked_exile_return(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** eligible entry.

        Lowest position is the same policy ``_default_discard`` takes, and for
        the same reason — which entries are eligible at all is the printed
        phrase's business and is read off the list the interactive seat is
        offered, and anything past "one of them" is AI valuation rather than
        rules. A pile this seat owns nothing in is a prompt with no answer, so
        it simply comes off the queue.
        """
        live = self.live_linked_exile_return_choices(choice)
        if live and self._resolve_linked_exile_return(choice, live[0]):
            return
        self.discard_pending_choice(choice)

    # -- Exiling cards out of a named player's graveyard ---------------------

    def arm_graveyard_exile_pick(
        self, player_index: int, owner_index: int, payload: dict, context
    ) -> None:
        """Queue "exile up to N <type> cards from <player>'s graveyard".

        The whole payload travels rather than the candidate list, for the reason
        ``arm_choose_cards_in_hand`` gives: it is the *rule* the candidates came
        from, and re-running it is what keeps the list offered and the list an
        answer is checked against from being two lists.

        **The pick is not always an exile.** "…unless you put two cards from
        your graveyard on the bottom of your library" (Gurzigost) is the same
        question — which N cards out of this pile — with another destination,
        so the payload's ``destination`` rides the prompt (absent for every
        exile, whose prompt data is byte-identical to what it was) and the one
        answer path moves the cards where it says.
        """
        destination = payload.get("destination")
        self.arm_pending_choice(
            "graveyard_exile_pick", player_index,
            card_name=context.card.name,
            owner_index=int(owner_index),
            count=int(payload.get("count", 1)),
            up_to=bool(payload.get("up_to")),
            **({"destination": destination} if destination else {}),
            _payload=dict(payload),
            _context=context,
        )

    def live_graveyard_exile_candidates(self, choice: PendingChoice) -> list[int]:
        """The positions in that pile the printed noun phrase admits.

        Through ``graveyard_card_matches``, the one predicate the single-card
        graveyard exile, its picker and its re-check already share (idiom 9):
        a second reading here would offer a card the resolution then refuses,
        or refuse one it would have taken.

        "…a black creature card **other than this card** from your graveyard"
        (Ichorid) takes one *slot* out, never a kind of card: CR 113.7's source
        is the card whose ability this is, and a second copy of it in the same
        pile is another card and a legal choice. Through
        ``excluded_graveyard_slot``, the reader Junk Diver's "another" already
        goes through.
        """
        from ....handlers._common import graveyard_slots_matching

        owner = self.players[int(choice.data["owner_index"])]
        spec = dict(choice.data.get("_payload") or {})
        context = choice.data.get("_context")
        return graveyard_slots_matching(
            spec, owner.graveyard, getattr(context, "card", None)
        )

    def _how_many_graveyard_cards(self, choice: PendingChoice) -> int:
        """The **ceiling**, not the floor: "up to two" out of a pile holding one
        is one, and out of a pile holding three is still two (CR 608.2)."""
        return min(
            int(choice.data.get("count", 1)),
            len(self.live_graveyard_exile_candidates(choice)),
        )

    def confirm_graveyard_exile_pick(
        self, player_index: int, graveyard_indices
    ) -> bool:
        return self.resolve_pending_choice(
            "graveyard_exile_pick", player_index,
            graveyard_indices=graveyard_indices,
        )

    def _record_graveyard_exile(self, choice: PendingChoice, cards: list) -> None:
        context = choice.data.get("_context")
        if context is not None:
            # Both keys the sweep that exiles a board writes, because the
            # sentences behind this one ask the same two questions: how many,
            # and which. Written even for an empty pick — an *absent* key is a
            # back-reference with no producer, which is a different thing from
            # a producer that took nothing.
            context.results[EXILED_THIS_WAY_OBJECTS] = list(cards)
            context.results[EXILED_THIS_WAY] = len(cards)
        self.discard_pending_choice(choice)

    def _resolve_graveyard_exile_pick(
        self, choice: PendingChoice, graveyard_indices
    ) -> bool:
        """Take the chosen cards out of that pile and into their owner's exile.

        Every pick is validated before anything moves, the shape the two-zone
        exile search already takes: a single bad entry rejects the whole answer
        and leaves the prompt queued, so a malformed request cannot exile half
        a selection. "Up to" is what makes an empty answer legal; a fixed count
        owes exactly what the pile can supply.

        Highest index first, because a graveyard is a list and taking one
        renumbers everything behind it — the same reason the counted hand pick
        re-computes its candidates between picks.
        """
        owner = self.players[int(choice.data["owner_index"])]
        live = set(self.live_graveyard_exile_candidates(choice))
        wanted = self._how_many_graveyard_cards(choice)
        picks = list(graveyard_indices or [])
        if len(picks) != len(set(picks)):
            return False
        if len(picks) > wanted or (
            not choice.data.get("up_to") and len(picks) != wanted
        ):
            return False
        if any(index not in live for index in picks):
            return False
        taken = [owner.graveyard[index] for index in picks]
        if choice.data.get("destination") == GRAVEYARD_PICK_TO_LIBRARY_BOTTOM:
            return self._bottom_graveyard_pick(choice, owner, picks)
        for index in sorted(picks, reverse=True):
            owner.exile.append(owner.graveyard.pop(index))
        # "When this creature enters, exile up to two target cards from a
        # single graveyard. When this creature leaves the battlefield, return
        # **the exiled cards** to their owner's graveyard." (Gravegouger.)
        # CR 607.2a links the two abilities, so the cards are recorded as
        # exiled *with* the permanent whose ability exiled them — the record
        # the second ability drains (`put_exiled_with_source`). Linked whenever
        # a permanent did the exiling, for the reason every other exile-with-
        # a-source handler gives: nothing ends the link on its own (no
        # ``ends_on``), so it is inert for Rysorian Badger, which never asks,
        # and everything for a card whose other ability does. A spell has no
        # permanent and links nothing.
        #
        # **The object, not its id.** A source that left the battlefield
        # before this resolved has already had its leaves-the-battlefield
        # trigger find an empty pile, so these cards are exiled for good —
        # the old-style Oblivion Ring reading (Mesmeric Fiend's ruling,
        # 2018-03-16, of the same two triggers). The record lands on an
        # object nothing reads again, which is that outcome.
        context = choice.data.get("_context")
        source = getattr(context, "source_permanent", None)
        if source is not None:
            for card in taken:
                link_exiled_card(source, card, int(choice.data["owner_index"]))
        self._record_graveyard_exile(choice, taken)
        self.log.append(
            f"{self.players[choice.player_index].name} exiled "
            + (", ".join(card.name for card in taken) or "nothing")
            + f" from {owner.name}'s graveyard "
            f"({choice.data.get('card_name', 'an effect')})"
        )
        return True

    def _bottom_graveyard_pick(
        self, choice: PendingChoice, owner, picks: list[int]
    ) -> bool:
        """Put the validated *picks* on the bottom of *owner*'s library.

        "…unless you put two cards from your graveyard on the bottom of your
        library." (Gurzigost.) In the order the seat named them, through the
        library seam (CR 903.9b rides it), and then CR 401.4's order is
        offered to the owner when two or more went down together — the
        ordinary ``reorder_library`` prompt pointed at the bottom, which asks
        an interactive seat only, so a headless or AI seat keeps the order it
        named and consumes nothing.
        """
        cards = [owner.graveyard[index] for index in picks]
        for index in sorted(picks, reverse=True):
            owner.graveyard.pop(index)
        moved = [card for card in cards if self.put_card_into_library(owner, card)]
        self.discard_pending_choice(choice)
        self.log.append(
            f"{self.players[choice.player_index].name} put "
            + (", ".join(card.name for card in moved) or "nothing")
            + f" from {owner.name}'s graveyard on the bottom of their library "
            f"({choice.data.get('card_name', 'an effect')})"
        )
        self.offer_library_bottom_order(owner, len(moved))
        return True

    def _default_graveyard_exile_pick(self, choice: PendingChoice) -> None:
        """The stated "up to N" policy: the maximum, in pile order.

        Taking cards out of an opponent's graveyard costs the seat nothing —
        this is a gift under "take gifts, pay tolls, make no trades" — and pile
        order is seed-deterministic, which is what AI and headless play need. A
        seat that should pick cleverly needs a weight in
        ``engine/ai_valuation.py``, not a branch here.

        One such weight, for another seat's pile: the cards their owner could
        still cast from there go first (``ai_valuation.graveyard_denial_order``
        — a flashback card is a spell that seat still holds). A pile with none
        is taken in pile order exactly as before.

        And its mirror for the seat's **own** pile, where every pick in the
        pool is a price or a forced loss — an offer's ("any player may exile a
        card from their graveyard", Carrion Rats), a toll's (Rotting Giant,
        Gurzigost's bottom of the library), an "if you do" (Ichorid), a
        replacement's (Nefarious Lich), an upkeep's (Decaying Soil): the least
        valuable first (``ai_valuation.graveyard_price_order``). Pile order
        gave up whatever sat at the bottom, a flashback spell as soon as a
        land (Torment's W2G3).
        """
        live = self.live_graveyard_exile_candidates(choice)
        owner_index = int(choice.data["owner_index"])
        if owner_index != choice.player_index:
            from ....ai_valuation import graveyard_denial_order

            live = graveyard_denial_order(self, owner_index, live)
        else:
            from ....ai_valuation import graveyard_price_order

            live = graveyard_price_order(self, owner_index, live)
        wanted = self._how_many_graveyard_cards(choice)
        if not self._resolve_graveyard_exile_pick(choice, live[:wanted]):
            self._record_graveyard_exile(choice, [])

    # -- Which graveyard "a single graveyard" means --------------------------

    def graveyard_piles_with_a_legal_card(self, payload: dict) -> list[int]:
        """The seats whose graveyard holds a card the printed phrase admits.

        The rule rather than the list, for ``arm_graveyard_exile_pick``'s
        reason: a pile offered here is a pile the pick will then be re-checked
        against, and two readings of "which cards does this phrase name" is
        exactly the drift ``graveyard_card_matches`` exists to stop.
        """
        from ....handlers._common import graveyard_card_matches

        return [
            seat for seat, player in enumerate(self.players)
            if any(graveyard_card_matches(payload, card)
                   for card in player.graveyard)
        ]

    def arm_graveyard_pile_choice(
        self, player_index: int, payload: dict, context
    ) -> None:
        """Queue "which graveyard?" for "exile … from **a single** graveyard".

        A prompt of its own rather than a wider ``graveyard_exile_pick``,
        because the two questions have different answers and different
        candidate rules — and because answering this one *arms* that one, which
        is how a chain of decisions stays a single resolution (CR 608.2): the
        stack object stays put until the last prompt of the chain is answered.
        """
        self.arm_pending_choice(
            "graveyard_pile_choice", player_index,
            card_name=context.card.name,
            seats=self.graveyard_piles_with_a_legal_card(payload),
            _payload=dict(payload),
            _context=context,
        )

    def live_graveyard_pile_choices(self, choice: PendingChoice) -> list[int]:
        """The offered piles that are still legal answers.

        Recomputed rather than trusted: a card can leave a graveyard between the
        offer and the answer (another player's effect in response), and a pile
        that no longer holds a card the phrase names is a pile the pick behind
        this would find empty.
        """
        offered = set(choice.data.get("seats") or ())
        return [
            seat
            for seat in self.graveyard_piles_with_a_legal_card(
                dict(choice.data.get("_payload") or {})
            )
            if seat in offered
        ]

    def confirm_graveyard_pile_choice(self, player_index: int, seat) -> bool:
        return self.resolve_pending_choice(
            "graveyard_pile_choice", player_index, seat=seat
        )

    def _resolve_graveyard_pile_choice(self, choice: PendingChoice, seat) -> bool:
        live = self.live_graveyard_pile_choices(choice)
        context = choice.data.get("_context")
        if not live:
            # Every offered pile has been emptied of legal cards while this was
            # owed. The sentence carries on having exiled nothing rather than
            # staying owed a prompt with no answer — and both record keys are
            # written, because an *absent* key is a back-reference with no
            # producer, a different thing from a producer that took nothing.
            if context is not None:
                context.results[EXILED_THIS_WAY_OBJECTS] = []
                context.results[EXILED_THIS_WAY] = 0
            self.discard_pending_choice(choice)
            return True
        if not isinstance(seat, int) or seat not in live:
            return False
        payload = dict(choice.data.get("_payload") or {})
        self.discard_pending_choice(choice)
        self.log.append(
            f"{choice.data.get('card_name', 'An effect')}: chose "
            f"{self.players[seat].name}'s graveyard"
        )
        # The second half of the chain, armed by the answer to the first. The
        # prompt this queues stamps the same resolving stack object, so the
        # object stays on the stack and no step advances until it too is
        # answered.
        self.arm_graveyard_exile_pick(
            choice.player_index, seat, payload, context
        )
        return True

    def _default_graveyard_pile_choice(self, choice: PendingChoice) -> None:
        """The stated policy: the first live pile **that is not the chooser's
        own**, in seat order — and its own only when no other is live.

        This prompt is armed by one sentence, "exile … from a single
        graveyard", and exiling is denial. The policy was "the first live pile
        in seat order", stated as "not a valuation" — and it was one all the
        same, a different one per chair: the seat at index 0 exiled its own
        graveyard and the seat at index 1 its opponent's, over the same board
        (Decompose, Rapid Decay, Ebony Charm, Carrion Beetles, Famished
        Ghoul). Which pile a seat denies is
        ``ai_valuation.denied_graveyard_pile``; still seat order within it,
        so it is as seed-deterministic as it was.
        """
        from ....ai_valuation import denied_graveyard_pile

        live = self.live_graveyard_pile_choices(choice)
        seat = denied_graveyard_pile(choice.player_index, live)
        if seat is None or not self._resolve_graveyard_pile_choice(choice, seat):
            context = choice.data.get("_context")
            if context is not None:
                context.results[EXILED_THIS_WAY_OBJECTS] = []
                context.results[EXILED_THIS_WAY] = 0
            self.discard_pending_choice(choice)
