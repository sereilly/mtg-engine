from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Permanent
from ._common import apply_damage_to_creature, resolve_amount, resolve_target_permanent
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

    damage = resolve_amount(instruction.payload.get("amount", 0), x_value)
    target_perm_idx = context.target_permanent_index
    # Fireball's cross-seat divided list: any mix of creatures and player faces
    # on both sides, each dealt damage // n ("divided evenly, rounded down").
    if context.divided_targets:
        entries = [
            (seat, index)
            for seat, index in context.divided_targets
            if 0 <= seat < len(game.players)
            and (index is None or 0 <= index < len(game.players[seat].battlefield))
        ]
        n = len(entries)
        if n == 0:
            game.log.append(f"{card.name} had no remaining targets")
            return True, "resolved"
        per_target = damage // n
        # Creatures first (highest index first so removals can't shift earlier
        # indices), then faces.
        for seat, index in sorted(
            (e for e in entries if e[1] is not None), key=lambda e: e[1], reverse=True
        ):
            target_perm = game.players[seat].battlefield[index]
            dealt = game._mark_damage_on_permanent(target_perm, per_target, source=source_permanent or card)
            game.log.append(f"{card.name} dealt {dealt} damage to {target_perm.card.name}")
            if dealt > 0 and target_perm.damage_marked < target_perm.effective_toughness:
                game._fire_dealt_damage_triggers(target_perm)
        for seat, index in entries:
            if index is not None:
                continue
            face = game.players[seat]
            dealt = game._deal_damage_to_player(face, per_target, source=card)
            game.log.append(f"{card.name} dealt {dealt} damage to {face.name}")
        # Lethal damage destroys as a state-based action, which regeneration
        # shields can replace (CR 704.5g / 701.15).
        game._destroy_marked_creatures()
        return True, "resolved"
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
            dealt = game._mark_damage_on_permanent(target_perm, per_target, source=source_permanent or card)
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
            # is_creature (not the printed type line) so animated lands — Kormus
            # Bell swamps, Living Lands forests — count as creatures here.
            if not target_perm.is_creature and "planeswalker" not in type_line:
                game.log.append(
                    f"{card.name}: '{target_perm.card.name}' is not a valid 'any target' target (115.4)"
                )
                return True, "resolved"
        # A Jade Monolith redirect (source-aware) is handled inside
        # _mark_damage_on_permanent so combat and spell damage share one path.
        # Disintegrate-style riders: the damaged creature can't be regenerated
        # this turn, and if it would die this turn it is exiled instead (a
        # replacement effect honored by _destroy_marked_creatures / _permanent_to_graveyard).
        if target_perm.is_creature:
            if instruction.payload.get("no_regen"):
                target_perm.metadata["cant_be_regenerated_this_turn"] = True
            if instruction.payload.get("exile_if_dies"):
                target_perm.metadata["exile_if_dies_this_turn"] = True
        apply_damage_to_creature(
            game, target_perm, damage, source_permanent or card,
            log_message=lambda dealt: f"{card.name} dealt {dealt} damage to {target_perm.card.name}",
        )
    else:
        damage = game._deal_damage_to_player(target, damage, source=source_permanent or card)
        if source_permanent is not None:
            game.log.append(f"{card.name} dealt {damage} damage")
        else:
            game.log.append(f"{target.name} took {damage} damage")
    return True, "resolved"


@effect_handler("deal_damage_to_player")
def deal_damage_to_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """A triggered ability that deals a fixed amount of damage to a player, resolving
    off the stack. Used by triggers that previously dealt damage inline at fire time:
    Dingus Egg (land dies), the land-enters 2-damage trigger, and Aura death damage.
    The victim and amount are carried in ``trigger_context`` so a synthetic instruction
    (no parsed payload) is enough."""
    tctx = context.trigger_context or {}
    victim_idx = tctx.get("victim_player_index")
    amount = int(tctx.get("amount", 0))
    if victim_idx is None or not (0 <= victim_idx < len(game.players)) or amount <= 0:
        return True, "resolved"
    victim = game.players[victim_idx]
    dealt = game._deal_damage_to_player(victim, amount, source=context.source_permanent)
    game.log.append(f"{context.card.name} dealt {dealt} damage to {victim.name}")
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

    target_perm = resolve_target_permanent(context, player=caster)
    if target_perm is None:
        game.log.append(f"{card.name}: no creature to deal damage to")
        return True, "resolved"

    apply_damage_to_creature(
        game, target_perm, amount, card,
        log_message=lambda dealt: (
            f"{card.name} dealt {dealt} damage to {target_perm.card.name} and {caster.name} gained {amount} life"
        ),
    )
    return True, "resolved"


@effect_handler("deal_damage_each_creature_and_player")
def deal_damage_each_creature_and_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    amount = int(instruction.payload.get("amount", 1))
    _mass_damage_players_and_creatures(game, card, amount, lambda perm: True)
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
        dealt = game._mark_damage_on_permanent(target_perm, amount, source=card)
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
    damage = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    target_perm_idx = context.target_permanent_index
    # Drain Life is an "any target" spell — it may hit a creature. Deal to the
    # chosen creature and gain life equal to the damage actually dealt (capped by
    # its toughness, mirroring the card's life-gain limit).
    if isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(target.battlefield):
        target_perm = target.battlefield[target_perm_idx]
        if target_perm.is_creature:
            dealt = apply_damage_to_creature(
                game, target_perm, damage, card,
                log_message=lambda dealt: f"{card.name} dealt {dealt} damage to {target_perm.card.name}",
            )
            game._gain_life(caster, dealt, card.name)
            return True, "resolved"
    damage = game._deal_damage_to_player(target, damage, source=card)
    game.log.append(f"{card.name} dealt {damage} damage to {target.name}")
    game._gain_life(caster, damage, card.name)
    return True, "resolved"


def _has_flying(perm: Permanent) -> bool:
    return bool(
        "Flying" in perm.card.keywords
        or perm.metadata.get("gains_flying")
        or perm.metadata.get("gains_flying_until_eot")
    )


def _mass_damage_players_and_creatures(game: Game, card, damage: int, creature_predicate) -> None:
    """Earthquake/Hurricane sweep: damage every player, then every creature
    passing the predicate, then destroy the lethally damaged as one SBA batch."""
    for player in game.players:
        game._deal_damage_to_player(player, damage, source=card)
    for player in game.players:
        for perm in list(player.battlefield):
            if perm.is_creature and creature_predicate(perm):
                game._mark_damage_on_permanent(perm, damage, source=card)
    game._destroy_marked_creatures()


@effect_handler("earthquake_damage")
def earthquake_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    damage = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    _mass_damage_players_and_creatures(game, card, damage, lambda perm: not _has_flying(perm))
    game.log.append(f"{card.name} dealt {damage} earthquake damage to each non-flying creature and each player")
    return True, "resolved"


@effect_handler("hurricane_damage")
def hurricane_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    damage = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    _mass_damage_players_and_creatures(game, card, damage, _has_flying)
    game.log.append(f"{card.name} dealt {damage} hurricane damage to each flying creature and each player")
    return True, "resolved"
