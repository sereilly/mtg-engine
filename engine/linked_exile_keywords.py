"""Keyword abilities read off a permanent's linked exile (CR 607.2a).

"As long as a card exiled with this creature has flying, this creature has
flying. The same is true for fear, first strike, double strike, haste,
landwalk, protection, and trample." (Death-Mask Duplicant.)

``line_rewrites.expand_same_is_true_lines`` writes the paragraph out as eight
conditional statics, and ``static_bonuses`` reads each into a
``conditional_static`` whose condition is :data:`LINKED_EXILE_HAS` — "a card
exiled with this creature has <quality>" — answered here, off the cards the
permanent's own imprint exiled that are still in exile
(``linked_exile.cards_still_exiled_with``). A card in exile has no layers
applied (CR 613.1), so what it "has" is what it prints
(``printed_characteristics``' keyword seed, the reader a permanent's printed
keywords start from).

**Landwalk and protection are families, not words** (CR 702.14a, 702.16a): a
card "has landwalk" when it has any landwalk ability, and the creature then
has *those* landwalk abilities — the 2004-12-01 ruling: "Death-Mask Duplicant
gains all landwalk and protection abilities of the imprinted creature cards.
If Death-Mask Duplicant imprints a card with protection from red and a card
with protection from creatures, it has protection from red and from
creatures." So the effect half of those two lines is not a keyword grant but
:data:`LINKED_EXILE_FAMILY`, carried out where each family is granted: the
layer-6 derived grants for landwalk (``mixins/lords``' conditional self-grant
step) and the protection reader for protection
(``mixins/protection._protection_qualities``). Both are read on every ask, so
a card leaving exile takes its ability with it (CR 611.3a).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import CardDefinition

#: The ``conditional_static`` condition kind: "a card exiled with this
#: creature has <quality>".
LINKED_EXILE_HAS = "linked_exile_has"

#: The ``conditional_static`` payload key whose value names a family the
#: permanent has every instance of that its linked cards print.
LINKED_EXILE_FAMILY = "linked_exile_family"

LANDWALK = "landwalk"
PROTECTION = "protection"

#: The families "has <word>" may name on both halves of the sentence.
FAMILIES = frozenset({LANDWALK, PROTECTION})


def _linked_cards(game, source) -> list["CardDefinition"]:
    from .linked_exile import cards_still_exiled_with

    if game is None or source is None:
        return []
    return [card for card, _owner in cards_still_exiled_with(game, source)]


def card_landwalks(card: "CardDefinition") -> tuple[str, ...]:
    """The landwalk abilities *card* prints — each one a quality the block
    check enforces (``landwalk.landwalk_requirement``); the bare family word
    the ingested keywords carry names no land and is left out."""
    from .landwalk import landwalk_requirement
    from .printed_characteristics import _printed_abilities

    return tuple(sorted(
        ability for ability in _printed_abilities(card)
        if landwalk_requirement(ability) is not None
    ))


def card_protection_clauses(card: "CardDefinition") -> list[str]:
    """Each "protection from …" clause *card* prints, through the reader a
    permanent's own printed protection is read by."""
    from .keywords import printed_protection_clauses
    from .oracle import compile_card_oracle

    return printed_protection_clauses(compile_card_oracle(card))


def card_has_quality(card: "CardDefinition", quality: str) -> bool:
    """Whether *card* — not a permanent — has the keyword *quality*, a family
    counting any member."""
    from .printed_characteristics import _printed_abilities

    if quality == LANDWALK:
        return bool(card_landwalks(card))
    if quality == PROTECTION:
        return bool(card_protection_clauses(card))
    return quality in _printed_abilities(card)


def linked_exile_has(game, source, quality: str) -> bool:
    """Whether a card exiled with *source* (and still exiled) has *quality*."""
    return any(card_has_quality(card, quality) for card in _linked_cards(game, source))


def linked_exile_landwalks(game, source) -> tuple[str, ...]:
    """Every landwalk ability a card exiled with *source* prints, once each
    (CR 702.14e: the same landwalk twice is redundant)."""
    walks: list[str] = []
    for card in _linked_cards(game, source):
        for walk in card_landwalks(card):
            if walk not in walks:
                walks.append(walk)
    return tuple(walks)


def linked_exile_protection_clauses(game, source) -> list[str]:
    """Every protection clause a card exiled with *source* prints."""
    clauses: list[str] = []
    for card in _linked_cards(game, source):
        clauses.extend(card_protection_clauses(card))
    return clauses


__all__ = [
    "FAMILIES",
    "LINKED_EXILE_FAMILY",
    "LINKED_EXILE_HAS",
    "card_has_quality",
    "card_landwalks",
    "card_protection_clauses",
    "linked_exile_has",
    "linked_exile_landwalks",
    "linked_exile_protection_clauses",
]
