"""Handing back, one card at a time, what an earlier effect exiled — by record.

"Exile all permanents. **For as long as any of those cards remain exiled, at
the beginning of each player's upkeep, that player returns one of the exiled
cards they own to the battlefield.**" (Dimensional Breach.)

"Those cards" are the cards the sweep put into exile, and CR 400.7 is what
makes them hard to name later: a card that leaves exile and comes back is a new
object, and two copies of a card in a deck are one ``CardDefinition``, so
neither the card nor the zone says whether a card in exile is still *one of
those*. The exile register (``engine/exiled_records.py``) does — one
:class:`~engine.exiled_records.ExiledRecord` per exiled object, retired by the
one departure seam (``Game.take_card_from_exile``) as its card leaves. So the
pile is a list of records, registered once per resolution by
:func:`exiled_this_way_records` (the delayed ability's arming registers them,
CR 603.7c, and freezes the list into its ``captured``), and every reader asks
the record whether it still speaks.

Its own module rather than a corner of ``linked_exile``: a linked pile is
recorded on the permanent that exiled it (CR 607.2a, 610.3) and ended by that
permanent leaving, where these are recorded on the game and named by a spell
that is long gone. The two share the Aura return (CR 303.4f/g) and read it
through the same two predicates, ``aura_attachment.is_aura_card`` and
``returning_aura_hosts``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..aura_attachment import attach_aura, is_aura_card, returning_aura_hosts
from ..exiled_records import (EXILED_THIS_WAY_RECORDS, record_exiled_card,
                              still_exiled)
from ..entry_awaiting import entry_happened
from ..models import Permanent
from ..permanent_cards import stays_out_of_battlefield
from ..oracle_types import EXILED_CARDS_WITH_OWNERS
from ..resumption import run_resumable
from ._targets import frozen_that_player_seat
from .registry import effect_handler

if TYPE_CHECKING:
    from ..exiled_records import ExiledRecord
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


#: Where the pick and an Aura's host are recorded while the return waits for
#: them (``permanent_choice``'s ``result_key`` convention): the record chosen,
#: and the id of the permanent the Aura will enchant.
RETURN_PICK_KEY = "exiled_card_return_pick"
RETURN_HOST_KEY = "exiled_card_return_host"


def exiled_this_way_records(game: "Game", context) -> list:
    """The records "those cards" / "the exiled cards" names for this
    resolution, registering them the first time they are asked for.

    Read off the scratchpad's :data:`EXILED_THIS_WAY_RECORDS` when an earlier
    reader (the delayed ability's arming) already registered them — the frozen
    list a delayed ability carries is that same list, so a firing a turn later
    asks the very records the creating spell made. Otherwise one record per
    ``(owner_seat, card)`` pair the exile step wrote
    (:data:`~engine.oracle_types.EXILED_CARDS_WITH_OWNERS`), for a card that is
    still in that seat's exile: the step in front put it there a moment ago,
    so a card already gone (a replacement sent it elsewhere) has no record to
    make.
    """
    results = context.results if context.results is not None else {}
    held = results.get(EXILED_THIS_WAY_RECORDS)
    if held is not None:
        return list(held)
    records: list = []
    for owner_index, card in results.get(EXILED_CARDS_WITH_OWNERS) or ():
        if not (isinstance(owner_index, int) and 0 <= owner_index < len(game.players)):
            continue
        if not any(held_card is card for held_card in game.players[owner_index].exile):
            continue
        records.append(record_exiled_card(game, card, owner_index))
    results[EXILED_THIS_WAY_RECORDS] = records
    return records


def returnable_exiled_records(
    game: "Game", records, seat: int, *, owned: bool,
) -> list:
    """The records *seat* may return to the battlefield right now — the one
    answer the prompt offers, its answer is checked against, and the default
    picks from.

    A record whose card has left exile is no card at all (CR 400.7, 603.7c).
    "They own" narrows to *seat*'s own cards (CR 108.3). And "you can't pick a
    card that can't legally be returned to the battlefield" (the card's ruling,
    2004-10-04): an Aura with nothing it could enchant stays where it is
    (CR 303.4g), so it is not offered — the board is read as it stands, since
    the card enters alone and any permanent already there may be its host.
    """
    already_there = list(game.all_permanents())
    pile = []
    for record in records:
        if not still_exiled(game, record):
            continue
        if owned and record.owner_index != seat:
            continue
        if is_aura_card(record.card) and not returning_aura_hosts(
            game, seat, record.card, already_there,
        ):
            continue
        pile.append(record)
    return pile


def _chooser_seat(game: "Game", instruction, context) -> int | None:
    """Who picks: the seat the firing event froze ("that player", whose
    upkeep), or the ability's controller for a bare imperative."""
    if (instruction.payload or {}).get("chooser") == "that_player":
        return frozen_that_player_seat(game, context)
    return next(
        (seat for seat, seated in enumerate(game.players) if seated is context.caster),
        None,
    )


@effect_handler("return_one_exiled_card")
def return_one_exiled_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…that player returns one of the exiled cards they own to the
    battlefield." (Dimensional Breach.)

    Three steps, each of which may wait for an answer, through
    ``run_resumable`` — the last thing this handler does
    (``engine/resumption.py``'s rule):

    1. **the pick** — every card *seat* can return (:func:`returnable_exiled_records`);
       one is simply it, several are the ``exiled_card_return`` prompt, whose
       default for a seat nobody asks is the most valuable card;
    2. **an Aura's host** (CR 303.4f) — chosen as it enters, by the player
       putting it there, from what is already on the battlefield; an
       interactive seat with a choice is asked (``permanent_choice``), any
       other takes ``ai_targets.choose_returning_aura_host``;
    3. **the move** — out of exile through the departure seam with *this*
       record (so the record that retires is the one that spoke for the card,
       not a look-alike's), onto the battlefield under the chooser's control
       (CR 110.2a). It has just come under that control, so it is summoning
       sick (CR 302.6; the card's ruling, 2004-10-04).

    A seat with nothing to return is asked nothing.
    """
    from ..ai_targets import choose_returning_aura_host

    card_name = getattr(context.card, "name", "") or "Effect"
    seat = _chooser_seat(game, instruction, context)
    if seat is None or not 0 <= seat < len(game.players):
        game.log.append(f"{card_name}: no player to return an exiled card")
        return True, "resolved"
    owned = bool((instruction.payload or {}).get("owned_by_chooser"))
    records = exiled_this_way_records(game, context)
    context.results.pop(RETURN_PICK_KEY, None)
    context.results.pop(RETURN_HOST_KEY, None)
    player = game.players[seat]

    def step(which: str) -> None:
        if which == "pick":
            pile = returnable_exiled_records(game, records, seat, owned=owned)
            if not pile:
                game.log.append(
                    f"{player.name} has no exiled card to return ({card_name})"
                )
                return
            if len(pile) == 1:
                context.results[RETURN_PICK_KEY] = pile[0]
                return
            game.arm_exiled_card_return(
                seat, card_name=card_name, result_key=RETURN_PICK_KEY,
                records=records, owned=owned, context=context,
            )
            return
        record = context.results.get(RETURN_PICK_KEY)
        if record is None:
            return
        if which == "host":
            if not is_aura_card(record.card):
                return
            legal = returning_aura_hosts(
                game, seat, record.card, list(game.all_permanents()),
            )
            if not legal:
                context.results[RETURN_HOST_KEY] = None
                return
            if len(legal) > 1 and game.asks_a_person(seat):
                game.arm_permanent_choice(
                    seat,
                    card_name=card_name,
                    prompt=(
                        f"Choose what {record.card.name} enchants as it returns "
                        "to the battlefield."
                    ),
                    result_key=RETURN_HOST_KEY,
                    payload={
                        "legal_host_for_card": record.card,
                        "host_controller": seat,
                        "default_prefers": "returning_aura_host",
                    },
                    context=context,
                    candidates=legal,
                )
                return
            host = (
                legal[0] if len(legal) == 1
                else choose_returning_aura_host(game, seat, record.card, legal)
            )
            context.results[RETURN_HOST_KEY] = host.permanent_id
            return
        _return_record_to_battlefield(
            game, record, seat, context.results.get(RETURN_HOST_KEY), card_name,
        )

    run_resumable(game, ["pick", "host", "move"], step)
    return True, "resolved"


def _return_record_to_battlefield(
    game: "Game", record: "ExiledRecord", seat: int, host_id, card_name: str,
) -> None:
    """Move *record*'s card onto the battlefield under *seat*'s control.

    Asked again here, because the pick and the move are two moments: the card
    must still be one of those cards (an answer can wait, and anything at all
    can happen to a card in exile while it does), and an Aura's host must
    still be a legal one as it enters (CR 303.4f) — without one the Aura
    stays exiled (CR 303.4g).
    """
    card = record.card
    owner = game.players[record.owner_index]
    if not still_exiled(game, record):
        game.log.append(f"{card_name}: {card.name} is no longer exiled")
        return
    # CR 400.4a, asked before the card leaves exile (``permanent_cards``).
    if stays_out_of_battlefield(game, card, owner, "exile"):
        return
    host = None
    if is_aura_card(card):
        host = game.permanent_by_id(host_id) if isinstance(host_id, int) else None
        if host is None or not returning_aura_hosts(game, seat, card, [host]):
            game.log.append(
                f"{card.name} has nothing it could enchant and stays in "
                f"{owner.name}'s exile"
            )
            return
    game.take_card_from_exile(owner, card, record=record)
    arrival = Permanent(card=card)
    if seat != record.owner_index:
        # CR 108.3: ownership never moves, and the entry is handed one seat
        # for both (``Game.leave_linked_exile``'s reason).
        arrival.metadata["owner_player_index"] = record.owner_index

    # Attached once it is there — the entry's ``then``, at the answer when an
    # "as it enters" choice keeps it on its way (CR 614.12a).
    def arrived() -> None:
        # Said once it is there, and only if it got there
        # (``entry_awaiting.entry_happened``): a returning creature nobody cast
        # is exiled again under Containment Priest, which says so itself. (The
        # seam's "its delayed ability ends", for the last card leaving, is
        # written as the card leaves, ahead of this.)
        if not entry_happened(arrival):
            return
        game.log.append(
            f"{game.players[seat].name} returned {card.name} to the battlefield"
            + (f" enchanting {host.card.name}" if host is not None else "")
            + f" ({card_name})"
        )
        if host is not None:
            attach_aura(arrival, host)
        game._recompute_continuous_effects()

    game._put_permanent_onto_battlefield(seat, arrival, None, then=arrived)
