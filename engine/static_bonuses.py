"""Conditional static power/toughness bonuses (CR 613 layer 7c).

"This creature gets +N/+N as long as <condition>" — Sedge Troll, Kird Ape,
Giant Tortoise. The bonus size and the condition's subject are both data, and
the clause is printed in **two word orders**:

    This creature gets +1/+1 as long as you control a Swamp.
    As long as you control a Swamp, this creature gets +1/+1.

Only the first was ever dispatched. The second was admitted by a whitelist
literal in the compiler's support gate that spelled out *Swamp*, so a card
printed that way reported `supported` and then never got the bonus — while the
identical sentence naming any other land type was reported unsupported. Gate
and dispatch derive from this one table now, so both orders work for every
type and an unrecognized wording fails loud.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from .oracle_types import _NUMBER_WORDS

# Desert is included alongside the five basics: Arabian Nights prints
# "as long as you control a Desert", and the check this feeds
# (_refresh_dynamic_creatures) matches by type, not by basic-ness.
BASIC_LAND_WORDS = ("plains", "island", "swamp", "mountain", "forest", "desert")
_LAND_ALTERNATION = "|".join(BASIC_LAND_WORDS)

_BONUS = r"gets \+(?P<power>\d+)/\+(?P<toughness>\d+)"


@dataclass(frozen=True)
class StaticBonus:
    """An instruction kind the P/T refresh dispatches on, plus its data."""

    kind: str
    payload: dict[str, object] = field(default_factory=dict)


# (pattern, kind). Each condition appears twice — trailing and leading — because
# both are printed. Writing them as one table is what keeps the two orders from
# drifting into "one is implemented, the other is whitelisted".
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(rf"{_BONUS} as long as you control an? (?P<land_type>{_LAND_ALTERNATION})\b"),
        "conditional_land_bonus",
    ),
    (
        re.compile(
            rf"^as long as you control an? (?P<land_type>{_LAND_ALTERNATION}), "
            rf".*?{_BONUS}$"
        ),
        "conditional_land_bonus",
    ),
    (
        re.compile(rf"{_BONUS} as long as (?:it's|this creature is) untapped\b"),
        "conditional_untapped_bonus",
    ),
    (
        re.compile(rf"^as long as (?:it's|this creature is) untapped, .*?{_BONUS}$"),
        "conditional_untapped_bonus",
    ),
)


def static_bonus_for(normalized_line: str) -> StaticBonus | None:
    """The conditional static ability *normalized_line* grants, or None.

    Takes an already-normalized line (``oracle.normalize_creature_line``).
    The two legacy kinds are tried first so their payloads stay byte-identical;
    everything newer rides the general ``conditional_static`` shape below.
    """
    for pattern, kind in _PATTERNS:
        match = pattern.search(normalized_line)
        if match is None:
            continue
        groups = match.groupdict()
        payload: dict[str, object] = {
            "power": int(groups["power"]),
            "toughness": int(groups["toughness"]),
        }
        if groups.get("land_type"):
            payload["land_type"] = groups["land_type"]
        return StaticBonus(kind, payload)
    return conditional_static_for(normalized_line)


# ---------------------------------------------------------------------------
# The general conditional static: <effect> as long as <condition>
# ---------------------------------------------------------------------------
#
# One instruction kind, ``conditional_static``, with the condition and the
# effect both payload — the legacy kinds above baked the condition into the
# kind, which is one dispatch branch per condition per effect class and grows
# multiplicatively. Who consumes which half is split by layer: the P/T delta
# is contributed by ``_refresh_dynamic_creatures`` (layer 7c's derived
# channel), keyword grants by ``_recalculate_lord_buffs`` (layer 6's derived
# grants, whose clear/rebuild that pass owns), and "can't be blocked" is asked
# at block-legality time — a condition can change between recomputes, and the
# blocking check is the read that matters.

_DRAWN_CONDITION = re.compile(
    r"^you've drawn (?P<count>[a-z]+) or more cards this turn$"
)
_CONTROLS_PLANESWALKER_CONDITION = re.compile(
    r"^you control an? (?P<subtype>[a-z]+) planeswalker$"
)
_HAS_PLUS1_CONDITION = re.compile(r"^it has a \+1/\+1 counter on it$")

_EFFECT_PT = re.compile(
    r"^gets \+(?P<power>\d+)/\+(?P<toughness>\d+)(?: and has (?P<keywords>[a-z ]+))?$"
)
_EFFECT_KEYWORDS = re.compile(r"^has (?P<keywords>[a-z ]+)$")
_EFFECT_UNBLOCKABLE = re.compile(r"^can't be blocked$")


@lru_cache(maxsize=1)
def _implemented_keywords() -> frozenset[str]:
    # Lazy for the same reason lord_buffs' vocabulary is: the grammar package
    # imports this module, and the keyword set belongs to the engine's one
    # registry rather than a copy here.
    from .grammar import vocabulary

    return vocabulary.IMPLEMENTED_KEYWORDS


def _parse_condition_text(text: str) -> dict[str, object] | None:
    match = _DRAWN_CONDITION.match(text)
    if match is not None:
        count = _NUMBER_WORDS.get(match.group("count"))
        if count is None:
            return None
        return {"kind": "drawn_cards_this_turn", "count": count}
    match = _CONTROLS_PLANESWALKER_CONDITION.match(text)
    if match is not None:
        return {"kind": "controls_planeswalker", "subtype": match.group("subtype")}
    if _HAS_PLUS1_CONDITION.match(text) is not None:
        return {"kind": "has_plus1_counter"}
    return None


def _parse_effect_text(text: str) -> dict[str, object] | None:
    match = _EFFECT_PT.match(text)
    if match is not None:
        effect: dict[str, object] = {
            "power": int(match.group("power")),
            "toughness": int(match.group("toughness")),
        }
        if match.group("keywords"):
            keywords = _keyword_list(match.group("keywords"))
            if keywords is None:
                return None
            effect["keywords"] = keywords
        return effect
    match = _EFFECT_KEYWORDS.match(text)
    if match is not None:
        keywords = _keyword_list(match.group("keywords"))
        if keywords is None:
            return None
        return {"keywords": keywords}
    if _EFFECT_UNBLOCKABLE.match(text) is not None:
        return {"cant_be_blocked": True}
    return None


def _keyword_list(text: str) -> list[str] | None:
    """The keyword abilities *text* names — every one must be implemented,
    because a conditional grant of a word without behaviour is a grant of
    nothing and the line must refuse instead."""
    words = [part.strip() for part in re.split(r",| and ", text) if part.strip()]
    if not words or any(word not in _implemented_keywords() for word in words):
        return None
    return words


def conditional_static_for(normalized_line: str) -> StaticBonus | None:
    """"<effect> as long as <condition>", in both printed word orders."""
    line = normalized_line.strip().rstrip(".")
    subject = "this creature "
    if line.startswith("as long as "):
        # "As long as <condition>, this creature <effect>" (Gnarled Sage).
        rest = line[len("as long as "):]
        condition_text, separator, effect_clause = rest.partition(", ")
        if not separator or not effect_clause.startswith(subject):
            return None
        effect_text = effect_clause[len(subject):]
    else:
        # "This creature <effect> as long as <condition>" (Sigiled Contender,
        # Tome Anima, Predatory Wurm).
        if not line.startswith(subject):
            return None
        remainder = line[len(subject):]
        effect_text, separator, condition_text = remainder.partition(" as long as ")
        if not separator:
            return None
    condition = _parse_condition_text(condition_text)
    effect = _parse_effect_text(effect_text)
    if condition is None or effect is None:
        return None
    return StaticBonus("conditional_static", {**effect, "condition": condition})


def conditional_static_holds(game, seat: int, source, condition: dict) -> bool:
    """Whether a ``conditional_static`` payload's condition holds right now.

    Beside the table that produces the payloads so the vocabulary has one
    definition; *game* and *source* are duck-typed (the control seam and the
    permanent's own state are all it reads).
    """
    kind = condition.get("kind")
    if kind == "drawn_cards_this_turn":
        player = game.players[seat]
        return len(player.cards_drawn_this_turn) >= int(condition.get("count", 0))
    if kind == "controls_planeswalker":
        subtype = condition.get("subtype")
        return any(
            perm.has_type("planeswalker") and perm.has_type(subtype)
            for perm in game.controlled_by(seat)
        )
    if kind == "has_plus1_counter":
        return int(source.metadata.get("plus_counters", 0)) > 0
    return False


def singular_land_type(word: str) -> str:
    """The land subtype *word* names, however it was pluralised.

    Four of the five basic types pluralise with a trailing "s"; Plains is
    spelled identically singular and plural, so stripping one unconditionally
    produces "plain" — a subtype no land has. Checking the known types first
    means the shape of the word never has to be guessed.
    """
    lowered = word.strip().lower()
    if lowered in BASIC_LAND_WORDS:
        return lowered
    trimmed = lowered.rstrip("s")
    return trimmed if trimmed in BASIC_LAND_WORDS else lowered
