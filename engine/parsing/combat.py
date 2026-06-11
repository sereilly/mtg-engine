"""Combat-manipulation effects: blocking restrictions, combat removal."""

from __future__ import annotations

from ..oracle_types import _instruction
from .base import RuleResult, parse_rule


# Dwarven Warriors: make small creature unblockable
@parse_rule(120)
def grant_unblockable_to_low_power_target(text: str, activated: bool) -> RuleResult:
    if "target creature with power 2 or less can't be blocked this turn" in text:
        return _instruction("grant_unblockable_to_low_power_target"), "activated_evasion" if activated else "spell_pattern"
    return None


@parse_rule(230)
def grant_unlimited_blocking(text: str, activated: bool) -> RuleResult:
    if "target creature defending player controls can block any number of creatures this turn" in text:
        effect_kind = "activated_keyword" if activated else "spell_pattern"
        return _instruction("grant_unlimited_blocking"), effect_kind
    return None


@parse_rule(240)
def randomize_blockers(text: str, activated: bool) -> RuleResult:
    if "this turn, instead of declaring blockers" in text:
        return _instruction("randomize_blockers"), "spell_pattern"
    return None


@parse_rule(250)
def remove_creature_from_combat(text: str, activated: bool) -> RuleResult:
    if "remove target creature defending player controls from combat" in text:
        effect_kind = "activated_combat" if activated else "spell_pattern"
        return _instruction("remove_creature_from_combat"), effect_kind
    return None


@parse_rule(260)
def left_right_division_on_attack(text: str, activated: bool) -> RuleResult:
    if "whenever one or more creatures you control attack, each defending player divides all creatures without flying" in text:
        return _instruction("left_right_combat_division"), "spell_pattern"
    return None


@parse_rule(420)
def prevent_all_combat_damage(text: str, activated: bool) -> RuleResult:
    if "prevent all combat damage that would be dealt this turn" in text:
        return _instruction("prevent_all_combat_damage"), "spell_pattern"
    return None


@parse_rule(920)
def mark_non_wall_target_to_attack(text: str, activated: bool) -> RuleResult:
    if activated and "choose target non-wall creature" in text:
        return _instruction("mark_non_wall_target_to_attack"), "activated_combat"
    return None
