"""Stack-interaction effects: copying and countering spells."""

from __future__ import annotations

from ..oracle_types import _instruction
from .base import RuleResult, parse_rule
from .common import find_color_word


@parse_rule(21000)
def copy_target_spell(text: str, activated: bool) -> RuleResult:
    if "copy target instant or sorcery spell" in text:
        return _instruction("copy_top_stack_spell"), "spell_pattern"
    return None


# Color-specific counterspells (Deathgrip, Lifeforce, etc.)
@parse_rule(104000)
def counter_target_color_spell(text: str, activated: bool) -> RuleResult:
    color_sym = find_color_word(text, "counter target {} spell")
    if color_sym:
        return _instruction("counter_top_stack_spell", color_filter=color_sym), "spell_pattern"
    return None


# Spell Blast: "Counter target spell with mana value X."
@parse_rule(104500)
def counter_target_spell_with_mana_value_x(text: str, activated: bool) -> RuleResult:
    if "counter target spell with mana value x" in text:
        return _instruction("counter_top_stack_spell", mv_equals_x=True), "spell_pattern"
    return None


# Power Sink: "Counter target spell unless its controller pays {X}. If that player
# doesn't, they tap all lands with mana abilities they control and lose all unspent
# mana." The controller may pay {X} (X chosen by Power Sink's caster) to save it.
@parse_rule(104800)
def counter_target_spell_unless_pays_x(text: str, activated: bool) -> RuleResult:
    if "counter target spell unless its controller pays {x}" in text:
        return _instruction("counter_top_stack_spell", unless_pays_x=True), "spell_pattern"
    return None


@parse_rule(105000)
def counter_target_spell(text: str, activated: bool) -> RuleResult:
    if "counter target spell" in text:
        return _instruction("counter_top_stack_spell"), "spell_pattern"
    return None
