from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import permanent_matches_filter, resolve_target_permanent
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
    # Honor an explicitly chosen land (Ley Druid: "{T}: Untap target land" — the
    # player picks which land). Fall back to the first land the target controls
    # only when no explicit choice was made.
    perm = resolve_target_permanent(
        context,
        predicate=lambda p: p.card.primary_type == "land",
        fallback_on_invalid_choice=False,
    )
    if perm is not None:
        perm.tapped = False
    game.log.append("Untapped target land" if perm is not None else "No land to untap")
    return True, "resolved"


@effect_handler("untap_target_permanent")
def untap_target_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    untapped = game._tap_or_untap_target(
        target, make_tapped=False, target_permanent_index=context.target_permanent_index
    )
    game.log.append("Untapped target permanent" if untapped else "No valid permanent to untap")
    return True, "resolved"


@effect_handler("untap_attacker_and_prevent_combat_damage")
def untap_attacker_and_prevent_combat_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Ebony Horse: untap the chosen attacking creature you control and shield
    # it — all combat damage that would be dealt to or by it this turn is
    # prevented (the flag is honored in combat_damage_step and cleared in
    # cleanup via _EOT_METADATA_KEYS).
    caster = context.caster
    perm = resolve_target_permanent(
        context,
        predicate=lambda p: p.is_creature and p.attacking and game.controls(caster, p),
        fallback_players=(caster,),
        fallback_on_invalid_choice=False,
    )
    if perm is None:
        game.log.append(f"{context.card.name}: no attacking creature you control to untap")
        return True, "resolved"
    perm.tapped = False
    perm.metadata["prevent_combat_damage_to_and_by_until_eot"] = True
    game.log.append(
        f"{context.card.name} untapped {perm.card.name}; all combat damage to and by it is prevented this turn"
    )
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
    # Ali Baba: "Tap target Wall." — the parsed noun-phrase filter restricts
    # what the ability may tap; an explicitly chosen non-matching permanent
    # fizzles rather than falling back to an arbitrary one.
    if any(k in instruction.payload for k in ("type_filter", "subtype_filter", "color_filter")):
        caster = context.caster
        perm = resolve_target_permanent(
            context,
            predicate=lambda p: permanent_matches_filter(p, instruction.payload),
            fallback_players=(target, caster),
            fallback_on_invalid_choice=False,
        )
        if perm is not None:
            game.become_tapped(perm)
            game._turn_face_up(perm)
            game.log.append(f"Tapped {perm.card.name}")
        else:
            game.log.append("No valid permanent to tap")
        return True, "resolved"
    tapped = game._tap_or_untap_target(
        target, make_tapped=True, target_permanent_index=context.target_permanent_index
    )
    game.log.append("Tapped target permanent" if tapped else "No valid permanent to tap")
    return True, "resolved"


@effect_handler("tap_or_untap_target")
def tap_or_untap_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Twiddle: toggle the chosen permanent's tapped state (tap an untapped one,
    # untap a tapped one). Honor the explicitly chosen permanent on either
    # battlefield; fall back to the first permanent for AI/headless play.
    perm = resolve_target_permanent(context, predicate=lambda p: True)
    if perm is None:
        game.log.append("No valid permanent to tap or untap")
        return True, "resolved"
    perm.tapped = not perm.tapped
    if perm.tapped:
        game._turn_face_up(perm)
    game.log.append(f"{'Tapped' if perm.tapped else 'Untapped'} {perm.card.name}")
    return True, "resolved"


@effect_handler("tap_target_player_lands_and_drain_mana")
def tap_target_player_lands_and_drain_mana(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    for perm in game.controlled_by(target):
        if perm.card.primary_type == "land":
            game.become_tapped(perm)
    for sym in ("W", "U", "B", "R", "G", "C"):
        target.mana_pool[sym] = 0
    target.creature_only_mana.clear()
    game.log.append(f"{card.name} tapped all lands and drained mana from {target.name}")
    return True, "resolved"
