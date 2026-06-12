"""Stack-interaction effects: copying and countering spells."""

from __future__ import annotations

from ..oracle_types import _COLOR_WORD_TO_SYMBOL, _instruction
from .base import RuleResult, parse_rule


@parse_rule(210)
def copy_target_spell(text: str, activated: bool) -> RuleResult:
    if "copy target instant or sorcery spell" in text:
        return _instruction("copy_top_stack_spell"), "spell_pattern"
    return None


# Color-specific counterspells (Deathgrip, Lifeforce, etc.)
@parse_rule(1040)
def counter_target_color_spell(text: str, activated: bool) -> RuleResult:
    for color_word, color_sym in _COLOR_WORD_TO_SYMBOL.items():
        if f"counter target {color_word} spell" in text:
            return _instruction("counter_top_stack_spell", color_filter=color_sym), "spell_pattern"
    return None


# Spell Blast: "Counter target spell with mana value X."
@parse_rule(1045)
def counter_target_spell_with_mana_value_x(text: str, activated: bool) -> RuleResult:
    if "counter target spell with mana value x" in text:
        return _instruction("counter_top_stack_spell", mv_equals_x=True), "spell_pattern"
    return None


@parse_rule(1050)
def counter_target_spell(text: str, activated: bool) -> RuleResult:
    if "counter target spell" in text:
        return _instruction("counter_top_stack_spell"), "spell_pattern"
    return None
