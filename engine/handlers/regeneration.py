from __future__ import annotations

from typing import TYPE_CHECKING

from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("grant_regeneration_to_target_creature")
def grant_regeneration_to_target_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    regenerated = game._grant_regeneration_shield(
        target, target_permanent_index=context.target_permanent_index
    )
    game.log.append("Regeneration shield granted" if regenerated else "No valid creature to regenerate")
    return True, "resolved"


@effect_handler("grant_regeneration_to_self")
def grant_regeneration_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    source_permanent.regeneration_shield += 1
    game.log.append(f"{card.name} gains regeneration shield")
    return True, "resolved"


@effect_handler("grant_regeneration_to_enchanted_creature")
def grant_regeneration_to_enchanted_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    enchanted = source_permanent.metadata.get("attached_to")
    if enchanted is None:
        return False, "aura not attached to a creature"
    enchanted.regeneration_shield += 1
    game.log.append(f"{card.name} grants regeneration shield to {enchanted.card.name}")
    return True, "resolved"
