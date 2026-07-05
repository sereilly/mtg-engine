"""Effects that don't fit a larger category: text changes, recoloring,
land-type changes, self-animation, token creation."""

from __future__ import annotations

from typing import Any

from ..oracle_types import OracleInstruction, _instruction
from .base import RuleResult, parse_rule
from .common import find_color_word


@parse_rule(48000)
def mark_text_modified(text: str, activated: bool) -> RuleResult:
    if "change the text of target spell or permanent by replacing all instances of one" in text:
        # Magical Hack swaps a basic land type; Sleight of Mind swaps a color word.
        # The mode decides whether the handler remaps land types/landwalk or stores
        # a color-word remap — neither recolors the target permanent.
        if "basic land type" in text:
            return _instruction("mark_text_modified", mode="land_type"), "spell_pattern"
        if "color word" in text:
            return _instruction("mark_text_modified", mode="color_word"), "spell_pattern"
        return _instruction("mark_text_modified"), "spell_pattern"
    return None


@parse_rule(51000)
def recolor_target(text: str, activated: bool) -> RuleResult:
    target_color = find_color_word(text, "becomes {}")
    if target_color:
        payload: dict[str, Any] = {"target_color": target_color}
        return OracleInstruction("recolor_target_from_text", "", payload), "spell_pattern"
    return None


@parse_rule(91000)
def change_target_land_type(text: str, activated: bool) -> RuleResult:
    if activated and "target land becomes a forest" in text:
        return _instruction("change_target_land_type", land_type="forest"), "activated_landtype"
    return None


@parse_rule(96000)
def animate_self_until_end_of_combat(text: str, activated: bool) -> RuleResult:
    if activated and "this artifact becomes a 3/6 golem artifact creature until end of combat" in text:
        return _instruction("animate_self_until_end_of_combat", power=3, toughness=6), "activated_animate"
    return None


@parse_rule(97000)
def create_wasp_token(text: str, activated: bool) -> RuleResult:
    # The Hive — emits the generic create_token instruction (engine/tokens.py).
    if activated and "create a 1/1 colorless insect artifact creature token with flying named wasp" in text:
        return _instruction(
            "create_token",
            name="Wasp",
            power=1,
            toughness=1,
            type_line="Artifact Creature — Insect",
            keywords=("Flying",),
        ), "activated_token"
    return None


@parse_rule(100000)
def add_mire_counter(text: str, activated: bool) -> RuleResult:
    if activated and "put a mire counter on target non-swamp land" in text:
        return _instruction("add_mire_counter_to_target_land"), "activated_landtype"
    return None
