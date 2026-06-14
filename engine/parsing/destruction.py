"""Permanent destruction effects."""

from __future__ import annotations

import re
from typing import Any

from ..oracle_types import _COLOR_WORD_TO_SYMBOL, OracleInstruction, _instruction
from .base import RuleResult, parse_rule

_DESTROY_LAND_TYPE_RE = re.compile(r"destroy all (plains|islands|swamps|mountains|forests)")


@parse_rule(520)
def chaos_orb_flip(text: str, activated: bool) -> RuleResult:
    if "flip it onto the battlefield" in text:
        return _instruction("chaos_orb_flip"), "activated_chaos_orb"
    return None


@parse_rule(530)
def destroy_all_artifacts_creatures_enchantments(text: str, activated: bool) -> RuleResult:
    if "destroy all artifacts, creatures, and enchantments" in text:
        return _instruction("destroy_all_artifacts_creatures_enchantments"), "spell_pattern"
    return None


@parse_rule(540)
def destroy_all_creatures(text: str, activated: bool) -> RuleResult:
    if "destroy all creatures" in text:
        no_regen = "can't be regenerated" in text or "cannot be regenerated" in text
        payload: dict[str, Any] = {"bypass_regeneration": True} if no_regen else {}
        return OracleInstruction("destroy_all_creatures", "", payload), "spell_pattern"
    return None


@parse_rule(550)
def destroy_all_enchantments(text: str, activated: bool) -> RuleResult:
    if "destroy all enchantments" in text:
        return _instruction("destroy_all_enchantments"), "spell_pattern"
    return None


@parse_rule(560)
def destroy_all_lands(text: str, activated: bool) -> RuleResult:
    if "destroy all lands" in text:
        return _instruction("destroy_all_lands"), "spell_pattern"
    return None


# Destroy all of a specific land type (e.g., "Destroy all Plains.")
@parse_rule(570)
def destroy_all_lands_of_type(text: str, activated: bool) -> RuleResult:
    m = _DESTROY_LAND_TYPE_RE.search(text)
    if m:
        land = m.group(1)
        return _instruction("destroy_all_lands_of_type", land_type=land), "spell_pattern"
    return None


@parse_rule(610)
def destroy_target(text: str, activated: bool) -> RuleResult:
    if "destroy target" not in text:
        return None
    effect_kind = "activated_destroy" if activated else "spell_pattern"
    # Inspect the noun phrase that follows "destroy target" — adjectives such as
    # "tapped", "nonblack", or a subtype like "Wall" can sit between "target" and
    # the actual type word (e.g. "destroy target tapped creature",
    # "destroy target nonartifact, nonblack creature", "destroy target Wall").
    # Matching the bare type word with a word boundary avoids false hits inside
    # "noncreature"/"nonartifact" (those have no boundary before the type word).
    clause = text.split("destroy target", 1)[1].split(".")[0]

    def _clause_has(word: str) -> bool:
        return re.search(rf"\b{word}\b", clause) is not None

    type_filter: str | None = None
    subtype_filter: str | None = None
    if "artifact or enchantment" in clause:
        type_filter = "artifact_or_enchantment"
    elif _clause_has("wall"):
        # Walls are creatures; restrict by the Wall subtype (e.g. Tunnel).
        type_filter = "creature"
        subtype_filter = "wall"
    elif _clause_has("creature"):
        type_filter = "creature"
    elif _clause_has("artifact"):
        type_filter = "artifact"
    elif _clause_has("enchantment"):
        type_filter = "enchantment"
    elif _clause_has("land"):
        type_filter = "land"
    # "destroy target tapped creature" (Royal Assassin) only hits tapped permanents.
    tapped_only = _clause_has("tapped")
    color_filter: str | None = next(
        (sym for word, sym in _COLOR_WORD_TO_SYMBOL.items() if f" {word} " in f" {text} "),
        None,
    )
    # Parse exclusion restrictions: "nonblack", "nonartifact", etc.
    exclude_colors: list[str] = []
    for word, sym in _COLOR_WORD_TO_SYMBOL.items():
        if f"non{word}" in text:
            exclude_colors.append(sym)
    exclude_types: list[str] = []
    for t in ("artifact", "creature", "enchantment", "land"):
        if f"non{t}" in text:
            exclude_types.append(t)
    destroy_payload: dict[str, Any] = {}
    if type_filter:
        destroy_payload["type_filter"] = type_filter
    if subtype_filter:
        destroy_payload["subtype_filter"] = subtype_filter
    if tapped_only:
        destroy_payload["tapped_only"] = True
    if color_filter:
        destroy_payload["color_filter"] = color_filter
    if exclude_colors:
        destroy_payload["exclude_colors"] = exclude_colors
    if exclude_types:
        destroy_payload["exclude_types"] = exclude_types
    no_regen_destroy = "can't be regenerated" in text or "cannot be regenerated" in text
    if no_regen_destroy:
        destroy_payload["bypass_regeneration"] = True
    return OracleInstruction("destroy_target_permanent", "", destroy_payload), effect_kind
