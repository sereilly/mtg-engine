"""A pile exiled *with* a source or *this way*, and where it goes (CR 610.3).

The handler twin of ``engine/grammar/lowering/linked_exile.py``. A pile recorded
on the exiling permanent (``engine/linked_exile.py``) or by the resolution that
made it (``EXILED_BY_SEAT``), and drained later: into a hand (Knowledge Vault,
Mangara's Tome's draw replacement, Necropotence at the end step), onto a library
(Scroll Rack), onto the battlefield (every seat's pile at once, Living Death),
or held until the source leaves or untaps (Tawnos's Coffin, with the counters it
noted; Idol of Endurance). Exiling a hand face down as such a pile
(Duplicity, Scroll Rack) is here too, because the pile is the record the rest
reads.

Split out of ``zones.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ..linked_exile import (LEAVES, UNTAPPED, link_exiled_card,
                            take_linked_entries, take_linked_entry_at,
                            until_leaves_has_ended)
# Which exiled cards are face down (CR 406.3) — its own line, so the import
# above, which rounds append to, cannot collide with it.
from ..linked_exile import face_down_exiled_cards
from ..models import Permanent
from ..oracle_types import EXILED_BY_SEAT, PUT_INTO_HAND_THIS_WAY
from ._filters import _card_matches_filter, permanent_matches_filter
from ._targets import resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


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
        # APNAP order (CR 101.4), and so the order the cards are stamped in as
        # they enter together (CR 613.7m: the active player's objects have the
        # earlier timestamps). This walked ``range(len(game.players))``, which
        # is that order only while seat 0 is the active player — a Living
        # Death cast by seat 1 stamped seat 0's creatures first. A seat that
        # has left returns nothing (CR 800.4a), as its two siblings below
        # already answer.
        seats = game.apnap_seats()
    elif who == "that_player":
        # "…**that player** returns those cards to their hand." (Suppress.) The
        # seat is read off the **record**, which is keyed by who exiled: one
        # named player emptied a hand, so the map holds one seat and that is
        # the player the words name. It is deliberately not the seat this
        # resolution happens to be carrying — that is the delay's own business
        # (*when* it fires), and a delay that binds no player hands over
        # whichever seat a targetless resolution defaults to. Read that way,
        # the same sentence behind "at the beginning of the next end step"
        # compiled and never gave back a hand its caster had aimed at
        # themselves.
        #
        # A record holding several seats is not one "that player"; the seat the
        # resolution was handed breaks the tie if it is among them, and
        # otherwise nobody's pile moves — falling back to the caster would hand
        # the spell's controller a hand the card took from somebody else.
        recorded = [
            seat for seat in by_seat
            if isinstance(seat, int) and 0 <= seat < len(game.players)
        ]
        if len(recorded) == 1:
            seats = recorded
        else:
            seats = [
                i for i, seated in enumerate(game.players)
                if seated is context.target and i in recorded
            ][:1]
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
            # Asked before the card leaves, because the answer is derived from
            # the pile: a card exiled **face down** (CR 406.3) going back to a
            # hidden zone was never shown to anybody, and a log line naming it
            # is the one place the table would learn what Suppress hid.
            hidden = any(
                held is card for held in face_down_exiled_cards(game, seat)
            )
            if not game.take_card_from_exile(player, card):
                game.log.append(
                    f"{context.card.name}: "
                    f"{'a face-down card' if hidden else card.name} "
                    "is no longer exiled"
                )
                continue
            if zone == "hand" and hidden:
                game.put_card_into_hand(player, card)
                game.log.append(
                    f"{player.name} returned a face-down card from exile to "
                    "their hand"
                )
                returned += 1
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
    described = dict(payload.get("card_filter") or {})
    # "**Target player** exiles all cards from their hand face down."
    # (Suppress.) One chosen seat's whole hand, the same act a third way round:
    # nobody picks, so nothing is asked, and the seat is the resolution's own
    # target. A **spell** has no permanent to link the pile to, so the
    # face-down record goes on the game's register instead — the arrangement
    # ``exile_top_of_library`` has for Three Wishes, made inside
    # ``exile_hand_slots`` so every caller of that seam gets it. With no target
    # nothing is exiled: the caster's own hand is not the hand the card named.
    if str(payload.get("who", "you")) == "target_player":
        victim_seat = next(
            (i for i, seated in enumerate(game.players) if seated is context.target),
            None,
        )
        if victim_seat is None:
            game.log.append(f"{context.card.name}: no player was named to exile a hand")
            return True, "resolved"
        victim = game.players[victim_seat]
        game.exile_hand_slots(
            context, source, victim_seat,
            [
                slot for slot, card in enumerate(victim.hand)
                if _card_matches_filter(card, described)
            ],
            face_down=bool(payload.get("face_down")),
        )
        return True, "resolved"
    if payload.get("face_down") and source is None:
        game.log.append("the face-down exile has no permanent to be linked to")
        return True, "resolved"
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
        if instruction.payload.get("at_random"):
            # "Choose a card **at random** that was exiled with Skyship
            # Weatherlight. Put that card into its owner's hand." The same one
            # card with nobody choosing it, so there is no prompt to arm: the
            # pick is made here, out of the list a chooser would have been
            # offered (``live_linked_exile_positions``), and through the
            # module RNG the AI simulator seeds so a seed still replays a run.
            live = game.live_linked_exile_positions(
                source,
                owner_index=(
                    seat if instruction.payload.get("owned_by_chooser") else None
                ),
            )
            name = context.card.name if context.card is not None else "that permanent"
            if not live:
                game.log.append(f"nothing is exiled with {name}")
                return True, "resolved"
            entry = take_linked_entry_at(source, random.choice(live))
            game.leave_linked_exile(entry, zone)
            game.log.append(
                f"{entry['card'].name}, chosen at random from the cards exiled "
                f"with {name}, goes to its owner's {zone}"
            )
            return True, "resolved"
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
    if until_leaves_has_ended(game, source):
        # CR 610.3b: the Idol left after its ability triggered and before it
        # resolved, so the cards do not move - there would be nothing left to
        # send them back.
        game.log.append(
            f"{context.card.name} left the battlefield before its ability "
            "resolved, so no card is exiled"
        )
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
    from ..aura_attachment import auras_attached_to

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
    returned_to = ""
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
            if destination == "battlefield":
                # "Return that card to the battlefield under **its owner's**
                # control." (Liberate.) CR 400.3 put the card in its owner's
                # exile, so the seat holding it is the owner; "under your
                # control" is the ability's controller instead, and the
                # permanent then remembers whose it is, exactly as
                # ``reanimate_bound_card`` records it. A new object either way
                # (CR 400.7): no counters, no Auras, summoning-sick.
                owner_seat = game.players.index(owner)
                seat = (
                    owner_seat
                    if instruction.payload.get("control") == "owner"
                    else game.players.index(caster)
                )
                permanent = Permanent(card=card)
                if owner_seat != seat:
                    permanent.metadata["owner_player_index"] = owner_seat
                game._put_permanent_onto_battlefield(seat, permanent, None)
                moved.append(card)
                returned_to = game.players[seat].name
                break
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
    if moved and destination == "battlefield":
        game.log.append(
            f"{', '.join(card.name for card in moved)} returned to the "
            f"battlefield under {returned_to}'s control ({context.card.name})"
        )
    elif moved:
        if destination == "hand":
            # "…until **you put a card into your hand**" (Tainted Pact). What
            # this step put there, for a stopping clause to ask about — see
            # ``oracle_types.PUT_INTO_HAND_THIS_WAY``.
            context.results[PUT_INTO_HAND_THIS_WAY] = list(moved)
        names = ", ".join(card.name for card in moved)
        # "…return it to its **owner's** hand" (Psychic Theft, Planeswalker's
        # Mischief) lands in the hand of the seat whose exile held it, which is
        # not the caster's — and the line said the caster had put it into
        # *their* hand, in a public log, about a card that went the other way.
        to_owner = bool(instruction.payload.get("to_owner"))
        game.log.append(
            (
                f"{names} returned to its owner's hand from exile"
                if to_owner
                else f"{caster.name} put {names} into their hand from exile"
            )
            if destination == "hand"
            else f"{names} was put into its owner's graveyard from exile"
        )
    elif instruction.payload.get("only_if_unplayed"):
        # Two different nothings, and the log says which: a card that was
        # played has left exile, and a conditional exile that never happened
        # ("**If it's an instant or sorcery card**, exile it" — Planeswalker's
        # Mischief, about a creature card) left no card to ask about.
        game.log.append(
            f"{context.card.name}: the exiled card was played, so nothing is "
            "moved"
            if cards else f"{context.card.name}: no card was exiled"
        )
    else:
        game.log.append(f"{context.card.name}: nothing was left in exile to take")
    return True, "resolved"
