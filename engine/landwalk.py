"""Landwalk (CR 702.14) — the ability's printed quality, and the land it looks for.

CR 702.14a spells the family as "[type]walk", where the type "is usually a land
type, but it can also be the card type land plus any combination of land types,
card types, and/or supertypes". So the pool prints two shapes:

``islandwalk``, ``forestwalk``, …
    the quality is a **land subtype**, welded onto the word.
``legendary landwalk`` (Livonya Silone), ``nonbasic landwalk``
    the quality is a **supertype** (optionally negated) sitting in front of the
    family word ``landwalk``.

Both are one question — "does the defending player control a land like this?"
(CR 702.14c) — so both are one requirement here rather than two enforcement
sites. The quality is **payload**: a card printing ``snow landwalk`` or
``world landwalk`` needs no code, because the supertype comes from
``data/vocabulary`` like every other type word, and a set printing a new land
subtype needs ``scripts/fetch_vocabulary.py`` and nothing else.

This module is also the *gate*: ``engine.oracle``'s keyword-line admission asks
:func:`landwalk_requirement` whether a printed quality is one the check below
can actually test. A quality admitted with nothing testing it would ship a
creature whose evasion silently never applies — the quiet failure the keyword
registry exists to prevent, in the one spelling ``IMPLEMENTED_KEYWORDS`` cannot
hold, since the ability's name *is* the printed quality.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import Permanent

#: The family word a quality-first landwalk is printed in front of.
LANDWALK = "landwalk"


class LandwalkRequirement(NamedTuple):
    """What land the defending player must control for this landwalk to apply.

    ``kind`` is ``"subtype"`` (``islandwalk`` → an Island) or ``"supertype"``
    (``legendary landwalk`` → a legendary land). ``negated`` is CR 702.14c's
    "without the specified type or supertype" — ``nonbasic landwalk``.
    """

    kind: str
    quality: str
    negated: bool = False


@lru_cache(maxsize=None)
def landwalk_requirement(ability: str) -> LandwalkRequirement | None:
    """The requirement *ability* names, or None if it is not landwalk at all.

    None is also the answer for the bare family word ``landwalk``: Scryfall's
    keywords field lists it beside the concrete ability (Livonya Silone is
    ``("Landwalk", "First strike", "Legendary landwalk")``), and a landwalk with
    no quality names no land, so it restricts no block.
    """
    from .grammar.vocabulary import LAND_TYPES, TYPE_LINE_SUPERTYPES

    ability = (ability or "").strip().lower().rstrip(".")
    if not ability:
        return None
    if ability.endswith("walk") and " " not in ability:
        subtype = ability[: -len("walk")]
        if subtype in LAND_TYPES:
            return LandwalkRequirement("subtype", subtype)
        return None
    head, _, tail = ability.partition(" ")
    if tail != LANDWALK:
        return None
    negated = head.startswith("non")
    quality = head[3:] if negated else head
    if quality in TYPE_LINE_SUPERTYPES:
        return LandwalkRequirement("supertype", quality, negated)
    return None


def is_landwalk(ability: str) -> bool:
    """Whether *ability* is a landwalk the engine can enforce."""
    return landwalk_requirement(ability) is not None


def land_satisfies(permanent: "Permanent", requirement: LandwalkRequirement) -> bool:
    """Whether *permanent* is the land CR 702.14c asks the defender to control.

    Types go through the computed accessors, so an animated land, a copy or a
    basic-land-type change answers with what it *currently* is. The supertype
    arm reads the effective type line for the reason ``printed_supertypes``
    documents: no layer computes a supertype, so the line an object effectively
    has is the whole answer.
    """
    from .layer_bridge import printed_supertypes

    if not permanent.has_type("land"):
        return False
    if requirement.kind == "subtype":
        return permanent.has_type(requirement.quality)
    held = requirement.quality in printed_supertypes(
        permanent.effective_card.type_line
    )
    return not held if requirement.negated else held


__all__ = [
    "LANDWALK",
    "LandwalkRequirement",
    "is_landwalk",
    "land_satisfies",
    "landwalk_requirement",
]
