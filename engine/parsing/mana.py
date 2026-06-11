"""Mana production and mana-cost effects."""

from __future__ import annotations

from ..oracle_types import _instruction
from .base import RuleResult, parse_rule


@parse_rule(270)
def drain_target_lands_mana(text: str, activated: bool) -> RuleResult:
    if "activates a mana ability of each land they control" in text and "loses all unspent mana" in text:
        return _instruction("drain_target_lands_mana"), "spell_pattern"
    return None


@parse_rule(500)
def sacrifice_creature_for_black_mana(text: str, activated: bool) -> RuleResult:
    if "as an additional cost to cast this spell, sacrifice a creature" in text:
        return _instruction("sacrifice_creature_for_black_mana"), "spell_pattern"
    return None


@parse_rule(890)
def sacrifice_self_for_mana(text: str, activated: bool) -> RuleResult:
    if activated and "add three mana of any one color" in text:
        return _instruction("sacrifice_self_for_mana", amount=3, color="G", any_color=True), "activated_mana"
    return None


@parse_rule(1010)
def channel_life_for_mana(text: str, activated: bool) -> RuleResult:
    if "you may pay 1 life" in text and "add {c}" in text:
        return _instruction("channel_life_for_mana"), "spell_pattern"
    return None


@parse_rule(1020)
def add_one_mana_any_color(text: str, activated: bool) -> RuleResult:
    if activated and "add one mana of any color" in text:
        return _instruction("add_mana_from_text", oracle_text=text, any_color=True), "activated_mana"
    return None


@parse_rule(1030)
def add_mana_from_text(text: str, activated: bool) -> RuleResult:
    if "add {" in text:
        any_color = "any one color" in text or "any color" in text
        effect_kind = "activated_mana" if activated else "spell_pattern"
        return _instruction("add_mana_from_text", oracle_text=text, any_color=any_color), effect_kind
    return None
