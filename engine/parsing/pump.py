"""Power/toughness pumps, counters, and keyword grants."""

from __future__ import annotations

import re

from ..oracle_types import _instruction
from .base import RuleResult, parse_rule

_PUMP_TARGET_X_RE = re.compile(r"target (?:blocking )?creature gets \+(x|\d+)/\+(x|\d+) until end of turn")
_PUMP_ENCHANTED_RE = re.compile(r"enchanted creature gets \+(-?\d+)/\+(-?\d+)")


# Dragon Whelp: pump and delayed sacrifice
@parse_rule(130)
def dragon_whelp_pump(text: str, activated: bool) -> RuleResult:
    if (
        "this creature gets +1/+0 until end of turn" in text
        and "if this ability has been activated four or more times this turn" in text
        and "sacrifice this creature at the beginning of the next end step" in text
    ):
        return _instruction("pump_self_with_sacrifice_condition"), "activated_pump"
    return None


@parse_rule(580)
def berserk_pump(text: str, activated: bool) -> RuleResult:
    if "target creature gains trample and gets +x/+0 until end of turn" in text:
        return _instruction("berserk_pump"), "spell_pattern"
    return None


@parse_rule(590)
def grant_target_flying_until_eot(text: str, activated: bool) -> RuleResult:
    if "target creature gains flying until end of turn" in text:
        ek = "activated_keyword" if activated else "spell_pattern"
        return _instruction("grant_target_flying_until_eot"), ek
    return None


@parse_rule(600)
def pump_target_creature_until_eot(text: str, activated: bool) -> RuleResult:
    pump_target_x_match = _PUMP_TARGET_X_RE.search(text)
    if pump_target_x_match:
        p_str, t_str = pump_target_x_match.group(1), pump_target_x_match.group(2)
        return _instruction(
            "pump_target_creature_until_eot",
            power=p_str if p_str == "x" else int(p_str),
            toughness=t_str if t_str == "x" else int(t_str),
        ), "spell_pattern"
    return None


@parse_rule(810)
def pump_self_power(text: str, activated: bool) -> RuleResult:
    if activated and "this creature gets +1/+0 until end of turn" in text:
        return _instruction("pump_self", power=1, toughness=0), "activated_pump"
    return None


@parse_rule(820)
def pump_self_toughness(text: str, activated: bool) -> RuleResult:
    if activated and "this creature gets +0/+1 until end of turn" in text:
        return _instruction("pump_self", power=0, toughness=1), "activated_pump"
    return None


@parse_rule(830)
def pump_self_both(text: str, activated: bool) -> RuleResult:
    if activated and "this creature gets +1/+1 until end of turn" in text:
        return _instruction("pump_self", power=1, toughness=1), "activated_pump"
    return None


# Activated pump that applies to the enchanted creature (e.g. Firebreathing)
@parse_rule(840)
def pump_enchanted_creature(text: str, activated: bool) -> RuleResult:
    if activated:
        m = _PUMP_ENCHANTED_RE.search(text)
        if m:
            return _instruction(
                "pump_enchanted_creature",
                power=int(m.group(1)),
                toughness=int(m.group(2)),
            ), "activated_pump"
    return None


@parse_rule(850)
def grant_self_flying_until_eot(text: str, activated: bool) -> RuleResult:
    if activated and "this creature gains flying until end of turn" in text:
        return _instruction("grant_self_flying_until_eot"), "activated_keyword"
    return None


@parse_rule(860)
def grant_banding_to_target(text: str, activated: bool) -> RuleResult:
    if activated and "target creature gains banding until end of turn" in text:
        return _instruction("grant_banding_to_target"), "activated_keyword"
    return None


@parse_rule(870)
def add_counter_to_self(text: str, activated: bool) -> RuleResult:
    if activated and "put a +1/+1 counter on this creature" in text:
        return _instruction("add_counter_to_self", power=1, toughness=1), "activated_counter"
    return None


@parse_rule(880)
def add_variable_power_counters(text: str, activated: bool) -> RuleResult:
    if activated and "put up to x +1/+0 counters on this creature" in text:
        return _instruction("add_variable_power_counters_to_self"), "activated_counter"
    return None


# Stone Giant: throw a smaller creature at the sky
@parse_rule(930)
def grant_flying_and_delayed_destruction(text: str, activated: bool) -> RuleResult:
    if activated and "target creature you control with toughness less than this creature's power gains flying until end of turn" in text:
        return _instruction("grant_flying_and_delayed_destruction"), "activated_keyword"
    return None
