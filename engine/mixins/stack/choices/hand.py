"""Cards picked out of a hand.

A non-random discard and what reads how many were discarded; the caster's pick
out of a revealed hand (Duress, Mind Warp) and what happens to the chosen card;
cards put back from a hand onto the library (Brainstorm); a card exiled out of
a hand, put onto the battlefield out of one, or chosen in one for a later step
to act on; "discard it unless you pay N life"; and the revealed-hand
notification a viewer dismisses. Every candidate list is read from the hand as
it stands, because each card that leaves renumbers the ones behind it.
"""

from __future__ import annotations

import random
from ....linked_exile import link_exiled_card
from ....models import Permanent
from ....oracle_types import DISCARDED_BY_SEAT, DISCARDED_THIS_WAY
from ....grammar.lowering._events import PUT_FROM_HAND_PERMANENTS
from ....pending_choices import PendingChoice
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
            and card_matches_any(card, alternatives)
        ]

    def _resolve_discard(self, choice: PendingChoice, hand_indices: list[int], to_library: bool) -> bool:
        from ....handlers.zones import _resolve_one_discard

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
        results = choice.data.get("_results")
        if results is not None:
            results["discarded_count"] = discarded
            # And the per-seat tally, which is the same fact asked the way a
            # sentence about "**they**" asks it. Written beside the single
            # number rather than instead of it: "…then draw that many" reads
            # one seat's answer where "damage to each player equal to 3 minus
            # the number of cards they discarded" reads every seat's, and one
            # key cannot be both.
            by_seat = results.setdefault(DISCARDED_BY_SEAT, {})
            by_seat[choice.player_index] = discarded
            # …and *which* cards went, for the sentence that asks about them
            # rather than about how many: "You gain 3 life for each **land
            # card** discarded this way" (Gerrard's Verdict). Extended rather
            # than assigned, as the random discard's record is: two discards in
            # one resolution are one "this way". A card that went somewhere
            # hidden is not in *took* (CR 701.9c) and is counted above only.
            results.setdefault(DISCARDED_THIS_WAY, []).extend(took or ())
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
        from ....handlers.zones import _resolve_one_discard
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
            self.log.append(
                f"{card.name} went on top of {victim.name}'s library"
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
            victim.exile.append(card)
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
        card = victim.hand.pop(hand_index)
        victim.exile.append(card)
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
            import random

            random.shuffle(player.library)
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
        """Put the lowest-index cards back, in hand order.

        Lowest-index is the same stated policy ``_default_discard`` takes, and
        for the same reason: which cards are *legal* answers is the card's
        business and there is no restriction here, so anything past "enough of
        them" is AI valuation rather than rules.
        """
        count = min(int(choice.data["count"]), len(self.players[choice.player_index].hand))
        if not self._resolve_hand_to_library(choice, list(range(count))):
            self.discard_pending_choice(choice)

    def _default_discard(self, choice: PendingChoice) -> None:
        """Discard the lowest-index *eligible* cards, keeping them in the
        graveyard.

        Lowest-index is the stated policy; which cards are candidates at all is
        not policy but the card's printed phrase, so it is read from the same
        list the interactive seat is offered. Re-read each time round, because
        each discard renumbers the hand behind it.
        """
        from ....handlers.zones import _resolve_one_discard

        discarded = 0
        took: list = []
        for _ in range(int(choice.data["count"])):
            eligible = self.live_discard_candidates(choice)
            if not eligible:
                break
            if not _resolve_one_discard(
                self, choice.player_index, eligible[0], to_library=False,
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
        """Resolve a pending discard with a default choice (the lowest-index cards,
        kept in the graveyard). Used for AI players and headless simulation."""
        self.auto_resolve_pending_choices(kinds=("discard",))

    # -- A card exiled out of a hand -----------------------------------------

    def live_exile_from_hand_choices(self, choice: PendingChoice) -> list[int]:
        """The hand slots still eligible, from the engine's own rule.

        Re-run rather than stored, for ``live_put_from_hand_choices``' reason:
        the list the seat is offered and the list its answer is checked against
        have to be one list.
        """
        from ....handlers.zones import exile_from_hand_candidates

        return exile_from_hand_candidates(
            self, choice.data.get("_payload") or {}, self.players[choice.player_index]
        )

    def live_exile_hand_pile_choices(self, choice: PendingChoice) -> list[int]:
        """The hand slots the "any number of cards" pick may name.

        Re-run rather than stored, for ``live_exile_from_hand_choices``'
        reason one prompt over: the list the seat is offered and the list its
        answer is checked against have to be one list.
        """
        from ....handlers.zones import exile_from_hand_candidates

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
        player.exile.append(card)
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
        context = choice.data.get("_context")
        if context is not None:
            context.results.setdefault("exiled_cards", []).append(card)
        self.log.append(f"{player.name} exiled {card.name} from their hand ({name})")
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
        from ....handlers.zones import put_from_hand_candidates

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
        player.hand = [c for i, c in enumerate(player.hand) if i != hand_index]
        # "…onto the battlefield **tapped**." (Terrain Generator.) CR 110.5b:
        # the entry state is the effect's to say, so it is set on the object
        # before it enters rather than by a tap after — no "becomes tapped"
        # event happens, which is what the printed word means.
        arrival = Permanent(
            card=card,
            tapped=bool((choice.data.get("_payload") or {}).get("tapped")),
        )
        self._put_permanent_onto_battlefield(
            choice.player_index, arrival, None
        )
        # "…onto the battlefield **attached to this creature**." (Academy
        # Researchers.) CR 303.4f: the Aura is attached as it enters. Done here
        # rather than by a step behind this one because the permanent does not
        # exist until the answer arrives — the same reason the id record below
        # is written here — and because an Aura that existed for even one
        # state-based check attached to nothing would be put into a graveyard
        # by CR 704.5m.
        #
        # The host is addressed by the id the arming froze (CR 400.7), and the
        # legality was already asked of the *candidate list* — CR 303.4a is why
        # this card is not in the offer at all when the source cannot carry it,
        # so nothing is re-checked here that could leave the Aura unattached.
        host_id = (choice.data.get("_payload") or {}).get("attach_to_permanent_id")
        if isinstance(host_id, int):
            from ....aura_attachment import attach_aura

            host = self.permanent_by_id(host_id)
            if host is not None:
                attach_aura(arrival, host)
                self._recompute_continuous_effects()
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
        self.log.append(f"{player.name} put {card.name} onto the battlefield ({name})")
        self.discard_pending_choice(choice)
        return True

    def _default_put_from_hand_choice(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** eligible card in hand order.

        Not a valuation — hand order is seed-deterministic, which is what AI and
        headless play need, and it is the same policy
        ``put_cards_from_hand_onto_battlefield`` already states for the sweep
        beside it: more battlefield is what the AI plays toward. A seat that
        should decline cleverly needs a weight in ``engine/ai_valuation.py``,
        not a branch here.
        """
        live = self.live_put_from_hand_choices(choice)
        if not live or not self._resolve_put_from_hand_choice(choice, live[0]):
            self._resolve_put_from_hand_choice(choice, None)

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
        from ....handlers.zones import chosen_hand_card_candidates

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
        from ....handlers._common import _card_matches_filter
        from ....handlers.zones import hand_slot_filters

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
        return bool((choice.data.get("_payload") or {}).get("any_number"))

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
        if payload.get("actor") == "each_player":
            # "**Each player** chooses a card in their hand." (Stronghold
            # Gambit.) One entry per seat, seeded by the handler — a flat list
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
        if count_key:
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
        if payload.get("hidden"):
            # CR 101.4a: a card chosen out of a hand may stay face down as it
            # is chosen (Stronghold Gambit). The log is public, so naming the
            # card here would show every seat still choosing what this one
            # hid; the sentence that reveals it is what names it.
            chosen = f"{len(cards)} card(s)" if cards else "no cards"
        else:
            chosen = ", ".join(c.name for c in cards) or "no cards"
        self.log.append(f"{player.name} {verb} {chosen} ({name})")
        return True

    def _default_choose_cards_in_hand(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** eligible cards in hand order.

        Not a valuation — hand order is seed-deterministic, which is what AI
        and headless play need, and it is the same policy every other pick out
        of a hand in this file states. A seat that should choose cleverly needs
        a weight in ``engine/ai_valuation.py``, not a branch here — and the one
        that does is ``ai_policy.order_hand_pick``: a pick the program then puts
        onto the battlefield for its owner (Stronghold Gambit) takes the card
        that sentence admits, at its superlative's extreme.
        """
        from ....ai_policy import order_hand_pick

        context = choice.data.get("_context")
        live = order_hand_pick(
            self, choice.player_index, self.live_choose_cards_in_hand(choice),
            choice.data.get("_payload") or {}, getattr(context, "card", None),
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
        # matching itself, in hand order — ``_default_keep_permanents``' policy.
        slotted = self.match_hand_slots(choice)
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

    # -- Discard the card you just drew, unless you pay (CR 118.3b) ---------

    def arm_discard_unless_pay_life(
        self, player_index: int, *, card, life: int, source_name: str,
        queued_draws: int = 0, queued_exclude_sources: tuple[int, ...] = (),
        cause_seat: int | None = None,
    ) -> None:
        """Offer *player_index* the choice of paying *life* or discarding *card*.

        "That player discards it **unless they pay 3 life**"
        (Breathstealer's Crypt). A price on a card already in a hand, which is
        what makes it its own kind rather than ``pay_life_to_save``
        (``optional_pay.py``): that one is asked of every seat about a
        *permanent* on the battlefield, and its whole record is which
        permanents somebody paid for. Here the payer and the affected card are
        one seat and one card, and the card is addressed **by identity** — a
        hand repeats one immutable ``CardDefinition`` per copy, so a name would
        name every copy of it.

        The parameters are the printed ones: nothing here knows the card that
        prints the sentence, so a second card printing "unless they pay N life"
        about a drawn card needs no code.

        The draws queued behind the replaced one ride here rather than being
        made by the caller: CR 121.2 makes an N-card draw N events, and an
        interactive seat answers this on a later request — so a caller looping
        would draw the rest while the offer was still open, which CR 608.2
        forbids. The resolver makes them once the answer is in.
        """
        self.arm_pending_choice(
            "discard_unless_pay_life", player_index,
            card_name=card.name,
            life=int(life),
            source_name=source_name,
            _card=card,
            _queued_draws=int(queued_draws),
            _queued_exclude_sources=tuple(queued_exclude_sources),
            # Whose ability would make this seat discard (CR 109.5): the
            # permanent printing the sentence, which is not whoever happens to
            # be resolving when the draw it replaces is made — a draw step has
            # nobody resolving at all. Named by the caller, so
            # `arm_pending_choice`'s own stamp never overrides it.
            **({"_cause_seat": int(cause_seat)} if cause_seat is not None else {}),
        )

    def confirm_discard_unless_pay_life(
        self, player_index: int, accept: bool = True
    ) -> bool:
        """Answer "…discards it unless they pay N life"."""
        return self.resolve_pending_choice(
            "discard_unless_pay_life", player_index, accept=bool(accept)
        )

    def _resolve_discard_unless_pay_life(
        self, choice: PendingChoice, accept: bool
    ) -> bool:
        """Pay the life, or discard the card the offer was about.

        The discard goes through ``take_card_from_hand``, which removes exactly
        **one** copy by identity. The obvious spelling — filtering the hand by
        ``is not card`` — deletes every copy, and a player who drew their second
        Grizzly Bears would lose both.

        A card that has already left the hand is no longer there to discard and
        nothing is done: the offer was about that card, and CR 701.9a moves a
        card *from a hand*.
        """
        data = choice.data
        player = self.players[choice.player_index]
        life = int(data.get("life", 0))
        card = data.get("_card")
        self.discard_pending_choice(choice)
        # CR 119.4: a player may pay N life only with at least N to pay. Paying
        # down to exactly 0 is legal and the state-based check that follows ends
        # the game, so this refuses a payment that is not there rather than
        # protecting a life total.
        if accept and player.life >= life:
            player.life -= life
            self.log.append(
                f"{player.name} paid {life} life to keep {data.get('card_name', 'a card')} "
                f"({data.get('source_name', '')})"
            )
        elif card is not None and self.take_card_from_hand(player, card):
            # Through the discard seam, never straight to the graveyard: a
            # discard is CR 701.9a's event, so a replacement over it (Library
            # of Leng, Dodecapod) and every watcher of one (Megrim) sees this
            # one too. The cause is the seat the offer was armed for.
            self._discard_card(player, card, cause_seat=data.get("_cause_seat"))
            self.log.append(
                f"{player.name} discarded {data.get('card_name', 'a card')} "
                f"({data.get('source_name', '')})"
            )
        # The rest of the replaced draw, made now that the offer is answered.
        # Each is its own event (CR 121.2) and goes back through the seam, so a
        # second card drawn under the same enchantment gets its own reveal and
        # its own offer.
        queued = int(data.get("_queued_draws", 0) or 0)
        if queued > 0:
            self._draw_with_replacements(
                player, queued,
                exclude_sources=tuple(data.get("_queued_exclude_sources") or ()),
            )
        return True

    def _default_discard_unless_pay_life(self, choice: PendingChoice) -> None:
        """The stated policy for a seat nobody is asking: pay, while the payment
        is not the seat's whole life total.

        A policy rather than a valuation, the discipline
        ``_default_pay_life_to_save`` states one method over: the card is the
        seat's own and keeping it is the reason the price is printed, so the
        default is to pay — and never to pay itself to nothing for one card. A
        card that should choose otherwise wants a valuation in
        ``engine/ai_valuation.py``, not a branch here.
        """
        life = int(choice.data.get("life", 0))
        self._resolve_discard_unless_pay_life(
            choice, self.players[choice.player_index].life > life
        )
