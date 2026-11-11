"""Cards picked out of a hand.

A non-random discard and what reads how many were discarded; the caster's pick
out of a revealed hand (Duress, Mind Warp) and what happens to the chosen card;
cards put back from a hand onto the library (Brainstorm); a card exiled out of
a hand, put onto the battlefield out of one, or chosen in one for a later step
to act on; and the revealed-hand notification a viewer dismisses. Every
candidate list is read from the hand as it stands, because each card that
leaves renumbers the ones behind it. ("Discard it unless you pay N life" is a
price, and is answered beside the other life-priced offer, in
``optional_pay.py``.)

One pick goes the other way and lives here for its shape: a card brought *into*
a hand from outside the game (the Judgment Wishes, CR 400.11b), which is the
put-from-hand pick with its two ends swapped and is answered the same way —
a position in a pile the seat looks through in full, checked against the rule
the pile was offered by.
"""

from __future__ import annotations

from ....exiled_records import record_exiled_card
from ....linked_exile import link_exiled_card
from ....entry_awaiting import entry_happened
from ....models import Permanent
from ....permanent_cards import stays_out_of_battlefield
from ....grammar.lowering._events import PUT_FROM_HAND_PERMANENTS
from ....pending_choices import ChoiceSpec, PendingChoice
from ....search_filters import search_matches


class HandChoicesMixin:
    # -- Discard ------------------------------------------------------------

    def confirm_discard(self, player_index: int, hand_indices: list[int], to_library: bool = False) -> bool:
        """Resolve a pending non-random discard (Disrupting Scepter) with the
        player's chosen cards. ``to_library`` puts them on top of the library
        instead of the graveyard, but only if Library of Leng allows it."""
        return self.resolve_pending_choice(
            "discard", player_index, hand_indices=hand_indices, to_library=to_library
        )

    def live_discard_candidates(self, choice: PendingChoice) -> list[int]:
        """The hand positions this seat may still discard, in hand order.

        Public because the prompt renderer is the second legitimate caller: the
        list offered and the list an answer is checked against have to be one
        rule rather than two copies of it — the same arrangement
        ``live_tap_any_number`` makes, and the same failure it prevents.
        """
        from ....subject_filters import card_matches_any

        described = dict(choice.data.get("filter") or {})
        hand = self.players[choice.player_index].hand
        alternatives = (described,) if described else ()
        # "Draw two cards, then discard one **of them**." (Krovikan Sorcerer.)
        # An identity restriction rather than a characteristic one, so it
        # arrives as the hand positions the arming step drew into rather than as
        # a filter: every copy of a card in a hand is the *same* Python object
        # (`web/deck_builder.py` repeats one definition per copy), so "one of
        # the cards you just drew" cannot be told from "another copy of the same
        # card you were already holding" by anything but position.
        only = choice.data.get("only_indices")
        allowed = set(only) if only is not None else None
        return [
            index for index, card in enumerate(hand)
            if (allowed is None or index in allowed)
            and card_matches_any(
                card, alternatives, game=self, owner=choice.player_index,
            )
        ]

    def _resolve_discard(self, choice: PendingChoice, hand_indices: list[int], to_library: bool) -> bool:
        from ....handlers.discards import _resolve_one_discard

        count = int(choice.data["count"])
        chosen = [i for i in dict.fromkeys(hand_indices)][:count]
        # "Discard **up to** two cards" (Kinetic Augur): fewer is a legal answer,
        # none included. A ceiling read as an exact count would force the player
        # to pitch cards they were offered the choice of keeping.
        if len(chosen) != count and not choice.data.get("up_to"):
            return False
        # "Discard a **creature** card": a card the phrase does not name is not
        # a legal answer, and is refused rather than slid onto one that is — a
        # stale click must not throw away a card the player meant to keep.
        eligible = set(self.live_discard_candidates(choice))
        if any(index not in eligible for index in chosen):
            return False
        # Remove in descending order so earlier indices stay valid as we pop.
        took: list = []
        # One event: a discard an opponent causes can put the card onto the
        # battlefield instead (Dodecapod), and every such card enters together
        # (CR 603.6a).
        with self.entering_together():
            for hand_index in sorted(chosen, reverse=True):
                if not _resolve_one_discard(
                    self, choice.player_index, hand_index, to_library, took=took
                ):
                    return False
        self.discard_pending_choice(choice)
        self._after_discard_answered(choice, len(chosen), took)
        return True

    def _after_discard_answered(
        self, choice: PendingChoice, discarded: int, took: list | None = None
    ) -> None:
        """Everything that reads *how many* cards were actually discarded.

        One place, because both answer paths — a seat's own picks and the
        non-interactive default — reach it, and the number is knowable nowhere
        else: nothing downstream of a queued choice can read a count the player
        has not given yet.

        Two readers today. "…then draw that many cards" (Kinetic Augur) is the
        fused shape, whose follow-on the prompt was armed with. The other is the
        ordinary back-reference: a discard that recorded its count into the
        resolution scratchpad lets "…for each card discarded this way" (Recall)
        be a later step of an ordinary ``sequence`` rather than a second fused
        kind. Discarding nothing records a zero, which is what both sentences
        say.
        """
        # The resolution's records — the total, the per-seat tally ("…3 minus
        # the number of cards **they** discarded", Mind Bomb), which cards went
        # ("for each **land card** discarded this way", Gerrard's Verdict) and
        # which went per seat ("each player who didn't discard a creature card
        # this way", Strongarm Tactics) — through the one writer the
        # each-player discard's inline default shares. A card that went
        # somewhere hidden is not in *took* (CR 701.9c) and is counted only.
        from ....handlers.discards import record_discards

        record_discards(
            choice.data.get("_results"), choice.player_index, discarded, took,
        )
        player = self.players[choice.player_index]
        if choice.data.get("draw_that_many") and discarded > 0:
            # CR 614.5: a draw a replacement effect *created* is not replaced
            # again by that same effect. The prompt carries which sources have
            # already had their opportunity (Chains of Mephistopheles), and an
            # ordinary "discard, then draw that many" carries none.
            drawn = self._draw_with_replacements(
                player,
                discarded,
                exclude_sources=tuple(choice.data.get("draw_exclude_sources") or ()),
            )
            self.log.append(f"{player.name} drew {drawn} card(s) for the cards discarded")
        # The draws that were queued *behind* the one this prompt replaced.
        # CR 121.2 makes "draw three cards" three individual draws; a
        # replacement takes one of them and the rest have to wait for the
        # answer, because they are later steps of the same instruction.
        # They are draws of the same event as the one the prompt replaced, so
        # what that event had already been through stays excluded (CR 614.5:
        # the doubler that made them does not double them again) — and the
        # seam parks them while the draw above is waiting on another
        # replacement's offer.
        queued = int(choice.data.get("queued_draws", 0) or 0)
        if queued > 0:
            self._draw_with_replacements(
                player, queued,
                exclude_sources=tuple(
                    choice.data.get("queued_exclude_sources") or ()
                ),
            )

    # -- The caster's pick out of a revealed hand (Duress) --------------------

    def confirm_revealed_hand_pick(
        self, player_index: int, hand_index: int | None = None
    ) -> bool:
        return self.resolve_pending_choice(
            "revealed_hand_pick", player_index, hand_index=hand_index
        )

    def _resolve_revealed_hand_pick(self, choice: PendingChoice, hand_index) -> bool:
        """The caster's pick out of a revealed hand (Duress).

        The legal indices are re-checked against the record armed with the
        choice rather than trusted from the wire: a client offering the whole
        hand would otherwise turn "a noncreature, nonland card" into "any card",
        which is the same hole the search picker closed.

        ``hand_index`` of None is the chooser **declining** — "choose **up to** X
        cards from it" (Discordant Dirge), CR 601.2c's ceiling. Admitted only
        where the card printed the words: a Duress that could be answered with
        nothing is a spell that does not resolve, and the whole chain stops
        rather than the one prompt, because the permission is about the printed
        number and not about this pick.
        """
        if hand_index is None:
            if not choice.data.get("up_to"):
                return False
            self.discard_pending_choice(choice)
            self.log.append(
                f"{choice.data.get('card_name', 'An effect')}: "
                f"{self.players[choice.player_index].name} chose no more cards"
            )
            return True
        if hand_index not in (choice.data.get("legal_indices") or []):
            return False
        victim_index = int(choice.data["victim_index"])
        self._record_revealed_hand_pick(choice, victim_index, hand_index)
        if not self._apply_revealed_hand_fate(choice, victim_index, hand_index):
            return False
        self.discard_pending_choice(choice)
        self._rearm_revealed_hand_pick(choice, victim_index)
        return True

    def _default_revealed_hand_pick(self, choice: PendingChoice) -> None:
        """A non-interactive caster takes the costliest legal card.

        A stated policy, like the up-to-N maximum and the modal first mode: mana
        value is the one ranking every card in the pool answers, and a card that
        wants a cleverer pick needs a valuation rather than a special case here.
        """
        legal = list(choice.data.get("legal_indices") or [])
        victim_index = int(choice.data["victim_index"])
        taken = False
        if legal and 0 <= victim_index < len(self.players):
            hand = self.players[victim_index].hand
            legal.sort(key=lambda i: (-(hand[i].cmc if i < len(hand) else 0), i))
            self._record_revealed_hand_pick(choice, victim_index, legal[0])
            taken = self._apply_revealed_hand_fate(choice, victim_index, legal[0])
        self.discard_pending_choice(choice)
        if taken:
            self._rearm_revealed_hand_pick(choice, victim_index)

    def _rearm_revealed_hand_pick(self, choice: PendingChoice, victim_index: int) -> None:
        """"…choose **X** cards from it" (Mind Warp) — the picks after the first.

        A chain of one-card prompts rather than one multi-select, because
        taking a card renumbers the hand behind it: the legal indices have to be
        recomputed against the hand as it now stands, and a set answered all at
        once against stale indices is the bug the counted search's atomic answer
        exists to avoid. The pending-choice queue is built for this — a prompt
        armed by *answering* an earlier one keeps the same resolution open.

        The chooser sees the whole hand each time, so nothing is decided with
        less information than the printed simultaneous choice gives.
        """
        remaining = int(choice.data.get("remaining", 1)) - 1
        if remaining <= 0 or not 0 <= victim_index < len(self.players):
            return
        exclude_types = list(choice.data.get("exclude_types") or ())
        # Ostracize's positive twin of the exclusion, carried onto every pick of
        # the chain for the reason the exclusion is: the picks after the first
        # are the same printed choice, so a narrowing that survived only the
        # first answer would widen the sentence part-way through.
        card_types = list(choice.data.get("card_types") or ())
        # "a **nonbasic** land card" (Encroach). The third narrowing, carried
        # for the two beside it's reason: the picks after the first are the same
        # printed choice, so a narrowing that survived only the first would
        # widen every pick behind it.
        excluded_supertypes = list(choice.data.get("exclude_supertypes") or ())
        narrowing = {
            "exclude_types": exclude_types,
            "exclude_basic_lands": bool(choice.data.get("exclude_basic_lands")),
        }
        if card_types:
            narrowing["card_type"] = tuple(card_types)
        if excluded_supertypes:
            narrowing["exclude_supertypes"] = excluded_supertypes
        # "…a card **of that color**" (Addle): the fourth narrowing, carried for
        # the three above's reason.
        any_colors = list(choice.data.get("any_colors") or ())
        if any_colors:
            narrowing["restrictions"] = {"any_colors": any_colors}
        victim = self.players[victim_index]
        legal = [
            index
            for index, held in enumerate(victim.hand)
            if search_matches(held, narrowing, game=self, owner=victim)
        ]
        if not legal:
            return
        self.arm_pending_choice(
            "revealed_hand_pick", choice.player_index,
            card_name=choice.data.get("card_name", ""),
            victim_index=victim_index,
            legal_indices=legal,
            remaining=min(remaining, len(legal)),
            fate=str(choice.data.get("fate", "discard")),
            exclude_types=exclude_types,
            exclude_basic_lands=narrowing["exclude_basic_lands"],
            card_types=card_types,
            exclude_supertypes=excluded_supertypes,
            any_colors=any_colors,
            source_id=choice.data.get("source_id"),
            record=choice.data.get("record"),
            # The printed "up to" survives every answer: the picks after the
            # first are the same printed choice, so a chooser who could stop
            # after one and not after two would be answering a card nobody
            # printed.
            up_to=bool(choice.data.get("up_to")),
            # CR 109.5: the picks after the first are the same spell's, and
            # they are armed from an *answer* — when nothing is resolving and
            # `arm_pending_choice` has no seat to stamp. Carried, so the second
            # card Mind Warp takes was caused by the same player as the first.
            **(
                {"_cause_seat": choice.data["_cause_seat"]}
                if choice.data.get("_cause_seat") is not None else {}
            ),
        )

    def _record_revealed_hand_pick(
        self, choice: PendingChoice, victim_index: int, hand_index: int
    ) -> None:
        """Write down **which card was chosen**, before anything moves it.

        "…then you choose a card other than a basic land card from it. Search
        that player's graveyard, hand, and library for all cards with the same
        name as **the chosen card**…" (Lobotomy.) The sentence behind the pick
        names the card by name, and by the time it runs the card may be in a
        graveyard, in exile or still where it was — so the name is recorded here,
        where the answer and the hand are both in hand.

        Written for **every** fate, not only the one that needs it: the pick is
        a chosen card whatever becomes of it, which is what lets
        ``lowering/_records`` declare the record for the instruction kind rather
        than for one of its payload values. Under the same key
        ``choose_card_name`` writes, because "the chosen card's name" and "the
        chosen card name" are one question asked by two sentences.
        """
        record = choice.data.get("record")
        if record is None or not 0 <= victim_index < len(self.players):
            return
        hand = self.players[victim_index].hand
        if not 0 <= hand_index < len(hand):
            return
        record["chosen_card_name"] = hand[hand_index].name

    def _apply_revealed_hand_fate(
        self, choice: PendingChoice, victim_index: int, hand_index: int
    ) -> bool:
        """What happens to the chosen card. One place, because the family varies
        only here — Duress discards it, and the exile ending arrives with the
        card that needs it."""
        from ....handlers.discards import _resolve_one_discard
        from ....linked_exile import LEAVES, link_exiled_card, until_leaves_source

        fate = str(choice.data.get("fate", "discard"))
        if fate == "name":
            # "…then you choose a card other than a basic land card from it."
            # (Lobotomy.) The choice **is** the whole sentence: nothing happens
            # to the card, and what the pick was for is the sentence behind it,
            # which reads the name this pick already recorded. The same shape
            # ``statement_dispatch_naming``'s own docstring asks of every
            # choice — "the lowering carries the bounds of the choice and
            # nothing else".
            return True
        if fate == "discard":
            # The causing seat comes off *this* prompt: `_resolve_one_discard`
            # looks its own up under the ``discard`` kind, which is not the
            # prompt an opponent's pick out of a revealed hand is — so a
            # Psychic Purge taken by Coercion was "caused by nobody" whenever
            # the caster answered from a prompt rather than a default.
            return _resolve_one_discard(
                self, victim_index, hand_index, to_library=False,
                cause_seat=choice.data.get("_cause_seat"),
            )
        if fate == "library_top":
            # "Put that card on top of that player's library." (Painful
            # Memories.) Both seams, and both for the reason they exist: a hand
            # holds the *same object* for every copy of a card, so the removal
            # goes through `take_card_from_hand` or it deletes every copy; and
            # CR 903.9b can divert a card headed for a library, so the arrival
            # goes through `put_card_into_library`.
            victim = self.players[victim_index]
            if not 0 <= hand_index < len(victim.hand):
                return False
            card = victim.hand[hand_index]
            if not self.take_card_from_hand(victim, card):
                return False
            self.put_card_into_library(victim, card, position="top")
            # "Look at target player's hand and choose a card from it. You put
            # that card on top of its owner's library." (Painful Memories.) A
            # look is not a reveal (CR 701.20e): the chooser and the owner know
            # the card, a third seat and a spectator do not, and ``game.log``
            # is all of theirs.
            self.log.append(
                f"a card from {victim.name}'s hand went on top of their library"
            )
            return True
        if fate == "exile":
            # "…and exile that card." (Psychic Theft.) Into its owner's exile
            # (CR 400.3), recorded as ``exiled_cards`` for the permission and
            # the delayed return behind it — the record Grinning Totem's
            # search leaves for the same two sentences.
            victim = self.players[victim_index]
            if not 0 <= hand_index < len(victim.hand):
                return False
            card = victim.hand[hand_index]
            if not self.take_card_from_hand(victim, card):
                return False
            card = self.put_card_into_exile(victim, card)
            record = choice.data.get("record")
            if record is not None:
                record["exiled_cards"] = [card]
            # "When this creature enters, target opponent reveals their hand
            # and you choose a nonland card from it. Exile that card. When this
            # creature leaves the battlefield, return the exiled card to its
            # owner's hand." (Mesmeric Fiend.) CR 607.2a links the two, so the
            # card is recorded as exiled *with* the permanent whose ability
            # exiled it — Kitesail Freebooter's record below, minus the
            # ``ends_on``: nothing about the exile itself ends it, and the
            # second ability is what moves it. A spell (Psychic Theft) has no
            # source and links nothing.
            #
            # Looked up by id like Freebooter's, and **not** linked once the
            # source has really left: by then its leaves-the-battlefield
            # trigger has already found an empty pile, and the card is exiled
            # for good — Mesmeric Fiend's ruling (2018-03-16): "Then its first
            # ability will resolve and exile a nonland card from the target
            # opponent's hand indefinitely."
            source = until_leaves_source(self, choice.data.get("source_id"))
            if source is not None:
                link_exiled_card(source, card, victim_index)
            self.log.append(f"{card.name} was exiled from {victim.name}'s hand")
            return True
        if fate != "exile_until_source_leaves":
            return False
        # "Exile that card until this creature leaves the battlefield."
        # (Kitesail Freebooter.) The card is held *by the source*, not by the
        # game: what returns it is the source leaving, and a record on the
        # permanent is a record that goes wherever the permanent does — the
        # linked-exile shape CR 400.7 needs, since the returning card is a new
        # object and nothing may hold a stale reference to it.
        source = until_leaves_source(self, choice.data.get("source_id"))
        victim = self.players[victim_index]
        if not 0 <= hand_index < len(victim.hand):
            return False
        if source is None:
            # CR 610.3b, behind the handler's own check, which declines to arm
            # this pick at all once the source has left. Should one be owed
            # anyway, the answer is taken and nothing is exiled - refusing it
            # would leave a prompt nobody can ever satisfy, which is a game
            # that waits for ever.
            self.log.append(
                f"{choice.data.get('card_name', 'The source')} has left the "
                "battlefield, so no card is exiled"
            )
            return True
        card = self.put_card_into_exile(victim, victim.hand.pop(hand_index))
        link_exiled_card(
            source, card, victim_index, to="hand", ends_on=(LEAVES,)
        )
        self.log.append(
            f"{card.name} is exiled until {source.card.name} leaves the battlefield"
        )
        return True

    # -- Hand back onto the library ------------------------------------------

    def confirm_hand_to_library(
        self, player_index: int, hand_indices: list[int], to_bottom: bool = False
    ) -> bool:
        """Resolve a pending "put N cards from your hand on top of your library"
        (Brainstorm, Stunted Growth) with the player's chosen cards.

        The order of *hand_indices* is the order the card gives them ("in any
        order"): the first named ends up on top.

        *to_bottom* is the second half of Dream Cache's answer — "both on top of
        your library **or both on the bottom**". It is refused on every other
        card rather than ignored: a bottomed Brainstorm is a strictly different
        spell, and nothing on the board would show it.
        """
        return self.resolve_pending_choice(
            "hand_to_library", player_index,
            hand_indices=hand_indices, to_bottom=to_bottom,
        )

    def _resolve_hand_to_library(
        self, choice: PendingChoice, hand_indices: list[int],
        to_bottom: bool = False,
    ) -> bool:
        """Move the chosen cards, last-named first, so the first is on top.

        Each card is taken through ``take_card_from_hand`` and put through
        ``put_card_into_library`` — the two seams, both of which exist because
        the obvious spelling is wrong: a hand holds the *same object* for every
        copy of a card, and CR 903.9b can divert a card headed for a library.

        The cards are read out **before** any of them move, because taking one
        renumbers the hand behind it — the same reason ``_default_discard``
        re-reads its candidate list each time round, arrived at from the other
        direction.
        """
        count = int(choice.data["count"])
        hand = self.players[choice.player_index].hand
        chosen = [i for i in dict.fromkeys(hand_indices) if 0 <= i < len(hand)][:count]
        # "Shuffle **any number of** cards from your hand into your library."
        # (Credit Voucher.) The count the prompt carries is a ceiling rather
        # than an exact number, so a shorter answer is a legal one — including
        # the empty answer, which is the player declining the offer. Every other
        # card reaching this prompt names an exact number and keeps the equality
        # it had: a Brainstorm that put back one card would leave a hand the
        # spell says it does not.
        if bool(choice.data.get("up_to")):
            if len(chosen) > count:
                return False
        elif len(chosen) != count:
            return False
        # "…both on top of your library **or both on the bottom of your
        # library**" (Dream Cache). Which end is part of the answer, and only
        # where the card offers it: a bottoming answer on Brainstorm is refused
        # rather than ignored, because ignoring it would put the cards on top
        # while the client believed it had bottomed them.
        destination = choice.data.get("destination")
        # "…on **the bottom** of their library in any order." (Teferi's Puzzle
        # Box.) The card names the end and the player only names the order, so
        # the answer's ``to_bottom`` says nothing here — read as the offer it is
        # on Dream Cache, a default-False answer would put the whole hand back
        # on top, which is the opposite card.
        if destination == "bottom":
            position = "bottom"
        else:
            if to_bottom and destination != "either_end":
                return False
            position = "bottom" if to_bottom else "top"
        player = self.players[choice.player_index]
        cards = [hand[index] for index in chosen]
        # On the bottom the printed order is the order they are named, because
        # the first named goes down first; on top it is reversed, so the first
        # named ends up on top. Both are the same sentence read from the
        # library's own end.
        for card in (cards if position == "bottom" else reversed(cards)):
            if self.take_card_from_hand(player, card):
                self.put_card_into_library(player, card, position=position)
        # "**Shuffle** a card from your hand into your library."
        # (Lat-Nam's Legacy.) CR 701.24a makes the shuffle part of the move
        # rather than a rider on it, so it happens here rather than as a step
        # after — and where in the library the cards were put stops meaning
        # anything, which is why the two sentences can share one prompt.
        #
        # Through the module-level RNG every other shuffle in this engine uses,
        # so a seeded run stays reproducible.
        if choice.data.get("shuffle"):
            self.shuffle_library_of(player)
            self.log.append(
                f"{player.name} shuffled {len(cards)} card(s) into their library"
            )
            # "…, **then draw that many cards**." (Credit Voucher.) The draw is
            # part of this move rather than a step after it, for the reason the
            # shuffle above already is: "that many" is the number the answer
            # just decided, and this is the only place in the engine that knows
            # it — a later step would be reading a count recorded before the
            # question was asked.
            #
            # Through ``_draw_with_replacements``, the one draw seam, so an
            # armed draw replacement applies here exactly as it would in a draw
            # step.
            if choice.data.get("draw_after") and cards:
                drawn = self._draw_with_replacements(player, len(cards))
                self.log.append(f"{player.name} draws {drawn} card(s)")
        else:
            self.log.append(
                f"{player.name} put {len(cards)} card(s) on the {position} of "
                f"their library"
            )
        self.discard_pending_choice(choice)
        return True

    def _default_hand_to_library(self, choice: PendingChoice) -> None:
        """Put back the cards the seat least wants to hold, the one of them it
        wants most named first — on top, drawn first
        (``ai_prompt_picks.hand_to_library_picks``).

        How many is the card's business (an exact count, or the whole offer of
        an "any number"); which ones was the first cards in hand, so a
        Brainstorm put back the two spells it had just drawn beside a fourth
        land.
        """
        from ....ai_prompt_picks import hand_to_library_picks

        count = min(int(choice.data["count"]), len(self.players[choice.player_index].hand))
        picks = hand_to_library_picks(self, choice.player_index, count)
        if not self._resolve_hand_to_library(choice, picks):
            self.discard_pending_choice(choice)

    def _default_discard(self, choice: PendingChoice) -> None:
        """Discard the *eligible* cards the seat least wants to hold
        (``ai_prompt_picks.discard_order``: a payable madness card first, then
        by ``held_worth``, the card sparing a printed penalty ahead of both —
        ``ai_prompts.order_discard``), hand order between equals. The
        lowest-index cards were the discard.

        Where the prompt offers Library of Leng's library top, each card goes
        there as ``ai_prompt_picks.takes_library_top`` says — the answer the
        Library's own offer gets on a discard the seat did not choose
        (``replacements/zone_changes._leng_discard_default``). It declined the top
        always: the graveyard was every default's.

        Which cards are candidates at all is not policy but the card's printed
        phrase, so it is read from the same list the interactive seat is
        offered. Re-read each time round, because each discard renumbers the
        hand behind it.
        """
        from ....ai_prompt_picks import discard_order, takes_library_top
        from ....handlers.discards import _resolve_one_discard

        discarded = 0
        took: list = []
        weighed: dict = {}
        # Whose sentence this is, for the default — the card the arming site
        # named, else the object stamped as resolving when it was armed — and
        # the seat that caused it (CR 109.5, ``discard_cause_seat``): "You
        # gain 3 life for each land card discarded this way" (Gerrard's
        # Verdict) is a payoff the discarder's choice decides.
        source_card = choice.data.get("_source_card")
        if source_card is None:
            source_card = getattr(choice.data.get("_stack_item"), "card", None)
        cause_seat = self.discard_cause_seat(choice.data.get("_cause_seat"))
        # One event: a discard an opponent causes can put the card onto the
        # battlefield instead (Dodecapod), and every such card enters together
        # (CR 603.6a).
        with self.entering_together():
            for _ in range(int(choice.data["count"])):
                eligible = discard_order(
                    self, choice.player_index, self.live_discard_candidates(choice),
                    source_card, weighed, cause_seat=cause_seat,
                )
                if not eligible:
                    break
                to_library = bool(choice.data.get("allow_top_of_library")) and (
                    takes_library_top(
                        self, choice.player_index,
                        self.players[choice.player_index].hand[eligible[0]],
                    )
                )
                if not _resolve_one_discard(
                    self, choice.player_index, eligible[0], to_library=to_library,
                    took=took,
                ):
                    break
                discarded += 1
        self.discard_pending_choice(choice)
        # The stated policy for "up to" is to take the whole offer, and the
        # reason has widened rather than changed. It used to be "this pairing
        # only ever prints with a draw behind it, so discarding fewer is
        # strictly less card selection for the same cards" — a fact about which
        # cards existed, which stopped being true when "discard **any number of**
        # creature cards. For each card discarded this way, put two +1/+1
        # counters on this creature" (Mind Maggots) arrived with counters behind
        # it instead of a draw. The policy still holds on both, because on both
        # the offer buys something per card; it is a policy for a seat that does
        # not evaluate, not a claim about the pool, and the next card to print a
        # ceiling whose payoff is *not* worth the cards is what would need a
        # real valuation here rather than a default.
        self._after_discard_answered(choice, discarded, took)

    def auto_resolve_pending_discard(self) -> None:
        """Resolve a pending discard with a default choice (the cards least
        worth holding, kept in the graveyard). Used for AI players and
        headless simulation."""
        self.auto_resolve_pending_choices(kinds=("discard",))

    # -- A card exiled out of a hand -----------------------------------------

    def live_exile_from_hand_choices(self, choice: PendingChoice) -> list[int]:
        """The hand slots still eligible, from the engine's own rule.

        Re-run rather than stored, for ``live_put_from_hand_choices``' reason:
        the list the seat is offered and the list its answer is checked against
        have to be one list.
        """
        from ....handlers.hand import exile_from_hand_candidates

        return exile_from_hand_candidates(
            self, choice.data.get("_payload") or {}, self.players[choice.player_index]
        )

    def live_exile_hand_pile_choices(self, choice: PendingChoice) -> list[int]:
        """The hand slots the "any number of cards" pick may name.

        Re-run rather than stored, for ``live_exile_from_hand_choices``'
        reason one prompt over: the list the seat is offered and the list its
        answer is checked against have to be one list.
        """
        from ....handlers.hand import exile_from_hand_candidates

        return exile_from_hand_candidates(
            self, choice.data.get("_payload") or {},
            self.players[choice.player_index],
        )

    def confirm_exile_hand_pile(self, player_index: int, hand_indices) -> bool:
        """Answer Scroll Rack's "exile **any number of** cards from your hand".

        "Any number" includes **zero**, which is a real answer and not a
        decline: the sentence behind it puts *that many* cards from the library
        into the hand, so answering none is an activation that legally does
        nothing.
        """
        return self.resolve_pending_choice(
            "exile_hand_pile_choice", player_index, hand_indices=hand_indices
        )

    def _resolve_exile_hand_pile(self, choice: PendingChoice, hand_indices) -> bool:
        """Exile the named slots as one linked pile.

        Every pick is validated **before** anything moves, the rule the exile
        search states: one bad slot rejects the whole answer and leaves the
        prompt queued, so a malformed request cannot exile half a selection.
        A repeat is rejected rather than deduplicated — a seat naming one card
        twice has not said what it means.
        """
        live = set(self.live_exile_hand_pile_choices(choice))
        cleaned: list[int] = []
        for index in hand_indices or []:
            if not isinstance(index, int) or index not in live or index in cleaned:
                return False
            cleaned.append(index)
        self.exile_hand_slots(
            choice.data.get("_context"),
            choice.data.get("_source_permanent"),
            choice.player_index,
            cleaned,
            face_down=bool((choice.data.get("_payload") or {}).get("face_down")),
        )
        self.discard_pending_choice(choice)
        return True

    def _default_exile_hand_pile(self, choice: PendingChoice) -> None:
        """The stated policy: **every** eligible card.

        The same reading ``_default_search_exile`` gives an unbounded "any
        number": each card comes straight back — Scroll Rack replaces them one
        for one off the library and Duplicity hands the previous pile over — so
        the maximum is the only default that leaves nothing on the table. A
        seat that took none would activate the artifact and do nothing at all.
        """
        if not self._resolve_exile_hand_pile(
            choice, self.live_exile_hand_pile_choices(choice)
        ):
            self.discard_pending_choice(choice)

    def confirm_exile_from_hand_choice(self, player_index: int, hand_index) -> bool:
        """Answer the pending pick. ``hand_index`` of None declines, which is an
        answer only where the sentence made an offer: "You **may** exile a
        nonland card from your hand" (Ice Cauldron). The bare printing — "Exile
        a card from your hand face down" (Gustha's Scepter) — is mandatory and
        refuses it, because a decline there is an ability that resolves having
        moved nothing."""
        return self.resolve_pending_choice(
            "exile_from_hand_choice", player_index, hand_index=hand_index
        )

    def _resolve_exile_from_hand_choice(self, choice: PendingChoice, hand_index) -> bool:
        """Exile the chosen card, and record it for the sentence behind this one.

        Two records, both needed and both about the same card:

        * ``exiled_cards`` on the resolution's scratchpad is what "you may cast
          **that card**" reads (`_PRODUCES`);
        * the linked-exile entry on the artifact is what "the last card exiled
          with **this artifact**" reads, long after this resolution is over
          (CR 610.3) — and it lives on the permanent rather than on the game
          because the permanent is what the phrase names.
        """
        from ....linked_exile import link_exiled_card

        player = self.players[choice.player_index]
        live = self.live_exile_from_hand_choices(choice)
        name = choice.data.get("card_name", "Effect")
        payload = choice.data.get("_payload") or {}
        if hand_index is None:
            # Only an *offer* may be declined. True by default because the
            # offered printing is the one that shipped first; the mandatory
            # printing says so in its payload.
            if not payload.get("optional", True):
                return False
            self.log.append(f"{player.name} exiled no card ({name})")
            self.discard_pending_choice(choice)
            return True
        if hand_index not in live:
            return False
        card = player.hand[hand_index]
        # Through the hand seam: a deck repeats one immutable definition per
        # copy, so an identity filter over the hand would remove every copy
        # where this removes exactly one.
        self.take_card_from_hand(player, card)
        card = self.put_card_into_exile(player, card)
        source = choice.data.get("_source_permanent")
        if source is not None:
            # CR 406.3's rider travels on the *entry*, not on the card: two
            # copies of one card in a deck are the same ``CardDefinition``
            # object, so the record of the exiling is the only thing that can
            # say which one is hidden. The *look* permission that may follow it
            # ("You may look at it for as long as it remains exiled", Gustha's
            # Scepter) is a sentence of its own and writes its own key onto
            # this entry once this prompt has been answered.
            link_exiled_card(
                source, card, choice.player_index,
                face_down=bool(payload.get("face_down")),
            )
        elif payload.get("face_down"):
            # CR 406.3 needs a record somebody can still find, and with no
            # permanent to hold it the game's register does — the arrangement
            # ``exile_hand_slots`` keeps for Suppress.
            record_exiled_card(self, card, choice.player_index, face_down=True)
        context = choice.data.get("_context")
        if context is not None:
            context.results.setdefault("exiled_cards", []).append(card)
        # "Exile a card from your hand **face down**." (Gustha's Scepter.) Its
        # name is nobody's to read (CR 406.3, 400.2) and ``game.log`` is every
        # seat's: the line says that a card went, not which.
        what = "a card face down" if payload.get("face_down") else card.name
        self.log.append(f"{player.name} exiled {what} from their hand ({name})")
        self.discard_pending_choice(choice)
        return True

    def _default_exile_from_hand_choice(self, choice: PendingChoice) -> None:
        """The stated policy: **a card** — the cheapest one to give up.

        This said "decline" for the offered printing, on the reasoning that a
        headless seat taking Ice Cauldron's offer would bury a card every time
        the artifact was activated. But the pick is not where that decision is
        made. "You may exile a card from your hand" is an ``optional_pay`` in
        front of this prompt, and *that* is the offer a seat nobody asks
        declines or takes (``_default_optional_pay``, and the trade it weighs);
        this prompt exists only once the offer has been taken. A seat that
        took it and then answered "no card" had said yes and no to one
        question — which is how Forsaken City's "If you do, untap this land"
        came to be an untap nobody could pay for honestly, and why the AI's
        pricing of that trade had to refuse it outright.

        So: the eligible card with the **lowest mana value**, the lowest hand
        slot among equals. One number printed on every card and nothing a
        valuation would have to explain; a seat that should keep its lands
        wants a weight in ``engine/ai_valuation.py`` rather than a branch here.

        **A mandatory exile** keeps the policy ``_default_discard`` states —
        the lowest-index eligible card — for the reason it always had: Mind
        Swords and Parallax Nexus take whatever is in front. Which cards are
        eligible at all is the printed phrase's business and is read off the
        same list the interactive seat is offered, never a second copy.
        """
        live = self.live_exile_from_hand_choices(choice)
        if live and (choice.data.get("_payload") or {}).get("optional", True):
            hand = self.players[choice.player_index].hand
            live = sorted(live, key=lambda slot: (hand[slot].cmc, slot))
        if live and self._resolve_exile_from_hand_choice(choice, live[0]):
            return
        # Nothing eligible: the offer was never made rather than declined,
        # which is the rule ``exile_chosen_card_from_hand`` states, and the
        # prompt has to come off the queue or the resolution never finishes.
        self.discard_pending_choice(choice)

    # -- A card put onto the battlefield out of a hand -----------------------

    def arm_put_from_hand_choice(self, player_index: int, payload: dict, context) -> None:
        """Queue "pick a card in your hand to put onto the battlefield" for
        *player_index*.

        The whole payload travels rather than the candidate list, for the reason
        ``arm_permanent_choice`` gives: it is the *rule* the candidates came
        from, and re-running it is what keeps the list offered and the list an
        answer is checked against from being two lists.
        """
        self.arm_pending_choice(
            "put_from_hand_choice", player_index,
            card_name=context.card.name,
            optional=bool(payload.get("optional")),
            _payload=dict(payload),
            _context=context,
        )

    def live_put_from_hand_choices(self, choice: PendingChoice) -> list[int]:
        """The hand slots still eligible, from the engine's own rule."""
        from ....handlers.hand import put_from_hand_candidates

        return put_from_hand_candidates(
            self, choice.data.get("_payload") or {}, self.players[choice.player_index]
        )

    def confirm_put_from_hand_choice(self, player_index: int, hand_index) -> bool:
        """Answer the pending pick. ``hand_index`` of None is declining, which is
        only an answer when the sentence said "may"."""
        return self.resolve_pending_choice(
            "put_from_hand_choice", player_index, hand_index=hand_index
        )

    def _resolve_put_from_hand_choice(self, choice: PendingChoice, hand_index) -> bool:
        from ....repeated_offers import OFFER_TAKEN_RESULTS

        player = self.players[choice.player_index]
        live = self.live_put_from_hand_choices(choice)
        name = choice.data.get("card_name", "Effect")
        if hand_index is None:
            # Declining. Refused outright on a mandatory pick with something
            # legal left, so a client cannot answer a sentence that offered no
            # way out — but allowed once nothing qualifies, because then the
            # decision is over either way (CR 608.2b).
            if live and not choice.data.get("optional"):
                return False
            self.log.append(f"{player.name} put no card onto the battlefield")
            self.discard_pending_choice(choice)
            return True
        if hand_index not in live:
            return False
        card = player.hand[hand_index]
        if stays_out_of_battlefield(self, card, player, "hand"):
            # Asked before the card leaves the hand (CR 614.17, 400.4a): a land
            # picked under Worms of the Earth "will stay where it is" (its
            # ruling, 2004-10-04). The pick is answered and nothing was put
            # onto the battlefield, so a repeated round (Eureka) records no
            # taken offer — "until no one puts a card onto the battlefield".
            self.discard_pending_choice(choice)
            return True
        player.hand = [c for i, c in enumerate(player.hand) if i != hand_index]
        # "…onto the battlefield **tapped**." (Terrain Generator.) CR 110.5b:
        # the entry state is the effect's to say, so it is set on the object
        # before it enters rather than by a tap after — no "becomes tapped"
        # event happens, which is what the printed word means.
        arrival = Permanent(
            card=card,
            tapped=bool((choice.data.get("_payload") or {}).get("tapped")),
        )
        host_id = (choice.data.get("_payload") or {}).get("attach_to_permanent_id")

        # Once it is there — the entry's ``then``, run at the answer when an
        # "as it enters" choice keeps it on its way (CR 614.12a).
        def arrived() -> None:
            # A replacement that took the entry away wrote its own line, and
            # nothing of this is owed for an entry that never happened
            # (``entry_awaiting.entry_happened``).
            if not entry_happened(arrival):
                return
            # "…onto the battlefield **attached to this creature**." (Academy
            # Researchers.) CR 303.4f: the Aura is attached as it enters. Done
            # here rather than by a step behind this one because the permanent
            # does not exist until the answer arrives — the same reason the id
            # record below is written here — and because an Aura that existed
            # for even one state-based check attached to nothing would be put
            # into a graveyard by CR 704.5m.
            #
            # The host is addressed by the id the arming froze (CR 400.7), and
            # the legality was already asked of the *candidate list* — CR
            # 303.4a is why this card is not in the offer at all when the
            # source cannot carry it, so nothing is re-checked here that could
            # leave the Aura unattached.
            if isinstance(host_id, int):
                from ....aura_attachment import attach_aura

                host = self.permanent_by_id(host_id)
                if host is not None:
                    attach_aura(arrival, host)
                    self._recompute_continuous_effects()
            self.log.append(
                f"{player.name} put {card.name} onto the battlefield ({name})"
            )

        self._put_permanent_onto_battlefield(
            choice.player_index, arrival, None, then=arrived,
        )
        # "If you do, sacrifice **it** …" (Flash). By id, like every other
        # producer of a permanent this engine records: the permanent may leave
        # between two steps of one resolution, and a returning one is a new
        # object (CR 400.7). Written here rather than in the handler that armed
        # the prompt, because the permanent does not exist until the answer
        # arrives — the same reason the reanimation is the only step that can
        # name what it reanimated.
        #
        # Set rather than appended: a repeated round (Eureka) offers the seats
        # in turn and each answer replaces the last, which is right for a
        # sentence naming "it" — a card printing "each of them" would want the
        # list, and there is none in the pool.
        choice.data["_context"].results[PUT_FROM_HAND_PERMANENTS] = (
            arrival.permanent_id
        )
        # The record a repeated round ends on — see engine/repeated_offers.py.
        # Appended rather than set, because every seat of the round shares the
        # one resolution scratchpad.
        choice.data["_context"].results.setdefault(OFFER_TAKEN_RESULTS, []).append(
            card.name
        )
        self.discard_pending_choice(choice)
        return True

    def _default_put_from_hand_choice(self, choice: PendingChoice) -> None:
        """The eligible card worth most as a permanent
        (``ai_prompt_picks.put_from_hand_pick``), never a decline while one is
        offered: more battlefield is what the AI plays toward, the policy
        ``put_cards_from_hand_onto_battlefield`` states for the sweep beside
        it.

        Which card was the first in hand order, so Metamorphose's opponent put
        a Forest onto the battlefield holding a Craw Wurm.
        """
        from ....ai_prompt_picks import put_from_hand_pick

        live = self.live_put_from_hand_choices(choice)
        pick = put_from_hand_pick(self, choice.player_index, live)
        if pick is None or not self._resolve_put_from_hand_choice(choice, pick):
            self._resolve_put_from_hand_choice(choice, None)

    # -- A card brought into a hand from outside the game --------------------

    def arm_outside_game_pick(self, player_index: int, payload: dict, context) -> None:
        """Queue "pick a card you own from outside the game" for *player_index*
        (the Wishes; CR 400.11b).

        The put-from-hand pick above with the other end moved: the candidates
        are sideboard positions and the destination is the hand. The whole
        payload travels for ``arm_put_from_hand_choice``'s reason — it is the
        *rule* the candidates came from, so the list offered and the list an
        answer is checked against are one list.
        """
        self.arm_pending_choice(
            "outside_game_pick", player_index,
            card_name=context.card.name if context.card is not None else "Effect",
            optional=bool(payload.get("optional")),
            reveal=bool(payload.get("reveal")),
            _payload=dict(payload),
            _context=context,
        )

    def live_outside_game_picks(self, choice: PendingChoice) -> list[int]:
        """The sideboard positions still eligible, from the engine's own rule."""
        from ....handlers.cards import outside_game_candidates

        return outside_game_candidates(
            self, choice.data.get("_payload") or {}, self.players[choice.player_index]
        )

    def confirm_outside_game_pick(self, player_index: int, sideboard_index) -> bool:
        """Answer the pending pick with a position in the seat's sideboard.
        ``None`` declines, which is an answer only when the step was offered
        (the "you may" in front of it) or once nothing qualifies."""
        return self.resolve_pending_choice(
            "outside_game_pick", player_index, sideboard_index=sideboard_index
        )

    def _resolve_outside_game_pick(self, choice: PendingChoice, sideboard_index) -> bool:
        player = self.players[choice.player_index]
        live = self.live_outside_game_picks(choice)
        name = choice.data.get("card_name", "Effect")
        if sideboard_index is None:
            # Refused on a mandatory pick with something left to take, so a
            # client cannot answer a sentence that offered no way out — Ring of
            # Ma'rûf's "instead put a card" — but allowed once nothing qualifies,
            # because then the decision is over either way (CR 608.2b).
            if live and not choice.data.get("optional"):
                return False
            self.log.append(
                f"{player.name} put no card from outside the game into their "
                f"hand ({name})"
            )
            self.discard_pending_choice(choice)
            return True
        if sideboard_index not in live:
            return False
        self.bring_card_from_outside_game(
            choice.player_index, sideboard_index,
            source_name=name, revealed=bool(choice.data.get("reveal")),
        )
        self.discard_pending_choice(choice)
        return True

    def _default_outside_game_pick(self, choice: PendingChoice) -> None:
        """The stated policy: the eligible card the seat would most want to
        tutor for (``ai_prompts.choose_outside_game_card``), the same weight a
        library search's AI answer reads — a sideboard is a pile the seat may
        look through in full (CR 400.11a), which is the search's situation
        exactly. A pick refused for any reason falls back to the decline, and a
        decline refused (a mandatory pick) to the first eligible card, so the
        prompt always comes off the queue."""
        from ....ai_prompts import choose_outside_game_card

        live = self.live_outside_game_picks(choice)
        pick = choose_outside_game_card(self, choice.player_index, live)
        if pick is not None and self._resolve_outside_game_pick(choice, pick):
            return
        if self._resolve_outside_game_pick(choice, None):
            return
        if not (live and self._resolve_outside_game_pick(choice, live[0])):
            self.discard_pending_choice(choice)

    # -- Cards picked out of a hand for a later step to act on ---------------

    def arm_choose_cards_in_hand(self, player_index: int, payload: dict, context) -> None:
        """Queue "choose N cards in your hand …" for *player_index*.

        The whole payload travels rather than the candidate list, for the
        reason ``arm_put_from_hand_choice`` gives: it is the *rule* the
        candidates came from, and re-running it is what keeps the list offered
        and the list an answer is checked against from being two lists.
        """
        self.arm_pending_choice(
            "choose_cards_in_hand", player_index,
            card_name=context.card.name,
            count=int(payload.get("count", 1)),
            _payload=dict(payload),
            _context=context,
        )

    def live_choose_cards_in_hand(self, choice: PendingChoice) -> list[int]:
        """The hand slots still eligible, from the engine's own rule."""
        from ....handlers.hand import chosen_hand_card_candidates

        return chosen_hand_card_candidates(
            self, choice.data.get("_payload") or {}, self.players[choice.player_index]
        )

    def _how_many_cards_to_choose(self, choice: PendingChoice) -> int:
        """How many the seat owes: the printed number, or every eligible card
        when the hand holds fewer (CR 608.2, do as much as possible).

        For a printed "**any number of**" (Metalworker and the eleven Urza's
        Destiny cards printed with it) the sentence names no count at all, so
        this answers the *maximum* and :meth:`_may_choose_fewer_cards_in_hand`
        is what tells a caller the pick may stop short of it. One number and one
        flag rather than a second method, because every reader — the resolve,
        the default and the prompt — needs both halves and a reader that got one
        of them would gate a Confirm the engine then refuses.
        """
        live = len(self.live_choose_cards_in_hand(choice))
        if (choice.data.get("_payload") or {}).get("up_to"):
            # "…put **up to seven** permanent cards from your hand onto the
            # battlefield." (Ugin, the Spirit Dragon's −10.) A printed ceiling:
            # the most is the count or the hand's eligible cards, whichever is
            # fewer, and :meth:`_may_choose_fewer_cards_in_hand` lets the pick
            # stop anywhere under it, nought included.
            return min(int(choice.data.get("count", 1)), live)
        if self._may_choose_fewer_cards_in_hand(choice):
            return live
        # "…chooses one card **of each color** from it" (Noxious Vapors). The
        # number owed is not printed and is not the hand's size: it is how many
        # of the printed slots this hand can fill at once, each with a card of
        # its own — a maximum matching, for ``_match_keeps``' reason.
        slotted = self.match_hand_slots(choice)
        if slotted is not None:
            return len(slotted)
        return min(int(choice.data.get("count", 1)), live)

    def match_hand_slots(
        self, choice: PendingChoice, hand_indices: "list[int] | None" = None,
    ) -> "dict[int, int] | None":
        """``{slot: hand index}`` for a slotted hand pick, or ``None`` when the
        pick is an ordinary counted one.

        Over *hand_indices* when given — an answer being checked — and over
        every live candidate otherwise, which is the most the card lets this
        seat keep. Assigned by hand **slot**, never by card: two copies of one
        card in a hand are one object, and a red pick naming one Lightning Bolt
        must not be read as naming both.
        """
        from ....handlers._filters import _card_matches_filter
        from ....handlers.hand import hand_slot_filters

        slot_filters = hand_slot_filters(choice.data.get("_payload") or {})
        if slot_filters is None:
            return None
        player = self.players[choice.player_index]
        candidates = (
            self.live_choose_cards_in_hand(choice)
            if hand_indices is None else list(hand_indices)
        )
        return self._match_keeps(
            candidates, slot_filters,
            lambda index, described: _card_matches_filter(
                player.hand[index], described, game=self, owner=player
            ),
        )

    def _may_choose_fewer_cards_in_hand(self, choice: PendingChoice) -> bool:
        """Whether the printed offer is "any number of …" rather than a count.

        Read off the payload the lowering wrote rather than inferred from the
        count, because nought is a legal answer to "any number" and an illegal
        one to "choose two": the two offers are told apart by the words the card
        prints, not by how many cards happen to be in the hand.
        """
        payload = choice.data.get("_payload") or {}
        # "Up to N" is the same promise with a ceiling (Ugin's −10): nought is
        # legal, and the count is how many at most.
        return bool(payload.get("any_number") or payload.get("up_to"))

    def confirm_choose_cards_in_hand(self, player_index: int, hand_indices) -> bool:
        return self.resolve_pending_choice(
            "choose_cards_in_hand", player_index, hand_indices=hand_indices
        )

    def _record_chosen_cards_in_hand(self, choice: PendingChoice, cards: list) -> None:
        context = choice.data["_context"]
        payload = choice.data.get("_payload") or {}
        key = str(payload.get("result_key") or "chosen_hand_cards")
        # The card objects, not their hand slots: the step that reads this
        # record moves cards out of the hand, and an index stops naming the
        # same card the moment one leaves.
        per_seat = payload.get("actor") in ("each_player", "each_opponent")
        if per_seat:
            # "**Each player** chooses a card in their hand." (Stronghold
            # Gambit.) "**Each opponent** may put any number of …" (Tempting
            # Wurm.) One entry per seat, seeded by the handler — a flat list
            # would be overwritten by whichever seat answered last.
            context.results.setdefault(key, {})[choice.player_index] = list(cards)
        else:
            context.results[key] = list(cards)
        # "**Reveal** any number of blue cards in your hand." (Brine Seer.) The
        # count the sentence behind it spends, beside the cards themselves —
        # two records for one step, because "for each card revealed this way"
        # asks a number and "for each blue instant card revealed this way"
        # (Sirocco) asks the cards. Written even for an empty pick, because an
        # absent key is a back-reference with no producer — a different thing
        # from a reveal that showed nothing.
        count_key = payload.get("count_key")
        if count_key and per_seat:
            # "…for each card **they** revealed this way" (Kamahl's Summons):
            # each seat's own number, beside every other seat's.
            context.results.setdefault(str(count_key), {})[
                choice.player_index
            ] = len(cards)
        elif count_key:
            context.results[str(count_key)] = len(cards)
        # …and the making-public itself (CR 701.20a), through the one feed the
        # web layer reads. Keyed on the printed verb rather than on the count
        # above, because those are two questions: a pick that records a number
        # need not be public, and Sylvan Library's is not.
        if payload.get("reveal") and cards:
            self.record_reveal(choice.player_index, [card.name for card in cards])
        self.discard_pending_choice(choice)

    def _resolve_choose_cards_in_hand(self, choice: PendingChoice, hand_indices) -> bool:
        player = self.players[choice.player_index]
        live = self.live_choose_cards_in_hand(choice)
        wanted = self._how_many_cards_to_choose(choice)
        picks = list(hand_indices or [])
        if len(set(picks)) != len(picks):
            return False
        # "Any number" makes *wanted* a ceiling and nought a legal answer; a
        # printed count makes it exact. Checked here rather than left to the
        # client, for the reason the candidate list is re-derived above: the
        # list an answer is checked against and the offer a board rendered have
        # to be one rule.
        if self._may_choose_fewer_cards_in_hand(choice):
            if len(picks) > wanted:
                return False
        elif len(picks) != wanted:
            return False
        if any(index not in live for index in picks):
            return False
        # A slotted pick is an *assignment*: as many cards as the hand can fill
        # slots with (checked above, through ``_how_many_cards_to_choose``) and
        # each in a slot of its own — two red cards are not "one card of each
        # color", however many colours the hand could have kept.
        slotted = self.match_hand_slots(choice, picks)
        if slotted is not None and len(slotted) != len(picks):
            return False
        cards = [player.hand[index] for index in picks]
        self._record_chosen_cards_in_hand(choice, cards)
        name = choice.data.get("card_name", "Effect")
        payload = choice.data.get("_payload") or {}
        verb = "revealed" if payload.get("reveal") else "chose"
        if not payload.get("reveal"):
            # A card chosen out of a hand stays in a hidden zone (CR 400.2)
            # until a sentence shows it: "choose two cards in your hand drawn
            # this turn" (Sylvan Library) reveals nothing, and CR 101.4a lets
            # a chosen card stay face down (Stronghold Gambit). The log is
            # public, so the line counts; the sentence that reveals, discards
            # or puts a card onto the battlefield is the one that names it.
            chosen = f"{len(cards)} card(s)" if cards else "no cards"
        else:
            chosen = ", ".join(c.name for c in cards) or "no cards"
        self.log.append(f"{player.name} {verb} {chosen} ({name})")
        return True

    def _default_choose_cards_in_hand(self, choice: PendingChoice) -> None:
        """The eligible cards the step behind the pick wants, by what each is
        worth for what that step does with them
        (``ai_prompt_picks.hand_pick_order``: put onto the battlefield, the
        dearest there; spared by a sweep of the rest, the dearest to hold;
        acted on otherwise, the cheapest to hold), hand order between equals
        so a seed still reproduces a run. Hand order was the whole answer, so
        Sylvan Library's two cards were the first two drawn.

        The program's own preferences go on top
        (``ai_prompts.order_hand_pick``): a pick the program then puts onto the
        battlefield for its owner (Stronghold Gambit) takes the card that
        sentence admits, at its superlative's extreme.
        """
        from ....ai_prompt_picks import hand_pick_order
        from ....ai_prompts import order_hand_pick

        context = choice.data.get("_context")
        payload = choice.data.get("_payload") or {}
        card = getattr(context, "card", None)
        live = order_hand_pick(
            self, choice.player_index,
            hand_pick_order(
                self, choice.player_index, self.live_choose_cards_in_hand(choice),
                payload, card,
            ),
            payload, card,
        )
        wanted = self._how_many_cards_to_choose(choice)
        # For "any number of" that is every eligible card, which is the offer's
        # ceiling rather than a valuation: nothing is spent to reveal, and every
        # sentence in the pool that reads the count reads it upward. Stated here
        # so a seat that should reveal fewer needs a weight in
        # ``engine/ai_valuation.py`` and not a branch in this method.
        answer = live[:wanted]
        # A slotted pick's first *wanted* candidates need not be assignable
        # (two red cards ahead of the hand's one blue), so the default is the
        # matching itself, over the candidates in the order above — the
        # matching keeps an earlier candidate wherever one can be kept, so
        # Noxious Vapors spares each colour's dearest card.
        slotted = self.match_hand_slots(choice, live)
        if slotted is not None:
            answer = sorted(slotted.values())
        if not self._resolve_choose_cards_in_hand(choice, answer):
            self._record_chosen_cards_in_hand(choice, [])

    # -- Glasses of Urza's revealed hand -------------------------------------

    def dismiss_hand_reveal(self, viewer_index: int) -> bool:
        """The viewer has seen the revealed hand; take the prompt down."""
        return self.resolve_pending_choice("hand_reveal", viewer_index)

    def _dismiss_hand_reveal(self, choice: PendingChoice) -> bool:
        self.discard_pending_choice(choice)
        return True


# ---------------------------------------------------------------------------
# This family's rows of the prompt table
# ---------------------------------------------------------------------------
#
# One ``ChoiceSpec`` per prompt kind of this family, in the table's order
# (``engine/pending_choices.py`` says what each field means). ``table.py``
# registers them, in the one list ``Game.iter_pending_prompts`` reads.

HAND_TO_LIBRARY_SPEC = ChoiceSpec(
    "hand_to_library",
    resolve=lambda game, choice, r: game._resolve_hand_to_library(
        choice, r["hand_indices"], bool(r.get("to_bottom")),
    ),
    default=lambda game, choice: game._default_hand_to_library(choice),
    action="hand_to_library_confirm",
    prompt_key="hand_to_library",
    blocked_detail="choose which cards go back on top of your library",
    blocks_every_seat=True,
    spectator_visible=True,
    hidden_for_ai=False,
    # Brainstorm draws three and then puts two back, and the two are steps of
    # one resolution: nothing after the prompt may read a hand the answer has
    # not reshaped yet (CR 608.2, CR 117.3b).
    suspends=True,
)

REVEALED_HAND_PICK_SPEC = ChoiceSpec(
    "revealed_hand_pick",
    # ``.get``, not ``[...]``: an answer with **no** index is the chooser
    # declining, which "choose **up to** X cards from it" (Discordant Dirge)
    # permits and every earlier printing does not. The resolver is what decides
    # whether the words were printed; a subscript here would make the decline a
    # KeyError before it could be judged.
    resolve=lambda game, choice, r: game._resolve_revealed_hand_pick(
        choice, r.get("hand_index")
    ),
    default=lambda game, choice: game._default_revealed_hand_pick(choice),
    action="revealed_hand_pick_confirm",
    prompt_key="revealed_hand_pick",
    blocked_detail="choose a card from the revealed hand before other actions",
    # "…then you choose a card … from it. **Search that player's graveyard,
    # hand, and library for all cards with the same name as the chosen card**…"
    # (Lobotomy.) The step behind the pick reads what it chose, so it must not
    # run while the choice is still owed (CR 608.2, CR 117.3b) — the same reason
    # ``search_library`` suspends, and inert for every printing that has
    # nothing behind the pick.
    suspends=True,
    # The revealed hand is public from the moment it is revealed (CR 701.20),
    # so a spectator sees the prompt exactly as the choosing seat does.
    spectator_visible=True,
)

DISCARD_SPEC = ChoiceSpec(
    "discard",
    resolve=lambda game, choice, r: game._resolve_discard(choice, r["hand_indices"], r["to_library"]),
    default=lambda game, choice: game._default_discard(choice),
    action="discard_confirm",
    prompt_key="discard_select",
    blocked_detail="complete discard before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    # "Discard X cards, then <do something for each card discarded this way>"
    # (Recall) is the shape: the step behind the discard has to see the cards
    # that were actually discarded, not the hand as it stood when the prompt was
    # armed. CR 608.2 / CR 117.3b — nothing else in the resolution happens until
    # the last of its prompts is answered.
    suspends=True,
)

HAND_REVEAL_SPEC = ChoiceSpec(
    "hand_reveal",
    resolve=lambda game, choice, r: game._dismiss_hand_reveal(choice),
    default=lambda game, choice: game._dismiss_hand_reveal(choice),
    action="dismiss_hand_reveal",
    prompt_key="hand_reveal",
    # Not a decision — the viewer has already seen the hand. Nothing waits on it.
    blocked_detail=None,
    spectator_visible=True,
    hidden_for_ai=False,
)

EXILE_FROM_HAND_CHOICE_SPEC = ChoiceSpec(
    "exile_from_hand_choice",
    resolve=lambda game, choice, r: game._resolve_exile_from_hand_choice(
        choice, r.get("hand_index")
    ),
    default=lambda game, choice: game._default_exile_from_hand_choice(choice),
    action="exile_from_hand_confirm",
    prompt_key="exile_from_hand_choice",
    blocked_detail="choose a card to exile before other actions",
    # The sentence behind this one reads what was exiled ("you may cast that
    # card for as long as it remains exiled"), so nothing after it may run
    # until it is answered (CR 608.2).
    suspends=True,
    # …and a non-interactive seat therefore never queues it: the rest of the
    # activation — the charge counter and the mana note — has to finish, which
    # is the same reason `cast_choice` and `pay_life_to_save` take their default
    # where the offer stands.
    default_at_arm=True,
    # A hand is hidden (CR 400.2), so the options are the chooser's alone.
    hidden_for_ai=False,
)

EXILE_HAND_PILE_CHOICE_SPEC = ChoiceSpec(
    "exile_hand_pile_choice",
    resolve=lambda game, choice, r: game._resolve_exile_hand_pile(
        choice, r.get("hand_indices") or []
    ),
    default=lambda game, choice: game._default_exile_hand_pile(choice),
    action="exile_hand_pile_confirm",
    prompt_key="exile_hand_pile_choice",
    blocked_detail="choose which cards to exile before other actions",
    # "Put **that many** cards from the top of your library into your hand" is
    # the next step of the same resolution and reads what this exiled, so
    # nothing after it may run until it is answered (CR 608.2).
    suspends=True,
    # A hand is hidden (CR 400.2), so the options are the chooser's alone.
    hidden_for_ai=False,
)

PUT_FROM_HAND_CHOICE_SPEC = ChoiceSpec(
    "put_from_hand_choice",
    resolve=lambda game, choice, r: game._resolve_put_from_hand_choice(
        choice, r.get("hand_index")
    ),
    default=lambda game, choice: game._default_put_from_hand_choice(choice),
    action="put_from_hand_confirm",
    prompt_key="put_from_hand_choice",
    blocked_detail="choose a card to put onto the battlefield before other actions",
    # The round this is a step of counts the answers to decide whether it
    # happens again (Eureka), so the loop genuinely stops here.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands. That is also what
    # keeps AI and headless play free of the suspension above.
    default_at_arm=True,
    # Deliberately *not* spectator_visible, unlike ``permanent_choice``: the
    # candidates are cards in a hand (CR 400.2, a hidden zone), so rendering them
    # to a seatless viewer would publish the hand. Only the seat that owes the
    # decision is shown it.
)

CHOOSE_CARDS_IN_HAND_SPEC = ChoiceSpec(
    "choose_cards_in_hand",
    resolve=lambda game, choice, r: game._resolve_choose_cards_in_hand(
        choice, r.get("hand_indices")
    ),
    default=lambda game, choice: game._default_choose_cards_in_hand(choice),
    action="choose_cards_in_hand_confirm",
    prompt_key="choose_cards_in_hand",
    blocked_detail="choose the cards in your hand before other actions",
    blocks_every_seat=True,
    # The pick is what the next step of the same resolution repeats over, so
    # that step must not run before the answer exists.
    suspends=True,
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands. That is also what
    # keeps AI and headless play free of the suspension above.
    default_at_arm=True,
    # Deliberately *not* spectator_visible, for ``put_from_hand_choice``'s
    # reason: the candidates are cards in a hand (CR 400.2, a hidden zone), so
    # rendering them to a seatless viewer would publish the hand.
)

OUTSIDE_GAME_PICK_SPEC = ChoiceSpec(
    # "You may reveal a sorcery card you own from outside the game and put it
    # into your hand." (The Judgment Wishes.) CR 400.11b's card brought into
    # the game: a position in the seat's own sideboard, checked against the
    # printed phrase the pick was armed with.
    #
    # Not Ring of Ma'rûf's ``outside_game_draw`` with a type narrowing. That
    # one is a CR 614 replacement choice, answered inside the draw it replaced
    # and resolving the draws queued behind it (CR 121.2); this is a step of a
    # resolving spell, held on ``pending_choices`` with the stack object until
    # it is answered (CR 608.2). The two share the reader of what may come in
    # (``Game._outside_game_choices``) and the mover (``Game.
    # bring_card_from_outside_game``), not a queue.
    "outside_game_pick",
    resolve=lambda game, choice, r: game._resolve_outside_game_pick(
        choice, r.get("sideboard_index")
    ),
    default=lambda game, choice: game._default_outside_game_pick(choice),
    action="outside_game_pick_confirm",
    prompt_key="outside_game_pick",
    blocked_detail=(
        "choose a card you own from outside the game before other actions"
    ),
    # **Not** ``suspends``: the move *is* the answer, and nothing printed
    # behind it reads the card it brings in — the Wishes' "Exile <this>" and
    # Death Wish's life loss stand behind the "you may" offer, which does not
    # suspend either, and Ring of Ma'rûf's pick is a replacement's whole
    # effect. ``blocked_detail`` is what makes the game wait (CR 608.2). A card
    # printing a step that reads the brought-in card is the one that makes
    # this a suspending kind (and a row in ``tests/engine/
    # test_pending_choices.py``'s ratchet).
    # A non-interactive seat never queues it: the resolution has to finish, and
    # the stated default is taken where the effect stands.
    default_at_arm=True,
    # Deliberately *not* spectator_visible: the candidates are the seat's
    # sideboard, which ``web/serialization`` keeps private like a hand — so
    # only the seat that owes the decision is shown them.
)
