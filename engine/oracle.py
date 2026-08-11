"""Oracle-text compiler.

Turns a card's oracle text into an OracleProgram: a set of instructions,
activated abilities, triggered abilities, and static lines the game engine
can execute. This module owns tokenizing, line classification (keyword /
triggered / activated / static), and the per-card compile cache.

Reading an effect clause is delegated, and `_line_instruction` is where the
two front ends meet, most general first:

1. ``engine/grammar/`` — a real parser over Magic's templating. Whatever it
   claims, it claims for every card printed the same way.
2. ``engine/card_hooks.py``'s ``CARD_LINE_INSTRUCTIONS`` — one printed line of
   one card, for sentences no second card could share. A production for those
   would be a whole-card substring match wearing a grammar hat.

Precedence follows from that ordering: a line the grammar learns to read stops
reaching its card hook, which is what makes a superseded hook dead rather than
wrong.

There is no third. ``engine/parsing/``'s ``@parse_rule`` registry — a flat table
of substring predicates, hand-ordered against one another, which claimed a
clause on a prefix and dropped whatever followed — is deleted. A line no front
end reads now produces no instruction, which is the loud failure the invariant
asks for: the card is reported unsupported and names the clause.
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
)
from .characteristic_defining import dynamic_pt_for
from .auras import unclaimed_aura_lines
from .combat_restrictions import combat_restriction_for
from .effect_labels import activated_label, triggered_label
from .lord_buffs import LORD_BUFF_KIND, lord_buff_for, lord_buff_payload
from .static_bonuses import static_bonus_for
from .grammar import ast as grammar_ast, compile_line as compile_grammar_line
from .grammar.vocabulary import IMPLEMENTED_KEYWORDS

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


# The keyword registry lives in `engine/grammar/vocabulary.py` and this module
# reads it. It used to be spelled out here as well — seventeen Title Case
# strings beside seventeen lowercase ones, held equal by hand, compared by
# nothing. The two gate different halves of the same question (this one admits a
# printed keyword *line*; the grammar's refuses to *lower* an unimplemented
# keyword), so a keyword added to one and not the other produces a card that is
# either admitted and inert or refused for a behaviour that exists — and a new
# set is a keyword-adding event by definition.
#
# This is the rule the comment on `_is_supported_static_creature_line` already
# states for lord buffs and combat restrictions: the gate and the dispatch must
# read the SAME table. Held by `tests/engine/test_keyword_registry.py`, which
# checks the gate's *behaviour* against the registry rather than comparing two
# lists — comparing them is something a future second copy would also pass.
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
    # A colour-list narrowing ("…a spell that's white, blue, black, or red",
    # Quirion Dryad). The list is condition payload, read by the you_cast_spell
    # event filter; must precede its unnarrowed prefix below.
    ("you_cast_spell",
     r"whenever you cast a spell that's (?P<cast_colors>[a-z]+(?:, [a-z]+)*,? or [a-z]+)"),
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
    # "…of combat on your turn" narrows the bare form to the active player's
    # combat (Adherent of Hope); must precede its own prefix below.
    ("combat_your_turn",    r"at the beginning of combat on your turn"),
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

    # Extract any trailing "if ..." guard on the effect. The clause it strips is
    # no longer read on its own: the front ends take the whole line, so the
    # guard's only job now is the payload key attached below.
    if_kind, _clean_effect = _extract_if_condition(remainder)

    instruction, effect_kind = _reading(
        _line_instruction(line, card_name, condition_kind=condition.kind)
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
# Grammar front end
# ---------------------------------------------------------------------------
#
# engine.grammar parses a line into a typed AST and lowers it to instructions.
# It runs on every line, and its result is used when every category it lowered
# to is switched on in engine.grammar.GRAMMAR_CATEGORIES. A line it refuses now
# reaches the name-keyed card hooks and then nothing — there is no legacy
# registry left underneath, so a category switched off is a card reported
# unsupported rather than a card quietly read by something else.


def _grammar_instruction(
    line: str,
    card_name: str | None,
    *,
    activated: bool = False,
    condition_kind: str | None = None,
    spell_line_only: bool = False,
) -> tuple[OracleInstruction, str] | None:
    """The grammar's ``(instruction, effect_kind)`` for one line, or None when
    the grammar does not claim it.

    *activated* and *condition_kind* name the **position** the line occupies —
    an ability's clause, a trigger's remainder (whose condition they carry), or
    a plain effect line. They decide only the ``effect_kind`` label
    (``engine/effect_labels.py``), never the instruction.

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
    if isinstance(compiled.node, grammar_ast.DerivedLine):
        # A derivation table's board-wide static is a *co-effect*, collected by
        # _grammar_static_coeffects after the per-line pass rather than here.
        # See that function for why the position matters.
        return None
    if spell_line_only and not isinstance(compiled.node, grammar_ast.SpellEffectLine):
        return None

    instructions = compiled.instructions
    instruction = (
        instructions[0] if len(instructions) == 1
        else OracleInstruction("sequence", "", {"steps": instructions})
    )
    category = next(iter(sorted(compiled.categories)), "effect")
    if condition_kind is not None:
        effect_kind = triggered_label(instruction.kind, condition_kind)
    elif activated:
        effect_kind = activated_label(instruction.kind, category)
    else:
        effect_kind = "spell_pattern"
    return instruction, effect_kind


def _grammar_static_coeffects(
    oracle_text: str, card_name: str | None
) -> tuple[OracleInstruction, ...]:
    """Board-wide continuous statics a derivation table reads off one line.

    Kormus Bell's "All Swamps are 1/1 black creatures that are still lands.",
    Conversion's "All Mountains are Plains.", Jihad's conditional anthem — each
    derived in full by an engine table (``engine/grammar/derived.py`` names
    them) and each a *co-effect*: it coexists with whatever else the card says
    rather than being the effect the card's resolution carries out.

    Collected after the per-line pass, for the reason the deleted
    ``parse_static_coeffects`` also was: a card can state one of these alongside
    a clause that already claimed the card's instruction (Conversion's upkeep
    cost, Jihad's enter-choice and sacrifice trigger). Claiming it as an
    ordinary line instruction would *suppress* the reading of those other
    sentences, which is a different program, not a better one.
    """
    coeffects: list[OracleInstruction] = []
    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        compiled = compile_grammar_line(line, card_name=card_name)
        if compiled.usable and isinstance(compiled.node, grammar_ast.DerivedLine):
            coeffects.extend(compiled.instructions)
    return tuple(coeffects)


def _card_hook_instruction(
    line: str,
    card_name: str | None,
    *,
    spell_line_only: bool = False,
) -> tuple[OracleInstruction, str] | None:
    """The name-keyed reading of one line, for texts that are a single card.

    The second front end, consulted only where the grammar declined. Most of
    what ``engine/parsing/`` claimed is templating and belongs in a production;
    the rest is one card's sentence bound to a handler written for it, and those
    live in ``engine/card_hooks.py`` — the one file whose subject is a card's
    name (see CARD_LINE_INSTRUCTIONS for the entry bar).

    Kept out of :func:`_grammar_instruction` on purpose, so that stubbing the
    grammar (``tests/engine/test_front_end_safety.py``) leaves the hooks
    standing; folding them in would stub those too and the guard would report
    every hooked card as a loss.

    A hook carries its own ``effect_kind``, so it never consults
    ``engine/effect_labels.py`` and the position flags do not reach it.
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
    condition_kind: str | None = None,
    spell_line_only: bool = False,
) -> tuple[OracleInstruction, str] | None:
    """The front ends that read one line, most general first: the grammar, then
    the name-keyed card hooks. There is no third — a line neither claims has no
    instruction, and the card is reported unsupported naming the clause."""
    found = _grammar_instruction(
        line, card_name,
        activated=activated, condition_kind=condition_kind,
        spell_line_only=spell_line_only,
    )
    if found is not None:
        return found
    return _card_hook_instruction(line, card_name, spell_line_only=spell_line_only)


def _reading(
    found: tuple[OracleInstruction, str] | None,
) -> tuple[OracleInstruction | None, str]:
    """A front end's reading, widened to the ``(instruction | None, label)`` shape
    the ability parsers return.

    This was ``_prefer_line_reading``, which took a *second* argument — the
    legacy registry's reading of the same line — and used it for two things: the
    instruction when no front end claimed the line, and the ``effect_kind``
    label whenever a legacy rule matched, even where the grammar had already
    produced the instruction. The first is gone with the registry; the second is
    ``engine/effect_labels.py``.
    """
    if found is None:
        return None, "unsupported"
    return found


def _modal_head(line: str, wrapper: type) -> "grammar_ast.ModalNode | None":
    """The modal head *line* is, read through the grammar — or None.

    *wrapper* is the ability-line node the head has to sit inside, and it is
    what tells a spell's mode list apart from an activated ability's:
    ``SpellEffectLine`` for the bare "Choose one —" a spell announces on the
    stack (CR 601.2b), ``ActivatedAbilityNode`` for the "{2}: Choose one —"
    :func:`expand_modal_activated_lines` rewrites. A head behind a *trigger*
    matches neither and is claimed by nothing here, which is right: its modes
    are chosen when the ability goes on the stack (CR 700.2b), not when the card
    is cast.

    **One reader.** Two substring matchers used to answer this — ``choose
    one\\b`` anywhere in the card's text for a spell, a mana-symbols-then-``choose
    one`` regex per line for an ability — and between them they got the count
    wrong (``choose one`` matches inside "Choose one **or more**", so Sublime
    Epiphany read as a one-mode spell), missed every count but one, and asked
    the question of the whole card rather than of a line. The grammar parses the
    count and the lowering refuses what the engine cannot carry out, so a head
    it declines is one this must not act on either — which is exactly what
    checking ``lowering_error`` says.
    """
    compiled = compile_grammar_line(line)
    if compiled.lowering_error is not None:
        return None
    node = compiled.node
    if not isinstance(node, wrapper):
        return None
    statement = getattr(node, "statement", None)
    return statement if isinstance(statement, grammar_ast.ModalNode) else None


def _mode_reading(label: str, card_name: str | None) -> tuple[OracleInstruction, str] | None:
    """A modal bullet's ``(instruction, effect_kind)``, or None.

    ``effect_kind`` is "spell_pattern" for every bullet the front ends claim,
    not the grammar's category label. A mode is one alternative of a spell, and
    the label is what ``SimulationResult`` and the support report bucket the
    *card* by — so it names the reading's shape, exactly as it did when the
    legacy registry produced it.
    """
    found = _line_instruction(label, card_name)
    if found is None:
        return None
    return found[0], "spell_pattern"


def _bullets_after(lines: list[str], index: int) -> list[str]:
    """The run of bulleted lines immediately below *index* — a head's modes.

    Stops at the first line that is not a bullet, which is what makes this
    *grouping* rather than a scan: the old version partitioned the card's whole
    text at the first "•" and split the remainder, so a bullet list anywhere on
    the card belonged to any "choose one" anywhere else on it.

    Fewer than two is not a mode list. CR 700.2 defines a modal spell as having
    "two or more options in a bulleted list", so a lone bullet under a head is
    text this does not understand, and returning it as a one-mode spell would be
    a guess wearing the shape of a reading.
    """
    bullets: list[str] = []
    for raw in lines[index + 1:]:
        line = raw.strip()
        if not line.startswith("•"):
            break
        bullets.append(_WHITESPACE_RE.sub(" ", line.lstrip("•").strip()).strip())
    return bullets if len(bullets) >= 2 else []


def _modal_options(oracle_text: str, card_name: str | None) -> tuple[ModalOption, ...]:
    """The bullets of a "Choose one —" spell, one :class:`ModalOption` each.

    Grouping a head with the bullets below it is line classification, which is
    this module's job; *reading* each of those lines is the grammar's, on both
    halves — the head through :func:`_modal_head`, each bullet's effect through
    the same front ends an ordinary line goes to (:func:`_line_instruction`). A
    mode is supported exactly when its own clause is, which is why a card with
    one readable mode and one unreadable one still resolves the readable one.

    Modal **activated** abilities never reach here: ``expand_modal_activated_lines``
    has already rewritten them into one ordinary ability line per bullet, so a
    bullet arriving here is always one alternative of a spell. A modal
    **triggered** ability does reach here and is not claimed, because its head
    parses as a ``TriggeredAbilityNode`` rather than a spell's effect line —
    where the old whole-text substring test would have turned its modes into
    cast-time ones.
    """
    if "choose" not in oracle_text.lower() or "•" not in oracle_text:
        # A pre-filter, not a second reading: both are necessary for the grammar
        # to return a head at all, so this can only skip work, never an answer.
        return ()

    lines = oracle_text.splitlines()
    for index, raw in enumerate(lines):
        if _modal_head(raw.strip(), grammar_ast.SpellEffectLine) is None:
            continue
        bullets = _bullets_after(lines, index)
        if not bullets:
            continue
        options: list[ModalOption] = []
        for label in bullets:
            instruction, effect_kind = _reading(_mode_reading(label, card_name))
            # The original casing is kept for the UI's mode picker.
            options.append(
                ModalOption(label.rstrip("."), instruction, effect_kind, instruction is not None)
            )
        return tuple(options)
    return ()


# ---------------------------------------------------------------------------
# Creature-line helpers
# ---------------------------------------------------------------------------

def _is_supported_keyword_line(line: str) -> bool:
    """Whether a printed keyword line names only keywords the engine implements.

    Reads `IMPLEMENTED_KEYWORDS` rather than a local copy: what may be *admitted*
    here and what the grammar will *lower* are the same claim, and two lists
    agreeing by hand is the arrangement this codebase keeps finding bugs in.
    """
    normalized = normalize_creature_line(line)
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    if not parts:
        return False
    # The two parameterised keywords are admitted by prefix plus quality:
    # "protection from white and from blue" and "hexproof from blue" carry the
    # quality as payload, not as part of the keyword's identity. Only *colour*
    # qualities are admitted, because colours are what _protection_colors and
    # _can_be_targeted model — admitting "protection from Demons" would ship
    # the word and silently drop the shield, so a non-colour quality keeps the
    # whole line refused with the clause named.
    return all(
        part in IMPLEMENTED_KEYWORDS or _colour_qualified_keyword_part(part)
        for part in parts
    )


def _colour_qualified_keyword_part(part: str) -> bool:
    for prefix in ("protection from ", "hexproof from "):
        if part.startswith(prefix):
            qualities = [
                q.strip()
                for q in re.split(r",|\band from\b|\band\b", part[len(prefix):])
                if q.strip()
            ]
            return bool(qualities) and all(
                q in _COLOR_WORD_TO_SYMBOL for q in qualities
            )
    return False


def _parse_activated_ability(line: str, card_name: str | None = None) -> ParsedActivatedAbility | None:
    normalized = normalize_creature_line(line)
    if ":" not in normalized:
        return None

    effect_text = normalized.split(":", 1)[1].strip()
    instruction, effect_kind = _reading(
        _line_instruction(line, card_name, activated=True)
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
    line. The legacy fallback this replaced collapsed the card's entire text to
    one string and kept the first rule that matched it, so an artifact whose
    activated ability the grammar reads in full still had its card-level
    instruction produced by re-reading the whole card — two front ends answering
    the same question about the same line, and only one of them per line. That
    whole-text pass is gone with the registry; a line nothing claims now
    contributes nothing, rather than borrowing a sentence from elsewhere on the
    card.

    Reusing the ability parse rather than re-running the grammar is what keeps
    the assembly per line, so a production claiming one line cannot delete the
    reading of any other.

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
        # triggered one whose condition the trigger table refuses (Cursed Land).
        # Its instruction used to arrive from the whole-text parse or from
        # parse_static_coeffects re-reading the card; it comes from this line
        # or from nowhere.
        static = _line_instruction(line, card_name)
        if static is not None:
            instructions.append(static[0])
    return instructions


# ---------------------------------------------------------------------------
# Top-level compiler
# ---------------------------------------------------------------------------

def expand_modal_activated_lines(oracle_text: str) -> str:
    """Rewrite '{cost}: Choose one —' + bullets into one ability line per
    bullet. Text without that shape is returned unchanged. Shared with
    engine.legality so target classification sees the same lines.

    A modal ACTIVATED ability ("{2}: Choose one —" followed by bullet lines,
    e.g. Pyramids) becomes one plain activated-ability line per bullet, same
    cost, so the existing multi-ability machinery (ability_index choice,
    per-ability targeting) covers it — and so the bullets are never mistaken for
    cast-time modes or top-level spell effects.

    Whether a line *is* such a head is the grammar's answer
    (:func:`_modal_head`), not a regex's. The regex it replaced admitted mana
    symbols only, so "Sacrifice a creature: Choose one —" would have been left
    on the floor, and it hard-coded "choose one" so no other count could ever be
    read — while the grammar refuses a count the engine cannot carry out and
    that refusal reaches here as a head this declines to expand. Only the cost
    is still taken from the raw text, because this rewrites text: re-rendering a
    parsed cost would be a second spelling of it, free to differ from the one
    ``mixins/stack/activation.py`` charges.
    """
    if "choose" not in (oracle_text or "").lower():
        return oracle_text
    lines = (oracle_text or "").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # ":" and "choose" are both necessary for the grammar to read the line
        # as an activated modal head, so testing them first only skips work.
        if ":" in line and "choose" in line.lower() and (
            _modal_head(line, grammar_ast.ActivatedAbilityNode) is not None
        ):
            bullets = _bullets_after(lines, i)
            if bullets:
                cost = line.partition(":")[0].strip()
                out.extend(f"{cost}: {bullet}" for bullet in bullets)
                i += 1 + len(bullets)
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

def _derived_static_claims(
    oracle_text: str, normalized_text: str, card_name: str | None = None
) -> list[str]:
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
    from .card_hooks import DRAW_STEP_MODIFIERS
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
    # The *name-keyed* half of the same CR 504 story (Island Sanctuary's
    # skip-your-draw-for-protection), registered in card_hooks and carried out by
    # phases/draw_step.py, phases/declare_attackers_step.py and
    # phases/untap_step.py. It has no instruction either, and until this claim it
    # had no support of its own: the card was held up by a `spell_pattern` marker
    # the whole-text fallback produced from the words "draw a card" inside a
    # sentence about *skipping* one. Deleting that fallback is what exposed it —
    # tests/engine/test_derived_support.py named the card immediately.
    if card_name in DRAW_STEP_MODIFIERS:
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

        # Line by line — the only way it is assembled now. The legacy path that
        # stood alongside it collapsed the card's whole text to one string and
        # kept only the first rule that matched, so a second sentence ("Draw a
        # card. Each player discards a card.") was silently dropped and an
        # artifact whose activated ability the grammar reads in full still had
        # its card-level instruction produced by re-reading the card end to end.
        instructions: list[OracleInstruction] = _noncreature_line_instructions(
            oracle_text,
            name,
            activated_abilities,
            triggered_abilities,
            whole_card=primary_type in {"artifact", "enchantment"},
        )
        # "Choose one —" modal spells: parse each bullet as a selectable mode so
        # the game can resolve the player's chosen mode rather than always the
        # first. Built from the original text to keep human-readable labels.
        modes = _modal_options(oracle_text, name)

        if not instructions and modes and modes[0].instruction is not None:
            # A modal spell's card-level instruction is its *first* mode's — the
            # bullets are alternatives, so there is no other honest candidate,
            # and the stack executes this list when nothing chose a mode.
            #
            # The whole-text fallback that stood beside this is deleted with the
            # rule registry, and its removal is the last of the silent
            # partial-reads: it collapsed the card to one string, where "counter
            # target red spell. destroy target red permanent" reads as a spell
            # that does both, and where a sentence *no line* produced an
            # instruction for could still hand the card one borrowed from
            # somewhere else in its text. Four cards carried such an instruction
            # (Fastbond, Island Sanctuary, Jihad, Lich) and nothing dispatched
            # any of them.
            instructions.append(modes[0].instruction)

        # Static continuous co-effects (e.g. Conversion's "All Mountains are
        # Plains.") that follow a primary clause already claimed above and that
        # no line above claimed for itself, derived line by line by
        # engine/grammar/derived.py.
        for coeffect in _grammar_static_coeffects(oracle_text, name):
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
            for claim in _derived_static_claims(oracle_text, normalized_text, name)
        )

        instructions.extend(
            OracleInstruction("spell_pattern", pattern)
            for pattern in SUPPORTED_SPELL_PATTERNS
            if pattern in normalized_text
        )

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
