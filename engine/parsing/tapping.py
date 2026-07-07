"""Tap and untap effects."""

from __future__ import annotations

from ..oracle_types import _instruction
from .base import RuleResult, parse_rule
from .common import parse_target_filter


@parse_rule(15000)
def untap_self(text: str, activated: bool) -> RuleResult:
    if activated and ("untap this artifact" in text or "untap this permanent" in text):
        return _instruction("untap_self"), "activated_untap"
    return None


@parse_rule(28000)
def tap_lands_and_drain_mana(text: str, activated: bool) -> RuleResult:
    if "tap all lands target player controls" in text and "loses all unspent mana" in text:
        return _instruction("tap_target_player_lands_and_drain_mana"), "spell_pattern"
    return None


@parse_rule(69000)
def untap_enchanted_creature(text: str, activated: bool) -> RuleResult:
    if activated and "untap enchanted creature" in text:
        return _instruction("untap_enchanted_creature"), "activated_untap"
    return None


@parse_rule(70000)
def untap_target_land(text: str, activated: bool) -> RuleResult:
    if "untap target land" in text and activated:
        return _instruction("untap_target_land"), "activated_untap"
    return None


@parse_rule(70500)
def tap_or_untap_target(text: str, activated: bool) -> RuleResult:
    # Twiddle: "You may tap or untap target artifact, creature, or land." The
    # caster chooses tap or untap; we toggle the chosen permanent's tapped state,
    # which is the only meaningful choice in every situation (choosing the no-op
    # direction is never useful). Must out-rank the tap-only / untap-only rules.
    if "tap or untap target" in text:
        return _instruction("tap_or_untap_target"), "spell_pattern"
    return None


@parse_rule(70800)
def untap_attacker_and_prevent_combat_damage(text: str, activated: bool) -> RuleResult:
    # Ebony Horse: "Untap target attacking creature you control. Prevent all
    # combat damage that would be dealt to and dealt by that creature this
    # turn." One instruction carries both sentences; the handler claims the
    # prevention rider (see HANDLER_CLAIMS in scripts/parse_coverage.py).
    # Must out-rank the generic untap_target rule.
    if (
        "untap target attacking creature you control" in text
        and "prevent all combat damage that would be dealt to and dealt by that creature" in text
    ):
        return _instruction("untap_attacker_and_prevent_combat_damage"), "spell_pattern"
    return None


@parse_rule(71000)
def untap_target(text: str, activated: bool) -> RuleResult:
    if "untap target" in text:
        return _instruction("untap_target_permanent"), "spell_pattern"
    return None


@parse_rule(72000)
def tap_target(text: str, activated: bool) -> RuleResult:
    if "tap target" in text:
        # Ali Baba: "{R}: Tap target Wall." — carry the noun-phrase restriction
        # so resolution and the legality enumerator only accept matching
        # permanents. Icy Manipulator's "artifact, creature, or land" parses to
        # no filter, preserving its any-permanent behavior.
        clause = text.split("tap target", 1)[1].split(".", 1)[0]
        payload = {}
        if "artifact, creature, or land" not in clause and "permanent" not in clause:
            payload = parse_target_filter(clause, text).to_payload()
        return _instruction("tap_target_permanent", **payload), "spell_pattern"
    return None
