from __future__ import annotations

import random
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
    # Blaze of Glory: "Target creature defending player controls can block any number
    # of creatures this turn. It blocks each attacking creature this turn if able."
    # Honor the chosen creature; fall back to the first only for AI/headless play.
    target = context.target
    card = context.card
    idx = context.target_permanent_index
    blocker = None
    if isinstance(idx, int) and 0 <= idx < len(target.battlefield):
        if target.battlefield[idx].card.primary_type == "creature":
            blocker = target.battlefield[idx]
    if blocker is None:
        blocker = next((perm for perm in target.battlefield if perm.card.primary_type == "creature"), None)
    if blocker is not None:
        # Lets it block any number of attackers (_max_blocks_for) and requires it to
        # block each attacker it can (enforced when blocks are declared).
        blocker.metadata["can_block_any_number_until_eot"] = True
        blocker.metadata["must_block_all_until_eot"] = True
        game.log.append(f"{card.name}: {blocker.card.name} can block any number of creatures this turn")
    else:
        game.log.append(f"{card.name} found no creature to grant unlimited blocking")
    return True, "resolved"


@effect_handler("randomize_blockers")
def randomize_blockers(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    # Camouflage: mark this turn so the defending player's blocks are assigned by
    # random pile (resolve_camouflage_blocking) rather than chosen this combat.
    game.camouflage_active_turn = game.turn
    game.log.append(f"{card.name} set up random pile blocking this turn")
    return True, "resolved"


@effect_handler("remove_creature_from_combat")
def remove_creature_from_combat(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # False Orders: "Remove target creature defending player controls from combat.
    # Creatures it was blocking that had become blocked by only that creature this
    # combat become unblocked." Honor the chosen blocker; fall back to the first
    # creature only when no explicit target was supplied (AI/headless).
    target = context.target
    card = context.card
    idx = context.target_permanent_index
    removed_index: int | None = None
    if isinstance(idx, int) and 0 <= idx < len(target.battlefield):
        if target.battlefield[idx].card.primary_type == "creature":
            removed_index = idx
    if removed_index is None:
        removed_index = next(
            (i for i, perm in enumerate(target.battlefield) if perm.card.primary_type == "creature"),
            None,
        )
    if removed_index is None:
        game.log.append(f"{card.name} had no creature to remove from combat")
        return True, "resolved"

    removed = target.battlefield[removed_index]
    removed.metadata["removed_from_combat"] = True

    # If this creature is currently blocking, take it out of combat: drop it as a
    # blocker and unblock any attacker whose only blocker it was.
    target_player_index = game.players.index(target)
    if target_player_index == game.combat_defending_player_index and removed_index in game.combat_blockers:
        freed_attackers = list(game.combat_blockers.get(removed_index, []))
        game.combat_blockers.pop(removed_index, None)
        game.combat_band_blocks.pop(removed_index, None)
        removed.blocking_attacker_controller = None
        removed.blocking_attacker_index = None
        active = game.players[game.active_player_index]
        for a_idx in freed_attackers:
            still_blocked = any(a_idx in atks for atks in game.combat_blockers.values())
            if not still_blocked and 0 <= a_idx < len(active.battlefield):
                active.battlefield[a_idx].blocked = False
        # CR 702.22h: band block propagation is recomputed from combat_blockers.
        game._apply_band_block_propagation()

    game.log.append(f"{card.name} removed {removed.card.name} from combat")
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
    # A fresh attack re-opens both players' pile decisions.
    game.combat_left_right_defender_locked = False
    game.combat_left_right_attacker_locked = False

    # Seed a sensible default division so AI/headless combat still resolves: the
    # defending player's non-flying creatures are split into left/right at random,
    # and every attacker defaults to "left". This doubles as the AI's actual choice
    # (an AI defender "chooses randomly"); a human overrides it via the UI before
    # blocks are declared (assign_defender_piles / assign_attacker_piles). The
    # module RNG is seeded in AI simulations, so a seeded run stays reproducible.
    defender_index = game.combat_defending_player_index
    if isinstance(defender_index, int) and 0 <= defender_index < len(game.players):
        defender = game.players[defender_index]
        game.combat_defender_piles = {}
        for idx, perm in enumerate(defender.battlefield):
            if perm.card.primary_type != "creature":
                continue
            if game._has_keyword(perm, "flying"):
                continue  # flyers are in neither pile (they may block anything)
            game.combat_defender_piles[idx] = random.choice(("left", "right"))
    game.combat_attacker_piles = {idx: random.choice(("left", "right")) for idx in game.combat_attackers}
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
    # Helm of Chatzuk: "{1}, {T}: Target creature gains banding until end of turn."
    # Honor the chosen target (any creature, on either battlefield); fall back to
    # the first creature only when no explicit target was supplied (AI/headless).
    target = context.target
    idx = context.target_permanent_index
    target_creature = None
    if isinstance(idx, int) and 0 <= idx < len(target.battlefield):
        candidate = target.battlefield[idx]
        if candidate.card.primary_type == "creature":
            target_creature = candidate
    if target_creature is None:
        target_creature = next((perm for perm in target.battlefield if perm.card.primary_type == "creature"), None)
    if target_creature is None:
        game.log.append("No valid creature target for banding effect")
        return False, "no valid creature target for banding effect"
    target_creature.metadata["gains_banding_until_eot"] = True
    game.log.append(f"{target_creature.card.name} gains banding until end of turn")
    return True, "resolved"
