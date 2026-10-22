"""Cards off the top of a library: draw, mill, scry.

The handler twin of ``engine/grammar/lowering/cards.py``, under its name: a card
*arriving* — in a hand by a draw (CR 121), in a graveyard by a mill (CR 701.17),
back on the top or the bottom of the library by a scry (CR 701.22) or a surveil
— and the draw replacements an ability arms for later ("the next time you would
draw a card this turn, instead …"), which ``Game._draw_with_replacements``
consumes at the next draw. Every draw here is made through that seam.

Split out of ``zones.py`` at the 2,000-line cap's split round, when that module
stood at 11,769 lines. Cards already *in* a hand are ``hand.py``'s, and the
discards — with their two fused draw-and-discard shapes — are ``discards.py``'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Permanent
from ..oracle_types import (DREW_BY_SEAT, DREW_COUNT, MILLED_THIS_WAY,
                            OTHER_THAN_EVENT_SUBJECT_PLAYER,
                            X_FROM_COUNT_PER_RECIPIENT)
from ._amounts import per_recipient_amount, resolve_amount
from ._filters import _card_matches_filter
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("draw_target_cards")
def draw_target_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target player draws N cards", and "**its controller** draws a card"
    inside a loop over objects an earlier step swept (Martyr's Cry).

    ``drawer_seat`` names a per-object record; the loop resolves it to one seat
    per iteration (``OracleExecutionContext.iteration_seats``). With the record
    absent nobody drew — the sentence named a seat nothing recorded — and the
    honest answer is to draw nothing rather than to fall back on
    ``context.target``, which is a seat this sentence never mentions.
    """
    # "**Each player** draws a card." (Winter Sky.) A set of seats, named by the
    # same ``recipient`` key `mill_target_player` reads for the same phrase one
    # zone over. Read before the per-object record below, which names one seat
    # per iteration of a loop this branch is not inside. Each drawer draws from
    # their own library, which is why it is a loop rather than a shared count.
    recipient = instruction.payload.get("recipient")
    if recipient in (
        "each_player", "each_opponent", OTHER_THAN_EVENT_SUBJECT_PLAYER,
    ):
        caster_index = game.players.index(context.caster)
        # CR 101.4's order for "each player", and the caster excluded for "each
        # opponent". A seat that has left the game draws nothing (CR 800.4a).
        if recipient == OTHER_THAN_EVENT_SUBJECT_PLAYER:
            # "…each of **that player's** opponents draws three cards."
            # (Standstill.) Every seat but the one the firing event froze -
            # which includes this ability's own controller whenever somebody
            # else cast the spell. With no seat recorded the words are
            # measured from nobody, and nobody draws.
            named = (context.trigger_context or {}).get("event_subject_player")
            if not isinstance(named, int):
                game.log.append(
                    f"{context.card.name}: nothing recorded which player that was"
                )
                return True, "resolved"
            total = len(game.players)
            active = game.active_player_index or 0
            seats = sorted(
                (
                    i for i, p in enumerate(game.players)
                    if i != named and not p.lost
                ),
                key=lambda i: ((i - active) % total, i),
            )
        elif recipient == "each_opponent":
            seats = [s for s in game.opponents_of(caster_index) if not game.players[s].lost]
        else:
            total = len(game.players)
            active = game.active_player_index or 0
            seats = sorted(
                (i for i, p in enumerate(game.players) if not p.lost),
                key=lambda i: ((i - active) % total, i),
            )
        # "…draws a card **for each creature card in their graveyard**."
        # (Nature's Resurgence.) One number per seat, taken against that seat's
        # own zone — the same channel and the same evaluator
        # `each_player_discards_a_card` asks for "a third of the cards in their
        # hand", because a single ``amount`` here is resolved once and would
        # give every player the first one's number. Read before ``amount``,
        # which the lowering removes when it emits this.
        per_seat = instruction.payload.get(X_FROM_COUNT_PER_RECIPIENT)
        count = (
            None if per_seat is not None
            else resolve_amount(instruction.payload.get("amount", 0), context.x_value)
        )
        for seat in seats:
            drawer = game.players[seat]
            wanted = (
                per_recipient_amount(game, context, per_seat, drawer)
                if per_seat is not None else count
            )
            drawn = game._draw_with_replacements(drawer, wanted)
            game.log.append(f"{drawer.name} drew {drawn} cards")
        return True, "resolved"
    drawer_seat = instruction.payload.get("drawer_seat")
    # "…**that player** draws an additional card" (Malignant Growth). A seat a
    # trigger's fire site froze rather than one this resolution chose, named by
    # the record it was frozen under — the same key `draw_up_to_cards` reads for
    # the ceiling spelling of the same sentence. Read before ``context.target``,
    # which for a trigger that chose nothing holds whatever the resolution was
    # already carrying; a record nothing wrote is a seat this sentence never
    # named, so nobody draws.
    seat_record = instruction.payload.get("drawer_seat_record")
    if seat_record is not None:
        recorded = (context.results or {}).get(seat_record)
        if recorded is None:
            recorded = (context.trigger_context or {}).get(seat_record)
        if recorded is None:
            game.log.append(
                f"{context.card.name}: nothing recorded which player that was"
            )
            return True, "resolved"
        target = game.players[int(recorded)]
    elif drawer_seat is not None:
        seat = context.iteration_seats.get(str(drawer_seat))
        if seat is None:
            game.log.append(
                f"{context.card.name}: nothing recorded whose permanent that was"
            )
            return True, "resolved"
        target = game.players[int(seat)]
    else:
        target = context.target
    # "…then draws **as many cards as they discarded this way**" (Forget).
    # ``amount_from`` names a scratchpad key an earlier step of this same
    # resolution wrote; a key nothing wrote reads as zero, which is what the
    # sentence says when the step in front of it did nothing (an empty hand
    # discards no cards, so this draws none).
    counted_from = instruction.payload.get("amount_from")
    count = (
        max(0, int(context.results.get(counted_from, 0) or 0))
        if counted_from is not None
        else resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    )
    drawn = game._draw_with_replacements(target, count)
    # "…then this enchantment deals damage to the player equal to **the number
    # of cards they drew this way**." (Malignant Growth.) How many really
    # arrived, which is the only place the sentence behind it can read the
    # number from: a replacement may have stopped some (CR 614) and an empty
    # library gives fewer than were asked for. Declared in
    # ``lowering/_records._PRODUCES``, so a back-reference with no draw in front
    # of it refuses rather than reading zero.
    context.results[DREW_COUNT] = drawn
    game.log.append(f"{target.name} drew {drawn} cards")
    return True, "resolved"


@effect_handler("draw_controller_cards")
def draw_controller_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    card = context.card
    # "Discard all the cards in your hand, **then draw that many cards**."
    # (Tolarian Winds; Nantuko Cultivator.) The lowering writes the record the
    # number lives in as ``amount_from`` for this kind exactly as for
    # ``draw_target_cards`` above, and this handler never read it: both cards
    # compiled supported and drew nothing. A key nothing wrote reads as zero.
    counted_from = instruction.payload.get("amount_from")
    count = (
        max(0, int(context.results.get(counted_from, 0) or 0))
        if counted_from is not None
        else resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    )
    drawn = game._draw_with_replacements(caster, count)
    game.log.append(f"{card.name} drew {drawn} card")
    return True, "resolved"


@effect_handler("arm_lamp_draw_replacement")
def arm_lamp_draw_replacement(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Aladdin's Lamp: arm the controller's next draw this turn to become
    "look at the top X, choose one to draw, bottom the rest in a random
    order". Consumed by Game._draw_with_replacements at the next draw."""
    caster = context.caster
    x = max(1, int(context.x_value or 0))
    game.lamp_draw_replacements[game.players.index(caster)] = x
    game.log.append(
        f"{context.card.name}: {caster.name}'s next draw this turn looks at the top {x} card(s) instead"
    )
    return True, "resolved"


@effect_handler("arm_outside_game_draw_replacement")
def arm_outside_game_draw_replacement(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Ring of Ma'rûf: arm the controller's next draw this turn to become "put a
    card you own from outside the game into your hand" instead. Consumed by
    Game._draw_with_replacements at the next draw."""
    caster = context.caster
    game.outside_game_draw_replacements.add(game.players.index(caster))
    game.log.append(
        f"{context.card.name}: instead of {caster.name}'s next draw this turn, they put "
        "a card they own from outside the game into their hand"
    )
    return True, "resolved"


@effect_handler("arm_draw_replacement")
def arm_draw_replacement(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"The next time you would draw a card this turn, instead <effect>."
    (Mangara's Tome.)

    CR 614.1's one-shot replacement, recorded on the game rather than on the
    permanent: the effect belongs to the ability that resolved (CR 611.2), so
    destroying the source in response does not un-arm it. The source rides
    along because the armed instruction may still name something recorded on it
    — Mangara's Tome's own pile — and that is a *link between abilities*
    (CR 610.3), which survives the object.

    Two activations arm two replacements, and the draw seam spends them one at
    a time, oldest first: each is its own effect, and CR 614.1 gives each its
    own event.
    """
    inner = instruction.payload.get("instruction")
    if inner is None:  # pragma: no cover - the lowering refuses an empty effect
        return True, "resolved"
    caster = context.caster
    game.armed_draw_replacements.append({
        "player_index": game.players.index(caster),
        "instruction": inner,
        "source": context.source_permanent,
    })
    game.log.append(
        f"{context.card.name}: {caster.name}'s next draw this turn is replaced"
    )
    return True, "resolved"


@effect_handler("arm_turn_draw_replacement")
def arm_turn_draw_replacement(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Until end of turn, if target player would draw a card, instead that
    player skips that draw and you draw a card." (Plagiarize.)

    A CR 614 replacement a resolving spell creates for the turn, recorded on
    the caster's seat (CR 109.5's "you") with the chosen player as the seat
    whose draws it takes (``engine/turn_replacements.py``); the draw seam's
    interceptor in ``engine/replacements.py`` reads it and the cleanup step's
    one sweep ends it. On the game rather than on any permanent for
    ``arm_draw_replacement``'s reason above: the effect is the resolved
    spell's (CR 611.2), and there is no permanent.

    The chosen player is the spell's announced target; one who has become an
    illegal target by resolution has already stopped the spell (CR 608.2b),
    so this reads the resolution's target and nothing else.
    """
    from ..turn_replacements import DRAW, TurnReplacement, arm_turn_replacement

    target = context.target
    if target is None or target not in game.players:
        game.log.append(f"{context.card.name}: no player was chosen")
        return True, "resolved"
    affected = game.players.index(target)
    arm_turn_replacement(game, TurnReplacement(
        seat=game.players.index(context.caster),
        event=DRAW,
        source_name=getattr(context.card, "name", None),
        affected_seat=affected,
    ))
    game.log.append(
        f"{context.card.name}: this turn, if {target.name} would draw a card, "
        f"{context.caster.name} draws instead"
    )
    return True, "resolved"


@effect_handler("draw_reveal_discard_unless_land")
def draw_reveal_discard_unless_land(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Sindbad: "Draw a card and reveal it. If it isn't a land card, discard
    it." The reveal is public (logged); a non-land is discarded through
    _discard_card so Library of Leng's replacement still applies."""
    caster = context.caster
    card = context.card
    if not caster.library:
        # 120.3: the draw is still attempted; drawing from an empty library
        # marks the loss the same way every other draw does.
        game._draw_with_replacements(caster, 1)
        game.log.append(f"{card.name}: {caster.name} has no cards to draw")
        return True, "resolved"
    # Through the seam, and *then* read what arrived: a replacement may have
    # taken this draw (Aladdin's Lamp) or doubled it (Teferi's Ageless
    # Insight), so the top of the library before the draw is not reliably the
    # card that gets revealed.
    if not game._draw_with_replacements(caster, 1) or not caster.cards_drawn_this_turn:
        game.log.append(f"{card.name}: {caster.name} drew nothing to reveal")
        return True, "resolved"
    drawn = caster.cards_drawn_this_turn[-1]
    game.log.append(f"{card.name}: {caster.name} drew and revealed {drawn.name}")
    game.record_reveal(game.players.index(caster), [drawn.name])
    if drawn.primary_type != "land":
        caster.hand.remove(drawn)
        game._discard_card(caster, drawn)
        game.log.append(f"{caster.name} discarded {drawn.name} (not a land card)")
    return True, "resolved"


@effect_handler("mill_target_player")
def mill_target_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """CR 701.17a: put the top N cards of a player's library into their
    graveyard.

    Milling fewer than N because the library ran out is not a loss — CR 704.5b
    only fires when a player actually *attempts to draw* from an empty library,
    so this stops at whatever is there.

    The same ``recipient`` key ``target_loses_life`` reads: absent means the
    spell's target, "caster" the controller ("Mill four cards."),
    "each_opponent" every living opponent, "damaged_player" the seat a damage
    trigger's fire site froze ("whenever this creature deals damage to an
    opponent, **that player** mills a card", Reef Pirates). Each miller mills
    their own library, which is why the loop is per victim rather than a shared
    count.

    A ``damaged_player`` with no record mills nobody, never the ability's own
    controller: that is the seat this effect must not hit, and it is the same
    rule ``discard_hand`` follows for the same words under the same event.
    """
    amount = resolve_amount(instruction.payload.get("amount", 1) or 1, context.x_value)
    recipient = instruction.payload.get("recipient")
    if recipient == "caster":
        victims = [context.caster]
    elif recipient == "each_opponent":
        victims = [
            game.players[i]
            for i in game.opponents_of(game.players.index(context.caster))
        ]
    elif recipient == "each_player":
        # "Each player mills two cards." (Whetstone.) CR 101.4's order — the
        # active player first, then the rest in turn order — and a seat that
        # has left the game mills nothing (CR 800.4a). The same shape
        # ``draw_target_cards`` reads for the same two words one zone over.
        total = len(game.players)
        active = game.active_player_index or 0
        victims = [
            game.players[seat]
            for seat in sorted(
                (i for i, p in enumerate(game.players) if not p.lost),
                key=lambda i: ((i - active) % total, i),
            )
        ]
    elif recipient == "damaged_player":
        seat = (context.trigger_context or {}).get("defending_player_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(f"{context.card.name}: no recorded player, no mill")
            return True, "resolved"
        victims = [game.players[seat]]
    elif recipient == "event_subject_player":
        # "At the beginning of each player's upkeep, **that player** mills a
        # card." (Worry Beads.) The seat whose step this firing is, frozen by
        # the upkeep announcement (CR 603.10) under the key every other reader
        # of those two words takes — the damage recipient beside it, the draw's
        # `drawer_seat_record`, `subject_filters`' "that player". A different
        # record from ``damaged_player`` above and deliberately a separate
        # branch: that one is the seat a damage event hit, and on a step
        # trigger nothing has hit anybody.
        #
        # No record mills nobody, never the ability's controller — the same
        # rule the damaged branch above follows, and for its reason: the
        # controller is the seat this must not hit on every upkeep but their
        # own.
        seat = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(f"{context.card.name}: no recorded player, no mill")
            return True, "resolved"
        victims = [game.players[seat]]
    elif recipient == "defending_player":
        # "Whenever this creature becomes blocked, **defending player** mills
        # three cards." (Flint Golem.) CR 506.2's seat, read from the key the
        # combat fire sites stamp — the same one the life loss and the poison
        # counter read — rather than from the board: the attacker can have left
        # combat by the time this resolves. No record mills nobody, never the
        # ability's controller, for the two branches above' reason.
        seat = (context.trigger_context or {}).get("trigger_defending_player_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(
                f"{context.card.name}: no recorded defending player, no mill"
            )
            return True, "resolved"
        victims = [game.players[seat]]
    else:
        victims = [context.target]
    # "…**If a card with the chosen name was milled this way**, you draw a
    # card." (Foreshadow.) What this step actually put into a graveyard, for
    # the sentence behind it — and nothing else can say: a graveyard holds
    # whatever else has gone there, and two copies of a card in a deck are the
    # same immutable object, so a name match over the pile would find the wrong
    # one. Under the key the repeated mill already writes, because "put into
    # that graveyard **this way**" is one question.
    put_there = context.results.setdefault(MILLED_THIS_WAY, [])
    for victim in victims:
        # CR 701.17a: "that player puts **that many cards from the top** of
        # their library into their graveyard" — the cards are the top N as the
        # mill begins, so they come off the library together and are then put
        # where they go one by one. It popped a card per iteration, which read
        # the same until something on the way to the graveyard touched the
        # library: Legacy Weapon milled first is shuffled back in, and the
        # *next* pop then took whatever the shuffle left on top — the Weapon
        # again as often as not — where the card under it is the one this
        # mill named.
        taken = victim.library[:max(0, int(amount))]
        del victim.library[:len(taken)]
        for card in taken:
            game.put_card_into_graveyard(victim, card, from_zone="library")
            put_there.append(card)
        game.log.append(f"{victim.name} milled {len(taken)} card(s)")
    return True, "resolved"


@effect_handler("mill_until_matching")
def mill_until_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target opponent mills a card, then repeats this process until a
    creature card or X cards have been put into their graveyard this way,
    whichever comes first." (Helm of Obedience, CR 701.17a per card.)

    A loop rather than a count, and the difference is the whole card: the
    library is asked one card at a time and *what came off the top* decides
    whether the next iteration happens. Reading it as ``mill_target_player``
    with an amount of X would mill X cards whatever was among them.

    Three ways it ends, and all three are the card's own sentence:

    * the stopping card was put into the graveyard - the loop stops **after**
      that card, which is what makes it reachable by the sentence behind this
      one;
    * the printed limit is reached (X, chosen as the ability was activated);
    * the library ran out. Not a loss: CR 704.5b fires on an attempted *draw*
      from an empty library, and a mill is not a draw. The same rule
      ``mill_target_player`` states one handler over.

    ``milled_this_way`` records the cards this loop put there that matched the
    stopping filter, which is what both sentences behind it read. The record is
    written even when it is empty - an absent key is a back-reference with no
    producer, which is a different thing from a producer that found nothing.
    """
    victim = context.target
    if victim is None:
        game.log.append(f"{context.card.name}: no player to mill")
        return True, "resolved"
    limit = resolve_amount(instruction.payload.get("limit", 0), context.x_value)
    stop_filter = dict(instruction.payload.get("stop_filter") or {})
    matched: list = []
    milled = 0
    while milled < limit and victim.library:
        card = victim.library.pop(0)
        game.put_card_into_graveyard(victim, card, from_zone="library")
        milled += 1
        if _card_matches_filter(card, stop_filter, game=game, owner=victim):
            matched.append(card)
            break
    context.results[MILLED_THIS_WAY] = matched
    game.log.append(
        f"{victim.name} milled {milled} card(s) "
        + (
            f"and stopped on {matched[0].name}"
            if matched
            else "without hitting "
            + ("a " + "/".join(stop_filter.get("type_filter") or ()) or "a card")
        )
    )
    return True, "resolved"


@effect_handler("put_milled_card_onto_battlefield")
def put_milled_card_onto_battlefield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…put one of them onto the battlefield under your control." (Helm of
    Obedience.)

    "Them" is the set the loop recorded, and reading it from the record rather
    than from the graveyard is the whole point: the pile also holds cards this
    effect never touched, and the card may take only the ones it put there.

    The set has one member, because the loop stops on the first card its filter
    matched - so the pick is not offered. A card that could put two matching
    cards in at once would need a prompt here, and nothing in this engine can:
    a mill is a direct move with no CR 614 seam of its own.

    The card is taken out of the graveyard **by identity**, because two copies
    of one card in a deck are the same ``CardDefinition`` object and
    ``list.remove`` compares by value - it would take whichever copy was
    nearest the bottom of the pile.
    """
    cards = list(
        context.results.get(
            instruction.payload.get("cards_from") or MILLED_THIS_WAY
        ) or ()
    )
    if not cards:
        game.log.append(f"{context.card.name}: nothing was put there this way")
        return True, "resolved"
    if instruction.payload.get("the_one_card") and len(cards) != 1:
        # "…return **it** from your graveyard to the battlefield" (Aether
        # Rift). A singular pronoun over a record holding several cards names
        # none of them; taking the first would be the effect acting on
        # whichever card the sample happened to draw first.
        game.log.append(f"{context.card.name}: \"it\" names no one card")
        return True, "resolved"
    card = cards[0]
    owner = next(
        (
            player for player in game.players
            if any(held is card for held in player.graveyard)
        ),
        None,
    )
    if owner is None:
        # It has already left the graveyard by some other route. CR 608.2's "as
        # much as possible" - and a card put onto the battlefield from nowhere
        # is a card this effect created.
        game.log.append(f"{card.name} is no longer in a graveyard")
        return True, "resolved"
    for index, held in enumerate(owner.graveyard):
        if held is card:
            del owner.graveyard[index]
            break
    seat = (
        game.players.index(context.caster)
        if instruction.payload.get("under_your_control")
        else game.players.index(owner)
    )
    arrival = Permanent(card=card)
    # CR 108.3: the owner is the player whose graveyard it came out of, and it
    # is recorded because the controller is somebody else — without it the card
    # would go to the thief's graveyard when it dies.
    arrival.metadata["owner_player_index"] = game.players.index(owner)
    game._put_permanent_onto_battlefield(seat, arrival, None)
    game.log.append(
        f"{game.players[seat].name} put {card.name} onto the battlefield"
    )
    game._recompute_continuous_effects()
    return True, "resolved"


@effect_handler("scry")
def scry(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """CR 701.22a: look at the top N cards of your library, put any number of
    them on the bottom in any order and the rest back on top in any order.

    Modelled as a *choice*, never as an application. Keeping everything on top
    is a legal outcome of a scry but never a legal implementation of one,
    because the decision is the whole effect — a handler that silently kept the
    cards would report the card supported while playing a different card. The
    seat is asked through the pending-choice queue, the same machinery
    ``reorder_target_library_top`` uses; a non-interactive seat is drained into
    the AI default.

    CR 701.22b: a scry of 0 is not a scry event at all, so nothing is armed —
    and a library with fewer than N cards simply offers what is there, since
    looking at the top of a short library is not a draw and CR 704.5b never
    fires.
    """
    caster = context.caster
    amount = resolve_amount(instruction.payload.get("amount", 1) or 1, context.x_value)
    top_count = min(amount, len(caster.library))
    if top_count <= 0:
        game.log.append(f"{caster.name} scries {amount} with nothing to look at")
        return True, "resolved"
    caster_index = game.players.index(caster)
    game.arm_pending_choice(
        "scry", caster_index,
        top_count=top_count, amount=amount, card_name=context.card.name,
    )
    game.log.append(f"{caster.name} is scrying {top_count}")
    return True, "pending_scry"


@effect_handler("surveil")
def surveil(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """CR 701.25a: look at the top N cards of your library, then put any number
    of them into your graveyard and the rest on top of your library in any
    order.

    Scry's decision with one destination changed, so it is scry's prompt with
    that destination as data (``destination: "graveyard"``) rather than a
    second prompt kind — the look, the arrangement, the validation and the
    suspension of the resolution behind it are the same, and one answer shape
    is one thing for a client to send. What differs is where the cards the
    seat does not keep go, and ``_resolve_scry`` reads that off the choice.

    CR 701.25c: a surveil of 0 is no surveil event, so nothing is armed; and a
    short library offers what is there (no draw, so CR 704.5b never fires).
    """
    caster = context.caster
    amount = resolve_amount(instruction.payload.get("amount", 1) or 1, context.x_value)
    top_count = min(amount, len(caster.library))
    if top_count <= 0:
        game.log.append(f"{caster.name} surveils {amount} with nothing to look at")
        return True, "resolved"
    game.arm_pending_choice(
        "scry", game.players.index(caster),
        top_count=top_count, amount=amount, card_name=context.card.name,
        destination="graveyard",
    )
    game.log.append(f"{caster.name} is surveilling {top_count}")
    return True, "pending_scry"


@effect_handler("each_player_draws_up_to_cards")
def each_player_draws_up_to_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each player may draw up to two cards." (Truce.)

    ``each_player_discards_up_to_cards``'s twin one zone over, and the same
    arrangement for the same reasons. One ``draw_up_to`` prompt per seat with
    the printed ceiling, offered in turn order (CR 101.4); the ceiling *is* the
    offer, since a player may answer with none, which is why the "may" in front
    of it collapses into this rather than arming a yes/no of its own
    (``engine/grammar/lowering/_collapses._each_player_optional_draw``).

    Every seat is recorded, including one that draws nothing, because "for each
    card less than two **a player** draws this way" is a number for every player
    and a seat the record never mentions has to read as zero rather than as a
    missing key. The scratchpad rides the prompt, so what is written is what the
    seat actually chose.
    """
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    caster_index = game.players.index(context.caster)
    if instruction.payload.get("actor") == "each_opponent":
        seats = [s for s in game.opponents_of(caster_index) if not game.players[s].lost]
    else:
        # CR 101.4: the active player first, then the rest in turn order.
        count = len(game.players)
        active = game.active_player_index or 0
        seats = sorted(
            (i for i, p in enumerate(game.players) if not p.lost),
            key=lambda i: ((i - active) % count, i),
        )
    by_seat = context.results.setdefault(DREW_BY_SEAT, {})
    for seat in seats:
        player = game.players[seat]
        by_seat[seat] = 0
        game.arm_pending_choice(
            "draw_up_to", seat,
            amount=amount,
            card_name=context.card.name,
            _results=context.results,
        )
        game.log.append(f"{player.name} may draw up to {amount} card(s)")
    return True, "resolved"


@effect_handler("draw_up_to_cards")
def draw_up_to_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"**Its controller** may draw up to two cards …" (Arcane Denial.)

    ``each_player_draws_up_to_cards``'s sibling with one seat instead of a set,
    through the same ``draw_up_to`` prompt: the printed ceiling *is* the offer,
    since a player may answer with none, which is why the "may" in front of it
    collapses into this rather than arming a yes/no of its own
    (``engine/grammar/lowering/_collapses._referent_seat_optional_draw``).

    The seat comes off the record named in the payload, never off
    ``context.target``. This sentence is printed inside a delay: it fires a turn
    after the counter, on somebody else's upkeep, and the spell whose controller
    it names is a card in a graveyard by then — CR 108.4 gives that card no
    controller at all. A record nothing wrote is a seat this sentence never
    named, so nobody draws, which is the same answer ``draw_target_cards`` gives
    one function up and for the same reason.
    """
    record = instruction.payload.get("drawer_seat_record")
    seat = (context.results or {}).get(record) if record else None
    if seat is None:
        # …and the frozen half. A delayed ability's context carries what the
        # creating effect knew (CR 608.2h), merged into the trigger context by
        # `create_delayed_trigger`; the live scratchpad of *this* resolution
        # holds nothing, because the step that wrote the seat ran a turn ago.
        seat = (context.trigger_context or {}).get(record) if record else None
    if seat is None:
        game.log.append(
            f"{context.card.name}: nothing recorded whose spell that was"
        )
        return True, "resolved"
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    drawer = game.players[int(seat)]
    context.results.setdefault(DREW_BY_SEAT, {})[int(seat)] = 0
    game.arm_pending_choice(
        "draw_up_to", int(seat),
        amount=amount,
        card_name=context.card.name,
        _results=context.results,
    )
    game.log.append(f"{drawer.name} may draw up to {amount} card(s)")
    return True, "resolved"
