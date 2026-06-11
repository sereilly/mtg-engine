"""Damage-dealing effects."""

from __future__ import annotations

import re

from ..oracle_types import _instruction
from .base import RuleResult, parse_rule

_DAMAGE_AND_SELF_RE = re.compile(r"deals (\d+) damage to any target and (\d+) damage to you")
_DAMAGE_N_RE = re.compile(r"deals (\d+) damage")


@parse_rule(290)
def earthquake_damage(text: str, activated: bool) -> RuleResult:
    if "deals x damage" in text and "each creature without flying" in text:
        effect_kind = "activated_damage" if activated else "spell_pattern"
        return _instruction("earthquake_damage", amount="x"), effect_kind
    return None


@parse_rule(300)
def hurricane_damage(text: str, activated: bool) -> RuleResult:
    if "deals x damage" in text and "each creature with flying" in text:
        effect_kind = "activated_damage" if activated else "spell_pattern"
        return _instruction("hurricane_damage", amount="x"), effect_kind
    return None


@parse_rule(310)
def deal_x_damage_and_gain_life(text: str, activated: bool) -> RuleResult:
    if "deals x damage" in text and "you gain life equal to the damage dealt" in text:
        effect_kind = "activated_damage" if activated else "spell_pattern"
        return _instruction("deal_damage_and_gain_life", amount="x"), effect_kind
    return None


@parse_rule(320)
def deal_x_damage(text: str, activated: bool) -> RuleResult:
    if "deals x damage" in text:
        effect_kind = "activated_damage" if activated else "spell_pattern"
        return _instruction("deal_damage", amount="x"), effect_kind
    return None


@parse_rule(330)
def deal_damage_and_self_damage(text: str, activated: bool) -> RuleResult:
    self_dmg_match = _DAMAGE_AND_SELF_RE.search(text)
    if self_dmg_match:
        effect_kind = "activated_damage" if activated else "spell_pattern"
        return _instruction(
            "deal_damage_and_self_damage",
            amount=int(self_dmg_match.group(1)),
            self_damage=int(self_dmg_match.group(2)),
        ), effect_kind
    return None


@parse_rule(340)
def deal_damage_equal_to_swamps(text: str, activated: bool) -> RuleResult:
    if "deals damage" in text and "equal to the number of swamps" in text:
        return _instruction("deal_damage_equal_to_swamps"), "upkeep_effect"
    return None


@parse_rule(350)
def deal_damage_each_creature_and_player(text: str, activated: bool) -> RuleResult:
    if "deals 1 damage to each creature and each player" in text:
        effect_kind = "activated_damage" if activated else "spell_pattern"
        return _instruction("deal_damage_each_creature_and_player", amount=1), effect_kind
    return None


@parse_rule(370)
def deal_n_damage(text: str, activated: bool) -> RuleResult:
    dmg_match = _DAMAGE_N_RE.search(text)
    if dmg_match:
        effect_kind = "activated_damage" if activated else "spell_pattern"
        return _instruction("deal_damage", amount=int(dmg_match.group(1))), effect_kind
    return None
