from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Permanent
from ..pt import add_pt_modifier, set_base_pt
from ._common import apply_temp_pt_boost, resolve_amount, resolve_target_permanent
from .registry import effect_handler
from ..keywords import grant_keyword

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("berserk_pump")
def berserk_pump(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    target_perm = resolve_target_permanent(game, context)
    if target_perm is not None:
        boost = target_perm.effective_power
        # "+X/+0 until end of turn" — apply now and track it so cleanup removes it
        # if the creature survives (Berserk only destroys it if it attacked).
        apply_temp_pt_boost(target_perm, boost)
        grant_keyword(target_perm, "trample", until_eot=True)
        # "At the beginning of the next end step, destroy that creature if it
        # attacked this turn." Mark it; the end step checks attacked_this_turn.
        target_perm.metadata["destroy_if_attacked_eot"] = True
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
    apply_temp_pt_boost(enchanted, power_delta, toughness_delta)
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
    apply_temp_pt_boost(source_permanent, power_delta, toughness_delta)
    game.log.append(f"{card.name} gets +{power_delta}/+{toughness_delta} until end of turn")
    return True, "resolved"


@effect_handler("pump_self_with_sacrifice_condition")
def pump_self_with_sacrifice_condition(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    apply_temp_pt_boost(source_permanent, 1)
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
    power_delta = resolve_amount(instruction.payload.get("power", 0), x_value)
    toughness_delta = resolve_amount(instruction.payload.get("toughness", 0), x_value)
    blocking_only = bool(instruction.payload.get("blocking_only"))

    def _eligible(perm: Permanent) -> bool:
        if not perm.is_creature:
            return False
        # Righteousness: the target must be a creature that is currently blocking.
        if blocking_only and not game._is_blocking_creature(perm):
            return False
        return True

    target_perm = resolve_target_permanent(
        game, context, predicate=_eligible, fallback_players=(target, caster)
    )
    if target_perm is not None:
        apply_temp_pt_boost(target_perm, power_delta, toughness_delta)
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
    attacking_only = bool(instruction.payload.get("attacking_only"))
    blocking_only = bool(instruction.payload.get("blocking_only"))
    target_players = game.players if instruction.payload.get("all") else [caster]
    for player in target_players:
        for perm in list(player.battlefield):
            if not perm.is_creature:
                continue
            # Army of Allah: only creatures attacking at resolution are buffed.
            if attacking_only and not perm.attacking:
                continue
            # Piety: only creatures blocking at resolution are buffed.
            if blocking_only and not game._is_blocking_creature(perm):
                continue
            actual_colors = set(perm.card.colors)
            if "color_override" in perm.metadata:
                actual_colors = {perm.metadata["color_override"]}
            if color_sym and color_sym not in actual_colors:
                continue
            apply_temp_pt_boost(perm, power_delta, toughness_delta)
    game.log.append(f"{card.name} buffed matching creatures")
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


@effect_handler("add_plus1_counters_for_each_creature_died")
def add_plus1_counters_for_each_creature_died(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Khabál Ghoul: "At the beginning of each end step, put a +1/+1 counter on
    this creature for each creature that died this turn." Resolves off the stack;
    the death count is captured in trigger_context at fire time."""
    source = context.source_permanent
    count = int((context.trigger_context or {}).get("count", 0))
    if source is None or count <= 0:
        return True, "resolved"
    source.power_bonus += count * int(instruction.payload.get("power", 1))
    source.toughness_bonus += count * int(instruction.payload.get("toughness", 1))
    game.log.append(f"{source.card.name} gets {count} +1/+1 counter(s)")
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


@effect_handler("add_counter_to_target")
def add_counter_to_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a +1/+1 counter on target creature." The kind Dwarven
    Weaponsmith's hook has always emitted (it resolved to nothing before this
    handler existed) and the grammar now lowers to as well."""
    card = context.card
    target_creature = resolve_target_permanent(game, context)
    if target_creature is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    add_pt_modifier(
        target_creature,
        int(instruction.payload.get("power", 1)),
        int(instruction.payload.get("toughness", 1)),
    )
    game.log.append(f"{target_creature.card.name} gets a +1/+1 counter ({card.name})")
    return True, "resolved"


@effect_handler("add_counter_to_each_you_control")
def add_counter_to_each_you_control(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a +1/+1 counter on each creature you control." (Basri's
    Solidarity.) Read through the control seam, so a borrowed creature counts
    and a lost one does not."""
    card = context.card
    caster = context.caster
    for perm in game.controlled_by(caster):
        if not perm.is_creature:
            continue
        add_pt_modifier(
            perm,
            int(instruction.payload.get("power", 1)),
            int(instruction.payload.get("toughness", 1)),
        )
    game.log.append(f"{card.name}: each creature {caster.name} controls gets a +1/+1 counter")
    return True, "resolved"


@effect_handler("grant_self_flying_until_eot")
def grant_self_flying_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    grant_keyword(source_permanent, "flying", until_eot=True)
    game.log.append(f"{card.name} gains flying until end of turn")
    return True, "resolved"


@effect_handler("grant_target_flying_until_eot")
def grant_target_flying_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    target_creature = resolve_target_permanent(game, context)
    if target_creature is not None:
        grant_keyword(target_creature, "flying", until_eot=True)
        game.log.append(f"{target_creature.card.name} gains flying until end of turn from {card.name}")
    return True, "resolved"


@effect_handler("grant_islandwalk_and_linked_destroy")
def grant_islandwalk_and_linked_destroy(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Sandals of Abdallah: "Target creature gains islandwalk until end of
    turn. When that creature dies this turn, destroy this artifact." The grant
    is an until-end-of-turn layer-6 grant; the death link is recorded on the
    creature and drained by _permanent_to_graveyard + the state-based sweep."""
    card = context.card
    source_permanent = context.source_permanent
    target_creature = resolve_target_permanent(game, context)
    if target_creature is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    grant_keyword(target_creature, "islandwalk", until_eot=True)
    if source_permanent is not None:
        links = target_creature.metadata.setdefault("on_death_destroy_permanents", [])
        if source_permanent not in links:
            links.append(source_permanent)
    game.log.append(f"{target_creature.card.name} gains islandwalk until end of turn ({card.name})")
    return True, "resolved"


@effect_handler("set_base_pt_target_until_eot")
def set_base_pt_target_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Sorceress Queen ("has base power and toughness 0/2") / Singing Tree
    ("has base power 0", toughness untouched). ``payload["toughness"]`` is
    None when the ability only sets power."""
    card = context.card
    source_permanent = context.source_permanent
    exclude_self = bool(instruction.payload.get("exclude_self"))
    attacking_only = bool(instruction.payload.get("attacking_only"))
    flying_only = bool(instruction.payload.get("flying_only"))

    def _eligible(perm: Permanent) -> bool:
        if not perm.is_creature:
            return False
        if exclude_self and source_permanent is not None and perm is source_permanent:
            return False
        if attacking_only and not perm.attacking:
            return False
        if flying_only and not game._has_keyword(perm, "flying"):
            return False
        return True

    target_perm = resolve_target_permanent(game, context, predicate=_eligible)
    if target_perm is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"

    power = instruction.payload.get("power")
    toughness = instruction.payload.get("toughness")
    set_base_pt(target_perm, power, toughness, until_eot=True)
    if toughness is None:
        game.log.append(f"{card.name}: {target_perm.card.name} has base power {power} until end of turn")
    else:
        game.log.append(
            f"{card.name}: {target_perm.card.name} has base power and toughness {power}/{toughness} until end of turn"
        )
    return True, "resolved"


@effect_handler("grant_flying_and_delayed_destruction")
def grant_flying_and_delayed_destruction(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"

    def _is_legal(perm) -> bool:
        return (
            perm.is_creature
            and perm.effective_toughness < source_permanent.effective_power
        )

    # Honor the player-chosen creature (Stone Giant targets "target creature you
    # control with toughness less than this creature's power"). Fall back to the
    # first legal creature only for AI/untargeted activations — an explicitly
    # chosen illegal target fizzles.
    target_creature = resolve_target_permanent(
        game, context, player=caster, predicate=_is_legal, fallback_on_invalid_choice=False
    )
    if target_creature is not None:
        grant_keyword(target_creature, "flying", until_eot=True)
        target_creature.metadata["destroy_at_next_end_step"] = True
        game.log.append(f"{target_creature.card.name} gains temporary flying and delayed destruction")
    else:
        game.log.append("No valid target for Stone Giant effect")
    return True, "resolved"
