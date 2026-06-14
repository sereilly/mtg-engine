"""Damage prevention and redirection effects."""

from __future__ import annotations

import re

from ..oracle_types import _instruction
from .base import RuleResult, parse_rule

_PREVENT_N_RE = re.compile(r"prevent the next (\d+) damage")


@parse_rule(730)
def prevent_next_x_damage(text: str, activated: bool) -> RuleResult:
    if "prevent the next x damage" in text:
        effect_kind = "activated_prevent" if activated else "spell_pattern"
        # "dealt to you" means the activating player, not a chosen target
        # (e.g. Conservator). Otherwise the shield goes to the designated target.
        to_self = "would be dealt to you" in text
        return _instruction("grant_prevention_shield", amount="x", to_self=to_self), effect_kind
    return None


@parse_rule(740)
def prevent_next_n_damage(text: str, activated: bool) -> RuleResult:
    prevent_match = _PREVENT_N_RE.search(text)
    if prevent_match:
        amount = int(prevent_match.group(1))
        effect_kind = "activated_prevent" if activated else "spell_pattern"
        # Conservator: "Prevent the next 2 damage that would be dealt to you this
        # turn." — "you" is the ability's controller, so the shield is granted to
        # the caster, not to the default (opponent) target.
        to_self = "would be dealt to you" in text
        return _instruction("grant_prevention_shield", amount=amount, to_self=to_self), effect_kind
    return None


# Circle of Protection style: "would deal damage to you this turn, prevent that damage"
@parse_rule(750)
def color_protection_shield(text: str, activated: bool) -> RuleResult:
    if "would deal damage to you this turn, prevent that damage" in text and activated:
        return _instruction("grant_prevention_shield", amount=1, protection_kind="color"), "activated_prevent"
    return None


@parse_rule(760)
def forcefield_shield(text: str, activated: bool) -> RuleResult:
    if "the next time an unblocked creature of your choice would deal combat damage to you this turn, prevent all but 1 of that damage" in text and activated:
        return _instruction("grant_forcefield_shield"), "activated_prevent"
    return None


@parse_rule(940)
def redirect_one_damage_to_owner(text: str, activated: bool) -> RuleResult:
    if activated and "the next 1 damage that would be dealt to this creature this turn is dealt to its owner instead" in text:
        return _instruction("redirect_one_damage_to_owner"), "activated_prevent"
    return None


@parse_rule(950)
def jade_monolith_redirect(text: str, activated: bool) -> RuleResult:
    if activated and "next time a source of your choice would deal damage to target creature this turn" in text:
        return _instruction("jade_monolith_redirect"), "activated_prevent"
    return None
