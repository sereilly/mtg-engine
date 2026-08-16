from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import resolve_amount
from .registry import effect_handler
from ..mana_payment import generic_cost

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
@effect_handler("opponents_lose_half_life")
def opponents_lose_half_life(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Shahrazad's life clause, without the subgame.

    The card says "each player who doesn't win the subgame loses half their
    life, rounded up". The engine does not play subgames, so it resolves the
    documented simplification: the caster is treated as the winner and every
    other player pays. The log says so rather than reporting it as the real
    card — a simplification the player can see is a different thing from a
    card that quietly does nothing, which is what this used to do.
    """
    caster = context.caster
    card = context.card
    for player in game.players:
        if player is caster or player.lost:
            continue
        loss = max(0, (player.life + 1) // 2)
        player.life -= loss
        game.log.append(
            f"{card.name}: {player.name} loses {loss} life (half, rounded up) — "
            "subgame not played; its caster is treated as the winner"
        )
    return True, "resolved"


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
    card = context.card
    # "…loses **that much** life" (Vito): the number is the firing event's, not
    # this effect's, so it is read out of the trigger's captured context under
    # the key the lowering named. An absent record loses nothing rather than
    # falling back to a static amount the card never printed.
    from_trigger = instruction.payload.get("amount_from_trigger")
    if from_trigger is not None:
        amount = max(0, int((context.trigger_context or {}).get(from_trigger, 0)))
    else:
        amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    # The same recipient key deal_damage reads: absent means the spell's
    # target, "caster" the controller ("You lose 3 life"), "each_opponent"
    # every living opponent. Life loss is not damage (CR 120.3), so no shield
    # or replacement contends here.
    recipient = instruction.payload.get("recipient")
    if recipient == "caster":
        victims = [context.caster]
    elif recipient == "each_opponent":
        victims = [
            game.players[i]
            for i in game.opponents_of(game.players.index(context.caster))
        ]
    elif recipient == "each_player":
        # "Each player loses 2 life." (Bad Deal) — the caster too; a player who
        # has already left the game is nobody (CR 800.4a).
        victims = [p for p in game.players if not p.lost]
    elif recipient == "event_subject_controller":
        # "That player" after an event about an object: the controller of that
        # object, frozen by the fire site (CR 603.10). Massacre Wurm's dead
        # creature is in a graveyard by now and Gloom Sower's blocker may have
        # left combat, so a board read cannot answer either — and Control Magic
        # makes controller and owner differ, so the owner is not the answer.
        seat = (context.trigger_context or {}).get("event_subject_controller")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(f"{card.name}: no recorded controller, no life lost")
            return True, "resolved"
        victims = [game.players[seat]]
    elif recipient == "last_target_controller":
        # "Destroy target creature. Its controller loses 2 life." (Liliana,
        # Death Mage.) The destroy step recorded the controller before the
        # permanent left (CR 608.2h, last-known information); no record means
        # the destroy found no target, and the rider fizzles with it.
        seat = context.results.get("last_target_controller_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(f"{card.name}: no destroyed creature, no life lost")
            return True, "resolved"
        victims = [game.players[seat]]
    else:
        victims = [context.target]
    # "…for each creature card in their graveyard" (Liliana, Death Mage's −7):
    # the amount is per matching card in the victim's own graveyard.
    per_each = instruction.payload.get("per_each")
    for victim in victims:
        loss = amount
        if per_each is not None:
            wanted = tuple(per_each.get("card_types") or ())
            loss = amount * sum(
                1
                for c in victim.graveyard
                if not wanted or c.primary_type in wanted
            )
        before = victim.life
        victim.life -= loss
        game.log.append(
            f"{card.name}: {victim.name} lost {loss} life ({before} -> {victim.life})"
        )
    return True, "resolved"


@effect_handler("opponents_who_could_not_discard_lose_life")
def opponents_who_could_not_discard_lose_life(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each opponent who can't loses 3 life." (Liliana, Waker of the Dead's
    +1.) Reads the seats the preceding each-player discard recorded as unable
    to pay; only the caster's opponents lose life."""
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    caster_index = game.players.index(context.caster)
    could_not = context.results.get("players_who_could_not_discard") or []
    for seat in could_not:
        if seat == caster_index or not (0 <= seat < len(game.players)):
            continue
        victim = game.players[seat]
        before = victim.life
        victim.life -= amount
        game.log.append(
            f"{context.card.name}: {victim.name} could not discard and lost "
            f"{amount} life ({before} -> {victim.life})"
        )
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
            entry = {"card_name": card.name, "cost": generic_cost(int(cost)), "life": life}
            if game._player_can_pay_optional(controller, entry):
                game.arm_pending_choice(
                    "optional_pay", game.players.index(controller), **entry
                )
            return True, "resolved"
        game._gain_life(controller, life, card.name)
        return True, "resolved"
    # "You gain N life" affects the controller; "target player gains N life"
    # affects the chosen target (CR 115.10b). Default to target for legacy
    # instructions that predate the recipient payload.
    recipient = instruction.payload.get("recipient", "target")
    gainer = context.caster if recipient == "caster" else context.target
    # "You gain life equal to the damage dealt" — the amount is whatever the
    # preceding damage instruction in this same resolution actually dealt, which
    # it recorded in the context scratchpad. This is what lets damage-then-gain
    # be two composable instructions instead of one fused kind.
    source_key = instruction.payload.get("amount_from")
    trigger_key = instruction.payload.get("amount_from_trigger")
    if trigger_key is not None:
        # The firing event's own number, frozen into the trigger's context by
        # the fire site: "…you gain life equal to its power" on a dies trigger
        # (Conclave Mentor), whose source is in a graveyard by the time this
        # resolves, so last-known information is the only legal reading
        # (CR 603.10). An absent record gains nothing rather than reading a
        # card's printed power as if it were the permanent's.
        life_gain = max(0, int((context.trigger_context or {}).get(trigger_key, 0)))
    elif source_key is not None:
        life_gain = max(0, int(context.results.get(source_key, 0)))
    else:
        life_gain = resolve_amount(instruction.payload.get("amount", 0), x_value)
    # "…for each creature you control with flying" (Aven Gagglemaster): the
    # gain is multiplied by a battlefield count of the gainer's own permanents,
    # keywords asked of layer 6 so a granted flying counts.
    per_each = instruction.payload.get("per_each")
    if per_each is not None and per_each.get("zone") == "battlefield":
        wanted_types = tuple(per_each.get("card_types") or ())
        wanted_keywords = tuple(per_each.get("with_keywords") or ())
        life_gain *= sum(
            1
            for perm in game.controlled_by(gainer)
            if (not wanted_types or ("creature" in wanted_types and perm.is_creature)
                or any(perm.has_type(t) for t in wanted_types if t != "creature"))
            and all(game._has_keyword(perm, kw) for kw in wanted_keywords)
        )
    game._gain_life(gainer, life_gain, card.name)
    return True, "resolved"


@effect_handler("gain_life_equal_to_damage_dealt")
def gain_life_equal_to_damage_dealt(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """El-Hajjaj: "Whenever this creature deals damage, you gain that much
    life." The amount is threaded through trigger_context by
    _fire_combat_damage_to_player_triggers (the trigger has no static payload
    of its own — the life gained depends on what actually happened)."""
    caster = context.caster
    card = context.card
    tctx = context.trigger_context or {}
    amount = int(tctx.get("amount", 0))
    if amount > 0:
        game._gain_life(caster, amount, card.name)
    return True, "resolved"


@effect_handler("arm_draw_step_life_loss_unless_pay")
def arm_draw_step_life_loss_unless_pay(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Nafs Asp: "that player loses 1 life at the beginning of their next draw
    step unless they pay {1} before that draw step." The victim (not Nafs
    Asp's controller) is the one who owes the obligation, captured in
    trigger_context by _fire_combat_damage_to_player_triggers."""
    card = context.card
    tctx = context.trigger_context or {}
    idx = tctx.get("defending_player_index")
    if not (isinstance(idx, int) and 0 <= idx < len(game.players)):
        return True, "resolved"
    game.pending_draw_step_life_loss.append({
        "player_index": idx,
        "amount": resolve_amount(instruction.payload.get("amount", 1), context.x_value),
        "cost": int(instruction.payload.get("cost", 1)),
        "source_name": card.name,
    })
    game.log.append(
        f"{game.players[idx].name} will lose {instruction.payload.get('amount', 1)} life at their next draw "
        f"step unless they pay {{{instruction.payload.get('cost', 1)}}} ({card.name})"
    )
    return True, "resolved"


@effect_handler("grant_extra_turn")
def grant_extra_turn(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    caster_index = game.players.index(caster)
    # "Take two extra turns after this one." (Teferi, Master of Time) — each
    # queued turn is its own CR 500.7 insertion.
    count = int(instruction.payload.get("count", 1))
    for _ in range(count):
        game.add_extra_turn(caster_index)
    game.log.append(
        f"{caster.name} gained an extra turn" if count == 1
        else f"{caster.name} gained {count} extra turns"
    )
    return True, "resolved"


@effect_handler("sacrifice_creature_gain_life_by_toughness")
def sacrifice_creature_gain_life_by_toughness(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Diamond Valley: sacrifice one of the caster's own creatures, then gain
    life equal to the toughness it had. Reuses the same "sacrifice a creature"
    resolution helper as the Sacrifice card / sacrifice_creature_for_mana.

    The toughness is the creature's *effective* toughness as it last existed on
    the battlefield (CR 608.2h) — a Giant Tortoise sacrificed while untapped is
    worth its +0/+3, not its printed 1."""
    caster = context.caster
    card = context.card
    chosen = context.target_permanent_index if isinstance(context.target_permanent_index, int) else None
    sacrificed = game._sacrifice_creature_for_mana(caster, chosen_index=chosen)
    if sacrificed is None:
        game.log.append(f"{caster.name} had no creature to sacrifice")
        return True, "resolved"
    game._gain_life(caster, max(0, sacrificed.effective_toughness), card.name)
    return True, "resolved"


@effect_handler("gain_twice_artifact_damage_taken")
def gain_twice_artifact_damage_taken(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Reverse Polarity. Zero artifact damage gains zero life, which is a real
    outcome for this card rather than a failure to resolve."""
    caster = context.caster
    amount = 2 * max(0, caster.artifact_damage_taken_this_turn)
    if amount:
        game._gain_life(caster, amount, context.card.name)
    else:
        game.log.append(f"{context.card.name}: no artifact damage taken this turn")
    return True, "resolved"
