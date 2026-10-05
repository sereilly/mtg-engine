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

**Three more parameters since Planeshift**, each a word the template can print
and the table used to refuse: *whose* lands ("Lands **you control** are …",
Natural Emergence — the source's controller, CR 109.5), a *keyword* the
animated lands have ("…creatures **with first strike**", layer 6), and the
two-sentence spelling of the same template ("…creatures. **They're still
lands.**"), which says nothing the one-sentence spelling does not. All three
are payload on the same instruction, and :func:`land_animation_reaches` is the
one answer to "which lands", asked by the layer-4 refresh and the layer-6 grant
alike.
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
    controller -- whose lands: ``"you"`` for "Lands **you control** are …"
                  (Natural Emergence), the seat that controls the *source*
                  (CR 109.5); None for "All …", which is every player's
    keywords   -- the keyword abilities the animated lands have ("…creatures
                  **with first strike**"), layer 6, lowercase; empty for a line
                  that prints none
    """

    land_type: str | None
    power: int
    toughness: int
    color: str | None = None
    controller: str | None = None
    keywords: tuple[str, ...] = ()


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
#
# The subject is "all <type>" or "<type> you control"; the tail is "that are
# still lands" or the same clause as a sentence of its own ("…. They're still
# lands", the spelling Oracle uses once anything follows "creatures"). Every
# optional group is a word the dataclass carries, so nothing here is matched
# and dropped.
_PATTERN = re.compile(
    r"^(?:all (?P<type>[a-z'-]+)|(?P<own_type>[a-z'-]+) you control)"
    r" are (?P<power>\d+)/(?P<toughness>\d+)"
    r"(?: (?P<color>[a-z]+))? creatures"
    r"(?: with (?P<keywords>[a-z ,]+?))?"
    r"(?: that are still lands|\. they're still lands)$"
)


def _keyword_list(words: str | None) -> tuple[str, ...] | None:
    """The keyword abilities "with <words>" names, or None when any of them is
    not one the engine implements.

    ``vocabulary.IMPLEMENTED_KEYWORDS`` is the registry — the one frozenset
    that says which keywords have behaviour behind them — so "with first
    strike" is granted and "with banding and horsemanship" would refuse the
    whole line rather than animate the lands and drop a word. Separated on the
    comma and the "and" a list of them prints.
    """
    if not words:
        return ()
    implemented = _vocabulary().IMPLEMENTED_KEYWORDS
    names = [
        name.strip()
        for name in re.split(r",\s*(?:and\s+)?|\s+and\s+", words.strip())
        if name.strip()
    ]
    if not names or any(name not in implemented for name in names):
        return None
    return tuple(names)


def land_animation_for(normalized_line: str) -> LandAnimation | None:
    """The land animation *normalized_line* imposes, or None.

    Takes an already-normalized line (``oracle.normalize_creature_line``), with
    or without its trailing period.
    """
    match = _PATTERN.match(normalized_line.strip().rstrip("."))
    if match is None:
        return None
    type_word = match.group("type") or match.group("own_type")
    controller = "you" if match.group("own_type") else None
    keywords = _keyword_list(match.group("keywords"))
    if keywords is None:
        return None
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
        controller=controller,
        keywords=keywords,
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
    # The two Planeshift keys, each emitted only when printed — so the four
    # animators that shipped before them compile to the payloads they had.
    if animation.controller:
        payload["controller"] = animation.controller
    if animation.keywords:
        payload["keywords"] = list(animation.keywords)
    return payload


def land_animation_from_payload(payload: dict) -> LandAnimation:
    """Rebuild the derived animation an ``animate_all_lands`` instruction carries."""
    land_type = payload.get("land_type")
    controller = payload.get("controller")
    return LandAnimation(
        land_type=str(land_type) if land_type is not None else None,
        power=int(payload.get("power", 1)),
        toughness=int(payload.get("toughness", 1)),
        color=payload.get("color"),
        controller=str(controller) if controller else None,
        keywords=tuple(str(word) for word in payload.get("keywords") or ()),
    )


def land_animation_reaches(game, source, animation: LandAnimation, permanent) -> bool:
    """Whether *animation*, printed on *source*, animates *permanent*.

    The whole of "which lands", in one place, because two layers ask it: the
    layer-4 refresh that makes the land a creature and the layer-6 pass that
    gives it the animation's keywords. Asked separately they would be two
    readings of one noun phrase, and a land could gain first strike from an
    enchantment that does not make it a creature.

    * a **land** — through ``has_type``, so a permanent an effect made a land
      counts and one that stopped being a land does not (CR 613 layer 4);
    * of the printed **land type**, likewise through the layers, so a land
      whose type an effect replaced animates by what it is now (CR 305.7);
    * under the **seat** the phrase names: "you control" is the controller of
      *source* (CR 109.5), read through the control seam on both sides, so a
      land or an animator that changes hands is answered as it stands. A
      source nobody controls reaches nothing.
    """
    if not permanent.has_type("land"):
        return False
    if animation.land_type is not None and not permanent.has_type(animation.land_type):
        return False
    if animation.controller == "you":
        seat = game.controller_index_of(source)
        if seat is None or game.controller_index_of(permanent) != seat:
            return False
    return True


__all__ = [
    "LAND_ANIMATION_KIND",
    "LandAnimation",
    "land_animation_for",
    "land_animation_from_payload",
    "land_animation_payload",
    "land_animation_reaches",
]
