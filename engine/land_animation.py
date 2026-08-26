"""Text-keyed land animation (CR 613 layer 4).

"All Swamps are 1/1 black creatures that are still lands" (Kormus Bell) and
"All Forests are 1/1 creatures that are still lands" (Living Lands) are one
printed template with three parameters: which land type, what power/toughness,
and — optionally — what colour the animated lands become.

Both halves of the gate/dispatch split were live here, which is why this table
exists:

* The **gate** was two parse rules doing ``"all swamps are 1/1 black creatures
  that are still lands" in text``, each emitting an instruction kind that spelled
  the land type out (``animate_all_swamps`` / ``animate_all_forests``). A card
  printed "All Mountains are 1/1 red creatures that are still lands" matched
  neither literal and compiled **unsupported** — the false-negative failure.
* The **dispatch** (``mixins/permanent_state._refresh_dynamic_creatures``)
  matched ``perm.card.name == "Kormus Bell"``. A differently-named card with
  Kormus Bell's *exact* text therefore compiled **supported** and then animated
  nothing at all — the silent-wrongness failure, measured before this table was
  written.

One template, one instruction kind (``animate_all_lands``), one payload the
refresh reads. ``tests/rules/test_land_animation.py`` pins the name-agnosticism
with invented cards: a test naming only Kormus Bell passes against the broken
version, which is exactly how the sibling combat-restriction bug survived.

The land type is validated against ``data/vocabulary/land_types.json`` rather
than a hardcoded list of the five basics, because the enforcing check
(``Permanent.has_type``) resolves any land subtype through the layer system and
so does not care which one it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# The instruction kind a derived animation compiles to. One kind for the whole
# family: the land type, the P/T and the colour are payload, so a new printing
# of the template adds no dispatch.
LAND_ANIMATION_KIND = "animate_all_lands"


@dataclass(frozen=True)
class LandAnimation:
    """Lands of one type become creatures while the source is on the battlefield.

    land_type  -- the land subtype animated, singular and lowercase ("swamp"),
                  or None when the printed noun phrase is the bare card type
                  ("All **lands** are 1/1 creatures that are still lands",
                  Living Plane) and every land is animated whatever its
                  subtypes. None is "no restriction", not "unrecognized": an
                  unreadable subtype refuses the line (see below).
    power/toughness -- the base P/T the animated lands take (CR 613 layer 7b)
    color      -- mana symbol the animated lands become, or None when the
                  printed line names no colour (Living Lands says nothing about
                  colour, so its Forests keep theirs)
    """

    land_type: str | None
    power: int
    toughness: int
    color: str | None = None


@lru_cache(maxsize=1)
def _vocabulary():
    # Imported lazily: the grammar package imports engine-level derivation
    # modules, so a module-level import here would close a cycle.
    from .grammar import vocabulary

    return vocabulary


def _land_subtype(word: str) -> str | None:
    """The land type *word* names, however it was pluralised.

    The catalog stores singulars and "Plains" is its own plural, so each
    candidate stem is tried *against the catalog* instead of a shape being
    assumed — the same reason ``lord_buffs._creature_subtype`` works this way.
    """
    land_types = _vocabulary().LAND_TYPES
    for candidate in (word, word[:-1]):
        if candidate and candidate in land_types:
            return candidate
    return None


# The head noun when the sentence names no subtype at all: "All **lands** are
# 1/1 creatures that are still lands" (Living Plane). It is the card type, so it
# is read here rather than looked for in the subtype catalog — where it is
# absent, and where its absence would look exactly like an unknown subtype and
# refuse the line.
_UNTYPED_NOUNS = ("lands", "land")

# Anchored at both ends: a line that says anything more than this carries a
# rider the refresh would not perform, and admitting it would be the
# loose-gate/strict-dispatch defect one level down.
_PATTERN = re.compile(
    r"^all (?P<type>[a-z'-]+) are (?P<power>\d+)/(?P<toughness>\d+)"
    r"(?: (?P<color>[a-z]+))? creatures that are still lands$"
)


def land_animation_for(normalized_line: str) -> LandAnimation | None:
    """The land animation *normalized_line* imposes, or None.

    Takes an already-normalized line (``oracle.normalize_creature_line``), with
    or without its trailing period.
    """
    match = _PATTERN.match(normalized_line.strip().rstrip("."))
    if match is None:
        return None
    type_word = match.group("type")
    if type_word in _UNTYPED_NOUNS:
        # Every land, whatever it is called. Distinguished from the refusal
        # below by being checked first: both are spelled ``None`` on the
        # dataclass, and a subtype the catalog has never heard of must keep
        # refusing rather than widening into "all lands".
        land_type = None
    else:
        land_type = _land_subtype(type_word)
        if land_type is None:
            return None
    color_word = match.group("color")
    color = None
    if color_word is not None:
        color = _vocabulary().COLOR_WORDS.get(color_word)
        # "All Swamps are 1/1 *artifact* creatures that are still lands" would
        # reach here with an adjective this table cannot express. Refusing keeps
        # the card unsupported and loud rather than animating it as if the word
        # were not printed.
        if color is None:
            return None
    return LandAnimation(
        land_type=land_type,
        power=int(match.group("power")),
        toughness=int(match.group("toughness")),
        color=color,
    )


def land_animation_payload(animation: LandAnimation) -> dict[str, object]:
    """*animation* as an ``OracleInstruction`` payload."""
    payload: dict[str, object] = {
        "power": animation.power,
        "toughness": animation.toughness,
    }
    # Omitted rather than written as None when the sentence names no subtype:
    # the payload says what the line restricts, and an absent key is what the
    # refresh reads as "no restriction".
    if animation.land_type is not None:
        payload["land_type"] = animation.land_type
    if animation.color:
        payload["color"] = animation.color
    return payload


def land_animation_from_payload(payload: dict) -> LandAnimation:
    """Rebuild the derived animation an ``animate_all_lands`` instruction carries."""
    land_type = payload.get("land_type")
    return LandAnimation(
        land_type=str(land_type) if land_type is not None else None,
        power=int(payload.get("power", 1)),
        toughness=int(payload.get("toughness", 1)),
        color=payload.get("color"),
    )


__all__ = [
    "LAND_ANIMATION_KIND",
    "LandAnimation",
    "land_animation_for",
    "land_animation_from_payload",
    "land_animation_payload",
]
