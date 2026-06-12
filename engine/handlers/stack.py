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
    caster = context.caster
    target = context.target
    card = context.card
    if game.stack:
        copied = game.stack[-1]
        game._apply_spell_text(caster, target, copied.card, x_value=copied.x_value)
        game.log.append(f"{card.name} copied {copied.card.name}")
    else:
        game.log.append(f"{card.name} resolved with no spell to copy")
    return True, "resolved"


@effect_handler("counter_top_stack_spell")
def counter_top_stack_spell(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    color_filter = instruction.payload.get("color_filter")
    if game.stack:
        top = game.stack[-1]
        if color_filter and color_filter not in (top.card.colors or ()):
            game.log.append(f"{card.name}: top spell is not color {color_filter}, cannot counter")
            return True, "resolved"
        # Spell Blast: X must equal the target spell's mana value. When no X was
        # chosen (None, or 0 auto-inferred from an empty pool), assume the caster
        # chose the matching value.
        if instruction.payload.get("mv_equals_x") and context.x_value:
            top_mv = int(top.card.cmc or 0)
            if int(context.x_value) != top_mv:
                game.log.append(
                    f"{card.name}: X={context.x_value} does not match {top.card.name}'s mana value {top_mv}, cannot counter"
                )
                return True, "resolved"
        countered = game.stack.pop()
        game.players[countered.caster_index].graveyard.append(countered.card)
        game.log.append(f"{card.name} countered {countered.card.name}")
        counter_hook = ON_SPELL_COUNTERED.get(card.name)
        if counter_hook is not None:
            counter_hook(game, card, countered)
    else:
        game.log.append(f"{card.name} resolved with no spell to counter")
    return True, "resolved"
