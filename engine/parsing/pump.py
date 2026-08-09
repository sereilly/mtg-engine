"""Power/toughness pumps, counters, and keyword grants.

The generic forms — "target creature gets +N/+N until end of turn", the
self-pump variants, "enchanted creature gets +N/+N", the flying and banding
grants, and both base-P/T setters — are now productions in
``engine/grammar/parser.py``. Three of them had been written as one rule per
literal P/T value (``pump_self_1_0``, ``pump_self_0_1``, ``pump_self_1_1``),
which is the flat registry's scaling problem in miniature: a rule per number.

What is left bundles a pump with something the grammar has no node for yet — a
delayed sacrifice, a linked destruction, a conditional board-wide anthem.
"""

from __future__ import annotations

from ..oracle_types import _instruction
from .base import RuleResult, activated_kind, parse_rule


# Dragon Whelp: pump plus an activation counter and a delayed sacrifice.
@parse_rule(13000)
def dragon_whelp_pump(text: str, activated: bool) -> RuleResult:
    if (
        "this creature gets +1/+0 until end of turn" in text
        and "if this ability has been activated four or more times this turn" in text
        and "sacrifice this creature at the beginning of the next end step" in text
    ):
        return _instruction("pump_self_with_sacrifice_condition"), "activated_pump"
    return None


# Berserk: the pump size is the creature's own power, and it carries a delayed
# end-step destruction.
@parse_rule(58000)
def berserk_pump(text: str, activated: bool) -> RuleResult:
    if "target creature gains trample and gets +x/+0 until end of turn" in text:
        return _instruction("berserk_pump"), "spell_pattern"
    return None


# Sandals of Abdallah: "Target creature gains islandwalk until end of turn.
# When that creature dies this turn, destroy this artifact." The grant is
# linked to a delayed trigger on the granted creature.
@parse_rule(58500)
def grant_islandwalk_and_linked_destroy(text: str, activated: bool) -> RuleResult:
    if (
        "target creature gains islandwalk until end of turn" in text
        and "destroy this artifact" in text
    ):
        return _instruction("grant_islandwalk_and_linked_destroy"), activated_kind(activated, "keyword")
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


# Stone Giant: the target restriction compares the target's toughness against
# the source's power, and the grant carries a delayed destruction.
@parse_rule(93000)
def grant_flying_and_delayed_destruction(text: str, activated: bool) -> RuleResult:
    if activated and "target creature you control with toughness less than this creature's power gains flying until end of turn" in text:
        return _instruction("grant_flying_and_delayed_destruction"), "activated_keyword"
    return None
