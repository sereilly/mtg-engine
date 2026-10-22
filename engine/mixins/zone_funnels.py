"""The doors between zones: every way a card reaches a hand, a library or a graveyard, and onto the battlefield.

Each is one function because each is a rule with no single fire site. CR
903.9b is a replacement over "would be put into its owner's hand or library
from anywhere" - a bounce, a tuck, a regrowth and a draw - so every such move
goes through ``put_card_into_hand`` / ``put_card_into_library``; "if a card
would be put into your graveyard from anywhere" is ``put_card_into_graveyard``;
and CR 614.6 for a permanent on its way off the battlefield is
``_leaving_battlefield_replaced``. A permanent returned to a hand is counted
on the way (``_announce_permanent_returned_to_hand``).

The departures are doors too: ``take_card_from_hand`` and
``take_card_from_exile`` remove exactly **one** copy, by identity, because a
deck repeats one immutable definition per copy and an identity filter removes
them all; the exile door also retires the record the departing card carried
(``engine/exiled_records.py``). Linked exile's way back
(``leave_linked_exile`` / ``return_linked_exile``, CR 610.3) and
``exile_hand_slots`` are built on them.

And the one entry path onto the battlefield, ``_enter_battlefield``, wrapped
by ``_put_permanent_onto_battlefield`` in one CR 603.3b window so the
entering permanent's triggers and every observer's go on the stack together.
"""

from __future__ import annotations

from ..cast_permissions import end_while_exiled_grants
from ..continuous import next_timestamp
from ..control import set_base_controller
from ..enter_effects import CAST_THIS_TURN_STAMP
from ..exiled_records import (forget_record, newest_record_for,
                              record_exiled_card)
from ..events import emit
from ..faces import whole_card
from ..models import Permanent, PlayerState, next_permanent_id
from ..oracle_types import EVENT_SUBJECT_LAST_KNOWN, EXILED_BY_SEAT
from ..replacements import apply_replacements
from ..replacements.permanents import apply_entry_riders
from ..tokens import is_token_card


class ZoneFunnelsMixin:
    # -- the two zones CR 903.9b intercepts ---------------------------------
    #
    # Every "put this card into a hand / a library" in the engine goes through
    # one of these two. That is not tidiness: CR 903.9b is a replacement over an
    # event with no single fire site — a bounce, a tuck, a regrowth and a draw
    # are all "would be put into its owner's hand or library from anywhere" —
    # and a rule with thirty possible fire sites is a rule twenty-nine of them
    # forget. Outside a Commander game both are a plain append, so nothing else
    # changes shape.

    def _owner_seat(self, owner) -> int:
        """A seat index from either a seat index or a ``PlayerState``. Both
        spellings reach these seams from call sites that already hold one or the
        other, and converting at the boundary is cheaper than making every
        caller convert.

        By **identity**, not ``list.index``. ``PlayerState`` is a plain
        ``@dataclass``, so its generated ``__eq__`` compares field by field and
        two seats that happen to match — the pregame board, a test's two fresh
        players, an emptied-out endgame — answer the *first* of them. Every seam
        that converts here then writes to the wrong player's zone, which is the
        look-alike bug ``tests/engine/test_control_reads.py`` documents one zone
        over, arriving through the seat rather than through the object.
        """
        if isinstance(owner, int):
            return owner
        for seat, player in enumerate(self.players):
            if player is owner:
                return seat
        raise ValueError(f"{getattr(owner, 'name', owner)!r} is not in this game")

    def take_card_from_hand(self, owner, card) -> bool:
        """Remove **one** copy of *card* from *owner*'s hand. True if it was there.

        The mirror of ``put_card_into_hand``, and it exists because the obvious
        spelling is wrong. A hand is a ``list[CardDefinition]`` and a deck is
        built by repeating one definition — ``deck.extend([card] * count)`` in
        ``web/deck_builder.py``, and the same in the AI simulator — so every
        copy of a card in a hand is *the same Python object*. That makes
        ``player.hand = [c for c in player.hand if c is not card]`` remove all
        of them, and the caller then puts exactly one somewhere: the rest cease
        to exist.

        ``engine/phases/upkeep_step.py`` documents the same bug found in a
        graveyard (Nether Shadow: five cards in, four out) and fixed there by
        carrying the index. Five more sites had it in hands — Sylvan Library's
        "put the card on top of your library", a forced discard, two discard
        costs and a put-onto-the-battlefield — all invisible until a deck held
        two copies of one card *and* one of those effects fired. The AI
        simulator's fixed eight-card decklist could reach neither half.

        Removing by index is what makes it exactly one, and identity is what
        picks the index: ``list.remove`` and ``list.index`` compare by value,
        which on a frozen dataclass means two different printings of one card
        would match each other.
        """
        player = self.players[self._owner_seat(owner)] if isinstance(owner, int) else owner
        for index, held in enumerate(player.hand):
            if held is card:
                del player.hand[index]
                return True
        return False

    def take_card_from_exile(self, owner, card, *, record=None) -> bool:
        """Remove **one** copy of *card* from *owner*'s exile. True if it was there.

        Leaving exile is one transition (CR 406.2 read backwards), for the
        reason leaving the battlefield and leaving a hand are: something has to
        happen when a card goes, and thirteen open-coded departures are thirteen
        places to forget it — ten of which had. What has to happen here is the
        exile register
        (``engine/exiled_records.py``): a record keyed on the exiled *object*
        carries its counters, its face-down flag and who may look at it, and its
        liveness is derived from the pile rather than maintained.

        Derivation makes a stale record inert but not gone, and CR 400.7 is
        exactly the rule that breaks: a card that changes zones becomes a new
        object "with no memory of, or relation to, its previous existence", and
        CR 406.7 says the same of a card re-exiled out of exile. A record left
        behind is that memory — the *next* effect to exile the same card finds
        it live again and hides a card nobody exiled face down, or hands it
        counters nobody put there. Retiring the record here is what makes the
        derivation one-way.

        Removing by index is what makes it exactly one, and **identity** is what
        picks the index. ``list.remove``/``list.index`` compare by value, and
        four of the sites this replaced spelled it that way: two printings of
        one card are equal-looking objects, and the same ``CardDefinition`` can
        sit in two seats' exiles at once (a deck repeats one immutable
        definition per copy and the catalog is shared), so the value spelling
        reaches a look-alike. That is the bug class
        ``tests/engine/test_control_reads.py`` was written for, one zone over.

        *record* is the :class:`~engine.exiled_records.ExiledRecord` the caller
        already holds — the upkeep trigger that fires *for* a record knows which
        one it is finishing with, which is stronger than any derivation, and a
        named record is retired whether or not a card was found (the caller is
        saying it is done with it). Left off, the newest live record for this
        seat and card is retired, and only when a card actually left.
        """
        seat = self._owner_seat(owner)
        player = self.players[seat]
        # Both reads happen before the removal: liveness is derived from the
        # pile, so a record asked for afterwards answers None in exactly the
        # case that needs retiring.
        doomed = record if record is not None else newest_record_for(self, seat, card)
        for index, held in enumerate(player.exile):
            if held is card:
                del player.exile[index]
                if doomed is not None:
                    forget_record(self, doomed)
                # …and what "for as long as it remains exiled" granted over it
                # (CR 611.2b), for the record's own reason one line up: a grant
                # left behind is a memory CR 400.7 says the card does not have.
                end_while_exiled_grants(self, seat, card)
                return True
        if record is not None:
            forget_record(self, record)
        return False

    def put_card_into_hand(self, owner, card, *, from_battlefield=None) -> bool:
        """Put *card* into its owner's hand, unless something diverts it.

        Returns True when the card actually arrived. False means it was a token
        and ceased to exist (CR 111.7), it went to the command zone instead
        (CR 903.9b), a CR 614 replacement sent it somewhere else, or it is
        waiting on its owner's answer and is in no zone until then — in every
        case the caller must not also record a card arriving in hand.

        *from_battlefield* is the :class:`Permanent` this card is the card
        **of**, when it is arriving here by leaving the battlefield. It is what
        makes a leaves-the-battlefield replacement (CR 614.6) expressible: this
        seam is handed a ``CardDefinition``, which a deck shares between every
        copy of a card, so the event cannot be keyed to the card — only to the
        object that is leaving. A caller that moves a permanent and does not
        pass it is a hole in that event, which is why
        ``tests/engine/test_leave_battlefield_seam.py`` asks for it.
        """
        seat = self._owner_seat(owner)
        # CR 709.4: everywhere but the stack a split card is the whole card. A
        # spell's card is its *half* (``engine/faces.py``), so the three zone
        # seams are where it becomes one card again — asked here rather than at
        # each place a spell can be sent, which is the reason these are seams.
        card = whole_card(card)
        if is_token_card(card):
            # CR 111.7's own parenthesis: "if a token changes zones, applicable
            # triggered abilities will trigger before the token ceases to
            # exist." A bounced token *is* returned to its owner's hand — it is
            # the state-based action that then removes it — so the move is
            # announced even though no card is left to record.
            self._announce_permanent_returned_to_hand(from_battlefield, seat)
            return False  # CR 111.7 / 704.5d: it ceases to exist instead
        if self._leaving_battlefield_replaced(from_battlefield, owner, "hand"):
            return False
        if self.commander_zone_change(seat, card, "hand"):
            return False
        self.players[seat].hand.append(card)
        self._announce_permanent_returned_to_hand(from_battlefield, seat)
        return True

    def _announce_permanent_returned_to_hand(self, permanent, seat: int) -> None:
        """Announce a permanent moving from the battlefield to a hand
        ("whenever a permanent is returned to a player's hand", Warped
        Devotion).

        **Here because this is the one place both halves are known.** Leaving
        the battlefield is one transition (``remove_from_battlefield``) and
        where the card goes next is its caller's business; arriving in a hand
        is this seam, and what the card came *from* is its ``from_battlefield``
        argument. A bounce spell, a gating creature's entry trigger, a land
        returned as a cost, an upkeep "return a creature" and a sweep all meet
        only here, so an announcement at any one of them is an announcement the
        others forget.

        Nothing is announced where no permanent was named — a card drawn, or
        returned from a graveyard, reaches a hand without anything having been
        *returned from the battlefield* — and nothing where the move did not
        happen: a commander diverted to the command zone (CR 903.9b) or a
        CR 614 replacement that sent the permanent elsewhere was not returned
        to a hand, and the two early returns above are those cases.

        Made **before** the caller takes the permanent off the battlefield,
        which is CR 603.10a's look-back spelled as an order of operations: the
        noun phrase is asked of the permanent as it last existed there, and a
        watcher returned by the same effect is still on the battlefield to see
        it — and to see itself.

        *seat* is the hand's — the owner's (CR 400.3) — frozen as the seat the
        event is about, because "that player" has nothing else to mean by the
        time the ability resolves.

        **And it is counted here**, for the same reason it is announced here.
        "If a permanent was put into your hand from the battlefield this turn"
        (Barrin, Tolarian Archmage) reads ``permanents_to_hand_this_turn``,
        which two of this seam's callers bumped by hand and the rest did not:
        a bounce spell counted, and a land returned by Storm Cauldron, an
        artifact swept up by Hurkyl's Recall, a creature returned as a cost, a
        Firestorm Phoenix that would have died and a Rakalite at the end step
        did not. One writer, where every one of them already meets.

        A **token** counts, which the hand-written bumps had the other way
        round: "If a token is returned to your hand, it's put there before it
        ceases to exist" (Barrin's ruling, 2020-06-23) — the move happened,
        which is why this is reached for one at all.
        """
        if permanent is None:
            return
        from ..events import emit

        self.permanents_to_hand_this_turn[seat] = (
            self.permanents_to_hand_this_turn.get(seat, 0) + 1
        )

        emit(
            self, "permanent_returned_to_hand",
            subject=permanent,
            seat=seat, event_subject_player=seat,
            event_subject_permanent_id=getattr(permanent, "permanent_id", None),
            event_subject_name=permanent.effective_card.name,
        )

    def put_card_into_library(
        self, owner, card, position: str = "bottom", *, from_battlefield=None
    ) -> bool:
        """Put *card* into its owner's library, unless something diverts it.
        ``position`` is "top" or "bottom"; the return value and
        *from_battlefield* read as :meth:`put_card_into_hand`'s do."""
        seat = self._owner_seat(owner)
        card = whole_card(card)  # CR 709.4 — see ``put_card_into_hand``
        if is_token_card(card):
            return False  # CR 111.7 / 704.5d: it ceases to exist instead
        if self._leaving_battlefield_replaced(from_battlefield, owner, "library"):
            return False
        if self.commander_zone_change(seat, card, "library"):
            return False
        library = self.players[seat].library
        if position == "top":
            library.insert(0, card)
        else:
            library.append(card)
        return True

    def put_card_into_graveyard(
        self, owner, card, *, from_zone=None, from_battlefield=None
    ) -> bool:
        """Put *card* into *owner*'s graveyard, unless something diverts it.

        *from_zone* is the zone it came out of, named only where a card says
        the words. "When this card is put into your graveyard **from your
        library**" (Gaea's Blessing) is a trigger no permanent can ever fire
        (CR 113.6k), so nothing on the battlefield can be scanned for it and
        the announcement has to happen where the move does. Optional and
        defaulting to None because the seam has twenty-six callers and only the
        library ones have a card watching: an unnamed source zone announces
        nothing, which is what every caller meant before the words existed.

        The third of the zone seams, and it exists for the reason CR 903.9b gave
        the first two: "if a card would be put into your graveyard **from
        anywhere**" (Forbidden Crypt) has no single fire site — a death, a
        discard, a mill, a spell finishing on the stack and a sacrifice are all
        the same event — and twenty-six fire sites is twenty-five places to
        forget it.

        Returns True when the card actually arrived. False means a CR 614
        replacement sent it somewhere else, and every caller must read it the
        way they read :meth:`put_card_into_hand`'s: do not also record a card
        reaching the graveyard.

        The seat is the caller's, not derived. CR 400.3 sends a card to its
        *owner's* graveyard and almost every caller has already worked that out
        — but an ownership exchange (Bazaar of Baghdad's family) deliberately
        files a card under the player who now owns it, and deriving the seat
        here would quietly undo that.

        No token guard, unlike the hand and library seams: CR 111.7 does put a
        token into the graveyard before the state-based action makes it cease to
        exist, and the one path that moves a dying permanent's card
        (:meth:`_permanent_to_graveyard`) already keeps a token's card out. A
        guard here would be a second, differently-worded answer to a question
        that already has one.
        """
        seat = self._owner_seat(owner)
        card = whole_card(card)  # CR 709.4 — see ``put_card_into_hand``
        # *from_battlefield* is the :class:`Permanent` this card is the card
        # **of**, when it is arriving here by leaving the battlefield — the
        # argument the hand and library seams already take, for the reason they
        # give: the seam is handed a shared ``CardDefinition``, and an effect
        # about *this object's own* move ("If Legacy Weapon would be put into a
        # graveyard from anywhere…") has to read the object as it last existed
        # (CR 613: a copy of it has the sentence, and one that lost its
        # abilities does not). It rides the event; nothing here reads it.
        consumed, _ = apply_replacements(
            self,
            "put_into_graveyard",
            {
                "player": self.players[seat], "card": card,
                "from_zone": from_zone, "permanent": from_battlefield,
            },
        )
        if consumed:
            return False
        self.players[seat].graveyard.append(card)
        # "…**that were put there from the battlefield this turn**" (No Rest
        # for the Wicked). Recorded on the one seam every arrival passes
        # through, keyed by the pile it landed in (CR 400.3's owner) — the same
        # place the exile replacement and the arrival event are, because "from
        # the battlefield" is a fact about *this* move and nothing in the
        # graveyard afterwards remembers it. A token never gets here: the
        # permanent path keeps its card out (CR 111.7), which is the difference
        # between this record and the tally beside it.
        if from_zone == "battlefield":
            self.players[seat].cards_put_into_your_graveyard_from_battlefield_this_turn.append(card)
        # Announced **after** the card has arrived, because CR 603.6 has a
        # zone-change trigger look for its object in the zone it moved to — and
        # a replacement that diverted the card returned above, so nothing fires
        # for a card that never got here.
        if from_zone == "library":
            emit(
                self, "self_put_into_graveyard_from_library",
                subject=card, owner_index=seat,
            )
        # "When a card is put into **your** graveyard from anywhere" (Energy
        # Field), "whenever **another** card is put into a graveyard from
        # anywhere" (Planar Void), "when **this creature** is put into a
        # graveyard from anywhere" (Serra Avatar). **One** announcement for all
        # three, which is the whole reason this seam exists: "from anywhere" has
        # no single fire site — a death, a discard, a mill, a sacrifice and a
        # spell finishing on the stack are all this event — and a fire site per
        # spelling is twenty-five places to forget it. It is the same argument
        # CR 903.9b makes for the replacement one screen up.
        #
        # Unscoped by source zone, which is what "from anywhere" says. Every
        # narrowing the three sentences print rides as *data* and is tested by
        # the watcher's own filter: whose graveyard it is comes off the seat,
        # and "another" is a comparison between the moved card and the observer.
        #
        # The card also rides as ``dead_card`` because that is the one channel
        # "that card" already reads (`lowering/_deaths.py`'s BOUND_CARD_EVENTS,
        # `exile_bound_card`). A second key for the same referent is how one
        # printed phrase ends up with two answers.
        #
        # **Two branches of USG's wave 2 each added one of these emits**, and
        # the merge kept both — so every card put into a graveyard announced
        # itself twice and every watcher triggered twice. Nothing textual can
        # see that: both statements are correct, and it is having two of them
        # that is wrong. One emit, whose payload is the union of what the three
        # sentences need.
        emit(
            self, "card_put_into_graveyard",
            subject=card, owner_index=seat, dead_card=card,
            graveyard_from_zone=from_zone,
        )
        return True

    def _leaving_battlefield_replaced(self, permanent, owner, destination: str) -> bool:
        """CR 614.6 for a permanent on its way off the battlefield — whether a
        replacement sent it somewhere other than *destination*.

        Asked **at the destination**, not at ``remove_from_battlefield``, and
        that is the whole design. The removal is the one transition every exit
        passes through, but it decides no destination: the caller does, one
        statement later, and a replacement fired at the removal would have to
        suppress that caller. Asked here the event is complete — what is
        leaving, and where it was going — and a consumed event simply returns
        False, which every caller of these two seams already reads as "the card
        did not arrive; do not record one".

        The three destinations a permanent's card can reach are a graveyard, a
        hand and a library, and each has exactly one seam:
        ``_permanent_to_graveyard`` asks this too. **Exile is deliberately not
        one of them**: a permanent already on its way to exile is a permanent
        already going where "exile it instead" would send it, so there is
        nothing to replace and firing here would exile the card twice.
        """
        if permanent is None:
            return False
        consumed, _ = apply_replacements(
            self, "would_leave_battlefield",
            {
                "player": owner if isinstance(owner, PlayerState)
                else self.players[self._owner_seat(owner)],
                "permanent": permanent,
                "destination": destination,
            },
        )
        return bool(consumed)

    def exile_hand_slots(
        self, context, source, seat: int, slots: list[int],
        *, face_down: bool = False,
    ) -> list:
        """Exile the cards in *seat*'s hand at *slots* as one linked pile.

        The shared half of "exile all cards from your hand face down"
        (Duplicity) and "exile any number of cards from your hand face down"
        (Scroll Rack): a sweep and a pick end in the same act, and the act has
        three things it must not forget — the hand seam, the linked-exile
        record, and the two scratchpad keys the sentences behind it read. One
        function so all three cannot be remembered in one place and forgotten
        in the other, which is the ``become_tapped`` shape this repo names.

        Through ``take_card_from_hand``: a deck repeats one immutable
        definition per copy, so every copy of a card in a hand is the *same*
        Python object and an identity filter over the list removes all of them.

        The cards are resolved from their slots **before anything moves**,
        because each removal renumbers the ones behind it — and then taken and
        linked in the seat's own hand order, so the pile reads the way the hand
        did rather than backwards.

        Two records, both about the same cards and neither redundant.
        ``exiled_cards`` is what a count behind this reads ("put **that many**
        cards from the top of your library into your hand"); ``exiled_entries``
        is what an *exclusion* behind it reads ("put **all other** cards … into
        your hand"), and only the entries can answer that — the pile may
        already hold another copy of the same card, and the cards are the same
        object.
        """
        from ..linked_exile import link_exiled_card

        player = self.players[seat]
        wanted = [
            player.hand[index] for index in sorted(slots)
            if 0 <= index < len(player.hand)
        ]
        taken = []
        entries = []
        for card in wanted:
            # Through the hand seam: a deck repeats one immutable definition
            # per copy, so every copy of a card in a hand is the same Python
            # object and this removes exactly one of them.
            self.take_card_from_hand(player, card)
            player.exile.append(card)
            taken.append(card)
            if source is not None:
                entries.append(
                    link_exiled_card(source, card, seat, face_down=face_down)
                )
            if face_down and (source is None or not self.is_on_battlefield(source)):
                # CR 406.3 needs a record somebody can still *find*. A spell
                # has no permanent to hold one ("Target player exiles all
                # cards from their hand face down", Suppress), and a permanent
                # that paid for the ability with itself is not on a battlefield
                # to be scanned ("{T}, Sacrifice this artifact: Each player
                # exiles all cards from their hand face down", Memory Jar) — so
                # for both the fact goes on the game's register, which is
                # `exile_top_of_library`'s arrangement for Three Wishes. Without
                # it the pile was face up to every viewer for as long as it
                # stayed exiled, which for Memory Jar was always.
                #
                # Only when the link cannot be seen: `face_down_exiled_cards`
                # counts both registers, and a card recorded on each would hide
                # a second, face-up copy of itself.
                record_exiled_card(self, card, seat, face_down=True)
        if context is not None:
            context.results.setdefault("exiled_cards", []).extend(taken)
            context.results.setdefault("exiled_entries", []).extend(entries)
            # …and the same cards keyed by **seat**, which is a fourth question
            # and the one "each player … returns to their hand each card
            # **they** exiled this way" (Memory Jar) asks. The flat list cannot
            # answer it: read once per player it would hand every seat the whole
            # table's hands. Seeded for this seat even when it exiled nothing,
            # for the reason the graveyard sweep seeds its own — a seat the map
            # never mentioned falls through to a `.get` default, and the honest
            # default for "what did this player exile" is an empty pile rather
            # than somebody else's. Written here rather than in the one caller
            # that needs it, because the seat is this function's own parameter
            # and a record kept in one of two callers is the shape this file
            # exists to prevent.
            by_seat = context.results.setdefault(EXILED_BY_SEAT, {})
            by_seat.setdefault(seat, []).extend(taken)
            # …and the *number*, which is a third question and the one "put
            # that many cards from the top of your library into your hand"
            # (Scroll Rack) asks. Its own key because a bare back-reference
            # resolves against quantities alone — a list handed to one would
            # make "that many" name a pile.
            context.results["exiled_count"] = (
                int(context.results.get("exiled_count") or 0) + len(taken)
            )
        self.log.append(
            f"{player.name} exiled {len(taken)} card(s) from their hand"
            if taken else f"{player.name} exiled no cards from their hand"
        )
        return taken

    def leave_linked_exile(
        self, entry: dict, zone: str, *, controller_index: int | None = None
    ) -> "Permanent | None":
        """Take one linked-exile entry's card out of exile and into *zone*.

        *controller_index* is the seat a **battlefield** arrival enters under
        (CR 110.2a: the player the effect instructed to put it there). It
        defaults to the card's owner, which is what every automatic return means
        — those give a card back to where it came from — and is passed only by
        an effect whose printed sentence names no owner, "return a card exiled
        with this enchantment to the battlefield" (Purgatory). Ownership never
        moves either way (CR 108.3), so the card goes back to its owner's
        graveyard when it next dies.

        The one placement both readers of the record share: the automatic
        return below, and the ``put_exiled_with_source`` handler that Knowledge
        Vault's two linked abilities compile to. Returns the arriving
        ``Permanent`` for a battlefield destination and None otherwise; None
        also means the card was not in exile to move, which is CR 608.2b doing
        as much as possible rather than creating a card from nowhere.

        A hand or a library goes through ``put_card_into_hand`` /
        ``put_card_into_library`` rather than appending, because CR 903.9b has
        no single fire site and this is one more of the places that would have
        forgotten it. Out of exile through ``take_card_from_exile`` for the
        matching reason on the other side — and because ``card not in
        owner.exile`` followed by ``.remove(card)`` is the value comparison that
        finds a look-alike printing rather than the card this entry recorded.
        """
        owner_index = int(entry["owner_index"])
        owner = self.players[owner_index]
        card = entry["card"]
        if not self.take_card_from_exile(owner_index, card):
            return None
        if zone == "hand":
            self.put_card_into_hand(owner, card)
            return None
        if zone == "library":
            self.put_card_into_library(owner, card)
            return None
        if zone != "battlefield":
            getattr(owner, zone).append(card)
            return None
        arrival = Permanent(card=card)
        seat = owner_index if controller_index is None else int(controller_index)
        if seat != owner_index:
            # The base controller and the owner differ, which is the one fact
            # `_put_permanent_onto_battlefield` cannot re-derive: it is handed a
            # seat and takes it for both. Recorded for `reanimate_bound_card`'s
            # reason — everywhere else in this pool the two coincide, so the
            # only thing that could say otherwise is the write that made them
            # differ.
            arrival.metadata["owner_player_index"] = owner_index
        self._put_permanent_onto_battlefield(seat, arrival, None)
        if entry.get("tapped"):
            arrival.tapped = True
        if entry.get("counters"):
            from ..handlers.linked_exile import restore_noted_counters

            restore_noted_counters(self, arrival, entry["counters"])
        return arrival

    def return_linked_exile(self, permanent: Permanent, why: str, ending: str) -> None:
        """Give back everything *ending* gives back of what was exiled with
        ``permanent`` (CR 400.7, 610.3).

        Two callers, because two things can end a linked exile: the permanent
        leaving the battlefield (Kitesail Freebooter, Idol of Endurance) and —
        Tawnos's Coffin alone — the permanent becoming untapped. One function
        because the unwinding is identical and the difference is only what says
        the word.

        *ending* is which of the two happened, and it is matched against the
        entry's own ``ends_on`` rather than assumed: only a card exiled by an
        ability that printed "or becomes untapped" comes back for an untap.
        Without that test the untap caller ended every linked exile in the
        game, and Idol of Endurance — which taps for its own ability — dumped
        its whole pile into the graveyard at the next untap step.
        """
        from ..linked_exile import take_linked_entries

        entries = take_linked_entries(permanent, ending=ending)
        returned: Permanent | None = None
        for entry in entries:
            owner = self.players[int(entry["owner_index"])]
            card = entry["card"]
            # Back to the zone it was taken from. Kitesail Freebooter takes from
            # a hand, Idol of Endurance from a graveyard and Tawnos's Coffin
            # from the battlefield, and a card returned to the wrong one is a
            # card the effect created out of nothing — so the origin rides the
            # entry rather than being a constant here.
            destination = str(entry.get("to", "hand"))
            if card not in owner.exile:
                continue
            arrival = self.leave_linked_exile(entry, destination)
            if arrival is None:
                self.log.append(
                    f"{card.name} returns to {owner.name}'s {destination} "
                    f"({permanent.card.name} {why})"
                )
                continue
            # "…**attached to that permanent**" — the Auras go back onto the
            # creature the entry before them brought back, which is why they
            # travel in one record and in printed order. Nothing to attach to
            # means the Aura simply arrives, and CR 704.5n's sweep bins it.
            if entry.get("attach_to_returned") and returned is not None:
                from ..aura_attachment import attach_aura

                attach_aura(arrival, returned)
            else:
                returned = arrival
            self.log.append(
                f"{card.name} returns to the battlefield "
                f"({permanent.card.name} {why})"
            )
        if entries:
            self._recompute_continuous_effects()

    def _put_permanent_onto_battlefield(
        self,
        controller_index: int,
        permanent: Permanent,
        target_player_index: int | None,
        *,
        was_cast: bool = False,
        from_zone: str | None = None,
        played_as_land: bool = False,
    ) -> None:
        """One entry (:meth:`_enter_battlefield`), as one window for CR
        603.3b (``putting_triggers_on_stack``): the entering permanent's own
        "when this enters" and every observer's "whenever a creature
        enters" go on the stack together, and their controller orders them.
        Inside a resolution the resolution's window is the one that asks.
        """
        with self.putting_triggers_on_stack():
            self._enter_battlefield(
                controller_index, permanent, target_player_index,
                was_cast=was_cast, from_zone=from_zone,
                played_as_land=played_as_land,
            )

    def _enter_battlefield(
        self,
        controller_index: int,
        permanent: Permanent,
        target_player_index: int | None,
        *,
        was_cast: bool = False,
        from_zone: str | None = None,
        played_as_land: bool = False,
    ) -> None:
        """Put *permanent* onto the battlefield — the one entry path there is.

        *was_cast* is CR 701.5a's distinction and defaults to the common case:
        of the entry sites in the engine, exactly one is a resolving permanent
        spell, and every other — a token, a reanimation, a cleanup return, an
        effect that puts a card into play — is a permanent that was **not**
        cast. Containment Priest is the first card to ask, and the honest answer
        for a caller that has not thought about it is the one that describes
        what most callers do.

        The default is also the direction that fails *visibly*: a cast creature
        wrongly exiled is a card a player watches disappear, where a reanimation
        wrongly surviving is nothing happening.

        *played_as_land* is the one caller that says ``was_cast`` and does not
        mean it. A land play resolves down the same road a permanent spell does
        (which is what ``was_cast`` tells this method, so the road's own entry
        trigger is not fired twice), and **a land is never cast** (CR 305.1:
        playing a land is a special action). It could not matter while no
        entering land could be a creature; under Living Lands a played Forest
        is one as it enters (CR 614.12), and Containment Priest asks.
        """
        cast_as_a_spell = was_cast and not played_as_land
        # CR 614.12, before anything asks how this permanent enters: a land
        # is judged "as it would exist on the battlefield", under the
        # continuous effects already there. With Blood Moon out a nonbasic
        # land enters as a Mountain that has lost its own abilities (CR 305.7)
        # — the toll the replacement just below charges, "enters tapped" and
        # "enters with … counters" in the entry state, each a static ability
        # of the land (CR 603.6d) it no longer has by then. One write, read by
        # all of them through ``Permanent.effective_card``.
        self.fold_land_type_statics_onto_entering(permanent, controller_index)
        # …and the same rule for every other board-wide static: what the
        # permanent will *be* (a creature under Titania's Song or Opalescence,
        # a Forest that Living Lands animates) and what it will *have* (no
        # ability at all under Humility) once it is there. Asked before the
        # replacements just below and the entry state after them, each of
        # which reads the permanent through the CR 613 accessors.
        judged = self.fold_board_statics_onto_entering(permanent, controller_index)
        # CR 614: "if a nontoken creature would enter … exile it instead"
        # (Containment Priest). Asked before anything else, because a
        # replacement means the permanent never enters at all — no id is
        # stamped, no layer contribution is made, no enters-the-battlefield
        # trigger is announced. A "when it enters, exile it" reading would let
        # every one of those happen first, which is a different card.
        consumed, _ = apply_replacements(
            self,
            "would_enter_battlefield",
            {
                "permanent": permanent,
                "controller_index": controller_index,
                "was_cast": cast_as_a_spell,
                # CR 616.1 asks the *affected* player to choose among contending
                # effects; for an entry that is the seat the permanent would
                # enter under.
                "player": self.players[controller_index],
            },
        )
        if consumed:
            if judged:
                # The fold asked the board's statics about a permanent that
                # then never arrived; what it wrote on everything else is
                # rebuilt from the board as it really is.
                self._recompute_continuous_effects()
            return
        # "…if it **entered from your graveyard**" (Archfiend's Vessel). Stamped
        # on the permanent rather than kept on the game, because the question is
        # asked of one object and a permanent that leaves takes the answer with
        # it (CR 400.7 gives the next one a new identity and a fresh stamp).
        # None means the caller did not say, which reads as "not from anywhere
        # this asks about" — the same defaulting as ``was_cast``, and the same
        # reason: most entries are not from a zone any card asks about.
        if from_zone is not None:
            permanent.metadata["entered_from_zone"] = from_zone
        # "Target creature **you cast this turn**" (Cycle of Life). Beside
        # `entered_from_zone` and for its reason: the question is asked of one
        # object and a permanent that leaves takes the answer with it (CR 400.7
        # gives the next one a new identity and a fresh stamp). *Who* and *when*
        # both, because the phrase asks both — a creature you cast last turn and
        # one your opponent cast this turn are each excluded, and a stamp
        # holding only the turn could not say so.
        #
        # `was_cast` is what makes this different from ENTERED_BATTLEFIELD_TURN
        # one function over: a reanimated creature entered this turn and was
        # never cast (CR 701.5a), which is exactly the creature this phrase does
        # not name.
        if cast_as_a_spell:
            permanent.metadata[CAST_THIS_TURN_STAMP] = {
                "seat": controller_index, "turn": self.turn,
            }
        # CR 400.7: what enters is a *new object*, so it gets a new identity —
        # nothing that held the old id may address it. Stamped before the append
        # so no reader can observe the permanent on the battlefield under an id
        # it is about to lose.
        permanent.permanent_id = next_permanent_id()
        # CR 613.7d, beside the id and for its reason: the object receives its
        # timestamp as it enters the zone, which is what a static ability on it
        # is ordered by (CR 613.7a). Before the append, so no layer read can
        # see the permanent on the battlefield under the stamp it was built
        # with.
        permanent.timestamp = next_timestamp()
        self.players[controller_index].battlefield.append(permanent)
        # "…put a nontoken permanent onto the battlefield" (Arboria, CR 506.3):
        # the per-turn half of the last-own-turn record, folded per seat at the
        # turn boundary (mixins/turn_management.begin_turn_bookkeeping). Here
        # because this is the one entry path there is — a fire site per caller
        # is the pattern that forgot `become_tapped` 41 times.
        if not permanent.metadata.get("is_token"):
            self.nontoken_permanents_entered_this_turn[controller_index] = (
                self.nontoken_permanents_entered_this_turn.get(controller_index, 0) + 1
            )
        # CR 613.1: the value layer 2 starts from. Recorded on entry and never
        # written again, so an ending control effect reverts to the seat that
        # put the permanent into play rather than to whichever seat held it
        # most recently.
        set_base_controller(permanent, controller_index)
        self._initialize_permanent_state(permanent, controller_index, target_player_index)
        # 611.3a/611.3c: static abilities apply as permanents enter. Recalculate
        # lord buffs so the new permanent immediately receives applicable bonuses,
        # and so any new lord immediately buffs existing matching permanents.
        self._recompute_continuous_effects()
        # The "…**then** X" half of an entry replacement (Land Equilibrium's
        # "puts that land onto the battlefield then sacrifices a land"). After
        # the append and after the recompute, because "then" means the new
        # permanent is on the battlefield and is itself a legal choice.
        apply_entry_riders(self, permanent, controller_index)
        # "Whenever a creature you control with power 4 or greater enters"
        # (Garruk's Uprising). Every entry path in the engine — a resolving
        # spell, a token, a reanimation, a cleanup return — comes through this
        # one function, so the announcement is one emit rather than a fire site
        # per path. After the recompute on purpose: a filter about power or type
        # asks what the board makes the permanent, and a lord that applied as it
        # entered is part of that (CR 611.3a).
        emit(
            self, "matching_permanent_enters", subject=permanent,
            # "Whenever a Djinn or Efreet enters, **destroy it**." (Suleiman's
            # Legacy.) The permanent the event was about, frozen by id for the
            # reason the power beside it is frozen: the trigger resolves after
            # the entry, and by then an index is not an identity (CR 400.7) and
            # the permanent may have moved. Under the key every "that <noun>"
            # reading in the engine already goes through, so a fire site taught
            # to freeze its subject reaches all of them at once — and recorded
            # on every entry for `entering_power`'s reason: one integer, against
            # a fire site that would have to know which cards care.
            event_subject_permanent_id=permanent.permanent_id,
            # "…its controller creates a token that's a copy of **that
            # creature**." (Dual Nature.) The object itself beside its id, for
            # CR 608.2h: an effect reading a specific object that has left uses
            # its last-known information, and by resolution the id resolves to
            # nothing (CR 400.7). The Permanent keeps its last battlefield state
            # once it leaves, so it *is* that information — the `dead_card`
            # arrangement one fire site over. One reference, on every entry,
            # for `entering_power`'s reason.
            **{EVENT_SUBJECT_LAST_KNOWN: permanent},
            # "…destroy all other permanents with **that name**." (Eye of
            # Singularity.) CR 201.2's name, frozen for the reason the id and
            # the power beside it are: the trigger resolves after the entry, and
            # a permanent that has left by then is a card in another zone the id
            # no longer resolves to (CR 400.7). Off the **effective** card, so a
            # Clone that entered as something else is swept under the name the
            # board showed (CR 707.2). One string, on every entry, for
            # `entering_power`'s reason.
            event_subject_name=permanent.effective_card.name,
            # "…deals damage equal to **that creature's** power" (Terror of the
            # Peaks). Frozen here rather than read at resolution: the trigger
            # resolves after the entry, and by then the creature may have been
            # pumped, shrunk or destroyed — CR 608.2's number is the one the
            # event had. Recorded on every entry because the cost is one integer
            # and the alternative is a fire site that knows which cards care.
            entering_power=max(0, permanent.effective_power),
            # "…you gain life equal to **its toughness**" (Angelic Chorus). The
            # other characteristic of the same object, frozen for the same
            # reason and at the same moment — a creature that entered under an
            # anthem is worth what the board made it, and by resolution the
            # anthem may be gone or the creature with it. Its own key rather
            # than a widening of the power beside it: two characteristics are
            # two numbers, and a reader handed one for the other is wrong
            # silently on every card whose P and T differ.
            entering_toughness=max(0, permanent.effective_toughness),
            # Whose it is, for "…deals 3 damage to **that player**" (Thelon's
            # Chant, Tourach's Chant, whose printed condition is "whenever a
            # player puts a Swamp onto the battlefield" — the same event named
            # from the player's side). Frozen here, like the power beside it,
            # because CR 603.10 asks what the game knew when the event happened
            # and the permanent may have changed hands by resolution. Recorded
            # on every entry for that key's reason: one seat integer, against a
            # fire site that would have to know which cards care.
            event_subject_controller=controller_index,
        )
        # **And the permanent's own "when this enters" trigger**, for every entry
        # that is not a cast.
        #
        # That trigger was fired from exactly one place — the resolution of a
        # permanent *spell* — so a permanent put onto the battlefield any other
        # way never fired it at all. A reanimated Archfiend's Vessel made no
        # Demon; a Niambi put into play returned nothing. Both reported
        # supported, because the ability compiles perfectly and nothing ran it.
        #
        # The cast path keeps its own call rather than deferring to this one:
        # it has the caster's cast-time target choice to thread through
        # (CR 601.2c), which an entry from a graveyard or a token creation has
        # no equivalent of. ``was_cast`` is what keeps the two from both firing,
        # and it is the same flag CR 701.5a needed for Containment Priest — one
        # fact about an entry, asked by two rules.
        #
        # ``targets_announced=False`` is that "no equivalent" said out loud: a
        # trigger with a target to choose chooses it as it is put on the stack
        # (CR 603.3d). Every trigger goes on the stack either way (CR 603.3) —
        # which, for an entry made during another object's resolution, is
        # *under* that object if a prompt holds it there, and so resolves after
        # it has finished.
        if not was_cast:
            self._apply_self_enters_battlefield_triggers(
                controller_index, permanent, target_player_index, None, None,
                targets_announced=False,
            )
