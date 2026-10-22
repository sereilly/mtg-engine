"""What one printed additional-cost sentence charges (CR 601.2b, 601.2f-h).

The table ``engine/cast_costs.py`` is asked through. The two cost objects the
cast path reads (``OptionalManaCost``, ``AdditionalCost``), the two sentences a
cost is printed in ("As an additional cost to cast this spell, …" and "You may
cast this card from your graveyard by paying … in addition to paying its other
costs"), the clause vocabulary both share, each clause mapped onto the field it
fills (``_COST_CLAUSES``, in the order it is tried), and the readers that turn
one printed line into one ``AdditionalCost`` (``additional_cost_for_line``).

Split out of ``engine/cast_costs.py`` at the 2,000-line cap, beneath it:
buyback's and kicker's rewrites are read back through these readers, and
``engine/cast_costs.py`` keeps the per-card entry points
(``additional_costs``, ``cast_cost_claims_line``, ``unread_cost_sentence``) and
still exports every name in its ``__all__``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .oracle_types import _NUMBER_WORDS
from .subject_filters import filter_head_noun


@dataclass(frozen=True)
class OptionalManaCost:
    """One "you may pay {1}{R}" an additional-cost sentence offers (CR 601.2b).

    Its own object rather than a field on :class:`AdditionalCost` because a
    single printed sentence offers **several** of them independently — Primitive
    Justice's "you may pay {1}{R} and/or {1}{G} any number of times" is two
    offers, each paid however many times the caster likes, and the effect reads
    the two counts apart. One field could hold one count; two cards in this set
    need two.

    ``symbols`` is the canonical spelling ``mana_cost_label`` produces, so the
    key a resolution reads back by ("for each additional **{1}{R}** you paid")
    is the same string however the card printed it. ``repeatable`` is CR 601.2b's
    "any number of times": without it the offer may be taken once.
    """

    symbols: str
    repeatable: bool = False
    #: "Kicker **{X}**" (Verdeloth the Ancient) / "Kicker **{X}{2}**" (Kangee,
    #: Aerie Keeper). How many {X} symbols the offer prints. CR 107.3a names
    #: "an additional cost with an {X} in it" as one of the four places an X is
    #: announced, and this is the mana-shaped one: the caster who takes the
    #: offer names a number and pays that much generic mana per symbol on top of
    #: :attr:`cost`.
    #:
    #: A count rather than a flag for the reason a mana cost's own X is counted
    #: (CR 107.3: "{X}{X}" is twice X), and its own field rather than a symbol
    #: inside :attr:`cost` because ``mana_cost_from_symbols`` -- the one reader
    #: that turns printed symbols into a payment -- refuses an X outright, and
    #: has to: a cost read with its X silently worth nothing is a spell cast for
    #: less than it prints.
    x_count: int = 0
    #: "**Spend only colored mana on X. No more than one mana of each color may
    #: be spent this way.**" (Emblazoned Golem, beside its "Kicker {X}".) A
    #: restriction on how this offer's X may be *paid* (CR 601.2h), printed on
    #: its own line and folded onto the offer it restricts by
    #: :func:`_additional_costs_of_text` -- the line names "X" and the offer is
    #: where this card's X lives.
    #:
    #: A flag on the offer rather than a table the cast path consults by card
    #: text, because there are four readers of "what does this offer cost at
    #: X?" (the payment, the picker's ceiling, the AI's sizing and the offer
    #: prompt) and each already holds the offer: :meth:`x_colorings` is the one
    #: answer they share, so a reader that prices the offer cannot do it
    #: without the restriction.
    x_one_of_each_color: bool = False

    def x_colorings(self, x_value: int | None) -> "tuple[tuple[str, ...], ...] | None":
        """Every set of colours the announced X may be paid with, or None when
        this offer's X is unrestricted.

        "No more than one mana of each color" over "only colored mana" is a
        choice of *which* colours, one unit each -- the payer's (CR 601.2h),
        and this engine has no channel to ask it, so every choice is returned
        and the reader takes the first the pool can pay
        (``pool_payment._x_color_allocations`` is the same arrangement for "Spend
        only black and/or red mana on X"). In WUBRG order, which is the only
        order the card's text is neutral about.

        **Empty when no choice exists**: there are five colours, so an X above
        five has no payment at all, which is how the sentence bounds X without
        ever saying so. ``((),)`` -- one choice, of nothing -- at X = 0.
        """
        if not (self.x_count and self.x_one_of_each_color):
            return None
        from itertools import combinations

        from .mana_spending import COLOR_SYMBOLS as FIVE_COLORS

        wanted = self.x_count * max(0, int(x_value or 0))
        return tuple(combinations(FIVE_COLORS, wanted))

    def payments_at(self, x_value: int | None) -> tuple[dict[str, int], ...]:
        """Every way one payment of this offer may be made at the announced X,
        as symbol dicts -- :meth:`cost_at` for an offer whose X any mana pays,
        and one dict per :meth:`x_colorings` choice for one it does not, the X
        written as the coloured pips that choice spends.

        What a *planner* asks (the picker's ceiling, the AI's sizing): "is any
        of these payable from this pool and these lands?" The payment itself
        does not go through the pips -- see ``pool_payment._pay_cast_cost`` for why
        a pip is not quite "a unit of that colour" -- but it walks the same
        choices in the same order.
        """
        colorings = self.x_colorings(x_value)
        if colorings is None:
            return (self.cost_at(x_value),)
        payments = []
        for coloring in colorings:
            charged = dict(self.cost)
            for symbol in coloring:
                charged[symbol] = charged.get(symbol, 0) + 1
            payments.append(charged)
        return tuple(payments)

    @property
    def cost(self) -> dict[str, int]:
        """What one payment of this offer costs **before any X**, as the symbol
        dict every payment in this engine speaks. Empty for a bare ``{X}``."""
        from .mana_payment import mana_cost_from_symbols

        printed = self.symbols.replace("{X}", "") if self.x_count else self.symbols
        return mana_cost_from_symbols(printed) or {}

    def cost_at(self, x_value: int | None) -> dict[str, int]:
        """What one payment costs with the announced X folded in (CR 107.3a).

        The one place an offer's X becomes mana, read by the charge
        (``casting.queue_from_hand``) and the picker's ceiling
        (``legality_cast_spec.cast_cost_offers``) alike. An unannounced X is 0, which is
        CR 107.3's reading of a number nobody named and the only one that
        cannot charge a player for mana they did not agree to.
        """
        charged = dict(self.cost)
        if self.x_count:
            extra = self.x_count * max(0, int(x_value or 0))
            if extra:
                charged["generic"] = charged.get("generic", 0) + extra
        return charged


@dataclass(frozen=True)
class AdditionalCost:
    """One printed additional cost.

    ``sacrifice_filter`` is the noun phrase the sacrifice must match, in the same
    payload vocabulary ``ActivatedAbilityCost.sacrifice_filter`` and the
    forced-sacrifice prompt use — the *choice* is the same on all three sides
    (CR 601.2b and CR 602.2b are the same announcement step), so what may pay
    should not be described three ways. ``None`` means "no sacrifice", never
    "anything": an empty filter would let the payment be a land.
    """

    phrase: str
    sacrifice_filter: dict | None = None
    #: "…, sacrifice **two** creatures." (Phyrexian Tribute.) How many the
    #: printed cost eats, in the same field ``ActivatedAbilityCost`` carries it
    #: in and for the same reason CR 601.2b and CR 602.2b share a vocabulary:
    #: what may pay a printed sacrifice, and how many of it, is one question
    #: wherever the sacrifice is printed.
    #:
    #: Its own field rather than a count folded into the phrase, because the
    #: *number* is the whole of what makes such a cost unpayable: one creature
    #: is no more a payment than none (CR 601.2h), and a gate that asked only
    #: "is there a creature?" would admit the cast and then charge one -- a
    #: spell cast for less than it prints, which is this module's whole subject.
    sacrifice_count: int = 1
    #: "As an additional cost to cast this spell, **sacrifice all permanents
    #: you control**." (Kaervek's Spite.) A *quantifier*, not a count, and so
    #: its own field: "all" names however many the board holds, where
    #: ``sacrifice_count`` names a number the card printed -- folding the two
    #: together would price a board of one permanent and a board of six the
    #: same.
    #:
    #: It is also the one sacrifice cost that may name no card type. Every
    #: other one must (``_chargeable_object``'s last paragraph: an unnamed cost
    #: would let the payment eat a land the card never named), and "all" is
    #: exactly the phrase for which that reasoning inverts -- the payment eats
    #: everything *because the card says so*, and there is no cheaper reading
    #: for a dropped narrowing to slide onto. It is never part of
    #: ``_unpayable_additional_cost`` for the same reason: a board of nothing
    #: pays this cost in full (CR 601.2h), which is what makes Kaervek's Spite
    #: castable off an empty board.
    sacrifice_all_filter: dict | None = None
    #: "..., and **discard your hand**." (Kaervek's Spite.) The same field name
    #: ``ActivatedAbilityCost`` carries for the identical printed clause, so
    #: what a whole-hand discard costs is one answer wherever it is printed
    #: (CR 601.2b and CR 602.2b are one announcement step). Always payable -- an
    #: empty hand pays it -- so it too is outside the CR 601.2h gate.
    discard_whole_hand: bool = False
    #: "As an additional cost to cast this spell, **return X Swamps you control
    #: to their owner's hand**." (Infernal Harvest.) The same noun-phrase
    #: vocabulary the sacrifice one field up carries, one destination over --
    #: and its own field for the reason ``exile_filter`` is separate from
    #: ``sacrifice_filter``: a returned permanent is a *card in its owner's
    #: hand* afterwards, a sacrificed one is in a graveyard, and the cost is
    #: repayable where the others are not. ``None`` means "no return", never
    #: "anything".
    return_filter: dict | None = None
    #: How many the return eats. A printed number ("return two Swamps"), or the
    #: announced X when :attr:`return_count_x` is set.
    return_count: int = 1
    #: "…return **X** Swamps you control…" (Infernal Harvest.) CR 107.3a: an X
    #: in an **additional** cost is announced by the caster as part of casting,
    #: exactly as an X in a mana cost is -- and Infernal Harvest's X is *only*
    #: here, since its printed mana cost is {1}{B} with no {X} at all. A
    #: separate flag rather than a sentinel in ``return_count``, for the reason
    #: ``pay_life_x`` is separate from ``pay_life``: every reader of that field
    #: is arithmetic, and a string in it would be charged as garbage.
    #:
    #: **The client could not make that announcement, and the reason was one
    #: string.** ``web/static/app.js``'s "does this card need an X?" test was a
    #: substring probe of the printed *mana cost*, which for Infernal Harvest is
    #: ``{1}{B}`` -- so a human seat was offered no X box and the cast fell
    #: back to the 0 an unmade CR 107.3a announcement reads as here: legal
    #: (0 is a choice) and useless. The probe
    #: was one place short of CR 107.3a, which names four ("a mana cost,
    #: alternative cost, additional cost, and/or activation cost"), and Fire
    #: Covenant ({1}{B}{R}, "pay X life") lost the same way in the **shipped**
    #: pool. :func:`cast_announces_x` is now the one reader of that question and
    #: ``legality_cast_spec.cast_target_spec`` puts its answer on the picker's spec.
    return_count_x: bool = False
    #: "As an additional cost to cast this spell, **exile a creature you
    #: control**." (Soul Exchange.) The same noun-phrase vocabulary one field
    #: up, one zone over -- and its own field for the reason
    #: ``ActivatedAbilityCost`` keeps the two apart: an exiled permanent is
    #: still a card somewhere afterwards, a sacrificed one is in a graveyard,
    #: and a spell may read back either. ``None`` means "no exile", never
    #: "anything".
    exile_filter: dict | None = None
    #: "As an additional cost to cast this spell, **exile X creature cards from
    #: your graveyard**." (Haunting Misery.) The same verb one zone over, and
    #: its own pair of fields for the reason ``exile_filter`` above is separate
    #: from ``sacrifice_filter``: that one enumerates the caster's own
    #: *battlefield* and this one enumerates their *graveyard*, so a shared
    #: field would be read by the wrong enumerator on whichever card was
    #: written second -- and a card in a graveyard answers a strictly different
    #: matcher (CR 613.1: it has no computed characteristics at all).
    #:
    #: ``None`` means "no such cost", never "any card", for
    #: ``sacrifice_filter``'s reason: an empty filter would let the payment eat
    #: a land the card never named.
    exile_graveyard_filter: dict | None = None
    #: How many that cost exiles -- the announced X when
    #: :attr:`exile_graveyard_count_x` is set. Beside the filter for
    #: ``sacrifice_count``'s reason: only the *number* can make such a cost
    #: unpayable, since one card is no more a payment of a three-card cost than
    #: none (CR 601.2h).
    exile_graveyard_count: int = 1
    #: "...exile **X** creature cards..." (Haunting Misery). CR 107.3a: an X in
    #: an additional cost is announced by the caster as part of casting, and
    #: Haunting Misery's printed mana cost is {1}{B}{B} with no {X} in it -- so
    #: this clause is the *only* place its X lives, exactly as Infernal
    #: Harvest's return clause is for that card. A separate flag rather than a
    #: sentinel in the count above, for ``pay_life_x``'s reason: every reader of
    #: that field is arithmetic and a string in it would be charged as garbage.
    exile_graveyard_count_x: bool = False
    discard_cards: int = 0
    #: "As an additional cost to cast this spell, discard **X** cards."
    #: (Firestorm.) CR 107.3a's fourth place an X can live, and for this card
    #: the *only* one: its printed mana cost is {R}, so the discard clause is
    #: where X is announced and the damage line spends what the announcement
    #: bought. A separate flag rather than a sentinel in the count above, for
    #: ``pay_life_x``'s reason: every reader of that field is arithmetic and a
    #: string in it would be charged as garbage.
    discard_count_x: bool = False
    #: "…, discard **a red or green card**." (Surge of Strength.) Which cards in
    #: hand may pay the discard above, as the alternatives the payer chooses
    #: between — the same tuple-of-payloads shape
    #: ``ActivatedAbilityCost.discard_filters`` carries, read by the same
    #: function (``chargeable_costs._chargeable_discard_filters``) and tested by the same
    #: matcher (``subject_filters.card_matches_any``). CR 601.2b and CR 602.2b
    #: are one announcement step, so what may pay a printed discard is one
    #: answer wherever the discard is printed.
    #:
    #: An empty tuple is the unrestricted "discard a card", where the whole hand
    #: pays — never "nothing pays", which is what a refusal means and why the
    #: reader returns None for that instead.
    discard_filters: tuple[dict, ...] = ()
    #: "Buyback—Pay 3 life, **Discard a card at random**." (Flowstone Flood.)
    #: "As an additional cost to cast this spell, **discard a card at random**."
    #: (Sonic Burst.) The same field name ``ActivatedAbilityCost`` carries for
    #: the identically printed clause, and its own flag rather than an empty
    #: ``discard_filters`` for the reason that side states: "at random" is not a
    #: narrowing of *which* cards may pay — every card in hand may — it is the
    #: removal of the payer's **choice**, and a cost the payer picks is a
    #: strictly better cost than one chance picks. The two shapes look identical
    #: in the filter list and are not.
    #:
    #: It never affects payability: the gate below counts cards, and how the
    #: card is chosen out of a hand large enough cannot make the cost unpayable
    #: (CR 601.2h).
    discard_at_random: bool = False
    #: "As an additional cost to cast this spell, **choose a creature type**."
    #: (Caller of the Hunt.) The one cost in this file that consumes **nothing**
    #: — it takes no object off a board, out of a hand or out of a graveyard —
    #: and it is a cost all the same, because CR 601.2b is where the choice is
    #: made and the card's other line reads the answer back.
    #:
    #: A flag rather than the word itself, for the reason ``pay_life_x`` is a
    #: flag: the *word* is announced per cast (CR 601.2b) and this object is
    #: compiled once per card and cached, so a chosen type stored here would be
    #: one cast's answer serving every later cast of every copy.
    #:
    #: It is never part of ``_unpayable_additional_cost``: every creature type
    #: is a legal choice, so this cost is paid on any board at all — the same
    #: reasoning ``sacrifice_all_filter`` and ``discard_whole_hand`` carry, and
    #: the reason a cost that charges nothing still has to be *claimed*: a
    #: clause this table cannot read leaves the sentence unread, and the card
    #: then reports supported with its choice never made (``unread_cost_sentence``).
    choose_creature_type: bool = False
    #: "As an additional cost to cast this spell, **choose a number between 0
    #: and 5**." (Liquid Fire.) The second cost here that consumes nothing, and
    #: a cost for ``choose_creature_type``'s reason: CR 601.2b is where the
    #: choice is made, so an opponent sees the number before responding. The
    #: value is the printed range ``(low, high)``, both ends legal.
    #:
    #: **The number rides the cast's X.** The card's other line reads it back
    #: as "where X is the chosen number", and CR 601.2b says a variable
    #: "defined in the text of the spell by a choice that player would make
    #: later in the announcement" is chosen as the spell is announced — so the
    #: number *is* the announced X (CR 107.3a), and it travels the channel an
    #: announced X already has: the wire's ``x_value``, the stack object every
    #: viewer is shown, the value a copy inherits. A second channel would be a
    #: second number for one printed letter.
    #:
    #: It charges nothing and multiplies nothing. ``_read_cost_clauses``
    #: refuses a sentence pairing the choice with a clause that prices an X, so
    #: the announced number is never also a count of cards, permanents or
    #: life; and a card whose **mana cost** prints {X} is refused at the cast
    #: (:meth:`number_refusal`'s caller), because one announcement cannot be
    #: both a price in mana and a number chosen from a range. Unlike the
    #: creature type it *can* make a cast illegal — a number outside the range
    #: is not a choice the card offers — which is :meth:`number_refusal`, asked
    #: with the other CR 601.2h gates before anything is spent.
    choose_number: tuple[int, int] | None = None
    #: "…by paying **3 life** and discarding a card" (Demonic Embrace).
    #: CR 119.4 caps a life payment at the payer's life total and CR 601.2h then
    #: makes an unpayable cost an uncastable spell, checked with
    #: the rest of the costs before anything is spent.
    pay_life: int = 0
    #: "As an additional cost to cast this spell, pay **X** life." (Fire
    #: Covenant.) A life cost whose amount is the X the caster announces
    #: (CR 601.2b, CR 107.3) rather than a printed number — a separate field
    #: rather than a sentinel in ``pay_life``, because every reader of that
    #: field is arithmetic and a string in it would be charged as garbage.
    pay_life_x: bool = False
    #: "…, **you may pay {1}{R} and/or {1}{G} any number of times**."
    #: (Primitive Justice, Taste of Paradise, Undergrowth.) CR 601.2b's
    #: *optional* additional cost, and the only one in this file that is
    #: optional at all — every field above it is a price the cast pays or is
    #: refused for. So it is never part of ``_unpayable_additional_cost``: an
    #: offer nobody takes costs nothing, and an offer taken past what the pool
    #: can pay is refused by the mana payment itself, which is where CR 601.2h
    #: puts an unpayable mana cost.
    #:
    #: A tuple because one sentence may offer several independently, and how
    #: many times each was taken is what the resolution reads back — see
    #: ``game_types.ADDITIONAL_COSTS_PAID``.
    optional_mana: tuple[OptionalManaCost, ...] = ()
    #: The zone this cost applies to, when the sentence naming it also names a
    #: zone. Demonic Embrace costs {1}{B}{B} from the hand and {1}{B}{B} plus 3
    #: life plus a card from the graveyard — the *same card*, so the cost cannot
    #: be a property of the card alone. ``None`` means every zone, which is what
    #: an "as an additional cost to cast this spell" line means.
    from_zone: str | None = None
    #: "**Buyback—Sacrifice a land**." (Constant Mists.) CR 601.2b's optional
    #: additional cost when the price is *not* mana: the key the caster's
    #: announcement names this whole cost by, or ``None`` for the ordinary
    #: mandatory cost every field above describes.
    #:
    #: Its own field rather than a member of :attr:`optional_mana`, because
    #: those are runs of symbols the cast folds into the spell's mana payment
    #: and this is a permanent ``_pay_additional_costs`` collects — one field
    #: could not hold both, and a sacrifice charged as mana is a price nobody
    #: pays. And a flag on the *cost* rather than on each clause, because the
    #: sentence it comes from is one offer: "you may sacrifice a land" is taken
    #: whole or declined whole, so there is no sentence in which one clause is
    #: optional and its neighbour is not.
    #:
    #: When set, every price this cost describes is charged only if the
    #: announcement took it — so ``_unpayable_additional_cost`` must not refuse
    #: the cast of a caster who declined (an offer is not a price, CR 601.2b),
    #: and ``_pay_additional_costs`` must not collect one.
    optional_key: str | None = None
    #: "Kicker—**{2}{B}**, Discard a creature card." (Dralnu's Pet.) The mana
    #: half of an optional price that is not *only* mana, as the canonical
    #: spelling ``mana_cost_label`` produces; empty for every other cost.
    #:
    #: Its own field rather than a member of :attr:`optional_mana`, because
    #: those are **offers** — each taken or declined on its own, each with its
    #: own key and count — and this is one clause of a single offer whose key
    #: is :attr:`optional_key`: the {2}{B} and the discard are paid together or
    #: not at all, and "kicked" is one answer. Folded into ``optional_mana`` it
    #: would be a second announcement the caster could take without the
    #: discard.
    #:
    #: Only ever set on a cost that carries an ``optional_key`` (the reader
    #: refuses the clause anywhere else): a *mandatory* additional cost in mana
    #: is a sentence no card prints, and admitting one here would charge it
    #: through a path that reads this field only for an offer that was taken.
    mana_symbols: str = ""

    @property
    def mana_cost(self) -> dict[str, int]:
        """What :attr:`mana_symbols` charges, as the symbol dict every payment
        in this engine speaks. Empty for a cost with no mana clause."""
        from .mana_payment import mana_cost_from_symbols

        return (mana_cost_from_symbols(self.mana_symbols) or {}) if self.mana_symbols else {}

    def life_charged(self, x_value: int | None) -> int:
        """How much life this cost takes, given the announced X.

        One reader for the gate and the payment, because they are the same
        question asked twice — CR 601.2h refuses the cast when the answer is
        more life than the caster has, and CR 601.2b's announcement is what
        makes the answer knowable at all. A cost that spelled X and charged the
        printed 0 is the shape this whole module exists to prevent.
        """
        if self.pay_life_x:
            return max(0, int(x_value or 0))
        return self.pay_life

    def returned_count(self, x_value: int | None) -> int:
        """How many permanents this cost returns, given the announced X.

        One reader for the gate and the payment, for :meth:`life_charged`'s
        reason one method up: CR 601.2h refuses the cast when the answer is
        more permanents than the caster controls, and CR 107.3a's announcement
        is what makes the answer knowable at all. A cost that read X and
        charged the printed 1 would be a spell cast for a fraction of its
        price -- and for Infernal Harvest, whose X *is* this cost, it would
        also make the spell's damage and its price disagree.
        """
        if self.return_count_x:
            return max(0, int(x_value or 0))
        return self.return_count

    def exiled_from_graveyard(self, x_value: int | None) -> int:
        """How many cards this cost exiles from the graveyard, given the
        announced X.

        One reader for the gate and the payment, for :meth:`life_charged`'s
        reason two methods up: CR 601.2h refuses the cast when the answer is
        more cards than the graveyard holds, and CR 107.3a's announcement is
        what makes the answer knowable at all. A cost that read X and charged
        the printed 1 would be a spell cast for a fraction of its price -- and
        for Haunting Misery, whose X *is* this cost, it would also make the
        spell's damage and its price disagree.
        """
        if self.exile_graveyard_count_x:
            return max(0, int(x_value or 0))
        return self.exile_graveyard_count

    def number_refusal(self, x_value: int | None) -> str | None:
        """Why *x_value* is not a number this cost lets its caster choose, or
        None — including for a cost that chooses no number at all.

        One reader for the gate and the picker's bounds, because they are one
        question: the range is the card's, and a picker offering what the gate
        refuses is a cast announced and then declined.

        ``None`` is **no number yet**, and refuses nothing: the castable
        highlight and the offer pricer ask the cost gate before anything is
        announced, and "is there a number this card would take?" is always
        yes. The cast itself never asks with None — it settles an unmade
        announcement to 0 first, which is what one reads as everywhere in this
        engine, so a range that excludes 0 refuses a cast that named nothing
        exactly as "X can't be 0" does one table over.
        """
        if self.choose_number is None or x_value is None:
            return None
        low, high = self.choose_number
        chosen = int(x_value)
        if low <= chosen <= high:
            return None
        return f"{chosen} is not a number between {low} and {high}"

    def discarded_count(self, x_value: int | None) -> int:
        """How many cards this cost discards, given the announced X.

        One reader for the gate and the payment, for :meth:`life_charged`'s
        reason: CR 601.2h refuses the cast when the answer is more cards than
        the hand holds, and CR 107.3a's announcement is what makes the answer
        knowable at all. A cost that read X and charged the printed 1 would be
        a spell cast for a fraction of its price -- and for Firestorm, whose X
        *is* this cost, it would also make the spell's damage and its price
        disagree, since the same X sizes both.
        """
        if self.discard_count_x:
            return max(0, int(x_value or 0))
        return self.discard_cards

    def describe(self) -> str:
        parts = []
        for offer in self.optional_mana:
            parts.append(
                f"you may pay {offer.symbols}"
                + (" any number of times" if offer.repeatable else "")
            )
        if self.mana_symbols:
            parts.append(f"pay {self.mana_symbols}")
        if self.sacrifice_all_filter is not None:
            parts.append(
                f"sacrifice all {filter_head_noun(self.sacrifice_all_filter)}s "
                f"you control"
            )
        if self.sacrifice_filter is not None:
            noun = filter_head_noun(self.sacrifice_filter)
            parts.append(
                f"sacrifice a {noun}" if self.sacrifice_count == 1
                else f"sacrifice {self.sacrifice_count} {noun}s"
            )
        if self.discard_whole_hand:
            parts.append("discard your hand")
        if self.return_filter is not None:
            noun = filter_head_noun(self.return_filter)
            how_many = "X" if self.return_count_x else str(self.return_count)
            parts.append(
                f"return {how_many} {noun}"
                + ("" if how_many == "1" else "s")
                + " you control to their owner's hand"
            )
        if self.exile_filter is not None:
            parts.append(f"exile a {filter_head_noun(self.exile_filter)}")
        if self.exile_graveyard_filter is not None:
            noun = graveyard_card_noun(self.exile_graveyard_filter)
            how_many = (
                "X" if self.exile_graveyard_count_x
                else str(self.exile_graveyard_count)
            )
            parts.append(
                f"exile {how_many} {noun}"
                + ("" if how_many == "1" else "s")
                + " from your graveyard"
            )
        if self.choose_creature_type:
            parts.append("choose a creature type")
        if self.choose_number is not None:
            parts.append(
                "choose a number between "
                f"{self.choose_number[0]} and {self.choose_number[1]}"
            )
        if self.pay_life_x:
            parts.append("pay X life")
        elif self.pay_life:
            parts.append(f"pay {self.pay_life} life")
        if self.discard_cards:
            named = filter_head_noun(self.discard_filters[0]) if self.discard_filters else "card"
            how_many = "X" if self.discard_count_x else str(self.discard_cards)
            parts.append(
                f"discard {how_many} {named}(s)"
                + (" at random" if self.discard_at_random else "")
            )
        return " and ".join(parts) or "no additional cost"


# Canonical lowercase phrases, matched against a whole normalized line. Both
# shapes the pool prints; a third goes here beside them.
#: "As an additional cost to cast this spell, <clauses>." (CR 601.2b.)
#:
#: This was a table of two whole *phrases*, each of which wrote the preamble out
#: again — so the only thing that varied was the clause after the comma, and a
#: clause nobody had listed was a line the table did not read. Fumarole's "pay 3
#: life" is one, and the way it showed up is worth keeping: the card had no
#: other blocker, so the moment its second line parsed it compiled *supported*
#: and cast for free. A preamble plus a clause vocabulary is the same shape
#: ``_SELF_PERMISSION_COSTS`` one function down already had.
_ADDITIONAL_COST_PREAMBLE = re.compile(
    r"^as an additional cost to cast this spell, (?P<costs>.+)$"
)


#: "You may cast this card from your <zone> by paying <costs> in addition to
#: paying its other costs." The costs half of the sentence
#: ``cast_permissions.self_permission_zone`` reads the zone half of.
_SELF_PERMISSION_COSTS = re.compile(
    r"^you may cast this card from your (?P<zone>graveyard|exile) by paying "
    r"(?P<costs>.+?) in addition to paying its other costs$"
)

#: The cost clauses either sentence may list, each mapped to the field it fills.
#: A clause outside this set makes the whole line unread — the card then reports
#: unsupported, or keeps the line in the parse-coverage backlog, rather than
#: being castable at a discount, which is the direction a cost must never drift
#: in.
#:
#: **One table for both sentences**, which print the same costs in two
#: grammatical forms: "as an additional cost …, **pay 3 life**" and "…by
#: **paying 3 life** in addition to paying its other costs". Two tables would be
#: two answers to "what can this engine charge", and the one that grew slower
#: would decide which cards were free.
#:
#: "pay X life" (Fire Covenant) is here now, and the note that used to say why
#: it was not is worth keeping: X is announced as the spell is cast (CR 601.2b)
#: and this engine used to run the affordability gate *before* resolving it, so
#: a clause here would have charged zero. That ordering was the bug, not the
#: reason — the card was already `supported` on its damage line alone, so the
#: cost was not being deferred, it was not being charged at all. The gate now
#: runs after X is announced and before any mana is spent, which is where
#: CR 601.2h puts it.
_COST_CLAUSES: tuple[tuple[re.Pattern[str], str], ...] = (
    # "…, **you may pay {1}{R} and/or {1}{G} any number of times**." (Primitive
    # Justice.) CR 601.2b's optional additional cost. First in the table because
    # it is the one clause whose text begins with a word another row could
    # claim, and because it is the only *optional* one — every row below it is a
    # price, and reading this as one would refuse the cast of a caster who
    # simply declined the offer.
    #
    # The whole run of symbols is captured together: ``_read_cost_clauses``
    # splits its sentence on ", " and " and ", and "and/or" contains neither, so
    # a two-offer sentence arrives here intact and is split by the reader below.
    (
        re.compile(
            r"^you may pay (?P<mana>\{.+?\})(?P<repeated> any number of times)?$"
        ),
        "optional_mana",
    ),
    # "…, **choose a creature type**." (Caller of the Hunt.) CR 601.2b's
    # choice-shaped additional cost: it charges nothing, and it is a cost
    # because the rule says the choice is made *here* — the card's other line
    # ("creatures of the chosen type") reads the answer back off the permanent,
    # and an entry-time reading would make a countered spell one that never
    # chose and a reanimated creature one that chose anyway.
    #
    # Above the life rows only in source order; no row in this table shares a
    # first word with it.
    (re.compile(r"^choose a creature type$"), "choose_creature_type"),
    # "…, **choose a number between 0 and 5**." (Liquid Fire.) The other
    # choice-shaped cost, beside the first. Both ends are printed digits in the
    # one printing there is; a spelled-out number matches nothing and leaves
    # the sentence unread, which is the loud direction.
    #
    # The clause contains the word this table's reader splits a sentence on,
    # so ``_split_cost_clauses`` keeps a "between N and M" whole.
    (
        re.compile(r"^choose a number between (?P<low>\d+) and (?P<high>\d+)$"),
        "choose_number",
    ),
    # "Kicker—**{2}{B}**, Discard a creature card." (Dralnu's Pet.) A run of
    # mana symbols as *one clause among several* of an optional price — the
    # reader admits it only under an ``optional_key`` (see
    # ``AdditionalCost.mana_symbols``). A sentence that is nothing but "you may
    # pay {2}{B}" never reaches this row: the offer row at the top of the table
    # claims it whole, which is what keeps an ordinary mana kicker an offer
    # with a count rather than a clause.
    (re.compile(r"^(?:pay )?(?P<mana>(?:\{[^{}]+\})+)$"), "mana"),
    (re.compile(r"^(?:pay )?x life$"), "pay_life_x"),
    (re.compile(r"^(?:pay )?(\d+) life$"), "pay_life"),
    # "discard a card", and its **narrowed** spelling: "discard a red or green
    # card" (Surge of Strength). This row used to be the literal
    # ``(?:a|one) card``, so a printed narrowing matched nothing at all — and a
    # clause this table cannot read leaves the whole sentence unread, which for
    # a card whose *other* line compiles means it reports ``supported`` and is
    # cast **without the cost**. Surge of Strength was exactly that: the discard
    # was printed, claimed by nobody, and never charged.
    #
    # The noun phrase goes through the same reader an activation cost's discard
    # does (``chargeable_costs._chargeable_discard_filters``), so what may pay a printed
    # discard is one answer wherever the discard is printed. Only the singular
    # is admitted, for the reason ``grammar/costs.py`` states on the activation
    # side: a counted "discard two cards" is a shape nothing charges, and
    # admitting it would describe a payment that never happens.
    # "..., and **discard your hand**." (Kaervek's Spite.) Above the counted
    # discard below, whose noun phrase must begin with an article and so cannot
    # claim these words -- the order is what keeps the two from ever being one
    # question, not what resolves a fight between them.
    (re.compile(r"^(?:discard|discarding) your hand$"), "discard_whole_hand"),
    # "…, discard **X** cards." (Firestorm.) CR 107.3a's X in an additional
    # cost, the same shape the return and the graveyard exile above already
    # carry -- and, as for both of those, the *only* place this card's X lives:
    # its printed mana cost is {R}. It had a row of its own here, which handed
    # the noun after the X to the filter reader whole, so "discard X cards **at
    # random**" (Devastating Dreams) was a noun phrase called "cards at random"
    # and the sentence went unread. It is the row below now: the X is a count
    # and "at random" a rider, and ``read_discard_clause`` reads both where
    # they are printed. The count is announced rather than printed, and the
    # payment collects exactly what was announced.
    # "…, **discard two cards**." (Forbid, through CR 702.27a's rewrite of its
    # buyback line.) "…, **discard a card at random**." (Flowstone Flood, Sonic
    # Burst.) One catch-all row read by :func:`read_discard_clause`, which is
    # the arrangement the sacrifice and the return rows below already have and
    # is here for their reason: the count and the "at random" rider are printed
    # around the noun phrase, so splitting them off in the row's regex would put
    # a second reading of the phrase beside ``_chargeable_discard_filters``.
    #
    # This row used to be the literal ``(?:a|an|one) .+``, whose note said a
    # counted discard "is a shape nothing charges". That was true of the *cast*
    # path when it was written and is no longer: ``_pay_additional_costs``
    # already loops ``discarded_count(x_value)`` times, because the announced X
    # of Firestorm needed exactly that loop — so a printed count charges through
    # the same code an announced one does. The reader refuses whatever it cannot
    # charge, which is what keeps the widening from admitting a free cast.
    (re.compile(r"^(?:discard|discarding) (?P<noun>.+)$"), "discard"),
    # The **noun phrase is read, not spelled out**. This row was
    # ``sacrifice a creature`` as a literal, so Goblin Grenade's "sacrifice a
    # **Goblin**" matched nothing at all -- and a clause the table cannot read
    # leaves the line unclaimed, which for a card whose *other* line compiles
    # means it reports ``supported`` and is cast without its real cost. The
    # phrase goes through the same reader an activation cost's does
    # (``chargeable_costs.chargeable_sacrifice_payload``), so what may pay a printed
    # cost is one answer wherever the cost is printed.
    # "..., **return X Swamps you control to their owner's hand**." (Infernal
    # Harvest.) The destination is part of the clause and not an afterthought:
    # this is the only zone the payment can reach, and a sentence naming
    # another one must refuse rather than be charged against the hand. The
    # apostrophe is either kind because the ingested text prints the curly one.
    (
        re.compile(
            r"^(?:return|returning) (?P<noun>.+) to (?:their|its) "
            r"owner(?:s(?:'|’)|(?:'|’)s)? hands?$"
        ),
        "return",
    ),
    # "..., **sacrifice all permanents you control**." (Kaervek's Spite.) Read
    # **before** the counted sacrifice below, which would otherwise claim these
    # words through its catch-all noun and then refuse them: "all permanents
    # you control" pins no card type, and every counted sacrifice must
    # (``_chargeable_object``). A row that refuses is a row that costs the card
    # its support, so the specific quantifier goes first.
    (
        re.compile(r"^(?:sacrifice|sacrificing) (?P<noun>all .+)$"),
        "sacrifice_all",
    ),
    (re.compile(r"^(?:sacrifice|sacrificing) (?P<noun>.+)$"), "sacrifice"),
    # "…, **exile a creature you control**." (Soul Exchange.) The same clause
    # one zone over, gated by the exile charger's own reader for the same
    # reason -- two readers of one phrase drift, and the direction they drift
    # in is a cost nobody pays.
    # "..., **exile X creature cards from your graveyard**." (Haunting
    # Misery.) Read **before** the battlefield exile below, whose catch-all
    # noun would claim these words and then refuse them:
    # ``_chargeable_object`` admits one zone only, and a row that refuses is
    # a row that costs the card its support. The zone is part of the clause
    # rather than an afterthought, exactly as the return row states one
    # field over.
    (
        re.compile(r"^(?:exile|exiling) (?P<noun>.+ from your graveyard)$"),
        "exile_graveyard",
    ),
    (re.compile(r"^(?:exile|exiling) (?P<noun>.+)$"), "exile"),
)


def read_discard_clause(
    phrase: str,
) -> tuple[tuple[dict, ...], int, bool, bool] | None:
    """What "discard <noun phrase>" charges — ``(filters, count, at_random,
    count_x)`` — or None when the payment path cannot collect it.

    The count splits off the front exactly as :func:`read_sacrifice_clause`
    splits one, and the ``at random`` rider comes off the **back** before the
    noun parser sees the phrase at all — the same order, and for the same
    reason, that ``oracle._chargeable_activation_cost`` strips it on the
    activation side (CR 601.2b and CR 602.2b are one announcement step). "At
    random" is not part of what the card must *be*; it says who picks. Left in,
    the noun parser refuses "a card at random" and the whole cost sentence goes
    unread, which for a card whose other line compiles is a spell cast for free.

    The alternatives go through ``chargeable_costs._chargeable_discard_filters``, the one
    reader an activation cost's discard already uses, so what may pay a printed
    discard is one answer wherever the discard is printed. An empty tuple from
    it is the unrestricted "discard a card" and a real answer; None is the
    refusal, and it propagates.

    A count of zero or one falls through to the singular, which is where
    "a card" has always been read: ``_NUMBER_WORDS`` maps "a", "an" and "one" to
    1, so an article can never be mistaken for a count.

    **An X is a count too** (*count_x*; CR 107.3a's additional cost with an X
    in it): "discard **X** cards" (Firestorm, the Dreams) and "discard X cards
    **at random**" (Devastating Dreams) are this clause with its two modifiers,
    the count and the rider, each read where it is printed. The X had its own
    row in ``_COST_CLAUSES`` that handed the noun after it to the filter reader
    whole, so "cards at random" was a noun phrase nobody could read and
    Devastating Dreams' price was charged by nothing. The count reported for an
    X is 1 -- the field every "is there a discard?" truth test reads -- and how
    many cards are actually charged is ``AdditionalCost.discarded_count``.
    """
    from .chargeable_costs import _chargeable_discard_filters

    rest = phrase.strip()
    at_random = rest.endswith(" at random")
    if at_random:
        rest = rest[: -len(" at random")].strip()
    count, _, tail = rest.partition(" ")
    if count == "x" and tail:
        narrowed = _chargeable_discard_filters(tail)
        return None if narrowed is None else (narrowed, 1, at_random, True)
    number = int(count) if count.isdigit() else _NUMBER_WORDS.get(count, 0)
    if number >= 2 and tail:
        narrowed = _chargeable_discard_filters(tail)
        return None if narrowed is None else (narrowed, number, at_random, False)
    narrowed = _chargeable_discard_filters(rest)
    return None if narrowed is None else (narrowed, 1, at_random, False)


def read_sacrifice_clause(phrase: str) -> tuple[dict, int] | None:
    """What "sacrifice <noun phrase>" charges — ``(filter, count)`` — or None.

    "…, sacrifice **two** creatures." (Phyrexian Tribute.) The count is printed
    in front of the noun phrase, which leaves that phrase the bare plural the
    noun parser reads with ``plural=True`` -- the same split ``oracle`` makes
    for the identically shaped activation cost, with the same table reading the
    word. Anything that is not a number of two or more falls through to the
    singular, which is where "a creature" has always been read:
    ``_NUMBER_WORDS`` maps "a", "an" and "one" to 1, so the article cannot be
    mistaken for a count.

    **One reader for both cost kinds.** CR 601.2b's additional cost and
    CR 118.9's alternative cost print this clause identically — "sacrifice a
    Goblin", "sacrifice two Mountains" — and ``engine/alternative_costs.py``
    calls this rather than spelling the split out again, for the reason
    ``_chargeable_object`` states one level down: two readers of one printed
    phrase drift, and the direction a *cost* drifts in is a price charged more
    widely, or not at all, than the card prints.

    "all" is deliberately absent. "Sacrifice **all** permanents you control"
    (Kaervek's Spite) is a different quantifier, not a count, and it reaches
    :func:`read_sacrifice_all_clause` below — folding it in here would make a
    board of one permanent and a board of six the same printed price.
    """
    count, _, rest = phrase.partition(" ")
    number = int(count) if count.isdigit() else _NUMBER_WORDS.get(count, 0)
    if number >= 2 and rest:
        described = _chargeable_object(rest, "sacrifice", plural=True)
        return None if described is None else (described, number)
    described = _chargeable_object(phrase, "sacrifice")
    return None if described is None else (described, 1)


def read_return_clause(phrase: str) -> tuple[dict, int, bool] | None:
    """What "return <noun phrase> to their owner's hand" charges, as
    ``(filter, count, count_is_x)``, or None.

    The count is split off the front exactly as :func:`read_sacrifice_clause`
    splits one, with the one addition CR 107.3a asks for: an **X** may stand
    where the number does, and the caster announces its value as part of
    casting. Infernal Harvest is the whole reason -- its printed mana cost is
    {1}{B} with no {X} in it, so this clause is the only place its X lives, and
    a reader that only understood digits would have charged one Swamp for a
    spell that deals however much damage the caster announced.

    The noun phrase goes through the **sacrifice** charger, not a reader of its
    own. Both name a permanent on the payer's own battlefield -- which is the
    whole of what a charger has to answer -- and they differ only in where the
    permanent goes afterwards, which is the payment's business. Two readers of
    one phrase drift, and the direction a cost drifts in is a price charged
    more widely, or not at all, than the card prints.
    """
    count, _, rest = phrase.partition(" ")
    if count == "x" and rest:
        described = _chargeable_object(rest, "sacrifice", plural=True)
        return None if described is None else (described, 0, True)
    number = int(count) if count.isdigit() else _NUMBER_WORDS.get(count, 0)
    if number >= 2 and rest:
        described = _chargeable_object(rest, "sacrifice", plural=True)
        return None if described is None else (described, number, False)
    described = _chargeable_object(phrase, "sacrifice")
    return None if described is None else (described, 1, False)


def graveyard_card_noun(described: dict | None) -> str:
    """What a graveyard-exile cost's cards are called in a sentence: "creature
    card" for a phrase naming a type, plain "card" for one naming none
    (Skeletal Scrying). ``filter_head_noun`` answers "permanent" for the
    second, which is right for a board and wrong for a pile."""
    kind = (described or {}).get("type_filter")
    return f"{kind} card" if isinstance(kind, str) else "card"


def read_graveyard_exile_clause(phrase: str) -> tuple[dict, int, bool] | None:
    """What "exile <n> <noun phrase> from your graveyard" charges, as
    ``(filter, count, count_is_x)``, or None.

    "As an additional cost to cast this spell, exile **X creature cards from
    your graveyard**." (Haunting Misery.) The count splits off the front exactly
    as :func:`read_return_clause` splits one, X included -- CR 107.3a lets an X
    stand where the number does, and Haunting Misery's printed mana cost is
    {1}{B}{B}, so this clause is the only place its X lives.

    The noun phrase goes through the **card** charger
    (``chargeable_card_filter``), not the permanent one every other clause in
    this file uses, and that is the whole reason this is its own reader: a card
    in a graveyard has no computed characteristics (CR 613.1), so
    ``_card_matches_filter`` answers a strictly different question from
    ``subject_matches``, and a key one can test the other silently drops.

    Both halves of the zone are **checked**, never assumed: a phrase naming a
    library, or somebody else's graveyard, is a payment this cast path has no
    enumerator for, and reading it as the caster's own pile would charge a cost
    out of the wrong zone.
    """
    import dataclasses

    from .grammar import ast
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.lowering._common import chargeable_card_filter
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream

    count, _, rest = phrase.partition(" ")
    if count == "x" and rest:
        number, is_x = 0, True
    else:
        number = int(count) if count.isdigit() else _NUMBER_WORDS.get(count, 0)
        is_x = False
        if number < 2:
            # No count printed at all: the whole phrase is the noun, which is
            # the singular "exile a creature card from your graveyard". The
            # article stays on it, and the noun parser refuses it -- the pool
            # prints no such additional cost, and admitting one here would be a
            # reading nothing tests.
            number, rest = 1, phrase
    if not rest:
        return None
    lexed = tokenize(rest.strip())
    if not lexed.tokens:
        return None
    stream = TokenStream(lexed.tokens, lexed.normalized)
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        return None
    if not stream.exhausted:
        return None
    if described.zone != "graveyard":
        return None
    owner = described.zone_owner
    if owner is None or getattr(owner, "kind", None) != "you":
        return None
    # Back to the *unstated* zone, which is ``ObjectFilter``'s default and is
    # not ``None``: the charger's key check compares every field against the
    # dataclass default, so a ``None`` here reads as a narrowing it cannot
    # honour and refuses the phrase this function has already read.
    unstated = ast.ObjectFilter()
    stripped = dataclasses.replace(
        described, zone=unstated.zone, zone_owner=unstated.zone_owner
    )
    carried = chargeable_card_filter(stripped)
    if carried is None:
        return None
    # "…, exile X **cards** from your graveyard." (Skeletal Scrying.) The
    # empty reduction is a real answer — "any card in your graveyard" — and it
    # is what the card prints. This refused every phrase that named no type, on
    # the ground that an *unnamed* cost lets the payment eat any card in the
    # pile; here any card in the pile is the printed price, and the refusal
    # cost the card its support ("printed cost nothing charges") rather than
    # protecting anything. What that rule guards is a narrowing the reduction
    # **lost**, and ``chargeable_card_filter`` returns None for a key the card
    # matcher cannot test rather than dropping it — the argument
    # ``chargeable_costs.cost_object_is_chargeable`` makes for "Sacrifice a permanent".
    return carried, (0 if is_x else number), is_x


def read_sacrifice_all_clause(phrase: str) -> dict | None:
    """What "sacrifice **all** <noun phrase>" charges, as a filter, or None.

    "As an additional cost to cast this spell, sacrifice all permanents you
    control" (Kaervek's Spite). The quantifier is the price: what is charged is
    every permanent the phrase names, however many that is, so there is no
    count to read and nothing for :func:`read_sacrifice_clause` to do with it.

    This is the one sacrifice cost admitted with **no card type named**.
    ``_chargeable_object`` refuses those, because "sacrifice a permanent" would
    let the payment eat a land the card never mentioned and the payer would
    take the cheapest thing on their board -- but under "all" there is no
    cheapest thing, and the un-narrowed phrase is the *most expensive* reading
    rather than the least. What is still required is that the phrase be
    testable: it goes through the same ``chargeable_sacrifice_payload`` reader
    every other sacrifice cost does, so a narrowing ``subject_matches`` cannot
    answer refuses the line instead of being silently dropped -- which would
    charge more than the card prints, this file's failure in the other
    direction.
    """
    from .grammar import subject_filter_payload
    from .chargeable_costs import chargeable_sacrifice_payload

    rest = phrase[len("all "):].strip() if phrase.startswith("all ") else ""
    if not rest:
        return None
    described = subject_filter_payload(rest, plural=True)
    if described is None:
        return None
    if described.get("zone") not in (None, "battlefield"):
        return None
    return chargeable_sacrifice_payload(described)


#: "As an additional cost to cast this spell, **you may** sacrifice a land."
#: CR 601.2b's optional additional cost in its non-mana form — the sentence
#: ``expand_buyback_line`` writes for Constant Mists.
#:
#: A prefix on the whole sentence rather than a row in ``_COST_CLAUSES``,
#: because "may" governs every clause after it: a caster who declines pays none
#: of them, and a row would have made it a property of the one clause it
#: matched.
_OPTIONAL_COST_CLAUSE = re.compile(r"^you may (?P<rest>.+)$")


def _read_cost_clauses(costs: str) -> dict | None:
    """The fields the clauses of one cost sentence fill, or None.

    **Every** clause must be read or the whole sentence is refused: one this
    table cannot charge would otherwise be dropped, and a dropped cost is a
    spell cast for less than it prints. That is the same all-or-nothing rule
    ``upkeep_costs.upkeep_cost_from_phrase`` states for CR 702.24a's cost, and
    it is here for the same reason.
    """
    fields: dict = {
        "pay_life": 0, "pay_life_x": False, "discard_cards": 0,
        "discard_filters": (), "discard_count_x": False,
        "discard_at_random": False,
        "sacrifice_filter": None, "sacrifice_count": 1, "exile_filter": None,
        "exile_graveyard_filter": None, "exile_graveyard_count": 1,
        "exile_graveyard_count_x": False,
        "sacrifice_all_filter": None, "discard_whole_hand": False,
        "return_filter": None, "return_count": 1, "return_count_x": False,
        "optional_mana": (),
        "optional_key": None,
        "choose_creature_type": False,
        "choose_number": None,
        "mana_symbols": "",
    }
    # CR 601.2b's optional non-mana price. Tested **after** the mana-offer row,
    # which claims "you may pay {1}{R} …" whole: stripping the prefix first
    # would leave "pay {1}{R}" for a table whose only mana row wants the words
    # back, and the sentence would refuse. So the specific reading wins and this
    # only sees a sentence it did not claim.
    sentence = costs.strip()
    if _COST_CLAUSES[0][0].match(sentence) is None:
        offered = _OPTIONAL_COST_CLAUSE.match(sentence)
        if offered is not None:
            # The key is the clause text itself, which is what makes the
            # announcement's key and the rewrite's key the same string by
            # construction: ``_buyback_line_offer`` reads it back off the
            # ``AdditionalCost`` this builds rather than normalizing the printed
            # line a second time.
            fields["optional_key"] = offered.group("rest").strip()
            costs = fields["optional_key"]
    for clause in _split_cost_clauses(costs):
        clause = clause.strip()
        if not clause:
            continue
        for pattern, field in _COST_CLAUSES:
            found = pattern.match(clause)
            if found is None:
                continue
            if field == "optional_mana":
                offers = _optional_mana_offers(
                    found.group("mana"), repeatable=bool(found.group("repeated")),
                )
                if offers is None:
                    # A symbol the payment cannot spend ({X}, a hybrid) or a
                    # second offer of the same cost, which would give the
                    # read-back one key for two counts. Refused whole, this
                    # function's rule everywhere else.
                    return None
                fields["optional_mana"] = fields["optional_mana"] + offers
            elif field == "choose_creature_type":
                fields["choose_creature_type"] = True
            elif field == "choose_number":
                low, high = int(found.group("low")), int(found.group("high"))
                if fields["choose_number"] is not None or low > high:
                    # Two choices would be two numbers on one X, and an empty
                    # range is a cost nobody can pay. Refused whole.
                    return None
                fields["choose_number"] = (low, high)
            elif field == "mana":
                from .mana_payment import (mana_cost_from_symbols,
                                           mana_cost_label)

                if fields["optional_key"] is None or fields["mana_symbols"]:
                    # A mana clause outside an offer (no card prints a
                    # mandatory one, and nothing would charge it), or a second
                    # one, which one field cannot hold. Refused whole.
                    return None
                if _X_SYMBOL.search(found.group("mana")):
                    # An {X} in a compound price has nowhere to be announced:
                    # the X machinery is the mana offers' (``x_count``).
                    return None
                symbols = mana_cost_from_symbols(found.group("mana"))
                if not symbols:
                    return None
                fields["mana_symbols"] = mana_cost_label(symbols)
            elif field == "pay_life_x":
                fields["pay_life_x"] = True
            elif field == "pay_life":
                fields["pay_life"] += int(found.group(1))
            elif field == "discard":
                if fields["discard_cards"]:
                    # A second discard clause would need a second alternatives
                    # list, and one field cannot hold two: folded together they
                    # would read as a union, which is a strictly *cheaper* cost
                    # than the two narrowings printed. Refused whole, which is
                    # this function's rule everywhere else.
                    return None
                read = read_discard_clause(found.group("noun"))
                if read is None:
                    return None
                # For an X, ``discard_cards`` stays the printed *count* -- 1,
                # because an announced X of zero is still a cost this card
                # prints and every "is there a discard on this cast?" reader is
                # a truth test on this field. How many cards are actually
                # charged is ``discarded_count(x_value)``, the one reader the
                # gate and the payment share.
                (
                    fields["discard_filters"],
                    fields["discard_cards"],
                    fields["discard_at_random"],
                    fields["discard_count_x"],
                ) = read
            elif field == "return":
                if fields["return_filter"] is not None:
                    # Two return clauses would need two filters and one field
                    # cannot hold two; folded together they read as a union,
                    # which is a strictly cheaper cost than the two printed.
                    return None
                read = read_return_clause(found.group("noun"))
                if read is None:
                    return None
                (
                    fields["return_filter"],
                    fields["return_count"],
                    fields["return_count_x"],
                ) = read
            elif field == "exile_graveyard":
                if fields["exile_graveyard_filter"] is not None:
                    # Two such clauses would need two filters and one field
                    # cannot hold two; folded together they read as a union,
                    # which is a strictly cheaper cost than the two printed.
                    return None
                read = read_graveyard_exile_clause(found.group("noun"))
                if read is None:
                    return None
                (
                    fields["exile_graveyard_filter"],
                    fields["exile_graveyard_count"],
                    fields["exile_graveyard_count_x"],
                ) = read
            elif field == "discard_whole_hand":
                fields["discard_whole_hand"] = True
            elif field == "sacrifice_all":
                if fields["sacrifice_all_filter"] is not None:
                    # Two "all" clauses would need two filters and one field
                    # cannot hold two; folded together they read as a union,
                    # which is a strictly cheaper cost than the two printed.
                    return None
                described = read_sacrifice_all_clause(found.group("noun"))
                if described is None:
                    return None
                fields["sacrifice_all_filter"] = described
            elif field == "sacrifice":
                read = read_sacrifice_clause(found.group("noun"))
                if read is None:
                    return None
                fields["sacrifice_filter"], fields["sacrifice_count"] = read
            else:
                described = _chargeable_object(found.group("noun"), field)
                if described is None:
                    # The phrase names something the payment path cannot
                    # enumerate or cannot test. The whole sentence is refused
                    # rather than charged as the part that was read — the
                    # all-or-nothing rule this function already states, and the
                    # one that keeps a card unsupported instead of cheap.
                    return None
                fields[f"{field}_filter"] = described
            break
        else:
            return None
    if fields["choose_number"] is not None and (
        fields["pay_life_x"] or fields["return_count_x"]
        or fields["exile_graveyard_count_x"] or fields["discard_count_x"]
        or fields["optional_mana"] or fields["optional_key"] is not None
    ):
        # The chosen number is the cast's X (see ``choose_number``). Beside a
        # clause that *prices* an X it would be charged as that many cards,
        # permanents or life — a number the card says to choose, spent as a
        # count it never printed. Inside an offer it would be a choice made
        # only by a caster who took the offer, which the range gate cannot
        # ask. No card prints either; refused whole.
        return None
    return fields


def _split_cost_clauses(costs: str) -> list[str]:
    """The clauses of one cost sentence: split on commas and on "and".

    Except the "and" **inside** a printed range — "choose a number between 0
    and 5" is one clause, and cut at that word it is two that no row reads,
    which refuses the whole sentence. The separator is kept only when the
    piece in front of it ends "between <number>" and the piece behind it opens
    with a number; every other sentence splits exactly as it did.
    """
    pieces = _COST_CLAUSE_SPLIT.split(costs)
    clauses = [pieces[0]]
    for separator, piece in zip(pieces[1::2], pieces[2::2]):
        if (
            separator.strip() == "and"
            and re.search(r"\bbetween \d+$", clauses[-1])
            and re.match(r"\d+\b", piece)
        ):
            clauses[-1] = f"{clauses[-1]} and {piece}"
        else:
            clauses.append(piece)
    return clauses


#: One printed {X}, either case (the cost sentences are read lowercased).
_X_SYMBOL = re.compile(r"\{x\}", re.IGNORECASE)


def _optional_mana_offers(
    printed: str, *, repeatable: bool
) -> tuple[OptionalManaCost, ...] | None:
    """The offers ``{1}{R} and/or {1}{G}`` names, or None.

    "and/or" is the only conjunction the pool prints here, and it is read as
    *independent* offers rather than as one cost: Primitive Justice's caster may
    pay {1}{R} twice and {1}{G} not at all, and the two counts are read back
    separately. A conjunction this does not know refuses the sentence, which
    leaves the card unsupported rather than castable for a cost nobody charged.

    Each run goes through ``mana_cost_from_symbols`` — the one reader that turns
    printed symbols into a payment — and is spelled back out by
    ``mana_cost_label``, so the key the effect reads back by is canonical rather
    than however this card happened to print it.

    Two offers of the *same* cost refuse: they would share one read-back key and
    one count, so the second would silently double the first.
    """
    from .mana_payment import mana_cost_from_symbols, mana_cost_label

    runs = [run.strip() for run in re.split(r"\s*and/or\s*", printed.strip())]
    offers: list[OptionalManaCost] = []
    for run in runs:
        if not run:
            return None
        if re.fullmatch(r"(?:\{[^{}]+\})+", run) is None:
            # Anything but a bare run of symbols — a word left over from a
            # conjunction this does not read, most likely. Refused rather than
            # charged as the part that matched.
            return None
        # "you may pay **{X}{2}**" -- CR 702.33a's rewrite of Kangee's kicker.
        # The X symbols are counted off the run and the rest goes through the
        # one reader below, which refuses an X on purpose (see
        # ``OptionalManaCost.x_count``). Either case: both preambles are
        # matched against a lowercased line.
        x_count = len(_X_SYMBOL.findall(run))
        rest = _X_SYMBOL.sub("", run)
        if x_count and repeatable:
            # "{X} any number of times" would need an X per payment and the
            # announcement carries one. No card prints it; refused rather than
            # charged as one X shared between payments.
            return None
        symbols = mana_cost_from_symbols(rest) if rest else None
        if not symbols and not (x_count and not rest):
            return None
        # The canonical key: X first, as Magic prints a mana cost, then
        # ``mana_cost_label``'s spelling of whatever is not X.
        label = "{X}" * x_count + (mana_cost_label(symbols) if symbols else "")
        if any(offer.symbols == label for offer in offers):
            return None
        offers.append(
            OptionalManaCost(label, repeatable=repeatable, x_count=x_count)
        )
    return tuple(offers) or None


def _chargeable_object(
    phrase: str, action: str, *, plural: bool = False
) -> dict | None:
    """The filter payload a "sacrifice/exile <noun phrase>" cost charges, or None.

    The **charger's own** reading, not a second one: ``engine/oracle.py`` holds
    ``chargeable_sacrifice_payload`` and ``chargeable_exile_payload`` because an
    activation cost asks the same question (CR 601.2b and CR 602.2b are one
    announcement step), and a phrase admitted here that they would refuse is a
    cost this table claims and nothing collects.

    **One zone**, because that is all ``_pay_additional_costs`` can reach: both
    verbs take a permanent off the caster's own battlefield. A phrase naming a
    graveyard or a hand is already refused by ``subject_filter_payload``, whose
    whole job is to read a phrase describing a *permanent*; the zone check below
    is the belt to that braces, so a later widening of that reader cannot
    silently admit a cost this table has nothing to charge.

    Imported inside the function for the reason every other reader of these does:
    ``engine/oracle.py`` imports ``engine/cast_costs.py``, and so this module,
    at load time, so the edge back is taken at call time.

    *plural* is what a printed count leaves behind: "sacrifice two **creatures**"
    is the bare plural, and the noun parser reads a plural only when it is told
    to -- so the flag travels with the count rather than the reader guessing
    from the word, which is how "creatures" and "creature" would come to be one
    phrase.
    """
    from .grammar import subject_filter_payload
    from .chargeable_costs import (chargeable_exile_payload,
                                   chargeable_sacrifice_payload,
                                   cost_object_is_chargeable)

    described = subject_filter_payload(phrase.strip(), plural=plural)
    if described is None:
        return None
    if described.get("zone") not in (None, "battlefield"):
        return None
    reader = (
        chargeable_sacrifice_payload if action == "sacrifice"
        else chargeable_exile_payload
    )
    carried = reader(described)
    if not cost_object_is_chargeable(carried):
        # A phrase the payment path has no enumeration for. Through the same
        # reader ``grammar/costs.py`` asks for an activation cost, because
        # CR 601.2b and CR 602.2b are one announcement step: a phrase one
        # admits and the other refuses is a cost charged on one card and not on
        # the next.
        return None
    return carried


def _self_permission_cost(line: str) -> AdditionalCost | None:
    """The additional costs a self-granted zone permission charges, or None.

    Every clause must be read or the line is refused: a sentence that named a
    cost this table cannot charge would otherwise let the card be cast from the
    graveyard for less than it prints.
    """
    match = _SELF_PERMISSION_COSTS.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    fields = _read_cost_clauses(match.group("costs"))
    if fields is None:
        return None
    return AdditionalCost(match.group(0), from_zone=match.group("zone"), **fields)


def _printed_additional_cost(line: str) -> AdditionalCost | None:
    """The costs "As an additional cost to cast this spell, …" charges, or None.

    Unmarked by zone, which is what the sentence means: the cost applies
    wherever the spell is cast from (see ``AdditionalCost.from_zone``).
    """
    match = _ADDITIONAL_COST_PREAMBLE.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    fields = _read_cost_clauses(match.group("costs"))
    if fields is None:
        return None
    return AdditionalCost(match.group(0), **fields)


def additional_cost_for_line(line: str) -> AdditionalCost | None:
    """The cost *line* states, or None when it states none.

    Matched on the line's whole text (minus a trailing period) rather than as a
    substring, because a substring match is how the whitelist this replaced came
    to claim things it did not implement.
    """
    return _printed_additional_cost(line) or _self_permission_cost(line)


#: Where one clause of a printed cost list ends, as ``_read_cost_clauses``
#: splits it. Named once so the rewrite and the reader cannot disagree about
#: what a clause is.
_COST_CLAUSE_SPLIT = re.compile(r"(,\s*|\s+and\s+)")
