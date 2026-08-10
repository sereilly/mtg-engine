"""Life total changes, extra turns, and game-ending effects."""

from __future__ import annotations

import re

from ..oracle_types import _instruction
from .base import RuleResult, activated_kind, parse_rule

_LOSE_LIFE_RE = re.compile(r"target player loses (\d+) life")
_GAIN_LIFE_RE = re.compile(r"gains? (\d+) life")


def _life_recipient(text: str) -> str:
    """Who gains the life: the spell/ability's controller or a chosen target.

    "Target player gains N life" / "that player gains N life" is a targeted
    effect (CR 115). "You gain N life" and the bare "gain N life" form (common
    on activated abilities, e.g. "{T}: You gain 1 life") affect the controller —
    "you" is never a target (CR 115.10b).
    """
    if "target player" in text or "that player" in text:
        return "target"
    return "caster"


@parse_rule(46000)
def grant_extra_turn(text: str, activated: bool) -> RuleResult:
    if "take an extra turn after this one" in text:
        return _instruction("grant_extra_turn"), "spell_pattern"
    return None


# Rule 104.3e: effect that states a player loses the game
@parse_rule(64000)
def target_player_loses_game(text: str, activated: bool) -> RuleResult:
    if "target player loses the game" in text:
        return _instruction("target_player_loses_game"), "spell_pattern"
    return None


# Rule 104.2b: effect that states a player wins the game (spell/sorcery form)
@parse_rule(65000)
def player_wins_game(text: str, activated: bool) -> RuleResult:
    if "you win the game" in text:
        return _instruction("player_wins_game"), "spell_pattern"
    return None


# Rule 104.4c: effect that states the game is a draw
@parse_rule(66000)
def game_is_draw(text: str, activated: bool) -> RuleResult:
    if "the game is a draw" in text:
        return _instruction("game_is_draw"), "spell_pattern"
    return None


# Shahrazad: "Players play a Magic subgame, using their libraries as their
# decks. Each player who doesn't win the subgame loses half their life, rounded
# up." Subgames are out of scope, so the documented simplification is that the
# caster is treated as the subgame's winner and everyone else pays the life.
# Matched on the life clause specifically — the subgame sentence is what the
# engine can't honour, and claiming it would be the silent-support bug this
# rule exists to fix.
@parse_rule(66500)
def opponents_lose_half_life_subgame(text: str, activated: bool) -> RuleResult:
    if "loses half their life, rounded up" in text and "subgame" in text:
        return _instruction("opponents_lose_half_life"), "spell_pattern"
    return None


@parse_rule(67000)
def target_loses_n_life(text: str, activated: bool) -> RuleResult:
    lose_life_match = _LOSE_LIFE_RE.search(text)
    if lose_life_match:
        return _instruction("target_loses_life", amount=int(lose_life_match.group(1))), "spell_pattern"
    return None


@parse_rule(68000)
def target_gains_x_life(text: str, activated: bool) -> RuleResult:
    if "gains x life" in text or "gain x life" in text:
        return _instruction("target_gains_life", amount="x", recipient=_life_recipient(text)), "spell_pattern"
    return None


# Diamond Valley: "{T}, Sacrifice a creature: You gain life equal to the
# sacrificed creature's toughness." The sacrifice itself is resolved by the
# handler (matching how Sacrifice / sacrifice_creature_for_black_mana already
# fold a "sacrifice a creature" cost clause into effect resolution).
@parse_rule(79800)
def sacrifice_creature_gain_life_by_toughness(text: str, activated: bool) -> RuleResult:
    if activated and "gain life equal to the sacrificed creature's toughness" in text:
        return _instruction("sacrifice_creature_gain_life_by_toughness"), "activated_gain_life"
    return None


@parse_rule(80000)
def target_gains_n_life(text: str, activated: bool) -> RuleResult:
    if "gain" in text and "life" in text:
        gain_match = _GAIN_LIFE_RE.search(text)
        if gain_match:
            effect_kind = activated_kind(activated, "gain_life")
            return _instruction(
                "target_gains_life",
                amount=int(gain_match.group(1)),
                recipient=_life_recipient(text),
            ), effect_kind
    return None


_ARTIFACT_DAMAGE_LIFE_RE = re.compile(
    r"you gain x life, where x is twice the damage dealt to you so far this turn "
    r"by artifacts?(?: sources)?"
)


# Ahead of the generic "gain X life" rule (68000): first match wins by
# ascending order, so the more specific reading of the same opening words has to
# come first or it never fires. The wording is matched from the *printed* text —
# the card says "by artifacts", and a regex written from a truncated log said
# "by artifact sources" and silently matched nothing.
@parse_rule(63_950)
def gain_twice_artifact_damage_taken(text: str, activated: bool) -> RuleResult:
    """Reverse Polarity: gain twice the artifact-sourced damage taken this turn."""
    if _ARTIFACT_DAMAGE_LIFE_RE.search(text):
        return _instruction("gain_twice_artifact_damage_taken"), "spell_pattern"
    return None
