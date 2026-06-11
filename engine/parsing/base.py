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


def parse_rule(order: int, name: str | None = None) -> Callable[[RuleFn], RuleFn]:
    """Register a parse rule at an explicit position in the matching sequence.

    Rules run in ascending *order*; the first rule to return a result wins.
    Explicit ordering lets rules live in category modules while still giving
    deterministic precedence (specific patterns must outrank generic ones,
    e.g. "destroy all creatures" before "destroy target"). Pick an unused
    order between the two rules yours must run between.
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


def iter_rules() -> tuple[ParseRule, ...]:
    global _sorted_cache
    if _sorted_cache is None:
        _sorted_cache = tuple(sorted(_RULES, key=lambda rule: rule.order))
    return _sorted_cache
