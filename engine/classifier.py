from __future__ import annotations

from dataclasses import dataclass
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
    if not re.match(r"^(?:\{[^}]+\})+(?:, \{t\})?:", normalized):
        return False

    supported_fragments = (
        "deals ",
        "destroy target",
        "regenerate this creature",
        "regenerate target creature",
        "this creature gets +",
        "this creature gains flying",
        "put up to x +1/+0 counters on this creature",
        "put a +1/+1 counter on this creature",
        "target creature gets +",
        "target creature gains",
        "target creature with power 2 or less can't be blocked this turn",
        "target land becomes a forest",
        "choose target non-wall creature",
        "target creature you control with toughness less than this creature's power gains flying until end of turn",
        "the next 1 damage that would be dealt to this creature this turn is dealt to its owner instead",
        "untap target land",
        "prevent the next",
        "add ",
    )
    return any(fragment in normalized for fragment in supported_fragments)


def _is_supported_static_creature_line(line: str) -> bool:
    normalized = _normalize_creature_line(line)
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
