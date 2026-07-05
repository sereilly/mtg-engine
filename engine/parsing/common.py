"""Shared text-parsing helpers for the parse-rule modules.

This module registers no ``@parse_rule`` functions — it only hosts logic the
category modules share (mirroring ``engine/handlers/_common.py`` on the
handler side). Keeping these in one place stops each new rule from
re-implementing color-word scans, duration literals, or target noun-phrase
filtering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..oracle_types import _COLOR_WORD_TO_SYMBOL

# Creature subtypes the target-noun parser recognizes ("destroy target Wall").
# Extend this tuple when a set introduces tribal targeting (e.g. Arabian
# Nights adds camel/elephant/djinn/efreet).
KNOWN_CREATURE_SUBTYPES: tuple[str, ...] = ("wall",)


def find_color_word(text: str, template: str = "{}") -> str | None:
    """Mana symbol of the first color word whose ``template.format(word)``
    occurs in *text* (e.g. ``find_color_word(text, "counter target {} spell")``),
    or None. For a bare-word scan that must not match inside "nonblack"-style
    prefixes, use :func:`find_padded_color_word`."""
    for word, sym in _COLOR_WORD_TO_SYMBOL.items():
        if template.format(word) in text:
            return sym
    return None


def find_padded_color_word(text: str) -> str | None:
    """Mana symbol of the first color word appearing as a whitespace-padded
    word in *text* (so "nonblack" does not match "black"), or None."""
    padded = f" {text} "
    for word, sym in _COLOR_WORD_TO_SYMBOL.items():
        if f" {word} " in padded:
            return sym
    return None


def find_excluded_colors(text: str) -> list[str]:
    """Mana symbols excluded by "non<color>" wording ("nonblack creature")."""
    return [sym for word, sym in _COLOR_WORD_TO_SYMBOL.items() if f"non{word}" in text]


def find_excluded_types(text: str) -> list[str]:
    """Card types excluded by "non<type>" wording ("nonartifact creature")."""
    return [t for t in ("artifact", "creature", "enchantment", "land") if f"non{t}" in text]


def cant_be_regenerated(text: str) -> bool:
    """Whether the clause forbids regeneration ("It can't be regenerated.")."""
    return "can't be regenerated" in text or "cannot be regenerated" in text


def parse_duration(text: str) -> str | None:
    """Canonical duration token for a clause, or None when no duration wording
    is present (an unqualified effect is permanent)."""
    if "until end of turn" in text or "this turn" in text:
        return "until_end_of_turn"
    if "until end of combat" in text:
        return "until_end_of_combat"
    return None


@dataclass(frozen=True)
class TargetFilter:
    """Structured form of a "target <noun phrase>" restriction.

    Produced by :func:`parse_target_filter`; consumed at resolution time by
    ``engine.handlers._common.permanent_matches_filter`` so parsing and
    runtime legality share one vocabulary.
    """

    type_filter: str | None = None
    subtype_filter: str | None = None
    tapped_only: bool = False
    color_filter: str | None = None
    exclude_colors: tuple[str, ...] = ()
    exclude_types: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """Instruction-payload dict, emitting only the keys that are set (the
        exact key set the destroy_target rule has always produced)."""
        payload: dict[str, Any] = {}
        if self.type_filter:
            payload["type_filter"] = self.type_filter
        if self.subtype_filter:
            payload["subtype_filter"] = self.subtype_filter
        if self.tapped_only:
            payload["tapped_only"] = True
        if self.color_filter:
            payload["color_filter"] = self.color_filter
        if self.exclude_colors:
            payload["exclude_colors"] = list(self.exclude_colors)
        if self.exclude_types:
            payload["exclude_types"] = list(self.exclude_types)
        return payload


def parse_target_filter(clause: str, full_text: str) -> TargetFilter:
    """Parse the noun phrase following "target" into a :class:`TargetFilter`.

    *clause* is the text after "target" up to the sentence end (adjectives such
    as "tapped", "nonblack", or a subtype like "Wall" can sit between "target"
    and the type word). *full_text* is the whole normalized clause — color and
    non-exclusion wording is scanned there, matching the historical
    destroy_target behavior.
    """

    def _clause_has(word: str) -> bool:
        # Word boundary so "creature" doesn't match inside "noncreature".
        return re.search(rf"\b{word}\b", clause) is not None

    type_filter: str | None = None
    subtype_filter: str | None = None
    if "artifact or enchantment" in clause:
        type_filter = "artifact_or_enchantment"
    else:
        for subtype in KNOWN_CREATURE_SUBTYPES:
            if _clause_has(subtype):
                # Subtype words imply the creature type ("destroy target Wall").
                type_filter = "creature"
                subtype_filter = subtype
                break
    if type_filter is None:
        if _clause_has("creature"):
            type_filter = "creature"
        elif _clause_has("artifact"):
            type_filter = "artifact"
        elif _clause_has("enchantment"):
            type_filter = "enchantment"
        elif _clause_has("land"):
            type_filter = "land"
    return TargetFilter(
        type_filter=type_filter,
        subtype_filter=subtype_filter,
        tapped_only=_clause_has("tapped"),
        color_filter=find_padded_color_word(full_text),
        exclude_colors=tuple(find_excluded_colors(full_text)),
        exclude_types=tuple(find_excluded_types(full_text)),
    )
