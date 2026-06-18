from __future__ import annotations

from typing import TYPE_CHECKING

from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("untap_self")
def untap_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    if not source_permanent.tapped:
        return False, f"{card.name} is already untapped"
    source_permanent.tapped = False
    game.log.append(f"{card.name} untapped itself")
    return True, "resolved"


@effect_handler("untap_target_land")
def untap_target_land(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    untapped = False
    # Honor an explicitly chosen land (Ley Druid: "{T}: Untap target land" — the
    # player picks which land). Fall back to the first land the target controls.
    idx = context.target_permanent_index
    if isinstance(idx, int) and 0 <= idx < len(target.battlefield):
        chosen = target.battlefield[idx]
        if chosen.card.primary_type == "land":
            chosen.tapped = False
            untapped = True
    if not untapped and not isinstance(idx, int):
        for perm in target.battlefield:
            if perm.card.primary_type == "land":
                perm.tapped = False
                untapped = True
                break
    game.log.append("Untapped target land" if untapped else "No land to untap")
    return True, "resolved"


@effect_handler("untap_target_permanent")
def untap_target_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    untapped = game._tap_or_untap_target(target, make_tapped=False)
    game.log.append("Untapped target permanent" if untapped else "No valid permanent to untap")
    return True, "resolved"


@effect_handler("untap_enchanted_creature")
def untap_enchanted_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    attached_to = source_permanent.metadata.get("attached_to")
    if attached_to is not None:
        attached_to.tapped = False
        game.log.append(f"Untapped {attached_to.card.name} via {card.name}")
    return True, "resolved"


@effect_handler("tap_target_permanent")
def tap_target_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    tapped = game._tap_or_untap_target(target, make_tapped=True)
    game.log.append("Tapped target permanent" if tapped else "No valid permanent to tap")
    return True, "resolved"


@effect_handler("tap_target_player_lands_and_drain_mana")
def tap_target_player_lands_and_drain_mana(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    for perm in target.battlefield:
        if perm.card.primary_type == "land":
            perm.tapped = True
    for sym in ("W", "U", "B", "R", "G", "C"):
        target.mana_pool[sym] = 0
    game.log.append(f"{card.name} tapped all lands and drained mana from {target.name}")
    return True, "resolved"
