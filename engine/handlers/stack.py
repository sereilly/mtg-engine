from __future__ import annotations

from typing import TYPE_CHECKING

from ..card_hooks import ON_SPELL_COUNTERED
from ..game_types import StackItem
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("copy_top_stack_spell")
def copy_top_stack_spell(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Fork: "Copy target instant or sorcery spell... You may choose new targets for
    # the copy." Copy the chosen spell if one was targeted, otherwise the topmost
    # instant or sorcery on the stack (Fork itself has already been popped to
    # resolve). The copy is put onto the stack under Fork's controller so it
    # resolves independently, and gets new targets if the Fork caster chose them.
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

    caster_index = game.players.index(caster)
    # "You may choose new targets for the copy." When the Fork caster supplied a
    # new target (a creature/permanent index, optionally on a specific player),
    # the copy uses it; otherwise the copy keeps the original spell's targets.
    if context.target_permanent_index is not None:
        new_target_player_index = game.players.index(context.target) if context.target is not None else copied.target_player_index
        new_target_permanent_index = context.target_permanent_index
    else:
        new_target_player_index = copied.target_player_index
        new_target_permanent_index = copied.target_permanent_index

    game.stack.append(
        StackItem(
            card=copied.card,
            caster_index=caster_index,
            target_player_index=new_target_player_index,
            target_permanent_index=new_target_permanent_index,
            x_value=copied.x_value,
            new_color=copied.new_color,
            old_color=copied.old_color,
            chosen_mode_index=copied.chosen_mode_index,
            target_stack_item=copied.target_stack_item,
            target_stack_name=copied.target_stack_name,
            is_copy=True,
        )
    )
    game.log.append(f"{card.name} copied {copied.card.name} (copy put on the stack)")
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
        # targeted spell's controller is asked to pay {X} (X chosen by Power Sink's
        # caster) to keep their spell. Rather than auto-paying, arm a pending mana
        # payment: the target spell stays on the stack while its controller decides
        # (a human taps lands and pays/declines via the prompt; headless/AI play is
        # auto-resolved deterministically). Paying {0} always succeeds, so X=0 never
        # counters — resolve that immediately without a prompt.
        if instruction.payload.get("unless_pays_x"):
            cost = max(0, int(context.x_value or 0))
            if cost == 0:
                game.log.append(
                    f"{game.players[target.caster_index].name} pays {{0}}; "
                    f"{target.card.name} is not countered by {card.name}"
                )
                return True, "resolved"
            game.pending_mana_payment = {
                "player_index": target.caster_index,
                "amount": cost,
                "card_name": card.name,
                "counter_card": card,
                "stack_item": target,
                "_new": True,
            }
            game.log.append(
                f"{card.name}: {game.players[target.caster_index].name} must pay "
                f"{{{cost}}} or {target.card.name} is countered"
            )
            return True, "resolved"

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
