from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ..keywords import grant_keyword
from ..models import Permanent
from ._common import (
    _card_matches_filter,
    graveyard_card_matches,
    permanent_matches_filter,
    resolve_amount,
    resolve_target_permanent,
    resolve_target_permanents,
)
# The runtime class. The bare name is a TYPE_CHECKING-only import above, and
# two handlers here *build* instructions for an optional payment's branches.
from ..oracle_types import OracleInstruction as _OracleInstruction
from ..resumption import run_resumable
from ..search_filters import search_matches
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("draw_target_cards")
def draw_target_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    count = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    drawn = game._draw_with_replacements(target, count)
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
    drawn = game._draw_with_replacements(caster, draw_count)
    game.log.append(f"{card.name}: {caster.name} drew {drawn} card(s)")

    actual_discard = min(discard_count, len(caster.hand))
    if actual_discard <= 0:
        return True, "resolved"
    player_index = game.players.index(caster)
    game.arm_pending_choice(
        "discard", player_index,
        count=actual_discard,
        allow_top_of_library=game._controls_top_of_library_discard(caster),
    )
    game.log.append(f"{caster.name} must choose {actual_discard} card(s) to discard")
    return True, "pending_discard"


@effect_handler("discard_hand_ante_then_draw_seven")
def discard_hand_ante_then_draw_seven(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Contract from Below: "Discard your hand, ante the top card of your
    library, then draw seven cards." The anted card goes to the ante zone
    (CR 407), not the graveyard."""
    caster = context.caster
    card = context.card
    while caster.hand:
        caster.graveyard.append(caster.hand.pop(0))
    if caster.library:
        # CR 407.4: the caster owns the cards in their own library, so they are
        # the player who can ante the top one.
        game.ante_object(game.players.index(caster), caster.library.pop(0))
    drawn = game._draw_with_replacements(caster, 7)
    game.log.append(f"{card.name} resolved: discarded hand and drew {drawn} cards")
    return True, "resolved"


@effect_handler("each_player_antes_top_card")
def each_player_antes_top_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    anted = 0
    # CR 407.4: each player antes their own top card, so every ante is made by
    # that card's owner.
    for index, player in enumerate(game.players):
        if player.library:
            game.ante_object(index, player.library.pop(0))
            anted += 1
    game.log.append(f"{card.name} anted {anted} card(s)")
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
    caster.graveyard.extend(others)
    if others:
        game.log.append(
            f"{card.name} put {len(others)} other card(s) {caster.name} owns "
            "from the ante into their graveyard"
        )
    drawn = game._draw_with_replacements(caster, 1)
    game.log.append(f"{card.name} drew {drawn} card")
    return True, "resolved"


@effect_handler("wheel_of_fortune")
def wheel_of_fortune(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    for player in game.players:
        while player.hand:
            player.graveyard.append(player.hand.pop(0))
        game._draw_with_replacements(player, 7)
    game.log.append("Wheel effect resolved for all players")
    return True, "resolved"


@effect_handler("timetwister")
def timetwister(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    for player in game.players:
        pool = player.library + player.hand + player.graveyard
        player.library = list(pool)
        player.hand = []
        player.graveyard = []
        game._draw_with_replacements(player, 7)
    game.log.append("Timetwister effect resolved for all players")
    return True, "resolved"


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
        seat = (context.trigger_context or {}).get(str(named))
        if seat is None:
            # The trigger that would have recorded it did not: CR 603.10's
            # last-known information is simply absent, so the effect falls back
            # to its controller rather than guessing a seat.
            continue
        seats[key] = int(seat)
    game.arm_pending_choice(
        "search_library", caster_index,
        **seats,
        count=instruction.payload.get("count", 1),
        card_type=instruction.payload.get("card_type", "any"),
        zones=zones,
        restrictions=dict(instruction.payload.get("restrictions") or {}),
        destination=instruction.payload.get("destination", "hand"),
        # "…put one onto the battlefield tapped and the other into your hand"
        # (Cultivate): one entry per find, in the printed order. A counted
        # search is answered whole — every find in one pick list — and which
        # find fills which slot is then its own question, asked through the
        # `search_destination` prompt when the slots differ.
        destinations=list(instruction.payload.get("destinations") or ()),
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
        # "…, reveal it/those cards, …" (CR 701.20): the finds are shown to
        # every player, which the resolution records as one reveal event when
        # the search ends. A search that does not print the word shows nothing.
        reveal=bool(instruction.payload.get("reveal")),
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
    actual = min(
        resolve_amount(instruction.payload.get("amount", 0), context.x_value), len(target.hand)
    )
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
        player.graveyard.append(card)
        game.log.append(f"{player.name} discarded {card.name}")
    return True


@effect_handler("discard_x_target_cards")
def discard_x_target_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    x_value = context.x_value
    x = max(0, x_value or 0)
    actual = min(x, len(target.hand))
    indices = random.sample(range(len(target.hand)), actual)
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
    game.players[seat].graveyard.append(card)
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
        holder = game.players[from_seat]
        if card in holder.exile:
            holder.exile.remove(card)
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
        if card in holder.exile:
            holder.exile.remove(card)
        holder.graveyard.append(card)
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
    seat = game.players.index(context.target) if context.target in game.players else None
    if seat is None:
        game.log.append(f"{context.card.name}: no player chosen")
        return True, "resolved"
    victim = game.players[seat]
    card_type = str(instruction.payload.get("card_type", "artifact"))

    def _eligible(card) -> bool:
        return card_type in (getattr(card, "type_line", "") or "").lower()

    # "Any number" prints no maximum, so the cap is the pile itself.
    picked = _resolve_graveyard_slots(victim, context, len(victim.graveyard), _eligible)
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


@effect_handler("return_creature_from_graveyard_to_hand")
def return_creature_from_graveyard_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    any_card = bool(instruction.payload.get("any_card"))
    card_type = instruction.payload.get("card_type")
    card_types = tuple(instruction.payload.get("card_types") or ())

    def _eligible(card) -> bool:
        # The picker's predicate, not a third spelling of it. The payload and
        # the spec carry the same key names because one is derived from the
        # other, so there is one answer to "may this card be chosen?".
        return graveyard_card_matches(instruction.payload, card)

    # "Return up to two target creature cards from your graveyard to your hand."
    # (Sanguine Indulgence.) The several-targets description says a list was
    # collected, so every chosen slot is honoured rather than only the first.
    targets_desc = instruction.payload.get("targets") or {}
    if (
        isinstance(targets_desc, dict)
        and isinstance(targets_desc.get("count"), int)
        and targets_desc["count"] > 1
    ):
        picked = _resolve_graveyard_slots(
            caster, context, targets_desc["count"], _eligible
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
    if isinstance(idx, int) and 0 <= idx < len(caster.graveyard) and _eligible(
        caster.graveyard[idx]
    ):
        chosen = caster.graveyard.pop(idx)
        game.put_card_into_hand(caster, chosen)
        game.log.append(f"Returned {chosen.name} from graveyard to hand")
        return True, "resolved"
    if card_types:
        chosen_index = next(
            (i for i, c in enumerate(caster.graveyard) if _eligible(c)), None
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
            (i for i, c in enumerate(caster.graveyard) if _eligible(c)), None
        )
        if chosen_index is None:
            game.log.append(f"No {card_type} card in graveyard to return")
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
    source_player = caster
    if instruction.payload.get("any_graveyard") and context.target is not None:
        source_player = context.target
    reanimated = game._reanimate_creature_to_battlefield(caster, source_player, idx)
    # "It gains haste." — folded into the reanimation because the permanent
    # does not exist until this step runs. The newest arrival on the caster's
    # battlefield is the reanimated creature.
    gains = tuple(instruction.payload.get("gains") or ())
    if reanimated and gains:
        caster_index = game.players.index(caster)
        arrivals = list(game.controlled_by(caster_index))
        if arrivals:
            newest = arrivals[-1]
            for keyword in gains:
                grant_keyword(newest, keyword)
    game.log.append("Reanimated creature to battlefield" if reanimated else "No creature to reanimate")
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
    tapped = bool(instruction.payload.get("tapped"))
    game._put_permanent_onto_battlefield(
        game.players.index(caster), Permanent(card=card, tapped=tapped), None
    )
    game.log.append(
        f"{card.name} returned from the graveyard to the battlefield"
        + (" tapped" if tapped else "")
    )
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
    if isinstance(targets_desc, dict) and isinstance(targets_desc.get("count"), int) and targets_desc["count"] > 1:
        chosen = resolve_target_permanents(game, context)
        for perm in chosen:
            owner_idx = game.owner_index_of(perm)
            owner = game.players[owner_idx] if owner_idx is not None else context.caster
            game.put_card_into_hand(owner, perm.card)
            if owner_idx is not None:
                game.permanents_to_hand_this_turn[owner_idx] = (
                    game.permanents_to_hand_this_turn.get(owner_idx, 0) + 1
                )
            game.remove_from_battlefield(perm)
            game.log.append(f"{perm.card.name} returned to {owner.name}'s hand")
        if not chosen:
            game.log.append("No creatures to return")
        return True, "resolved"
    # A narrowed or widened bounce ("up to one target non-Spirit creature",
    # Roaming Ghostlight; "up to one other target creature or planeswalker",
    # Barrin) carries its filter. Resolved strictly — no fallback scan, since
    # "up to one" legally names nothing — and enforced here so a stale or
    # illegal choice bounces nothing rather than the wrong thing.
    bounce_filter = instruction.payload.get("filter")
    if bounce_filter:
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
        owner_idx = game.owner_index_of(perm)
        owner = game.players[owner_idx] if owner_idx is not None else context.caster
        game.put_card_into_hand(owner, perm.card)
        if owner_idx is not None:
            game.permanents_to_hand_this_turn[owner_idx] = (
                game.permanents_to_hand_this_turn.get(owner_idx, 0) + 1
            )
        game.remove_from_battlefield(perm)
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
    index = context.target_permanent_index
    returned = (
        game.permanent_at(game.players.index(target), index)
        if isinstance(index, int) else None
    )
    bounced = game._bounce_target_creature(target, context.target_permanent_index)
    if bounced and returned is not None:
        context.results["returned_mana_value"] = _mana_value_of(returned.card)
    game.log.append("Returned creature to hand" if bounced else "No creature to return")
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
        default_name=_commonest_visible_name(game, seat, instruction.payload),
    )
    return True, "pending_name_and_strip"


def _commonest_visible_name(game, seat: int, payload: dict) -> str:
    """The name a non-interactive seat picks: the one appearing most often in
    the zones the search reaches, ties broken by name so a seed replays exactly.

    Basic land names are excluded because the card forbids them — the default
    has to obey the same restriction the prompt does, or a headless game would
    make a choice a player could not.
    """
    from collections import Counter

    player = game.players[seat]
    counts: Counter = Counter()
    for zone in payload.get("zones") or ():
        for card in getattr(player, zone, []):
            if "basic" in (card.type_line or "").lower():
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
    seat = context.results.get(payload.get("whose"))
    if seat is None:
        game.log.append(f"{context.card.name}: nobody to reveal from")
        return True, "resolved"
    player = game.players[seat]
    described = dict(payload.get("filter") or {})

    revealed: list = []
    found = None
    while player.library:
        card = player.library.pop(0)
        if _card_matches_filter(card, described):
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
    if payload.get("rest") == "shuffle_into_library":
        player.library.extend(revealed)
        # Through the module RNG `run_ai_simulation` seeds, like every other
        # shuffle in the engine, so a given seed still replays exactly.
        random.shuffle(player.library)
    else:
        player.graveyard.extend(revealed)
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
    """
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
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
            return True, "resolved"
        game.log.append(f"{context.card.name}: nothing to exile")
        return True, "resolved"
    owner_index = game.owner_index_of(source)
    owner = game.players[owner_index] if owner_index is not None else context.caster
    game.remove_from_battlefield(source)
    if not source.metadata.get("is_token", False):
        # CR 111.7: a token ceases to exist rather than going to exile.
        owner.exile.append(source.card)
    context.results["exiled_self"] = True
    game.log.append(f"{source.card.name} was exiled")
    return True, "resolved"


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
    perm = resolve_target_permanent(
        game,
        context,
        predicate=lambda candidate: permanent_matches_filter(candidate, payload),
    )
    if perm is None:
        game.log.append(f"{card.name}: no valid permanent to exile")
        return True, "resolved"
    controller_index = game.controller_index_of(perm)
    owner_index = game.owner_index_of(perm)
    game.remove_from_battlefield(perm)
    if owner_index is None:
        owner_index = controller_index if controller_index is not None else 0
    game.players[owner_index].exile.append(perm.card)
    if controller_index is not None:
        context.results["exiled_permanent_controller"] = controller_index
    game.log.append(f"{card.name} exiled {perm.card.name}")
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
    legal = [
        index
        for index, held in enumerate(victim.hand)
        if search_matches(held, {"exclude_types": exclude_types})
    ]
    game.log.append(
        f"{victim.name} revealed their hand ({len(victim.hand)} card(s)) to {card.name}"
    )
    if not legal:
        game.log.append(f"{card.name}: no card in that hand can be chosen")
        return True, "resolved"
    game.arm_pending_choice(
        "revealed_hand_pick", caster_index,
        card_name=card.name,
        victim_index=victim_index,
        legal_indices=legal,
        fate=str(instruction.payload.get("fate", "discard")),
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
    victim = context.target if context.target is not None else context.caster
    exiled = list(victim.graveyard)
    victim.graveyard.clear()
    victim.exile.extend(exiled)
    game.log.append(
        f"{context.card.name} exiled {victim.name}'s graveyard ({len(exiled)} card(s))"
    )
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
    # Record the reveal so the UI can show the viewer the actual cards in the
    # target player's hand (Glasses of Urza). The viewer is the ability's
    # controller; the target is the player whose hand is looked at.
    viewer_index = game.players.index(viewer)
    # Only the most recent reveal is shown, so a second look replaces the first
    # rather than queueing behind it.
    game.clear_pending_choices("hand_reveal", viewer_index)
    game.arm_pending_choice(
        "hand_reveal", viewer_index,
        target_index=game.players.index(target),
        card_names=[c.name for c in target.hand],
    )
    seen = len(target.hand)
    game.log.append(f"{card.name}: {viewer.name} looked at {target.name}'s hand ({seen} cards)")
    return True, "resolved"


@effect_handler("mill_target_player")
def mill_target_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """CR 701.13a: put the top N cards of a player's library into their
    graveyard.

    Milling fewer than N because the library ran out is not a loss — CR 704.5b
    only fires when a player actually *attempts to draw* from an empty library,
    so this stops at whatever is there.

    The same ``recipient`` key ``target_loses_life`` reads: absent means the
    spell's target, "caster" the controller ("Mill four cards."),
    "each_opponent" every living opponent. Each miller mills their own library,
    which is why the loop is per victim rather than a shared count.
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
    else:
        victims = [context.target]
    for victim in victims:
        milled = 0
        for _ in range(amount):
            if not victim.library:
                break
            victim.graveyard.append(victim.library.pop(0))
            milled += 1
        game.log.append(f"{victim.name} milled {milled} card(s)")
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
            game.put_card_into_hand(owner_index, permanent.card)
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
    Game.phase_out_permanent, and the creature returns at its controller's
    next untap step."""
    target_perm = resolve_target_permanent(game, context)
    if target_perm is None or not target_perm.is_creature:
        game.log.append(f"{context.card.name}: no valid creature target")
        return True, "resolved"
    game.phase_out_permanent(target_perm)
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
    Voyager's −3.) A zone change, not a destruction: no dies-trigger fires and
    regeneration cannot save it. The card goes to its *owner's* library
    (CR 400.3), whoever controlled the permanent."""
    target_perm = resolve_target_permanent(game, context)
    if target_perm is None or not target_perm.is_creature:
        game.log.append(f"{context.card.name}: no valid creature target")
        return True, "resolved"
    owner_idx = game.owner_index_of(target_perm)
    owner = game.players[owner_idx] if owner_idx is not None else context.caster
    game.remove_from_battlefield(target_perm)
    game._remove_aura_effects(target_perm)
    game.put_card_into_library(owner, target_perm.card, "top")
    game.log.append(
        f"{context.card.name}: {target_perm.card.name} put on top of {owner.name}'s library"
    )
    return True, "resolved"


# CR 110.4: the card types that are permanents — what "permanent card" means
# when Ugin's −10 reads your hand.
_PERMANENT_TYPES = ("artifact", "creature", "enchantment", "land", "planeswalker")


@effect_handler("put_cards_from_hand_onto_battlefield")
def put_cards_from_hand_onto_battlefield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put up to seven permanent cards from your hand onto the battlefield."
    (Ugin, the Spirit Dragon's −10.) Non-interactive seats take every eligible
    card up to the cap, in hand order — "up to" makes any subset legal, and
    more battlefield is the default the AI already plays toward."""
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

    chosen = [card for card in caster.hand if eligible(card)][:count]
    caster_index = game.players.index(caster)
    for card in chosen:
        caster.hand = [c for c in caster.hand if c is not card]
        game._put_permanent_onto_battlefield(caster_index, Permanent(card=card), None)
        game.log.append(f"{caster.name} put {card.name} onto the battlefield")
    if not chosen:
        game.log.append(f"{caster.name} put no cards onto the battlefield")
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

    def matches(perm: Permanent) -> bool:
        type_filter = payload.get("type_filter")
        if type_filter and not permanent_matches_filter(perm, {"type_filter": type_filter}):
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
    for perm in victims:
        owner_idx = game.owner_index_of(perm)
        owner = game.players[owner_idx] if owner_idx is not None else context.caster
        if not perm.metadata.get("is_token", False):
            owner.exile.append(perm.card)
        game._remove_aura_effects(perm)
    game.remove_all_from_battlefield(victims)
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
    caster = context.caster
    if not caster.library:
        game.log.append(f"{caster.name} has no library to reveal from")
        return True, "resolved"
    top = caster.library[0]
    context.results["revealed_card"] = top
    game.log.append(f"{caster.name} revealed {top.name} from the top of their library")
    game.record_reveal(game.players.index(caster), [top.name])
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
    anything watching discards sees them."""
    caster = context.caster
    discarded = list(caster.hand)
    caster.hand = []
    for card in discarded:
        game._discard_card(caster, card)
    game.log.append(f"{caster.name} discarded their hand ({len(discarded)} card(s))")
    return True, "resolved"


@effect_handler("each_player_discards_a_card")
def each_player_discards_a_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each player discards a card." (Liliana, Waker of the Dead's +1.)

    Who could not is recorded in the resolution scratchpad, because the
    printed rider "Each opponent who can't loses 3 life." reads it. An
    interactive seat's choice goes through the discard prompt; a
    non-interactive seat discards its first card, matching the existing
    discard default."""
    could_not: list[int] = []
    for seat, player in enumerate(game.players):
        if player.lost:
            continue
        if not player.hand:
            could_not.append(seat)
            game.log.append(f"{player.name} cannot discard (empty hand)")
            continue
        if seat in game.interactive_seats:
            game.arm_pending_choice(
                "discard", seat,
                count=1,
                allow_top_of_library=game._controls_top_of_library_discard(player),
            )
            game.log.append(f"{player.name} must choose a card to discard")
        else:
            card = player.hand[0]
            player.hand = [c for c in player.hand if c is not card]
            game._discard_card(player, card)
            game.log.append(f"{player.name} discarded {card.name}")
    context.results["players_who_could_not_discard"] = could_not
    return True, "resolved"


@effect_handler("exile_top_of_library")
def exile_top_of_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile the top three cards of your library." (Chandra, Heart of Fire's
    +1.) The exiled cards are recorded under ``exiled_cards`` for the same
    resolution's "you may play cards exiled this way" to read — the exile is
    what makes that sentence mean anything."""
    caster = context.caster
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    exiled = []
    for _ in range(min(amount, len(caster.library))):
        card = caster.library.pop(0)
        caster.exile.append(card)
        exiled.append(card)
    context.results["exiled_cards"] = exiled
    if exiled:
        game.log.append(
            f"{caster.name} exiled {', '.join(card.name for card in exiled)} "
            "from the top of their library"
        )
    else:
        game.log.append(f"{caster.name} has no cards left to exile")
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
    caster = context.caster
    caster_index = game.players.index(caster)
    game.arm_pending_choice(
        "search_exile_cards", caster_index,
        zones=tuple(instruction.payload.get("zones") or ("graveyard", "library")),
        card_types=tuple(instruction.payload.get("card_types") or ()),
        colors=tuple(instruction.payload.get("colors") or ()),
        _context=context,
    )
    game.log.append(f"{caster.name} is searching their graveyard and library")
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
    held = list(source.metadata.get("exiled_until_leaves") or ())
    for card in taken:
        caster.graveyard.remove(card)
        caster.exile.append(card)
        held.append({"owner_index": owner_index, "card": card, "to": "graveyard"})
    source.metadata["exiled_until_leaves"] = held
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
    those counters put on it (CR 121.6), so CR 614 may change how many arrive
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
    held = list(source.metadata.get("exiled_until_leaves") or ())
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
    source.metadata["exiled_until_leaves"] = held + entries
    game.log.append(
        f"{context.card.name} exiled {victim.card.name}"
        + (f" and {len(auras)} Aura(s)" if auras else "")
    )
    return True, "resolved"


@effect_handler("grant_cast_permission")
def grant_cast_permission(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """A cast-or-play permission (CR 601.3) over cards in a named zone —
    engine/cast_permissions.py holds the state, the cast path asks it, and
    cleanup expires the turn-scoped grants. Three payload forms, matching the
    printed sentences the lowering admits."""
    from ..cast_permissions import grant_permission

    caster = context.caster
    caster_index = game.players.index(caster)
    payload = instruction.payload
    duration = payload.get("duration")
    source_name = context.card.name if context.card is not None else ""

    if payload.get("cards_from") == "exiled_cards":
        cards = list(context.results.get("exiled_cards") or [])
        if not cards:
            game.log.append(f"{source_name}: nothing was exiled, so there is nothing to permit")
            return True, "resolved"
        grant_permission(
            game, player_index=caster_index, zone=payload.get("zone", "exile"),
            mode=payload.get("mode", "cast"), cards=cards,
            duration=duration, source_name=source_name,
            source_permanent_id=game.permanent_id_of(context.source_permanent),
        )
        game.log.append(
            f"{caster.name} may {payload.get('mode', 'cast')} "
            f"{', '.join(card.name for card in cards)} from exile this turn"
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
        held = list((source.metadata.get("exiled_until_leaves") or ()) if source else ())
        cards = [
            entry["card"] for entry in held
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
        card_types = tuple(payload.get("card_types") or ())
        colors = tuple(payload.get("colors") or ())

        def _legal(card) -> bool:
            if card_types and card.primary_type not in card_types:
                return False
            if colors and not any(color in card.colors for color in colors):
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
    caster = context.caster
    payload = instruction.payload
    # "Look at **that many** cards" (Garruk's Harbinger): the number the firing
    # event carried, frozen by the fire site. An absent record looks at nothing
    # rather than falling back to a count the card never printed.
    from_trigger = payload.get("amount_from_trigger")
    if from_trigger is not None:
        amount = max(0, int((context.trigger_context or {}).get(from_trigger, 0)))
    else:
        amount = resolve_amount(payload.get("amount", 0), context.x_value)
    top_count = min(amount, len(caster.library))
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
    # The narrowing, the optionality and the order the rest go back in all ride
    # the prompt, so what is offered, what an answer is checked against and what
    # a non-interactive seat takes are one rule (``live_look_top_candidates``).
    game.arm_pending_choice(
        "look_top_pick", caster_index,
        top_count=top_count, amount=amount, card_name=context.card.name,
        filter=_merged_pick_filter(payload.get("filters") or ()),
        filters=tuple(payload.get("filters") or ()),
        optional=bool(payload.get("optional")),
        rest_order=payload.get("rest_order", "any"),
        rest_destination=payload.get("rest_destination", "library_bottom"),
    )
    game.log.append(f"{caster.name} is looking at the top {top_count} cards of their library")
    return True, "pending_look_top_pick"


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
    eligible = [card for card in caster.hand if _card_matches_filter(card, described)]
    amount = min(
        resolve_amount(instruction.payload.get("amount", 0), context.x_value), len(eligible)
    )
    if amount <= 0:
        game.log.append(f"{caster.name} has no cards to discard")
        return True, "resolved"
    player_index = game.players.index(caster)
    game.arm_pending_choice(
        "discard", player_index,
        count=amount,
        filter=described,
        allow_top_of_library=game._controls_top_of_library_discard(caster),
    )
    game.log.append(f"{caster.name} must choose {amount} card(s) to discard")
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
    card = caster.graveyard.pop(idx)
    game.put_card_into_library(caster, card)
    game.log.append(f"{context.card.name}: {card.name} put on the bottom of {caster.name}'s library")
    return True, "resolved"


@effect_handler("return_spell_or_creature_to_hand")
def return_spell_or_creature_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return target spell or creature to its owner's hand." (Unsubstantiate.)
    A chosen spell is unstacked to its owner's hand — not countered, so
    nothing is binned and no counter triggers fire; a chosen creature is the
    ordinary bounce."""
    chosen = context.stack_target
    if chosen is not None and chosen in game.stack:
        game.stack.remove(chosen)
        owner = game.players[chosen.caster_index]
        game.put_card_into_hand(owner, chosen.card)
        game.log.append(
            f"{context.card.name} returned {chosen.card.name} from the stack "
            f"to {owner.name}'s hand"
        )
        return True, "resolved"
    bounced = game._bounce_target_creature(context.target, context.target_permanent_index)
    game.log.append(
        "Returned creature to hand" if bounced else f"{context.card.name}: nothing was returned"
    )
    return True, "resolved"


@effect_handler("shuffle_hand_into_library")
def shuffle_hand_into_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Winds of Change: "Each player shuffles the cards from their hand into
    their library, then draws that many cards."

    CR 701.19 — the cards move and the library is shuffled as one action, so
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
    for player in players:
        moved = len(player.hand)
        player.library.extend(player.hand)
        player.hand.clear()
        # Through the module-level RNG every other shuffle uses, so a seeded run
        # stays reproducible (the determinism invariant).
        random.shuffle(player.library)
        game.log.append(
            f"{player.name} shuffled {moved} card(s) from their hand into their library"
        )
        if then_draw and moved:
            game._draw_with_replacements(player, moved)
    return True, "resolved"


@effect_handler("shuffle_graveyard_into_library")
def shuffle_graveyard_into_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Feldon's Cane: "{T}, Exile this artifact: Shuffle your graveyard into
    your library."

    CR 701.19: the cards move and the library is shuffled as one action, so
    there is nothing to schedule and nothing that can observe a half-moved
    zone. The graveyard is emptied rather than filtered — every card in it
    goes, which is what "your graveyard" means.
    """
    whose = str(instruction.payload.get("whose", "you"))
    player = context.caster if whose == "you" else context.target
    if player is None:
        return False, "no player to shuffle"
    moved = len(player.graveyard)
    player.library.extend(player.graveyard)
    player.graveyard.clear()
    # Through the module-level RNG every other shuffle uses, so a seeded run
    # stays reproducible (the determinism invariant).
    random.shuffle(player.library)
    game.log.append(
        f"{player.name} shuffled {moved} card(s) from their graveyard into their library"
    )
    return True, "resolved"
