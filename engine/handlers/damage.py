from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Permanent, PlayerState
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("deal_damage")
def deal_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    source_permanent = context.source_permanent
    x_value = context.x_value

    amount = instruction.payload.get("amount", 0)
    damage = max(0, x_value or 0) if amount == "x" else int(amount)
    target_perm_idx = context.target_permanent_index
    # Support multiple target indices for spells like Fireball
    if isinstance(target_perm_idx, list):
        indices = [i for i in target_perm_idx if isinstance(i, int) and 0 <= i < len(target.battlefield)]
        n = len(indices)
        if n == 0:
            # No valid creature targets; treat as player damage
            damage = game._deal_damage_to_player(target, damage, source=card)
            game.log.append(f"{target.name} took {damage} damage")
            return True, "resolved"
        per_target = damage // n if n > 0 else 0
        for idx in sorted(indices, reverse=True):
            target_perm = target.battlefield[idx]
            dealt = game._mark_damage_on_permanent(target_perm, per_target)
            game.log.append(f"{card.name} dealt {dealt} damage to {target_perm.card.name}")
            if dealt > 0 and target_perm.damage_marked < target_perm.effective_toughness:
                game._fire_dealt_damage_triggers(target_perm)
        # Lethal damage destroys as a state-based action, which regeneration
        # shields can replace (CR 704.5g / 701.15).
        game._destroy_marked_creatures()
        return True, "resolved"
    if target_perm_idx is not None and isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(target.battlefield):
        # Damage targets a creature permanent, not the player
        target_perm = target.battlefield[target_perm_idx]
        # 115.4: "any target" is limited to creatures, players, planeswalkers, and battles.
        # Noncreature artifacts (and other noncreature non-planeswalker permanents) are not
        # valid "any target" targets — the spell fizzles against them.
        if "any target" in card.oracle_text.lower():
            type_line = target_perm.card.type_line.lower()
            if "creature" not in type_line and "planeswalker" not in type_line:
                game.log.append(
                    f"{card.name}: '{target_perm.card.name}' is not a valid 'any target' target (115.4)"
                )
                return True, "resolved"
        redirect_idx = target_perm.metadata.pop("redirect_damage_to_player", None)
        if redirect_idx is not None and 0 <= redirect_idx < len(game.players):
            redirect_player = game.players[redirect_idx]
            d = game._deal_damage_to_player(redirect_player, damage)
            game.log.append(f"Jade Monolith redirected {d} damage to {redirect_player.name}")
            return True, "resolved"
        # Disintegrate-style riders: the damaged creature can't be regenerated
        # this turn, and if it would die this turn it is exiled instead (a
        # replacement effect honored by _destroy_marked_creatures / _permanent_to_graveyard).
        if target_perm.card.primary_type == "creature":
            if instruction.payload.get("no_regen"):
                target_perm.metadata["cant_be_regenerated_this_turn"] = True
            if instruction.payload.get("exile_if_dies"):
                target_perm.metadata["exile_if_dies_this_turn"] = True
        dealt = game._mark_damage_on_permanent(target_perm, damage)
        effective_toughness = target_perm.effective_toughness
        game.log.append(f"{card.name} dealt {dealt} damage to {target_perm.card.name}")
        if target_perm.damage_marked >= effective_toughness:
            # Lethal damage destroys as a state-based action, which regeneration
            # shields can replace (CR 704.5g / 701.15).
            game._destroy_marked_creatures()
        elif dealt > 0:
            game._fire_dealt_damage_triggers(target_perm)
    else:
        damage = game._deal_damage_to_player(target, damage, source=source_permanent or card)
        if source_permanent is not None:
            game.log.append(f"{card.name} dealt {damage} damage")
        else:
            game.log.append(f"{target.name} took {damage} damage")
    return True, "resolved"


@effect_handler("simulacrum_redirect")
def simulacrum_redirect(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Simulacrum: caster gains life equal to the damage dealt to them this turn,
    # then deals that much damage to a target creature they control.
    caster = context.caster
    card = context.card
    amount = max(0, caster.damage_taken_this_turn)

    if amount > 0:
        game._gain_life(caster, amount, card.name)

    target_perm_idx = context.target_permanent_index
    target_perm = None
    if isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(caster.battlefield):
        candidate = caster.battlefield[target_perm_idx]
        if candidate.card.primary_type == "creature":
            target_perm = candidate
    if target_perm is None:
        target_perm = next((p for p in caster.battlefield if p.card.primary_type == "creature"), None)

    if target_perm is None:
        game.log.append(f"{card.name}: no creature to deal damage to")
        return True, "resolved"

    dealt = game._mark_damage_on_permanent(target_perm, amount)
    game.log.append(f"{card.name} dealt {dealt} damage to {target_perm.card.name} and {caster.name} gained {amount} life")
    if dealt > 0 and target_perm.damage_marked >= target_perm.effective_toughness:
        # Lethal damage destroys as a state-based action, which regeneration
        # shields can replace (CR 704.5g / 701.15).
        game._destroy_marked_creatures()
    elif dealt > 0:
        game._fire_dealt_damage_triggers(target_perm)
    return True, "resolved"


@effect_handler("deal_damage_each_creature_and_player")
def deal_damage_each_creature_and_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    amount = int(instruction.payload.get("amount", 1))
    for player in game.players:
        game._deal_damage_to_player(player, amount, source=card)
    dead: list[tuple[PlayerState, Permanent]] = []
    for player in game.players:
        for perm in player.battlefield:
            if perm.card.primary_type == "creature":
                game._mark_damage_on_permanent(perm, amount)
                if perm.damage_marked >= perm.effective_toughness:
                    dead.append((player, perm))
    for player, perm in dead:
        if perm in player.battlefield:
            player.battlefield.remove(perm)
            player.graveyard.append(perm.card)
            game.log.append(f"{perm.card.name} died from {card.name}")
    game.log.append(f"{card.name} dealt {amount} damage to each creature and each player")
    return True, "resolved"


@effect_handler("deal_damage_and_self_damage")
def deal_damage_and_self_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    amount = int(instruction.payload.get("amount", 0))
    self_damage = int(instruction.payload.get("self_damage", 0))
    target_perm_idx = context.target_permanent_index
    if isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(target.battlefield):
        target_perm = target.battlefield[target_perm_idx]
        dealt = game._mark_damage_on_permanent(target_perm, amount)
        game.log.append(f"{card.name} dealt {dealt} damage to {target_perm.card.name}")
        if target_perm.damage_marked >= target_perm.effective_toughness:
            # Lethal damage destroys as a state-based action, which regeneration
            # shields can replace (CR 704.5g / 701.15).
            game._destroy_marked_creatures()
    else:
        damage = game._deal_damage_to_player(target, amount, source=card)
        game.log.append(f"{card.name} dealt {damage} damage to {target.name}")
    self_damage = game._deal_damage_to_player(caster, self_damage, source=card)
    game.log.append(f"{card.name} dealt {self_damage} damage to {caster.name} (self-damage)")
    return True, "resolved"


@effect_handler("deal_damage_and_gain_life")
def deal_damage_and_gain_life(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    x_value = context.x_value
    amount = instruction.payload.get("amount", 0)
    damage = max(0, x_value or 0) if amount == "x" else int(amount)
    target_perm_idx = context.target_permanent_index
    # Drain Life is an "any target" spell — it may hit a creature. Deal to the
    # chosen creature and gain life equal to the damage actually dealt (capped by
    # its toughness, mirroring the card's life-gain limit).
    if isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(target.battlefield):
        target_perm = target.battlefield[target_perm_idx]
        if target_perm.card.primary_type == "creature":
            dealt = game._mark_damage_on_permanent(target_perm, damage)
            game.log.append(f"{card.name} dealt {dealt} damage to {target_perm.card.name}")
            if target_perm.damage_marked >= target_perm.effective_toughness:
                game._destroy_marked_creatures()
            elif dealt > 0:
                game._fire_dealt_damage_triggers(target_perm)
            game._gain_life(caster, dealt, card.name)
            return True, "resolved"
    damage = game._deal_damage_to_player(target, damage, source=card)
    game.log.append(f"{card.name} dealt {damage} damage to {target.name}")
    game._gain_life(caster, damage, card.name)
    return True, "resolved"


@effect_handler("earthquake_damage")
def earthquake_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    x_value = context.x_value
    amount = instruction.payload.get("amount", 0)
    damage = max(0, x_value or 0) if amount == "x" else int(amount)
    # Deal damage to each player
    for player in game.players:
        game._deal_damage_to_player(player, damage, source=card)
    # Deal damage to each creature without flying on every battlefield
    for player in game.players:
        for perm in list(player.battlefield):
            if perm.card.primary_type != "creature":
                continue
            has_flying = (
                "Flying" in perm.card.keywords
                or perm.metadata.get("gains_flying")
                or perm.metadata.get("gains_flying_until_eot")
            )
            if has_flying:
                continue
            game._mark_damage_on_permanent(perm, damage)
    game._destroy_marked_creatures()
    game.log.append(f"{card.name} dealt {damage} earthquake damage to each non-flying creature and each player")
    return True, "resolved"


@effect_handler("hurricane_damage")
def hurricane_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    x_value = context.x_value
    amount = instruction.payload.get("amount", 0)
    damage = max(0, x_value or 0) if amount == "x" else int(amount)
    for player in game.players:
        game._deal_damage_to_player(player, damage, source=card)
    for player in game.players:
        for perm in list(player.battlefield):
            if perm.card.primary_type != "creature":
                continue
            has_flying = (
                "Flying" in perm.card.keywords
                or perm.metadata.get("gains_flying")
                or perm.metadata.get("gains_flying_until_eot")
            )
            if not has_flying:
                continue
            game._mark_damage_on_permanent(perm, damage)
    game._destroy_marked_creatures()
    game.log.append(f"{card.name} dealt {damage} hurricane damage to each flying creature and each player")
    return True, "resolved"
