"""Zone-change effects: draw, discard, ante, graveyard, exile, library."""

from __future__ import annotations

import re

from ..oracle_types import _instruction, _parse_number_token
from .base import RuleResult, activated_kind, parse_rule

_REANIMATE_ENCHANTED_RE = re.compile(r"return enchanted creature card to the battlefield under your control")
_DRAWS_N_RE = re.compile(r"target player draws (\w+) cards?")
_DISCARDS_N_RE = re.compile(r"target player discards (\w+) cards?")
# Bazaar of Baghdad: "Draw two cards, then discard three cards." No target
# word — draws/discards affect the ability's own controller.
_DRAW_THEN_DISCARD_RE = re.compile(r"draw (\w+) cards?, then discard (\w+) cards?")


# Animate Dead and similar: 'Return enchanted creature card to the battlefield under your control'
@parse_rule(14000)
def reanimate_enchanted_creature(text: str, activated: bool) -> RuleResult:
    if _REANIMATE_ENCHANTED_RE.search(text):
        return _instruction("reanimate_creature"), "spell_pattern"
    return None


@parse_rule(16000)
def draw_x_cards(text: str, activated: bool) -> RuleResult:
    if "target player draws x cards" in text:
        effect_kind = activated_kind(activated, "draw")
        return _instruction("draw_target_cards", amount="x"), effect_kind
    return None


@parse_rule(17000)
def discard_hand_ante_then_draw_seven(text: str, activated: bool) -> RuleResult:
    if "discard your hand, ante the top card of your library, then draw seven cards" in text:
        return _instruction("discard_hand_ante_then_draw_seven"), "spell_pattern"
    return None


@parse_rule(18000)
def each_player_antes_top_card(text: str, activated: bool) -> RuleResult:
    if "each player antes the top card of their library" in text:
        return _instruction("each_player_antes_top_card"), "spell_pattern"
    return None


# Jeweled Bird: "{T}: Ante this artifact. If you do, put all other cards you own
# from the ante into your graveyard, then draw a card." The ante is the effect
# (the cost is just {T}), so this must claim the whole clause — the trailing
# draw included — before the generic "draw a card" shorthand does.
_ANTE_SELF_CLEAR_DRAW_RE = re.compile(
    r"ante this (?:artifact|creature|enchantment|permanent|land)\. "
    r"if you do, put all other cards you own from the ante into your graveyard, "
    r"then draw a card"
)


@parse_rule(18500)
def ante_self_then_clear_ante_and_draw(text: str, activated: bool) -> RuleResult:
    if activated and _ANTE_SELF_CLEAR_DRAW_RE.search(text):
        return _instruction("ante_self_then_clear_ante_and_draw"), "activated_ante"
    return None


@parse_rule(19000)
def exchange_ante_with_top_library(text: str, activated: bool) -> RuleResult:
    if "you own target card in the ante. exchange that card with the top card of your library" in text:
        return _instruction("exchange_ante_with_top_library"), "spell_pattern"
    return None


@parse_rule(20000)
def draw_n_cards(text: str, activated: bool) -> RuleResult:
    draw_match = _DRAWS_N_RE.search(text)
    if draw_match:
        count = _parse_number_token(draw_match.group(1))
        if count > 0:
            effect_kind = activated_kind(activated, "draw")
            return _instruction("draw_target_cards", amount=count), effect_kind
    return None


@parse_rule(20500)
def draw_then_discard_self(text: str, activated: bool) -> RuleResult:
    m = _DRAW_THEN_DISCARD_RE.search(text)
    if m:
        draw_count = _parse_number_token(m.group(1))
        discard_count = _parse_number_token(m.group(2))
        effect_kind = activated_kind(activated, "draw")
        return _instruction(
            "draw_then_discard_self", draw=draw_count, discard=discard_count
        ), effect_kind
    return None


@parse_rule(38000)
def reanimate_from_graveyard(text: str, activated: bool) -> RuleResult:
    if "from your graveyard to the battlefield" in text or "from a graveyard onto the battlefield" in text:
        return _instruction("reanimate_creature"), "spell_pattern"
    return None


@parse_rule(39000)
def bounce_target_creature(text: str, activated: bool) -> RuleResult:
    if "return target creature to its owner's hand" in text:
        return _instruction("bounce_target_creature"), "spell_pattern"
    return None


@parse_rule(40000)
def exile_target_creature_until_eot(text: str, activated: bool) -> RuleResult:
    if "exile target creature until end of turn" in text:
        return _instruction("exile_target_creature_until_eot"), "spell_pattern"
    return None


@parse_rule(41000)
def exile_creature_gain_life(text: str, activated: bool) -> RuleResult:
    if "exile target creature" in text and "its controller gains life equal to its power" in text:
        return _instruction("exile_creature_gain_life_equal_to_power"), "spell_pattern"
    return None


@parse_rule(41500)
def phase_out_target_creature_until_source_leaves(text: str, activated: bool) -> RuleResult:
    # Oubliette: "target creature phases out until this enchantment leaves the
    # battlefield. Tap that creature as it phases in this way." Modeled as a
    # scoped exile-and-return tracked on the source (not full CR 702.26
    # phasing, which is listed as an unsupported keyword) — same linked-
    # duration shape as Aladdin/Old Man of the Sea's control-steal effects.
    if "target creature phases out until this" in text and "leaves the battlefield" in text:
        return _instruction("phase_out_target_creature_until_source_leaves"), "spell_pattern"
    return None


@parse_rule(43000)
def wheel_of_fortune(text: str, activated: bool) -> RuleResult:
    if "each player discards their hand, then draws seven cards" in text:
        return _instruction("wheel_of_fortune"), "spell_pattern"
    return None


@parse_rule(44000)
def timetwister(text: str, activated: bool) -> RuleResult:
    if "each player shuffles their hand and graveyard into their library, then draws seven cards" in text:
        return _instruction("timetwister"), "spell_pattern"
    return None


@parse_rule(45000)
def search_library(text: str, activated: bool) -> RuleResult:
    if "search your library for a card, put that card into your hand, then shuffle" in text:
        return _instruction("search_library", count=1, card_type="any"), "spell_pattern"
    return None


@parse_rule(47000)
def reorder_target_library_top(text: str, activated: bool) -> RuleResult:
    if "look at the top three cards of target player's library, then put them back in any order" in text:
        return _instruction("reorder_target_library_top"), "spell_pattern"
    return None


@parse_rule(49000)
def peek_hand_and_force_play(text: str, activated: bool) -> RuleResult:
    if "look at target opponent's hand and choose a card from it" in text:
        return _instruction("peek_hand_and_force_play"), "spell_pattern"
    return None


@parse_rule(62000)
def return_creature_from_graveyard_to_hand(text: str, activated: bool) -> RuleResult:
    if "from your graveyard to your hand" in text:
        # Raise Dead: "target CREATURE card"; Regrowth: "target card" — any type.
        any_card = "creature card" not in text
        return _instruction("return_creature_from_graveyard_to_hand", any_card=any_card), "spell_pattern"
    return None


@parse_rule(63000)
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


# Aladdin's Lamp: "{X}, {T}: The next time you would draw a card this turn,
# instead look at the top X cards of your library, put all but one of them on
# the bottom of your library in a random order, then draw a card." Arms a
# one-shot draw replacement; must out-rank the generic "draw a card" shorthand.
@parse_rule(89200)
def arm_lamp_draw_replacement(text: str, activated: bool) -> RuleResult:
    if "the next time you would draw a card this turn, instead look at the top x cards" in text:
        return _instruction("arm_lamp_draw_replacement"), "activated_draw"
    return None


# Ring of Ma'rûf: "{5}, {T}, Exile this artifact: The next time you would draw a
# card this turn, instead put a card you own from outside the game into your
# hand." Same one-shot draw-replacement shape as Aladdin's Lamp, drawing from the
# sideboard instead of the library; must likewise out-rank the generic draw rule.
@parse_rule(89300)
def arm_outside_game_draw_replacement(text: str, activated: bool) -> RuleResult:
    if (
        "the next time you would draw a card this turn, instead put a card you own "
        "from outside the game into your hand" in text
    ):
        return _instruction("arm_outside_game_draw_replacement"), "activated_draw"
    return None


# Sindbad: "Draw a card and reveal it. If it isn't a land card, discard it."
# Must out-rank the generic activated "draw a card" shorthand below.
@parse_rule(89500)
def draw_reveal_discard_unless_land(text: str, activated: bool) -> RuleResult:
    if "draw a card and reveal it" in text and "if it isn't a land card, discard it" in text:
        return _instruction("draw_reveal_discard_unless_land"), "activated_draw"
    return None


@parse_rule(90000)
def activated_draw_a_card(text: str, activated: bool) -> RuleResult:
    if activated and "draw a card" in text:
        return _instruction("draw_controller_cards", amount=1), "activated_draw"
    return None


@parse_rule(98000)
def cast_face_down_creature(text: str, activated: bool) -> RuleResult:
    if activated and "you may cast that card face down as a 2/2 creature spell" in text:
        return _instruction("cast_face_down_creature"), "activated_cast"
    return None


@parse_rule(99000)
def look_at_target_hand(text: str, activated: bool) -> RuleResult:
    if activated and "look at target player's hand" in text:
        return _instruction("look_at_target_hand"), "activated_look"
    return None


# "Target player mills N cards." (Millstone, and every mill card since.) The
# count is a parameter: cards print it as a numeral or a number word, and
# baking either into the rule would mean a new rule per number.
_MILL_RE = re.compile(
    r"target player mills (?P<count>\w+) cards?"
)


@parse_rule(18_700)
def target_player_mills(text: str, activated: bool) -> RuleResult:
    match = _MILL_RE.search(text)
    if match is None:
        return None
    count = _parse_number_token(match.group("count"))
    if count is None:
        return None
    return _instruction("mill_target_player", amount=count), activated_kind(activated, "mill")


# "Return all artifacts target player owns to their hand." (Hurkyl's Recall.)
# Ownership, not control: a stolen artifact goes back to the hand of the player
# who owns it, and the engine already distinguishes the two (owner_index_of).
@parse_rule(19_500)
def return_all_owned_artifacts_to_hand(text: str, activated: bool) -> RuleResult:
    if "return all artifacts target player owns to their hand" in text:
        return (
            _instruction("return_all_owned_artifacts_to_hand"),
            activated_kind(activated, "bounce"),
        )
    return None
