from __future__ import annotations

from typing import TYPE_CHECKING

from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("delayed_destroy_blocked_or_blocker")
def delayed_destroy_blocked_or_blocker(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Resolve Cockatrice / Thicket Basilisk's block trigger (Rule 509.2a).

    The trigger was put on the stack when blockers were declared; on resolution
    it marks the creature it blocked / that blocked it for destruction at end of
    combat. The victim is identified by the stack item's target indices, captured
    at declaration time (509.3f).
    """
    target = context.target
    idx = context.target_permanent_index
    victim = target.battlefield[idx] if isinstance(idx, int) and 0 <= idx < len(target.battlefield) else None
    if victim is None:
        game.log.append(f"{context.card.name} block trigger had no valid target")
        return True, "no target"
    victim.metadata["destroy_at_end_of_combat"] = True
    game.log.append(f"{context.card.name} will destroy {victim.card.name} at end of combat")
    return True, "resolved"


@effect_handler("grant_unlimited_blocking")
def grant_unlimited_blocking(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    blocker = next((perm for perm in target.battlefield if perm.card.primary_type == "creature"), None)
    if blocker is not None:
        blocker.metadata["must_block_all_until_eot"] = True
    game.log.append(f"{card.name} created a forced blocking assignment")
    return True, "resolved"


@effect_handler("randomize_blockers")
def randomize_blockers(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    game.log.append(f"{card.name} set up random pile blocking this turn")
    return True, "resolved"


@effect_handler("remove_creature_from_combat")
def remove_creature_from_combat(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    removed = next((perm for perm in target.battlefield if perm.card.primary_type == "creature"), None)
    if removed is not None:
        removed.metadata["removed_from_combat"] = True
    game.log.append(f"{card.name} removed a blocker from combat")
    return True, "resolved"


@effect_handler("left_right_combat_division")
def left_right_combat_division(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    # Record that the division was established this combat so the rest of the
    # engine (and tests) can observe that the attack trigger actually fired.
    if context.source_permanent is not None:
        context.source_permanent.metadata["left_right_division_turn"] = game.turn
    game.combat_left_right_active = True
    game.combat_left_right_defender_index = game.combat_defending_player_index

    # Seed a sensible default division so AI/headless combat still resolves: the
    # defending player's non-flying creatures alternate left/right, and every
    # attacker defaults to "left". The UI lets both players override these before
    # blocks are declared (assign_defender_piles / assign_attacker_piles).
    defender_index = game.combat_defending_player_index
    if isinstance(defender_index, int) and 0 <= defender_index < len(game.players):
        defender = game.players[defender_index]
        game.combat_defender_piles = {}
        side_toggle = 0
        for idx, perm in enumerate(defender.battlefield):
            if perm.card.primary_type != "creature":
                continue
            if game._has_keyword(perm, "flying"):
                continue  # flyers are in neither pile (they may block anything)
            game.combat_defender_piles[idx] = "left" if side_toggle % 2 == 0 else "right"
            side_toggle += 1
    game.combat_attacker_piles = {idx: "left" for idx in game.combat_attackers}
    game.log.append(f"{card.name} established left/right combat division")
    return True, "resolved"


@effect_handler("prevent_all_combat_damage")
def prevent_all_combat_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    game.combat_damage_prevented_until_eot = True
    game.log.append("Combat damage prevented until end of turn")
    return True, "resolved"


@effect_handler("mark_non_wall_target_to_attack")
def mark_non_wall_target_to_attack(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    target_creature = next(
        (
            perm
            for perm in target.battlefield
            if perm.card.primary_type == "creature" and "wall" not in perm.card.type_line.lower()
        ),
        None,
    )
    if target_creature is not None:
        target_creature.metadata["must_attack_until_eot"] = True
        target_creature.metadata["destroy_if_did_not_attack_eot"] = True
        game.log.append(f"{target_creature.card.name} marked to attack this turn")
    else:
        game.log.append("No non-Wall target for Nettling Imp effect")
    return True, "resolved"


@effect_handler("force_active_player_creatures_to_attack")
def force_active_player_creatures_to_attack(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    active = game.players[game.active_player_index]
    marked: list[str] = []
    for permanent in active.battlefield:
        if permanent.card.primary_type != "creature":
            continue
        permanent.metadata["must_attack_until_eot"] = True
        is_wall = "wall" in permanent.card.type_line.lower()
        # "Ignore this effect for each creature the player didn't control
        # continuously since the beginning of the turn."
        entered_this_turn = permanent.metadata.get("summoning_sickness_turn") == game.turn
        if not is_wall and not entered_this_turn:
            permanent.metadata["destroy_if_did_not_attack_eot"] = True
        marked.append(permanent.card.name)
    if marked:
        game.log.append(f"{context.card.name} forces {', '.join(marked)} to attack this turn")
    else:
        game.log.append(f"{context.card.name} resolved with no creatures to force into combat")
    return True, "resolved"


@effect_handler("grant_unblockable_to_low_power_target")
def grant_unblockable_to_low_power_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    target_creature = next(
        (perm for perm in target.battlefield if perm.card.primary_type == "creature" and perm.effective_power <= 2),
        None,
    )
    if target_creature is not None:
        target_creature.metadata["cant_be_blocked_until_eot"] = True
        game.log.append(f"{target_creature.card.name} can't be blocked this turn")
    else:
        game.log.append("No valid low-power creature for unblockable effect")
    return True, "resolved"


@effect_handler("grant_banding_to_target")
def grant_banding_to_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    # Banding is granted to one of the controller's own creatures, not the opponent's.
    target_creature = next((perm for perm in caster.battlefield if perm.card.primary_type == "creature"), None)
    if target_creature is None:
        game.log.append("No valid creature target for banding effect")
        return False, "no valid creature target for banding effect"
    target_creature.metadata["gains_banding_until_eot"] = True
    game.log.append(f"{target_creature.card.name} gains banding until end of turn")
    return True, "resolved"
