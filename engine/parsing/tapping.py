"""Tap and untap effects."""

from __future__ import annotations

from ..oracle_types import _instruction
from .base import RuleResult, parse_rule


@parse_rule(150)
def untap_self(text: str, activated: bool) -> RuleResult:
    if activated and ("untap this artifact" in text or "untap this permanent" in text):
        return _instruction("untap_self"), "activated_untap"
    return None


@parse_rule(280)
def tap_lands_and_drain_mana(text: str, activated: bool) -> RuleResult:
    if "tap all lands target player controls" in text and "loses all unspent mana" in text:
        return _instruction("tap_target_player_lands_and_drain_mana"), "spell_pattern"
    return None


@parse_rule(690)
def untap_enchanted_creature(text: str, activated: bool) -> RuleResult:
    if activated and "untap enchanted creature" in text:
        return _instruction("untap_enchanted_creature"), "activated_untap"
    return None


@parse_rule(700)
def untap_target_land(text: str, activated: bool) -> RuleResult:
    if "untap target land" in text and activated:
        return _instruction("untap_target_land"), "activated_untap"
    return None


@parse_rule(705)
def tap_or_untap_target(text: str, activated: bool) -> RuleResult:
    # Twiddle: "You may tap or untap target artifact, creature, or land." The
    # caster chooses tap or untap; we toggle the chosen permanent's tapped state,
    # which is the only meaningful choice in every situation (choosing the no-op
    # direction is never useful). Must out-rank the tap-only / untap-only rules.
    if "tap or untap target" in text:
        return _instruction("tap_or_untap_target"), "spell_pattern"
    return None


@parse_rule(710)
def untap_target(text: str, activated: bool) -> RuleResult:
    if "untap target" in text:
        return _instruction("untap_target_permanent"), "spell_pattern"
    return None


@parse_rule(720)
def tap_target(text: str, activated: bool) -> RuleResult:
    if "tap target" in text:
        return _instruction("tap_target_permanent"), "spell_pattern"
    return None
