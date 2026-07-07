"""Damage prevention and redirection effects."""

from __future__ import annotations

import re

from ..oracle_types import _COLOR_WORD_TO_SYMBOL, _instruction
from .base import RuleResult, activated_kind, parse_rule

_PREVENT_N_RE = re.compile(r"prevent the next (\d+) damage")
_COLOR_SOURCE_RE = re.compile(r"a (\w+) source of your choice")


@parse_rule(73000)
def prevent_next_x_damage(text: str, activated: bool) -> RuleResult:
    if "prevent the next x damage" in text:
        effect_kind = activated_kind(activated, "prevent")
        # "dealt to you" means the activating player, not a chosen target
        # (e.g. Conservator). Otherwise the shield goes to the designated target.
        to_self = "would be dealt to you" in text
        to_source = "would be dealt to this creature" in text or "would be dealt to this permanent" in text
        return _instruction("grant_prevention_shield", amount="x", to_self=to_self, to_source=to_source), effect_kind
    return None


@parse_rule(74000)
def prevent_next_n_damage(text: str, activated: bool) -> RuleResult:
    prevent_match = _PREVENT_N_RE.search(text)
    if prevent_match:
        amount = int(prevent_match.group(1))
        effect_kind = activated_kind(activated, "prevent")
        # Conservator: "Prevent the next 2 damage that would be dealt to you this
        # turn." — "you" is the ability's controller, so the shield is granted to
        # the caster, not to the default (opponent) target. Rock Hydra:
        # "...dealt to this creature" — the shield protects the source permanent.
        to_self = "would be dealt to you" in text
        to_source = "would be dealt to this creature" in text or "would be dealt to this permanent" in text
        return _instruction("grant_prevention_shield", amount=amount, to_self=to_self, to_source=to_source), effect_kind
    return None


# Reverse Damage: "The next time a source of your choice would deal damage to you
# this turn, prevent that damage. You gain life equal to the damage prevented this
# way." A spell (not activated) — distinct from the Circle of Protection shield in
# that it gains life equal to the prevented damage and is colorless (any source).
@parse_rule(74500)
def reverse_damage_shield(text: str, activated: bool) -> RuleResult:
    if (
        not activated
        and "would deal damage to you this turn, prevent that damage" in text
        and "gain life equal to the damage prevented" in text
    ):
        return _instruction("grant_reverse_damage_shield"), "spell_pattern"
    return None


# Eye for an Eye: "The next time a source of your choice would deal damage to
# you this turn, instead that source deals that much damage to you and Eye for
# an Eye deals that much damage to that source's controller." The damage still
# happens; a mirror copy hits the source's controller.
@parse_rule(74700)
def mirror_damage_shield(text: str, activated: bool) -> RuleResult:
    if (
        "instead that source deals that much damage to you" in text
        and "deals that much damage to that source's controller" in text
    ):
        return _instruction("arm_mirror_damage"), "spell_pattern"
    return None


# Circle of Protection style: "The next time a red source of your choice would deal
# damage to you this turn, prevent that damage." The controller chooses a source of
# the named color; the color is captured so the UI can prompt for that source.
@parse_rule(75000)
def color_protection_shield(text: str, activated: bool) -> RuleResult:
    if "would deal damage to you this turn, prevent that damage" in text and activated:
        color_match = _COLOR_SOURCE_RE.search(text)
        prevention_color = (
            _COLOR_WORD_TO_SYMBOL.get(color_match.group(1)) if color_match else None
        )
        return (
            _instruction(
                "grant_prevention_shield",
                amount=1,
                protection_kind="color",
                prevention_color=prevention_color,
            ),
            "activated_prevent",
        )
    return None


@parse_rule(76000)
def forcefield_shield(text: str, activated: bool) -> RuleResult:
    if "the next time an unblocked creature of your choice would deal combat damage to you this turn, prevent all but 1 of that damage" in text and activated:
        return _instruction("grant_forcefield_shield"), "activated_prevent"
    return None


@parse_rule(94000)
def redirect_one_damage_to_owner(text: str, activated: bool) -> RuleResult:
    if activated and "the next 1 damage that would be dealt to this creature this turn is dealt to its owner instead" in text:
        return _instruction("redirect_one_damage_to_owner"), "activated_prevent"
    return None


@parse_rule(95000)
def jade_monolith_redirect(text: str, activated: bool) -> RuleResult:
    if activated and "next time a source of your choice would deal damage to target creature this turn" in text:
        return _instruction("jade_monolith_redirect"), "activated_prevent"
    return None
