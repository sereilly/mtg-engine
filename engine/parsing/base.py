from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ..oracle_types import OracleInstruction

# A rule inspects normalized effect text and either claims it — returning the
# instruction plus its effect_kind — or returns None to let later rules try.
RuleResult = Optional[tuple[OracleInstruction, str]]
RuleFn = Callable[[str, bool], RuleResult]


@dataclass(frozen=True)
class ParseRule:
    order: int
    name: str
    fn: RuleFn


_RULES: list[ParseRule] = []
_ORDERS_SEEN: set[int] = set()
_sorted_cache: tuple[ParseRule, ...] | None = None


# Band base orders (one global order space shared by every category module —
# cross-category precedence is intentional: "destroy all creatures" must beat
# "destroy target" even though they could live in different files). Historic
# LEA orders were multiplied by 100 to open ~99 slots between former
# neighbors; write new rules as BAND_X + offset. The bands, ascending:
BAND_UPKEEP = 1_000            # upkeep pay-or-else effects
BAND_NAMED_TRIGGERS = 7_000    # named triggered-ability effects
BAND_SPELLS = 14_000           # spells — zones, combat tricks, damage, library
BAND_DESTRUCTION = 51_000      # recolor, mass/targeted destruction, pumps, discard
BAND_LIFE_TAP_PREVENT = 64_000 # game-ending, life totals, tap/untap, prevention
BAND_ACTIVATED = 81_000        # activated abilities (pump, counters, tokens, misc)
BAND_MANA_COUNTER = 101_000    # mana production, counterspells
BAND_TRIGGER_SHORTHANDS = 106_000  # "draw a card", "you lose the game"
BAND_GLOBAL_STATIC = 113_000   # global/static buffs (lowest precedence)


def parse_rule(order: int, name: str | None = None) -> Callable[[RuleFn], RuleFn]:
    """Register a parse rule at an explicit position in the matching sequence.

    Rules run in ascending *order*; the first rule to return a result wins.
    Explicit ordering lets rules live in category modules while still giving
    deterministic precedence (specific patterns must outrank generic ones,
    e.g. "destroy all creatures" before "destroy target"). Pick an unused
    order between the two rules yours must run between — new rules should be
    written as ``BAND_X + offset`` using the band constants above.
    """

    def decorator(fn: RuleFn) -> RuleFn:
        global _sorted_cache
        if order in _ORDERS_SEEN:
            raise ValueError(f"duplicate parse rule order {order} ({name or fn.__name__})")
        _ORDERS_SEEN.add(order)
        _RULES.append(ParseRule(order=order, name=name or fn.__name__, fn=fn))
        _sorted_cache = None
        return fn

    return decorator


def activated_kind(activated: bool, kind: str) -> str:
    """The effect_kind for a clause that can appear on either an activated
    ability ("activated_<kind>") or a spell ("spell_pattern")."""
    return f"activated_{kind}" if activated else "spell_pattern"


def iter_rules() -> tuple[ParseRule, ...]:
    global _sorted_cache
    if _sorted_cache is None:
        _sorted_cache = tuple(sorted(_RULES, key=lambda rule: rule.order))
    return _sorted_cache
