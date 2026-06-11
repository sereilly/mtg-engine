from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ..models import Permanent, PlayerState
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("destroy_all_creatures")
def destroy_all_creatures(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    bypass_regen = instruction.payload.get("bypass_regeneration", False)
    for player in game.players:
        survivors: list[Permanent] = []
        for permanent in player.battlefield:
            if permanent.card.primary_type == "creature" and not bypass_regen and permanent.regeneration_shield > 0:
                permanent.regeneration_shield -= 1
                permanent.tapped = True
                survivors.append(permanent)
            elif permanent.card.primary_type == "creature":
                game._permanent_to_graveyard(player, permanent)
            else:
                survivors.append(permanent)
        player.battlefield = survivors
    game.log.append("All creatures were destroyed")
    return True, "resolved"


@effect_handler("destroy_all_artifacts_creatures_enchantments")
def destroy_all_artifacts_creatures_enchantments(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    for player in game.players:
        survivors: list[Permanent] = []
        for permanent in player.battlefield:
            primary_type = permanent.card.primary_type
            if primary_type == "creature" and permanent.regeneration_shield > 0:
                permanent.regeneration_shield -= 1
                permanent.tapped = True
                survivors.append(permanent)
            elif primary_type in {"artifact", "creature", "enchantment"}:
                player.graveyard.append(permanent.card)
            else:
                survivors.append(permanent)
        player.battlefield = survivors
    game.log.append("All artifacts, creatures, and enchantments were destroyed")
    return True, "resolved"


@effect_handler("destroy_all_enchantments")
def destroy_all_enchantments(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    for player in game.players:
        survivors: list[Permanent] = []
        for permanent in player.battlefield:
            if permanent.card.primary_type == "enchantment":
                player.graveyard.append(permanent.card)
            else:
                survivors.append(permanent)
        player.battlefield = survivors
    game.log.append("All enchantments were destroyed")
    return True, "resolved"


@effect_handler("destroy_all_lands")
def destroy_all_lands(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    for player in game.players:
        survivors: list[Permanent] = []
        for permanent in player.battlefield:
            if permanent.card.primary_type == "land":
                player.graveyard.append(permanent.card)
            else:
                survivors.append(permanent)
        player.battlefield = survivors
    game.log.append("All lands were destroyed")
    return True, "resolved"


@effect_handler("destroy_all_lands_of_type")
def destroy_all_lands_of_type(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    land_type = str(instruction.payload.get("land_type", "")).lower().rstrip("s")
    for player in game.players:
        survivors: list[Permanent] = []
        for permanent in player.battlefield:
            if permanent.card.primary_type == "land":
                # Determine printed or overridden land type
                perm_type_line = (permanent.metadata.get("land_type_override") or permanent.card.type_line or "").lower()
                if land_type in perm_type_line:
                    player.graveyard.append(permanent.card)
                    continue
            survivors.append(permanent)
        player.battlefield = survivors
    game.log.append(f"All {land_type}s were destroyed")
    return True, "resolved"


@effect_handler("destroy_target_permanent")
def destroy_target_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    source_permanent = context.source_permanent
    destroyed = game._destroy_target_permanent(
        target,
        type_filter=instruction.payload.get("type_filter"),
        color_filter=instruction.payload.get("color_filter"),
        target_permanent_index=context.target_permanent_index,
        exclude_colors=instruction.payload.get("exclude_colors"),
        exclude_types=instruction.payload.get("exclude_types"),
        bypass_regeneration=instruction.payload.get("bypass_regeneration", False),
    )
    if destroyed:
        if source_permanent is not None:
            game.log.append(f"{card.name} destroyed {destroyed.name}")
        else:
            game.log.append(f"Destroyed {destroyed.name}")
    else:
        game.log.append("No valid target permanent found")
    return True, "resolved"


@effect_handler("chaos_orb_flip")
def chaos_orb_flip(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    source_permanent = context.source_permanent
    # Collect all permanents from all players except Chaos Orb itself
    candidates: list[tuple[PlayerState, Permanent]] = [
        (player, perm)
        for player in game.players
        for perm in player.battlefield
        if perm is not source_permanent
    ]
    num_to_destroy = random.randint(0, min(2, len(candidates)))
    chosen = random.sample(candidates, num_to_destroy) if num_to_destroy > 0 else []
    for victim_player, victim_perm in chosen:
        victim_player.graveyard.append(victim_perm.card)
        victim_player.battlefield = [p for p in victim_player.battlefield if p is not victim_perm]
        game.log.append(f"Chaos Orb flip destroyed {victim_perm.card.name}")
    # Always destroy Chaos Orb itself
    if source_permanent is not None:
        for player in game.players:
            if source_permanent in player.battlefield:
                player.graveyard.append(source_permanent.card)
                player.battlefield = [p for p in player.battlefield if p is not source_permanent]
                break
    game.log.append("Chaos Orb was destroyed after flip")
    return True, "resolved"
