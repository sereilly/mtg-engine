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
    instructions: tuple[OracleInstruction, ...] = ()
    activated_abilities: tuple[ParsedActivatedAbility, ...] = ()
    triggered_abilities: tuple[ParsedTriggeredAbility, ...] = ()
    static_lines: tuple[str, ...] = ()


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
}


def _parse_number_token(token: str) -> int:
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token, 0)


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
