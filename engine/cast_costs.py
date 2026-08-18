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
from typing import TYPE_CHECKING

from .subject_filters import filter_head_noun

if TYPE_CHECKING:
    from .models import CardDefinition


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
    discard_cards: int = 0
    #: "…by paying **3 life** and discarding a card" (Demonic Embrace).
    #: CR 118.4 makes an unpayable life cost an uncastable spell, checked with
    #: the rest of the costs before anything is spent.
    pay_life: int = 0
    #: The zone this cost applies to, when the sentence naming it also names a
    #: zone. Demonic Embrace costs {1}{B}{B} from the hand and {1}{B}{B} plus 3
    #: life plus a card from the graveyard — the *same card*, so the cost cannot
    #: be a property of the card alone. ``None`` means every zone, which is what
    #: an "as an additional cost to cast this spell" line means.
    from_zone: str | None = None

    def describe(self) -> str:
        parts = []
        if self.sacrifice_filter is not None:
            parts.append(f"sacrifice a {filter_head_noun(self.sacrifice_filter)}")
        if self.pay_life:
            parts.append(f"pay {self.pay_life} life")
        if self.discard_cards:
            parts.append(f"discard {self.discard_cards} card(s)")
        return " and ".join(parts) or "no additional cost"


# Canonical lowercase phrases, matched against a whole normalized line. Both
# shapes the pool prints; a third goes here beside them.
ADDITIONAL_COSTS: tuple[AdditionalCost, ...] = (
    AdditionalCost(
        "as an additional cost to cast this spell, sacrifice a creature",
        sacrifice_filter={"type_filter": "creature"},
    ),
    AdditionalCost(
        "as an additional cost to cast this spell, discard a card",
        discard_cards=1,
    ),
)


#: "You may cast this card from your <zone> by paying <costs> in addition to
#: paying its other costs." The costs half of the sentence
#: ``cast_permissions.self_permission_zone`` reads the zone half of.
_SELF_PERMISSION_COSTS = re.compile(
    r"^you may cast this card from your (?P<zone>graveyard|exile) by paying "
    r"(?P<costs>.+?) in addition to paying its other costs$"
)

#: The cost clauses that sentence may list, each mapped to the field it fills.
#: A clause outside this set makes the whole line unread — the card then reports
#: unsupported rather than castable at a discount, which is the direction a cost
#: must never drift in.
_SELF_PERMISSION_CLAUSES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(\d+) life$"), "pay_life"),
    (re.compile(r"^discarding (?:a|one) card$"), "discard_one"),
)


def _self_permission_cost(line: str) -> AdditionalCost | None:
    """The additional costs a self-granted zone permission charges, or None.

    Every clause must be read or the line is refused: a sentence that named a
    cost this table cannot charge would otherwise let the card be cast from the
    graveyard for less than it prints.
    """
    match = _SELF_PERMISSION_COSTS.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    fields: dict[str, int] = {"pay_life": 0, "discard_cards": 0}
    for clause in re.split(r",\s*|\s+and\s+", match.group("costs")):
        clause = clause.strip()
        if not clause:
            continue
        for pattern, field in _SELF_PERMISSION_CLAUSES:
            found = pattern.match(clause)
            if found is None:
                continue
            if field == "pay_life":
                fields["pay_life"] += int(found.group(1))
            else:
                fields["discard_cards"] += 1
            break
        else:
            return None
    return AdditionalCost(
        match.group(0), pay_life=fields["pay_life"],
        discard_cards=fields["discard_cards"], from_zone=match.group("zone"),
    )


def additional_cost_for_line(line: str) -> AdditionalCost | None:
    """The cost *line* states, or None when it states none.

    Matched on the line's whole text (minus a trailing period) rather than as a
    substring, because a substring match is how the whitelist this replaced came
    to claim things it did not implement.
    """
    text = line.strip().lower().rstrip(".")
    for cost in ADDITIONAL_COSTS:
        if text == cost.phrase:
            return cost
    return _self_permission_cost(line)


def additional_costs(card: CardDefinition) -> tuple[AdditionalCost, ...]:
    """Every additional cost *card* prints, in printed order."""
    found = [
        cost
        for line in (card.oracle_text or "").split("\n")
        if (cost := additional_cost_for_line(line)) is not None
    ]
    return tuple(found)


def cast_cost_claims_line(line: str) -> bool:
    """Whether this table reads *line*.

    The support gate and the parse-coverage report both ask this, so what the
    engine implements and what it claims to have read cannot drift — the same
    seam ``enter_effects.enter_effect_line`` is.
    """
    return additional_cost_for_line(line) is not None


__all__ = [
    "ADDITIONAL_COSTS",
    "AdditionalCost",
    "additional_cost_for_line",
    "additional_costs",
    "cast_cost_claims_line",
]
