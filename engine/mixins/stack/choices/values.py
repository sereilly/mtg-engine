"""A value chosen on resolution or as a permanent enters: a type, a colour, a word.

CR 608.2d's choices, made when the effect needs them: a land type (and the
ordered pair Vision Charm swaps), a card type, a creature type, a colour, the
colour or colours a permanent becomes, the colour a mana ability produces, and
which vocabulary a text change replaces a word from. And the same vocabulary
asked as a permanent enters ("as this enters, choose an opponent [and a
color]"), which is ``enter_choice`` — the prompt ``engine/enter_effects.py``'s
``ENTRY_CHOICES`` table arms.
"""

from __future__ import annotations

from ....grammar.phrases import BASIC_LAND_WORDS
from ....color_changes import change_color
from ....continuous import next_timestamp
from ....land_types import CHOSEN_LAND_TYPES, change_land_type
from ....pending_choices import PendingChoice


def _entry_choice_option_allowed(choice: PendingChoice, answer: str) -> bool:
    """Whether *answer* is one of the options the entering permanent's own
    sentence printed (CR 614.1c).

    "As this enchantment enters, choose **black or red**" (Mangara's Equity),
    "…choose **Island or Swamp**" (Roots of Life). Most entry choices name a
    *catalog* and are bounded by it; these name their options outright, and the
    list travels on the choice so the picker offers exactly what this refuses
    to go outside (idiom 9).

    An arming with no list is unbounded by anything but its catalog, which is
    every other shape of this prompt — so an absent key is a pass rather than a
    refusal, and the six older armings are untouched.

    A free function rather than a method for the reason the two call sites give:
    both branches of ``_resolve_enter_choice`` ask it about the same choice, and
    it needs nothing off the game.
    """
    options = choice.data.get("entry_choice_options")
    if not options:
        return True
    return str(answer).strip().lower() in {
        str(option).strip().lower() for option in options
    }


class ValueChoicesMixin:
    # -- Phantasmal Terrain's land type -------------------------------------

    _BASIC_LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest")

    def land_type_choice_options(self, choice: PendingChoice) -> tuple[str, ...]:
        """The basic land types a pending ``land_type_choice`` may be answered
        with: the list its sentence printed ("becomes **a Plains or an
        Island**", Tundra Kavu), or CR 305.6's five where it printed none
        ("the basic land type of your choice", Jinx; Phantasmal Terrain).

        **One reader**, asked by the resolver that checks the answer, by the
        default a non-interactive seat takes and by the prompt renderer
        (idiom 9) — so the picker cannot show a type the answer path refuses,
        and a seat cannot name one the card does not print. A printed entry
        outside the five is dropped rather than offered: the wire field is the
        five-way basic, and a type nobody can send is not an option.
        """
        printed = tuple(
            word for word in (
                str(option).strip().lower()
                for option in (choice.data.get("options") or ())
            )
            if word in self._BASIC_LAND_TYPES
        )
        return printed or self._BASIC_LAND_TYPES

    def default_land_type_choice(self, choice: PendingChoice) -> str:
        """What a non-interactive seat answers a ``land_type_choice`` with.

        An Island, which is the provisional default the kind has always taken
        — unless the sentence offered a list that does not include one, where
        the first printed type is the answer: the default has to be a type the
        resolver accepts, or the prompt would be discarded unanswered and the
        land left unchanged by an ability that resolved.
        """
        offered = self.land_type_choice_options(choice)
        return "island" if "island" in offered else offered[0]

    def confirm_land_type(self, player_index: int, land_type: str) -> bool:
        """Resolve a pending Phantasmal Terrain choice with the controller's chosen
        basic land type, overriding the provisional default on the enchanted land."""
        return self.resolve_pending_choice("land_type_choice", player_index, land_type=land_type)

    def _resolve_land_type(self, choice: PendingChoice, land_type: str) -> bool:
        """CR 608.2d's choice, made: the land's type is recorded now.

        Two armings reach here. Phantasmal Terrain's names the land by its
        owner's seat and its battlefield slot, and keys the contribution on the
        **Aura**, so the change ends when the Aura does. Jinx's names it by
        ``permanent_id`` and keys the contribution on a duration label, because
        an instant has no permanent for the change to hang on and the cleanup
        step is what ends it. Which land and which source are therefore both
        read off the choice rather than assumed — the Aura's spelling is kept
        exactly as it was so its behaviour does not move.
        """
        land_type = str(land_type or "").strip().lower()
        if land_type not in self.land_type_choice_options(choice):
            return False
        permanent_id = choice.data.get("land_permanent_id")
        if permanent_id is not None:
            # An id, not a slot: anything leaving the battlefield renumbers
            # every later index, and this answer arrives after the handler that
            # armed it has returned (ROADMAP idiom 11). A land that has left
            # resolves to None, which is a fizzle and not a fall back to
            # whichever permanent inherited the slot.
            land = self.permanent_by_id(permanent_id)
        else:
            owner = self.players[choice.data["land_owner_index"]]
            idx = choice.data["land_index"]
            land = (
                owner.battlefield[idx]
                if 0 <= idx < len(owner.battlefield) else None
            )
        if land is not None:
            # Keyed on the Aura, so the change ends when the Aura does — and
            # ends only its own contribution. Jinx passes its own label instead.
            change_land_type(
                land, land_type,
                source=choice.data.get("land_type_source", choice.data.get("_aura")),
                label=choice.data["card_name"],
                ends_with_source=bool(
                    choice.data.get("land_type_ends_with_source")
                ),
            )
            self.log.append(
                f"{choice.data['card_name']}: "
                + (
                    "enchanted land" if permanent_id is None
                    else land.card.name
                )
                + f" becomes a {land_type.title()}"
            )
            # The answer is the effect: until it is given nothing has changed,
            # and once it is, every type-scoped static on the board has a
            # different land to reach or to pass by (CR 613.8a — "All
            # Mountains are Plains" depends on the choice that makes a
            # Mountain). Recomputed by ``_answer_pending_choice``, the seam
            # every answer passes: this one did not for a while, so the land
            # read as its new type and as nothing a static says of that type
            # until some later action happened to refresh it.
        self.discard_pending_choice(choice)
        return True

    # -- Vision Charm's ordered pair of land types ---------------------------

    def confirm_land_type_swap(
        self, player_index: int, from_type: str, to_type: str
    ) -> bool:
        """Answer "choose a land type and a basic land type" with the pair."""
        return self.resolve_pending_choice(
            "land_type_swap", player_index,
            from_type=from_type, to_type=to_type,
        )

    def _resolve_land_type_swap(
        self, choice: PendingChoice, from_type, to_type
    ) -> bool:
        """Make every land of *from_type* a *to_type* until end of turn.

        The swap is performed **here**, by the resolver, rather than by the
        handler that armed the prompt: CR 608.2d puts the choice inside the
        resolution, and the set the sweep reaches is named by the answer. That
        is Jinx's arrangement one land at a time, and it is why this kind does
        not need to suspend anything — there is no later step to hold.

        Each catalog is checked separately and against the one the *sentence*
        named (idiom 9, the same list the prompt offered): "a land type" is all
        of CR 205.3i's and "a basic land type" is the five, and an answer
        outside either is refused rather than repaired.

        CR 611.2c fixes the set now: a land played afterwards is not swapped.
        The contribution is keyed on a fresh label rather than on a permanent,
        because an instant leaves none — the same reason Jinx's does.
        """
        from ....grammar.vocabulary import LAND_TYPES

        first = str(from_type or "").strip().lower()
        second = str(to_type or "").strip().lower()
        first_pool = (
            self._BASIC_LAND_TYPES if choice.data.get("first_basic") else LAND_TYPES
        )
        second_pool = (
            self._BASIC_LAND_TYPES if choice.data.get("second_basic") else LAND_TYPES
        )
        if first not in first_pool or second not in second_pool:
            return False
        source = f"{choice.data.get('duration', 'until_end_of_turn')}:{next_timestamp()}"
        swapped = []
        for land in self.permanents_matching(
            lambda perm: perm.has_type("land") and perm.has_type(first)
        ):
            change_land_type(land, second, source=source, label=choice.data["card_name"])
            swapped.append(land)
        self.log.append(
            f"{choice.data['card_name']}: {len(swapped)} {first}(s) became "
            f"{second}s until end of turn"
        )
        self._recompute_continuous_effects()
        self.discard_pending_choice(choice)
        return True

    # -- Teferi's Realm's card type ------------------------------------------

    def confirm_card_type_choice(self, player_index: int, card_type: str) -> bool:
        """Answer "chooses artifact, creature, land, or non-Aura enchantment"
        with one of the options the card offered."""
        return self.resolve_pending_choice(
            "card_type_choice", player_index, card_type=card_type
        )

    def _resolve_card_type_choice(self, choice: PendingChoice, card_type) -> bool:
        """Record the chosen card type on the ability's source (CR 608.2d).

        **Its own kind rather than a seventh shape of ``enter_choice``**, and
        the difference is not cosmetic: this choice is made when a *triggered
        ability resolves*, not as a permanent enters, and the sentence that
        reads it back is a one-shot sweep in the same resolution. So it has to
        ``suspend`` — an answer that arrived after the sweep had already run on
        the default would change nothing at all, which is a prompt that lies.
        ``enter_choice`` does not suspend and must not start: Hall of Gemstone's
        second sentence is a *continuous* effect that re-reads the record on
        every recompute, so a late answer there really does take effect.

        The answer is bounded by the **printed options**, not by a catalog: the
        card offered four, and a seat that could answer "instant" would name a
        type no permanent has while one that could answer "enchantment" would
        escape the Aura exclusion the card prints. Checked against the same list
        the prompt offered (idiom 9), and refused rather than repaired.
        """
        from ....handlers._common import CHOSEN_CARD_TYPE

        word = str(card_type or "").strip().lower()
        offered = [
            str(option).strip().lower()
            for option in (choice.data.get("options") or ())
        ]
        if word not in offered:
            return False
        permanent = choice.data.get("permanent")
        if permanent is not None and self.is_on_battlefield(permanent):
            permanent.metadata[CHOSEN_CARD_TYPE] = word
            self.log.append(f"{choice.data.get('card_name', '')}: chose {word}")
        # "Choose artifact, creature, or land." (Turnabout.) The **spell**'s
        # reading of the same sentence: there is no permanent to write on, so
        # the word goes into the resolution scratchpad the next step of this
        # same resolution reads — the arrangement ``_resolve_creature_type_
        # choice`` below already has, and for its reason.
        context = choice.data.get("_context")
        result_key = choice.data.get("result_key")
        if context is not None and result_key is not None:
            context.results[result_key] = word
            self.log.append(f"{choice.data.get('card_name', '')}: chose {word}")
        self.discard_pending_choice(choice)
        return True

    # -- "…the creature type of your choice" (CR 608.2d) ---------------------

    def arm_creature_type_choice(
        self, player_index: int, *, card_name: str, result_key: str, context,
        default: str | None, excluded: tuple[str, ...] = (),
    ):
        """Queue "choose a creature type" for the resolving spell's controller.

        The answer goes into the **resolution scratchpad** rather than onto a
        permanent, which is what separates this from ``enter_choice``'s
        creature-type shape: Extinction is a sorcery, so there is no permanent
        for a CR 614.1c entry choice to have been recorded on, and the sentence
        that spends the word is the next step of the same resolution.

        *excluded* is a printed "**other than Wall**" (Unnatural Selection):
        carried on the prompt, which is what the picker's list and the
        resolver's check both read (``creature_type_choice_options``). Absent
        from the prompt data when the card prints none.
        """
        return self.arm_pending_choice(
            "creature_type_choice", player_index,
            card_name=card_name,
            result_key=result_key,
            default_creature_type=default,
            _context=context,
            **({"excluded": list(excluded)} if excluded else {}),
        )

    def creature_type_choice_options(self, choice: PendingChoice) -> frozenset[str]:
        """The creature types a pending ``creature_type_choice`` may be
        answered with: CR 205.3m's catalog, less whatever the sentence printed
        after "other than".

        **One reader** for the resolver and the prompt renderer (idiom 9), so
        the picker cannot offer a word the answer path refuses and a seat
        cannot name one the card forbids.
        """
        from ....grammar.vocabulary import CREATURE_TYPES

        excluded = {
            str(word).strip().lower()
            for word in (choice.data.get("excluded") or ())
        }
        return frozenset(CREATURE_TYPES - excluded) if excluded else CREATURE_TYPES

    def confirm_creature_type_choice(
        self, player_index: int, creature_type: str
    ) -> bool:
        """Answer "the creature type of your choice" with one word."""
        return self.resolve_pending_choice(
            "creature_type_choice", player_index, creature_type=creature_type
        )

    def _resolve_creature_type_choice(
        self, choice: PendingChoice, creature_type
    ) -> bool:
        """Record the chosen creature type for the step behind this one.

        CR 205.3m bounds the answer, checked against the same catalog the picker
        offers (idiom 9) so the two cannot disagree — and refused rather than
        repaired, because quietly keeping the default would tell the player they
        had chosen something they had not.

        An empty answer keeps whatever the handler stamped before arming, which
        is a real choice already recorded rather than none at all.
        """
        word = str(creature_type or "").strip().lower()
        if word:
            if word not in self.creature_type_choice_options(choice):
                return False
            choice.data["_context"].results[choice.data["result_key"]] = word
            self.log.append(f"{choice.data.get('card_name', '')}: chose {word}")
        self.discard_pending_choice(choice)
        return True

    # -- "Choose a color." at resolution (CR 608.2d) -------------------------

    def arm_color_choice(
        self, player_index: int, *, card_name: str, permanent, result_key: str,
        context, default: str, colors=None,
    ):
        """Queue "choose a color" for the seat the resolving ability names.

        **Its own kind rather than a seventh shape of ``enter_choice``**, and
        for ``_resolve_card_type_choice``'s reason one characteristic over: this
        choice is made while a spell or ability *resolves*, not as a permanent
        enters, so a sentence later in the same resolution may be what reads it
        back — and that sentence cannot run before the answer arrives. So the
        kind ``suspends``, where ``enter_choice`` does not and must not: the
        readers it serves are continuous effects that re-read the record on
        every recompute, and a late answer there really does take effect.

        The answer goes to **both** records. ``chosen_color`` on the permanent
        is the standing one — the colour Chromatic Armor's shield and Hall of
        Gemstone's mana swap keep asking about for as long as they last — and
        the scratchpad key is what a later step of *this* resolution reads. Two
        writers would be a permanent with two chosen colours; one writer with
        two records is one answer in the two places its two kinds of reader
        look.

        *colors* is the list the sentence narrows the choice to ("a color **of
        a permanent you control**", Meteor Crater), or None for CR 105.1's
        five. Carried on the prompt so the picker offers exactly what the
        resolver will accept, and the resolver refuses anything else.
        """
        return self.arm_pending_choice(
            "color_choice", player_index,
            card_name=card_name,
            permanent=permanent,
            result_key=result_key,
            default_color=default,
            colors=list(colors) if colors else None,
            _context=context,
        )

    def confirm_color_choice(self, player_index: int, mana_color: str) -> bool:
        """Answer "choose a color" with one colour word or symbol."""
        return self.resolve_pending_choice(
            "color_choice", player_index, mana_color=mana_color
        )

    def _resolve_color_choice(self, choice: PendingChoice, mana_color) -> bool:
        """Record the chosen colour for the readers behind this step.

        CR 105.1 bounds the answer to the five colours, checked through the same
        normaliser the picker's option list comes from (idiom 9), and refused
        rather than repaired — quietly keeping the default would tell the player
        they had chosen something they had not.

        An empty answer keeps whatever the handler stamped before arming, which
        is a real choice already recorded rather than none at all.
        """
        word = mana_color
        if word is not None and str(word).strip():
            try:
                symbol = self._normalize_mana_color(word)
            except ValueError:
                return False
            if not symbol:
                return False
            offered = choice.data.get("colors")
            if offered and symbol not in offered:
                # A colour the sentence does not offer (Meteor Crater's "of a
                # permanent you control") is refused for the reason a
                # non-colour is: the prompt stays owed rather than quietly
                # taking the default.
                return False
            permanent = choice.data.get("permanent")
            if permanent is not None and self.is_on_battlefield(permanent):
                permanent.metadata["chosen_color"] = symbol
            context = choice.data.get("_context")
            result_key = choice.data.get("result_key")
            if context is not None and result_key is not None:
                context.results[str(result_key)] = symbol
            self.log.append(f"{choice.data.get('card_name', '')}: chose {symbol}")
            # A chosen colour can condition a static (Jihad's anthem), and the
            # board was last computed against the default — the same recompute
            # ``_resolve_enter_choice`` makes for its own colour branch.
            self._recalculate_lord_buffs()
        self.discard_pending_choice(choice)
        return True

    # -- "As this enters, choose an opponent [and a color]" -------------------

    def confirm_enter_choice(
        self, player_index: int, opponent_index: int | None = None,
        mana_color: str | None = None, card_name: str | None = None,
        land_types: "tuple[str, str] | list[str] | None" = None,
        creature_type: str | None = None,
        land_type: str | None = None,
    ) -> bool:
        """Resolve a pending "as this enters, choose an opponent [and a color]"
        prompt (Black Vise / Jihad), overwriting the provisional defaults
        stamped on the permanent at ETB."""
        return self.resolve_pending_choice(
            "enter_choice", player_index, opponent_index=opponent_index,
            mana_color=mana_color, card_name=card_name, land_types=land_types,
            creature_type=creature_type, land_type=land_type,
        )

    def _resolve_enter_choice(
        self, choice: PendingChoice, opponent_index: int | None = None,
        mana_color: str | None = None, card_name: str | None = None,
        land_types: "tuple[str, str] | list[str] | None" = None,
        creature_type: str | None = None,
        land_type: str | None = None,
    ) -> bool:
        player_index = choice.player_index
        # "…choose **a creature type**." (An-Zerrin Ruins.) A fifth shape of
        # this one prompt and the fourth that names no seat, so it answers and
        # returns rather than falling through to the opponent check.
        #
        # CR 205.3m: the answer must be a creature type — checked against the
        # same catalog the picker offers, so the two cannot disagree (idiom 9)
        # — and anything else is refused rather than repaired, because quietly
        # keeping the default would tell the player they had chosen something
        # they had not. An empty answer keeps the default, which is a choice
        # already recorded rather than none at all.
        # "…choose **a land type**." (Shimmer.) The sixth shape of this one
        # prompt and the fifth that names no seat, so it answers and returns
        # like the creature type below it.
        #
        # CR 205.3i: the answer must be a land type — and the *whole* catalog,
        # not the five basics: Shimmer may name Desert. Checked against the
        # same vocabulary the picker offers, so the two cannot disagree
        # (idiom 9), and anything else is refused rather than repaired. The
        # static beside the choice reads the record, so the board is
        # recomputed once it changes.
        if choice.data.get("needs_land_type"):
            from ....grammar.vocabulary import LAND_TYPES

            permanent = choice.data["permanent"]
            if land_type:
                word = str(land_type).strip().lower()
                # "…choose **Island or Swamp**." (Roots of Life.) The sentence
                # printed the offer, so the catalog is not what bounds the
                # answer — the two words are. Asked of the same list the picker
                # was handed (idiom 9), and refused rather than repaired: a
                # third land type here is a strictly better card.
                if not _entry_choice_option_allowed(choice, word):
                    return False
                if word not in LAND_TYPES:
                    return False
                if self.is_on_battlefield(permanent):
                    permanent.metadata["chosen_land_type"] = word
                    self.log.append(
                        f"{choice.data['card_name']}: chose {word}"
                    )
                    self._recalculate_lord_buffs()
            self.discard_pending_choice(choice)
            return True
        if choice.data.get("needs_creature_type"):
            from ....grammar.vocabulary import CREATURE_TYPES

            permanent = choice.data["permanent"]
            # "…choose **a color and a creature type**." (Volrath's Laboratory.)
            # One prompt with two answers, the shape the opponent-and-colour
            # branch at the bottom already has — so the colour is validated
            # *before* anything is written, and a bad word refuses the whole
            # answer rather than leaving the permanent holding one new choice
            # and one default.
            wants_color = bool(choice.data.get("needs_color"))
            color = None
            if wants_color:
                try:
                    color = self._normalize_mana_color(mana_color)
                except ValueError:
                    return False
            word = None
            if creature_type:
                word = str(creature_type).strip().lower()
                if word not in CREATURE_TYPES:
                    return False
            if self.is_on_battlefield(permanent):
                chose: list[str] = []
                if word is not None:
                    permanent.metadata["chosen_creature_type"] = word
                    chose.append(word)
                if color is not None:
                    permanent.metadata["chosen_color"] = color
                    chose.append(color)
                if chose:
                    self.log.append(
                        f"{choice.data['card_name']}: chose {' and '.join(chose)}"
                    )
                if color is not None:
                    # A chosen colour can condition a static (Jihad's anthem),
                    # and the board was last computed against the default.
                    self._recalculate_lord_buffs()
                # …and a chosen creature type *is* a static's effect
                # ("Creatures you control are the chosen type", Conspiracy) —
                # CR 613 layer 4, where which permanents every other
                # type-scoped static reaches was last decided against the
                # default. Dralnu's Crusade's "All Goblins" did not include the
                # Goblins this answer had just made until some later action
                # happened to recompute the board; and a lord's "Elf creatures
                # get +1/+1" reads the same types one layer up. It is
                # recomputed by ``_answer_pending_choice``, after every answer
                # and not just the ones that remembered to.
            self.discard_pending_choice(choice)
            return True
        # "…choose **two basic land types**." (Illusionary Terrain.) A fourth
        # shape of this one prompt, and the third that names no seat — so it
        # answers and returns like the two below rather than falling through to
        # the opponent check. The pair is **ordered**: the static reads "the
        # first chosen type" and "the second chosen type", so a reversed answer
        # is a different, legal choice and not a normalization to apply.
        #
        # An answer naming anything but two distinct basic land types is
        # refused rather than repaired: quietly keeping the default would tell
        # the player they had chosen something they had not.
        if choice.data.get("needs_land_types"):
            permanent = choice.data["permanent"]
            if land_types is not None:
                pair = tuple(str(word).strip().lower() for word in land_types)
                if len(pair) != 2 or pair[0] == pair[1]:
                    return False
                if any(word not in BASIC_LAND_WORDS for word in pair):
                    return False
                if self.is_on_battlefield(permanent):
                    permanent.metadata[CHOSEN_LAND_TYPES] = pair
                    self.log.append(
                        f"{choice.data['card_name']}: chose {pair[0]} and {pair[1]}"
                    )
                    self._refresh_dynamic_creatures()
            self.discard_pending_choice(choice)
            return True
        # "…choose a card name" (Runed Halo). A different question from the
        # opponent-and-colour one this prompt was written for, so it answers and
        # returns rather than falling through the seat check below — there is no
        # seat in this choice at all.
        #
        # Any name is legal: CR 202.1 lets a player name any card, and the
        # choice is not bounded by what is on a board. An empty answer keeps the
        # default rather than naming nothing, which would make the protection
        # apply to nothing.
        # …and only when no seat is asked for beside it. "As this artifact
        # enters, choose an opponent **and** a card name" (Booby Trap) is one
        # prompt with two answers, so it falls through to the opponent branch at
        # the bottom, which writes both — the same early-return rule the colour
        # branch below follows, and for its reason: this prompt asks one
        # question in several shapes and only some of them name a seat.
        #
        # ``.get``, and it is not style: Runed Halo's arming passes
        # ``needs_card_name`` and no ``opponents`` key at all, so the subscript
        # this used to be raised ``KeyError`` on the one shape the branch
        # exists for — an interactive seat could be *shown* Runed Halo's prompt
        # and could not answer it. The renderer was fixed for the same missing
        # keys a set earlier; the answer path was not.
        if choice.data.get("needs_card_name") and not choice.data.get("opponents"):
            from ....cast_restrictions import CHOSEN_CARD_NAMES

            permanent = choice.data["permanent"]
            # "…**you and an opponent each** choose a card name other than a
            # basic land card name." (Null Chamber.) Two seats answering into
            # one record, so the slot says whose answer this is — read as a set
            # by the ban, but written by index, because a prompt answering into
            # the wrong slot would swap the two players' choices.
            slot = choice.data.get("card_name_slot")
            if slot is not None:
                # ``BASIC_LAND_WORDS`` is the module-level import. A local one
                # here would shadow it for the *whole* function — Python binds
                # a name by function, not by block — and Illusionary Terrain's
                # branch above would raise reading it before this line ran.
                if card_name:
                    # The one restriction the sentence prints. CR 201.2 leaves
                    # the choice otherwise unbounded, so a name off the offered
                    # list is legal — this is the only answer that is not, and
                    # it is refused rather than repaired: quietly keeping the
                    # default would tell the player they had chosen something
                    # they had not.
                    if str(card_name).strip().lower() in BASIC_LAND_WORDS:
                        return False
                    names = list(
                        permanent.metadata.get(CHOSEN_CARD_NAMES) or ["", ""]
                    )
                    while len(names) <= int(slot):
                        names.append("")
                    names[int(slot)] = card_name
                    permanent.metadata[CHOSEN_CARD_NAMES] = names
                self.discard_pending_choice(choice)
                self.log.append(
                    f"{self.players[player_index].name} named "
                    f"{card_name or 'nothing'} for {choice.data['card_name']}"
                )
                return True
            # "…choose a **nonland** card name." (Meddling Mage.) CR 201.4a's
            # bound, through the one reader the spell-side "choose a card name"
            # prompt already refuses with — so the two prompts cannot come to
            # disagree about what a printed bound admits. Refused rather than
            # repaired, for the reason the slot branch above gives.
            if card_name and self._named_card_breaks_printed_bound(
                choice, str(card_name).strip()
            ):
                return False
            if card_name:
                permanent.metadata["chosen_card_name"] = card_name
            self.discard_pending_choice(choice)
            self.log.append(
                f"{self.players[player_index].name} named "
                f"{permanent.metadata.get('chosen_card_name') or 'nothing'}"
            )
            return True
        # "…choose a color." (Psychic Allergy.) A colour and no player, so
        # there is no seat to validate — the same early return the card-name
        # branch above takes, and for the same reason: this prompt asks one
        # question of three different shapes and only two of them name a seat.
        if choice.data["needs_color"] and not choice.data["opponents"]:
            permanent = choice.data["permanent"]
            try:
                color = self._normalize_mana_color(mana_color)
            except ValueError:
                return False
            # "…choose **black or red**." (Mangara's Equity.) The land-type
            # branch's rule one characteristic over: where the sentence printed
            # the offer, the five colours are not what bounds the answer.
            if color is not None and not _entry_choice_option_allowed(choice, color):
                return False
            if color is not None and self.is_on_battlefield(permanent):
                permanent.metadata["chosen_color"] = color
                self.log.append(f"{choice.data['card_name']}: chose {color}")
                self._recalculate_lord_buffs()
            self.discard_pending_choice(choice)
            self.check_state_based_actions()
            return True
        if opponent_index not in choice.data["opponents"]:
            return False
        permanent = choice.data["permanent"]
        color = None
        if choice.data["needs_color"]:
            try:
                color = self._normalize_mana_color(mana_color)
            except ValueError:
                return False
            if color is None:
                return False
        # "…and a card name **other than a basic land card name**." (Booby
        # Trap.) The one restriction the sentence prints on CR 201.2's otherwise
        # unbounded choice, refused rather than repaired for the reason the
        # card-name branch above gives: quietly keeping the default would tell
        # the player they had chosen something they had not. An empty answer
        # keeps the default, which is a choice already recorded.
        if choice.data.get("needs_card_name") and card_name:
            if str(card_name).strip().lower() in BASIC_LAND_WORDS:
                return False
        # The permanent may already be gone (e.g. destroyed at instant speed);
        # the choice then has nothing to apply to, but the prompt still clears.
        if self.is_on_battlefield(permanent):
            permanent.metadata["chosen_player_index"] = opponent_index
            chose = f"{self.players[player_index].name} chose {self.players[opponent_index].name}"
            if color is not None:
                permanent.metadata["chosen_color"] = color
                chose += f" and {color}"
            if choice.data.get("needs_card_name") and card_name:
                permanent.metadata["chosen_card_name"] = card_name
                chose += f" and {card_name}"
            self.log.append(f"{choice.data['card_name']}: {chose}")
            if color is not None:
                # Jihad's anthem is conditioned on the chosen color/player.
                self._recalculate_lord_buffs()
            # "…equal to 1 plus the number of creatures **the chosen player**
            # controls." (Lost Order of Jarkeld.) A characteristic-defining P/T
            # counting a board the answer just named, so the answer has to be
            # what it counts: the default stamped at entry was a different seat,
            # and the refresh that ran then measured that one. The land-types
            # branch above already recomputes for the same reason.
            self._refresh_dynamic_creatures()
        self.discard_pending_choice(choice)
        self.check_state_based_actions()
        return True

    # -- Which vocabulary a text change replaces a word from -----------------

    def live_text_change_vocabularies(self, permanent, old_symbol: str) -> list[str]:
        """The vocabularies whose printed word is actually on *permanent*.

        A text change that rewrites a word the permanent does not have is a
        legal choice (CR 612.1 puts no such condition on it) and changes
        nothing, so offering it would be a question one of whose answers is
        "do nothing" — the shortcut every other picker here takes when a choice
        has one real answer. The *written* text, not the printed card: a second
        text change rewrites what the first wrote.
        """
        # `text_changes`' own tables, both keyed by mana **symbol**. The
        # grammar's `COLOR_WORDS` is the same pairs the other way round (word →
        # symbol) and reading it here would look up "U" and find nothing, which
        # is a vocabulary silently never offered.
        from ....text_changes import COLOR_WORDS, LAND_TYPE_WORDS

        symbol = (old_symbol or "").upper()
        effective = permanent.effective_card
        written = " ".join(
            (effective.type_line, effective.oracle_text, *effective.keywords)
        ).lower()
        found = []
        colour = COLOR_WORDS.get(symbol)
        if colour and colour in written:
            found.append("color_word")
        land = LAND_TYPE_WORDS.get(symbol)
        if land and land in written:
            found.append("land_type")
        return found

    def arm_text_change_vocabulary(
        self, player_index: int, permanent, old_symbol: str, new_symbol: str,
        card_name: str, duration: str | None = None,
    ) -> None:
        """Queue "a colour word, or a basic land type?" for Mind Bend.

        One vocabulary that could do anything is not a decision, and none at all
        is not a prompt: the swap is performed straight away in the first case
        and nothing happens in the second, exactly as the pile choice one file
        over decides whether to ask at all.
        """
        live = self.live_text_change_vocabularies(permanent, old_symbol)
        if not live:
            self.log.append(
                f"{card_name} had no effect: {permanent.card.name} has no such "
                "word in its text"
            )
            return
        if len(live) == 1:
            self._apply_text_change_vocabulary(
                permanent, live[0], old_symbol, new_symbol, card_name,
                duration=duration,
            )
            return
        self.arm_pending_choice(
            "text_change_vocabulary", player_index,
            card_name=card_name,
            permanent_name=permanent.card.name,
            options=list(live),
            old_symbol=(old_symbol or "").upper(),
            new_symbol=(new_symbol or "").upper(),
            # Absent for the three cards that print no duration, so their
            # prompt data is byte-identical to what it was. "Until end of turn"
            # is a property of the *effect being created*, so it has to survive
            # the decision the seat still owes -- a duration read at the
            # resolution and dropped at the prompt would be a Whim of Volrath
            # that lasts forever whenever its target had both words.
            **({"duration": duration} if duration else {}),
            _permanent=permanent,
        )

    def _apply_text_change_vocabulary(
        self, permanent, mode: str, old_symbol: str, new_symbol: str,
        card_name: str, duration: str | None = None,
    ) -> None:
        """Perform the swap the seat named, through the same two writers the
        single-vocabulary cards use — a third copy here would be a third answer
        to what a text change records."""
        from ....text_changes import (LAND_TYPE_WORDS, change_color_word,
                                     change_land_word)

        if mode == "color_word":
            if change_color_word(
                permanent, old_symbol, new_symbol, label=card_name,
                duration=duration,
            ):
                self.log.append(
                    f"{card_name} changed {old_symbol} text to {new_symbol} on "
                    f"{permanent.card.name}"
                )
            return
        old_type = LAND_TYPE_WORDS.get((old_symbol or "").upper())
        new_type = LAND_TYPE_WORDS.get((new_symbol or "").upper())
        if old_type and new_type and change_land_word(
            permanent, old_type, new_type, label=card_name, duration=duration,
        ):
            self.log.append(
                f"{card_name} changed {old_type} to {new_type} in "
                f"{permanent.card.name}'s text"
            )
            # A land word inside a lord's grant line ("Other Goblins have
            # mountainwalk") is part of a buff the board caches, so the swap has
            # to be re-derived — the same call the single-vocabulary handler
            # makes for the same reason.
            self._recalculate_lord_buffs()

    def confirm_text_change_vocabulary(self, player_index: int, mode) -> bool:
        return self.resolve_pending_choice(
            "text_change_vocabulary", player_index, mode=mode
        )

    def _resolve_text_change_vocabulary(self, choice: PendingChoice, mode) -> bool:
        permanent = choice.data.get("_permanent")
        if mode not in (choice.data.get("options") or ()):
            return False
        if permanent is None or not self.is_on_battlefield(permanent):
            # It left while the prompt was owed (CR 608.2b): nothing to rewrite,
            # and the decision is over either way.
            self.discard_pending_choice(choice)
            return True
        self.discard_pending_choice(choice)
        self._apply_text_change_vocabulary(
            permanent, str(mode), str(choice.data.get("old_symbol") or ""),
            str(choice.data.get("new_symbol") or ""),
            str(choice.data.get("card_name") or ""),
            duration=choice.data.get("duration"),
        )
        return True

    def _default_text_change_vocabulary(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** offered vocabulary, which is the
        colour word.

        Not a valuation — the order is the one
        ``live_text_change_vocabularies`` builds and is seed-deterministic. A
        seat that should weigh a type-line rewrite against a colour one needs a
        weight in ``engine/ai_valuation.py``, not a branch here.
        """
        options = list(choice.data.get("options") or ())
        if not options or not self._resolve_text_change_vocabulary(
            choice, options[0]
        ):
            self.discard_pending_choice(choice)

    # -- Becoming the colour or colours of your choice (Shyft) --------------

    def arm_color_set_choice(
        self, player_index: int, *, permanent, card_name: str, several: bool
    ) -> None:
        """Ask *player_index* which colour or colours *permanent* becomes.

        CR 608.2d puts the choice in the resolution — not as a trigger goes on
        the stack, and not with an activation either, which CR 602.2b does not
        announce a colour with — so the question is put here, on the standing
        queue, by every subject the phrase is printed on: Shyft's trigger, Dream
        Coat's host, Prismatic Lace's target.

        A deterministic default is stamped before the prompt, the discipline
        every entry choice follows: the colour the *opponents* hold least of
        among nontoken permanents, which is the choice a player makes with this
        card — a creature that shares a colour with the board is the one every
        colour-hoser reaches. The same reasoning ``_default_terrain_land_types``
        writes down, one card over.
        """
        colors = ["W", "U", "B", "R", "G"]
        default = self._least_common_opponent_color(player_index)
        self.arm_pending_choice(
            "color_set_choice", player_index,
            card_name=card_name,
            permanent=permanent,
            several=bool(several),
            colors=colors,
            default_colors=[default],
        )

    def _least_common_opponent_color(self, seat: int) -> str:
        """The colour *seat*'s opponents control fewest of, among nontoken
        permanents. Ties break on the printed WUBRG order, so a seeded run
        reproduces."""
        counts = {color: 0 for color in ("W", "U", "B", "R", "G")}
        for other, player in enumerate(self.players):
            if other == seat or player.lost:
                continue
            for perm in self.controlled_by(other):
                if perm.metadata.get("is_token"):
                    continue
                for color in self._effective_colors(perm):
                    if color in counts:
                        counts[color] += 1
        order = list(counts)
        return min(order, key=lambda color: (counts[color], order.index(color)))

    # -- Which colour a mana ability produces (CR 608.2d) ------------------

    def confirm_mana_color_choice(self, player_index: int, color) -> bool:
        """Answer "add N mana of any one color"."""
        return self.resolve_pending_choice(
            "mana_color_choice", player_index, color=color
        )

    def _mana_color_offered(self, choice: PendingChoice) -> list[str]:
        """The colours this clause narrowed the choice to (CR 608.2d).

        Read off the arming rather than recomputed: "any color that a land an
        opponent controls could produce" was answered when the ability began
        resolving, and a board that changed under a queued prompt would offer a
        colour the card never had.
        """
        return [str(c).upper() for c in (choice.data.get("colors") or ())]

    def _resolve_mana_color_choice(self, choice: PendingChoice, color) -> bool:
        """Put the chosen colour's mana in the pool, and note it was added.

        Refused rather than clamped when the answer is outside the offered set:
        the picker was given that list, so an answer outside it is a stale or
        invented one and taking the nearest colour would put mana the card
        cannot make into somebody's pool (idiom 9).
        """
        offered = self._mana_color_offered(choice)
        try:
            symbol = self._normalize_mana_color(color)
        except ValueError:
            return False
        if not symbol or (offered and symbol not in offered):
            return False
        self.discard_pending_choice(choice)
        self._pay_out_chosen_mana(choice, symbol)
        return True

    def _default_mana_color_choice(self, choice: PendingChoice) -> None:
        """The colour the resolution would have taken with nobody to ask.

        Deliberately *not* a valuation: it is the same answer
        ``add_mana_from_text`` reached before this prompt existed, so a seeded
        AI run and a headless resolution produce exactly the mana they always
        did. A seat that should choose better wants a weight in
        ``engine/ai_valuation.py``, not a branch here.
        """
        self.discard_pending_choice(choice)
        self._pay_out_chosen_mana(choice, str(choice.data.get("default_color") or "G"))

    def _pay_out_chosen_mana(self, choice: PendingChoice, symbol: str) -> None:
        """The half both answers share: the mana, the log line and the note.

        One method because the record is the thing that must not drift — Carpet
        of Flowers' second trigger reads it, and a default that added mana
        without writing it down would let the enchantment fire twice in a turn.

        **The restriction is the second thing that must not drift** (CR 106.6).
        "Add X mana of any one color … spend this mana only to cast creature
        spells" (Food Chain) reaches this method whenever the colour was not
        already named, so a bucket decided in the producer and forgotten here
        would mean the restriction applied to a headless seat and not to a human
        one — the same mana, spendable on anything, depending only on who was
        asked.
        """
        from ....mana_ability_records import note_mana_added
        from ....restricted_mana import mana_bucket

        player = self.players[choice.player_index]
        amount = int(choice.data.get("amount", 0) or 0)
        spend_only = choice.data.get("spend_only")
        if amount > 0:
            bucket = mana_bucket(player, spend_only)
            bucket[symbol] = bucket.get(symbol, 0) + amount
            note_mana_added(
                self, choice.data.get("source"), str(choice.data.get("record") or "")
            )
        note = str(choice.data.get("note") or "")
        restricted = f" (spendable only on {spend_only})" if spend_only else ""
        self.log.append(
            f"{choice.data.get('card_name', 'An ability')} produced "
            f"{amount} {symbol} mana{note}{restricted}"
        )

    def confirm_color_set_choice(self, player_index: int, colors) -> bool:
        """Answer "become the color or colors of your choice"."""
        return self.resolve_pending_choice(
            "color_set_choice", player_index, colors=colors
        )

    def _resolve_color_set_choice(self, choice: PendingChoice, colors) -> bool:
        """Write the chosen set as this permanent's colour (CR 613 layer 5).

        Refused rather than silently narrowed when the card offered one colour
        and the answer names several — "the color of your choice" is one, and a
        prompt that took two would be a card nobody printed.
        """
        data = choice.data
        wanted = list(colors) if isinstance(colors, (list, tuple)) else [colors]
        symbols = []
        for entry in wanted:
            try:
                symbol = self._normalize_mana_color(entry)
            except ValueError:
                return False
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        if not symbols:
            return False
        if len(symbols) > 1 and not data.get("several"):
            return False
        permanent = data["permanent"]
        self.discard_pending_choice(choice)
        if not self.is_on_battlefield(permanent):
            # It left while the prompt was owed; there is nothing to recolour
            # and the prompt still clears.
            return True
        # A tuple whenever the card offered a set, so layer 5 writes every
        # colour rather than the first — the shape `collect_color_effects`
        # already reads, and a bare symbol otherwise. Stamped now, as the
        # answer is given: the effect begins when the colour is known
        # (CR 613.7b), not when the prompt was armed.
        change_color(
            permanent, tuple(symbols) if data.get("several") else symbols[0]
        )
        self._recalculate_lord_buffs()
        self.log.append(
            f"{permanent.card.name} became {'/'.join(symbols)} "
            f"({data.get('card_name', '')})"
        )
        return True

    def _default_color_set_choice(self, choice: PendingChoice) -> None:
        self._resolve_color_set_choice(choice, choice.data.get("default_colors") or [])
