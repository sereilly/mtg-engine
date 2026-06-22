"""Declarative oracle-text parse rules.

Each module in this package registers @parse_rule functions that map a
normalized oracle-text effect clause to an (OracleInstruction, effect_kind)
pair. Rules run in ascending registration order; the first match wins. To
support a new card pattern, add one rule to the matching category module —
no existing code needs to change.
"""

from __future__ import annotations

import re

from ..oracle_types import ModalOption, OracleInstruction
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
_CHOOSE_ONE_RE = re.compile(r"choose one\b", re.IGNORECASE)
_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_mode_clause(label: str) -> str:
    """Lowercase, drop reminder text and collapse whitespace so a single modal
    bullet can be fed to the parse-rule registry the same way a full effect
    clause is."""
    cleaned = _PARENTHETICAL_RE.sub("", label.lower())
    return _WHITESPACE_RE.sub(" ", cleaned).strip().rstrip(".")


def parse_modal_options(oracle_text: str) -> tuple[ModalOption, ...]:
    """Parse the bullet options of a "Choose one —" modal spell.

    Returns one ModalOption per bullet (in order, original-case labels for the
    UI), or an empty tuple when the text is not modal. Each option's effect is
    parsed independently through the same rule registry as a normal spell, so a
    mode is supported exactly when its clause maps to a known instruction.
    """
    if "•" not in oracle_text or not _CHOOSE_ONE_RE.search(oracle_text):
        return ()

    # Everything from the first bullet onward is the list of modes; the text
    # before it ("Choose one —") is just the preamble.
    _, _, body = oracle_text.partition("•")
    options: list[ModalOption] = []
    for raw in body.split("•"):
        label = _WHITESPACE_RE.sub(" ", raw.strip()).strip()
        if not label:
            continue
        display = label.rstrip(".")
        instr, kind = parse_primary_instruction(_normalize_mode_clause(label), activated=False)
        options.append(ModalOption(display, instr, kind, instr is not None))
    return tuple(options)


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


def parse_static_coeffects(text: str) -> list[OracleInstruction]:
    """Static continuous effects that can co-exist with a primary clause and so
    are missed by ``parse_primary_instruction`` (which returns only the first
    match). For example Conversion's "All Mountains are Plains." follows an
    upkeep cost clause that already claims the primary instruction.
    """
    instructions: list[OracleInstruction] = []
    result = global_effects.static_land_type_change(text, False)
    if result is not None:
        instructions.append(result[0])
    return instructions


__all__ = [
    "ParseRule",
    "RuleFn",
    "RuleResult",
    "iter_rules",
    "parse_modal_options",
    "parse_primary_instruction",
    "parse_rule",
]
