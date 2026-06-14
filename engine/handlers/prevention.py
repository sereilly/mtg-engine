from __future__ import annotations

from typing import TYPE_CHECKING

from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("grant_prevention_shield")
def grant_prevention_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    x_value = context.x_value
    raw_amount = instruction.payload.get("amount", 0)
    amount = max(0, x_value or 0) if raw_amount == "x" else int(raw_amount)
    # CoP-style abilities say "prevent damage to you" — protection_kind="color"
    # means the caster/controller is always the beneficiary. Conservator-style
    # abilities ("...dealt to you this turn") set to_self=True for the same reason.
    if instruction.payload.get("protection_kind") == "color" or instruction.payload.get("to_self"):
        caster.damage_prevention_pool += amount
        game.log.append(f"{caster.name} gains prevention shield for {amount} damage")
        return True, "resolved"

    # "Prevent the next N damage that would be dealt to any target" (Healing
    # Salve's prevention mode, Samite Healer, …): the target may be a creature,
    # in which case the shield protects that creature rather than its controller.
    target_perm_idx = context.target_permanent_index
    if (
        isinstance(target_perm_idx, int)
        and 0 <= target_perm_idx < len(target.battlefield)
        and target.battlefield[target_perm_idx].card.primary_type == "creature"
    ):
        permanent = target.battlefield[target_perm_idx]
        permanent.damage_prevention_pool += amount
        game.log.append(f"{permanent.card.name} gains prevention shield for {amount} damage")
        return True, "resolved"

    target.damage_prevention_pool += amount
    game.log.append(f"{target.name} gains prevention shield for {amount} damage")
    return True, "resolved"


@effect_handler("grant_forcefield_shield")
def grant_forcefield_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    caster.combat_damage_cap_one_charges += 1
    game.log.append("Forcefield shield granted")
    return True, "resolved"


@effect_handler("redirect_one_damage_to_owner")
def redirect_one_damage_to_owner(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    source_permanent.metadata["redirect_one_damage_to_owner_until_eot"] = int(
        source_permanent.metadata.get("redirect_one_damage_to_owner_until_eot", 0)
    ) + 1
    game.log.append(f"{card.name} will redirect next 1 damage to its owner")
    return True, "resolved"


@effect_handler("jade_monolith_redirect")
def jade_monolith_redirect(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    target_creature = next((p for p in target.battlefield if p.card.primary_type == "creature"), None)
    if target_creature is not None:
        caster_idx = game.players.index(caster)
        target_creature.metadata["redirect_damage_to_player"] = caster_idx
        game.log.append(f"Jade Monolith marks {target_creature.card.name} for damage redirect to {caster.name}")
    return True, "resolved"
