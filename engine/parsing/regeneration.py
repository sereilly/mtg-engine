"""Regeneration effects."""

from __future__ import annotations

from ..oracle_types import _instruction
from .base import RuleResult, parse_rule


@parse_rule(770)
def regenerate_target_creature(text: str, activated: bool) -> RuleResult:
    if "regenerate target creature" in text:
        effect_kind = "activated_regenerate" if activated else "spell_pattern"
        return _instruction("grant_regeneration_to_target_creature"), effect_kind
    return None


@parse_rule(780)
def regenerate_self(text: str, activated: bool) -> RuleResult:
    if activated and "regenerate this creature" in text:
        return _instruction("grant_regeneration_to_self"), "activated_regenerate"
    return None


@parse_rule(790)
def regenerate_enchanted_creature(text: str, activated: bool) -> RuleResult:
    if activated and "regenerate enchanted creature" in text:
        return _instruction("grant_regeneration_to_enchanted_creature"), "activated_regenerate"
    return None
