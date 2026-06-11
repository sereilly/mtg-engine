"""Upkeep pay-or-else effects (condition already stripped by the caller)."""

from __future__ import annotations

import re

from ..oracle_types import _extract_mana_cost_from_text, _instruction
from .base import RuleResult, parse_rule

_DAMAGE_UNLESS_PAY_RE = re.compile(r"this \w+ deals (\d+) damage to you unless you pay")
_SELF_DAMAGE_RE = re.compile(r"this creature deals (\d+) damage to you")


# "sacrifice this enchantment unless you pay {X}..." (Conversion, Stasis)
@parse_rule(10)
def upkeep_pay_or_sacrifice_enchantment(text: str, activated: bool) -> RuleResult:
    if "sacrifice this enchantment unless you pay" in text:
        mana = _extract_mana_cost_from_text(text)
        return _instruction("upkeep_pay_or_sacrifice_enchantment", mana=mana), "upkeep_effect"
    return None


# "sacrifice this creature unless you pay {X}" (Seasinger, Sea Serpent variants)
@parse_rule(20)
def upkeep_pay_or_sacrifice_self(text: str, activated: bool) -> RuleResult:
    if "sacrifice this creature unless you pay" in text:
        mana = _extract_mana_cost_from_text(text)
        return _instruction("upkeep_pay_or_sacrifice_self", mana=mana), "upkeep_effect"
    return None


# "this creature/artifact deals N damage to you unless you pay {X}..." (Force of Nature)
@parse_rule(30)
def upkeep_pay_or_deal_damage_to_controller(text: str, activated: bool) -> RuleResult:
    damage_unless_pay = _DAMAGE_UNLESS_PAY_RE.search(text)
    if damage_unless_pay:
        damage = int(damage_unless_pay.group(1))
        mana = _extract_mana_cost_from_text(text)
        return _instruction("upkeep_pay_or_deal_damage_to_controller", damage=damage, mana=mana), "upkeep_effect"
    return None


# "unless you pay {...}, tap this creature and sacrifice a land of an opponent's choice" (Demonic Hordes)
@parse_rule(40)
def upkeep_pay_or_tap_and_sacrifice_opponent_land(text: str, activated: bool) -> RuleResult:
    if "unless you pay" in text and "sacrifice a land of an opponent" in text:
        mana = _extract_mana_cost_from_text(text)
        return _instruction("upkeep_pay_or_tap_and_sacrifice_opponent_land", mana=mana), "upkeep_effect"
    return None


# "sacrifice a creature other than this creature. if you can't, this creature deals N damage to you"
@parse_rule(50)
def upkeep_sacrifice_other_creature_or_deal_damage(text: str, activated: bool) -> RuleResult:
    if "sacrifice a creature other than this creature" in text:
        alt_damage_match = _SELF_DAMAGE_RE.search(text)
        alt_damage = int(alt_damage_match.group(1)) if alt_damage_match else 0
        return _instruction("upkeep_sacrifice_other_creature_or_deal_damage", damage=alt_damage), "upkeep_effect"
    return None


# Black Vise: "this artifact deals x damage to that player, where x is the number of cards in their hand minus 4"
@parse_rule(60)
def upkeep_chosen_player_hand_overflow_damage(text: str, activated: bool) -> RuleResult:
    if "number of cards in their hand minus 4" in text:
        return _instruction("upkeep_chosen_player_hand_overflow_damage"), "upkeep_effect"
    return None
