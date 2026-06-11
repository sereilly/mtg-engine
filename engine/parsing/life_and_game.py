"""Life total changes, extra turns, and game-ending effects."""

from __future__ import annotations

import re

from ..oracle_types import _instruction
from .base import RuleResult, parse_rule

_LOSE_LIFE_RE = re.compile(r"target player loses (\d+) life")
_GAIN_LIFE_RE = re.compile(r"gains? (\d+) life")


@parse_rule(460)
def grant_extra_turn(text: str, activated: bool) -> RuleResult:
    if "take an extra turn after this one" in text:
        return _instruction("grant_extra_turn"), "spell_pattern"
    return None


# Rule 104.3e: effect that states a player loses the game
@parse_rule(640)
def target_player_loses_game(text: str, activated: bool) -> RuleResult:
    if "target player loses the game" in text:
        return _instruction("target_player_loses_game"), "spell_pattern"
    return None


# Rule 104.2b: effect that states a player wins the game (spell/sorcery form)
@parse_rule(650)
def player_wins_game(text: str, activated: bool) -> RuleResult:
    if "you win the game" in text:
        return _instruction("player_wins_game"), "spell_pattern"
    return None


# Rule 104.4c: effect that states the game is a draw
@parse_rule(660)
def game_is_draw(text: str, activated: bool) -> RuleResult:
    if "the game is a draw" in text:
        return _instruction("game_is_draw"), "spell_pattern"
    return None


@parse_rule(670)
def target_loses_n_life(text: str, activated: bool) -> RuleResult:
    lose_life_match = _LOSE_LIFE_RE.search(text)
    if lose_life_match:
        return _instruction("target_loses_life", amount=int(lose_life_match.group(1))), "spell_pattern"
    return None


@parse_rule(680)
def target_gains_x_life(text: str, activated: bool) -> RuleResult:
    if "gains x life" in text or "gain x life" in text:
        return _instruction("target_gains_life", amount="x"), "spell_pattern"
    return None


@parse_rule(800)
def target_gains_n_life(text: str, activated: bool) -> RuleResult:
    if "gain" in text and "life" in text:
        gain_match = _GAIN_LIFE_RE.search(text)
        if gain_match:
            effect_kind = "activated_gain_life" if activated else "spell_pattern"
            return _instruction("target_gains_life", amount=int(gain_match.group(1))), effect_kind
    return None
