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

    def describe(self) -> str:
        """The cost as a player would say it, for a log line and a prompt label.

        Rendered off the payload rather than off the printed sentence: the
        sentence is what the *card* says and this is what the *payment* will do,
        so a narrowing the payload dropped shows up here as a description that
        stopped matching the card — which is the direction a cost description
        should fail in.
        """
        parts = []
        if self.pay_life:
            parts.append(f"pay {self.pay_life} life")
        if self.exile_from_hand is not None:
            parts.append(f"exile {_a_card_answering(self.exile_from_hand)} from your hand")
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

_PAY_LIFE = re.compile(r"^pay (\d+) life$")

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
    from .oracle import _chargeable_discard_filters

    fields: dict = {"pay_life": 0, "exile_from_hand": None}
    for clause in re.split(r",\s*|\s+and\s+", costs):
        clause = clause.strip()
        if not clause:
            continue
        life = _PAY_LIFE.match(clause)
        if life is not None:
            fields["pay_life"] += int(life.group(1))
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
        return None
    if not fields["pay_life"] and fields["exile_from_hand"] is None:
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
    """
    found = [
        cost
        for line in (card.oracle_text or "").split("\n")
        if (cost := alternative_cost_for_line(line)) is not None
    ]
    return tuple(found)


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
]
