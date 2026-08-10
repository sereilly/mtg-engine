"""Oracle-text compiler.

Turns a card's oracle text into an OracleProgram: a set of instructions,
activated abilities, triggered abilities, and static lines the game engine
can execute. This module owns tokenizing, line classification (keyword /
triggered / activated / static), and the per-card compile cache.

Reading an effect clause is delegated, and `_line_instruction` is where the
three front ends meet, most general first:

1. ``engine/grammar/`` — a real parser over Magic's templating. Whatever it
   claims, it claims for every card printed the same way.
2. ``engine/card_hooks.py``'s ``CARD_LINE_INSTRUCTIONS`` — one printed line of
   one card, for sentences no second card could share. A production for those
   would be a whole-card substring match wearing a grammar hat.
3. ``engine/parsing/`` — the legacy ``@parse_rule`` registry, being deleted.

Precedence follows from that ordering: a line the grammar learns to read stops
reaching its card hook, which is what makes a superseded hook dead rather than
wrong.
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
    _MANA_TOKEN_RE,
    _extract_mana_cost_from_text,
    _instruction,
    _parse_number_token,
)
from .characteristic_defining import dynamic_pt_for
from .auras import unclaimed_aura_lines
from .combat_restrictions import combat_restriction_for
from .lord_buffs import LORD_BUFF_KIND, lord_buff_for, lord_buff_payload
from .static_bonuses import static_bonus_for
from .grammar import ast as grammar_ast, compile_line as compile_grammar_line
from .parsing import parse_modal_options, parse_primary_instruction, parse_static_coeffects
from .parsing.base import activated_kind

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
    "Double strike",
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
    "Desertwalk",
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
    "prevent all combat damage that would be dealt this turn",
    "look at target player's hand",
    "draw a card",
    "add three mana of any one color",
    "at the beginning of your upkeep, sacrifice this enchantment unless you pay",
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
    "target creature gains banding until end of turn",
    "copy target instant or sorcery spell",
    "remove this card from your deck before playing if you're not playing for ante",
    "discard your hand, ante the top card of your library, then draw seven cards",
    "you own target card in the ante. exchange that card with the top card of your library",
    "each player antes the top card of their library",
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
    # First match wins and patterns are unanchored at the end, so a pattern
    # that is a strict prefix of a later pattern's text would shadow it —
    # specific forms must precede their generic prefixes. Guarded by
    # tests/engine/test_trigger_tables.py.
    ("creature_deals_combat_damage",r"whenever this creature deals combat damage to a player"),
    ("creature_deals_damage_to_opponent", r"whenever this creature deals damage to an opponent"),
    ("deals_damage_to_player",      r"whenever .+ deals damage to a player"),
    ("creature_deals_damage",       r"whenever this creature deals damage"),
    ("creature_blocks_or_blocked_by_nonwall", r"whenever this creature blocks or becomes blocked by a non-wall creature"),
    ("creature_attacks_or_blocks",  r"whenever this creature attacks or blocks"),
    ("creature_attacks",            r"whenever this creature attacks"),
    ("creature_blocks",             r"whenever this creature blocks"),
    ("creature_becomes_blocked",    r"whenever this creature becomes blocked"),
    ("creature_dealt_damage",               r"whenever this creature is dealt damage"),
    ("creature_dealt_damage_by_self_dies",  r"whenever a creature dealt damage by this creature this turn dies"),
    ("enchanted_land_tapped",       r"whenever enchanted land becomes tapped"),
    ("self_becomes_tapped",         r"whenever this land becomes tapped"),
    # "Whenever a Forest an opponent controls becomes tapped" (Lifetap). The
    # type and the controller scope are named groups, so the restriction
    # arrives as condition-payload data and one dispatcher
    # (engine/events.py::_becomes_tapped_filter) covers every card written this
    # way. Must follow the two specific forms above, which name their subject
    # ("enchanted land", "this land") rather than quantifying it.
    ("permanent_becomes_tapped",
     r"whenever an? (?P<tapped_subtype>[a-z]+)"
     r"(?: (?P<tapped_controller>an opponent controls|you control))? becomes tapped"),
    # "Whenever a Mountain is tapped for mana" (Gauntlet of Might) narrows the
    # same condition to one land type; the unnarrowed "whenever a player taps a
    # land for mana" (Manabarbs, Mana Flare) follows it.
    ("land_tapped_for_mana",        r"whenever a (?P<tapped_land_subtype>[a-z]+) is tapped for mana"),
    ("land_tapped_for_mana",        r"whenever a player taps a land for mana"),
    # A colour-narrowed cast trigger (the Rod/Cup/Sphere cycle). The colour is
    # captured into the condition payload so one dispatcher covers every card
    # written this way; must precede the unnarrowed form below.
    ("spell_cast",                  r"whenever a player casts a (?P<color_word>white|blue|black|red|green) spell"),
    ("spell_cast",                  r"whenever a player casts a spell"),
    ("opponent_casts_spell",        r"whenever an opponent casts a spell"),
    ("you_cast_spell",              r"whenever you cast a spell"),
    ("enchantment_cast",            r"whenever you cast an enchantment spell"),
    ("creature_enters",             r"whenever a creature enters(?: the battlefield)?"),
    ("land_enters",                 r"whenever a land enters(?: the battlefield)?"),
    ("artifact_enters",             r"whenever an artifact enters(?: the battlefield)?"),
    ("one_or_more_attack",          r"whenever one or more creatures you control attack"),
    ("draws_card",                  r"whenever you draw a card"),
)

# "when" triggers (enter/leave events)
WHEN_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("enters_battlefield",          r"when (?:this|.+) enters(?: the battlefield)?"),
    ("leaves_battlefield",          r"when (?:this|.+) leaves(?: the battlefield)?"),
    ("dies",                        r"when (?:this creature|.+) dies"),
    ("you_gain_life",               r"when you gain life"),
    ("becomes_target",              r"when (?:this|.+) becomes the target"),
    ("no_islands",                  r"when you control no islands"),
    ("no_lands",                    r"when you control no lands"),
)

# "at the beginning of" triggers
AT_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("upkeep_self",         r"at the beginning of your upkeep"),
    ("upkeep_each",         r"at the beginning of each (?:player's )?upkeep"),
    # Deliberately excludes `land`: Cursed Land's upkeep damage is already dealt
    # by the enchant-land upkeep pass in phases/upkeep_step.py. Adding `land`
    # here compiles a *second* trigger and the card deals its damage twice —
    # caught by test_cursed_land_deals_upkeep_damage_to_land_controller.
    ("upkeep_enchanted_controller", r"at the beginning of the upkeep of enchanted (?:creature|artifact|enchantment)'s controller"),
    ("upkeep_chosen",       r"at the beginning of the chosen player's upkeep"),
    ("draw_step_each",      r"at the beginning of each player's draw step"),
    ("end_step",            r"at the beginning of (?:the |each |your )?end(?: step)?"),
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
    # Non-mana additional costs written as prose in the cost clause. Only the
    # clause left of the ":" counts — "Draw a card" as an effect must not be read
    # as a cost.
    cost_lower = cost_part.lower()
    discard_last_drawn = "discard the last card you drew this turn" in cost_lower
    exile_self = bool(re.search(r"\bexile this (artifact|creature|enchantment|permanent|land)\b", cost_lower))
    # "Sacrifice this artifact" (Black Lotus, Bottle of Suleiman). Older
    # printings name the card instead of saying "this artifact", so accept
    # either wording.
    sacrifice_self = bool(
        re.search(r"\bsacrifice this (artifact|creature|enchantment|permanent|land)\b", cost_lower)
    )
    return ActivatedAbilityCost(
        required, requires_tap, discard_last_drawn, exile_self, sacrifice_self
    )


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
            # Named groups become the condition's payload, so a narrowed
            # condition ("…casts a *blue* spell") carries its restriction as
            # data. Event dispatch reads it instead of needing a per-card hook.
            payload = {k: v for k, v in m.groupdict().items() if v is not None}
            return TriggerCondition(
                kind=kind, trigger=trigger_word, raw_text=m.group(0), payload=payload
            )
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


def _parse_triggered_ability(line: str, card_name: str | None = None) -> ParsedTriggeredAbility | None:
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

    instruction, effect_kind = _prefer_line_reading(
        _line_instruction(line, card_name),
        parse_primary_instruction(clean_effect, activated=False),
    )

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
# Grammar front end (strangler fig)
# ---------------------------------------------------------------------------
#
# engine.grammar parses a line into a typed AST and lowers it to instructions.
# It runs on every line, but its result is only *used* when every category it
# lowered to is switched on in engine.grammar.GRAMMAR_CATEGORIES; otherwise the
# legacy @parse_rule registry handles the line exactly as before. That keeps the
# migration continuously shippable: a category is enabled only once the
# differential guard is green for it, and the legacy rules for a category are
# deleted only once the coverage ratchet shows the grammar claims every line
# they used to.

# A grammar category maps to the legacy effect_kind vocabulary so newly
# grammar-supported lines report the same way rule-supported ones always have.
_CATEGORY_EFFECT_KINDS = {"damage": "damage", "pump": "pump", "life": "life"}


def _grammar_instruction(
    line: str,
    card_name: str | None,
    *,
    activated: bool = False,
    spell_line_only: bool = False,
) -> tuple[OracleInstruction, str] | None:
    """The grammar's ``(instruction, effect_kind)`` for one line, or None to
    fall back to the legacy rule registry.

    A multi-instruction lowering is wrapped in a single ``sequence``
    instruction, so composition becomes first-class in the IR without changing
    the one-instruction shape that ParsedActivatedAbility,
    ParsedTriggeredAbility and the stack all currently assume.

    *spell_line_only* restricts the result to plain one-shot effect lines: the
    instructions of a card whose *resolution* carries them out. For an instant
    or sorcery the stack executes the first non-``spell_pattern`` instruction in
    that list, so an activated ability's effect must never enter it — the spell
    would perform the ability on resolution.

    A permanent's list is a mirror rather than a program (see
    ``_noncreature_line_instructions``), so it does hold its abilities' effects,
    exactly as ``_parse_creature_program`` has always done for creatures.
    ``_resolve_card`` puts a permanent onto the battlefield and returns without
    reaching ``_apply_spell_text``, which is the only caller that executes this
    list — so the mirror cannot fire on cast.
    """
    compiled = compile_grammar_line(line, card_name=card_name)
    if not compiled.usable:
        return None
    if spell_line_only and not isinstance(compiled.node, grammar_ast.SpellEffectLine):
        return None

    instructions = compiled.instructions
    instruction = (
        instructions[0] if len(instructions) == 1
        else OracleInstruction("sequence", "", {"steps": instructions})
    )
    category = next(iter(sorted(compiled.categories)), "effect")
    effect_kind = activated_kind(activated, _CATEGORY_EFFECT_KINDS.get(category, category))
    return instruction, effect_kind


def _card_hook_instruction(
    line: str,
    card_name: str | None,
    *,
    spell_line_only: bool = False,
) -> tuple[OracleInstruction, str] | None:
    """The name-keyed reading of one line, for texts that are a single card.

    The third front end, consulted only where the grammar declined. Most of what
    ``engine/parsing/`` claimed is templating and belongs in a production; the
    rest is one card's sentence bound to a handler written for it, and those
    move to ``engine/card_hooks.py`` — the one file whose subject is a card's
    name (see CARD_LINE_INSTRUCTIONS for the entry bar).

    Kept out of :func:`_grammar_instruction` on purpose. That function is what
    ``tests/engine/test_grammar_fallback_safety.py`` stubs to compile the pool
    without the grammar; folding the hooks into it would stub those too and the
    guard would report every hooked card as a loss.
    """
    from .card_hooks import card_line_instruction

    found = card_line_instruction(card_name, normalize_creature_line(line))
    if found is None:
        return None
    if spell_line_only and _is_ability_line(line):
        return None
    return found.instruction, found.effect_kind


def _is_ability_line(line: str) -> bool:
    """Whether *line* is an activated or triggered ability rather than a plain
    effect the card's resolution carries out.

    The same question ``spell_line_only`` asks of the grammar's node type, asked
    of the raw text — an ability's effect must never enter an instant's or
    sorcery's instruction list, or the spell would perform the ability when it
    resolves.
    """
    normalized = normalize_creature_line(line)
    if ":" in normalized:
        return True
    return _parse_trigger_condition(normalized)[0] is not None


def _line_instruction(
    line: str,
    card_name: str | None,
    *,
    activated: bool = False,
    spell_line_only: bool = False,
) -> tuple[OracleInstruction, str] | None:
    """The front ends that read one line, most general first: the grammar, then
    the name-keyed card hooks."""
    found = _grammar_instruction(
        line, card_name, activated=activated, spell_line_only=spell_line_only
    )
    if found is not None:
        return found
    return _card_hook_instruction(line, card_name, spell_line_only=spell_line_only)


def _prefer_line_reading(
    reading: tuple[OracleInstruction, str] | None,
    legacy: tuple[OracleInstruction | None, str],
) -> tuple[OracleInstruction | None, str]:
    """Take the per-line reading's instruction when there is one, but keep the
    legacy ``effect_kind`` label where the legacy rules also matched.

    *reading* is what :func:`_line_instruction` produced — the grammar's, or the
    card hooks'. The label feeds reporting (``SimulationResult``, the support
    report) rather than dispatch, so holding it steady keeps the migration's
    diff to the thing that actually matters — the instruction.
    """
    legacy_instruction, legacy_kind = legacy
    if reading is None:
        return legacy_instruction, legacy_kind
    instruction, reading_kind = reading
    return instruction, (legacy_kind if legacy_instruction is not None else reading_kind)


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


def _parse_activated_ability(line: str, card_name: str | None = None) -> ParsedActivatedAbility | None:
    normalized = normalize_creature_line(line)
    if ":" not in normalized:
        return None

    effect_text = normalized.split(":", 1)[1].strip()
    instruction, effect_kind = _prefer_line_reading(
        _line_instruction(line, card_name, activated=True),
        parse_primary_instruction(effect_text, activated=True),
    )
    supported = instruction is not None
    return ParsedActivatedAbility(
        source_line=line,
        normalized_effect=effect_text,
        supported=supported,
        cost=parse_activated_ability_cost(line),
        effect_kind=effect_kind,
        instruction=instruction,
    )


# "This creature doesn't untap during your untap step." — the behavior is
# already enforced directly in phases/untap_step.py's text scan; this only
# needs to be recognized as a supported static line so the whole creature
# doesn't classify as unsupported.
_DOESNT_UNTAP_LINE = "this creature doesn't untap during your untap step"


def _is_supported_static_creature_line(line: str) -> bool:
    normalized = normalize_creature_line(line)
    if normalized.startswith("protection from "):
        return True
    if static_bonus_for(normalized) is not None:
        return True
    if normalized == _DOESNT_UNTAP_LINE:
        return True
    if dynamic_pt_for(normalized) is not None:
        return True
    # The gate and the dispatch must read the SAME table. The literals below are
    # matched by `startswith`, while `combat_restriction_for`'s patterns are
    # anchored — so a line like "this creature can't block creatures with
    # flying" was gated in by the prefix "this creature can't block", then
    # matched no anchored pattern and fell through to a bare `static_line`:
    # supported, with the restriction silently absent. Deriving the gate from
    # the dispatch table means an unrecognized rider is now reported unsupported
    # (loud) instead.
    if combat_restriction_for(normalized) is not None:
        return True
    # A lord's continuous buff to other creatures. The gate used to admit the
    # bare prefix "other ", which is a template in disguise: "Other Goblins
    # glimmer uncontrollably." compiled as supported and did nothing. It asks
    # the derivation table the consumer dispatches on, so an unimplemented
    # keyword, an unrecognized granted ability or an unmodelled condition is now
    # reported unsupported rather than admitted and dropped.
    if lord_buff_for(normalized) is not None:
        return True
    # "As this creature enters, it becomes your choice of <body>, …"
    # (Primal Clay). Carried out by _initialize_permanent_state, which reads the
    # bodies from this same parser — so what is claimed here and what is applied
    # cannot describe different cards.
    from .enter_effects import choosable_bodies

    if choosable_bodies(normalized):
        return True
    static_patterns = (
        "this creature enters with seven +1/+0 counters on it",
        "this creature enters with x +1/+1 counters on it",
        "this creature enters tapped",
        "at end of combat, if this creature attacked or blocked this combat, remove a +1/+0 counter from it",
        "for each 1 damage that would be dealt to this creature, if it has a +1/+1 counter on it, remove a +1/+1 counter from it and prevent that 1 damage",
        # "can't attack", "can't block", "can't attack unless defending player
        # controls a <type>", "attacks each combat if able" and "can't be
        # blocked by walls" are gated above by combat_restriction_for, whose
        # patterns are anchored. Listing them here too would restore the prefix
        # hole those anchors close.
        # "other " is deliberately NOT here. It was the whole support test for a
        # lord line — a prefix admitting any sentence that began with the word —
        # and it is now `lord_buff_for` above, which claims the sentence end to
        # end or not at all.
        "this creature can block an additional creature each combat",
        "as long as this creature is untapped, all damage that would be dealt to you by unblocked creatures is dealt to this creature instead",
        "remove a corpse counter from this creature: regenerate this creature",
        "you may have this creature enter as a copy of any creature on the battlefield",
        # Desert Nomads / Camel: static shield against Desert lands' damage
        # ability. Handled by a replacement-effect interceptor (checked
        # against oracle text directly) rather than a compiled instruction —
        # see engine/replacements.py:_prevent_desert_damage, which also
        # covers Camel's clause extending the shield to creatures banded
        # with it.
        "prevent all damage that would be dealt to this creature by deserts",
        "as long as this creature is attacking, prevent all damage deserts would deal to this creature",
        # Ali from Cairo: a life-total-floor replacement effect (CR 614),
        # handled by engine/replacements.py:_floor_life_at_one against oracle
        # text directly rather than a compiled instruction.
        "damage that would reduce your life total to less than 1 reduces it to 1 instead",
        # Guardian Beast: static artifact protection (can't-be-enchanted,
        # indestructible, can't-gain-control) while untapped. Checked by
        # mixins/effects.py:_untapped_artifact_protector_active at each
        # relevant site rather than a compiled instruction.
        "as long as this creature is untapped, noncreature artifacts you control can't be enchanted, "
        "they have indestructible, and other players can't gain control of them",
        # Old Man of the Sea: a pure player option with no forced game-state
        # consequence if unused (the untap step already defaults to
        # untapping); its actual gameplay hook is the linked-duration control
        # ability, which cares about the CURRENT tapped state, not this line.
        "you may choose not to untap this creature during your untap step",
    )
    return any(normalized.startswith(pattern) for pattern in static_patterns)


# ---------------------------------------------------------------------------
# Creature program parser
# ---------------------------------------------------------------------------

def _parse_creature_program(
    oracle_text: str,
    card_name: str | None = None,
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
        trig = _parse_triggered_ability(line, card_name)
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
        ability = _parse_activated_ability(line, card_name)
        if ability is not None and ability.supported:
            activated.append(ability)
            if ability.instruction is not None:
                instructions.append(ability.instruction)
            continue

        # 4. Static text
        if _is_supported_static_creature_line(line):
            normalized = normalize_creature_line(line)
            # Characteristic-defining P/T (CR 604.3). One instruction kind
            # carrying what to count: these were four branches matching literals
            # that embedded the card's own name, so a reprint or any
            # functionally identical card compiled as unsupported.
            if (dynamic_pt := dynamic_pt_for(normalized)) is not None:
                instructions.append(
                    OracleInstruction(dynamic_pt.kind, "", dynamic_pt.payload)
                )
            elif (bonus := static_bonus_for(normalized)) is not None:
                instructions.append(OracleInstruction(bonus.kind, "", bonus.payload))
            elif (lord := lord_buff_for(normalized)) is not None:
                # The lord line the gate just admitted, carried as data. The
                # consumer used to re-parse `static_line`'s text with two
                # regexes of its own, which is how the gate and the dispatch came
                # to disagree about what "other " meant.
                instructions.append(
                    OracleInstruction(LORD_BUFF_KIND, "", lord_buff_payload(lord))
                )
            elif (restriction := combat_restriction_for(normalized)) is not None:
                # Combat restrictions are templates, derived rather than listed
                # (engine/combat_restrictions.py). The chain that used to sit
                # here matched exact strings and hardcoded Island, so a card
                # naming any other land type fell through to `static_line` and
                # attacked freely while still reporting supported.
                instructions.append(
                    OracleInstruction(restriction.kind, "", restriction.payload)
                )
            else:
                instructions.append(OracleInstruction("static_line", normalized))
            static_lines.append(normalized)
            continue

        # Name the offending line so support_report on a new set pinpoints
        # exactly which clause needs a parse rule.
        return False, "unsupported", f"creature text too complex: {line!r}", (), (), (), ()

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


def _parse_noncreature_abilities(
    oracle_text: str, card_name: str | None = None
) -> tuple[ParsedActivatedAbility, ...]:
    abilities: list[ParsedActivatedAbility] = []
    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        ability = _parse_activated_ability(line, card_name)
        if ability is not None:
            abilities.append(ability)
    return tuple(abilities)


def _parse_noncreature_triggered(
    oracle_text: str, card_name: str | None = None
) -> tuple[ParsedTriggeredAbility, ...]:
    """Extract triggered abilities from non-creature oracle text."""
    abilities: list[ParsedTriggeredAbility] = []
    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        trig = _parse_triggered_ability(line, card_name)
        if trig is not None:
            abilities.append(trig)
    return tuple(abilities)


def _by_source_line(abilities) -> dict[str, list]:
    """Parsed abilities grouped by the line they came from, in printed order.

    A list per line rather than one entry: a card may print the same line twice,
    and the assembly below consumes them in order so the second occurrence is
    not silently the first one again.
    """
    grouped: dict[str, list] = {}
    for ability in abilities:
        grouped.setdefault(ability.source_line, []).append(ability)
    return grouped


def _noncreature_line_instructions(
    oracle_text: str,
    card_name: str | None,
    activated: tuple[ParsedActivatedAbility, ...],
    triggered: tuple[ParsedTriggeredAbility, ...],
    *,
    whole_card: bool,
) -> list[OracleInstruction]:
    """The card-level instruction each line of a noncreature card contributes,
    in printed order.

    Assembled from the reading the compiler has *already* produced for that
    line. The legacy fallback in the caller collapses the card's entire text to
    one string and keeps the first rule that matches it, so an artifact whose
    activated ability the grammar reads in full still had its card-level
    instruction produced by re-reading the whole card — two front ends answering
    the same question about the same line, and only one of them per line.

    Reusing the ability parse rather than re-running the grammar is what keeps
    the fallback *per line*: those parses already try the grammar first and drop
    to the legacy rules only for the clause the grammar refused, so a production
    claiming one line cannot delete the reading of any other.

    *whole_card* tells the list's two meanings apart. For an instant or sorcery
    it is the program that *resolves* — the stack executes the first
    non-``spell_pattern`` instruction — so only plain effect lines belong in it.
    For a permanent it is a mirror of everything the card does, scanned by kind
    by the layer bridge, the upkeep pass and the AI: the same mirror
    ``_parse_creature_program`` has always built for creatures, and which
    ``engine/ai_valuation.py``'s ``SPELL_TYPES`` gate already documents. A
    permanent's abilities keep their own entries in ``activated_abilities`` and
    ``triggered_abilities``; nothing resolves this list on its own.
    """
    acts = _by_source_line(activated) if whole_card else {}
    trigs = _by_source_line(triggered) if whole_card else {}

    instructions: list[OracleInstruction] = []
    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        # Modal bullets are alternatives collected into `modes`, not effects the
        # card performs. Letting one into the top-level list would make a
        # "Choose one" spell always resolve whichever bullet was claimed.
        if not line or line.startswith("•"):
            continue

        found = _line_instruction(line, card_name, spell_line_only=True)
        if found is not None:
            instructions.append(found[0])
            continue
        if not whole_card:
            continue

        # An ability line: take the instruction its own parse produced.
        ability = None
        for group in (trigs, acts):
            pending = group.get(line)
            if pending:
                ability = pending.pop(0)
                break
        if ability is not None:
            if ability.supported and ability.instruction is not None:
                instructions.append(ability.instruction)
            continue

        # Neither — a static ability ("Black creatures get +1/+1."), or a
        # triggered one whose condition the legacy trigger table refuses
        # (Cursed Land). Its instruction used to arrive from the whole-text
        # parse or from parse_static_coeffects re-reading the card.
        static = _line_instruction(line, card_name)
        if static is not None:
            instructions.append(static[0])
    return instructions


# ---------------------------------------------------------------------------
# Top-level compiler
# ---------------------------------------------------------------------------

# A modal ACTIVATED ability ("{2}: Choose one —" followed by bullet lines,
# e.g. Pyramids). Expanded into one plain activated-ability line per bullet
# (same cost) so the existing multi-ability machinery (ability_index choice,
# per-ability targeting) covers it — and so the bullets are never mistaken
# for cast-time modes or top-level spell effects.
_MODAL_ABILITY_HEAD_RE = re.compile(r"^((?:\{[^}]+\}[,\s]*)+):\s*choose one\s*[—\-–]?\s*$", re.IGNORECASE)


def expand_modal_activated_lines(oracle_text: str) -> str:
    """Rewrite '{cost}: Choose one —' + bullets into one ability line per
    bullet. Text without that shape is returned unchanged. Shared with
    engine.legality so target classification sees the same lines."""
    if "choose one" not in (oracle_text or "").lower():
        return oracle_text
    lines = (oracle_text or "").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        head = _MODAL_ABILITY_HEAD_RE.match(lines[i].strip())
        if head is not None:
            cost = head.group(1).strip()
            j = i + 1
            bullets: list[str] = []
            while j < len(lines) and lines[j].strip().startswith("•"):
                bullets.append(lines[j].strip().lstrip("•").strip())
                j += 1
            if bullets:
                out.extend(f"{cost}: {bullet}" for bullet in bullets)
                i = j
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)

# Layouts the compiler can read straight from the top-level characteristics.
# Every other layout (split, flip, transform, modal_dfc, adventure, meld, …)
# leaves mana_cost and oracle_text empty and puts the real text in card_faces,
# so compiling one as-is would classify it a supported vanilla — a silently
# wrong answer rather than an error. Face-aware compilation is roadmap phase 3;
# until then these are explicitly unsupported.
SUPPORTED_LAYOUTS = frozenset({
    "normal", "leveler", "class", "saga", "case", "planar", "scheme", "vanguard", "token",
})


# ---------------------------------------------------------------------------
# Support derived from the text-keyed rule tables
# ---------------------------------------------------------------------------

def _derived_static_claims(oracle_text: str, normalized_text: str) -> list[str]:
    """Names of the rule tables that already implement this card's text.

    These tables (untap_restrictions, draw_step_modifiers, cost_modifiers,
    enter_effects) read a permanent's oracle text directly at the step that
    needs them, so they need no instruction to *work*. They were nonetheless
    absent from the support gate, which listed the same behaviours as whitelist
    literals with the table's parameters baked in — "creatures with power **3**
    or greater don't untap", "players can't untap more than **one** creature".

    That is the false-negative half of the gate/dispatch split: a card printed
    "power 4 or greater" was enforced correctly by the table and reported
    **unsupported**, because the literal named a different number. Deriving
    support from the tables that do the work means the parameter is data here
    too.
    """
    from .cost_modifiers import cost_modifier_claims_line
    from .draw_step_modifiers import draw_step_bonus_for
    from .enter_effects import enter_effect_line
    from .global_statics import global_static_for
    from .land_play_allowance import land_play_allowance_for
    from .untap_restrictions import untap_restriction_for

    claims: list[str] = []
    if untap_restriction_for(oracle_text) is not None:
        claims.append("untap_restrictions")
    # Extra land plays (Fastbond). The land-drop path derives the allowance from
    # the permanent's own text, so the gate has to ask the same table — a
    # wording the table cannot read must make the card unsupported rather than
    # supported-with-the-permission-missing, which is what the name-keyed count
    # this replaced produced.
    if land_play_allowance_for(oracle_text) is not None:
        claims.append("land_play_allowance")
    # A board-wide static (Titania's Song, Energy Flux) contributes its effects
    # through the CR 613 layer bridge and, for a granted ability, through the
    # affected permanent's effective card — so there is no instruction to
    # produce, and without this the source card would report unsupported while
    # working perfectly.
    if global_static_for(oracle_text) is not None:
        claims.append("global_statics")
    if draw_step_bonus_for(oracle_text) is not None:
        claims.append("draw_step_modifiers")
    if any(
        cost_modifier_claims_line(normalize_creature_line(line))
        for line in oracle_text.splitlines()
    ):
        claims.append("cost_modifiers")
    # The whole entry-state registry, not two of its constants: every phrase in
    # engine/enter_effects.py is implemented by _initialize_permanent_state, so
    # naming a subset here is the same partial-list mistake one level down.
    if any(enter_effect_line(line) for line in oracle_text.splitlines()):
        claims.append("enter_effects")
    return claims


def _effect_handler_kinds() -> frozenset[str]:
    """Instruction kinds with a registered handler.

    Imported lazily and cached: ``engine.handlers`` imports the compiler, so a
    module-level import here would be a cycle.
    """
    global _EFFECT_HANDLER_KINDS
    if _EFFECT_HANDLER_KINDS is None:
        from .handlers import EFFECT_HANDLERS

        _EFFECT_HANDLER_KINDS = frozenset(EFFECT_HANDLERS)
    return _EFFECT_HANDLER_KINDS


_EFFECT_HANDLER_KINDS: frozenset[str] | None = None


# Unbounded cache: card definitions are immutable and the pool is finite, so
# every distinct card compiles exactly once per process — even with thousands
# of cards the programs are tiny compared to recompilation cost.
@lru_cache(maxsize=None)
def _compile_card_oracle(
    name: str,
    primary_type: str,
    oracle_text: str,
    keywords: tuple[str, ...],
    layout: str = "normal",
) -> OracleProgram:
    # Pyramids-style "{cost}: Choose one —" + bullets become one activated
    # ability per bullet before any other classification runs.
    oracle_text = expand_modal_activated_lines(oracle_text)
    normalized_text = _normalize_text(oracle_text)

    if layout not in SUPPORTED_LAYOUTS:
        return OracleProgram(
            False, "unsupported", f"unsupported card layout: {layout}", normalized_text
        )

    if any(keyword in keywords for keyword in UNSUPPORTED_KEYWORDS):
        return OracleProgram(False, "unsupported", "unsupported keyword", normalized_text)

    if any(pattern in normalized_text for pattern in UNSUPPORTED_PATTERNS):
        return OracleProgram(False, "unsupported", "complex oracle pattern", normalized_text)

    if primary_type == "land":
        # Mana production is driven by CardDefinition.produced_mana, not by
        # parsing oracle text (basic lands' whole ability line is reminder
        # text in parens, e.g. "({T}: Add {W}.)", which normalize_creature_line
        # strips to nothing). A land is therefore ALWAYS at least playable —
        # unlike creatures/artifacts, an unparsed bonus ability degrades just
        # that ability, never the land's own castability. Non-reminder-text
        # ability lines (Desert's damage ping, Bazaar of Baghdad's draw-
        # discard, …) are parsed the same way artifacts' are, so lands with
        # abilities beyond mana become activatable too.
        activated_abilities = _parse_noncreature_abilities(oracle_text, name)
        triggered_abilities = _parse_noncreature_triggered(oracle_text, name)
        return OracleProgram(
            True, "land_mana", "basic land support", normalized_text,
            activated_abilities=activated_abilities,
            triggered_abilities=triggered_abilities,
        )

    if primary_type == "creature":
        supported, effect_kind, reason, instructions, activated, triggered, static_lines = _parse_creature_program(oracle_text, name)
        return OracleProgram(supported, effect_kind, reason, normalized_text, instructions, activated, triggered, static_lines)

    if primary_type in {"artifact", "enchantment", "instant", "sorcery"}:
        if not normalized_text:
            return OracleProgram(True, "permanent_vanilla", "no oracle text", normalized_text)

        activated_abilities = _parse_noncreature_abilities(oracle_text, name)
        triggered_abilities = _parse_noncreature_triggered(oracle_text, name)

        # Line by line. The legacy path below collapses the card's whole text to
        # one string and keeps only the first rule that matches it, so a second
        # sentence ("Draw a card. Each player discards a card.") was silently
        # dropped, and an artifact whose activated ability the grammar reads in
        # full still had its card-level instruction produced by re-reading the
        # card end to end.
        instructions: list[OracleInstruction] = _noncreature_line_instructions(
            oracle_text,
            name,
            activated_abilities,
            triggered_abilities,
            whole_card=primary_type in {"artifact", "enchantment"},
        )
        if not instructions:
            primary_instruction, _ = parse_primary_instruction(normalized_text, activated=False)
            if primary_instruction is not None:
                instructions.append(primary_instruction)

        # Static continuous co-effects (e.g. Conversion's "All Mountains are
        # Plains.") that follow a primary clause already claimed above and that
        # no line above claimed for itself.
        for coeffect in parse_static_coeffects(normalized_text):
            if coeffect.kind not in {i.kind for i in instructions}:
                instructions.append(coeffect)

        # An Aura used to be classified supported by the single whitelist
        # substring "enchant creature", with nothing ever looking past the
        # enchant clause — so an Aura whose effect the engine does not
        # implement, or one with no effect line at all, entered play and did
        # nothing while reporting support. Every effect line must be claimed
        # (engine/auras.py) or the card is unsupported, with the offending line
        # named.
        aura_lines = [normalize_creature_line(line) for line in oracle_text.split("\n")]
        if any(line.startswith("enchant ") for line in aura_lines):
            unclaimed = unclaimed_aura_lines(aura_lines, name)
            if unclaimed:
                return OracleProgram(
                    False,
                    "unsupported",
                    f"unimplemented aura effect: {unclaimed[0]}",
                    normalized_text,
                )

        instructions.extend(
            OracleInstruction("derived_static_rule", claim)
            for claim in _derived_static_claims(oracle_text, normalized_text)
        )

        instructions.extend(
            OracleInstruction("spell_pattern", pattern)
            for pattern in SUPPORTED_SPELL_PATTERNS
            if pattern in normalized_text
        )

        # "Choose one —" modal spells: parse each bullet as a selectable mode so
        # the game can resolve the player's chosen mode rather than always the
        # first. Built from the original text to keep human-readable labels.
        modes = parse_modal_options(oracle_text)

        # Only mark as unsupported if all triggered abilities are unsupported
        # and no spell-pattern instructions were already matched (e.g. Howling Mine).
        if triggered_abilities and all(not t.supported for t in triggered_abilities) and not instructions:
            return OracleProgram(False, "unsupported", "unsupported triggered ability", normalized_text)

        # A one-shot spell that resolves through no handler does nothing when
        # cast. `spell_pattern` is a marker recording that a whitelist substring
        # matched; it carries no behaviour, so a spell whose every instruction
        # is one is supported on the strength of a string comparison. Shahrazad
        # shipped that way, and ingesting Revised produced two more
        # (Shatterstorm, Crumble) on first contact.
        #
        # tests/engine/test_no_hollow_support.py asserted this as a property of
        # the pool; making it the compiler's own contract is what stops the next
        # set introducing another. Permanents are excluded for the same reason
        # that guard excludes them: they legitimately work through statics,
        # auras, layers and the text-keyed step tables.
        if (
            primary_type in ("instant", "sorcery")
            and instructions
            and not modes
            and not any(instruction.kind in _effect_handler_kinds() for instruction in instructions)
            and not any(a.supported for a in activated_abilities)
            and not triggered_abilities
        ):
            return OracleProgram(
                False,
                "unsupported",
                "no handler implements this spell's effect",
                normalized_text,
            )

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
    return _compile_card_oracle(
        card.name, card.primary_type, card.oracle_text, card.keywords, card.layout
    )
