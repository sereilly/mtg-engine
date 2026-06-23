from __future__ import annotations

from typing import TYPE_CHECKING

from ..card_hooks import ON_SPELL_COUNTERED
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("copy_top_stack_spell")
def copy_top_stack_spell(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Fork: "Copy target instant or sorcery spell..." Copy the chosen spell if one
    # was targeted, otherwise the topmost instant or sorcery on the stack (Fork
    # itself has already been popped to resolve). The copy keeps the original's
    # targets (Fork lets you choose new ones, which the simulation does not model).
    caster = context.caster
    card = context.card
    copied = None
    chosen = context.stack_target
    if chosen is not None and chosen in game.stack and chosen.card.primary_type in ("instant", "sorcery"):
        copied = chosen
    if copied is None:
        copied = next(
            (item for item in reversed(game.stack) if item.card.primary_type in ("instant", "sorcery")),
            None,
        )
    if copied is None:
        game.log.append(f"{card.name} resolved with no instant or sorcery spell to copy")
        return True, "resolved"
    copy_target_idx = (
        copied.target_player_index
        if copied.target_player_index is not None
        else (1 - copied.caster_index)
    )
    copy_target = game.players[copy_target_idx] if 0 <= copy_target_idx < len(game.players) else caster
    game._apply_spell_text(
        caster,
        copy_target,
        copied.card,
        target_permanent_index=copied.target_permanent_index,
        x_value=copied.x_value,
        mode_index=copied.chosen_mode_index,
    )
    game.log.append(f"{card.name} copied {copied.card.name}")
    return True, "resolved"


@effect_handler("counter_top_stack_spell")
def counter_top_stack_spell(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    color_filter = instruction.payload.get("color_filter")
    if game.stack:
        # Counter the chosen spell if one was targeted, otherwise the top of stack.
        chosen = context.stack_target
        target = chosen if (chosen is not None and chosen in game.stack) else game.stack[-1]
        if color_filter and color_filter not in game._stack_item_colors(target):
            game.log.append(f"{card.name}: {target.card.name} is not color {color_filter}, cannot counter")
            return True, "resolved"
        # Spell Blast: X must equal the target spell's mana value. When no X was
        # chosen (None, or 0 auto-inferred from an empty pool), assume the caster
        # chose the matching value.
        if instruction.payload.get("mv_equals_x") and context.x_value:
            target_mv = int(target.card.cmc or 0)
            if int(context.x_value) != target_mv:
                game.log.append(
                    f"{card.name}: X={context.x_value} does not match {target.card.name}'s mana value {target_mv}, cannot counter"
                )
                return True, "resolved"
        # Power Sink: "Counter target spell unless its controller pays {X}." The
        # targeted spell's controller may pay {X} (X chosen by Power Sink's caster)
        # to keep their spell. Paid automatically from the pool when able
        # (deterministic). Paying {0} always succeeds, so X=0 counters nothing.
        if instruction.payload.get("unless_pays_x"):
            cost = max(0, int(context.x_value or 0))
            spell_controller = game.players[target.caster_index]
            available = sum(spell_controller.mana_pool.get(s, 0) for s in spell_controller.mana_pool)
            if available >= cost:
                remaining = cost
                for sym in list(spell_controller.mana_pool):
                    while remaining > 0 and spell_controller.mana_pool.get(sym, 0) > 0:
                        spell_controller.mana_pool[sym] -= 1
                        remaining -= 1
                game.log.append(
                    f"{spell_controller.name} paid {{{cost}}}; {target.card.name} is not countered by {card.name}"
                )
                return True, "resolved"
            # Couldn't pay: spell is countered and the rider (tap lands, drain mana)
            # applies via the ON_SPELL_COUNTERED hook below.

        game.stack.remove(target)
        countered = target
        game.players[countered.caster_index].graveyard.append(countered.card)
        game.log.append(f"{card.name} countered {countered.card.name}")
        counter_hook = ON_SPELL_COUNTERED.get(card.name)
        if counter_hook is not None:
            counter_hook(game, card, countered)
    else:
        game.log.append(f"{card.name} resolved with no spell to counter")
    return True, "resolved"
