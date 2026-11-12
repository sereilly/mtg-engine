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
Its entry state is performed with the permanent in no zone (CR 614.12a), and
an entry that leaves a choice owed at a table that holds for answers waits
on its way until the last answer (``engine/entry_awaiting.py``,
``_finish_answered_entries``); a caller acts on the entered permanent through
``then``. Permanents one event puts onto the battlefield enter together
(CR 603.6a): the caller opens the event with ``entering_together`` and every
newcomer is announced with all of them on the battlefield.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable

from ..aura_attachment import attach_aura
from ..cast_permissions import end_while_exiled_grants
from ..continuous import next_timestamp
from ..control import set_base_controller
from ..enter_effects import CAST_THIS_TURN_STAMP
from ..delayed_triggers import end_exhausted_exile_delays
from ..entry_awaiting import (ENTERED, ENTRY_EVENT, ENTRY_OUTCOME,
                              ENTRY_SUSPENDED, REPLACED, DeferredEntry,
                              EntryEvent, EntryInProgress, apnap_order,
                              entered_together, entry_in_progress,
                              entry_is_awaited)
from ..exiled_records import (forget_record, newest_record_for,
                              record_exiled_card)
from ..events import emit
from ..face_down import forget_face_down_departure, revealed_as_it_moves
from ..faces import whole_card
from ..graveyard_order import (distinct_graveyard_object, held_in_a_graveyard,
                               record_arrival_history, record_graveyard_arrival)
from ..linked_exile import forget_linked_entries
from ..models import Permanent, PlayerState, next_permanent_id
from ..oracle_types import EVENT_SUBJECT_LAST_KNOWN, EXILED_BY_SEAT
from ..pending_choices import spec_for
from ..replacements import answered_restart, apply_replacements
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

        ``engine/phases/upkeep_prompts.py`` documents the same bug found in a
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

    def put_card_into_exile(self, owner, card):
        """Put *card* into *owner*'s exile and return **the object the pile
        now holds** — which every caller writes down instead of *card*.

        Arriving in exile is one transition, for the reason leaving it is
        (``take_card_from_exile``): something has to happen at the door. A deck
        repeats one immutable ``CardDefinition`` per copy and the catalog is
        shared between seats, so the copy arriving can be **the same Python
        object** as a copy already exiled — and every record about an exiled
        card names its object: a linked-exile entry (``engine/linked_exile.py``),
        an ``ExiledRecord``, a while-exiled grant, a cast permission, the cards
        a Dimensional Breach's "as long as any of those cards remain exiled"
        counts. Each reader maps the object back to the *first* position
        holding it. With a Breach's face-up Temple and a Parallel Thoughts
        pile's face-down Temple in one exile, the Breach's showed ``<hidden>``,
        the pile's showed by name, and taking the pile's top card took the
        Breach's (Scourge's post-promotion session).

        So **no exile ever holds one object twice**: a card arriving as an
        object some seat's exile already holds arrives as a new, equal object
        (CR 400.7: a card that changes zones becomes a new object; CR 406.7 the
        same for one exiled again). Equal by value — its name, its compile,
        every fold memo (``copies.card_identity``) are the card's — and its own
        by identity, which is the only key every record already uses. Only on a
        collision, so a card exiled alone stays the object everything else
        holds: a commander's designation (CR 903.3, by object) and a caller
        that kept the card it moved still find it. When the copy made is a
        designated commander's, the designation moves to it.

        A record written for the card **before** it lands (an ``ExiledRecord``
        marked ``awaiting_arrival`` — a spell exiling itself is binned at the
        end of its own resolution, CR 608.2n) is bound to the object as it
        lands.
        """
        from ..exiled_records import bind_awaiting_records, distinct_exile_object

        seat = self._owner_seat(owner)
        player = self.players[seat]
        landed = card
        if any(
            held is card for seated in self.players for held in seated.exile
        ):
            landed = distinct_exile_object(card)
            commanders = getattr(player, "commanders", None) or []
            for index, commander in enumerate(commanders):
                if commander is card:
                    commanders[index] = landed
                    break
        bind_awaiting_records(self, seat, card, landed)
        player.exile.append(landed)
        return landed

    def put_cards_into_exile(self, owner, cards) -> list:
        """:meth:`put_card_into_exile` for each of *cards*, in order; the list
        of objects the pile now holds."""
        return [self.put_card_into_exile(owner, card) for card in cards]

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
        one card are equal-looking objects, and the value spelling reaches a
        look-alike. (One object at two exile positions is what
        :meth:`put_card_into_exile` exists to prevent; identity is what lets
        that guarantee mean anything here.) That is the bug class
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
                # …and every linked entry naming it — who exiled it with a
                # permanent that lets them play it (Shared Fate), that it was
                # exiled face down (Necropotence): a record naming an object
                # that left is a memory CR 400.7 says the card does not have.
                forget_linked_entries(self, seat, card)
                # …and a delayed ability lasting "for as long as any of those
                # cards remain exiled" (Dimensional Breach), whose last card
                # this may have been (CR 603.7b, CR 611.2b).
                end_exhausted_exile_delays(self)
                return True
        if record is not None:
            forget_record(self, record)
            end_exhausted_exile_delays(self)
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
        # A face-down object is revealed as it moves the same way (CR 708.9).
        card = whole_card(revealed_as_it_moves(self, card, from_battlefield))
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
        self, owner, card, position: "str | int" = "bottom", *, from_battlefield=None
    ) -> bool:
        """Put *card* into its owner's library, unless something diverts it.
        ``position`` is "top" or "bottom", or a depth from the top — ``3`` is
        "third from the top" (Long-Term Plans), and a library with fewer cards
        above that depth takes the card on the bottom (its 2004-10-04 ruling);
        the return value and *from_battlefield* read as
        :meth:`put_card_into_hand`'s do."""
        seat = self._owner_seat(owner)
        # CR 709.4 and CR 708.9 — see ``put_card_into_hand``.
        card = whole_card(revealed_as_it_moves(self, card, from_battlefield))
        if is_token_card(card):
            return False  # CR 111.7 / 704.5d: it ceases to exist instead
        if self._leaving_battlefield_replaced(from_battlefield, owner, "library"):
            return False
        if self.commander_zone_change(seat, card, "library"):
            return False
        library = self.players[seat].library
        if position == "top":
            library.insert(0, card)
        elif isinstance(position, int) and not isinstance(position, bool):
            library.insert(min(max(position - 1, 0), len(library)), card)
        else:
            library.append(card)
        return True

    def put_card_into_graveyard(
        self, owner, card, *, from_zone=None, from_battlefield=None
    ):
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

        Returns **the object the pile now holds** when the card actually
        arrived — *card* itself, or a new equal object when some graveyard
        already held *card* (below; CR 400.7) — and a caller that writes the
        card down afterwards writes that object down. Always truthy. False
        means a CR 614 replacement sent it somewhere else, and every caller
        must read it the way they read :meth:`put_card_into_hand`'s: do not
        also record a card reaching the graveyard.

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
        # CR 709.4 and CR 708.9 — see ``put_card_into_hand``.
        card = whole_card(revealed_as_it_moves(self, card, from_battlefield))
        # *from_battlefield* is the :class:`Permanent` this card is the card
        # **of**, when it is arriving here by leaving the battlefield — the
        # argument the hand and library seams already take, for the reason they
        # give: the seam is handed a shared ``CardDefinition``, and an effect
        # about *this object's own* move ("If Legacy Weapon would be put into a
        # graveyard from anywhere…") has to read the object as it last existed
        # (CR 613: a copy of it has the sentence, and one that lost its
        # abilities does not). It rides the event; nothing here reads it.
        #
        # CR 616.1e: Legacy Weapon under Forbidden Crypt, or under Yawgmoth's
        # Will's turn, is two effects replacing one move, and the card's owner
        # chooses which applies. The answer can wait because every effect of
        # this kind sends the card somewhere else (CR 614.6): a move that
        # suspends reports False — the card did not arrive — which is what it
        # will be whatever is answered, and the re-run (with the card already
        # whole, so it is not revealed twice) puts it where the answer says.
        event = self.graveyard_event(
            seat, card, from_zone=from_zone, from_battlefield=from_battlefield,
        )
        consumed, _ = apply_replacements(
            self, "put_into_graveyard", event,
            restart=answered_restart(
                self, "put_into_graveyard", event,
                lambda: self.put_card_into_graveyard(
                    seat, card, from_zone=from_zone,
                    from_battlefield=from_battlefield,
                ),
            ),
        )
        if consumed:
            return False
        # **No graveyard ever holds one object twice** — exile's rule
        # (:meth:`put_card_into_exile`), at this zone's one arrival. A deck
        # repeats one immutable ``CardDefinition`` per copy and the catalog is
        # shared between seats, so the copy arriving can be the very object a
        # graveyard already holds — and every record about a card in a
        # graveyard names its object: the "put there from the battlefield this
        # turn" record below, a ``GraveyardTarget``'s stamp, CR 613.7d's
        # arrival stamps, a flashback grant (Recoup), "that card" on a dies
        # trigger. With one object at two positions each of them answered for
        # whichever copy came first: an old Grizzly Bears and one Bolted this
        # turn were one object, so Raise Dead returning the new one left No
        # Rest for the Wicked a Bears to return. A copy arriving as an object
        # some graveyard holds arrives as a new, equal one (CR 400.7) — only on
        # a collision, so a card put into a graveyard alone stays the object
        # its caller holds, and a commander's designation (CR 903.3, by
        # object) moves to the copy made of it.
        landed = card
        if held_in_a_graveyard(self.players, card):
            landed = distinct_graveyard_object(card)
            commanders = getattr(self.players[seat], "commanders", None) or []
            for index, commander in enumerate(commanders):
                if commander is card:
                    commanders[index] = landed
                    break
        # "…**that were put there from the battlefield this turn**" (No Rest
        # for the Wicked, Second Sunrise). Recorded on the one seam every
        # arrival passes through, keyed by the pile it landed in (CR 400.3's
        # owner) — the same place the exile replacement and the arrival event
        # are, because "from the battlefield" is a fact about *this* move and
        # nothing in the graveyard afterwards remembers it. Before the append,
        # because the same call retires what the record says about a card that
        # left a pile since (CR 400.7), and that is counted against the pile as
        # it was. A token never gets here: the permanent path keeps its card
        # out (CR 111.7), which is the difference between this record and the
        # tally beside it.
        record_arrival_history(self.players, seat, landed, from_zone)
        self.players[seat].graveyard.append(landed)
        # CR 613.7d: the card gets its timestamp as it enters the zone, which
        # is the timestamp a static ability functioning from here carries
        # (CR 613.7a; Anger's ruling, 2004-10-04: "set at the time that this
        # card goes to your graveyard"). Recorded on the one road every
        # arrival takes, by the module that keeps the record in step with the
        # pile.
        record_graveyard_arrival(self.players[seat], landed)
        # Announced **after** the card has arrived, because CR 603.6 has a
        # zone-change trigger look for its object in the zone it moved to — and
        # a replacement that diverted the card returned above, so nothing fires
        # for a card that never got here. About *landed*, the object the pile
        # holds, for the same reason: a trigger finds its card there.
        if from_zone == "library":
            emit(
                self, "self_put_into_graveyard_from_library",
                subject=landed, owner_index=seat,
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
        #
        # …and the id of the permanent this card was, when it left the
        # battlefield to get here: "**another** card" (Planar Void) excludes
        # the watcher's own card, and once the arrival can be a new object
        # (above) the card alone cannot say that a dying Planar Void is the
        # watcher. None for every other road.
        emit(
            self, "card_put_into_graveyard",
            subject=landed, owner_index=seat, dead_card=landed,
            graveyard_from_zone=from_zone,
            moved_permanent_id=getattr(from_battlefield, "permanent_id", None),
        )
        return landed

    def graveyard_event(
        self, owner, card, *, from_zone=None, from_battlefield=None,
    ) -> dict:
        """The ``put_into_graveyard`` event *card*'s move into *owner*'s
        graveyard raises (CR 614 — Forbidden Crypt, Legacy Weapon): the seat
        whose pile it is, the card as it would land there (already whole,
        CR 709.4 and 708.9), the zone it left and the permanent it was.

        One builder, read by :meth:`put_card_into_graveyard` and by the two
        events CR 616.1 treats as the same move — a permanent dying and a card
        being discarded — which join this one's effects to their own
        contention set (``apply_replacements``' *joined*), so the predicates
        are asked about the event the seam would raise and no other."""
        return {
            "player": self.players[self._owner_seat(owner)], "card": card,
            "from_zone": from_zone, "permanent": from_battlefield,
        }

    def leaving_battlefield_event(self, permanent, owner, destination: str) -> dict:
        """The ``would_leave_battlefield`` event *permanent*'s move to
        *destination* raises (Dreams of the Dead) — built once, for
        :meth:`_leaving_battlefield_replaced` and for a death, which joins it
        (``_move_permanent_to_graveyard``)."""
        return {
            "player": owner if isinstance(owner, PlayerState)
            else self.players[self._owner_seat(owner)],
            "permanent": permanent,
            "destination": destination,
        }

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
        # No `restart`: one effect of this kind exists (Dreams of the Dead's
        # exile), and a contention needs two — the hand and the library have no
        # replacements of their own for it to meet. A death, the one
        # destination where it does meet others, asks it joined to them.
        # ``tests/engine/test_kg4_asks_replacement_sites.py`` fails the day a
        # second is registered.
        consumed, _ = apply_replacements(
            self, "would_leave_battlefield",
            self.leaving_battlefield_event(permanent, owner, destination),
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
            card = self.put_card_into_exile(player, card)
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
        self, entry: dict, zone: str, *, controller_index: int | None = None,
        then: "Callable[[Permanent], None] | None" = None,
    ) -> "Permanent | None":
        """Take one linked-exile entry's card out of exile and into *zone*.

        *then* is called with a **battlefield** arrival once it is there — the
        entry's ``then`` (``_put_permanent_onto_battlefield``), so a caller that
        attaches it does so after any "as it enters" choice (CR 614.12a).

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
        if zone == "battlefield" and any(
            held is card for held in owner.exile
        ):
            from ..permanent_cards import stays_out_of_battlefield

            # CR 400.4a, asked before the card leaves exile: a card that
            # cannot enter stays exiled (``permanent_cards``).
            if stays_out_of_battlefield(self, card, owner, "exile"):
                return None
        if not self.take_card_from_exile(owner_index, card):
            return None
        if zone == "hand":
            self.put_card_into_hand(owner, card)
            return None
        if zone == "library":
            self.put_card_into_library(owner, card)
            return None
        if zone == "graveyard":
            # "When this creature leaves the battlefield, return the exiled
            # cards to their owner's graveyard." (Gravegouger; Knowledge Vault,
            # Gustha's Scepter, Duplicity.) Through the graveyard's one arrival
            # like every other road there: this was an append through the
            # computed zone name, so Forbidden Crypt never saw these cards,
            # "whenever a card is put into a graveyard from anywhere" (Planar
            # Void) never heard of them, and two copies of one card could land
            # as one object.
            self.put_card_into_graveyard(owner, card, from_zone="exile")
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
        # Once it is there — the entry's ``then``, run at the answer when an
        # "as it enters" choice keeps it on its way (CR 614.12a) — and then
        # whatever the caller does with it (*then*, called with the arrival).
        def arrived() -> None:
            # Nothing of this is owed for an entry a replacement took away
            # (``entry_awaiting.entry_happened``) — the caller's *then* included.
            if arrival.metadata.get(ENTRY_OUTCOME) != ENTERED:
                return
            if entry.get("tapped"):
                arrival.tapped = True
            if entry.get("counters"):
                from ..handlers.linked_exile import restore_noted_counters

                restore_noted_counters(self, arrival, entry["counters"])
            if then is not None:
                then(arrival)

        self._put_permanent_onto_battlefield(seat, arrival, None, then=arrived)
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
        from ..linked_exile import entry_name_for_the_log, take_linked_entries

        entries = take_linked_entries(permanent, ending=ending)
        returned: Permanent | None = None
        # One event (CR 610.3d, 603.6a): everything the ending gives back enters
        # together, each Aura attached to its host once all of them are there.
        with self.entering_together():
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
                # "…**attached to that permanent**" — the Auras go back onto the
                # creature the entry before them brought back, which is why they
                # travel in one record and in printed order. Nothing to attach to
                # means the Aura simply arrives, and CR 704.5n's sweep bins it.
                # Attached once the Aura is there (the entry's ``then``).
                host = returned if entry.get("attach_to_returned") else None

                # Said once it is there, and only if it got there: the
                # arrival's ``then`` runs for an entry that happened alone.
                def back(arrival, host=host, card=card) -> None:
                    self.log.append(
                        f"{card.name} returns to the battlefield "
                        f"({permanent.card.name} {why})"
                    )
                    if host is not None:
                        attach_aura(arrival, host)

                arrival = self.leave_linked_exile(entry, destination, then=back)
                if arrival is None:
                    # A face-down entry going back to a hand is never shown
                    # (CR 406.3, 400.2), so the line counts it.
                    self.log.append(
                        f"{entry_name_for_the_log(entry, destination)} returns to "
                        f"{owner.name}'s {destination} "
                        f"({permanent.card.name} {why})"
                    )
                    continue
                if host is None:
                    returned = arrival
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
        then: "Callable[[], None] | None" = None,
    ) -> None:
        """One entry (:meth:`_enter_battlefield`), as one window for CR
        603.3b (``putting_triggers_on_stack``): the entering permanent's own
        "when this enters" and every observer's "whenever a creature
        enters" go on the stack together, and their controller orders them.
        Inside a resolution the resolution's window is the one that asks.

        *then* is what the caller does to the permanent once it is there —
        attach it, tap it and make it attack, put the counters it returns
        with on it, write the log line. Run after the entry, outside its
        window, exactly where the caller's next statement used to run; and
        when the entry **waits for its "as it enters" choice** (CR 614.12a,
        ``engine/entry_awaiting.py``) it is run with the rest of the entry, at
        the last answer — a caller writing that work after this call would do
        it to a permanent that is not on the battlefield yet.
        ``tests/engine/test_kg3_entry_callers.py`` holds every caller to it.

        Inside an open event (``entering_together``) only the entry state is
        performed here; the rest — and *then* — is done with the event's other
        newcomers when it closes.
        """
        with self.putting_triggers_on_stack():
            waits = self._enter_battlefield(
                controller_index, permanent, target_player_index,
                was_cast=was_cast, from_zone=from_zone,
                played_as_land=played_as_land, then=then,
            )
        if not waits and then is not None:
            then()

    @contextmanager
    def entering_together(self):
        """One event putting several permanents onto the battlefield (CR
        603.6a) — the block a caller wraps around the entries it makes
        together: "each player … puts all cards they exiled this way onto the
        battlefield" (Living Death), "return those cards to the battlefield"
        (Planar Guide), the tokens one instruction creates, the cards CR
        610.3d returns at once when a sweep takes away every permanent that
        exiled them.

        Each entry made inside the block is **handed in** (``DeferredEntry``)
        and nothing else of it happens until the event closes
        (``_close_entry_event``). Then each newcomer's entry state is performed
        in turn, with the permanent in no zone (CR 614.12a) and **in APNAP
        order** of the seat it enters under (CR 101.4: the active player makes
        any choices required, then each other player in turn order; CR
        613.7m: their timestamps in that order) — so no newcomer's entry
        replacement sees another: CR 614.12 asks only "continuous effects that
        already exist", and CR 614.13a makes no object entering at the same
        time a choosable one. Then the entries are completed together
        (``_finish_or_await``): every newcomer appended, one recompute (CR
        611.3c), each one's "…then" rider, and only then each one's "enters"
        announcement and its own enter trigger, with every newcomer on the
        battlefield to see them. Entered one at a time, an observer among them
        saw only those behind it: a Goblin Assassin returned by Planar Guide
        after a Goblin Clearcutter triggered once instead of twice, and a Soul
        Warden put back by Living Death gained life for the creatures after it
        and none for those before it (its ruling, 2025-01-24: it triggers "for
        each of those other creatures").

        **An event can outlive the block.** A prompt armed inside it carries
        it (``entry_awaiting.ENTRY_EVENT``) and its answer re-joins it
        (``rejoining_entry_event``), and the block's end closes it only once
        no such prompt that stops a loop is still owed — otherwise the last
        answer does. A loop whose steps each stop to ask opens its event with
        :meth:`entering_together_through` instead.

        At a table that holds for answers an event any of whose newcomers
        still owes an "as it enters" choice waits as one, completed at the
        last answer any of them owes (``_finish_answered_entries``), each
        entry's ``then`` with it. So a caller writes nothing that reads an
        entered permanent inside the block, or after it, except through
        ``then`` — the rule ``tests/engine/test_kg3_entry_callers.py`` holds
        every entry to; ``tests/engine/test_kg3_batch_roads.py`` holds every
        entry made in a loop to this block.

        Re-entrant: a block opened inside an open one is the same event. An
        entry that a newcomer's own entry state makes is an event of its own
        — the entry states are performed once the event is no longer open.
        """
        if self.entry_batch is not None:
            yield
            return
        event = self._open_entry_event()
        try:
            yield
        except BaseException:
            self._abandon_entry_event(event)
            raise
        self._opener_finished(event)

    def entering_together_through(self, run: "Callable") -> None:
        """One event (CR 603.6a) around a **resumable loop** whose steps may
        each stop to ask (``engine/resumption.py``): ``run(then)`` runs the
        loop, and *then* is the loop's last step, which says the event has
        been handed everything its loop will hand it.

        "Each player may put an artifact, creature, enchantment, or land card
        from their hand onto the battlefield" (Show and Tell): one offer per
        seat, each answered after the call that made it has returned, and its
        ruling (2008-04-01) is that "after all choices are made, the cards are
        put onto the battlefield simultaneously". A ``with`` block around the
        loop closed at the first seat's suspension, so each seat's card
        entered at its own answer and a Soul Warden on the second seat never
        saw the first seat's creature arrive. Here the event is set aside
        whenever the loop stops (``entry_batch`` is None between answers, so
        nothing else that happens meanwhile joins it), each answer re-joins it,
        and it closes at the last answer.

        Inside an open event the loop is part of that one, and *then* is None.
        """
        if self.entry_batch is not None:
            run(None)
            return
        event = self._open_entry_event()

        def last_step() -> None:
            self._opener_finished(event)

        try:
            run(last_step)
        except BaseException:
            self._abandon_entry_event(event)
            raise
        finally:
            # Stopped to ask, or finished: either way nothing after this is
            # the event's until an answer re-joins it.
            if self.entry_batch is event:
                self.entry_batch = None

    def _open_entry_event(self) -> EntryEvent:
        """Open a new event and make it the one entries are handed to."""
        event = EntryEvent(item=self.resolving_stack_item)
        self.entry_batch = event
        self.open_entry_events.append(event)
        return event

    def _abandon_entry_event(self, event: EntryEvent) -> None:
        """An event whose opener raised: nothing it was handed is performed."""
        event.closed = event.opener_done = True
        if self.entry_batch is event:
            self.entry_batch = None
        self._forget_entry_event(event)

    def _forget_entry_event(self, event: EntryEvent) -> None:
        self.open_entry_events = [
            open_event for open_event in self.open_entry_events
            if open_event is not event
        ]

    def _opener_finished(self, event: EntryEvent) -> None:
        """Whatever opened *event* has handed it everything it will: it
        closes now, unless a prompt it stamped is still owed — then at that
        prompt's answer (``rejoining_entry_event``)."""
        event.opener_done = True
        if self.entry_batch is event:
            self.entry_batch = None
        if not self.entry_event_owed(event):
            self._close_entry_event(event)

    def entry_event_owed(self, event: EntryEvent) -> bool:
        """Whether a decision armed inside *event* that stops a loop is still
        owed — the loop behind it may hand the event more newcomers once it is
        answered. On either queue; one being answered right now (``_answered``)
        is not owed any more."""
        return any(
            choice.data.get(ENTRY_EVENT) is event
            and spec_for(choice.kind).suspends
            and spec_for(choice.kind).open_for(self, choice)
            and not choice.data.get("_answered")
            for choice in self.pending_choices
        ) or any(
            choice.data.get(ENTRY_EVENT) is event
            for choice in self.pending_replacement_choices
        )

    @contextmanager
    def rejoining_entry_event(self, choice):
        """Answer *choice* as one more part of the event it was armed in (CR
        603.6a): the entries the answer makes — and the loop it resumes —
        are handed to that event, and once its opener is done and nothing it
        stamped is owed, the event closes here. Inert for a prompt armed
        outside any event, or in one that has closed."""
        event = choice.data.get(ENTRY_EVENT)
        if event is None or event.closed:
            yield
            return
        outer = self.entry_batch
        self.entry_batch = event
        try:
            yield
        finally:
            self.entry_batch = (
                None if outer is event and event.closed else outer
            )
        self.close_entry_event_if_settled(event)

    def close_entry_event_if_settled(self, event: EntryEvent) -> None:
        """Close *event* if its opener is done and nothing it stamped is owed
        — the moment after an answer, or after a prompt it stamped was
        dropped unanswered."""
        if (
            not event.closed
            and event.opener_done
            and self.entry_batch is not event
            and not self.entry_event_owed(event)
        ):
            self._close_entry_event(event)

    def close_entry_events_of(self, item) -> None:
        """The backstop for an event whose loop never came back: *item* has
        finished resolving (``_release_stack_item``), so every event opened
        while it resolved is closed — what it was handed enters now rather
        than never."""
        for event in list(self.open_entry_events):
            if event.item is item and not event.closed:
                self._close_entry_event(event)

    @contextmanager
    def outside_any_entry_event(self):
        """Set the open event aside for something that is an event of its own
        (a state-based check, CR 704.3), and hand it back afterwards."""
        event, self.entry_batch = self.entry_batch, None
        try:
            yield
        finally:
            self.entry_batch = event

    def _close_entry_event(self, event: EntryEvent) -> None:
        """Perform everything *event* was handed, together (CR 603.6a).

        Each newcomer's entry state first, in APNAP order of the seat it
        enters under (``entry_awaiting.apnap_order``; CR 101.4, 613.7m), with
        the event already closed — an entry a newcomer's entry state makes is
        an event of its own — then ``_finish_or_await`` over every newcomer
        nothing replaced, and each caller's ``then``: at once, or with the
        rest of the entry when a choice keeps the event waiting."""
        if event.closed:
            return
        event.closed = event.opener_done = True
        if self.entry_batch is event:
            self.entry_batch = None
        self._forget_entry_event(event)
        if not event.puts:
            return
        with self.outside_any_entry_event():
            records: list = []
            replaced: list = []
            waits = False
            with self.putting_triggers_on_stack():
                try:
                    for put in apnap_order(self, event.puts):
                        record = self._begin_entry(put, stamp_id=False)
                        if record is ENTRY_SUSPENDED:
                            # Its "would enter" replacements contend and its
                            # player is being asked (CR 616.1e): it leaves
                            # the event, and the answer finishes it alone —
                            # the entry, then its ``then``.
                            continue
                        if record is None:
                            replaced.append(put)
                        else:
                            records.append(record)
                except BaseException:
                    for record in records:
                        self._forget_entry(record)
                    raise
                if records:
                    waits = self._finish_or_await(records)
            # An entry a replacement took away (CR 614: Containment Priest)
            # never waits: its caller's continuation runs now, as it always
            # has.
            for put in replaced:
                if put.then is not None:
                    put.then()
            if not waits:
                for record in records:
                    if record.then is not None:
                        record.then()

    def entry_is_awaited(self, permanent: Permanent) -> bool:
        """Whether *permanent*'s entry is waiting for its "as it enters"
        choice (CR 614.12a) — on its way, on no battlefield yet."""
        return entry_is_awaited(self, permanent)

    def entry_choice_applies(self, permanent) -> bool:
        """Whether an answer about *permanent*'s entry still has a permanent
        to write to: on the battlefield, or on its way there.

        The entry resolvers asked ``is_on_battlefield`` alone, which answered
        "it left while the prompt was owed" for every permanent whose entry
        waits for the answer (CR 614.12a) — the one permanent the answer is
        for. A permanent that really has left is neither."""
        return permanent is not None and (
            self.is_on_battlefield(permanent)
            or entry_in_progress(self, permanent) is not None
        )

    def _finish_answered_entries(self) -> bool:
        """Complete every waiting entry whose last "as it enters" prompt has
        been answered; True when one was.

        Asked by the answer funnel (``PendingChoicesMixin._apply_choice_answer``
        and ``_apply_choice_default``) once an answer is applied and before the
        loop it suspended resumes — so the permanent is on the battlefield
        before the next step of the resolution that put it there reads it —
        and by the force-release backstop. Every record, not only the answered
        prompt's permanent: an answer can take another entry's last prompt
        away with it. In the order the entries began.

        **An event's newcomers finish together** (CR 603.6a,
        ``entering_together``): a record is finished only once no record of
        its event owes a choice, and finishing it completes every one of them.
        """
        finished = False
        for record in list(self.entries_in_progress):
            if record.finish is None:
                # Still performing its entry state, further up the call stack
                # — or one of an event still being handed its newcomers.
                continue
            if not any(entry is record for entry in self.entries_in_progress):
                # Completed with the rest of its event, earlier in this pass.
                continue
            if any(
                self.permanent_is_entering(member.permanent)
                for member in entered_together(record)
            ):
                continue
            record.finish()
            finished = True
        return finished

    def _enter_battlefield(
        self,
        controller_index: int,
        permanent: Permanent,
        target_player_index: int | None,
        *,
        was_cast: bool = False,
        from_zone: str | None = None,
        played_as_land: bool = False,
        then: "Callable[[], None] | None" = None,
    ) -> bool:
        """Put *permanent* onto the battlefield — the one entry path there is.
        True when the entry is **waiting** for its "as it enters" choice
        (CR 614.12a) and will be completed by the answer; then *then* runs
        there too.

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

        **Inside an open event** (``entering_together``) the entry is handed
        to it and True is returned: everything below is done when the event
        closes, with its other newcomers (``_close_entry_event``). Only the
        id is stamped now (CR 400.7), so a caller that records what it put
        down ("if you do, sacrifice **it**", Flash) records the identity the
        permanent will have.
        """
        # What becomes of *this* entry is not known yet (``entry_happened``):
        # an object put back after an earlier entry starts again unanswered.
        permanent.metadata.pop(ENTRY_OUTCOME, None)
        put = DeferredEntry(
            permanent, controller_index, target_player_index,
            was_cast=was_cast, from_zone=from_zone,
            played_as_land=played_as_land, then=then,
        )
        event = self.entry_batch
        if event is not None:
            permanent.permanent_id = next_permanent_id()
            event.puts.append(put)
            return True
        record = self._begin_entry(put, stamp_id=True)
        if record is ENTRY_SUSPENDED:
            # CR 616.1e is being asked: nothing of the entry has happened, and
            # the answer performs it and runs *then* (``_enter_answered_entry``)
            # — so this waits, exactly as an entry whose "as it enters" choice
            # is owed does.
            return True
        if record is None:
            return False
        return self._finish_or_await([record])

    def _begin_entry(self, put: DeferredEntry, *, stamp_id: bool):
        """Everything of one entry up to the battlefield append: the board's
        statics folded on, the "would enter" replacements, the stamps, and the
        entry state with the permanent in no zone (CR 614.12a). The record of
        the entry on its way — or None when a replacement took it away, or
        ``ENTRY_SUSPENDED`` when its replacements contend and its affected
        player is being asked which applies first (CR 616.1e): the answer
        re-runs this from the top (``_enter_answered_entry``).

        *stamp_id* is False for an entry an open event was handed, whose id
        was stamped as it was handed in."""
        permanent, controller_index = put.permanent, put.controller_index
        target_player_index = put.target_player_index
        was_cast, from_zone = put.was_cast, put.from_zone
        played_as_land = put.played_as_land
        cast_as_a_spell = was_cast and not played_as_land
        permanent.metadata.pop(ENTRY_OUTCOME, None)
        # A permanent object entering again is a new object (CR 400.7): the
        # face-down values it was last seen leaving with (CR 708.9,
        # ``face_down.reveal_departing``) are not what it is now.
        forget_face_down_departure(permanent)
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
        event = {
            "permanent": permanent,
            "controller_index": controller_index,
            "was_cast": cast_as_a_spell,
            # CR 616.1 asks the *affected* player to choose among contending
            # effects; for an entry that is the seat the permanent would
            # enter under.
            "player": self.players[controller_index],
        }
        # **A "can't" first, and alone** (CR 614.17: "Lands can't enter the
        # battlefield", Worms of the Earth). It is not a replacement effect,
        # and an event that can't happen may be replaced only by a
        # self-replacement effect (614.17c) — so it is never one of the
        # contenders the affected player chooses among below, and a land
        # Worms stops stays where it was whatever else would have applied.
        consumed, _ = apply_replacements(self, "cant_enter_battlefield", event)
        suspended = False
        if not consumed:
            # CR 616.1e: Land Equilibrium beside an Alliances land's toll its
            # controller cannot pay (its ruling, 2009-10-01: "the player who
            # will control that land chooses which replacement effect to
            # apply"), Containment Priest beside a toll on a creature nobody
            # cast — asked of a person. Nothing has happened to the entry
            # when the question is armed, so the answer re-runs it from the
            # top and the caller's continuation behind it.
            stamp = {"id": stamp_id}
            restart = answered_restart(
                self, "would_enter_battlefield", event,
                lambda: self._enter_answered_entry(put, stamp_id=stamp["id"]),
            )
            consumed, _ = apply_replacements(
                self, "would_enter_battlefield", event, restart=restart,
            )
            suspended = consumed and self._entry_question_owed(restart)
            if suspended and stamp_id:
                # The identity the permanent will have, now (CR 400.7): a
                # caller that records what it put down ("if you do,
                # sacrifice **it**", Flash) reads it as the call returns —
                # the arrangement an open event's hand-in already makes.
                permanent.permanent_id = next_permanent_id()
                stamp["id"] = False
        if consumed:
            if judged:
                # The fold asked the board's statics about a permanent that
                # then never arrived; what it wrote on everything else is
                # rebuilt from the board as it really is.
                self._recompute_continuous_effects()
            if suspended:
                return ENTRY_SUSPENDED
            # Taken away (``entry_awaiting.entry_replaced``): what a caller's
            # line about the entry asks before it claims one — unless the
            # replacement itself put this very permanent onto the battlefield
            # (Mox Diamond's toll paid by a seat nobody asks re-enters it
            # inside the event, ``_resolve_entry_discard_toll``), which wrote
            # its own outcome.
            if permanent.metadata.get(ENTRY_OUTCOME) != ENTERED:
                permanent.metadata[ENTRY_OUTCOME] = REPLACED
            # A rider an effect applied before another took the entry away
            # (Land Equilibrium chosen ahead of an Alliances land's unpaid
            # toll): the modified event still holds its "then sacrifices a
            # land" (CR 614.6: "A modified event occurs instead"; 616.1f
            # applied the toll to its entry alone). Unreachable in the order
            # a seat nobody asks takes, which applies the toll first.
            apply_entry_riders(self, permanent, controller_index)
            return None
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
        # it is about to lose. (An entry an open event was handed has had its
        # id since it was handed in.)
        if stamp_id:
            permanent.permanent_id = next_permanent_id()
        # CR 613.7d, beside the id and for its reason: the object receives its
        # timestamp as it enters the zone, which is what a static ability on it
        # is ordered by (CR 613.7a). Before the append, so no layer read can
        # see the permanent on the battlefield under the stamp it was built
        # with.
        permanent.timestamp = next_timestamp()
        # CR 613.1: the value layer 2 starts from. Recorded on entry and never
        # written again, so an ending control effect reverts to the seat that
        # put the permanent into play rather than to whichever seat held it
        # most recently.
        set_base_controller(permanent, controller_index)
        # **The entry state, before the permanent is anywhere** (CR 614.12a:
        # "that choice is made before the permanent enters the
        # battlefield"). Performed with the permanent on its way — in no
        # zone, its seat answered by the record (``controller_index_of``) —
        # so a choice it makes, the defaults a seat nobody asks takes, the
        # counters it enters with and the tolls it charges all happen before
        # any static of its reaches the board and before anything sees it
        # arrive. It used to be performed after the append, and a person's
        # Ward Sliver sat on the battlefield with a provisional colour while
        # its prompt was open, Soul Warden having already gained its life.
        record = EntryInProgress(
            permanent, controller_index,
            target_player_index=target_player_index, was_cast=was_cast,
            then=put.then,
        )
        self.entries_in_progress.append(record)
        # The entry state is this permanent's own: whatever it puts onto the
        # battlefield is an event of its own, not one of this event's
        # newcomers — performed with no event open (``_close_entry_event``
        # closes its event first; a lone entry is made outside one).
        try:
            self._initialize_permanent_state(
                permanent, controller_index, target_player_index
            )
        except BaseException:
            self._forget_entry(record)
            raise
        return record

    def _entry_question_owed(self, restart) -> bool:
        """Whether the entry whose re-run is *restart* stopped to ask CR
        616.1e's question rather than being taken away — the ``effect_order``
        prompt it armed carries that very re-run. ``apply_replacements``
        reports both as consumed (its caller's one question is "do not carry
        on"), and an entry has a second one: whether its ``then`` runs now,
        for an entry that did not happen, or at the answer."""
        return any(
            choice.kind == "effect_order" and choice.data.get("_restart") is restart
            for choice in self.pending_choices
        )

    def _enter_answered_entry(self, put: DeferredEntry, *, stamp_id: bool) -> None:
        """The answer to an entry's CR 616.1e question: the entry performed
        from the top — the replacements again, now with the answer recorded
        (``answered_restart``), the stamps and the entry state — then the rest
        of it, or the wait for an "as it enters" choice, and the caller's
        *then* behind it: at once for an entry the answer took away or
        completed, with the rest of the entry when it waits. Alone, as one
        CR 603.3b window: an entry that left its event to ask is an event of
        its own by the time it is answered."""
        waits = False
        with self.putting_triggers_on_stack():
            record = self._begin_entry(put, stamp_id=stamp_id)
            if record is ENTRY_SUSPENDED:
                return
            if record is not None:
                waits = self._finish_or_await([record])
        if not waits and put.then is not None:
            put.then()

    def _finish_or_await(self, records) -> bool:
        """Complete the entries one event made, *records* — or wait.

        **A choice is still owed**, at a table that holds for answers (a
        person; the simulator's driver): the rest of every entry is the
        answer's to finish (``_finish_answered_entries``), with what each
        caller does to its permanent behind it, and True is returned. One
        ``finish`` for the whole event, run once no newcomer of it owes
        anything (CR 603.6a: they enter together, so they wait together). A
        bare headless table holds nothing — its prompts are drained by the
        caller once this returns — so there the permanents enter now, as they
        always have, and False is returned: the caller runs each ``then``.
        """
        if self.holds_for_answers() and any(
            self.permanent_is_entering(record.permanent) for record in records
        ):
            together = tuple(records)

            def finish() -> None:
                for record in together:
                    self._forget_entry(record)
                self._complete_entries(together)
                for record in together:
                    if record.then is not None:
                        record.then()

            for record in together:
                record.finish = finish
                if len(together) > 1:
                    record.together = together
            return True
        for record in records:
            self._forget_entry(record)
        self._complete_entries(records)
        return False

    def _forget_entry(self, record) -> None:
        """Take *record* off ``entries_in_progress``, by identity."""
        self.entries_in_progress = [
            entry for entry in self.entries_in_progress if entry is not record
        ]

    def _complete_entries(self, records) -> None:
        """Everything from the battlefield append onward, for every newcomer
        of one event at once: the half of :meth:`_enter_battlefield` that
        waits when a choice is owed, and that an event's newcomers do
        together (CR 603.6a)."""
        for record in records:
            permanent, controller_index = record.permanent, record.controller_index
            self.players[controller_index].battlefield.append(permanent)
            # The entry happened (``entry_awaiting.entry_happened``) — what a
            # caller's ``then`` asks, rather than whether the permanent is
            # still there by the time it runs.
            permanent.metadata[ENTRY_OUTCOME] = ENTERED
            # "…put a nontoken permanent onto the battlefield" (Arboria, CR
            # 506.3): the per-turn half of the last-own-turn record, folded
            # per seat at the turn boundary
            # (mixins/turn_management.begin_turn_bookkeeping). Here because
            # this is the one entry path there is — a fire site per caller is
            # the pattern that forgot `become_tapped` 41 times.
            if not permanent.metadata.get("is_token"):
                self.nontoken_permanents_entered_this_turn[controller_index] = (
                    self.nontoken_permanents_entered_this_turn.get(controller_index, 0) + 1
                )
        # 611.3a/611.3c: static abilities apply as permanents enter. Recalculate
        # lord buffs so the new permanent immediately receives applicable bonuses,
        # and so any new lord immediately buffs existing matching permanents —
        # once, with every newcomer of the event there, so a lord entering
        # beside a creature it pumps has pumped it before either is announced.
        self._recompute_continuous_effects()
        # The "…**then** X" half of an entry replacement (Land Equilibrium's
        # "puts that land onto the battlefield then sacrifices a land"). After
        # the append and after the recompute, because "then" means the new
        # permanent is on the battlefield and is itself a legal choice.
        for record in records:
            apply_entry_riders(self, record.permanent, record.controller_index)
        # **And then each newcomer is announced, with every one of them on
        # the battlefield** (CR 603.6a: "all permanents on the battlefield
        # (including the newcomers) are checked"), so an observer that entered
        # beside it sees it whichever of them came first.
        for record in records:
            self._announce_entry(record)

    def _announce_entry(self, record) -> None:
        """One newcomer's "enters" announcement and its own enter trigger."""
        permanent, controller_index = record.permanent, record.controller_index
        target_player_index, was_cast = record.target_player_index, record.was_cast
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
        # "Whenever **a land enters**" (Ankh of Mishra, Tectonic Instability):
        # the same event for a land, by any road (CR 603.6a). It was announced
        # only where a land was *played*, so a Rampant Growth or a Planar Birth
        # under an Ankh dealt no damage.
        if permanent.has_type("land"):
            self._process_land_enters(controller_index)
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
