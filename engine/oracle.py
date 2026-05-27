# New additions to oracle_compiler.py

from __future__ import annotations

from typing import Any
from dataclasses import dataclass, field
from functools import lru_cache
import re

from .models import CardDefinition


SUPPORTED_KEYWORDS = {
    "Banding",
    "Flying",
    "First strike",
    "Trample",
    "Vigilance",
    "Haste",
    "Defender",
    "Reach",
    "Protection",
    "Landwalk",
    "Swampwalk",
    "Forestwalk",
    "Islandwalk",
    "Mountainwalk",
    "Plainswalk",
}

UNSUPPORTED_KEYWORDS = {
    "Rampage",
    "Cumulative upkeep",
    "Phasing",
}

UNSUPPORTED_PATTERNS = (
    "exchange control",
)

UNSUPPORTED_REGEX_PATTERNS = ()

SUPPORTED_SPELL_PATTERNS = (
    "target player draws",
    "draws x cards",
    "deals",
    "deals x damage",
    "destroy target",
    "destroy all",
    "counter target",
    "gets +",
    "creatures get +",
    "target player discards",
    "loses",
    "regenerate target",
    "tap target",
    "untap target",
    "target creature with power 2 or less can't be blocked this turn",
    "prevent the next",
    "would deal damage to you this turn, prevent that damage",
    "from your graveyard to your hand",
    "from your graveyard to the battlefield",
    "from a graveyard onto the battlefield",
    "return target creature to its owner's hand",
    "each player discards their hand, then draws seven cards",
    "each player shuffles their hand and graveyard into their library, then draws seven cards",
    "search your library for a card, put that card into your hand, then shuffle",
    "take an extra turn after this one",
    "as an additional cost to cast this spell, sacrifice a creature",
    "becomes red",
    "becomes black",
    "becomes blue",
    "becomes green",
    "becomes white",
    "attacking creatures you control get +1/+0",
    "prevent all combat damage that would be dealt this turn",
    "look at target player's hand",
    "draw a card",
    "add three mana of any one color",
    "at the beginning of each player's draw step, if this artifact is untapped, that player draws an additional card",
    "at the beginning of your upkeep, sacrifice this enchantment unless you pay",
    "untapped creatures you control get +0/+2",
    "players skip their untap steps",
    "players can't untap more than one creature during their untap steps",
    "as long as this artifact is untapped, players can't untap more than one land during their untap steps",
    "creatures with power 3 or greater don't untap during their controllers' untap steps",
    "whenever a player taps a land for mana, that player adds one mana of any type that land produced",
    "this artifact becomes a 3/6 golem artifact creature until end of combat",
    "create a 1/1 colorless insect artifact creature token with flying named wasp",
    "enchant wall",
    "whenever a land enters",
    "at the beginning of the chosen player's upkeep",
    "enchant creature",
    "enchant land",
    "enchant artifact",
    "has swampwalk",
    "has forestwalk",
    "has islandwalk",
    "has mountainwalk",
    "has plainswalk",
    "add one mana",
    "add {",
    "gain",
    "each player chooses a number of lands they control equal to the number of lands controlled by the player who controls the fewest",
    "the next time an unblocked creature of your choice would deal combat damage to you this turn, prevent all but 1 of that damage",
    "white spells cost {3} more to cast",
    "all swamps are 1/1 black creatures that are still lands",
    "all forests are 1/1 creatures that are still lands",
    "you have no maximum hand size",
    "look at the top three cards of target player's library, then put them back in any order",
    "you may have that player shuffle",
    "change the text of target spell or permanent by replacing all instances of one basic land type with another",
    "change the text of target spell or permanent by replacing all instances of one color word with another",
    "look at target opponent's hand and choose a card from it",
    "target creature defending player controls can block any number of creatures this turn",
    "this turn, instead of declaring blockers",
    "put a mire counter on target non-swamp land",
    "remove target creature defending player controls from combat",
    "whenever one or more creatures you control attack, each defending player divides all creatures without flying",
    "you may spend white mana as though it were red mana",
    "target creature gains banding until end of turn",
    "copy target instant or sorcery spell",
    "remove this card from your deck before playing if you're not playing for ante",
    "discard your hand, ante the top card of your library, then draw seven cards",
    "you own target card in the ante. exchange that card with the top card of your library",
    "each player antes the top card of their library",
    "you may have this enchantment enter as a copy of any artifact on the battlefield",
)


# ---------------------------------------------------------------------------
# Supported trigger condition patterns
# Each entry: (kind, regex_or_substring)
# Checked in order; first match wins.
# ---------------------------------------------------------------------------

# "whenever" triggers
WHENEVER_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("creature_dies",               r"whenever a creature dies"),
    ("creature_you_control_dies",   r"whenever a creature you control dies"),
    ("creature_deals_damage",       r"whenever this creature deals damage"),
    ("creature_deals_combat_damage",r"whenever this creature deals combat damage to a player"),
    ("creature_attacks",            r"whenever this creature attacks"),
    ("creature_blocks",             r"whenever this creature blocks"),
    ("creature_becomes_blocked",    r"whenever this creature becomes blocked"),
    ("creature_attacks_or_blocks",  r"whenever this creature attacks or blocks"),
    ("land_tapped_for_mana",        r"whenever a player taps a land for mana"),
    ("spell_cast",                  r"whenever a player casts a spell"),
    ("opponent_casts_spell",        r"whenever an opponent casts a spell"),
    ("you_cast_spell",              r"whenever you cast a spell"),
    ("enchantment_cast",            r"whenever you cast an enchantment spell"),
    ("creature_enters",             r"whenever a creature enters(?: the battlefield)?"),
    ("land_enters",                 r"whenever a land enters(?: the battlefield)?"),
    ("artifact_enters",             r"whenever an artifact enters(?: the battlefield)?"),
    ("one_or_more_attack",          r"whenever one or more creatures you control attack"),
    ("draws_card",                  r"whenever you draw a card"),
    ("deals_damage_to_player",      r"whenever .+ deals damage to a player"),
)

# "when" triggers (enter/leave events)
WHEN_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("enters_battlefield",          r"when (?:this|.+) enters(?: the battlefield)?"),
    ("leaves_battlefield",          r"when (?:this|.+) leaves(?: the battlefield)?"),
    ("dies",                        r"when (?:this creature|.+) dies"),
    ("you_gain_life",               r"when you gain life"),
    ("becomes_target",              r"when (?:this|.+) becomes the target"),
)

# "at the beginning of" triggers
AT_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("upkeep_self",         r"at the beginning of your upkeep"),
    ("upkeep_each",         r"at the beginning of each (?:player's )?upkeep"),
    ("upkeep_chosen",       r"at the beginning of the chosen player's upkeep"),
    ("draw_step_each",      r"at the beginning of each player's draw step"),
    ("end_step",            r"at the beginning of (?:each )?end(?: step)?"),
    ("combat",              r"at the beginning of combat"),
)

# "if" conditions that can appear mid-effect
IF_CONDITION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("artifact_untapped",       r"if this artifact is untapped"),
    ("creature_died_this_turn", r"if a creature died this turn"),
    ("no_creatures_in_hand",    r"if you have no creatures in hand"),
    ("paid_mana",               r"if you paid? .+"),
    ("controls_island",         r"if (?:you |defending player )?controls? an? island"),
    ("controls_swamp",          r"if (?:you |defending player )?controls? an? swamp"),
    ("is_untapped",             r"if (?:this|it) is untapped"),
    ("not_playing_for_ante",    r"if you're not playing for ante"),
)


@dataclass(frozen=True)
class OracleToken:
    kind: str
    value: str


@dataclass(frozen=True)
class ActivatedAbilityCost:
    mana: dict[str, int]
    requires_tap: bool = False


@dataclass(frozen=True)
class OracleInstruction:
    kind: str
    value: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TriggerCondition:
    """Represents the condition half of a triggered ability.

    kind     -- semantic label, e.g. "creature_dies", "upkeep_self"
    trigger  -- the raw trigger word: "when", "whenever", or "at"
    raw_text -- the normalized condition clause as it appeared in oracle text
    payload  -- optional structured data extracted from the condition
    """
    kind: str
    trigger: str          # "when" | "whenever" | "at"
    raw_text: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedActivatedAbility:
    source_line: str
    normalized_effect: str
    supported: bool
    cost: ActivatedAbilityCost
    effect_kind: str = "unsupported"
    instruction: OracleInstruction | None = None


@dataclass(frozen=True)
class ParsedTriggeredAbility:
    """A fully parsed triggered ability: condition + effect instruction.

    source_line  -- original oracle text line
    condition    -- the parsed trigger condition
    instruction  -- the parsed effect, or None if unsupported
    supported    -- True only if both condition and effect are recognized
    effect_kind  -- mirrors the effect_kind convention used elsewhere
    """
    source_line: str
    condition: TriggerCondition
    instruction: OracleInstruction | None
    supported: bool
    effect_kind: str = "unsupported"


@dataclass(frozen=True)
class OracleProgram:
    supported: bool
    effect_kind: str
    reason: str
    normalized_text: str
    tokens: tuple[OracleToken, ...]
    instructions: tuple[OracleInstruction, ...] = ()
    activated_abilities: tuple[ParsedActivatedAbility, ...] = ()
    triggered_abilities: tuple[ParsedTriggeredAbility, ...] = ()
    static_lines: tuple[str, ...] = ()


class OracleLexer:
    _TOKEN_RE = re.compile(r"\{[^}]+\}|[A-Za-z']+|\d+|\n|[:.,;+/\-]")

    def tokenize(self, oracle_text: str) -> tuple[OracleToken, ...]:
        if not oracle_text:
            return ()

        tokens: list[OracleToken] = []
        for raw in self._TOKEN_RE.findall(oracle_text):
            if raw == "\n":
                tokens.append(OracleToken("newline", raw))
                continue
            if raw.startswith("{") and raw.endswith("}"):
                tokens.append(OracleToken("mana", raw.upper()))
                continue
            if raw.isdigit():
                tokens.append(OracleToken("number", raw))
                continue
            if raw == ":":
                tokens.append(OracleToken("colon", raw))
                continue
            if raw in {".", ",", ";", "+", "/", "-"}:
                tokens.append(OracleToken("symbol", raw))
                continue
            tokens.append(OracleToken("word", raw.lower()))
        return tuple(tokens)


_LEXER = OracleLexer()


def lex_oracle_text(oracle_text: str) -> tuple[OracleToken, ...]:
    return _LEXER.tokenize(oracle_text)


def _normalize_text(oracle_text: str) -> str:
    return re.sub(r"\s+", " ", oracle_text.strip().lower())


def normalize_creature_line(line: str) -> str:
    lowered = line.lower()
    lowered = re.sub(r"\([^)]*\)", "", lowered)
    lowered = lowered.replace(";", ",")
    lowered = re.sub(r"\s+", " ", lowered).strip(" .,")
    return lowered


def parse_activated_ability_cost(line: str) -> ActivatedAbilityCost:
    required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 0}
    requires_tap = False
    if not line or ":" not in line:
        return ActivatedAbilityCost(required, requires_tap)

    cost_part = line.split(":", 1)[0]
    for token in re.findall(r"\{([^}]+)\}", cost_part.upper()):
        if token == "T":
            requires_tap = True
            continue
        if token.isdigit():
            required["generic"] += int(token)
            continue
        if token in {"W", "U", "B", "R", "G", "C"}:
            required[token] += 1
    return ActivatedAbilityCost(required, requires_tap)


def _instruction(kind: str, value: str = "", **payload: Any) -> OracleInstruction:
    return OracleInstruction(kind, value, payload)


def _parse_number_token(token: str) -> int:
    number_words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
    }
    if token.isdigit():
        return int(token)
    return number_words.get(token, 0)


# ---------------------------------------------------------------------------
# Trigger condition parsing
# ---------------------------------------------------------------------------

def _match_trigger_patterns(
    text: str,
    patterns: tuple[tuple[str, str], ...],
    trigger_word: str,
) -> TriggerCondition | None:
    for kind, pattern in patterns:
        m = re.match(pattern, text)
        if m:
            return TriggerCondition(kind=kind, trigger=trigger_word, raw_text=m.group(0))
    return None


def _parse_trigger_condition(normalized_line: str) -> tuple[TriggerCondition | None, str]:
    """Try to parse a trigger condition from the start of a normalized line.

    Returns (TriggerCondition, remainder_effect_text) or (None, original_line).
    The remainder is the effect clause after the condition, with leading
    punctuation and whitespace stripped.
    """
    if normalized_line.startswith("whenever "):
        cond = _match_trigger_patterns(normalized_line, WHENEVER_TRIGGER_PATTERNS, "whenever")
        if cond:
            remainder = normalized_line[len(cond.raw_text):].lstrip(" ,")
            return cond, remainder

    if normalized_line.startswith("when "):
        cond = _match_trigger_patterns(normalized_line, WHEN_TRIGGER_PATTERNS, "when")
        if cond:
            remainder = normalized_line[len(cond.raw_text):].lstrip(" ,")
            return cond, remainder

    if normalized_line.startswith("at "):
        cond = _match_trigger_patterns(normalized_line, AT_TRIGGER_PATTERNS, "at")
        if cond:
            remainder = normalized_line[len(cond.raw_text):].lstrip(" ,")
            return cond, remainder

    return None, normalized_line


def _extract_if_condition(effect_text: str) -> tuple[str | None, str]:
    """Strip a trailing 'if ...' clause from an effect and return (if_kind, clean_effect).

    Returns (None, original_text) if no recognized 'if' condition is present.
    """
    # Look for ", if ..." near the end of the effect text
    if_match = re.search(r",\s*(if .+)$", effect_text)
    if not if_match:
        return None, effect_text

    if_clause = if_match.group(1)
    for kind, pattern in IF_CONDITION_PATTERNS:
        if re.match(pattern, if_clause):
            clean = effect_text[: if_match.start()].strip()
            return kind, clean

    return None, effect_text


def _parse_triggered_ability(line: str) -> ParsedTriggeredAbility | None:
    """Parse a single oracle text line as a triggered ability.

    Returns None if the line doesn't start with a trigger word at all,
    so the caller can try other parsers. Returns a ParsedTriggeredAbility
    with supported=False if the trigger prefix is recognized but the
    condition or effect is not.
    """
    normalized = normalize_creature_line(line)

    condition, remainder = _parse_trigger_condition(normalized)
    if condition is None:
        return None  # not a triggered ability line

    # Strip leading colon/comma that sometimes follows the condition clause
    remainder = remainder.lstrip(": ")

    # Extract any trailing "if ..." guard on the effect
    if_kind, clean_effect = _extract_if_condition(remainder)

    instruction, effect_kind = _parse_primary_instruction(clean_effect, activated=False)

    if instruction is not None and if_kind is not None:
        # Attach the if-condition into the instruction payload
        instruction = OracleInstruction(
            instruction.kind,
            instruction.value,
            {**instruction.payload, "if_condition": if_kind},
        )

    supported = instruction is not None
    return ParsedTriggeredAbility(
        source_line=line,
        condition=condition,
        instruction=instruction,
        supported=supported,
        effect_kind=effect_kind if supported else "unsupported",
    )


# ---------------------------------------------------------------------------
# Effect instruction parsing (unchanged from original, reproduced in full)
# ---------------------------------------------------------------------------

def _parse_primary_instruction(text: str, *, activated: bool) -> tuple[OracleInstruction | None, str]:
    if activated and ("untap this artifact" in text or "untap this permanent" in text):
        return _instruction("untap_self"), "activated_untap"
    if "target player draws x cards" in text:
        effect_kind = "activated_draw" if activated else "spell_pattern"
        return _instruction("draw_target_cards", amount="x"), effect_kind

    if "discard your hand, ante the top card of your library, then draw seven cards" in text:
        return _instruction("discard_hand_ante_then_draw_seven"), "spell_pattern"

    if "each player antes the top card of their library" in text:
        return _instruction("each_player_antes_top_card"), "spell_pattern"

    if "you own target card in the ante. exchange that card with the top card of your library" in text:
        return _instruction("exchange_ante_with_top_library"), "spell_pattern"

    draw_match = re.search(r"target player draws (\w+) cards?", text)
    if draw_match:
        count = _parse_number_token(draw_match.group(1))
        if count > 0:
            effect_kind = "activated_draw" if activated else "spell_pattern"
            return _instruction("draw_target_cards", amount=count), effect_kind

    if "copy target instant or sorcery spell" in text:
        return _instruction("copy_top_stack_spell"), "spell_pattern"

    if "each player chooses a number of lands they control equal to the number of lands controlled by the player who controls the fewest" in text:
        return _instruction("balance_resources"), "spell_pattern"

    if "target creature defending player controls can block any number of creatures this turn" in text:
        effect_kind = "activated_keyword" if activated else "spell_pattern"
        return _instruction("grant_unlimited_blocking"), effect_kind

    if "this turn, instead of declaring blockers" in text:
        return _instruction("randomize_blockers"), "spell_pattern"

    if "remove target creature defending player controls from combat" in text:
        effect_kind = "activated_combat" if activated else "spell_pattern"
        return _instruction("remove_creature_from_combat"), effect_kind

    if "whenever one or more creatures you control attack, each defending player divides all creatures without flying" in text:
        return _instruction("left_right_combat_division"), "spell_pattern"

    if "deals x damage" in text:
        effect_kind = "activated_damage" if activated else "spell_pattern"
        return _instruction("deal_damage", amount="x"), effect_kind

    if activated and "deals 2 damage to any target and 3 damage to you" in text:
        return _instruction("deal_damage_and_self_damage", amount=2, self_damage=3), "activated_damage"

    dmg_match = re.search(r"deals (\d+) damage", text)
    if dmg_match:
        effect_kind = "activated_damage" if activated else "spell_pattern"
        return _instruction("deal_damage", amount=int(dmg_match.group(1))), effect_kind

    if "from your graveyard to the battlefield" in text or "from a graveyard onto the battlefield" in text:
        return _instruction("reanimate_creature"), "spell_pattern"

    if "return target creature to its owner's hand" in text:
        return _instruction("bounce_target_creature"), "spell_pattern"

    if "prevent all combat damage that would be dealt this turn" in text:
        return _instruction("prevent_all_combat_damage"), "spell_pattern"

    if "each player discards their hand, then draws seven cards" in text:
        return _instruction("wheel_of_fortune"), "spell_pattern"

    if "each player shuffles their hand and graveyard into their library, then draws seven cards" in text:
        return _instruction("timetwister"), "spell_pattern"

    if "search your library for a card, put that card into your hand, then shuffle" in text:
        return _instruction("tutor_top_card"), "spell_pattern"

    if "take an extra turn after this one" in text:
        return _instruction("grant_extra_turn"), "spell_pattern"

    if "look at the top three cards of target player's library, then put them back in any order" in text:
        return _instruction("reorder_target_library_top"), "spell_pattern"

    if "change the text of target spell or permanent by replacing all instances of one basic land type with another" in text:
        return _instruction("mark_text_modified"), "spell_pattern"

    if "change the text of target spell or permanent by replacing all instances of one color word with another" in text:
        return _instruction("mark_text_modified"), "spell_pattern"

    if "look at target opponent's hand and choose a card from it" in text:
        return _instruction("peek_hand_and_force_play"), "spell_pattern"

    if "as an additional cost to cast this spell, sacrifice a creature" in text:
        return _instruction("sacrifice_creature_for_black_mana"), "spell_pattern"

    if any(f"becomes {color}" in text for color in ("red", "black", "blue", "green", "white")):
        return _instruction("recolor_target_from_text"), "spell_pattern"

    if "destroy all artifacts, creatures, and enchantments" in text:
        return _instruction("destroy_all_artifacts_creatures_enchantments"), "spell_pattern"

    if "destroy all creatures" in text:
        return _instruction("destroy_all_creatures"), "spell_pattern"

    if "destroy all lands" in text:
        return _instruction("destroy_all_lands"), "spell_pattern"

    if "destroy target" in text:
        effect_kind = "activated_destroy" if activated else "spell_pattern"
        return _instruction("destroy_target_permanent", oracle_text=text), effect_kind

    if "from your graveyard to your hand" in text:
        return _instruction("return_creature_from_graveyard_to_hand"), "spell_pattern"

    discard_match = re.search(r"target player discards (\w+) cards?", text)
    if discard_match:
        count = _parse_number_token(discard_match.group(1))
        if count > 0:
            return _instruction("discard_target_cards", amount=count), "spell_pattern"

    lose_life_match = re.search(r"target player loses (\d+) life", text)
    if lose_life_match:
        return _instruction("target_loses_life", amount=int(lose_life_match.group(1))), "spell_pattern"

    if "gains x life" in text or "gain x life" in text:
        return _instruction("target_gains_life", amount="x"), "spell_pattern"

    if "untap target land" in text and activated:
        return _instruction("untap_target_land"), "activated_untap"

    if "untap target" in text:
        return _instruction("untap_target_permanent"), "spell_pattern"

    if "tap target" in text:
        return _instruction("tap_target_permanent"), "spell_pattern"

    prevent_match = re.search(r"prevent the next (\d+) damage", text)
    if prevent_match:
        amount = int(prevent_match.group(1))
        effect_kind = "activated_prevent" if activated else "spell_pattern"
        return _instruction("grant_prevention_shield", amount=amount), effect_kind

    if "would deal damage to you this turn, prevent that damage" in text and activated:
        return _instruction("grant_prevention_shield", amount=1), "activated_prevent"

    if "the next time an unblocked creature of your choice would deal combat damage to you this turn, prevent all but 1 of that damage" in text and activated:
        return _instruction("grant_forcefield_shield"), "activated_prevent"

    if "regenerate target creature" in text:
        effect_kind = "activated_regenerate" if activated else "spell_pattern"
        return _instruction("grant_regeneration_to_target_creature"), effect_kind

    if activated and "regenerate this creature" in text:
        return _instruction("grant_regeneration_to_self"), "activated_regenerate"

    if "gain" in text and "life" in text:
        gain_match = re.search(r"gains? (\d+) life", text)
        if gain_match:
            effect_kind = "activated_gain_life" if activated else "spell_pattern"
            return _instruction("target_gains_life", amount=int(gain_match.group(1))), effect_kind

    if activated and "this creature gets +1/+0 until end of turn" in text:
        return _instruction("pump_self", power=1, toughness=0), "activated_pump"

    if activated and "this creature gets +0/+1 until end of turn" in text:
        return _instruction("pump_self", power=0, toughness=1), "activated_pump"

    if activated and "this creature gets +1/+1 until end of turn" in text:
        return _instruction("pump_self", power=1, toughness=1), "activated_pump"

    if activated and "this creature gains flying until end of turn" in text:
        return _instruction("grant_self_flying_until_eot"), "activated_keyword"

    if activated and "target creature gains banding until end of turn" in text:
        return _instruction("grant_banding_to_target"), "activated_keyword"

    if activated and "put a +1/+1 counter on this creature" in text:
        return _instruction("add_counter_to_self", power=1, toughness=1), "activated_counter"

    if activated and "put up to x +1/+0 counters on this creature" in text:
        return _instruction("add_variable_power_counters_to_self"), "activated_counter"

    if activated and "add three mana of any one color" in text:
        return _instruction("sacrifice_self_for_mana", amount=3, color="G"), "activated_mana"

    if activated and "draw a card" in text:
        return _instruction("draw_controller_cards", amount=1), "activated_draw"

    if activated and "target creature with power 2 or less can't be blocked this turn" in text:
        return _instruction("grant_unblockable_to_low_power_target"), "activated_evasion"

    if activated and "target land becomes a forest" in text:
        return _instruction("change_target_land_type", land_type="forest"), "activated_landtype"

    if activated and "choose target non-wall creature" in text:
        return _instruction("mark_non_wall_target_to_attack"), "activated_combat"

    if activated and "target creature you control with toughness less than this creature's power gains flying until end of turn" in text:
        return _instruction("grant_flying_and_delayed_destruction"), "activated_keyword"

    if activated and "the next 1 damage that would be dealt to this creature this turn is dealt to its owner instead" in text:
        return _instruction("redirect_one_damage_to_owner"), "activated_prevent"

    if activated and "this artifact becomes a 3/6 golem artifact creature until end of combat" in text:
        return _instruction("animate_self_until_end_of_combat", power=3, toughness=6), "activated_animate"

    if activated and "create a 1/1 colorless insect artifact creature token with flying named wasp" in text:
        return _instruction("create_wasp_token"), "activated_token"

    if activated and "look at target player's hand" in text:
        return _instruction("look_at_target_hand"), "activated_look"

    if activated and "put a mire counter on target non-swamp land" in text:
        return _instruction("add_mire_counter_to_target_land"), "activated_landtype"

    if activated and "add {" in text:
        return _instruction("add_mana_from_text", oracle_text=text), "activated_mana"

    if "counter target spell" in text:
        return _instruction("counter_top_stack_spell"), "spell_pattern"

    # Triggered-ability effect shorthands (no "activated" guard needed)
    if "draw a card" in text:
        return _instruction("draw_controller_cards", amount=1), "triggered_draw"

    if "put a +1/+1 counter on this creature" in text:
        return _instruction("add_counter_to_self", power=1, toughness=1), "triggered_counter"

    if "put a +1/+1 counter on target creature" in text:
        return _instruction("add_counter_to_target", power=1, toughness=1), "triggered_counter"

    if "you lose the game" in text:
        return _instruction("player_loses_game"), "triggered_loss"

    if "you win the game" in text:
        return _instruction("player_wins_game"), "triggered_win"

    if "sacrifice this permanent" in text or "sacrifice this creature" in text:
        return _instruction("sacrifice_self"), "triggered_sacrifice"

    return None, "unsupported"


# ---------------------------------------------------------------------------
# Creature-line helpers (unchanged)
# ---------------------------------------------------------------------------

def _is_supported_keyword_line(line: str) -> bool:
    normalized = normalize_creature_line(line)
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    if not parts:
        return False
    supported = {keyword.lower() for keyword in SUPPORTED_KEYWORDS}
    return all(part in supported for part in parts)


def _parse_activated_ability(line: str) -> ParsedActivatedAbility | None:
    normalized = normalize_creature_line(line)
    if ":" not in normalized:
        return None

    effect_text = normalized.split(":", 1)[1].strip()
    instruction, effect_kind = _parse_primary_instruction(effect_text, activated=True)
    supported = instruction is not None
    return ParsedActivatedAbility(
        source_line=line,
        normalized_effect=effect_text,
        supported=supported,
        cost=parse_activated_ability_cost(line),
        effect_kind=effect_kind,
        instruction=instruction,
    )


def _is_supported_static_creature_line(line: str) -> bool:
    normalized = normalize_creature_line(line)
    if normalized.startswith("protection from "):
        return True
    static_patterns = (
        "this creature enters with seven +1/+0 counters on it",
        "this creature enters with x +1/+1 counters on it",
        "at end of combat, if this creature attacked or blocked this combat, remove a +1/+0 counter from it",
        "for each 1 damage that would be dealt to this creature, if it has a +1/+1 counter on it, remove a +1/+1 counter from it and prevent that 1 damage",
        "this creature can't block",
        "this creature can't attack",
        "this creature can't attack unless defending player controls an island",
        "this creature attacks each combat if able",
        "this creature can block an additional creature each combat",
        "as long as you control a swamp, this creature gets +1/+1",
        "keldon warlord's power and toughness are each equal to the number of non-wall creatures you control",
        "plague rats's power and toughness are each equal to the number of creatures named plague rats on the battlefield",
        "as long as gaea's liege isn't attacking",
        "nightmare's power and toughness are each equal to the number of swamps you control",
        "gets +1/+1 as long as you control a swamp",
        "this creature gets +1/+1 as long as you control a swamp",
        "whenever this creature casts an enchantment spell",
        "whenever you cast an enchantment spell, you may draw a card",
        "whenever this creature blocks or becomes blocked by a non-wall creature, destroy that creature at end of combat",
        "whenever this creature deals damage to an opponent, that player discards a card at random",
        "whenever this creature is dealt damage, put a +1/+1 counter on it",
        "whenever a creature dealt damage by this creature this turn dies, put a +1/+1 counter on this creature",
        "this creature can't be blocked by walls",
        "when you control no islands, sacrifice this creature",
        "as long as this creature is untapped, all damage that would be dealt to you by unblocked creatures is dealt to this creature instead",
        "at the beginning of your upkeep, unless you pay {b}{b}{b}, tap this creature and sacrifice a land of an opponent's choice",
        "at the beginning of your upkeep, this creature deals 8 damage to you unless you pay",
        "at the beginning of your upkeep, sacrifice a creature other than this creature",
        "at the beginning of your upkeep, sacrifice this creature unless you pay",
        "at the beginning of your upkeep, if this card is in your graveyard with three or more creature cards above it, you may put this card onto the battlefield",
        "at the beginning of each end step, put a corpse counter on this creature for each creature that died this turn",
        "remove a corpse counter from this creature: regenerate this creature",
        "when this creature dies, its owner loses half their life, rounded up",
        "you may have this creature enter as a copy of any creature on the battlefield",
        "other ",
    )
    if normalized.startswith("other ") and " get +" in normalized:
        return True
    return any(normalized.startswith(pattern) for pattern in static_patterns)


# ---------------------------------------------------------------------------
# Creature program parser — updated to handle triggered abilities per line
# ---------------------------------------------------------------------------

def _parse_creature_program(
    oracle_text: str,
) -> tuple[bool, str, str, tuple[OracleInstruction, ...], tuple[ParsedActivatedAbility, ...], tuple[ParsedTriggeredAbility, ...], tuple[str, ...]]:
    text = oracle_text.strip()
    if not text:
        return True, "creature_simple", "simple creature support", (), (), (), ()

    instructions: list[OracleInstruction] = []
    activated: list[ParsedActivatedAbility] = []
    triggered: list[ParsedTriggeredAbility] = []
    static_lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # 1. Plain keyword line (e.g. "Flying, Trample")
        if _is_supported_keyword_line(line):
            normalized = normalize_creature_line(line)
            instructions.append(OracleInstruction("keyword_line", normalized))
            static_lines.append(normalized)
            continue

        # 2. Triggered ability
        trig = _parse_triggered_ability(line)
        if trig is not None:
            if not trig.supported:
                return False, "unsupported", "unsupported triggered ability", (), (), (), ()
            triggered.append(trig)
            if trig.instruction is not None:
                instructions.append(trig.instruction)
            continue

        # 3. Activated ability
        ability = _parse_activated_ability(line)
        if ability is not None and ability.supported:
            activated.append(ability)
            if ability.instruction is not None:
                instructions.append(ability.instruction)
            continue

        # 4. Static text
        if _is_supported_static_creature_line(line):
            normalized = normalize_creature_line(line)
            instructions.append(OracleInstruction("static_line", normalized))
            static_lines.append(normalized)
            continue

        return False, "unsupported", "creature text too complex", (), (), (), ()

    return (
        True,
        "creature_simple",
        "simple creature support",
        tuple(instructions),
        tuple(activated),
        tuple(triggered),
        tuple(static_lines),
    )


def _parse_noncreature_abilities(oracle_text: str) -> tuple[ParsedActivatedAbility, ...]:
    abilities: list[ParsedActivatedAbility] = []
    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        ability = _parse_activated_ability(line)
        if ability is not None:
            abilities.append(ability)
    return tuple(abilities)


def _parse_noncreature_triggered(oracle_text: str) -> tuple[ParsedTriggeredAbility, ...]:
    """Extract triggered abilities from non-creature oracle text."""
    abilities: list[ParsedTriggeredAbility] = []
    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        trig = _parse_triggered_ability(line)
        if trig is not None:
            abilities.append(trig)
    return tuple(abilities)


# ---------------------------------------------------------------------------
# Top-level compiler
# ---------------------------------------------------------------------------

@lru_cache(maxsize=2048)
def _compile_card_oracle(
    name: str,
    primary_type: str,
    oracle_text: str,
    keywords: tuple[str, ...],
) -> OracleProgram:
    tokens = lex_oracle_text(oracle_text)
    normalized_text = _normalize_text(oracle_text)

    if any(keyword in keywords for keyword in UNSUPPORTED_KEYWORDS):
        return OracleProgram(False, "unsupported", "unsupported keyword", normalized_text, tokens)

    if any(re.search(pattern, normalized_text) for pattern in UNSUPPORTED_REGEX_PATTERNS):
        return OracleProgram(False, "unsupported", "complex oracle pattern", normalized_text, tokens)

    if any(pattern in normalized_text for pattern in UNSUPPORTED_PATTERNS):
        return OracleProgram(False, "unsupported", "complex oracle pattern", normalized_text, tokens)

    if primary_type == "land":
        return OracleProgram(True, "land_mana", "basic land support", normalized_text, tokens)

    if primary_type == "creature":
        supported, effect_kind, reason, instructions, activated, triggered, static_lines = _parse_creature_program(oracle_text)
        return OracleProgram(supported, effect_kind, reason, normalized_text, tokens, instructions, activated, triggered, static_lines)

    if primary_type in {"artifact", "enchantment", "instant", "sorcery"}:
        if not normalized_text:
            return OracleProgram(True, "permanent_vanilla", "no oracle text", normalized_text, tokens)

        instructions: list[OracleInstruction] = []
        primary_instruction, _ = _parse_primary_instruction(normalized_text, activated=False)
        if primary_instruction is not None:
            instructions.append(primary_instruction)

        instructions.extend(
            OracleInstruction("spell_pattern", pattern)
            for pattern in SUPPORTED_SPELL_PATTERNS
            if pattern in normalized_text
        )

        activated_abilities = _parse_noncreature_abilities(oracle_text)
        triggered_abilities = _parse_noncreature_triggered(oracle_text)

        # An unsupported triggered ability on a non-creature marks the card unsupported
        if any(not t.supported for t in triggered_abilities):
            return OracleProgram(False, "unsupported", "unsupported triggered ability", normalized_text, tokens)

        if instructions or any(a.supported for a in activated_abilities) or triggered_abilities:
            return OracleProgram(
                True,
                "spell_pattern",
                "pattern-supported effect",
                normalized_text,
                tokens,
                tuple(instructions),
                activated_abilities,
                triggered_abilities,
            )

        return OracleProgram(False, "unsupported", "effect not in basic pattern set", normalized_text, tokens)

    return OracleProgram(False, "unsupported", "unknown card type", normalized_text, tokens)


def compile_card_oracle(card: CardDefinition) -> OracleProgram:
    return _compile_card_oracle(card.name, card.primary_type, card.oracle_text, card.keywords)