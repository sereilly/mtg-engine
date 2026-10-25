"""Tapping a land for mana: which of its mana abilities a tap runs, whether it may, and the tap.

``tap_land_for_mana`` is the player's tap (CR 605.1a), and a cost an effect
collects taps each planned land through it too (``Game._pay_planned_cost``).
Asking for a symbol picks the ability as well as the colour (CR 605: each
mana ability is its own); ``land_mana_ability_for`` names it by index.

``is_tap_alone_mana_ability`` is the one predicate for which abilities this
seam may run: a supported mana ability whose whole cost is {T} (CR 106.12),
with nothing on it the seam cannot honour part-way through a payment.
``_land_mana_abilities`` walks the land's effective card for the free one and
says whether a priced one exists; a basic land type the land gained is a
second mana ability with no text (CR 305.6/305.7, ``_gained_type_mana``).
``land_mana_tap_refusal`` is the seam's own gate, pure, so what a planner
counts and what the tap makes are one answer; its CR 602.5 half is
``land_tap_prohibition``, over the one prohibition table.

What follows the tap - the replacement over the production, an Aura's
additional mana and the triggers that watch a land tapped for mana - is the
event, ``land_tapped_for_mana.py``.
"""

from __future__ import annotations

import dataclasses

from ..keywords import abilities_lost_at
from ..mana_payment import answer_color_choices
from ..game_types import OracleExecutionContext
from ..oracle import compile_card_oracle


def _is_free_beyond_tapping(cost) -> bool:
    """Whether *cost* is the tap symbol and nothing else.

    Compared against a default cost rather than by listing the fields that must
    be empty. A list would silently start ignoring any cost component added
    later — and ignoring a cost component here means performing an ability
    without paying for it, which is the one direction this check exists to
    prevent.
    """
    empty_mana = {symbol: 0 for symbol in cost.mana}
    return cost == dataclasses.replace(
        type(cost)(mana=empty_mana), requires_tap=True
    )


#: The six types of mana a tap can be asked for (CR 106.1b).
_TAPPABLE_SYMBOLS = frozenset({"W", "U", "B", "R", "G", "C"})


def is_tap_alone_mana_ability(ability) -> bool:
    """Whether *ability* is one the tap-for-mana seam may run: a supported mana
    ability (CR 605.1a; an ``if_then`` "…add {C}{C} instead" too) whose whole
    cost is {T} (CR 106.12's "tap for mana").

    One predicate for the three readers that ask it — the seam's own walk, the
    seam taking an ability the player chose by index, and the web route that
    decides which of the engine's two entry points a land click goes to. Those
    answering separately is how the route kept a three-kind set of its own
    while the seam asked CR 605.1a, and a land's coloured second ability went
    down the path that skips every swap and trigger the seam announces.
    """
    from ..activation_restrictions import (prints_activation_restriction,
                                           restrictions_askable_mid_payment)
    from ..mana_payment import carries_an_offer, is_mana_ability

    instruction = getattr(ability, "instruction", None)
    if instruction is None or not getattr(ability, "supported", False):
        return False
    if not (is_mana_ability(ability) or instruction.kind == "if_then"):
        return False
    cost = ability.cost
    if not (bool(cost.requires_tap) and _is_free_beyond_tapping(cost)):
        return False
    # **And nothing the seam cannot honour from inside a payment.** The seam is
    # reached part-way through paying a cost (CR 601.2g), with nobody holding
    # priority, and it asks no CR 602.5 gate — so a printed "Activate only …"
    # clause would go unenforced there; "only as an instant" is CR 304.5's
    # "the player must have priority". And an ability that asks another player
    # something has no mana to give until they answer. "{T}: Choose a color.
    # Add one mana of that color unless any player pays {1}. Activate only as
    # an instant." (Rhystic Cave) is both. Such an ability is the activation
    # path's, which gates it and runs it inline all the same (CR 605.3b); the
    # seam reports it priced, which is the answer it already refuses.
    #
    # **Unless every clause is a board condition** the seam asks itself
    # ("{T}: Add {W} or {B}. Activate only if you control a Swamp.", the
    # Tainted lands): ``Game.land_mana_tap_refusal`` asks it of the ability
    # by index, so the clause is enforced at this door too, and the land's
    # coloured mana is reachable by a tap, the planner and the highlight.
    line = getattr(ability, "source_line", "") or ""
    return not (
        (
            prints_activation_restriction(line)
            and not restrictions_askable_mid_payment(line)
        )
        or carries_an_offer(instruction)
    )


#: The tap refusals `tap_land_for_mana` logs, by the reason key
#: `land_mana_tap_refusal` returns, as the suffix after the land's name.
_LOGGED_TAP_REFUSALS = {
    "summoning_sick": " has summoning sickness",
    "activations_forbidden": "'s activated abilities can't be activated this turn",
    "aura_activations_forbidden": "'s activated abilities can't be activated",
}


#: The reason key `land_mana_tap_refusal` returns for a CR 602.5 prohibition,
#: by the row of ``activation_prohibitions.ACTIVATION_PROHIBITIONS`` that
#: answered. The three this seam asked before it asked the table keep the keys
#: their callers and tests already read; every other row is its own kind, and
#: `tap_land_for_mana` logs the sentence the table gives it.
_TAP_REFUSAL_BY_ROW = {
    "permanent_shut_off_this_turn": "activations_forbidden",
    "aura_all_shut_off": "aura_activations_forbidden",
    "printed_restriction": "activation_restricted",
}


class LandManaTapsMixin:
    @staticmethod
    def _land_mana_abilities(land):
        """``(free_instruction, priced)`` for the land's own mana abilities.

        The first is the instruction an ability whose cost is **the tap alone**
        produces -- what this entry point may run, having already tapped the
        land and charging nothing further. The second says whether the land has
        a mana ability the tap does *not* pay for.

        Both, from one walk, because the caller needs them together and the
        difference decides opposite answers. A land with neither is a basic or a
        Bazaar of Baghdad and falls through to the ``produced_mana`` summary; a
        land with the second and not the first must be **refused**, because that
        summary is Scryfall's list of symbols the land can make and says nothing
        at all about what they cost.

        **A land whose type an effect set has neither of its own** (CR 305.7):
        it "loses all abilities generated from its rules text … and gains the
        appropriate mana ability for each new basic land type", which is the
        summary path. ``land_types.lost_abilities_to_type_change`` named three
        readers — layer 6, the activation gate, the trigger scan — and this
        was the fourth that did not ask: a Karplusan Forest under Blood Moon
        tapped for its printed {C} through this seam while the activation path
        refused the very same ability, and a Mishra's Workshop still made
        {C}{C}{C}. It no longer asks either, because the walk below is over
        the land's *effective* card, which is the land with its own text
        struck — and what is left in it is what the rule keeps: a mana ability
        another effect **granted** the land ("Lands you control have '{T}: Add
        two mana of any one color.'", Overlaid Terrain), which the arm that
        stood here returned in front of.
        """
        from ..activation_restrictions import prints_activation_restriction
        from ..mana_payment import is_mana_ability, land_text_is_run

        if not land_text_is_run(land):
            # A land none of whose text compiles (Rhystic Cave, until PCY
            # W3G1): the summary below would be its whole reading — free mana
            # with every cost and condition taken out. Reported as priced,
            # which is the answer the tap seam refuses.
            return None, True
        priced = False
        for ability in compile_card_oracle(land.effective_card).activated_abilities:
            instruction = ability.instruction
            if instruction is None or not ability.supported:
                continue
            if not (is_mana_ability(ability) or instruction.kind == "if_then"):
                continue
            if is_tap_alone_mana_ability(ability) and not prints_activation_restriction(
                ability.source_line or ""
            ):
                return instruction, priced
            # A tap-alone ability that prints a board condition ("Activate
            # only if you control a Swamp", the Tainted lands) is reachable by
            # index and asked its clause there (``land_mana_tap_refusal``), but
            # it is never the default a bare tap runs: a default that could be
            # refused would refuse the land's free mana with it.
            priced = True
        return None, priced

    def _chosen_land_mana_ability(self, land, ability_index: int):
        """The instruction of the mana ability *ability_index* names on *land*,
        or None when that ability is not one this seam may run.

        CR 605: each mana ability is a separate ability its controller chooses
        to activate, and the index is the one the activation path and the wire
        already address a permanent's abilities by
        (``targeting.usable_activated_abilities`` over the playable card). So a
        Karplusan Forest's coloured second ability, or the "{T}: Add two mana
        of any one color" Overlaid Terrain grants it, is reachable through the
        seam rather than always losing to the land's own first ability.

        Only a tap-alone mana ability: anything costing more is the activation
        path's to pay (CR 602.2b), which this seam refuses by design.
        """
        usable = self.usable_abilities_of(land)
        if not 0 <= ability_index < len(usable):
            return None
        chosen = usable[ability_index]
        return chosen.instruction if is_tap_alone_mana_ability(chosen) else None

    def land_mana_ability_for(self, land, color: str) -> int | None:
        """Which of *land*'s mana abilities makes *color* — an index for
        ``tap_land_for_mana(ability_index=…)`` — or None for the seam's default.

        CR 605: each mana ability is its own ability, and the tap seam runs the
        land's **first** tap-alone one unless told which. For a painland that
        is "{T}: Add {C}", so a payer that counted a Karplusan Forest or an
        Underground River as a coloured mana and tapped it by colour alone got
        {C}. None whenever the default already makes the colour (a basic, a
        dual, City of Brass, a land under a swap the seam applies to any
        ability), so every land that taps correctly by default taps exactly
        as it did.

        On the game rather than in the AI's policy, where it was written
        (``ai_payment.planned_tap_ability`` asks here now): the engine's own
        payer — a cost an effect collects, ``_pay_planned_cost`` — taps lands
        for a colour a plan counted on exactly as an AI seat does, and two
        readers choosing an ability two ways is a land that pays for one
        player and not for the other.
        """
        from ..ai_valuation import mana_ability_symbols
        from ..land_mana_swaps import swapped_production

        free, _priced = self._land_mana_abilities(land)
        if free is None or color in mana_ability_symbols(free):
            return None
        # …nor where a land type the land **gained** makes it (CR 305.6:
        # "{T}: Add {B}" for a Swamp it was made): that is the seam's own arm,
        # which runs when no ability is named.
        if color in self._gained_type_mana(land):
            return None
        # **A land under a swap makes the swapped symbol by any of its
        # abilities** ("If a land is tapped for mana, it produces {B}
        # instead", Infernal Darkness), so the default one answers — and it is
        # the one that costs nothing more. Asked for the {B} the swap makes,
        # an Underground River was sent to its second ability because that is
        # the one whose *printed* symbols include {B}: the plan took a point
        # of damage to pay a generic pip its free {C} would have paid. The
        # one exception is a colours-only swap ("…instead of any other
        # **color**", Hall of Gemstone) over a default that makes only {C},
        # which the swap leaves alone.
        swap = swapped_production(self, land)
        if swap is not None and swap.produced is not None and not (
            swap.colors_only and mana_ability_symbols(free) <= {"C"}
        ):
            return None
        for index, ability in enumerate(self.usable_abilities_of(land)):
            if not is_tap_alone_mana_ability(ability):
                continue
            if color in mana_ability_symbols(ability.instruction) and (
                self.land_mana_tap_refusal(land, index) is None
            ):
                return index
        return None

    def land_mana_tap_refusal(self, land, ability_index: int | None = None) -> str | None:
        """Why tapping *land* for mana through :meth:`tap_land_for_mana` would
        be refused right now — a short reason key — or None when it would make
        mana. Pure: nothing is tapped, logged or produced.

        **The seam's own gate, made askable.** The AI's tap planner
        (`ai_payment._plan_land_taps`) counted every untapped land as a mana,
        while this seam refuses a storage or depletion land with no counter
        to pay (Sand Silos), a land with no mana ability at all (Bazaar of
        Baghdad), a summoning-sick land creature and a land under Interdict —
        so the AI tapped "for" a spell, the tap made nothing and the cast was
        refused for insufficient mana, the same spell every turn. Invisible
        while the simulator ignored mana costs; the web app's AI seat, which
        never did, had it all along. One predicate, asked by both, so what the
        planner counts and what the tap makes cannot disagree.
        """
        # ``has_type``, not the printed line: a Clone that copied a Forest some
        # Living Lands had animated is a Forest (CR 707.2) and taps for {G}.
        # Asked of the Clone's own card it was a creature, and no land at all.
        if land is None or not land.has_type("land") or land.tapped:
            return "not_an_untapped_land"

        # Tapping a land for mana *is* activating its mana ability (CR 106.12),
        # so the gates the activation path asks of that ability are asked here
        # too — this seam is the second door to the same ability, and a gate
        # one door asks and the other does not is a rule enforced on half the
        # wire. CR 302.6 (through CR 602.5a): a land that is a creature —
        # Mishra's Factory animated, a Forest under Living Lands — has the
        # summoning-sickness rule like any creature, and a {T} mana ability is
        # a {T} ability.
        if self._is_summoning_sick(land):
            return "summoning_sick"
        # **And CR 602.5, through the one table** (``engine/activation_
        # prohibitions.py``). This seam used to ask two of its rows by hand —
        # Interdict's per-permanent ban and an Aura's "its activated abilities
        # can't be activated" (Stupefying Touch, Volrath's Curse) — and the
        # rest of the table not at all, so a Forest tapped for mana on another
        # player's turn under City of Solitude ("This stops players from
        # activating mana abilities", 2009-10-01) and a Forest that Living
        # Lands made a creature tapped under Cursed Totem ("Cursed Totem stops
        # players from activating mana abilities of creatures", 2021-06-18).
        # The rows that print CR 605.1a's exception (Abeyance, Hand to Hand,
        # Faith's Fetters) answer for a mana ability by themselves, so asking
        # the whole table is the rule and no row is listed here.
        prohibited = self.land_tap_prohibition(land, ability_index)
        if prohibited is not None:
            return _TAP_REFUSAL_BY_ROW.get(prohibited.kind, prohibited.kind)

        # A land with no mana ability at all (Island of Wak-Wak, Bazaar of
        # Baghdad) can't be tapped for mana — without this, the color fallback
        # below would invent a green mana out of nothing. A compiled one the
        # summary does not know about (a mana ability granted to such a land)
        # is a mana ability all the same.
        if ability_index is not None:
            if self._chosen_land_mana_ability(land, ability_index) is None:
                return "no_such_mana_ability"
            # "{T}: Add {W} or {B}. **Activate only if you control a Swamp.**"
            # (Tainted Field.) CR 602.5's clause is the table's
            # ``printed_restriction`` row, asked above of the ability chosen —
            # the seam admits such an ability only when every clause is a
            # board condition (``restrictions_askable_mid_payment``).
            return None
        mana_ability, priced_mana_ability = self._land_mana_abilities(land)
        if mana_ability is None and not land.effective_produced_mana:
            if not land.basic_land_types:
                return "no_mana_ability"
        # **A land that has lost all abilities has lost this one too**
        # (CR 613.1f). The mana ability a basic land type gives is an ability
        # like any other — CR 305.6 calls it intrinsic, not exempt — and
        # Humility's own ruling says so: "Removes all creature abilities. This
        # includes mana abilities. Animated lands will also lose the ability
        # to tap for mana." (2007-02-01.) A Forest under Living Lands and a
        # Humility is a 1/1 that taps for nothing. What is left to tap for is
        # a mana ability an effect granted it *afterwards*, which is the
        # compiled one above — the walk is over the effective card, where
        # only the newer grants remain. The summary path below is the type's
        # ability and the printed card's, and it asked nothing.
        if mana_ability is None and abilities_lost_at(land) is not None:
            return "no_mana_ability"

        # **And a land whose mana ability costs more than the tap cannot be
        # tapped for mana here either** (CR 602.2b: every cost, at one moment).
        # "{T}, Remove a depletion counter from this land: Add {B}{B}" (Peat Bog
        # and its four siblings) and "{T}, Remove any number of storage
        # counters ...: Add {B} for each" (the storage-land cycles, Gemstone
        # Mine) all fall past the compiled-ability branch below -- it takes only
        # a tap-alone cost, correctly -- and landed on the ``produced_mana``
        # fallback, which adds **one** mana of the summary's colour and charges
        # nothing. Sixteen lands in the pool tapped for a free mana for ever,
        # spending no counter and so never sacrificing themselves; six of them
        # ship. The amount is wrong too, but the unpaid cost is what makes it a
        # different card.
        #
        # Refused rather than approximated: the seat activates the ability and
        # pays, which is the path that works. Producing nothing is the honest
        # answer for a caller -- the AI's auto-tap, the web's land click -- that
        # asked to tap a land and cannot pay what the land asks.
        if (
            mana_ability is None and priced_mana_ability
            # …unless the land has a second, free one: the mana ability of a
            # basic land type it *gained* (see ``_gained_type_mana``).
            and not self._gained_type_mana(land)
        ):
            return "priced_mana_ability"
        return None

    def land_tap_prohibition(self, land, ability_index: int | None = None):
        """The CR 602.5 prohibition that forbids tapping *land* for mana right
        now — an ``ActivationProhibition`` — or None.

        Asked of the ability the tap would activate (CR 605: each mana ability
        is its own): the one *ability_index* names, else the land's own free
        mana ability, else CR 305.6's intrinsic one
        (``mana_payment.INTRINSIC_LAND_MANA_ABILITY``), which is what a basic
        land and a land read off its summary are tapping. An index that names
        no tap-alone mana ability has nothing to ask; the seam refuses it for
        that reason instead. Pure, like the table.
        """
        from ..activation_prohibitions import activation_prohibition

        ability = self._land_tap_ability(land, ability_index)
        if ability is None:
            return None
        return activation_prohibition(
            self, self.controller_index_of(land), land, ability
        )

    def _land_tap_ability(self, land, ability_index: int | None):
        from ..mana_payment import INTRINSIC_LAND_MANA_ABILITY

        if ability_index is not None:
            usable = self.usable_abilities_of(land)
            if not 0 <= ability_index < len(usable):
                return None
            chosen = usable[ability_index]
            return chosen if is_tap_alone_mana_ability(chosen) else None
        free, _priced = self._land_mana_abilities(land)
        if free is not None:
            for ability in compile_card_oracle(land.effective_card).activated_abilities:
                if ability.instruction is free:
                    return ability
        return INTRINSIC_LAND_MANA_ABILITY

    @staticmethod
    def _gained_type_mana(land) -> tuple[str, ...]:
        """The mana symbols of the basic land types *land* gained "in addition
        to its other land types" (Blanket of Night) — CR 305.7's last
        sentence: it "keeps its land types and rules text, and it gains the
        new land types **and mana abilities**".

        So such a land has two kinds of mana ability, and they are not found
        in the same place: what it prints is a compiled ability, and what the
        gained type gives it is CR 305.6's intrinsic "{T}: Add [symbol]",
        which is no text at all. Empty for every other land, a land whose type
        an effect *set* included — that one has only the intrinsic ability,
        which the summary path below already is — **until a mana ability
        granted to it is in the compiled walk** (Riftstone Portal's "{T}: Add
        {G} or {W}"): then the summary is never read, so its own types count
        here too, or a Swamp so granted taps for {G} when asked for {B}. Only
        a *granted* one: a land whose own text prints a mana ability beside its
        type is the walk's already, and counting its type here too sent a
        restricted "{T}: Add {W}{W}" Plains under a swap down the type's
        unrestricted road (``test_land_mana_swap_buckets``). Not after a
        "loses all abilities" (CR 613.1f), which only a newer grant survives.
        """
        from ..land_types import added_land_types

        added = set(added_land_types(land))
        if (
            land.basic_land_types and abilities_lost_at(land) is None
            and not LandManaTapsMixin._prints_own_mana_ability(land)
        ):
            free, priced = LandManaTapsMixin._land_mana_abilities(land)
            if free is not None or priced:
                added |= set(land.basic_land_types)
        if not added:
            return ()
        return tuple(
            symbol
            for land_type, symbol in zip(land.basic_land_types, land.basic_land_mana)
            if land_type in added
        )

    @staticmethod
    def _prints_own_mana_ability(land) -> bool:
        """Whether *land*'s own rules text still gives it a mana ability the
        walk in :meth:`_land_mana_abilities` would find — never for a land
        whose type an effect set, which lost that text (CR 305.7). "Own" is
        ``Permanent.card_through_layer_3``: what it prints, copies (CR 707.2)
        or was rewritten to say (CR 612), before any layer-6 grant."""
        from ..land_types import lost_abilities_to_type_change
        from ..mana_payment import is_mana_ability

        if lost_abilities_to_type_change(land):
            return False
        return any(
            ability.supported and ability.instruction is not None
            and (is_mana_ability(ability) or ability.instruction.kind == "if_then")
            for ability in compile_card_oracle(land.card_through_layer_3).activated_abilities
        )

    def _default_tap_symbols(self, land, mana_ability) -> tuple[str, ...]:
        """The symbols *mana_ability* — the one a tap of *land* with no
        ability named runs — can make, read off the ability itself; the
        printed summary where its shape is not read."""
        from ..board_payment import _makes

        made = _makes(self, land, mana_ability)
        if made is None:
            return tuple(land.effective_card.produced_mana or ())
        return tuple(made)

    @staticmethod
    def _tap_alone_makes_only_gained_mana(land) -> tuple[str, ...]:
        """The symbols a **tap alone** makes from *land* where its own mana
        ability costs more than the tap and a gained land type's does not —
        or empty, for every other land.

        A Hickory Woodlot under Blanket of Night has two mana abilities: the
        one it prints ("{T}, Remove a depletion counter: Add {G}{G}"), which
        this seam does not run, and the gained Swamp's "{T}: Add {B}"
        (CR 305.6), which it does. So what the land can be *tapped for* is
        {B} and only {B} — per symbol, not per land — and every reader that
        counts the land as mana has to hear that: the planner's list
        (``mana_payment.taps_for_payment``) left it out altogether, and the
        planner's hook, the castable highlight and the wire's colour list
        each offered the {G} its summary names for a tap that makes {B}.
        """
        free, priced = LandManaTapsMixin._land_mana_abilities(land)
        if free is None and priced:
            return LandManaTapsMixin._gained_type_mana(land)
        return ()

    def tap_land_for_mana(
        self,
        player_index: int,
        land_name: str,
        chosen_color: str | None = None,
        permanent_index: int | None = None,
        *,
        permanent_id: int | None = None,
        ability_index: int | None = None,
    ) -> bool:
        """Tap one land for mana (CR 605.1a), as its controller.

        *chosen_color* is the mana symbol the seat asks the land for — one of
        the six types (CR 106.1b), or None for "whatever it makes". **Asking
        chooses the ability as well as the colour** (CR 605: each mana ability
        is its own, and the player picks which to activate): a Karplusan
        Forest asked for {R} runs "{T}: Add {R} or {G}. This land deals 1
        damage to you.", and asked for nothing runs "{T}: Add {C}."
        (``board_payment.tap_alone_ability_for``). It used to run the first
        one whatever was asked, so every reader that said the land pays {R}
        was contradicted by the tap. A symbol the land cannot make is no
        choice and takes the land's default, as it always has; a string that
        is no mana symbol at all is **refused**, with nothing tapped — it
        reached the colour normalizer inside a handler and raised.

        *ability_index* is which of the land's mana abilities the player chose
        outright, indexing the same list the activation path does, and wins
        over what the colour would have picked. With neither, the land's
        first tap-alone mana ability runs.

        *permanent_id* addresses the land the way the rest of the engine does
        and takes precedence over the name-and-slot pair above it, which exists
        because the web layer addresses a permanent by its **slot**. A caller
        walking a whole battlefield has no slot to quote and cannot use the
        name either: two Forests are one name, and
        ``_find_controlled_permanent`` answers with the first — which on a
        forced tap-out is the one already tapped, so the untapped one is
        skipped and the seat pays nothing. The id is stable across the loop
        (CR 400.7) where a slot is not.
        """
        player = self.players[player_index]
        if permanent_id is not None:
            land = self.permanent_by_id(permanent_id)
            if land is not None and self.controller_index_of(land) != player_index:
                land = None
        else:
            resolved = self._find_controlled_permanent(
                player, land_name, permanent_index
            )
            land = resolved[1] if resolved else None
        # What was *asked for*, kept apart from the default the rest of this
        # method falls back on: only a symbol somebody named picks an ability.
        asked = None if chosen_color is None else str(chosen_color).strip().upper()
        if asked is not None and asked not in _TAPPABLE_SYMBOLS:
            if asked:
                # Not one of the six mana types: nothing this land or any
                # other could be tapped for.
                return False
            asked = None
        chosen_color = asked or "G"
        if (
            ability_index is None and asked is not None
            and land is not None and land.has_type("land")
        ):
            from ..board_payment import tap_alone_ability_for

            ability_index = tap_alone_ability_for(self, land, asked)
        refusal = self.land_mana_tap_refusal(land, ability_index)
        if refusal is not None:
            # The refusals a player can see the reason for are logged, as they
            # always were; the rest are a land that makes no mana here. A CR
            # 602.5 prohibition the seam did not ask before it asked the table
            # is logged in the table's own sentence.
            if refusal in _LOGGED_TAP_REFUSALS:
                self.log.append(f"{land.card.name}{_LOGGED_TAP_REFUSALS[refusal]}")
            else:
                from ..activation_prohibitions import ACTIVATION_PROHIBITIONS

                if any(row.kind == refusal for row in ACTIVATION_PROHIBITIONS):
                    prohibited = self.land_tap_prohibition(land, ability_index)
                    if prohibited is not None:
                        self.log.append(prohibited.details)
            return False
        gained_symbol = None
        if ability_index is not None:
            mana_ability = self._chosen_land_mana_ability(land, ability_index)
        else:
            mana_ability, _priced = self._land_mana_abilities(land)
            # "Each land is a Swamp **in addition to its other land types**."
            # (Blanket of Night.) The land keeps the mana ability it prints
            # and gains its new type's (CR 305.7's last sentence, CR 305.6), so
            # the colour the seat asks for says which of the two it is
            # activating: the gained type's when only that one makes it — and
            # when the land's own mana ability costs more than the tap (a
            # depletion land's), which this seam does not run and must not
            # hand out free under the gained type's name. A land with no
            # compiled ability at all (a basic, a dual) is the summary path's
            # as it always was: its printed types and the gained one are both
            # in ``effective_produced_mana``.
            gained = self._gained_type_mana(land)
            if gained and (
                (mana_ability is None and _priced)
                or (
                    mana_ability is not None
                    and chosen_color in gained
                    # …and not what the ability about to run makes. This asked
                    # the printed summary, which lists what *every* ability of
                    # the land makes: an Underground River under the Blanket,
                    # asked for {B}, was "already a {B} land" by its painful
                    # second ability and so ran its first, for {C}.
                    and chosen_color not in self._default_tap_symbols(
                        land, mana_ability
                    )
                )
            ):
                mana_ability = None
                gained_symbol = chosen_color if chosen_color in gained else gained[0]

        # CR 701.26a's event, announced by the one tap seam. City of Brass
        # ("Whenever this land becomes tapped, it deals 1 damage to you") and
        # Psychic Venom ("Whenever enchanted land becomes tapped…") each used to
        # be dispatched by a hand-written pass here, which meant each fired on
        # *this* tapper and on none of the others — an Icy Manipulator, an
        # attack cost, or any of the other places `become_tapped` is called.
        # Both are ordinary `permanent_becomes_tapped` triggers now, so they go
        # on the stack (CR 603.3) from wherever the tap happens.
        self.become_tapped(land)

        def produce() -> str:
            # **The land's own compiled mana ability, when it has one.** This used
            # to add exactly one symbol chosen from `produced_mana`, which is right
            # for every land in the 1993-94 base sets and for the dual cycles — all
            # of them produce one mana — and silently wrong for the first land that
            # does not. Antiquities brought four: Mishra's Workshop prints
            # {C}{C}{C} and paid one, and the Urza's cycle's assembly could not be
            # read at all because the amount is behind a condition.
            #
            # `produced_mana` is Scryfall's summary of *which symbols* a land can
            # make; it says nothing about how many or under what condition. The
            # compiled ability says both, so it is what runs, and the summary is
            # the fallback for a basic whose whole ability line is CR 305.6
            # reminder text and compiles to nothing.
            # "One mana of any type **that land produced**" (Mana Flare) reads this
            # at the bottom of the method, and the compiled-ability branch below
            # writes into the pool without ever naming a symbol — so it was left
            # unbound there, and a Mana Flare over any land whose mana ability
            # compiles (every dual, every filter land) raised `UnboundLocalError`
            # instead of adding mana. Seeded with the colour the seat asked for,
            # which is the answer for a land that offers a choice and the closest
            # honest one for a land that does not.
            mana_symbol = chosen_color
            if mana_ability is not None:
                instruction = mana_ability
                # The colour arrives the way the activation path delivers it,
                # so "tap Badlands for {R}" keeps meaning what it did; the
                # handler ignores it unless the printed clause offers a choice.
                #
                # **A colour, or nothing.** The request is a mana *symbol*, and
                # {C} is one a land may be asked for — it is what
                # ``_land_payment_colors`` answers for every land under Ritual
                # of Subdual, so it is what the AI's plan and the client's
                # colour fan send. Injected as the answer to "{R} or {G}" it
                # reached the handler's colour normaliser, which raises: a dual
                # land under a colourless swap ended the game with a
                # ValueError. Colourless is not a colour (CR 105.1), so a land
                # asked for it has been told nothing about its choice and makes
                # its first printed alternative — which the swap then replaces.
                asked_color = self._chosen_mana_color(chosen_color)
                if asked_color:
                    instruction = dataclasses.replace(
                        instruction,
                        payload={**instruction.payload, "color": asked_color},
                    )
                # …and to the "Choose a color" step of a two-sentence spelling
                # ("Choose a color. Add one mana of that color."), which the
                # outer injection cannot reach — CR 605.3b, one helper for both
                # inline sites (``mana_payment.answer_color_choices``).
                instruction = answer_color_choices(
                    instruction, self._chosen_mana_color(chosen_color)
                )
                self._execute_oracle_instruction(
                    instruction,
                    OracleExecutionContext(
                        caster=player,
                        target=player,
                        card=land.card,
                        source_permanent=land,
                        # The colour again, on the key the activation path carries
                        # it on (``new_color``), because the payload injection above
                        # rewrites only the *outer* instruction: a painland's "Add
                        # {R} or {G}. This land deals 1 damage to you." lowers to a
                        # ``sequence`` whose nested add step never sees it, and asked
                        # for {G} would make the first printed alternative.
                        choices={"new_color": self._chosen_mana_color(chosen_color)},
                    ),
                )
            else:
                produced = land.effective_produced_mana
                if gained_symbol is not None:
                    mana_symbol = gained_symbol
                elif produced:
                    # A colour swapped away is still a legitimate request: the seat
                    # names the symbol the land prints and the swap decides what
                    # comes out, so the request is mapped through the swaps rather
                    # than dropped. `produced[0]` is the answer only when nothing
                    # maps — a land asked for a colour it never made.
                    mana_symbol = land.produced_symbol_for(chosen_color) or produced[0]
                else:
                    symbols = land.basic_land_mana
                    if symbols:
                        mana_symbol = symbols[0]
                player.mana_pool[mana_symbol] = player.mana_pool.get(mana_symbol, 0) + 1
            return mana_symbol

        # CR 106.12: what follows is the event — the record, the replacement
        # over the production, the production itself and everything that
        # watches a land tapped for mana. One method, because this is one of
        # three roads to it (:meth:`_land_tapped_for_mana`).
        self._land_tapped_for_mana(
            player_index, land, chosen_color, produce, land_name=land_name,
        )
        return True
