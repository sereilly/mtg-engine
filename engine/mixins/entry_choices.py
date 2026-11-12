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

The prompt-table rows of the entry prompts answered here (``entry_exile``,
``body_choice``, ``entry_reveal``) are at the foot, beside the methods they
name, and ``mixins/stack/choices/table.py`` registers them in its order.
"""

from __future__ import annotations

from ..entry_choices import CHOSEN_COLOR_KEY
from ..keywords import grant_keyword
from ..models import Permanent, PlayerState
from ..pending_choices import ChoiceSpec
from ..pt import add_pt_counters, pt_counter_deltas, set_base_pt
from ..static_bonuses import BASIC_LAND_WORDS
from ..announced_creature_type import narrows_by_announced_type
from ..late_modules import LateModules
from ..oracle import compile_card_oracle

_late = LateModules(__package__.rpartition(".")[0])


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
        ``printed_characteristics.COPIABLE_VALUE``, ahead of every effect the clock has
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
        from ..printed_characteristics import COPIABLE_VALUE

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

    def _default_body_choice(self, choice) -> None:
        """The answer a seat gives when nobody asks it: the first printed body.

        A seat nobody asks had that body applied as the permanent entered, so
        there is nothing left to do but drop the prompt. A person had none
        applied (CR 614.12a, ``_stamps_entry_default``), so a person's prompt
        answered by default applies it now — the same body, by the same
        resolver an answer goes through."""
        permanent = choice.data.get("permanent")
        if permanent is None or "chosen_body" in permanent.metadata:
            self.discard_pending_choice(choice)
            return
        if not self._resolve_body_choice(choice, 0):
            self.discard_pending_choice(choice)

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
            if _card_matches_filter(
                card, described, game=self, owner=choice.player_index,
            )
        ]

    def _resolve_entry_exile(self, choice, picks) -> bool:
        """Exile the chosen cards and place the counter each one buys.

        Every pick is validated before anything moves - a single bad entry
        rejects the whole answer and leaves the prompt queued, so a malformed
        request cannot exile half a payment and leave the creature the wrong
        size. The count is exact rather than "up to": the card says *X* cards,
        and a short answer is the case the CR 614 interceptor already refused
        the entry for.

        **…except "any number of"** (Sutured Ghoul, ``any_number``): no count
        is owed, so any answer from none to every candidate is one, and no
        counter is bought. ``link_to_entering`` records each exiled card *with*
        the entering permanent (CR 607.2b) for the ability that reads "the
        exiled cards" — the Ghoul's CDA, which sums them.
        """
        player = self.players[choice.player_index]
        permanent = choice.data.get("_entering_permanent") or choice.data.get("permanent")
        wanted = int(choice.data.get("count", 0))
        offered = tuple(choice.data.get("counters") or ())
        legal = set(self._entry_exile_candidates(choice))
        if not isinstance(picks, list):
            return False
        if choice.data.get("any_number"):
            if len(picks) > len(legal):
                return False
        elif len(picks) != wanted:
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
            card = self.put_card_into_exile(player, player.graveyard.pop(index))
            exiled.append((card, counter))
        if choice.data.get("link_to_entering") and permanent is not None:
            from ..linked_exile import link_exiled_card

            # In graveyard order, which is the order a player reads the pile.
            for card, _counter in reversed(exiled):
                link_exiled_card(permanent, card, choice.player_index)
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

        **"Any number of"** (Sutured Ghoul): every candidate. Each card the
        Ghoul exiles is what its size is made of, and a 0/0 entering with an
        empty pile dies to the state-based check — so for a seat nobody asks
        the most is the only answer that is never the worst one.
        """
        player = self.players[choice.player_index]
        wanted = int(choice.data.get("count", 0))
        offered = tuple(choice.data.get("counters") or ())
        if choice.data.get("any_number"):
            wanted = len(self._entry_exile_candidates(choice))
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

    # -- "Amplify N": reveal cards from your hand as this enters (CR 702.38a) --

    def _entry_reveal_candidates(self, choice) -> list[int]:
        """Hand slots the reveal may name, re-derived from the filter the
        prompt was armed with — the offer and the answer's check are one list
        (idiom 9), and a hand that changed since is read as it is now."""
        from ..amplify import revealable_hand_slots

        return revealable_hand_slots(
            self, choice.player_index, dict(choice.data.get("filter") or {})
        )

    def _resolve_entry_reveal(self, choice, hand_indices) -> bool:
        """Reveal the chosen cards and place the counters they buy.

        "Any number of" (CR 702.38a): none is a legal answer and so is every
        candidate, but a slot outside the candidates or named twice rejects the
        whole answer and leaves the prompt queued — a malformed request cannot
        reveal a Goblin for a Beast's amplify. The cards stay in the hand and
        become public (CR 701.20a): the log names them and the reveal feed the
        web layer reads carries them. The counters go through
        ``place_plus1_counters`` — entering with counters is a counter placement
        like any other, so a CR 614 doubler of +1/+1 counters raises it.
        """
        if not isinstance(hand_indices, list):
            return False
        picks = list(hand_indices)
        if any(not isinstance(index, int) for index in picks):
            return False
        if len(set(picks)) != len(picks):
            return False
        legal = set(self._entry_reveal_candidates(choice))
        if any(index not in legal for index in picks):
            return False
        player = self.players[choice.player_index]
        permanent = choice.data.get("_entering_permanent") or choice.data.get("permanent")
        revealed = [player.hand[index] for index in sorted(picks)]
        name = choice.data.get("card_name", "an entering permanent")
        each = int(choice.data.get("counters_each", 0) or 0)
        if revealed:
            self.record_reveal(choice.player_index, [card.name for card in revealed])
        self.log.append(
            f"{player.name} revealed "
            + (", ".join(card.name for card in revealed) if revealed else "no cards")
            + f" for {name}'s amplify"
        )
        self.discard_pending_choice(choice)
        if revealed and each > 0 and permanent is not None:
            placed = self.place_plus1_counters(permanent, each * len(revealed))
            self.log.append(
                f"{name} entered with {placed} +1/+1 counter(s) (amplify {each})"
            )
            self._recompute_continuous_effects()
        return True

    def _default_entry_reveal(self, choice) -> None:
        """The stated policy for a seat nobody asks (idiom 8): **every**
        eligible card.

        Revealing costs nothing and each card is counters on the controller's
        own creature, so the most is the answer that is never the worst one —
        Ghastly Remains is a 0/0 that dies to the state-based check with an
        empty reveal. What revealing gives away (the hand, to the table) is a
        weight ``engine/ai_valuation.py`` would have to argue, not a branch
        here.
        """
        if not self._resolve_entry_reveal(choice, self._entry_reveal_candidates(choice)):
            # The candidates were just derived from the same rule, so a refusal
            # is a bug and not a board state; dropping the prompt keeps a
            # headless seat from stalling on it.
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

    def _next_opponent_in_turn_order(self, seat: int) -> int | None:
        """The first living opponent of *seat* after it in turn order, or None.

        The seat an "an opponent chooses" entry asks (Callous Oppressor) when
        nobody decides otherwise. With several opponents the controller decides
        who (CR 601.7a, 602.3a and 700.2e say so of every choice an effect hands
        "an opponent", and 800.4g has the controller pick the replacement when
        that opponent leaves): the controller is asked when a person sits there
        (:meth:`_arm_opponent_creature_type_entry`), and the next opponent in
        turn order is the stated default — on a two-player table, the only
        answer.
        """
        opponents = self._living_opponents_in_turn_order(seat)
        return opponents[0] if opponents else None

    def _living_opponents_in_turn_order(self, seat: int) -> list[int]:
        """*seat*'s living opponents (``opponents_of``), the next in turn order
        first."""
        total = len(self.players)
        rival = set(self.opponents_of(seat))
        return [
            other
            for other in ((seat + step) % total for step in range(1, total))
            if other in rival and not self.players[other].lost
        ]

    def _arm_opponent_creature_type_entry(self, permanent, controller: int) -> None:
        """"As this creature enters, **an opponent chooses** a creature type."
        (Callous Oppressor.) Who answers, then the answer.

        One opponent: that opponent is asked (or defaults). Several, with a
        person in the controller's seat: the controller chooses which first —
        the ``enter_choice`` prompt's opponent shape, Black Vise's, flagged
        ``then_opponent_chooses_creature_type`` — and the chosen opponent's
        creature-type prompt is armed by the answer
        (:meth:`_ask_opponent_for_creature_type`). A controller nobody asks
        takes the stated default seat. The default type for the default seat is
        stamped first either way, so nothing waits on a seat that cannot answer.
        """
        opponents = self._living_opponents_in_turn_order(controller)
        if not opponents:
            return
        default_seat = opponents[0]
        if len(opponents) > 1 and self.asks_a_person(controller):
            # Nothing stamped: a person is choosing who chooses, and the
            # permanent waits on its way for both answers (CR 614.12a,
            # ``_stamps_entry_default``).
            self.arm_pending_choice(
                "enter_choice", controller,
                card_name=permanent.card.name, permanent=permanent,
                needs_color=False, opponents=list(opponents),
                default_seat=default_seat, default_color=None,
                then_opponent_chooses_creature_type=True,
            )
            return
        self._ask_opponent_for_creature_type(permanent, default_seat)

    def _ask_opponent_for_creature_type(self, permanent, chooser: int) -> None:
        """Arm *chooser*'s "choose a creature type" for *permanent*, with the
        type that protects the most of the chooser's own creatures stamped as
        its default (:meth:`_protecting_creature_type`)."""
        default_type = self._protecting_creature_type(chooser)
        if self._stamps_entry_default(chooser):
            permanent.metadata["chosen_creature_type"] = default_type
        self.arm_pending_choice(
            "enter_choice", chooser,
            card_name=permanent.card.name, permanent=permanent,
            needs_color=False, opponents=[], default_seat=None,
            default_color=None, needs_creature_type=True,
            default_creature_type=default_type,
            # Armed by the controller's *answer* when several opponents could
            # choose, after the entry state has stamped its prompts — so it
            # says itself which permanent it keeps on its way.
            _entering_permanent=permanent,
        )

    def _protecting_creature_type(self, seat: int) -> str:
        """The creature type *seat* names when its choice **spares** its own
        creatures — "target creature that isn't of the chosen type" (Callous
        Oppressor), chosen by the Oppressor's opponent.

        The type the seat's own creatures on the battlefield have most of,
        through the layers — **not** net of anyone else's: what the word
        protects is the chooser's own board, and the Oppressor's controller
        holding more of the same type changes nothing about which of the
        chooser's creatures it can take. With none on its board, the type its
        own cards still to be played have most of
        (:meth:`_own_creature_type_counts`); with none of those, "human", the
        catalog's commonest word, for :meth:`_default_chosen_creature_type`'s
        reason. Ties go to the alphabetically first word.
        """
        from ..handlers.value_choices import _creature_type_census

        mine: dict[str, int] = {}
        for holder, words in _creature_type_census(self, "battlefield", seat):
            if holder != seat:
                continue
            for word in words:
                mine[word] = mine.get(word, 0) + 1
        if mine:
            return max(sorted(mine), key=lambda word: mine[word])
        own = self._own_creature_type_counts(seat)
        if own:
            return max(sorted(own), key=lambda word: own[word])
        return "human"

    def _default_chosen_creature_type(self, caster_index: int, card=None) -> str:
        """The creature type An-Zerrin Ruins takes when nobody chooses.

        The type *caster_index*'s opponents have most of among nontoken
        creatures — the choice a player would make with the card, and the
        reason a default is stated rather than left to the first word of a
        catalog (idiom 8): a type nobody controls makes the enchantment inert,
        which is legal and pointless.

        **Unless the card feeds the type rather than hosing it**, which
        ``ai_prompt_readers.chosen_creature_type_side`` reads off what *card* does
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
        from ..layer_bridge import computed_types
        from ..printed_characteristics import printed_shape
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

        **A type that narrows the spell's targets** ("Return up to three
        target creature cards of the creature type of your choice from your
        graveyard", Aphetto Dredging) names a board of its own: the caster's
        graveyard, whose creature cards are what the word decides. So the
        default there is the type most of them share, which is the most the
        spell could return; an empty pile falls back to the reading above.
        Each card's types through ``card_creature_types`` with the caster's
        seat — the pile's owner, and the spell's controller for the card's
        own types below: "the same is true for creature spells you control and
        creature cards you own that aren't on the battlefield" (Conspiracy)
        makes every one of them the chosen type and nothing else (CR 205.1a,
        613.1), so the printed count named a type no card in the pile had.
        """
        from ..object_creature_types import card_creature_types
        from ..printed_characteristics import printed_shape

        if card is not None and self._cast_type_narrows_graveyard_targets(card):
            pile: dict[str, int] = {}
            for held in self.players[caster_index].graveyard:
                if "creature" not in printed_shape(held)[0]:
                    continue
                for word in card_creature_types(self, held, caster_index):
                    pile[word] = pile.get(word, 0) + 1
            if pile:
                return max(sorted(pile), key=lambda word: pile[word])
        counts = self._creature_type_counts()
        if counts:
            return max(sorted(counts), key=lambda word: counts[word])

        if card is not None and "creature" in printed_shape(card)[0]:
            printed = card_creature_types(self, card, caster_index)
            if printed:
                return sorted(printed)[0]
        return "human"

    def _cast_type_narrows_graveyard_targets(self, card) -> bool:
        """Whether the creature type *card*'s cast announces narrows the
        cards it targets (``announced_creature_type``) — read off the target
        spec the card's own program derives, the description every reader of
        those targets holds."""
        derive_cast_spec = _late.targeting.derive_cast_spec

        # A permanent spell targets nothing (CR 115.1); only an instant's or a
        # sorcery's own targets can be chosen under its announcement.
        if getattr(card, "primary_type", None) not in ("instant", "sorcery"):
            return False
        return narrows_by_announced_type(
            derive_cast_spec(card, compile_card_oracle(card))
        )

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


# ---------------------------------------------------------------------------
# This family's rows of the prompt table
# ---------------------------------------------------------------------------
#
# One ``ChoiceSpec`` per prompt kind of this family, in the table's order
# (``engine/pending_choices.py`` says what each field means).
# ``stack/choices/table.py`` registers them, in the one list
# ``Game.iter_pending_prompts`` reads.

ENTRY_EXILE_SPEC = ChoiceSpec(
    "entry_exile",
    resolve=lambda game, choice, r: game._resolve_entry_exile(choice, r.get("picks")),
    default=lambda game, choice: game._default_entry_exile(choice),
    action="entry_exile_confirm",
    prompt_key="entry_exile",
    blocked_detail="exile the entering permanent's cards before other actions",
    # The resolution that armed this has to finish, so a non-interactive seat
    # never queues it: the stated default is taken where the entry stands, which
    # is also what keeps AI and headless play from waiting on a prompt nobody
    # will answer.
    default_at_arm=True,
    # A graveyard is a public zone (CR 400.2), so there is nothing here a
    # seatless viewer may not already see - unlike `put_from_hand_choice` and
    # `choose_cards_in_hand`, whose candidates would publish a hand.
    spectator_visible=True,
)

BODY_CHOICE_SPEC = ChoiceSpec(
    "body_choice",
    resolve=lambda game, choice, r: game._resolve_body_choice(choice, r["option_index"]),
    # Primal Clay's first printed body is applied as it enters for a seat
    # nobody asks, so the default is already in place; a person has none
    # applied until they answer (CR 614.12a), and the default applies it.
    default=lambda game, choice: game._default_body_choice(choice),
    action="body_choice_confirm",
    prompt_key="body_choice",
    blocked_detail="choose the entering creature's body before other actions",
    default_at_arm=True,
)

ENTRY_REVEAL_SPEC = ChoiceSpec(
    # "Amplify N" (CR 702.38a): "As this object enters, reveal any number of
    # cards from your hand that share a creature type with it. This permanent
    # enters with N +1/+1 counters on it for each card revealed this way." A
    # choice of hand slots made as the permanent enters (CR 614.1c), answered
    # with the slots to reveal (`hand_indices`), none included. The entry
    # exile's arrangement with the hand where that has a graveyard: the
    # permanent has not finished entering until it is answered, so the
    # state-based sweep leaves a 0/0 Ghastly Remains alone meanwhile.
    "entry_reveal",
    resolve=lambda game, choice, r: game._resolve_entry_reveal(
        choice, r.get("hand_indices")
    ),
    default=lambda game, choice: game._default_entry_reveal(choice),
    action="entry_reveal_confirm",
    prompt_key="entry_reveal",
    blocked_detail="choose which cards to reveal for the entering creature's amplify before other actions",
    # The resolution that put the permanent onto the battlefield has to finish,
    # so a seat nobody asks takes the stated default where the entry stands.
    default_at_arm=True,
    # Deliberately *not* spectator_visible, for `choose_cards_in_hand`'s
    # reason: the candidates are cards in a hand (CR 400.2, a hidden zone),
    # and only the ones the seat chooses become public.
)
