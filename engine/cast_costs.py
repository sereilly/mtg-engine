"""Text-keyed *additional* costs a spell prints in its own text (CR 601.2b).

The same model as ``cast_restrictions.py``, and for the same reason: "As an
additional cost to cast this spell, sacrifice a creature" means the same thing
on every card that prints it, so it is a table keyed by the canonical phrase
rather than four per-card hooks. A new card printed with a known phrase needs no
registration at all.

**What this replaced was not a gap, it was worse than one.** The phrase sat in
``SUPPORTED_SPELL_PATTERNS`` — a substring whitelist whose match produces a
marker instruction with no handler — so Village Rites compiled to "draw two
cards" plus a no-op, reported ``supported``, and cast **for free**: the cost was
claimed, never paid, and nothing in the engine knew the difference. Thrill of
Possibility's discard did not even get the marker. Alpha's Sacrifice and
Metamorphosis escaped only because a *card hook* folded the cost into their
effect, which is why the general form had never been needed.

A cost is not an effect, so none of this is an instruction. The compiler asks
this table whether a line is a cost (which is what stops the line being reported
"too complex"), and ``queue_from_hand`` asks it twice more: once before any
payment, because CR 601.2h says an unpayable cost can't be paid and CR 601.2h's
failure is *the spell can't be cast*, and once after, to perform it.
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from .oracle_types import _NUMBER_WORDS, compilation_cache
from .subject_filters import filter_head_noun

if TYPE_CHECKING:
    from .models import CardDefinition


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

    @property
    def cost(self) -> dict[str, int]:
        """What one payment of this offer costs, as the symbol dict every
        payment in this engine speaks."""
        from .mana_payment import mana_cost_from_symbols

        return mana_cost_from_symbols(self.symbols) or {}


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
    #: ``legality.cast_target_spec`` puts its answer on the picker's spec.
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
    #: function (``oracle._chargeable_discard_filters``) and tested by the same
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
            noun = filter_head_noun(self.exile_graveyard_filter)
            how_many = (
                "X" if self.exile_graveyard_count_x
                else str(self.exile_graveyard_count)
            )
            parts.append(
                f"exile {how_many} {noun} card"
                + ("" if how_many == "1" else "s")
                + " from your graveyard"
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
    # does (``oracle._chargeable_discard_filters``), so what may pay a printed
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
    # its printed mana cost is {R}. Read **before** the singular row below,
    # whose noun must open with an article and so cannot claim these words; the
    # order is what keeps the two from ever being one question.
    #
    # Only an X, deliberately. A printed "discard two cards" is admitted
    # nowhere, which is the note the singular row already carries: a counted
    # discard the payment cannot collect would describe a payment that never
    # happens. Here the count is not printed at all -- it is announced, and the
    # payment collects exactly what was announced.
    (re.compile(r"^(?:discard|discarding) x (?P<noun>.+)$"), "discard_x"),
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
    # (``oracle.chargeable_sacrifice_payload``), so what may pay a printed
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
) -> tuple[tuple[dict, ...], int, bool] | None:
    """What "discard <noun phrase>" charges — ``(filters, count, at_random)`` —
    or None when the payment path cannot collect it.

    The count splits off the front exactly as :func:`read_sacrifice_clause`
    splits one, and the ``at random`` rider comes off the **back** before the
    noun parser sees the phrase at all — the same order, and for the same
    reason, that ``oracle._chargeable_activation_cost`` strips it on the
    activation side (CR 601.2b and CR 602.2b are one announcement step). "At
    random" is not part of what the card must *be*; it says who picks. Left in,
    the noun parser refuses "a card at random" and the whole cost sentence goes
    unread, which for a card whose other line compiles is a spell cast for free.

    The alternatives go through ``oracle._chargeable_discard_filters``, the one
    reader an activation cost's discard already uses, so what may pay a printed
    discard is one answer wherever the discard is printed. An empty tuple from
    it is the unrestricted "discard a card" and a real answer; None is the
    refusal, and it propagates.

    A count of zero or one falls through to the singular, which is where
    "a card" has always been read: ``_NUMBER_WORDS`` maps "a", "an" and "one" to
    1, so an article can never be mistaken for a count.
    """
    from .oracle import _chargeable_discard_filters

    rest = phrase.strip()
    at_random = rest.endswith(" at random")
    if at_random:
        rest = rest[: -len(" at random")].strip()
    count, _, tail = rest.partition(" ")
    number = int(count) if count.isdigit() else _NUMBER_WORDS.get(count, 0)
    if number >= 2 and tail:
        narrowed = _chargeable_discard_filters(tail)
        return None if narrowed is None else (narrowed, number, at_random)
    narrowed = _chargeable_discard_filters(rest)
    return None if narrowed is None else (narrowed, 1, at_random)


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
    if carried is None or not (
        carried.get("type_filter") or carried.get("subtype_filter")
    ):
        # An *unnamed* cost would let the payment eat any card in the pile --
        # the same narrowing every other clause in this file makes, and for its
        # reason: the payer would give up the cheapest thing they had.
        return None
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
    from .oracle import chargeable_sacrifice_payload

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
    for clause in re.split(r",\s*|\s+and\s+", costs):
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
            elif field == "pay_life_x":
                fields["pay_life_x"] = True
            elif field == "pay_life":
                fields["pay_life"] += int(found.group(1))
            elif field in ("discard", "discard_x"):
                from .oracle import _chargeable_discard_filters

                if fields["discard_cards"]:
                    # A second discard clause would need a second alternatives
                    # list, and one field cannot hold two: folded together they
                    # would read as a union, which is a strictly *cheaper* cost
                    # than the two narrowings printed. Refused whole, which is
                    # this function's rule everywhere else.
                    return None
                if field == "discard_x":
                    narrowed = _chargeable_discard_filters(found.group("noun"))
                    if narrowed is None:
                        return None
                    # ``discard_cards`` stays the printed *count* — 1 here,
                    # because an announced X of zero is still a cost this card
                    # prints and every "is there a discard on this cast?" reader
                    # is a truth test on this field. How many cards are actually
                    # charged is ``discarded_count(x_value)``, the one reader
                    # the gate and the payment share.
                    fields["discard_cards"] += 1
                    fields["discard_filters"] = narrowed
                    fields["discard_count_x"] = True
                else:
                    read = read_discard_clause(found.group("noun"))
                    if read is None:
                        return None
                    (
                        fields["discard_filters"],
                        fields["discard_cards"],
                        fields["discard_at_random"],
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
    return fields


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
        symbols = mana_cost_from_symbols(run)
        if not symbols:
            return None
        label = mana_cost_label(symbols)
        if any(offer.symbols == label for offer in offers):
            return None
        offers.append(OptionalManaCost(label, repeatable=repeatable))
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
    ``engine/oracle.py`` imports this module at load time, so the edge back is
    taken at call time.

    *plural* is what a printed count leaves behind: "sacrifice two **creatures**"
    is the bare plural, and the noun parser reads a plural only when it is told
    to -- so the flag travels with the count rather than the reader guessing
    from the word, which is how "creatures" and "creature" would come to be one
    phrase.
    """
    from .grammar import subject_filter_payload
    from .oracle import (chargeable_exile_payload, chargeable_sacrifice_payload,
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


# ---------------------------------------------------------------------------
# Buyback (CR 702.27)
# ---------------------------------------------------------------------------
#
# **A rewrite, not a flag**, for exactly ``engine/equipment.py``'s reason.
# CR 702.27a says "Buyback [cost]" *means* two static abilities that function
# while the spell is on the stack:
#
#   "You may pay an additional [cost] as you cast this spell" and "If the
#   buyback cost was paid, put this spell into its owner's hand instead of
#   into that player's graveyard as it resolves."
#
# The first of those is a sentence this table already reads in full, so the
# keyword line is rewritten into it before any line is classified
# (:func:`expand_buyback_lines`, composed into ``oracle.expand_ability_lines``)
# and from there nothing downstream knows the word: ``_read_cost_clauses``
# reads the offer, ``legality.cast_cost_offers`` prices it against the pool and
# the untapped lands, ``web/static/app.js``'s cast-offer prompt asks for it, and
# ``casting._optional_cost_announcement`` records how many times it was taken.
#
# The **second** static ability is the half none of that machinery had, and it
# is implemented at the one seam a resolving spell leaves the stack through
# (``mixins/stack/resolution._bin_spell_card``), asked through
# :func:`buyback_paid` below. The claim and the implementation cannot drift
# because they are the *same reader*: a card whose keyword line was rewritten
# into an offer is exactly a card :func:`buyback_cost` names a cost for, so the
# hand-return applies to every card the cost was charged on and to no other.

#: "Buyback {3}", "Buyback {1}{U}". The cost is a run of mana symbols taken
#: from the printed line so a coloured pip keeps its letter, exactly as
#: ``equipment._EQUIP_LINE`` takes an equip cost.
_BUYBACK_LINE = re.compile(
    r"^buyback\s+(?P<cost>(?:\{[^{}]+\})+)$", re.IGNORECASE
)

#: Any line that *is* a buyback keyword line, readable or not. The wider shape
#: is what the support gate asks (:func:`unread_cost_sentence`), so a printing
#: this file cannot read — a buyback whose cost is not mana, say — is reported
#: as an unimplemented cost rather than falling through to a gate that never
#: heard of the keyword and casting the spell for its printed mana alone.
#:
#: **What follows the word has to be a cost**, and the width is kept by not
#: asking whether it is a cost this file can *charge*: CR 702.27a is
#: "Buyback [cost]", and every printing of one opens its cost with a mana
#: symbol or with the em dash a non-mana cost is printed behind. So a
#: "Buyback {X}" nobody can pay still matches here and is still reported.
#:
#: This was a bare "^buyback" word-boundary probe until Memory Crystal, whose
#: line -- "Buyback costs cost {2} less." -- is not a keyword line at all but a
#: static ability *about* buyback costs, read in full by
#: ``engine/cost_modifiers.py``. The prefix claimed it, the rewrite could not
#: read it, and the card was reported as a cost nothing charges: a gate refusing
#: a card another table implements, which is the one direction this gate is not
#: for. The plural noun after the keyword is what says so, and a cost never
#: begins with one.
_BUYBACK_SHAPE = re.compile(r"^buyback\s*(?:[—–-]|\{)", re.IGNORECASE)

#: "**Buyback—Sacrifice a land**." (Constant Mists.) CR 702.27's cost is any
#: cost, not a run of mana symbols, and the printed form for a non-mana one puts
#: it after an em dash rather than after a space. Every other buyback in the
#: pool is mana; this shape is the one the keyword's rewrite could not read, so
#: the card was refused by the support gate rather than cast for its mana alone.
_BUYBACK_COST_LINE = re.compile(
    r"^buyback\s*[—–-]\s*(?P<cost>.+)$", re.IGNORECASE
)

_BUYBACK_REMINDER = re.compile(r"\([^)]*\)")

#: CR 702.27a's first static ability, spelled as the sentence
#: ``_ADDITIONAL_COST_PREAMBLE`` above already reads.
BUYBACK_RULES_TEXT = (
    "As an additional cost to cast this spell, you may pay {cost}."
)

#: The same static ability when the cost is not mana. "Pay" is the mana verb, so
#: the printed clause carries its own ("sacrifice a land") and the rewrite only
#: supplies the preamble and CR 601.2b's "may".
BUYBACK_COST_RULES_TEXT = (
    "As an additional cost to cast this spell, you may {cost}."
)


#: Where one clause of a printed cost list ends, as ``_read_cost_clauses``
#: splits it. Named once so the rewrite and the reader cannot disagree about
#: what a clause is.
_COST_CLAUSE_SPLIT = re.compile(r"(,\s*|\s+and\s+)")


def _lowered_clauses(printed: str) -> str:
    """*printed* with the first letter of each clause lowercased.

    Only the first letter of each, never the whole word and never the whole
    clause: a printed subtype ("sacrifice a **Goblin**") is read by the noun
    parser with its case intact, and a wholesale lowercasing would eat it.
    """
    pieces = _COST_CLAUSE_SPLIT.split(printed)
    return "".join(
        piece if index % 2 else piece[:1].lower() + piece[1:]
        for index, piece in enumerate(pieces)
    )


def _buyback_line_offer(line: str) -> tuple[str, str] | None:
    """``(announcement key, rules sentence)`` for one buyback line, or None.

    The key is what ``optional_cost_payments`` is keyed by and what
    :func:`buyback_paid` reads back, so it must be *one* string on both sides.
    For a mana cost it is ``mana_cost_label``'s canonical spelling, the same one
    ``_optional_mana_offers`` gives the rewritten sentence. For a non-mana cost
    it is read straight back off the :class:`AdditionalCost` the rewritten
    sentence produces — not normalized a second time here, because a second
    normalization is a second answer, and the two disagreeing is a card that
    charged its buyback and went to the graveyard anyway.

    A non-mana cost the table cannot charge returns None, which leaves
    :func:`unread_cost_sentence` reporting the card rather than casting it for
    its printed mana with a price nobody was offered.
    """
    from .mana_payment import mana_cost_from_symbols, mana_cost_label

    stripped = " ".join(_BUYBACK_REMINDER.sub("", line or "").split())
    stripped = stripped.strip().rstrip(".")
    match = _BUYBACK_LINE.match(stripped)
    if match is not None:
        symbols = mana_cost_from_symbols(match.group("cost"))
        if not symbols:
            return None
        label = mana_cost_label(symbols)
        return label, BUYBACK_RULES_TEXT.format(cost=label)
    match = _BUYBACK_COST_LINE.match(stripped)
    if match is None:
        return None
    # The printed clause opens a line, so it is capitalized ("Sacrifice a
    # land"); mid-sentence it is not. Only the first letter is touched — a
    # wholesale lowercasing would eat a printed subtype ("sacrifice a Goblin"),
    # which the noun reader needs the case of.
    #
    # **Every clause, not only the first.** A buyback cost is a *list* — "Pay 3
    # life, Discard a card at random" (Flowstone Flood) — and Magic capitalizes
    # each item of it, because each opens where a sentence would. Lowering only
    # the leading letter of the whole line left "Discard" capitalized in the
    # middle of the rewritten sentence, where ``_COST_CLAUSES``' rows are
    # lowercase and match nothing: the clause went unread and, by
    # ``_read_cost_clauses``' all-or-nothing rule, took the whole cost with it.
    # The split is the same one that reader splits on, so a clause boundary
    # cannot mean two things.
    clause = match.group("cost").strip().rstrip(".")
    sentence = BUYBACK_COST_RULES_TEXT.format(cost=_lowered_clauses(clause))
    read = _printed_additional_cost(sentence)
    if read is None or read.optional_key is None:
        return None
    return read.optional_key, sentence


def _buyback_line_cost(line: str) -> str | None:
    """The canonical key one printed buyback line's offer is announced by, or
    None.

    Canonical for :func:`_buyback_line_offer`'s reason: this string is the key
    the announcement is recorded under and the key :func:`buyback_paid` reads it
    back by, and two spellings of one cost would make the read-back miss a
    payment that was really made.
    """
    offer = _buyback_line_offer(line)
    return None if offer is None else offer[0]


def is_buyback_line(line: str) -> bool:
    """Whether *line* is a printed buyback keyword line, readable or not."""
    stripped = _BUYBACK_REMINDER.sub("", line or "").strip()
    return _BUYBACK_SHAPE.match(stripped) is not None


def expand_buyback_line(line: str) -> str | None:
    """The CR 702.27a rules text for one printed buyback line, or None."""
    offer = _buyback_line_offer(line)
    return None if offer is None else offer[1]


def expand_buyback_lines(oracle_text: str) -> str:
    """*oracle_text* with every buyback keyword line rewritten to its rules text.

    Text without one is returned unchanged, so applying this to every card costs
    a substring test. Applied by the compiler before any line is classified —
    beside ``expand_equip_lines`` and for its reason: what the compiler reads
    and what every other reader of a card's lines reads must be one text.
    """
    if not oracle_text or "uyback" not in oracle_text:
        return oracle_text
    return "\n".join(
        expand_buyback_line(line) or line for line in oracle_text.split("\n")
    )


def buyback_cost(oracle_text: str) -> str | None:
    """The canonical symbols *oracle_text*'s buyback keyword offers, or None.

    Read off the **printed** text, which is what a resolving spell's
    ``CardDefinition`` still carries: the rewrite happens inside the compiler
    and nothing writes it back onto the card.
    """
    for line in (oracle_text or "").split("\n"):
        cost = _buyback_line_cost(line)
        if cost is not None:
            return cost
    return None


def buyback_paid(card: CardDefinition, choices: dict | None) -> bool:
    """Whether this cast of *card* paid its buyback cost (CR 702.27a).

    *choices* is the resolving stack item's own record — the pool is empty by
    resolution (CR 500.5) and the announcement is long over, so
    ``additional_costs_paid`` is the only place the answer survives, exactly as
    it is for "for each additional {1}{R} you paid".

    False for a card printing no buyback, which is every card but twelve: this
    is asked at every spell's resolution.
    """
    cost = buyback_cost(getattr(card, "oracle_text", "") or "")
    if cost is None:
        return False
    paid = (choices or {}).get("additional_costs_paid") or {}
    try:
        return int(paid.get(cost, 0) or 0) > 0
    except (TypeError, ValueError):
        return False


@compilation_cache
@lru_cache(maxsize=None)
def _additional_costs_of_text(
    oracle_text: str, card_name: str, legendary: bool
) -> tuple[AdditionalCost, ...]:
    """:func:`additional_costs` keyed on what it actually reads.

    Cached because it is asked of every card in every hand on every poll
    (``legality.cast_cost_offers``) and now runs the whole rewrite pass to
    answer — and because the answer is a pure function of exactly the three
    arguments ``expand_ability_lines`` takes.

    ``@compilation_cache`` because that pass *is* part of the compiler: a caller
    that stubs the grammar out and puts it back leaves this holding whatever the
    stub said otherwise, which is the shape ``clear_compilation_caches`` exists
    for.
    """
    from .oracle import expand_ability_lines

    lines = expand_ability_lines(
        oracle_text or "", card_name=card_name or None, legendary=legendary
    ).splitlines()
    return tuple(
        cost
        for line in lines
        if (cost := additional_cost_for_line(line)) is not None
    )


def additional_costs(card: CardDefinition) -> tuple[AdditionalCost, ...]:
    """Every additional cost *card* prints, in printed order.

    Read off ``expand_ability_lines``'s text rather than off ``oracle_text``,
    which is CLAUDE.md's rule that every reader of a card's lines starts from
    that function — and this file is one of the readers it names. Buyback
    (CR 702.27a) is *defined* as one of these costs and reaches this table only
    as the rewrite's sentence, so a reader that split the printed text would see
    a buyback card with no additional cost at all and charge nothing: this
    module's own failure, one rewrite later.
    """
    return _additional_costs_of_text(
        card.oracle_text or "",
        getattr(card, "name", "") or "",
        bool(getattr(card, "is_legendary", False)),
    )


def costs_charged_from(
    card: CardDefinition, from_zone: str
) -> tuple[AdditionalCost, ...]:
    """The additional costs *card* is charged for a cast leaving *from_zone*.

    The zone test ``queue_from_hand`` and ``targeting._cast_cost_picker`` both
    make, written once: a cost naming a zone is a price for casting from *that*
    zone (Demonic Embrace's graveyard price), so a reader that took the card
    alone would describe a cast nobody is being charged for.
    """
    return tuple(
        cost
        for cost in additional_costs(card)
        if cost.from_zone is None or cost.from_zone == from_zone
    )


def cast_announces_x(card: CardDefinition, *, from_zone: str = "hand") -> bool:
    """Whether casting *card* from *from_zone* makes its controller announce a
    value for X (CR 107.3a).

    **The whole of CR 107.3a's list, which is the point.** The rule reads "a
    mana cost, alternative cost, additional cost, and/or activation cost with an
    {X}, [-X], or X in it" -- four places, of which ``web/static/app.js`` asked
    only the first, as a substring probe of the printed mana-cost string. Fire
    Covenant's is ``{1}{B}{R}`` and Infernal Harvest's is ``{1}{B}``: neither
    prints an {X} anywhere, because both spell their X in an *additional* cost
    ("pay X life", "return X Swamps you control to their owner's hand"). So the
    browser offered no X box, the cast took the 0 an unmade CR 107.3a
    announcement reads as here, and two spells that are entirely about X
    resolved doing nothing at all -- legal,
    since 0 is a choice, and useless.

    Here rather than beside either reader for the reason
    ``oracle_types.cost_target_count`` gives one module over: the picker is a
    *third* reader of a question the gate and the payment already ask
    (``AdditionalCost.life_charged`` / ``returned_count`` are the other two), and
    the direction a third copy drifts in is a price the player is never asked
    for. A cost field that later spells X is added to this one function and every
    reader gains it.

    The alternative-cost arm of the rule (CR 118.9) has no card behind it in this
    pool -- no ``AlternativeCost`` field carries an X -- so it is named here and
    not written: a dead arm is a claim nothing tests.
    """
    if "{X}" in (card.mana_cost or "").upper():
        return True
    return any(
        cost.pay_life_x or cost.return_count_x or cost.exile_graveyard_count_x
        or cost.discard_count_x
        for cost in costs_charged_from(card, from_zone)
    )


def unread_cost_sentence(line: str) -> str | None:
    """*line* if it announces a cost of this table's kind that it cannot
    charge, else None.

    The **table's own** answer to "is this my sentence?", asked by the support
    gate in ``engine/oracle.py``. Not a second reader: the preambles are the
    ones :func:`additional_cost_for_line` matches with, and the refusal is that
    function's own — this only distinguishes "no cost here" from "a cost here I
    refused", which the boolean seam above collapses.

    That distinction is the whole of the gate. A card whose cost line nothing
    reads is not a card missing a feature: it is a card *cheaper than it
    prints*, and because a card is supported when **any** of its lines is, it
    reports supported and casts at its printed mana cost with the extra price
    skipped. Kaervek's Spite sacrificed nothing and Infernal Harvest returned
    no Swamp, both green in every instrument except this one. The gate makes it
    loud, which is the standing invariant: a card may fail as unsupported; it
    may never resolve as something other than what it says.
    """
    normalized = line.strip().lower().rstrip(".")
    for preamble in (_ADDITIONAL_COST_PREAMBLE, _SELF_PERMISSION_COSTS):
        match = preamble.match(normalized)
        if match is not None and _read_cost_clauses(match.group("costs")) is None:
            return match.group(0)
    # A buyback line the rewrite could not read (CR 702.27a). This is asked of
    # the compiler's *expanded* text, where a readable one has already become
    # the sentence above — so what survives here is a printing
    # :func:`expand_buyback_line` refused, and refusing the card is the only
    # honest answer: the alternative is a spell cast at its printed mana cost
    # with an optional price nobody was offered and a hand-return nobody gets.
    if is_buyback_line(line) and expand_buyback_line(line) is None:
        # Spelled the way every other return here is — lowercased, reminder
        # text and the full stop off — because the caller quotes it back to the
        # reader as "printed cost nothing charges: …".
        stripped = " ".join(_BUYBACK_REMINDER.sub("", line or "").split())
        return stripped.strip().lower().rstrip(".")
    return None


def cast_cost_claims_line(line: str) -> bool:
    """Whether this table reads *line*.

    The support gate and the parse-coverage report both ask this, so what the
    engine implements and what it claims to have read cannot drift — the same
    seam ``enter_effects.enter_effect_line`` is.
    """
    return additional_cost_for_line(line) is not None


__all__ = [
    "AdditionalCost",
    "OptionalManaCost",
    "BUYBACK_RULES_TEXT",
    "buyback_cost",
    "buyback_paid",
    "expand_buyback_line",
    "expand_buyback_lines",
    "is_buyback_line",
    "read_return_clause",
    "read_sacrifice_all_clause",
    "read_sacrifice_clause",
    "additional_cost_for_line",
    "additional_costs",
    "cast_announces_x",
    "cast_cost_claims_line",
    "costs_charged_from",
    "unread_cost_sentence",
]
