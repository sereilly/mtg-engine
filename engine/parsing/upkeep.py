"""Upkeep pay-or-else effects (condition already stripped by the caller)."""

from __future__ import annotations

import re

from ..oracle_types import _NUMBER_WORDS, _extract_mana_cost_from_text, _instruction
from .base import RuleResult, parse_rule

_DAMAGE_UNLESS_PAY_RE = re.compile(r"this \w+ deals (\d+) damage to you unless you pay")
_SELF_DAMAGE_RE = re.compile(r"this creature deals (\d+) damage to you")
_CREATURES_ABOVE_RE = re.compile(r"(\w+) or more creature cards above it")
_SACRIFICE_LAND_CONDITIONAL_DAMAGE_RE = re.compile(
    r"sacrifice a land\. if you sacrifice an? (\w+) this way, this creature deals (\d+) damage to you"
)


# Cyclone: "put a wind counter on this enchantment, then sacrifice this
# enchantment unless you pay {G} for each wind counter on it. If you pay, this
# enchantment deals damage equal to the number of wind counters on it to each
# creature and each player." Must out-rank the generic pay-or-sacrifice rule.
@parse_rule(900)
def upkeep_wind_counter_pay_or_sacrifice(text: str, activated: bool) -> RuleResult:
    if (
        "put a wind counter on this enchantment" in text
        and "sacrifice this enchantment unless you pay {g} for each wind counter on it" in text
    ):
        return _instruction("upkeep_wind_counter_pay_or_sacrifice"), "upkeep_effect"
    return None


# "sacrifice this enchantment unless you pay {X}..." (Conversion, Stasis)
@parse_rule(1000)
def upkeep_pay_or_sacrifice_enchantment(text: str, activated: bool) -> RuleResult:
    if "sacrifice this enchantment unless you pay" in text:
        mana = _extract_mana_cost_from_text(text)
        return _instruction("upkeep_pay_or_sacrifice_enchantment", mana=mana), "upkeep_effect"
    return None


# "sacrifice this creature unless you pay {X}" (Seasinger, Sea Serpent variants)
@parse_rule(2000)
def upkeep_pay_or_sacrifice_self(text: str, activated: bool) -> RuleResult:
    if "sacrifice this creature unless you pay" in text:
        mana = _extract_mana_cost_from_text(text)
        return _instruction("upkeep_pay_or_sacrifice_self", mana=mana), "upkeep_effect"
    return None


# Mana Vault / Basalt Monolith / Island Fish Jasconius: "you may pay {N}. If you
# do, untap this artifact/permanent/creature." An optional pay during your own
# upkeep that untaps the source permanent.
@parse_rule(2200)
def upkeep_pay_to_untap_self(text: str, activated: bool) -> RuleResult:
    if "may pay" in text and (
        "untap this artifact" in text or "untap this permanent" in text or "untap this creature" in text
    ):
        mana = _extract_mana_cost_from_text(text)
        return _instruction("upkeep_pay_to_untap_self", mana=mana), "upkeep_effect"
    return None


# Paralyze: "that player may pay {N}. If the player does, untap the creature." An
# optional pay during the enchanted creature's controller's upkeep.
@parse_rule(2400)
def upkeep_pay_to_untap_enchanted(text: str, activated: bool) -> RuleResult:
    if "may pay" in text and ("untap the creature" in text or "untap enchanted creature" in text):
        mana = _extract_mana_cost_from_text(text)
        return _instruction("upkeep_pay_to_untap_enchanted", mana=mana), "upkeep_effect"
    return None


# "this creature/artifact deals N damage to you unless you pay {X}..." (Force of Nature)
@parse_rule(3000)
def upkeep_pay_or_deal_damage_to_controller(text: str, activated: bool) -> RuleResult:
    damage_unless_pay = _DAMAGE_UNLESS_PAY_RE.search(text)
    if damage_unless_pay:
        damage = int(damage_unless_pay.group(1))
        mana = _extract_mana_cost_from_text(text)
        return _instruction("upkeep_pay_or_deal_damage_to_controller", damage=damage, mana=mana), "upkeep_effect"
    return None


# "unless you pay {...}, tap this creature and sacrifice a land of an opponent's choice" (Demonic Hordes)
@parse_rule(4000)
def upkeep_pay_or_tap_and_sacrifice_opponent_land(text: str, activated: bool) -> RuleResult:
    if "unless you pay" in text and "sacrifice a land of an opponent" in text:
        mana = _extract_mana_cost_from_text(text)
        return _instruction("upkeep_pay_or_tap_and_sacrifice_opponent_land", mana=mana), "upkeep_effect"
    return None


# "sacrifice a creature other than this creature. if you can't, this creature deals N damage to you"
@parse_rule(5000)
def upkeep_sacrifice_other_creature_or_deal_damage(text: str, activated: bool) -> RuleResult:
    if "sacrifice a creature other than this creature" in text:
        alt_damage_match = _SELF_DAMAGE_RE.search(text)
        alt_damage = int(alt_damage_match.group(1)) if alt_damage_match else 0
        return _instruction("upkeep_sacrifice_other_creature_or_deal_damage", damage=alt_damage), "upkeep_effect"
    return None


# Serendib Djinn: "Sacrifice a land. If you sacrifice an Island this way,
# this creature deals 3 damage to you."
@parse_rule(5500)
def upkeep_sacrifice_land_conditional_damage(text: str, activated: bool) -> RuleResult:
    m = _SACRIFICE_LAND_CONDITIONAL_DAMAGE_RE.search(text)
    if m:
        land_type, damage = m.group(1), int(m.group(2))
        return _instruction(
            "upkeep_sacrifice_land_conditional_damage", land_type=land_type, damage=damage
        ), "upkeep_effect"
    return None


# Black Vise: "this artifact deals x damage to that player, where x is the number of cards in their hand minus 4"
@parse_rule(6000)
def upkeep_chosen_player_hand_overflow_damage(text: str, activated: bool) -> RuleResult:
    if "number of cards in their hand minus 4" in text:
        return _instruction("upkeep_chosen_player_hand_overflow_damage"), "upkeep_effect"
    return None


# Nether Shadow: "if this card is in your graveyard with N or more creature cards
# above it, you may put this card onto the battlefield". This ability functions
# from the graveyard, so resolve_upkeep scans the owner's graveyard for it.
@parse_rule(6500)
def upkeep_return_self_from_graveyard(text: str, activated: bool) -> RuleResult:
    if (
        "in your graveyard" in text
        and "creature cards above it" in text
        and "put this card onto the battlefield" in text
    ):
        match = _CREATURES_ABOVE_RE.search(text)
        min_above = _NUMBER_WORDS.get(match.group(1), 3) if match else 3
        return _instruction(
            "upkeep_return_self_from_graveyard", min_creatures_above=min_above
        ), "upkeep_effect"
    return None


# Erhnam Djinn: "target non-Wall creature an opponent controls gains
# forestwalk until your next upkeep."
@parse_rule(6600)
def grant_forestwalk_until_next_upkeep(text: str, activated: bool) -> RuleResult:
    if (
        "target non-wall creature an opponent controls gains forestwalk"
        in text
        and "until your next upkeep" in text
    ):
        return _instruction("grant_forestwalk_until_next_upkeep"), "upkeep_effect"
    return None


# Ghazbân Ogre: "if a player has more life than each other player, the player
# with the most life gains control of this creature."
@parse_rule(6700)
def upkeep_most_life_gains_control(text: str, activated: bool) -> RuleResult:
    if (
        "if a player has more life than each other player" in text
        and "the player with the most life gains control of this creature" in text
    ):
        return _instruction("upkeep_most_life_gains_control"), "upkeep_effect"
    return None


# Drop of Honey: "At the beginning of your upkeep, destroy the creature with
# the least power. It can't be regenerated. If two or more creatures are tied
# for least power, you choose one of them."
@parse_rule(6900)
def upkeep_destroy_least_power_creature(text: str, activated: bool) -> RuleResult:
    if "destroy the creature with the least power" in text:
        return _instruction("upkeep_destroy_least_power_creature"), "upkeep_effect"
    return None


# Magnetic Mountain: "At the beginning of each player's upkeep, that player
# may choose any number of tapped blue creatures they control and pay {4} for
# each creature chosen this way. If the player does, untap those creatures."
@parse_rule(6800)
def upkeep_pay_per_creature_untap_color(text: str, activated: bool) -> RuleResult:
    if (
        "may choose any number of tapped blue creatures they control" in text
        and "pay {4} for each creature chosen this way" in text
    ):
        return _instruction(
            "upkeep_pay_per_creature_untap_color", color="U", cost_per=4
        ), "upkeep_effect"
    return None
