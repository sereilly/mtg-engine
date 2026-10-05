from __future__ import annotations

import dataclasses
import random
from typing import TYPE_CHECKING

from ..auras import PUT_ONTO_BATTLEFIELD_BY
from ..exiled_records import (record_exiled_card, records_for_cards,
                              source_object)
from ..linked_exile import LEAVES, UNTAPPED, link_exiled_card, linked_entries, take_linked_entries
from ..keywords import grant_keyword
from ..models import Permanent
from ._common import (
    _card_matches_filter,
    _resolve_chosen_subtype,
    return_permanent_to_owners_hand,
    _one_choice,
    evaluate_count,
    per_recipient_amount,
    frozen_that_player_seat,
    excluded_graveyard_slot,
    graveyard_card_matches,
    permanent_matches_filter,
    resolve_amount,
    resolve_role_graveyard_card,
    resolve_role_permanent,
    resolve_target_permanent,
    resolve_target_permanents,
    roles_still_legal,
)
# The runtime class. The bare name is a TYPE_CHECKING-only import above, and
# two handlers here *build* instructions for an optional payment's branches.
from ..oracle_types import (DISCARDED_BY_SEAT, DREW_BY_SEAT, DREW_COUNT,
                            EXILED_BY_SEAT,
                            MILLED_THIS_WAY,
                           LAST_TARGET_CONTROLLER,
                            LAST_TARGET_NAME,
                            REVEALED_HAND_CARDS,
                            REVEALED_THIS_WAY,
                            REVEALED_TOP_CARDS_BY_SEAT,
                            EXILED_THIS_WAY, EXILED_THIS_WAY_OBJECTS,
                            HAND_CARDS_TO_LIBRARY, MILLED_THIS_WAY,
                            PER_OBJECT_SEAT_RECORDS,
                            SWEPT_OWNER_SEATS,
                            X_FROM_COUNT_PER_RECIPIENT)
from ..oracle_types import OracleInstruction as _OracleInstruction
from ..replacements import EXILE_ON_LEAVING_BATTLEFIELD
from ..revealed_hands import reveal_hand_while_present
from ..resumption import run_resumable
from ..search_filters import card_has_type, search_matches
from ..tokens import CREATED_TOKEN_RESULT_KEY, tokens_created_with
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
    if recipient in ("each_player", "each_opponent"):
        caster_index = game.players.index(context.caster)
        # CR 101.4's order for "each player", and the caster excluded for "each
        # opponent". A seat that has left the game draws nothing (CR 800.4a).
        if recipient == "each_opponent":
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
    drawn = game._draw_with_replacements(
        caster, resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    )
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


@effect_handler("put_exiled_pile_top_into_hand")
def put_exiled_pile_top_into_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put the top card of the exiled pile into its owner's hand." (Mangara's
    Tome.)

    "The exiled pile" is the linked record its other ability made (CR 610.3),
    read off this ability's own source. An empty pile puts nothing anywhere and
    says so — the card offers no other outcome, and this is where a Tome that
    has spent all five cards ends up.

    Into the hand through ``Game.put_card_into_hand``, like every other card
    reaching a hand, so CR 903.9b sees it.
    """
    from ..linked_exile import take_top_linked_entry

    source = context.source_permanent
    entry = take_top_linked_entry(source)
    if entry is None:
        game.log.append(f"{context.card.name}: the exiled pile is empty")
        return True, "resolved"
    owner = game.players[int(entry.get("owner_index", 0))]
    card = entry["card"]
    # The card leaves exile whether or not the hand accepts it: a commander
    # diverted to the command zone (CR 903.9b) has still left the pile. Through
    # the departure seam, so the exile register retires with it.
    game.take_card_from_exile(owner, card)
    game.put_card_into_hand(owner, card)
    game.log.append(
        f"{context.card.name}: {card.name} goes from the exiled pile to "
        f"{owner.name}'s hand"
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


@effect_handler("draw_then_discard_self")
def draw_then_discard_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Bazaar of Baghdad: "Draw two cards, then discard three cards." Affects
    the ability's own controller; the discard is non-random, so it becomes a
    pending choice (the same flow discard_target_cards uses)."""
    caster = context.caster
    card = context.card
    draw_count = int(instruction.payload.get("draw", 0))
    discard_count = int(instruction.payload.get("discard", 0))
    held_before = len(caster.hand)
    drawn = game._draw_with_replacements(caster, draw_count)
    game.log.append(f"{card.name}: {caster.name} drew {drawn} card(s)")

    # "…then discard one **of them**" (Krovikan Sorcerer). The candidates are
    # the positions this resolution's draw landed in, measured rather than
    # assumed from the count: a replacement can turn a draw into something else
    # (CR 614), so the hand may have grown by fewer cards than were asked for —
    # and a range computed off ``draw_count`` would then offer cards the seat
    # was already holding.
    only_indices = (
        list(range(held_before, len(caster.hand)))
        if instruction.payload.get("from_drawn") else None
    )
    actual_discard = min(
        discard_count,
        len(only_indices) if only_indices is not None else len(caster.hand),
    )
    if actual_discard <= 0:
        return True, "resolved"
    game.arm_pending_choice(
        "discard", game.players.index(caster),
        count=actual_discard,
        allow_top_of_library=game._controls_top_of_library_discard(caster),
        **({"only_indices": only_indices} if only_indices is not None else {}),
    )
    game.log.append(f"{caster.name} must choose {actual_discard} card(s) to discard")
    return True, "pending_discard"


@effect_handler("ante_top_card")
def ante_top_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Ante the top card of <possessive> library." (CR 407.)

    Who antes is payload: Demonic Attorney's "each player antes …" sweeps every
    seat, Rebirth's offer names the one seat that accepted it. It used to be two
    name-keyed handlers because the grammar had no word for the verb; the two
    cards print the same sentence with a different subject, which is exactly
    what a recipient key is for.

    CR 407.4 is why the seat is also the *owner* index handed to
    ``ante_object``: a card is anted by the player who owns it, so every ante
    here comes off that player's own library.
    """
    who = instruction.payload.get("players", "caster")
    if who == "each_player":
        # A player who has already left the game is nobody (CR 800.4a).
        seats = [i for i, p in enumerate(game.players) if not p.lost]
    elif who == "that_player":
        # The seat this resolution is currently about — the one that accepted
        # the offer in front of the ante. `handlers/control_flow.may` binds it
        # per prompt, so each accepting player antes their own card.
        seats = [game.players.index(context.target)]
    else:
        seats = [game.players.index(context.caster)]
    anted = 0
    for index in seats:
        player = game.players[index]
        if player.library:
            game.ante_object(index, player.library.pop(0))
            anted += 1
    game.log.append(f"{context.card.name} anted {anted} card(s)")
    # What the "if a player does" rider reads: whether an ante actually
    # happened. An empty library antes nothing, and the branch must not run.
    context.results["anted_cards"] = anted
    return True, "resolved"


@effect_handler("exchange_ante_with_top_library")
def exchange_ante_with_top_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Darkpact: "You own target card in the ante. Exchange that card with the
    top card of your library." With nothing of yours in the ante there is
    nothing to exchange (CR 608.2b: the effect does as much as it can)."""
    caster = context.caster
    card = context.card
    if not caster.ante:
        game.log.append(f"{card.name}: {caster.name} owns no card in the ante to exchange")
        return True, "resolved"
    if not caster.library:
        game.log.append(f"{card.name} resolved with no library card to exchange")
        return True, "resolved"
    chosen = context.target_permanent_index if isinstance(context.target_permanent_index, int) else 0
    if not (0 <= chosen < len(caster.ante)):
        chosen = 0
    anted = caster.ante.pop(chosen)
    # CR 407.4: the replacement card comes off the caster's own library, so the
    # caster is the player anting it.
    game.ante_object(game.players.index(caster), caster.library.pop(0))
    game.put_card_into_hand(caster, anted)
    game.log.append(
        f"{card.name}: {caster.name} exchanged {anted.name} in the ante "
        f"for the top card of their library"
    )
    return True, "resolved"


@effect_handler("ante_self_then_clear_ante_and_draw")
def ante_self_then_clear_ante_and_draw(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Jeweled Bird: "{T}: Ante this artifact. If you do, put all other cards
    you own from the ante into your graveyard, then draw a card."

    The ante is the *effect*, not part of the cost, so the Bird moves from the
    battlefield to the ante zone (CR 407) on resolution. The "if you do" rider
    only happens when it actually got anted — a Bird that has already left the
    battlefield antes nothing and the rest of the ability does nothing, and
    neither does one activated by a player who doesn't own it: CR 407.4 makes
    the owner the only player who can ante an object."""
    caster = context.caster
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    owner_index = game.owner_index_of(source_permanent)
    controller_seat = game.controller_index_of(source_permanent)
    controller = game.players[controller_seat] if controller_seat is not None else None
    if controller is None:
        game.log.append(f"{card.name} is no longer on the battlefield to ante")
        return True, "resolved"
    # CR 407.4: only the owner can ante it. A stolen Bird (Control Magic, Old Man
    # of the Sea) can be activated by its new controller, but the ante — and so
    # the whole "if you do" rider — simply doesn't happen.
    if not game.can_ante(game.players.index(caster), owner_index):
        game.log.append(
            f"{caster.name} doesn't own {card.name} and can't ante it (CR 407.4)"
        )
        return True, "resolved"
    # "All other cards you own from the ante" is everything the *ability's
    # controller* owns there before the Bird arrives — captured first, since a
    # CardDefinition is shared per name and identity alone couldn't tell a
    # previously anted copy apart from this one.
    others = list(caster.ante)
    game.remove_from_battlefield(source_permanent)
    game.ante_object(owner_index, source_permanent.card)
    game.log.append(f"{caster.name} anted {card.name}")

    # `others` is the exact prefix of caster.ante taken before the append, so
    # slicing it off leaves only the newly anted Bird.
    caster.ante = caster.ante[len(others):]
    for other in others:
        game.put_card_into_graveyard(caster, other)
    if others:
        game.log.append(
            f"{card.name} put {len(others)} other card(s) {caster.name} owns "
            "from the ante into their graveyard"
        )
    drawn = game._draw_with_replacements(caster, 1)
    game.log.append(f"{card.name} drew {drawn} card")
    return True, "resolved"




def _search_restrictions(game: Game, payload: dict, context) -> dict:
    """The armed search's restrictions, with the ones only a resolution can
    answer resolved.

    ``named_from_target`` is "a card **with the same name as target nontoken
    creature**" (Mask of the Mimic): the name is the chosen target's, which is
    not knowable when the card compiles. It is turned into an ordinary ``named``
    here, so every seat answers the same search — the engine re-checking a
    pick, the AI choosing for itself and the web picker offering a list all read
    ``search_filters.search_matches`` and none of them has a target in hand.

    A target that is gone by resolution (CR 608.2b removes it) leaves the key in
    place and no name behind it, and ``search_matches`` then matches nothing:
    the search finds no card rather than every card, which is the direction a
    dropped narrowing must never fail in.
    """
    restrictions = dict(payload.get("restrictions") or {})
    # "…a creature card with mana value **X** or less" (Citanul Flute). CR
    # 601.2b fixed X when the activation cost was paid, so by now it is a
    # number — resolved here, once, because every seat that answers this search
    # reads the armed restrictions and none of them has the activation in hand.
    # A symbol left in the payload would reach ``search_matches``' comparison
    # and be compared against a card's mana value as a string.
    mana_value = restrictions.get("mana_value")
    if isinstance(mana_value, dict) and mana_value.get("value") == "x":
        restrictions["mana_value"] = {
            **mana_value, "value": max(0, int(context.x_value or 0)),
        }
    # "…a card **with the same name as that creature**" (Remembrance). The name
    # of the object the firing event was about, turned into an ordinary
    # ``named`` here for ``named_from_target``'s reason one branch down: every
    # seat that answers this search reads the armed restrictions, and none of
    # them has a trigger context in hand.
    #
    # Off ``dead_card`` rather than off ``dead_name``, because that is the
    # channel every fire site in ``BOUND_CARD_EVENTS`` writes — the graveyard
    # arrival records the card and no name at all. A record nothing wrote leaves
    # the key in place with no name behind it, and ``search_matches`` then
    # matches nothing: the search finds no card rather than every card, which is
    # the direction a dropped narrowing must never fail in.
    if restrictions.get("named_from_event"):
        recorded = (context.trigger_context or {}).get("dead_card")
        name = getattr(recorded, "name", None)
        if name is not None:
            restrictions["named"] = name
    # "…a card **with the same name as that card**" (Assembly Hall). The name of
    # a card an earlier step of *this same effect* turned face up, read out of
    # the resolution's own scratchpad under the key the lowering named — the
    # third referent this function resolves, and it goes through the same
    # ``named`` for the two above's reason: every seat that answers this search
    # reads the armed restrictions, and none of them has the scratchpad.
    #
    # The record is a list (a reveal may turn up several), and the name is the
    # first entry's: the sentence says "that **card**", singular, and the only
    # printing of it reveals exactly one. A record that is empty — nothing was
    # revealed, because the hand held no card the phrase admits — leaves the key
    # in place with no name behind it, and ``search_matches`` then matches
    # nothing: the search finds no card rather than every card.
    record_key = restrictions.get("named_from_record")
    if record_key:
        revealed = context.results.get(str(record_key)) or ()
        first = next(iter(revealed), None)
        name = getattr(first, "name", None)
        if name is not None:
            restrictions["named"] = name
    if not restrictions.get("named_from_target"):
        return restrictions
    # Through the seam every handler resolves a chosen permanent by, so the
    # name read here is the object the announcement named -- an index alone
    # renumbers the moment anything leaves the battlefield, and the sacrifice
    # this card charges as an additional cost has already left one.
    chosen = resolve_target_permanent(game, context)
    if chosen is not None:
        # The **effective** name (CR 707.2 puts name first among the copiable
        # values): "the same name as target creature" aimed at a Clone copying
        # Grizzly Bears is a search for Grizzly Bears. The printed face read
        # here made Mask of the Mimic and Pack Hunt search for "Clone".
        restrictions["named"] = chosen.effective_card.name
    return restrictions


@effect_handler("search_library")
def search_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    caster_index = game.players.index(caster)
    # The zones the search may look in and the restriction on what it may find
    # both travel to the choice, so every seat answers the same search: the
    # engine re-checks the answer against them, the AI picks within them, and
    # the web layer offers them. Defaulting to the library alone keeps a
    # payload written before the graveyard existed meaning what it meant.
    zones = tuple(instruction.payload.get("zones", ("library",)))
    # "…from **its owner's** graveyard … under the control of **that
    # creature's owner**." (Reincarnation.) Whose zone is looked in and whose
    # battlefield receives are two questions, and neither is "the seat that
    # chooses" — CR 608.2c makes the chooser the ability's controller. Both
    # ride as seats so the picker, the AI and the resolver read one answer;
    # absent, they default to the chooser, which is every other card.
    seats: dict[str, int] = {}
    for key, payload_key in (
        ("zone_seat", "zone_owner"), ("battlefield_seat", "battlefield_owner"),
    ):
        named = instruction.payload.get(payload_key)
        if named is None:
            continue
        # Two places a named seat can come from, asked in the order they are
        # decided. A loop over the objects an earlier step recorded resolves its
        # per-object records for the iteration in progress — Glyph of
        # Reincarnation's "the graveyard of the player who controlled that
        # creature the last time it became blocked by that Wall". Outside a loop
        # there is only the trigger's own captured context. One lookup rather
        # than a payload flag saying which to consult, because the two never
        # both answer: a loop binding exists only inside its loop.
        seat = context.iteration_seats.get(str(named))
        if seat is None:
            seat = (context.trigger_context or {}).get(str(named))
        if seat is None:
            # The trigger that would have recorded it did not: CR 603.10's
            # last-known information is simply absent, so the effect falls back
            # to its controller rather than guessing a seat.
            continue
        seats[key] = int(seat)
    # "Search **target player's** library …" (Jester's Cap, Jester's Mask). The
    # seat is the ability's own target rather than a record an earlier trigger
    # wrote, so it is asked here and not through the loop above — a chosen
    # target is not something the trigger context holds. Whose battlefield or
    # hand receives follows it by default (`search_filters.landing_seat`), which
    # is what makes "that player puts those cards into their hand" land in the
    # searched player's hand and not the searcher's.
    if instruction.payload.get("zone_owner_target") and context.target is not None:
        if context.target in game.players:
            seats["zone_seat"] = game.players.index(context.target)
    # "…put that card onto the battlefield **under your control**." (Bribery.)
    # CR 110.2a's controller, and the one seat neither of the two readings above
    # can supply: it is not a record a trigger wrote and it is not the seat whose
    # library was opened — it is the ability's own controller, which is exactly
    # the seat ``landing_seat`` stops defaulting to the moment ``zone_seat`` is
    # set. Read after that block for that reason: written the other way round,
    # the searched player's seat would overwrite it and the creature would enter
    # on the side it came from.
    if instruction.payload.get("battlefield_under_caster"):
        seats["battlefield_seat"] = caster_index
    # "…for **that many** cards" — the number an earlier step of this same
    # resolution recorded (Jester's Mask's emptied hand). Read here rather than
    # baked into the payload, because the count is a fact about the board.
    counted_from = instruction.payload.get("amount_from")
    printed_count = instruction.payload.get("count", 1)
    if counted_from is not None:
        count = max(0, int(context.results.get(counted_from, 0) or 0))
    elif printed_count == "any":
        # "…for **any number of** Goblin cards" (Goblin Recruiter). CR 701.23a:
        # a search looks at every card in the zone, so the only ceiling is how
        # many of them the phrase admits — counted here, where the zones and the
        # seat are known, rather than baked into a payload that would then be a
        # printed ceiling the card does not have.
        #
        # It is a ceiling on the *slots*, not a promise: `up_to` rides with it,
        # so finding fewer (none included) stays a legal answer.
        from ..search_filters import search_matches
        searched_seat_index = seats.get("zone_seat", caster_index)
        looked_in = game.players[searched_seat_index]
        pool = [
            card
            for zone_name in zones
            for card in (
                looked_in.library if zone_name == "library" else looked_in.graveyard
            )
        ]
        count = sum(
            1 for card in pool
            if search_matches(
                card, instruction.payload, game=game, owner=caster_index,
            )
        )
    else:
        count = int(printed_count)
    destinations = list(instruction.payload.get("destinations") or ())
    if not destinations and count > 1:
        # A search for several cards that all go to one place (Jester's Cap's
        # three exiles). The counted flow is driven by one entry per find, so
        # the list is built here where the number is known — Cultivate's
        # printing carries its own, because its finds go to different places.
        destinations = [instruction.payload.get("destination", "hand")] * count
    if counted_from is not None and count <= 0:
        game.log.append(
            f"{context.card.name}: nothing was recorded to search for"
        )
        return True, "resolved"
    game.arm_pending_choice(
        "search_library", caster_index,
        **seats,
        count=count,
        card_type=instruction.payload.get("card_type", "any"),
        zones=zones,
        restrictions=_search_restrictions(game, instruction.payload, context),
        destination=instruction.payload.get("destination", "hand"),
        # "…put one onto the battlefield tapped and the other into your hand"
        # (Cultivate): one entry per find, in the printed order. A counted
        # search is answered whole — every find in one pick list — and which
        # find fills which slot is then its own question, asked through the
        # `search_destination` prompt when the slots differ.
        destinations=destinations,
        tapped=list(instruction.payload.get("tapped") or ()),
        # The searching card's name, for the prompts' labels — data, not
        # dispatch.
        card_name=context.card.name if context.card is not None else "",
        # The single-find spelling of the same fact, plus the conditional untap
        # rider that rides with it (Fabled Passage) — both belong to the search
        # rather than to a later sentence, because they are about the card it
        # finds.
        enters_tapped=bool(instruction.payload.get("enters_tapped")),
        untap_found_if=instruction.payload.get("untap_found_if"),
        up_to=bool(instruction.payload.get("up_to")),
        # "…and exile the rest." (Doomsday.) What happens to the searched piles
        # once the finds are out of them. It rides to the prompt like the zones
        # and the restriction do, because the seat that answers is the seat
        # whose zones are emptied and the answer is what says which cards
        # survive.
        exile_rest=bool(instruction.payload.get("exile_rest")),
        # "…, reveal it/those cards, …" (CR 701.20): the finds are shown to
        # every player, which the resolution records as one reveal event when
        # the search ends. A search that does not print the word shows nothing.
        reveal=bool(instruction.payload.get("reveal")),
        # The resolution's own scratchpad, so the search can write down what it
        # put onto the battlefield: "…put that card onto the battlefield, then
        # shuffle. **That Dragon** gains haste" (Zirilan of the Claw) names it,
        # and the search suspends on a prompt — by the time the sentence behind
        # it runs, the card is one permanent among many. Handed over here
        # because this is where the resolution and the prompt meet.
        record=context.results,
        # …and **under which key**, for a search whose finds are held rather
        # than placed (Intuition). Every other record this prompt writes is a
        # fact about the search itself and has one name; a held pile is a value
        # the *next sentence* reads, so the sentence that reads it is what names
        # the channel. Absent for every search written before this one.
        record_key=instruction.payload.get("record_key"),
    )
    # Whose zone, not the chooser's, because they are not always the same seat.
    searched = game.players[seats.get("zone_seat", caster_index)]
    game.log.append(
        f"{caster.name} is searching "
        + ("their " if searched is caster else f"{searched.name}'s ")
        + " and ".join(zones)
    )
    return True, "pending_search_library"


@effect_handler("reorder_target_library_top")
def reorder_target_library_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    caster_index = game.players.index(caster)
    target_index = game.players.index(target)
    top_count = min(3, len(target.library))
    # "You may have that player shuffle" (Natural Selection) lets the caster
    # optionally shuffle the target's library after reordering. Read off the
    # instruction, not the card: a handler that re-reads oracle text is a second
    # reading of a sentence the compiler already read, and the two drift.
    may_shuffle = bool(instruction.payload.get("may_shuffle"))
    game.arm_pending_choice(
        "reorder_library", caster_index,
        target_index=target_index, top_count=top_count, may_shuffle=may_shuffle,
    )
    game.log.append(f"{caster.name} is looking at the top {top_count} cards of {target.name}'s library")
    return True, "pending_reorder_library"


@effect_handler("reorder_own_library_top")
def reorder_own_library_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Look at the top four cards of your library, then put them back in any
    order." (Sage Owl.)

    ``reorder_target_library_top`` over the looker's **own** pile, and its own
    kind rather than that one with a seat swapped: that kind is registered in
    ``engine/targeting.py`` as targeting a player, so a trigger lowered onto it
    would go on the stack asking for a target Sage Owl never offers.

    One seat answers and one library is rearranged, and they are the same
    player by construction — the printed possessive says so — which is why
    neither is read off a target. How many cards is payload, where the printed
    sentence put it; the library being shorter is not an error (CR 609.3's "as
    many as you can"), and with fewer than two cards there is no order left to
    choose, so nothing is asked.
    """
    caster = context.caster
    seat = game.players.index(caster)
    top_count = min(
        resolve_amount(instruction.payload.get("amount", 0), context.x_value),
        len(caster.library),
    )
    if top_count < 2:
        game.log.append(
            f"{caster.name} has no order left to choose ({context.card.name})"
        )
        return True, "resolved"
    game.arm_pending_choice(
        "reorder_library", seat,
        target_index=seat, top_count=top_count, may_shuffle=False,
    )
    game.log.append(
        f"{caster.name} is looking at the top {top_count} cards of their library"
    )
    return True, "pending_reorder_library"


@effect_handler("choose_card_name")
def choose_card_name(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"**Choose a card name**, then target opponent mills a card…"
    (Foreshadow.)

    A step that produces a *value* and no effect, exactly as "choose a color"
    does. The name is chosen as the spell resolves (CR 608.2) and CR 202.1 lets
    a player name any card at all, so nothing is offered and nothing is
    validated — whatever the seat types is the name.

    Its own prompt kind rather than a fused whole-effect handler like the three
    naming paragraphs beside it (Demonic Consultation, Nebuchadnezzar,
    Necromentia). Those three read *what the name is for* in the same handler
    because their sentences share one pile; this one's name is read by an
    ordinary condition two sentences later, so the choice is a step and the
    reading is a condition.

    The prompt suspends the resolution (CR 608.2, CR 117.3b): the mill behind
    it must not run while the name is still owed, because a seat that saw the
    milled card before naming would be choosing with information the card does
    not give them.

    ``card_type`` is the printed bound on CR 202.1's freedom — "Choose a
    **creature** card name" (Wood Sage). It is carried to the prompt and the
    default is taken *within* it, because a headless game has to obey the same
    restriction the prompt does; the answer is checked against the catalog when
    it comes back, which is the only place a named card can be looked up at
    all.
    """
    seat = game.players.index(context.caster)
    card_type = instruction.payload.get("card_type") or None
    # "…other than a basic land card name" (Desperate Research): the other
    # printed bound, carried to the prompt and obeyed by the default exactly as
    # the type is.
    no_basics = bool(instruction.payload.get("exclude_basic_land_names"))
    game.arm_pending_choice(
        "choose_card_name", seat,
        card_name=context.card.name if context.card is not None else "",
        card_type=card_type,
        **({"exclude_basic_land_names": True} if no_basics else {}),
        # A non-interactive seat names the commonest card it may legally look
        # at — the opponents' graveyards, which CR 400.2 makes public. Naming
        # from a library or a hand would be the AI reading hidden information.
        # Nothing to see names nothing, which is legal and simply misses.
        default_name=_commonest_visible_name(
            game,
            next(iter(game.opponents_of(seat)), seat),
            ("graveyard",), exclude_basics=no_basics, card_type=card_type,
        ),
        record=context.results,
    )
    return True, "pending_choose_card_name"


@effect_handler("bin_revealed_card")
def bin_revealed_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…**put it into that player's graveyard**." (Wand of Denial.)

    The card an earlier step of this same resolution turned up, moved from
    wherever it still is to its **owner's** graveyard (CR 400.3) — which is the
    player whose library it came out of, not the seat that looked at it.

    Located by identity and removed by index: two copies of a card in a deck are
    the same immutable ``CardDefinition``, so ``list.remove`` would take
    whichever entry came first. A card that has moved since is left alone, which
    is CR 608.2 doing as much as it can.

    Through ``Game.put_card_into_graveyard``, the one seam a card reaches a
    graveyard by.
    """
    card = context.results.get("revealed_card")
    if card is None:
        game.log.append(f"{context.card.name}: no card was turned up")
        return True, "resolved"
    for player in game.players:
        for index, held in enumerate(player.library):
            if held is card:
                player.library.pop(index)
                game.put_card_into_graveyard(player, held, from_zone="library")
                game.log.append(
                    f"{context.card.name}: {held.name} goes into "
                    f"{player.name}'s graveyard"
                )
                return True, "resolved"
    game.log.append(f"{context.card.name}: {card.name} has already moved")
    return True, "resolved"


@effect_handler("reveal_top_opponent_chooses")
def reveal_top_opponent_chooses(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Reveal the top three cards of your library. Target opponent chooses one
    of those cards. Put that card into your graveyard." (Thran Tome.)

    The reveal and the choice are one step because the choice is made **from**
    what the reveal showed \u2014 ``reveal_hand_and_choose`` one zone over records
    the same reasoning. What is new here is *who* chooses: CR 608.2c makes the
    ability's controller the actor for everything the sentence does not say
    otherwise about, and this sentence says otherwise, so the prompt is queued
    on the opponent's seat with the revealer's carried as payload.

    CR 701.20 moves nothing, so the cards stay on top of the library and the
    answer moves exactly one of them. Fewer cards than the printed number is a
    legal board \u2014 the reveal shows what is there \u2014 and an empty library shows
    nothing and chooses nothing.
    """
    caster = context.caster
    caster_index = game.players.index(caster)
    opponent = context.target
    if opponent not in game.players:
        game.log.append(f"{context.card.name}: no opponent to choose")
        return True, "resolved"
    opponent_index = game.players.index(opponent)
    count = resolve_amount(instruction.payload.get("count", 1) or 1, context.x_value)
    # **The pile may be a graveyard instead** (Phyrexian Grimoire: "target
    # opponent chooses one of the top two cards of your graveyard"). The same
    # question and the same prompt, with two things read off the payload: there
    # is no reveal, because CR 400.2 makes a graveyard public and there is
    # nothing to show anybody; and CR 404.2 keeps a graveyard in the order
    # cards reached it, newest on top, so "the top two" are the *last* two of
    # the list rather than the first. An absent `from_zone` is the library, so
    # every payload written before this is unchanged.
    from_zone = str(instruction.payload.get("from_zone", "library"))
    # **The pile may already be out of every zone**, held by an earlier step of
    # this same resolution (Intuition: "Search your library for three cards and
    # reveal them. Target opponent chooses one."). A third pile source and the
    # same question, which is why it rides the payload rather than forking the
    # kind: what this instruction does is *ask an opponent which of these
    # cards*, and where they came from is data.
    #
    # The search revealed them already (its printed "reveal them", CR 701.20a)
    # and shuffled already (CR 701.23h), so neither happens again here — and
    # ``from_zone`` becomes "held", which is the word the mover reads as "this
    # card is in no zone; just place it".
    held_key = instruction.payload.get("cards_from")
    if held_key is not None:
        revealed = list(context.results.get(str(held_key)) or ())
        from_zone = "held"
        if not revealed:
            # The search found nothing, which an empty library makes the only
            # possible answer (CR 701.23d's "as many as possible"). There is
            # nothing to choose between.
            game.log.append(
                f"{context.card.name}: nothing was found to choose from"
            )
            return True, "resolved"
    else:
        pile = list(getattr(caster, from_zone, ()))
        revealed = (
            list(reversed(pile[-max(int(count), 0):])) if from_zone == "graveyard"
            else pile[:max(int(count), 0)]
        )
    if not revealed:
        game.log.append(f"{caster.name} has no cards in their {from_zone}")
        return True, "resolved"
    if from_zone == "library":
        game.record_reveal(caster_index, [card.name for card in revealed])
        game.log.append(
            f"{caster.name} revealed {', '.join(card.name for card in revealed)} "
            f"from the top of their library"
        )
    game.arm_pending_choice(
        "opponent_picks_revealed", opponent_index,
        card_name=context.card.name if context.card is not None else "",
        revealer_index=caster_index,
        cards=[card.name for card in revealed],
        fate=str(instruction.payload.get("fate", "graveyard")),
        from_zone=from_zone,
        # "…and put **the other one** into your hand." What the pick did *not*
        # take, which only a pile the sentence keeps talking about can have.
        # Absent for a library pile, where CR 701.20b leaves the rest where
        # they were.
        other_fate=instruction.payload.get("other_fate"),
        # The card objects, so the answer moves the card that was *revealed*
        # rather than whatever has since slid into that library slot. Private,
        # like every live reference on a prompt.
        _cards=revealed,
    )
    return True, "resolved"


@effect_handler("reveal_top_sorting_by_chosen_name")
def reveal_top_sorting_by_chosen_name(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Reveal the top four cards of your library and put all of them with that
    name into your hand. Put the rest into your graveyard." (Wood Sage.)

    One step for both printed sentences, because "the rest" is exactly what the
    first did not take: split apart, the second would move cards out of a pile
    nothing had recorded.

    The name is the one the ability's earlier step wrote into this resolution's
    scratchpad (``chosen_card_name``), and the lowering refuses the sentence
    without that step — so an absent record here means the seat named nothing,
    which is a legal answer that matches nothing. It is **not** treated as
    "match everything": the whole pile would go to the hand, which is the
    opposite of what an empty name means.

    CR 701.20 shows the cards and moves none of them, so the pile is taken off
    the library here and every card is placed by this handler. Fewer cards than
    the printed number is an ordinary board — the reveal shows what is there.

    Both zones are reached through the seams that own them
    (``put_card_into_hand``, ``put_card_into_graveyard``), never by appending
    to a list: CR 903.9b rides the first and the discard/mill watchers ride the
    second.
    """
    caster = context.caster
    seat = game.players.index(caster)
    count = resolve_amount(
        instruction.payload.get("amount", 0) or 0, context.x_value
    )
    revealed = caster.library[:max(int(count), 0)]
    if not revealed:
        game.log.append(f"{caster.name} has no cards to reveal")
        return True, "resolved"
    del caster.library[:len(revealed)]
    game.record_reveal(seat, [card.name for card in revealed])
    named = str(context.results.get("chosen_card_name") or "").strip()
    game.log.append(
        f"{caster.name} revealed {', '.join(card.name for card in revealed)}"
    )
    _place_sorted_reveal(
        game, caster, revealed, instruction.payload,
        lambda card: bool(named) and card.name == named,
    )
    return True, "resolved"


def _place_sorted_reveal(game, caster, revealed, payload, matches) -> None:
    """Split one revealed pile between its two printed zones.

    The half :func:`reveal_top_sorting_by_chosen_name` and
    :func:`reveal_top_sorting_by_filter` share: the two cards differ in what
    "matches" means and in nothing else, so the predicate is the argument and
    the procedure is written once. Two copies would be one card's fix landing
    on one of them.

    Both zones are reached through the seams that own them
    (``put_card_into_hand``, ``put_card_into_graveyard``), never by appending to
    a list: CR 903.9b rides the first and the discard/mill watchers ride the
    second.
    """
    match_zone = str(payload.get("match_zone", "hand"))
    rest_zone = str(payload.get("rest_zone", "graveyard"))
    for card in revealed:
        zone = match_zone if matches(card) else rest_zone
        if zone == "hand":
            game.put_card_into_hand(caster, card)
        elif zone == "battlefield":
            # "…puts all land cards revealed this way onto the battlefield
            # **tapped**." (Clear the Land.) CR 110.2 gives a permanent nobody
            # was told to control to its owner, which here is the player whose
            # library it came out of — the same seat that revealed it, because
            # the printed subject of both clauses is one player. ``tapped`` is
            # CR 110.5b and only ever rides the match half, which is where the
            # word is printed.
            game._put_permanent_onto_battlefield(
                game.players.index(caster),
                Permanent(card=card, tapped=bool(payload.get("match_tapped"))),
                None,
            )
        elif zone == "exile":
            # CR 406.3: an exiled card goes to its owner's exile, which for a
            # card off the top of a library is the seat whose library it was.
            caster.exile.append(card)
        else:
            game.put_card_into_graveyard(caster, card, from_zone="library")


@effect_handler("reveal_top_sorting_by_filter")
def reveal_top_sorting_by_filter(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Reveal the top four cards of your library. Put all land cards revealed
    this way into your hand and the rest into your graveyard." (Mulch.)

    :func:`reveal_top_sorting_by_chosen_name` with the predicate printed on the
    card rather than read out of the resolution's scratchpad. One step for both
    printed sentences for that handler's reason: "the rest" is exactly what the
    first did not take, so split apart the second would move cards out of a
    pile nothing had recorded.

    CR 701.20 shows the cards and moves none of them, so the pile is taken off
    the library here and every card is placed by this handler. Fewer cards than
    the printed number is an ordinary board — the reveal shows what is there.
    """
    count = resolve_amount(
        instruction.payload.get("amount", 0) or 0, context.x_value
    )
    described = dict(instruction.payload.get("filter") or {})
    # "**Each player** reveals the top five cards of **their** library."
    # (Clear the Land.) One seat or every seat, and the procedure below is
    # identical either way — which is why this is a loop over a seat list
    # rather than a second handler. In APNAP order (CR 101.4), because the
    # sentence is one effect several players perform and the turn order is what
    # decides who reveals first.
    if instruction.payload.get("whose") == "each_player":
        table = len(game.players)
        active = (
            game.active_player_index
            if game.active_player_index is not None else 0
        )
        seats = [(active + offset) % table for offset in range(table)]
    else:
        seats = [game.players.index(context.caster)]
    for seat in seats:
        looked = game.players[seat]
        revealed = looked.library[:max(int(count), 0)]
        if not revealed:
            game.log.append(f"{looked.name} has no cards to reveal")
            continue
        del looked.library[:len(revealed)]
        game.record_reveal(seat, [card.name for card in revealed])
        game.log.append(
            f"{looked.name} revealed {', '.join(card.name for card in revealed)}"
        )
        _place_sorted_reveal(
            game, looked, revealed, instruction.payload,
            lambda card, _owner=looked: _card_matches_filter(
                card, described, game=game, owner=_owner
            ),
        )
    return True, "resolved"


@effect_handler("put_revealed_card_onto_battlefield")
def put_revealed_card_onto_battlefield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Reveal the top card of your library. If it's a creature card, **put it
    onto the battlefield**." (Call of the Wild.)

    ``bin_revealed_card`` above with the other destination, and located the same
    way and for the same reason: CR 701.20 moves a revealed card nowhere, so it
    is still in the library it was turned up in — found by **identity**, because
    two copies of a card in a deck are the same immutable ``CardDefinition`` and
    ``list.remove`` would take whichever entry came first.

    It enters under its owner's control, which is the seat whose library it came
    out of: the sentence names no other, and CR 110.2 gives a permanent nobody
    was told to control to its owner. A card that has moved since is left alone
    — CR 608.2 doing as much as it can.
    """
    card = context.results.get("revealed_card")
    if card is None:
        game.log.append(f"{context.card.name}: no card was turned up")
        return True, "resolved"
    for seat, player in enumerate(game.players):
        for index, held in enumerate(player.library):
            if held is card:
                player.library.pop(index)
                game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
                game.log.append(
                    f"{context.card.name}: {card.name} enters the battlefield"
                )
                return True, "resolved"
    game.log.append(f"{context.card.name}: {card.name} has already moved")
    return True, "resolved"


@effect_handler("graveyard_top_to_library")
def graveyard_top_to_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"If the top card of target player's graveyard is a creature card, put
    that card on top of that player's library." (Guiding Spirit.)

    The printed "if" is performed here rather than as a condition over this
    step, because both halves name the same card: the top of the graveyard is
    read once, tested, and moved. Split into an ``if_then`` the test would ask
    about one card and the move would go and find the top again — the same card
    today and a different one the moment anything at all happens between them.

    **The top of a graveyard is the last card put into it**, which this engine
    keeps as the *end* of the list: every path that bins a card appends. So the
    read is ``[-1]``, and getting that backwards would move the oldest card in
    the pile — a card that plays, reports supported and does the wrong thing.

    Through ``Game.put_card_into_library``, the one seam every "put this card
    into a library" goes through (CR 903.9b has no single fire site).
    """
    target = context.target
    if target is None:
        return False, "no target player"
    if not target.graveyard:
        game.log.append(f"{context.card.name}: {target.name}'s graveyard is empty")
        return True, "resolved"
    top = target.graveyard[-1]
    described = instruction.payload.get("filter") or {}
    if described and not _card_matches_filter(
        top, described, game=game, owner=target
    ):
        game.log.append(
            f"{context.card.name}: {top.name} is not what the ability names"
        )
        return True, "resolved"
    # Popped by index rather than by ``remove``: two copies of a card in a deck
    # are the same immutable ``CardDefinition``, so a value comparison would
    # take whichever entry came first.
    target.graveyard.pop(len(target.graveyard) - 1)
    game.put_card_into_library(target, top, "top")
    game.log.append(
        f"{context.card.name}: {top.name} goes on top of {target.name}'s library"
    )
    return True, "resolved"


@effect_handler("look_at_target_library_top")
def look_at_target_library_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Look at the top five cards of target player's library. You may then
    have that player shuffle that library." (Visions.)

    The same prompt ``reorder_target_library_top`` above raises, with the
    rearranging switched off — the two cards look at the same pile and offer
    the same shuffle, and Visions simply never gets to put the cards back in an
    order of its choosing. ``may_reorder`` is enforced in
    ``Game._resolve_reorder_library`` rather than only in the UI: a permission
    the client alone honours is a rule nothing enforces.

    How many cards and whether the shuffle is offered are read off the payload,
    where the sentence put them.
    """
    caster = context.caster
    target = context.target
    if target is None:
        return False, "no target player"
    top_count = min(
        resolve_amount(instruction.payload.get("amount", 0), context.x_value),
        len(target.library),
    )
    # "Look at the top card of target player's library. **If it's a nonland
    # card**, …" (Wand of Denial.) The sentences behind a look name the card it
    # turned up, and this is the only step that can say which one that is —
    # by the time they run the resolution has suspended on the prompt and come
    # back. Under the key every "is it a …?" clause in this engine already
    # reads: a look and a reveal differ in *who sees* the card (CR 701.20 shows
    # it to everybody), and the pronoun behind either names the same object.
    #
    # Only the single-card look records one, because "it" is unambiguous only
    # there — a look at five cards names no single card at all. The prompt this
    # arms cannot reorder or shuffle, so the card recorded here is still the
    # card on top when the sentences behind it run.
    if top_count == 1 and target.library:
        context.results["revealed_card"] = target.library[0]
    game.arm_pending_choice(
        "reorder_library", game.players.index(caster),
        target_index=game.players.index(target),
        top_count=top_count,
        may_shuffle=bool(instruction.payload.get("may_shuffle")),
        may_reorder=False,
    )
    game.log.append(
        f"{caster.name} is looking at the top {top_count} cards of {target.name}'s library"
    )
    return True, "pending_reorder_library"


@effect_handler("discard_target_cards")
def discard_target_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    # ``who: "defending_player"`` names the seat the combat fire site froze into
    # the trigger's context (CR 506.2) rather than a seat anybody targeted —
    # Mindstab Thrull, whose discard has no target at all. The same key
    # ``discard_x_target_cards`` reads for the random half of the same sentence,
    # so one printed phrase resolves to one seat whichever handler runs it.
    if instruction.payload.get("who") == "defending_player":
        seat = (context.trigger_context or {}).get("trigger_defending_player_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            # The attacker can leave combat before this resolves, and a seat
            # nobody recorded is not a seat to empty a hand from.
            return True, "resolved"
        target = game.players[seat]
    if instruction.payload.get("who") == "event_subject_controller":
        # "Whenever a green creature dies, **its controller** discards a card."
        # (Bereavement.) The seat that controlled what the firing event was
        # about, frozen by the fire site (CR 603.10) because by now the
        # permanent is a card in a graveyard and CR 108.4 gives it no
        # controller. The same key the damage, sacrifice and life-gain handlers
        # read for the same printed phrase, so one possessive names one player
        # whatever the sentence goes on to do to them.
        seat = (context.trigger_context or {}).get("event_subject_controller")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            # A seat nobody froze is not a hand to empty. Dropping the phrase
            # would discard from whichever player a targetless resolution
            # defaults to — the ability's own controller on this card.
            game.log.append(
                f"{context.card.name if context.card else 'the ability'}: "
                "no player was named to discard"
            )
            return True, "resolved"
        target = game.players[seat]
    actual = min(
        resolve_amount(instruction.payload.get("amount", 0), context.x_value), len(target.hand)
    )
    # "…then draws as many cards as they discarded this way" (Forget) reads the
    # count back out of the scratchpad, so a discard that never happened has to
    # leave a zero rather than no key at all — a missing key and a zero read the
    # same to the draw, and writing it is what says the number is this step's
    # answer rather than an absence.
    context.results["discarded_count"] = 0
    if actual <= 0:
        game.log.append(f"{target.name} has no cards to discard")
        return True, "resolved"
    # This is a non-random discard ("discards a card"), so the discarding player
    # chooses which card. Defer to a pending choice; the UI prompts the human and
    # the AI auto-resolves it. Library of Leng lets them choose top-of-library.
    player_index = game.players.index(target)
    game.arm_pending_choice(
        "discard", player_index,
        count=actual,
        allow_top_of_library=game._controls_top_of_library_discard(target),
        # The scratchpad rides the prompt: how many cards actually went is not
        # known until the seat answers, and `_after_discard_answered` is the one
        # place both answer paths (a seat's own picks and the non-interactive
        # default) reach.
        _results=context.results,
    )
    game.log.append(f"{target.name} must choose {actual} card(s) to discard")
    return True, "pending_discard"


@effect_handler("each_opponent_discards_cards")
def each_opponent_discards_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each opponent discards two cards." (Bad Deal.) A chosen discard per
    opponent, so each gets their own pending choice; an AI seat answers with
    the discard default the moment it is armed, a human's queues."""
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    caster_index = game.players.index(context.caster)
    any_pending = False
    for seat in game.opponents_of(caster_index):
        opponent = game.players[seat]
        actual = min(amount, len(opponent.hand))
        if actual <= 0:
            game.log.append(f"{opponent.name} has no cards to discard")
            continue
        game.arm_pending_choice(
            "discard", seat,
            count=actual,
            allow_top_of_library=game._controls_top_of_library_discard(opponent),
        )
        game.log.append(f"{opponent.name} must choose {actual} card(s) to discard")
        any_pending = True
    return True, ("pending_discard" if any_pending else "resolved")


@effect_handler("opponent_discards_random_card_on_damage")
def opponent_discards_random_card_on_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Hypnotic Specter: "Whenever this creature deals damage to a player, that
    player discards a card at random." Resolves off the stack; the player who took
    the damage is carried in ``trigger_context``."""
    tctx = context.trigger_context or {}
    idx = tctx.get("defending_player_index")
    if idx is None or not (0 <= idx < len(game.players)):
        return True, "resolved"
    defending = game.players[idx]
    if defending.hand:
        discarded = defending.hand.pop(random.randrange(len(defending.hand)))
        game._discard_card(defending, discarded)
        game.log.append(f"{context.card.name}: {defending.name} discards {discarded.name} at random")
    return True, "resolved"


def _resolve_one_discard(game: Game, player_index: int, hand_index: int, to_library: bool) -> bool:
    """Move one chosen card from a player's hand to their graveyard (or, with
    Library of Leng, the top of their library). Returns False on a bad index."""
    if not (0 <= player_index < len(game.players)):
        return False
    player = game.players[player_index]
    if not (0 <= hand_index < len(player.hand)):
        return False
    card = player.hand.pop(hand_index)
    choice = game.pending_choice_of("discard", player_index)
    allow_top = bool(choice is not None and choice.data.get("allow_top_of_library"))
    if to_library and allow_top:
        game.put_card_into_library(player, card, "top")
        game.log.append(f"{player.name} discarded {card.name} to the top of their library (Library of Leng)")
    else:
        game.put_card_into_graveyard(player, card)
        game.log.append(f"{player.name} discarded {card.name}")
    # The discarded card's own trigger (CR 113.6, Psychic Purge — a sorcery
    # whose ability would otherwise function only on the stack, and whose
    # trigger condition can only be met in a hand). This is the
    # *second* place a card is discarded — `Game._discard_card` is the other —
    # and the two differ because this one already performed Library of Leng's
    # replacement itself, by offering the destination. So the announcement is
    # its own call rather than a third spelling of the move, and it is here
    # because a trigger honoured on one path and not the other is the shape
    # that hides.
    #
    # The causing seat comes off the prompt (`_cause_seat`, stamped by
    # `arm_pending_choice` from the resolving stack): by the time a prompt is
    # answered the resolution that armed it has returned, so `resolving_seats`
    # is empty and reading it here would say "nobody caused this".
    game._announce_discard_triggers(
        player, card,
        cause_seat=(choice.data.get("_cause_seat") if choice is not None else None),
    )
    # …and the board's watchers (Necropotence). The second of the two discard
    # seams: a watcher announced on one path only would fire for a random
    # discard and not for a chosen one, which is half the cards in the pool.
    game.announce_discard(player, card)
    return True


@effect_handler("discard_x_target_cards")
def discard_x_target_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target player discards X cards at random." (Mind Twist.) "Target player
    discards a card at random." (Gwendlyn Di Corci.)

    One handler, because only the *number* differs and who picks the cards —
    nobody, `random.sample` does — is what separates a discard handler from its
    sibling. The count is therefore payload with the chosen X as its fallback,
    rather than a second kind: a printed count baked into the kind name would
    make every other printed number a new kind with a new handler, which is the
    shape this codebase refuses everywhere else. The kind keeps its historical
    name; the X in it is where the count *used* to live.

    ``who: "defending_player"`` names the seat the combat fire site froze into
    the trigger's context (CR 506.2) rather than a seat anybody targeted — Cloak
    of Confusion, whose discard has no target at all. ``who: "caster"`` names
    the ability's own controller (CR 608.2's unwritten subject) — Ring of
    Renewal's "discard a card at random, then draw two cards", which likewise
    targets nobody. Payload for the same reason the count is: the sample and the
    move are identical, and only who holds the hand differs.

    The default stays ``context.target``, and the two named seats exist because
    it is *not* a safe default for an effect that chose no target: the context's
    target for a targetless activation is the opponent, so an unnamed seat here
    would empty the wrong hand and log itself resolved.
    """
    target = context.target
    if instruction.payload.get("who") == "caster":
        target = context.caster
    if instruction.payload.get("who") == "defending_player":
        seat = (context.trigger_context or {}).get("trigger_defending_player_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            # The attacker can leave combat before this resolves, and a seat
            # nobody recorded is not a seat to empty a hand at random from.
            return True, "resolved"
        target = game.players[seat]
    if instruction.payload.get("who") == "event_subject_player":
        # "At the beginning of each player's upkeep, **that player** discards a
        # card at random." (Bottomless Pit.) The seat the firing event froze —
        # a different player on every upkeep, and never the source's controller
        # except on one turn in four. Read through the one reader of the printed
        # phrase, so this and any sentence beside it name the same player.
        seat = frozen_that_player_seat(game, context)
        if seat is None:
            # A seat nobody froze is not a hand to empty at random. Ending the
            # effect is the honest direction: dropping the narrowing here would
            # discard from whichever player a targetless resolution defaults to.
            game.log.append(
                f"{context.card.name if context.card else 'the ability'}: "
                "no player was named to discard"
            )
            return True, "resolved"
        target = game.players[seat]
    amount = instruction.payload.get("amount")
    if not isinstance(amount, int):
        amount = context.x_value
    x = max(0, amount or 0)
    # "…discards a **creature** card at random." (Rag Man.) The sample is drawn
    # from the slots answering the printed phrase, not from the whole hand —
    # re-checked here rather than trusted from the lowering, which is the same
    # rule every other narrowed handler follows. No filter is every slot, which
    # is what Mind Twist has always meant.
    filters = instruction.payload.get("filter") or {}
    eligible = [
        index for index, held in enumerate(target.hand)
        if not filters or _card_matches_filter(held, filters, game=game, owner=target)
    ]
    actual = min(x, len(eligible))
    # ``random.sample`` over the eligible slots, drawing from the module-level
    # RNG ``run_ai_simulation`` seeds — so a given seed still replays a run
    # exactly, which sampling from a fresh Random() would break.
    indices = random.sample(eligible, actual)
    for i in sorted(indices, reverse=True):
        discarded = target.hand.pop(i)
        game._discard_card(target, discarded)  # Library of Leng -> top of library
    game.log.append(f"{target.name} discarded {actual} cards at random")
    return True, "resolved"


def _resolve_graveyard_slots(caster, context, count, eligible):
    """The cards *count* chosen graveyard slots name, removed from the graveyard.

    **An index is not an identity** (ROADMAP idiom #11), and a graveyard is the
    hand's case rather than the battlefield's: a card there has no
    ``permanent_id``, and two copies of one card are literally one
    ``CardDefinition`` object, so neither an id nor ``is`` can tell two slots
    apart. What can is the order of removal. Each slot is resolved to its card
    *before* anything leaves the zone, and the removals then run highest index
    first, because popping slot 0 slides every later card down one and would
    hand slot 1 the wrong card - the graveyard spelling of the bug
    :func:`resolve_target_slots` exists for on the battlefield.

    A repeated index collapses: CR 601.2c says one instance of "target" cannot
    name the same object twice, so a client sending ``[0, 0]`` gets one card
    back, not two. A slot that is out of range or names an ineligible card is
    dropped (CR 608.2b) and the rest of the effect still happens; an empty
    answer is a legal outcome of "up to N".
    """
    chosen = context.target_permanent_index
    slots = chosen if isinstance(chosen, list) else ([] if chosen is None else [chosen])
    graveyard = caster.graveyard
    seen: set[int] = set()
    resolved: list[tuple[int, object]] = []
    for slot in slots[:count]:
        if not isinstance(slot, int) or slot in seen:
            continue
        if not (0 <= slot < len(graveyard)) or not eligible(graveyard[slot]):
            continue
        seen.add(slot)
        resolved.append((slot, graveyard[slot]))
    for index, _card in sorted(resolved, key=lambda pair: pair[0], reverse=True):
        graveyard.pop(index)
    # Printed order, not removal order: the hand and the log read left to right.
    return [card for _index, card in resolved]


@effect_handler("place_held_card")
def place_held_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Put the card a "held" search found where a later step decided.

    Its own instruction kind because it is what the branches of Transmute
    Artifact's optional payment *are*: the `may` machinery runs instruction
    lists, so "put it onto the battlefield" and "put it into its owner's
    graveyard" have to be instructions rather than closures.
    """
    card = context.results.get("found_card")
    if card is None:
        return True, "resolved"
    context.results["found_card"] = None
    seat = game.players.index(context.caster)
    destination = str(instruction.payload.get("destination", "battlefield"))
    if destination == "battlefield":
        game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
        game.log.append(f"{card.name} enters the battlefield")
        return True, "resolved"
    # CR 400.3: a card put into a graveyard goes to its **owner's**, and the
    # only owner a library card can have is the player whose library it was.
    game.put_card_into_graveyard(seat, card, from_zone="library")
    game.log.append(f"{card.name} is put into its owner's graveyard")
    return True, "resolved"


@effect_handler("transmute_by_sacrifice")
def transmute_by_sacrifice(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Transmute Artifact's whole effect.

    Three decisions in a row, each one shaping the next: what to give up, what
    to look for, and — only when the find costs more than what went — whether to
    pay the difference. So the steps run through ``run_resumable``: the first two
    suspend on a prompt, and the work behind each is recorded rather than run
    against an answer nobody has given yet.

    Every piece is the engine's existing machinery. The sacrifice is the
    standing forced-sacrifice prompt, told to record what it took (CR 608.2h —
    by the time the comparison runs the artifact is a card in a graveyard, and a
    different object); the search is the standing library search with the find
    *held* rather than placed, because where it goes is the next step's
    decision; and the payment is the ordinary optional-pay entry whose accept
    and decline branches are the two placements the card prints.
    """
    caster = context.caster
    seat = game.players.index(caster)
    results = context.results

    def _sacrifice(_step) -> None:
        game.arm_forced_sacrifice(
            seat, 1,
            filter=dict(instruction.payload.get("sacrifice_filter") or {}),
            reason=context.card.name if context.card is not None else "Transmute",
            record=results,
        )

    def _search(_step) -> None:
        given = list(results.get("sacrificed_cards") or ())
        if not given:
            # "**If you do**" — nothing was given up, so nothing follows.
            game.log.append(f"{context.card.name}: nothing was sacrificed")
            return
        game.arm_pending_choice(
            "search_library", seat,
            count=1,
            card_type=(instruction.payload.get("search_filter") or {}).get(
                "type_filter", "any"
            ),
            zones=("library",),
            restrictions={},
            destination="held",
            destinations=[],
            tapped=[],
            card_name=context.card.name if context.card is not None else "",
            enters_tapped=False,
            untap_found_if=None,
            up_to=False,
            reveal=False,
            record=results,
        )

    def _place(_step) -> None:
        card = results.get("found_card")
        given = list(results.get("sacrificed_cards") or ())
        if card is None or not given:
            return
        paid_for = int(getattr(given[0], "cmc", 0) or 0)
        wanted = int(getattr(card, "cmc", 0) or 0)
        if wanted <= paid_for:
            game._execute_oracle_instruction(
                _OracleInstruction("place_held_card", "", {"destination": "battlefield"}),
                context,
            )
            return
        # "If it's greater, you may pay {X}, where X is the difference." The
        # number is the difference and nothing else, so it is computed here
        # rather than asked for — CR 107.3 lets a cost name a value the effect
        # fixes.
        difference = wanted - paid_for
        game.arm_pending_choice(
            "optional_pay", seat,
            card_name=context.card.name if context.card is not None else "",
            cost={"generic": difference},
            life=0,
            _source_permanent=context.source_permanent,
            _on_accept=(
                _OracleInstruction("place_held_card", "", {"destination": "battlefield"}),
            ),
            _on_decline=(
                _OracleInstruction("place_held_card", "", {"destination": "graveyard"}),
            ),
            _on_reflexive=(),
            _context=context,
            prompt=f"Pay {{{difference}}}?",
        )

    run_resumable(game, [_sacrifice, _search, _place], lambda step: step(None))
    return True, "resolved"


@effect_handler("take_ownership_of_exiled")
def take_ownership_of_exiled(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """The exchange half of Bronze Tablet: each exiled card ends up owned by the
    other player.

    CR 108.3 makes ownership fixed for the whole game; the ante rules (CR 407)
    are where the exception lives, and this is one of the handful of cards that
    is it. The engine models a zone per player, so "that player owns this card"
    *is* the card sitting in that player's exile — there is nothing else about
    ownership for anything to read.

    Its own instruction kind because it is the decline branch of an optional
    payment, and that machinery runs instruction lists.
    """
    swap = context.results.get("ownership_exchange")
    if not swap:
        return True, "resolved"
    context.results["ownership_exchange"] = None
    for from_seat, to_seat, card in swap:
        # Out of one exile and into another. CR 406.7 makes that a new object
        # that has just been exiled even though it never left the zone, so
        # whatever the register said about the old one stops applying — which
        # is what the departure seam does, and why the move is spelled as a
        # departure followed by an arrival rather than a list edit.
        game.take_card_from_exile(from_seat, card)
        game.players[to_seat].exile.append(card)
        game.log.append(
            f"{game.players[to_seat].name} now owns {card.name}"
        )
    return True, "resolved"


@effect_handler("return_exiled_source_to_graveyard")
def return_exiled_source_to_graveyard(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """The paid branch of Bronze Tablet: "put this card into its owner's
    graveyard". Only *this* card moves — the other exiled card stays exiled,
    which is what the printed sentence says and what makes paying a real cost
    rather than a full undo."""
    swap = context.results.get("ownership_exchange")
    if not swap:
        return True, "resolved"
    context.results["ownership_exchange"] = None
    for from_seat, _to_seat, card in swap:
        if card is not context.card:
            continue
        holder = game.players[from_seat]
        game.take_card_from_exile(from_seat, card)
        game.put_card_into_graveyard(holder, card)
        game.log.append(f"{card.name} is put into its owner's graveyard")
    return True, "resolved"


@effect_handler("exchange_ownership_unless_paid")
def exchange_ownership_unless_paid(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Bronze Tablet: "Exile this artifact and target nontoken permanent an
    opponent owns. That player may pay 10 life. If they do, put this card into
    its owner's graveyard. Otherwise, that player owns this card and you own the
    other exiled card."

    An ante card (CR 407): the exchange is the one place CR 108.3's "ownership
    never changes" is not true, and the engine's ownership *is* which player's
    zone a card sits in, so the swap is a move between the two exile piles.

    The payment is the ordinary optional-pay entry, which learned a life cost
    for this card — and it is owed by the **victim**, not by the activator,
    which is the whole tension of the card and the reason the prompt names a
    seat rather than defaulting to the controller.
    """
    from ..subject_filters import subject_matches

    source = context.source_permanent
    if source is None:
        return True, "resolved"
    caster_index = game.players.index(context.caster)
    described = dict(instruction.payload.get("filter") or {})
    owner = instruction.payload.get("owner")

    def _eligible(perm) -> bool:
        if perm is source or not subject_matches(
            game, perm, described, observer=caster_index, source=source
        ):
            return False
        seat = game.owner_index_of(perm)
        return seat is not None and (seat != caster_index) == (owner != "you")

    victim = resolve_target_permanent(game, context, predicate=_eligible)
    if victim is None:
        game.log.append(f"{context.card.name}: no valid permanent to exchange")
        return True, "resolved"
    victim_seat = game.owner_index_of(victim)
    if victim_seat is None:
        return True, "resolved"
    game.remove_all_from_battlefield([source, victim])
    game.players[caster_index].exile.append(source.card)
    game.players[victim_seat].exile.append(victim.card)
    game.log.append(
        f"{context.card.name} exiled itself and {victim.card.name}"
    )
    # (holder seat, new owner seat, card) — what the two branches below read.
    context.results["ownership_exchange"] = [
        (caster_index, victim_seat, source.card),
        (victim_seat, caster_index, victim.card),
    ]
    game.arm_pending_choice(
        "optional_pay", victim_seat,
        card_name=context.card.name,
        cost={},
        life_cost=int(instruction.payload.get("life", 0)),
        life=0,
        prompt=f"Pay {instruction.payload.get('life', 0)} life?",
        _source_permanent=source,
        _on_accept=(_OracleInstruction("return_exiled_source_to_graveyard", "", {}),),
        _on_decline=(_OracleInstruction("take_ownership_of_exiled", "", {}),),
        _on_reflexive=(),
        _context=context,
    )
    return True, "resolved"


@effect_handler("put_graveyard_cards_on_library_top")
def put_graveyard_cards_on_library_top(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Drafna's Restoration: "Put any number of target artifact cards from
    target player's graveyard on top of their library in any order."

    Two targets on one line — a player, and the cards in their graveyard — so
    the seat comes from the spell's chosen target and the slots index *that*
    player's graveyard rather than the caster's. That is the whole difference
    from the returns above, and it is why the cards are resolved through
    :func:`_resolve_graveyard_slots` with the target player passed in.

    **"In any order" is the order the targets were named in.** CR 601.2c
    chooses the targets in sequence, and there is nothing else on the wire that
    could carry an ordering — so the controller's choice of order *is* their
    choice of order, and the first card named ends up on top.
    """
    # Whose graveyard, said by the lowering rather than inferred here. "Your
    # graveyard … your library" (Reinforcements) names the ability's controller
    # and chooses no player at all, so reading `context.target` for it would
    # index the *opponent's* graveyard with slots picked out of the caster's —
    # the wrong pile, silently, with the right number of cards moved.
    if instruction.payload.get("graveyard_owner") == "you":
        victim = context.caster
    elif context.target in game.players:
        victim = context.target
    else:
        game.log.append(f"{context.card.name}: no player chosen")
        return True, "resolved"

    def _eligible(card) -> bool:
        # The picker's predicate, not a third spelling of it — the arrangement
        # `return_creature_from_graveyard_to_hand` one screen down already
        # makes, and for its reason: the payload and the spec carry the same key
        # names because one is derived from the other, so there is one answer to
        # "may this card be chosen?". This arm read `card_type in type_line`,
        # which is the same answer for the one key it knew and no answer at all
        # for "any card" (Misinformation) or a supertype (Lodestone Bauble).
        return graveyard_card_matches(instruction.payload, card)

    # "Any number" prints no maximum, so the cap is the pile itself; "up to
    # three" prints one, and the description the lowering built carries it.
    described = instruction.payload.get("targets") or {}
    limit = (
        len(victim.graveyard) if described.get("unbounded")
        else min(int(described.get("count") or 1), len(victim.graveyard))
    )
    picked = _resolve_graveyard_slots(victim, context, limit, _eligible)
    if not picked:
        game.log.append(f"{context.card.name}: no card moved out of the graveyard")
        return True, "resolved"
    # Last named first, so the first card the controller chose ends up on top.
    for card in reversed(picked):
        game.put_card_into_library(victim, card, position="top")
    game.log.append(
        f"{context.card.name} put {len(picked)} card(s) on top of {victim.name}'s library"
    )
    return True, "resolved"


def _return_graveyard_card_to_owners_hand(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Return target creature card **from a graveyard to its owner's hand**."
    (Endbringer's Revel.)

    The pile is the announced seat's (``_run_stack_item_resolution`` writes the
    stamped card's seat back onto the item before any handler runs), and the
    hand is the same player's: a card in a graveyard is in its owner's
    (CR 404.1, 400.3), so "its owner's hand" needs no second lookup. The
    activator's own hand is reached only when the card was theirs.

    A slot that was named and no longer answers the printed noun is CR 608.2b's
    illegal target and returns nothing. An announcement naming **no** slot (an
    AI seat that announced the ability bare) takes the first matching card,
    searched the way Hymn of Rebirth's any-graveyard reanimation searches: the
    named seat, then the activator, then everyone else.
    """
    caster = context.caster

    def _eligible(card) -> bool:
        return graveyard_card_matches(instruction.payload, card)

    named = context.target if context.target in game.players else None
    index = context.target_permanent_index
    found = None
    if isinstance(index, int):
        if (
            named is not None
            and 0 <= index < len(named.graveyard)
            and _eligible(named.graveyard[index])
        ):
            found = (named, index)
    else:
        found = next(
            (
                (player, slot)
                for player in (named, caster, *game.players)
                if player is not None
                for slot, card in enumerate(player.graveyard)
                if _eligible(card)
            ),
            None,
        )
    if found is None:
        game.log.append(f"{context.card.name}: no card was returned from a graveyard")
        return True, "resolved"
    owner, slot = found
    chosen = owner.graveyard.pop(slot)
    game.put_card_into_hand(owner, chosen)
    game.log.append(
        f"{context.card.name}: returned {chosen.name} from {owner.name}'s "
        f"graveyard to {owner.name}'s hand"
    )
    return True, "resolved"


@effect_handler("return_creature_from_graveyard_to_hand")
def return_creature_from_graveyard_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    if instruction.payload.get("any_graveyard"):
        return _return_graveyard_card_to_owners_hand(game, instruction, context)
    caster = context.caster
    any_card = bool(instruction.payload.get("any_card"))
    card_type = instruction.payload.get("card_type")
    card_types = tuple(instruction.payload.get("card_types") or ())

    # "Return **another** target artifact card from your graveyard to your
    # hand." (Junk Diver.) CR 113.7's source, and a *slot* rather than a kind
    # of card — so it is asked beside the predicate through the one reader the
    # picker also asks, and never folded into ``_eligible``: two copies of one
    # card in one graveyard are the same ``CardDefinition`` object, and a
    # per-card test would take both away where the sentence takes one.
    #
    # ``context.card`` is the ability's own source (CR 113.7), which for the
    # dies-trigger printing this sentence is a card sitting in the very pile
    # being searched. Without it Junk Diver returned **itself** out of an
    # otherwise empty graveyard.
    excluded = excluded_graveyard_slot(
        instruction.payload, caster.graveyard, context.card
    )

    def _eligible(card) -> bool:
        # The picker's predicate, not a third spelling of it. The payload and
        # the spec carry the same key names because one is derived from the
        # other, so there is one answer to "may this card be chosen?".
        return graveyard_card_matches(instruction.payload, card)

    def _eligible_slot(index: int) -> bool:
        """The same question asked of a *position*, which is what the printed
        "another" narrows. Every scan below goes through this rather than
        through ``_eligible`` alone."""
        return index != excluded and _eligible(caster.graveyard[index])

    # "Return up to two target creature cards from your graveyard to your hand."
    # (Sanguine Indulgence.) The several-targets description says a list was
    # collected, so every chosen slot is honoured rather than only the first.
    targets_desc = instruction.payload.get("targets") or {}
    printed_count = targets_desc.get("count") if isinstance(targets_desc, dict) else None
    # Whether the sentence's target *count* is the announced X, remembered
    # before the letter is turned into a number. Everything below the
    # conversion sees an ordinary integer, and "is this a targeted list?" is a
    # different question from "how long is it?" — conflating the two is what
    # made the ``> 1`` gate wrong (see there).
    counted_x = printed_count == "x"
    if printed_count == "x":
        # "Return **X** target creature cards from your graveyard to your hand."
        # (Shattered Crypt.) The announced X (CR 601.2b), which is not a number
        # until the spell is on the stack — so the several-slot branch reads it
        # here rather than being told a literal by the lowering.
        #
        # Gated on the string rather than left to ``isinstance(int)``, which is
        # what this branch used to ask: the Crypt's count arrived as ``'x'``,
        # failed that test, fell through to the single-card path and returned
        # **one** card of however many X paid for — while the card lost X life
        # and reported itself supported.
        printed_count = int(context.x_value or 0)
    # An X-counted list goes through the slot resolver **whatever X is**, and
    # the ``> 1`` beside it is a printed number's threshold rather than this
    # one's. Two cards were mis-resolved by sharing it:
    #
    # * Shattered Crypt cast for X=1 with a list-shaped announcement fell past
    #   the ``isinstance(idx, int)`` branch below (a one-element list is not an
    #   int) and out into the "return whatever creature is nearest" fallback —
    #   so the browser, which sends a list for every several-target picker,
    #   returned the first creature card in the pile instead of the one the
    #   caster targeted.
    # * "Return **up to X** target cards…" (Reap) counted at 0 reached the same
    #   fallback and returned a card for a spell that names none — an effect
    #   happening more often than the card allows, which is the direction that
    #   never announces itself.
    #
    # Zero picks is a legal outcome here, not a reason to guess: the sentence
    # targets (CR 601.2c), so an announcement naming nothing returns nothing.
    if counted_x or (isinstance(printed_count, int) and printed_count > 1):
        picked = _resolve_graveyard_slots(
            caster, context, printed_count, _eligible
        )
        for returned_card in picked:
            game.put_card_into_hand(caster, returned_card)
            game.log.append(
                f"Returned {returned_card.name} from graveyard to hand"
            )
        if not picked:
            game.log.append("No card was returned from the graveyard")
        return True, "resolved"

    # Honor the caster's chosen graveyard card (Rule 601.2c). Regrowth
    # (any_card) accepts any type; Raise Dead only a creature card.
    idx = context.target_permanent_index
    if isinstance(idx, int) and 0 <= idx < len(caster.graveyard) and _eligible_slot(
        idx
    ):
        chosen = caster.graveyard.pop(idx)
        game.put_card_into_hand(caster, chosen)
        game.log.append(f"Returned {chosen.name} from graveyard to hand")
        return True, "resolved"
    if card_types:
        chosen_index = next(
            (i for i in range(len(caster.graveyard)) if _eligible_slot(i)), None
        )
        if chosen_index is None:
            game.log.append(f"No {' or '.join(card_types)} card in graveyard to return")
            return True, "resolved"
        chosen = caster.graveyard.pop(chosen_index)
        game.put_card_into_hand(caster, chosen)
        game.log.append(f"Returned {chosen.name} from graveyard to hand")
        return True, "resolved"
    if card_type is not None and card_type != "creature":
        chosen_index = next(
            (i for i in range(len(caster.graveyard)) if _eligible_slot(i)), None
        )
        if chosen_index is None:
            game.log.append(f"No {card_type} card in graveyard to return")
            return True, "resolved"
        chosen = caster.graveyard.pop(chosen_index)
        game.put_card_into_hand(caster, chosen)
        game.log.append(f"Returned {chosen.name} from graveyard to hand")
        return True, "resolved"

    # The unnarrowed creature return, and the last place the printed "another"
    # has to be honoured: with an exclusion in force the generic scan would take
    # the source itself, so the slot walk above is used instead. Without one the
    # call is left exactly as it was, so every card written before this keeps
    # its behaviour byte for byte.
    if excluded is not None:
        chosen_index = next(
            (i for i in range(len(caster.graveyard)) if _eligible_slot(i)), None
        )
        if chosen_index is None:
            game.log.append("No creature to return")
            return True, "resolved"
        chosen = caster.graveyard.pop(chosen_index)
        game.put_card_into_hand(caster, chosen)
        game.log.append(f"Returned {chosen.name} from graveyard to hand")
        return True, "resolved"
    returned = game._return_creature_from_graveyard(caster)
    if not returned and any_card and caster.graveyard:
        chosen = caster.graveyard.pop(0)
        game.put_card_into_hand(caster, chosen)
        game.log.append(f"Returned {chosen.name} from graveyard to hand")
        return True, "resolved"
    game.log.append("Returned creature from graveyard" if returned else "No creature to return")
    return True, "resolved"


@effect_handler("return_chosen_cards_from_graveyard_to_hand")
def return_chosen_cards_from_graveyard_to_hand(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Return a card from your graveyard to your hand **for each card
    discarded this way**." (Recall.)

    Chosen while the spell resolves, not targeted at cast time (CR 601.2c): how
    many cards there are to return is the answer to a prompt this same
    resolution armed, so the picks could not have been named when the spell went
    on the stack. Nothing is lost by that — the cards are in the chooser's own
    graveyard, a public zone with no shroud, no protection and nothing for
    targeting to protect.

    The picker is the search prompt, pointed at the graveyard. Not a second
    prompt kind, because the question is the one that prompt already asks —
    "choose up to N cards from this zone, and here is what may be chosen" — and
    it already suspends the resolution, already has a non-interactive default and
    is already rendered. What the printed sentence adds is *where the number
    comes from*.

    Fewer cards than the number asked for is a legal outcome (CR 608.2b): the
    count is capped at what the graveyard holds, and an empty graveyard returns
    nothing rather than arming a prompt with nothing in it.
    """
    caster = context.caster
    source_key = instruction.payload.get("amount_from")
    if source_key is not None:
        amount = max(0, int(context.results.get(source_key, 0) or 0))
    else:
        amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)

    def _eligible(card) -> bool:
        return graveyard_card_matches(instruction.payload, card)

    available = sum(1 for card in caster.graveyard if _eligible(card))
    amount = min(amount, available)
    if amount <= 0:
        game.log.append(f"{caster.name} returns no cards from their graveyard")
        return True, "resolved"
    game.arm_pending_choice(
        "search_library", game.players.index(caster),
        count=amount,
        card_type=instruction.payload.get("card_type") or "any",
        zones=("graveyard",),
        restrictions={},
        destination="hand",
        # One slot per card the sentence asks for, all of them the hand. Two or
        # more slots is what puts the prompt on its counted path, where the
        # whole answer arrives at once.
        destinations=["hand"] * amount,
        tapped=[False] * amount,
        card_name=context.card.name if context.card is not None else "",
        enters_tapped=False,
        untap_found_if=None,
        up_to=False,
        reveal=False,
    )
    game.log.append(
        f"{caster.name} chooses {amount} card(s) from their graveyard to return"
    )
    return True, "resolved"


#: The scratchpad key a reanimation records its arrival under. Spelled again in
#: ``grammar/lowering/_events.py`` rather than imported across the seam, and
#: held to it by ``lowering/_records._PRODUCES`` — the same arrangement the
#: tap's ``tapped_permanents`` has.
REANIMATED_PERMANENTS = "reanimated_permanents"


def _holds_a_reanimable_card(player, index, card_filter, card_type="creature") -> bool:
    """Whether *player*'s graveyard holds a card of *card_type* this effect may
    take.

    With *index* given, the question is only about that slot — the announced
    target — because a named target that is legal settles where the card comes
    from and no search happens at all.
    """
    graveyard = getattr(player, "graveyard", ())

    def eligible(card) -> bool:
        return card_has_type(card, card_type) and (
            card_filter is None or card_filter(card)
        )

    if isinstance(index, int):
        return 0 <= index < len(graveyard) and eligible(graveyard[index])
    return any(eligible(card) for card in graveyard)


def _reanimable_slot(player, card_filter, card_type="creature"):
    """The first slot of *player*'s graveyard this effect may take, or nothing.

    A generator so the caller can write one ``next`` over seats and slots
    together: an empty pile contributes no slot rather than a None to filter
    out afterwards.
    """
    for index, card in enumerate(getattr(player, "graveyard", ())):
        if card_has_type(card, card_type) and (
            card_filter is None or card_filter(card)
        ):
            yield index
            return


@effect_handler("reanimate_creature")
def reanimate_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    # Resurrection returns "target creature card from your graveyard", so the chosen
    # index is into the caster's own graveyard regardless of which seat the UI tags.
    # "…from a graveyard" (Liliana, Waker of the Dead's emblem) widens the source
    # to the chosen player's graveyard; "under your control" is already how
    # _reanimate_creature_to_battlefield puts it into play for the caster.
    idx = context.target_permanent_index
    idx = idx if isinstance(idx, int) else None
    # "Return target **artifact** card from your graveyard to the battlefield."
    # (Argivian Restoration.) Which kind of card comes back is the sentence's
    # own word and rides the payload; "creature" is what every printing before
    # it said, so a payload written without the key means exactly what it did.
    # Every reader of it below goes through ``card_has_type`` — CR 205.2a gives
    # a card every type its line names, and ``primary_type`` picks one of them
    # by the order of a list, which is what made an Artifact Creature card
    # invisible to a phrase naming an artifact.
    card_type = str(instruction.payload.get("card_type", "creature"))
    # "Return **the top** creature card of your graveyard to the
    # battlefield." (Shallow Grave.) CR 404.1 puts an arriving card on *top* of
    # its owner's graveyard and CR 404.2 keeps the pile in that order, and this
    # engine appends — so the top card is the last entry, the most recently
    # added, and "the top creature card" is the last one of them. Nobody
    # chooses, so any index the wire happened to carry is not this effect's: it
    # is overwritten rather than preferred.
    #
    # (CR 404.3 is the *simultaneous-arrival* tie-break and is not this rule;
    # ``engine/graveyard_order.py`` records the correction and the W1G1 report
    # lists the sites that copied it.)
    if instruction.payload.get("from_top"):
        idx = next(
            (
                slot
                for slot in range(len(caster.graveyard) - 1, -1, -1)
                if card_has_type(caster.graveyard[slot], card_type)
            ),
            None,
        )
        if idx is None:
            game.log.append(
                f"{context.card.name}: no {card_type} card in the graveyard"
            )
            context.results[REANIMATED_PERMANENTS] = ()
            return True, "resolved"
    any_graveyard = bool(instruction.payload.get("any_graveyard"))
    source_player = caster
    if any_graveyard and context.target is not None:
        source_player = context.target
    # "target **white or black** creature card" (Dreams of the Dead). Applied
    # here as well as at announcement, through the one predicate the picker and
    # the activation gate ask (`graveyard_card_matches`) — a picker and a
    # resolution that disagree are a target the player may announce and the
    # effect then declines to affect. A card with no printed colour hands over
    # no filter at all, so every reanimation written before this is unchanged.
    colors = tuple(instruction.payload.get("colors") or ())
    # "target **Aura** card from a graveyard" (Iridescent Drake). CR 205.3b: a
    # subtype, carried on the key ``graveyard_card_matches`` reads it under, so
    # the same predicate answers the colour narrowing beside it. The two are
    # gathered into one spec rather than into two lambdas because a card must
    # satisfy every word the phrase printed.
    subtypes = tuple(instruction.payload.get("graveyard_subtypes") or ())
    spec: dict[str, object] = {}
    if colors:
        spec["graveyard_colors"] = list(colors)
    if subtypes:
        spec["graveyard_subtypes"] = list(subtypes)
    if spec:
        # The type word travels with the narrowings rather than being left to
        # the predicate's default. ``graveyard_card_matches`` ends "a spec that
        # names no type is about a creature card" — right for the reanimation
        # Auras it was written for, and wrong for "target **Aura** card", whose
        # subtype narrows a phrase that names no card type at all: the subtype
        # test passed and the creature default then refused every Aura in the
        # pile. Written as the word this handler is already searching by, so
        # the two readers ask one question; a payload with no ``card_type`` key
        # spells "creature" here exactly as the default did.
        spec["card_type"] = card_type
    # "…onto the battlefield under your control **attached to this creature**."
    # (Iridescent Drake.) CR 303.4g: an Aura entering with no legal object to
    # enchant *remains in its current zone* — so the host is not a step behind
    # the move, it is part of which cards this sentence can move at all, and it
    # therefore rides the same filter the picker and the resolution share.
    #
    # A source that has left the battlefield names no host, so 303.4g leaves
    # nothing that could legally arrive: the effect does nothing rather than
    # putting an Aura into play attached to nothing for the next state-based
    # sweep to bin (CR 704.5m).
    attach_host = None
    if instruction.payload.get("attach_to") == "source":
        attach_host = context.source_permanent
        if attach_host is None or not game.is_on_battlefield(attach_host):
            game.log.append(
                f"{context.card.name}: it is no longer on the battlefield"
            )
            context.results[REANIMATED_PERMANENTS] = ()
            return True, "resolved"
    card_filter = None
    if spec or attach_host is not None:
        from ..auras import enchant_card_refusal

        caster_seat = (
            game.players.index(caster) if caster in game.players else None
        )

        def card_filter(card, _spec=spec, _host=attach_host, _seat=caster_seat):
            if _spec and not graveyard_card_matches(_spec, card):
                return False
            if _host is None:
                return True
            # The one enchant gate the cast, the sweep and both pickers ask —
            # so "can this Aura enchant that creature?" has one answer here as
            # everywhere else.
            return (
                _seat is not None
                and enchant_card_refusal(game, card, _seat, _host) is None
            )
    if any_graveyard and not _holds_a_reanimable_card(
        source_player, idx, card_filter, card_type
    ):
        # **No card was named, and the seat that was named holds none.** The
        # index fallback below searches the *caster's* graveyard, which is right
        # for "from your graveyard" and blind for "from a graveyard": an AI seat
        # announces the effect without picking a slot, so Hymn of Rebirth
        # resolved and put nothing onto the battlefield whenever the only
        # creature card was in someone else's pile. The order is the Aura
        # printing's, which has searched this way all along
        # (``mixins/oracle_instructions.py``): the named seat, then the caster,
        # then everyone else.
        found = next(
            (
                (player, slot)
                for player in (source_player, caster, *game.players)
                for slot in _reanimable_slot(player, card_filter, card_type)
            ),
            None,
        )
        if found is not None:
            # The slot travels with the seat. The fallback one level down
            # searches the *caster's* pile by construction — right for every
            # other reanimation, and the reason the seat alone would not have
            # been enough here.
            source_player, idx = found
    reanimated = game._reanimate_creature_to_battlefield(
        caster, source_player, idx, card_filter=card_filter, card_type=card_type
    )
    # "enchant creature **put onto the battlefield with Necromancy**" — the
    # relation that clause is about, stamped by the step that performs it
    # because nothing else can say so: the ability's target was a *card* in a
    # graveyard, and CR 400.7 makes what arrived a new object with no history on
    # the board. `auras.enchant_card_refusal` reads it back. Unconditional: a
    # permanent nobody asks the question about carries a spare id, where a
    # permanent the question *is* asked about and that was not stamped would be
    # a legal host the card never allowed.
    if reanimated is not None and context.source_permanent is not None:
        reanimated.metadata[PUT_ONTO_BATTLEFIELD_BY] = (
            context.source_permanent.permanent_id
        )
    # "It gains haste." — folded into the reanimation because the permanent
    # does not exist until this step runs, and read off the arrival itself
    # rather than off "the newest permanent the caster controls", which an
    # enters-trigger creating a token makes wrong.
    # "…**attached to this creature**." (Iridescent Drake.) CR 303.4f attaches
    # the Aura as part of the same move, inside this one resolution — nothing
    # checks state-based actions between the arrival and this line, so the Aura
    # is never an unattached one for CR 704.5m to find. Through ``attach_aura``,
    # which stamps the CR 613.7e timestamp and records both directions.
    if reanimated is not None and attach_host is not None:
        from ..auras import attach_aura

        attach_aura(reanimated, attach_host)
    gains = tuple(instruction.payload.get("gains") or ())
    if reanimated is not None and gains:
        for keyword in gains:
            grant_keyword(reanimated, keyword)
    # "If the creature would leave the battlefield, exile it instead of putting
    # it anywhere else." (Dreams of the Dead.) Armed on the permanent this step
    # created, which is the only object the sentence can be about — the
    # ability's target is a card in a graveyard. The marker is what
    # `engine/replacements.py`'s `would_leave_battlefield` interceptor reads,
    # and it lives on the permanent rather than on the card because a
    # `CardDefinition` is shared between every copy of a card in a deck.
    if reanimated is not None and instruction.payload.get("exile_on_leave"):
        reanimated.metadata[EXILE_ON_LEAVING_BATTLEFIELD] = True
    # What this step put onto the battlefield, for the sentences that name it
    # afterwards ("that creature gains …"). By id, like every other producer:
    # the permanent may leave between two steps of one resolution, and a
    # returning one is a new object (CR 400.7).
    context.results[REANIMATED_PERMANENTS] = (
        (reanimated.permanent_id,) if reanimated is not None else ()
    )
    # "You lose life equal to **that card's mana value**." (Reanimate.) The
    # number frozen where the object still had it (CR 608.2h): the sentence
    # behind this one cannot go and look, because the ability's target was a
    # card in a graveyard and CR 400.7 makes what arrived a new object.
    #
    # Written **unconditionally**, zero when nothing came back. The lowering
    # admitted the phrase on the strength of this producer, so a resolution that
    # sometimes writes nothing is a reader that sometimes finds nothing, and
    # "nothing arrived" has a right answer: you lose no life. CR 202.3 off the
    # effective card, exactly as the destroy that shares this record does — a
    # permanent that entered as a copy has the copied cost.
    context.results["its_mana_value"] = (
        int(getattr(reanimated.effective_card, "cmc", 0) or 0)
        if reanimated is not None else 0
    )
    game.log.append(
        f"Reanimated {card_type} to battlefield" if reanimated is not None
        else f"No {card_type} to reanimate"
    )
    return True, "resolved"


@effect_handler("reanimate_aura_onto_source")
def reanimate_aura_onto_source(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return target Aura card from your graveyard to the battlefield
    **attached to Hakim**." (Hakim, Loreweaver.)

    Its own handler rather than a rider on ``reanimate_creature``, because
    CR 303.4f makes the attachment part of the entry rather than a step after
    it: an Aura that entered attached to nothing is what CR 704.5m puts
    straight back in the graveyard, so a version that put the card down and
    then attached would be a card that works only when nothing looks in
    between.

    **The host is the ability's own source and nothing else.** It is read off
    ``context.source_permanent`` rather than off the board, because a permanent
    that has left between activation and resolution has no host to offer
    (CR 608.2b) — and picking some other creature would be an Aura landing
    where the card never said.

    Legality is ``auras.aura_attach_refusal``, the one predicate the cast gate,
    the CR 704.5m sweep and the two other resolutions ask. CR 303.4j: an
    attachment that would be illegal simply does not happen, and here that
    means the card stays in the graveyard — putting it onto the battlefield
    unattached would be strictly worse than not resolving, since the sweep
    would bin it and the card would be gone.
    """
    from ..auras import attach_aura, aura_attach_refusal

    caster = context.caster
    host = context.source_permanent
    if host is None or not game.is_on_battlefield(host):
        game.log.append(f"{context.card.name}: nothing to attach the Aura to")
        context.results[REANIMATED_PERMANENTS] = ()
        return True, "resolved"
    spec = dict(instruction.payload)
    idx = context.target_permanent_index
    if not (
        isinstance(idx, int)
        and 0 <= idx < len(caster.graveyard)
        and graveyard_card_matches(spec, caster.graveyard[idx])
    ):
        # The same order every other reanimation falls back through: an AI seat
        # announces the ability without naming a slot, so the first legal card
        # in the pile is the one this takes. A re-check rather than a trust,
        # for the reason `reanimate_creature` re-checks: a picker and a
        # resolution that disagree are a target the player may announce and the
        # effect then declines.
        idx = next(
            (
                slot
                for slot, card in enumerate(caster.graveyard)
                if graveyard_card_matches(spec, card)
            ),
            None,
        )
    if idx is None:
        game.log.append(f"{context.card.name}: no Aura card in the graveyard")
        context.results[REANIMATED_PERMANENTS] = ()
        return True, "resolved"
    aura_card = caster.graveyard[idx]
    arrival = Permanent(card=aura_card)
    refusal = aura_attach_refusal(game, arrival, host)
    if refusal is not None:
        game.log.append(
            f"{context.card.name}: {aura_card.name} cannot enchant "
            f"{host.card.name} ({refusal})"
        )
        context.results[REANIMATED_PERMANENTS] = ()
        return True, "resolved"
    caster.graveyard.pop(idx)
    game._put_permanent_onto_battlefield(
        game.seat_index(caster), arrival, None, from_zone="graveyard"
    )
    attach_aura(arrival, host)
    # CR 704.5m is asked at once, the way the attach handler asks it: layer
    # contributions are computed on read, so nothing has to be refreshed — but
    # an Aura that arrived on a host it may not stay on has to go now rather
    # than at the next sweep.
    game.check_state_based_actions()
    context.results[REANIMATED_PERMANENTS] = (arrival.permanent_id,)
    game.log.append(
        f"{aura_card.name} returned to the battlefield attached to "
        f"{host.card.name}"
    )
    return True, "resolved"


@effect_handler("return_bound_card_to_owners_hand")
def return_bound_card_to_owners_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return that card to its owner's hand." (Puppet Master.)

    The bound object — the card of the creature whose death fired the trigger,
    which CR 404.1 put in its *owner's* graveyard. The fire site froze the card
    itself (CR 603.10); by resolution nothing else could name it, because the
    permanent is gone and a graveyard holds several copies of a popular card
    under one name.

    Located by identity and removed with ``pop`` at the found index, for the
    reason ``return_self_from_graveyard`` records: a name match finds the wrong
    entry and a rebuild-from-survivors removes every copy.

    Records ``returned_bound_card`` either way — True when the card actually
    reached a hand, False when it had already left the graveyard (exiled in
    response) or was diverted (CR 903.9b). "If that card is returned to its
    owner's hand this way" is exactly that question.
    """
    card = (context.trigger_context or {}).get("dead_card")
    context.results["returned_bound_card"] = False
    if card is None:
        return True, "resolved"
    # "…to **your** hand" (Enduring Renewal) rather than "…to its owner's hand"
    # (Puppet Master). Two seats, and which one the card names is payload: on
    # Enduring Renewal they coincide, because the trigger only fires on a card
    # put into the controller's own graveyard — but reading them as one would
    # put an opponent's dead creature in the wrong hand the moment another card
    # printed the other word.
    recipient = (
        context.caster if instruction.payload.get("to_seat") == "controller" else None
    )
    for player in game.players:
        for index, held in enumerate(player.graveyard):
            if held is card:
                player.graveyard.pop(index)
                lands_with = recipient if recipient is not None else player
                if game.put_card_into_hand(lands_with, card):
                    context.results["returned_bound_card"] = True
                    game.log.append(
                        f"{card.name} returned to {lands_with.name}'s hand"
                    )
                return True, "resolved"
    # CR 603.6: the ability looks for the object in the zone it moves it out of.
    game.log.append(f"{card.name} was no longer in a graveyard")
    return True, "resolved"


@effect_handler("reanimate_bound_card")
def reanimate_bound_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put that card onto the battlefield under your control." (Seraph,
    Krovikan Vampire.)

    ``return_bound_card_to_owners_hand`` with a different destination, and the
    same three reasons for every line of it: the bound object is the card of the
    creature whose death fired the trigger, the fire site froze the card itself
    (CR 603.10) because by resolution nothing else could name it, and it is
    located by identity and removed with ``pop`` at the found index — a name
    match finds the wrong entry in a graveyard holding two copies.

    Under **your** control, which CR 400.3 lets an effect say; ownership does
    not move, so the card goes back to its owner's graveyard when it next dies.
    ``control="owner"`` is the other seat the phrase can name — "return that
    card to the battlefield **under its owner's control**" (Abduction), where
    the Aura took the creature while it lived and gives it back when it dies.
    Absent, the payload means CR 110.2a's default, which is this seat.

    "Sacrifice the creature when you lose control of this creature" is the same
    sentence's second half, and it is recorded here rather than lowered as a
    step of its own: the rider names a permanent that does not exist until this
    instruction makes one. ``engine/linked_sacrifice.py`` holds the record and
    the state-based sweep re-checks it.
    """
    from ..damage_deaths import creatures_it_damaged_that_died
    from ..linked_sacrifice import link_sacrifice_to_source
    from ..models import Permanent

    if instruction.payload.get("from_damage_deaths"):
        # Krovikan Vampire's "that card" is the one its own intervening-if
        # found. **Every** one of them, when the ledger holds several: the
        # trigger fires once per end step and its condition asks whether *a*
        # creature died, so with two deaths the sentence names two cards and
        # nothing in it says which one to prefer. Reanimating the first would be
        # a choice the card never offers anybody.
        cards = creatures_it_damaged_that_died(context.source_permanent)
    else:
        card = (context.trigger_context or {}).get("dead_card")
        cards = [card] if card is not None else []
    context.results["reanimated_bound_card"] = False
    if not cards:
        game.log.append(
            f"{context.card.name}: no recorded card to put onto the battlefield"
        )
        return True, "resolved"
    controller_seat = game.players.index(context.caster)
    to_owner = instruction.payload.get("control") == "owner"
    for card in cards:
        for player in game.players:
            found = next(
                (i for i, held in enumerate(player.graveyard) if held is card), None
            )
            if found is None:
                continue
            owner_seat = game.players.index(player)
            # CR 404.1 put the card in its *owner's* graveyard, so the seat
            # holding it is the owner — which is what "under its owner's
            # control" names, found here rather than passed in because it is
            # the graveyard scan that discovers it.
            seat = owner_seat if to_owner else controller_seat
            player.graveyard.pop(found)
            permanent = Permanent(card=card)
            # CR 400.3: "under your control" moves control, never ownership, so
            # the card goes to its **owner's** graveyard when it next leaves.
            # Recorded on the permanent for the reason Animate Dead's
            # reanimation records it: the base controller is the owner
            # everywhere else in this pool, and here the two differ by
            # construction.
            if owner_seat != seat:
                permanent.metadata["owner_player_index"] = owner_seat
            game._put_permanent_onto_battlefield(seat, permanent, None)
            context.results["reanimated_bound_card"] = True
            if instruction.payload.get("sacrifice_when_control_lost"):
                source = context.source_permanent
                if source is not None:
                    link_sacrifice_to_source(permanent, source, seat)
            game.log.append(
                f"{card.name} entered the battlefield under "
                f"{game.players[seat].name}'s control ({context.card.name})"
            )
            break
        else:
            # CR 603.6: the ability looks for the object in the zone it moves it
            # out of. Exiled in response, or already reanimated by an earlier
            # firing of this same ability.
            game.log.append(f"{card.name} was no longer in a graveyard")
    return True, "resolved"


@effect_handler("return_source_card_to_owners_hand")
def return_source_card_to_owners_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return this card to its owner's hand." (Puppet Master's paid rider.)

    The ability's own source, printed with **no source zone** — so unlike
    ``return_self_from_graveyard``, whose sentence names one, this reaches
    whichever zone the object is actually in (CR 608.2). Usually the graveyard:
    an Aura whose enchanted creature has left is put there by the CR 704.5m
    sweep, which runs the next time a player would receive priority and so
    before this trigger resolves. But the sweep is not guaranteed to have run —
    a caller that resolves the stack without an intervening priority pass finds
    the Aura still on the battlefield — and a handler that looked in one zone
    would silently do nothing in the other.

    By identity, like every other graveyard reach in this module, and across
    every graveyard rather than the resolving seat's: CR 404.1 puts the card in
    its *owner's*, and an Aura its controller did not own goes to the other
    player's.

    ``from: "battlefield"`` takes that reach away, and one shape asks for it:
    the sentence as the effect of a **delayed** ability (Contempt's "…return it
    and this Aura to their owners' hands at end of combat"). A whole combat step
    later, CR 400.7 makes the card in the graveyard a different object from the
    permanent the ability was created about — so an Aura destroyed in response
    to the trigger stays dead, where the reach above would hand it back. The
    lowering decides which reading applies, from the event the sentence is
    under (``_common._source_return_reach``).
    """
    card = context.card
    source = context.source_permanent
    if source is not None and game.is_on_battlefield(source):
        # CR 108.3's seat, read the way ``control.base_controller`` says to:
        # the recorded base seat, and *where the permanent sits* when there is
        # none. The literal ``.get(..., 0)`` this replaced was a third answer —
        # seat 0 — so an Aura on a board that recorded no base controller went
        # to the wrong player's hand, which no assertion about seat 0's hand can
        # tell from the right one.
        from ..control import base_controller

        seat = base_controller(source)
        if seat is None:
            seat = game.controller_index_of(source)
        owner = game.players[seat if seat is not None else 0]
        game.remove_from_battlefield(source)
        if game.put_card_into_hand(owner, card, from_battlefield=source):
            game.log.append(f"{card.name} returned to {owner.name}'s hand")
        return True, "resolved"
    if instruction.payload.get("from") == "battlefield":
        game.log.append(f"{card.name} was no longer on the battlefield")
        return True, "resolved"
    for player in game.players:
        for index, held in enumerate(player.graveyard):
            if held is card:
                player.graveyard.pop(index)
                if game.put_card_into_hand(player, card):
                    game.log.append(f"{card.name} returned to {player.name}'s hand")
                return True, "resolved"
    game.log.append(f"{card.name} was no longer in a graveyard")
    return True, "resolved"


@effect_handler("return_source_card_to_battlefield")
def return_source_card_to_battlefield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return this card to the battlefield under your control [attached to
    that creature] [as a non-Aura enchantment]." (Takklemaggot.)

    The ability's own source, printed with no source zone — the same reach
    ``return_source_card_to_owners_hand`` makes, and for its reason: by the time
    an Aura's death trigger resolves the CR 704.5m sweep has usually already put
    the card in a graveyard, but a caller that resolves the stack without an
    intervening priority pass finds it still on the battlefield, and a handler
    that looked in one zone would silently do nothing in the other.

    Every rider is payload, and each is recorded on the permanent as a *layer*
    contribution rather than applied: the lost subtype is layer 4
    (``layer_bridge.LOST_TYPES``), the lost and gained ability lines are layer 6
    (``keywords``), and both are read back by ``Permanent.effective_card`` and
    ``computed_types``. So the CR 704.5m sweep, the UI and the compiler all get
    one answer to "what is this permanent now?" — which is the whole reason the
    non-Aura half is not a flag the sweep checks for itself.
    """
    from ..auras import attach_aura, aura_attach_refusal
    from ..keywords import grant_ability_line, remove_ability_line
    from ..layer_bridge import LOST_TYPES

    card = context.card
    source = context.source_permanent
    seat = game.seat_index(context.caster)
    # "…under **its owner's** control." (Ivory Gargoyle.) CR 400.3's seat, which
    # is not the ability's controller for a creature that changed hands before
    # it died. Read off the *permanent* while there still is one and off the
    # graveyard that held the card once there is not — CR 404.3 puts a card in
    # its owner's graveyard, so the pile that had it names the owner. An absent
    # payload key is every card written before the phrase existed and keeps
    # meaning "you".
    owners_control = instruction.payload.get("control") == "owner"
    if owners_control and source is not None:
        from ..control import base_controller

        # CR 108.3's answer, which this engine reads off the seat the permanent
        # *entered* under — never off where it currently sits, which is the
        # thief's side and the whole reason the card names the owner.
        owner = base_controller(source)
        if isinstance(owner, int):
            seat = owner
    if source is not None and game.is_on_battlefield(source):
        game.remove_from_battlefield(source)
    else:
        for player in game.players:
            for index, held in enumerate(player.graveyard):
                if held is card:
                    player.graveyard.pop(index)
                    if owners_control:
                        seat = game.seat_index(player)
                    break
            else:
                continue
            break
        else:
            # CR 603.6: the ability looks for the object in the zone it moves it
            # out of. Gone means the ability does nothing, rather than making a
            # second copy of the card.
            game.log.append(f"{card.name} was no longer in a graveyard")
            return True, "resolved"

    payload = instruction.payload
    permanent = Permanent(card=card)
    for subtype in payload.get("losing_subtypes") or ():
        permanent.metadata.setdefault(LOST_TYPES, []).append(
            {"subtypes": (str(subtype).lower(),), "source": card.name}
        )
    for line in payload.get("losing_abilities") or ():
        remove_ability_line(permanent, line)
    for line in payload.get("gaining_abilities") or ():
        grant_ability_line(permanent, line[:1].upper() + line[1:])
    # Whose upkeep the granted trigger watches and who it hits: the seat this
    # resolution asked to choose. Recorded on the permanent because the ability
    # it was granted is compiled from the *permanent's* text, with no memory of
    # the resolution that granted it — the same channel Storm World's chosen
    # player already uses.
    chosen_seat = context.results.get("chosen_player")
    if isinstance(chosen_seat, int):
        permanent.metadata["chosen_player_index"] = chosen_seat

    game._put_permanent_onto_battlefield(seat, permanent, None)
    # "…return it to the battlefield under your control **and put a death
    # counter on it**." (Bogardan Phoenix.) The permanent this step created,
    # recorded by id for the sentence behind it — CR 400.7 makes it a *new
    # object*, so "it" cannot mean the one that died, and every other reader in
    # the resolution is still holding the dead one. The reanimation's own
    # channel, because the question is the reanimation's question asked of the
    # ability's own source.
    context.results.setdefault(REANIMATED_PERMANENTS, []).append(
        permanent.permanent_id
    )
    game.log.append(
        f"{card.name} returned to the battlefield under {game.players[seat].name}'s control"
    )

    host_key = payload.get("attached_to")
    if host_key:
        host = game.permanent_by_id(context.results.get(host_key))
        # CR 303.4j asked one more time at the move itself, over the same
        # predicate the picker used: a host chosen legally may have stopped
        # being one while the rest of this resolution ran.
        refusal = aura_attach_refusal(game, permanent, host)
        if refusal is None:
            attach_aura(permanent, host)
            game.log.append(f"{card.name} attached to {host.card.name}")
        else:
            game.log.append(f"{card.name} could not attach: {refusal}")
    return True, "resolved"


@effect_handler("return_self_from_graveyard")
def return_self_from_graveyard(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return this card from your graveyard to the battlefield [tapped]."
    (Silversmote Ghoul; CR 113.6m.)

    The object is the ability's own source, so nothing is chosen and there is no
    target index to read. CR 108.4a decides whose graveyard is searched: a card
    in a graveyard has no controller, so the ability's "your" is its owner's seat
    — the seat the fire site enqueued it under.

    Located by **identity**, not by name and not by index. A graveyard is a list
    of ``CardDefinition`` and two copies of one card are the same immutable
    object, so a name match finds the wrong entry and a list-comprehension
    rebuild removes *both* — which is exactly what the Nether Shadow scan in
    ``phases/upkeep_step.py`` does today. ``pop`` at an identity-found index
    removes one.
    """
    caster = context.caster
    card = context.card
    for index, held in enumerate(caster.graveyard):
        if held is card:
            caster.graveyard.pop(index)
            break
    else:
        # CR 603.6: the ability looks for the object in the zone it moves it out
        # of. Gone (exiled in response, shuffled away) means the ability does
        # nothing, rather than conjuring a second copy of the card.
        game.log.append(f"{card.name} was no longer in the graveyard")
        return True, "resolved"
    # "…to your **hand**." (Whiteout.) The destination is payload rather than a
    # second handler, because everything above it — the object is the ability's
    # own source, found by identity in the graveyard the ability functions from
    # — is the same work either way. Absent means the battlefield, which is what
    # every payload written before the hand spelling existed says.
    if instruction.payload.get("to") == "hand":
        # Through the write seam, so CR 903.9b rides it like every other
        # put-into-a-hand.
        if game.put_card_into_hand(caster, card):
            game.log.append(f"{card.name} returned from the graveyard to hand")
        return True, "resolved"
    tapped = bool(instruction.payload.get("tapped"))
    arrived = Permanent(card=card, tapped=tapped)
    game._put_permanent_onto_battlefield(
        game.players.index(caster), arrived, None
    )
    game.log.append(
        f"{card.name} returned from the graveyard to the battlefield"
        + (" tapped" if tapped else "")
    )
    # "…**with a +1/+1 counter on it**." (Sand Golem.) CR 121.2 puts the
    # counters on as the permanent arrives, so they go on *this* object rather
    # than on whatever a later step might find — the permanent is new
    # (CR 400.7) and no target names it.
    #
    # Through the placement seams rather than by poking metadata, so the P/T
    # pair reaches layer 7d and the CR 704.5q sweep can find it: a counter
    # placed by hand is a counter nothing can take off.
    for kind, count in (instruction.payload.get("counters") or {}).items():
        if str(kind) == "+1/+1":
            game.place_plus1_counters(arrived, int(count))
        else:
            game.place_pt_counters(arrived, str(kind), int(count))
        game.log.append(f"{card.name} enters with {count} {kind} counter(s)")
    return True, "resolved"


def _mana_value_of(card) -> int:
    """A card's mana value (CR 202.3), for the step that reads what a bounce
    returned.

    Off the printed cost, which is the only reading available: the object being
    asked about has left the battlefield, so there is no permanent to put through
    the layer system and no continuous effect that could have changed the number
    anyway (CR 202.3b — mana value is computed from the mana cost as printed).
    """
    return int(card.cmc or 0)


@effect_handler("bounce_target_creature")
def bounce_target_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # "Return up to two target creatures to their owners' hands." (Read the
    # Tides' second mode.) The several-targets description says a list was
    # collected: each slot resolves strictly (a departed target is dropped,
    # CR 608.2b) and each creature goes to its own owner's hand (CR 400.3).
    targets_desc = instruction.payload.get("targets") or {}
    # ``not in (None, 1)`` and never ``isinstance(..., int) and > 1``, which is
    # what stood here: a count of ``"x"`` is exactly what a computed number
    # looks like on this key ("Return up to **X** target permanents to their
    # owners' hands", Recantation), and an int test reads it as "not several"
    # and falls through to the single-target path below — one permanent
    # returned of the X the picker collected, with nothing to see. The destroy
    # handler one family over already asks it this way.
    if isinstance(targets_desc, dict) and targets_desc.get("count") not in (None, 1):
        # The printed noun phrase, honoured rather than assumed. This branch
        # used to take every slot the picker filled: right for "up to two target
        # creatures", whose picker offers only creatures, and wrong the moment a
        # narrowing the picker cannot enforce arrives — the same asymmetry the
        # singular branch below spells out at length. Asked through
        # ``subject_matches`` for that branch's reason: a controller is a seat
        # comparison (CR 109.5) the object alone cannot answer.
        from ..subject_filters import subject_matches

        described = targets_desc.get("filter") or {}
        observer = (
            game.players.index(context.caster) if context.caster in game.players
            else None
        )
        # Handed **into** the resolver as its predicate rather than applied to
        # what it returns, and that is the whole of the fix: its default
        # predicate is ``p.is_creature``, so a bare
        # ``resolve_target_permanents(game, context)`` drops every non-creature
        # slot before this branch can see it — Recantation returned two of the
        # three permanents its picker collected and logged itself resolved.
        chosen = resolve_target_permanents(
            game, context,
            predicate=lambda perm: subject_matches(
                game, perm, described,
                observer=observer, source=context.source_permanent,
            ),
        )
        for perm in chosen:
            owner = return_permanent_to_owners_hand(game, perm, context.caster)
            game.log.append(f"{perm.card.name} returned to {owner.name}'s hand")
        if not chosen:
            game.log.append("No permanents to return")
        return True, "resolved"
    # A narrowed or widened bounce ("up to one target non-Spirit creature",
    # Roaming Ghostlight; "up to one other target creature or planeswalker",
    # Barrin) carries its filter. Resolved strictly — no fallback scan, since
    # "up to one" legally names nothing — and enforced here so a stale or
    # illegal choice bounces nothing rather than the wrong thing.
    # ``in``, not truthiness: "Return target **permanent** to its owner's hand"
    # (Boomerang) narrows nothing, so its filter is an empty dict — and an empty
    # dict read as "no filter" would drop through to the creature-only fallback
    # below and refuse to bounce the land the spell legally targeted. The key's
    # *presence* is what says the lowering described this bounce's subject.
    if "filter" in instruction.payload:
        bounce_filter = instruction.payload["filter"]
        source = context.source_permanent

        # "another target creature **you control**" (Niambi, Esteemed Speaker).
        # Through ``subject_matches`` rather than the pure matcher, because the
        # controller question is a seat comparison the object alone cannot
        # answer (CR 109.5) — and it carries ``exclude_self`` in the same call,
        # so the two narrowings are one rule instead of one here and one there.
        # Late import: ``subject_filters`` imports this package's ``_common``,
        # so the edge is taken at call time rather than at module load.
        from ..subject_filters import subject_matches

        observer = game.players.index(context.caster)

        def _legal(perm) -> bool:
            return subject_matches(
                game, perm, bounce_filter, observer=observer, source=source
            )

        perm = resolve_target_permanent(
            game, context, predicate=_legal, fallback_on_invalid_choice=False,
        )
        if perm is None:
            game.log.append(f"{context.card.name}: nothing was returned")
            return True, "resolved"
        owner = return_permanent_to_owners_hand(game, perm, context.caster)
        # "…you gain life equal to that creature's mana value" (Niambi). Read
        # here, while the permanent is still in hand, because the next step of
        # this same resolution has no way back to it — CR 400.7 makes the card in
        # the hand a new object, and the battlefield no longer holds the old one.
        # ``_PRODUCES`` names this kind as the producer, so every path of this
        # handler that returns one creature records it.
        context.results["returned_mana_value"] = _mana_value_of(perm.card)
        game.log.append(f"{perm.card.name} returned to {owner.name}'s hand")
        return True, "resolved"
    target = context.target
    # Resolved **once**, by id, and used for both the bounce and the record.
    # An earlier removal renumbers the battlefield under a recorded index
    # (CR 400.7), so the slot names whichever creature slid into the vacated
    # place — and this site used to read it twice, once here for
    # "…equal to that creature's mana value" and once inside the bounce. Two
    # reads of one choice are free to disagree: the life could be gained for a
    # creature other than the one returned.
    returned = resolve_target_permanent(game, context, player=target)
    bounced = game._bounce_target_creature(returned)
    if bounced and returned is not None:
        context.results["returned_mana_value"] = _mana_value_of(returned.card)
    game.log.append("Returned creature to hand" if bounced else "No creature to return")
    return True, "resolved"


@effect_handler("bounce_event_subject")
def bounce_event_subject(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever a creature becomes the target of a spell or ability, **return
    that creature to its owner's hand**." (Cowardice.)

    The permanent the *trigger's own event* was about, carried by id in the
    trigger's context — ``destroy_event_subject``'s twin one zone change over
    (CR 400.1; a return to a hand is no keyword action at all), reading the same
    frozen key for the same reason: nothing was chosen (CR 603.3d printed no
    target), and by resolution an index is not an identity (CR 400.7 / 603.10).

    Not routed through ``bounce_target_creature``: that one raises a picker for
    a choice this card never offered and then returns whichever permanent the
    resolution context happened to hold.

    **No re-check of the printed noun**, for that handler's stated reason: the
    event's filter already decided this permanent is what the trigger was
    about, and asking again would let a creature that stopped being one between
    the two escape a bounce the rules have already aimed at it.

    A permanent already gone is returned by nothing, which is CR 608.2b doing
    as much as it can. Cowardice's own reminder text says the spell that
    triggered it still resolves and finds nothing there.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("event_subject_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the permanent it named is gone")
        return True, "resolved"
    owner = return_permanent_to_owners_hand(game, victim, context.caster)
    game.log.append(
        f"{victim.card.name} returned to {owner.name}'s hand ({context.card.name})"
    )
    return True, "resolved"


def _was_attached_to(perm, host_id: int) -> bool:
    """Whether *perm* is — or was, this resolution — attached to *host_id*.

    Both records, because a sweep that names an attachment can run after the
    host has moved: "Return target creature **and all white Auras you own
    attached to it**" (Word of Undoing) bounces the creature in the step before
    this one, and ``detach_aura`` has already cleared the live pointer by then.
    That is CR 603.10's reading — the spell chose its target while it was on the
    battlefield — and the id is what keeps it from matching a look-alike
    (CR 400.7).
    """
    host = perm.metadata.get("attached_to") or perm.metadata.get("last_attached_to")
    return host is not None and getattr(host, "permanent_id", None) == host_id


@effect_handler("return_all_matching")
def return_all_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return to your hand all enchantments you both own and control…"
    (Remove Enchantments.)

    The sweep twin of ``bounce_target_creature``: no pick, every permanent the
    noun phrase names, each to *its owner's* hand (CR 400.3). One handler for
    every such phrase, because what a bounce does per object does not depend on
    which noun was printed — the noun is the payload.

    The filter is asked through ``subject_matches`` with CR 109.5's observer:
    "you control", "you own" and the host phrase inside "attached to permanents
    you control" are all seat comparisons, and the lowering admitted the line
    only because this is where they are answered.

    ``attached_to`` narrows the sweep to what is on one named permanent —
    "…and all white Auras you own **attached to it**" (Word of Undoing), where
    "it" is the creature the same spell targeted. Beside the filter rather than
    inside it, because it is a relation no read of the Aura alone can answer:
    the referent is resolved here and the hosts are compared by identity, the
    same split ``destroy_all_matching`` makes for the same key.

    The matched list is taken **before** anything moves. A permanent leaving
    detaches its Auras, so a sweep that re-read the board between removals
    would stop matching Auras it had already named — and "attached to" is
    exactly what half of this card's phrases ask about. Word of Undoing makes
    that load-bearing rather than careful: the creature is bounced by the step
    in front of this one, so by the time the sweep runs every Aura it names has
    already fallen off.
    """
    from ..subject_filters import subject_matches

    swept = instruction.payload.get("filter") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )
    host_id = None
    attached_to = instruction.payload.get("attached_to")
    if attached_to is not None:
        # By **id**, not by object, and that is what makes Word of Undoing work
        # at all: the step in front of this one has already bounced the
        # creature, so ``permanent_by_id`` no longer finds it while every Aura
        # still holds the record of what it was on. CR 400.7 makes the id
        # unique to that object, so a look-alike cannot answer to it.
        # Through ``_one_choice``, because the two callers hand this field
        # different shapes: a *spell* records one id (Word of Undoing) and an
        # *activated ability* records the whole announced list, even when the
        # list is one long. Read raw, an ability's `[7]` never equals any
        # permanent's id and the sweep found nothing on a host the player had
        # chosen — Scarab of the Unseen is the first ability to reach here.
        host_id = (
            _one_choice(context.target_permanent_id)
            if attached_to == "target" else None
        )
        if not isinstance(host_id, int):
            # The relation is the whole narrowing, so a referent this cannot
            # resolve ends the sweep rather than widening it to the board.
            game.log.append(
                f"{context.card.name}: nothing is attached to a permanent that is gone"
            )
            return True, "resolved"
    # "…each creature **that player** controls with power greater than the
    # number of cards in **their** hand." (Noetic Scales.) The seat the firing
    # event froze (CR 603.10) — a different player on every upkeep, and never
    # this artifact's controller except on their own turn. Read through the one
    # reader of the printed phrase, so both narrowings that name it name the
    # same player; None where nothing froze one, which the matcher answers by
    # refusing the words rather than by widening the sweep to the table.
    that_player = frozen_that_player_seat(game, context)
    matched = [
        perm for perm in game.all_permanents()
        if subject_matches(
            game, perm, swept, observer=observer, source=context.source_permanent,
            that_player=that_player,
        )
        and (host_id is None or _was_attached_to(perm, host_id))
    ]
    returned: list[str] = []
    for perm in matched:
        if not game.is_on_battlefield(perm):
            # It went with something else this same sweep removed — a token
            # ceasing to exist, an Aura falling off. Nothing left to return.
            continue
        return_permanent_to_owners_hand(game, perm, context.caster)
        returned.append(perm.card.name)
    game.log.append(
        f"{context.card.name} returned {', '.join(returned)} to hand"
        if returned else f"{context.card.name}: nothing to return"
    )
    return True, "resolved"


@effect_handler("exile_target_creature_until_eot")
def exile_target_creature_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    # 610.3: zone-change one-shot "until" EOT; second one-shot returns at cleanup
    target_perm_idx = context.target_permanent_index
    exiled_perm: Permanent | None = None
    if isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(target.battlefield):
        candidate = target.battlefield[target_perm_idx]
        if candidate.is_creature:
            exiled_perm = candidate
            game.remove_from_battlefield(candidate)
    if exiled_perm is None:
        for perm in list(game.controlled_by(target)):
            if perm.is_creature:
                exiled_perm = perm
                game.remove_from_battlefield(perm)
                break
    if exiled_perm is not None:
        target.exile.append(exiled_perm.card)
        owner_idx = game.players.index(target)
        game.exile_until_eot.append((owner_idx, exiled_perm.card))
        game.log.append(f"{exiled_perm.card.name} exiled until end of turn by {card.name}")
    else:
        game.log.append(f"{card.name}: no valid creature to exile")
    return True, "resolved"


@effect_handler("strip_cards_with_chosen_name")
def strip_cards_with_chosen_name(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Search that player's graveyard, hand, and library for all cards with the
    same name as the chosen card and exile them. Then that player shuffles."
    (Lobotomy.)

    …and "Exile target nonblack creature. Search **its controller's** graveyard,
    hand, and library for all cards with the same name as **that creature** and
    exile them. Then that player shuffles." (Eradicate, Scour, Splinter, Sowing
    Salt; Quash prints it behind a counter.) One handler because it is one
    effect: three zones walked in the printed order, every copy of one name
    exiled, and the library shuffled at the end. What differs is only where the
    name and the seat are read from, which the lowering settles into two payload
    keys — see the branch below.

    The **decomposed** half of Necromentia's paragraph. That card fuses the
    naming, the strip and a token clause into one handler because its last
    sentence counts a pile only that handler holds; this one has nothing behind
    it, so the naming is the step in front and this is the strip alone — reading
    the name out of the resolution's scratchpad, which is where every "the
    chosen card" in this engine is written.

    CR 701.23c is about this card by name: with an empty hand nothing was
    chosen, so the quality is undefined, the searcher still searches and finds
    nothing. An unrecorded name is exactly that case and is **not** treated as
    "match everything" — the whole library would go to exile, which is the
    opposite of what an empty choice means.

    The zones are walked in the printed order and only the library is shuffled
    (CR 701.24): a graveyard is an open zone and a hand is its owner's, and
    randomising either would be a move the sentence does not describe.
    """
    # Which two records this sentence reads, or neither. Lobotomy names the
    # seat it searched outright and reads the name out of ``chosen_card_name``;
    # Eradicate and its four siblings name *both* off the step in front of them
    # — "its controller's" zones, "that creature's" name — and the lowering
    # says which pair, because only it knows what an exile, a destroy or a
    # counter leaves behind.
    name_record = instruction.payload.get("name_record")
    seat_record = instruction.payload.get("seat_record")
    if name_record is not None:
        seat = context.results.get(seat_record)
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            # The step in front chose nothing — its target had left (CR 608.2b)
            # — so there is no object for "its controller" or "that creature" to
            # name and nothing to search. Not a search that finds everything:
            # an unrecorded seat would otherwise fall through to the resolving
            # spell's own target, which for these five is the permanent or the
            # spell rather than a player.
            game.log.append(
                f"{context.card.name}: nothing was chosen, so no zones are searched"
            )
            return True, "resolved"
        target = game.players[seat]
        named = str(context.results.get(name_record) or "").strip()
    else:
        target = context.target
        if target is None or target not in game.players:
            game.log.append(f"{context.card.name}: no player to search")
            return True, "resolved"
        named = str(context.results.get("chosen_card_name") or "").strip()
    zones = tuple(instruction.payload.get("zones") or ())
    if not named:
        # The pick chose nothing (an empty hand, or a hand of nothing but basic
        # lands). The search still happens and finds nothing, which CR 701.23c
        # spells out on this very card.
        game.log.append(
            f"{context.card.name}: nothing was chosen, so nothing is exiled"
        )
        if "library" in zones:
            random.shuffle(target.library)
        return True, "resolved"
    taken: list[str] = []
    for zone in zones:
        cards = getattr(target, zone, None)
        if cards is None:
            continue
        kept = [card for card in cards if card.name != named]
        found = [card for card in cards if card.name == named]
        if found:
            cards[:] = kept
            target.exile.extend(found)
            taken.extend(card.name for card in found)
    if "library" in zones:
        random.shuffle(target.library)
    game.log.append(
        f"{target.name} lost {len(taken)} copies of {named} to "
        f"{context.card.name}"
    )
    return True, "resolved"


@effect_handler("name_and_strip")
def name_and_strip(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Necromentia: name a card, strip every copy from an opponent's three
    zones, then pay them a Zombie for each one taken from their **hand**.

    One handler for the whole effect because the three printed sentences share
    one choice and one pile — "each card exiled from their hand this way" counts
    exactly the subset the search took from one of the zones, and split apart
    the last sentence would count a pile nobody recorded.

    The name is chosen as the spell resolves (CR 608.2), and CR 202.1 lets a
    player name any card — bounded here only by the printed restriction, which
    is that it may not be a basic land's name. A seat that names nothing strips
    nothing, which is legal and useless; the default names the commonest card
    among what it can see, which is the choice a player would actually make.
    """
    caster = context.caster
    target = context.target
    if target is None or target is caster:
        game.log.append(f"{context.card.name}: no opponent to search")
        return True, "resolved"
    seat = game.players.index(target)
    game.arm_pending_choice(
        "name_and_strip", game.players.index(caster),
        card_name=context.card.name,
        target_seat=seat,
        zones=list(instruction.payload.get("zones") or ()),
        token_zone=instruction.payload.get("token_zone", "hand"),
        token=dict(instruction.payload.get("token") or {}),
        default_name=_commonest_visible_name(
            game, seat, instruction.payload.get("zones") or ()
        ),
    )
    return True, "pending_name_and_strip"


def _commonest_visible_name(
    game, seat: int, zones, *, exclude_basics: bool = True,
    card_type: str | None = None,
) -> str:
    """The name a non-interactive seat picks: the one appearing most often in
    *zones* of *seat*'s cards, ties broken by name so a seed replays exactly.

    Whether basic land names count is the *card's* restriction, not this
    helper's: Necromentia forbids them and a headless game must obey the same
    rule its prompt does, while Petra Sphinx's guess may name anything (CR
    202.1) and excluding them there would refuse a name a player would happily
    pick. So it is a parameter, and the zone list is passed rather than dug out
    of a payload key only one caller has.

    ``card_type`` is the same fact in the other direction — "Choose a
    **creature** card name" (Wood Sage) bounds what may legally be named, and a
    default outside the bound is a headless game breaking a rule the prompt
    enforces. Nothing matching leaves the name empty, which is what a seat with
    no legal answer it can see actually has.
    """
    from collections import Counter

    player = game.players[seat]
    counts: Counter = Counter()
    for zone in zones or ():
        for card in getattr(player, zone, []):
            if exclude_basics and "basic" in (card.type_line or "").lower():
                continue
            if card_type and card.primary_type != card_type:
                continue
            counts[card.name] += 1
    if not counts:
        return ""
    best = max(counts.values())
    return sorted(name for name, n in counts.items() if n == best)[0]


@effect_handler("reveal_until_match")
def reveal_until_match(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…reveals cards from the top of their library until they reveal a
    creature card. That player puts that card onto the battlefield, then
    shuffles the rest into their library." (Transmogrify.)

    One handler for the whole procedure, because the three sentences describe
    one pile: "that card" is what the reveal stopped on and "the rest" is
    exactly what it turned over first, so nothing between them can be a separate
    instruction without recording a list for the next one to read.

    **A library that never produces a match is not an error.** CR 701.20a's
    reveal is bounded by the library, so an empty one ends the search — the
    player reveals their whole library, puts nothing onto the battlefield, and
    shuffles it back. Anything else here is an infinite loop on a real board.
    """
    payload = instruction.payload
    whose = payload.get("whose")
    if whose == "you":
        # "Reveal cards from the top of **your** library …" (Sacred Guide.) The
        # printed word rather than a back-reference, so there is no record to
        # read and none to demand: the seat is the one performing the effect.
        # Read through ``context.caster`` for the reason every other handler
        # does — it is CR 109.5's answer already resolved, and a scan would
        # differ from it under a control change.
        seat = game.players.index(context.caster)
    else:
        seat = context.results.get(whose)
    if seat is None:
        game.log.append(f"{context.card.name}: nobody to reveal from")
        return True, "resolved"
    player = game.players[seat]
    described = dict(payload.get("filter") or {})

    revealed: list = []
    found = None
    while player.library:
        card = player.library.pop(0)
        if _card_matches_filter(card, described, game=game, owner=player):
            found = card
            break
        revealed.append(card)

    if found is not None:
        game.log.append(f"{player.name} revealed {found.name}")
        game.record_reveal(seat, [found.name])
        if payload.get("destination") == "battlefield":
            game._put_permanent_onto_battlefield(
                seat, Permanent(card=found), None, from_zone="library",
            )
        else:
            game.put_card_into_hand(player, found)
    else:
        game.log.append(f"{player.name} revealed their library and found nothing")

    # "…then shuffles the rest into their library." The revealed cards go back
    # and the library is shuffled, which is why they were held aside rather than
    # put back one at a time — CR 701.24 shuffles once, at the end.
    rest = payload.get("rest")
    if rest == "shuffle_into_library":
        player.library.extend(revealed)
        # Through the module RNG `run_ai_simulation` seeds, like every other
        # shuffle in the engine, so a given seed still replays exactly.
        random.shuffle(player.library)
    elif rest == "exile":
        # "…and **exile** all other cards revealed this way." (Sacred Guide.)
        # The third printed fate, and the one that costs the revealer the
        # cards for good — a graveyard is a zone half this pool can reach back
        # into, so lowering the word onto the branch below would have made the
        # card strictly better than it reads.
        for card in revealed:
            player.exile.append(card)
        if revealed:
            game.log.append(
                f"{player.name} exiled {len(revealed)} card(s) revealed this way"
            )
    else:
        for card in revealed:
            game.put_card_into_graveyard(player, card, from_zone="library")
    return True, "resolved"


@effect_handler("exile_bound_card")
def exile_bound_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When that creature dies this turn, exile **it**." (Whippoorwill.)

    The object a delayed ability was bound to, after the death that fired it —
    so what is exiled is a *card in a graveyard*, never a permanent. CR 603.7d
    makes the ability's source the permanent that created it, which is exactly
    the reading this handler exists to avoid: routed through ``exile_self``,
    Whippoorwill exiled itself every time its target died.

    The card is found by name in the owner's graveyard, the two facts the death
    seam freezes into the trigger's context (CR 608.2h): by resolution the
    permanent is gone, CR 400.7 makes its card a new object, and a graveyard
    has no controller to re-derive the seat from. Two copies of one card in a
    pile are literally one ``CardDefinition``, so which of them is taken is not
    a question with an answer — and the *last* one is taken, because a death
    puts the card on top.

    A card that has already left that pile exiles nothing rather than falling
    back to a scan: CR 608.2's "as much as possible", and a scan would exile
    whichever look-alike it reached first.

    **Two ways the card can have been recorded, and the identity one wins.**
    "Whenever a nontoken creature is put into your graveyard from the
    battlefield, exile that card" (Purgatory) fires from the death seam, which
    freezes the ``CardDefinition`` itself; the delayed spelling above it froze a
    seat and a *name*, because that fire site had nothing else. An identity is
    strictly the better answer — a graveyard holding two copies of one card
    holds one ``CardDefinition`` twice, so the name cannot tell them apart and
    the seat cannot either — so it is asked first and the name is the fallback
    rather than the rule.

    The exile is **recorded against the ability's source** (CR 610.3). Nothing
    here can know whether the permanent has a second ability naming "a card
    exiled with this enchantment" — Purgatory does, Whippoorwill does not — and
    the record is the only thing that could answer it, so it is always written.
    It ends nothing on its own: ``ends_on`` is empty, so no sweep gives these
    cards back.
    """
    from ..linked_exile import link_exiled_card

    trigger = context.trigger_context or {}
    card = trigger.get("dead_card")
    owner = None
    index = None
    if card is not None:
        for player in game.players:
            found = next(
                (i for i, held in enumerate(player.graveyard) if held is card), None
            )
            if found is not None:
                owner, index = player, found
                break
        if owner is None:
            game.log.append(
                f"{context.card.name}: {card.name} is no longer in a graveyard"
            )
            return True, "resolved"
    else:
        seat = trigger.get("event_subject_owner")
        name = trigger.get("dead_name")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)) or not name:
            game.log.append(f"{context.card.name}: no card was recorded to exile")
            return True, "resolved"
        owner = game.players[seat]
        index = next(
            (i for i in range(len(owner.graveyard) - 1, -1, -1)
             if owner.graveyard[i].name == name),
            None,
        )
        if index is None:
            game.log.append(
                f"{context.card.name}: {name} is no longer in {owner.name}'s graveyard"
            )
            return True, "resolved"
    exiled = owner.graveyard.pop(index)
    owner.exile.append(exiled)
    source = context.source_permanent
    if source is not None:
        link_exiled_card(source, exiled, game.players.index(owner))
    game.log.append(
        f"{context.card.name} exiled {exiled.name} from {owner.name}'s graveyard"
    )
    return True, "resolved"


@effect_handler("exile_self")
def exile_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile it." / "Exile this creature." (Archfiend's Vessel.)

    The ability's own source, which is not a target: nothing is chosen, so there
    is no picker, no legality check and nothing to re-resolve. A source that has
    already left the battlefield exiles nothing rather than falling back to a
    scan — CR 608.2b's "do as much as possible", and a scan here would exile
    whichever look-alike it reached first.

    Records whether it happened, so "**If you do**, create a 5/5 black Demon
    creature token" is the ordinary if-you-do branch rather than a fused
    instruction.

    ``counters`` is "…with two scream counters on it" (All Hallow's Eve): the
    card goes to exile carrying them, and the register in
    ``engine/exiled_records.py`` is what remembers so — a ``CardDefinition`` in
    an exile list has nowhere to keep them and no identity to key them on. The
    registration happens here, where the exiling is *decided*, for both paths:
    a spell exiling itself is binned at the very end of its own resolution
    (CR 608.2n), so this is the only moment both a permanent and a spell pass
    through.
    """
    def _register(owner_index: int, card) -> None:
        counters = instruction.payload.get("counters") or {}
        if not counters:
            return
        # ``resolve_amount`` rather than ``int``: a count may be the cast's X
        # (CR 107.3), which travels as the string ``"x"`` — the same spelling
        # every other counted payload in this engine carries. Resolved once,
        # because the register and the log must not disagree about how many.
        placed = {
            str(k): resolve_amount(v, context.x_value) for k, v in counters.items()
        }
        record_exiled_card(
            game, card, owner_index,
            # CR 108.4: a card in exile has no controller, so its abilities
            # belong to its owner. Recorded explicitly rather than left to
            # default, because "at the beginning of **your** upkeep" needs a
            # seat and the register is the only thing that still has one.
            controller_index=owner_index,
            counters=placed,
        )
        game.log.append(
            f"{card.name} was exiled with "
            + ", ".join(
                f"{count} {name} counter" + ("s" if count != 1 else "")
                for name, count in placed.items()
            )
        )

    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        # "When this creature dies, **exile it** if it had a death counter on
        # it." (Bogardan Phoenix.) A dies-trigger's source is in a graveyard by
        # the time the ability resolves (CR 603.3 puts the trigger on the stack
        # *after* the state-based action moved the card), and "it" means that
        # card — CR 603.10's last-known information names the object, and the
        # object's current zone is where the move comes from. Without this the
        # exile branch of a dies-trigger logged "nothing to exile" and the card
        # stayed in the graveyard, which for the Phoenix is the card returning
        # for ever.
        #
        # By identity through the hand/graveyard seam's own reasoning: two
        # copies of a card in a deck are the same immutable ``CardDefinition``,
        # so a name match would take whichever entry came first.
        # …and **an ability activated from a graveyard** (Carrionette's
        # "Exile this card and target creature", CR 113.6m). There is no
        # permanent at all there, so the branch below would read the sentence
        # as a spell exiling itself and set the resolving-spell flag on an
        # ability — which bins nothing and leaves the card in the pile, exactly
        # the failure the Phoenix note above describes.
        #
        # ``ability_text`` is the discriminator and it is the only sound one:
        # it is set for an activated ability and None for a spell, where the
        # zone is not. A graveyard scan run for a *spell* would find another
        # copy of the same card in the pile — two copies of a card in a deck
        # are the same object — and exile that one instead of the spell.
        #
        # Hoisted above the resolving-spell branch for that same reason: the
        # two are told apart by the discriminator rather than by which one is
        # tried first.
        if context.card is not None and (
            source is not None or context.ability_text is not None
        ):
            # The resolving seat's own pile first. Two copies of one card in
            # two graveyards are the *same* ``CardDefinition`` object, so a
            # scan in seat order would take an opponent's copy whenever they
            # sit earlier — and for a graveyard-activated ability CR 113.6m
            # names one pile in particular, the activator's.
            piles = [context.caster] + [
                player for player in game.players if player is not context.caster
            ]
            for player in piles:
                for index, held in enumerate(player.graveyard):
                    if held is context.card:
                        player.graveyard.pop(index)
                        player.exile.append(held)
                        context.results["exiled_self"] = True
                        _register(game.players.index(player), held)
                        game.log.append(
                            f"{context.card.name} was exiled from "
                            f"{player.name}'s graveyard"
                        )
                        return True, "resolved"
        # **A spell exiling itself** (Experimental Overload's "Exile Experimental
        # Overload."). There is no permanent — the object is the spell on the
        # stack — so this is CR 608.2n's "where the card goes" rather than a
        # zone change of something in play, and it routes through the same flag
        # the "if that spell would be put into your graveyard, exile it instead"
        # rider uses. Set rather than performed: the card is still resolving,
        # and the resolution tail is the one place that bins it.
        if source is None and context.card is not None:
            game.exile_resolving_spell = True
            context.results["exiled_self"] = True
            game.log.append(f"{context.card.name} will be exiled as it resolves")
            # Registered under the seat whose exile the resolution tail will
            # bin it to — its **owner's** (CR 400.3), which is the resolving
            # stack object's ``owner_index`` and not the caster when the spell
            # was cast out of another player's zone. A record keyed to the
            # caster would never be live, and All Hallow's Eve's scream
            # counters would never come off.
            resolving = (getattr(game, "resolving_items", None) or [None])[-1]
            owner_seat = (
                resolving.owner_index
                if resolving is not None and resolving.card is context.card
                else game.players.index(context.caster)
            )
            _register(owner_seat, context.card)
            return True, "resolved"
        game.log.append(f"{context.card.name}: nothing to exile")
        return True, "resolved"
    owner_index = game.owner_index_of(source)
    owner = game.players[owner_index] if owner_index is not None else context.caster
    game.remove_from_battlefield(source)
    if not source.metadata.get("is_token", False):
        # CR 111.7: a token ceases to exist rather than going to exile.
        owner.exile.append(source.card)
        # The seat the owner lookup already found. ``players.index(owner)``
        # would compare ``PlayerState`` by value, which is the look-alike bug
        # the control seam documents for permanents.
        _register(
            owner_index if owner_index is not None else game.players.index(context.caster),
            source.card,
        )
    context.results["exiled_self"] = True
    game.log.append(f"{source.card.name} was exiled")
    return True, "resolved"


@effect_handler("exile_created_token")
def exile_created_token(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile **that token**…" — the token an earlier step of this same effect
    created (Stangg).

    Not a target and not the source: the token maker wrote its ``permanent_id``
    to the resolution scratchpad, and this reads it back. By id rather than by
    a scan for a matching token, for the reason every bound object in this
    engine is an id — a second Stangg Twin on another battlefield is a
    look-alike, and a scan would reach whichever came first.

    The id is read from the firing trigger's context first: this instruction is
    normally the effect of a *delayed* ability, and by the time that ability
    fires the resolution that created the token is long over. The delayed entry
    froze the scratchpad (CR 608.2h), which is where the id then lives.

    ``created_with_source`` is the same object one reach further out — "exile
    **the token**" (Dance of Many), where the token maker is a *different
    ability of the same permanent* and fired turns ago. No scratchpad survives
    that, so the id comes off the durable record the maker stamped on the token
    (``tokens_created_with``). One kind rather than two, because what differs
    is where the id is read and not what is done with it.

    A token that is already gone exiles nothing (CR 608.2b, and CR 111.7 —
    a token that has left the battlefield has ceased to exist).
    """
    # "Create three … tokens. **Exile them** at the beginning of the next
    # cleanup step." (Waylay.) The plural of the same back-reference, reading
    # the list the maker recorded beside the single id — out of the *frozen*
    # scratchpad first, because this instruction is normally a delayed
    # ability's and the resolution that made the tokens is long over
    # (CR 608.2h). A token already gone exiles nothing (CR 111.7).
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        ids = (context.trigger_context or {}).get(str(recorded_key))
        if not isinstance(ids, (list, tuple)):
            ids = context.results.get(str(recorded_key))
        found = [
            game.permanent_by_id(one)
            for one in (ids or ())
            if isinstance(one, int)
        ]
        gone = [perm for perm in found if perm is not None]
        if not gone:
            game.log.append(f"{context.card.name}: the tokens it named are gone")
            return True, "resolved"
        for perm in gone:
            _exile_one_created_token(game, context, perm)
        return True, "resolved"
    if instruction.payload.get("created_with_source"):
        made = tokens_created_with(game, context.source_permanent)
        # The phrase is singular. A permanent that made several would leave
        # "the token" naming no one of them, so the sentence takes the one it
        # names and nothing otherwise — the same refusal every ambiguous
        # back-reference in this engine takes.
        token = made[0] if len(made) == 1 else None
    else:
        recorded = (context.trigger_context or {}).get(CREATED_TOKEN_RESULT_KEY)
        if not isinstance(recorded, int):
            recorded = context.results.get(CREATED_TOKEN_RESULT_KEY)
        token = game.permanent_by_id(recorded) if isinstance(recorded, int) else None
    if token is None:
        game.log.append(f"{context.card.name}: the token it named is gone")
        return True, "resolved"
    _exile_one_created_token(game, context, token)
    return True, "resolved"


def _exile_one_created_token(game: Game, context: OracleExecutionContext, token) -> None:
    """Send one recorded token where CR 111.7 and CR 400.3 send it.

    One body because the plural branch above exiles several and a second copy
    of the CR 111.7 test is a second chance for one of them to forget that a
    token ceases to exist rather than going to exile.
    """
    owner_index = game.owner_index_of(token)
    game.remove_from_battlefield(token)
    if not token.metadata.get("is_token", False) and owner_index is not None:
        # CR 111.7: a token ceases to exist rather than going to exile. The
        # check is here rather than assumed because the scratchpad records a
        # *permanent* id, and nothing stops a later card from recording one
        # that is not a token.
        game.players[owner_index].exile.append(token.card)
    game.log.append(f"{context.card.name} exiled {token.card.name}")


@effect_handler("exile_target_permanent")
def exile_target_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile target creature or planeswalker." / "Exile target nonland
    permanent." — the *permanent* exile, as distinct from
    ``exile_target_creature_until_eot``, which records a return at cleanup.
    Nothing here is remembered, because nothing comes back (CR 406.1).

    Three things this deliberately does not open-code:

    * **the removal.** ``remove_from_battlefield`` is the one transition off
      the battlefield; a hand-rolled rebuild would skip the combat renumbering
      every leave depends on, and ``list.remove`` matches a look-alike.
    * **the destination.** CR 400.3 sends an exiled card to its *owner's*
      exile, which is not the seat that was targeted once it was stolen.
    * **the controller, read before the removal.** "Its controller creates a
      token" is a later step of the same resolution, and once the permanent is
      gone there is nobody left to ask — which is why this is two composed
      instructions rather than one fused kind.
    """
    card = context.card
    payload = instruction.payload
    # "Exile **two target** nonartifact creatures." (Ashes to Ashes; Dust to
    # Dust prints the same over artifacts.) The several-targets description is
    # the opt-in: a list was collected at announcement, so each slot resolves
    # strictly and a target that has left is simply dropped (CR 608.2b) rather
    # than falling back to whatever a scan reaches first, which for two slots
    # would exile a permanent the player never chose. A lowering that dropped
    # ``count`` would exile one of the two and report the card supported.
    targets_desc = instruction.payload.get("targets") or {}
    if (
        isinstance(targets_desc, dict)
        and isinstance(targets_desc.get("count"), int)
        and targets_desc["count"] > 1
    ):
        # The printed predicate rather than the default, which is "is it a
        # creature?" — Dust to Dust names artifacts, and a slot the resolver
        # rejects is a slot silently dropped. Idiom 9: the picker's enumeration
        # is a hint, so the printed filter is what decides, here as at
        # announcement.
        chosen = resolve_target_permanents(
            game, context,
            predicate=lambda candidate: permanent_matches_filter(candidate, payload),
        )
        if not chosen:
            game.log.append(f"{card.name}: no valid permanent to exile")
            return True, "resolved"
        # Each one to its **owner's** exile, read before its own removal: the
        # loop is one resolution and a controller read after the fact has
        # nobody left to ask.
        for perm in chosen:
            controller_index = game.controller_index_of(perm)
            owner_index = game.owner_index_of(perm)
            game.remove_from_battlefield(perm)
            if owner_index is None:
                owner_index = controller_index if controller_index is not None else 0
            game.players[owner_index].exile.append(perm.card)
            game.log.append(f"{card.name} exiled {perm.card.name}")
        # No `last_target_controller`: the key names *the* controller, and
        # a several-target exile has one per permanent. A later step reading it
        # would silently act on whichever one happened to be written last, so
        # the key is left absent and any card that needs it refuses for want of
        # a producer rather than acting on the wrong seat.
        return True, "resolved"
    # "Exile target permanent **you own or control**." (Telim'Tor's Edict;
    # Safe Haven prints "you control".) A *relative* narrowing — a question
    # about a seat rather than about the card — which the pure matcher
    # deliberately cannot answer and therefore silently drops. The picker's
    # spec for this kind carries no filter either, so the phrase was enforced
    # nowhere at all: the Edict exiled any permanent on the table.
    #
    # ``subject_matches`` is the one reader of what a printed noun phrase
    # means, with the resolving controller as "you" (CR 109.5) — idiom 9, the
    # picker's enumeration is a hint and the resolution re-checks the answer.
    from ..subject_filters import subject_matches

    described = {key: value for key, value in payload.items() if key != "targets"}
    observer = (
        game.players.index(context.caster)
        if context.caster in game.players else None
    )
    def _answers(candidate) -> bool:
        return subject_matches(
            game, candidate, described, observer=observer,
            source=context.source_permanent,
        )

    # **A recorded id is the choice** (CR 601.2c), read strictly: the permanent
    # it names if that still answers the printed description, and otherwise
    # nothing (CR 608.2b). ``resolve_target_permanent`` falls through to a scan
    # of the target's battlefield when the id fails its predicate, which is
    # right for a caller that recorded no choice and wrong for one that did:
    # Eradicate cast at a creature made black in response exiled the creature
    # beside it, and Topple ("…with the greatest power among creatures on the
    # battlefield") exiled whichever creature had just overtaken its target. A
    # seat-only announcement (no id) keeps the scan.
    recorded = context.target_permanent_id
    if isinstance(recorded, list):
        recorded = recorded[0] if recorded else None
    if isinstance(recorded, int):
        named = game.permanent_by_id(recorded)
        perm = named if named is not None and _answers(named) else None
    else:
        perm = resolve_target_permanent(game, context, predicate=_answers)
    if perm is None:
        game.log.append(f"{card.name}: no valid permanent to exile")
        return True, "resolved"
    controller_index = game.controller_index_of(perm)
    owner_index = game.owner_index_of(perm)
    # "You gain life equal to **its toughness**" (Exile) is a later step of the
    # same resolution asking a question about an object that will by then be a
    # card in exile — CR 613.1 gives it no computed characteristics at all, so
    # the number is frozen here, one line before the removal, exactly as
    # ``destroy_target_permanent`` freezes its pair one line before the destroy
    # (CR 608.2h). The effective value, so a pumped or counter-laden creature is
    # worth what it was worth on the battlefield.
    #
    # Toughness alone. The power of an exiled permanent has an owner already —
    # ``_fused_exile_then_controller_life`` — and ``_records._PRODUCES`` says
    # at length why declaring it here would un-refuse a near-miss that reads
    # the wrong seat.
    context.results["its_toughness"] = max(0, int(perm.effective_toughness))
    # "…all cards with the same name as **that creature**" (Eradicate, Scour,
    # Splinter, Sowing Salt). The name, frozen one line before the removal for
    # the toughness's reason above: the search runs after this step and by then
    # the permanent is a card in exile, which CR 400.7 makes a new object no
    # board read can find. Through ``effective_card`` (CR 707.2) so a Clone of
    # Grizzly Bears strips Grizzly Bears rather than the copy's printed face.
    context.results[LAST_TARGET_NAME] = perm.effective_card.name
    game.remove_from_battlefield(perm)
    if owner_index is None:
        owner_index = controller_index if controller_index is not None else 0
    game.players[owner_index].exile.append(perm.card)
    # Recorded as exiled **with** the ability's source when that source is a
    # permanent (CR 610.3), exactly as ``exile_top_of_library`` does it and for
    # the same reason: nothing ends the link on its own — the entry carries no
    # ``ends_on`` — so it is inert for every card that never asks, and it is
    # everything for Safe Haven, whose upkeep trigger returns "each card exiled
    # with this land". Without it that trigger drains an empty pile and the
    # creatures never come back, which is the shape of a card reporting
    # supported and quietly doing nothing.
    if context.source_permanent is not None:
        link_exiled_card(context.source_permanent, perm.card, owner_index)
    if controller_index is not None:
        context.results[LAST_TARGET_CONTROLLER] = controller_index
    game.log.append(f"{card.name} exiled {perm.card.name}")
    return True, "resolved"


@effect_handler("reveal_hand")
def reveal_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target player reveals their hand." (CR 701.20 — Inquisition on its
    own, and the first half of Amnesia and Rag Man.)

    Its own step, so what happens to the revealed cards is the next
    instruction's business. The cards are *named*, because that is what
    "revealed" means here: a line saying only how many were held would leave
    the reveal indistinguishable from not revealing at all, and Inquisition's
    next sentence is sized by what is in that hand. Through ``record_reveal``, the one feed the web
    layer reads, rather than a log line alone: a reveal the client cannot show
    is a reveal the player has to take on trust, and Rag Man's at-random discard
    is exactly the effect where seeing the hand is the point.
    """
    # "**You** may reveal your hand …" (Manabond.) The printed word, read off
    # the payload rather than inferred from an empty ``context.target``: a
    # sentence is a sequence and by its second step the resolution may be
    # carrying a target an earlier step chose, so the inference would reveal
    # whichever hand that step happened to name. The same distinction
    # ``deal_damage`` records about its own recipient.
    if instruction.payload.get("who") == "you":
        victim = context.caster
    else:
        victim = context.target if context.target is not None else context.caster
    seat = next(
        (i for i, seated in enumerate(game.players) if seated is victim), None
    )
    names = [held.name for held in victim.hand]
    # "**For each blue instant card revealed this way**, …" (Sirocco.) What was
    # shown, as cards rather than names: the sentence behind this one narrows by
    # colour and card type, and a list of names cannot be asked either. Written
    # even for an empty hand, because an absent key is a back-reference with no
    # producer — a different thing from a reveal that showed nothing.
    context.results[REVEALED_HAND_CARDS] = list(victim.hand)
    if seat is not None:
        game.record_reveal(seat, names)
    game.log.append(
        f"{victim.name} reveals their hand: " + (", ".join(names) or "(empty)")
    )
    return True, "resolved"


@effect_handler("discard_all_matching_cards")
def discard_all_matching_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…and discards all nonland cards." (Amnesia.)

    Nobody chooses, so there is no pending choice and no prompt: every card in
    the hand answering the printed phrase is discarded. The filter is re-checked
    here rather than trusted from the lowering for the reason every other
    handler re-checks one — the payload describes what the card said, and this
    is the reader that decides what leaves the zone.

    **Idiom 11**: two copies of one card in a hand are literally one
    ``CardDefinition`` object, so the cards to discard are resolved *before*
    anything leaves the zone, and then removed by position from the back — a
    scan-and-remove by value would take the wrong copy of a pair.
    """
    victim = context.target if context.target is not None else context.caster
    filters = instruction.payload.get("filter") or {}
    # "…discards all cards **of that color**." (Persecute.) CR 608.2d's choice,
    # made by the sentence in front of this one and read out of the scratchpad
    # rather than off a permanent — the card that prints it is a sorcery and
    # there is none. Resolved here into the ordinary ``color_filter`` every card
    # matcher already reads, exactly as the sweep one family over resolves
    # ``subtype_filter_from``.
    #
    # **No colour means no discard**, and it must: an unanswered choice read as
    # "no narrowing" is not a card that does less, it is one that empties the
    # whole hand.
    color_key = instruction.payload.get("color_filter_from")
    if color_key is not None:
        chosen = context.results.get(str(color_key))
        if not chosen:
            game.log.append(
                f"{context.card.name}: no colour was chosen, so nothing is discarded"
            )
            return True, "resolved"
        filters = dict(filters)
        filters["color_filter"] = str(chosen)
    # "…discards all creature cards **of that type**." (Tsabo's Decree.) The
    # colour's sibling: a creature type an earlier step of this resolution
    # chose (CR 608.2d), resolved into the ordinary ``subtype_filter`` the card
    # matcher reads. No word means no discard, for the reason given above.
    subtype_key = instruction.payload.get("subtype_filter_from")
    if subtype_key is not None:
        chosen_type = context.results.get(str(subtype_key))
        if not chosen_type:
            game.log.append(
                f"{context.card.name}: no creature type was chosen, so nothing "
                "is discarded"
            )
            return True, "resolved"
        filters = dict(filters)
        filters["subtype_filter"] = str(chosen_type)
    doomed = [
        index for index, held in enumerate(victim.hand)
        if _card_matches_filter(held, filters, game=game, owner=victim)
    ]
    for index in reversed(doomed):
        discarded = victim.hand.pop(index)
        game._discard_card(victim, discarded)
    game.log.append(
        f"{victim.name} discarded {len(doomed)} card(s)"
        if doomed else f"{victim.name} had no cards to discard"
    )
    return True, "resolved"


@effect_handler("reveal_hand_and_choose")
def reveal_hand_and_choose(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target opponent reveals their hand. You choose a noncreature, nonland
    card from it. That player discards that card." (Duress.)

    The first time one player chooses from *another* player's hidden zone. The
    reveal is what makes that legal (CR 701.20 — the hand is public information
    from here on), so it is logged rather than assumed, and the choice is queued
    on the **caster's** seat with the victim's as payload: every other pending
    choice in the engine is owed by the player it is about, and this one is not.

    Nothing is queued when no card in the hand answers the filter — a choice
    with no legal answer is not a choice, and leaving it queued would block the
    caster on a prompt they cannot satisfy.
    """
    card = context.card
    if instruction.payload.get("victim") == "event_subject_player":
        # "Look at **that player's** hand …" (Leshrac's Sigil). Nothing was
        # targeted, so the seat is the one the firing event froze (CR 603.10)
        # rather than whatever this resolution is carrying. An absent key is a
        # trigger nobody froze a seat for; the lowering's gate is what keeps
        # that from arriving, and reading nothing here is the right answer if
        # it ever does.
        seat = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return False, "no seat was frozen for 'that player'"
        victim = game.players[seat]
    else:
        victim = context.target if context.target is not None else context.caster
    victim_index = next(
        (i for i, seated in enumerate(game.players) if seated is victim), None
    )
    caster_index = next(
        (i for i, seated in enumerate(game.players) if seated is context.caster), None
    )
    if victim_index is None or caster_index is None:
        return True, "resolved"
    exclude_types = list(instruction.payload.get("exclude_types") or ())
    # "…a card **other than a basic land card** from it" (Lobotomy). The second
    # narrowing this picker can carry, and it travels beside the first for that
    # one's reason: what is offered and what an answer is checked against are
    # one predicate, and a restriction only the handler knew about would be a
    # client offering the whole hand.
    # "You choose **a creature card** from it." (Ostracize.) The positive form
    # of the same question, under the key ``search_matches`` already answers it
    # with — and it travels beside the other two for their reason: a type only
    # this handler knew about would be a client offering the whole hand.
    card_types = list(instruction.payload.get("card_types") or ())
    narrowing = {
        "exclude_types": exclude_types,
        "exclude_basic_lands": bool(
            instruction.payload.get("exclude_basic_lands")
        ),
    }
    if card_types:
        narrowing["card_type"] = tuple(card_types)
    # "a **nonbasic** land card" (Encroach). The third narrowing, carried for
    # the two above it's reason: an exclusion only this handler knew about is a
    # client offering the whole hand.
    excluded_supertypes = list(instruction.payload.get("exclude_supertypes") or ())
    if excluded_supertypes:
        narrowing["exclude_supertypes"] = excluded_supertypes
    legal = [
        index
        for index, held in enumerate(victim.hand)
        if search_matches(held, narrowing)
    ]
    # CR 701.20 makes a reveal public where CR 701.20e's look shows the chooser
    # alone, so the line says which happened rather than saying "revealed" for
    # both.
    looked_at = bool(instruction.payload.get("looked_at"))
    game.log.append(
        f"{victim.name}"
        + (
            f" showed their hand ({len(victim.hand)} card(s)) to {context.caster.name}"
            if looked_at
            else f" revealed their hand ({len(victim.hand)} card(s))"
        )
        + f" to {card.name}"
    )
    if not legal:
        game.log.append(f"{card.name}: no card in that hand can be chosen")
        return True, "resolved"
    # "…choose **X** cards from it" (Mind Warp). Capped at what the hand holds:
    # CR 608.2 does as much as it can, and a prompt asking for a card that is
    # not there would never be answerable.
    wanted = min(
        resolve_amount(instruction.payload.get("count", 1), context.x_value),
        len(legal),
    )
    if wanted <= 0:
        game.log.append(f"{card.name}: no cards are chosen")
        return True, "resolved"
    game.arm_pending_choice(
        "revealed_hand_pick", caster_index,
        card_name=card.name,
        victim_index=victim_index,
        legal_indices=legal,
        remaining=wanted,
        # "…choose **up to** X cards from it" (Discordant Dirge). CR 601.2c's
        # ceiling, which is what lets the chooser stop before the number is
        # reached. Carried onto every prompt of the chain by
        # ``_rearm_revealed_hand_pick`` — the picks after the first are the same
        # printed choice, so the permission has to survive each answer.
        up_to=bool(instruction.payload.get("up_to")),
        # Carried so the picks after the first can recompute what is legal
        # against the hand as it then stands.
        exclude_types=exclude_types,
        exclude_basic_lands=narrowing["exclude_basic_lands"],
        card_types=card_types,
        exclude_supertypes=excluded_supertypes,
        fate=str(instruction.payload.get("fate", "discard")),
        # The resolution's own scratchpad. Every pick writes the chosen card's
        # name into it — the pick *is* a chosen card, whatever becomes of it —
        # so a later sentence naming "the chosen card" (Lobotomy's search) has
        # one place to read it from, and ``lowering/_records`` can declare the
        # record for the kind rather than for one of its fates.
        record=context.results,
        # "…until **this creature** leaves the battlefield" (Kitesail
        # Freebooter): the source holds the exiled card, so which permanent it
        # is has to reach the answer. By id, because the prompt outlives the
        # resolution that armed it.
        source_id=(
            context.source_permanent.permanent_id
            if context.source_permanent is not None else None
        ),
    )
    return True, "resolved"


@effect_handler("exile_target_graveyard")
def exile_target_graveyard(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile target player's graveyard." (Tormod's Crypt.)

    The whole zone at once. A graveyard is its owner's (CR 404.1) and so is the
    exile zone, so every card goes from one to the other with no CR 400.3
    ownership lookup — and the list is emptied rather than filtered, because the
    card names no restriction.
    """
    # "Exile **all graveyards**." (Bazaar of Wonders.) Every pile, named by
    # nobody — which is why the payload key is what selects the sweep rather
    # than a sentinel seat: this sentence chooses no target (CR 115.1), and a
    # seat here would be one.
    victims = (
        list(game.players) if instruction.payload.get("every")
        else [context.target if context.target is not None else context.caster]
    )
    for victim in victims:
        exiled = list(victim.graveyard)
        victim.graveyard.clear()
        victim.exile.extend(exiled)
        game.log.append(
            f"{context.card.name} exiled {victim.name}'s graveyard "
            f"({len(exiled)} card(s))"
        )
    return True, "resolved"


@effect_handler("exile_graveyard_position")
def exile_graveyard_position(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile the bottom card of target player's graveyard." (Phyrexian
    Furnace.) The same handler runs the price of Barrow Ghoul's and Circling
    Vultures' "unless you exile the top creature card of your graveyard",
    which the board family decomposes into a ``May`` around this instruction.

    Which cards is ``graveyard_order.positions_named`` — the one scan, shared
    with the activation-cost payment path, so a phrase read as a cost and the
    same phrase read as an effect cannot name different cards. It answers with
    *indices* rather than cards because two copies of one card in one graveyard
    are the same Python object, and an identity filter over the list would take
    both.

    A pile with nothing the phrase names exiles nothing and still resolves:
    CR 608.2 finishes what it can, and an effect is not a cost. The **cost**
    reading of the same phrase refuses instead, which is CR 118.3 and lives at
    the payment site.
    """
    from ..graveyard_order import positions_named

    owner = instruction.payload.get("owner", "you")
    victim = (
        context.caster if owner == "you"
        else (context.target if context.target is not None else context.caster)
    )
    taken = positions_named(victim.graveyard, dict(instruction.payload))
    exiled = [victim.graveyard[index] for index in taken]
    # Highest index first: the positions were found against the pile as it
    # stands, and removing a lower one renumbers every position above it.
    for index in sorted(taken, reverse=True):
        del victim.graveyard[index]
    # A graveyard is its owner's and so is the exile zone (CR 404.1, CR 406.1),
    # so the cards go from one to the other with no CR 400.3 lookup.
    victim.exile.extend(exiled)
    if exiled:
        game.log.append(
            f"{context.card.name} exiled "
            + ", ".join(card.name for card in exiled)
            + f" from the {instruction.payload.get('position', 'top')} of "
            f"{victim.name}'s graveyard"
        )
    else:
        game.log.append(
            f"{victim.name}'s graveyard has nothing {context.card.name} can exile"
        )
    context.results["exiled_cards"] = exiled
    return True, "resolved"


@effect_handler("reanimate_graveyard_position")
def reanimate_graveyard_position(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put the top creature card of defending player's graveyard onto the
    battlefield **under your control**." (Bone Dancer.)

    Which card is ``graveyard_order.positions_named`` — the one scan, shared
    with ``exile_graveyard_position`` above and with the activation-cost payment
    path, so a printed position read as a cost and the same position read as an
    effect cannot name different cards. It answers with an **index** rather than
    a card because two copies of one card in one graveyard are the same Python
    object, and an identity filter over the pile would take both.

    Whose pile is CR 506.2's defending player, frozen into the trigger's context
    by the combat fire site rather than read off the board — the same key
    ``exile_cards_from_graveyard`` reads, and for its reason: this resolves in a
    priority window after the declaration, and an attacker removed from combat
    in between would leave a board read naming nobody.

    Whose **battlefield** is the ability's controller, which is the whole of the
    card: CR 404.1 puts the card in its owner's graveyard, so the default
    arrival (CR 400.3) would hand the creature back to the player being
    attacked.

    An empty pile reanimates nothing and still resolves (CR 608.2 finishes what
    it can) — and returns False from the ``may`` it sits inside, which is what
    keeps "If you do, this creature assigns no combat damage this turn" from
    firing on a turn where nothing came back.
    """
    from ..graveyard_order import positions_named

    if instruction.payload.get("graveyard_owner") != "defending_player":
        game.log.append(f"{context.card.name}: no graveyard named")
        return True, "resolved"
    seat = (context.trigger_context or {}).get("trigger_defending_player_index")
    if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
        game.log.append(
            f"{context.card.name}: no defending player was recorded"
        )
        return True, "no graveyard"
    victim = game.players[seat]
    taken = positions_named(victim.graveyard, dict(instruction.payload))
    if not taken:
        game.log.append(
            f"{victim.name}'s graveyard has nothing {context.card.name} can "
            f"return"
        )
        return True, "no card"
    caster_index = game.players.index(context.caster)
    moved = []
    # Highest index first: the positions were found against the pile as it
    # stands, and removing a lower one renumbers every position above it.
    for index in sorted(taken, reverse=True):
        moved.append(victim.graveyard.pop(index))
    for card in moved:
        game._put_permanent_onto_battlefield(
            caster_index, Permanent(card=card), None, from_zone="graveyard"
        )
        game.log.append(
            f"{context.card.name} returned {card.name} from {victim.name}'s "
            f"graveyard under {context.caster.name}'s control"
        )
    return True, "resolved"


@effect_handler("exile_cost_sacrifices")
def exile_cost_sacrifices(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…, then exile this artifact and those creature cards." (Sword of the
    Ages.)

    Everything the ability's own cost sacrificed, taken out of the graveyard the
    sacrifice put it in. CR 601.2h paid that cost before the ability reached the
    stack, so there is no battlefield step here and no permanent to move — each
    is a *card* now (CR 400.7), found in its **owner's** graveyard, which is not
    always the seat that controlled it.

    Each card is matched by object identity, never by name: two copies of the
    same creature in one graveyard are two cards, and exiling "a Grizzly Bears"
    would be free to take the wrong one.

    A cost that ate nothing but the source exiles just the source, which is what
    "any number of creatures" and none of them means.
    """
    cards = [
        permanent.card
        for permanent in ((context.choices or {}).get("sacrificed_set_for_cost") or ())
    ]
    source = context.source_permanent
    if source is not None:
        cards.append(source.card)
    exiled: list[str] = []
    for card in cards:
        for player in game.players:
            index = next(
                (i for i, held in enumerate(player.graveyard) if held is card), None
            )
            if index is not None:
                player.exile.append(player.graveyard.pop(index))
                exiled.append(card.name)
                break
    game.log.append(
        f"{context.card.name} exiled {', '.join(exiled)}"
        if exiled
        else f"{context.card.name}: nothing it sacrificed is still in a graveyard"
    )
    return True, "resolved"


@effect_handler("move_random_graveyard_card")
def move_random_graveyard_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Reorder your graveyard at random. An opponent chooses a card at random
    in your graveyard. If it's a creature card, put it onto the battlefield.
    Otherwise, exile it." (Search for Survivors.)

    The graveyard is an ordered pile here (CR 404.1's top card is read by
    other cards), so the reorder is performed, not skipped. A pick "at random"
    is nobody's decision, so no prompt is armed; it needs an opponent to make
    it, and with none left nothing is chosen. The module RNG, which
    ``run_ai_simulation`` seeds, so a seed replays the run.
    """
    caster = context.caster
    caster_index = game.players.index(caster)
    payload = instruction.payload
    pile = caster.graveyard
    if payload.get("shuffle_first"):
        random.shuffle(pile)
    if not pile or not list(game.opponents_of(caster_index)):
        game.log.append(f"{context.card.name}: no card was chosen")
        return True, "resolved"
    card = pile.pop(random.randrange(len(pile)))
    if card_has_type(card, str(payload.get("card_type") or "creature")):
        game._put_permanent_onto_battlefield(
            caster_index, Permanent(card=card), None, from_zone="graveyard"
        )
        game.log.append(f"{context.card.name} put {card.name} onto the battlefield")
    else:
        caster.exile.append(card)
        game.log.append(f"{context.card.name} exiled {card.name}")
    return True, "resolved"


@effect_handler("exile_target_graveyard_card")
def exile_target_graveyard_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile target card from a graveyard." (Return to Nature's third mode,
    which used to resolve having done nothing.)

    No permanent is involved, so none of the battlefield machinery applies: the
    card is popped out of the graveyard it is in and appended to that same
    player's exile — a graveyard is an owner's zone (CR 404.1), so CR 400.3
    needs no separate lookup.
    """
    card = context.card
    owner = context.target if context.target is not None else context.caster
    # **Last-known information is frozen at the fire site** (CR 608.2h, ROADMAP
    # idiom #6). "If it was a creature card" is asked after the card has left
    # the graveyard, so the answer is recorded here, as the card is taken, not
    # re-read from the exile pile at the next step — where another effect's
    # exile would answer for this one.
    context.results["exiled_cards"] = []
    index = context.target_permanent_index
    if not (isinstance(index, int) and 0 <= index < len(owner.graveyard)):
        # Honour the choice, else take the first legal one — the same fallback
        # pick_target_permanent uses, so a stale choice does not fizzle an
        # effect the rest of the engine is not written to fizzle.
        owner = next((player for player in game.players if player.graveyard), owner)
        index = 0 if owner.graveyard else None
    if index is None:
        game.log.append(f"{card.name}: no card in any graveyard to exile")
        return True, "resolved"
    exiled = owner.graveyard.pop(index)
    owner.exile.append(exiled)
    context.results["exiled_cards"] = [exiled]
    game.log.append(f"{card.name} exiled {exiled.name} from {owner.name}'s graveyard")
    return True, "resolved"


@effect_handler("exile_graveyard_cards")
def exile_graveyard_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile all creature cards from your graveyard." (Zombie Mob.)

    The sweep the battlefield one beside it cannot be: CR 613.1 gives a card in
    a graveyard no computed characteristics at all, so what the noun phrase
    narrows by is answered by the *card* matcher — the same reader a discard
    cost and a graveyard target already share.

    Nothing is chosen and nothing is ordered: exile is an unordered zone
    (CR 406.2 orders no zone but the library and the graveyard), and "all" names
    the whole matching set. The pile is read once into a list before anything
    moves, because removing from a list while iterating it skips entries — and
    a graveyard holds several copies of a popular card under one name, so the
    survivors are rebuilt by *slot* rather than by value (idiom 11).
    """
    payload = instruction.payload
    who = str(payload.get("graveyard_owner") or "")
    if who == "each_player":
        seats = list(range(len(game.players)))
    elif who == "you":
        seats = [game.players.index(context.caster)]
    else:
        game.log.append(f"{context.card.name}: no graveyard named")
        return True, "resolved"
    described = dict(payload.get("filter") or {})
    # One entry per seat, **including the empty ones**, and seeded before
    # anything moves. The sentence behind this one is read once per player
    # ("puts all cards *they* exiled this way onto the battlefield"), so a seat
    # the map never mentioned would fall through to whatever a `.get` default
    # is — and the honest default for "what did this player exile" is an empty
    # pile, not somebody else's.
    by_seat = context.results.setdefault(EXILED_BY_SEAT, {})
    for seat in seats:
        by_seat.setdefault(seat, [])
    # The flat pair beside the per-seat map, seeded before anything moves for
    # the same reason: "you gain 1 life **for each card exiled this way**"
    # (Honor the Fallen) is a later step of this same resolution, and a sweep
    # that emptied every pile of nothing has to answer it with a zero rather
    # than with whatever a `.get` default is. Three records, three questions —
    # whose, how many, which — and the map cannot answer the last two without a
    # reader that knows its shape.
    all_taken: list = []
    context.results[EXILED_THIS_WAY_OBJECTS] = all_taken
    context.results[EXILED_THIS_WAY] = 0
    exiled = 0
    for seat in seats:
        owner = game.players[seat]
        taken_slots = [
            index for index, card in enumerate(owner.graveyard)
            if _card_matches_filter(card, described, game=game, owner=owner)
        ]
        if not taken_slots:
            continue
        taken = [owner.graveyard[index] for index in taken_slots]
        kept = [
            card for index, card in enumerate(owner.graveyard)
            if index not in set(taken_slots)
        ]
        owner.graveyard[:] = kept
        owner.exile.extend(taken)
        by_seat[seat].extend(taken)
        all_taken.extend(taken)
        exiled += len(taken)
        game.log.append(
            f"{context.card.name} exiled {len(taken)} card(s) from "
            f"{owner.name}'s graveyard"
        )
    context.results[EXILED_THIS_WAY] = exiled
    if not exiled:
        game.log.append(f"{context.card.name}: no card in that graveyard to exile")
    return True, "resolved"


@effect_handler("put_exiled_this_way")
def put_exiled_this_way(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each player … puts all cards **they** exiled this way onto the
    battlefield." (Living Death.)

    The per-seat pile an earlier step of this same resolution recorded, given
    back one seat at a time. Every card enters under the control of the player
    who put it there (CR 110.2a) — which is what the printed subject says and
    what makes this a mass reanimation rather than a theft.

    Read out of ``EXILED_BY_SEAT`` and not off the exile zone: a player's exile
    holds cards this effect never touched, and CR 400.7's "no memory of its
    previous existence" is exactly why the pile has to be the record rather
    than a re-scan. It is also why the entries are consumed **positionally** —
    two copies of one card in a graveyard are the same ``CardDefinition``
    object, so a match by value would take the same card twice and leave the
    other in exile.

    A card that is no longer in that seat's exile by the time this runs is
    skipped and said so: something else moved it, and CR 608.2 does as much of
    the instruction as it can.
    """
    payload = instruction.payload
    zone = str(payload.get("zone") or "battlefield")
    if zone not in ("battlefield", "hand"):
        game.log.append(f"{context.card.name}: no handler puts a pile in the {zone}")
        return True, "resolved"
    who = str(payload.get("who", "you"))
    by_seat = dict(context.results.get(EXILED_BY_SEAT) or {})
    if who == "each_player":
        seats = list(range(len(game.players)))
    else:
        seats = [game.players.index(context.caster)]
    described = dict(payload.get("filter") or {})
    returned = 0
    for seat in seats:
        player = game.players[seat]
        for card in list(by_seat.get(seat) or ()):
            if described and not _card_matches_filter(
                card, described, game=game, owner=player
            ):
                continue
            if not game.take_card_from_exile(player, card):
                game.log.append(
                    f"{context.card.name}: {card.name} is no longer exiled"
                )
                continue
            if zone == "hand":
                # "…returns to **their** hand each card they exiled this way."
                # (Memory Jar.) The pile's own owner's hand, which is the seat
                # this loop is already on — a hand is somebody's zone
                # (CR 402.1) where a battlefield is nobody's, and the lowering
                # refused any third party's. Through ``put_card_into_hand``
                # rather than an append, because CR 903.9b has no single fire
                # site and this is one more of the places that would forget it.
                game.put_card_into_hand(player, card)
                game.log.append(
                    f"{player.name} returned {card.name} from exile to their hand"
                )
                returned += 1
                continue
            game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
            game.log.append(
                f"{player.name} put {card.name} onto the battlefield from exile"
            )
            returned += 1
    if not returned:
        game.log.append(f"{context.card.name}: no exiled cards to put back")
    return True, "resolved"


@effect_handler("exile_cards_from_graveyard")
def exile_cards_from_graveyard(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…exile up to two target creature cards from defending player's
    graveyard." (Rysorian Badger.)

    The counted twin of ``exile_target_graveyard_card``, and a *prompt* rather
    than an announced list of targets: no picker in this engine names two cards
    in one graveyard, and a triggered ability's targets are chosen at
    resolution here (see the CR 608.2b entry in ROADMAP.md). The seat that
    would have announced them picks them instead, out of the same pile, as the
    ability resolves.

    Whose pile is the seat the *combat* named (CR 506.2), frozen into the
    trigger's context by the declare-attackers fire site — the same key the
    defending player's discard reads. A seat nobody recorded is not a pile to
    exile from: the attacker can have left combat by the time this resolves,
    and picking some other graveyard would be a card doing what it never said.

    ``exiled_this_way`` is written by the *answer*, not here, which is why the
    choice spec suspends: "you gain 1 life for each card exiled this way" is a
    later step of this same resolution and would read a zero otherwise.
    """
    owner = str(instruction.payload.get("graveyard_owner") or "")
    caster_index = game.players.index(context.caster)
    # "…from **a single** graveyard" (Ebony Charm). The pile is not printed;
    # the chooser names it as the spell resolves, and only where there is a
    # choice to make. One pile with a legal card in it is not a decision, and
    # none at all is not a prompt — offering either would be a question with one
    # answer or with none, which the seat then has to dismiss.
    if owner == "chosen":
        piles = game.graveyard_piles_with_a_legal_card(dict(instruction.payload))
        if not piles:
            game.log.append(
                f"{context.card.name}: no graveyard holds a card it can exile"
            )
            context.results[EXILED_THIS_WAY_OBJECTS] = []
            context.results[EXILED_THIS_WAY] = 0
            return True, "resolved"
        if len(piles) == 1:
            game.arm_graveyard_exile_pick(
                caster_index, piles[0], dict(instruction.payload), context
            )
        else:
            game.arm_graveyard_pile_choice(
                caster_index, dict(instruction.payload), context
            )
        return True, "resolved"
    # "Exile **X target** creature cards from **your** graveyard." (Midnight
    # Ritual.) The one pile of the three whose seat is known when the spell goes
    # on the stack, so the cards are *announced* (CR 601.2c) rather than chosen
    # as it resolves — which is why this is the branch that resolves slots
    # instead of arming a prompt.
    #
    # Through ``_resolve_graveyard_slots``, the same reader the graveyard return
    # uses for Shattered Crypt's identical "X target … cards from your
    # graveyard": a graveyard slot is not an identity (two copies of one card in
    # one pile are literally one ``CardDefinition``), so what tells them apart is
    # the order of removal, and a second copy of that reasoning here is how one
    # of the two ends up popping the wrong card.
    #
    # A count of zero is a legal outcome, not a reason to guess: X may be 0, and
    # CR 608.2b says an announcement naming nothing exiles nothing.
    #
    # "…you may exile **a land card from your graveyard**" (Forgotten Harvest)
    # prints no "target", so nothing was announced: the lowering emits no
    # ``targets`` description and the controller picks as it resolves, through
    # the same prompt the other two piles use.
    if owner == "you" and not instruction.payload.get("targets"):
        game.arm_graveyard_exile_pick(
            caster_index, caster_index, dict(instruction.payload), context
        )
        return True, "resolved"
    if owner == "you":
        count = instruction.payload.get("count")
        wanted = int(context.x_value or 0) if count == "x" else int(count or 1)
        taken = _resolve_graveyard_slots(
            context.caster, context, wanted,
            lambda card: graveyard_card_matches(instruction.payload, card),
        )
        context.caster.exile.extend(taken)
        context.results[EXILED_THIS_WAY_OBJECTS] = list(taken)
        context.results[EXILED_THIS_WAY] = len(taken)
        game.log.append(
            f"{context.card.name} exiled "
            + (", ".join(card.name for card in taken) or "nothing")
            + f" from {context.caster.name}'s graveyard"
        )
        return True, "resolved"
    if owner != "defending_player":
        game.log.append(f"{context.card.name}: no graveyard named")
        return True, "resolved"
    seat = (context.trigger_context or {}).get("trigger_defending_player_index")
    if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
        game.log.append(
            f"{context.card.name}: no defending player was recorded"
        )
        return True, "resolved"
    game.arm_graveyard_exile_pick(
        caster_index, seat, dict(instruction.payload), context
    )
    return True, "resolved"


@effect_handler("reveal_hand_while_source_present")
def reveal_hand_while_source_present(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Stromgald Spy: "…you may have defending player play with their hand
    revealed for as long as this creature remains on the battlefield."

    CR 701.20a: revealing shows the cards to every player, and the hand stays a
    hidden zone by classification (CR 400.2) — so nothing here moves a card, and
    the whole effect is a record the per-seat serialization reads.

    The record goes on the **source**, which is what implements the duration
    with no sweep: ``engine/revealed_hands.py`` scans the battlefield for it, a
    permanent that leaves stops being in the scan (CR 611.2b) and a returning
    one is a new object with no record (CR 400.7).

    The seat is CR 506.2's defender, frozen by the combat fire site rather than
    read off the board: this resolves in a priority window after the
    declaration, and an attacker that left combat in between would leave a board
    read naming nobody.
    """
    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    seat = (context.trigger_context or {}).get("trigger_defending_player_index")
    if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
        game.log.append(f"{context.card.name}: no defending player was recorded")
        return True, "resolved"
    reveal_hand_while_present(source, seat)
    game.log.append(
        f"{context.card.name}: {game.players[seat].name} plays with their hand "
        f"revealed while {source.card.name} remains on the battlefield"
    )
    return True, "resolved"


@effect_handler("phase_out_target_creature_until_source_leaves")
def phase_out_target_creature_until_source_leaves(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    target_perm = resolve_target_permanent(game, context, predicate=lambda p: p.is_creature)
    if target_perm is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    owner_index = game.controller_index_of(target_perm)
    if owner_index is None:
        return True, "resolved"
    # By identity throughout: ``list.remove`` compares by value, and Permanent is
    # a dataclass with generated __eq__, so it takes the first *equal* permanent
    # — an opponent's identically-stated copy of the same card — rather than the
    # one that was chosen.
    owner_player = game.players[owner_index]
    game.remove_from_battlefield(target_perm)
    # Auras/Equipment attached to the phased creature phase out with it (CR 702.26h).
    attachments: list[tuple[int, Permanent]] = []
    for seat, player in enumerate(game.players):
        leaving = [
            perm for perm in game.controlled_by(seat)
            if perm.metadata.get("attached_to") is target_perm
        ]
        if leaving:
            game.remove_all_from_battlefield(leaving)
            attachments.extend((seat, perm) for perm in leaving)
    source_permanent.metadata["phased_out_permanent"] = target_perm
    source_permanent.metadata["phased_out_owner_index"] = owner_index
    source_permanent.metadata["phased_out_attachments"] = attachments
    game.log.append(f"{card.name} phases {target_perm.card.name} out")
    return True, "resolved"


@effect_handler("exile_creature_gain_life_equal_to_power")
def exile_creature_gain_life_equal_to_power(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    # Swords to Plowshares: exile target creature; its controller gains life = its power
    target_perm_idx = context.target_permanent_index
    exiled_perm: Permanent | None = None
    if isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(target.battlefield):
        candidate = target.battlefield[target_perm_idx]
        if candidate.is_creature:
            exiled_perm = candidate
            game.remove_from_battlefield(candidate)
    if exiled_perm is None:
        for perm in list(game.controlled_by(target)):
            if perm.is_creature:
                exiled_perm = perm
                game.remove_from_battlefield(perm)
                break
    if exiled_perm is not None:
        target.exile.append(exiled_perm.card)
        life_gain = exiled_perm.effective_power
        game.log.append(f"{exiled_perm.card.name} exiled by {card.name}")
        game._gain_life(target, life_gain, card.name)
    else:
        game.log.append(f"{card.name}: no valid creature to exile")
    return True, "resolved"


@effect_handler("peek_hand_and_force_play")
def peek_hand_and_force_play(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Word of Command: the caster looks at the target's hand and chooses a card
    for that player to play. Arms a pending choice resolved by
    confirm_word_of_command (which plays the chosen card as the target). Also
    surfaces the revealed hand so the UI can show it to the caster."""
    target = context.target
    caster = context.caster
    card = context.card
    if not target.hand:
        game.log.append(f"{card.name}: {target.name} has no cards to play")
        return True, "resolved"
    caster_index = game.players.index(caster)
    target_index = game.players.index(target)
    game.arm_pending_choice(
        "word_of_command", caster_index,
        target_index=target_index, card_name=card.name,
        hand=[c.name for c in target.hand],
    )
    game.log.append(f"{card.name}: {caster.name} looks at {target.name}'s hand to choose a card to force")
    return True, "resolved"


@effect_handler("look_at_target_hand")
def look_at_target_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    viewer = context.caster
    card = context.card
    # ``who: "defending_player"`` names CR 506.2's seat, frozen into the
    # trigger's context by the combat fire site (Port Inspector) — nobody
    # targeted it, so ``context.target`` for this trigger is whatever the
    # resolution was already carrying, which on a becomes-blocked trigger is the
    # *blocker*'s controller by coincidence and the viewer's own seat as soon as
    # the coincidence stops holding. The same key the two discards beside this
    # handler read for the same printed phrase.
    if instruction.payload.get("who") == "defending_player":
        seat = (context.trigger_context or {}).get("trigger_defending_player_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            # The attacker can leave combat before this resolves, and a seat
            # nobody recorded is not a hand to show.
            return True, "resolved"
        target = game.players[seat]
    # Record the reveal so the UI can show the viewer the actual cards in the
    # target player's hand (Glasses of Urza). The viewer is the ability's
    # controller; the target is the player whose hand is looked at.
    viewer_index = game.players.index(viewer)
    # Only the most recent reveal is shown, so a second look replaces the first
    # rather than queueing behind it.
    game.clear_pending_choices("hand_reveal", viewer_index)
    # "…**a card at random** in target player's hand" (Urza's Bauble): one card,
    # picked by nobody. Through the module RNG the rest of the engine seeds, so
    # a given seed replays the look exactly. An empty hand shows nothing rather
    # than failing — CR 608.2 does as much as it can.
    if instruction.payload.get("random_card"):
        shown = (
            [random.choice(target.hand).name] if target.hand else []
        )
    else:
        shown = [c.name for c in target.hand]
    game.arm_pending_choice(
        "hand_reveal", viewer_index,
        target_index=game.players.index(target),
        card_names=shown,
    )
    game.log.append(
        f"{card.name}: {viewer.name} looked at "
        + (
            f"{len(shown)} card(s) at random in {target.name}'s hand"
            if instruction.payload.get("random_card")
            else f"{target.name}'s hand ({len(shown)} cards)"
        )
    )
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
        milled = 0
        for _ in range(amount):
            if not victim.library:
                break
            card = victim.library.pop(0)
            game.put_card_into_graveyard(victim, card, from_zone="library")
            put_there.append(card)
            milled += 1
        game.log.append(f"{victim.name} milled {milled} card(s)")
    return True, "resolved"


@effect_handler("exile_graveyard_arrivals_this_turn")
def exile_graveyard_arrivals_this_turn(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"If a card would be put into your graveyard from anywhere this turn,
    exile that card instead." (Yawgmoth's Will.)

    CR 614 for a window. The marker goes on the seat and the interceptor in
    ``engine/replacements.py`` reads it — the arrangement Disintegrate's
    "if it would die this turn" already has on a permanent, one object wider —
    because a sorcery is on no battlefield when the replacement is meant to
    apply, and the static reading of the same sentence works by scanning
    battlefields for the text.

    The seat is the spell's controller: "your graveyard" is CR 109.5's, and the
    lowering refuses every other printed scope rather than arming a record whose
    seat the interceptor could not answer.

    Swept with the rest of the turn (``turn_management``'s cleanup loop), which
    is CR 514.2 and the same place every other "this turn" record forgets.
    """
    context.caster.exile_cards_bound_for_graveyard_this_turn = True
    game.log.append(
        f"{context.caster.name}'s cards will be exiled instead of going to "
        "their graveyard this turn"
    )
    return True, "resolved"


@effect_handler("choose_target_cards")
def choose_target_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose two target creature cards in your graveyard." (Victimize.)

    The announcement, and nothing else: CR 601.2c chose the cards as the spell
    was cast, and this sentence prints no effect. It exists so
    ``engine/targeting.py`` can derive the picker from the compiled program,
    which is where every other card's comes from — the same job
    ``choose_target_permanent`` does one zone over.

    Nothing is *recorded* either, and that is the difference from the plural
    permanent choice: the announced slots ride the stack item for the whole
    resolution, so the sentence behind this reads the same list this picker
    filled. A record would be a second copy of it, free to disagree the moment
    an earlier step moved a card in the pile.

    Nothing leaves the graveyard here. "Sacrifice a creature. **If you do**,
    return the chosen cards" is a price that may not be paid, and cards taken
    out now would be cards in no zone at all.
    """
    game.log.append(f"{context.card.name}: cards chosen from the graveyard")
    return True, "resolved"


@effect_handler("reanimate_announced_cards")
def reanimate_announced_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…return **the chosen cards** to the battlefield tapped." (Victimize.)

    The cards an earlier sentence of this same spell announced (CR 601.2c),
    read off the resolution's own target list rather than out of a record —
    ``choose_target_cards`` says why.

    Through ``_resolve_graveyard_slots``, the one reader of a list of graveyard
    slots: a card in a pile has no ``permanent_id`` and two copies of one card
    there are the same ``CardDefinition``, so only the order of removal can tell
    two slots apart. A slot whose card has left, or that names a card the
    printed phrase does not (CR 608.2b), is dropped and the rest still happen.

    Under the spell's controller (CR 110.2a), which is the seat whose graveyard
    the phrase named.
    """
    caster = context.caster
    tapped = bool(instruction.payload.get("tapped"))
    seat = game.players.index(caster)

    def _eligible(card) -> bool:
        # The picker's own predicate, asked here so the resolution and the
        # announcement cannot disagree about which cards were legal.
        return graveyard_card_matches(instruction.payload, card)

    picked = _resolve_graveyard_slots(caster, context, len(caster.graveyard), _eligible)
    for card in picked:
        permanent = Permanent(card=card)
        if tapped:
            permanent.tapped = True
        game._put_permanent_onto_battlefield(seat, permanent, None)
        game.log.append(
            f"{caster.name} returned {card.name} to the battlefield from the graveyard"
        )
    if not picked:
        game.log.append(f"{context.card.name}: no announced card to return")
    return True, "resolved"


@effect_handler("each_player_takes_from_graveyard")
def each_player_takes_from_graveyard(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each player puts a creature card from their graveyard onto the
    battlefield." (Exhume.) "…each player … returns up to three cards from
    their graveyard to their hand." (Ill-Gotten Gains.)

    One pick per seat, out of that seat's own graveyard and into that seat's own
    zone — which is why it arms a prompt per player rather than resolving a
    target: nothing is announced (CR 115.1), there is nothing for targeting to
    protect in a public zone, and the seat that chooses is not the seat that
    cast the spell. The same ``search_library`` prompt Reincarnation's graveyard
    pick already uses, with the two seats named on it, so one picker, one AI
    policy and one re-check serve every reading of "a card from a graveyard".

    How many, whether fewer is a legal answer and where they land are payload,
    because the two cards differ in nothing else: both empty a pile into a zone
    one seat at a time, and a second kind would be a second copy of arming this
    prompt.

    Offered in CR 101.4's order — the active player first — and only to a seat
    whose graveyard actually holds a card the phrase names: a prompt over a pile
    with nothing in it is a decision with one answer, and arming it would stop
    the game to ask it (``ChoiceSpec.holds_priority``). A seat that cannot takes
    nothing, which is CR 608.2's "as much as possible".
    """
    card_type = str(instruction.payload.get("card_type", "any"))
    destination = str(instruction.payload.get("destination", "battlefield"))
    count = max(1, int(instruction.payload.get("count", 1)))
    up_to = bool(instruction.payload.get("up_to"))
    total = len(game.players)
    active = game.active_player_index or 0
    seats = sorted(
        (i for i, p in enumerate(game.players) if not p.lost),
        key=lambda i: ((i - active) % total, i),
    )
    armed = 0
    for seat in seats:
        player = game.players[seat]
        available = sum(
            1 for card in player.graveyard
            if card_type == "any" or card_has_type(card, card_type)
        )
        if not available:
            game.log.append(f"{player.name} has no {card_type} card to take")
            continue
        # The printed ceiling, capped by the pile: a counted search is driven by
        # one entry per find, and a slot with nothing that could fill it is a
        # find the seat can never make.
        slots = min(count, available)
        game.arm_pending_choice(
            "search_library", seat,
            zone_seat=seat,
            battlefield_seat=seat,
            count=slots,
            card_type=card_type,
            zones=("graveyard",),
            restrictions={},
            destination=destination,
            destinations=[destination] * slots if slots > 1 else [],
            tapped=[],
            card_name=context.card.name if context.card is not None else "",
            enters_tapped=False,
            untap_found_if=None,
            up_to=up_to,
            exile_rest=False,
            reveal=False,
            record=context.results,
            record_key=None,
        )
        armed += 1
    if not armed:
        game.log.append(f"{context.card.name}: no graveyard holds one")
    return True, "resolved"


@effect_handler("separate_library_top_into_piles")
def separate_library_top_into_piles(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Phyrexian Portal, all three of its sentences.

    Three decisions by two seats, so the handler does nothing but hand the
    first of them to the right player: the opponent divides, knowing what is in
    the piles, and the controller chooses and searches without knowing. Each
    later decision is armed by answering the one before it, which keeps the
    whole procedure inside one resolution (CR 608.2, CR 117.3b).

    The ten cards come **out of the library** here and travel on the prompts.
    They are going to exile, to a hand and back into a shuffled library, so
    there is no arrangement of the library that could hold them meanwhile - and
    the alternative, leaving them in place and addressing them by index, is an
    index into a zone the next answer changes.
    """
    caster = context.caster
    splitter = context.target
    if splitter is None or splitter is caster:
        # "Target **opponent**" - the picker enforces it, and a resolution that
        # somehow arrived without one divides nothing rather than handing the
        # caster their own library face down.
        game.log.append(f"{context.card.name}: no opponent to divide the piles")
        return True, "resolved"
    count = resolve_amount(instruction.payload.get("count", 0), context.x_value)
    taken = caster.library[:count]
    if not taken:
        game.log.append(f"{caster.name} has no cards to divide")
        return True, "resolved"
    del caster.library[:count]
    game.arm_pending_choice(
        "library_pile_split", game.players.index(splitter),
        card_name=context.card.name if context.card is not None else "",
        owner_index=game.players.index(caster),
        _cards=list(taken),
        _source_permanent=context.source_permanent,
    )
    return True, "resolved"


@effect_handler("look_top_cycle_and_stack")
def look_top_cycle_and_stack(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Lim-Dul's Vault, all three of its sentences (CR 701.24).

    The whole effect is one offer asked over and over, so the handler does
    almost nothing: it announces the first look and arms the offer. Every
    iteration after that is a prompt armed by *answering* the one before it,
    which is how a chain of decisions stays inside one resolution (CR 608.2,
    CR 117.3b) - the ability stays on the stack until the last answer, and the
    shuffle that ends the card happens on the answer that declines.

    Nothing is moved here. "Look at the top five cards" changes no zone; what
    it changes is what one player knows, and the cards it names are simply the
    top of the library at the moment each offer is answered.
    """
    caster = context.caster
    seat = game.players.index(caster)
    count = resolve_amount(instruction.payload.get("count", 0), context.x_value)
    life_cost = resolve_amount(instruction.payload.get("life_cost", 0), context.x_value)
    looked = min(count, len(caster.library))
    game.log.append(
        f"{caster.name} looks at the top {looked} card(s) of their library"
    )
    game.arm_pending_choice(
        "library_cycle_offer", seat,
        card_name=context.card.name if context.card is not None else "",
        count=int(count),
        life_cost=int(life_cost),
    )
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


@effect_handler("look_at_library_top_then_bottom")
def look_at_library_top_then_bottom(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Look at the top card of defending player's library. You may put that
    card on the bottom of that player's library." (Coral Fighters.)

    The same decision a scry is — look at the top N and choose which of them go
    to the bottom — over somebody else's pile, so it arms the same prompt with
    ``library_index`` naming whose library it is. Not *called* a scry: the card
    prints no keyword (CR 701.22 arrived long after Mirage) and the pile is not
    the chooser's, and the instruction says what the sentence says.

    Modelled as a choice for the scry handler's stated reason: leaving the card
    on top is a legal outcome and never a legal implementation, because the
    decision is the whole effect.

    Whose library is CR 506.2's defending player, read off what the combat fire
    site froze — the same key ``discard_target_cards`` reads for the seat its
    own untargeted sentence names. No record means the attacker left combat
    before this resolved, and a seat nobody wrote down is not a library to look
    through.
    """
    caster = context.caster
    seat = None
    if instruction.payload.get("who") == "defending_player":
        recorded = (context.trigger_context or {}).get("trigger_defending_player_index")
        seat = recorded if isinstance(recorded, int) else None
    elif context.target is not None:
        seat = game.players.index(context.target)
    if seat is None or not (0 <= seat < len(game.players)):
        game.log.append(f"{context.card.name}: no recorded player, no library to look at")
        return True, "resolved"
    owner = game.players[seat]
    amount = resolve_amount(instruction.payload.get("amount", 1) or 1, context.x_value)
    top_count = min(amount, len(owner.library))
    if top_count <= 0:
        game.log.append(f"{context.card.name}: {owner.name}'s library is empty")
        return True, "resolved"
    game.arm_pending_choice(
        "scry", game.players.index(caster),
        top_count=top_count, amount=amount, card_name=context.card.name,
        library_index=seat,
    )
    game.log.append(
        f"{caster.name} is looking at the top {top_count} of {owner.name}'s library"
    )
    return True, "pending_scry"


@effect_handler("return_all_owned_artifacts_to_hand")
def return_all_owned_artifacts_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Hurkyl's Recall: "Return all artifacts target player owns to their hand."

    Owns, not controls. An artifact the target player owns but an opponent has
    stolen still returns, and to the *owner's* hand (CR 400.3) — which is why
    this asks ``owner_index_of`` rather than reading the battlefield it happens
    to be sitting on.
    """
    owner_index = game.players.index(context.target)
    returned = 0
    for player in game.players:
        for permanent in list(player.battlefield):
            if not permanent.has_type("artifact"):
                continue
            if game.owner_index_of(permanent) != owner_index:
                continue
            # Identity, not value: two untapped Moxen of the same name are ``==``.
            game.remove_from_battlefield(permanent)
            game.put_card_into_hand(
                owner_index, permanent.card, from_battlefield=permanent
            )
            game._remove_aura_effects(permanent)
            returned += 1
    game.log.append(f"Returned {returned} artifact(s) to {context.target.name}'s hand")
    return True, "resolved"


# ---------------------------------------------------------------------------
# Planeswalker-block zone movers (M21 loyalty abilities)
# ---------------------------------------------------------------------------


@effect_handler("phase_out_target")
def phase_out_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature you don't control phases out." (Teferi, Master of
    Time's −3.) CR 702.26: not a zone change — the machinery is
    Game.phase_out_permanent, and the object returns at its controller's next
    untap step.

    **Not "creature" — whatever the printed noun phrase said.** The predicate
    used to be the resolver's default, ``is_creature``, and Reality Ripple
    ("Target **artifact, creature, or land** phases out") compiled supported,
    offered all three to the picker and then silently did nothing to two of
    them: the handler declined a target the engine had already accepted, logged
    "no valid target" and let the spell resolve. Asked through the same
    ``subject_matches`` the picker enumerated with — with the caster as observer
    (CR 109.5), so Teferi, Master of Time's "creature **you don't control**" is
    tested here too rather than only at announcement.
    """
    from ..subject_filters import subject_matches
    from ._common import block_pair_permanents

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = game.players.index(context.caster)
    # "Whenever this creature becomes blocked by a creature, put **that
    # creature** on top of its owner's library." (Elven Warhounds.) The
    # permanent is the one the block pair bound, not a chosen target — same
    # zone change, and the subject key is the only thing that differs, which is
    # why it is a payload here rather than a second handler.
    #
    # ``block_pair_permanents`` rather than the stack item's target, because the
    # two halves of the pair are frozen differently and reading the target on
    # the *blocks* half names the source itself.
    if instruction.payload.get("subject") == "block_pair":
        bound = block_pair_permanents(game, context)
        if not bound:
            game.log.append(f"{context.card.name}: the blocking creature has left")
            return True, "resolved"
        target_perm = bound[0]
    else:
        target_perm = resolve_target_permanent(
            game, context,
            predicate=lambda perm: subject_matches(
                game, perm, described, observer=observer,
                source=context.source_permanent,
            ),
        )
    if target_perm is None:
        game.log.append(f"{context.card.name}: no valid target")
        return True, "resolved"
    game.phase_out_permanent(target_perm)
    return True, "resolved"


@effect_handler("phase_out_recorded_permanents")
def phase_out_recorded_permanents(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…choose a land that player controls, then **the chosen permanents phase
    out**." (Equipoise, CR 702.26.)

    The set an earlier step of this same resolution recorded, read through
    ``recorded_permanent_ids`` — the one reader of the ``permanents_from``
    channel, so this cannot disagree with the twenty other steps that write it
    about whether a record is one id or a list.

    **Anything no longer on the battlefield is skipped**, and that is the
    printed reading rather than a guard against the impossible. Equipoise runs
    its process three times into one record, so the third round's sentence names
    the first two rounds' picks as well — and a phased-out permanent is treated
    as though it does not exist (CR 702.26b), which is exactly a permanent this
    step cannot phase out. Reading the record without the check would push the
    same permanent onto its controller's phased-out pile twice and phase it back
    in as two objects.
    """
    from ._common import recorded_permanent_ids

    left = 0
    for permanent_id in recorded_permanent_ids(
        context, instruction.payload.get("permanents_from")
    ):
        perm = game.permanent_by_id(permanent_id)
        if perm is None or not game.is_on_battlefield(perm):
            continue
        game.phase_out_permanent(perm)
        left += 1
    game.log.append(f"{context.card.name}: {left} permanent(s) phased out")
    return True, "resolved"


@effect_handler("forbid_phase_out")
def forbid_phase_out(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Until your next upkeep, target permanent **can't phase out**."
    (Spatial Binding, CR 702.26.)

    The restriction beside ``phase_out_target``'s action, recorded on the chosen
    permanent by ``engine/phasing_locks.py`` — which is where the sweep that
    ends it is named, and which both phase-out paths ask.

    "**Your** next upkeep" is the ability's controller (CR 109.5), not the
    permanent's, so the seat is frozen here and compared at the sweep. Reading
    it off the target would let a Binding on an opponent's permanent expire on
    the wrong turn.

    The printed noun phrase is re-tested at resolution through the same
    ``subject_matches`` the picker enumerated with, which is Reality Ripple's
    lesson in this same file: a handler taking the resolver's default predicate
    declines targets the engine already accepted.
    """
    from ..phasing_locks import forbid_phase_out as record_lock
    from ..subject_filters import subject_matches

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = game.players.index(context.caster) if context.caster in game.players else None
    target_perm = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described, observer=observer,
            source=context.source_permanent,
        ),
    )
    if target_perm is None:
        game.log.append(f"{context.card.name}: no valid target")
        return True, "resolved"
    record_lock(
        target_perm,
        duration=str(instruction.payload.get("duration") or "end_of_turn"),
        seat=observer,
    )
    game.log.append(
        f"{target_perm.card.name} can't phase out ({context.card.name})"
    )
    return True, "resolved"


@effect_handler("phase_out_self")
def phase_out_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"This creature phases out." (Mist Dragon, Crystal Golem, Vaporous Djinn,
    Warping Wurm, Frenetic Efreet.)

    The ability's own source, which is a different question from a target: the
    sentence names nothing to pick, so there is nothing to describe and nothing
    to re-check at resolution. A source that has already left the battlefield
    phases out nothing, which is what ``phase_out_permanent`` reports by
    returning False (CR 702.26 acts on a permanent, and there is none).
    """
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: not on the battlefield to phase out")
        return True, "resolved"
    game.phase_out_permanent(source)
    return True, "resolved"


@effect_handler("phase_out_bound_permanent")
def phase_out_bound_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever a creature you control attacks, **it phases out at end of
    combat**." (Teferi's Veil, CR 511.1 / CR 603.7.)

    The object is the one the ability that created this delay bound
    (CR 603.7c), carried by id in the trigger's context — the attacker the
    Veil's own trigger fired on, which by end of combat may have been removed
    from combat, blocked, or renumbered by something else leaving (CR 400.7).
    So it is an id, never an index and never a board search.

    ``phase_out_self``'s twin for a permanent that is *not* the source: the
    Veil is an enchantment and stays where it is, and its own source would be
    an illegal reading of "it" that phases out the enchantment instead of the
    creature.

    **No re-check of the printed noun**, for ``destroy_event_subject``'s stated
    reason one file over: the pronoun re-states the trigger's own noun phrase,
    the condition already decided this creature is what the ability is about,
    and asking again at end of combat would let a creature whose controller
    changed mid-combat escape a phase-out CR 603.7c has already aimed at it.

    A permanent already gone phases out nothing, which is CR 608.2b doing as
    much as it can rather than a failure.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("bound_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the permanent it named is gone")
        return True, "resolved"
    game.phase_out_permanent(victim)
    return True, "resolved"


@effect_handler("forbid_source_phase_out")
def forbid_source_phase_out(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{U}: Until your next upkeep, **this creature** can't phase out."
    (Ertai's Familiar, CR 702.26.)

    ``forbid_phase_out``'s twin on the ability's own source, and its own kind
    for the reason ``phase_out_self`` is one beside ``phase_out_target``: the
    sentence names nothing to pick, so routing it through the targeted kind
    would raise a picker for a choice CR 602.2b says was never offered and then
    lock whatever the resolution happened to be holding.

    The record and the sweep that ends it are ``engine/phasing_locks.py``'s, so
    a printed window with no sweep behind it refuses at lowering rather than
    being written and never lifted. "**Your** next upkeep" is the ability's
    controller (CR 109.5) — here the same seat as the creature's, but frozen
    from the ability rather than read off the permanent, because that is the
    seat the words name.
    """
    from ..phasing_locks import forbid_phase_out as record_lock

    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: not on the battlefield to lock")
        return True, "resolved"
    seat = (
        game.players.index(context.caster)
        if context.caster in game.players else None
    )
    record_lock(
        source,
        duration=str(instruction.payload.get("duration") or "your_next_upkeep"),
        seat=seat,
    )
    game.log.append(f"{source.card.name} can't phase out ({context.card.name})")
    return True, "resolved"


@effect_handler("phase_in_and_out_matching")
def phase_in_and_out_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Simultaneously, all phased-out creatures phase in and all creatures with
    phasing phase out." (Time and Tide, CR 702.26.)

    **Both sets are read before either is applied**, which is the whole of what
    the printed adverb buys: a creature with phasing that phases in here must
    not be swept straight back out, and one that phases out must not be counted
    as arriving. That is the same simultaneity ``Game.resolve_phasing_for``
    implements for the untap-step event (CR 702.26a), and it is written the same
    way — read, then apply — rather than with a per-permanent flag to keep in
    step.

    The incoming half reads each seat's ``phased_out`` holding list, because a
    phased-out permanent is on no battlefield (CR 702.26b) and no scan of one
    can find it. The outgoing half reads the board through the same
    ``subject_matches`` every other sweep uses, with the caster as observer
    (CR 109.5).

    A phase-out lock (Spatial Binding) is not consulted here: ``phase_out_permanent``
    asks it at the one transition every phase-out passes through, which is
    exactly why that check lives there and not at each call site.
    """
    from ..subject_filters import subject_matches

    payload = instruction.payload
    returning_filter = payload.get("returning") or {}
    leaving_filter = payload.get("leaving") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )

    def _matches(perm, described) -> bool:
        return subject_matches(
            game, perm, described,
            observer=observer, source=context.source_permanent,
        )

    # Read both sets first — see the docstring.
    returning: list[tuple[int, list]] = []
    for seat, player in enumerate(game.players):
        chosen = [p for p in player.phased_out if _matches(p, returning_filter)]
        if chosen:
            returning.append((seat, chosen))
    leaving = [
        perm for perm in game.all_permanents()
        if _matches(perm, leaving_filter)
    ]

    for seat, permanents in returning:
        game.phase_in_for(seat, permanents=permanents)
    for perm in leaving:
        game.phase_out_permanent(perm)
    game.log.append(
        f"{context.card.name}: "
        f"{sum(len(p) for _, p in returning)} phased in, {len(leaving)} phased out"
    )
    return True, "resolved"


@effect_handler("phase_out_enchanted")
def phase_out_enchanted(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{U}{U}: Enchanted creature phases out." (Vanishing, CR 702.26.)

    The Aura's own attachment, read through ``attached_host`` the way every
    other enchanted-subject handler reads it — no target is chosen, so there
    is nothing to describe and nothing to re-check at resolution.

    **The Aura goes with it and comes back with it.** That is not this
    handler's doing: ``phase_out_permanent`` drags a host's attached Auras
    along (CR 702.26d), so Vanishing phases out beside the creature it
    enchants and phases in attached to the same object — which is why phasing
    an enchanted creature is not the same as removing it, and why CR 702.26j
    is right that no attach or unattach trigger fires either way.
    """
    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    # Last-known information (CR 608.2h): Vanishing destroyed in response to
    # its own activation still phases out the creature it was on — the ability
    # exists independently of its source (CR 113.7a).
    from ._common import attached_host

    host = attached_host(game, source)
    if host is None:
        game.log.append(f"{context.card.name}: nothing enchanted to phase out")
        return True, "resolved"
    game.phase_out_permanent(host)
    return True, "resolved"


@effect_handler("phase_out_block_pair")
def phase_out_block_pair(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"This creature and **that creature** phase out." (Dream Fighter.)

    The other half of the block CR 509.3a-d announced. Read through
    ``block_pair_permanents``, the one function that knows how the two fire
    sites bind it — the becomes-blocked half puts the creature in the stack
    item's target, the blocks half targets the *blocker* (so a self-affecting
    trigger can find itself) and carries the pair in ``blocked_permanent_ids``.
    Reading the target on the blocks half would phase out this creature twice
    and its opponent not at all.

    The source's own half of the sentence is a separate ``phase_out_self``
    beside this one, because the union lowers to one statement per phrase.
    CR 702.26a's simultaneity is not at stake: a one-shot phase-out is not the
    keyword's alternation, and the pair was frozen by the trigger before either
    permanent moved.
    """
    from ._common import block_pair_permanents

    victims = [
        perm for perm in block_pair_permanents(game, context)
        if game.is_on_battlefield(perm)
    ]
    if not victims:
        game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    for perm in victims:
        game.phase_out_permanent(perm)
    return True, "resolved"


@effect_handler("phase_out_matching")
def phase_out_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"All lands you control phase out." (Taniwha.)

    A sweep over the printed noun phrase, asked through ``subject_matches`` with
    the ability's controller as observer (CR 109.5) so "you control" means the
    same seat here as it does in the picker. The set is fixed before anything
    moves: phasing an Aura out drags its host's other attachments with it
    (CR 702.26g), so a sweep that re-read the board between permanents would
    trip over what its own earlier steps removed.
    """
    from ..subject_filters import subject_matches

    described = instruction.payload.get("filter") or {}
    observer = game.players.index(context.caster)
    victims = [
        perm for perm in game.all_permanents()
        if subject_matches(
            game, perm, described, observer=observer,
            source=context.source_permanent,
        )
    ]
    for perm in victims:
        if game.is_on_battlefield(perm):
            game.phase_out_permanent(perm)
    game.log.append(f"{context.card.name}: {len(victims)} permanent(s) phased out")
    return True, "resolved"


@effect_handler("phase_out_opponent_creatures")
def phase_out_opponent_creatures(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each creature target opponent controls phases out. Until the end of
    your next turn, they can't phase in." (Teferi, Timeless Voyager's −8.)

    The countdown counts the caster's turn ends: cast on the caster's own turn
    the block survives this turn's end and the caster's next turn's end, which
    is what "the end of your next turn" spans."""
    caster_index = game.players.index(context.caster)
    target = context.target
    if target is None or target is context.caster:
        target = next(
            (game.players[i] for i in game.opponents_of(caster_index)), None
        )
    if target is None:
        return True, "resolved"
    blocked = bool(instruction.payload.get("cant_phase_in_until_your_next_turn"))
    ends = 2 if game.active_player_index == caster_index else 1
    victims = [perm for perm in game.controlled_by(game.players.index(target)) if perm.is_creature]
    for perm in victims:
        if blocked:
            perm.metadata["phase_in_blocked"] = {
                "seat": caster_index,
                "turn_ends_remaining": ends,
            }
        game.phase_out_permanent(perm)
    game.log.append(
        f"{context.card.name}: {len(victims)} creature(s) phased out"
    )
    return True, "resolved"


@effect_handler("put_target_on_library_top")
def put_target_on_library_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put target creature on top of its owner's library." (Teferi, Timeless
    Voyager's −3); "target artifact or enchantment" (Disempower); "target land"
    (Fallow Earth). A zone change, not a destruction: no dies-trigger fires and
    regeneration cannot save it. The card goes to its *owner's* library
    (CR 400.3), whoever controlled the permanent.

    **The type comes from the printed noun phrase**, asked through the same
    ``subject_matches`` the picker enumerated with. It was pinned to
    ``is_creature`` here, which is Reality Ripple's defect one file over: a
    spell whose target the engine had already accepted, declined at resolution
    with "no valid creature target" and resolved having done nothing.
    """
    from ..subject_filters import subject_matches

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = game.players.index(context.caster)
    targets_desc = instruction.payload.get("targets") or {}
    if isinstance(targets_desc, dict) and targets_desc.get("count") not in (None, 1):
        # "Put **two target lands** on top of their owners' libraries." (Plow
        # Under.) A chosen list, resolved strictly per slot the way
        # ``destroy_target_permanent``'s list branch resolves one: a slot whose
        # permanent has left is dropped (CR 608.2b) rather than slid onto
        # another, and the filter is re-asked because a land that stopped being
        # one is no longer what the caster chose.
        #
        # ``bottom_instead_colors`` is not read here and cannot arrive: the
        # lowering refuses the rider on this shape, because "if **that**
        # creature is red" asks a colour of one object and this branch holds
        # several.
        chosen = resolve_target_permanents(
            game, context,
            predicate=lambda perm: subject_matches(
                game, perm, described, observer=observer,
                source=context.source_permanent,
            ),
        )
        moved: list[str] = []
        for perm in chosen:
            if not game.is_on_battlefield(perm):
                continue
            owner_idx = game.owner_index_of(perm)
            owner = (
                game.players[owner_idx] if owner_idx is not None else context.caster
            )
            game.remove_from_battlefield(perm)
            game._remove_aura_effects(perm)
            game.put_card_into_library(
                owner, perm.card, "top", from_battlefield=perm
            )
            moved.append(perm.card.name)
        game.log.append(
            f"{context.card.name} put {', '.join(moved)} on top of their "
            "owners' libraries"
            if moved else f"{context.card.name}: no valid target"
        )
        return True, "resolved"
    target_perm = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described, observer=observer,
            source=context.source_permanent,
        ),
    )
    if target_perm is None:
        game.log.append(f"{context.card.name}: no valid target")
        return True, "resolved"
    owner_idx = game.owner_index_of(target_perm)
    owner = game.players[owner_idx] if owner_idx is not None else context.caster
    # "If that creature is **red**, you may put it on the bottom of its owner's
    # library **instead**." (Ether Well.) One move with two possible ends, so
    # the colour is asked *before* anything moves and the prompt performs the
    # move — putting it on top and then moving it would be two zone changes
    # where the card describes one. The colour is read through layer 5
    # (``effective_colors``), not off the printed card: a creature a Painter's
    # Servant has made red is red (CR 613), and the printed line is not.
    colors = tuple(instruction.payload.get("bottom_instead_colors") or ())
    if colors and any(
        color in target_perm.effective_colors for color in colors
    ):
        game.arm_library_end_choice(
            game.players.index(context.caster), target_perm, owner_idx
            if owner_idx is not None else game.players.index(context.caster),
            context,
        )
        return True, "resolved"
    # "…on **the bottom** of its owner's library." (Mercenary Informer.) The
    # same move to the library's other end; the lowering emits it on this
    # single-target shape only.
    end = "bottom" if instruction.payload.get("library_end") == "bottom" else "top"
    game.remove_from_battlefield(target_perm)
    game._remove_aura_effects(target_perm)
    game.put_card_into_library(
        owner, target_perm.card, end, from_battlefield=target_perm
    )
    where = "on top of" if end == "top" else "on the bottom of"
    game.log.append(
        f"{context.card.name}: {target_perm.card.name} put {where} {owner.name}'s library"
    )
    return True, "resolved"


@effect_handler("put_all_matching_on_library_top")
def put_all_matching_on_library_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put all enchantments on top of their owners' libraries." (Harmonic
    Convergence.)

    The sweep twin of ``put_target_on_library_top``: no pick, every permanent
    the printed noun phrase names, each onto **its own owner's** library
    (CR 400.3) whoever controlled it. A zone change rather than a destruction,
    so no dies trigger fires and regeneration cannot save one.

    The matched list is taken **before** anything moves, for
    ``return_all_matching``'s reason one screen up: a permanent leaving detaches
    its Auras, so a sweep that re-read the board between removals would stop
    matching objects it had already named — and an Aura is exactly what this
    card's noun phrase names most of.

    ``subject_matches`` with CR 109.5's observer, because "you control" and the
    rest of the seat comparisons are answered there and nowhere else; the
    lowering admitted the line only because that is true.
    """
    from ..subject_filters import subject_matches

    swept = instruction.payload.get("filter") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )
    that_player = frozen_that_player_seat(game, context)
    matched = [
        perm for perm in game.all_permanents()
        if subject_matches(
            game, perm, swept, observer=observer, source=context.source_permanent,
            that_player=that_player,
        )
    ]
    tucked: list[str] = []
    for perm in matched:
        if not game.is_on_battlefield(perm):
            # It went with something else this same sweep removed — a token
            # ceasing to exist, an Aura falling off its host.
            continue
        owner_idx = game.owner_index_of(perm)
        owner = game.players[owner_idx] if owner_idx is not None else context.caster
        game.remove_from_battlefield(perm)
        game._remove_aura_effects(perm)
        game.put_card_into_library(
            owner, perm.card, "top", from_battlefield=perm
        )
        tucked.append(perm.card.name)
    game.log.append(
        f"{context.card.name} put {', '.join(tucked)} on top of their owners' libraries"
        if tucked else f"{context.card.name}: nothing to put on a library"
    )
    return True, "resolved"


@effect_handler("put_source_card_on_library_top")
def put_source_card_on_library_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put this creature on top of its owner's library." (Thalakos Mistfolk's
    ``{U}`` ability.) "When this creature dies, you may put it on top of its
    owner's library." (Avenging Angel.)

    The ability's own source, printed with **no source zone** — so this reaches
    whichever zone the object is actually in (CR 608.2), exactly as
    ``return_source_card_to_owners_hand`` does one screen up and for its reason.
    Mistfolk's is still on the battlefield when the ability resolves; the
    Angel's is a card in its owner's graveyard, because a dies trigger resolves
    after the creature has already been put there (CR 700.4, CR 603.6d), and a
    handler that looked only at the battlefield would silently do nothing for
    the card that made this shape worth having.

    By identity across every graveyard rather than the resolving seat's:
    CR 404.1 puts a card in its *owner's*, and a creature its controller did not
    own dies into the other player's pile.
    """
    card = context.card
    source = context.source_permanent
    if source is not None and game.is_on_battlefield(source):
        owner_idx = game.owner_index_of(source)
        owner = game.players[owner_idx] if owner_idx is not None else context.caster
        game.remove_from_battlefield(source)
        game._remove_aura_effects(source)
        game.put_card_into_library(owner, card, "top", from_battlefield=source)
        game.log.append(
            f"{card.name} put on top of {owner.name}'s library"
        )
        return True, "resolved"
    for player in game.players:
        for index, held in enumerate(player.graveyard):
            if held is card:
                player.graveyard.pop(index)
                game.put_card_into_library(player, card, "top")
                game.log.append(
                    f"{card.name} put on top of {player.name}'s library"
                )
                return True, "resolved"
    game.log.append(f"{card.name} was no longer in a graveyard")
    return True, "resolved"


# CR 110.4: the card types that are permanents — what "permanent card" means
# when Ugin's −10 reads your hand.
_PERMANENT_TYPES = ("artifact", "creature", "enchantment", "land", "planeswalker")


@effect_handler("put_cards_from_hand_onto_battlefield")
def put_cards_from_hand_onto_battlefield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put up to seven permanent cards from your hand onto the battlefield."
    (Ugin, the Spirit Dragon's −10.) Non-interactive seats take every eligible
    card up to the cap, in hand order — "up to" makes any subset legal, and
    more battlefield is the default the AI already plays toward.

    "…put **all** land cards from it onto the battlefield." (Manabond.) The
    sweep spelling, and nothing is chosen at all: every card the phrase names
    goes. ``all`` rather than a very large count, because a count is a number
    the lowering would have to know before the hand is in view — and a ceiling
    read as a sweep, or a sweep read as a ceiling, is the same card playing two
    different ways.
    """
    caster = context.caster
    count = int(instruction.payload.get("count", 0))
    wanted_types = tuple(instruction.payload.get("card_types") or ())
    permanents_only = bool(instruction.payload.get("permanents_only"))

    def eligible(card) -> bool:
        if wanted_types:
            return card.primary_type in wanted_types
        if permanents_only:
            return card.primary_type in _PERMANENT_TYPES
        return True

    eligible_cards = [card for card in caster.hand if eligible(card)]
    chosen = (
        eligible_cards if instruction.payload.get("all")
        else eligible_cards[:count]
    )
    caster_index = game.players.index(caster)
    for card in chosen:
        game.take_card_from_hand(caster, card)
        game._put_permanent_onto_battlefield(caster_index, Permanent(card=card), None)
        game.log.append(f"{caster.name} put {card.name} onto the battlefield")
    if not chosen:
        game.log.append(f"{caster.name} put no cards onto the battlefield")
    return True, "resolved"


def exile_from_hand_candidates(game, payload: dict, player) -> list[int]:
    """The hand slots "you may exile a <filter> card from your hand" may be
    answered with (Ice Cauldron).

    Public for ``put_from_hand_candidates``' reason exactly: the renderer shows
    the seat what it may pick and the resolver checks what came back, and a list
    built twice is a list that can be offered wider than it is checked.
    """
    described = payload.get("card_filter") or {}
    return [
        index
        for index, card in enumerate(player.hand)
        if _card_matches_filter(card, described, game=game, owner=player)
    ]


@effect_handler("exile_chosen_card_from_hand")
def exile_chosen_card_from_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"You may exile a nonland card from your hand." (Ice Cauldron.)

    The card is chosen on resolution out of a hidden zone, so the pick *is* the
    effect and it goes through the pending-choice queue. The offer suspends the
    resolution: the sentence behind it — "you may cast that card for as long as
    it remains exiled" — reads what this exiled, and a step that ran before the
    answer would grant permission over an empty list.

    Nothing eligible is an offer never made rather than an offer declined, the
    same rule ``put_chosen_card_from_hand_onto_battlefield`` states beside it.
    """
    caster = context.caster
    seat = game.players.index(caster)
    payload = dict(instruction.payload)
    if payload.get("face_down") and context.source_permanent is None:
        # CR 406.3's rider needs a permanent to be recorded on, exactly as the
        # library-top exile beside it does: with nothing to link the entry to,
        # the card cannot be hidden, and exiling it face *up* is a different
        # effect. So the exile does not happen at all rather than happening in
        # full view.
        game.log.append("the face-down exile has no permanent to be linked to")
        return True, "resolved"
    if not exile_from_hand_candidates(game, payload, caster):
        game.log.append(
            f"{context.card.name}: {caster.name} has no card to exile"
        )
        return True, "resolved"
    game.arm_pending_choice(
        "exile_from_hand_choice", seat,
        card_name=context.card.name,
        _payload=payload,
        _context=context,
        _source_permanent=context.source_permanent,
    )
    return True, "resolved"


@effect_handler("exile_cards_from_hand")
def exile_cards_from_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each player exiles two cards from their hand." (Mind Swords.)

    Each seat chooses out of its own hidden hand (CR 400.2), in turn order from
    the active player (CR 101.4), so this arms the pick
    ``exile_chosen_card_from_hand`` already arms — the **mandatory** printing of
    it, which has no Decline — once per card owed. One card at a time rather
    than a new multi-card prompt: the chooser sees the whole hand at each pick,
    so nothing is decided with less information than one simultaneous pick of
    two would give, and the prompt, its renderer and its non-interactive
    default (the lowest-index eligible card) are the ones that already exist.

    CR 608.2's "as much as possible": a seat holding fewer eligible cards than
    the printed number exiles every one it has, and a seat with none is
    logged and skipped. The cards leave through the hand seam in the prompt's
    resolver, never by an identity filter over the hand.

    "**Target opponent** exiles a card from their hand." (Parallax Nexus.) The
    announced seat alone (``actor: target``), read off the resolution's chosen
    player — the same prompt, armed once. A target that is no player at all by
    now is CR 608.2b's "does nothing" rather than a fall back to every seat.

    **Linked when the source is a permanent** (CR 607.2a), exactly as
    ``exile_target_permanent`` records its exile and for its reason: the entry
    carries no ``ends_on``, so it is inert for every card that never asks, and
    it is the whole of Parallax Nexus's leave trigger — "each player returns to
    their hand all cards they own exiled with it" drains an empty pile without
    it, and the cards a Nexus took would stay in exile for ever. A spell (Mind
    Swords) has no permanent to link to, and its exile stays unlinked.
    """
    payload = instruction.payload
    amount = int(payload.get("amount", 1) or 0)
    caster_index = game.players.index(context.caster)
    if payload.get("actor") == "target":
        chosen = context.target
        if not any(chosen is seated for seated in game.players):
            game.log.append(
                f"{getattr(context.card, 'name', '')}: no player to exile a card"
            )
            return True, "resolved"
        candidates = {
            next(i for i, seated in enumerate(game.players) if seated is chosen)
        }
    elif payload.get("actor") == "each_opponent":
        candidates = set(game.opponents_of(caster_index))
    else:
        candidates = set(range(len(game.players)))
    count = len(game.players)
    active = game.active_player_index or 0
    seats = sorted(
        (seat for seat in candidates if not game.players[seat].lost),
        key=lambda seat: ((seat - active) % count, seat),
    )
    pick = {
        "optional": False,
        "card_filter": dict(payload.get("card_filter") or {}),
    }
    card_name = getattr(context.card, "name", "")
    for seat in seats:
        player = game.players[seat]
        owed = min(amount, len(exile_from_hand_candidates(game, pick, player)))
        if owed <= 0:
            game.log.append(f"{card_name}: {player.name} has no card to exile")
            continue
        game.log.append(
            f"{card_name}: {player.name} exiles {owed} card(s) from their hand"
        )
        for _ in range(owed):
            game.arm_pending_choice(
                "exile_from_hand_choice", seat,
                card_name=card_name,
                _payload=pick,
                _context=context,
                _source_permanent=context.source_permanent,
            )
    return True, "resolved"


def put_from_hand_candidates(game, payload: dict, player) -> list[int]:
    """The hand slots a "put a … card from your hand onto the battlefield" offer
    may be answered with.

    Public because two callers need it and one rule has to answer both: the
    prompt renderer, which shows the seat what it may pick, and the resolver,
    which checks what came back. A list built twice is a list that can be
    offered wider than it is checked.
    """
    described = payload.get("card_filter") or {}
    permanents_only = bool(payload.get("permanents_only"))
    # "…put an Aura card from your hand onto the battlefield **attached to this
    # creature**." (Academy Researchers.) CR 303.4a: an Aura may be put onto the
    # battlefield only attached to an object its own enchant ability can
    # enchant, so a card the host cannot legally carry is not among the answers
    # — offering it would put an Aura into play attached to nothing, which
    # CR 704.5m bins on the next sweep with the card already out of the hand.
    #
    # The host arrives as an **id** stamped on the payload when the offer was
    # armed, because this function is called again to check the answer and by
    # then the permanent may have moved (CR 400.7 — an index is not an
    # identity). A host that has gone leaves nothing legal to pick, which is the
    # direction that offers nothing rather than the whole hand.
    from ..auras import enchant_card_refusal

    host_id = payload.get("attach_to_permanent_id")
    host = game.permanent_by_id(host_id) if isinstance(host_id, int) else None
    seat = game.players.index(player) if player in game.players else None
    if host_id is not None and (host is None or seat is None):
        return []
    return [
        index
        for index, card in enumerate(player.hand)
        if _card_matches_filter(card, described, game=game, owner=player)
        and (not permanents_only or card.primary_type in _PERMANENT_TYPES)
        and (
            host is None
            or enchant_card_refusal(game, card, seat, host) is None
        )
    ]


@effect_handler("put_chosen_card_from_hand_onto_battlefield")
def put_chosen_card_from_hand_onto_battlefield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…put **a** permanent card from their hand onto the battlefield."
    (Eureka.)

    One card, and the seat picks which — so the pick *is* the effect, and it is
    a prompt rather than a slice off the front of the hand like the "up to N"
    sweep above. ``optional`` (the sentence said "may") adds declining to the
    answers; without it the seat must pick, and only an empty candidate list
    ends it.

    "their hand" is the hand of the seat the offer was made to, which is
    ``context.target`` once a multi-seat offer has rebound it; "your hand" is
    the caster's. The payload says which, because the two are different
    sentences.
    """
    payload = instruction.payload
    player = context.target if payload.get("whose") == "offered" else context.caster
    seat = game.players.index(player)
    if payload.get("attach_to") == "source":
        # "…attached to **this creature**." (Academy Researchers.) The host is
        # the ability's own source, frozen onto the payload by **id** here —
        # the one moment it is in hand — so the candidate rule, the prompt and
        # the answer check all resolve the same permanent however long the seat
        # takes to answer. A source that has already left names no host, and
        # CR 303.4a leaves nothing that could legally be put onto the
        # battlefield.
        source = context.source_permanent
        if source is None or not game.is_on_battlefield(source):
            game.log.append(
                f"{context.card.name}: it is no longer on the battlefield"
            )
            return True, "resolved"
        payload = {**payload, "attach_to_permanent_id": source.permanent_id}
        instruction = dataclasses.replace(instruction, payload=payload)
    # "…a creature card **of the chosen type**" (Belbe's Portal). The word is
    # the CR 614.1c record on the ability's source, resolved here into an
    # ordinary ``subtype_filter`` and frozen onto the payload for the
    # ``attach_to`` reason above: the candidate rule, the prompt and the answer
    # check all re-run off this payload, and none of them holds the source. The
    # source is read even if it has left the battlefield — the chosen type is
    # its last known information (CR 608.2h). No record leaves the key in place,
    # and ``_card_matches_filter`` then refuses every card: nothing is offered
    # rather than the whole hand.
    from ..subject_filters import SOURCE_RESOLVED_CARD_KEYS

    described = payload.get("card_filter") or {}
    if any(described.get(key) for key in SOURCE_RESOLVED_CARD_KEYS):
        payload = {
            **payload,
            "card_filter": _resolve_chosen_subtype(
                dict(described), context.source_permanent
            ),
        }
    if not put_from_hand_candidates(game, payload, player):
        # Nothing to pick. Not an offer declined — an offer never made, which is
        # the same rule ``handlers/control_flow._offer_to_seat`` states for an
        # action cost nobody can pay.
        game.log.append(
            f"{player.name} has no card {context.card.name} could put onto the battlefield"
        )
        return True, "resolved"
    game.arm_put_from_hand_choice(seat, payload, context)
    return True, "resolved"


@effect_handler("exile_all_matching")
def exile_all_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile each permanent with mana value X or less that's one or more
    colors." (Ugin, the Spirit Dragon's −X.) A sweep, not a destruction:
    indestructible does not save anything and no dies-trigger fires. Each
    card goes to its owner's exile (CR 400.3)."""
    payload = instruction.payload
    bound = payload.get("mana_value")
    x_value = int(context.x_value or 0)

    # Every narrowing the noun phrase printed except the two the lowering
    # lifted off it. They are separated *here*, once, rather than inside the
    # loop: `mana_value` may be the spell's X, which is not a number until this
    # resolution, and `colored_only` asks about the computed colours rather
    # than about a named one — neither is a question the pure matcher answers.
    narrowings = {
        key: value for key, value in payload.items()
        if key not in ("mana_value", "colored_only", "name_from_event")
    }
    # "…exile all tokens **with the same name as that creature**." (Dual
    # Nature.) CR 201.2's comparison against the name the firing event froze —
    # the creature has left the battlefield by now (CR 400.7), so the id beside
    # it resolves to nothing and the name is the one thing the sentence still
    # has. The destroy sweep's reading of the same key, for Eye of Singularity.
    #
    # No name ends the resolution: a dropped narrowing on a sweep is not a card
    # that does less, it is one that exiles every token on the table.
    event_name: str | None = None
    if payload.get("name_from_event"):
        event_name = (context.trigger_context or {}).get("event_subject_name")
        if not event_name:
            game.log.append(f"{context.card.name}: no name for 'that name' to be")
            return True, "resolved"

    # "Exile all creatures **blocked by this creature**." (Wall of Nets.) A
    # relation to the ability's own source, which the pure matcher cannot
    # answer and silently drops — on a sweep that is every creature on the
    # table. ``subject_matches`` is the one reader that can, and it takes the
    # source and the observer this resolution already holds, so the whole
    # payload goes through it rather than one key being special-cased. A spell
    # has no source permanent, which is the direction that refuses rather than
    # widens: ``blocked_by_source`` with nothing to compare against matches
    # nobody.
    from ..subject_filters import subject_matches

    observer = (
        game.players.index(context.caster)
        if context.caster in game.players else None
    )
    source_permanent = context.source_permanent

    def matches(perm: Permanent) -> bool:
        if narrowings and not subject_matches(
            game, perm, narrowings, observer=observer, source=source_permanent
        ):
            return False
        if event_name is not None and perm.effective_card.name != event_name:
            return False
        if payload.get("colored_only") and not perm.effective_colors:
            return False
        if bound is not None:
            raw = bound.get("value")
            limit = x_value if raw == "x" else int(raw)
            value = perm.effective_card.cmc or 0
            op = bound.get("op")
            if op == "le" and not value <= limit:
                return False
            if op == "ge" and not value >= limit:
                return False
            if op == "eq" and not value == limit:
                return False
        return True

    victims = [perm for perm in game.all_permanents() if matches(perm)]
    # Who controlled each of them, read **before** the sweep (CR 608.2h /
    # idiom 6): "For each creature exiled this way, its controller draws a
    # card" (Martyr's Cry) asks about a permanent that no longer exists by the
    # time the loop runs, and CR 400.7 makes the exiled card a new object with
    # no controller at all.
    controllers = {
        perm.permanent_id: seat
        for perm in victims
        for seat in (game.controller_index_of(perm),)
        if seat is not None
    }
    # …and who **owned** each of them, read in the same place and for a reason
    # one relation over (CR 108.3): "each player chooses one of the exiled cards
    # and puts it onto the battlefield under their control" (Thieves' Auction)
    # gives the card to somebody who does not own it, and after CR 400.7 there
    # is no object left to ask. Filled in the loop below, where the owner is
    # already being resolved to route the card to the right pile.
    owners: dict[int, int] = {}
    for perm in victims:
        owner_idx = game.owner_index_of(perm)
        if owner_idx is not None:
            owners[perm.permanent_id] = owner_idx
        owner = game.players[owner_idx] if owner_idx is not None else context.caster
        if not perm.metadata.get("is_token", False):
            owner.exile.append(perm.card)
            # Recorded as exiled **with** the ability's source when there is one
            # (CR 610.3), exactly as ``exile_top_of_library`` records its pile
            # and for that handler's stated reason: nothing ends the link on its
            # own — the entries carry no ``ends_on`` — so it is inert for Ugin
            # and it is everything for Wall of Nets, whose leaves-the-
            # battlefield ability ("return all cards exiled with it") is the
            # only thing that ever moves the pile. A token is not recorded
            # because it simply ceases to exist (CR 111.7) and there is no card
            # to give back.
            if source_permanent is not None and owner_idx is not None:
                link_exiled_card(source_permanent, perm.card, owner_idx)
        game._remove_aura_effects(perm)
    game.remove_all_from_battlefield(victims)
    context.results[EXILED_THIS_WAY_OBJECTS] = victims
    context.results[EXILED_THIS_WAY] = len(victims)
    context.results[PER_OBJECT_SEAT_RECORDS["controller"]] = controllers
    context.results[SWEPT_OWNER_SEATS] = owners
    game.log.append(f"{context.card.name} exiled {len(victims)} permanent(s)")
    return True, "resolved"


@effect_handler("reveal_top_of_library")
def reveal_top_of_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Reveal the top card of your library." (Track Down.)

    CR 701.20: revealing shows a card to all players and **moves it nowhere**.
    So the card stays on top, the log names it — that is what a reveal is to
    this engine — and the whole lasting effect is the record left for the
    sentences after it.

    Recorded rather than re-read, because the very next sentence may draw it:
    "if it's a creature or land card, draw a card" asks about the card that was
    revealed, and by the time the branch runs the library's top is a different
    card. An empty library records nothing, which the condition reads as False —
    a legal outcome, not an error.
    """
    # "Reveal the top card of **target opponent's** library." (Prophecy.) Whose
    # deck is opened is payload, because the sentences behind the reveal read
    # the record it leaves: revealing off the caster's own library would gain
    # the life for the wrong card and leave the wrong deck to be shuffled.
    # Absent for every reveal printed about "your library", so those keep
    # reaching ``context.caster`` and their payload byte-identical.
    whose = str(instruction.payload.get("whose", "you"))
    if whose == "each_player":
        # "**Each player** reveals the top card of their library." (Game
        # Preserve.) One library per seat, in CR 101.4's order — the active
        # player first — so a seeded AI run reproduces exactly. A seat that has
        # left the game reveals nothing (CR 800.4a) and an empty library
        # contributes no card, which is what makes the sentence behind this one
        # False rather than vacuously true.
        #
        # Recorded as ``{seat: card}`` rather than a flat list because "put
        # those cards onto the battlefield **under their owners' control**"
        # needs a different battlefield per card, and nothing else can say
        # which: CR 701.20a leaves every card on top of its own library, so by
        # the time the next sentence runs there is no move to read the seat off.
        by_seat: dict[int, object] = {}
        total = len(game.players)
        active = game.active_player_index or 0
        order = sorted(
            (i for i, p in enumerate(game.players) if not p.lost),
            key=lambda i: ((i - active) % total, i),
        )
        for seat in order:
            player = game.players[seat]
            if not player.library:
                game.log.append(f"{player.name} has no library to reveal from")
                continue
            top = player.library[0]
            by_seat[seat] = top
            game.log.append(
                f"{player.name} revealed {top.name} from the top of their library"
            )
            game.record_reveal(seat, [top.name])
        context.results[REVEALED_TOP_CARDS_BY_SEAT] = by_seat
        return True, "resolved"
    revealer = context.caster if whose == "you" else context.target
    if revealer is None:
        game.log.append(f"{context.card.name}: no player to reveal from")
        return True, "resolved"
    if not revealer.library:
        game.log.append(f"{revealer.name} has no library to reveal from")
        return True, "resolved"
    top = revealer.library[0]
    context.results["revealed_card"] = top
    game.log.append(
        f"{revealer.name} revealed {top.name} from the top of their library"
    )
    game.record_reveal(game.players.index(revealer), [top.name])
    return True, "resolved"


@effect_handler("put_revealed_top_cards_onto_battlefield")
def put_revealed_top_cards_onto_battlefield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…put **those cards** onto the battlefield **under their owners'
    control**." (Game Preserve.)

    The cards an earlier step of this same resolution revealed off the top of
    every library, each going to the seat whose library it came off — which is
    what "their owners'" says and why the record is keyed by seat. CR 400.3: a
    card put onto the battlefield by an effect that names an owner enters under
    that player's control, not the ability controller's.

    Nothing recorded is nothing to put: the reveal in front of this is the only
    producer, and the intervening condition already refuses an empty one.
    Each card is removed from its own library **by identity** at the position it
    still occupies, because two copies of a card are the same immutable object
    and a value comparison would take the wrong one.
    """
    by_seat = context.results.get(REVEALED_TOP_CARDS_BY_SEAT) or {}
    if not by_seat:
        game.log.append(f"{context.card.name}: no revealed card to put onto the battlefield")
        return True, "resolved"
    for seat, card in sorted(by_seat.items()):
        if not (0 <= seat < len(game.players)):
            continue
        owner = game.players[seat]
        for index, held in enumerate(owner.library):
            if held is card:
                owner.library.pop(index)
                break
        else:
            # It left the library between the reveal and this step. CR 400.7
            # makes whatever is on top now a different object, so nothing is
            # put rather than the wrong card.
            game.log.append(f"{card.name} was no longer on top of {owner.name}'s library")
            continue
        game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
        game.log.append(
            f"{owner.name} put {card.name} onto the battlefield ({context.card.name})"
        )
    return True, "resolved"


@effect_handler("shuffle_library")
def shuffle_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Then that player shuffles." (Prophecy.) CR 701.24.

    The library is randomised and **nothing moves into it**, which is what
    separates this from the two shuffles below that empty a zone first: those
    have a pile to move, and this has the reason no pile is needed — a card was
    looked at, and the shuffle is what stops anybody knowing where it went.

    Through the module-level RNG every other shuffle here uses, so a seeded run
    stays reproducible (the determinism invariant).
    """
    whose = str(instruction.payload.get("whose", "you"))
    player = context.caster if whose == "you" else context.target
    if player is None:
        return False, "no player to shuffle"
    random.shuffle(player.library)
    game.log.append(f"{player.name} shuffled their library")
    return True, "resolved"


@effect_handler("reveal_top_to_hand_or_bottom")
def reveal_top_to_hand_or_bottom(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Reveal the top card of your library. If it's a creature card, put it
    into your hand. Otherwise, put it on the bottom of your library." (Garruk,
    Savage Herald's +1.) Revealing is public: the log names the card either
    way, which is what a reveal means to this engine."""
    caster = context.caster
    if not caster.library:
        game.log.append(f"{caster.name} has no library to reveal from")
        return True, "resolved"
    card_type = instruction.payload.get("card_type")
    top = caster.library.pop(0)
    game.record_reveal(game.players.index(caster), [top.name])
    if card_type is None or top.primary_type == card_type:
        game.put_card_into_hand(caster, top)
        game.log.append(f"{caster.name} revealed {top.name} and put it into their hand")
    else:
        game.put_card_into_library(caster, top)
        game.log.append(
            f"{caster.name} revealed {top.name} and put it on the bottom of their library"
        )
    return True, "resolved"


@effect_handler("discard_hand")
def discard_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Discard your hand" (Chandra, Heart of Fire). Every card, no choice to
    make, so no prompt — each discard still goes through _discard_card so
    anything watching discards sees them.

    ``who`` names a *different* seat when the sentence did: "whenever this
    creature deals damage to an opponent, **that player** discards their hand"
    (Nicol Bolas) empties the hand of the player the firing event recorded
    (CR 603.10), read from the trigger's context under the key every damage fire
    site stamps. No record means the words named nobody and nothing is
    discarded, which is the same rule the random-discard handler above follows —
    never a fall back to the ability's controller, who is the one player this
    effect must not hit.
    """
    caster = context.caster
    if instruction.payload.get("who") == "each_player":
        # "**Each player** discards their hand…" (Windfall, Ill-Gotten Gains.)
        # Every living seat in CR 101.4's order, which is the order every other
        # each-player loop in this engine walks — nothing here is a decision,
        # but a seeded run still has to replay identically. A player who has
        # left the game is not one of them (CR 800.4a). One loop for the whole
        # family, which is why "each player" is a value of ``who`` and not a
        # second handler.
        #
        # It was, briefly, *two* copies of this block — a parallel-round merge
        # unioned both rewrites of this function and the second sat after this
        # one's ``return``, unreachable. The two differed by a single line and
        # it was this one's ``by_seat`` write, so the wrong survivor would have
        # made the sentence behind Windfall's read a zero with nothing failing.
        # `tests/engine/test_no_function_re_asks_a_settled_dispatch.py` is the
        # guard that now sees it; a repeated *top-level* name never could.
        #
        # The tally is recorded **per seat**, under the key the per-seat
        # discards already write: the sentence behind this one asks for "the
        # greatest number of cards **a player** discarded this way", and a
        # single number would be whichever hand the loop emptied last.
        total = len(game.players)
        active = game.active_player_index or 0
        seats = sorted(
            (i for i, p in enumerate(game.players) if not p.lost),
            key=lambda i: ((i - active) % total, i),
        )
        by_seat = context.results.setdefault(DISCARDED_BY_SEAT, {})
        emptied = 0
        for seat in seats:
            player = game.players[seat]
            gone = list(player.hand)
            player.hand = []
            for card in gone:
                game._discard_card(player, card)
            by_seat[seat] = len(gone)
            emptied += len(gone)
            game.log.append(
                f"{player.name} discarded their hand ({len(gone)} card(s))"
            )
        # The flat key too, for the sentence that asks about the whole
        # resolution rather than about one seat — written for the same reason
        # the single-seat branch below writes it, and as the total rather than
        # as any one seat's share, which is what "this way" names when the
        # effect emptied every hand.
        context.results["discarded_count"] = emptied
        return True, "resolved"
    if instruction.payload.get("who") == "damaged_player":
        seat = (context.trigger_context or {}).get("defending_player_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(f"{context.card.name}: no recorded player, no discard")
            return True, "resolved"
        caster = game.players[seat]
    if instruction.payload.get("who") == "defending_player":
        # CR 506.2's seat rather than the damaged one above: Robber Fly's
        # trigger deals no damage at all, so the damage key is simply absent for
        # it. The two words are two records and reading one for both would empty
        # nobody's hand on every card of the second kind — the distinction
        # ``player_gets_poison_counters`` already states for the same pair.
        seat = (context.trigger_context or {}).get("trigger_defending_player_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(f"{context.card.name}: no recorded player, no discard")
            return True, "resolved"
        caster = game.players[seat]
    if instruction.payload.get("who") == "target":
        # "…**target opponent** discards their hand." (Brink of Madness.) The
        # seat the announcement chose (CR 601.2c, and CR 603.3d for the trigger
        # this one is printed on), which arrives as ``context.target`` exactly
        # as it does for ``discard_target_cards`` beside this handler.
        #
        # A resolution carrying no player is a target nobody named, and
        # ``caster`` above it is the ability's *controller* — the one seat this
        # effect must not empty. So it refuses rather than falling back, which
        # is the rule the ``damaged_player`` branch above states in its own
        # words and the one the whole ``who`` family is written to.
        # Identity, never ``in``: :class:`PlayerState` is a plain dataclass, so
        # equality compares its fields and two seats holding equal state answer
        # the same — ``game.seat_index`` states the rule and this is its
        # membership half.
        target = context.target
        if target is None or not any(seat is target for seat in game.players):
            game.log.append(
                f"{context.card.name if context.card else 'the ability'}: "
                "no player was named to discard"
            )
            return True, "resolved"
        caster = target
    discarded = list(caster.hand)
    caster.hand = []
    for card in discarded:
        game._discard_card(caster, card)
    # "…, then draws **that many** cards." (Shocker.) How many actually went,
    # under the key every other discard in this file already writes — a hand
    # that was empty discards nothing and draws nothing, which is CR 608.2's
    # "as much as possible" and the reason the number is counted here rather
    # than read off the printed sentence, which names none.
    context.results["discarded_count"] = len(discarded)
    game.log.append(f"{caster.name} discarded their hand ({len(discarded)} card(s))")
    return True, "resolved"


@effect_handler("each_player_discards_a_card")
def each_player_discards_a_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each player discards a card." (Liliana, Waker of the Dead's +1.)
    ""…then discards a third of the cards in their hand…" (Pox.)

    Who could not is recorded in the resolution scratchpad, because the
    printed rider "Each opponent who can't loses 3 life." reads it. An
    interactive seat's choice goes through the discard prompt; a
    non-interactive seat discards its first cards, matching the existing
    discard default.

    **How many is per seat**, and that is why it is a count spec rather than an
    amount: "a third of the cards in **their** hand" has one answer per player,
    and a single number could only be one of them. Evaluated against each
    player in turn through the same evaluator every other computed count uses,
    so the fraction and its rounding are applied in one place (CR 107.2/107.3).
    An absent spec and an absent amount are the printed one this handler was
    written for.
    """
    per_seat = instruction.payload.get(X_FROM_COUNT_PER_RECIPIENT)
    fixed = int(instruction.payload.get("amount", 1) or 0)
    could_not: list[int] = []
    for seat, player in enumerate(game.players):
        if player.lost:
            continue
        count = (
            evaluate_count(game, player, per_seat) if per_seat is not None else fixed
        )
        count = min(max(0, count), len(player.hand))
        if count == 0:
            # CR 608.2: as much as possible. A player asked for none discards
            # none — and only an empty hand is what the printed rider means by
            # "can't", so a computed zero over an empty hand is still recorded
            # and a computed zero over a full one is not.
            if not player.hand:
                could_not.append(seat)
                game.log.append(f"{player.name} cannot discard (empty hand)")
            continue
        if seat in game.interactive_seats:
            game.arm_pending_choice(
                "discard", seat,
                count=count,
                allow_top_of_library=game._controls_top_of_library_discard(player),
            )
            game.log.append(
                f"{player.name} must choose {count} card(s) to discard"
            )
        else:
            for _ in range(count):
                card = player.hand[0]
                game.take_card_from_hand(player, card)
                game._discard_card(player, card)
                game.log.append(f"{player.name} discarded {card.name}")
    context.results["players_who_could_not_discard"] = could_not
    return True, "resolved"


@effect_handler("each_player_discards_up_to_cards")
def each_player_discards_up_to_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each player may discard up to three cards." (Mind Bomb.)

    One ``discard`` prompt per seat with the printed ceiling, offered in turn
    order (CR 101.4). The ceiling *is* the offer — a player may answer with
    none — which is why the "may" in front of it collapses into this rather than
    arming a yes/no offer of its own
    (``engine/grammar/lowering/_collapses._each_player_optional_discard``).

    Every seat is recorded, including the ones with nothing to discard, because
    "3 minus the number of cards **they** discarded this way" is a number for
    every player and a seat the record never mentions has to read as zero rather
    than as a missing key. The scratchpad rides the prompt, so the count that is
    written is the one the seat actually chose — the hand as it stood when the
    prompt was armed is not the answer.
    """
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    # "Each player discards **any number of** cards" (Flux): the ceiling is the
    # seat's own hand rather than a printed number, and only the resolution
    # knows how big that is. Sized per seat below, where the hand is in hand.
    any_number = bool(instruction.payload.get("any_number"))
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
    by_seat = context.results.setdefault(DISCARDED_BY_SEAT, {})
    context.results.setdefault("discarded_count", 0)
    for seat in seats:
        player = game.players[seat]
        by_seat[seat] = 0
        actual = len(player.hand) if any_number else min(amount, len(player.hand))
        if actual <= 0:
            game.log.append(f"{player.name} has no cards to discard")
            continue
        game.arm_pending_choice(
            "discard", seat,
            count=actual,
            up_to=True,
            allow_top_of_library=game._controls_top_of_library_discard(player),
            _results=context.results,
        )
        game.log.append(f"{player.name} may discard up to {actual} card(s)")
    return True, "resolved"


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


@effect_handler("exile_top_of_library")
def exile_top_of_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile the top three cards of your library." (Chandra, Heart of Fire's
    +1.) The exiled cards are recorded under ``exiled_cards`` for the same
    resolution's "you may play cards exiled this way" to read — the exile is
    what makes that sentence mean anything.

    They are *also* recorded as exiled **with** the ability's source, when the
    source is a permanent (CR 610.3, engine/linked_exile.py). Nothing ends that
    link on its own — the entries carry no ``ends_on`` — so it is inert for
    Chandra and it is everything for Knowledge Vault, whose other two abilities
    are the only things that ever move the pile.

    ``face down`` (CR 406.3) needs that record to mean anything: two copies of
    one card in a deck are the same ``CardDefinition`` object, so the record of
    the exiling is the only sound answer to "which exiled card is hidden".

    **A spell has no permanent to hold that record**, and used to refuse the
    whole exile for want of one — which made "Exile the top three cards of your
    library face down" (Three Wishes) a sentence that compiled, lowered and did
    nothing. The register that answers for an exiler which never becomes a
    permanent is ``engine/exiled_records.py``, whose whole argument is this one:
    the identity of the exiled object is the record. So the fact goes there when
    there is no permanent and onto the permanent when there is, and
    ``linked_exile.face_down_exiled_cards`` reads both.
    """
    caster = context.caster
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    face_down = bool(instruction.payload.get("face_down"))
    source = context.source_permanent
    owner_index = game.players.index(caster)
    exiled = []
    for _ in range(min(amount, len(caster.library))):
        card = caster.library.pop(0)
        caster.exile.append(card)
        exiled.append(card)
        if source is not None:
            link_exiled_card(source, card, owner_index, face_down=face_down)
        elif face_down:
            record_exiled_card(game, card, owner_index, face_down=True)
    context.results["exiled_cards"] = exiled
    if exiled:
        game.log.append(
            f"{caster.name} exiled {', '.join(card.name for card in exiled)} "
            "from the top of their library"
        )
    else:
        game.log.append(f"{caster.name} has no cards left to exile")
    return True, "resolved"


@effect_handler("exile_entire_library")
def exile_entire_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"That player exiles all cards from their library." (Thought Lash, when
    its cumulative upkeep goes unpaid.)

    The whole zone, in order, so a later effect that could look at the pile
    sees what was on top. It does **not** end the game by itself: CR 704.5b
    makes a player lose only when they would draw from an empty library, which
    is the next draw step — so this leaves the seat alive with nothing to draw,
    exactly as the card reads.

    A seat the trigger did not freeze is a card acting on the wrong player, so
    an unresolvable recipient does nothing rather than falling back to the
    resolving seat: emptying the wrong library is the game, not a smaller
    effect.
    """
    recipient = str(instruction.payload.get("recipient", "caster"))
    if recipient == "caster":
        victim = context.caster
    else:
        seat = frozen_that_player_seat(game, context)
        if seat is None:
            game.log.append(
                f"{context.card.name}: no player was named to empty a library"
            )
            return True, "resolved"
        victim = game.players[seat]
    emptied = list(victim.library)
    victim.library.clear()
    victim.exile.extend(emptied)
    game.log.append(
        f"{victim.name} exiled their whole library "
        f"({len(emptied)} card(s)) to {context.card.name}"
    )
    return True, "resolved"


@effect_handler("put_library_top_into_hand")
def put_library_top_into_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put that many cards from the top of your library into your hand."
    (Scroll Rack.)

    **Not a draw**, and that is the whole of why it is its own handler.
    CR 121.1 defines a draw as putting the top card of a library into a hand,
    but an effect that spells those words instead of saying "draw" is not one
    (CR 121.5): no "whenever you draw a card" trigger sees it, and no draw
    replacement applies. Routed through ``_draw_with_replacements`` this card
    would ring every draw trigger on the board and be stopped by every draw
    replacement, which is a different card.

    Through ``put_card_into_hand``, the CR 903.9b seam every card reaching a
    hand goes through — a draw is the *only* thing this differs from.

    Fewer cards than asked for is an ordinary board: CR 704.5b's loss fires on
    an attempted **draw** from an empty library, and this is not one, so a short
    library simply gives what it has.
    """
    caster = context.caster
    amount = resolve_amount(instruction.payload.get("amount", 0) or 0, context.x_value)
    recorded = instruction.payload.get("amount_from")
    if recorded is not None:
        amount = int(context.results.get(recorded) or 0)
    taken = caster.library[:max(int(amount), 0)]
    if not taken:
        game.log.append(f"{caster.name} puts no cards into their hand")
        return True, "resolved"
    del caster.library[:len(taken)]
    for card in taken:
        game.put_card_into_hand(caster, card)
    game.log.append(
        f"{caster.name} put {len(taken)} card(s) from the top of their library "
        "into their hand"
    )
    return True, "resolved"


@effect_handler("put_exiled_pile_on_library")
def put_exiled_pile_on_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Then look at the exiled cards and put them on top of your library in
    any order." (Scroll Rack.)

    The linked pile (CR 610.3) drained back onto the library. The pile is put
    there first and the *order* is then the ordinary reorder prompt, which is
    what makes the look real: the seat is shown exactly those cards and
    arranges them, and CR 406.3 is satisfied because they are no longer exiled
    by the time anybody sees them.

    Reusing ``reorder_library`` rather than arming a prompt of its own is the
    point. That prompt already asks "here are the top N of your library, put
    them in an order" — which is this sentence once the cards are on top — so
    the renderer, the AI default and the wire action all already exist, and a
    second prompt would be a second answer to one question.

    A pile of fewer than two has no order to choose, so nothing is asked; the
    cards are on the library either way.
    """
    source = context.source_permanent
    caster = context.caster
    seat = game.players.index(caster)
    entries = take_linked_entries(source)
    if not entries:
        name = context.card.name if context.card is not None else "that permanent"
        game.log.append(f"nothing is exiled with {name}")
        return True, "resolved"
    moved = []
    for entry in entries:
        owner = game.players[int(entry["owner_index"])]
        # Through the one transition out of exile (CR 400.7): the exile
        # register hangs a card's counters, its face-down flag and its look
        # permission off the object, and a list write leaves them behind. It
        # answers False for a card that has already gone by some other route,
        # which is the same "a card put back from nowhere is a card this effect
        # created" the sweep beside this one states.
        if not game.take_card_from_exile(owner, entry["card"]):
            continue
        moved.append(entry["card"])
    if not moved:
        return True, "resolved"
    if str(instruction.payload.get("position", "top")) == "bottom":
        caster.library.extend(moved)
        game.log.append(
            f"{len(moved)} card(s) go on the bottom of {caster.name}'s library"
        )
        return True, "resolved"
    caster.library[:0] = moved
    game.log.append(
        f"{len(moved)} card(s) go on top of {caster.name}'s library"
    )
    if len(moved) < 2:
        return True, "resolved"
    game.arm_pending_choice(
        "reorder_library", seat,
        target_index=seat, top_count=len(moved), may_shuffle=False,
    )
    return True, "pending_reorder_library"


@effect_handler("exile_hand_pile")
def exile_hand_pile(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile **all** cards from your hand face down." (Duplicity.)
    "Exile **any number of** cards from your hand face down." (Scroll Rack.)

    A *pile* out of a hidden zone, recorded on the exiling permanent
    (CR 610.3) — which is the only place a face-down exile can be recorded:
    two copies of one card in a deck are the same ``CardDefinition`` object, so
    nothing on the card can say which of them is hidden.

    Both quantifiers are one handler because the exile is identical; what
    differs is whether anybody is asked. "All" asks nothing. "Any number of"
    is a pick and goes through the pending-choice queue, and **zero is a legal
    answer** — which is why the sentence behind it on Scroll Rack draws that
    many cards rather than a printed number.

    Without a permanent to link to, the exile does not happen at all rather
    than happening face up: that is the rule ``exile_chosen_card_from_hand``
    already states one screen down, and for its reason — an exile that
    silently happened in full view is the loudest kind of quiet wrong.

    The entries this step created are recorded **by identity** under
    ``exiled_entries``, for a sentence like Duplicity's "put **all other**
    cards you own exiled with this enchantment into your hand": "other" means
    other than the ones this resolution just put there, and a card name cannot
    say that — the pile may already hold another copy of the same card.
    """
    caster = context.caster
    seat = game.players.index(caster)
    source = context.source_permanent
    payload = dict(instruction.payload)
    if payload.get("face_down") and source is None:
        game.log.append("the face-down exile has no permanent to be linked to")
        return True, "resolved"
    described = dict(payload.get("card_filter") or {})
    # "**Each player** exiles all cards from their hand face down." (Memory
    # Jar.) The same act once per seat rather than a second kind: what the
    # exile does to a hand does not depend on whose it is, and the seat is what
    # ``exile_hand_slots`` already takes. The pick branch below is not reachable
    # from here — a per-seat "any number of" is refused in the lowering,
    # because a pick is owed by the seat that makes it and the queue would have
    # to hold one prompt per player.
    if str(payload.get("who", "you")) == "each_player":
        for index in range(len(game.players)):
            player = game.players[index]
            game.exile_hand_slots(
                context, source, index,
                [
                    slot for slot, card in enumerate(player.hand)
                    if _card_matches_filter(card, described)
                ],
                face_down=bool(payload.get("face_down")),
            )
        return True, "resolved"
    slots = [
        index for index, card in enumerate(caster.hand)
        if _card_matches_filter(card, described)
    ]
    if payload.get("quantifier") == "any_number" and seat in game.interactive_seats:
        if not slots:
            game.log.append(f"{caster.name} has no card to exile")
            return True, "resolved"
        game.arm_pending_choice(
            "exile_hand_pile_choice", seat,
            card_name=context.card.name if context.card is not None else "",
            _payload=payload,
            _context=context,
            _source_permanent=source,
        )
        return True, "resolved"
    # "All" takes every matching card, and a non-interactive seat answering
    # "any number of" takes every matching card too — the stated policy for an
    # unbounded may-per-card, the same one `_default_search_exile` gives: the
    # cards come back, so the maximum is the only default that leaves nothing
    # on the table.
    game.exile_hand_slots(
        context, source, seat, slots,
        face_down=bool(payload.get("face_down")),
    )
    return True, "resolved"


@effect_handler("put_exiled_with_source")
def put_exiled_with_source(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put all cards exiled with this artifact into their owner's hand."
    (Knowledge Vault's ``{0}``; its trigger says "…with it into their owner's
    graveyard".)

    The pile is drained, not copied: once the cards have moved they are no
    longer exiled with anything, and the record is what the *other* linked
    ability reads. Knowledge Vault is exactly that case — the ``{0}`` ability
    sacrifices the artifact, which puts its leaves-the-battlefield trigger on
    the stack, and the trigger has to find an empty pile a moment later rather
    than pulling the same cards out of the hand they just reached.

    Reading the record off ``context.source_permanent`` is also what lets it
    survive the sacrifice: the record lives on the ``Permanent`` object, and
    that object is still the one the resolution is holding after it has left
    the battlefield (CR 400.7 makes any *returning* permanent a new object, so
    an id would not do).
    """
    source = context.source_permanent
    zone = str(instruction.payload.get("zone", "hand"))
    if instruction.payload.get("one_of"):
        # "Return **a card you own** exiled with this artifact to your hand."
        # (Gustha's Scepter.) One card out of the same pile, and the ability's
        # controller says which — so the pick *is* the effect and it goes
        # through the pending-choice queue, exactly as the exile that filled
        # the pile did. The record is *not* drained here: the cards left behind
        # are still exiled with the permanent.
        seat = game.players.index(context.caster)
        game.arm_pending_choice(
            "linked_exile_return", seat,
            card_name=context.card.name if context.card is not None else "",
            zone=zone,
            owned_by_chooser=bool(instruction.payload.get("owned_by_chooser")),
            # CR 110.2a, for the one destination that has no possessive to
            # print: "return a card exiled with this enchantment **to the
            # battlefield**" (Purgatory) puts it under the control of the seat
            # the effect instructed, and every other spelling names an owner.
            under_control_of_chooser=(
                instruction.payload.get("under_control_of") == "chooser"
            ),
            _source_permanent=source,
        )
        return True, "resolved"
    # "Return **each creature card** exiled with this artifact…" (Cold Storage).
    # The printed narrowing, applied *before* the drain: a card the sentence
    # does not name is still exiled with this permanent afterwards, so taking
    # the whole pile and putting part of it back would be two zone changes where
    # the card describes none for it. Absent on every other printing, where the
    # sentence names the pile whole.
    wanted_type = instruction.payload.get("card_type")
    entries = take_linked_entries(source)
    # "Put **all other cards you own** exiled with this enchantment into your
    # hand." (Duplicity.) Two narrowings on the sweep, applied here and then
    # put back like the card-type one below, because a card the sentence does
    # not name is still exiled with this permanent afterwards.
    #
    # "Other" is a back-reference to the exile *this same resolution* performed
    # a step earlier, and it is answered by **entry identity**: a card name
    # cannot say it, because the pile may already hold another copy of the same
    # card — and a hand repeats one immutable ``CardDefinition`` per copy, so
    # the objects are not distinct either. The entries are the only distinct
    # things there are.
    if instruction.payload.get("others_only") or instruction.payload.get(
        "owned_by_chooser"
    ):
        just_exiled = tuple(context.results.get("exiled_entries") or ())
        chooser_seat = game.players.index(context.caster)
        excluded = []
        wanted = []
        for entry in entries:
            if instruction.payload.get("others_only") and any(
                entry is fresh for fresh in just_exiled
            ):
                excluded.append(entry)
            elif instruction.payload.get("owned_by_chooser") and int(
                entry["owner_index"]
            ) != chooser_seat:
                excluded.append(entry)
            else:
                wanted.append(entry)
        entries = wanted
        if excluded:
            from ..linked_exile import link_exiled_card

            for entry in excluded:
                link_exiled_card(
                    source, entry["card"], int(entry["owner_index"]),
                    ends_on=tuple(entry.get("ends_on") or ()),
                    face_down=bool(entry.get("face_down")),
                )
    if wanted_type is not None:
        from ..linked_exile import link_exiled_card

        # Through the one card-in-a-zone matcher (_card_matches_filter),
        # never primary_type: CR 205.2a gives a card every type printed on
        # it, and an "Artifact Creature" collapsed to one word is a creature
        # this sentence would leave in exile.
        described = {"type_filter": str(wanted_type)}
        kept = [e for e in entries if not _card_matches_filter(e["card"], described)]
        entries = [e for e in entries if _card_matches_filter(e["card"], described)]
        for entry in kept:
            link_exiled_card(
                source, entry["card"], int(entry["owner_index"]),
                ends_on=tuple(entry.get("ends_on") or ()),
            )
    if not entries:
        name = context.card.name if context.card is not None else "that permanent"
        game.log.append(f"nothing is exiled with {name}")
        return True, "resolved"
    moved: list[str] = []
    onto_battlefield = False
    # CR 110.2a: "under **your** control" names the seat the effect instructed,
    # which is not the owner. Absent means the owner, which is what every
    # automatic return and every "into their owner's <zone>" spelling means.
    controller_index = (
        game.players.index(context.caster)
        if instruction.payload.get("under_control_of") == "chooser" else None
    )
    for entry in entries:
        owner = game.players[int(entry["owner_index"])]
        if entry["card"] not in owner.exile:
            # It has already left exile by some other route; a card put back
            # from nowhere is a card this effect created.
            continue
        # The one placement, shared with the automatic return: a hand or a
        # library goes through the CR 903.9b seam rather than being appended.
        onto_battlefield |= game.leave_linked_exile(
            entry, zone, controller_index=controller_index
        ) is not None
        moved.append(entry["card"].name)
    if moved:
        # "…under **your** control" is not the owner's zone, so the line has to
        # say whose it is or the log describes a different effect.
        whose = (
            game.players[controller_index].name if controller_index is not None
            else "their owner"
        )
        game.log.append(f"{', '.join(moved)} go to {whose}'s {zone}")
        if onto_battlefield:
            game._recompute_continuous_effects()
    return True, "resolved"


@effect_handler("grant_look_at_exiled_cards")
def grant_look_at_exiled_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"You may look at it for as long as it remains exiled." (Gustha's
    Scepter, the sentence after its face-down exile.)

    A card in exile face down is hidden from **every** player, its owner
    included (CR 406.3) — Knowledge Vault says nothing about looking and its
    controller cannot read its own pile. So this sentence is an effect, and
    what it changes is one seat's view of one entry.

    Written onto the linked-exile entry rather than onto the card, for
    ``link_exiled_card``'s standing reason: two copies of one card in a deck
    are the same ``CardDefinition`` object, so the record of the exiling is the
    only thing that can say which one this permission covers. The entries are
    matched by **identity** against what this resolution exiled, newest first,
    one entry per card — a value comparison would mark a different printing of
    the same card that some earlier activation put there.

    The duration needs no sweep: the permission lives on the entry, and the
    entry is drained the moment the card leaves exile.

    **A spell grants the same permission over the same cards and has no
    permanent**, so its record is the game's exile register instead (Three
    Wishes; see ``exile_top_of_library``). Both are written here rather than by
    two instructions, because the sentence is one sentence — a second kind would
    be a look permission whose reading depended on what exiled the card.
    """
    source = context.source_permanent
    exiled = list(context.results.get(instruction.payload.get("cards_from") or "exiled_cards") or ())
    if not exiled:
        # Nothing was exiled (the pick found no eligible card), so there is
        # nothing to grant — not a failure; the sentence before this one already
        # logged why.
        return True, "resolved"
    seat = game.players.index(context.caster)
    if source is None:
        granted = []
        for record in records_for_cards(game, exiled):
            if record.looker_index is None:
                record.looker_index = seat
                granted.append(record.card.name)
        if granted:
            game.log.append(
                f"{game.players[seat].name} may look at {', '.join(granted)} "
                "for as long as it remains exiled"
            )
        return True, "resolved"
    remaining = list(exiled)
    granted: list[str] = []
    for entry in reversed(linked_entries(source)):
        if not remaining:
            break
        if entry.get("looker_index") is not None:
            continue
        for position, card in enumerate(remaining):
            if entry["card"] is card:
                entry["looker_index"] = seat
                granted.append(card.name)
                del remaining[position]
                break
    if granted:
        game.log.append(
            f"{game.players[seat].name} may look at {', '.join(granted)} "
            "for as long as it remains exiled"
        )
    return True, "resolved"


@effect_handler("search_and_exile_matching")
def search_and_exile_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Search your graveyard and library for any number of red instant and/or
    sorcery cards, exile them, then shuffle." (Chandra, Heart of Fire's −9.)

    Armed as a suspending choice: the picks decide what the *next* step of the
    same resolution ("You may cast them this turn.") has to permit, so the
    steps behind this one wait for the answer — the Opt lesson, applied here
    by registration rather than by hoping.
    """
    from ..ai_valuation import exiled_search_pile_comes_back

    caster = context.caster
    caster_index = game.players.index(caster)
    zones = tuple(instruction.payload.get("zones") or ("graveyard", "library"))
    game.arm_pending_choice(
        "search_exile_cards", caster_index,
        zones=zones,
        card_types=tuple(instruction.payload.get("card_types") or ()),
        colors=tuple(instruction.payload.get("colors") or ()),
        # "…for **three** cards" (Foresight). A printed ceiling on the find,
        # absent for the "any number of" spelling — the resolver refuses a
        # longer answer and the non-interactive default trims to it.
        maximum=instruction.payload.get("maximum"),
        # "…exile them in a face-down pile, and shuffle that pile." (Mangara's
        # Tome.) Carried to the resolver rather than acted on here, because
        # nothing has been found yet: the pile is what the *answer* exiles, and
        # this handler only asks the question.
        face_down_pile=bool(instruction.payload.get("face_down_pile")),
        shuffle_pile=bool(instruction.payload.get("shuffle_pile")),
        # Whether anything on this card reads the pile back, which is what a
        # headless seat needs before it answers "any number". Derived from the
        # compiled program (``ai_valuation.exiled_search_pile_comes_back``) and
        # carried on the prompt, so the resolver's stated policy is read off the
        # card rather than off the three cards that policy was written for.
        comes_back=(
            exiled_search_pile_comes_back(context.card)
            if context.card is not None else True
        ),
        _context=context,
    )
    game.log.append(f"{caster.name} is searching their {' and '.join(zones)}")
    return True, "pending_search_exile"


@effect_handler("exile_graveyard_until_leaves")
def exile_graveyard_until_leaves(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile all creature cards with mana value 3 or less from your graveyard
    until this artifact leaves the battlefield." (Idol of Endurance.)

    A **linked** exile (CR 400.7, CR 610.3): the pile is recorded on the
    permanent, not on the game, because what returns it is the permanent leaving
    and a record on the permanent goes wherever the permanent does. That is the
    same store Kitesail Freebooter's single card uses, and the same one
    ``remove_from_battlefield`` empties — the one transition out, so nothing has
    to remember to unwind this.

    Returning to the **graveyard** rather than the hand is the difference the
    entry's ``to`` records: these cards were exiled from a graveyard, and a card
    put back somewhere it never was is a card the effect created.
    """
    from ..subject_filters import card_matches_any

    source = context.source_permanent
    if source is None:
        game.log.append("the linked exile has no permanent to be linked to")
        return True, "resolved"
    caster = context.caster
    owner_index = game.players.index(caster)
    described = dict(instruction.payload.get("filter") or {})
    alternatives = (described,) if described else ()
    taken = [card for card in caster.graveyard if card_matches_any(card, alternatives)]
    if not taken:
        game.log.append(f"{caster.name} has no matching card in their graveyard")
        return True, "resolved"
    for card in taken:
        caster.graveyard.remove(card)
        caster.exile.append(card)
        link_exiled_card(
            source, card, owner_index, to="graveyard", ends_on=(LEAVES,)
        )
    game.log.append(
        f"{source.card.name} exiles {', '.join(card.name for card in taken)} "
        f"from {caster.name}'s graveyard"
    )
    return True, "resolved"


def _note_counters(permanent) -> dict[str, int]:
    """Every counter on *permanent*, by kind — what Tawnos's Coffin "notes".

    Keyed by the engine's own metadata spelling, so nothing here has to
    enumerate which kinds of counter exist; :func:`restore_noted_counters` is
    the half that knows +1/+1 is not a plain number.
    """
    noted: dict[str, int] = {}
    for key, value in permanent.metadata.items():
        if not key.endswith("_counters") or not isinstance(value, int) or value <= 0:
            continue
        noted[key] = int(value)
    plus = int(permanent.metadata.get("plus_counters", 0) or 0)
    if plus > 0:
        noted["plus_counters"] = plus
    return noted


def restore_noted_counters(game, permanent, noted: dict) -> None:
    """Put back the counters :func:`_note_counters` recorded.

    +1/+1 counters go through ``Game.place_plus1_counters``, the seam, not the
    library operation under it: a permanent that *enters with* counters has
    those counters put on it (CR 122.6), so CR 614 may change how many arrive
    and CR 603 may fire on their arrival — the two things the seam is for.

    Every other kind is CR 122.1's inert marker whose whole existence is the
    number, so the number is written back.
    """
    for key, count in (noted or {}).items():
        if key == "plus_counters":
            game.place_plus1_counters(permanent, int(count))
            continue
        permanent.metadata[key] = int(permanent.metadata.get(key, 0)) + int(count)


@effect_handler("exile_until_leaves_or_untaps")
def exile_until_leaves_or_untaps(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Tawnos's Coffin: "Exile target creature and all Auras attached to it.
    Note the number and kind of counters that were on that creature. When this
    artifact leaves the battlefield or becomes untapped, return that exiled card
    to the battlefield under its owner's control tapped with the noted number
    and kind of counters on it. If you do, return the other exiled cards …
    attached to that permanent."

    A **linked** exile (CR 400.7, CR 610.3) recorded on the permanent, which is
    the store Kitesail Freebooter and Idol of Endurance already use. What this
    card adds to it is a destination (the battlefield), a state to come back in
    (tapped, with the noted counters) and a relationship between the returned
    cards (the Auras go back onto the creature).

    The counters are **noted**, not derived, for the reason CR 608.2h exists: by
    the time the return runs the permanent is long gone, and the object that
    comes back is a new one (CR 400.7) with no counters at all.
    """
    from ..auras import auras_attached_to

    source = context.source_permanent
    if source is None:
        game.log.append("the linked exile has no permanent to be linked to")
        return True, "resolved"
    payload = instruction.payload
    victim = resolve_target_permanent(
        game, context,
        predicate=lambda candidate: permanent_matches_filter(candidate, payload),
    )
    if victim is None:
        game.log.append(f"{context.card.name}: no valid creature to exile")
        return True, "resolved"
    auras = list(auras_attached_to(victim))
    entries = [
        {
            "owner_index": game.owner_index_of(victim) or 0,
            "card": victim.card,
            "to": "battlefield",
            "tapped": True,
            "counters": _note_counters(victim),
        }
    ] + [
        {
            "owner_index": game.owner_index_of(aura) or 0,
            "card": aura.card,
            "to": "battlefield",
            # "…attached to that permanent" — the Auras go back onto the
            # creature the entry above brings with them, which is why they are
            # one record rather than two unrelated ones.
            "attach_to_returned": True,
        }
        for aura in auras
    ]
    game.remove_all_from_battlefield([victim, *auras])
    for entry, permanent in zip(entries, [victim, *auras]):
        game.players[int(entry["owner_index"])].exile.append(permanent.card)
        link_exiled_card(
            source, permanent.card, entry["owner_index"],
            to="battlefield",
            # The one ability in the pool whose exile ends on *either* event.
            ends_on=(LEAVES, UNTAPPED),
            tapped=bool(entry.get("tapped")),
            counters=entry.get("counters"),
            attach_to_returned=bool(entry.get("attach_to_returned")),
        )
    game.log.append(
        f"{context.card.name} exiled {victim.card.name}"
        + (f" and {len(auras)} Aura(s)" if auras else "")
    )
    return True, "resolved"


#: How each permission duration reads in the log, so the line says what the
#: card said rather than what the first card to print the sentence happened to
#: say. Absent means an unbounded grant, which reads as nothing at all.
_PERMISSION_DURATION_WORDS = {
    "end_of_turn": " this turn",
    "your_next_turn": " until their next turn",
    "your_next_upkeep": " until their next upkeep",
    "until_source_grants_again": " until it exiles another card",
    "while_exiled": " for as long as it remains exiled",
}


@effect_handler("grant_top_of_library_revealed")
def grant_top_of_library_revealed(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Until end of turn, for as long as that card remains on top of your
    library, **play with the top card of your library revealed**." (Temporal
    Aperture.)

    CR 400.2: the top card becomes a public object. ``engine/library_top.py``
    holds the record and answers the question for every reader — the web
    payload's ``library_top`` face among them — so this handler does nothing
    but arm it.

    A grant per resolution rather than one the card keeps: activating the
    artifact twice in a turn reveals whichever card the *second* shuffle turned
    up, and the first record simply stops holding the moment its own card is no
    longer first (CR 611.2b). Nothing has to retire it, which is the whole
    reason the state half of the duration needs no sweep.
    """
    from ..library_top import END_OF_TURN, TopRevealGrant, add_reveal_grant

    payload = instruction.payload
    source_name = context.card.name if context.card is not None else ""
    revealed = context.results.get(str(payload.get("cards_from") or ""))
    if revealed is None:
        # The reveal in front of this step found an empty library, so there is
        # no card the "for as long as" clause could be about — and a grant with
        # nothing to be about is one that could never end (CR 611.2b's "if the
        # duration never starts, the effect does nothing").
        game.log.append(f"{source_name}: nothing was revealed, so nothing is shown")
        return True, "resolved"
    lifetime = str(payload.get("duration") or "")
    if lifetime != END_OF_TURN:
        # The lowering admits only "until end of turn", and this is the reason
        # rather than a second copy of that rule: END_OF_TURN is the one
        # lifetime the cleanup sweep clears, so a record arriving with any other
        # would be a reveal nothing ever ends. Refused out loud here rather than
        # stored and forgotten.
        game.log.append(
            f"{source_name}: no sweep ends a top-of-library reveal that lasts "
            f"{lifetime or 'indefinitely'}"
        )
        return True, "resolved"
    add_reveal_grant(
        context.caster,
        TopRevealGrant(card=revealed, lifetime=lifetime, source_name=source_name),
    )
    game.log.append(
        f"{context.caster.name} plays with the top card of their library "
        f"revealed for as long as {revealed.name} remains on top"
    )
    return True, "resolved"


@effect_handler("grant_cast_permission")
def grant_cast_permission(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """A cast-or-play permission (CR 601.3) over cards in a named zone —
    engine/cast_permissions.py holds the state, the cast path asks it, and
    cleanup expires the turn-scoped grants. Three payload forms, matching the
    printed sentences the lowering admits.

    **Who is permitted is payload too.** "At the beginning of each player's
    upkeep, that player exiles a card at random from their hand. **The player**
    may play that card this turn." (Elkin Lair.) CR 601.3 grants the permission
    to the player the sentence names, and on this card that is a different seat
    every upkeep — never the ability's controller except on one turn in four.
    ``recipient`` carries it — the same key the mill, the discard and Thought
    Lash's library exile already spell "which seat is this instruction about" —
    read through the one reader of the printed phrase
    (``frozen_that_player_seat``), so the grant and the exile in front of it
    cannot land on two different players."""
    from ..cast_permissions import grant_permission

    caster = context.caster
    caster_index = game.players.index(caster)
    payload = instruction.payload
    duration = payload.get("duration")
    source_name = context.card.name if context.card is not None else ""
    if payload.get("recipient") == "event_subject_player":
        named = frozen_that_player_seat(game, context)
        if named is None:
            # A seat the trigger did not freeze is a permission handed to the
            # wrong player, which is worse than none at all: it would let the
            # ability's controller play a card out of somebody else's hand.
            game.log.append(
                f"{source_name}: no player was named to be given the permission"
            )
            return True, "resolved"
        grantee_index = named
    else:
        grantee_index = caster_index
    grantee = game.players[grantee_index]

    if payload.get("cards_from") == "exiled_cards":
        cards = list(context.results.get("exiled_cards") or [])
        if not cards:
            game.log.append(f"{source_name}: nothing was exiled, so there is nothing to permit")
            return True, "resolved"
        zone = payload.get("zone", "exile")
        # **Whose pile each card is in.** CR 400.3 sends an object to its
        # *owner's* zone, and a search of somebody else's library exiles a card
        # they own (Grinning Totem) — so the cards this permission names are not
        # always in the grantee's own exile, and a grant that assumed they were
        # would cover nothing at all. Read off the board rather than passed
        # down, because the step that exiled them is the only one that knew and
        # the answer is visible here.
        by_seat: dict[int | None, list] = {}
        for card in cards:
            seat = next(
                (
                    index for index, player in enumerate(game.players)
                    if any(held is card for held in getattr(player, zone, ()))
                ),
                grantee_index,
            )
            by_seat.setdefault(None if seat == grantee_index else seat, []).append(card)
        for zone_seat, held in by_seat.items():
            grant_permission(
                game, player_index=grantee_index, zone=zone,
                mode=payload.get("mode", "cast"), cards=held,
                duration=duration, source_name=source_name,
                source_permanent_id=game.permanent_id_of(context.source_permanent),
                zone_player_index=zone_seat,
            )
        game.log.append(
            f"{grantee.name} may {payload.get('mode', 'cast')} "
            f"{', '.join(card.name for card in cards)} from exile"
            + _PERMISSION_DURATION_WORDS.get(duration, "")
        )
        return True, "resolved"

    if payload.get("cards_from") == "revealed_card":
        # "Shuffle your library, then reveal the top card. Until end of turn,
        # for as long as that card remains on top of your library, … you may
        # play that card without paying its mana cost." (Temporal Aperture.)
        #
        # The card is the one the reveal in front of this step recorded, not
        # whatever is on top now: nothing has moved, but reading the library
        # again would be a second answer to a question one step already
        # answered, and the two come apart the moment a card printing this
        # sentence draws first.
        #
        # ``position="top"`` is the *other half of the printed duration* rather
        # than a narrowing — see ``cast_permissions.CastPermission.position``.
        # It is what makes the grant end when the card stops being on top, and
        # dropping it would leave the card playable from anywhere in the
        # library for the rest of the turn.
        revealed = context.results.get("revealed_card")
        if revealed is None:
            game.log.append(
                f"{source_name}: nothing was revealed, so there is nothing to permit"
            )
            return True, "resolved"
        grant_permission(
            game, player_index=grantee_index, zone="library",
            mode=payload.get("mode", "play"), cards=[revealed],
            position=payload.get("position"), free=bool(payload.get("free")),
            duration=duration, source_name=source_name,
            source_permanent_id=game.permanent_id_of(context.source_permanent),
        )
        game.log.append(
            f"{grantee.name} may play {revealed.name} from the top of their "
            f"library"
            + _PERMISSION_DURATION_WORDS.get(duration, "")
            + " for as long as it remains on top"
        )
        return True, "resolved"

    if payload.get("cards_from") == "exiled_with_source":
        # "…from among cards exiled with this artifact" (Idol of Endurance).
        # The pile is the permanent's own linked exile, read live: a card that
        # has already been cast this turn has left the exile zone, and
        # ``_covers`` refuses it there rather than needing this list pruned.
        from ..subject_filters import card_matches_any

        source = context.source_permanent
        described = dict(payload.get("filter") or {})
        alternatives = (described,) if described else ()
        cards = [
            entry["card"] for entry in linked_entries(source)
            if int(entry.get("owner_index", -1)) == caster_index
            and card_matches_any(entry["card"], alternatives)
        ]
        if not cards:
            game.log.append(f"{source_name} has exiled nothing to cast")
            return True, "resolved"
        grant_permission(
            game, player_index=caster_index, zone="exile", mode="cast",
            cards=cards, free=bool(payload.get("free")),
            duration=duration, source_name=source_name,
            source_permanent_id=game.permanent_id_of(source),
        )
        game.log.append(
            f"{caster.name} may cast {', '.join(card.name for card in cards)} "
            f"from exile this turn"
        )
        return True, "resolved"

    if payload.get("target_graveyard_card"):
        # "target red instant or sorcery card from your graveyard" — always
        # the caster's own graveyard; the chosen index is honoured when it
        # names a legal card, else the first legal card stands in, the same
        # fallback every other stale-choice path takes.
        from ..object_colors import object_colors

        card_types = tuple(payload.get("card_types") or ())
        colors = tuple(payload.get("colors") or ())

        def _legal(card) -> bool:
            # ``card_has_type`` for ``cast_permissions._covers``' reason, and it
            # is the same question one step earlier: which card in the pile the
            # permission may name. The two disagreeing would offer a card the
            # permission then refuses.
            if card_types and not any(
                card_has_type(card, name) for name in card_types
            ):
                return False
            if colors and not any(
                color in object_colors(game, card, caster) for color in colors
            ):
                return False
            return True

        index = context.target_permanent_index
        chosen = None
        if isinstance(index, int) and 0 <= index < len(caster.graveyard):
            candidate = caster.graveyard[index]
            if _legal(candidate):
                chosen = candidate
        if chosen is None:
            chosen = next((card for card in caster.graveyard if _legal(card)), None)
        if chosen is None:
            game.log.append(f"{source_name}: no legal card in {caster.name}'s graveyard")
            return True, "resolved"
        grant_permission(
            game, player_index=caster_index, zone="graveyard", mode="cast",
            cards=[chosen], duration=duration,
            exile_instead=bool(payload.get("exile_instead")),
            source_name=source_name,
        )
        game.log.append(f"{caster.name} may cast {chosen.name} from their graveyard")
        return True, "resolved"

    if payload.get("blanket"):
        # "Until end of turn, you may cast instant and sorcery spells from the
        # top of your graveyard." (Bösium Strip.) No card is named, so
        # ``cards`` stays None and what the grant covers is re-asked of the
        # board on every read — which is what the printed sentence means: the
        # top of a graveyard is whatever is on top *now*, and a card resolved
        # at grant time would go on being castable after something else was
        # binned on top of it.
        grant_permission(
            game, player_index=caster_index, zone=payload.get("zone", "graveyard"),
            mode=payload.get("mode", "cast"), cards=None,
            card_types=tuple(payload.get("card_types") or ()),
            position=payload.get("position"),
            exile_instead=bool(payload.get("exile_instead")),
            duration=duration, source_name=source_name,
        )
        game.log.append(
            f"{caster.name} may cast "
            + " and ".join(payload.get("card_types") or ("any",))
            + " spells from the top of their graveyard this turn"
        )
        return True, "resolved"

    if payload.get("free"):
        grant_permission(
            game, player_index=caster_index, zone=payload.get("zone", "hand"),
            mode=payload.get("mode", "cast"), cards=None, free=True,
            duration=duration, source_name=source_name,
        )
        game.log.append(
            f"{caster.name} may cast spells from their hand without paying "
            "their mana costs this turn"
        )
        return True, "resolved"

    game.log.append(f"{source_name}: unrecognized cast permission payload")
    return True, "resolved"


def _merged_pick_filter(filters: tuple) -> dict:
    """One payload for the single-alternative case, empty otherwise.

    ``live_look_top_candidates`` OR's a tuple of alternatives; this keeps the
    older single-filter key meaningful for a caller that reads it, and returns
    nothing when the phrase named several — where no single dict can stand for
    the union without narrowing it.
    """
    return dict(filters[0]) if len(filters) == 1 else {}


@effect_handler("look_top_pick_to_hand")
def look_top_pick_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """See the Truth: look at the top N, put one into your hand and the rest
    on the bottom in any order — unless the spell was cast from anywhere other
    than the hand, in which case every looked-at card goes to the hand and
    there is nothing to choose. ``context.cast_from_zone`` is the field the
    permission-seam round added for exactly this sentence."""
    payload = instruction.payload
    # Whose library. "Target player looks at the top three cards of **their**
    # library" (Ashnod's Cylix) names a seat the activation chose, and the
    # looker and the pile are the same player by construction — the possessive
    # says so — so one lookup answers both. Every other card in this family
    # prints "your library", which is the ability's own controller and the key
    # is absent. A named looker the ability never chose does nothing at all:
    # looking at a library the card did not name would be worse than the
    # ability fizzling, and the pile is hidden, so nobody would see it.
    if payload.get("looker") == "target_player":
        if context.target not in game.players:
            game.log.append(f"{context.card.name}: no player chosen")
            return True, "resolved"
        caster = context.target
    else:
        caster = context.caster
    # "Look at the top X cards of **target opponent's** library. Exile one of
    # those cards…" (Sealed Fate.) The pile is the chosen player's and every
    # decision about it is the caster's — the one shape ``looker`` cannot say,
    # because there one seat answers both questions. A named pile the spell
    # never chose does nothing at all, for ``looker``'s reason: reading the
    # wrong library is worse than the spell fizzling, and the pile is hidden,
    # so nobody would see it.
    chooser = caster
    if payload.get("pile_owner") is not None:
        if context.target not in game.players:
            game.log.append(f"{context.card.name}: no player chosen")
            return True, "resolved"
        caster = context.target
    # "Look at **that many** cards" (Garruk's Harbinger): the number the firing
    # event carried, frozen by the fire site. An absent record looks at nothing
    # rather than falling back to a count the card never printed.
    from_trigger = payload.get("amount_from_trigger")
    if from_trigger is not None:
        amount = max(0, int((context.trigger_context or {}).get(from_trigger, 0)))
    else:
        amount = resolve_amount(payload.get("amount", 0), context.x_value)
    top_count = min(amount, len(caster.library))
    # Written before anything can end the step early: a pick that takes no
    # card (an empty library) took a card with no mana value, and the gain
    # behind it reads zero rather than whatever an earlier step left.
    if payload.get("record_pick"):
        context.results[str(payload["record_pick"])] = 0
    if top_count <= 0:
        game.log.append(f"{caster.name} has no cards to look at")
        return True, "resolved"
    if payload.get("all_to_hand_if_cast_elsewhere") and context.cast_from_zone != "hand":
        taken = [caster.library.pop(0) for _ in range(top_count)]
        caster.hand.extend(taken)
        game.log.append(
            f"{context.card.name} was cast from the {context.cast_from_zone}: "
            f"{caster.name} puts all {top_count} looked-at cards into their hand"
        )
        return True, "resolved"
    caster_index = game.players.index(caster)
    chooser_index = game.players.index(chooser)
    # "**Reveal** a number of cards from the top of your library …" (Eye of
    # Yawgmoth.) CR 701.20a shows the pile to every player, which is the whole
    # difference from the looks this handler otherwise performs (CR 701.20e) —
    # so it is recorded and logged by name, before the pick moves any of them.
    if payload.get("revealed"):
        shown = [card.name for card in caster.library[:top_count]]
        game.record_reveal(caster_index, shown)
        game.log.append(f"{caster.name} reveals {', '.join(shown)}")
    # The narrowing, the optionality and the order the rest go back in all ride
    # the prompt, so what is offered, what an answer is checked against and what
    # a non-interactive seat takes are one rule (``live_look_top_candidates``).
    game.arm_pending_choice(
        "look_top_pick", chooser_index,
        # Whose library is looked through, when that is not the seat answering.
        # Absent for every card but Sealed Fate, so those prompts carry exactly
        # the data they always did.
        **({"pile_index": caster_index} if chooser_index != caster_index else {}),
        top_count=top_count, amount=amount, card_name=context.card.name,
        filter=_merged_pick_filter(payload.get("filters") or ()),
        filters=tuple(payload.get("filters") or ()),
        optional=bool(payload.get("optional")),
        rest_order=payload.get("rest_order", "any"),
        rest_destination=payload.get("rest_destination", "library_bottom"),
        pick_destination=payload.get("pick_destination", "hand"),
        # "Put **two** of them into your hand" (Ancestral Memories): how many
        # picks are still owed. One is every other card in the family, and the
        # answer path re-arms the prompt while more are owed — see
        # `_resolve_look_top_pick`.
        remaining=max(1, int(payload.get("pick_count", 1))),
        # "…You gain life equal to that card's mana value." (Reviving Vapors.)
        # Where the answer writes the taken card's mana value, for the step of
        # this same resolution that reads it. Absent for every other printing.
        **(
            {"_record_pick": (context, str(payload["record_pick"]))}
            if payload.get("record_pick") else {}
        ),
    )
    game.log.append(
        f"{chooser.name} is looking at the top {top_count} cards of "
        + ("their library" if chooser is caster else f"{caster.name}'s library")
    )
    return True, "pending_look_top_pick"


@effect_handler("look_top_exile_random")
def look_top_exile_random(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Orcish Librarian: "Look at the top eight cards of your library. Exile
    four of them at random, then put the rest on top of your library in any
    order."

    Nothing here is a decision until the last clause. The exile is at random —
    ``random.sample`` over the module RNG ``run_ai_simulation`` seeds, so a
    seed replays a run exactly — and the rest going back **on top** is the
    order the player chooses, asked through the ``reorder_library`` prompt this
    shares with ``look_top_pick_to_hand``'s top-destination tail.

    A library shorter than the card's number is not an error: CR 609.3-style
    "as many as you can" is the general rule for a count over a zone, so what is
    there is what is looked at and the exile is capped to it.
    """
    caster = context.caster
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    top_count = min(amount, len(caster.library))
    if top_count <= 0:
        game.log.append(f"{caster.name} has no cards to look at")
        return True, "resolved"
    exile_count = min(
        resolve_amount(instruction.payload.get("exile_count", 0), context.x_value),
        top_count,
    )
    looked = caster.library[:top_count]
    del caster.library[:top_count]
    exiled_slots = set(random.sample(range(top_count), exile_count))
    rest = [card for index, card in enumerate(looked) if index not in exiled_slots]
    for index in sorted(exiled_slots):
        caster.exile.append(looked[index])
    caster.library[:0] = rest
    game.log.append(
        f"{caster.name} looked at the top {top_count} cards and exiled "
        f"{exile_count} at random"
    )
    if len(rest) > 1:
        seat = game.seat_index(caster)
        game.arm_pending_choice(
            "reorder_library", seat,
            target_index=seat, top_count=len(rest), may_shuffle=False,
        )
        return True, "pending_reorder_library"
    return True, "resolved"


@effect_handler("discard_controller_cards")
def discard_controller_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…discard a card." with the effect's own controller as the implied
    subject (Jeskai Elder's "You may draw a card. If you do, discard a card.").
    The same pending choice the targeted discard arms, pointed at the caster —
    who picks the cards, exactly as the printed sentence leaves it to them."""
    caster = context.caster
    # "Discard a **creature** card" (Crypt Lurker): the payment comes from the
    # cards the printed phrase names, so the count is bounded by *those* rather
    # than by the hand. The filter rides the prompt so what is offered, what the
    # answer is checked against and what a non-interactive seat takes are one
    # rule (see ``live_discard_candidates``).
    described = dict(instruction.payload.get("filter") or {})
    eligible = [card for card in caster.hand
                if _card_matches_filter(card, described, game=game, owner=caster)]
    # "Discard **any number of** creature cards" (Mind Maggots): a ceiling with
    # no printed number, so the bound is however many cards the phrase names in
    # this hand — a number only the resolution knows, which is why the lowering
    # sends a flag rather than an amount. `up_to` then makes it a ceiling: "any
    # number" includes none, and a required count would force the whole hand out.
    any_number = bool(instruction.payload.get("any_number"))
    amount = (
        len(eligible) if any_number else
        min(
            resolve_amount(instruction.payload.get("amount", 0), context.x_value),
            len(eligible),
        )
    )
    # Recorded before the prompt, and again with the real number when it is
    # answered: "…for each card discarded this way" has to read a zero when
    # there was nothing to discard, not a key the scratchpad never grew.
    context.results["discarded_count"] = 0
    # And the per-seat tally, for the same reason and at the same moment. One
    # number cannot answer "how many did **they** discard" once the discard is
    # offered to every player (Mind Bomb): the last seat to answer would decide
    # everybody's number. Seeded to zero here so a seat with nothing to discard
    # reads as zero rather than as a seat the record never mentions.
    player_seat = game.players.index(caster)
    by_seat = context.results.setdefault(DISCARDED_BY_SEAT, {})
    by_seat[player_seat] = 0
    if amount <= 0:
        game.log.append(f"{caster.name} has no cards to discard")
        return True, "resolved"
    game.arm_pending_choice(
        "discard", player_seat,
        count=amount,
        # Only when the phrase printed a ceiling, so every discard written
        # before "any number of" existed arms a byte-identical choice.
        **({"up_to": True} if any_number else {}),
        filter=described,
        allow_top_of_library=game._controls_top_of_library_discard(caster),
        # The live scratchpad, so the answer can record how many were actually
        # discarded for the steps queued behind this prompt (see
        # ``_after_discard_answered``). Private: it holds engine objects and is
        # none of a client's business.
        _results=context.results,
    )
    game.log.append(
        f"{caster.name} may discard up to {amount} card(s)" if any_number
        else f"{caster.name} must choose {amount} card(s) to discard"
    )
    return True, "pending_discard"


@effect_handler("discard_then_draw_that_many")
def discard_then_draw_that_many(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Discard up to two cards, then draw that many cards." (Kinetic Augur.)

    One instruction because the second number *is* the answer to the first: how
    many are drawn is however many the player chose to discard, and that choice
    is a pending prompt. Two instructions would run the draw while the prompt was
    still owed and draw nothing at all.

    The prompt carries the follow-on rather than the resolution carrying it,
    which is the same arrangement Library of Leng's ``to_library`` already rides
    on: what happens when a discard is answered belongs to the discard.
    """
    caster = context.caster
    amount = min(
        resolve_amount(instruction.payload.get("amount", 0), context.x_value),
        len(caster.hand),
    )
    if amount <= 0:
        game.log.append(f"{caster.name} has no cards to discard")
        return True, "resolved"
    game.arm_pending_choice(
        "discard", game.players.index(caster),
        count=amount,
        up_to=bool(instruction.payload.get("up_to")),
        draw_that_many=True,
        allow_top_of_library=game._controls_top_of_library_discard(caster),
    )
    game.log.append(
        f"{caster.name} may discard up to {amount} card(s), then draws that many"
    )
    return True, "pending_discard"


@effect_handler("put_graveyard_card_on_library_bottom")
def put_graveyard_card_on_library_bottom(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put target card from your graveyard on the bottom of your library."
    (Epitaph Golem.) Honours the chosen graveyard index, else takes the first
    card — the stale-choice fallback every other graveyard reader uses."""
    caster = context.caster
    if not caster.graveyard:
        game.log.append(f"{context.card.name}: no card in the graveyard to bottom")
        return True, "resolved"
    idx = context.target_permanent_index
    if not (isinstance(idx, int) and 0 <= idx < len(caster.graveyard)):
        idx = 0
    # "Put target **Rebel** card …" (Lin Sivvi, Defiant Hero). A narrowed
    # payload is re-checked against the card in the chosen slot through the one
    # predicate the picker and the activation gate asked, so neither a stale
    # index nor the fallback above can bottom a card the sentence never named
    # (CR 608.2b: an illegal target is not acted on). The empty payload is
    # Epitaph Golem's "target card", which any card answers.
    if instruction.payload and not graveyard_card_matches(
        instruction.payload, caster.graveyard[idx]
    ):
        game.log.append(
            f"{context.card.name}: the chosen card is no longer a legal target"
        )
        return True, "resolved"
    card = caster.graveyard.pop(idx)
    game.put_card_into_library(caster, card)
    game.log.append(f"{context.card.name}: {card.name} put on the bottom of {caster.name}'s library")
    return True, "resolved"


@effect_handler("put_top_of_graveyard_on_library_bottom")
def put_top_of_graveyard_on_library_bottom(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put the top card of your graveyard on the bottom of your library."
    (Soldevi Digger.)

    The *top* of a graveyard is the card most recently put there (CR 404.1: a
    graveyard is an ordered pile), which in this engine is the last element —
    every path into a graveyard appends. So it is ``pop()``, not the ``pop(0)``
    its targeted neighbour above falls back to: that one is a stale-choice
    default for a card somebody chose, and this one is the printed position.

    An empty graveyard moves nothing. CR 608.2's "as much as possible" — the
    ability still resolves, and the cost was paid at activation either way.
    """
    caster = context.caster
    if not caster.graveyard:
        game.log.append(f"{context.card.name}: no card in the graveyard to bottom")
        return True, "resolved"
    card = caster.graveyard.pop()
    game.put_card_into_library(caster, card)
    game.log.append(
        f"{context.card.name}: {card.name} put on the bottom of "
        f"{caster.name}'s library"
    )
    return True, "resolved"


@effect_handler("return_spell_or_creature_to_hand")
def return_spell_or_creature_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return target spell or creature to its owner's hand." (Unsubstantiate.)
    A chosen spell is unstacked to its owner's hand — not countered, so
    nothing is binned and no counter triggers fire; a chosen creature is the
    ordinary bounce."""
    chosen = context.stack_target
    # By identity, as every other leave-the-stack site walks it: a
    # ``StackItem`` compares by value, so two casts of one card with one target
    # are equal and ``in``/``remove`` would find whichever sits lower.
    slot = next(
        (index for index, item in enumerate(game.stack) if item is chosen), None
    )
    if chosen is not None and slot is not None:
        del game.stack[slot]
        if chosen.is_copy:
            # CR 707.10a: a copy of a spell leaving the stack ceases to exist —
            # it has no card to put in anybody's hand.
            game.log.append(
                f"{context.card.name} returned {chosen.card.name} (copy) from "
                "the stack, and it ceases to exist"
            )
            return True, "resolved"
        # "to its **owner's** hand" (CR 108.3) — the stack object's owner, who
        # is not its caster when it was cast out of another player's zone.
        owner = game.players[chosen.owner_index]
        game.put_card_into_hand(owner, chosen.card)
        game.log.append(
            f"{context.card.name} returned {chosen.card.name} from the stack "
            f"to {owner.name}'s hand"
        )
        return True, "resolved"
    bounced = game._bounce_target_creature(
        resolve_target_permanent(game, context)
    )
    game.log.append(
        "Returned creature to hand" if bounced else f"{context.card.name}: nothing was returned"
    )
    return True, "resolved"


@effect_handler("shuffle_hand_cards_into_library")
def shuffle_hand_cards_into_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Shuffle **a card** from your hand into your library." (Lat-Nam's Legacy.)

    The whole-hand shuffle below with a number in front of it, and a different
    handler for the one reason that matters: a counted subset of a hidden zone
    is a *decision*. CR 402.1 lets only its owner look at a hand, so nobody else
    can pick, and the pick has to be asked rather than taken — which is what
    arming the prompt does and what the sweep below has nothing to do.

    The prompt is ``hand_to_library``, the one Brainstorm already uses, with the
    shuffle as a flag on it. The two sentences differ by where the cards land
    and by nothing else: both take a chosen number out of a hand and put them in
    the library through the two seams (``take_card_from_hand``,
    ``put_card_into_library``), and a second prompt kind would be a second copy
    of that, free to forget one of them.

    **Not a discard.** CR 701.9a makes discarding an action abilities watch, and
    none of that is happening here — the same distinction the handler below the
    prompt already draws.

    An empty hand moves nothing, and the "if you do" behind this reads the count
    rather than the answer: CR 608.2 does as much as it can, and with no card to
    move the sentence did not happen.
    """
    player = context.caster
    # "Shuffle **any number of** cards from your hand into your library, then
    # draw that many cards." (Credit Voucher.) The same move with the count left
    # to the hand's owner, so the prompt carries a *ceiling* — the whole hand —
    # and `up_to` lets the answer be smaller. CR 402.1 is why it is asked at all
    # and CR 601.2b-style announcement is why the number is not known here.
    open_ended = bool(instruction.payload.get("any_number"))
    if open_ended:
        actual = len(player.hand)
    else:
        amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
        actual = min(amount, len(player.hand))
    # Recorded before the prompt and whatever the answer is, exactly as the
    # Brainstorm handler records its own count: the number is settled here and
    # the prompt only decides which cards. "If you do, draw two cards at the
    # beginning of the next turn's upkeep" is the step that reads it.
    #
    # For the open-ended spelling the number is *not* settled here — it is
    # whatever the answer says — so what is recorded is the ceiling, and the
    # draw that reads the real number is performed by the answer itself rather
    # than by a later step reading this key.
    context.results[HAND_CARDS_TO_LIBRARY] = actual
    if actual <= 0:
        game.log.append(f"{player.name} has no card to shuffle away")
        return True, "resolved"
    game.arm_pending_choice(
        "hand_to_library", game.players.index(player),
        count=actual, shuffle=True,
        **(
            {"up_to": True, "draw_after": bool(instruction.payload.get("then_draw"))}
            if open_ended else {}
        ),
    )
    game.log.append(
        f"{player.name} must choose "
        + (f"up to {actual}" if open_ended else f"{actual}")
        + " card(s) to shuffle into their library"
    )
    return True, "pending_hand_to_library"


@effect_handler("shuffle_hand_into_library")
def shuffle_hand_into_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Winds of Change: "Each player shuffles the cards from their hand into
    their library, then draws that many cards."

    CR 701.24 — the cards move and the library is shuffled as one action, so
    the count the draw reads is taken *before* the move and nothing can observe
    a half-moved zone. Each player is one whole shuffle-then-draw: the libraries
    are separate, so no seat's draw can see another's cards whichever order the
    loop runs in.

    The draw goes through ``_draw_with_replacements``. A player whose draw is
    replaced (Aladdin's Lamp, Teferi's Ageless Insight) gets that replacement
    here exactly as they would in their draw step; ``PlayerState.draw`` would
    skip every armed one.
    """
    whose = str(instruction.payload.get("whose", "you"))
    if whose == "each_player":
        players = [player for player in game.players if not player.lost]
    elif whose == "you":
        players = [context.caster]
    else:  # pragma: no cover - the lowering admits no other subject
        return False, "no player to shuffle"
    then_draw = bool(instruction.payload.get("then_draw"))
    # "…, **then draws seven cards**." (Time Spiral.) The printed number, which
    # is not what moved: a player whose hand and graveyard were both empty still
    # draws a full grip, so this count is applied whatever the shuffle took —
    # which is exactly what the ``and moved`` guard below is for the other
    # spelling and must not be for this one.
    then_draw_count = instruction.payload.get("then_draw_count")
    # "…their hand **and graveyard** into their library." (Diminishing Returns.)
    # The second pile joins the *same* move, which is why it rides this
    # instruction: CR 701.24 randomises the library once, and a graveyard
    # shuffle written as a statement after this one would shuffle it twice with
    # the hand's cards already down among the graveyard's.
    with_graveyard = bool(instruction.payload.get("with_graveyard"))
    for player in players:
        moved = len(player.hand)
        # Through the library seam, not a bare extend: CR 903.9b has no single
        # fire site, and a commander shuffled in from a hand is exactly the
        # "would be put into its owner's library from anywhere" the rule names.
        for card in list(player.hand):
            game.put_card_into_library(player, card)
        player.hand.clear()
        buried = 0
        if with_graveyard:
            buried = len(player.graveyard)
            for card in list(player.graveyard):
                game.put_card_into_library(player, card)
            player.graveyard.clear()
        # Through the module-level RNG every other shuffle uses, so a seeded run
        # stays reproducible (the determinism invariant).
        random.shuffle(player.library)
        game.log.append(
            f"{player.name} shuffled {moved} card(s) from their hand"
            + (f" and {buried} from their graveyard" if with_graveyard else "")
            + " into their library"
        )
        if then_draw_count is not None:
            game._draw_with_replacements(player, int(then_draw_count))
        elif then_draw and moved:
            game._draw_with_replacements(player, moved)
    return True, "resolved"


@effect_handler("shuffle_graveyard_into_library")
def shuffle_graveyard_into_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Feldon's Cane: "{T}, Exile this artifact: Shuffle your graveyard into
    your library."

    CR 701.24a: the cards move and the library is shuffled as one action, so
    there is nothing to schedule and nothing that can observe a half-moved
    zone. The graveyard is emptied rather than filtered — every card in it
    goes, which is what "your graveyard" means.
    """
    whose = str(instruction.payload.get("whose", "you"))
    player = context.caster if whose == "you" else context.target
    if player is None:
        return False, "no player to shuffle"
    # "Target player shuffles **up to three target cards** from their graveyard
    # into their library." (Gaea's Blessing.) The moving cards were chosen at
    # announcement (CR 601.2c), so they are resolved as slots rather than
    # described — the same resolution ``put_graveyard_cards_on_library_top``
    # performs for the identical noun phrase one destination over, and through
    # the same predicate, so the picker and this cannot disagree about which
    # cards the line may name. An "up to" that named none is a legal
    # announcement and shuffles the library anyway (CR 701.24a).
    described_targets = instruction.payload.get("targets") or {}
    if described_targets:
        limit = (
            len(player.graveyard) if described_targets.get("unbounded")
            else min(int(described_targets.get("count") or 1), len(player.graveyard))
        )
        picked = _resolve_graveyard_slots(
            player, context, limit,
            lambda card: graveyard_card_matches(instruction.payload, card),
        )
        # ``_resolve_graveyard_slots`` has already taken them out of the pile,
        # highest slot first, which is the only way two copies of one card can
        # be told apart there (they are one ``CardDefinition`` object).
        for card in picked:
            game.put_card_into_library(player, card, position="top")
        random.shuffle(player.library)
        game.log.append(
            f"{player.name} shuffled {len(picked)} chosen card(s) from their "
            "graveyard into their library"
        )
        return True, "resolved"
    # "Shuffle **all creature cards** from your graveyard into your library."
    # (Barishi.) The named subset, tested by ``graveyard_card_matches`` — the
    # one predicate this engine has for a printed noun phrase over a graveyard,
    # so the phrase means here what it means in every return that reads it. The
    # key's absence is Feldon's Cane's whole pile, which is why the loop below
    # is one loop rather than two paths.
    described = instruction.payload.get("cards")
    if described:
        moving = [c for c in player.graveyard if graveyard_card_matches(described, c)]
    else:
        moving = list(player.graveyard)
    moved = len(moving)
    # By identity, and one pass: a graveyard holding two copies of one card is
    # the reason ``list.remove`` is not used anywhere near a zone in this
    # engine, and the survivors are what stays.
    moving_ids = {id(card) for card in moving}
    player.graveyard[:] = [c for c in player.graveyard if id(c) not in moving_ids]
    player.library.extend(moving)
    # Through the module-level RNG every other shuffle uses, so a seeded run
    # stays reproducible (the determinism invariant). CR 701.24a: the library is
    # shuffled even when nothing moved into it, because the sentence says to.
    random.shuffle(player.library)
    game.log.append(
        f"{player.name} shuffled {moved} card(s) from their graveyard into their library"
    )
    return True, "resolved"


@effect_handler("shuffle_source_card_into_library")
def shuffle_source_card_into_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When this creature dies, shuffle **it** into its owner's library."
    (Alabaster Dragon.)

    The ability's own card, printed with **no source zone** — so like
    ``return_source_card_to_owners_hand`` this reaches whichever zone actually
    holds it rather than one it assumes. Usually the graveyard, since CR 404.1
    put it there before the trigger resolved; the battlefield branch is for a
    caller that resolves the stack with no state-based check in between.

    Located by identity across **every** graveyard, not the resolving seat's:
    CR 404.1 files a card under its *owner*, and a creature that changed hands
    before it died is in the other player's pile. ``put_card_into_library`` is
    the seam rather than an append, for CR 903.9b's reason — a commander goes to
    the command zone instead, and thirty fire sites is twenty-nine places to
    forget it.

    The shuffle happens even when the card has already left — exiled in
    response from the graveyard — because CR 701.24c says so outright, with
    Guile (the same printed sentence) as its example: "that library is
    shuffled even if none of those objects are in the zone they're expected to
    be in". It is the reason a player cannot read the deck for the answer.
    """
    card = context.card
    source = context.source_permanent
    owner = None
    if source is not None and game.is_on_battlefield(source):
        owner = game.players[source.metadata.get("base_controller_index", 0)]
        game.remove_from_battlefield(source)
        game.put_card_into_library(owner, card, from_battlefield=source)
    else:
        for player in game.players:
            found = next(
                (i for i, held in enumerate(player.graveyard) if held is card), None
            )
            if found is not None:
                player.graveyard.pop(found)
                owner = player
                game.put_card_into_library(player, card)
                break
    if owner is None:
        # Nothing to move. The library is still shuffled — the sentence names
        # one, and a player who could tell "the card was gone" from "the card
        # came back" by watching the deck would know something the card never
        # tells them.
        owner = context.caster
        game.log.append(f"{card.name} was no longer in a graveyard")
    else:
        game.log.append(f"{card.name} was shuffled into {owner.name}'s library")
    random.shuffle(owner.library)
    return True, "resolved"


@effect_handler("shuffle_target_permanent_into_library")
def shuffle_target_permanent_into_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{2}, {T}: Shuffle target nontoken permanent you control into its owner's
    library." (Rishadan Pawnshop.)

    A zone change, not a destruction: nothing dies, no regeneration applies and
    no dies-trigger fires. The card lands in its **owner's** library
    (CR 400.3/CR 108.3), asked through ``Game.owner_index_of`` — the one
    accessor for that question, never a field read here — so a permanent stolen
    from the other seat goes back into *their* deck, not the activator's. The
    printed phrase says "you control" and CR 400.3 says whose library, and those
    are two different players exactly when it matters.

    The printed noun phrase is re-asked here through ``subject_matches``, the
    same answer the picker enumerated with: CR 608.2b only says the target must
    still be *legal*, and a permanent that stopped being nontoken or changed
    hands since the announcement is no longer what the card described.

    ``put_card_into_library`` is the seam rather than an append, for CR 903.9b's
    reason — a commander headed for a library goes to the command zone instead —
    and the shuffle is part of the move rather than a step after it
    (CR 701.24a).

    A target that has left is CR 608.2b's "does as much as it can": nothing
    moves. The library is still shuffled, because the sentence names one and a
    player who could tell "it worked" from "it fizzled" by watching the deck
    would know something the card never tells them (CR 701.24c).
    """
    from ..subject_filters import subject_matches

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = game.players.index(context.caster)
    target_perm = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described, observer=observer,
            source=context.source_permanent,
        ),
        fallback_on_invalid_choice=False,
    )
    if target_perm is None or not game.is_on_battlefield(target_perm):
        game.log.append(f"{context.card.name}: no valid permanent to shuffle away")
        random.shuffle(context.caster.library)
        return True, "resolved"
    owner_index = game.owner_index_of(target_perm)
    owner = (
        game.players[owner_index] if owner_index is not None else context.caster
    )
    card = target_perm.card
    game.remove_from_battlefield(target_perm)
    game._remove_aura_effects(target_perm)
    game.put_card_into_library(owner, card, from_battlefield=target_perm)
    random.shuffle(owner.library)
    game.log.append(
        f"{context.card.name}: {card.name} was shuffled into "
        f"{owner.name}'s library"
    )
    return True, "resolved"


@effect_handler("name_then_reveal_top")
def name_then_reveal_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Petra Sphinx: "Target player chooses a card name, then reveals the top
    card of their library. If that card has the chosen name, that player puts
    it into their hand. If it doesn't, the player puts it into their
    graveyard."

    One handler because the three sentences are one procedure: the name decides
    where the card goes, and neither the name nor the revealed card exists
    before this resolution begins (CR 608.2). The choosing seat is the targeted
    player's, and so is the library, the hand and the graveyard — the card
    never says "you" anywhere.

    The card is **not** turned over here. It is revealed as part of answering
    the prompt, because a reveal before the name is chosen would show the
    chooser what to name.
    """
    target = context.target
    if target is None:
        game.log.append(f"{context.card.name}: no player to ask")
        return True, "resolved"
    seat = game.players.index(target)
    if not target.library:
        # CR 701.20a: there is nothing to reveal, so nothing is named either —
        # the choice would decide the destination of a card that does not
        # exist. An empty library is not a loss here; the draw step is.
        game.log.append(f"{context.card.name}: {target.name} has no library to reveal")
        return True, "resolved"
    game.arm_pending_choice(
        "name_then_reveal_top", seat,
        card_name=context.card.name,
        match_zone=instruction.payload.get("match_zone", "hand"),
        miss_zone=instruction.payload.get("miss_zone", "graveyard"),
        # A player knows what is in their own library, only not its order
        # (CR 400.2), so naming its commonest remaining card is a choice a
        # human at the table could make — and it is deterministic, which is
        # what a seeded replay needs. Basic lands are in: this card prints no
        # restriction, and CR 202.1 lets a player name any card.
        default_name=_commonest_visible_name(
            game, seat, ("library",), exclude_basics=False
        ),
        # "…and this artifact deals 2 damage to them" (Vexing Arcanix): the
        # miss branch's second half. The source travels with it because by the
        # time the prompt is answered this resolution has returned, and a
        # damage event needs to know what dealt it (colour-scoped prevention,
        # CR 702.16i protection, "a source you control").
        miss_damage=int(instruction.payload.get("miss_damage", 0) or 0),
        _damage_source=context.source_permanent or context.card,
    )
    return True, "pending_name_then_reveal_top"


#: Where the repeated pick keeps the cards it has already offered, on the
#: resolution's own scratchpad. Written here and read by the prompt's resolver
#: through the context it carries, because the loop spans several prompts and
#: nothing on a board records a choice.
FORGOTTEN_PICKS = "repeated_graveyard_picks"


@effect_handler("repeated_graveyard_pick")
def repeated_graveyard_pick(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Forgotten Lore: "Target opponent chooses a card in your graveyard. You
    may pay {G}. If you do, repeat this process except that opponent can't
    choose a card already chosen for Forgotten Lore. Then put the last chosen
    card into your hand."

    One round of the loop: the opponent picks, and answering that prompt offers
    the caster the cost that buys another round. The chain runs through the
    pending-choice queue rather than a Python loop, because two different seats
    answer alternately and neither answer is available when this returns.

    The exclusion set and the last pick live on ``context.results``, which every
    round of the chain shares — the `optional_pay` entry carries this same
    context, so the instruction that re-arms the prompt sees what the previous
    rounds recorded.

    Nothing left to choose ends the process, which is the other way out of it
    besides declining: the printed "repeat" cannot repeat over an empty
    graveyard, and the last card chosen is still put into the hand.
    """
    caster = context.caster
    opponent = context.target
    if opponent is None or opponent is caster:
        game.log.append(f"{context.card.name}: no opponent to choose")
        return True, "resolved"
    already = context.results.setdefault(FORGOTTEN_PICKS, [])
    legal = [
        index
        for index, card in enumerate(caster.graveyard)
        if not any(card is taken for taken in already)
    ]
    if not legal:
        _finish_repeated_graveyard_pick(game, context)
        return True, "resolved"
    game.arm_pending_choice(
        "graveyard_pick_for_price", game.players.index(opponent),
        card_name=context.card.name,
        owner_index=game.players.index(caster),
        legal_indices=legal,
        cost=dict(instruction.payload.get("cost") or {}),
        _instruction=instruction,
        _context=context,
    )
    game.log.append(
        f"{opponent.name} must choose a card in {caster.name}'s graveyard "
        f"({context.card.name})"
    )
    return True, "pending_graveyard_pick_for_price"


def _finish_repeated_graveyard_pick(game: Game, context: OracleExecutionContext) -> None:
    """"Then put the **last chosen** card into your hand." — the pick the loop
    stopped on, whichever way it stopped.

    By identity in the caster's own graveyard: a graveyard is a list of card
    definitions and two copies of a card are the same object, so a name match
    would take whichever one came first.
    """
    caster = context.caster
    picks = context.results.get(FORGOTTEN_PICKS) or []
    if not picks:
        game.log.append(f"{context.card.name}: nothing was chosen")
        return
    last = picks[-1]
    for index, held in enumerate(caster.graveyard):
        if held is last:
            caster.graveyard.pop(index)
            game.put_card_into_hand(caster, last)
            game.log.append(
                f"{caster.name} put {last.name} into their hand "
                f"({context.card.name})"
            )
            return
    game.log.append(f"{last.name} was no longer in {caster.name}'s graveyard")


@effect_handler("finish_repeated_graveyard_pick")
def finish_repeated_graveyard_pick(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Then put the last chosen card into your hand." (Forgotten Lore.)

    The decline branch of the loop's payment offer, and its own instruction
    because the loop can also end by running the graveyard out — two ways in,
    one sentence.
    """
    _finish_repeated_graveyard_pick(game, context)
    return True, "resolved"


@effect_handler("put_exiled_cards_into_zone")
def put_exiled_cards_into_zone(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Necropotence: "Put that card into your hand at the beginning of your next
    end step."

    Grinning Totem: "At the beginning of your next upkeep, if you haven't played
    it, put it into its owner's graveyard."

    The cards a step of the same effect exiled, read out of the resolution
    scratchpad — which for a *delayed* ability is the copy frozen when it was
    created (CR 603.7d, ``DelayedTrigger.captured``). Nothing else could name
    them: by the time the step arrives the exile zone holds whatever else has
    gone there since, and a card in it is not distinguishable by name.

    Located by **identity**, in whichever seat's exile holds it. That is one
    rule and not two: a card is in exactly one exile list, so this finds the
    same card the caster-only scan found whenever there was one, and it differs
    only where the card is somebody else's — which is Grinning Totem's, because
    CR 400.3 put the searched player's card into the searched player's exile.

    A card that has already left is not conjured back, and that is also where
    Grinning Totem's printed condition is enforced: "if you haven't played it"
    is true exactly when the card is still in exile, because playing it took it
    out. (It is not the *permission* that answers — a "your next upkeep" grant
    is swept as the upkeep step begins, before this ability can fire, so by the
    time the question is asked every such grant is gone whether it was used or
    not.) ``only_if_unplayed`` is the printed word, carried so the log can say
    which case it took.
    """
    # Two places one record can be, and which one depends on how far the
    # sentence travelled. Inside a single resolution it is the scratchpad; a
    # *delayed* ability's creation froze the whole scratchpad into the entry
    # (CR 603.7d) and it arrives as the trigger's captured context. Reading only
    # the first is why this fired at the end step and found nothing.
    cards = list(
        (context.trigger_context or {}).get("exiled_cards")
        or context.results.get("exiled_cards")
        or ()
    )
    caster = context.caster
    destination = str(instruction.payload.get("zone", "hand"))
    moved: list = []
    # The caster's own pile first, then everybody else's. Identity alone is not
    # enough to pick the pile: a deck repeats one immutable ``CardDefinition``
    # per copy and the catalog is shared between seats, so *the same object* can
    # sit in two players' exiles at once — and a bare scan would then take
    # whichever seat came first in the list. Necropotence's card is always its
    # controller's, so asking that pile first keeps it exactly where it was, and
    # the wider scan is reached only by the card that needs it.
    seats = [context.caster] + [p for p in game.players if p is not context.caster]
    for card in cards:
        for owner in seats:
            # Through the departure seam, which locates the copy by identity and
            # retires the exile record with it — a stale record is inert until
            # the *same* card is exiled again by something else, when it would
            # come back to life still saying "face down" (CR 400.7, 406.7).
            if not game.take_card_from_exile(owner, card):
                continue
            if destination == "graveyard":
                # CR 400.3: its **owner's** graveyard, and the owner is the
                # player whose exile held it — the card reached that pile out of
                # that player's own library. Through the write seam like the
                # hand branch below: the graveyard gained one at Mirage's third
                # wave (Forbidden Crypt's "if a card would be put into your
                # graveyard from anywhere"), and this line was written a merge
                # earlier when there was none. The guard is what said so.
                if game.put_card_into_graveyard(owner, card):
                    moved.append(card)
            # Through the write seam, so CR 903.9b rides it. "…its **owner's**
            # hand" (Psychic Theft) is the seat whose exile held it.
            elif game.put_card_into_hand(
                owner if instruction.payload.get("to_owner") else caster, card
            ):
                moved.append(card)
            break
    if moved:
        names = ", ".join(card.name for card in moved)
        game.log.append(
            f"{caster.name} put {names} into their hand from exile"
            if destination == "hand"
            else f"{names} was put into its owner's graveyard from exile"
        )
    elif instruction.payload.get("only_if_unplayed"):
        game.log.append(
            f"{context.card.name}: the exiled card was played, so nothing is binned"
        )
    else:
        game.log.append(f"{context.card.name}: nothing was left in exile to take")
    return True, "resolved"


@effect_handler("exile_bound_card_from_graveyard")
def exile_bound_card_from_graveyard(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Necropotence: "Whenever you discard a card, exile that card from your
    graveyard."

    The card the discard announced, located by **identity** in the graveyard it
    was put into. A name match would find the wrong copy: a graveyard is a list
    of ``CardDefinition`` and every copy of a card in a deck is the same
    immutable object.

    Gone by the time this resolves — exiled in response, or moved by a
    replacement that sent the discard somewhere other than the graveyard
    (Library of Leng) — means the ability does nothing, which is CR 603.6's
    answer rather than a failure.
    """
    card = (context.trigger_context or {}).get("discarded_card")
    if card is None:
        return True, "resolved"
    owner = context.caster
    for index, held in enumerate(owner.graveyard):
        if held is card:
            owner.graveyard.pop(index)
            owner.exile.append(card)
            game.log.append(
                f"{card.name} was exiled from {owner.name}'s graveyard "
                f"({context.card.name})"
            )
            return True, "resolved"
    game.log.append(f"{card.name} was no longer in {owner.name}'s graveyard")
    return True, "resolved"


@effect_handler("name_then_consult")
def name_then_consult(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Demonic Consultation: "Choose a card name. Exile the top six cards of
    your library, then reveal cards from the top of your library until you
    reveal a card with the chosen name. Put that card into your hand and exile
    all other cards revealed this way."

    Nothing happens here but the question. **The order is the card**: the six
    cards are exiled after the name is fixed and without being looked at, so
    the name may be among them — which is why the exile lives in the answer
    rather than here, where it would happen before the chooser had spoken.

    Unlike Petra Sphinx's guess, an empty library is not a reason to skip the
    prompt: exiling nothing and revealing nothing is a legal outcome of this
    spell, and the player has still cast it.
    """
    caster = context.caster
    seat = game.players.index(caster)
    game.arm_pending_choice(
        "name_then_consult", seat,
        card_name=context.card.name if context.card is not None else "",
        exile_count=int(instruction.payload.get("exile_count", 0) or 0),
        # A player knows what is in their own library, only not its order
        # (CR 400.2), so naming its commonest remaining card is a choice a human
        # at the table could make — and it is deterministic, which is what a
        # seeded replay needs.
        default_name=_commonest_visible_name(
            game, seat, ("library",), exclude_basics=False
        ),
    )
    return True, "pending_name_then_consult"


@effect_handler("name_and_random_reveal")
def name_and_random_reveal(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Nebuchadnezzar: name a card, make an opponent reveal N cards at random
    from a hidden zone, then discard every revealed card with that name.

    One handler for the whole effect because the three printed sentences share
    one choice and one pile: "all cards with that name **revealed this way**"
    is the subset the random reveal turned up, not every copy in the hand.
    Split apart, the discard would take the whole hand's worth and the
    randomness would mean nothing.

    The name is chosen as the ability resolves (CR 608.2), and the reveal is
    taken from the pile that exists *then* — which is why the count is resolved
    here rather than at activation: X was announced, but how many cards the
    opponent holds is a fact about this moment.
    """
    caster = context.caster
    target = context.target
    if target is None or target is caster:
        game.log.append(f"{context.card.name}: no opponent to reveal from")
        return True, "resolved"
    seat = game.players.index(target)
    count = resolve_amount(instruction.payload.get("count", 0), context.x_value)
    game.arm_pending_choice(
        "name_and_random_reveal", game.players.index(caster),
        card_name=context.card.name,
        target_seat=seat,
        count=max(0, int(count)),
        zone=str(instruction.payload.get("zone", "hand")),
        # A non-interactive seat names the commonest card in the opponent's
        # **graveyard**, which is the only zone bearing on this it may look at
        # (CR 400.2) — naming from the hand it is about to reveal from would be
        # the AI reading hidden information. An empty graveyard names nothing,
        # which reveals and discards nothing: legal, and the honest answer for a
        # seat with no information. Basics are not excluded, because this card
        # prints no restriction on the name (CR 202.1).
        default_name=_commonest_visible_name(
            game, seat, ("graveyard",), exclude_basics=False
        ),
    )
    return True, "pending_name_and_random_reveal"


#: The zones a card whose ownership is changing can be found in. "…from
#: anywhere" (Tempest Efreet) is printed because the source was sacrificed as a
#: cost and is therefore already gone from the battlefield — but the words say
#: anywhere, and a card that has since been exiled or shuffled away is still the
#: card the ability names. The battlefield is not in the list: a permanent there
#: is a `Permanent`, not a card, and this exchange is about the card.
_OWNERSHIP_ZONES = ("graveyard", "hand", "exile", "library", "ante")


def _locate_card_for_ownership(
    game: Game, card, prefer_seat: int = 0
) -> tuple[int, str, int] | None:
    """Where *card* is, as ``(owner seat, zone name, index)``, or None.

    Located by **identity** and returned as an index rather than as the object:
    the catalog hands out one ``CardDefinition`` per card, so two copies in one
    zone are the same object and only an index can say *which* of them moves.
    Identity cannot tell two copies apart at all, so *prefer_seat* — the seat
    the ability was activated from, which is where the card it sacrificed is —
    is searched first. Without it a *previous* copy already sitting in the
    victim's graveyard would be found instead, and the exchange would hand that
    player back their own card.
    """
    seats = sorted(range(len(game.players)), key=lambda seat: seat != prefer_seat)
    for seat in seats:
        player = game.players[seat]
        for zone in _OWNERSHIP_ZONES:
            pile = getattr(player, zone, None) or ()
            for index, held in enumerate(pile):
                if held is card:
                    return seat, zone, index
    return None


@effect_handler("ante_or_exchange_ownership")
def ante_or_exchange_ownership(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Timmerian Fiends: "The owner of target artifact may ante the top card of
    their library. If that player doesn't, exchange ownership of that artifact
    and this creature…"

    The sibling of :func:`random_reveal_ownership_exchange` below, and built the
    same way: the offer is the ordinary optional-pay entry, it is owed by the
    **victim** rather than by the activator, and the decline branch is its own
    instruction because the prompt machinery runs instruction lists.

    Two things differ from the Efreet, and both are why the paragraph is its own
    production. The seat asked is the target's **owner** (CR 108.3), not its
    controller and not a chosen player — a stolen artifact is still anted for by
    the player who owns it. And what the seat is offered is an *action* rather
    than a payment, so whether the offer can be made at all is asked through
    ``_narrow_to_takeable_actions`` — the same predicate ``handlers/control_flow``
    asks of every other optional action, so a seat with no library is not
    offered an ante it cannot perform and the card's "if that player doesn't"
    branch applies instead.

    Inert outside the ante variant, for the reason the Efreet is: CR 108.3 fixes
    ownership for the whole game, CR 407 is the only exception, and CR 407.1
    makes that variant opt-in.
    """
    from ..subject_filters import subject_matches
    from .control_flow import _narrow_to_takeable_actions

    card_name = getattr(context.card, "name", "")
    if not getattr(game, "playing_for_ante", False):
        game.log.append(
            f"{card_name}: ownership changes only in a game played for ante "
            "(CR 108.3, CR 407.1)"
        )
        return True, "resolved"
    caster_seat = game.players.index(context.caster)
    described = {"type_filter": str(instruction.payload.get("type_word", "artifact"))}
    source = context.source_permanent

    def _eligible(perm) -> bool:
        return subject_matches(
            game, perm, described, observer=caster_seat, source=source
        )

    victim = resolve_target_permanent(game, context, predicate=_eligible)
    if victim is None:
        game.log.append(f"{card_name}: no valid permanent to exchange")
        return True, "resolved"
    owner_seat = game.owner_index_of(victim)
    if owner_seat is None:
        return True, "resolved"
    owner = game.players[owner_seat]
    # The offer's own frozen context, with "that player" bound to the owner —
    # which is who the printed ante and the printed graveyard both name. Frozen
    # for ``_offer_to_seat``'s reason: the entry outlives this call.
    offer_context = dataclasses.replace(context, target=owner)
    # The permanent is addressed by id, never by index: an index stops naming
    # the same object the moment anything leaves the battlefield, and the whole
    # point of the decline branch is that something is about to.
    decline = (
        _OracleInstruction(
            "take_permanent_in_ownership_exchange", "",
            {"permanent_id": victim.permanent_id},
        ),
    )
    accept, offerable = _narrow_to_takeable_actions(
        game, owner,
        (_OracleInstruction("ante_top_card", "", {"players": "that_player"}),),
        offer_context,
    )
    if not offerable:
        game.log.append(
            f"{card_name}: {owner.name} has nothing to ante, so the exchange stands"
        )
        run_resumable(
            game, decline,
            lambda step: game._execute_oracle_instruction(step, offer_context),
        )
        return True, "resolved"
    game.arm_pending_choice(
        "optional_pay", owner_seat,
        card_name=card_name,
        cost={},
        life=0,
        prompt=f"Ante the top card of your library to keep {victim.card.name}?",
        _source_permanent=source,
        _on_accept=accept,
        _on_decline=decline,
        _on_reflexive=(),
        _context=offer_context,
    )
    return True, "resolved"


def _take_located_card(game: Game, located: tuple[int, str, int], card) -> None:
    """Lift *card* out of the zone :func:`_locate_card_for_ownership` found it in.

    Exile is the one of the five that has a departure transition behind it
    (``Game.take_card_from_exile``, which retires the exile register with the
    card); the rest are plain lists here, and the index is the address because
    that is what the locator returned. One helper because both readers of the
    locator move the card they found, and a zone name reaching a ``pop`` is
    invisible to the static guard over ``.exile`` — so the branch belongs in the
    one place a reader of that guard will look.
    """
    seat, zone, at = located
    if zone == "exile":
        game.take_card_from_exile(seat, card)
        return
    getattr(game.players[seat], zone).pop(at)


def _give_card_to_graveyard(
    game: Game, card, new_owner_seat: int, prefer_seat: int
) -> bool:
    """Move *card*, wherever it is, into *new_owner_seat*'s graveyard.

    "Put ~ **from anywhere** into that player's graveyard" (Timmerian Fiends).
    The card is not on a battlefield — it was sacrificed to pay the ability's
    cost and is sitting in a graveyard — so this reaches no zone seam: nothing
    leaves play here, and ownership in this engine *is* which player's zone a
    card sits in, which makes the move between the two piles the change itself.

    Located by identity through :func:`_locate_card_for_ownership`, with
    *prefer_seat* for its stated reason. False when the card is nowhere to be
    found (CR 701.12a).
    """
    located = _locate_card_for_ownership(game, card, prefer_seat)
    if located is None:
        return False
    _take_located_card(game, located, card)
    game.put_card_into_graveyard(new_owner_seat, card)
    return True


@effect_handler("take_permanent_in_ownership_exchange")
def take_permanent_in_ownership_exchange(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """The decline branch of Timmerian Fiends: the swap itself.

    "Ownership" in this engine is which player's zone a card sits in, so the two
    printed moves *are* the exchange rather than a consequence of it — the same
    reading :func:`take_revealed_card_in_exchange` below makes.

    **The ownership change is recorded before the permanent leaves**, on the
    field ``owner_index_of`` reads. That is what routes the card to the
    activator's graveyard through ``_permanent_to_graveyard`` — CR 400.3 sends a
    permanent's card to its *owner*, and by then the activator is the owner
    (CR 407's exception to CR 108.3). Writing the graveyard by hand instead
    would have skipped the dies-triggers, the Aura teardown, the death count and
    every CR 614 would-die replacement, which is exactly the class
    ``tests/engine/test_leave_battlefield_seam.py`` exists to catch.

    CR 701.12a's atomicity: with the source card nowhere to be found there is
    nothing to exchange it *for*, so it is looked for **first** and no part of
    the exchange happens.
    """
    card_name = getattr(context.card, "name", "")
    victim_player = context.target
    if victim_player is None or victim_player not in game.players:
        return True, "resolved"
    victim_seat = game.players.index(victim_player)
    caster_seat = game.players.index(context.caster)
    permanent_id = instruction.payload.get("permanent_id")
    taken = (
        game.permanent_by_id(permanent_id) if isinstance(permanent_id, int) else None
    )
    if taken is None:
        game.log.append(f"{card_name}: the permanent it named has left")
        return True, "resolved"
    if _locate_card_for_ownership(game, context.card, caster_seat) is None:
        # Nothing has moved yet, so CR 701.12a leaves the board untouched.
        game.log.append(
            f"{card_name} is nowhere to be found, so no ownership is exchanged"
        )
        return True, "resolved"
    taken_name = taken.card.name
    holder_seat = game.controller_index_of(taken)
    holder = game.players[holder_seat] if holder_seat is not None else victim_player
    taken.metadata["owner_player_index"] = caster_seat
    game._permanent_to_graveyard(holder, taken)
    game.remove_from_battlefield(taken)
    _give_card_to_graveyard(game, context.card, victim_seat, caster_seat)
    game.log.append(
        f"{context.caster.name} now owns {taken_name} and "
        f"{victim_player.name} now owns {card_name} (CR 407)"
    )
    return True, "resolved"


@effect_handler("random_reveal_ownership_exchange")
def random_reveal_ownership_exchange(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Tempest Efreet: "Target opponent may pay 10 life. If that player
    doesn't, they reveal a card at random from their hand. Exchange ownership
    of the revealed card and this creature…"

    The payment is the ordinary optional-pay entry and it is owed by the
    **victim**, exactly as Bronze Tablet's is; what is new is that the *decline*
    branch has to pick a card first. So the branch is its own instruction rather
    than work done here — the prompt machinery runs instruction lists, and this
    handler's whole job is to offer the choice to the right seat.

    Inert outside the ante variant. CR 108.3 fixes ownership for the whole game
    and CR 407 is the only exception; CR 407.1 makes that variant opt-in, so an
    ownership change in an ordinary duel is not a rule this engine has.
    """
    card_name = getattr(context.card, "name", "")
    if not getattr(game, "playing_for_ante", False):
        game.log.append(
            f"{card_name}: ownership changes only in a game played for ante "
            "(CR 108.3, CR 407.1)"
        )
        return True, "resolved"
    victim = context.target
    if victim is None or victim not in game.players or victim is context.caster:
        game.log.append(f"{card_name}: no opponent to exchange with")
        return True, "resolved"
    victim_seat = game.players.index(victim)
    life = int(instruction.payload.get("life", 0))
    game.arm_pending_choice(
        "optional_pay", victim_seat,
        card_name=card_name,
        cost={},
        life_cost=life,
        life=0,
        prompt=f"Pay {life} life?",
        _source_permanent=context.source_permanent,
        _on_accept=(),
        _on_decline=(_OracleInstruction("take_revealed_card_in_exchange", "", {}),),
        _on_reflexive=(),
        _context=context,
    )
    return True, "resolved"


@effect_handler("take_revealed_card_in_exchange")
def take_revealed_card_in_exchange(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """The decline branch of Tempest Efreet: the random reveal and the swap.

    The reveal samples an **index**, never a card object. Two copies of one card
    in a hand are the same ``CardDefinition``, so sampling the objects would
    make a hand of two Mountains and a Shivan Dragon a coin flip rather than a
    one-in-three — and would pick the *first* matching slot to remove either way.

    "Ownership" in this engine is which player's zone a card sits in, so the two
    printed moves *are* the exchange rather than a consequence of it, and there
    is nothing further to record. CR 701.12a still applies: with the source card
    nowhere to be found there is nothing to exchange it *for*, so the revealed
    card goes back where it came from and no part of the exchange happens.
    """
    card_name = getattr(context.card, "name", "")
    victim = context.target
    if victim is None or victim not in game.players:
        return True, "resolved"
    caster_seat = game.players.index(context.caster)
    if not victim.hand:
        game.log.append(f"{card_name}: {victim.name} has no card to reveal")
        return True, "resolved"
    index = random.randrange(len(victim.hand))
    revealed = victim.hand[index]
    game.log.append(f"{victim.name} reveals {revealed.name} at random")
    located = _locate_card_for_ownership(game, context.card, caster_seat)
    if located is None:
        # A reveal does not move a card, so nothing has to be put back: the
        # revealed card is still in the hand it was revealed from, and CR
        # 701.12a's atomicity means no part of the exchange happens.
        game.log.append(
            f"{card_name} is nowhere to be found, so no ownership is exchanged"
        )
        return True, "resolved"
    victim.hand.pop(index)
    _take_located_card(game, located, context.card)
    # Through the one seam every "put this card into a hand" goes through, so
    # CR 903.9b sees it (a commander taken this way is offered its command zone
    # like any other move to a hand). The hand it goes to is the new owner's,
    # which is what an ownership exchange *is* in this engine.
    game.put_card_into_hand(game.players[caster_seat], revealed)
    game.put_card_into_graveyard(victim, context.card)
    game.log.append(
        f"{context.caster.name} now owns {revealed.name} and {victim.name} now "
        f"owns {card_name} (CR 407)"
    )
    return True, "resolved"


def chosen_hand_card_candidates(game, payload: dict, player) -> list[int]:
    """The hand slots "choose N cards in your hand …" may be answered with.

    Public and singular for ``put_from_hand_candidates``' reason: the prompt
    renderer shows the seat what it may pick and the resolver checks what came
    back, and a list built twice is a list that can be offered wider than it is
    checked.

    Two narrowings, and they are asked of different things. The printed noun
    phrase is a question about the *card* and goes through the shared card
    matcher. "Drawn this turn" is not a question about the card at all —
    nothing on its face answers it and ``_card_matches_filter`` has no player to
    ask — so it is answered here, against the record every draw path already
    feeds (``PlayerState.cards_drawn_this_turn``). By identity, never by name: a
    second copy of a card drawn this turn is a different object and was not
    drawn.
    """
    described = payload.get("card_filter") or {}
    drawn_this_turn = bool(payload.get("drawn_this_turn"))
    provenance = player.cards_drawn_this_turn if drawn_this_turn else ()
    return [
        index
        for index, card in enumerate(player.hand)
        if _card_matches_filter(card, described, game=game, owner=player)
        and (
            not drawn_this_turn
            or any(card is drawn for drawn in provenance)
        )
    ]


@effect_handler("choose_cards_in_hand")
def choose_cards_in_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose two cards in your hand drawn this turn." (Sylvan Library.)

    Nothing moves: the pick is recorded under the key the lowering named, and
    the sentence after it ("for each of those cards, …") is what acts on them.
    The cards themselves are recorded rather than hand indices — a hand index
    stops naming the same card the moment anything leaves the hand, which the
    very next step does.

    CR 608.2's "as much as possible": a hand holding fewer eligible cards than
    the printed number chooses all of them rather than none.

    "**Each player** chooses a card in their hand." (Stronghold Gambit.) One
    prompt per living seat in APNAP order (CR 101.4), each out of that seat's
    own hand, all armed at once — CR 101.4a keeps the cards face down as they
    are chosen, so no seat's pick waits on another's — and recorded per seat
    (``{seat: [cards]}``) because every answer is its own. The resolution waits
    for the last of them (the kind suspends).
    """
    payload = instruction.payload
    if payload.get("actor") == "each_player":
        from .control_flow import _offered_seats

        result_key = str(payload.get("result_key") or "chosen_hand_cards")
        by_seat: dict[int, list] = {}
        context.results[result_key] = by_seat
        for seat in _offered_seats(game, "each_player", context):
            player = game.players[seat]
            by_seat[seat] = []
            if not chosen_hand_card_candidates(game, payload, player):
                game.log.append(
                    f"{context.card.name}: {player.name} has no card to choose"
                )
                continue
            game.arm_choose_cards_in_hand(seat, payload, context)
        return True, "resolved"
    player = context.caster
    seat = game.players.index(player)
    candidates = chosen_hand_card_candidates(game, payload, player)
    result_key = str(payload.get("result_key") or "chosen_hand_cards")
    if not candidates:
        context.results[result_key] = []
        game.log.append(
            f"{context.card.name}: {player.name} has no card to choose"
        )
        return True, "resolved"
    game.arm_choose_cards_in_hand(seat, payload, context)
    return True, "resolved"


def _chosen_cards_still_in_hand(game, record: dict) -> list[tuple[int, object]]:
    """``(seat, card)`` for every card a per-seat hand pick recorded that is
    still in that seat's hand, in APNAP order.

    By identity against the seat's *own* hand: every copy of a card in a hand is
    one shared object, and two players' decks built from one catalog share the
    object across hands too, so "is it still there" is only answerable per
    seat. A card that left between the pick and now is not revealed and does
    not compete (CR 608.2: do as much as possible).
    """
    out: list[tuple[int, object]] = []
    for seat in sorted(record, key=lambda s: (
        (s - (game.active_player_index or 0)) % max(len(game.players), 1), s
    )):
        if not (isinstance(seat, int) and 0 <= seat < len(game.players)):
            continue
        hand = game.players[seat].hand
        for card in record.get(seat) or ():
            if any(card is held for held in hand):
                out.append((seat, card))
    return out


@effect_handler("reveal_chosen_hand_cards")
def reveal_chosen_hand_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Then each player reveals their chosen card." (Stronghold Gambit.)

    Every hidden pick made public at once (CR 701.20a), through the one reveal
    feed the web layer reads — one event per seat, because each player reveals
    their own. Nothing moves; the sentence after this one reads the same record.
    """
    record = context.results.get(str(instruction.payload.get("cards_from"))) or {}
    shown: dict[int, list[str]] = {}
    for seat, card in _chosen_cards_still_in_hand(game, record):
        shown.setdefault(seat, []).append(card.name)
    for seat, names in shown.items():
        game.record_reveal(seat, names)
        game.log.append(
            f"{game.players[seat].name} reveals {', '.join(names)} "
            f"({context.card.name})"
        )
    if not shown:
        game.log.append(f"{context.card.name}: no player revealed a card")
    return True, "resolved"


@effect_handler("put_chosen_hand_cards_onto_battlefield")
def put_chosen_hand_cards_onto_battlefield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"The owner of each creature card revealed this way with the lowest mana
    value puts it onto the battlefield." (Stronghold Gambit.)

    Only the recorded cards compete, and only those the printed phrase admits
    (``_card_matches_filter``, the card-in-a-zone matcher) — a revealed land is
    not in the comparison at all, so it cannot be "the lowest". The superlative
    is then asked of the survivors and **every** card tied at the extreme
    enters, because "each … with the lowest mana value" names all of them.
    Mana value is the printed one (CR 202.3), which is all a card in a hand has.

    Each enters under its **owner**, who is the player the sentence makes put
    it there (CR 110.2a), out of that owner's hand through the hand seam.
    """
    payload = instruction.payload
    record = context.results.get(str(payload.get("cards_from"))) or {}
    described = payload.get("card_filter") or {}
    entrants = [
        (seat, card)
        for seat, card in _chosen_cards_still_in_hand(game, record)
        if _card_matches_filter(
            card, described, game=game, owner=game.players[seat]
        )
    ]
    superlative = payload.get("superlative") or {}
    if entrants and superlative:
        if superlative.get("characteristic") != "mana_value":
            # The lowering admits nothing else; a hand-built payload naming a
            # characteristic no card in a hand has puts nothing in rather than
            # guessing which card was meant.
            game.log.append(f"{context.card.name}: nothing to compare")
            return True, "resolved"
        pick = min if superlative.get("extreme") == "least" else max
        best = pick(int(getattr(card, "cmc", 0) or 0) for _, card in entrants)
        entrants = [
            (seat, card) for seat, card in entrants
            if int(getattr(card, "cmc", 0) or 0) == best
        ]
    if not entrants:
        game.log.append(f"{context.card.name}: no revealed card enters")
        return True, "resolved"
    for seat, card in entrants:
        owner = game.players[seat]
        if not game.take_card_from_hand(owner, card):
            continue
        game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
        game.log.append(
            f"{owner.name} puts {card.name} onto the battlefield ({context.card.name})"
        )
    return True, "resolved"


@effect_handler("reveal_cards_from_hand")
def reveal_cards_from_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Reveal any number of artifact cards in your hand." (Metalworker, the
    five Urza's Destiny Seers, their five Scents and Rofellos's Gift.)

    Nothing moves and nothing is spent: the seat picks a subset of its own
    hand, those cards become public (CR 701.20a), and the sentence after this
    one reads the count off the record. The pick goes through the same queued
    choice Sylvan Library's does — one prompt for "which cards in your hand",
    with the printed offer ("any number of" against a count) and the printed
    verb as payload — because what differs between the two sentences is data
    and not a mechanism.

    ``chosen_hand_card_candidates`` is the one rule that says which cards the
    printed noun phrase admits, so the list offered and the list an answer is
    checked against cannot be two lists.

    An empty candidate set answers itself: nought is a legal answer to "any
    number", so there is nothing to ask and both records are written where the
    effect stands. Written rather than left absent, because an absent key is a
    back-reference with no producer — which is a refusal, not a zero.
    """
    payload = instruction.payload
    player = context.caster
    seat = game.players.index(player)
    candidates = chosen_hand_card_candidates(game, payload, player)
    if not candidates:
        context.results[str(payload.get("result_key") or REVEALED_HAND_CARDS)] = []
        context.results[str(payload.get("count_key") or REVEALED_THIS_WAY)] = 0
        game.log.append(
            f"{context.card.name}: {player.name} reveals no cards"
        )
        return True, "resolved"
    game.arm_choose_cards_in_hand(seat, payload, context)
    return True, "resolved"


@effect_handler("put_iterated_card_on_library")
def put_iterated_card_on_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put the card on top of your library." (Sylvan Library.)

    "The card" is the object the enclosing repetition is on, so this reads
    ``context.iteration_target`` and refuses to guess without one: a sentence
    naming a loop's object outside a loop names nothing, and picking some card
    out of the hand instead would be a card doing something it never says.

    Through ``Game.put_card_into_library`` rather than by moving the card
    itself, because CR 903.9b's return to the command zone has no single fire
    site and this is one more of them.
    """
    card = context.iteration_target
    if card is None:
        game.log.append(
            f"{context.card.name}: no card for this step to move"
        )
        return True, "resolved"
    player = context.caster
    if not any(c is card for c in player.hand):
        # It left the hand between the choice and this step. CR 608.2: do as
        # much as possible, which here is nothing.
        game.log.append(
            f"{context.card.name}: {getattr(card, 'name', 'that card')} is no "
            f"longer in {player.name}'s hand"
        )
        return True, "resolved"
    game.take_card_from_hand(player, card)
    position = "bottom" if str(instruction.payload.get("position", "top")) == "bottom" else "top"
    game.put_card_into_library(player, card, position)
    game.log.append(
        f"{context.card.name}: {player.name} put {card.name} on "
        f"{'the bottom' if position == 'bottom' else 'top'} of their library"
    )
    return True, "resolved"


@effect_handler("put_self_into_zone")
def put_self_into_zone(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put it into your graveyard." — the ability's own source changes zones.

    The source is a permanent or a card in **exile** (All Hallow's Eve, whose
    upkeep trigger finally bins the exiled card once its last scream counter
    has come off), and ``exiled_records.source_object`` is the one reader that
    answers for both.

    The destination is payload, and today the only one the grammar admits is a
    graveyard — see ``lowering/zones._lower_put_source_into_zone``, which
    refuses the rest by name rather than letting a card report itself supported
    and land somewhere else.

    CR 400.3 sends a card to **its owner's** graveyard whatever the effect
    printed, which is why "your graveyard" and "its owner's graveyard" lower to
    the same instruction and the owner lookup happens here.
    """
    zone = str(instruction.payload.get("zone", "graveyard"))
    if zone != "graveyard":  # pragma: no cover - the lowering refuses the rest
        return False, f"no handler puts a source into a {zone}"
    source = source_object(context)
    if source is None:
        game.log.append(f"{context.card.name}: nothing left to move")
        return True, "resolved"
    if isinstance(source, Permanent):
        owner_index = game.owner_index_of(source)
        owner = game.players[owner_index] if owner_index is not None else context.caster
        if not game.is_on_battlefield(source):
            game.log.append(f"{context.card.name}: nothing left to move")
            return True, "resolved"
        game.remove_from_battlefield(source)
        game._permanent_to_graveyard(owner, source)
        return True, "resolved"
    # An exile record. The card leaves exile and the register forgets it, both
    # in the departure seam — and *this* record by name rather than the one the
    # seam would derive, because two copies of the card produce two
    # equal-looking entries and the trigger resolving here fires for exactly
    # one of them. Retiring the other would strand this copy's counters on a
    # card that is no longer there.
    owner = game.players[source.owner_index]
    game.take_card_from_exile(source.owner_index, source.card, record=source)
    game.put_card_into_graveyard(owner, source.card)
    game.log.append(f"{source.card.name} was put into {owner.name}'s graveyard from exile")
    return True, "resolved"


@effect_handler("return_all_cards_from_graveyard")
def return_all_cards_from_graveyard(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each player returns all creature cards from their graveyard to the
    battlefield." (All Hallow's Eve.)

    A sweep reanimation: no target, no pick, every card a printed noun phrase
    names. ``who`` is the returning player — ``each_player`` or the ability's
    controller — and it is payload rather than two kinds because the sentence
    is the same one either way.

    Each card comes back under **its own player's** control, which is what the
    printed subject says: "each player returns … from *their* graveyard".
    Reading the sentence without its subject would hand the table's graveyards
    to whoever's upkeep it was, which is a different card.

    The graveyard is drained highest-index-first, so popping one does not
    renumber the slots still to come — the ordering every other multi-card
    graveyard move in this engine follows, and the reason it is not a removal
    by value: two copies of one card in a graveyard are the *same*
    ``CardDefinition``, so ``.remove()`` would take whichever came first.
    """
    described = dict(instruction.payload.get("filter") or {})
    who = str(instruction.payload.get("who", "you"))
    # "…to **your hand**." (Crystal Chimes.) The pair of zones is what picks the
    # move, and the graveyard half is the same either way — which is why it is
    # one key rather than a second kind that would re-derive the same sweep.
    # Absent means the battlefield, so every payload written before this means
    # what it meant.
    destination = str(instruction.payload.get("destination", "battlefield"))
    # "…to the battlefield **tapped**." (Planar Birth.) CR 110.5b.
    tapped = bool(instruction.payload.get("tapped"))
    # "…**that were put there from the battlefield this turn**." (No Rest for
    # the Wicked.) Beside the filter and not inside it, because how a card
    # reached a pile is not on the card: a graveyard has a printed type line and
    # nothing else (CR 613.1), so the record the game kept as the move happened
    # is the only thing that can answer.
    only_this_turn = bool(instruction.payload.get("put_there_this_turn"))
    if who == "each_player":
        # CR 101.4's order, and a seat that has left the game returns nothing
        # (CR 800.4a): a lost player has no battlefield, so putting a card onto
        # it makes a permanent nobody controls. This read the raw seat range,
        # which is All Hallow's Eve mis-played in the one game shape where the
        # difference exists — and the two per-seat handlers beside it already
        # answer the question this way.
        total = len(game.players)
        active = game.active_player_index or 0
        seats = sorted(
            (i for i, p in enumerate(game.players) if not p.lost),
            key=lambda i: ((i - active) % total, i),
        )
    else:
        seats = [game.players.index(context.caster)]
    returned = 0
    for seat in seats:
        player = game.players[seat]
        taken = [
            index for index, card in enumerate(player.graveyard)
            if _card_matches_filter(card, described, game=game, owner=player)
        ]
        if only_this_turn:
            # Matched by **count of entries**, not by membership: two copies of
            # a card in a deck are the same immutable ``CardDefinition``, so a
            # graveyard holding one that died this turn and one that was
            # discarded last turn holds one object twice — and the record says
            # how many of them arrived the way the sentence names. Newest first,
            # since a death puts the card on top and that is the copy the record
            # is about.
            arrived = list(
                player.cards_put_into_your_graveyard_from_battlefield_this_turn
            )
            allowed: list[int] = []
            for index in sorted(taken, reverse=True):
                card = player.graveyard[index]
                match = next(
                    (i for i, held in enumerate(arrived) if held is card), None
                )
                if match is None:
                    continue
                arrived.pop(match)
                allowed.append(index)
            taken = allowed
        cards = [player.graveyard[index] for index in taken]
        for index in sorted(taken, reverse=True):
            player.graveyard.pop(index)
        for card in cards:
            if destination == "hand":
                # CR 903.9b's seam, never `player.hand.append` — a bounce, a
                # tuck and a regrowth are all "would be put into its owner's
                # hand", and this is one of the thirty fire sites that rule has
                # no single one of.
                game.put_card_into_hand(player, card)
                game.log.append(
                    f"{player.name} returned {card.name} to their hand from the graveyard"
                )
                returned += 1
                continue
            permanent = Permanent(card=card)
            if tapped:
                permanent.tapped = True
            game._put_permanent_onto_battlefield(seat, permanent, None)
            game.log.append(
                f"{player.name} returned {card.name} to the battlefield from the graveyard"
            )
            returned += 1
    if not returned:
        game.log.append(f"{context.card.name}: no cards to return")
    return True, "resolved"


#: The scratchpad key the random reveal writes beside ``revealed_card``: which
#: slot of the hand it named. The card object alone cannot answer that — two
#: copies of one card in a hand are literally the same object (idiom 11), so a
#: discard by value would take whichever one ``list.remove`` reached first.
REVEALED_HAND_INDEX = "revealed_card_hand_index"

#: Which of a revealed hand's cards *one* of Sirocco's offers is about. Private
#: to a single offer's branch context — the resolution's own scratchpad is
#: shared, and a key written into it per offer would leave every branch reading
#: whichever was armed last.
_DISCARDED_REVEALED_CARD = "discarded_revealed_card"


@effect_handler("reveal_random_card_from_hand")
def reveal_random_card_from_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target player reveals a card at random from their hand." (Wand of Ith.)

    CR 701.20 over one card nobody chose. Recorded under the same
    ``revealed_card`` key the library reveal writes, so the sentences behind it
    — "if it's a land card", "discards **it**" — read the one referent this
    engine has for a revealed card rather than a second one.

    The slot is recorded beside it, because the card object is not an identity
    in a hand: two copies of one card there are the same object, and a discard
    by value would take whichever the list reached first.

    An empty hand reveals nothing, which the condition behind it reads as False
    — a legal outcome, not an error.

    **Whose hand is stated when the sentence states it.** "…then reveal a card
    at random from **your** hand" (Cursed Scroll) is the effect's own
    controller, and the fallback below cannot answer it: ``context.target`` is
    the *ability's* target, which on that card is whoever the damage is aimed
    at. The fallback stays for the targeted printings, where the ability
    targets exactly the player the sentence names.
    """
    if instruction.payload.get("revealer") == "you":
        victim = context.caster
    else:
        victim = context.target if context.target is not None else context.caster
    if not victim.hand:
        game.log.append(f"{victim.name} has no cards in hand to reveal")
        return True, "resolved"
    index = random.randrange(len(victim.hand))
    card = victim.hand[index]
    context.results["revealed_card"] = card
    context.results[REVEALED_HAND_INDEX] = index
    seat = next((i for i, seated in enumerate(game.players) if seated is victim), None)
    if seat is not None:
        game.record_reveal(seat, [card.name])
    game.log.append(f"{victim.name} reveals {card.name} at random from their hand")
    return True, "resolved"


@effect_handler("exile_random_card_from_hand")
def exile_random_card_from_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"At the beginning of each player's upkeep, **that player exiles a card at
    random from their hand**." (Elkin Lair.)

    One card nobody chose, out of a hand nobody looked at — CR 701.13a's exile
    over a random pick, which is why the seat is not asked anything and no
    prompt is armed. Recorded under the one ``exiled_cards`` key every other
    exile writes, so the two sentences behind it ("the player may play that
    card", "if the player hasn't played the card…") read the referent this
    engine already has rather than a second one.

    **Whose hand is payload**, under the same ``recipient`` key the mill, the
    discard and Thought Lash's library exile use, and the seat is the one the
    firing event froze (``frozen_that_player_seat``). A seat that cannot be
    resolved exiles
    *nothing* rather than falling back to the ability's controller: on this card
    the controller's own hand is the wrong hand three times in four, and taking
    a card out of it at random is not a smaller effect, it is a different one.

    The card is popped **by index**, not by value: a hand is the one zone where
    two copies of a card are the same object (a deck repeats one immutable
    ``CardDefinition``), so ``list.remove`` would take whichever came first.
    ``random.randrange`` rather than a private RNG, for the reason every other
    random pick in this file uses it — ``run_ai_simulation`` seeds the module
    RNG and a seed has to replay a run exactly.
    """
    recipient = str(instruction.payload.get("recipient") or "caster")
    if recipient == "event_subject_player":
        seat = frozen_that_player_seat(game, context)
        if seat is None:
            game.log.append(
                f"{context.card.name}: no player was named to exile a card"
            )
            return True, "resolved"
        victim = game.players[seat]
    else:
        victim = context.caster
    if not victim.hand:
        game.log.append(f"{victim.name} has no cards in hand to exile")
        context.results["exiled_cards"] = []
        return True, "resolved"
    index = random.randrange(len(victim.hand))
    card = victim.hand[index]
    victim.hand.pop(index)
    victim.exile.append(card)
    context.results["exiled_cards"] = [card]
    game.log.append(
        f"{victim.name} exiled {card.name} at random from their hand"
    )
    return True, "resolved"


@effect_handler("discard_revealed_card")
def discard_revealed_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """The declined branch of "…discards it unless they pay N life".

    "It" is the card the reveal recorded, taken **by slot**: a hand is the one
    zone where two copies of a card are one object, so the index resolved at
    reveal time is the only thing that names which of them was shown.

    A hand that has changed underneath the prompt discards nothing rather than
    guessing — the card the sentence named is not there to discard.
    """
    victim = context.target if context.target is not None else context.caster
    card = context.results.get("revealed_card")
    index = context.results.get(REVEALED_HAND_INDEX)
    if card is None or not isinstance(index, int):
        return True, "resolved"
    if not (0 <= index < len(victim.hand)) or victim.hand[index] is not card:
        game.log.append(f"{context.card.name}: {card.name} is no longer in hand")
        return True, "resolved"
    victim.hand.pop(index)
    game.put_card_into_graveyard(victim, card)
    game.log.append(f"{victim.name} discards {card.name}")
    return True, "resolved"


@effect_handler("discard_revealed_unless_pay_life")
def discard_revealed_unless_pay_life(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"That player discards it unless they pay 1 life." / "…unless they pay
    life equal to its mana value." (Wand of Ith.)

    An offer to a seat that is not the ability's controller, on the same
    ``optional_pay`` queue every other offer uses — so the same three loops in
    ``web/prompts.py`` render it, gate the actions it blocks and answer it for
    an AI seat, and the ability stays on the stack until it is answered
    (CR 608.2, CR 117.3b).

    The *paying* seat is put on the branches' context rather than on the
    payment's payload: ``pay_life`` charges ``context.caster``, and replacing it
    here is what makes one payment instruction chargeable to whoever was
    offered it — the discard on the other branch reads the same context and so
    cannot come apart from it.

    CR 119.4: a player may pay life only with a life total at least the amount,
    so a seat that cannot pay is never offered the choice — it simply discards,
    which is what the sentence says happens when the cost is not paid.
    """
    from .life_and_game import can_pay_life

    victim = context.target if context.target is not None else context.caster
    seat = next((i for i, seated in enumerate(game.players) if seated is victim), None)
    card = context.results.get("revealed_card")
    if card is None or seat is None:
        return True, "resolved"
    printed = instruction.payload.get("life", 0)
    # "…life equal to **its** mana value" — a number nothing knows until the
    # card is revealed, so it is read here off the card the reveal recorded
    # rather than resolved at lowering.
    amount = int(card.cmc or 0) if printed == "revealed_mana_value" else int(printed)
    discard = (_OracleInstruction("discard_revealed_card", "", {}),)
    paying_context = dataclasses.replace(context, caster=victim)
    if not can_pay_life(victim, amount):
        game._execute_oracle_instruction(discard[0], paying_context)
        return True, "resolved"
    game.arm_pending_choice(
        "optional_pay", seat,
        card_name=context.card.name if context.card is not None else "",
        cost={},
        life=0,
        _source_permanent=context.source_permanent,
        _on_accept=(_OracleInstruction("pay_life", "", {"amount": amount}),),
        _on_decline=discard,
        _on_reflexive=(),
        _context=paying_context,
        prompt=f"Pay {amount} life to keep {card.name}?",
    )
    return True, "resolved"


@effect_handler("discard_revealed_matching_unless_pay_life")
def discard_revealed_matching_unless_pay_life(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"For each blue instant card revealed this way, that player discards that
    card unless they pay 4 life." (Sirocco.)

    The plural of ``discard_revealed_unless_pay_life``: one offer per card the
    reveal in front of this one showed that the printed phrase names, all on the
    same ``optional_pay`` queue, so the spell stays on the stack until the last
    is answered (CR 608.2, CR 117.3b) and ``web/prompts.py``'s three loops
    render, gate and default them exactly as they do a single one.

    **Each offer carries its own card**, in a *copy* of the resolution's
    scratchpad: ``results`` is one dict for the whole resolution, so writing the
    card into it per offer would leave every branch reading whichever was armed
    last. Nothing after this sentence reads the record, which is what makes the
    copy free.

    The discard names the card rather than a slot. Two copies of one card in a
    hand are the same Python object and the pile renumbers as cards leave, so
    the slot the reveal saw is stale by the second answer —
    ``Game.take_card_from_hand`` removes exactly one, by an index found through
    identity.

    CR 119.4: a player may pay life only with a life total at least the amount,
    so a seat that cannot pay is never offered the choice — it simply discards,
    which is what the sentence says happens when the cost is not paid.
    """
    from .life_and_game import can_pay_life

    victim = context.target if context.target is not None else context.caster
    seat = next((i for i, seated in enumerate(game.players) if seated is victim), None)
    revealed = context.results.get(REVEALED_HAND_CARDS)
    if seat is None or not revealed:
        return True, "resolved"
    described = dict(instruction.payload.get("filter") or {})
    amount = int(instruction.payload.get("life", 0))
    # Re-checked here rather than trusted from the lowering, for the reason
    # every other handler re-checks: the payload describes what the card said,
    # and this is the reader that decides which cards are offered.
    matching = [
        card for card in revealed
        if _card_matches_filter(card, described, game=game, owner=victim)
    ]
    for card in matching:
        paying = dataclasses.replace(
            context, caster=victim,
            results={**context.results, _DISCARDED_REVEALED_CARD: card},
        )
        discard = (
            _OracleInstruction("discard_bound_revealed_card", "", {}),
        )
        if not can_pay_life(victim, amount):
            game._execute_oracle_instruction(discard[0], paying)
            continue
        game.arm_pending_choice(
            "optional_pay", seat,
            card_name=context.card.name if context.card is not None else "",
            cost={},
            life=0,
            _source_permanent=context.source_permanent,
            _on_accept=(_OracleInstruction("pay_life", "", {"amount": amount}),),
            _on_decline=discard,
            _on_reflexive=(),
            _context=paying,
            prompt=f"Pay {amount} life to keep {card.name}?",
        )
    return True, "resolved"


@effect_handler("discard_bound_revealed_card")
def discard_bound_revealed_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """The declined branch of one of Sirocco's offers.

    The card is named rather than pointed at by a slot, which is the whole
    difference from ``discard_revealed_card`` beside it: that one is about the
    single card a reveal showed and the slot is what says *which copy*, where
    this one is one of several offers whose answers arrive in any order and
    renumber the pile as they land. ``Game.take_card_from_hand`` removes exactly
    one, by an index found through identity — a hand is the one zone where two
    copies of a card are the same object, so a filter by identity would remove
    both.
    """
    victim = context.target if context.target is not None else context.caster
    card = context.results.get(_DISCARDED_REVEALED_CARD)
    if card is None:
        return True, "resolved"
    if not game.take_card_from_hand(victim, card):
        game.log.append(f"{context.card.name}: {card.name} is no longer in hand")
        return True, "resolved"
    game.put_card_into_graveyard(victim, card)
    game.log.append(f"{victim.name} discards {card.name}")
    return True, "resolved"


@effect_handler("put_hand_cards_on_library")
def put_hand_cards_on_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Brainstorm: "…then put two cards from your hand on top of your library
    in any order." Stunted Growth: "Target player chooses three cards from
    their hand and puts them on top of their library in any order."

    The seat that owns the hand chooses which cards and in what order, so this
    arms a prompt rather than moving anything: a hand is a hidden zone and
    nothing but its owner can read it.

    **Not a discard.** CR 701.9a makes discarding a specific action that
    abilities watch — Necropotence exiles what you discard, Library of Leng
    redirects it — and none of that is happening here. Reusing the discard
    prompt with its ``to_library`` flag would have fired every one of those on a
    Brainstorm.

    Fewer cards in hand than the card names is not a failure: CR 608.2 does as
    much as it can.
    """
    recipient = instruction.payload.get("recipient")
    if recipient == "caster":
        player = context.caster
    elif recipient == "event_subject_player":
        # "At the beginning of each player's draw step, **that player** puts the
        # cards in their hand on the bottom of their library." (Teferi's Puzzle
        # Box.) The seat the fire site froze (CR 603.10), not the source's
        # controller and not `context.target` — a trigger that chose nothing
        # leaves whatever the resolution was already carrying there, which is
        # the wrong hand on every draw step but one. Through the one reader
        # every "that player" in this package goes through, so the phrase has
        # one answer.
        seat = frozen_that_player_seat(game, context)
        player = None if seat is None else game.players[seat]
    else:
        player = context.target
    if player is None or player not in game.players:
        game.log.append(f"{context.card.name}: no player to put cards back")
        return True, "resolved"
    if instruction.payload.get("whole_hand"):
        # "**the cards from** their hand" (Jester's Mask) — every one of them,
        # counted now rather than printed on the card. There is still an order
        # to choose (CR 401.4), which is what the prompt is for.
        actual = len(player.hand)
    else:
        amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
        actual = min(amount, len(player.hand))
    # How many actually went, recorded for the step that reads it back:
    # "Search that player's library for **that many** cards." Written before the
    # prompt is armed and whatever the answer is, because the number is settled
    # here — the prompt only decides the order.
    context.results[HAND_CARDS_TO_LIBRARY] = actual
    if actual <= 0:
        game.log.append(f"{player.name} has no cards to put back")
        return True, "resolved"
    game.arm_pending_choice(
        "hand_to_library", game.players.index(player), count=actual,
        # "…both on top of your library **or both on the bottom**" (Dream
        # Cache), "…on **the bottom** of their library in any order" (Teferi's
        # Puzzle Box). Carried onto the prompt so what the player is offered and
        # what an answer is checked against are one rule: without the key the
        # resolver refuses a bottoming answer outright, and with the wrong one
        # it would let a Puzzle Box be answered onto the top.
        **({"destination": instruction.payload["destination"]}
           if instruction.payload.get("destination") else {}),
    )
    game.log.append(
        f"{player.name} must choose {actual} card(s) to put back on their library"
    )
    return True, "pending_hand_to_library"


@effect_handler("return_recorded_permanents_to_hand")
def return_recorded_permanents_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…return **a creature you control** to its owner's hand." (Shrieking
    Drake, Stampeding Wildebeests, the Karoo land cycle's price, Bull Elephant,
    Ovinomancer, Waterspout Djinn.)

    The act half of a pick-then-act pair: the ``choose_permanents`` step in
    front of this one asked the controller which of their own permanents the
    sentence names, and this returns exactly those. Nothing is targeted, so
    there is no index to read and no CR 608.2b re-check to make — only the
    record.

    A permanent that has **left** since the pick is simply not returned. It was
    a different object the moment it left (CR 400.7) and the sentence never
    named the one that came back; an empty record is a legal outcome, not an
    error.

    The record's shape is the producer's, and this reader takes all three the
    engine writes under a ``permanents_from`` key — a bare id
    (``choose_permanent``), a list of ids (the sweeps), a list of ``Permanent``
    objects (``choose_permanents``, whose resolver records the objects because
    Raiding Party's reader wants them). That the channel carries three shapes is
    SET_PLAYBOOK's standing "``permanents_from`` carries two arities" gap, now
    measurably three; normalising here is the local half of it, as
    ``handlers/pump.py`` already says of itself.
    """
    recorded = (context.results or {}).get(
        str(instruction.payload.get("permanents_from", ""))
    ) or ()
    if isinstance(recorded, int) or isinstance(recorded, Permanent):
        recorded = (recorded,)
    returned: list[str] = []
    for entry in recorded:
        perm = (
            entry if isinstance(entry, Permanent)
            else game.permanent_by_id(entry) if isinstance(entry, int)
            else None
        )
        if perm is None or not game.is_on_battlefield(perm):
            continue
        name = perm.card.name
        return_permanent_to_owners_hand(game, perm, context.caster)
        returned.append(name)
    game.log.append(
        f"{context.card.name} returned {', '.join(returned)} to hand"
        if returned else f"{context.card.name}: nothing was returned to hand"
    )
    return True, "resolved"


@effect_handler("return_bound_permanent_to_hand")
def return_bound_permanent_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever this creature blocks a creature, return **that creature** to
    its owner's hand at end of combat." (Wall of Tears, CR 511.1 / CR 603.7.)

    The bounce twin of ``destroy_bound_permanent`` and ``phase_out_bound_permanent``,
    and read exactly as they are: the object is the one the ability that created
    this delay bound (CR 603.7c), carried by id in the trigger's context. By end
    of combat it may have been destroyed, removed from combat, or renumbered by
    something else leaving (CR 400.7) — so it is an id, never an index and never
    a board search.

    **No re-check of the printed noun**, for ``phase_out_bound_permanent``'s
    stated reason: the pronoun restates the trigger's own noun phrase, the
    condition already decided this creature is what the ability is about, and
    asking again at end of combat would let a creature whose type changed
    mid-combat escape a bounce CR 603.7c has already aimed at it.

    A permanent already gone is returned by nothing, which is CR 608.2b doing as
    much as it can rather than a failure.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("bound_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the permanent it named is gone")
        return True, "resolved"
    name = victim.card.name
    owner = return_permanent_to_owners_hand(game, victim, context.caster)
    game.log.append(f"{name} returned to {owner.name}'s hand")
    return True, "resolved"


@effect_handler("return_attached_permanent_to_hand")
def return_attached_permanent_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{W}: Return **enchanted creature** to its owner's hand." (Sun Clasp.)

    The bounce twin of ``destroy_attached_permanent``, and read the same way:
    CR 303.4b makes "enchanted" a name for the object this Aura is already
    attached to, so nothing is chosen, nothing is targeted, and there is no
    picker answer for the resolution context to carry.

    An Aura that has come unattached bounces nothing — the window CR 303.4c's
    state-based action has not closed yet — and the source going with it is
    ``attached_host``'s CR 603.10 last-known fallback, not this handler's
    problem.
    """
    from ._common import attached_host

    host = attached_host(game, context.source_permanent)
    if host is None or not game.is_on_battlefield(host):
        game.log.append(f"{context.card.name}: nothing attached to return")
        return True, "resolved"
    name = host.card.name
    owner = return_permanent_to_owners_hand(game, host, context.caster)
    game.log.append(f"{name} returned to {owner.name}'s hand")
    return True, "resolved"


#: Whose untap step a permanent is waiting to be returned to hand during
#: ("**During your next untap step**, as you untap your permanents, return this
#: land to its owner's hand" — Undiscovered Paradise). A seat index on the
#: permanent, written by the ability that armed it and read by the CR 614
#: ``would_untap`` replacement in `engine/replacements.py`.
#:
#: The seat is recorded rather than left implicit, unlike ``skip_next_untap``'s
#: unseated default beside it: that clause says "its controller's next untap
#: step", which the step finds by construction, and this one says **your** —
#: the ability's controller. A land that changes hands in between waits for the
#: step the card named, not for its new controller's.
RETURN_AT_NEXT_UNTAP_SEAT = "return_to_hand_at_next_untap_seat"


@effect_handler("return_self_instead_of_untapping")
def return_self_instead_of_untapping(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"During your next untap step, as you untap your permanents, return this
    land to its owner's hand." (Undiscovered Paradise.)

    This step only **arms** the effect; the return happens a step later, inside
    the untap step, through the ``would_untap`` replacement. Performing it here
    would be an ordinary self-bounce and the land would never produce the mana
    its own ability just added.

    A marker on the permanent rather than a delayed trigger, because the untap
    step gives nobody priority (CR 502.4): a delayed ability would untap the
    land, wait for the upkeep, and hand its controller a free untapped land for
    the turn — which is the one thing the card is printed to deny.

    An ability whose source has already left the battlefield arms nothing;
    CR 400.7 makes whatever comes back a different object, and this effect
    named the one that is gone.
    """
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: nothing left to return at untap")
        return True, "resolved"
    source.metadata[RETURN_AT_NEXT_UNTAP_SEAT] = game.players.index(context.caster)
    game.log.append(
        f"{context.card.name} will return to its owner's hand instead of untapping"
    )
    return True, "resolved"


@effect_handler("sacrifice_and_return_targets")
def sacrifice_and_return_targets(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Choose target artifact a player controls and target artifact card in
    that player's graveyard. If both targets are still legal as this ability
    resolves, that player simultaneously sacrifices the artifact and returns
    the artifact card to the battlefield." (Goblin Welder.)

    **The rider is the whole of what this handler adds to the two moves.**
    CR 608.2b removes an object from the stack only when *every* target is
    illegal, so with one target gone the default rule would still run the half
    that is left — an artifact sacrificed for a card that never comes back, or
    a card returned for nothing. The card says otherwise, and the payload
    carries the sentence that says it. Both roles are re-checked through
    ``roles_still_legal``, which asks the same relation table the picker
    narrowed with, so what the activator was offered and what happens here
    cannot come apart.

    **Simultaneously** (CR 608.2's "as much as possible at once") is why the
    card leaves the graveyard *before* the artifact is sacrificed into it: the
    sacrifice feeds the very pile the return reads, and the return must not be
    able to see it. Written for the rule rather than for a failing case, and
    the test beside it says so — the stamp is keyed by ordinal, so on today's
    boards the reversed order resolves to the same copy and nothing observable
    separates them. That is a fact about the stamp, not a licence.

    Who acts is "that player" — the seat the first slot's own "a player
    controls" bound — so the card comes back under *their* control, on *their*
    battlefield, which is the same seat whose graveyard it was chosen from.
    Nothing here is relative to the ability's controller, and reading it as
    "you" would let a Welder steal an opponent's artifact out of their pile.
    """
    payload = instruction.payload or {}
    roles = ((payload.get("targets") or {}).get("roles") or ())
    if len(roles) != 2:
        return False, "a weld names two roles"
    sacrificed_role, returned_role = roles[0].get("role"), roles[1].get("role")
    observer = game.players.index(context.caster)
    # The printed rider, read off the payload rather than assumed from the
    # kind. It is always present today — the lowering refuses the sentence
    # without it, because CR 608.2b's partial resolution is a card nothing here
    # implements — so this is a reader of what the card says, not a defence
    # against a payload that cannot arrive.
    if payload.get("all_targets_required") and not roles_still_legal(
        game, context, payload, observer=observer
    ):
        # Not a fizzle: CR 608.2b counters the ability only if *every* target
        # is illegal, and that is decided above this handler
        # (``legality.illegal_targets_refusal``). This is the printed
        # condition, so the ability resolves and does nothing.
        game.log.append(
            f"{context.card.name}: both targets are not still legal — nothing happens"
        )
        return True, "resolved"
    artifact = resolve_role_permanent(game, context, payload, sacrificed_role)
    stamp = resolve_role_graveyard_card(game, context, payload, returned_role)
    if artifact is None or stamp is None:
        game.log.append(f"{context.card.name}: a chosen target is gone")
        return True, "resolved"
    seat = game.controller_index_of(artifact)
    slot = game.graveyard_index_of(stamp)
    if seat is None or slot is None:
        game.log.append(f"{context.card.name}: a chosen target is gone")
        return True, "resolved"
    actor = game.players[stamp.seat]
    # Out of the pile first — see the docstring: the sacrifice below puts a
    # card into this very graveyard, and "simultaneously" means the return may
    # not see it.
    returning = actor.graveyard.pop(slot)
    game.sacrifice_permanent(artifact)
    arrival = Permanent(card=returning)
    game._put_permanent_onto_battlefield(stamp.seat, arrival, None)
    game.log.append(
        f"{context.card.name}: {actor.name} sacrifices {artifact.card.name} "
        f"and returns {returning.name} to the battlefield"
    )
    return True, "resolved"
