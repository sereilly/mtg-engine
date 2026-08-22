"""Text-keyed untap-step restrictions (CR 502).

"Players skip their untap steps", "players can't untap more than one land
during their untap steps", "creatures with power 3 or greater don't untap
during their controllers' untap steps" — these are templates, not card
quirks. Any card printed with the phrase behaves the same way, so the
restriction is derived from oracle text here rather than registered per card
name in ``card_hooks.py``. Same model as ``cast_restrictions.py``.

The untap step reads only the derived :class:`UntapRestriction`; adding a card
that uses one of these templates requires no change anywhere. A card whose
wording is genuinely new adds one pattern to the table below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from .oracle_types import _COLOR_WORD_TO_SYMBOL, _NUMBER_WORDS


@dataclass(frozen=True)
class UntapRestriction:
    """Declarative "don't untap as normal" constraint from a permanent.

    scope      -- what the restriction applies to: "all" | "land" | "creature"
                  | "creature_color"
    limit      -- max permanents of that scope the active player may untap
                  (0 with scope="all" skips the untap step entirely; None
                  means no count limit)
    min_power  -- per-permanent block: creatures with effective power >= N
                  don't untap (Meekstone)
    only_while_source_untapped -- the restriction is active only while the
                  source permanent itself is untapped (Winter Orb)
    color      -- with scope="creature_color", the mana symbol of the creatures
                  that don't untap (Magnetic Mountain)
    """

    scope: str
    limit: int | None = None
    min_power: int | None = None
    only_while_source_untapped: bool = False
    color: str | None = None


# "As long as this artifact is untapped, ..." (Winter Orb) — a self-state
# qualifier that can precede any of the restrictions below, so it is stripped
# first rather than duplicated into every pattern.
_WHILE_UNTAPPED = re.compile(
    r"^as long as (?:this|~) [a-z ]*?is untapped, (?P<rest>.+)$"
)

_COUNT_WORD = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
_COLOR_WORD = "|".join(sorted(_COLOR_WORD_TO_SYMBOL, key=len, reverse=True))


def _skip_untap_step(match: re.Match) -> UntapRestriction:
    return UntapRestriction(scope="all", limit=0)


def _limit_per_type(match: re.Match) -> UntapRestriction:
    return UntapRestriction(
        scope=match.group("type"), limit=_NUMBER_WORDS[match.group("count")]
    )


def _power_block(match: re.Match) -> UntapRestriction:
    return UntapRestriction(scope="creature", min_power=int(match.group("power")))


def _color_block(match: re.Match) -> UntapRestriction:
    return UntapRestriction(
        scope="creature_color", color=_COLOR_WORD_TO_SYMBOL[match.group("color")]
    )


# Ordered: the first pattern whose regex matches the (qualifier-stripped) line
# wins, so more specific wordings precede more general ones.
UNTAP_RESTRICTION_PATTERNS: tuple[tuple[re.Pattern, Callable[[re.Match], UntapRestriction]], ...] = (
    (re.compile(r"^players skip their untap steps$"), _skip_untap_step),
    (
        re.compile(
            rf"^players can't untap more than (?P<count>{_COUNT_WORD}) "
            r"(?P<type>land|creature|artifact)s? during their untap steps$"
        ),
        _limit_per_type,
    ),
    (
        re.compile(
            r"^creatures with power (?P<power>\d+) or greater don't untap "
            r"during their controllers' untap steps$"
        ),
        _power_block,
    ),
    (
        re.compile(
            rf"^(?P<color>{_COLOR_WORD}) creatures don't untap "
            r"during their controllers' untap steps$"
        ),
        _color_block,
    ),
)


def _restriction_from_line(line: str) -> UntapRestriction | None:
    qualifier = _WHILE_UNTAPPED.match(line)
    only_while_untapped = qualifier is not None
    if qualifier is not None:
        line = qualifier.group("rest")
    for pattern, build in UNTAP_RESTRICTION_PATTERNS:
        match = pattern.match(line)
        if match is not None:
            restriction = build(match)
            if only_while_untapped:
                return UntapRestriction(
                    scope=restriction.scope,
                    limit=restriction.limit,
                    min_power=restriction.min_power,
                    only_while_source_untapped=True,
                    color=restriction.color,
                )
            return restriction
    return None


@lru_cache(maxsize=None)
def untap_restriction_for(oracle_text: str) -> UntapRestriction | None:
    """The untap-step restriction *oracle_text* imposes, or None.

    Cached on the text itself, which is immutable on a ``CardDefinition``, so
    the untap step's per-permanent scan stays a dict lookup like the name-keyed
    table it replaced. Only the first matching line counts: no printed card
    carries two untap restrictions, and silently combining them would hide a
    wording this table does not actually understand.
    """
    if "untap" not in oracle_text.lower():
        return None
    for raw_line in oracle_text.lower().split("\n"):
        line = raw_line.strip().rstrip(".")
        if not line:
            continue
        restriction = _restriction_from_line(line)
        if restriction is not None:
            return restriction
    return None


# ---------------------------------------------------------------------------
# Per-source restrictions
# ---------------------------------------------------------------------------
#
# The table above describes restrictions a permanent imposes on *other*
# permanents. A second, simpler family describes what a permanent's own text
# says about itself, and `phases/untap_step.py` enforces it by scanning each
# battlefield permanent's oracle text for these two phrases. The phrases live
# here so that scan and the whole-line matcher below are built from one string
# each — a copy in either place could drift and start claiming a wording the
# untap step does not actually honour.

# "This artifact doesn't untap during your untap step." (Basalt Monolith, Mana
# Vault, Time Vault, Brass Man, Island Fish Jasconius) — the permanent simply
# stays tapped.
SELF_DOESNT_UNTAP_PHRASE = "doesn't untap during your untap step"

# "You may choose not to untap this creature during your untap step." (Old Man
# of the Sea) — the controller may keep it tapped; the untap step honours an
# explicit choice and otherwise keeps it tapped while its linked steal is live.
SELF_MAY_KEEP_TAPPED_PHRASE = "you may choose not to untap"

_SELF_NOUN = r"(?:artifact|creature|enchantment|land|permanent)"

# Built from the phrases above and anchored at both ends. Anchoring is what
# makes a claim on one of these lines honest: the untap step's substring probe
# fires on *any* line containing the phrase, so only a line that is nothing but
# the restriction is fully implemented by it. "Enchanted creature doesn't untap
# during its controller's untap step" (Paralyze) is deliberately outside this
# table — it is one half of a fused instruction in
# mixins/oracle_instructions.py, not a self-referential line the untap step
# reads.
_SELF_UNTAP_LINE_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (
        re.compile(rf"^this {_SELF_NOUN} {re.escape(SELF_DOESNT_UNTAP_PHRASE)}$"),
        "doesnt_untap",
    ),
    (
        re.compile(
            rf"^{re.escape(SELF_MAY_KEEP_TAPPED_PHRASE)} this {_SELF_NOUN} "
            r"during your untap step$"
        ),
        "may_keep_tapped",
    ),
)


def self_untap_line(line: str) -> str | None:
    """Name the per-source untap restriction *line* states in full, or None.

    The whole-line form of the two substring probes in
    ``phases/untap_step.py``. Its only caller is
    ``engine/grammar/registries.py``, which needs to know whether a line's
    behaviour is already carried out from the card's raw text — nothing
    dispatches on the returned name.
    """
    normalized = line.strip().lower().rstrip(".")
    for pattern, name in _SELF_UNTAP_LINE_PATTERNS:
        if pattern.match(normalized):
            return name
    return None
