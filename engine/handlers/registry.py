from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction

# An effect handler executes one instruction kind against the game state and
# returns (supported, details) — the same contract the old monolithic
# _execute_oracle_instruction if-chain used.
EffectHandler = Callable[["Game", "OracleInstruction", "OracleExecutionContext"], tuple[bool, str]]

EFFECT_HANDLERS: dict[str, EffectHandler] = {}


def effect_handler(*kinds: str) -> Callable[[EffectHandler], EffectHandler]:
    """Register a function as the executor for one or more instruction kinds.

    Dispatch is a dict lookup, so execution cost stays O(1) no matter how many
    instruction kinds the engine grows to support.
    """

    def decorator(func: EffectHandler) -> EffectHandler:
        for kind in kinds:
            if kind in EFFECT_HANDLERS:
                raise ValueError(f"duplicate effect handler for instruction kind: {kind}")
            EFFECT_HANDLERS[kind] = func
        return func

    return decorator
