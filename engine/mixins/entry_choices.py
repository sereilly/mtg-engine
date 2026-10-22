"""What an entering permanent chooses, and what a seat nobody asks chooses.

"As this enters, choose ..." is part of the permanent arriving (CR 614.1c,
CR 614.12), and ``PermanentStateMixin._perform_entry_state`` is where each
such choice is armed or made. This mixin holds the two things that are not
one line of it:

* the entry choices whose answer does more than record a value - "your
  choice of" bodies (Primal Clay, ``_apply_chosen_body``), "as this creature
  enters, exile X cards from your graveyard" with its counters, and the most
  life "the amount you pay can't be more than ..." allows (Nameless Race);
* the **defaults**: the colour, creature type, card name, land type or
  printed option a seat takes when nobody asks it (an AI seat, a headless
  run). Each is a stated policy (idiom 8) - usually what the seat's
  opponents have most of, because a choice that reaches nothing is legal
  and pointless - never the first word of a catalog.

``_default_cast_creature_type`` is the one default asked at a cast (CR
601.2b) rather than an entry. It is here because it reads the same
creature-type counts the entry default does.
"""

from __future__ import annotations

from ..entry_choices import CHOSEN_COLOR_KEY
from ..keywords import grant_keyword
from ..models import Permanent, PlayerState
from ..pt import add_pt_counters, pt_counter_deltas, set_base_pt
from ..static_bonuses import BASIC_LAND_WORDS


class EntryChoicesMixin:
    def _apply_chosen_body(self, permanent: Permanent, body: dict) -> None:
        """Set a "your choice of" creature's P/T, granted keyword and subtypes.

        Base P/T through engine/pt.py and the keyword through the layer-6
        grant API, so the body is the object's characteristics rather than a
        rewritten card — the mistake Animate Artifact used to make.

        **The size is a copiable value, not a layer-7b effect with a place in
        the timestamp order.** CR 613.2a: "'As … enters' … abilities generate
        copiable effects if they set power and toughness" — layer 1, where
        every later layer starts (CR 613.2c). So it is written at
        ``layer_bridge.COPIABLE_VALUE``, ahead of every effect the clock has
        stamped: a Primal Clay that chose 3/3 is 1/1 under a Humility that was
        there first, where a write stamped "now" would have beaten it.

        The **subtypes** are neither: they are layer 4, and layer 4 is derived
        on every recompute rather than written. So the chosen body is recorded
        and `collect_type_effects` reads it — which is also what makes replacing
        one body with another free, since the previous body's types were never
        stored anywhere to undo.
        """
        from ..keywords import grant_keyword, remove_keyword

        for option in permanent.metadata.get("body_options") or ():
            if option.get("keyword"):
                remove_keyword(permanent, option["keyword"])
        from ..layer_bridge import COPIABLE_VALUE

        set_base_pt(
            permanent, int(body["power"]), int(body["toughness"]),
            timestamp=COPIABLE_VALUE,
        )
        if body.get("keyword"):
            grant_keyword(permanent, body["keyword"])
        permanent.metadata["chosen_body"] = dict(body)
        self._recompute_continuous_effects()

    def confirm_enter_body_choice(self, player_index: int, option_index: int) -> bool:
        """Answer a pending "your choice of <body>" prompt."""
        return self.resolve_pending_choice("body_choice", player_index, option_index=option_index)

    def _resolve_body_choice(self, choice, option_index: int) -> bool:
        options = choice.data["options"]
        if not (0 <= option_index < len(options)):
            return False
        permanent = choice.data["permanent"]
        chosen = options[option_index]
        self._apply_chosen_body(permanent, chosen)
        self.log.append(
            f"{permanent.card.name} entered as a "
            f"{chosen['power']}/{chosen['toughness']}"
            + (f" with {chosen['keyword']}" if chosen["keyword"] else "")
        )
        self.discard_pending_choice(choice)
        return True

    # -- "As this creature enters, exile X <cards> from your graveyard" -------

    def _entry_exile_candidates(self, choice) -> list[int]:
        """Graveyard positions the printed noun phrase admits, oldest first.

        The picker's hint and the answer's re-check are this one list (idiom 9):
        a client offering the whole graveyard would otherwise turn "X creature
        cards" into "X cards".
        """
        from ..handlers._filters import _card_matches_filter

        described = dict(choice.data.get("filter") or {})
        graveyard = self.players[choice.player_index].graveyard
        return [
            index
            for index, card in enumerate(graveyard)
            if _card_matches_filter(card, described)
        ]

    def _resolve_entry_exile(self, choice, picks) -> bool:
        """Exile the chosen cards and place the counter each one buys.

        Every pick is validated before anything moves - a single bad entry
        rejects the whole answer and leaves the prompt queued, so a malformed
        request cannot exile half a payment and leave the creature the wrong
        size. The count is exact rather than "up to": the card says *X* cards,
        and a short answer is the case the CR 614 interceptor already refused
        the entry for.
        """
        player = self.players[choice.player_index]
        permanent = choice.data.get("_entering_permanent") or choice.data.get("permanent")
        wanted = int(choice.data.get("count", 0))
        offered = tuple(choice.data.get("counters") or ())
        legal = set(self._entry_exile_candidates(choice))
        if not isinstance(picks, list) or len(picks) != wanted:
            return False
        chosen: list[tuple[int, str | None]] = []
        seen: set[int] = set()
        for pick in picks:
            index = pick.get("index") if isinstance(pick, dict) else None
            counter = pick.get("counter") if isinstance(pick, dict) else None
            if not isinstance(index, int) or index not in legal or index in seen:
                return False
            seen.add(index)
            if offered:
                if counter not in offered:
                    return False
            elif counter is not None:
                return False
            chosen.append((index, counter))
        # Idiom 11: in a graveyard two copies of one card are literally one
        # object, so the answer's indices are turned into removals highest-first
        # rather than resolved by value - popping in that order is the only
        # walk under which no earlier removal renumbers a later pick.
        exiled: list[tuple[object, str | None]] = []
        for index, counter in sorted(chosen, key=lambda pick: -pick[0]):
            card = player.graveyard.pop(index)
            player.exile.append(card)
            exiled.append((card, counter))
        for _card, counter in exiled:
            if counter is None or permanent is None:
                continue
            if counter == "+1/+1":
                # Through the seam: entering with counters is a counter
                # placement like any other, so a Conclave Mentor raises it
                # (CR 614.1c's replacement applies as the permanent enters).
                self.place_plus1_counters(permanent, 1)
            else:
                add_pt_counters(permanent, counter)
        self.log.append(
            f"{player.name} exiled "
            + (", ".join(card.name for card, _ in exiled) if exiled else "nothing")
            + f" for {choice.data.get('card_name', 'an entering permanent')}"
        )
        self.discard_pending_choice(choice)
        self._recompute_continuous_effects()
        return True

    def _default_entry_exile(self, choice) -> None:
        """The stated policy for a seat nobody asks (idiom 8).

        **Which cards**: the cheapest matching cards first, ties by graveyard
        order. The exile is a cost with no upside of its own - each card bought
        exactly one counter whichever card it was - so the only question is what
        the graveyard loses, and mana value is the engine's own measure of that.

        **Which counter**: the offered kind that raises both halves furthest
        (``min(power, toughness)``, then the total, then printed order). For the
        three this card prints that is ``+1/+1``: ``+2/+0`` leaves a creature
        that dies to any ping it trades with and ``+0/+2`` leaves one that never
        kills anything, and the balanced counter is the only one that both
        survives and threatens.
        """
        player = self.players[choice.player_index]
        wanted = int(choice.data.get("count", 0))
        offered = tuple(choice.data.get("counters") or ())
        candidates = sorted(
            self._entry_exile_candidates(choice),
            key=lambda index: (player.graveyard[index].cmc or 0, index),
        )[:wanted]
        counter = None
        if offered:
            counter = max(
                offered,
                key=lambda kind: (
                    min(pt_counter_deltas(kind)),
                    sum(pt_counter_deltas(kind)),
                    -offered.index(kind),
                ),
            )
        picks = [{"index": index, "counter": counter} for index in sorted(candidates)]
        if not self._resolve_entry_exile(choice, picks):
            # The graveyard cannot have shrunk between the interceptor's count
            # and this arm, so a rejection here is a bug and not a board state.
            # Dropping the prompt rather than leaving it queued keeps a
            # headless seat from stalling on it forever.
            self.discard_pending_choice(choice)

    def _dominant_nontoken_color(self, player: PlayerState) -> str:
        """The color *player* controls most of among nontoken permanents — the
        deterministic default for Jihad's "choose a color" (a color the chosen
        opponent actually controls keeps the enchantment alive)."""
        counts: dict[str, int] = {}
        for perm in self.controlled_by(player):
            if perm.metadata.get("is_token"):
                continue
            for color in self._effective_colors(perm):
                counts[color] = counts.get(color, 0) + 1
        if not counts:
            return "W"
        return max(sorted(counts), key=lambda c: counts[c])

    def _default_chosen_color(self, caster_index: int) -> str:
        """The colour a "choose a color" entry effect takes when nobody chooses.

        The colour *caster_index*'s **opponents** hold most of among nontoken
        permanents — the stated policy for a choice nothing else constrains
        (idiom 8), and the same reasoning `_default_chosen_creature_type` below
        gives: a colour nobody controls makes every "choose a color" effect
        inert, which is a legal choice no player would make and an AI seat would
        be stuck with.

        A method rather than the inline count it used to be, because two entry
        shapes need the same answer now — the colour alone (Psychic Allergy) and
        the colour beside a creature type (Volrath's Laboratory) — and two
        spellings of one default is how a card comes to be armed with one value
        and resolved against another.

        ``_dominant_nontoken_color`` above is the *per-seat* question Jihad asks
        of the opponent it names; this is the same count over every opponent at
        once, which is a different question and not a wording of it.
        """
        counts: dict[str, int] = {}
        for seat, player in enumerate(self.players):
            if seat == caster_index or player.lost:
                continue
            for perm in self.controlled_by(seat):
                if perm.metadata.get("is_token"):
                    continue
                for color in self._effective_colors(perm):
                    counts[color] = counts.get(color, 0) + 1
        if not counts:
            return "W"
        return max(sorted(counts), key=lambda c: counts[c])

    def _default_chosen_creature_type(self, caster_index: int, card=None) -> str:
        """The creature type An-Zerrin Ruins takes when nobody chooses.

        The type *caster_index*'s opponents have most of among nontoken
        creatures — the choice a player would make with the card, and the
        reason a default is stated rather than left to the first word of a
        catalog (idiom 8): a type nobody controls makes the enchantment inert,
        which is legal and pointless.

        **Unless the card feeds the type rather than hosing it**, which
        ``ai_valuation.chosen_creature_type_side`` reads off what *card* does
        with the word: Belbe's Portal puts a creature of the chosen type out of
        its controller's hand, Urza's Incubator makes its controller's spells
        of the type cheaper, and the opponents' type is the one answer certain
        to make either of them do nothing. Those take the type the controller's
        **own** cards have most of (:meth:`_own_creature_type_counts`). The
        weight-free half of "take gifts": derived from the compiled program and
        the two text tables, never from a name.

        Read through ``computed_types``, so a creature whose type line a layer-4
        effect rewrote counts as what it *is* rather than as what it was
        printed as — the same read ``subject_matches`` will make when the
        restriction is applied.

        "Human" when no opponent controls a creature at all: any word is a legal
        choice there, and the printed catalog's most common type is the one most
        likely to matter if a board arrives later.
        """
        if card is not None:
            from ..ai_prompt_readers import chosen_creature_type_side

            if chosen_creature_type_side(card) == "you":
                own = self._own_creature_type_counts(caster_index)
                if own:
                    return max(sorted(own), key=lambda word: own[word])
        counts = self._creature_type_counts(
            skip_seat=caster_index, include_tokens=False
        )
        if not counts:
            return "human"
        return max(sorted(counts), key=lambda word: counts[word])

    def _own_creature_type_counts(self, seat: int) -> dict[str, int]:
        """How many of *seat*'s creature cards **still to be played** have each
        type — its hand and its library — or, when those hold none, the
        creatures it already controls.

        The cards that want their controller's type spend it on cards not yet
        in play: Belbe's Portal reads the hand, Urza's Incubator every creature
        spell yet to be cast, and the library is where both come from — a
        player knows their own decklist. The board is the fallback rather than
        the count because a type the seat has already played out is the one a
        Portal can no longer feed. Hand and library through
        ``card_creature_types``, the board through ``computed_types``: the two
        readers ``object_creature_types`` names for the two kinds of object.
        """
        from ..layer_bridge import computed_types, printed_shape
        from ..object_creature_types import card_creature_types

        counts: dict[str, int] = {}
        player = self.players[seat]
        for zone in (player.hand, player.library):
            for owned in zone:
                # A creature *card*: `card_creature_types` hands a noncreature
                # card its printed subtypes (an Aura, a Forest), which are not
                # creature types and are not what the choice is choosing.
                if "creature" not in printed_shape(owned)[0]:
                    continue
                for subtype in card_creature_types(self, owned, seat):
                    counts[subtype] = counts.get(subtype, 0) + 1
        if counts:
            return counts
        for perm in self.controlled_by(seat):
            if perm.metadata.get("is_token"):
                continue
            card_types, subtypes = computed_types(perm)
            if "creature" not in card_types:
                continue
            for subtype in subtypes:
                counts[subtype] = counts.get(subtype, 0) + 1
        return counts

    def _creature_type_counts(
        self, *, skip_seat: int | None = None, include_tokens: bool = True
    ) -> dict[str, int]:
        """How many creatures of each type the named battlefields hold.

        One counting loop for the two defaults that need it, which is this
        file's own stated reason for `_default_chosen_color` being a method:
        two spellings of one count is how a card comes to be armed with one
        value and resolved against another.

        Read through ``computed_types`` (CR 613 layer 4), so an animated land
        counts as the creature it is and a retyped creature counts as what it
        *is* rather than as what it was printed as — the same read
        ``subject_matches`` makes when the chosen word is finally applied.

        The two knobs are exactly what the two callers disagree about, and
        neither disagreement is cosmetic. ``skip_seat`` drops a seat because
        An-Zerrin Ruins' choice hoses an opponent and counting the chooser's
        own board would aim the hoser at themselves; the cast-time choice below
        names no seat at all, so it counts every one. ``include_tokens`` is the
        same split one object kind over: a hoser aimed at a token type is aimed
        at whatever died last, while a count that *is* a creature's power
        (Caller of the Hunt) counts every creature the battlefield actually has
        — CR 111.1 makes a token a creature like any other.
        """
        from ..layer_bridge import computed_types

        counts: dict[str, int] = {}
        for seat, player in enumerate(self.players):
            if seat == skip_seat or player.lost:
                continue
            for perm in self.controlled_by(seat):
                if not include_tokens and perm.metadata.get("is_token"):
                    continue
                card_types, subtypes = computed_types(perm)
                if "creature" not in card_types:
                    continue
                for subtype in subtypes:
                    counts[subtype] = counts.get(subtype, 0) + 1
        return counts

    def _default_cast_creature_type(self, caster_index: int, card=None) -> str:
        """The creature type a CR 601.2b "choose a creature type" cost takes
        when the caster names none.

        The *cast-time* sibling of `_default_chosen_creature_type` above, and a
        separate default rather than a second caller of it, because the two
        clauses name different boards. "As this enchantment enters, choose a
        creature type" is printed on cards that hose what the chosen type does
        (An-Zerrin Ruins), so its default reads the **opponents'** board. "As an
        additional cost to cast this spell, choose a creature type" names no
        seat whatever — Caller of the Hunt then counts "creatures of the chosen
        type **on the battlefield**", every battlefield — so the default counts
        every seat, tokens included.

        The card's own printed creature types are the fallback before the
        catalog's, which is the choice a player makes on an empty board: Caller
        of the Hunt is a Human, so naming Human makes it at least a 1/1 the
        moment it arrives rather than a 0/0 that dies to CR 704.5f on an empty
        table. "Human" behind that for the reason the entry default gives: any
        word is legal there, and it is the pool's most common type.

        Stated as policy rather than left to the first word of a catalog
        (idiom 8): a type nobody controls makes every reader of the choice inert,
        which is legal and is not a choice any player would make.
        """
        counts = self._creature_type_counts()
        if counts:
            return max(sorted(counts), key=lambda word: counts[word])
        from ..layer_bridge import printed_shape

        if card is not None:
            types, printed = printed_shape(card)
            if "creature" in types and printed:
                return sorted(printed)[0]
        return "human"

    def _nameable_cards(
        self, chooser_index: int, *, exclude: str | None = None
    ) -> list[str]:
        """The card names *chooser_index* can see, for a "choose a card name"
        picker.

        CR 201.2 does not bound the choice by any board — a player may name any
        card — so this is an *offer* rather than a whitelist, and the resolver
        deliberately accepts a name that is not on it. What it excludes is the
        one thing the printed line excludes: a basic land card name, which
        Null Chamber may not name.
        """
        from ..grammar.phrases import BASIC_LAND_WORDS

        basics = {word.capitalize() for word in BASIC_LAND_WORDS}
        seen = [
            card.name
            for seat, player in enumerate(self.players)
            if seat != chooser_index and not player.lost
            for card in reversed(player.graveyard)
        ] + [
            perm.card.name
            for seat, player in enumerate(self.players)
            if seat != chooser_index and not player.lost
            for perm in self.controlled_by(seat)
        ]
        return sorted({
            name for name in seen if name not in basics and name != exclude
        })

    def _default_named_card(
        self, chooser_index: int, *, exclude: str | None = None
    ) -> str:
        """The card name *chooser_index* takes when nobody chooses.

        The first name they can see that is not a basic land — the choice a
        player would make with a card whose whole point is to stop something,
        and the reason a default is stated rather than left empty (idiom 8):
        naming nothing makes the enchantment inert, which is legal and
        pointless. Empty when there is nothing to see, which is the honest
        answer for a board with nothing on it.
        """
        offered = self._nameable_cards(chooser_index, exclude=exclude)
        return offered[0] if offered else ""

    def _default_entry_choice_option(
        self, caster_index: int, record_key: str, options: "tuple[str, ...]"
    ) -> str:
        """The option a permanent takes when its sentence printed exactly two
        and nobody chose (Mangara's Equity, Roots of Life).

        One policy for both records, because there is one question: the option
        *caster_index*'s **opponents** answer most often. That is the stated
        default for a choice nothing else constrains (idiom 8) and the same
        reasoning `_default_chosen_land_type` and the colour branch above give
        — an option nobody's board answers makes the permanent inert, which is
        legal and is not a choice any player would make.

        A tie, or a board that answers neither, falls to the **first printed**
        option. That is a word the card itself names rather than an
        alphabetical accident, and the two are equally good by construction:
        nothing distinguished them.

        Colours are read through ``_effective_colors`` and types through
        ``computed_types`` (CR 613), which are the reads ``subject_matches``
        will make when the record is spent — a default counted off the printed
        line would pick the option a Magical Hack had already moved.
        """
        from ..layer_bridge import computed_types

        counts = {option: 0 for option in options}
        for seat, player in enumerate(self.players):
            if seat == caster_index or player.lost:
                continue
            for perm in self.controlled_by(seat):
                if record_key == CHOSEN_COLOR_KEY:
                    answered = self._effective_colors(perm)
                else:
                    card_types, subtypes = computed_types(perm)
                    answered = subtypes if "land" in card_types else ()
                for option in options:
                    if option in answered:
                        counts[option] += 1
        best = max(counts.values())
        # ``options`` order, not ``max`` over a dict: the first printed option
        # is the tie-break, and iterating the counts would make it whichever
        # word happened to be inserted first.
        for option in options:
            if counts[option] == best:
                return option
        return options[0]

    def _default_chosen_land_type(self, caster_index: int) -> str:
        """The land type Shimmer takes when nobody chooses.

        The type *caster_index*'s opponents control most of — the choice a
        player would make with the card, and the reason a default is stated
        rather than left to the first word of a catalog (idiom 8): a type
        nobody controls makes the enchantment inert, which is legal and
        pointless.

        Read through ``computed_types`` (CR 613 layer 4) rather than off the
        printed type line, so a land some earlier effect turned into a Swamp
        counts as a Swamp — the same read ``subject_matches`` will make when
        the static is applied. ``basic_land_types`` would answer only for the
        five basics, and this choice ranges over every land type there is.

        "Island" when no opponent controls a land at all: any word is a legal
        choice there, and it is the type the pool prints most.
        """
        from ..grammar.vocabulary import LAND_TYPES
        from ..layer_bridge import computed_types

        counts: dict[str, int] = {}
        for seat, player in enumerate(self.players):
            if seat == caster_index or player.lost:
                continue
            for perm in self.controlled_by(seat):
                card_types, subtypes = computed_types(perm)
                if "land" not in card_types:
                    continue
                for subtype in subtypes:
                    if subtype in LAND_TYPES:
                        counts[subtype] = counts.get(subtype, 0) + 1
        if not counts:
            return "island"
        return max(sorted(counts), key=lambda word: counts[word])

    def _default_terrain_land_types(self, caster_index: int) -> tuple[str, str]:
        """The ordered pair Illusionary Terrain takes when nobody chooses.

        The type *caster_index*'s opponents control most of, turned into the one
        they control least — the choice a player would make with the card, and
        the reason a default is stated rather than left to the first two words
        of a list (idiom 8): a pair naming a type nobody has makes the
        enchantment inert, which is legal and pointless.

        Counted through ``basic_land_types`` (layer 4), so a land some earlier
        effect already changed is counted as what it is now.
        """
        from ..grammar.phrases import BASIC_LAND_WORDS

        counts = {word: 0 for word in BASIC_LAND_WORDS}
        for seat, player in enumerate(self.players):
            if seat == caster_index or player.lost:
                continue
            for perm in self.controlled_by(seat):
                for land_type in perm.basic_land_types:
                    if land_type in counts:
                        counts[land_type] += 1
        first = max(BASIC_LAND_WORDS, key=lambda word: (counts[word], -BASIC_LAND_WORDS.index(word)))
        second = min(
            (word for word in BASIC_LAND_WORDS if word != first),
            key=lambda word: (counts[word], BASIC_LAND_WORDS.index(word)),
        )
        return first, second

    def _nameless_race_cap(self, seat: int, described: dict) -> int:
        """The most life "the amount you pay can't be more than …" allows.

        Two halves the printed sentence adds: matching permanents the opponents
        control, and matching cards in their graveyards. Through the control
        seam for the first (``controls`` is a seat question, CR 109.5) and the
        card matcher for the second, because a card in a zone has no computed
        characteristics at all (CR 613.1).

        An **empty** spec is the card that prints no cap at all (Minion of the
        Wastes), and its ceiling is the one CR 119.4 imposes on every life
        payment: a player may pay more than 0 only up to their life total. Read
        here rather than left to the prompt, so the two spellings of one
        printed entry cost reach the same arming code.
        """
        from ..handlers._filters import _card_matches_filter, permanent_matches_filter

        if not described:
            return max(0, int(self.players[seat].life))
        total = 0
        for opponent in self.opponents_of(seat):
            for perm in self.controlled_by(opponent):
                if permanent_matches_filter(perm, described["battlefield"]):
                    total += 1
            for card in self.players[opponent].graveyard:
                if _card_matches_filter(
                    card, described["graveyard"], game=self, owner=opponent
                ):
                    total += 1
        return total
