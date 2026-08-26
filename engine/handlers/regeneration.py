from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import _one_choice, resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("grant_regeneration_to_target_creature")
def grant_regeneration_to_target_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    regenerated = game._grant_regeneration_shield(
        target,
        target_permanent_index=_one_choice(context.target_permanent_index),
        target_permanent_id=_one_choice(context.target_permanent_id),
        filter=instruction.payload,
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


@effect_handler("deny_regeneration_to_target")
def deny_regeneration_to_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Hurr Jackal: 'Target creature can't be regenerated this turn.' Reuses
    the cant_be_regenerated_this_turn flag Disintegrate-style effects already
    set (checked wherever a regeneration shield would apply)."""
    target = resolve_target_permanent(game, context)
    if target is None:
        return False, "no valid creature target"
    target.metadata["cant_be_regenerated_this_turn"] = True
    game.log.append(f"{target.card.name} can't be regenerated this turn")
    return True, "resolved"
