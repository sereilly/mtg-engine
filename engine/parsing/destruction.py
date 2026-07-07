"""Permanent destruction effects."""

from __future__ import annotations

import re
from typing import Any

from ..oracle_types import OracleInstruction, _instruction
from .base import RuleResult, activated_kind, parse_rule
from .common import cant_be_regenerated, parse_target_filter

_DESTROY_LAND_TYPE_RE = re.compile(r"destroy all (plains|islands|swamps|mountains|forests)")


@parse_rule(51500)
def volcanic_eruption(text: str, activated: bool) -> RuleResult:
    # Volcanic Eruption: "Destroy X target Mountains. Volcanic Eruption deals
    # damage to each creature and each player equal to the number of Mountains put
    # into a graveyard this way."
    if "destroy x target mountains" in text:
        return _instruction("volcanic_eruption"), "spell_pattern"
    return None


@parse_rule(52000)
def chaos_orb_flip(text: str, activated: bool) -> RuleResult:
    if "flip it onto the battlefield" in text:
        return _instruction("chaos_orb_flip"), "activated_chaos_orb"
    return None


@parse_rule(53000)
def destroy_all_artifacts_creatures_enchantments(text: str, activated: bool) -> RuleResult:
    if "destroy all artifacts, creatures, and enchantments" in text:
        return _instruction("destroy_all_artifacts_creatures_enchantments"), "spell_pattern"
    return None


@parse_rule(54000)
def destroy_all_creatures(text: str, activated: bool) -> RuleResult:
    if "destroy all creatures" in text:
        payload: dict[str, Any] = {"bypass_regeneration": True} if cant_be_regenerated(text) else {}
        return OracleInstruction("destroy_all_creatures", "", payload), "spell_pattern"
    return None


@parse_rule(55000)
def destroy_all_enchantments(text: str, activated: bool) -> RuleResult:
    if "destroy all enchantments" in text:
        return _instruction("destroy_all_enchantments"), "spell_pattern"
    return None


@parse_rule(56000)
def destroy_all_lands(text: str, activated: bool) -> RuleResult:
    if "destroy all lands" in text:
        return _instruction("destroy_all_lands"), "spell_pattern"
    return None


# Destroy all of a specific land type (e.g., "Destroy all Plains.")
@parse_rule(57000)
def destroy_all_lands_of_type(text: str, activated: bool) -> RuleResult:
    m = _DESTROY_LAND_TYPE_RE.search(text)
    if m:
        land = m.group(1)
        return _instruction("destroy_all_lands_of_type", land_type=land), "spell_pattern"
    return None


# Pyramids mode 1: "Destroy target Aura attached to a land." Must out-rank the
# generic destroy-target rule, whose noun parser would read "...a land" as a
# land target.
@parse_rule(60500)
def destroy_target_aura_on_land(text: str, activated: bool) -> RuleResult:
    if "destroy target aura attached to a land" in text:
        return _instruction(
            "destroy_target_permanent", type_filter="enchantment", attached_to_land=True
        ), activated_kind(activated, "destroy")
    return None


# Pyramids mode 2: "The next time target land would be destroyed this turn,
# remove all damage marked on it instead." Arms a one-shot destruction shield.
@parse_rule(60600)
def shield_target_land_from_destruction(text: str, activated: bool) -> RuleResult:
    if "the next time target land would be destroyed this turn, remove all damage marked on it instead" in text:
        return _instruction("shield_target_land_from_destruction"), activated_kind(activated, "prevent")
    return None


@parse_rule(61000)
def destroy_target(text: str, activated: bool) -> RuleResult:
    if "destroy target" not in text:
        return None
    effect_kind = activated_kind(activated, "destroy")
    # The noun phrase after "destroy target" — adjectives such as "tapped",
    # "nonblack", or a subtype like "Wall" can sit between "target" and the
    # actual type word. parse_target_filter owns that vocabulary.
    clause = text.split("destroy target", 1)[1].split(".")[0]
    destroy_payload = parse_target_filter(clause, text).to_payload()
    if cant_be_regenerated(text):
        destroy_payload["bypass_regeneration"] = True
    return OracleInstruction("destroy_target_permanent", "", destroy_payload), effect_kind
