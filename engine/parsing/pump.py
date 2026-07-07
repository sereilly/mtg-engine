"""Power/toughness pumps, counters, and keyword grants."""

from __future__ import annotations

import re

from ..oracle_types import _instruction
from .base import RuleResult, activated_kind, parse_rule

_PUMP_TARGET_X_RE = re.compile(r"target (?:blocking )?creature gets \+(x|\d+)/\+(x|\d+) until end of turn")
_PUMP_ENCHANTED_RE = re.compile(r"enchanted creature gets \+(-?\d+)/\+(-?\d+)")
# Sorceress Queen: "Target creature other than this creature has base power
# and toughness 0/2 until end of turn."
_SET_BASE_PT_BOTH_RE = re.compile(
    r"target creature( other than this creature)? has base power and toughness (\d+)/(\d+) until end of turn"
)
# Singing Tree: "Target attacking creature has base power 0 until end of
# turn." / Island of Wak-Wak: "Target creature with flying has base power 0
# until end of turn." — sets only power; toughness is untouched. Checked
# after the "and toughness" form so its digit group can't accidentally match
# "power and".
_SET_BASE_POWER_ONLY_RE = re.compile(
    r"target (?P<attacking>attacking )?creature(?P<flying> with flying)?"
    r"(?P<exclude_self> other than this creature)? has base power (?P<power>\d+) until end of turn"
)


# Dragon Whelp: pump and delayed sacrifice
@parse_rule(13000)
def dragon_whelp_pump(text: str, activated: bool) -> RuleResult:
    if (
        "this creature gets +1/+0 until end of turn" in text
        and "if this ability has been activated four or more times this turn" in text
        and "sacrifice this creature at the beginning of the next end step" in text
    ):
        return _instruction("pump_self_with_sacrifice_condition"), "activated_pump"
    return None


@parse_rule(58000)
def berserk_pump(text: str, activated: bool) -> RuleResult:
    if "target creature gains trample and gets +x/+0 until end of turn" in text:
        return _instruction("berserk_pump"), "spell_pattern"
    return None


# Sandals of Abdallah: "{2}, {T}: Target creature gains islandwalk until end
# of turn. When that creature dies this turn, destroy this artifact."
@parse_rule(58500)
def grant_islandwalk_and_linked_destroy(text: str, activated: bool) -> RuleResult:
    if (
        "target creature gains islandwalk until end of turn" in text
        and "destroy this artifact" in text
    ):
        return _instruction("grant_islandwalk_and_linked_destroy"), activated_kind(activated, "keyword")
    return None


@parse_rule(59000)
def grant_target_flying_until_eot(text: str, activated: bool) -> RuleResult:
    if "target creature gains flying until end of turn" in text:
        ek = activated_kind(activated, "keyword")
        return _instruction("grant_target_flying_until_eot"), ek
    return None


@parse_rule(60000)
def pump_target_creature_until_eot(text: str, activated: bool) -> RuleResult:
    pump_target_x_match = _PUMP_TARGET_X_RE.search(text)
    if pump_target_x_match:
        p_str, t_str = pump_target_x_match.group(1), pump_target_x_match.group(2)
        return _instruction(
            "pump_target_creature_until_eot",
            power=p_str if p_str == "x" else int(p_str),
            toughness=t_str if t_str == "x" else int(t_str),
            # Righteousness: "Target blocking creature gets +7/+7." The target is
            # restricted to a creature that is currently blocking (CR 509.1).
            blocking_only="target blocking creature" in text,
        ), "spell_pattern"
    return None


def _register_pump_self(order: int, power: int, toughness: int) -> None:
    @parse_rule(order, name=f"pump_self_{power}_{toughness}")
    def _rule(text: str, activated: bool) -> RuleResult:
        if activated and f"this creature gets +{power}/+{toughness} until end of turn" in text:
            return _instruction("pump_self", power=power, toughness=toughness), "activated_pump"
        return None


for _order, _power, _toughness in ((81000, 1, 0), (82000, 0, 1), (83000, 1, 1)):
    _register_pump_self(_order, _power, _toughness)


# Activated pump that applies to the enchanted creature (e.g. Firebreathing)
@parse_rule(84000)
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


@parse_rule(85000)
def grant_self_flying_until_eot(text: str, activated: bool) -> RuleResult:
    if activated and "this creature gains flying until end of turn" in text:
        return _instruction("grant_self_flying_until_eot"), "activated_keyword"
    return None


@parse_rule(86000)
def grant_banding_to_target(text: str, activated: bool) -> RuleResult:
    if activated and "target creature gains banding until end of turn" in text:
        return _instruction("grant_banding_to_target"), "activated_keyword"
    return None


@parse_rule(87000)
def add_counter_to_self(text: str, activated: bool) -> RuleResult:
    if activated and "put a +1/+1 counter on this creature" in text:
        return _instruction("add_counter_to_self", power=1, toughness=1), "activated_counter"
    return None


@parse_rule(88000)
def add_variable_power_counters(text: str, activated: bool) -> RuleResult:
    if activated and "put up to x +1/+0 counters on this creature" in text:
        return _instruction("add_variable_power_counters_to_self"), "activated_counter"
    return None


# Stone Giant: throw a smaller creature at the sky
@parse_rule(93000)
def grant_flying_and_delayed_destruction(text: str, activated: bool) -> RuleResult:
    if activated and "target creature you control with toughness less than this creature's power gains flying until end of turn" in text:
        return _instruction("grant_flying_and_delayed_destruction"), "activated_keyword"
    return None


@parse_rule(93500)
def set_base_pt_both_until_eot(text: str, activated: bool) -> RuleResult:
    m = _SET_BASE_PT_BOTH_RE.search(text)
    if m:
        exclude_self = bool(m.group(1))
        power, toughness = int(m.group(2)), int(m.group(3))
        ek = activated_kind(activated, "set_pt")
        return _instruction(
            "set_base_pt_target_until_eot",
            power=power, toughness=toughness, exclude_self=exclude_self,
        ), ek
    return None


@parse_rule(93600)
def set_base_power_only_until_eot(text: str, activated: bool) -> RuleResult:
    m = _SET_BASE_POWER_ONLY_RE.search(text)
    if m:
        ek = activated_kind(activated, "set_pt")
        return _instruction(
            "set_base_pt_target_until_eot",
            power=int(m.group("power")), toughness=None,
            exclude_self=bool(m.group("exclude_self")),
            attacking_only=bool(m.group("attacking")),
            flying_only=bool(m.group("flying")),
        ), ek
    return None
