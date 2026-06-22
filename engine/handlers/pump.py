from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("berserk_pump")
def berserk_pump(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    target_perm: Permanent | None = None
    if context.target_permanent_index is not None and 0 <= context.target_permanent_index < len(target.battlefield):
        candidate = target.battlefield[context.target_permanent_index]
        if candidate.card.primary_type == "creature":
            target_perm = candidate
    if target_perm is None:
        target_perm = next((p for p in target.battlefield if p.card.primary_type == "creature"), None)
    if target_perm is not None:
        boost = target_perm.effective_power
        target_perm.power_bonus += boost
        target_perm.metadata["gains_trample_until_eot"] = True
        game.log.append(f"{card.name} pumped {target_perm.card.name} by +{boost}/+0 and granted trample")
    else:
        game.log.append(f"{card.name}: no valid creature target")
    return True, "resolved"


@effect_handler("pump_enchanted_creature")
def pump_enchanted_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    enchanted = source_permanent.metadata.get("attached_to")
    if enchanted is None:
        return False, "aura not attached to a creature"
    power_delta = int(instruction.payload.get("power", 0))
    toughness_delta = int(instruction.payload.get("toughness", 0))
    enchanted.power_bonus += power_delta
    enchanted.toughness_bonus += toughness_delta
    enchanted.metadata["temporary_power_bonus_until_eot"] = int(
        enchanted.metadata.get("temporary_power_bonus_until_eot", 0)
    ) + power_delta
    enchanted.metadata["temporary_toughness_bonus_until_eot"] = int(
        enchanted.metadata.get("temporary_toughness_bonus_until_eot", 0)
    ) + toughness_delta
    game.log.append(f"{card.name} grants {enchanted.card.name} +{power_delta}/+{toughness_delta} until end of turn")
    return True, "resolved"


@effect_handler("pump_self")
def pump_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    power_delta = int(instruction.payload.get("power", 0))
    toughness_delta = int(instruction.payload.get("toughness", 0))
    source_permanent.power_bonus += power_delta
    source_permanent.toughness_bonus += toughness_delta
    source_permanent.metadata["temporary_power_bonus_until_eot"] = int(
        source_permanent.metadata.get("temporary_power_bonus_until_eot", 0)
    ) + power_delta
    source_permanent.metadata["temporary_toughness_bonus_until_eot"] = int(
        source_permanent.metadata.get("temporary_toughness_bonus_until_eot", 0)
    ) + toughness_delta
    game.log.append(
        f"{card.name} gets +{int(instruction.payload.get('power', 0))}/+{int(instruction.payload.get('toughness', 0))} until end of turn"
    )
    return True, "resolved"


@effect_handler("pump_self_with_sacrifice_condition")
def pump_self_with_sacrifice_condition(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    source_permanent.power_bonus += 1
    source_permanent.metadata["temporary_power_bonus_until_eot"] = int(
        source_permanent.metadata.get("temporary_power_bonus_until_eot", 0)
    ) + 1
    activation_count = int(source_permanent.metadata.get("pump_activation_count", 0)) + 1
    source_permanent.metadata["pump_activation_count"] = activation_count
    if activation_count >= 4:
        source_permanent.metadata["sacrifice_at_next_end_step"] = True
    game.log.append(
        f"{card.name} gets +1/+0 until end of turn (activation {activation_count})"
    )
    return True, "resolved"


@effect_handler("pump_target_creature_until_eot")
def pump_target_creature_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    x_value = context.x_value
    raw_power = instruction.payload.get("power", 0)
    raw_toughness = instruction.payload.get("toughness", 0)
    power_delta = max(0, x_value or 0) if raw_power == "x" else int(raw_power)
    toughness_delta = max(0, x_value or 0) if raw_toughness == "x" else int(raw_toughness)
    blocking_only = bool(instruction.payload.get("blocking_only"))

    def _eligible(perm: Permanent) -> bool:
        if perm.card.primary_type != "creature":
            return False
        # Righteousness: the target must be a creature that is currently blocking.
        if blocking_only and not game._is_blocking_creature(perm):
            return False
        return True

    target_perm: Permanent | None = None
    if context.target_permanent_index is not None and 0 <= context.target_permanent_index < len(target.battlefield):
        candidate = target.battlefield[context.target_permanent_index]
        if _eligible(candidate):
            target_perm = candidate
    if target_perm is None:
        target_perm = next((p for p in target.battlefield if _eligible(p)), None)
    if target_perm is None:
        target_perm = next((p for p in caster.battlefield if _eligible(p)), None)
    if target_perm is not None:
        target_perm.power_bonus += power_delta
        target_perm.toughness_bonus += toughness_delta
        target_perm.metadata["temporary_power_bonus_until_eot"] = int(
            target_perm.metadata.get("temporary_power_bonus_until_eot", 0)
        ) + power_delta
        target_perm.metadata["temporary_toughness_bonus_until_eot"] = int(
            target_perm.metadata.get("temporary_toughness_bonus_until_eot", 0)
        ) + toughness_delta
        game.log.append(f"{card.name} gives {target_perm.card.name} +{power_delta}/+{toughness_delta} until end of turn")
    return True, "resolved"


# buff_creatures_global from a SPELL (sorcery/instant): locks in the set of
# affected creatures at resolution (611.2c). Uses power_bonus so it is NOT
# recalculated dynamically (unlike static abilities which use static_buff_*).
@effect_handler("buff_creatures_global")
def buff_creatures_global(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    card = context.card
    color_sym = instruction.payload.get("color")
    power_delta = int(instruction.payload.get("power", 0))
    toughness_delta = int(instruction.payload.get("toughness", 0))
    target_players = game.players if instruction.payload.get("all") else [caster]
    for player in target_players:
        for perm in list(player.battlefield):
            if perm.card.primary_type != "creature":
                continue
            actual_colors = set(perm.card.colors)
            if "color_override" in perm.metadata:
                actual_colors = {perm.metadata["color_override"]}
            if color_sym and color_sym not in actual_colors:
                continue
            perm.power_bonus += power_delta
            perm.toughness_bonus += toughness_delta
            perm.metadata["temporary_power_bonus_until_eot"] = (
                int(perm.metadata.get("temporary_power_bonus_until_eot", 0)) + power_delta
            )
            perm.metadata["temporary_toughness_bonus_until_eot"] = (
                int(perm.metadata.get("temporary_toughness_bonus_until_eot", 0)) + toughness_delta
            )
    game.log.append(f"{card.name} buffed matching creatures")
    return True, "resolved"


# switch_pt: switches a target creature's power and toughness (613.4d)
@effect_handler("switch_pt")
def switch_pt(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    target_perm: Permanent | None = None
    if context.target_permanent_index is not None and 0 <= context.target_permanent_index < len(target.battlefield):
        candidate = target.battlefield[context.target_permanent_index]
        if candidate.card.primary_type == "creature":
            target_perm = candidate
    if target_perm is None:
        target_perm = next((p for p in target.battlefield if p.card.primary_type == "creature"), None)
    if target_perm is None:
        target_perm = next((p for p in caster.battlefield if p.card.primary_type == "creature"), None)
    if target_perm is not None:
        target_perm.metadata["pt_switched"] = not target_perm.metadata.get("pt_switched", False)
        game.log.append(f"{card.name} switched power/toughness of {target_perm.card.name}")
    return True, "resolved"


# become_pt_until_eot: sets absolute power/toughness (layer 7b) until EOT
@effect_handler("become_pt_until_eot")
def become_pt_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    new_power = int(instruction.payload.get("power", 0))
    new_toughness = int(instruction.payload.get("toughness", 0))
    target_perm = None
    if context.target_permanent_index is not None and 0 <= context.target_permanent_index < len(target.battlefield):
        candidate = target.battlefield[context.target_permanent_index]
        if candidate.card.primary_type == "creature":
            target_perm = candidate
    if target_perm is None:
        target_perm = next((p for p in target.battlefield if p.card.primary_type == "creature"), None)
    if target_perm is None:
        target_perm = next((p for p in caster.battlefield if p.card.primary_type == "creature"), None)
    if target_perm is not None:
        target_perm.metadata["absolute_power_until_eot"] = new_power
        target_perm.metadata["absolute_toughness_until_eot"] = new_toughness
        game.log.append(f"{card.name} set {target_perm.card.name} to {new_power}/{new_toughness} until EOT")
    return True, "resolved"


@effect_handler("add_variable_power_counters_to_self")
def add_variable_power_counters_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Clockwork Beast: "{X}, {T}: Put up to X +1/+0 counters on this creature.
    # This ability can't cause the total number of +1/+0 counters on this
    # creature to be greater than seven."
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    current = int(source_permanent.metadata.get("plus_1_0_counters", 0))
    requested = max(0, context.x_value or 0)
    added = min(requested, max(0, 7 - current))
    if added:
        source_permanent.power_bonus += added
        source_permanent.metadata["plus_1_0_counters"] = current + added
    game.log.append(f"{card.name} gets {added} +1/+0 counter(s)")
    return True, "resolved"


@effect_handler("add_counter_to_self")
def add_counter_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    source_permanent.power_bonus += int(instruction.payload.get("power", 0))
    source_permanent.toughness_bonus += int(instruction.payload.get("toughness", 0))
    game.log.append(f"{card.name} gets a +1/+1 counter")
    return True, "resolved"


@effect_handler("grant_self_flying_until_eot")
def grant_self_flying_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    source_permanent.metadata["gains_flying_until_eot"] = True
    game.log.append(f"{card.name} gains flying until end of turn")
    return True, "resolved"


@effect_handler("grant_target_flying_until_eot")
def grant_target_flying_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    target_perm_idx = context.target_permanent_index
    target_creature = None
    if target_perm_idx is not None and 0 <= target_perm_idx < len(target.battlefield):
        candidate = target.battlefield[target_perm_idx]
        if candidate.card.primary_type == "creature":
            target_creature = candidate
    if target_creature is None:
        target_creature = next((p for p in target.battlefield if p.card.primary_type == "creature"), None)
    if target_creature is not None:
        target_creature.metadata["gains_flying_until_eot"] = True
        game.log.append(f"{target_creature.card.name} gains flying until end of turn from {card.name}")
    return True, "resolved"


@effect_handler("grant_flying_and_delayed_destruction")
def grant_flying_and_delayed_destruction(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"

    def _is_legal(perm) -> bool:
        return (
            perm.card.primary_type == "creature"
            and perm.effective_toughness < source_permanent.effective_power
        )

    # Honor the player-chosen creature (Stone Giant targets "target creature you
    # control with toughness less than this creature's power"). Fall back to the
    # first legal creature for AI/untargeted activations.
    target_creature = None
    idx = context.target_permanent_index
    if isinstance(idx, int) and 0 <= idx < len(caster.battlefield):
        candidate = caster.battlefield[idx]
        if _is_legal(candidate):
            target_creature = candidate
    if target_creature is None and not isinstance(idx, int):
        target_creature = next((perm for perm in caster.battlefield if _is_legal(perm)), None)
    if target_creature is not None:
        target_creature.metadata["gains_flying_until_eot"] = True
        target_creature.metadata["destroy_at_next_end_step"] = True
        game.log.append(f"{target_creature.card.name} gains temporary flying and delayed destruction")
    else:
        game.log.append("No valid target for Stone Giant effect")
    return True, "resolved"
