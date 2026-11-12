"""What a card **reveals** (CR 701.20a) off a **library's top**: a card shown to
every player.

The handler twin of the first half of ``engine/grammar/lowering/reveal.py``: the
top of a library sorted by a chosen name or a printed phrase (Wood Sage, Mulch),
chosen from by an opponent (Thran Tome, Guided Passage), revealed until a match
(Transmogrify, Thought Dissector's second stop), and turned up and put somewhere
(Call of the Wild, Game Preserve, Track Down's record for the sentence behind
it). The reveal-until run is the part that grows: each stop and each fate a new
printing gives "the rest" lands in :func:`reveal_until_match`.

Split out of ``zones.py`` at the 2,000-line cap's split round, and cut again at
the pre-Fifth-Dawn split round on the line this docstring drew between its two
halves: the reveals of a **hand** — the bare reveal, Duress's
reveal-and-choose, Stromgald Spy's standing reveal, and the card revealed at
random with what the sentences behind it do with that card — are
``hand_reveals.py``'s. A **look** (the private half, which shows a card to one
player) is ``library.py``'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..faces import has_name
from ..entry_awaiting import entry_happened
from ..models import Permanent
from ..permanent_cards import stays_out_of_battlefield
from ..oracle_types import REVEALED_TOP_CARDS_BY_SEAT
from ..search_filters import card_has_type
from ._amounts import resolve_amount
from ._chosen import _resolve_chosen_subtype
from ._filters import _card_matches_filter
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


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
    what the reveal showed \u2014 ``hand_reveals.reveal_hand_and_choose`` one zone
    over records the same reasoning. What is new here is *who* chooses:
    CR 608.2c makes the ability's controller the actor for everything the
    sentence does not say otherwise about, and this sentence says otherwise, so
    the prompt is queued on the opponent's seat with the revealer's carried as
    payload.

    CR 701.20 moves nothing, so the cards stay on top of the library and the
    answer moves exactly one of them. Fewer cards than the printed number is a
    legal board \u2014 the reveal shows what is there \u2014 and an empty library shows
    nothing and chooses nothing.
    """
    caster = context.caster
    caster_index = game.players.index(caster)
    chooser_from = instruction.payload.get("chooser_from")
    if chooser_from is not None:
        # "**An opponent** chooses a creature card from among them." (Animal
        # Magnetism.) The seat ``choose_opponent`` wrote one step up (CR
        # 608.2d); none recorded is nobody to choose, and nothing is asked.
        recorded = context.results.get(str(chooser_from))
        opponent = (
            game.players[recorded]
            if isinstance(recorded, int) and 0 <= recorded < len(game.players)
            else None
        )
    else:
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
    # "An opponent chooses **a creature card** from among them." (Animal
    # Magnetism.) The printed narrowing, as the list of revealed slots the
    # chooser may name — offered by the prompt and re-checked by its
    # resolver, so the two cannot disagree. Absent is "one of those cards":
    # every slot.
    pick_filter = instruction.payload.get("pick_filter")
    legal = [
        index for index, card in enumerate(revealed)
        if pick_filter is None
        or _card_matches_filter(card, dict(pick_filter), game=game, owner=caster)
    ]
    other_fate = instruction.payload.get("other_fate")
    if not legal:
        # Nothing the sentence lets the opponent name: no choice is made
        # (CR 608.2: as much as possible), and the rest — every revealed
        # card — still goes where the card sends it.
        game.log.append(
            f"{context.card.name}: no revealed card can be chosen"
        )
        if other_fate:
            # One event (CR 603.6a).
            with game.entering_together():
                for card in revealed:
                    if game._move_picked_pile_card(caster, card, from_zone, str(other_fate)):
                        game.log.append(f"{card.name} goes to the {other_fate}")
        return True, "resolved"
    game.arm_pending_choice(
        "opponent_picks_revealed", opponent_index,
        card_name=context.card.name if context.card is not None else "",
        revealer_index=caster_index,
        cards=[card.name for card in revealed],
        legal_indices=legal,
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


@effect_handler("reveal_library_opponent_chooses")
def reveal_library_opponent_chooses(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Reveal the cards in your library. An opponent chooses from among them a
    creature card, a land card, and a noncreature, nonland card. You put the
    chosen cards into your hand. Then shuffle." (Guided Passage.)

    The pick is asked through the **search prompt**, on the opponent's seat
    over the revealer's library: one seat choosing cards out of another's
    library, one per printed description, is exactly what that prompt carries
    (``zone_seat`` for whose pile, ``one_of_each`` for the descriptions), and
    its resolver already validates the answer whole, shuffles as the picks
    leave (the printed "Then shuffle") and lands each card in the pile's
    owner's hand. A second picker would be a second reading of the same three
    phrases.

    It is not a search, and the two differences are both data. Nothing is
    hidden — CR 701.20a shows every card to every player, recorded here — and
    nothing is optional: no ``up_to`` is armed, so the resolver's floor makes
    the opponent choose a card for every description the library can answer
    (the card's ruling: a description it cannot answer is simply skipped).

    "An opponent" is the seat ``choose_opponent`` wrote one step up (CR 608.2d).
    With none recorded there is nobody to choose and nothing is put anywhere —
    but the library was still revealed, and is still shuffled.
    """
    from ..search_filters import ONE_OF_EACH

    caster = context.caster
    caster_index = game.players.index(caster)
    card_name = context.card.name if context.card is not None else ""
    names = [card.name for card in caster.library]
    if names:
        game.record_reveal(caster_index, names)
    game.log.append(
        f"{caster.name} revealed their library ({len(names)} card(s)) — {card_name}"
    )
    chooser = context.results.get("chosen_player")
    if not isinstance(chooser, int) or not names:
        if names:
            game.log.append(f"{card_name}: no opponent to choose")
        game.shuffle_library_of(caster)
        return True, "resolved"
    slots = [dict(slot) for slot in instruction.payload.get(ONE_OF_EACH) or ()]
    destination = str(instruction.payload.get("destination", "hand"))
    game.arm_pending_choice(
        "search_library", chooser,
        zone_seat=caster_index,
        count=len(slots),
        card_type="any",
        zones=("library",),
        restrictions={ONE_OF_EACH: slots},
        destination=destination,
        destinations=[destination] * len(slots),
        tapped=[False] * len(slots),
        card_name=card_name,
        record=context.results,
        # The whole library was revealed two lines up, so which cards were
        # chosen out of it is something every player watched.
        finds_are_public=True,
    )
    game.log.append(
        f"{game.players[chooser].name} is choosing from {caster.name}'s library"
    )
    return True, "pending_search_library"


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
        lambda card: bool(named) and has_name(card, named),
    )
    return True, "resolved"


def _place_sorted_reveal(game, caster, revealed, payload, matches) -> tuple[list, list]:
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

    "…and the rest **on the bottom of your library in any order**." (Goblin
    Ringleader.) The one rest that is a *position* rather than a zone, and so
    the one move here that is not a zone change: CR 701.20b leaves a revealed
    card in the library it was turned up in, and the bottom of that library is
    still that library. It is therefore laid down directly rather than through
    ``put_card_into_library`` — CR 903.9b offers a commander the command zone
    when it "would be put into its owner's … library **from anywhere**", and a
    card that never left has come from nowhere (the same reading the scry and
    look-and-bottom resolvers take). It is also the one placed as a pile
    instead of card by card: CR 401.4 gives the order of cards put in one
    position at one time to their owner, so they are gathered and the seam
    that asks for it (``offer_library_bottom_order``) is called once every
    find has been taken.

    Returns what each half came to — ``(matched, rest)``, the cards in revealed
    order — for a caller that says where they went; the two older callers read
    neither.
    """
    match_zone = str(payload.get("match_zone", "hand"))
    rest_zone = str(payload.get("rest_zone", "graveyard"))
    matched, rest, bottomed, stayed = [], [], [], []
    # One event (CR 603.6a): the finds enter together.
    with game.entering_together():
        for card in revealed:
            found = bool(matches(card))
            (matched if found else rest).append(card)
            zone = match_zone if found else rest_zone
            if zone == "library_bottom":
                bottomed.append(card)
                continue
            if zone == "battlefield" and stays_out_of_battlefield(
                game, card, caster, "library",
            ):
                # "…put all **Goblin** cards revealed this way onto the
                # battlefield": a Kindred instant of the type is one of them,
                # and not "the rest" — CR 400.4a leaves it in the library it
                # was revealed in (CR 701.20b), on top, where the reveal found
                # it. Laid back for the bottom's reason below: a card that
                # never left has come from nowhere.
                stayed.append(card)
                continue
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
                game.put_card_into_exile(caster, card)
            else:
                game.put_card_into_graveyard(caster, card, from_zone="library")
    if stayed:
        caster.library[0:0] = stayed
    if bottomed:
        caster.library.extend(bottomed)
        game.offer_library_bottom_order(caster, len(bottomed))
    return matched, rest


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

    "Put all **Goblin** cards revealed this way into your hand and the rest
    **on the bottom of your library in any order**." (Goblin Ringleader and
    Apocalypse's six other recruiters.) The same step with a subtype for the
    predicate and a position for the rest. What went where is logged for that
    rest and not for the others, because it is the one that leaves no trace: a
    graveyard and an exile pile are public and can be read afterwards, and the
    bottom of a library cannot (CR 401.2) — so the reveal line alone would
    leave the table to work out which of four cards the player now holds.
    """
    count = resolve_amount(
        instruction.payload.get("amount", 0) or 0, context.x_value
    )
    described = dict(instruction.payload.get("filter") or {})
    # "…all creature cards **of the chosen type**…" (Brass Herald). The word is
    # the CR 614.1c record on the ability's source, turned here into the
    # ordinary ``subtype_filter`` the card matcher reads. The source is read
    # even if it has left the battlefield — the type it chose is its last known
    # information (CR 608.2h). No record leaves the key in place and
    # ``_card_matches_filter`` then refuses every card: nothing is kept, rather
    # than every creature card.
    described = _resolve_chosen_subtype(described, context.source_permanent)
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
    # Every seat's finds in one event (CR 603.6a): "each player … puts all land
    # cards revealed this way onto the battlefield" is one sentence about all of
    # them.
    with game.entering_together():
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
            matched, rest = _place_sorted_reveal(
                game, looked, revealed, instruction.payload,
                lambda card, _owner=looked: _card_matches_filter(
                    card, described, game=game, owner=_owner
                ),
            )
            if instruction.payload.get("rest_zone") == "library_bottom":
                kept = ", ".join(card.name for card in matched) or "no card"
                where = (
                    "onto the battlefield"
                    if instruction.payload.get("match_zone") == "battlefield"
                    else "into their hand"
                )
                game.log.append(
                    f"{looked.name} put {kept} {where} and {len(rest)} card(s) "
                    f"on the bottom of their library"
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
                # "If it's a **Goblin** card, put it onto the battlefield": a
                # Kindred instant of the type passes the test, and CR 400.4a
                # leaves it on top of the library it was revealed in.
                if stays_out_of_battlefield(game, card, player, "library"):
                    return True, "resolved"
                player.library.pop(index)
                arrival = Permanent(card=card)

                def arrived() -> None:
                    # A replacement that took the entry away wrote its own line, and
                    # nothing of this is owed for an entry that never happened
                    # (``entry_awaiting.entry_happened``).
                    if not entry_happened(arrival):
                        return
                    game.log.append(
                        f"{context.card.name}: {card.name} enters the battlefield"
                    )

                game._put_permanent_onto_battlefield(seat, arrival, None, then=arrived)
                return True, "resolved"
    game.log.append(f"{context.card.name}: {card.name} has already moved")
    return True, "resolved"


@effect_handler("put_revealed_card_into_hand")
def put_revealed_card_into_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Reveal the top card of your library. If that card is a creature card
    of the chosen type, **put it into your hand**." (Bloodline Shaman.)

    ``put_revealed_card_onto_battlefield`` above with the third destination,
    located the same way and for the same reason — the revealed card is still
    in its library (CR 701.20 moves nothing), found by identity — and moved
    through the one hand seam (``Game.put_card_into_hand``) into its
    **owner's** hand (CR 400.3), which is the seat whose library it came out
    of. A card that has moved since is left alone.
    """
    card = context.results.get("revealed_card")
    if card is None:
        game.log.append(f"{context.card.name}: no card was turned up")
        return True, "resolved"
    for player in game.players:
        for index, held in enumerate(player.library):
            if held is card:
                player.library.pop(index)
                if game.put_card_into_hand(player, held):
                    game.log.append(
                        f"{context.card.name}: {held.name} goes into "
                        f"{player.name}'s hand"
                    )
                return True, "resolved"
    game.log.append(f"{context.card.name}: {card.name} has already moved")
    return True, "resolved"


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
    elif whose == "target":
        # "**Target opponent** reveals cards …" (Thought Dissector): the seat
        # the activation announced (CR 601.2c), gone if it has left the game.
        chosen = context.target
        seat = (
            game.players.index(chosen)
            if chosen is not None and chosen in game.players and not chosen.lost
            else None
        )
    else:
        seat = context.results.get(whose)
    if seat is None:
        game.log.append(f"{context.card.name}: nobody to reveal from")
        return True, "resolved"
    player = game.players[seat]
    described = dict(payload.get("filter") or {})
    # "Choose a creature type. Reveal cards … until you reveal a creature card
    # **of that type**." (Riptide Shapeshifter.) The word the choosing step in
    # front wrote (CR 608.2d), turned into the ``subtype_filter`` the card
    # matcher reads. **No word means no match** — read as no narrowing, the
    # run would stop on the first creature card of any type — so the run turns
    # over the whole library and finds nothing, which is what a reveal for a
    # type nobody named does.
    chosen_from = described.pop("subtype_filter_from", None)
    chosen_word = None
    if chosen_from is not None:
        chosen_word = context.results.get(str(chosen_from))
        if chosen_word:
            described["subtype_filter"] = str(chosen_word)
        else:
            game.log.append(f"{context.card.name}: no creature type was chosen")

    def matches(card) -> bool:
        if chosen_from is not None and not chosen_word:
            return False
        return _card_matches_filter(card, described, game=game, owner=player)

    if payload.get("destination") == "revealed":
        return _reveal_until_match_in_place(game, seat, matches, context)

    revealed: list = []
    found = None
    # "…until an artifact card **or X cards** are revealed, whichever comes
    # first." (Thought Dissector.) The second stop: a run that has turned over
    # this many cards with no match ends there — the match itself counted
    # among them when it is the last one (it is "revealed" either way).
    limit = payload.get("limit")
    if limit is not None:
        limit = max(0, int(context.x_value or 0) if limit == "x" else int(limit))
    # The run stops on the match **without taking it**: it is still the top
    # card when the sentence moves it (CR 701.20b), so a card the move cannot
    # make is a card that never left.
    while player.library and (limit is None or len(revealed) < limit):
        if matches(player.library[0]):
            found = player.library[0]
            break
        revealed.append(player.library.pop(0))
    if revealed and limit is not None:
        # Thought Dissector's pile is public as it is turned over; recorded
        # for that run alone, so every other run's reveal record is as it was.
        game.record_reveal(seat, [card.name for card in revealed])

    if found is not None:
        game.log.append(f"{player.name} revealed {found.name}")
        game.record_reveal(seat, [found.name])
        if payload.get("destination") == "battlefield":
            # "…until you reveal a **Goblin** card. Put that card onto the
            # battlefield": the run may stop on a Kindred instant of the type,
            # which CR 400.4a leaves on top of the library, above "the rest",
            # which still go where the card sends them (CR 609.3).
            #
            # "…under **your** control" (Thought Dissector): the effect's
            # controller, with the owner recorded (CR 108.3), the arrangement
            # every "under your control" reanimation makes.
            to_seat = (
                game.players.index(context.caster)
                if payload.get("under_your_control") else seat
            )
            if not stays_out_of_battlefield(game, found, player, "library", seat=to_seat):
                player.library.pop(0)
                arriving = Permanent(card=found)
                if to_seat != seat:
                    arriving.metadata["owner_player_index"] = seat
                game._put_permanent_onto_battlefield(
                    to_seat, arriving, None, from_zone="library",
                )
            # "…**and sacrifice this artifact**." Only with a find, and only if
            # the source is still there to sacrifice — the card's ruling
            # (2004-12-01): the artifact card comes in "even if Thought
            # Dissector has already left the battlefield and you can't
            # sacrifice it."
            source = context.source_permanent
            if (
                payload.get("sacrifice_source_on_find")
                and source is not None and game.is_on_battlefield(source)
                and game.controller_index_of(source) == game.players.index(context.caster)
            ):
                game.sacrifice_permanent(source)
                game.log.append(f"{context.card.name} was sacrificed")
        else:
            player.library.pop(0)
            game.put_card_into_hand(player, found)
    elif limit is not None and len(revealed) >= limit:
        game.log.append(
            f"{player.name} revealed {len(revealed)} card(s) and found nothing"
        )
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
        game.shuffle_library_of(player)
    elif rest == "exile":
        # "…and **exile** all other cards revealed this way." (Sacred Guide.)
        # The third printed fate, and the one that costs the revealer the
        # cards for good — a graveyard is a zone half this pool can reach back
        # into, so lowering the word onto the branch below would have made the
        # card strictly better than it reads.
        game.put_cards_into_exile(player, revealed)
        if revealed:
            game.log.append(
                f"{player.name} exiled {len(revealed)} card(s) revealed this way"
            )
    elif rest == "bottom_any_order":
        # "…and the rest on the bottom of their library in any order."
        # (Proteus Staff.) The pile never left the library (CR 701.20b), so it
        # is laid back under it rather than through ``put_card_into_library``,
        # and its owner orders it (CR 401.4) through the seam every "in any
        # order" bottom reaches.
        player.library.extend(revealed)
        if revealed:
            game.log.append(
                f"{player.name} put {len(revealed)} revealed card(s) on the "
                "bottom of their library"
            )
            game.offer_library_bottom_order(player, len(revealed))
    else:
        for card in revealed:
            game.put_card_into_graveyard(player, card, from_zone="library")
    return True, "resolved"


#: The pile a fateless reveal-until left revealed on top of its library, in
#: the order it was turned over — the find last. Spelled once more in
#: ``grammar/lowering/_record_keys.REVEALED_UNTIL_CARDS``, which the record
#: declaration reads.
REVEALED_UNTIL_CARDS = "revealed_until_cards"


def _reveal_until_match_in_place(
    game: Game, seat: int, matches, context: OracleExecutionContext,
) -> tuple[bool, str]:
    """"Reveal cards from the top of your library until you reveal a nonland
    card." with **no fate of its own** (Goblin Machinist, Erratic Explosion).

    CR 701.20b: revealing moves nothing. So nothing is popped — the run reads
    down the library from the top, stops on the first card *matches* accepts,
    and leaves every card it turned over where it lay, revealed (CR 701.20a:
    "for as long as necessary to complete the parts of the effect that card is
    relevant to"). Two records for the sentences behind: the pile itself,
    under :data:`REVEALED_UNTIL_CARDS`, for "put the revealed cards on the
    bottom", and the find's mana value under ``its_mana_value`` for "that
    card's mana value".

    **A library with no match is the whole library, and X is zero** — the
    rulings for both cards (2004-10-04): "If all the cards in your library are
    lands, X is zero" / "no damage is dealt". CR 107.2 gives the number of a
    card that does not exist as 0, and the pile is every card turned over.
    """
    player = game.players[seat]
    pile: list = []
    found = None
    for card in player.library:
        pile.append(card)
        if matches(card):
            found = card
            break
    context.results[REVEALED_UNTIL_CARDS] = pile
    context.results["its_mana_value"] = int(found.cmc or 0) if found is not None else 0
    # "If **the revealed land card** was a Mountain, …" (Goblin Charbelcher.)
    # The find, for the condition behind the run — written only when there is
    # one, so a run that found nothing has no revealed land card to ask about.
    if found is not None:
        context.results["revealed_card"] = found
    if pile:
        game.record_reveal(seat, [card.name for card in pile])
    if found is not None:
        game.log.append(
            f"{player.name} revealed {len(pile)} card(s) and stopped on "
            f"{found.name} (mana value {int(found.cmc or 0)})"
        )
    else:
        game.log.append(
            f"{player.name} revealed their library ({len(pile)} card(s)) and "
            "found nothing"
        )
    return True, "resolved"


@effect_handler("put_revealed_cards_on_bottom")
def put_revealed_cards_on_bottom(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put the revealed cards on the bottom of your library in any order."
    (Goblin Machinist, Erratic Explosion.)

    The pile the run in front of this step left revealed on top of the
    library (:func:`_reveal_until_match_in_place`), moved to the other end of
    the same library. Not a zone change — CR 701.20b left the cards in the
    library, and the bottom of that library is still that library — so it is
    laid down directly, as ``_place_sorted_reveal`` lays Goblin Ringleader's
    rest, rather than through ``put_card_into_library``.

    Each card is taken out **by identity**, top first: two copies of a card in
    a deck are the same ``CardDefinition``, and the pile is the top of the
    library, so the first occurrence from the top is the card the run turned
    over. A card that has left since is left alone (CR 608.2). Then CR 401.4:
    the owner orders cards put in one position at one time, asked once through
    ``offer_library_bottom_order`` — the seam every "in any order" bottom
    reaches.
    """
    pile = list(context.results.get(REVEALED_UNTIL_CARDS) or ())
    player = context.caster
    moved: list = []
    for card in pile:
        for index, held in enumerate(player.library):
            if held is card:
                moved.append(player.library.pop(index))
                break
    if not moved:
        game.log.append(f"{context.card.name}: no revealed card to put back")
        return True, "resolved"
    player.library.extend(moved)
    game.log.append(
        f"{player.name} put {len(moved)} revealed card(s) on the bottom of "
        "their library"
    )
    game.offer_library_bottom_order(player, len(moved))
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
    # In APNAP order (CR 101.4, CR 613.7m): the cards enter together, and the
    # active player's is stamped first. It was seat order, which a Game
    # Preserve on seat 1 — whose upkeep is the only time this triggers — got
    # backwards every time.
    # …and they enter together (CR 603.6a).
    with game.entering_together():
        for seat in game.apnap_seats(by_seat, include_lost=True):
            card = by_seat[seat]
            owner = game.players[seat]
            # CR 400.4a, asked before the card leaves its library
            # (``permanent_cards``); the others still enter.
            if any(held is card for held in owner.library) and (
                stays_out_of_battlefield(game, card, owner, "library")
            ):
                continue
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
            arrival = Permanent(card=card)

            def arrived(arrival=arrival, owner=owner, card=card) -> None:
                # A replacement that took the entry away wrote its own line, and
                # nothing of this is owed for an entry that never happened
                # (``entry_awaiting.entry_happened``).
                if not entry_happened(arrival):
                    return
                game.log.append(
                    f"{owner.name} put {card.name} onto the battlefield ({context.card.name})"
                )

            game._put_permanent_onto_battlefield(seat, arrival, None, then=arrived)
    return True, "resolved"


@effect_handler("reveal_top_to_hand_or_bottom")
def reveal_top_to_hand_or_bottom(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Reveal the top card of your library. If it's a creature card, put it
    into your hand. Otherwise, put it on the bottom of your library." (Garruk,
    Savage Herald's +1.) Revealing is public: the log names the card either
    way, which is what a reveal means to this engine.

    "Otherwise, put it **into your graveyard**" (Neurok Familiar) is the
    ``otherwise_zone`` the parser closed the list on.

    The type is asked with ``card_has_type`` (CR 205.2: a card has every type
    its line names), not ``primary_type``, which picks one by a list order:
    Neurok Familiar's "if it's an **artifact** card" read that way sent every
    artifact creature — "Artifact Creature" answers "creature" — to the
    graveyard."""
    caster = context.caster
    if not caster.library:
        game.log.append(f"{caster.name} has no library to reveal from")
        return True, "resolved"
    card_type = instruction.payload.get("card_type")
    top = caster.library.pop(0)
    game.record_reveal(game.players.index(caster), [top.name])
    if card_type is None or card_has_type(top, card_type):
        game.put_card_into_hand(caster, top)
        game.log.append(f"{caster.name} revealed {top.name} and put it into their hand")
    elif instruction.payload.get("otherwise_zone") == "graveyard":
        game.log.append(
            f"{caster.name} revealed {top.name} and put it into their graveyard"
        )
        game.put_card_into_graveyard(caster, top, from_zone="library")
    else:
        game.put_card_into_library(caster, top)
        game.log.append(
            f"{caster.name} revealed {top.name} and put it on the bottom of their library"
        )
    return True, "resolved"
