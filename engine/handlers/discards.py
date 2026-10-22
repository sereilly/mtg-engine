"""Discarding (CR 701.9): a card leaving its owner's hand for a graveyard.

The handler side of ``engine/grammar/lowering/_discards.py``, under its name.
Every shape the pool prints: target player discards N (chosen, or at random),
each opponent or each player discards, "up to N", a whole hand, every card a
printed phrase names, the ability's own controller, and the two fused shapes —
Bazaar of Baghdad's draw-then-discard and Kinetic Augur's
discard-then-draw-that-many. A chosen discard is a ``discard`` prompt on the
pending-choice queue, and :func:`_resolve_one_discard` is the one move its
answer makes, shared with the resolvers in ``engine/mixins/stack/choices.py``.

Split out of ``zones.py`` at the 2,000-line cap's split round. A discard of a
card a *reveal* chose ("…discards it unless they pay 1 life") is
``reveal.py``'s, beside the reveal that recorded which card.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ..counted_names import cards_sharing_a_name
from ..oracle_types import (DISCARDED_BY_SEAT, DISCARDED_INTO_GRAVEYARD,
                            DISCARDED_THIS_WAY, X_FROM_COUNT_PER_RECIPIENT)
from ._amounts import evaluate_count, resolve_amount
from ._filters import _card_matches_filter
from ._targets import frozen_that_player_seat
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


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
    if instruction.payload.get("who") in ("event_subject_player", "damaged_player"):
        # "Whenever a permanent is returned to a player's hand, **that player**
        # discards a card." (Warped Devotion); "Whenever a player casts a
        # spell, **that player** discards a card." (Oppression); "…deals damage
        # to a player, **that player** discards a card." (Abyssal Specter.) The
        # seat the firing event was about, through the one reader of the phrase
        # — the same one the random half of this sentence
        # (``discard_x_target_cards``) asks, so a chosen and a random discard
        # behind the same words name the same player.
        seat = frozen_that_player_seat(game, context)
        if seat is None:
            # Ending the effect is the honest direction: falling back to
            # ``context.target`` is exactly the wrong-hand discard this key
            # exists to stop.
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
    # …and *which* cards, for "You gain 3 life for each **land card** discarded
    # this way" (Gerrard's Verdict). Seeded empty for the count's reason: a
    # missing key and an empty list read the same to the sentence behind this
    # one, and writing it is what says this step answered. The prompt fills it
    # (`_after_discard_answered`), since nobody knows the cards until then.
    context.results.setdefault(DISCARDED_THIS_WAY, [])
    if actual <= 0:
        game.log.append(f"{target.name} has no cards to discard")
        return True, "resolved"
    # This is a non-random discard ("discards a card"), so the discarding player
    # chooses which card. Defer to a pending choice; the UI prompts the human and
    # the AI auto-resolves it. Library of Leng lets them choose top-of-library.
    player_index = game.players.index(target)
    # "Target player discards **up to** two cards": a ceiling, so fewer (none
    # included) is a legal answer. Only when printed, so every discard armed
    # before the key existed is byte-identical.
    ceiling = bool(instruction.payload.get("up_to"))
    game.arm_pending_choice(
        "discard", player_index,
        count=actual,
        **({"up_to": True} if ceiling else {}),
        allow_top_of_library=game._controls_top_of_library_discard(target),
        # The scratchpad rides the prompt: how many cards actually went is not
        # known until the seat answers, and `_after_discard_answered` is the one
        # place both answer paths (a seat's own picks and the non-interactive
        # default) reach.
        _results=context.results,
    )
    game.log.append(
        f"{target.name} may discard up to {actual} card(s)" if ceiling
        else f"{target.name} must choose {actual} card(s) to discard"
    )
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


def _resolve_one_discard(
    game: Game, player_index: int, hand_index: int, to_library: bool,
    *, took: list | None = None, cause_seat: int | None = None,
) -> bool:
    """Move one chosen card from a player's hand to their graveyard (or, with
    Library of Leng, the top of their library). Returns False on a bad index.

    *took* collects **which** card went, for the sentence behind the discard
    that asks ("You gain 3 life for each land card discarded this way",
    Gerrard's Verdict) — the chosen discard's half of the record
    ``discard_x_target_cards`` writes for a random one, under the same rule:
    a card that went to a *hidden* zone unrevealed (Library of Leng's library
    top) has undefined characteristics (CR 701.9c) and is counted, not listed.

    *cause_seat* is whose spell or ability asked for this discard, for a
    caller whose prompt is not the ``discard`` kind this function looks up — an
    opponent's pick out of a revealed hand (Coercion) is a different prompt
    armed by the same resolution. None reads it off the ``discard`` prompt.
    """
    if not (0 <= player_index < len(game.players)):
        return False
    player = game.players[player_index]
    if not (0 <= hand_index < len(player.hand)):
        return False
    card = player.hand.pop(hand_index)
    choice = game.pending_choice_of("discard", player_index)
    allow_top = bool(choice is not None and choice.data.get("allow_top_of_library"))
    if cause_seat is None and choice is not None:
        cause_seat = choice.data.get("_cause_seat")
    if to_library and allow_top:
        game.put_card_into_library(player, card, "top")
        game.log.append(f"{player.name} discarded {card.name} to the top of their library (Library of Leng)")
    else:
        # CR 614: "If a spell or ability an opponent controls causes you to
        # discard this card, put it onto the battlefield … instead of putting
        # it into your graveyard." (Dodecapod.) Asked here because this seam
        # performs Library of Leng's replacement itself, by offering the
        # destination, and so never runs the ``discard`` event `_discard_card`
        # does — one predicate and one body, read by both. A seat that chose
        # the library top above applied the Library's replacement first
        # (CR 616.1), after which there is no graveyard move left to replace.
        from ..madness import exile_madness_card
        from ..replacements import discarded_onto_battlefield

        # …and madness's (CR 702.35a: "…exiles it instead of putting it into
        # their graveyard"), for the same reason and through the same body the
        # ``discard`` event runs (`engine/madness.py`). In the event's own
        # order: Dodecapod's battlefield first, then the exile.
        if not discarded_onto_battlefield(
            game, player, card, game.discard_cause_seat(cause_seat)
        ) and not exile_madness_card(game, player, card):
            game.put_card_into_graveyard(player, card)
            game.log.append(f"{player.name} discarded {card.name}")
        if took is not None:
            took.append(card)
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
    game._announce_discard_triggers(player, card, cause_seat=cause_seat)
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
    recorded_size = instruction.payload.get("amount_from")
    if recorded_size is not None:
        # "Discard **any number** of cards at random." (Rites of Initiation.)
        # The player chose how many — the step in front of this one asked and
        # wrote the answer down — and chance chooses which. Read off the
        # scratchpad because that is where a number chosen during a resolution
        # is (CR 608.2d); an absent record is a step that never ran, and that
        # is no cards rather than the cast's X.
        amount = int(context.results.get(str(recorded_size)) or 0)
    elif not isinstance(amount, int):
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
    # What went, for the sentences behind this one — "If you discard a creature
    # card this way, return it from your graveyard …" (Aether Rift). Written as
    # empty lists and a zero on the path that takes nothing, for the reason
    # ``discard_target_cards`` writes its zero: a missing key and an empty one
    # read the same to a rider, and writing it is what says this step answered.
    took = context.results.setdefault(DISCARDED_THIS_WAY, [])
    landed = context.results.setdefault(DISCARDED_INTO_GRAVEYARD, [])
    for i in sorted(indices, reverse=True):
        discarded = target.hand.pop(i)
        pile, deck = len(target.graveyard), len(target.library)
        game._discard_card(target, discarded)  # Library of Leng -> top of library
        # CR 701.9c: a card discarded into a *hidden* zone unrevealed has
        # undefined characteristics, so "a creature card" is not something it
        # was. It still counts as a discard below.
        if len(target.library) == deck:
            took.append(discarded)
        if len(target.graveyard) > pile and target.graveyard[-1] is discarded:
            landed.append(discarded)
    context.results["discarded_count"] = (
        int(context.results.get("discarded_count") or 0) + actual
    )
    game.log.append(f"{target.name} discarded {actual} cards at random")
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
    if instruction.payload.get("who") == "damaged_player":
        # "…that player reveals their hand and discards all cards of that
        # color." (Crosis, the Purger.) The seat the damage froze; with none
        # recorded nothing is discarded, for ``reveal_hand``'s reason.
        frozen = frozen_that_player_seat(game, context)
        if frozen is None:
            game.log.append(f"{context.card.name}: no recorded player, no discard")
            return True, "resolved"
        victim = game.players[frozen]
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
    # "…discards all nonland cards with mana value **equal to the number**."
    # (Void.) The third record, a number this time, resolved into the ordinary
    # ``mana_value`` comparison. Zero is a legal number, so the test is for the
    # record rather than for its truth.
    number_key = instruction.payload.get("mana_value_from")
    if number_key is not None:
        chosen_number = context.results.get(str(number_key))
        if not isinstance(chosen_number, int) or isinstance(chosen_number, bool):
            game.log.append(
                f"{context.card.name}: no number was chosen, so nothing is discarded"
            )
            return True, "resolved"
        filters = dict(filters)
        filters["mana_value"] = {"op": "eq", "value": chosen_number}
    # "…discards all cards **of each of the sacrificed creature's colors**."
    # (Mind Extraction.) The fourth record, and the one a *cost* wrote: the
    # permanent the cast sacrificed (CR 601.2h), carried on the stack item's
    # choices as the object it was — so its colours are the ones it last had on
    # the battlefield (CR 608.2h), read through the layers and not off its
    # printed card. Resolved into the ordinary ``any_colors`` union: a
    # multicolored creature takes every card sharing **any** of its colours
    # (CR 105.2b, and the card's ruling of 2004-10-04).
    #
    # **No colour means no discard**, for the reason the colour record above
    # gives — a colorless creature, or a channel nothing paid into, read as
    # "no narrowing" would empty the hand. The hand has still been revealed.
    cost_channel = instruction.payload.get("any_colors_from_cost")
    if cost_channel is not None:
        from ..object_colors import object_colors

        paid = (context.choices or {}).get(str(cost_channel))
        shared = object_colors(game, paid)
        if not shared:
            game.log.append(
                f"{context.card.name}: "
                + ("the sacrificed permanent is colorless"
                   if paid is not None else "nothing was sacrificed")
                + ", so nothing is discarded"
            )
            return True, "resolved"
        filters = dict(filters)
        filters["any_colors"] = list(shared)
    victims = [victim]
    spared_by_seat: dict = {}
    if instruction.payload.get("who") == "each_player":
        # "Each player …, then discards all **other** nonland cards." (Noxious
        # Vapors.) Every living seat, in APNAP order (CR 101.4), each sparing
        # what *it* chose: ``spared_from`` names the per-seat record the pick in
        # front of this step wrote. An absent record spares nothing — which is
        # what "all other" means of a player who chose no card.
        from .offers import _offered_seats

        victims = [
            game.players[seat]
            for seat in _offered_seats(game, "each_player", context)
        ]
        recorded = context.results.get(
            str(instruction.payload.get("spared_from") or "")
        )
        spared_by_seat = recorded if isinstance(recorded, dict) else {}
    for victim in victims:
        # **Idiom 11, as a multiset.** Two copies of one card in a hand are one
        # object, so "is this card one of the spared ones" is not answerable by
        # identity alone — a player who kept one of two Lightning Bolts would
        # keep both. Each spared entry therefore excuses exactly one slot.
        spare = list(spared_by_seat.get(game.players.index(victim)) or ())
        doomed = []
        for index, held in enumerate(victim.hand):
            excused = next(
                (slot for slot, kept in enumerate(spare) if kept is held), None
            )
            if excused is not None:
                spare.pop(excused)
                continue
            if _card_matches_filter(held, filters, game=game, owner=victim):
                doomed.append(index)
        if instruction.payload.get("shares_name_in_hand"):
            # "…all nonland cards **with the same name as another card in their
            # hand**." (Hint of Insanity.) CR 201.2a over the pile: a card goes
            # only if some *other* card held beside it shares one of its names.
            # By position, never by identity — two copies of one card in a hand
            # are one object — and over the whole hand rather than over the
            # cards the phrase admits, because the other card is "a card", not
            # "a nonland card".
            paired = cards_sharing_a_name(victim.hand)
            doomed = [index for index in doomed if index in paired]
        for index in reversed(doomed):
            discarded = victim.hand.pop(index)
            game._discard_card(victim, discarded)
        game.log.append(
            f"{victim.name} discarded {len(doomed)} card(s)"
            if doomed else f"{victim.name} had no cards to discard"
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
    # "Discard **up to** two cards": the same ceiling with a printed number.
    ceiling = any_number or bool(instruction.payload.get("up_to"))
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
    # …and *which* cards, seeded empty for the count's reason; the prompt's
    # answer fills it (`_after_discard_answered`).
    context.results.setdefault(DISCARDED_THIS_WAY, [])
    if amount <= 0:
        game.log.append(f"{caster.name} has no cards to discard")
        return True, "resolved"
    game.arm_pending_choice(
        "discard", player_seat,
        count=amount,
        # Only when the phrase printed a ceiling, so every discard written
        # before "any number of" existed arms a byte-identical choice.
        **({"up_to": True} if ceiling else {}),
        filter=described,
        allow_top_of_library=game._controls_top_of_library_discard(caster),
        # The live scratchpad, so the answer can record how many were actually
        # discarded for the steps queued behind this prompt (see
        # ``_after_discard_answered``). Private: it holds engine objects and is
        # none of a client's business.
        _results=context.results,
    )
    game.log.append(
        f"{caster.name} may discard up to {amount} card(s)" if ceiling
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
