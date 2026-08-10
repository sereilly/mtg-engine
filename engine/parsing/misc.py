"""Effects that don't fit a larger category: text changes, recoloring,
land-type changes, self-animation, token creation."""

from __future__ import annotations

import re
from typing import Any

from ..oracle_types import OracleInstruction, _instruction
from .base import RuleResult, activated_kind, parse_rule
from .common import find_color_word

# Rukh Egg: "create a 4/4 red Bird creature token with flying at the
# beginning of the next end step." General enough for future "create a P/T
# color Subtype creature token [with Keyword] at the beginning of the next
# end step" delayed-token effects.
_DELAYED_TOKEN_RE = re.compile(
    r"create an? (\d+)/(\d+) (\w+) (\w+) creature token(?: with (\w+))? "
    r"at the beginning of the next end step"
)

# Bottle of Suleiman: "Flip a coin. If you win the flip, create a 5/5 colorless
# Djinn artifact creature token with flying. If you lose the flip, this artifact
# deals 5 damage to you."
_COIN_FLIP_TOKEN_OR_SELF_DAMAGE_RE = re.compile(
    r"flip a coin\. if you win the flip, create an? (\d+)/(\d+) (\w+) (\w+) "
    r"(artifact creature|creature) token(?: with (\w+))?\. "
    r"if you lose the flip, this \w+ deals (\d+) damage to you"
)


# Must out-rank the generic "deals N damage" rule (order 37000), which would
# otherwise claim only the losing branch and drop the flip entirely.
@parse_rule(36800)
def coin_flip_token_or_self_damage(text: str, activated: bool) -> RuleResult:
    m = _COIN_FLIP_TOKEN_OR_SELF_DAMAGE_RE.search(text)
    if not m:
        return None
    power, toughness, color_word, subtype, token_types, keyword, damage = m.groups()
    color_sym = find_color_word(color_word, "{}")
    name = subtype.capitalize()
    type_line = f"{'Artifact Creature' if token_types == 'artifact creature' else 'Creature'} — {name}"
    return _instruction(
        "coin_flip_token_or_self_damage",
        name=name,
        power=int(power),
        toughness=int(toughness),
        type_line=type_line,
        colors=(color_sym,) if color_sym else (),
        keywords=(keyword.capitalize(),) if keyword else (),
        damage=int(damage),
    ), "activated_token" if activated else "spell_pattern"


@parse_rule(48000)
def mark_text_modified(text: str, activated: bool) -> RuleResult:
    if "change the text of target spell or permanent by replacing all instances of one" in text:
        # Magical Hack swaps a basic land type; Sleight of Mind swaps a color word.
        # The mode decides whether the handler remaps land types/landwalk or stores
        # a color-word remap — neither recolors the target permanent.
        if "basic land type" in text:
            return _instruction("mark_text_modified", mode="land_type"), "spell_pattern"
        if "color word" in text:
            return _instruction("mark_text_modified", mode="color_word"), "spell_pattern"
        return _instruction("mark_text_modified"), "spell_pattern"
    return None


@parse_rule(51000)
def recolor_target(text: str, activated: bool) -> RuleResult:
    target_color = find_color_word(text, "becomes {}")
    if target_color:
        payload: dict[str, Any] = {"target_color": target_color}
        return OracleInstruction("recolor_target_from_text", "", payload), "spell_pattern"
    return None


# Aladdin: "Gain control of target artifact for as long as you control this
# creature." Reverted by the ON_LEAVE_BATTLEFIELD["Aladdin"] hook (unlike
# Control Magic/Steal Artifact, which are Auras reverted when they leave).
@parse_rule(51200)
def steal_target_permanent_linked_to_self(text: str, activated: bool) -> RuleResult:
    if activated and "gain control of target artifact for as long as you control this creature" in text:
        return _instruction("steal_target_permanent_linked_to_self"), "activated_steal"
    return None


# Old Man of the Sea: "Gain control of target creature with power less than
# or equal to this creature's power for as long as this creature remains
# tapped and that creature's power remains less than or equal to this
# creature's power." Reverted continuously (untap OR power comparison
# failing) by the game_ending.py SBA-style check, not just on leaving.
@parse_rule(51300)
def steal_creature_while_tapped_and_weaker(text: str, activated: bool) -> RuleResult:
    if (
        activated
        and "gain control of target creature with power less than or equal to this creature's power" in text
        and "for as long as this creature remains tapped" in text
    ):
        return _instruction("steal_creature_while_tapped_and_weaker"), "activated_steal"
    return None


@parse_rule(91000)
def change_target_land_type(text: str, activated: bool) -> RuleResult:
    if activated and "target land becomes a forest" in text:
        return _instruction("change_target_land_type", land_type="forest"), "activated_landtype"
    return None


@parse_rule(96000)
def animate_self_until_end_of_combat(text: str, activated: bool) -> RuleResult:
    if activated and "this artifact becomes a 3/6 golem artifact creature until end of combat" in text:
        return _instruction("animate_self_until_end_of_combat", power=3, toughness=6), "activated_animate"
    return None


@parse_rule(97000)
def create_wasp_token(text: str, activated: bool) -> RuleResult:
    # The Hive — emits the generic create_token instruction (engine/tokens.py).
    if activated and "create a 1/1 colorless insect artifact creature token with flying named wasp" in text:
        return _instruction(
            "create_token",
            name="Wasp",
            power=1,
            toughness=1,
            type_line="Artifact Creature — Insect",
            keywords=("Flying",),
        ), "activated_token"
    return None


# City in a Bottle: "Whenever one or more other nontoken permanents with a
# name originally printed in the Arabian Nights expansion are on the
# battlefield, their controllers sacrifice them. Players can't cast spells or
# play lands with a name originally printed in the Arabian Nights expansion."
# One instruction covers both clauses (checked continuously as a state-based
# action / at cast time — see game_ending.py and mixins/stack/casting.py) since a
# single distinctive phrase ("originally printed in the ... expansion")
# identifies the whole effect regardless of which clause matched first.
_ORIGINALLY_PRINTED_IN_RE = re.compile(r"originally printed in the (.+?) expansion")
_EXPANSION_NAME_TO_SET_CODE = {"arabian nights": "arn"}


@parse_rule(97300)
def ban_and_sacrifice_set_permanents(text: str, activated: bool) -> RuleResult:
    m = _ORIGINALLY_PRINTED_IN_RE.search(text)
    if not m:
        return None
    set_code = _EXPANSION_NAME_TO_SET_CODE.get(m.group(1))
    if set_code is None:
        return None
    return _instruction("ban_and_sacrifice_set_permanents", set_code=set_code), "spell_pattern"


@parse_rule(97500)
def create_token_at_next_end_step(text: str, activated: bool) -> RuleResult:
    m = _DELAYED_TOKEN_RE.search(text)
    if m:
        power, toughness, color_word, subtype, keyword = m.groups()
        color_sym = find_color_word(color_word, "{}")
        name = subtype.capitalize()
        return _instruction(
            "arm_end_step_token",
            name=name,
            power=int(power),
            toughness=int(toughness),
            type_line=f"Creature — {name}",
            colors=(color_sym,) if color_sym else (),
            keywords=(keyword.capitalize(),) if keyword else (),
        ), "triggered_token"
    return None


@parse_rule(100000)
def add_mire_counter(text: str, activated: bool) -> RuleResult:
    if activated and "put a mire counter on target non-swamp land" in text:
        return _instruction("add_mire_counter_to_target_land"), "activated_landtype"
    return None


_REMOVE_COUNTER_FROM_SELF_RE = re.compile(
    r"remove a (?P<kind>\w+) counter from this \w+"
)


@parse_rule(81_450)
def remove_counter_from_self(text: str, activated: bool) -> RuleResult:
    """"Remove a <kind> counter from this <permanent>." (Armageddon Clock.)

    Only as an *effect*. Scavenging Ghoul's "remove a corpse counter from this
    creature: regenerate this creature" spends one as a cost, which the cost
    parser reads from the clause left of the colon — this rule sees only what
    is right of it.
    """
    match = _REMOVE_COUNTER_FROM_SELF_RE.search(text)
    if match is None:
        return None
    return (
        _instruction("remove_counter_from_self", counter=match.group("kind")),
        activated_kind(activated, "counters"),
    )
