"""Board-wide effects: symmetry resets, land animation, global buffs."""

from __future__ import annotations

import re
from typing import Any

from ..oracle_types import _COLOR_WORD_TO_SYMBOL, OracleInstruction, _instruction
from .base import RuleResult, parse_rule

_GLOBAL_BUFF_RE = re.compile(r"(white|blue|black|red|green)?\s*creatures(?: you control)? get \+(\d+)/\+(\d+)")


@parse_rule(220)
def balance_resources(text: str, activated: bool) -> RuleResult:
    if "each player chooses a number of lands they control equal to the number of lands controlled by the player who controls the fewest" in text:
        return _instruction("balance_resources"), "spell_pattern"
    return None


# Global buff / animate-land effects (e.g. Kormus Bell, Living Lands)
@parse_rule(1130)
def animate_all_swamps(text: str, activated: bool) -> RuleResult:
    if "all swamps are 1/1 black creatures that are still lands" in text:
        return _instruction("animate_all_swamps"), "spell_pattern"
    return None


@parse_rule(1140)
def animate_all_forests(text: str, activated: bool) -> RuleResult:
    if "all forests are 1/1 creatures that are still lands" in text:
        return _instruction("animate_all_forests"), "spell_pattern"
    return None


@parse_rule(1150)
def buff_attacking_creatures(text: str, activated: bool) -> RuleResult:
    if "attacking creatures you control get +1/+0" in text:
        return _instruction("buff_attacking_creatures", power=1, toughness=0), "spell_pattern"
    return None


@parse_rule(1160)
def buff_untapped_creatures(text: str, activated: bool) -> RuleResult:
    if "untapped creatures you control get +0/+2" in text:
        return _instruction("buff_untapped_creatures", power=0, toughness=2), "spell_pattern"
    return None


# Generic creatures-get pump (e.g. "white creatures get +1/+1")
@parse_rule(1170)
def buff_creatures_global(text: str, activated: bool) -> RuleResult:
    global_match = _GLOBAL_BUFF_RE.search(text)
    if global_match:
        color_word, power_s, toughness_s = global_match.groups()
        payload: dict[str, Any] = {"power": int(power_s), "toughness": int(toughness_s)}
        if color_word:
            payload["color"] = _COLOR_WORD_TO_SYMBOL.get(color_word)
        payload["all"] = "you control" not in text
        return OracleInstruction("buff_creatures_global", "", payload), "spell_pattern"
    return None
