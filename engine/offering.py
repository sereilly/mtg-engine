"""Offering (CR 702.48): an optional additional cost with two consequences.

CR 702.48a: "Offering is a static ability that functions while the spell with
offering is on the stack. '[Quality] offering' means 'As an additional cost to
cast this spell, you may sacrifice a [quality] permanent. If you chose to pay
the additional cost, this spell's total cost is reduced by the sacrificed
permanent's mana cost, and you may cast this spell any time you could cast an
instant.'"

Three pieces, and each is answered where its kind of question already is:

* **The cost** is the rule's first sentence, so the keyword line is rewritten
  into it before any line is classified (``line_rewrites.expand_ability_lines``,
  kicker's and buyback's arrangement): "As an additional cost to cast this
  spell, you may sacrifice a Fox." From there it is an ordinary CR 601.2b
  optional additional cost — the cost table (``cast_costs.additional_costs``)
  reads it with its ``optional_key`` ("sacrifice a fox"), the cast's
  ``optional_cost_payments`` takes it, the CR 601.2h gate counts the Foxes,
  the cost picker asks which one (CR 702.48b: chosen at 601.2b) and
  ``_pay_additional_costs`` sacrifices it at 601.2h — none of which knows the
  word.
* **The reduction** (CR 702.48c) is a fact about one cast — it is sized by the
  permanent *this* cast sacrifices — so it is no static modifier on the board.
  :func:`offering_announcement` names the permanent at the announcement (the
  named one, else the deterministic pick the payment will take) and
  :func:`offering_reduction` turns its mana cost into the CR 118.7 reduction
  the cast path folds into the one it already applies (CR 601.2f): generic
  reduces generic, each coloured or colourless symbol reduces its own type and
  any excess comes off generic — ``cost_modifiers.reduce_cost``'s spill,
  word for word.
* **The timing** is CR 601.3c: "If an effect allows a player to cast a spell
  as though it had flash only if an alternative or additional cost is paid,
  that player may begin to cast that spell as though it had flash." So the
  timing gates' one question (``cast_timing.casts_at_instant_speed``) opens
  the window while a permanent that could be offered is on the caster's side
  (:func:`offering_opens_instant_timing`), and the cast path refuses an
  announcement that used the window without paying the offering
  (:func:`offering_timing_refusal`) — CR 601.2e's illegal proposal, rewound.

Several instances (no card prints two) would be two optional costs with two
keys, each reducing by what it sacrificed; nothing here assumes one.

The reminder text is not the rule (CR 207.2a) and is never read: the sentence
is built from the keyword's own [quality].
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cast_cost_clauses import AdditionalCost
    from .cost_modifier_lines import CostReduction
    from .game import Game
    from .models import CardDefinition, Permanent

#: The rules text CR 702.48a gives the keyword's cost, with the [quality]
#: written as the card prints it.
OFFERING_COST_TEXT = (
    "As an additional cost to cast this spell, you may sacrifice a {quality}."
)

#: "Fox offering (You may cast this spell any time …)" — one word of quality,
#: the keyword, and an optional parenthesised reminder (CR 207.2a), alone on a
#: line. Anchored at both ends so a sentence that merely mentions offering is
#: never read as the card's keyword.
_OFFERING_LINE = re.compile(
    r"^(?P<quality>[a-z][a-z'\-]*) offering\s*(?:\([^()]*\))?\s*\.?$",
    re.IGNORECASE,
)

#: Any line that *is* an offering keyword line, readable or not — a quality of
#: several words, or one the vocabulary does not know. Wider than the reader,
#: so :func:`unread_offering_line` can refuse what the rewrite declined.
_OFFERING_SHAPE = re.compile(
    r"^[a-z][a-z'\- ]* offering\s*(?:\([^()]*\))?\s*\.?$", re.IGNORECASE,
)


def offering_quality(line: str) -> str | None:
    """The printed [quality] of one offering keyword line ("Fox"), or None
    when *line* is not one this module can rewrite.

    The quality must be a word the vocabulary knows as a subtype or a card
    type: the sentence it writes is read by the sacrifice clause's own noun
    reader, and a word that reader would take for something else is a
    permanent the card does not name.
    """
    from .grammar.vocabulary import ALL_SUBTYPES, CARD_TYPES

    match = _OFFERING_LINE.match(" ".join((line or "").split()))
    if match is None:
        return None
    quality = match.group("quality")
    if quality.lower() not in ALL_SUBTYPES and quality.lower() not in CARD_TYPES:
        return None
    return quality


def is_offering_line(line: str) -> bool:
    """Whether *line* is a printed offering keyword line, readable or not."""
    return _OFFERING_SHAPE.match(" ".join((line or "").split())) is not None


@lru_cache(maxsize=None)
def _offering_cost_for_quality(quality: str) -> "AdditionalCost | None":
    """The CR 601.2b cost the rewritten sentence states, read by the cost
    table itself — so the cost this module reasons about is the one the cast
    path charges, never a second reading of the same words."""
    from .cast_cost_clauses import additional_cost_for_line

    cost = additional_cost_for_line(OFFERING_COST_TEXT.format(quality=quality))
    if (
        cost is None
        or cost.optional_key is None
        or cost.sacrifice_filter is None
        or cost.sacrifice_count != 1
        or cost.sacrifice_any_number
    ):
        return None
    return cost


def expand_offering_line(line: str) -> str | None:
    """CR 702.48a's cost sentence for one printed offering line, or None."""
    quality = offering_quality(line)
    if quality is None or _offering_cost_for_quality(quality) is None:
        return None
    return OFFERING_COST_TEXT.format(quality=quality)


def expand_offering_lines(oracle_text: str) -> str:
    """*oracle_text* with every offering keyword line rewritten to its cost
    sentence. Text without one is returned unchanged (a substring test)."""
    if not oracle_text or "offering" not in oracle_text.lower():
        return oracle_text
    return "\n".join(
        expand_offering_line(line) or line for line in oracle_text.split("\n")
    )


def unread_offering_line(oracle_text: str) -> str | None:
    """A printed offering-shaped line this module cannot rewrite, or None.

    The support gate's question, asked of the text **after** the expansion
    (``soulshift.unread_soulshift_line``'s arrangement): a line the rewrite
    consumed is gone, and only one it declined can reach here.
    """
    if not oracle_text or "offering" not in oracle_text.lower():
        return None
    for line in oracle_text.split("\n"):
        if is_offering_line(line):
            return " ".join(line.split())
    return None


@lru_cache(maxsize=None)
def _printed_offering_costs(oracle_text: str) -> "tuple[AdditionalCost, ...]":
    costs = []
    for line in (oracle_text or "").split("\n"):
        quality = offering_quality(line)
        if quality is None:
            continue
        cost = _offering_cost_for_quality(quality)
        if cost is not None:
            costs.append(cost)
    return tuple(costs)


def offering_costs(card: "CardDefinition") -> "tuple[AdditionalCost, ...]":
    """The optional sacrifice each of *card*'s offering lines rewrites into,
    in printed order — empty for a card with no offering.

    Read off the **printed** text, which is what a card on the stack still
    carries (the rewrite happens inside the compiler), as
    ``cast_costs.kicker_costs`` reads kicker's.
    """
    text = getattr(card, "oracle_text", "") or ""
    if "offering" not in text.lower():
        return ()
    return _printed_offering_costs(text)


def has_offering(card: "CardDefinition") -> bool:
    """Whether *card* prints an offering this engine reads."""
    return bool(offering_costs(card))


def offering_taken(cost: "AdditionalCost", taken: "dict | None") -> bool:
    """Whether the announcement *taken* paid this offering (CR 601.2b)."""
    try:
        return int((taken or {}).get(cost.optional_key, 0) or 0) > 0
    except (TypeError, ValueError):
        return False


def offering_reduction(permanent: "Permanent") -> "CostReduction":
    """CR 702.48c: what sacrificing *permanent* takes off the spell's total
    cost.

    "Generic mana in the sacrificed permanent's mana cost reduces generic mana
    in the spell's total cost. Colored and colorless mana in the sacrificed
    permanent's mana cost reduces mana of the same type in spell's total cost,
    and any excess reduces that much generic mana" — which is exactly the
    spilling coloured reduction ``cost_modifiers.reduce_cost`` applies (CR
    118.7b–c), so the reduction is built in its vocabulary and applied there.

    The mana cost is the permanent's **effective** one (a Clone's is what it
    copied, CR 707.2; a token's is nothing, CR 202.1b; {X} is 0 off the stack,
    CR 107.3g) — ``mana_payment.permanent_mana_cost``. A cost this engine
    cannot read (a hybrid symbol) reduces nothing: the conservative answer for
    a discount, where reading it as smaller would at worst cost the caster.
    """
    from .cost_modifier_lines import CostReduction
    from .mana_payment import permanent_mana_cost

    cost = permanent_mana_cost(permanent) or {}
    generic = int(cost.get("generic", 0) or 0)
    colored = tuple(
        (symbol, int(amount))
        for symbol, amount in sorted(cost.items())
        if symbol != "generic" and amount
    )
    return CostReduction(generic=generic, colored=colored)


def offering_candidates(
    game: "Game", seat: int, cost: "AdditionalCost",
) -> "list[Permanent]":
    """The permanents *seat* could offer for *cost* — the list the CR 601.2h
    gate counts and the payment claims from (``_additional_cost_candidates``)."""
    return game._additional_cost_candidates(seat, cost, giving_up="sacrifice")


def offering_charges(
    game: "Game", seat: int, card, cost: "AdditionalCost", *,
    extra_generic: int = 0,
) -> "list[tuple[Permanent, dict[str, int]]]":
    """For each permanent *seat* could offer for *cost*, the mana a cast of
    *card* is charged when that one is offered — CR 601.2f's total with CR
    702.48c's reduction for it joined to the board's, through the one reader
    of a cast's price (``cost_modifiers.cast_mana_charge``, the arithmetic the
    cast path itself applies, ``CostReduction.plus``).

    The offer a client is shown before it names the permanent (W2G2): "every
    price the wire shows is the one the cast charges" holds for an offering
    only per permanent, because the reduction is sized by which one goes.
    *extra_generic* is what the zone adds (CR 903.8's commander tax)."""
    from .cost_modifiers import cast_mana_charge

    return [
        (permanent, cast_mana_charge(
            game, seat, card, extra_generic=extra_generic,
            reduction_bought=offering_reduction(permanent),
        ))
        for permanent in offering_candidates(game, seat, cost)
    ]


def offering_opens_instant_timing(game: "Game", seat: int, card) -> bool:
    """Whether *card*'s offering lets *seat* begin to cast it as though it had
    flash right now (CR 601.3c) — it prints one and *seat* controls a
    permanent it could sacrifice for it.

    The candidate is asked because CR 601.3c opens the window only to a cast
    that will pay the cost: with nothing to offer there is no announcement the
    window could carry, and a highlight glowing over one would be a cast the
    path then refuses.
    """
    return any(
        offering_candidates(game, seat, cost)
        for cost in offering_costs(card)
    )


def offering_timing_refusal(
    game: "Game", seat: int, card, taken: "dict | None",
) -> str | None:
    """Why this cast of *card* may not be made now, or None: it is being cast
    at a time a sorcery could not be (CR 307.1's timing), nothing but its
    offering lets it be (``cast_timing.another_source_gives_instant_timing``,
    its own "as though it had flash" sentence included), and the announcement
    did not pay the offering.

    CR 601.3c lets such a cast *begin*; CR 601.2e makes it illegal once the
    cost is not paid, and the game rewinds — nothing is spent, because this is
    asked before anything is.
    """
    from .cast_timing import (a_sorcery_could_be_cast,
                              another_source_gives_instant_timing,
                              grants_flash)

    costs = offering_costs(card)
    if not costs or any(offering_taken(cost, taken) for cost in costs):
        return None
    if a_sorcery_could_be_cast(game, seat):
        return None
    if another_source_gives_instant_timing(game, seat, card) or grants_flash(
        getattr(card, "oracle_text", "") or ""
    ):
        return None
    from .alternative_costs import board_noun

    noun = board_noun(costs[0].sacrifice_filter)
    return (
        f"{card.name} can be cast at this time only by paying its offering "
        f"(sacrifice a {noun}) (CR 702.48a, CR 601.3c)"
    )


def offering_announcement(
    game: "Game",
    seat: int,
    card,
    *,
    taken: "dict | None",
    named: "list[Permanent | None]",
) -> "tuple[Permanent, CostReduction] | None":
    """The permanent this cast offers and the reduction it buys, or None when
    the cast takes no offering (or has nothing to offer — the CR 601.2h gate
    says so, in one place).

    CR 702.48b: the permanent is chosen as the spell's choices are made
    (601.2b) — *named* is what the caster named on the cast's cost channel
    (``Game._named_cast_cost_payers``), and the first of them the offering
    could take is the one; with none named it is the deterministic pick the
    payment takes (``default_sacrifice_pick``) over the same candidates, so
    the permanent the reduction is sized by is the permanent sacrificed.
    """
    for cost in offering_costs(card):
        if not offering_taken(cost, taken):
            continue
        candidates = offering_candidates(game, seat, cost)
        if not candidates:
            return None
        chosen = next(
            (
                found for found in named
                if found is not None
                and any(found is candidate for candidate in candidates)
            ),
            None,
        )
        if chosen is None:
            chosen = game.default_sacrifice_pick(candidates)
        return chosen, offering_reduction(chosen)
    return None


__all__ = [
    "OFFERING_COST_TEXT",
    "expand_offering_line",
    "expand_offering_lines",
    "has_offering",
    "is_offering_line",
    "offering_announcement",
    "offering_candidates",
    "offering_charges",
    "offering_costs",
    "offering_opens_instant_timing",
    "offering_quality",
    "offering_reduction",
    "offering_taken",
    "offering_timing_refusal",
    "unread_offering_line",
]
