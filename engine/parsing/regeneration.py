"""Regeneration effects."""

from __future__ import annotations

import re

from ..oracle_types import _instruction
from .base import RuleResult, activated_kind, parse_rule
from .common import KNOWN_CREATURE_SUBTYPES

_REGENERATE_SUBTYPE_RE = re.compile(
    rf"regenerate target ({'|'.join(KNOWN_CREATURE_SUBTYPES)})\b"
)


@parse_rule(77000)
def regenerate_target_creature(text: str, activated: bool) -> RuleResult:
    if "regenerate target creature" in text:
        effect_kind = activated_kind(activated, "regenerate")
        return _instruction("grant_regeneration_to_target_creature"), effect_kind
    return None


# Elephant Graveyard: "Regenerate target Elephant."
@parse_rule(77200)
def regenerate_target_subtype(text: str, activated: bool) -> RuleResult:
    m = _REGENERATE_SUBTYPE_RE.search(text)
    if m:
        effect_kind = activated_kind(activated, "regenerate")
        return _instruction(
            "grant_regeneration_to_target_creature", subtype_filter=m.group(1)
        ), effect_kind
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


# Hurr Jackal: "Target creature can't be regenerated this turn."
@parse_rule(79500)
def deny_regeneration_to_target(text: str, activated: bool) -> RuleResult:
    if "target creature can't be regenerated this turn" in text:
        effect_kind = activated_kind(activated, "deny_regeneration")
        return _instruction("deny_regeneration_to_target"), effect_kind
    return None
