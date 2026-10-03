"""Text-keyed **alternative** costs a spell prints in its own text (CR 118.9).

The other half of :mod:`engine.cast_costs`, and the difference is one word in
the rules: an *additional* cost is paid **as well as** the mana cost, an
*alternative* cost is paid **rather than** it (CR 118.9). Everything else about
the two is the same shape and deliberately so — a canonical phrase table rather
than per-card hooks, because "You may exile a red card from your hand rather
than pay this spell's mana cost" means the same thing on every card that prints
it, and Alliances prints it five times with one colour changed.

**What this replaced was not a gap, it was the shape ``cast_costs`` was written
to prevent, one rule over.** Force of Will and Pyrokinesis compiled
``supported`` — on their *other* line, the one that counters a spell or deals
the damage — while the line that defines them was claimed by nothing at all.
Nothing was wrong with what they did; what was missing was that they could
never be cast the way the card is famous for. ``scripts/parse_coverage.py``
could see it (both were in its unclaimed list); the refusal census could not,
because the card was not refused.

Three rules bound what this may do, and each is checked where CR puts it:

* **CR 118.9a** — only one alternative cost may be applied to a spell, and the
  intention is announced at CR 601.2b, before targets are chosen (601.2c) and
  long before anything is paid (601.2h). So the choice arrives *with* the cast
  action, exactly as the additional costs' choices do, rather than through the
  pending-choice queue: a queued prompt would put the spell on the stack before
  the game knew what was being paid for it.
* **CR 118.9c** — an alternative cost does not change the spell's mana cost.
  Nothing here touches ``CardDefinition.mana_cost``; the cast path skips the
  *payment*, and every reader of the printed cost (the commander tax, a
  colour-pip tax, a converted-mana-cost test) still sees ``{3}{U}{U}``.
* **CR 118.9d** — additional costs, increases and reductions still apply on top
  of an alternative cost. So this is gathered and paid *beside*
  ``cast_costs.additional_costs``, never instead of it, and the taxes above it
  in ``queue_from_hand`` are untouched.

A cost is not an effect, so none of this is an instruction — the same reason
``cast_costs`` produces none. The compiler asks this table whether a line is a
cost (which is what stops the line reading as unclaimed), and the cast path
asks it three more times: whether the caster *may* take it, whether they *can*
(CR 601.2h), and then to perform it.

**Both of CR 118.9's printed spellings are here**, because the rule names them
in one sentence: "Alternative costs are usually phrased, 'You may [action]
rather than pay [this object's] mana cost,' **or** 'You may cast [this object]
without paying its mana cost.'" This file used to carry a note saying the second
was deliberately absent because ``cast_permissions.CastPermission.free`` models
it. That is true of a waiver an **effect grants** — Aluren's, Chandra's, Idol of
Endurance's, all of which have a grantee, a zone and a duration — and false of
one a spell prints about *itself*. The five Mercadian Masques Legates print it
about themselves, and read through ``cast_permissions`` they would have needed a
permission nobody grants.

**And the offer can stand behind a printed condition** (:class:`CostCondition`).
"If you control a Swamp, you may pay 4 life rather than pay this spell's mana
cost" (Snuff Out) is CR 601.2b's announcement gated on a board, so the condition
is asked as the spell is cast and in exactly one place —
``Game.applicable_alternative_costs``, the reader the picker, the announcement's
check, the CR 601.2h gate, the AI policy and the payment all share. A condition
that does not hold makes the offer **not exist**, which is a different answer
from "exists and cannot be paid": the first is refused by CR 118.9 with nothing
shown, the second by CR 601.2h with a price named. Folding the two together
would show a player a price they are not being offered, or hide one they are.
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from .oracle_types import _COLOR_WORD_TO_SYMBOL

if TYPE_CHECKING:
    from .game import Game
    from .models import CardDefinition


@dataclass(frozen=True)
class CostCondition:
    """The "If <board>," an alternative cost may be printed behind.

    CR 118.9 says an alternative cost is one "its controller **may** pay rather
    than paying the spell's mana cost"; nothing in that rule says the offer has
    to be standing. Mercadian Masques prints eight cards where it is not — five
    Legates ("If an opponent controls a Swamp and you control a Plains, you may
    cast this spell without paying its mana cost"), Invigorate, Orim's Cure,
    Rouse and their siblings — and the condition is checked as the spell is
    cast, at CR 601.2b, along with the announcement it gates.

    Its own object rather than a field on the cost, because it answers a
    different question: the cost says what is *paid* and this says whether the
    offer exists at all. Folded in, "unpayable" and "not offered" would be one
    answer, and CR 601.2h's refusal message would name a price the player was
    never shown.

    ``controls`` is the printed board clauses, each a ``(seat word, filter,
    present)`` triple: the seat is "you" or "an opponent", and *present* is the
    quantifier the article carries ("a Plains" is a presence test, "no land
    cards" its negation). ``hand`` is the same triple one zone over -- "you have
    no land cards in hand" (Land Grant) -- and separate for the reason
    ``AdditionalCost`` keeps its zones apart: a card in a hand answers a
    strictly different matcher from a permanent on a battlefield (CR 613.1), so
    a shared field would be read by the wrong one on whichever card was written
    second.

    Every clause must hold. No card in the pool prints an "or", and reading a
    missing conjunction as one would be an offer standing on strictly more
    boards than the card names -- the direction a cost must never drift in.
    """

    phrase: str
    #: ("you" | "an opponent", filter payload, present) per printed clause.
    controls: tuple[tuple[str, dict, bool], ...] = ()
    #: (filter payload, present) for the hand clause, or None when none is
    #: printed. The seat is always the caster's own: no card in this pool reads
    #: an opponent's hand as a cast condition, and a reader that assumed one
    #: could would be describing a game this engine cannot see.
    hand: "tuple[dict, bool] | None" = None

    def describe(self) -> str:
        """The condition as a player would say it, for a log line and a prompt.

        Rendered off the payload rather than off the printed sentence, exactly
        as :meth:`AlternativeCost.describe` is and for its reason: a narrowing
        the payload dropped shows up here as a description that stopped matching
        the card.
        """
        parts = [
            f"{seat} {'controls' if seat != 'you' else 'control'} "
            f"{_article(board_noun(described)) if present else 'no'} "
            f"{board_noun(described)}"
            for seat, described, present in self.controls
        ]
        if self.hand is not None:
            described, present = self.hand
            parts.append(
                f"you have {'a' if present else 'no'} "
                f"{board_noun(described)} card"
                f"{'' if present else 's'} in hand"
            )
        return " and ".join(parts) or "always"


@dataclass(frozen=True)
class AlternativeCost:
    """One printed alternative cost (CR 118.9a).

    ``exile_from_hand`` is the alternatives a card exiled to pay must answer, in
    the same tuple-of-payloads vocabulary ``cast_costs.AdditionalCost``'s
    ``discard_filters`` and ``ActivatedAbilityCost.discard_filters`` carry, read
    by the same function and tested by the same matcher
    (``subject_filters.card_matches_any``). ``None`` means "no card leaves the
    hand", never "any card": an empty *tuple* already means "any card", which is
    a different and much cheaper cost.
    """

    phrase: str
    #: "You may **pay 1 life** and exile a blue card…" (Force of Will,
    #: Contagion). CR 119.4 caps a life payment at the payer's life total and
    #: CR 601.2h then makes an unpayable cost an uncastable spell rather than a
    #: free one, so this is checked before anything is spent.
    pay_life: int = 0
    exile_from_hand: tuple[dict, ...] | None = None
    #: "…its controller may **discard a card** that shares a color with that
    #: spell." (Dream Halls.) The same tuple-of-payloads vocabulary
    #: ``exile_from_hand`` one field up carries, one destination over -- and its
    #: own field for that field's reason: a discarded card is in a graveyard
    #: afterwards and an exiled one is not, and a spell may read either back.
    #: ``None`` means "no discard", never "any card".
    discard_from_hand: tuple[dict, ...] | None = None
    #: "…a card **that shares a color with that spell**." (Dream Halls.) A
    #: relation between the card paying and the spell being cast, which no
    #: filter payload can express: ``card_matches_any`` tests one card against a
    #: description, and this asks about two objects at once (CR 105.2, CR
    #: 202.2).
    #:
    #: Its own flag rather than a colour list, because *which* colours answer is
    #: not knowable until a spell is being cast -- and a colourless spell shares
    #: a colour with nothing, so it simply cannot be paid for this way. Dropped,
    #: the cost would let any card in hand pay for any spell, which is the
    #: cheaper direction a cost must never drift in.
    shares_color_with_spell: bool = False
    #: "You may **sacrifice two Mountains** rather than pay this spell's mana
    #: cost." (Fireblast, and the same cycle's Snuff Out one colour over.) The
    #: same ``(filter, count)`` pair ``cast_costs.AdditionalCost`` carries, read
    #: by the same function (``cast_costs.read_sacrifice_clause``) and tested by
    #: the same matcher — CR 601.2b's additional cost and CR 118.9's
    #: alternative one print this clause identically, so what may pay it is one
    #: answer wherever it is printed.
    #:
    #: ``None`` means "no sacrifice", never "anything": an empty filter would
    #: let the payment be a land the card never named, and the *count* is what
    #: makes such a cost unpayable at all — one Mountain is no more a payment
    #: than none (CR 601.2h).
    sacrifice_filter: dict | None = None
    sacrifice_count: int = 1
    #: "You may **exile the top three black cards of your graveyard** rather
    #: than pay this spell's mana cost." (Spinning Darkness.) The payload
    #: ``grammar.graveyard_position_payload_for`` builds — ``count``,
    #: ``position``, ``owner`` and an optional ``filter``.
    #:
    #: Its own field rather than a value on ``exile_from_hand`` above, for the
    #: reason that one is separate from ``sacrifice_filter``: nothing is
    #: **chosen** here. CR 404.1 puts each card on top of its owner's graveyard
    #: and CR 404.2 keeps the pile in that order, so the phrase has exactly one
    #: answer and there is no picker, no named index and no re-check. Read as a
    #: filter it would let any three black cards in the pile pay, which is
    #: strictly cheaper than the card prints.
    #:
    #: Only the caster's **own** graveyard: a payment out of somebody else's
    #: pile is a shape this cast path has no seat for, which is the narrowing
    #: the reader applies rather than a fact about the pool.
    exile_graveyard_position: dict | None = None
    #: "You may **return two Islands you control to their owner's hand** rather
    #: than pay this spell's mana cost." (Gush, Thwart, Tidal Bore.) The same
    #: ``(filter, count)`` pair ``cast_costs.AdditionalCost`` carries for the
    #: identically printed clause (Infernal Harvest), read by the same function
    #: (``cast_costs.read_return_clause``) and enumerated by the same candidate
    #: scan -- CR 601.2b's additional cost and CR 118.9's alternative one print
    #: this clause word for word, so what may pay it is one answer wherever it
    #: is printed.
    #:
    #: ``None`` means "no return", never "anything", and the *count* is what
    #: makes such a cost unpayable at all: one Island is no more a payment of a
    #: two-Island cost than none (CR 601.2h, CR 118.3).
    return_filter: dict | None = None
    return_count: int = 1
    #: "You may **tap an untapped creature you control** rather than pay this
    #: spell's mana cost." (Orim's Cure, Ramosian Rally.) The same
    #: ``(count, filter)`` an activation cost's identically printed clause
    #: carries, read by the same function (``oracle._chargeable_tap_cost``) --
    #: CR 601.2b and CR 602.2b are one announcement step.
    #:
    #: ``tap_count`` of 0 is "no tap cost", which is why the count and not the
    #: filter is the presence test here: the filter for "an untapped creature"
    #: is a perfectly ordinary payload and an empty one would read as "any
    #: permanent".
    tap_filter: dict | None = None
    tap_count: int = 0
    #: "If you have no land cards in hand, you may **reveal your hand** rather
    #: than pay this spell's mana cost." (Land Grant.) A payment that moves
    #: nothing and spends nothing -- what it costs is the information, which is
    #: why the *condition* is the whole of the card's price and why this is a
    #: flag rather than a filter. Always payable: a hand of nothing reveals
    #: nothing and has still paid (CR 601.2h has no shortfall to find).
    reveal_hand: bool = False
    #: "…you may **have an opponent gain 3 life** rather than pay this spell's
    #: mana cost." (Invigorate.) The one printed alternative cost in this pool
    #: whose payment lands on somebody *else*, which is what stops it being a
    #: ``pay_life`` with a sign: CR 119.4 caps what a player may **pay** at
    #: their own life total and puts no cap at all on what another player may
    #: gain, so the CR 601.2h gate must not ask this one the payer's question.
    #: Always payable for the same reason.
    opponent_gains_life: int = 0
    #: "If you control a Forest, rather than pay this spell's mana cost, you may
    #: **have each other player gain 6 life**." (Reverent Silence; Skyshroud
    #: Cutter prints 5.) Invigorate's price paid to **every** other seat rather
    #: than to one the caster picks, which is why it is a field beside
    #: ``opponent_gains_life`` and not that one with a flag: the two answer
    #: CR 119.7 differently. One opponent who cannot gain life leaves Invigorate
    #: payable through another, and leaves this one unpayable outright --
    #: "a cost that involves having **that player** gain life can't be paid",
    #: and here every other player is that player. A duel cannot tell the two
    #: apart; a free-for-all table can, and the wrong one is a spell cast for
    #: less than it prints.
    others_gain_life: int = 0
    #: "You may **cast this spell without paying its mana cost**." (The five
    #: Mercadian Masques Legates.) CR 118.9's *second* printed spelling, named
    #: in the rule beside the first -- "Alternative costs are usually phrased,
    #: 'You may [action] rather than pay [this object's] mana cost,' **or 'You
    #: may cast [this object] without paying its mana cost.'**"
    #:
    #: A flag rather than the absence of every other field, because
    #: :func:`_read_cost_clauses` refuses a sentence whose every clause read as
    #: nothing -- a free spell is the one answer that table must never give by
    #: accident, and this is the sentence that gives it **on purpose**. The two
    #: are reached by different preambles, so the accident stays impossible.
    free: bool = False
    #: The "If <board>," this offer stands behind, or None when it stands
    #: always. Asked by ``Game.applicable_alternative_costs`` -- one reader, so
    #: the offer the picker shows, the announcement's check, the CR 601.2h gate
    #: and the payment cannot disagree about whether there is an offer at all.
    condition: "CostCondition | None" = None

    def describe(self) -> str:
        """The cost as a player would say it, for a log line and a prompt label.

        Rendered off the payload rather than off the printed sentence: the
        sentence is what the *card* says and this is what the *payment* will do,
        so a narrowing the payload dropped shows up here as a description that
        stopped matching the card — which is the direction a cost description
        should fail in.
        """
        if self.free:
            # Its own sentence rather than an empty parts list, which the tail
            # below renders as "pay nothing": true, and not what the card says.
            # The words are the printed ones, so a log line and a prompt label
            # read back as the sentence the player is being offered.
            return "cast it without paying its mana cost"
        parts = []
        if self.pay_life:
            parts.append(f"pay {self.pay_life} life")
        if self.discard_from_hand is not None:
            parts.append(
                f"discard {_a_card_answering(self.discard_from_hand)}"
                + (
                    " that shares a color with it"
                    if self.shares_color_with_spell else ""
                )
            )
        if self.exile_from_hand is not None:
            parts.append(f"exile {_a_card_answering(self.exile_from_hand)} from your hand")
        if self.sacrifice_filter is not None:
            # ``board_noun``, not ``filter_head_noun``. Every card in the pool
            # that prints this clause names a *land subtype* -- Fireblast's two
            # Mountains, Crash's Mountain, Pulverize's two -- and the head noun
            # answers "permanent" for all of them, so the offer the client shows
            # read "sacrifice 2 permanents" and told the player nothing about
            # what was going to leave. The gate is unchanged; what changes is
            # whether the price is legible before it is taken.
            noun = board_noun(self.sacrifice_filter)
            parts.append(
                f"sacrifice {_article(noun)} {noun}" if self.sacrifice_count == 1
                else f"sacrifice {self.sacrifice_count} {noun}s"
            )
        if self.return_filter is not None:
            noun = board_noun(self.return_filter)
            parts.append(
                f"return {_article(noun)} {noun} you control to its owner's hand"
                if self.return_count == 1
                else f"return {self.return_count} {noun}s you control to their "
                     "owner's hand"
            )
        if self.tap_count:
            noun = board_noun(self.tap_filter or {})
            parts.append(
                f"tap an untapped {noun} you control" if self.tap_count == 1
                else f"tap {self.tap_count} untapped {noun}s you control"
            )
        if self.reveal_hand:
            parts.append("reveal your hand")
        if self.opponent_gains_life:
            parts.append(
                f"have an opponent gain {self.opponent_gains_life} life"
            )
        if self.others_gain_life:
            parts.append(
                f"have each other player gain {self.others_gain_life} life"
            )
        if self.exile_graveyard_position is not None:
            spec = self.exile_graveyard_position
            count = int(spec.get("count", 1))
            # Through the same describer the hand exile above uses, so the one
            # narrowing this cost's pool actually prints — a colour — is spelled
            # out rather than reduced to the head noun "permanent".
            noun = _a_card_answering((spec.get("filter") or {},))
            noun = noun[2:] if noun.startswith("a ") else noun
            parts.append(
                f"exile the {spec.get('position', 'top')} "
                + ("" if count == 1 else f"{count} ")
                + noun + ("" if count == 1 else "s")
                + " of your graveyard"
            )
        return " and ".join(parts) or "pay nothing"


#: "You may <clauses> rather than pay this spell's mana cost." (CR 118.9's first
#: printed spelling.) A preamble plus a clause vocabulary, for the reason
#: ``cast_costs._ADDITIONAL_COST_PREAMBLE`` is one: a table of whole phrases
#: writes the preamble out once per card and then cannot read a clause nobody
#: listed.
#:
#: CR 118.9's *second* spelling — "You may cast this spell without paying its
#: mana cost" — is deliberately not here. That sentence grants a permission
#: rather than naming a price, this engine already models it
#: (``cast_permissions.CastPermission.free``, which cites the same rule), and a
#: second reader of it would be a second answer to "may this be cast for
#: nothing".
#: The condition is an optional prefix rather than a second table, because it
#: is optional on the card: Force of Will prints the sentence bare and Rouse
#: prints the same sentence behind "If you control a Swamp,". One preamble means
#: one place the words "rather than pay this spell's mana cost" are recognized,
#: which is what stops a conditional card from being read by a table the
#: unconditional one has since outgrown.
_ALTERNATIVE_COST_PREAMBLE = re.compile(
    r"^(?:if (?P<condition>.+?), )?"
    r"you may (?P<costs>.+?) rather than pay this spell(?:'|’)s mana cost$"
)

#: The same sentence with its two halves swapped -- "If you control a Forest,
#: **rather than pay this spell's mana cost, you may** have an opponent gain 3
#: life." (Invigorate.) English word order, not a different rule, so it fills
#: the same fields through the same clause reader.
#:
#: Its own pattern rather than an alternation inside the one above, because the
#: two put the condition in different places relative to the offer and a single
#: regex holding both would have to make ``costs`` optional -- which is how a
#: sentence gets read as an alternative cost that charges nothing.
_ALTERNATIVE_COST_INVERTED = re.compile(
    r"^if (?P<condition>.+?), rather than pay this spell(?:'|’)s mana cost, "
    r"you may (?P<costs>.+)$"
)

#: CR 118.9's **second** printed spelling, named in the rule's own text beside
#: the first: "You may cast this spell without paying its mana cost." The five
#: Mercadian Masques Legates print it behind a condition; nothing in this pool
#: prints it bare, and the prefix is optional here for the reason it is optional
#: above -- the condition is a property of the card, not of the spelling.
#:
#: This module's docstring used to say this spelling was deliberately absent
#: because ``cast_permissions.CastPermission.free`` models it. That is true of a
#: waiver **granted by an effect** ("you may cast spells from your hand without
#: paying their mana costs") and false of one a spell prints about *itself*:
#: there is no effect to grant, no duration to expire and no zone to open, only
#: a price of nothing that CR 118.9 names an alternative cost in as many words.
#: Read there, the Legates would have needed a permission nobody grants.
_CAST_FOR_FREE_PREAMBLE = re.compile(
    r"^(?:if (?P<condition>.+?), )?"
    r"you may cast this spell without paying its mana cost$"
)

#: "If **you control a Plains**, …" / "If **an opponent controls a Swamp** and
#: **you control a Plains**, …" One clause of the condition prefix. The seat is
#: captured and the noun phrase is *delimited only* -- it is read by
#: ``subject_filters.quantified_board_phrase``, beside the matcher that answers
#: it, which is the split every board condition in this engine makes.
_CONTROLS_CLAUSE = re.compile(
    r"^(?P<seat>you|an opponent) controls? (?P<board>.+)$"
)

#: "If **you have no land cards in hand**, …" (Land Grant.) The condition's one
#: non-board clause, and the zone is part of the pattern rather than trailing
#: slack: a hand is the only zone this reader can scan, and a sentence naming a
#: graveyard or a library must refuse rather than be answered against the hand.
_HAND_CLAUSE = re.compile(r"^you have (?P<board>.+) in hand$")

#: "…exile **a blue card from your hand**…" The zone is part of the clause and
#: not an afterthought: this is the only zone the payment can reach, and a
#: sentence naming another one must refuse rather than be charged against the
#: hand. The noun phrase itself is delimited here and *read* by
#: ``oracle._chargeable_discard_filters`` — a regex approximating the noun
#: parser is a second reader of one phrase, and the direction those drift in is
#: a cost charged more widely than the card prints.
_EXILE_FROM_HAND = re.compile(r"^exile (?P<noun>.+) from your hand$")

#: "…exile **the top three black cards of your graveyard**…" (Spinning
#: Darkness). The phrase is delimited here and *read* by the grammar's own
#: production (``grammar.graveyard_position_payload_for``), never by a second
#: regex: a regex approximating that production is a second reader of one
#: clause, and the direction a cost drifts in is a price nobody pays. The zone
#: is part of the phrase rather than of this pattern, so a sentence naming a
#: library or somebody else's graveyard is refused by the reader instead of
#: being charged against the caster's own pile.
_EXILE_GRAVEYARD_POSITION = re.compile(r"^exile (the (?:top|bottom) .+)$")

_PAY_LIFE = re.compile(r"^pay (\d+) life$")

#: "…**return two Islands you control to their owner's hand**…" (Gush, Thwart,
#: Tidal Bore.) The destination is part of the clause and not an afterthought:
#: this is the only zone the payment can reach, and a sentence naming another
#: one must refuse rather than be charged against the hand. Delimiting only --
#: the noun phrase is read by ``cast_costs.read_return_clause``, the reader the
#: identically printed *additional* cost already uses. The apostrophe is either
#: kind because the ingested text prints the curly one.
_RETURN_TO_HAND = re.compile(
    r"^return (?P<noun>.+) to (?:their|its) "
    r"owner(?:s(?:'|’)|(?:'|’)s)? hands?$"
)

#: "…**have an opponent gain 3 life**…" (Invigorate.) An exact number and an
#: exact recipient: "an opponent" is a seat this cast path can pick and "each
#: opponent" is a different, strictly larger price that would need a different
#: payment, so the wider phrase refuses here rather than being charged as one.
_OPPONENT_GAINS_LIFE = re.compile(r"^have an opponent gain (\d+) life$")

#: "…**have each other player gain 6 life**…" (Reverent Silence, Skyshroud
#: Cutter.) The wider recipient the pattern above refuses, read as its own
#: payment: every other seat gains, nobody is picked, and CR 119.7 makes one
#: seat that cannot gain life an unpayable cost rather than a smaller one.
#: "Each opponent" is not this phrase -- in a game with teams it names fewer
#: seats -- and no card in the pool prints it, so it still refuses.
_EACH_OTHER_PLAYER_GAINS_LIFE = re.compile(
    r"^have each other player gain (\d+) life$"
)

#: "…its controller may **discard a card that shares a color with that
#: spell**." (Dream Halls.) The noun phrase is delimited here and *read* by
#: ``oracle._chargeable_discard_filters``, exactly as the exile clause above
#: delimits its own -- a regex approximating the noun parser is a second reader
#: of one phrase.
#:
#: The colour relation is part of the pattern rather than of the noun, because
#: it is not a property of the card at all: it is a comparison between the card
#: paying and the spell being cast, and no filter payload can hold it.
_DISCARD_FROM_HAND = re.compile(
    r"^discard (?P<noun>.+?)"
    r"(?P<sharing> that shares a color with that spell)?$"
)

#: "**Rather than pay the mana cost for a spell, its controller may** discard a
#: card that shares a color with that spell." (Dream Halls.)
#:
#: CR 118.9's alternative cost granted from a **board** rather than printed on
#: the spell, which is the whole of what makes it a different reader: every
#: sentence ``_ALTERNATIVE_COST_PREAMBLE`` matches is about the card it is
#: printed on ("*this spell's* mana cost"), and this one is about every spell
#: anybody casts. The relationship is ``cost_modifiers``' to ``cast_costs``, one
#: rule over.
_GRANTED_ALTERNATIVE_COST = re.compile(
    r"^rather than pay the mana cost for a spell, its controller may "
    r"(?P<costs>.+)$"
)

#: The printed word for each colour symbol, for :meth:`AlternativeCost.describe`
#: alone. Inverted from ``oracle_types._COLOR_WORD_TO_SYMBOL`` rather than
#: written out, so the two spellings of one mapping cannot drift.
_SYMBOL_TO_COLOR_WORD = {
    symbol: word for word, symbol in _COLOR_WORD_TO_SYMBOL.items()
}


def _a_card_answering(alternatives: tuple[dict, ...]) -> str:
    """"a blue card" / "a red or green card" / "a card" — what *alternatives*
    name, for a description.

    Only the colour keys are spelled out, because those are the only narrowings
    this cost's pool prints; anything else falls back to the head noun the rest
    of the engine describes a filter with. A description is not a gate, so an
    unspelled narrowing costs a vaguer sentence and nothing else.
    """
    from .subject_filters import filter_head_noun

    if not alternatives:
        return "a card"
    words: list[str] = []
    for alternative in alternatives:
        colors = alternative.get("any_colors") or (
            [alternative["color_filter"]] if alternative.get("color_filter") else []
        )
        words.extend(_SYMBOL_TO_COLOR_WORD.get(color, color) for color in colors)
    if not words:
        noun = filter_head_noun(alternatives[0])
        return f"a {noun} card" if noun != "permanent" else "a card"
    return "a " + " or ".join(words) + " card"


def read_condition(condition: str) -> "CostCondition | None":
    """The board *condition* gates an alternative cost on, or None.

    **Every** clause must be read or the whole condition is refused, which is
    :func:`_read_cost_clauses`'s rule one field over and is here for the
    inverse of its reason: a dropped *cost* clause is a spell cast for nothing,
    and a dropped *condition* clause is an offer standing on a board the card
    does not name -- which is the same spell cast for nothing, one step
    earlier.

    The noun phrases go through ``subject_filters.quantified_board_phrase``,
    the one reader the board conditions in ``cast_restrictions`` and
    ``activation_restrictions`` also use, so what "a Plains" means is one answer
    wherever a card prints it. A phrase carrying a key the matcher cannot test
    refuses rather than being approximated.
    """
    from .subject_filters import card_only_filter, quantified_board_phrase

    controls: list[tuple[str, dict, bool]] = []
    hand: "tuple[dict, bool] | None" = None
    for clause in condition.split(" and "):
        clause = clause.strip()
        if not clause:
            return None
        board = _CONTROLS_CLAUSE.match(clause)
        if board is not None:
            read = quantified_board_phrase(board.group("board"))
            if read is None:
                return None
            described, present = read
            controls.append((board.group("seat"), described, present))
            continue
        held = _HAND_CLAUSE.match(clause)
        if held is not None:
            if hand is not None:
                # Two hand clauses would need two payloads and one field cannot
                # hold two; folded together they would read as one, which is a
                # condition holding on strictly more boards than the two
                # printed.
                return None
            read = quantified_board_phrase(held.group("board"))
            if read is None:
                return None
            described, present = read
            # A card in a zone has no computed characteristics (CR 613.1), so
            # the phrase is put to the *card* matcher's key set as well: a
            # narrowing only ``subject_matches`` could answer would be silently
            # dropped by the hand scan and the condition would hold on a hand
            # the card does not name.
            narrowed = card_only_filter(described)
            if narrowed is None:
                return None
            hand = (narrowed, present)
            continue
        return None
    if not controls and hand is None:
        return None
    return CostCondition(condition, tuple(controls), hand)


def condition_holds(game: "Game", caster_index: int, condition) -> bool:
    """Whether *condition* holds for *caster_index* right now (CR 601.2b).

    Asked as the spell is cast, which is where CR 601.2b puts the announcement
    this gates -- and asked in exactly one place
    (``Game.applicable_alternative_costs``), so the offer the picker shows, the
    announcement's check, the CR 601.2h gate and the payment cannot disagree
    about whether there is an offer at all.

    CR 109.5's observer is the casting seat, so a "you" *inside* a noun phrase
    means the same player the outer "you control" does -- the reading
    ``cast_restrictions._condition_holds`` states for the identical clause.
    """
    from .subject_filters import card_matches_any, subject_matches

    if condition is None:
        return True
    for seat, described, present in condition.controls:
        if seat == "you":
            board = list(game.controlled_by(caster_index))
        else:
            # Every *other* seat, not one named opponent: "an opponent controls
            # a Swamp" is satisfied by any of them, and a duel's single
            # opponent is what made the difference invisible until a
            # free-for-all seat was added.
            board = [
                perm
                for other in range(len(game.players))
                if other != caster_index and not game.players[other].lost
                for perm in game.controlled_by(other)
            ]
        found = any(
            subject_matches(game, perm, described, observer=caster_index)
            for perm in board
        )
        if found is not present:
            return False
    if condition.hand is not None:
        described, present = condition.hand
        found = any(
            card_matches_any(held, (described,))
            for held in game.players[caster_index].hand
        )
        if found is not present:
            return False
    return True


def _article(noun: str) -> str:
    """"a" or "an" for *noun*, which is a land subtype more often than not.

    Crude on purpose -- a vowel test, not a pronunciation table. Every noun
    these descriptions reach is a card type or a land subtype ("Island",
    "artifact", "creature"), and the words English spells against the vowel rule
    ("a Unicorn", "an hour") are not among them. A description is not a gate, so
    the cost of being wrong here is a sentence that reads badly.
    """
    return "an" if noun[:1].lower() in "aeiou" else "a"


def board_noun(described: dict | None) -> str:
    """The one word a board filter names, for a description.

    ``subject_filters.filter_head_noun`` answers off ``type_filter`` alone and
    says "permanent" for anything else -- which is right for a picker's ``kind``
    and wrong here, because every noun phrase this file's conditions and its
    return cost print is a **land subtype**: "a Forest", "two Islands". Rendered
    through the head noun alone, five different Legates and three different
    Islands-return spells all describe themselves identically, and the offer the
    client shows stops naming the price.

    The subtype first, then the head noun, then "permanent" -- a description is
    not a gate, so a phrase this cannot spell costs a vaguer sentence and
    nothing else. Its counterpart for the *hand* half is
    :func:`_a_card_answering` above, which spells colours for that half's reason.
    """
    from .subject_filters import filter_head_noun

    subtype = (described or {}).get("subtype_filter")
    if isinstance(subtype, str) and subtype:
        return subtype.capitalize()
    return filter_head_noun(described)


def _read_cost_clauses(costs: str) -> dict | None:
    """The fields the clauses of one alternative-cost sentence fill, or None.

    **Every** clause must be read or the whole sentence is refused, which is
    ``cast_costs._read_cost_clauses``'s rule and is here for a sharper version
    of its reason: a dropped clause in an *additional* cost is a spell cast for
    less than it prints, and a dropped clause in an alternative cost is a spell
    cast for **nothing** — the mana cost has already been replaced by whatever
    was read.
    """
    from .cast_costs import read_sacrifice_clause
    from .oracle import _chargeable_discard_filters

    fields: dict = {
        "pay_life": 0,
        "exile_from_hand": None,
        "discard_from_hand": None,
        "shares_color_with_spell": False,
        "sacrifice_filter": None,
        "sacrifice_count": 1,
        "exile_graveyard_position": None,
        "return_filter": None,
        "return_count": 1,
        "tap_filter": None,
        "tap_count": 0,
        "reveal_hand": False,
        "opponent_gains_life": 0,
        "others_gain_life": 0,
    }
    for clause in re.split(r",\s*|\s+and\s+", costs):
        clause = clause.strip()
        if not clause:
            continue
        life = _PAY_LIFE.match(clause)
        if life is not None:
            fields["pay_life"] += int(life.group(1))
            continue
        # Read **before** the hand spelling below, which cannot claim these
        # words ("the top …" is not "… from your hand") — the order is what
        # keeps the two from ever being one question rather than what resolves
        # a fight between them.
        positioned = _EXILE_GRAVEYARD_POSITION.match(clause)
        if positioned is not None:
            from .grammar import graveyard_position_payload_for

            if fields["exile_graveyard_position"] is not None:
                # Two such clauses would need two payloads and one field cannot
                # hold two; folded together they would read as one, which is a
                # strictly cheaper cost than the two printed.
                return None
            described = graveyard_position_payload_for(
                positioned.group(1), seats=frozenset({"you"})
            )
            if described is None:
                # A phrase the payment path cannot resolve — somebody else's
                # pile, a narrowing the card matcher cannot test. Refused whole
                # rather than charged as the part that was read, this
                # function's all-or-nothing rule.
                return None
            fields["exile_graveyard_position"] = described
            continue
        # "**return two Islands you control to their owner's hand**" (Gush,
        # Thwart, Tidal Bore). Read through the additional cost's own reader,
        # never a second split of the same words: the two rules print one
        # clause (Infernal Harvest prints it as an additional cost), and a
        # phrase admitted here that ``cast_costs`` would refuse is a price this
        # table claims and the cast path cannot collect.
        returned = _RETURN_TO_HAND.match(clause)
        if returned is not None:
            from .cast_costs import read_return_clause

            if fields["return_filter"] is not None:
                # Two return clauses would need two filters and one field
                # cannot hold two; folded together they would read as a union,
                # which is a strictly cheaper cost than the two printed.
                return None
            read = read_return_clause(returned.group("noun"))
            if read is None:
                return None
            described, count, count_is_x = read
            if count_is_x:
                # "return X …" is announced as the spell is cast (CR 107.3a).
                # No card in this pool prints an X in an *alternative* cost and
                # nothing on this path announces one, so it refuses rather than
                # being charged as the 1 the reader defaults to -- a spell cast
                # for one land instead of however many were announced.
                return None
            fields["return_filter"], fields["return_count"] = described, count
            continue
        # "**tap an untapped creature you control**" (Orim's Cure, Ramosian
        # Rally). Through the activation cost's reader for the return clause's
        # reason above: CR 601.2b and CR 602.2b are one announcement step, so
        # what may pay a printed tap is one answer wherever the tap is printed.
        if clause.startswith("tap "):
            from .oracle import _chargeable_tap_cost

            if fields["tap_count"]:
                # Two tap clauses would need two filters and one field cannot
                # hold two -- the same refusal every counted clause here makes.
                return None
            read = _chargeable_tap_cost(clause)
            if read is None:
                return None
            fields["tap_count"], fields["tap_filter"] = read
            continue
        # "**reveal your hand**" (Land Grant). A payment that moves nothing:
        # what it costs is the information. Always payable, so it is outside
        # the CR 601.2h gate -- an empty hand reveals nothing and has paid.
        if clause == "reveal your hand":
            if fields["reveal_hand"]:
                return None
            fields["reveal_hand"] = True
            continue
        # "**have an opponent gain 3 life**" (Invigorate). The one payment in
        # this pool that lands on another player, which is what keeps it apart
        # from ``pay_life`` above rather than being it with a sign: CR 119.4
        # caps what a player may *pay* at their own life total and caps nothing
        # about what another player may gain.
        gained = _OPPONENT_GAINS_LIFE.match(clause)
        if gained is not None:
            fields["opponent_gains_life"] += int(gained.group(1))
            continue
        # "**have each other player gain 6 life**" (Reverent Silence). The
        # same gain handed to every other seat rather than one, so it is its
        # own field for CR 119.7's sake -- see ``AlternativeCost``.
        gained = _EACH_OTHER_PLAYER_GAINS_LIFE.match(clause)
        if gained is not None:
            fields["others_gain_life"] += int(gained.group(1))
            continue
        exiled = _EXILE_FROM_HAND.match(clause)
        if exiled is not None:
            if fields["exile_from_hand"] is not None:
                # Two exile clauses would need two alternatives lists and one
                # field cannot hold two; folded together they would read as a
                # union, which is a strictly cheaper cost than the two printed.
                return None
            named = _chargeable_discard_filters(exiled.group("noun"))
            if named is None:
                # The phrase names something the payment path cannot enumerate
                # or cannot test. Refused whole rather than charged as the part
                # that was read — the all-or-nothing rule above.
                return None
            fields["exile_from_hand"] = named
            continue
        # "**discard a card that shares a color with that spell**" (Dream
        # Halls). The hand's other destination, read through the same noun
        # reader the exile above uses so what may pay a printed discard is one
        # answer wherever the discard is printed. The colour relation is
        # carried rather than folded into the filter, because it is a question
        # about *two* objects and a filter describes one.
        discarded = _DISCARD_FROM_HAND.match(clause)
        if discarded is not None:
            if fields["discard_from_hand"] is not None:
                # Two discard clauses would need two alternatives lists and one
                # field cannot hold two; folded together they would read as a
                # union, which is a strictly cheaper cost than the two printed.
                return None
            named = _chargeable_discard_filters(discarded.group("noun"))
            if named is None:
                # The phrase names something the payment path cannot enumerate
                # or cannot test. Refused whole rather than charged as the part
                # that was read -- the all-or-nothing rule above.
                return None
            fields["discard_from_hand"] = named
            fields["shares_color_with_spell"] = bool(discarded.group("sharing"))
            continue
        # "**sacrifice two Mountains**" (Fireblast). Read through the additional
        # cost's own reader, never a second split of the same words: the two
        # rules print one clause, and a phrase admitted here that
        # ``cast_costs`` would refuse is a price this table claims and the cast
        # path cannot collect.
        if clause.startswith("sacrifice "):
            if fields["sacrifice_filter"] is not None:
                # Two sacrifice clauses would need two filters and one field
                # cannot hold two; folded together they would read as a single
                # cheaper cost, which is the direction this file must never
                # drift in.
                return None
            read = read_sacrifice_clause(clause[len("sacrifice "):])
            if read is None:
                # The phrase names something the payment path cannot enumerate
                # or cannot test. Refused whole rather than charged as the part
                # that was read — the all-or-nothing rule above.
                return None
            fields["sacrifice_filter"], fields["sacrifice_count"] = read
            continue
        return None
    if (
        not fields["pay_life"]
        and fields["exile_from_hand"] is None
        and fields["discard_from_hand"] is None
        and fields["sacrifice_filter"] is None
        and fields["exile_graveyard_position"] is None
        and fields["return_filter"] is None
        and not fields["tap_count"]
        and not fields["reveal_hand"]
        and not fields["opponent_gains_life"]
        and not fields["others_gain_life"]
    ):
        # "You may — rather than pay this spell's mana cost." A sentence whose
        # every clause was read as nothing is a free spell, which is the one
        # answer this table must never give by accident.
        return None
    return fields


def alternative_cost_for_line(line: str) -> AlternativeCost | None:
    """The alternative cost *line* states, or None when it states none.

    Matched on the line's whole text (minus a trailing period) rather than as a
    substring, for the reason ``cast_costs.additional_cost_for_line`` is: a
    substring match is how a whitelist comes to claim things it does not
    implement.
    """
    normalized = " ".join(line.strip().lower().split()).rstrip(".")
    free = _CAST_FOR_FREE_PREAMBLE.match(normalized)
    if free is not None:
        # The one sentence that names a price of nothing, and the only route to
        # ``free=True``: :func:`_read_cost_clauses` refuses an all-empty read
        # precisely so the *other* preambles can never reach this value by
        # accident (CR 118.9's first spelling with a clause nobody read).
        condition = free.group("condition")
        read = None if condition is None else read_condition(condition)
        if condition is not None and read is None:
            return None
        return AlternativeCost(free.group(0), free=True, condition=read)
    match = _ALTERNATIVE_COST_PREAMBLE.match(normalized)
    if match is None:
        match = _ALTERNATIVE_COST_INVERTED.match(normalized)
    if match is None:
        return None
    fields = _read_cost_clauses(match.group("costs"))
    if fields is None:
        return None
    condition = match.group("condition")
    read = None if condition is None else read_condition(condition)
    if condition is not None and read is None:
        # A condition this engine cannot test is not a smaller offer but a
        # *standing* one, which is the direction a cost must never drift in:
        # the whole sentence refuses, and the card reports the line unread.
        return None
    return AlternativeCost(match.group(0), condition=read, **fields)


def alternative_costs(card: CardDefinition) -> tuple[AlternativeCost, ...]:
    """Every alternative cost *card* prints, in printed order.

    A tuple rather than one cost even though CR 118.9a lets only one be
    *applied*: what the rule limits is the choice, not the printing, and the
    cast path is where the limit belongs — it is the only place that knows which
    one was chosen.

    Read off ``expand_ability_lines``'s text rather than off ``oracle_text``,
    which is CLAUDE.md's rule that every reader of a card's lines starts from
    that function — and the twin ``cast_costs.additional_costs`` obeys for a
    live reason (CR 702.27a's buyback *is* one of its costs and reaches it only
    as the rewrite's sentence). No rewrite produces an **alternative**-cost
    sentence today, so this moves no card in either manifest role; it is here so
    the two halves of one question are not read two ways, which is how the
    sibling would have been the one place short.
    """
    from .oracle import expand_card_lines

    found = [
        cost
        for line in expand_card_lines(card)
        if (cost := alternative_cost_for_line(line)) is not None
    ]
    return tuple(found)


@lru_cache(maxsize=None)
def granted_alternative_cost(oracle_text: str) -> "AlternativeCost | None":
    """The alternative cost this permanent grants **every spell**, or None.

    "Rather than pay the mana cost for a spell, its controller may discard a
    card that shares a color with that spell." (Dream Halls.) The board-wide
    twin of :func:`alternative_cost_for_line`, and its own reader for
    ``cost_modifiers``' reason one rule over: a printed cost is a property of
    the card being cast and a granted one is a property of a permanent on some
    battlefield, so the two are found by different questions even though what
    they charge is one vocabulary.

    Read off the whole text a line at a time, so a permanent printing the
    sentence beside other abilities still grants it.

    Cached on the text, which is immutable on a ``CardDefinition``, because
    this is asked of **every permanent on every battlefield** for every card in
    every hand on every poll -- the same arrangement and the same reason
    ``cost_modifiers.cost_modifiers_for`` states, down to the substring test
    that answers for the whole pool but one card without matching anything.
    """
    if "rather than pay the mana cost" not in (oracle_text or "").lower():
        return None
    for line in (oracle_text or "").split("\n"):
        match = _GRANTED_ALTERNATIVE_COST.match(
            " ".join(line.strip().lower().split()).rstrip(".")
        )
        if match is None:
            continue
        fields = _read_cost_clauses(match.group("costs"))
        if fields is None:
            continue
        return AlternativeCost(match.group(0), **fields)
    return None


def granted_alternative_cost_claims_line(line: str) -> bool:
    """Whether *line* is, in its entirety, the granted sentence above.

    The support gate and the parse-coverage report both ask this, so what the
    engine implements and what it claims to have read cannot drift -- the same
    seam :func:`alternative_cost_claims_line` is for the printed half.
    """
    return granted_alternative_cost(line) is not None


def unread_granted_alternative_cost_sentence(line: str) -> str | None:
    """*line* if it grants an alternative cost this table cannot charge, else
    None.

    :func:`unread_alternative_cost_sentence`'s twin, and the same defect one
    scope wider: a granted cost nobody reads is a permanent that sits on the
    battlefield doing nothing while its card reports whatever its other lines
    say. Dream Halls has no other lines, so today the gate reports it
    unsupported -- which is the honest answer and the one this exists to keep.
    """
    normalized = " ".join(line.strip().lower().split()).rstrip(".")
    match = _GRANTED_ALTERNATIVE_COST.match(normalized)
    if match is not None and _read_cost_clauses(match.group("costs")) is None:
        return match.group(0)
    return None


def unread_alternative_cost_sentence(line: str) -> str | None:
    """*line* if it announces an alternative cost this table cannot charge,
    else None.

    The twin of ``cast_costs.unread_cost_sentence``, and the sharper case of
    the same defect: an unread *additional* cost is a spell cast for less than
    it prints, and an unread *alternative* cost would be one cast for nothing
    at all if it were ever announced — while today it is quietly cast at the
    mana cost the card offers to replace, with the printed alternative
    unavailable and unmentioned. Fireblast was exactly that.
    """
    normalized = " ".join(line.strip().lower().split()).rstrip(".")
    if alternative_cost_for_line(line) is not None:
        return None
    for pattern in (_ALTERNATIVE_COST_PREAMBLE, _ALTERNATIVE_COST_INVERTED,
                    _CAST_FOR_FREE_PREAMBLE):
        match = pattern.match(normalized)
        if match is not None:
            # Read by a preamble and refused by the clause reader or the
            # condition reader — which is the whole population this exists to
            # name, and it is asked *after* the successful read above so a
            # sentence this table charges is never also reported unread.
            return match.group(0)
    return None


def alternative_cost_claims_line(line: str) -> bool:
    """Whether this table reads *line*.

    The support gate and the parse-coverage report both ask this, so what the
    engine implements and what it claims to have read cannot drift — the same
    seam ``cast_costs.cast_cost_claims_line`` is.
    """
    return alternative_cost_for_line(line) is not None


__all__ = [
    "AlternativeCost",
    "CostCondition",
    "board_noun",
    "condition_holds",
    "read_condition",
    "alternative_cost_claims_line",
    "alternative_cost_for_line",
    "alternative_costs",
    "granted_alternative_cost",
    "granted_alternative_cost_claims_line",
    "unread_alternative_cost_sentence",
    "unread_granted_alternative_cost_sentence",
]
