"""Permanent destruction effects.

The generic destroy rules that used to live here — "destroy target <noun>",
"destroy all creatures/enchantments/lands", "destroy all <basic land type>" —
have been replaced by a single production in ``engine/grammar/parser.py``. They
were the clearest illustration of what the flat registry cost: five rules whose
relative precedence had to be hand-numbered so that the sweep forms outranked
the targeted one, each re-deriving its own noun phrase. In the grammar the
distinction falls out of the noun phrase's quantifier, and the lowered
instructions are identical for every card in the pool.

What remains is genuinely bespoke: effects whose destruction is bundled with
something else, or whose target vocabulary the noun parser does not yet reach.
"""

from __future__ import annotations

from typing import Any

from ..oracle_types import OracleInstruction, _instruction
from .base import RuleResult, activated_kind, parse_rule
from .common import cant_be_regenerated


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


# Abu Ja'far: "When this creature dies, destroy all creatures blocking or
# blocked by it. They can't be regenerated." The scope is defined by combat
# relationship rather than a noun phrase, so it stays its own rule.
@parse_rule(53500)
def destroy_creatures_in_combat_with_source(text: str, activated: bool) -> RuleResult:
    if "destroy all creatures blocking or blocked by it" in text:
        payload: dict[str, Any] = (
            {"bypass_regeneration": True} if cant_be_regenerated(text) else {}
        )
        return (
            OracleInstruction("destroy_creatures_in_combat_with_source", "", payload),
            "spell_pattern",
        )
    return None


# Pyramids mode 1: "Destroy target Aura attached to a land." The restriction is
# on what the Aura is attached to, which the noun parser has no vocabulary for.
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
