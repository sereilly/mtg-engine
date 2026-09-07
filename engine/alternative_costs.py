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
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from .oracle_types import _COLOR_WORD_TO_SYMBOL

if TYPE_CHECKING:
    from .models import CardDefinition


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

    def describe(self) -> str:
        """The cost as a player would say it, for a log line and a prompt label.

        Rendered off the payload rather than off the printed sentence: the
        sentence is what the *card* says and this is what the *payment* will do,
        so a narrowing the payload dropped shows up here as a description that
        stopped matching the card — which is the direction a cost description
        should fail in.
        """
        from .subject_filters import filter_head_noun

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
            noun = filter_head_noun(self.sacrifice_filter)
            parts.append(
                f"sacrifice a {noun}" if self.sacrifice_count == 1
                else f"sacrifice {self.sacrifice_count} {noun}s"
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
_ALTERNATIVE_COST_PREAMBLE = re.compile(
    r"^you may (?P<costs>.+?) rather than pay this spell(?:'|’)s mana cost$"
)

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
    match = _ALTERNATIVE_COST_PREAMBLE.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    fields = _read_cost_clauses(match.group("costs"))
    if fields is None:
        return None
    return AlternativeCost(match.group(0), **fields)


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
    match = _ALTERNATIVE_COST_PREAMBLE.match(line.strip().lower().rstrip("."))
    if match is not None and _read_cost_clauses(match.group("costs")) is None:
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
    "alternative_cost_claims_line",
    "alternative_cost_for_line",
    "alternative_costs",
    "granted_alternative_cost",
    "granted_alternative_cost_claims_line",
    "unread_alternative_cost_sentence",
    "unread_granted_alternative_cost_sentence",
]
