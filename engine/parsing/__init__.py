"""Declarative oracle-text parse rules.

Each module in this package registers @parse_rule functions that map a
normalized oracle-text effect clause to an (OracleInstruction, effect_kind)
pair. Rules run in ascending registration order; the first match wins. To
support a new card pattern, add one rule to the matching category module —
no existing code needs to change.
"""

from __future__ import annotations

import re

from ..oracle_types import OracleInstruction
from .base import ParseRule, RuleFn, RuleResult, iter_rules, parse_rule

# Importing the category modules populates the rule registry.
from . import (  # noqa: E402,F401
    combat,
    damage,
    destruction,
    global_effects,
    life_and_game,
    mana,
    misc,
    prevention,
    pump,
    regeneration,
    stack,
    tapping,
    triggers,
    upkeep,
    zones,
)

_MODAL_SPLIT_RE = re.compile(r"\s*•\s*")


def parse_primary_instruction(text: str, *, activated: bool) -> tuple[OracleInstruction | None, str]:
    """Parse the primary effect instruction from a normalized effect clause."""
    # "Choose one" modal spells: parse only the first bullet so the primary
    # instruction matches the card's first mode (e.g. Healing Salve gains life,
    # Blue/Red Elemental Blast counters a spell).
    if "choose one" in text and "•" in text:
        parts = _MODAL_SPLIT_RE.split(text, maxsplit=2)
        if len(parts) >= 2:
            first_mode = parts[1].strip()
            instr, kind = parse_primary_instruction(first_mode, activated=activated)
            if instr is not None:
                return instr, kind

    for rule in iter_rules():
        result = rule.fn(text, activated)
        if result is not None:
            return result

    return None, "unsupported"


__all__ = [
    "ParseRule",
    "RuleFn",
    "RuleResult",
    "iter_rules",
    "parse_primary_instruction",
    "parse_rule",
]
