from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import permanent_matches_filter, resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..models import Permanent
    from ..oracle import OracleInstruction


@effect_handler("grant_regeneration_to_target_creature")
def grant_regeneration_to_target_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Regenerate target creature" (Death Ward), "target Elephant" (Elephant
    Graveyard), "target black creature" (Horror of Horrors).

    The printed narrowing arrives as the ordinary filter payload and is tested
    by the one matcher, so what this accepts is what ``legality.py``'s picker
    offered. ``fallback_on_invalid_choice=False`` because an explicitly chosen
    illegal target fizzles (CR 608.2b) rather than sliding onto whatever else is
    on the battlefield.
    """
    described = instruction.payload

    def eligible(perm: Permanent) -> bool:
        return perm.is_creature and permanent_matches_filter(perm, described)

    chosen = resolve_target_permanent(
        game, context, predicate=eligible, fallback_on_invalid_choice=False
    )
    if chosen is None:
        game.log.append("No valid creature to regenerate")
        return True, "resolved"
    chosen.regeneration_shield += 1
    game.log.append("Regeneration shield granted")
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


@effect_handler("deny_regeneration_to_self")
def deny_regeneration_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{1}: This creature can't be regenerated this turn." (Clergy of the Holy
    Nimbus.)

    The untargeted twin of ``deny_regeneration_to_target``: the source itself,
    read off the context rather than chosen, and the same flag both destruction
    paths already consult (CR 701.19c). It is the *counter* to the Clergy's own
    static regeneration, so the flag has to be one both sides read — which is
    why the static side asks ``engine/regeneration.py`` rather than carrying a
    second notion of "shielded".
    """
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    source_permanent.metadata["cant_be_regenerated_this_turn"] = True
    game.log.append(f"{source_permanent.card.name} can't be regenerated this turn")
    return True, "resolved"
