"""Regeneration effects."""

from __future__ import annotations

from ..oracle_types import _instruction
from .base import RuleResult, activated_kind, parse_rule


@parse_rule(77000)
def regenerate_target_creature(text: str, activated: bool) -> RuleResult:
    if "regenerate target creature" in text:
        effect_kind = activated_kind(activated, "regenerate")
        return _instruction("grant_regeneration_to_target_creature"), effect_kind
    return None


@parse_rule(78000)
def regenerate_self(text: str, activated: bool) -> RuleResult:
    if activated and "regenerate this creature" in text:
        return _instruction("grant_regeneration_to_self"), "activated_regenerate"
    return None


@parse_rule(79000)
def regenerate_enchanted_creature(text: str, activated: bool) -> RuleResult:
    if activated and "regenerate enchanted creature" in text:
        return _instruction("grant_regeneration_to_enchanted_creature"), "activated_regenerate"
    return None
