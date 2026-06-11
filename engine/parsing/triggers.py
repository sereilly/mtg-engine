"""Triggered-ability effect patterns and trigger-effect shorthands."""

from __future__ import annotations

from ..oracle_types import _instruction
from .base import RuleResult, parse_rule


# Raging River: left/right pile combat division
@parse_rule(70)
def raging_river_division(text: str, activated: bool) -> RuleResult:
    if "each defending player divides all creatures without flying they control into a \"left\" pile and a \"right\" pile" in text:
        return _instruction("left_right_combat_division"), "triggered_combat"
    return None


# Cockatrice: effect-only match (trigger condition is already stripped by caller)
@parse_rule(80)
def delayed_destroy_blocked_or_blocker(text: str, activated: bool) -> RuleResult:
    if (
        "destroy that creature at end of combat" in text
        or "destroy that creature at the end of combat" in text
    ):
        return _instruction("delayed_destroy_blocked_or_blocker"), "triggered_delayed_destroy"
    return None


# Hypnotic Specter: effect-only match
@parse_rule(90)
def opponent_discards_random_card_on_damage(text: str, activated: bool) -> RuleResult:
    if "that player discards a card at random" in text:
        return _instruction("opponent_discards_random_card_on_damage"), "triggered_discard"
    return None


# Scavenging Ghoul: at end step, corpse counters for each creature that died
@parse_rule(100)
def add_corpse_counters(text: str, activated: bool) -> RuleResult:
    if (
        "put a corpse counter on this creature for each creature that died this turn" in text
        or "put a corpse counter on this creature for each creature that died" in text
    ):
        return _instruction("add_corpse_counters_for_each_creature_died"), "triggered_counter"
    return None


# Scavenging Ghoul: remove a corpse counter to regenerate
@parse_rule(110)
def remove_counter_to_regenerate(text: str, activated: bool) -> RuleResult:
    if "remove a corpse counter from this creature: regenerate this creature" in text:
        return _instruction("remove_counter_to_regenerate_self"), "activated_regenerate"
    return None


@parse_rule(360)
def sacrifice_if_no_creatures(text: str, activated: bool) -> RuleResult:
    if "no creatures are on the battlefield" in text and "sacrifice this" in text:
        return _instruction("sacrifice_if_no_creatures"), "triggered_sacrifice"
    return None


# ---------------------------------------------------------------------------
# Triggered-ability effect shorthands (no "activated" guard needed)
# ---------------------------------------------------------------------------

@parse_rule(1060)
def triggered_draw_a_card(text: str, activated: bool) -> RuleResult:
    if "draw a card" in text:
        return _instruction("draw_controller_cards", amount=1), "triggered_draw"
    return None


@parse_rule(1070)
def triggered_counter_on_self(text: str, activated: bool) -> RuleResult:
    if "put a +1/+1 counter on this creature" in text or "put a +1/+1 counter on it" in text:
        return _instruction("add_counter_to_self", power=1, toughness=1), "triggered_counter"
    return None


@parse_rule(1080)
def triggered_counter_on_target(text: str, activated: bool) -> RuleResult:
    if "put a +1/+1 counter on target creature" in text:
        return _instruction("add_counter_to_target", power=1, toughness=1), "triggered_counter"
    return None


@parse_rule(1090)
def triggered_you_lose(text: str, activated: bool) -> RuleResult:
    if "you lose the game" in text:
        return _instruction("player_loses_game"), "triggered_loss"
    return None


@parse_rule(1100)
def triggered_you_win(text: str, activated: bool) -> RuleResult:
    if "you win the game" in text:
        return _instruction("player_wins_game"), "triggered_win"
    return None


@parse_rule(1110)
def triggered_sacrifice_self(text: str, activated: bool) -> RuleResult:
    if "sacrifice this permanent" in text or "sacrifice this creature" in text or "sacrifice this enchantment" in text:
        return _instruction("sacrifice_self"), "triggered_sacrifice"
    return None


@parse_rule(1120)
def triggered_owner_loses_half_life(text: str, activated: bool) -> RuleResult:
    if "its owner loses half their life, rounded up" in text:
        return _instruction("owner_loses_half_life"), "triggered_loss"
    return None
