"""What a card **reveals** (CR 701.20a): a card shown to every player.

The handler twin of ``engine/grammar/lowering/reveal.py``, with the same two
halves. The reveals of a library's top: sorted by a chosen name or a printed
phrase (Wood Sage, Mulch), chosen from by an opponent (Thran Tome, Guided
Passage), revealed until a match (Transmogrify), put onto the battlefield (Call
of the Wild, Game Preserve). And the reveals of a hand: the bare reveal,
Duress's reveal-and-choose, Stromgald Spy's standing reveal, and the card
revealed at random together with what the sentences behind it do with that card
— exile it, or have it discarded unless its owner pays life. Those read what the
reveal recorded — :data:`REVEALED_HAND_INDEX` among it, a slot, because two
copies of a card in a hand are one object — and stay beside the reveal that
writes it.

Split out of ``zones.py`` at the 2,000-line cap's split round. A **look** (the
private half, which shows a card to one player) is ``library.py``'s.
"""

from __future__ import annotations

import dataclasses
import random
from typing import TYPE_CHECKING

from ..faces import has_name
from ..linked_exile import until_leaves_has_ended
from ..models import Permanent
from ..oracle_types import REVEALED_HAND_CARDS, REVEALED_TOP_CARDS_BY_SEAT
# The runtime class. The bare name is a TYPE_CHECKING-only import below, and
# the handlers here *build* instructions for an optional payment's branches.
from ..oracle_types import OracleInstruction as _OracleInstruction
from ..revealed_hands import reveal_hand_while_present
from ..search_filters import search_matches
from ._amounts import resolve_amount
from ._chosen import _resolve_chosen_subtype
from ._filters import _card_matches_filter
from ._targets import frozen_that_player_seat
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
        random.shuffle(caster.library)
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
    matched, rest, bottomed = [], [], []
    for card in revealed:
        found = bool(matches(card))
        (matched if found else rest).append(card)
        zone = match_zone if found else rest_zone
        if zone == "library_bottom":
            bottomed.append(card)
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
            caster.exile.append(card)
        else:
            game.put_card_into_graveyard(caster, card, from_zone="library")
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
                player.library.pop(index)
                game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
                game.log.append(
                    f"{context.card.name}: {card.name} enters the battlefield"
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
    if instruction.payload.get("who") == "each_player":
        # "**Each player** reveals their hand, …" (Noxious Vapors.) Every
        # living seat's, in APNAP order (CR 101.4) — one reveal apiece through
        # the same feed, and one record of everything shown: "revealed this
        # way" behind this step is all of it.
        from .control_flow import _offered_seats

        shown: list = []
        for seat in _offered_seats(game, "each_player", context):
            revealer = game.players[seat]
            shown.extend(revealer.hand)
            names = [held.name for held in revealer.hand]
            game.record_reveal(seat, names)
            game.log.append(
                f"{revealer.name} reveals their hand: "
                + (", ".join(names) or "(empty)")
            )
        context.results[REVEALED_HAND_CARDS] = shown
        return True, "resolved"
    if instruction.payload.get("who") == "you":
        victim = context.caster
    elif instruction.payload.get("who") == "damaged_player":
        # "…**that player** reveals their hand…" (Crosis, the Purger.) The seat
        # the damage froze (CR 603.10). No record means the words named nobody
        # and no hand is shown — never a fall back to the ability's controller,
        # whose hand is the one this must not open. An empty record is written
        # all the same, so the sentence behind this one counts nothing rather
        # than reading a back-reference with no producer.
        frozen = frozen_that_player_seat(game, context)
        if frozen is None:
            context.results[REVEALED_HAND_CARDS] = []
            game.log.append(f"{context.card.name}: no recorded player, no reveal")
            return True, "resolved"
        victim = game.players[frozen]
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
    elif instruction.payload.get("victim") == "damaged_player":
        # "Whenever this creature deals combat damage to a player, look at
        # **that player's** hand …" (Doomsday Specter.) The seat the damage
        # went to, on the key every damage fire site stamps — read narrowly,
        # for the branch above's reason: with none recorded the words named
        # nobody, and the fallback below is the ability's own controller,
        # whose hand is the one this must not open.
        seat = (context.trigger_context or {}).get("defending_player_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return False, "no damaged player was frozen for 'that player'"
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
    # "Choose a color. … you choose a card **of that color** from it." (Addle.)
    # CR 608.2d's colour, read out of the scratchpad the choosing step wrote and
    # carried on the prompt beside the three narrowings above, for their reason.
    # **No colour means no card**: read as "no narrowing" the caster would be
    # choosing from the whole hand.
    any_colors: list[str] = []
    color_key = instruction.payload.get("color_filter_from")
    if color_key is not None:
        chosen_color = context.results.get(str(color_key))
        if not chosen_color:
            game.log.append(f"{card.name}: no colour was chosen, so no card is")
            return True, "resolved"
        any_colors = [str(chosen_color)]
        narrowing["restrictions"] = {"any_colors": any_colors}
    legal = [
        index
        for index, held in enumerate(victim.hand)
        # The seat is handed over for CR 202.2 alone — a card's colour in a
        # hand is its printed one unless something on a board says otherwise.
        if search_matches(held, narrowing, game=game, owner=victim)
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
    if (
        str(instruction.payload.get("fate", "discard")) == "exile_until_source_leaves"
        and until_leaves_has_ended(game, context.source_permanent)
    ):
        # Kitesail Freebooter's ruling (2020-06-23), which is CR 610.3b: "If
        # Kitesail Freebooter leaves the battlefield before its
        # enters-the-battlefield ability resolves, the opponent will reveal
        # their hand, but no card will be exiled." So the hand is shown, above,
        # and no pick is armed - an armed one could never be answered, since
        # the answer needs the permanent that would hold the card.
        game.log.append(
            f"{card.name} left the battlefield before its ability resolved, "
            "so no card is exiled"
        )
        return True, "resolved"
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
        any_colors=any_colors,
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
    for seat in game.apnap_seats(by_seat, include_lost=True):
        card = by_seat[seat]
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

#: Whose ability is making the offered seat discard (CR 109.5), for the two
#: "…discards it unless they pay N life" branches below. They run under a
#: context whose ``caster`` has been swapped for the **paying** seat — which is
#: what lets one ``pay_life`` instruction charge whoever was offered it — so by
#: the time the declined branch discards, ``Game.resolving_seats`` names the
#: victim and "a spell or ability an opponent controls causes you to discard"
#: (Psychic Purge, Dodecapod) would read as the victim's own doing. Written
#: into the scratchpad the two contexts share, by the step that still knows.
_DISCARD_CAUSE_SEAT = "discard_cause_seat"


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
        # "…equal to **that card's mana value**" (Planeswalker's Mirth) about a
        # card nobody revealed: CR 107.2, "if anything needs to use a number
        # that can't be determined … it uses 0 instead". Written rather than
        # left absent because ``lowering/_records`` declares the record for the
        # kind, and so a stale number from an earlier step cannot answer.
        context.results["its_mana_value"] = 0
        return True, "resolved"
    index = random.randrange(len(victim.hand))
    card = victim.hand[index]
    context.results["revealed_card"] = card
    context.results[REVEALED_HAND_INDEX] = index
    # The printed mana value (CR 202.3): a card in a hand has no computed
    # characteristics (CR 613.1), and the number is frozen here because the
    # sentence behind this one cannot go and look — the hand is hidden and the
    # slot was nobody's choice (CR 608.2h).
    context.results["its_mana_value"] = int(card.cmc or 0)
    seat = next((i for i, seated in enumerate(game.players) if seated is victim), None)
    if seat is not None:
        game.record_reveal(seat, [card.name])
    game.log.append(f"{victim.name} reveals {card.name} at random from their hand")
    return True, "resolved"


@effect_handler("exile_revealed_card")
def exile_revealed_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…If it's an instant or sorcery card, **exile it**." (Planeswalker's
    Mischief.)

    "It" is the card the reveal in front of this step recorded, taken out of
    the hand it was shown from **by slot** — ``discard_revealed_card``'s rule
    and for its reason: a hand is the one zone where two copies of a card are
    one object, so the index resolved at reveal time is the only thing that
    names which of them was shown. A hand that has changed underneath exiles
    nothing rather than guessing.

    Into its **owner's** exile (CR 400.3), which is the revealing player's and
    not the ability's controller's, and recorded under the one ``exiled_cards``
    key every other exile writes — so "you may cast it … for as long as it
    remains exiled" and "if you haven't cast it, return it" read the referent
    this engine already has. The record is written even when nothing moves:
    ``lowering/_records`` declares it for the kind, and an absent key is a
    back-reference with no producer rather than an exile of nothing.

    Whose hand is ``reveal_random_card_from_hand``'s own answer, read the same
    way, so the two steps cannot name different players.

    **A card turned up from a library is the same pronoun**, and the record is
    the same key (``reveal_top_of_library`` writes ``revealed_card`` too), so
    this kind answers for both zones rather than exiling nothing behind one of
    them: with no hand slot recorded the card is where ``bin_revealed_card``
    looks for it, still on its owner's library.
    """
    context.results["exiled_cards"] = []
    card = context.results.get("revealed_card")
    if card is None:
        return True, "resolved"
    index = context.results.get(REVEALED_HAND_INDEX)
    if not isinstance(index, int):
        for owner in game.players:
            for slot, held in enumerate(owner.library):
                if held is card:
                    owner.library.pop(slot)
                    owner.exile.append(card)
                    context.results["exiled_cards"] = [card]
                    game.log.append(
                        f"{owner.name} exiles {card.name} from their library"
                    )
                    return True, "resolved"
        game.log.append(f"{context.card.name}: {card.name} has already moved")
        return True, "resolved"
    victim = context.target if context.target is not None else context.caster
    if not (0 <= index < len(victim.hand)) or victim.hand[index] is not card:
        game.log.append(f"{context.card.name}: {card.name} is no longer in hand")
        return True, "resolved"
    victim.hand.pop(index)
    victim.exile.append(card)
    context.results["exiled_cards"] = [card]
    game.log.append(f"{victim.name} exiles {card.name} from their hand")
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
    # Through the discard seam, never straight to the graveyard: a discard is
    # CR 701.9a's event whoever chose the card, so a replacement over it
    # (Library of Leng, Dodecapod) and every watcher of one (Megrim, Psychic
    # Purge) has to see this one too. It went by the graveyard seam alone until
    # Dodecapod was driven against it, and nothing watching a discard fired.
    game._discard_card(
        victim, card, cause_seat=context.results.get(_DISCARD_CAUSE_SEAT)
    )
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
    # Before the caster is swapped, while the resolving seat is still the
    # ability's own controller — see ``_DISCARD_CAUSE_SEAT``. The scratchpad is
    # shared with the paying context, so the declined branch reads it there.
    context.results[_DISCARD_CAUSE_SEAT] = game.discard_cause_seat()
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
    # Read once, before any offer swaps the caster — see ``_DISCARD_CAUSE_SEAT``.
    cause_seat = game.discard_cause_seat()
    for card in matching:
        paying = dataclasses.replace(
            context, caster=victim,
            results={
                **context.results, _DISCARDED_REVEALED_CARD: card,
                _DISCARD_CAUSE_SEAT: cause_seat,
            },
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
    # Through the discard seam, for ``discard_revealed_card``'s reason.
    game._discard_card(
        victim, card, cause_seat=context.results.get(_DISCARD_CAUSE_SEAT)
    )
    game.log.append(f"{victim.name} discards {card.name}")
    return True, "resolved"
