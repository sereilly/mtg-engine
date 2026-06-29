from __future__ import annotations

from typing import TYPE_CHECKING

from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


# Rule 104.3e: effect that states a player loses the game
@effect_handler("target_player_loses_game", "player_loses_game")
def player_loses_game(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    # "you lose the game" triggers apply to caster; targeted spells apply to target
    loser = target if instruction.kind == "target_player_loses_game" else caster
    if not loser.lost:
        loser.lost = True
        game.log.append(f"{card.name}: {loser.name} lost the game (104.3e)")
    return True, "resolved"


# Rule 104.2b: effect that states caster wins the game
@effect_handler("player_wins_game")
def player_wins_game(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    card = context.card
    # 104.3f: if caster would also lose simultaneously, they lose instead
    if not caster.lost:
        # Mark all opponents as lost so caster is last standing (104.2a)
        for player in game.players:
            if player is not caster and not player.lost:
                player.lost = True
                game.log.append(f"{card.name}: {player.name} lost (104.2b: opponent loses)")
        game.log.append(f"{card.name}: {caster.name} wins the game (104.2b)")
    return True, "resolved"


# Rule 104.4c: effect that states the game is a draw
@effect_handler("game_is_draw")
def game_is_draw(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    if not game.is_draw:
        game.is_draw = True
        for player in game.players:
            player.lost = True
        game.log.append(f"{card.name}: the game is a draw (104.4c)")
    return True, "resolved"


@effect_handler("target_loses_life")
def target_loses_life(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    amount = int(instruction.payload.get("amount", 0))
    before = target.life
    target.life -= amount
    game.log.append(f"{card.name}: {target.name} lost {amount} life ({before} -> {target.life})")
    return True, "resolved"


@effect_handler("target_gains_life")
def target_gains_life(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    x_value = context.x_value
    # Soul Net-style death trigger resolving off the stack: "Whenever a creature
    # dies, you may pay {N}. If you do, gain N life." The trigger's controller is the
    # caster. When it carries an optional-pay cost, the pay-prompt is raised here at
    # resolution (not at fire time) — so no life is gained until the player answers,
    # via _pay_optional / confirm_optional_pay. With no cost, the controller just
    # gains the life on resolution.
    tctx = context.trigger_context
    if tctx is not None and "life" in tctx:
        controller = context.caster
        life = int(tctx.get("life", 0))
        cost = tctx.get("optional_pay_cost")
        if cost is not None:
            if game._player_can_pay_generic(controller, int(cost)):
                game.pending_optional_pays.append({
                    "card_name": card.name,
                    "player_index": game.players.index(controller),
                    "cost": int(cost),
                    "life": life,
                })
            return True, "resolved"
        game._gain_life(controller, life, card.name)
        return True, "resolved"
    amount = instruction.payload.get("amount", 0)
    # "You gain N life" affects the controller; "target player gains N life"
    # affects the chosen target (CR 115.10b). Default to target for legacy
    # instructions that predate the recipient payload.
    recipient = instruction.payload.get("recipient", "target")
    gainer = context.caster if recipient == "caster" else context.target
    life_gain = max(0, x_value or 0) if amount == "x" else int(amount)
    game._gain_life(gainer, life_gain, card.name)
    return True, "resolved"


@effect_handler("grant_extra_turn")
def grant_extra_turn(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    caster_index = game.players.index(caster)
    game.add_extra_turn(caster_index)
    game.log.append(f"{caster.name} gained an extra turn")
    return True, "resolved"
