"""Entwine (CR 702.42), the keyword and the additional cost it *is*.

CR 702.42a: "Entwine is a static ability of modal spells (see rule 700.2)
that functions while the spell is on the stack. 'Entwine [cost]' means 'You
may choose all modes of this spell instead of just the number specified. If
you do, you pay an additional [cost].' Using the entwine ability follows the
rules for choosing modes and paying additional costs in rules 601.2b and
601.2f–h." CR 702.42b: "If the entwine cost was paid, follow the text of each
of the modes in the order written on the card when the spell resolves."

**Two halves, each landing on machinery that already exists.**

* *The cost* is kicker's shape exactly (``engine/cast_costs.py``): an
  additional cost announced at CR 601.2b, which the keyword line is rewritten
  into before any line is classified (:func:`expand_entwine_lines`, composed
  into ``line_rewrites.expand_ability_lines``). From there the cost table
  reads the offer, ``legality_cast_spec.cast_cost_offers`` prices it,
  ``cast_additional_costs._optional_cost_announcement`` checks it and the
  stack item records it under ``additional_costs_paid`` — mana ("Entwine
  {2}") and non-mana ("Entwine—Sacrifice three lands.") alike, through the
  reader kicker and buyback share (``cast_costs._optional_cost_phrase_offer``).
* *The modes* are CR 700.2's choice of **more than one** mode, which "Choose
  one or more —" (Sublime Epiphany, CR 700.2d) already announces: one
  ``ChosenMode`` per mode, each with its own targets (CR 601.2c), resolved in
  printed order (``resolution._resolve_card``'s loop; CR 702.42b and
  CR 608.2c say the same thing). So an entwined cast is a cast whose
  ``mode_choices`` name every mode and whose entwine offer was paid, and
  ``cast_announcement._resolve_chosen_modes`` holds the two together
  (:func:`entwine_mode_refusal`): paying is choosing all, and choosing all on
  a "choose one" card is paying.

What the word adds beyond those two is the *link* between them, and it has
one reader: :func:`entwined`, asked of the announcement exactly as
``cast_costs.kicked`` is, off the key the rewrite produced — so the offer that
is charged is exactly the offer that lets every mode be chosen.

A copy of an entwined spell is entwined (CR 707.10: a copy copies "all
decisions made for it, including modes, targets, the value of X, and
additional or alternative costs"), and needs nothing here: the copy carries
the original's ``chosen_modes`` (``handlers/spell_copies._copy_of_spell``).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING

from .cast_costs import (BUYBACK_RULES_TEXT, _BUYBACK_REMINDER,
                         _optional_cost_phrase_offer, _printed_additional_cost)

if TYPE_CHECKING:
    from .models import CardDefinition


#: "Entwine {1}", "Entwine {2}{R}", "Entwine {G}{G}{G}". One run of mana
#: symbols, kept as printed so a coloured pip keeps its letter.
_ENTWINE_LINE = re.compile(
    r"^entwine\s+(?P<cost>(?:\{[^{}]+\})+)$", re.IGNORECASE
)

#: "**Entwine—Sacrifice three lands.**" (Betrayal of Flesh, Solar Tide.)
#: CR 702.42a's cost is any cost; a non-mana one is printed behind an em dash,
#: kicker's and buyback's shape with the other keyword in front, and read by
#: the same function (``cast_costs._optional_cost_phrase_offer``).
_ENTWINE_COST_LINE = re.compile(
    r"^entwine\s*[—–-]\s*(?P<cost>.+)$", re.IGNORECASE
)

#: Any line that *is* an entwine keyword line, readable or not — the wider
#: shape the support gate asks, for ``cast_costs._KICKER_SHAPE``'s reason: an
#: entwine whose cost this file cannot read must be reported as a cost nothing
#: charges, never fall through and leave the card a plain "choose one" with
#: half its text dropped (which is what all eleven Mirrodin printings were
#: before this module). What follows the word has to open a cost.
_ENTWINE_SHAPE = re.compile(r"^entwine\s*(?:[—–-]|\{)", re.IGNORECASE)


def _stripped(line: str) -> str:
    """*line* with its reminder text and full stop off."""
    stripped = " ".join(_BUYBACK_REMINDER.sub("", line or "").split())
    return stripped.strip().rstrip(".")


def _entwine_line_offer(line: str) -> tuple[str, str] | None:
    """``(announcement key, rules sentence)`` for one entwine line, or None.

    The key is read **back off** the cost the rewritten sentence produces —
    never spelled a second time here, for ``cast_costs._buyback_line_offer``'s
    reason: it is what the announcement is recorded under and what
    :func:`entwined` reads it back by, and two spellings of one cost is a spell
    that paid its entwine and resolved one mode.
    """
    stripped = _stripped(line)
    match = _ENTWINE_LINE.match(stripped)
    if match is None:
        cost_match = _ENTWINE_COST_LINE.match(stripped)
        if cost_match is None:
            return None
        return _optional_cost_phrase_offer(cost_match.group("cost"))
    read = _printed_additional_cost(
        BUYBACK_RULES_TEXT.format(cost=match.group("cost"))
    )
    if read is None or len(read.optional_mana) != 1:
        return None
    offer = read.optional_mana[0]
    if offer.x_count or offer.repeatable:
        # "Entwine {X}" is printed nowhere, and an X would want its own
        # announcement beside the spell's: refused rather than read at 0.
        return None
    key = offer.symbols
    return key, BUYBACK_RULES_TEXT.format(cost=key)


def is_entwine_line(line: str) -> bool:
    """Whether *line* is a printed entwine keyword line, readable or not."""
    return _ENTWINE_SHAPE.match(_BUYBACK_REMINDER.sub("", line or "").strip()) is not None


def expand_entwine_line(line: str) -> str | None:
    """The CR 601.2b cost sentence one printed entwine line stands for, or
    None."""
    offer = _entwine_line_offer(line)
    return None if offer is None else offer[1]


def expand_entwine_lines(oracle_text: str) -> str:
    """*oracle_text* with every entwine keyword line rewritten to its cost
    sentence.

    Text without one is returned unchanged, so applying this to every card
    costs a substring test. Applied by the compiler before any line is
    classified, beside ``cast_costs.expand_kicker_lines`` and for its reason:
    what the compiler reads and what every other reader of a card's lines
    reads must be one text.
    """
    if not oracle_text or "ntwine" not in oracle_text:
        return oracle_text
    return "\n".join(
        expand_entwine_line(line) or line for line in oracle_text.split("\n")
    )


@lru_cache(maxsize=None)
def entwine_cost(oracle_text: str) -> str | None:
    """The canonical key *oracle_text*'s entwine offer is announced by, or
    None for a card printing no (readable) entwine.

    Read off the **printed** text, which is what a resolving spell's
    ``CardDefinition`` still carries — the rewrite happens inside the compiler
    and nothing writes it back onto the card. Cached because it is asked of
    every modal spell that is cast.
    """
    if "ntwine" not in (oracle_text or ""):
        return None
    for line in oracle_text.split("\n"):
        offer = _entwine_line_offer(line)
        if offer is not None:
            return offer[0]
    return None


def entwined(card: "CardDefinition", choices: dict | None) -> bool:
    """Whether this cast of *card* paid its entwine cost (CR 702.42a).

    *choices* is the cast's own record — the stack item's ``choices``, or a
    record shaped like it (``{"additional_costs_paid": …}``) built from an
    announcement in progress. False for a card printing no entwine and for an
    object nothing cast.
    """
    key = entwine_cost(getattr(card, "oracle_text", "") or "")
    if key is None:
        return False
    paid = (choices or {}).get("additional_costs_paid") or {}
    try:
        return int(paid.get(key, 0) or 0) > 0
    except (TypeError, ValueError):
        return False


def entwine_offered(card: "CardDefinition", key: str) -> bool:
    """Whether *key* is *card*'s entwine offer — for the readers that label an
    offer (the cast-offer prompt) or weigh one (the AI), so they need not know
    which spelling the rewrite produced."""
    return key is not None and key == entwine_cost(getattr(card, "oracle_text", "") or "")


def entwine_mode_refusal(
    card: "CardDefinition", mode_count: int, chosen: "list[int]",
    entwine_paid: bool,
) -> str | None:
    """Why an announcement choosing the modes *chosen* (indices) of a card with
    *mode_count* modes is illegal under CR 702.42a, or None.

    Asked by ``cast_announcement._resolve_chosen_modes`` only of a card that
    prints entwine. The two halves of the keyword's one sentence are one
    choice: "You may choose all modes … If you do, you pay an additional
    [cost]." So a paid entwine with fewer than every mode is a price paid for
    nothing (and a spell doing less than its controller paid for), and every
    mode chosen with the entwine unpaid is the whole card for the price of one
    mode — both refused, before any mana leaves the pool.
    """
    indices = [
        index for index in chosen
        if isinstance(index, int) and not isinstance(index, bool)
    ]
    every = (
        len(indices) == len(chosen) == mode_count
        and set(indices) == set(range(mode_count))
    )
    if entwine_paid and not every:
        return (
            f"{card.name}: an entwined cast chooses every mode "
            f"(CR 702.42a), not {len(chosen)} of {mode_count}"
        )
    if every and len(chosen) > 1 and not entwine_paid:
        return (
            f"{card.name}: choosing every mode is entwining it, and the "
            f"entwine cost was not paid (CR 702.42a)"
        )
    return None


def entwined_mode_choices(
    card: "CardDefinition", mode_choices: "list[dict] | None",
    taken: "dict[str, int] | None", *, names_cast_targets: bool,
    mode_index: "int | None" = None,
) -> "tuple[list[dict] | None, str | None]":
    """``(mode_choices, refusal)`` for a cast of *card* that took the offers
    *taken* — the cast's own *mode_choices* unchanged unless it paid the
    entwine and named no mode, in which case every mode, each naming nothing.

    Asked by the cast path as the card is known and **before** anything reads
    ``mode_choices``: the bare-cast default (``bare_announcements``) defaults a
    cast-level target only for a cast with no modes listed, and an entwined
    spell announces per mode (CR 601.2b chooses the modes, then CR 601.2c
    each mode's targets), so each mode's target is defaulted on the mode, as a
    "choose one or more" mode's is.

    A cast that paid the entwine, named no mode list and named targets on the
    *cast* (*names_cast_targets*: a seat or an object) is refused: those
    fields are one announcement's, and spreading them over several modes
    would be the engine guessing which mode each target was meant for. So is
    one that named a **single** mode (*mode_index*): paying the entwine is
    choosing every mode, and the two answers contradict each other — the
    caller asked for one bullet and paid for all of them.
    """
    if mode_choices or entwine_cost(getattr(card, "oracle_text", "") or "") is None:
        return mode_choices, None
    if not entwined(card, {"additional_costs_paid": taken or {}}):
        return mode_choices, None
    from .oracle import compile_card_oracle

    modes = compile_card_oracle(card).modes
    if not modes:
        return mode_choices, None
    if mode_index is not None:
        return None, (
            f"{card.name}: an entwined cast chooses every mode (CR 702.42a), "
            f"not mode {mode_index} alone"
        )
    if names_cast_targets:
        return None, (
            f"{card.name}: an entwined cast names each mode's targets on that "
            f"mode (CR 601.2c)"
        )
    return [{"index": index} for index in range(len(modes))], None


def unread_entwine_line(oracle_text: str) -> str | None:
    """The first entwine line of the **expanded** *oracle_text* the rewrite
    could not read, lowercased with its reminder off — or None.

    A readable one has already become the cost sentence, so what survives is a
    printing :func:`expand_entwine_line` refused. Asked by the support gate in
    ``engine/oracle.py``: a card whose entwine nothing charges would be a
    plain "choose one" with half its text dropped.
    """
    for line in (oracle_text or "").splitlines():
        if is_entwine_line(line) and expand_entwine_line(line) is None:
            return _stripped(line).lower()
    return None


def unsupported_entwine(
    printed_text: str, expanded_text: str, card_name: str | None = None,
) -> str | None:
    """Why *printed_text*'s entwine cannot be honoured, or None — the support
    gate's one question about the keyword (``engine/oracle.py``).

    Two ways, both refused rather than dropped:

    * the line survived the rewrite (:func:`unread_entwine_line`) — a cost
      nothing charges;
    * the card has **no modes** for the keyword to choose all of. CR 702.42a
      makes entwine "a static ability of modal spells", so on anything else
      the offer would be a price that buys nothing; no printing does this, and
      the gate is what keeps a future one loud.
    """
    unread = unread_entwine_line(expanded_text)
    if unread is not None:
        return f"printed cost nothing charges: {unread}"
    if entwine_cost(printed_text or "") is None:
        return None
    from .ability_lines import _modal_options

    if len(_modal_options(printed_text or "", card_name)) < 2:
        return "entwine printed on a spell with no modes to choose (CR 702.42a)"
    return None


__all__ = [
    "unsupported_entwine",
    "entwine_cost",
    "entwine_mode_refusal",
    "entwine_offered",
    "entwined",
    "entwined_mode_choices",
    "expand_entwine_line",
    "expand_entwine_lines",
    "is_entwine_line",
    "unread_entwine_line",
]
