"""Oracle-text compiler.

Turns a card's oracle text into an OracleProgram: a set of instructions,
activated abilities, triggered abilities, and static lines the game engine
can execute. Effect-clause parsing is delegated to the declarative rule
registry in engine.parsing; this module owns tokenizing, line classification
(keyword / triggered / activated / static), and the per-card compile cache.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .models import CardDefinition
from .oracle_types import (
    ActivatedAbilityCost,
    ModalOption,
    OracleInstruction,
    OracleProgram,
    OracleToken,
    ParsedActivatedAbility,
    ParsedTriggeredAbility,
    TriggerCondition,
    _COLOR_WORD_TO_SYMBOL,
    _extract_mana_cost_from_text,
    _instruction,
    _parse_number_token,
)
from .parsing import parse_modal_options, parse_primary_instruction

__all__ = [
    "ActivatedAbilityCost",
    "ModalOption",
    "OracleInstruction",
    "OracleProgram",
    "OracleToken",
    "ParsedActivatedAbility",
    "ParsedTriggeredAbility",
    "TriggerCondition",
    "compile_card_oracle",
    "lex_oracle_text",
    "normalize_creature_line",
    "parse_activated_ability_cost",
]


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
    "target player loses the game",
    "you win the game",
    "the game is a draw",
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
    "target creature gains flying until end of turn",
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
    ("land_dies",                   r"whenever a land is put into a graveyard from the battlefield"),
    ("creature_dies",               r"whenever a creature dies"),
    ("creature_you_control_dies",   r"whenever a creature you control dies"),
    ("creature_deals_damage",       r"whenever this creature deals damage"),
    ("creature_deals_combat_damage",r"whenever this creature deals combat damage to a player"),
    ("cockatrice_blocks_or_blocked", r"whenever this creature blocks or becomes blocked by a non-wall creature"),
    ("hypnotic_specter_deals_damage", r"whenever this creature deals damage to an opponent"),
    ("creature_attacks",            r"whenever this creature attacks"),
    ("creature_blocks",             r"whenever this creature blocks"),
    ("creature_becomes_blocked",    r"whenever this creature becomes blocked"),
    ("creature_attacks_or_blocks",  r"whenever this creature attacks or blocks"),
    ("creature_dealt_damage",               r"whenever this creature is dealt damage"),
    ("creature_dealt_damage_by_self_dies",  r"whenever a creature dealt damage by this creature this turn dies"),
    ("enchanted_land_tapped",       r"whenever enchanted land becomes tapped"),
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
    ("no_islands",                  r"when you control no islands"),
)

# "at the beginning of" triggers
AT_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("upkeep_self",         r"at the beginning of your upkeep"),
    ("upkeep_each",         r"at the beginning of each (?:player's )?upkeep"),
    ("upkeep_enchanted_controller", r"at the beginning of the upkeep of enchanted enchantment's controller"),
    ("upkeep_chosen",       r"at the beginning of the chosen player's upkeep"),
    ("draw_step_each",      r"at the beginning of each player's draw step"),
    ("end_step",            r"at the beginning of (?:the |each )?end(?: step)?"),
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


def _compile_trigger_patterns(
    patterns: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple((kind, re.compile(pattern)) for kind, pattern in patterns)


# Precompiled once at import. Python's internal regex cache holds only 512
# entries, so relying on it would thrash as the pattern tables grow.
_COMPILED_WHENEVER_PATTERNS = _compile_trigger_patterns(WHENEVER_TRIGGER_PATTERNS)
_COMPILED_WHEN_PATTERNS = _compile_trigger_patterns(WHEN_TRIGGER_PATTERNS)
_COMPILED_AT_PATTERNS = _compile_trigger_patterns(AT_TRIGGER_PATTERNS)
_COMPILED_IF_PATTERNS = _compile_trigger_patterns(IF_CONDITION_PATTERNS)


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


_WHITESPACE_RE = re.compile(r"\s+")
_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")


def _normalize_text(oracle_text: str) -> str:
    return _WHITESPACE_RE.sub(" ", oracle_text.strip().lower())


def normalize_creature_line(line: str) -> str:
    lowered = line.lower()
    lowered = _PARENTHETICAL_RE.sub("", lowered)
    lowered = lowered.replace(";", ",")
    lowered = _WHITESPACE_RE.sub(" ", lowered).strip(" .,")
    return lowered


_MANA_TOKEN_RE = re.compile(r"\{([^}]+)\}")


def parse_activated_ability_cost(line: str) -> ActivatedAbilityCost:
    required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 0}
    requires_tap = False
    if not line or ":" not in line:
        return ActivatedAbilityCost(required, requires_tap)

    cost_part = line.split(":", 1)[0]
    for token in _MANA_TOKEN_RE.findall(cost_part.upper()):
        if token == "T":
            requires_tap = True
            continue
        if token.isdigit():
            required["generic"] += int(token)
            continue
        if token in {"W", "U", "B", "R", "G", "C"}:
            required[token] += 1
    return ActivatedAbilityCost(required, requires_tap)


# ---------------------------------------------------------------------------
# Trigger condition parsing
# ---------------------------------------------------------------------------

def _match_trigger_patterns(
    text: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    trigger_word: str,
) -> TriggerCondition | None:
    for kind, pattern in patterns:
        m = pattern.match(text)
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
        cond = _match_trigger_patterns(normalized_line, _COMPILED_WHENEVER_PATTERNS, "whenever")
        if cond:
            remainder = normalized_line[len(cond.raw_text):].lstrip(" ,")
            return cond, remainder

    if normalized_line.startswith("when "):
        cond = _match_trigger_patterns(normalized_line, _COMPILED_WHEN_PATTERNS, "when")
        if cond:
            remainder = normalized_line[len(cond.raw_text):].lstrip(" ,")
            return cond, remainder

    if normalized_line.startswith("at "):
        cond = _match_trigger_patterns(normalized_line, _COMPILED_AT_PATTERNS, "at")
        if cond:
            remainder = normalized_line[len(cond.raw_text):].lstrip(" ,")
            return cond, remainder

    return None, normalized_line


_TRAILING_IF_RE = re.compile(r",\s*(if .+)$")


def _extract_if_condition(effect_text: str) -> tuple[str | None, str]:
    """Strip a trailing 'if ...' clause from an effect and return (if_kind, clean_effect).

    Returns (None, original_text) if no recognized 'if' condition is present.
    """
    # Look for ", if ..." near the end of the effect text
    if_match = _TRAILING_IF_RE.search(effect_text)
    if not if_match:
        return None, effect_text

    if_clause = if_match.group(1)
    for kind, pattern in _COMPILED_IF_PATTERNS:
        if pattern.match(if_clause):
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

    instruction, effect_kind = parse_primary_instruction(clean_effect, activated=False)

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
# Effect instruction parsing — delegated to the engine.parsing rule registry.
# Kept as a module-level alias for backwards compatibility.
# ---------------------------------------------------------------------------

def _parse_primary_instruction(text: str, *, activated: bool) -> tuple[OracleInstruction | None, str]:
    return parse_primary_instruction(text, activated=activated)


# ---------------------------------------------------------------------------
# Creature-line helpers
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
    instruction, effect_kind = parse_primary_instruction(effect_text, activated=True)
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
        "this creature enters tapped",
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
        "this creature can't be blocked by walls",
        "as long as this creature is untapped, all damage that would be dealt to you by unblocked creatures is dealt to this creature instead",
        "remove a corpse counter from this creature: regenerate this creature",
        "you may have this creature enter as a copy of any creature on the battlefield",
        "other ",
    )
    if normalized.startswith("other ") and " get +" in normalized:
        return True
    return any(normalized.startswith(pattern) for pattern in static_patterns)


# ---------------------------------------------------------------------------
# Creature program parser
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

    any_supported_trigger = False
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
            if trig.supported:
                triggered.append(trig)
                any_supported_trigger = True
                if trig.instruction is not None:
                    instructions.append(trig.instruction)
                continue
            # Trigger condition recognized but effect is unsupported.
            # Before giving up, check if the full line is listed as a supported
            # static pattern (e.g. "at the beginning of your upkeep, unless you
            # pay …" for Demonic Hordes, or "when this creature dies …" for
            # Personal Incarnation).
            if _is_supported_static_creature_line(line):
                normalized = normalize_creature_line(line)
                instructions.append(OracleInstruction("static_line", normalized))
                static_lines.append(normalized)
                continue
            triggered.append(trig)
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
            # Emit specific instruction kinds for dynamic P/T patterns so game.py
            # never needs to parse oracle text to identify these behaviours.
            if "power and toughness are each equal to the number of non-wall creatures" in normalized:
                instructions.append(OracleInstruction("dynamic_pt_non_wall_creatures"))
            elif "power and toughness are each equal to the number of creatures named plague rats" in normalized:
                instructions.append(OracleInstruction("dynamic_pt_plague_rats"))
            elif "power and toughness are each equal to the number of swamps" in normalized:
                instructions.append(OracleInstruction("dynamic_pt_swamps"))
            elif normalized.startswith("as long as gaea's liege isn't attacking"):
                instructions.append(OracleInstruction("dynamic_pt_forests_gaea"))
            elif (
                "gets +1/+1 as long as you control a swamp" in normalized
                or "this creature gets +1/+1 as long as you control a swamp" in normalized
            ):
                instructions.append(OracleInstruction("conditional_swamp_bonus"))
            elif normalized == "this creature attacks each combat if able":
                instructions.append(OracleInstruction("must_attack_each_combat"))
            elif normalized == "this creature can't be blocked by walls":
                instructions.append(OracleInstruction("cant_be_blocked_by_walls"))
            elif normalized == "this creature can't attack unless defending player controls an island":
                instructions.append(OracleInstruction("cant_attack_without_island"))
            elif normalized == "this creature can't attack":
                instructions.append(OracleInstruction("cant_attack"))
            elif normalized == "this creature can't block":
                instructions.append(OracleInstruction("cant_block"))
            elif normalized == "this creature can't block creatures with power 2 or greater":
                instructions.append(OracleInstruction("cant_block_power_2_or_greater"))
            else:
                instructions.append(OracleInstruction("static_line", normalized))
            static_lines.append(normalized)
            continue

        return False, "unsupported", "creature text too complex", (), (), (), ()

    if triggered and not any_supported_trigger:
        return False, "unsupported", "unsupported triggered ability", (), (), tuple(triggered), tuple(static_lines)

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

# Unbounded cache: card definitions are immutable and the pool is finite, so
# every distinct card compiles exactly once per process — even with thousands
# of cards the programs are tiny compared to recompilation cost.
@lru_cache(maxsize=None)
def _compile_card_oracle(
    name: str,
    primary_type: str,
    oracle_text: str,
    keywords: tuple[str, ...],
) -> OracleProgram:
    normalized_text = _normalize_text(oracle_text)

    if any(keyword in keywords for keyword in UNSUPPORTED_KEYWORDS):
        return OracleProgram(False, "unsupported", "unsupported keyword", normalized_text)

    if any(pattern in normalized_text for pattern in UNSUPPORTED_PATTERNS):
        return OracleProgram(False, "unsupported", "complex oracle pattern", normalized_text)

    if primary_type == "land":
        return OracleProgram(True, "land_mana", "basic land support", normalized_text)

    if primary_type == "creature":
        supported, effect_kind, reason, instructions, activated, triggered, static_lines = _parse_creature_program(oracle_text)
        return OracleProgram(supported, effect_kind, reason, normalized_text, instructions, activated, triggered, static_lines)

    if primary_type in {"artifact", "enchantment", "instant", "sorcery"}:
        if not normalized_text:
            return OracleProgram(True, "permanent_vanilla", "no oracle text", normalized_text)

        instructions: list[OracleInstruction] = []
        primary_instruction, _ = parse_primary_instruction(normalized_text, activated=False)
        if primary_instruction is not None:
            instructions.append(primary_instruction)

        instructions.extend(
            OracleInstruction("spell_pattern", pattern)
            for pattern in SUPPORTED_SPELL_PATTERNS
            if pattern in normalized_text
        )

        # "Choose one —" modal spells: parse each bullet as a selectable mode so
        # the game can resolve the player's chosen mode rather than always the
        # first. Built from the original text to keep human-readable labels.
        modes = parse_modal_options(oracle_text)

        activated_abilities = _parse_noncreature_abilities(oracle_text)
        triggered_abilities = _parse_noncreature_triggered(oracle_text)

        # Only mark as unsupported if all triggered abilities are unsupported
        # and no spell-pattern instructions were already matched (e.g. Howling Mine).
        if triggered_abilities and all(not t.supported for t in triggered_abilities) and not instructions:
            return OracleProgram(False, "unsupported", "unsupported triggered ability", normalized_text)

        if instructions or any(a.supported for a in activated_abilities) or triggered_abilities:
            return OracleProgram(
                True,
                "spell_pattern",
                "pattern-supported effect",
                normalized_text,
                tuple(instructions),
                activated_abilities,
                triggered_abilities,
                modes=modes,
            )

        return OracleProgram(False, "unsupported", "effect not in basic pattern set", normalized_text)

    return OracleProgram(False, "unsupported", "unknown card type", normalized_text)


def compile_card_oracle(card: CardDefinition) -> OracleProgram:
    return _compile_card_oracle(card.name, card.primary_type, card.oracle_text, card.keywords)
