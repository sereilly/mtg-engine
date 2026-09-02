from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import count_from_payload, evaluate_count, resolve_amount
from ..exiled_records import source_object
from ..named_counters import counters_on
from ..oracle_types import COUNTERS_REMOVED, X_FROM_COUNT_PER_RECIPIENT
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


@effect_handler("player_gets_poison_counters")
def player_gets_poison_counters(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…that player gets a poison counter." (Pit Scorpion, Serpent Generator's
    tokens.) The player is the one the damage trigger recorded
    (``defending_player_index``, frozen by ``damage_events._announce``), and the
    counter lands on ``PlayerState.poison_counters`` — the field the CR 704.5c /
    122.1f state-based sweep in ``mixins/game_ending.py`` already reads, so ten
    or more loses the game with no code here."""
    amount = max(0, int(instruction.payload.get("amount", 1)))
    idx = (context.trigger_context or {}).get("defending_player_index")
    if amount <= 0 or idx is None or not (0 <= idx < len(game.players)):
        return True, "resolved"
    player = game.players[idx]
    player.poison_counters += amount
    noun = "poison counter" if amount == 1 else "poison counters"
    game.log.append(
        f"{context.card.name}: {player.name} gets {amount} {noun} "
        f"({player.poison_counters} total)"
    )
    return True, "resolved"


@effect_handler("remove_all_counters_from_target_player")
def remove_all_counters_from_target_player(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Target player loses all poison counters." (Leeches.)

    The mirror of :func:`player_gets_poison_counters` above and over the same
    store — ``PlayerState.poison_counters``, which the CR 704.5c / 122.1f sweep
    reads — so a player taken back under ten stops losing the game with no code
    here.

    **How many came off is recorded**, because the sentence behind it reads the
    number: "Leeches deals **that much** damage to that player" is the count
    this step removed, and by the time it runs the store holds zero. The record
    is what was actually taken, not what the card asked for — a player with two
    counters loses two and takes two.
    """
    player = context.target
    if player is None:
        game.log.append(f"{context.card.name}: no player to remove counters from")
        return True, "resolved"
    kind = str(instruction.payload.get("counter", "poison"))
    removed = max(0, int(player.poison_counters))
    player.poison_counters = 0
    context.results[COUNTERS_REMOVED] = removed
    noun = f"{kind} counter" if removed == 1 else f"{kind} counters"
    game.log.append(
        f"{context.card.name}: {player.name} loses {removed} {noun}"
    )
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
    # "Each player loses **a third of their life**" (Pox). One number per seat,
    # so it cannot be `context.x_value` — that is resolved once at the dispatch
    # point, against one player, and applying that share to everybody is a
    # different card. The channel the damage sweeps already use for this.
    per_seat = instruction.payload.get(X_FROM_COUNT_PER_RECIPIENT)
    for victim in victims:
        loss = evaluate_count(game, victim, per_seat) if per_seat is not None else amount
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


@effect_handler("set_life_total")
def set_life_total(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"That player's life total becomes 20." (Rebirth.)

    CR 119.5: setting a total is a gain or a loss of the difference, and it is
    written that way rather than as an assignment because both halves are
    events. The gain goes through ``_gain_life``, the one seam every life gain
    passes through — so Lich's "if you would gain life, draw that many cards
    instead" still replaces it and "whenever you gain life" still fires — and
    the loss is a plain subtraction, exactly as ``target_loses_life`` does it
    (life loss is not damage, CR 120.3, so nothing contends with it).

    The recipient key is the same vocabulary the rest of this module reads:
    "caster" is the controller, "each_player" every seat still in the game, and
    "that_player" the seat this resolution is about — which for an offer made to
    each player is the seat that accepted it (see ``handlers/control_flow.may``).
    """
    total = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    recipient = instruction.payload.get("recipient")
    if recipient == "caster":
        players = [context.caster]
    elif recipient == "each_player":
        players = [p for p in game.players if not p.lost]
    else:
        players = [context.target]
    for player in players:
        before = player.life
        if total > before:
            game._gain_life(player, total - before, context.card.name)
        elif total < before:
            player.life -= before - total
        game.log.append(
            f"{context.card.name}: {player.name}'s life total became {player.life} "
            f"(was {before})"
        )
    return True, "resolved"


@effect_handler("exchange_life_totals")
def exchange_life_totals(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exchange life totals with target opponent." (Mirror Universe.)

    CR 701.12c: each player *gains or loses* the amount needed to reach the
    other's previous total — not an assignment of two numbers. Written that way
    for the reason ``set_life_total`` above is: the gain goes through
    ``_gain_life``, the one seam every life gain passes through, so Lich's
    replacement still replaces it and "whenever you gain life" still fires.

    Both previous totals are read **before** either side moves. Moving one seat
    and then reading the other would hand the second seat the number the first
    had just been given, which is not an exchange but a copy — and on the card
    that prints this it is the difference between stealing an opponent's life
    total and setting both players to it.

    CR 701.12a makes the exchange atomic: a target that is no longer a legal
    seat leaves both totals alone rather than moving one of them.
    """
    card = context.card
    mine = context.caster
    theirs = context.target
    if theirs is None or theirs is mine or theirs.lost or mine.lost:
        game.log.append(
            f"{card.name}: no opponent to exchange life totals with, so nothing happens"
        )
        return True, "resolved"
    my_total, their_total = mine.life, theirs.life
    for player, wanted in ((mine, their_total), (theirs, my_total)):
        before = player.life
        if wanted > before:
            game._gain_life(player, wanted - before, card.name)
        elif wanted < before:
            player.life -= before - wanted
    game.log.append(
        f"{card.name}: {mine.name} and {theirs.name} exchanged life totals "
        f"({my_total}/{their_total} -> {mine.life}/{theirs.life})"
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
    if recipient == "event_subject_player":
        # "…**they** gain 1 life" under "at the beginning of each player's
        # upkeep" (Spiritual Sanctuary): the seat the firing event named,
        # frozen by the fire site (CR 603.10). The trigger has no target, so
        # `context.target` is whatever a targetless resolution defaults to —
        # which handed the life to the opponent on the controller's own upkeep,
        # and to the right seat everywhere else, making it look correct in
        # exactly the half of the cases a two-player test covers first.
        seat = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(f"{card.name}: no recorded player, no life gained")
            return True, "resolved"
        gainer = game.players[seat]
    else:
        gainer = context.caster if recipient == "caster" else context.target
    # "You gain life equal to the damage dealt" — the amount is whatever the
    # preceding damage instruction in this same resolution actually dealt, which
    # it recorded in the context scratchpad. This is what lets damage-then-gain
    # be two composable instructions instead of one fused kind.
    source_key = instruction.payload.get("amount_from")
    trigger_key = instruction.payload.get("amount_from_trigger")
    # "You gain life equal to the sacrificed creature's toughness" (Life Chisel,
    # Diamond Valley). A third channel beside the two below, and a third because
    # it is a different question: the scratchpad holds what a *step of this
    # effect* produced and the trigger context holds what the *event* carried,
    # while this names what the ability's own **cost** ate — paid, and off the
    # battlefield, before the ability was ever put on the stack (CR 601.2h).
    #
    # The toughness is the permanent's *effective* toughness as it last existed
    # (CR 608.2h): a Giant Tortoise sacrificed while untapped is worth its
    # +0/+3, not its printed 1. A cost that ate nothing gains nothing rather
    # than reading a printed number off a card.
    # "…you may gain life equal to **its** power" (Delif's Cone). CR 603.7c's
    # object: the creature the delay's opener targeted, addressed by the id the
    # arming handler froze — live, because the creature is on the battlefield
    # attacking when this resolves, and gone means no life rather than a printed
    # number read off a card.
    if instruction.payload.get("amount_from_bound_power"):
        bound = (context.trigger_context or {}).get("bound_permanent_id")
        watched = game.permanent_by_id(bound) if isinstance(bound, int) else None
        game._gain_life(
            gainer, max(0, watched.effective_power) if watched is not None else 0,
            card.name,
        )
        return True, "resolved"
    cost_characteristic = instruction.payload.get("amount_from_cost_sacrifice")
    if cost_characteristic is not None:
        sacrificed = context.choices.get("sacrificed_for_cost")
        life_gain = (
            max(0, int(getattr(sacrificed, f"effective_{cost_characteristic}", 0)))
            if sacrificed is not None else 0
        )
        game._gain_life(gainer, life_gain, card.name)
        return True, "resolved"
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
    # "…for each creature that died this turn" (Canopy Stalker): the game's own
    # tally, because the objects counted are exactly the ones no zone still
    # holds. Game-wide — `creatures_died_under_your_control_this_turn` beside it
    # is the per-seat tally, and reading one for the other is a different number
    # every time an opponent's creature dies.
    if per_each is not None and per_each.get("history") == "creatures_died_this_turn":
        life_gain *= int(getattr(game, "creatures_died_this_turn", 0))
    if per_each is not None and per_each.get("counters_on_source"):
        # "…**for each credit counter on this creature**" (Icatian
        # Moneychanger). Through the one counter reader, `counters_on`, which
        # asks `pt.pt_counter_key` — this file's own spelling of the key would
        # answer zero for every counter that also has rules meaning, silently,
        # because a missing key is a legal zero.
        #
        # The source may already have left: this ability's cost sacrifices it
        # (CR 603.6/608.2h), so the record read is the one the activation path
        # carried forward, which `source_object` is the one reader of.
        holder = source_object(context)
        life_gain *= (
            0 if holder is None
            else counters_on(holder, str(per_each["counters_on_source"]))
        )
    if per_each is not None and per_each.get("zone") not in (None, "battlefield"):
        # "For each artifact or creature card in **target opponent's**
        # graveyard, … you gain 1 life." (Spoils of Evil.) A count out of a zone
        # rather than off a battlefield, answered by `count_from_payload` — the
        # same reader `add_mana_from_text`'s per-each uses, and the same reader
        # the mana half of this very sentence goes through one instruction over.
        # Two readings of one count would be two answers on one card.
        life_gain *= count_from_payload(game, context, per_each)
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
    life_gain = _capped_life_gain(context, instruction, life_gain)
    game._gain_life(gainer, life_gain, card.name)
    return True, "resolved"


def _capped_life_gain(context, instruction, life_gain: int) -> int:
    """"…but not more life than A, B, or C" (Drain Life, Soul Burn).

    The cap is the second half of one sentence, so it belongs to the gain and
    not to the damage: ``deal_damage`` returns what was **dealt**, which lifelink
    and every damage trigger read, and only the life gained is limited. That is
    the same distinction Ali from Cairo draws between the damage dealt and the
    life lost, and getting it backwards would silently shrink the damage too.

    Each printed term is asked in turn and the smallest wins. A term whose
    record is missing caps the gain at zero rather than being skipped: the
    alternative is a gain the card never authorised, and "gained less than it
    should" is a bug that a game reports where "gained more" is one nobody
    notices.
    """
    terms = instruction.payload.get("capped_by") or ()
    if not terms:
        return life_gain
    for term in terms:
        kind = term.get("kind")
        if kind == "recipient_capacity":
            # Whom the damage went to and what they could absorb before it,
            # recorded by the damage step. The kinds are checked because the
            # printed terms are per kind of recipient — a card naming only
            # "the creature's toughness" does not cap a gain from damaging a
            # player, and reading the number without the kind would.
            recorded = (context.results or {}).get("damage_recipient")
            if not isinstance(recorded, dict):
                return 0
            if recorded.get("kind") not in (term.get("recipients") or ()):
                continue
            life_gain = min(life_gain, max(0, int(recorded.get("capacity", 0))))
        elif kind == "mana_spent_on_x":
            # "the amount of {B} spent on X" (Soul Burn) — the split the cast
            # chose (CR 601.2h), carried on the stack item because the pool it
            # came out of is emptied at the end of the step (CR 500.4).
            spent = (context.choices or {}).get("x_mana_spent") or {}
            life_gain = min(life_gain, max(0, int(spent.get(term.get("symbol"), 0))))
        else:
            # An unreadable term is the same failure as a missing record, and
            # the lowering refuses to emit one — this is the belt to its braces.
            return 0
    return max(0, life_gain)


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


@effect_handler("end_the_turn")
def end_the_turn(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"End the turn." (Discontinuity.) CR 724.1's whole process lives on the
    turn-structure mixin, where the rest of the phase and step navigation is;
    this is the instruction that asks for it."""
    game.end_the_turn()
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


#: Whether *player* could pay *amount* life right now (CR 119.4). One reader,
#: because the gate that decides whether "pay 4 life" is *offered* as an
#: alternative and the handler that performs it have to agree — an alternative
#: offered and then refused is a decision a player makes and does not get.
def can_pay_life(player, amount: int) -> bool:
    return player.life >= max(0, int(amount))


@effect_handler("pay_life")
def pay_life(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Pay 4 life." (Sylvan Library.) CR 119.4: the payment is a loss of that
    much life.

    Separate from ``target_loses_life`` for the reason ``ast.PayLife`` gives:
    this is an act a player has to be able to perform, and
    ``handlers/control_flow._action_is_takeable`` asks :func:`can_pay_life`
    before offering it. Reaching here unable to pay means the offer was never
    narrowed — so it is logged and nothing happens, rather than taking a
    player below zero on a cost they could not have chosen.
    """
    player = context.caster
    amount = max(0, int(instruction.payload.get("amount", 0)))
    if not can_pay_life(player, amount):
        game.log.append(
            f"{context.card.name}: {player.name} cannot pay {amount} life"
        )
        return True, "resolved"
    before = player.life
    player.life -= amount
    game.log.append(
        f"{context.card.name}: {player.name} paid {amount} life "
        f"({before} -> {player.life})"
    )
    return True, "resolved"
