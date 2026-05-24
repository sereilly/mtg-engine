from __future__ import annotations

from dataclasses import dataclass
import re

from .models import CardDefinition


SUPPORTED_KEYWORDS = {
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
    "Banding",
    "Rampage",
    "Cumulative upkeep",
    "Phasing",
}

UNSUPPORTED_PATTERNS = (
    "bands are blocked",
    "copy",
    "exchange control",
    "instead",
)

UNSUPPORTED_REGEX_PATTERNS = (
    r"\bante\b",
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
    "regenerate target",
    "tap target",
    "untap target",
    "prevent the next",
    "from your graveyard to your hand",
    "from your graveyard to the battlefield",
    "from a graveyard onto the battlefield",
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
)


@dataclass(frozen=True)
class CardClassification:
    supported: bool
    effect_kind: str
    reason: str


def _is_simple_creature(card: CardDefinition) -> bool:
    text = card.oracle_text.strip()
    if not text:
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if _is_supported_keyword_line(line):
            continue
        if _is_supported_activated_line(line):
            continue
        if _is_supported_static_creature_line(line):
            continue
        return False
    return True


def _normalize_creature_line(line: str) -> str:
    lowered = line.lower()
    lowered = re.sub(r"\([^)]*\)", "", lowered)
    lowered = lowered.replace(";", ",")
    lowered = re.sub(r"\s+", " ", lowered).strip(" .,")
    return lowered


def _is_supported_keyword_line(line: str) -> bool:
    normalized = _normalize_creature_line(line)
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    if not parts:
        return False
    supported = {keyword.lower() for keyword in SUPPORTED_KEYWORDS}
    return all(part in supported for part in parts)


def _is_supported_activated_line(line: str) -> bool:
    normalized = _normalize_creature_line(line)
    if not re.match(r"^\{[^}]+\}(, \{t\})?:", normalized):
        return False

    supported_fragments = (
        "deals ",
        "destroy target",
        "regenerate this creature",
        "regenerate target creature",
        "target creature gets +",
        "target creature gains",
        "untap target land",
        "prevent the next",
        "add ",
    )
    return any(fragment in normalized for fragment in supported_fragments)


def _is_supported_static_creature_line(line: str) -> bool:
    normalized = _normalize_creature_line(line)
    static_patterns = (
        "this creature can't block",
        "this creature can't attack",
        "this creature attacks each combat if able",
        "as long as you control a swamp, this creature gets +1/+1",
        "other ",
    )
    if normalized.startswith("other ") and " get +" in normalized:
        return True
    return any(normalized.startswith(pattern) for pattern in static_patterns)


def classify_card(card: CardDefinition) -> CardClassification:
    text = card.oracle_text.lower()

    if any(keyword in card.keywords for keyword in UNSUPPORTED_KEYWORDS):
        return CardClassification(False, "unsupported", "unsupported keyword")

    if any(re.search(pattern, text) for pattern in UNSUPPORTED_REGEX_PATTERNS):
        return CardClassification(False, "unsupported", "complex oracle pattern")

    if any(pattern in text for pattern in UNSUPPORTED_PATTERNS):
        return CardClassification(False, "unsupported", "complex oracle pattern")

    primary_type = card.primary_type
    if primary_type == "land":
        return CardClassification(True, "land_mana", "basic land support")

    if primary_type == "creature":
        if _is_simple_creature(card):
            return CardClassification(True, "creature_simple", "simple creature support")
        return CardClassification(False, "unsupported", "creature text too complex")

    if primary_type in {"artifact", "enchantment", "instant", "sorcery"}:
        if not text:
            return CardClassification(True, "permanent_vanilla", "no oracle text")
        if any(pattern in text for pattern in SUPPORTED_SPELL_PATTERNS):
            return CardClassification(True, "spell_pattern", "pattern-supported effect")
        return CardClassification(False, "unsupported", "effect not in basic pattern set")

    return CardClassification(False, "unsupported", "unknown card type")
