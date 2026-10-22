"""An **ownership** change and the ante (CR 108.3, CR 407).

The handler twin of ``engine/grammar/lowering/ownership.py``. CR 108.3 fixes a
card's owner for the whole game, and the ante rules are where the exception
lives: cards anted (Demonic Attorney, Rebirth, Jeweled Bird, Darkpact), and the
three exchanges of ownership — Bronze Tablet, Timmerian Fiends and Tempest
Efreet — which may move no card at all, because what changes is whose the card
is when the game ends.

Split out of ``zones.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

import dataclasses
import random
from typing import TYPE_CHECKING

# The runtime class. The bare name is a TYPE_CHECKING-only import below, and
# the handlers here *build* instructions for an optional payment's branches.
from ..oracle_types import OracleInstruction as _OracleInstruction
from ..resumption import run_resumable
from ._targets import resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


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
