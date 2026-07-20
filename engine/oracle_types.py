"""Shared oracle-text data types and small text helpers.

These live in their own module (rather than engine.oracle) so that the
parse-rule modules in engine/parsing can import them without creating an
import cycle with the oracle compiler.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_COLOR_WORD_TO_SYMBOL: dict[str, str] = {
    "white": "W",
    "blue": "U",
    "black": "B",
    "red": "R",
    "green": "G",
}

_X_SPEND_COLOR_RE = re.compile(r"spend only (white|blue|black|red|green) mana on x")


def x_spend_color_from_text(text: str) -> str | None:
    """The single color that may be spent on X ("Spend only black mana on X."
    — Drain Life), as a mana symbol, or None when X is unrestricted."""
    match = _X_SPEND_COLOR_RE.search(text.lower())
    return _COLOR_WORD_TO_SYMBOL[match.group(1)] if match else None


@dataclass(frozen=True)
class OracleToken:
    kind: str
    value: str


@dataclass(frozen=True)
class ActivatedAbilityCost:
    mana: dict[str, int]
    requires_tap: bool = False
    # Jandor's Ring: "{2}, {T}, Discard the last card you drew this turn: Draw a
    # card." A non-mana additional cost — the ability can't be activated unless
    # that card is still in hand, and activating discards it.
    discard_last_drawn: bool = False
    # Ring of Ma'rûf: "{5}, {T}, Exile this artifact: ..." — activating exiles
    # the source permanent as part of the cost.
    exile_self: bool = False


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
class ModalOption:
    """One mode of a "Choose one —" modal spell.

    label        -- human-readable bullet text (original case), for the UI prompt
    instruction  -- the parsed effect for this mode, or None if unsupported
    effect_kind  -- mirrors the effect_kind convention used elsewhere
    supported    -- True only if the mode's effect was recognized
    """
    label: str
    instruction: OracleInstruction | None
    effect_kind: str = "unsupported"
    supported: bool = False


@dataclass(frozen=True)
class OracleProgram:
    supported: bool
    effect_kind: str
    reason: str
    normalized_text: str
    instructions: tuple[OracleInstruction, ...] = ()
    activated_abilities: tuple[ParsedActivatedAbility, ...] = ()
    triggered_abilities: tuple[ParsedTriggeredAbility, ...] = ()
    static_lines: tuple[str, ...] = ()
    # Modes of a "Choose one —" modal spell, in bullet order. Empty for
    # non-modal cards. The player chooses one mode when the spell is cast.
    modes: tuple[ModalOption, ...] = ()


def _instruction(kind: str, value: str = "", **payload: Any) -> OracleInstruction:
    return OracleInstruction(kind, value, payload)


_NUMBER_WORDS = {
    "a": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def parse_number_token(token: str) -> int | None:
    """Strict number parse: digits or a spelled-out number word, else None.
    New parse rules should prefer this over ``_parse_number_token`` so an
    unrecognized word surfaces as a parse failure instead of a silent 0."""
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token)


def _parse_number_token(token: str) -> int:
    """Legacy lenient variant kept for existing call sites: unknown words
    parse as 0."""
    value = parse_number_token(token)
    return 0 if value is None else value


_MANA_TOKEN_RE = re.compile(r"\{([^}]+)\}")


def _extract_mana_cost_from_text(text: str) -> dict[str, int]:
    """Extract the first mana cost symbols found in *text* and return counts."""
    cost: dict[str, int] = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 0}
    for token in _MANA_TOKEN_RE.findall(text.upper()):
        if token.isdigit():
            cost["generic"] += int(token)
        elif token in {"W", "U", "B", "R", "G", "C"}:
            cost[token] += 1
    return cost
