"""The shuffles: a library put back into a random order (CR 701.24).

The handler twin of ``engine/grammar/lowering/shuffles.py``, and its axis:
*what* is shuffled in — nothing at all (the bare "then that player shuffles"), a
hand or a counted part of one (Winds of Change, Lat-Nam's Legacy), a graveyard
(Feldon's Cane), the source from a trigger that has already killed it (Alabaster
Dragon), or a chosen permanent (Rishadan Pawnshop). Where cards move, they move
and the library is shuffled as one action (CR 701.24a).

Split out of ``zones.py`` at the 2,000-line cap's split round. A shuffle answers
"what order is this library in now", which ``zones.py`` — "which zone does this
object end up in" — does not.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ..oracle_types import HAND_CARDS_TO_LIBRARY
from ._amounts import resolve_amount
from ._filters import graveyard_card_matches
from ._targets import _resolve_graveyard_slots, resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


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
