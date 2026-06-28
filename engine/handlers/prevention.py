from __future__ import annotations

from typing import TYPE_CHECKING

from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..models import PlayerState
    from ..oracle import OracleInstruction


def apply_prevention_shield(
    game: Game,
    target: PlayerState,
    target_permanent_index: object,
    amount: int,
    source_name: str | None = None,
) -> str:
    """Grant `amount` prevention shields to a chosen creature, or otherwise to the
    target player. Records `source_name` (the granting card) so the UI can show
    its art on the shield badge. Returns the name of the beneficiary."""
    if (
        isinstance(target_permanent_index, int)
        and 0 <= target_permanent_index < len(target.battlefield)
        and target.battlefield[target_permanent_index].card.primary_type == "creature"
    ):
        permanent = target.battlefield[target_permanent_index]
        permanent.damage_prevention_pool += amount
        permanent.damage_prevention_source = source_name
        game.log.append(f"{permanent.card.name} gains prevention shield for {amount} damage")
        return permanent.card.name
    target.damage_prevention_pool += amount
    target.damage_prevention_source = source_name
    game.log.append(f"{target.name} gains prevention shield for {amount} damage")
    return target.name


@effect_handler("grant_prevention_shield")
def grant_prevention_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    x_value = context.x_value
    raw_amount = instruction.payload.get("amount", 0)
    amount = max(0, x_value or 0) if raw_amount == "x" else int(raw_amount)
    source_name = context.card.name if context.card else None
    # CoP-style abilities say "prevent damage to you" — protection_kind="color"
    # means the caster/controller is always the beneficiary. Conservator-style
    # abilities ("...dealt to you this turn") set to_self=True for the same reason.
    prevention_color = instruction.payload.get("prevention_color")
    if instruction.payload.get("protection_kind") == "color":
        # Circle of Protection: "The next time a <color> source of your choice
        # would deal damage to you this turn, prevent that damage." Each activation
        # arms one color-scoped shield that prevents the entire next damage event
        # from a source of that color (CR 615) — distinct from the generic numeric
        # prevention pool so it only stops matching-colored damage.
        for _ in range(max(1, amount)):
            caster.color_prevention_shields.append(prevention_color)
        if prevention_color:
            caster.damage_prevention_color = prevention_color
        caster.damage_prevention_source = source_name
        # The chosen source (if the controller picked a specific permanent) is
        # recorded only for the log; matching is by color.
        chosen = None
        idx = context.target_permanent_index
        if isinstance(idx, int) and context.target is not None and 0 <= idx < len(context.target.battlefield):
            chosen = context.target.battlefield[idx].card.name
        game.log.append(
            f"{caster.name} sets a Circle of Protection shield against "
            + (f"{chosen} (a {prevention_color} source)" if chosen else f"a {prevention_color} source")
        )
        return True, "resolved"

    if instruction.payload.get("to_self"):
        caster.damage_prevention_pool += amount
        caster.damage_prevention_source = source_name
        game.log.append(f"{caster.name} gains prevention shield for {amount} damage")
        return True, "resolved"

    # "Prevent the next N damage that would be dealt to any target" (Healing
    # Salve's prevention mode, Samite Healer, …): the target may be a creature,
    # in which case the shield protects that creature rather than its controller.
    apply_prevention_shield(game, target, context.target_permanent_index, amount, source_name)
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
    """Jade Monolith: "The next time a source of your choice would deal damage to
    target creature this turn, that source deals that damage to you instead."

    The controller chooses the target creature (target_permanent_index on the
    target player's battlefield). The next damage that creature would take is
    redirected to the controller.
    """
    caster = context.caster
    target = context.target
    target_creature = None
    idx = context.target_permanent_index
    if isinstance(idx, int) and 0 <= idx < len(target.battlefield):
        candidate = target.battlefield[idx]
        if candidate.card.primary_type == "creature":
            target_creature = candidate
    if target_creature is None:
        target_creature = next((p for p in target.battlefield if p.card.primary_type == "creature"), None)
    if target_creature is not None:
        caster_idx = game.players.index(caster)
        target_creature.metadata["redirect_damage_to_player"] = caster_idx
        game.log.append(f"Jade Monolith marks {target_creature.card.name} for damage redirect to {caster.name}")
    return True, "resolved"
