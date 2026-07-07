"""Triggered-ability effect patterns and trigger-effect shorthands."""

from __future__ import annotations

import re

from ..oracle_types import _instruction
from .base import RuleResult, parse_rule

_LOSES_LIFE_UNLESS_PAY_RE = re.compile(
    r"that player loses (\d+) life at the beginning of their next draw step unless they pay \{(\d+)\} before that draw step"
)
_END_STEP_DAMAGE_IF_NOT_ATTACKED_RE = re.compile(
    r"if this creature didn't attack this turn, it deals (\d+) damage to you "
    r"unless it came under your control this turn"
)


# Raging River: left/right pile combat division
@parse_rule(7000)
def raging_river_division(text: str, activated: bool) -> RuleResult:
    if "each defending player divides all creatures without flying they control into a \"left\" pile and a \"right\" pile" in text:
        return _instruction("left_right_combat_division"), "triggered_combat"
    return None


# Cockatrice: effect-only match (trigger condition is already stripped by caller)
@parse_rule(8000)
def delayed_destroy_blocked_or_blocker(text: str, activated: bool) -> RuleResult:
    if (
        "destroy that creature at end of combat" in text
        or "destroy that creature at the end of combat" in text
    ):
        return _instruction("delayed_destroy_blocked_or_blocker"), "triggered_delayed_destroy"
    return None


# Hypnotic Specter: effect-only match
@parse_rule(9000)
def opponent_discards_random_card_on_damage(text: str, activated: bool) -> RuleResult:
    if "that player discards a card at random" in text:
        return _instruction("opponent_discards_random_card_on_damage"), "triggered_discard"
    return None


# El-Hajjaj: effect-only match — condition "whenever this creature deals
# damage" is already the existing creature_deals_damage trigger kind.
@parse_rule(9500)
def gain_life_equal_to_damage_dealt(text: str, activated: bool) -> RuleResult:
    if "you gain that much life" in text:
        return _instruction("gain_life_equal_to_damage_dealt"), "triggered_gain_life"
    return None


# Mijae Djinn: effect-only match — condition "whenever this creature attacks"
# already exists (creature_attacks).
@parse_rule(9600)
def coin_flip_remove_attacker_and_tap(text: str, activated: bool) -> RuleResult:
    if (
        "flip a coin" in text
        and "if you lose the flip, remove this creature from combat and tap it" in text
    ):
        return _instruction("coin_flip_remove_attacker_and_tap"), "triggered_coin_flip"
    return None


# Ydwen Efreet: effect-only match — condition "whenever this creature blocks"
# already exists (creature_blocks).
@parse_rule(9700)
def coin_flip_remove_blocker(text: str, activated: bool) -> RuleResult:
    if (
        "flip a coin" in text
        and "if you lose the flip, remove this creature from combat and it can't block this turn" in text
    ):
        return _instruction("coin_flip_remove_blocker"), "triggered_coin_flip"
    return None


# Nafs Asp: effect-only match — condition "whenever this creature deals
# damage to a player" is already covered by the deals-damage-to-player
# trigger family fired by _fire_combat_damage_to_player_triggers.
@parse_rule(9800)
def arm_draw_step_life_loss_unless_pay(text: str, activated: bool) -> RuleResult:
    m = _LOSES_LIFE_UNLESS_PAY_RE.search(text)
    if m:
        amount, cost = int(m.group(1)), int(m.group(2))
        return _instruction(
            "arm_draw_step_life_loss_unless_pay", amount=amount, cost=cost
        ), "triggered_delayed_life_loss"
    return None


# Erg Raiders: effect-only match — condition "at the beginning of your end
# step" is already the existing end_step trigger kind.
@parse_rule(9900)
def end_step_damage_if_not_attacked(text: str, activated: bool) -> RuleResult:
    m = _END_STEP_DAMAGE_IF_NOT_ATTACKED_RE.search(text)
    if m:
        return _instruction(
            "end_step_damage_if_not_attacked", amount=int(m.group(1))
        ), "triggered_damage"
    return None


# Scavenging Ghoul: at end step, corpse counters for each creature that died
@parse_rule(10000)
def add_corpse_counters(text: str, activated: bool) -> RuleResult:
    if (
        "put a corpse counter on this creature for each creature that died this turn" in text
        or "put a corpse counter on this creature for each creature that died" in text
    ):
        return _instruction("add_corpse_counters_for_each_creature_died"), "triggered_counter"
    return None


# Hasran Ogress: "Whenever this creature attacks, it deals 3 damage to you
# unless you pay {2}." Must out-rank the generic "deals N damage" spell rule
# (order 37000), which would drop the pay-out clause.
_SELF_DAMAGE_UNLESS_PAY_RE = re.compile(r"deals (\d+) damage to you unless you pay \{(\d+)\}")


@parse_rule(9850)
def self_damage_unless_pay(text: str, activated: bool) -> RuleResult:
    m = _SELF_DAMAGE_UNLESS_PAY_RE.search(text)
    if m:
        return _instruction(
            "self_damage_unless_pay", amount=int(m.group(1)), cost=int(m.group(2))
        ), "triggered_damage"
    return None


# Khabál Ghoul: at end step, +1/+1 counters for each creature that died.
# Must out-rank the generic "put a +1/+1 counter on this creature" shorthand
# (order 107000), which would drop the per-death scaling.
@parse_rule(10500)
def add_plus1_counters_for_deaths(text: str, activated: bool) -> RuleResult:
    if "put a +1/+1 counter on this creature for each creature that died this turn" in text:
        return _instruction(
            "add_plus1_counters_for_each_creature_died", power=1, toughness=1
        ), "triggered_counter"
    return None


# Unstable Mutation: "At the beginning of the upkeep of enchanted creature's
# controller, put a -1/-1 counter on that creature."
@parse_rule(10600)
def add_minus1_counter_to_enchanted(text: str, activated: bool) -> RuleResult:
    if "put a -1/-1 counter on that creature" in text:
        return _instruction("add_minus1_counter_to_enchanted"), "upkeep_effect"
    return None


# Scavenging Ghoul: remove a corpse counter to regenerate
@parse_rule(11000)
def remove_counter_to_regenerate(text: str, activated: bool) -> RuleResult:
    if "remove a corpse counter from this creature: regenerate this creature" in text:
        return _instruction("remove_counter_to_regenerate_self"), "activated_regenerate"
    return None


@parse_rule(36000)
def sacrifice_if_no_creatures(text: str, activated: bool) -> RuleResult:
    if "no creatures are on the battlefield" in text and "sacrifice this" in text:
        return _instruction("sacrifice_if_no_creatures"), "triggered_sacrifice"
    return None


# ---------------------------------------------------------------------------
# Triggered-ability effect shorthands (no "activated" guard needed)
# ---------------------------------------------------------------------------

@parse_rule(106000)
def triggered_draw_a_card(text: str, activated: bool) -> RuleResult:
    if "draw a card" in text:
        return _instruction("draw_controller_cards", amount=1), "triggered_draw"
    return None


@parse_rule(107000)
def triggered_counter_on_self(text: str, activated: bool) -> RuleResult:
    if "put a +1/+1 counter on this creature" in text or "put a +1/+1 counter on it" in text:
        return _instruction("add_counter_to_self", power=1, toughness=1), "triggered_counter"
    return None


@parse_rule(108000)
def triggered_counter_on_target(text: str, activated: bool) -> RuleResult:
    if "put a +1/+1 counter on target creature" in text:
        return _instruction("add_counter_to_target", power=1, toughness=1), "triggered_counter"
    return None


@parse_rule(109000)
def triggered_you_lose(text: str, activated: bool) -> RuleResult:
    if "you lose the game" in text:
        return _instruction("player_loses_game"), "triggered_loss"
    return None


@parse_rule(110000)
def triggered_you_win(text: str, activated: bool) -> RuleResult:
    if "you win the game" in text:
        return _instruction("player_wins_game"), "triggered_win"
    return None


@parse_rule(111000)
def triggered_sacrifice_self(text: str, activated: bool) -> RuleResult:
    if "sacrifice this permanent" in text or "sacrifice this creature" in text or "sacrifice this enchantment" in text:
        return _instruction("sacrifice_self"), "triggered_sacrifice"
    return None


@parse_rule(112000)
def triggered_owner_loses_half_life(text: str, activated: bool) -> RuleResult:
    if "its owner loses half their life, rounded up" in text:
        return _instruction("owner_loses_half_life"), "triggered_loss"
    return None
