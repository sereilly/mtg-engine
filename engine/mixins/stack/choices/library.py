"""Looking at, ordering and drawing from the top of a library.

The prompts whose answer reshapes a library a later step of the same
resolution reads: keep one of the top N and bottom the rest, scry (CR 701.22),
put cards back "in any order" on the top or the bottom (CR 401.4, whose order
is the library's owner's to choose), Lim-Dul's Vault's repeated look, which end
of a library a tucked card goes on, and Zur's Weirding's revealed draw that any
other player may buy into a graveyard.
"""

from __future__ import annotations

import random
from ....pending_choices import PendingChoice


class LibraryChoicesMixin:
    # -- Look at the top N, keep one, bottom the rest (See the Truth) ---------

    def confirm_look_top_pick(self, player_index: int, keep_index: int) -> bool:
        return self.resolve_pending_choice(
            "look_top_pick", player_index, keep_index=keep_index
        )

    def look_top_pile_index(self, choice: PendingChoice) -> int:
        """Whose library this prompt is looking through.

        The seat answering, except where the card separates the two: "Look at
        the top X cards of **target opponent's** library. Exile one of those
        cards…" (Sealed Fate) puts every decision with the caster and the pile
        with the opponent. One reader for all three callers — what is offered,
        what an answer moves, and what the client draws — because a second
        would be free to show one library and empty another.
        """
        pile = choice.data.get("pile_index")
        if isinstance(pile, int) and 0 <= pile < len(self.players):
            return pile
        return choice.player_index

    def live_look_top_candidates(self, choice: PendingChoice) -> list[int]:
        """Which of the looked-at positions may be taken, in library order.

        Public because the prompt renderer is the second legitimate caller: what
        is offered and what an answer is checked against have to be one rule
        rather than two copies of it — the arrangement ``live_discard_candidates``
        already makes, and for the same reason.
        """
        from ....subject_filters import card_matches_any

        caster = self.players[self.look_top_pile_index(choice)]
        top_count = min(int(choice.data.get("top_count", 0)), len(caster.library))
        # "a creature card **or** Garruk planeswalker card" — the alternatives
        # are OR'd, exactly as a narrowed discard cost's are, because the two
        # sides restrict different characteristics and one filter AND's its
        # keys. No alternatives means no narrowing: any looked-at card may be
        # taken, which is See the Truth's shape.
        alternatives = tuple(choice.data.get("filters") or ())
        if not alternatives:
            described = dict(choice.data.get("filter") or {})
            alternatives = (described,) if described else ()
        return [
            index for index in range(top_count)
            if card_matches_any(caster.library[index], alternatives)
        ]

    def _resolve_look_top_pick(
        self, choice: PendingChoice, keep_index: int | None
    ) -> bool:
        # The pile, which is the seat answering except on Sealed Fate — see
        # ``look_top_pile_index``. Everything below moves cards in *this*
        # player's library; who answers the prompt is ``choice.player_index``
        # and is used only to arm what comes next.
        caster = self.players[self.look_top_pile_index(choice)]
        top_count = min(int(choice.data.get("top_count", 0)), len(caster.library))
        looked = caster.library[:top_count]

        def _bottom_the_rest(rest: list) -> None:
            # "…and the other into your **graveyard**" (Waker of Waves). Where
            # the unchosen cards go is the card's own statement, so it is read
            # rather than assumed — a card that bottomed them instead is a
            # different card, and the difference is invisible until the pile is
            # looked at again.
            if choice.data.get("rest_destination") == "graveyard":
                for card in rest:
                    # The looked-at cards are the top of this library, so the
                    # move is one out of a library and says so. The seam
                    # announces a source zone only where a caller names it,
                    # and unnamed this was a mill that Gaea's Blessing's own
                    # trigger and "whenever a land card is put into your
                    # graveyard from your library" (Pedantic Learning) could
                    # not see.
                    self.put_card_into_graveyard(caster, card, from_zone="library")
                return
            # "…and **exile the rest**." (Browse.) The cards leave the game
            # rather than the library, which is why the same ability may be
            # activated again and again: the pile it looks at is a pile it has
            # already shortened. No order is asked for — exile is unordered
            # (CR 406.2 orders no zone but the library and the graveyard).
            if choice.data.get("rest_destination") == "exile":
                for card in rest:
                    caster.exile.append(card)
                return
            # "…and the rest on **top** of your library in any order."
            # (Diabolic Vision.) The same clause as the bottom one word over,
            # and a different kind of sentence: on the bottom "in any order" is
            # a freedom nothing can observe, so this resolver has always just
            # laid them down. On top it *is* the effect — the next N draws —
            # so the order has to be asked for. Chained onto this answer rather
            # than folded into it: `reorder_library` is a prompt that already
            # exists, with its own UI, AI default and action, and CR 608.2 keeps
            # a decision armed by answering another inside the same resolution.
            #
            # (That first claim was wrong, and Apocalypse measured it: the
            # bottom of a library *is* observed once the deck runs down to it.
            # ``offer_library_bottom_order`` is the seam that asks — Goblin
            # Ringleader's sorted reveal calls it — and the "any order" tail
            # below calls it too, now that the client labels the prompt by the
            # end of the library it is about.)
            if choice.data.get("rest_destination") == "library_top":
                caster.library[:0] = list(rest)
                # "…You choose one of those cards and put it into their
                # graveyard." (Balshan Beguiler.) No clause about the rest at
                # all: they were revealed, not moved, so they are where they
                # were and in the order they were — nobody is asked.
                if len(rest) > 1 and choice.data.get("rest_order") != "unchanged":
                    # Whose library is reordered, and **who orders it**: one
                    # seat everywhere but Sealed Fate, where the cards go back
                    # on the opponent's library in an order the caster chooses
                    # (CR 608.2 makes the spell's controller the actor).
                    self.arm_pending_choice(
                        "reorder_library", choice.player_index,
                        target_index=self.seat_index(caster),
                        top_count=len(rest), may_shuffle=False,
                    )
                return
            # "…on the bottom of your library **in a random order**." (Garruk's
            # Harbinger.) A stated order, not the player's freedom: the cards
            # go down shuffled, through the module RNG `run_ai_simulation`
            # seeds so a given seed still replays exactly. "In any order" is the
            # other spelling: the order is the player's by rule (CR 401.4), so
            # the cards are laid down as they lay and an interactive seat is
            # then asked to arrange them. Everybody else keeps "as they lay",
            # which is what every seat got before the question was asked.
            if choice.data.get("rest_order") == "random":
                rest = list(rest)
                random.shuffle(rest)
                caster.library.extend(rest)
                return
            caster.library.extend(rest)
            # Who arranges is the seat answering the look (CR 608.2): the
            # pile's owner everywhere but a look through somebody else's
            # library, which is the top-of-library tail's reading above.
            self.offer_library_bottom_order(
                caster, len(rest), chooser_index=choice.player_index,
            )

        # "**You may** reveal a … card from among them" (Garruk's Harbinger).
        # Declining is a legal answer, and it is not the same as an illegal one:
        # the rest still go to the bottom.
        if keep_index is None:
            if not choice.data.get("optional"):
                return False
            del caster.library[:top_count]
            _bottom_the_rest(looked)
            self.discard_pending_choice(choice)
            # The log names where the rest actually went. It said "on the
            # bottom" for every printing, which is Garruk's Harbinger's and not
            # Ancestral Knowledge's — the destination has been payload since
            # `rest_destination` existed.
            where = {
                "library_top": "back on top", "graveyard": "into the graveyard",
                "exile": "into exile",
            }.get(str(choice.data.get("rest_destination", "library_bottom")),
                  "on the bottom")
            self.log.append(f"{caster.name} took nothing and put the rest {where}")
            return True

        if not isinstance(keep_index, int) or not (0 <= keep_index < top_count):
            return False
        # A card the printed phrase does not name is not a legal answer, and is
        # refused rather than slid onto one that is.
        if keep_index not in self.live_look_top_candidates(choice):
            return False
        kept = caster.library[keep_index]
        # "Put **two** of them into your hand and the rest into your graveyard."
        # (Ancestral Memories.) A chain of one-card prompts rather than one
        # multi-select, for `_rearm_revealed_hand_pick`'s reason exactly: taking
        # a card renumbers the pile behind it, so a set of indices answered all
        # at once against the pile as it *was* addresses the wrong cards. Only
        # the taken card leaves; the rest stay where they are and the next
        # prompt looks at one fewer.
        remaining = int(choice.data.get("remaining", 1))
        if remaining > 1 and top_count > 1:
            caster.library.pop(keep_index)
            # Where the taken card goes, read the same way the terminal link
            # below reads it. This branch put every card in a **hand** whatever
            # the print said, which was safe only because the lowering refused
            # any other destination for a counted pick — and the moment
            # Ancestral Knowledge printed "exile any number of them", the first
            # nine of its ten picks would have been drawn instead of exiled.
            taken_to = str(choice.data.get("pick_destination", "hand"))
            if taken_to == "exile":
                caster.exile.append(kept)
            elif taken_to == "graveyard":
                # "You choose two of those cards and put them into that
                # player's graveyard." (Bamboozle.) Through the graveyard
                # seam, naming the zone the card left.
                self.put_card_into_graveyard(caster, kept, from_zone="library")
            else:
                self.put_card_into_hand(caster, kept)
            self.discard_pending_choice(choice)
            # W2G4 (log line only): the card is named where the table may know
            # it — exiled face up, or shown by the card's own sentence — and is
            # "a card" where it went from a library to a hand unseen.
            shown = (
                kept.name if self.find_is_public(choice.data, taken_to) else "a card"
            )
            if taken_to == "graveyard":
                # Who chose and whose pile are two seats here (Bamboozle), so
                # the line names both, as the last link of the chain does.
                self.log.append(
                    f"{self.players[choice.player_index].name} put {kept.name} "
                    f"from {caster.name}'s library into {caster.name}'s "
                    f"graveyard ({remaining - 1} more to choose)"
                )
            else:
                self.log.append(
                    f"{caster.name} took {shown} "
                    + ("into exile " if taken_to == "exile" else "into their hand ")
                    + f"({remaining - 1} more to take)"
                )
            # The keys are listed rather than the whole ``data`` dict passed
            # back, for `_rearm_revealed_hand_pick`'s reason: ``arm_pending_choice``
            # stamps its own bookkeeping into ``data`` (which stack object is
            # waiting, which seat caused the prompt), and handing those back as
            # arguments would re-arm the next link with a stale stamp.
            self.arm_pending_choice(
                "look_top_pick", choice.player_index,
                top_count=top_count - 1,
                amount=choice.data.get("amount", top_count - 1),
                card_name=choice.data.get("card_name", ""),
                filter=dict(choice.data.get("filter") or {}),
                filters=tuple(choice.data.get("filters") or ()),
                optional=bool(choice.data.get("optional")),
                rest_order=choice.data.get("rest_order", "any"),
                rest_destination=choice.data.get("rest_destination", "library_bottom"),
                pick_destination=choice.data.get("pick_destination", "hand"),
                remaining=remaining - 1,
                pile_index=choice.data.get("pile_index"),
                # Still the same pile, shown or not (W2G4, for the log line).
                **({"revealed": True} if choice.data.get("revealed") else {}),
            )
            return True
        del caster.library[:top_count]
        _bottom_the_rest([card for i, card in enumerate(looked) if i != keep_index])
        # "**Exile** one of those cards…" (Sealed Fate). The third printed
        # destination for the taken card, beside the hand and the library's
        # top, and the only one that takes it out of the game — read rather
        # than defaulted, exactly as the other two are.
        if choice.data.get("pick_destination") == "exile":
            caster.exile.append(kept)
            self.discard_pending_choice(choice)
            self.log.append(
                f"{self.players[choice.player_index].name} exiled a card from "
                f"{caster.name}'s library"
            )
            return True
        # "…and put it into **their graveyard**." (Balshan Beguiler; the last
        # of Bamboozle's two.) The fifth printed destination for the taken
        # card. A graveyard is public and so was the pile, so the card is
        # named.
        if choice.data.get("pick_destination") == "graveyard":
            self.put_card_into_graveyard(caster, kept, from_zone="library")
            self.discard_pending_choice(choice)
            self.log.append(
                f"{self.players[choice.player_index].name} put {kept.name} from "
                f"{caster.name}'s library into {caster.name}'s graveyard"
            )
            return True
        # Where the *kept* card goes, read the same way the rest's destination
        # is. "Puts one of them **back on top of their library**" (Ashnod's
        # Cylix) is this prompt's other printed answer: the card is not drawn,
        # it is the next card that player draws — a difference nothing else in
        # the sentence states and nobody can see until the draw step.
        if choice.data.get("pick_destination") == "library_top":
            self.put_card_into_library(caster, kept, position="top")
            self.discard_pending_choice(choice)
            self.log.append(
                f"{caster.name} put a card back on top of their library"
            )
            return True
        # "**If you don't**, put one of those cards on the bottom of your
        # library." (Preferred Selection.) The fourth printed destination for
        # the taken card, and the one that is a *cost* rather than a gain: the
        # card the player names is the one they are burying, and the rest of the
        # pile goes back where it was. Read rather than folded into the bottoming
        # of "the rest" — those are different cards and the sentence says which.
        if choice.data.get("pick_destination") == "library_bottom":
            self.put_card_into_library(caster, kept, position="bottom")
            self.discard_pending_choice(choice)
            self.log.append(
                f"{caster.name} put a card on the bottom of their library"
            )
            return True
        # "…You gain life equal to **that card's mana value**." (Reviving
        # Vapors.) Read off the card as it is taken — it is about to be in a
        # hand, where nothing can identify it again (CR 608.2h).
        record = choice.data.get("_record_pick")
        if record is not None:
            record_context, record_key = record
            record_context.results[record_key] = int(kept.cmc or 0)
        self.put_card_into_hand(caster, kept)
        self.discard_pending_choice(choice)
        # W2G4 (log line only): "Look at the top four cards … put one of them
        # into your hand" (Impulse) shows the card to nobody (CR 701.20e), and
        # this line is sent to every seat. Named only where the card's own
        # sentence revealed it — the whole pile (Reviving Vapors, Eye of
        # Yawgmoth) or the pick ("you may **reveal** a creature card from
        # among them", which is every pick the prompt narrowed to a type).
        shown = (
            kept.name
            if self.find_is_public(choice.data, "hand") or choice.data.get("filters")
            else "a card"
        )
        self.log.append(
            f"{caster.name} put {shown} into their hand and the rest away"
        )
        return True

    def _default_look_top_pick(self, choice: PendingChoice) -> None:
        """A non-interactive seat keeps the first card it *may* keep, and takes
        nothing when the phrase names none of them.

        The exception is an optional pick that **exiles from the chooser's own
        library** (Ancestral Knowledge): "any number" includes none, and there
        the pick is a cost rather than a gain — taking the first card ten times
        would exile a tenth of the deck for nothing. A stated policy, like the
        up-to-N maximum and the modal first mode; Sealed Fate's exile is not
        optional and empties somebody else's library, so it is untouched.
        """
        exiles_own = (
            choice.data.get("pick_destination") == "exile"
            and self.look_top_pile_index(choice) == choice.player_index
        )
        if choice.data.get("optional") and exiles_own:
            if not self._resolve_look_top_pick(choice, None):
                self.discard_pending_choice(choice)
            return
        eligible = self.live_look_top_candidates(choice)
        keep = eligible[0] if eligible else None
        if eligible and choice.data.get("_record_pick") is not None:
            # "…You gain life equal to that card's mana value." (Reviving
            # Vapors.) The one printing where the sentence itself says which
            # card is worth more, so the stated policy reads it: the greatest
            # mana value, and the first of those.
            pile = self.players[self.look_top_pile_index(choice)].library
            keep = max(eligible, key=lambda index: (pile[index].cmc or 0, -index))
        if not self._resolve_look_top_pick(choice, keep):
            self.discard_pending_choice(choice)

    # -- Library reorder ----------------------------------------------------

    def confirm_reorder_library(self, caster_index: int, new_order: list, shuffle: bool = False) -> bool:
        return self.resolve_pending_choice(
            "reorder_library", caster_index, new_order=new_order, shuffle=shuffle
        )

    def reorder_library_pile(self, choice: PendingChoice) -> list:
        """The cards a ``reorder_library`` prompt is arranging, uppermost first.

        The top ``top_count`` of the target library, or — ``position ==
        "bottom"`` — its last ``top_count``: the cards an effect has just put
        "on the bottom of your library in any order" (CR 401.4). One reader for
        what the prompt shows, what an answer permutes and what the default
        leaves, because a second would be free to show one end of a library and
        rearrange the other.
        """
        library = self.players[choice.data["target_index"]].library
        count = int(choice.data["top_count"])
        if choice.data.get("position") == "bottom":
            return library[max(len(library) - count, 0):]
        return library[:count]

    def offer_library_bottom_order(
        self, owner, count: int, *, chooser_index: int | None = None
    ) -> bool:
        """Ask for the order of the *count* cards an effect has just put on the
        bottom of *owner*'s library "in any order". True when a seat was asked.

        CR 401.4: "If an effect puts two or more cards in a specific position
        in a library at the same time, the owner of those cards may arrange
        them in any order. That library's owner doesn't reveal the order in
        which the cards go into the library." The caller lays the cards down
        first — it knows whether they came from another zone (the funnel,
        CR 903.9b) or were only ever moved *within* the library, which is what
        a looked-at or revealed pile is (CR 701.20b) — and the order is then
        the ordinary ``reorder_library`` prompt pointed at the library's other
        end. The arrangement Scroll Rack's top-of-library tail already has, for
        its reason: the renderer, the wire action and the answer check all
        exist, and a second prompt would be a second answer to one question.

        **Only an interactive seat is asked.** "As they lay" is the default
        order and taking it needs no prompt, so a headless or AI seat queues
        nothing and consumes no randomness — which is what keeps a seeded run,
        and every test written before the question existed, identical.

        ``chooser_index`` is the seat that arranges where a card gives the
        order to somebody other than the owner (the caster of a spell that
        looks through an opponent's library, CR 608.2); absent, it is the
        owner's by CR 401.4. Fewer than two cards leave no order to choose.
        """
        seat = self.seat_index(owner)
        count = min(int(count), len(self.players[seat].library))
        chooser = seat if chooser_index is None else chooser_index
        if count < 2 or chooser not in self.interactive_seats:
            return False
        self.arm_pending_choice(
            "reorder_library", chooser,
            target_index=seat, top_count=count, position="bottom",
            may_shuffle=False,
        )
        return True

    def offer_library_top_order(
        self, owner, count: int, *, chooser_index: int | None = None
    ) -> bool:
        """Ask for the order of the *count* cards an effect has just put on
        **top** of *owner*'s library. True when a seat was asked.

        :meth:`offer_library_bottom_order`'s twin for the library's other end,
        and CR 401.4 is the same sentence for both: "If an effect puts two or
        more cards in a specific position in a library at the same time, the
        **owner** of those cards may arrange them in any order." The caller
        lays the cards down first; the order is then the ordinary
        ``reorder_library`` prompt over the top *count* — the look-and-put-back
        prompt, with no shuffle on offer.

        The owner, not the spell's controller, which is the half the order
        "the targets were named in" could not carry: Lodestone Bauble puts
        cards from *a player's* graveyard on top of *their* library, and the
        player who named them is not the player whose draws they decide.

        Only an interactive seat is asked, for the bottom twin's reason: "as
        they lay" needs no prompt, so a headless or AI seat queues nothing and
        a seeded run reads as it did.
        """
        seat = self.seat_index(owner)
        count = min(int(count), len(self.players[seat].library))
        chooser = seat if chooser_index is None else chooser_index
        if count < 2 or chooser not in self.interactive_seats:
            return False
        self.arm_pending_choice(
            "reorder_library", chooser,
            target_index=seat, top_count=count, may_shuffle=False,
        )
        return True

    def _resolve_reorder_library(self, choice: PendingChoice, new_order: list, shuffle: bool) -> bool:
        target = self.players[choice.data["target_index"]]
        top_count = choice.data["top_count"]
        # "…and the rest **on the bottom of your library in any order**."
        # (Goblin Ringleader.) The same question about the library's other end:
        # the pile is its last N cards, everything above them stays where it
        # is, and element 0 of the answer is the uppermost of the pile — the
        # first of them a draw would reach — which is what "leftmost" means on
        # the prompt either way. No shuffle is ever offered there.
        if choice.data.get("position") == "bottom":
            pile = self.reorder_library_pile(choice)
            count = len(pile)
            if len(new_order) != count or sorted(new_order) != list(range(count)):
                return False
            target.library[len(target.library) - count:] = [
                pile[i] for i in new_order
            ]
            self.log.append(
                f"{target.name} put {count} cards on the bottom of their "
                f"library in an order they chose"
            )
            self.discard_pending_choice(choice)
            return True
        top = target.library[:top_count]
        rest = target.library[top_count:]
        # "Look at the top five cards of target player's library" (Visions) and
        # nothing else — the looker learns the order but never gets to change
        # it. Enforced here rather than by hiding the drag handles: a
        # permission only the client honours is a rule nothing enforces, and
        # this prompt is answered by whatever the wire sends.
        if not choice.data.get("may_reorder", True):
            new_order = list(range(top_count))
        if len(new_order) != top_count or sorted(new_order) != list(range(top_count)):
            return False
        target.library = [top[i] for i in new_order] + rest
        # "You may have that player shuffle" (Natural Selection): only honored when
        # the effect allows it.
        if shuffle and choice.data.get("may_shuffle"):
            random.shuffle(target.library)
            self.log.append(f"{target.name}'s library was shuffled")
        else:
            self.log.append(f"Top {top_count} cards of {target.name}'s library reordered")
        self.discard_pending_choice(choice)
        return True

    def _default_reorder_library(self, choice: PendingChoice) -> None:
        from ....ai_policy import choose_reorder_library_order

        # The bottom of a library: as they lay. The order is the owner's
        # freedom and nothing scores it — ``choose_reorder_library_order``
        # ranks the *next draws*, which these are the furthest cards from — so
        # the default is the order the effect put them down in, the one a seat
        # that was never asked gets (``offer_library_bottom_order``).
        if choice.data.get("position") == "bottom":
            identity = list(range(len(self.reorder_library_pile(choice))))
            if not self._resolve_reorder_library(choice, identity, shuffle=False):
                self.discard_pending_choice(choice)
            return
        order = choose_reorder_library_order(
            self, choice.player_index, choice.data["target_index"], choice.data["top_count"]
        )
        if not self._resolve_reorder_library(choice, order, shuffle=False):
            self.discard_pending_choice(choice)

    # -- Scry ---------------------------------------------------------------

    def confirm_scry(self, caster_index: int, card_order: list, bottom_count: int) -> bool:
        return self.resolve_pending_choice(
            "scry", caster_index, card_order=card_order, bottom_count=bottom_count
        )

    def _resolve_scry(self, choice: PendingChoice, card_order: list, bottom_count: int) -> bool:
        """CR 701.22a. ``card_order`` is a permutation of the looked-at cards
        reading top-first: the leading ``top_count - bottom_count`` entries go
        back on top in that order, the trailing ``bottom_count`` to the bottom
        in that order.

        One permutation plus a count rather than two lists, so the validation is
        the same total-permutation check ``_resolve_reorder_library`` makes —
        two lists could overlap or omit a card and still look plausible.
        """
        # Whose library, which is not always the chooser's: "look at the top
        # card of **defending player's** library. You may put that card on the
        # bottom of that player's library" (Coral Fighters) is this same
        # decision over somebody else's pile. Absent means the chooser's, which
        # is every scry (CR 701.22a is about your own library) and every payload
        # written before the key existed.
        owner = self.players[choice.data.get("library_index", choice.player_index)]
        top_count = choice.data["top_count"]
        if sorted(card_order) != list(range(top_count)):
            return False
        if not 0 <= bottom_count <= top_count:
            return False
        looked = owner.library[:top_count]
        rest = owner.library[top_count:]
        kept = [looked[i] for i in card_order[: top_count - bottom_count]]
        bottomed = [looked[i] for i in card_order[top_count - bottom_count :]]
        if choice.data.get("destination") == "graveyard":
            # Surveil (CR 701.25a): the cards not kept go to the graveyard
            # where a scry sends them to the bottom. The same answer shape —
            # ``bottom_count`` is "how many of the trailing entries leave the
            # top" — because it is the same decision. They come off the
            # library together and are then put where they go one by one,
            # through the graveyard seam and naming the zone they left
            # (CR 614 may divert one; "put into your graveyard from your
            # library" is a trigger some cards watch).
            owner.library = kept + rest
            for card in bottomed:
                self.put_card_into_graveyard(owner, card, from_zone="library")
            self.log.append(
                f"{self.players[choice.player_index].name} surveilled "
                f"{top_count} ({bottom_count} to the graveyard)"
            )
            self.discard_pending_choice(choice)
            return True
        # The bottomed cards go under everything that was already below the
        # looked-at ones, which is why `rest` sits between the two slices.
        owner.library = kept + rest + bottomed
        self.log.append(
            f"{self.players[choice.player_index].name} looked at the top "
            f"{top_count} of {owner.name}'s library ({bottom_count} to the bottom)"
        )
        self.discard_pending_choice(choice)
        return True

    def _default_scry(self, choice: PendingChoice) -> None:
        from ....ai_policy import choose_scry_arrangement

        card_order, bottom_count = choose_scry_arrangement(
            self, choice.player_index, choice.data["top_count"],
            library_index=choice.data.get("library_index"),
        )
        if not self._resolve_scry(choice, card_order, bottom_count):
            self.discard_pending_choice(choice)

    # -- The repeated look-and-bottom offer (Lim-Dul's Vault) ----------------

    def confirm_library_cycle_offer(self, player_index: int, accept: bool) -> bool:
        """Answer one round of "as many times as you choose, you may pay N
        life": accepting bottoms the cards just looked at, looks at the next
        lot and asks again; declining ends the loop and does the shuffle."""
        return self.resolve_pending_choice(
            "library_cycle_offer", player_index, accept=bool(accept)
        )

    def _library_cycle_finish(self, choice: PendingChoice) -> None:
        """"Then shuffle and put the last cards you looked at this way on top
        in any order."

        The order of the two halves is the whole card. The kept cards come out
        *first*, the rest of the library is shuffled (CR 701.24), and only then
        do they go back on top - shuffling with them still in it would lose
        them, and stacking before shuffling would shuffle them away again.

        The final ordering is chained onto this answer rather than done here:
        ``reorder_library`` is a prompt that already exists with its own UI, AI
        default and action, and a decision armed by answering another stays
        inside the same resolution.
        """
        import random

        player = self.players[choice.player_index]
        count = min(int(choice.data.get("count", 0)), len(player.library))
        kept = player.library[:count]
        rest = player.library[count:]
        random.shuffle(rest)
        player.library = kept + rest
        self.log.append(f"{player.name} shuffled their library")
        if count > 1:
            self.arm_pending_choice(
                "reorder_library", choice.player_index,
                target_index=choice.player_index, top_count=count,
                may_shuffle=False,
            )

    def _resolve_library_cycle_offer(self, choice: PendingChoice, accept: bool) -> bool:
        """One round of the loop.

        An accept that cannot be paid for is a decline, not a refused answer:
        CR 119.4 lets a player pay N life only with N or more life to pay it
        from, and a seat that says yes without the life has simply not paid -
        so the loop ends and the card still shuffles. Refusing the answer
        instead would leave the prompt queued with no answer that could ever
        clear it.
        """
        player = self.players[choice.player_index]
        life_cost = int(choice.data.get("life_cost", 0))
        count = int(choice.data.get("count", 0))
        self.discard_pending_choice(choice)
        if not accept or player.life < life_cost:
            self._library_cycle_finish(choice)
            self._release_stack_item(choice.data.get("_stack_item"))
            return True
        player.life -= life_cost
        name = choice.data.get("card_name", "Effect")
        self.log.append(f"{player.name} paid {life_cost} life ({name})")
        # "…put those cards on the bottom of your library **in any order**".
        # They go down as they lay: the order is the player's by rule, the
        # cards are at the bottom of a library that is about to be shuffled,
        # and nothing in the game can ask what it was.
        moved = player.library[:count]
        del player.library[:count]
        for card in moved:
            self.put_card_into_library(player, card, position="bottom")
        looked = min(count, len(player.library))
        self.log.append(
            f"{player.name} looks at the top {looked} card(s) of their library"
        )
        # The next round, armed by answering this one - the ability is still
        # resolving until the loop ends (CR 608.2).
        self.arm_pending_choice(
            "library_cycle_offer", choice.player_index,
            card_name=name, count=count, life_cost=life_cost,
        )
        return True

    def _default_library_cycle_offer(self, choice: PendingChoice) -> None:
        """The stated policy: **decline at once**.

        Not ``_default_optional_pay``'s "pay tolls" - that policy is written for
        an offer made once, and this one is made again every time it is taken.
        A headless seat that paid whenever it could afford to would pay its life
        total down to 1 for a shuffle it has no way to evaluate, which is a
        worse outcome than never having cast the spell. An unbounded optional
        payment has no stopping rule anybody can compute for the player, so the
        engine takes the only answer that cannot be wrong by an unbounded
        amount.
        """
        self._resolve_library_cycle_offer(choice, False)

    # -- Which end of a library a tuck puts its card on ----------------------

    def arm_library_end_choice(
        self, player_index: int, permanent, owner_index: int, context
    ) -> None:
        """Queue "top or bottom?" for a tuck whose card qualifies for the swap.

        The **permanent** travels rather than the card, so the answer moves the
        object this resolution resolved: two copies of one card in a library are
        the same ``CardDefinition``, and a card is not addressable while a
        permanent still is (CR 400.7).
        """
        self.arm_pending_choice(
            "library_end_choice", player_index,
            card_name=context.card.name,
            moved_name=permanent.card.name,
            owner_index=int(owner_index),
            owner_name=self.players[int(owner_index)].name,
            _permanent=permanent,
            _context=context,
        )

    def confirm_library_end_choice(self, player_index: int, to_bottom) -> bool:
        return self.resolve_pending_choice(
            "library_end_choice", player_index, to_bottom=to_bottom
        )

    def _resolve_library_end_choice(self, choice: PendingChoice, to_bottom) -> bool:
        """Move the permanent to the end the seat named.

        The move happens **here** rather than before the prompt, because "put it
        on the bottom **instead**" is one zone change with two possible ends: a
        version that tucked on top and then moved the card would be two zone
        changes, which is one more than the card describes and one more than any
        watcher should see.
        """
        permanent = choice.data.get("_permanent")
        if permanent is None or not self.is_on_battlefield(permanent):
            # It left while the prompt was owed. CR 608.2b: the effect does as
            # much as it can, which here is nothing.
            self.discard_pending_choice(choice)
            return True
        owner = self.players[int(choice.data["owner_index"])]
        self.remove_from_battlefield(permanent)
        self._remove_aura_effects(permanent)
        position = "bottom" if to_bottom else "top"
        self.put_card_into_library(
            owner, permanent.card, position, from_battlefield=permanent
        )
        self.discard_pending_choice(choice)
        self.log.append(
            f"{choice.data.get('card_name', 'An effect')}: "
            f"{permanent.card.name} put on {position} of {owner.name}'s library"
        )
        return True

    def _default_library_end_choice(self, choice: PendingChoice) -> None:
        """The stated policy: the **bottom**.

        The offer costs its controller nothing and buries the card deeper, so
        it is a gift under "take gifts, pay tolls, make no trades" — and it is
        deterministic, which is what AI and headless play need. A seat that
        should weigh the two ends needs a weight in ``engine/ai_valuation.py``,
        not a branch here.
        """
        self._resolve_library_end_choice(choice, True)

    # -- Buying a revealed draw out of a hand (Zur's Weirding) --------------

    def offer_revealed_draw_buyout(
        self,
        drawing_seat: int,
        *,
        card_name: str,
        source_name: str,
        queued_draws: int,
        exclude_sources: tuple[int, ...],
        queued_exclude_sources: tuple[int, ...] = (),
        remaining_seats: list[int] | None = None,
    ) -> None:
        """Put "any other player may pay 2 life" to the next seat that owes an
        answer, or finish the replaced draw when nobody is left.

        CR 101.4: the offer goes round **every other player** in turn order
        starting with the active player, and the first to pay ends the round.
        The rest of the round rides in the prompt's own data rather than in a
        loop here, because a human seat's answer arrives on a later request and
        a loop would have to survive that; the resolver arms the next seat.

        A seat that has left the game is nobody (CR 800.4a), and it is filtered
        on every pass rather than once, so a player who lost while the poll was
        open is not asked.
        """
        from ....replacements import REVEAL_DRAW_LIFE_COST

        if remaining_seats is None:
            count = len(self.players)
            active = self.active_player_index or 0
            remaining_seats = sorted(
                (
                    index for index, player in enumerate(self.players)
                    if index != drawing_seat and not player.lost
                ),
                key=lambda index: ((index - active) % count, index),
            )
        live = [
            seat for seat in remaining_seats
            if 0 <= seat < len(self.players) and not self.players[seat].lost
        ]
        if not live:
            self._finish_revealed_draw(
                drawing_seat, bought=False,
                queued_draws=queued_draws,
                exclude_sources=exclude_sources,
                queued_exclude_sources=queued_exclude_sources,
                source_name=source_name,
            )
            return
        self.arm_pending_choice(
            "revealed_draw_buyout", live[0],
            card_name=source_name,
            revealed_name=card_name,
            drawing_seat=drawing_seat,
            drawing_player=self.players[drawing_seat].name,
            life=REVEAL_DRAW_LIFE_COST,
            _remaining_seats=live[1:],
            _queued_draws=int(queued_draws),
            _exclude_sources=tuple(exclude_sources),
            _queued_exclude_sources=tuple(queued_exclude_sources),
        )

    def confirm_revealed_draw_buyout(self, player_index: int, accept: bool = True) -> bool:
        """Answer "any other player may pay 2 life" for the revealed card."""
        return self.resolve_pending_choice(
            "revealed_draw_buyout", player_index, accept=bool(accept)
        )

    def _resolve_revealed_draw_buyout(self, choice: PendingChoice, accept: bool) -> bool:
        """Pay and bin the revealed card, or decline and pass the offer on."""
        data = choice.data
        player = self.players[choice.player_index]
        life = int(data.get("life", 2))
        drawing_seat = int(data["drawing_seat"])
        self.discard_pending_choice(choice)
        # CR 119.4: a player may pay N life only with at least N to pay. Down to
        # exactly 0 is legal and the state-based check that follows ends the
        # game -- this is a refusal to pay what is not there.
        if accept and player.life >= life:
            player.life -= life
            self.log.append(
                f"{player.name} paid {life} life ({data.get('card_name', '')})"
            )
            self._finish_revealed_draw(
                drawing_seat, bought=True,
                queued_draws=int(data.get("_queued_draws", 0)),
                exclude_sources=tuple(data.get("_exclude_sources") or ()),
                queued_exclude_sources=tuple(
                    data.get("_queued_exclude_sources") or ()
                ),
                source_name=str(data.get("card_name", "")),
            )
            return True
        self.log.append(
            f"{player.name} declined to pay {life} life "
            f"({data.get('card_name', '')})"
        )
        self.offer_revealed_draw_buyout(
            drawing_seat,
            card_name=str(data.get("revealed_name", "")),
            source_name=str(data.get("card_name", "")),
            queued_draws=int(data.get("_queued_draws", 0)),
            exclude_sources=tuple(data.get("_exclude_sources") or ()),
            queued_exclude_sources=tuple(data.get("_queued_exclude_sources") or ()),
            remaining_seats=list(data.get("_remaining_seats") or ()),
        )
        return True

    def _default_revealed_draw_buyout(self, choice: PendingChoice) -> None:
        """The stated policy for a seat nobody is asking: **decline**.

        Not a valuation (``engine/ai_valuation.py`` is where one would go) but a
        policy, and one the shape of the offer forces: this is put to every
        other player on *every* draw for as long as the enchantment is on the
        battlefield, so a default that paid would spend a seat's whole life
        total inside a few turns of somebody else's draw steps. Declining costs
        nothing and leaves the card doing to a table of humans what it does.
        """
        self._resolve_revealed_draw_buyout(choice, False)

    def _finish_revealed_draw(
        self, drawing_seat: int, *, bought: bool, queued_draws: int,
        exclude_sources: tuple[int, ...],
        queued_exclude_sources: tuple[int, ...],
        source_name: str,
    ) -> None:
        """The two branches the poll ends in, plus the draws queued behind it.

        "If a player does, put that card into its owner's graveyard. Otherwise,
        that player draws a card." The card has been on top of the library all
        along (see the interceptor), so the payment moves it and a declined
        offer simply lets the draw happen -- through the seam, carrying this
        source in ``exclude_sources``, because CR 614.5 gives a replacement one
        opportunity per event and the draw this one just created must not be
        replaced by it again.
        """
        player = self.players[drawing_seat]
        if bought and player.library:
            card = player.library.pop(0)
            self.put_card_into_graveyard(player, card, from_zone="library")
            self.log.append(
                f"{card.name} was put into {player.name}'s graveyard "
                f"({source_name})"
            )
        elif not bought:
            self._draw_with_replacements(
                player, 1, exclude_sources=exclude_sources
            )
        if queued_draws > 0:
            # CR 121.2: the draws behind this one are their own events and get
            # their own trip through the seam -- including this replacement
            # again, which is what a two-card draw under Zur's Weirding is.
            self._draw_with_replacements(
                player, queued_draws, exclude_sources=queued_exclude_sources
            )
