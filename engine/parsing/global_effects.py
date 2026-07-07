"""Board-wide effects: symmetry resets, land animation, global buffs."""

from __future__ import annotations

import re
from typing import Any

from ..oracle_types import _COLOR_WORD_TO_SYMBOL, OracleInstruction, _instruction
from .base import RuleResult, parse_rule

_GLOBAL_BUFF_RE = re.compile(r"(white|blue|black|red|green)?\s*creatures(?: you control)? get \+(\d+)/\+(\d+)")


@parse_rule(22000)
def balance_resources(text: str, activated: bool) -> RuleResult:
    if "each player chooses a number of lands they control equal to the number of lands controlled by the player who controls the fewest" in text:
        return _instruction("balance_resources"), "spell_pattern"
    return None


# Global buff / animate-land effects (e.g. Kormus Bell, Living Lands)
@parse_rule(113000)
def animate_all_swamps(text: str, activated: bool) -> RuleResult:
    if "all swamps are 1/1 black creatures that are still lands" in text:
        return _instruction("animate_all_swamps"), "spell_pattern"
    return None


@parse_rule(114000)
def animate_all_forests(text: str, activated: bool) -> RuleResult:
    if "all forests are 1/1 creatures that are still lands" in text:
        return _instruction("animate_all_forests"), "spell_pattern"
    return None


_BASIC_LAND_TYPES = ("mountains", "forests", "islands", "swamps", "plains")
_STATIC_LAND_TYPE_RE = re.compile(
    rf"all ({'|'.join(_BASIC_LAND_TYPES)}) are ({'|'.join(_BASIC_LAND_TYPES)})\b"
)
# Plains is its own singular; the rest drop the trailing "s".
_LAND_TYPE_SINGULAR = {
    "mountains": "mountain",
    "forests": "forest",
    "islands": "island",
    "swamps": "swamp",
    "plains": "plains",
}


# Static basic-land-type change (e.g. Conversion: "All Mountains are Plains.").
# The generic land-animation rules above use an "are 1/1 creatures" clause, so a
# plain "X are Y" form (no "creature") is unambiguous here.
@parse_rule(114500)
def static_land_type_change(text: str, activated: bool) -> RuleResult:
    m = _STATIC_LAND_TYPE_RE.search(text)
    if m and "creature" not in text:
        return _instruction(
            "static_land_type_change",
            from_type=_LAND_TYPE_SINGULAR[m.group(1)],
            to_type=_LAND_TYPE_SINGULAR[m.group(2)],
        ), "spell_pattern"
    return None


@parse_rule(115000)
def buff_attacking_creatures(text: str, activated: bool) -> RuleResult:
    if "attacking creatures you control get +1/+0" in text:
        return _instruction("buff_attacking_creatures", power=1, toughness=0), "spell_pattern"
    return None


@parse_rule(116000)
def buff_untapped_creatures(text: str, activated: bool) -> RuleResult:
    if "untapped creatures you control get +0/+2" in text:
        return _instruction("buff_untapped_creatures", power=0, toughness=2), "spell_pattern"
    return None


# Generic creatures-get pump (e.g. "white creatures get +1/+1")
@parse_rule(117000)
def buff_creatures_global(text: str, activated: bool) -> RuleResult:
    global_match = _GLOBAL_BUFF_RE.search(text)
    if global_match:
        color_word, power_s, toughness_s = global_match.groups()
        payload: dict[str, Any] = {"power": int(power_s), "toughness": int(toughness_s)}
        if color_word:
            payload["color"] = _COLOR_WORD_TO_SYMBOL.get(color_word)
        payload["all"] = "you control" not in text
        # Army of Allah: "Attacking creatures get +2/+0 until end of turn."
        # Only creatures that are attacking when the spell resolves get the
        # buff. Word boundary so "nonattacking" can never match.
        if re.search(r"\battacking creatures get\b", text):
            payload["attacking_only"] = True
        # Piety: "Blocking creatures get +0/+3 until end of turn." — found by
        # the parse-coverage deletion probe (the qualifier was being dropped).
        if re.search(r"\bblocking creatures get\b", text):
            payload["blocking_only"] = True
        # Jihad: the anthem only applies while the chosen player controls a
        # nontoken permanent of the chosen color (choices stamped at ETB;
        # evaluated in _recalculate_lord_buffs).
        if "as long as the chosen player controls a nontoken permanent of the chosen color" in text:
            payload["requires_chosen_color_permanent"] = True
        return OracleInstruction("buff_creatures_global", "", payload), "spell_pattern"
    return None
