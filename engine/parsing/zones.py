"""Zone-change effects: draw, discard, ante, graveyard, exile, library."""

from __future__ import annotations

import re

from ..oracle_types import _instruction, _parse_number_token
from .base import RuleResult, parse_rule

_REANIMATE_ENCHANTED_RE = re.compile(r"return enchanted creature card to the battlefield under your control")
_DRAWS_N_RE = re.compile(r"target player draws (\w+) cards?")
_DISCARDS_N_RE = re.compile(r"target player discards (\w+) cards?")


# Animate Dead and similar: 'Return enchanted creature card to the battlefield under your control'
@parse_rule(140)
def reanimate_enchanted_creature(text: str, activated: bool) -> RuleResult:
    if _REANIMATE_ENCHANTED_RE.search(text):
        return _instruction("reanimate_creature"), "spell_pattern"
    return None


@parse_rule(160)
def draw_x_cards(text: str, activated: bool) -> RuleResult:
    if "target player draws x cards" in text:
        effect_kind = "activated_draw" if activated else "spell_pattern"
        return _instruction("draw_target_cards", amount="x"), effect_kind
    return None


@parse_rule(170)
def discard_hand_ante_then_draw_seven(text: str, activated: bool) -> RuleResult:
    if "discard your hand, ante the top card of your library, then draw seven cards" in text:
        return _instruction("discard_hand_ante_then_draw_seven"), "spell_pattern"
    return None


@parse_rule(180)
def each_player_antes_top_card(text: str, activated: bool) -> RuleResult:
    if "each player antes the top card of their library" in text:
        return _instruction("each_player_antes_top_card"), "spell_pattern"
    return None


@parse_rule(190)
def exchange_ante_with_top_library(text: str, activated: bool) -> RuleResult:
    if "you own target card in the ante. exchange that card with the top card of your library" in text:
        return _instruction("exchange_ante_with_top_library"), "spell_pattern"
    return None


@parse_rule(200)
def draw_n_cards(text: str, activated: bool) -> RuleResult:
    draw_match = _DRAWS_N_RE.search(text)
    if draw_match:
        count = _parse_number_token(draw_match.group(1))
        if count > 0:
            effect_kind = "activated_draw" if activated else "spell_pattern"
            return _instruction("draw_target_cards", amount=count), effect_kind
    return None


@parse_rule(380)
def reanimate_from_graveyard(text: str, activated: bool) -> RuleResult:
    if "from your graveyard to the battlefield" in text or "from a graveyard onto the battlefield" in text:
        return _instruction("reanimate_creature"), "spell_pattern"
    return None


@parse_rule(390)
def bounce_target_creature(text: str, activated: bool) -> RuleResult:
    if "return target creature to its owner's hand" in text:
        return _instruction("bounce_target_creature"), "spell_pattern"
    return None


@parse_rule(400)
def exile_target_creature_until_eot(text: str, activated: bool) -> RuleResult:
    if "exile target creature until end of turn" in text:
        return _instruction("exile_target_creature_until_eot"), "spell_pattern"
    return None


@parse_rule(410)
def exile_creature_gain_life(text: str, activated: bool) -> RuleResult:
    if "exile target creature" in text and "its controller gains life equal to its power" in text:
        return _instruction("exile_creature_gain_life_equal_to_power"), "spell_pattern"
    return None


@parse_rule(430)
def wheel_of_fortune(text: str, activated: bool) -> RuleResult:
    if "each player discards their hand, then draws seven cards" in text:
        return _instruction("wheel_of_fortune"), "spell_pattern"
    return None


@parse_rule(440)
def timetwister(text: str, activated: bool) -> RuleResult:
    if "each player shuffles their hand and graveyard into their library, then draws seven cards" in text:
        return _instruction("timetwister"), "spell_pattern"
    return None


@parse_rule(450)
def search_library(text: str, activated: bool) -> RuleResult:
    if "search your library for a card, put that card into your hand, then shuffle" in text:
        return _instruction("search_library", count=1, card_type="any"), "spell_pattern"
    return None


@parse_rule(470)
def reorder_target_library_top(text: str, activated: bool) -> RuleResult:
    if "look at the top three cards of target player's library, then put them back in any order" in text:
        return _instruction("reorder_target_library_top"), "spell_pattern"
    return None


@parse_rule(490)
def peek_hand_and_force_play(text: str, activated: bool) -> RuleResult:
    if "look at target opponent's hand and choose a card from it" in text:
        return _instruction("peek_hand_and_force_play"), "spell_pattern"
    return None


@parse_rule(620)
def return_creature_from_graveyard_to_hand(text: str, activated: bool) -> RuleResult:
    if "from your graveyard to your hand" in text:
        return _instruction("return_creature_from_graveyard_to_hand"), "spell_pattern"
    return None


@parse_rule(630)
def discard_cards(text: str, activated: bool) -> RuleResult:
    discard_match = _DISCARDS_N_RE.search(text)
    if discard_match:
        token = discard_match.group(1).lower()
        if token == "x":
            return _instruction("discard_x_target_cards"), "spell_pattern"
        count = _parse_number_token(token)
        if count > 0:
            return _instruction("discard_target_cards", amount=count), "spell_pattern"
    return None


@parse_rule(900)
def activated_draw_a_card(text: str, activated: bool) -> RuleResult:
    if activated and "draw a card" in text:
        return _instruction("draw_controller_cards", amount=1), "activated_draw"
    return None


@parse_rule(980)
def cast_face_down_creature(text: str, activated: bool) -> RuleResult:
    if activated and "you may cast that card face down as a 2/2 creature spell" in text:
        return _instruction("cast_face_down_creature"), "activated_cast"
    return None


@parse_rule(990)
def look_at_target_hand(text: str, activated: bool) -> RuleResult:
    if activated and "look at target player's hand" in text:
        return _instruction("look_at_target_hand"), "activated_look"
    return None
