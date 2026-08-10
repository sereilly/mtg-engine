"""Damage-dealing effects.

Most of this family now lives in ``engine/grammar/parser.py``: the plain
"deals N damage to <recipient>" form, the Earthquake/Hurricane/Sandstorm
sweeps, the Disintegrate riders, and the two-clause forms that used to need
their own fused instruction kinds (``deal_damage_and_self_damage``,
``deal_damage_and_opponent_choice``) — the grammar reads those as an ordinary
conjunction and emits two instructions.

What remains needs a quantity the grammar has no node for (a count of Swamps,
"the damage dealt to you this turn") or bundles damage with an unrelated
effect.
"""

from __future__ import annotations

import re

from ..oracle_types import _instruction
from .base import RuleResult, activated_kind, parse_rule

_DAMAGE_N_RE = re.compile(r"deals (\d+) damage")


@parse_rule(31000)
def deal_x_damage_and_gain_life(text: str, activated: bool) -> RuleResult:
    if "deals x damage" in text and "you gain life equal to the damage dealt" in text:
        effect_kind = activated_kind(activated, "damage")
        return _instruction("deal_damage_and_gain_life", amount="x"), effect_kind
    return None


@parse_rule(31500)
def simulacrum_effect(text: str, activated: bool) -> RuleResult:
    # Simulacrum: "You gain life equal to the damage dealt to you this turn.
    # Simulacrum deals damage to target creature you control equal to the damage
    # dealt to you this turn."
    if "deals damage to target creature you control equal to the damage dealt to you this turn" in text:
        return _instruction("simulacrum_redirect"), "spell_pattern"
    return None


@parse_rule(32000)
def deal_x_damage(text: str, activated: bool) -> RuleResult:
    if "deals x damage" in text:
        effect_kind = activated_kind(activated, "damage")
        return _instruction("deal_damage", amount="x"), effect_kind
    return None


@parse_rule(34000)
def deal_damage_equal_to_swamps(text: str, activated: bool) -> RuleResult:
    if "deals damage" in text and "equal to the number of swamps" in text:
        return _instruction("deal_damage_equal_to_swamps"), "upkeep_effect"
    return None


# Ifh-Bíff Efreet: "{G}: This creature deals 1 damage to each creature with
# flying and each player." Same sweep as Hurricane, fixed amount. Must
# out-rank the generic "deals N damage" rule.
_DAMAGE_EACH_FLIER_AND_PLAYER_RE = re.compile(
    r"deals (\d+) damage to each creature with flying and each player"
)


@parse_rule(34500)
def deal_damage_each_flier_and_player(text: str, activated: bool) -> RuleResult:
    m = _DAMAGE_EACH_FLIER_AND_PLAYER_RE.search(text)
    if m:
        return _instruction("hurricane_damage", amount=int(m.group(1))), activated_kind(activated, "damage")
    return None


@parse_rule(37000)
def deal_n_damage(text: str, activated: bool) -> RuleResult:
    dmg_match = _DAMAGE_N_RE.search(text)
    if dmg_match:
        effect_kind = activated_kind(activated, "damage")
        return _instruction("deal_damage", amount=int(dmg_match.group(1))), effect_kind
    return None


# Rocket Launcher: "{2}: This artifact deals 1 damage to any target. Destroy
# this artifact at the beginning of the next end step. Activate only if you've
# controlled this artifact continuously since the beginning of your most recent
# turn."
#
# Both trailing sentences ride on the damage instruction's payload rather than
# becoming instructions of their own: the destroy is a *consequence of having
# activated*, and the control clause is a restriction on activating at all —
# neither is a step in a sequence.
_SELF_DESTROY_AT_END_RE = re.compile(
    r"this \w+ deals (?P<amount>\d+) damage to any target\. destroy this \w+ "
    r"at the beginning of the next end step"
)


@parse_rule(14_050)
def damage_then_destroy_self_at_end_step(text: str, activated: bool) -> RuleResult:
    match = _SELF_DESTROY_AT_END_RE.search(text)
    if match is None:
        return None
    return (
        _instruction(
            "deal_damage",
            amount=int(match.group("amount")),
            destroys_source_at_end_step=True,
            requires_control_since_turn_start=(
                "continuously since the beginning of your most recent turn" in text
            ),
        ),
        activated_kind(activated, "damage"),
    )
