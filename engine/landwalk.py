"""Landwalk (CR 702.14) — the ability's printed quality, and the land it looks for.

CR 702.14a spells the family as "[type]walk", where the type "is usually a land
type, but it can also be the card type land plus any combination of land types,
card types, and/or supertypes". So the pool prints two shapes:

``islandwalk``, ``forestwalk``, …
    the quality is a **land subtype**, welded onto the word.
``legendary landwalk`` (Livonya Silone), ``nonbasic landwalk``
    the quality is a **supertype** (optionally negated) sitting in front of the
    family word ``landwalk``.
``snow forestwalk``, ``snow swampwalk`` (Ice Age)
    "any combination" taken literally: a supertype **and** a subtype, and the
    defending player must control a land answering both. This is why a
    requirement is a *tuple* of qualities rather than one — a reader that kept
    only the last word would let Rime Dryad through against any Forest, which
    is a strictly better creature than the one printed, and one that kept only
    the first would make it unblockable against any snow land at all.

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


class LandQuality(NamedTuple):
    """One of the qualities a landwalk names.

    ``kind`` is ``"subtype"`` (``islandwalk`` → an Island) or ``"supertype"``
    (``legendary landwalk`` → a legendary land). ``negated`` is CR 702.14c's
    "without the specified type or supertype" — ``nonbasic landwalk``.
    """

    kind: str
    quality: str
    negated: bool = False


class LandwalkRequirement(NamedTuple):
    """What land the defending player must control for this landwalk to apply.

    Every quality must hold of the **same** land (CR 702.14c): "snow
    forestwalk" asks for one land that is both, not for a snow land and,
    separately, a Forest.
    """

    qualities: tuple[LandQuality, ...]


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
    words = ability.split()
    if not words[-1].endswith("walk"):
        return None
    qualities: list[LandQuality] = []
    # Every word but the last is a supertype, optionally negated ("nonbasic
    # landwalk", "snow forestwalk"). An unknown one refuses the whole ability
    # rather than being skipped: a quality dropped from an evasion restriction
    # widens it, which is the one direction this must never go.
    for head in words[:-1]:
        negated = head.startswith("non")
        quality = head[3:] if negated else head
        if quality not in TYPE_LINE_SUPERTYPES:
            return None
        qualities.append(LandQuality("supertype", quality, negated))
    tail = words[-1]
    if tail != LANDWALK:
        subtype = tail[: -len("walk")]
        if subtype not in LAND_TYPES:
            return None
        qualities.append(LandQuality("subtype", subtype))
    if not qualities:
        # The bare family word, which names no land and so restricts no block.
        return None
    return LandwalkRequirement(tuple(qualities))


def is_landwalk(ability: str) -> bool:
    """Whether *ability* is a landwalk the engine can enforce."""
    return landwalk_requirement(ability) is not None


def land_satisfies(permanent: "Permanent", requirement: LandwalkRequirement) -> bool:
    """Whether *permanent* is the land CR 702.14c asks the defender to control.

    Types go through the computed accessors, so an animated land, a copy or a
    basic-land-type change answers with what it *currently* is — and the
    supertype arm does too, since layer 4 computes those as well: a land Arcum's
    Weathervane has thawed is no longer the snow Forest a snow forestwalker
    needs.
    """
    if not permanent.has_type("land"):
        return False
    supertypes = None
    for quality in requirement.qualities:
        if quality.kind == "subtype":
            if not permanent.has_type(quality.quality):
                return False
            continue
        if supertypes is None:
            supertypes = permanent.effective_supertypes
        held = quality.quality in supertypes
        if held == quality.negated:
            return False
    return True


__all__ = [
    "LANDWALK",
    "LandQuality",
    "LandwalkRequirement",
    "is_landwalk",
    "land_satisfies",
    "landwalk_requirement",
]
