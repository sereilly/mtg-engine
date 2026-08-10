from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import resolve_amount, resolve_target_permanent
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
        and target.battlefield[target_permanent_index].is_creature
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
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
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
        chosen_perm = resolve_target_permanent(context, predicate=lambda p: True, fallback_players=())
        chosen = chosen_perm.card.name if chosen_perm is not None else None
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

    # Rock Hydra: "{R}: Prevent the next 1 damage that would be dealt to this
    # creature this turn." The shield protects the ability's own source
    # permanent, never the (defaulted) target.
    if instruction.payload.get("to_source"):
        source_perm = context.source_permanent
        if source_perm is not None:
            source_perm.damage_prevention_pool += amount
            source_perm.damage_prevention_source = source_name
            game.log.append(
                f"{source_perm.card.name} gains prevention shield for {amount} damage"
            )
        return True, "resolved"

    # "Prevent the next N damage that would be dealt to any target" (Healing
    # Salve's prevention mode, Samite Healer, …): the target may be a creature,
    # in which case the shield protects that creature rather than its controller.
    apply_prevention_shield(game, target, context.target_permanent_index, amount, source_name)
    return True, "resolved"


@effect_handler("grant_reverse_damage_shield")
def grant_reverse_damage_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Reverse Damage: arm a one-shot shield against "a source of your choice".

    The caster picks the source — a permanent on any battlefield (chosen via
    target_permanent_index) or a spell on the stack (the threatening burn spell,
    chosen via stack_target). Only damage from that source is prevented and gained
    as life. With no chosen source (AI / headless casts), fall back to a generic
    charge that shields the entire next damage event from any source.
    """
    caster = context.caster
    chosen = None
    if context.stack_target is not None:
        # A spell on the stack: match later by its card identity (the same
        # CardDefinition the spell deals damage with when it resolves).
        chosen = context.stack_target.card
    else:
        chosen = resolve_target_permanent(context, predicate=lambda p: True, fallback_players=())
    if chosen is not None:
        caster.reverse_damage_sources.append(chosen)
        source_card = getattr(chosen, "card", chosen)
        game.log.append(
            f"{caster.name} armed a Reverse Damage shield against {getattr(source_card, 'name', 'a source')}"
        )
    else:
        caster.reverse_damage_charges += 1
        game.log.append(f"{caster.name} armed a Reverse Damage shield")
    caster.damage_prevention_source = context.card.name if context.card else None
    return True, "resolved"


@effect_handler("grant_forcefield_shield")
def grant_forcefield_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    # Honor the chosen unblocked attacker so only that creature's combat damage is
    # capped to 1. Fall back to a generic "next combat damage" cap for AI/headless
    # activations that supply no target.
    chosen = resolve_target_permanent(context, fallback_players=())
    if chosen is not None:
        caster.forcefield_capped_sources.append(chosen)
        game.log.append(f"Forcefield will prevent all but 1 combat damage from {chosen.card.name}")
    else:
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
    target player's battlefield) AND the damage source (choices["chosen_source"]: a
    battlefield permanent or a stack spell's card). The next damage that source
    would deal to the creature is redirected to the controller; with no recorded
    source choice (AI/legacy activations) any source's damage is redirected.
    """
    caster = context.caster
    target_creature = resolve_target_permanent(context)
    if target_creature is not None:
        caster_idx = game.players.index(caster)
        target_creature.metadata["redirect_damage_to_player"] = caster_idx
        chosen_source = context.choices.get("chosen_source")
        if chosen_source is not None:
            target_creature.metadata["redirect_damage_source"] = chosen_source
            source_name = getattr(getattr(chosen_source, "card", chosen_source), "name", "source")
            game.log.append(
                f"Jade Monolith marks {target_creature.card.name} for damage redirect to {caster.name}"
                f" (source: {source_name})"
            )
        else:
            target_creature.metadata.pop("redirect_damage_source", None)
            game.log.append(f"Jade Monolith marks {target_creature.card.name} for damage redirect to {caster.name}")
    return True, "resolved"


@effect_handler("shield_target_land_from_destruction")
def shield_target_land_from_destruction(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Pyramids mode 2: "The next time target land would be destroyed this
    turn, remove all damage marked on it instead." Arms a one-shot shield the
    destroy paths consume via _consume_land_destruction_shield."""
    card = context.card
    target_land = resolve_target_permanent(
        context,
        predicate=lambda p: p.card.primary_type == "land",
        fallback_players=(context.caster, context.target),
    )
    if target_land is None:
        game.log.append(f"{card.name}: no valid land target")
        return True, "resolved"
    target_land.metadata["land_destruction_shield_this_turn"] = True
    game.log.append(
        f"{card.name}: the next time {target_land.card.name} would be destroyed this turn, "
        "all damage marked on it is removed instead"
    )
    return True, "resolved"


@effect_handler("arm_mirror_damage")
def arm_mirror_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Eye for an Eye: the next damage dealt to you this turn by "a source of
    your choice" also hits that source's controller for the same amount.

    Mirrors Reverse Damage's shape: the caster picks the source — a permanent on
    any battlefield (target_permanent_index) or a spell on the stack
    (stack_target) — and only damage from that source is mirrored, matched by
    identity in _deal_damage_to_player. With no chosen source (AI / headless
    casts) fall back to a generic charge that mirrors the next damage event from
    any source."""
    caster = context.caster
    if context.stack_target is not None:
        # A spell on the stack: match later by its card identity (the same
        # CardDefinition the spell deals damage with when it resolves).
        chosen = context.stack_target.card
    else:
        chosen = resolve_target_permanent(context, predicate=lambda p: True, fallback_players=())
    if chosen is not None:
        caster.mirror_damage_sources.append(chosen)
        source_card = getattr(chosen, "card", chosen)
        game.log.append(
            f"{caster.name}: the next damage {getattr(source_card, 'name', 'a source')} "
            f"deals to them this turn is mirrored to its controller ({context.card.name})"
        )
    else:
        caster.mirror_damage_charges += 1
        game.log.append(
            f"{caster.name}: the next damage dealt to them this turn is mirrored "
            f"to its source's controller ({context.card.name})"
        )
    return True, "resolved"
