""""Choose a card name", and what the named card does next.

Necromentia's strip of every copy, Petra Sphinx's guess at the top card,
Foreshadow's bare name, Demonic Consultation's dig and Nebuchadnezzar's random
reveal. A name is any card's name (a split card has two, CR 709.4a), bounded
only by what the printed sentence allows —
``_named_card_breaks_printed_bound``, which the entry choice asks as well.
"""

from __future__ import annotations

import random
from ....faces import castable_faces, has_name, is_multi_face
from ....grammar.phrases import BASIC_LAND_WORDS
from ....models import Permanent
from ....pending_choices import PendingChoice


class CardNameChoicesMixin:
    # -- Necromentia's name, stripped from the named zones --------------------

    def confirm_name_and_strip(self, player_index: int, card_name: str) -> bool:
        """Answer Necromentia's "choose a card name" prompt."""
        return self.resolve_pending_choice(
            "name_and_strip", player_index, card_name=card_name
        )

    def _resolve_name_and_strip(self, choice: PendingChoice, card_name: str) -> bool:
        """Strip every copy of *card_name* from the named zones and pay the
        Zombies.

        CR 202.1 lets a player name any card; the one printed restriction is
        that it may not be a basic land's name, and that is enforced here rather
        than by the prompt's option list — the list is a convenience, the rule
        is the rule.

        The zones are searched in the printed order, and only the count from
        ``token_zone`` feeds the tokens: "each card exiled from their **hand**
        this way" is a strict subset of what was exiled, and counting the whole
        pile would make far more Zombies than the card promises.
        """
        from ....tokens import make_token_card

        data = choice.data
        target = self.players[data["target_seat"]]
        named = (card_name or "").strip()
        if not named:
            self.discard_pending_choice(choice)
            self.log.append("nothing was named, so nothing was exiled")
            return True
        if any(
            "basic" in (card.type_line or "").lower() and has_name(card, named)
            for zone in data["zones"] for card in getattr(target, zone, [])
        ):
            return False

        taken_from: dict[str, int] = {}
        for zone in data["zones"]:
            cards = getattr(target, zone, [])
            # ``has_name`` at every chosen-name test in this module
            # (CR 709.4a): a split card off the stack has both its halves'
            # names, so naming either finds it.
            kept = [card for card in cards if not has_name(card, named)]
            taken = [card for card in cards if has_name(card, named)]
            if taken:
                taken_from[zone] = len(taken)
                cards[:] = kept
                target.exile.extend(taken)
        # "That player shuffles" — once, after the search, and only their
        # library is disturbed (CR 701.24).
        random.shuffle(target.library)

        spec = data["token"]
        made = taken_from.get(data["token_zone"], 0)
        for _ in range(made):
            token_card = make_token_card(
                " ".join(w.title() for w in spec["subtypes"]) + " Token",
                int(spec["power"]), int(spec["toughness"]),
                "Creature — " + " ".join(w.title() for w in spec["subtypes"]),
                colors=tuple(spec["colors"]),
            )
            self._put_permanent_onto_battlefield(
                data["target_seat"],
                Permanent(card=token_card, metadata={"is_token": True}),
                None,
            )
        self.discard_pending_choice(choice)
        self.log.append(
            f"{target.name} lost {sum(taken_from.values())} copies of {named} "
            f"and made {made} token(s)"
        )
        return True

    def _default_name_and_strip(self, choice: PendingChoice) -> None:
        if not self._resolve_name_and_strip(choice, choice.data.get("default_name", "")):
            self.discard_pending_choice(choice)

    # -- "Target player chooses a card name, then reveals the top card" -------

    def confirm_name_then_reveal_top(self, player_index: int, card_name: str) -> bool:
        """Answer Petra Sphinx's "choose a card name" prompt."""
        return self.resolve_pending_choice(
            "name_then_reveal_top", player_index, card_name=card_name
        )

    def _resolve_name_then_reveal_top(
        self, choice: PendingChoice, card_name: str
    ) -> bool:
        """Reveal the top card and send it where the guess says.

        The reveal happens **here**, after the name is fixed: turning the card
        over while the prompt was open would tell the chooser what to name.

        CR 202.1 lets a player name any card at all and this card prints no
        restriction, so no name is refused — including one no card in the game
        bears, which simply misses. The comparison is against the card's own
        printed name, not an effective one: nothing in a library is a permanent
        and nothing there can be copying anything (CR 707.2).
        """
        data = choice.data
        player = self.players[choice.player_index]
        if not player.library:
            # The library emptied between arming and answering. Nothing to
            # reveal, so nothing moves.
            self.discard_pending_choice(choice)
            self.log.append(f"{player.name} has no card to reveal")
            return True
        named = (card_name or "").strip()
        revealed = player.library.pop(0)
        hit = bool(named) and has_name(revealed, named)
        zone_name = data["match_zone"] if hit else data["miss_zone"]
        # The hand is reached through the CR 614 seam every other "put this card
        # into a hand" in this engine goes through — a commander on its way to a
        # hand goes to the command zone instead (CR 903.9b), and thirty fire
        # sites is twenty-nine places to forget it.
        if zone_name == "hand":
            self.put_card_into_hand(player, revealed)
        else:
            getattr(player, zone_name).append(revealed)
        self.discard_pending_choice(choice)
        self.log.append(
            f"{player.name} named {named or 'nothing'} and revealed "
            f"{revealed.name} — it goes to their {zone_name}"
        )
        # "…and this artifact deals 2 damage to them" (Vexing Arcanix). Only on
        # a miss, and after the card has moved, because that is the printed
        # order. Through the one damage entry point, so the shields, the CR 614
        # replacements and the "dealt damage" triggers all see it.
        miss_damage = 0 if hit else int(data.get("miss_damage", 0) or 0)
        if miss_damage:
            self._deal_damage_to_player(
                player, miss_damage, source=data.get("_damage_source"),
                then=lambda dealt: self.log.append(
                    f"{player.name} is dealt {dealt} damage for the miss"
                ),
            )
        return True

    def confirm_choose_card_name(self, player_index: int, card_name: str) -> bool:
        """Answer Foreshadow's "choose a card name"."""
        return self.resolve_pending_choice(
            "choose_card_name", player_index, card_name=card_name
        )

    def _resolve_choose_card_name(
        self, choice: PendingChoice, card_name: str
    ) -> bool:
        """Record the name for the sentences behind this step.

        CR 202.1 lets a player name any card, and this card prints no
        restriction, so no name is refused — including one no card in the game
        bears, which simply never matches. An empty name is the honest answer
        for a seat with nothing to go on and matches nothing either.
        """
        if self._named_card_breaks_printed_bound(choice, (card_name or "").strip()):
            # Refused, not repaired: quietly recording something else would
            # tell the player they had named a card they had not.
            return False
        record = choice.data.get("record")
        if record is not None:
            record["chosen_card_name"] = (card_name or "").strip()
        self.discard_pending_choice(choice)
        self.log.append(
            f"{self.players[choice.player_index].name} named "
            + ((card_name or "").strip() or "nothing")
        )
        return True

    def _named_card_breaks_printed_bound(self, choice: PendingChoice, named: str) -> bool:
        """Whether *named* is a name the printed sentence does not let this
        seat choose.

        "Choose a **creature** card name" (Wood Sage) and "Choose a card name
        **other than a basic land card name**" (Desperate Research) each bound
        CR 202.1's freedom, and a bound only the prompt's label states is a
        rule nothing enforces: Wood Sage's seat could name Mountain and take
        every Mountain off the top of its library.

        A basic land card's name is a closed list (CR 205.3i's five basic land
        types name them, with "Snow-Covered" in front or without, and Wastes).
        A card *type* is not something a name can be asked — the engine holds
        no catalog — so it is asked of every card this game contains with that
        name: a name borne by a card here that is not of the type is refused,
        and a name borne by no card here matches nothing whatever its type.
        """
        if not named:
            return False
        lowered = named.lower()
        if choice.data.get("exclude_basic_land_names"):
            bare = lowered.removeprefix("snow-covered ").strip()
            if bare in BASIC_LAND_WORDS or lowered == "wastes":
                return True
        from ....faces import castable_faces, is_multi_face
        from ....search_filters import card_has_type

        held_cards = [
            card
            for player in self.players
            for zone in ("library", "hand", "graveyard", "exile")
            for card in getattr(player, zone, ())
        ] + [permanent.card for permanent in self.all_permanents()]
        # CR 201.4b: "If a player wants to choose the name of a split card, the
        # player must choose the name of one of its halves, **but not both**."
        # The joined spelling ("Stand // Deliver") is how a card file and a
        # decklist write the card and is the name of no spell, so recording it
        # would be a choice that silently matches nothing — refused, for the
        # reason every bound here is refused rather than repaired.
        if any(
            is_multi_face(card) and card.name.lower() == lowered
            for card in held_cards
        ):
            return True
        card_type = choice.data.get("card_type")
        # "Choose a **nonland** card name" (Meddling Mage) — the same bound
        # stated as the type the named card must *not* have. CR 201.4a makes
        # both a question about the named card's own characteristics.
        excluded_type = choice.data.get("excluded_card_type")
        if not card_type and not excluded_type:
            return False
        # CR 201.4b again: "use only that half's characteristics" — so each
        # card this game holds is asked as the spells it can be cast as, and
        # the half called *named* is the one whose type line is read.
        borne_by = [
            named_card
            for held in held_cards
            for named_card in castable_faces(held)
            if named_card.name.lower() == lowered
        ]
        if not borne_by:
            return False
        if card_type and not any(
            card_has_type(card, str(card_type)) for card in borne_by
        ):
            return True
        return bool(excluded_type) and all(
            card_has_type(card, str(excluded_type)) for card in borne_by
        )

    def _default_choose_card_name(self, choice: PendingChoice) -> None:
        self._resolve_choose_card_name(choice, choice.data.get("default_name", ""))

    def _default_name_then_reveal_top(self, choice: PendingChoice) -> None:
        if not self._resolve_name_then_reveal_top(
            choice, choice.data.get("default_name", "")
        ):
            self.discard_pending_choice(choice)

    # -- "Choose a card name, then consult your own library" -----------------

    def confirm_name_then_consult(self, player_index: int, card_name: str) -> bool:
        """Answer Demonic Consultation's "choose a card name" prompt."""
        return self.resolve_pending_choice(
            "name_then_consult", player_index, card_name=card_name
        )

    def _resolve_name_then_consult(
        self, choice: PendingChoice, card_name: str
    ) -> bool:
        """Exile the top N, then reveal down to the named card.

        Everything happens **after** the name is fixed, which is the whole
        card: the six exiled cards are never looked at, so the name may be
        among them and the reveal may then run the library out. That is not a
        failure and not a loss — CR 704.5b only fires when a player actually
        attempts to draw from an empty library, so the spell finishes and the
        next draw step is what kills them.

        CR 202.1 lets a player name any card at all and this spell prints no
        restriction, so no name is refused. The comparison is against the
        card's printed name: nothing in a library is a permanent, so nothing
        there can be copying anything (CR 707.2).
        """
        player = self.players[choice.player_index]
        named = (card_name or "").strip()
        exile_count = int(choice.data.get("exile_count", 0) or 0)
        paid = [player.library.pop(0) for _ in range(min(exile_count, len(player.library)))]
        player.exile.extend(paid)
        revealed: list = []
        found = None
        while player.library:
            card = player.library.pop(0)
            revealed.append(card)
            if named and has_name(card, named):
                found = card
                break
        # "…and exile all other cards revealed this way" — everything the
        # reveal turned over except the find, in the order it was turned over.
        for card in revealed:
            if card is found:
                continue
            player.exile.append(card)
        if found is not None:
            # Through the CR 614 seam every "put this card into a hand" uses,
            # so a commander headed for a hand goes to the command zone instead
            # (CR 903.9b).
            self.put_card_into_hand(player, found)
        self.discard_pending_choice(choice)
        self.log.append(
            f"{player.name} named {named or 'nothing'}, exiled {len(paid)} card(s) "
            + (
                f"and revealed down to {found.name}"
                if found is not None
                else f"and revealed their whole library ({len(revealed)} card(s)) without finding it"
            )
        )
        return True

    def _default_name_then_consult(self, choice: PendingChoice) -> None:
        if not self._resolve_name_then_consult(
            choice, choice.data.get("default_name", "")
        ):
            self.discard_pending_choice(choice)

    # -- "Choose a card name, then reveal N at random from a hand" -----------

    def confirm_name_and_random_reveal(self, player_index: int, card_name: str) -> bool:
        """Answer Nebuchadnezzar's "choose a card name" prompt."""
        return self.resolve_pending_choice(
            "name_and_random_reveal", player_index, card_name=card_name
        )

    def _resolve_name_and_random_reveal(
        self, choice: PendingChoice, card_name: str
    ) -> bool:
        """Reveal *count* cards at random from the target's zone, then discard
        every revealed card carrying the named name.

        The reveal happens **here**, after the name is fixed: turning cards over
        while the prompt was open would tell the chooser what to name.

        The randomness is over *indices*, so two copies of one card are two
        chances to be revealed, and it draws from the module RNG the rest of the
        engine seeds — a given seed replays the ability exactly.

        "All cards with that name **revealed this way**" is the whole reason
        this is one step: the discard is over the revealed subset, not over the
        hand, so a fourth copy the reveal missed stays put.
        """
        data = choice.data
        target = self.players[data["target_seat"]]
        zone = getattr(target, data.get("zone", "hand"), [])
        named = (card_name or "").strip()
        count = min(max(0, int(data.get("count", 0))), len(zone))
        # By index, not by card: `random.sample` over the objects would collapse
        # two equal cards into one candidate on any implementation that compares
        # by value, and this engine's CardDefinition is shared between copies.
        revealed_indices = sorted(random.sample(range(len(zone)), count)) if count else []
        revealed = [zone[i] for i in revealed_indices]
        discarded = [card for card in revealed if named and has_name(card, named)]
        for index in reversed(revealed_indices):
            if named and has_name(zone[index], named):
                self.put_card_into_graveyard(target, zone.pop(index))
        self.discard_pending_choice(choice)
        self.log.append(
            f"{target.name} revealed {len(revealed)} card(s) at random from their "
            f"{data.get('zone', 'hand')}"
            + (
                f" and discarded {len(discarded)} named {named}"
                if discarded else f" and discarded nothing named {named or 'nothing'}"
            )
        )
        return True

    def _default_name_and_random_reveal(self, choice: PendingChoice) -> None:
        if not self._resolve_name_and_random_reveal(
            choice, choice.data.get("default_name", "")
        ):
            self.discard_pending_choice(choice)
