"""Searching a library (CR 701.23), and the searches built the same way.

One prompt over the zones a searcher may look through. The single-find shape
answers with one index, a counted search ("up to two basic land cards") with
its whole set of picks, and "fail to find" is the second answer rather than a
way around the prompt — withheld where the search must find (CR 701.23d,
``_search_floor``). Where a counted search's printed slots send its finds to
different places, ``search_destination`` asks which found card goes where.
``find_is_public`` is the one answer to whether the table may learn which card
a search or a look took (CR 400.2); every log line that names a find asks it.

The two-zone exile search (Chandra, Heart of Fire's −9: a graveyard and a
library searched together, any number of finds exiled) is the same picker over
more than one zone, and lives here for that reason.
"""

from __future__ import annotations

import random
from ....linked_exile import link_exiled_card, shuffle_linked_pile
from ....pending_choices import PendingChoice
from ....oracle_types import SEARCHED_PERMANENTS
from ....search_filters import (landing_seat, search_matches,
                                search_names_a_quality, search_slots,
                                searched_seat, slot_assignment)


class LibrarySearchChoicesMixin:
    # -- Library search -----------------------------------------------------

    def confirm_search_library(
        self, caster_index: int, library_index: int, zone: str = "library"
    ) -> bool:
        return self.resolve_pending_choice(
            "search_library", caster_index, library_index=library_index, zone=zone
        )

    def confirm_search_library_picks(self, caster_index: int, picks: list) -> bool:
        """Answer a counted search ("up to two basic land cards") whole: every
        find in one action, each pick naming its zone and index there."""
        return self.resolve_pending_choice(
            "search_library", caster_index, picks=picks
        )

    def confirm_search_destination(self, caster_index: int, assignments: list) -> bool:
        return self.resolve_pending_choice(
            "search_destination", caster_index, assignments=assignments
        )

    def decline_search_library(self, caster_index: int) -> bool:
        """"Fail to find" (CR 701.23b) as an answer rather than an error.

        It is the *only* legal answer when nothing in the searched zones matches
        the restriction — "a card named Teferi, Timeless Voyager" usually finds
        nothing — so a seat that cannot find one still has to be able to leave
        the search. Routed through the same resolver as a find, because the
        library was searched either way and so is shuffled either way.
        """
        return self.resolve_pending_choice(
            "search_library", caster_index, library_index=-1, zone="none"
        )

    def _resolve_search_library(
        self, choice: PendingChoice, library_index: int, zone: str = "library",
        *, enforce_floor: bool = True,
    ) -> bool:
        # Who chooses and whose zone is looked in are two questions, and
        # Reincarnation prints them as two players: its controller picks the
        # card (CR 608.2c) out of the graveyard of the dead creature's owner.
        # The default is the chooser's own zone, which is every other card.
        caster = self.players[searched_seat(choice.data, choice.player_index)]
        zones = tuple(choice.data.get("zones", ("library",)))
        if zone == "none":
            # Fail-to-find ends the whole search, not one find of it: CR 701.23b
            # is about the search, and "up to two" makes finding fewer a legal
            # answer the player states by declining the rest.
            #
            # …but only where the card printed one. "Search your library for
            # three cards" (Intuition, Jester's Cap) is CR 701.23d's bare
            # quantity and *must* find that many, so a decline over a library
            # that holds them is not an answer — refused here as well as on the
            # picks path, because a floor enforced on one of the two ways into
            # the same prompt is a floor a client can walk around.
            #
            # ``enforce_floor`` is the one door out, and only the *default*
            # answer holds the key: a non-interactive seat whose policy list the
            # resolver refuses has to be able to leave the prompt, or a search
            # nobody can answer suspends the resolution for the rest of the
            # game. Every answer off the wire goes through the registry's
            # resolver, which never passes it.
            if enforce_floor and self._search_floor(choice) > 0:
                return False
            if "library" in zones:
                random.shuffle(caster.library)
            self._record_search_reveal(choice)
            self.discard_pending_choice(choice)
            # A search that found nothing still *searched*, so a printed "exile
            # the rest" still empties the zones (Doomsday with an empty library
            # and graveyard is a legal, and lethal, cast).
            self._exile_searched_remainder(choice.data, caster, zones)
            self.log.append(f"{caster.name} searched and found nothing more")
            return True
        # A counted search ("up to two basic land cards") takes its whole
        # answer at once through the picks path below; a per-find answer here
        # would reopen the split flow the atomic answer replaced.
        if len(choice.data.get("destinations") or ()) > 1:
            return False
        # A zone the search was not armed with is not a zone this search may
        # look in: "search your library" is a different card from "search your
        # library and/or graveyard", and the wire must not be able to promote
        # one into the other.
        if zone not in zones:
            return False
        source = caster.library if zone == "library" else caster.graveyard
        if library_index < 0 or library_index >= len(source):
            return False
        card = source[library_index]
        # What the search may *find* is checked here rather than trusted from
        # whoever answered. The web picker is sent the legal indices, but a
        # payload is a hint: a client that offered the whole library would
        # otherwise turn "a creature card with mana value 6 or greater" into
        # Demonic Tutor.
        if not search_matches(
            card, choice.data, game=self, owner=choice.player_index
        ):
            return False
        source.pop(library_index)
        # "…, reveal it, …" (CR 701.20): a search armed with the printed word
        # shows the find's face to every player when the search ends.
        if choice.data.get("reveal"):
            choice.data.setdefault("revealed_names", []).append(card.name)
        # "…put it onto the battlefield, then shuffle" (Garruk, Unleashed's
        # emblem) — the found card enters play instead of the hand. The
        # destination was fixed when the search was armed; the wire cannot
        # promote a tutor-to-hand into a tutor-to-battlefield.
        destination = choice.data.get("destination", "hand")
        enters_tapped = bool(choice.data.get("enters_tapped"))
        if destination == "held":
            # "Search your library for an artifact card. **If** that card's mana
            # value… put it onto the battlefield… **If you don't**, put it into
            # its owner's graveyard." (Transmute Artifact.) Where the find goes
            # is a later step's decision, so the search hands it over rather
            # than placing it — the card is out of the library and in nobody's
            # zone for exactly as long as it takes the next step of the same
            # resolution to run, with no priority in between.
            record = choice.data.get("record")
            if record is not None:
                record["found_card"] = card
            self.log.append(f"{caster.name} searched {zone} and found {card.name}")
            if zone == "library":
                random.shuffle(caster.library)
            self._record_search_reveal(choice)
            self.discard_pending_choice(choice)
            return True
        if destination == "battlefield":
            from ....models import Permanent as _Permanent

            found = _Permanent(card=card, tapped=enters_tapped)
            # **Who owns it** (CR 108.3), which for a card out of a library or
            # a graveyard is the player whose zone it was in — ``caster`` here,
            # the *searched* seat and not the searching one.
            #
            # Recorded on the permanent because ``owner_index_of`` otherwise
            # answers with the base controller, on a stated assumption that
            # "every way a permanent enters play in this pool puts it under its
            # owner's control". Bribery is the first card that makes that false:
            # it opens an opponent's library and puts the creature onto **your**
            # battlefield (CR 110.2a), so with nothing written here the Angel
            # would go to the thief's graveyard when it died rather than to its
            # owner's (CR 404.1). Written on every path rather than only where
            # the two seats differ — for every card before this one they are the
            # same seat, so the recorded answer is the one already given.
            found.metadata["owner_player_index"] = self.players.index(caster)
            # "…under the control of that creature's owner." Whose battlefield
            # again defaults to the chooser's, which is every other card — and
            # Bribery is the one that separates it from the line above: "put
            # that card onto the battlefield **under your control**" is the
            # searcher's side, out of the searched player's deck.
            self._put_permanent_onto_battlefield(
                landing_seat(choice.data, choice.player_index), found, None
            )
            # "…put that card onto the battlefield, then shuffle. **That
            # Dragon** gains haste until end of turn. Exile **it** at the
            # beginning of the next end step." (Zirilan of the Claw.) The
            # sentences behind a search name the permanent it put down, and
            # this is the only moment anything can say which one that is: the
            # search suspends on a prompt, so by the time the rest of the
            # resolution runs the card is one permanent among many.
            #
            # Written to the resolution's scratchpad under the key
            # ``lowering/_records._PRODUCES`` declares for this kind, which
            # is the same channel a reanimation already uses — one record
            # shape, so a sentence reading "that creature" cannot care which
            # step put the permanent there.
            record = choice.data.get("record")
            if record is not None:
                record.setdefault(SEARCHED_PERMANENTS, [])
                record[SEARCHED_PERMANENTS].append(found.permanent_id)
            # "Then if you control four or more lands, untap that land."
            # (Fabled Passage.) Counted *after* the land has entered, which is
            # when the printed "then" happens — so the land counts itself. Through
            # `become_untapped`, because anything that must happen when a
            # permanent untaps has one place to be.
            rider = choice.data.get("untap_found_if")
            if rider and found.tapped:
                from ....handlers._common import evaluate_count

                held = evaluate_count(self, caster, rider["filter"])
                if held >= int(rider["threshold"]):
                    self.become_untapped(found)
                    self.log.append(
                        f"{card.name} untaps ({held} counted)"
                    )
        elif destination == "library_top":
            # "…then shuffle and put that card on top." (Enlightened Tutor,
            # Mystical Tutor, Worldly Tutor.) The **order** is the effect: the
            # library is shuffled first and the find placed after, so it is on
            # top rather than somewhere random. That is why this branch shuffles
            # itself and returns rather than falling through to the shared
            # shuffle below — reaching that one would put the card on top and
            # then shuffle it back in, which is the card doing nothing.
            if zone == "library":
                random.shuffle(caster.library)
            self.put_card_into_library(caster, card, "top")
            shown = (
                card.name if self.find_is_public(choice.data, destination, zone)
                else "a card"
            )
            self.log.append(
                f"{caster.name} searched {zone} and put {shown} "
                "on top of their library"
            )
            self._record_search_reveal(choice)
            self.discard_pending_choice(choice)
            return True
        elif destination == "graveyard":
            # "…put that card into your graveyard, then shuffle." (Entomb; the
            # counted spelling is Buried Alive's.) Through
            # ``put_card_into_graveyard`` rather than an append, because
            # anything that must happen when a card arrives in a graveyard has
            # one place to be — Gaea's Blessing's "when this card is put into
            # your graveyard from your library" is a trigger a raw append would
            # walk straight past.
            self.put_card_into_graveyard(caster, card, from_zone=zone)
        elif destination == "exile":
            # CR 400.3: the card goes to its owner's exile, and its owner is the
            # player whose library it came out of — which is `caster` here, the
            # *searched* seat rather than the searching one.
            caster.exile.append(card)
            self._record_search_exile(choice.data, card)
        else:
            self.put_card_into_hand(caster, card)
        # **Who searched**, which is the seat that answered the prompt and not
        # the seat whose zone was opened — two questions this line answered with
        # one name, so Bribery logged "Bob searched library and put Serra Angel
        # onto the battlefield" for a search Alice made onto Alice's side. Where
        # they are the same seat (every card before this one) the sentence is
        # byte-identical.
        searcher = self.players[choice.player_index]
        whose = "" if searcher is caster else f"{caster.name}'s "
        # Named only where the table may know it (``find_is_public``): a card
        # that went from a library to a hand unrevealed is "a card".
        shown = (
            card.name if self.find_is_public(choice.data, destination, zone)
            else "a card"
        )
        self.log.append(
            f"{searcher.name} searched {whose}{zone} and put {shown} "
            + (
                "onto the battlefield" if destination == "battlefield"
                else "into exile" if destination == "exile"
                else "into their graveyard" if destination == "graveyard"
                else "into hand"
            )
        )
        # Only a library search shuffles (CR 701.23h, and the printed "If you
        # search your library this way, shuffle"): a graveyard is an open zone,
        # and randomising a library the player did not search would destroy
        # information they were entitled to keep.
        if zone == "library":
            random.shuffle(caster.library)
        self._record_search_reveal(choice)
        self.discard_pending_choice(choice)
        return True

    def _resolve_search_library_picks(self, choice: PendingChoice, picks: list) -> bool:
        """A counted search's one answer: every find at once (Cultivate).

        The picks are validated together before anything moves — each names a
        zone the search was armed with and a card the restriction admits, no
        card is taken twice, and each printed name is consumed by the find
        that used it (Alpine Houndmaster) — because a half-applied answer
        would leave the library short with the prompt still owed. An empty
        list is the fail-to-find (CR 701.23b): "up to" makes finding fewer a
        legal answer, and the library was searched either way.

        Where the finds land is a separate question the search does not
        answer: `_place_or_ask_destinations` applies the printed slots, and
        asks the finder which card fills which only when the slots differ.
        """
        slots = self._search_destination_slots(choice.data)
        if len(slots) < 2:
            # Not a counted search — the single-find path is its answer.
            return False
        if len(picks) > len(slots):
            return False
        # **CR 701.23d: a search for a bare quantity is a floor.** "Search your
        # library for three cards" (Intuition, Jester's Cap) must find that
        # many, or as many as possible if the zones hold fewer — where "up to
        # three" and "any number of" let the searcher stop early, which is the
        # `up_to` key those printings carry and these do not.
        #
        # Enforced here rather than in the picker, for the reason
        # `activation_restrictions.py` exists: a printed restriction nobody
        # enforces is not a dead clause, it is a clause that works more often
        # than the card allows — an Intuition that found one card would be a
        # strictly better spell, and silently so.
        #
        # Asked before the fail-to-find below, because with a floor an empty
        # answer *is* an under-find rather than CR 701.23b's decline.
        if len(picks) < self._search_floor(choice):
            return False
        if not picks:
            return self._resolve_search_library(choice, -1, "none")
        # Whose zones are looked in, which is not always the seat answering:
        # Jester's Cap's controller searches the *target's* library. The
        # single-find path beside this one has asked since Reincarnation; this
        # one read `choice.player_index`, which was latent only because no card
        # had yet combined a counted search with somebody else's zone.
        caster = self.players[searched_seat(choice.data, choice.player_index)]
        zones = tuple(choice.data.get("zones", ("library",)))
        working = dict(choice.data)
        seen: set[tuple[str, int]] = set()
        found: list = []
        for pick in picks:
            if not isinstance(pick, dict):
                return False
            zone = pick.get("zone", "library")
            index = pick.get("index", -1)
            if zone not in zones:
                return False
            source = caster.library if zone == "library" else caster.graveyard
            if not isinstance(index, int) or index < 0 or index >= len(source):
                return False
            if (zone, index) in seen:
                return False
            seen.add((zone, index))
            card = source[index]
            if not search_matches(
                card, working, game=self, owner=choice.player_index
            ):
                return False
            # "a card named A **and/or** a card named B": each printed name is
            # one find, dropped as it is used, so a library holding two copies
            # of the first card cannot answer both finds with it.
            among = list((working.get("restrictions") or {}).get("named_among") or ())
            if among:
                from ....search_filters import name_key

                working["restrictions"] = {
                    **(working.get("restrictions") or {}),
                    "named_among": [
                        n for n in among if name_key(n) != name_key(card.name)
                    ],
                }
            found.append((zone, index, card))
        # "a land card **of each basic land type**" (Gaea's Balance): every
        # find fills a printed description of its own. Asked of the answer as a
        # whole, after each card has passed the union above — a Tropical Island
        # beside a basic Forest is legal only with the dual read as the Island,
        # which no card-at-a-time test can decide — and before anything moves,
        # for this resolver's standing reason.
        if search_slots(choice.data) and None in slot_assignment(
            [card for _zone, _index, card in found], choice.data,
            game=self, owner=choice.player_index,
        ):
            return False
        # Highest index first so the earlier picks still address the cards
        # they named (the two zones do not renumber each other).
        for zone, index, _card in sorted(found, key=lambda entry: entry[1], reverse=True):
            source = caster.library if zone == "library" else caster.graveyard
            source.pop(index)
        cards = [card for _zone, _index, card in found]
        # "…, reveal those cards, …" (CR 701.20): one showing for the whole
        # search, recorded now — the finds are known even while where each
        # lands is still being asked.
        if choice.data.get("reveal"):
            choice.data["revealed_names"] = [card.name for card in cards]
        # **Who searched** is the seat that answered, which is not always the
        # seat whose zones were opened (Jester's Cap; Guided Passage's opponent
        # choosing out of the caster's library) — the single-find path has said
        # so since Bribery, and this one named the zone's owner for both. Where
        # they are the same seat the sentence is byte-identical.
        searcher = self.players[choice.player_index]
        whose = "" if searcher is caster else f"{caster.name}'s "
        # The finds are named only if every one of them is public wherever it
        # is about to land (``find_is_public``); otherwise the table is told
        # how many, which it could count for itself.
        everywhere_public = all(
            self.find_is_public(choice.data, destination)
            for destination, _tapped in (slots or [(choice.data.get("destination", "hand"), False)])
        )
        self.log.append(
            f"{searcher.name} searched {whose}" + " and ".join(zones)
            + " and found "
            + (
                ", ".join(card.name for card in cards) if everywhere_public
                else f"{len(cards)} card(s)"
            )
        )
        # The search is over once the finds are named (CR 701.23h): shuffle
        # before the destination question, which happens after the search.
        if "library" in zones:
            random.shuffle(caster.library)
        self._record_search_reveal(choice)
        self.discard_pending_choice(choice)
        # "…**and exile the rest**." (Doomsday.) Before the finds are placed,
        # or the cards about to go on top of the library would be exiled with
        # everything else \u2014 they are out of the zones already, but the library
        # is where they are going.
        self._exile_searched_remainder(choice.data, caster, zones)
        self._place_or_ask_destinations(choice.player_index, cards, slots, choice.data)
        return True

    def _search_findable_picks(self, choice: PendingChoice, limit: int) -> list:
        """Up to *limit* picks the resolver itself admits, in zone order.

        The safety net under :meth:`_default_search_library`, and it reads the
        one predicate the answer will be checked against rather than the AI's —
        a second reading is exactly what would leave the policy's list refused
        and the prompt still owed.
        """
        searched = self.players[searched_seat(choice.data, choice.player_index)]
        picks: list[dict] = []
        if search_slots(choice.data):
            # One find per printed description: the cards a largest assignment
            # gave a slot, which is by construction an answer the picks
            # resolver admits and one that meets its floor.
            findable = self._search_findable_entries(choice)
            assigned = slot_assignment(
                [card for _zone, _index, card in findable], choice.data,
                game=self, owner=choice.player_index,
            )
            return [
                {"zone": zone, "index": index}
                for (zone, index, _card), slot in zip(findable, assigned)
                if slot is not None
            ][:limit]
        for zone in tuple(choice.data.get("zones", ("library",))):
            cards = searched.library if zone == "library" else searched.graveyard
            for index, card in enumerate(cards):
                if len(picks) >= limit:
                    return picks
                if search_matches(
                    card, choice.data, game=self, owner=choice.player_index
                ):
                    picks.append({"zone": zone, "index": index})
        return picks

    def _search_findable_entries(self, choice: PendingChoice) -> list[tuple]:
        """Every ``(zone, index, card)`` in the searched zones the phrase
        admits, in zone order — the population the slot assignment is taken
        over, read through the one predicate every other reader asks."""
        searched = self.players[searched_seat(choice.data, choice.player_index)]
        return [
            (zone, index, card)
            for zone in tuple(choice.data.get("zones", ("library",)))
            for index, card in enumerate(
                searched.library if zone == "library" else searched.graveyard
            )
            if search_matches(
                card, choice.data, game=self, owner=choice.player_index
            )
        ]

    def _search_floor(self, choice: PendingChoice) -> int:
        """How many cards this search **must** find (CR 701.23d), or 0.

        Three conditions, each a different sentence. A printed "up to" or "any
        number of" is a ceiling and no floor at all. A search naming **one** card
        *with a stated quality* is left alone deliberately: the single-find
        flow's decline is the engine's one escape from a prompt nothing can
        answer, and closing it would strand a seat wherever the picker and the
        resolver read a restriction even slightly differently — and CR 701.23b
        lets that search fail anyway. And what is left is bounded by what is
        actually there — CR 701.23d's "or as many as possible", which is what
        keeps an empty library from being a refusal.

        **A search for "a card" names no quality and has a floor of one.** It
        was caught by the single-find exemption, so Demonic Tutor and Entomb
        offered "fail to find" and took it — the search CR 701.23d names by
        its own example. No restriction means nothing for the picker and the
        resolver to read differently, so the reason for the exemption does
        not reach it (``search_filters.search_names_a_quality``).
        """
        if choice.data.get("up_to"):
            return 0
        slots = len(self._search_destination_slots(choice.data))
        if slots < 2:
            if search_names_a_quality(choice.data):
                return 0
            return min(1, self._search_findable_count(choice))
        return min(slots, self._search_findable_count(choice))

    def _search_findable_count(self, choice: PendingChoice) -> int:
        """How many cards in the searched zones the phrase actually admits.

        The "…or as many as possible" half of CR 701.23d. A search with a floor
        can still come up short — an empty library, or three cards where the
        card asked for five — and that is a legal answer rather than a refusal,
        so the floor is the smaller of what the card names and what is there.

        Through ``search_matches``, the one predicate the engine, the AI and the
        web picker all answer with: a second count written here would be a
        second reading of the restriction, and the two would disagree the first
        time a narrowing was added to either.

        A search that finds **one card per printed description** (Guided
        Passage's "a creature card, a land card, and a noncreature, nonland
        card") can find no more than a largest assignment of cards to
        descriptions: three creatures in a library answer one slot, not three.
        """
        if search_slots(choice.data):
            return sum(
                slot is not None
                for slot in slot_assignment(
                    [card for _z, _i, card in self._search_findable_entries(choice)],
                    choice.data, game=self, owner=choice.player_index,
                )
            )
        searched = self.players[searched_seat(choice.data, choice.player_index)]
        zones = tuple(choice.data.get("zones", ("library",)))
        return sum(
            1
            for zone in zones
            for card in (searched.library if zone == "library" else searched.graveyard)
            if search_matches(
                card, choice.data, game=self, owner=choice.player_index
            )
        )

    def _exile_searched_remainder(self, data: dict, searched, zones: tuple) -> None:
        """"Search your library and graveyard for five cards **and exile the
        rest**." (Doomsday.)

        What becomes of the piles a search looked through, which for every other
        printing is nothing at all: CR 701.23a looks and leaves the zone as it
        was. Both named zones are emptied, because "the rest" is the rest of
        what was searched \u2014 emptying only the library would leave a graveyard
        the sentence also opened.

        CR 400.3 sends each card to its **owner's** exile, which is the player
        whose zones these are: a search of somebody else's library is a
        different flow (``zone_owner_target``) and no printing of it exiles the
        remainder, so the seat here is the one the finds were taken from.
        """
        if not data.get("exile_rest"):
            return
        moved = 0
        for zone_name in zones:
            pile = searched.library if zone_name == "library" else searched.graveyard
            moved += len(pile)
            searched.exile.extend(pile)
            pile.clear()
        self.log.append(
            f"{searched.name} exiled the rest of their "
            + " and ".join(zones)
            + f" ({moved} card(s))"
        )

    def _search_destination_slots(self, data: dict) -> list[tuple[str, bool]]:
        """The printed places a counted search's finds go, as (destination,
        enters-tapped) pairs in the printed order."""
        destinations = list(data.get("destinations") or ())
        tapped = list(data.get("tapped") or ())
        tapped += [False] * (len(destinations) - len(tapped))
        return list(zip(destinations, tapped))

    def _place_or_ask_destinations(
        self, seat: int, cards: list, slots: list[tuple[str, bool]], data: dict
    ) -> None:
        """Land the found cards, asking which goes where only when it matters.

        The question exists whenever the printed slots differ at all — with
        fewer finds than slots ("up to two … put one onto the battlefield
        tapped and the other into your hand", finding one), the finder still
        chooses which printed slot the card fills, which is Cultivate's
        ruling. Identical slots (both to hand, Alpine Houndmaster) have
        nothing to ask.
        """
        if not cards:
            return
        # Where a find *lands* is its own seat: "that player puts those cards
        # into their hand" (Jester's Mask) is the searched player's hand, not
        # the searcher's. Defaulted to the chooser, which is every other card.
        landing = landing_seat(data, seat)
        if len(set(slots)) <= 1:
            # "…put those cards on top **in any order**" (Goblin Recruiter):
            # the finder named them in the order they want, and each placement
            # goes *on top* of the last — so the list is walked backwards and
            # the first card named ends up first from the top. Every other
            # destination is order-blind, which is why this is one `reversed`
            # rather than a branch.
            ordered = (
                list(reversed(cards)) if slots[0][0] == "library_top" else cards
            )
            for card in ordered:
                destination, tapped = slots[0]
                self._place_found_card(landing, card, destination, tapped, data)
            return
        self.arm_pending_choice(
            "search_destination", seat,
            card_name=data.get("card_name", ""),
            cards=[card.name for card in cards],
            slots=[
                {"destination": destination, "tapped": tapped}
                for destination, tapped in slots
            ],
            # Carried onto the next prompt because that prompt's own payload has
            # no zone seats on it, and the seat that answers "which card goes
            # where" is still not necessarily the seat the cards go to.
            landing_seat=landing,
            _cards=list(cards),
            # And the resolution's scratchpad, for the same reason: a find that
            # is about to be *exiled* has to be written down where "you may play
            # that card" reads it, and this prompt is where the exile happens
            # once the slots differ. Absent on every search that records
            # nothing, which is what `_record_search_exile` answers to.
            record=data.get("record"),
        )

    def _record_search_exile(self, data: dict, card) -> None:
        """Write down a card this search **exiled**, for the sentence behind it.

        "…and exile it. … Until the beginning of your next upkeep, you may play
        that card." (Grinning Totem.) The permission names the card the search
        put in exile, and nothing else can say which one that is: the zone holds
        whatever else has gone there, and two copies of a card in a deck are the
        same immutable object, so a name match would find the wrong one.

        Under the one key every "cards exiled this way" in this engine reads
        (`lowering/_records._PRODUCES`), so a sentence saying it needs no reader
        of its own — and only the *exile* destination writes it, because a
        search that put its find in a hand exiled nothing.
        """
        record = data.get("record")
        if record is None:
            return
        record.setdefault("exiled_cards", []).append(card)

    def _place_found_card(
        self, seat: int, card, destination: str, tapped: bool, data: dict | None = None
    ) -> None:
        """One found card landing where the print sent it.

        *seat* is whose zone receives it, which is not always the seat that
        chose — "Search target player's library for three cards and exile
        them" (Jester's Cap) puts them in that player's exile, because CR 400.3
        sends an object to its **owner's** zone and the owner is the player
        whose library it came out of.

        *data* is the prompt's own dict, carried only so an exile can be
        recorded through the same seam the single-find path uses; a caller with
        nothing to record passes none.
        """
        caster = self.players[seat]
        if destination == "battlefield":
            from ....models import Permanent as _Permanent

            self._put_permanent_onto_battlefield(
                seat, _Permanent(card=card, tapped=tapped), None
            )
        elif destination == "exile":
            caster.exile.append(card)
            if data is not None:
                self._record_search_exile(data, card)
        elif destination == "held":
            # "Search your library for three cards and reveal them. **Target
            # opponent chooses one.**" (Intuition.) The counted twin of
            # ``_resolve_search_library``'s own "held" branch, and here for that
            # branch's reason word for word: where the finds go is a later
            # step's decision, so the search hands them over rather than placing
            # them. They are out of the library and in nobody's zone for exactly
            # as long as it takes the next step of the same resolution to run,
            # with no priority in between.
            #
            # A *list*, where the single-find branch writes one card: the next
            # sentence asks which of them, which only a pile can answer. The key
            # is named by the lowering that will read it (``record_key``),
            # because a held pile is a value rather than a fact about the search.
            record = (data or {}).get("record")
            key = (data or {}).get("record_key")
            if record is not None and key:
                record.setdefault(str(key), []).append(card)
        elif destination == "library_top":
            # "…then shuffle and put those cards on top in any order."
            # (Goblin Recruiter.) The counted twin of the single-find branch in
            # `_resolve_search_library`, and it had no branch here at all — a
            # counted search sent to the top of a library fell through to the
            # `else` and put every find in the finder's **hand**, which is a
            # different card. The shuffle already happened, up in the picks
            # resolver, so a card placed here stays on top.
            self.put_card_into_library(caster, card, "top")
        elif destination == "graveyard":
            # "Search your library for up to three creature cards, put them
            # into your graveyard, then shuffle." (Buried Alive.) Through the
            # seam for the reason the single-find branch gives: a card arriving
            # in a graveyard from a library is an event Gaea's Blessing triggers
            # on, and an append is a place for that to be forgotten.
            #
            # The source zone is claimed only for a search that looked in one
            # zone. This path is handed the finds without the slot each came
            # out of, and a two-zone search (`zones` naming a graveyard too)
            # could have taken this card from the graveyard — announcing
            # "from your library" for it would be a trigger firing on an event
            # that did not happen, which is worse than one that does not fire.
            zones = tuple(data.get("zones", ("library",))) if data else ("library",)
            self.put_card_into_graveyard(
                caster, card,
                from_zone="library" if zones == ("library",) else None,
            )
        else:
            self.put_card_into_hand(caster, card)
        where = (
            "onto the battlefield tapped" if destination == "battlefield" and tapped
            else "onto the battlefield" if destination == "battlefield"
            else "into exile" if destination == "exile"
            else "on top of their library" if destination == "library_top"
            else "into their graveyard" if destination == "graveyard"
            else "aside, for the next step to place" if destination == "held"
            else "into hand"
        )
        shown = card.name if self.find_is_public(data, destination) else "a card"
        self.log.append(f"{caster.name} put {shown} {where}")

    def _resolve_search_destination(self, choice: PendingChoice, assignments: list) -> bool:
        """Apply the finder's answer to "which found card goes where".

        ``assignments`` maps each found card, in the order the prompt listed
        them, to one printed slot. The slots must be distinct — two cards
        cannot both be the "one" put onto the battlefield — but with fewer
        cards than slots some slots go unfilled, which is how finding one
        card under a two-slot printing works.
        """
        cards = choice.data.get("_cards") or []
        slots = choice.data.get("slots") or []
        if len(assignments) != len(cards):
            return False
        if any(
            not isinstance(entry, int) or entry < 0 or entry >= len(slots)
            for entry in assignments
        ):
            return False
        if len(set(assignments)) != len(assignments):
            return False
        landing = int(choice.data.get("landing_seat", choice.player_index))
        for card, slot_index in zip(cards, assignments):
            slot = slots[slot_index]
            self._place_found_card(
                landing, card, slot["destination"], bool(slot.get("tapped")),
                choice.data,
            )
        self.discard_pending_choice(choice)
        return True

    def _default_search_destination(self, choice: PendingChoice) -> None:
        """Printed order — the first find fills the first slot. The AI's search
        default picks its best card first, so under Cultivate its best land is
        the one that reaches the battlefield, matching the old split flow."""
        self._resolve_search_destination(
            choice, list(range(len(choice.data.get("_cards") or ())))
        )

    #: Where a card is face up for the whole table once it arrives (CR 400.2:
    #: the battlefield, graveyards and exile are public zones) — and "held",
    #: the pile a search hands the next step of its own resolution, which that
    #: step then shows or places in one of the other three.
    _PUBLIC_FIND_ZONES = frozenset({"battlefield", "graveyard", "exile", "held"})

    @classmethod
    def find_is_public(cls, data: dict | None, destination: str, zone: str | None = None) -> bool:
        """Whether the table may be told **which** card a search or a look took.

        ``game.log`` is one list and every seat and spectator is sent it, so a
        line in it is an announcement. CR 701.20e: to look at a card is not to
        reveal it, and a card that goes from a library to a hand never leaves
        the hidden zones (CR 400.2) — nobody but the player holding it learns
        what it was. So a find is named only when something made it public:

        * the card's own sentence showed it — ``reveal`` on a search ("…,
          reveal it, …"), ``revealed`` on a look ("Reveal the top three
          cards…"), ``finds_are_public`` where an earlier step of the same
          effect showed the whole pile (Guided Passage);
        * it was found in a public zone (a search of a graveyard);
        * or it arrived in one.

        Impulse's kept card, Demonic Tutor's find and each of Doomsday's five
        were in the log by name, where the other seat's ``/state`` read them.
        """
        data = data or {}
        if data.get("reveal") or data.get("revealed") or data.get("finds_are_public"):
            return True
        zones = (zone,) if zone is not None else tuple(data.get("zones", ("library",)))
        if zones == ("graveyard",):
            return True
        return destination in cls._PUBLIC_FIND_ZONES

    def _record_search_reveal(self, choice: PendingChoice) -> None:
        """The showing a printed "reveal it/those cards" performs, made when the
        search ends (a decline included — the finds already made were shown).
        One event and one log line for the whole search, because "those cards"
        is one showing, not one per find."""
        revealed = list(choice.data.get("revealed_names") or ())
        if not revealed:
            return
        caster = self.players[choice.player_index]
        self.record_reveal(choice.player_index, revealed)
        self.log.append(f"{caster.name} revealed {', '.join(revealed)}")

    def _default_search_library(self, choice: PendingChoice) -> None:
        """The AI's search policy, and a fail-to-find when it declines or when
        its choice turns out not to be legal — the library is searched either
        way (CR 701.23b), which is what the decline path performs."""
        from ....ai_policy import choose_search_card, choose_search_cards

        slots = self._search_destination_slots(choice.data)
        if len(slots) > 1:
            picks = choose_search_cards(
                self, choice.player_index, choice.data, len(slots)
            )
            if not self._resolve_search_library_picks(choice, picks):
                # The policy's list was refused — it reads the restriction with
                # no game in hand, so it can differ from the resolver's reading
                # at the edges. Under a CR 701.23d floor the decline is no
                # longer a way out, so the fallback is the resolver's **own**
                # list before it is the decline: one predicate, asked the way
                # the answer will be checked.
                if not self._resolve_search_library_picks(
                    choice, self._search_findable_picks(choice, len(slots))
                ):
                    self._resolve_search_library(
                        choice, -1, "none", enforce_floor=False
                    )
            return
        found = choose_search_card(self, choice.player_index, choice.data)
        if found is None or not self._resolve_search_library(choice, found[1], found[0]):
            # A search that must find (CR 701.23d: "a card", with no quality
            # stated) is not one a policy may decline, so before the decline
            # the fallback is the resolver's own first findable card — the
            # arrangement the counted branch above already has.
            if self._search_floor(choice) > 0:
                for zone, index, _card in self._search_findable_entries(choice):
                    if self._resolve_search_library(choice, index, zone):
                        return
            self._resolve_search_library(choice, -1, "none", enforce_floor=False)

    # -- Two-zone exile search (Chandra, Heart of Fire's −9) ------------------

    def confirm_search_exile(self, caster_index: int, picks: list) -> bool:
        """*picks* is any number of ``{"zone": "library"|"graveyard",
        "index": int}`` entries — "any number" includes zero, which is this
        search's fail-to-find (CR 701.23b)."""
        return self.resolve_pending_choice(
            "search_exile_cards", caster_index, picks=picks
        )

    @staticmethod
    def _exile_search_matches(card, data: dict) -> bool:
        from ....search_filters import card_has_type

        card_types = tuple(data.get("card_types") or ())
        colors = tuple(data.get("colors") or ())
        # Through ``card_has_type``, never ``primary_type``: CR 205.2a gives a
        # card every type printed on it, and "artifact **and/or** creature
        # cards" (Skyship Weatherlight) is a union over them. ``primary_type``
        # collapses a type line to the first word of a fixed list, so a card
        # whose line reads "Land Creature" answered "land" and was neither.
        if card_types and not any(
            card_has_type(card, wanted) for wanted in card_types
        ):
            return False
        if colors and not any(color in card.colors for color in colors):
            return False
        return True

    def _resolve_search_exile(self, choice: PendingChoice, picks: list) -> bool:
        """Every pick is validated before anything moves — a single bad entry
        rejects the whole answer and leaves the prompt queued, so a malformed
        request cannot exile half a selection."""
        caster = self.players[choice.player_index]
        zones = tuple(choice.data.get("zones", ("graveyard", "library")))
        seen: set[tuple[str, int]] = set()
        cleaned: list[tuple[str, int]] = []
        for pick in picks or []:
            zone = pick.get("zone") if isinstance(pick, dict) else None
            index = pick.get("index") if isinstance(pick, dict) else None
            if zone not in zones:
                return False
            source = caster.library if zone == "library" else caster.graveyard
            if not isinstance(index, int) or not (0 <= index < len(source)):
                return False
            if (zone, index) in seen:
                return False
            seen.add((zone, index))
            if not self._exile_search_matches(source[index], choice.data):
                return False
            cleaned.append((zone, index))
        # "Search your library for **three** cards" (Foresight). A printed
        # ceiling, checked before anything moves like every other part of this
        # answer — CR 701.23b lets a search find fewer, so there is no floor,
        # but a fourth pick is a card the effect never named.
        maximum = choice.data.get("maximum")
        if maximum is not None and len(cleaned) > int(maximum):
            return False
        exiled = []
        for zone in ("library", "graveyard"):
            source = caster.library if zone == "library" else caster.graveyard
            for _, index in sorted(
                (pick for pick in cleaned if pick[0] == zone),
                key=lambda pick: -pick[1],
            ):
                card = source.pop(index)
                caster.exile.append(card)
                exiled.append(card)
        # The library was searched whether or not anything was taken from it,
        # and the printed "then shuffle" applies to the search, not the find.
        if "library" in zones:
            random.shuffle(caster.library)
        ctx = choice.data.get("_context")
        # "…exile them **in a face-down pile**, and shuffle that pile."
        # (Mangara's Tome.) The finds become one linked pile on the exiling
        # permanent (CR 610.3), which is what the artifact's second ability
        # names — without the record the cards are in exile and nothing on the
        # board can say which exile they are.
        #
        # ``ends_on`` is empty and that is the card: Mangara's Tome never gives
        # them back, so nothing ends the link and the pile outlives the
        # artifact in exile, exactly as Knowledge Vault's does.
        #
        # **Linked whenever a permanent did the exiling**, face down or not
        # (CR 607.2a): "…search your library for any number of artifact and/or
        # creature cards, exile them" is Skyship Weatherlight's first ability,
        # and its second names "a card … that was exiled with Skyship
        # Weatherlight". Linking only the face-down pile left that second
        # ability reading a record nothing wrote — the channel mismatch every
        # other exile-with-a-source handler already avoids by linking
        # unconditionally. Inert for a card that never asks (Chandra, Heart of
        # Fire's -9 reads its finds off the resolution, not off the record),
        # and a spell has no permanent to link to.
        source = getattr(ctx, "source_permanent", None) if ctx is not None else None
        if source is not None:
            face_down = bool(choice.data.get("face_down_pile"))
            for card in exiled:
                link_exiled_card(
                    source, card, choice.player_index, face_down=face_down
                )
            if face_down and choice.data.get("shuffle_pile"):
                # Through the module RNG the AI simulator seeds, like every
                # other shuffle here, so a seed still replays a run exactly.
                shuffle_linked_pile(source, random.shuffle)
        if ctx is not None:
            ctx.results["exiled_cards"] = exiled
        self.discard_pending_choice(choice)
        self.log.append(
            f"{caster.name} searched {' and '.join(zones)} and exiled "
            + (", ".join(card.name for card in exiled) if exiled else "nothing")
        )
        return True

    def _default_search_exile(self, choice: PendingChoice) -> None:
        """A non-interactive seat takes everything that matches **when the cards
        come back**: "any number" is a may per card, and where a later sentence
        hands the pile over (Foresight's delayed return, Mangara's Tome's
        recorded pile, Chandra's "you may cast them") the maximum is the only
        default that never leaves value on the table.

        Where nothing reads the pile back it takes **nothing**, and the same
        sentence justifies both: exiling your own library for good is spending
        the seat's own resources, and CR 701.23b's fail-to-find is always a
        legal answer. Mana Severance is the card that separates them — it
        exiles every land it can find and never returns one, so the old policy
        emptied a headless seat's land supply the day the card was supported.
        Which of the two a card is is derived from its compiled program
        (``ai_valuation.exiled_search_pile_comes_back``) and carried on the
        prompt, never named here: the reasoning "the cards come back castable"
        was a fact about three cards rather than about the sentence.

        Where a ceiling is printed the default takes that many — the same
        "as much as the card allows" reading, bounded. Without the trim the
        picks would be refused whole and the seat would take *nothing*, which
        is the opposite default."""
        if not choice.data.get("comes_back", True):
            if not self._resolve_search_exile(choice, []):
                self.discard_pending_choice(choice)
            return
        caster = self.players[choice.player_index]
        picks = [
            {"zone": zone, "index": index}
            for zone in ("graveyard", "library")
            if zone in tuple(choice.data.get("zones", ("graveyard", "library")))
            for index, card in enumerate(
                caster.graveyard if zone == "graveyard" else caster.library
            )
            if self._exile_search_matches(card, choice.data)
        ]
        maximum = choice.data.get("maximum")
        if maximum is not None:
            picks = picks[: int(maximum)]
        elif choice.data.get("comes_back_slowly"):
            # "Any number", and the pile is bought back one card at a time
            # (Skyship Weatherlight): everything is not the default that
            # leaves no value on the table, it is the one that leaves most of
            # the library in exile. How many, and which, is a weight
            # (`ai_policy.slow_pile_picks`); that it is asked at all is this
            # registry's decision, made where the candidates are known.
            from ....ai_policy import slow_pile_picks

            picks = slow_pile_picks(self, choice.player_index, picks)
        if not self._resolve_search_exile(choice, picks):
            self._resolve_search_exile(choice, [])
