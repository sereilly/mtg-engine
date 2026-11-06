"""Handlers that answer the prompts answered with cards.

One handler per kind of prompt, split as the renderers are (its renderer is in
``web/prompt_cards.py``): searching a library or exile, a look at a library's
top and the orders put back on it, cards picked out of a hand, a graveyard,
exile, a pile or from outside the game, separating into piles (CR 700.3),
naming a card and what the name then does, the cards an entering permanent
exiles or reveals, and a revealed hand or face-down look dismissed once seen.

Each one validates the client's answer against the prompt the engine armed
(never against the live board - CR 611.2c/603.12 fixed those sets when the
effect began) and hands it to the engine's confirm entry point.
"""

from __future__ import annotations

from fastapi import HTTPException
from engine.search_filters import SEARCHABLE_ZONES
from .action_registry import action_handler


@action_handler("search_library_confirm")
def _action_search_library_confirm(session, req, seat_type):
    pending = session.game.pending_search_library
    if pending is None:
        raise HTTPException(status_code=400, detail="no library search pending")
    if req.seat != pending["caster_index"]:
        raise HTTPException(status_code=400, detail="not your library search")
    # A counted search ("up to two basic land cards") is answered whole: every
    # find in one pick list. The engine validates the set together — zones,
    # restriction, no card twice — so a bad combination is a refused answer.
    if req.search_picks is not None:
        picks = [
            {"zone": pick.zone, "index": pick.index} for pick in req.search_picks
        ]
        ok = session.game.confirm_search_library_picks(req.seat, picks)
        if not ok:
            raise HTTPException(status_code=400, detail="invalid search picks")
        return
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index (library card index) is required")
    # Which zone the index addresses. The engine checks it against the zones
    # the search was armed with, so naming the graveyard on a library-only
    # search is a rejected answer rather than a widened effect.
    zone = req.search_zone or "library"
    if zone not in SEARCHABLE_ZONES:
        raise HTTPException(status_code=400, detail="unknown search zone")
    ok = session.game.confirm_search_library(req.seat, req.hand_index, zone)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid library card index")

@action_handler("search_library_decline")
def _action_search_library_decline(session, req, seat_type):
    pending = session.game.pending_search_library
    if pending is None:
        raise HTTPException(status_code=400, detail="no library search pending")
    if req.seat != pending["caster_index"]:
        raise HTTPException(status_code=400, detail="not your library search")
    # Failing to find is legal (CR 701.23b) and is the only answer available
    # when nothing in the searched zones matches the restriction — for a
    # search with a stated quality. A search simply for a quantity of cards
    # ("a card", "three cards") must find that many, or as many as the zone
    # holds (CR 701.23d); the engine refuses the decline, and the refusal is
    # said rather than swallowed — this used to return 200 either way, which
    # for a refused decline is a click that does nothing.
    if not session.game.decline_search_library(req.seat):
        raise HTTPException(
            status_code=400,
            detail=(
                "this search must find a card — it names no quality, so it "
                "can't fail to find while the zone has one (CR 701.23d)"
            ),
        )

@action_handler("search_destination_confirm")
def _action_search_destination_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("search_destination")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no destination choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.search_assignments is None:
        raise HTTPException(status_code=400, detail="search_assignments is required")
    # One printed-slot index per found card, distinct — the engine re-checks
    # the mapping, so a stale or doubled slot is a refused answer.
    ok = session.game.confirm_search_destination(req.seat, req.search_assignments)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid destination assignment")

@action_handler("look_top_pick_confirm")
def _action_look_top_pick_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("look_top_pick")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no look choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index (looked-at card index) is required")
    ok = session.game.confirm_look_top_pick(req.seat, req.hand_index)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid card index")

@action_handler("name_and_strip_confirm")
def _action_name_and_strip_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("name_and_strip")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no name choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")
    ok = session.game.confirm_name_and_strip(req.seat, req.card_name)
    if not ok:
        raise HTTPException(
            status_code=400, detail="a basic land's name cannot be chosen"
        )

@action_handler("name_and_random_reveal_confirm")
def _action_name_and_random_reveal_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("name_and_random_reveal")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no name choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")
    session.game.confirm_name_and_random_reveal(req.seat, req.card_name)

@action_handler("choose_card_name_confirm")
def _action_choose_card_name_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("choose_card_name")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no name choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")
    if not session.game.confirm_choose_card_name(req.seat, req.card_name):
        raise HTTPException(status_code=400, detail="the name could not be applied")

@action_handler("name_then_reveal_top_confirm")
def _action_name_then_reveal_top_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("name_then_reveal_top")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no name choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")
    if not session.game.confirm_name_then_reveal_top(req.seat, req.card_name):
        raise HTTPException(status_code=400, detail="the name could not be applied")

@action_handler("exiled_pile_claim_confirm")
def _action_exiled_pile_claim_confirm(session, req, seat_type):
    # Thieves' Auction: the seat whose turn it is in the round-robin names one
    # of the cards still on the pile. The index is into the offered list, which
    # is what the prompt rendered and what the resolver re-checks — every seat
    # ahead of this one has already shortened it.
    pending = next(
        (c for c in session.game.pending_choices_of("exiled_pile_claim")), None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no exiled-card pick pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.pile_index is None:
        raise HTTPException(status_code=400, detail="pile_index is required")
    if not session.game.confirm_exiled_pile_claim(req.seat, req.pile_index):
        raise HTTPException(status_code=400, detail="that card cannot be chosen")

@action_handler("graveyard_pick_for_price_confirm")
def _action_graveyard_pick_for_price_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("graveyard_pick_for_price")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no graveyard pick pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.graveyard_index is None:
        raise HTTPException(status_code=400, detail="graveyard_index is required")
    if not session.game.confirm_graveyard_pick_for_price(
        req.seat, req.graveyard_index
    ):
        raise HTTPException(status_code=400, detail="that card cannot be chosen")


@action_handler("name_then_consult_confirm")
def _action_name_then_consult_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("name_then_consult")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no name choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")
    if not session.game.confirm_name_then_consult(req.seat, req.card_name):
        raise HTTPException(status_code=400, detail="the name could not be applied")


@action_handler("search_exile_confirm")
def _action_search_exile_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("search_exile_cards")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no exile search pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your search")
    picks = [
        {"zone": pick.zone, "index": pick.index}
        for pick in (req.search_picks or [])
    ]
    # An empty list is the fail-to-find (CR 701.23b): "any number" includes
    # zero, so no separate decline action exists.
    ok = session.game.confirm_search_exile(req.seat, picks)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid search picks")

@action_handler("reorder_library_confirm")
def _action_reorder_library_confirm(session, req, seat_type):
    pending = session.game.pending_reorder_library
    if pending is None:
        raise HTTPException(status_code=400, detail="no library reorder pending")
    if req.seat != pending["caster_index"]:
        raise HTTPException(status_code=400, detail="not your library reorder")
    if req.card_order is None:
        raise HTTPException(status_code=400, detail="card_order is required")
    ok = session.game.confirm_reorder_library(req.seat, req.card_order, shuffle=bool(req.shuffle))
    if not ok:
        raise HTTPException(status_code=400, detail="invalid card order")

@action_handler("scry_confirm")
def _action_scry_confirm(session, req, seat_type):
    pending = session.game.pending_scry
    if pending is None:
        raise HTTPException(status_code=400, detail="no scry pending")
    if req.seat != pending["caster_index"]:
        raise HTTPException(status_code=400, detail="not your scry")
    if req.card_order is None or req.bottom_count is None:
        raise HTTPException(status_code=400, detail="card_order and bottom_count are required")
    ok = session.game.confirm_scry(req.seat, req.card_order, req.bottom_count)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid scry arrangement")

@action_handler("revealed_hand_pick_confirm")
def _action_revealed_hand_pick_confirm(session, req, seat_type):
    pending = next(iter(session.game.pending_choices_of("revealed_hand_pick")), None)
    if pending is None:
        raise HTTPException(status_code=400, detail="no revealed-hand choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    # A missing index is the chooser **declining**, which only "choose up to X
    # cards from it" (Discordant Dirge) permits — so it is passed through rather
    # than rejected here, and the resolver is what reads the printed permission.
    # Rejected at this layer instead, the client would have to know which cards
    # print the words, which is the split every other prompt here avoids.
    ok = session.game.confirm_revealed_hand_pick(req.seat, req.hand_index)
    if not ok:
        raise HTTPException(status_code=400, detail="that card cannot be chosen")

@action_handler("discard_confirm")
def _action_discard_confirm(session, req, seat_type):
    pending = session.game.pending_discard
    if pending is None:
        raise HTTPException(status_code=400, detail="no discard pending")
    if req.seat != pending["player_index"]:
        raise HTTPException(status_code=400, detail="not your discard")
    # "Discard **up to** two cards" / "discard **any number of** cards": none
    # is a legal answer, and the engine has always taken it. This refused an
    # empty list before the engine was asked, so over the wire a ceiling was a
    # floor of one. Only a ceiling may be answered with nothing — an exact
    # discard with no cards named is still a malformed request.
    if not req.discard_indices and not pending.get("up_to"):
        raise HTTPException(status_code=400, detail="discard_indices is required")
    ok = session.game.confirm_discard(
        req.seat, list(req.discard_indices or []), to_library=bool(req.to_library)
    )
    if not ok:
        raise HTTPException(status_code=400, detail="invalid discard selection")

@action_handler("hand_to_library_confirm")
def _action_hand_to_library_confirm(session, req, seat_type):
    # Brainstorm, Stunted Growth: which cards go back and in what order. The
    # order of `hand_indices` is the order the card gives ("in any order"), so
    # it is passed through rather than sorted — sorting it would silently take
    # the choice the card offers away.
    if req.hand_indices is None:
        raise HTTPException(status_code=400, detail="hand_indices is required")
    ok = session.game.confirm_hand_to_library(
        req.seat, list(req.hand_indices), bool(req.to_bottom)
    )
    if not ok:
        raise HTTPException(status_code=400, detail="invalid card selection")

@action_handler("discard_unless_pay_life_confirm")
def _action_discard_unless_pay_life_confirm(session, req, seat_type):
    # Breathstealer's Crypt: "that player discards it unless they pay 3 life."
    # One offer about one card, so the answer is just accept/decline.
    if req.accept is None:
        raise HTTPException(status_code=400, detail="accept (true/false) is required")
    ok = session.game.confirm_discard_unless_pay_life(req.seat, bool(req.accept))
    if not ok:
        raise HTTPException(
            status_code=400, detail="no pay-or-discard offer pending for you"
        )


@action_handler("revealed_draw_buyout_confirm")
def _action_revealed_draw_buyout_confirm(session, req, seat_type):
    # Zur's Weirding: "Then any other player may pay 2 life." One offer at a
    # time, so the answer is just accept/decline.
    if req.accept is None:
        raise HTTPException(status_code=400, detail="accept (true/false) is required")
    ok = session.game.confirm_revealed_draw_buyout(req.seat, bool(req.accept))
    if not ok:
        raise HTTPException(
            status_code=400, detail="no revealed-card offer pending for you"
        )

@action_handler("exile_from_hand_confirm")
def _action_exile_from_hand_confirm(session, req, seat_type):
    # Ice Cauldron: the seat picks a card in its hand to exile under the
    # artifact, or declines (accept=False / no hand_index). Declining is always
    # an answer here — the sentence says "you may" — and the engine re-checks
    # the pick against the same candidate rule the prompt was drawn from, so a
    # client offering a whole hand cannot widen the choice.
    pending = next(
        (c for c in session.game.pending_choices_of("exile_from_hand_choice")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no card exile pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    hand_index = None if req.accept is False else req.hand_index
    if not session.game.confirm_exile_from_hand_choice(req.seat, hand_index):
        raise HTTPException(status_code=400, detail="invalid card choice")

@action_handler("exile_hand_pile_confirm")
def _action_exile_hand_pile_confirm(session, req, seat_type):
    # Scroll Rack: the seat names any number of cards in its hand to exile face
    # down under the artifact. Zero is an answer rather than a decline — the
    # sentence behind it draws *that many* — so there is no `accept` here, and
    # the engine re-checks every slot against the same candidate rule the
    # prompt was drawn from, so a client offering more cannot widen the choice.
    pending = next(
        (c for c in session.game.pending_choices_of("exile_hand_pile_choice")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no hand exile pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not session.game.confirm_exile_hand_pile(req.seat, req.hand_indices or []):
        raise HTTPException(status_code=400, detail="invalid card choice")


@action_handler("put_from_hand_confirm")
def _action_put_from_hand_confirm(session, req, seat_type):
    # Eureka: the offered seat picks a card in its hand to put onto the
    # battlefield, or declines (accept=False / no hand_index). The engine
    # re-checks the pick against the same candidate rule the prompt was drawn
    # from, so a client offering a whole hand cannot widen the choice — and it
    # refuses a decline the sentence never offered.
    pending = next(
        (c for c in session.game.pending_choices_of("put_from_hand_choice")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no card choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    hand_index = None if req.accept is False else req.hand_index
    if hand_index is None and req.accept is not False:
        raise HTTPException(status_code=400, detail="hand_index is required")
    if not session.game.confirm_put_from_hand_choice(req.seat, hand_index):
        raise HTTPException(status_code=400, detail="invalid card choice")

@action_handler("outside_game_pick_confirm")
def _action_outside_game_pick_confirm(session, req, seat_type):
    # The Wishes: the seat picks a card of its sideboard to bring in from
    # outside the game (sideboard_index), or declines (accept=False). The
    # engine re-checks the pick against the candidate rule the prompt was
    # drawn from, so a client offering the whole sideboard cannot turn Burning
    # Wish into a fetch of any card — and it refuses a decline of a pick the
    # sentence made mandatory.
    pending = next(
        (c for c in session.game.pending_choices_of("outside_game_pick")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no outside-the-game pick pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    sideboard_index = None if req.accept is False else req.sideboard_index
    if sideboard_index is None and req.accept is not False:
        raise HTTPException(status_code=400, detail="sideboard_index is required")
    if not session.game.confirm_outside_game_pick(req.seat, sideboard_index):
        raise HTTPException(status_code=400, detail="invalid card choice")

@action_handler("choose_cards_in_hand_confirm")
def _action_choose_cards_in_hand_confirm(session, req, seat_type):
    # Sylvan Library: the seat picks which of its eligible cards the next step
    # acts on. The engine re-checks the picks against the same candidate rule
    # the prompt was drawn from, so a client sending a whole hand cannot widen
    # the choice — and it refuses a short answer, because the sentence names a
    # number and a partial pick is not one of its outcomes.
    pending = next(
        (c for c in session.game.pending_choices_of("choose_cards_in_hand")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no hand choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.hand_indices is None:
        raise HTTPException(status_code=400, detail="hand_indices is required")
    if not session.game.confirm_choose_cards_in_hand(req.seat, req.hand_indices):
        raise HTTPException(status_code=400, detail="invalid card choice")


@action_handler("library_pile_split_confirm")
def _action_library_pile_split_confirm(session, req, seat_type):
    # Phyrexian Portal: the opponent sends the positions that go into the first
    # pile. An empty list is a legal division - one pile of ten and one of none
    # is a real, and often good, way to divide.
    pending = next(
        (c for c in session.game.pending_choices_of("library_pile_split")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no pile split pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.first_pile is None:
        raise HTTPException(status_code=400, detail="first_pile is required")
    if not session.game.confirm_library_pile_split(req.seat, req.first_pile):
        raise HTTPException(status_code=400, detail="invalid division")


@action_handler("pile_exile_confirm")
def _action_pile_exile_confirm(session, req, seat_type):
    # Phyrexian Portal: which face-down pile goes to exile.
    pending = next(
        (c for c in session.game.pending_choices_of("pile_exile_choice")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no pile choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.pile_index is None:
        raise HTTPException(status_code=400, detail="pile_index is required")
    if not session.game.confirm_pile_exile_choice(req.seat, req.pile_index):
        raise HTTPException(status_code=400, detail="invalid pile")


@action_handler("pile_split_confirm")
def _action_pile_split_confirm(session, req, seat_type):
    # CR 700.3 (Fact or Fiction and its siblings): the separator sends the
    # positions that go into the first pile. An empty list is a legal
    # separation - a pile may be empty.
    pending = next((c for c in session.game.pending_choices_of("pile_split")), None)
    if pending is None:
        raise HTTPException(status_code=400, detail="no pile separation pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.first_pile is None:
        raise HTTPException(status_code=400, detail="first_pile is required")
    if not session.game.confirm_pile_split(req.seat, req.first_pile):
        raise HTTPException(status_code=400, detail="invalid separation")


@action_handler("pile_choice_confirm")
def _action_pile_choice_confirm(session, req, seat_type):
    # CR 700.3: which of the two face-up piles this seat chooses.
    pending = next((c for c in session.game.pending_choices_of("pile_choice")), None)
    if pending is None:
        raise HTTPException(status_code=400, detail="no pile to choose pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.pile_index is None:
        raise HTTPException(status_code=400, detail="pile_index is required")
    if not session.game.confirm_pile_choice(req.seat, req.pile_index):
        raise HTTPException(status_code=400, detail="invalid pile")


@action_handler("opponent_picks_revealed_confirm")
def _action_opponent_picks_revealed_confirm(session, req, seat_type):
    # Thran Tome: which of the revealed cards the *opponent* sends to the
    # revealer's graveyard. ``pile_index`` addresses the revealed list the
    # prompt showed, not the library \u2014 CR 701.20 moved nothing, and the engine
    # locates the card by identity from there.
    pending = next(
        (c for c in session.game.pending_choices_of("opponent_picks_revealed")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no revealed-card choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.pile_index is None:
        raise HTTPException(status_code=400, detail="pile_index is required")
    if not session.game.confirm_opponent_picks_revealed(req.seat, req.pile_index):
        raise HTTPException(status_code=400, detail="invalid revealed card")


@action_handler("pile_search_confirm")
def _action_pile_search_confirm(session, req, seat_type):
    # Phyrexian Portal: which card the search takes, or none at all
    # (CR 701.23b's fail-to-find, sent as accept=False).
    pending = next(
        (c for c in session.game.pending_choices_of("pile_search")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no pile search pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    index = None if req.accept is False else req.pile_index
    if index is None and req.accept is not False:
        raise HTTPException(status_code=400, detail="pile_index is required")
    if not session.game.confirm_pile_search(req.seat, index):
        raise HTTPException(status_code=400, detail="invalid card choice")


@action_handler("library_cycle_confirm")
def _action_library_cycle_confirm(session, req, seat_type):
    # Lim-Dul's Vault: another round of "pay 1 life and look again", or stop.
    # Both answers are legal every time - declining is what ends the loop and
    # runs the shuffle, so there is no "invalid" case beyond an absent prompt.
    pending = next(
        (c for c in session.game.pending_choices_of("library_cycle_offer")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no library cycle pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.accept is None:
        raise HTTPException(status_code=400, detail="accept is required")
    if not session.game.confirm_library_cycle_offer(req.seat, req.accept):
        raise HTTPException(status_code=400, detail="invalid answer")


@action_handler("linked_exile_return_confirm")
def _action_linked_exile_return_confirm(session, req, seat_type):
    # Gustha's Scepter: the seat picks which of the cards it owns under the
    # artifact comes back to its hand. The engine re-checks the pick against
    # the same candidate rule the prompt was drawn from, and there is no
    # decline — the sentence is mandatory.
    pending = next(
        (c for c in session.game.pending_choices_of("linked_exile_return")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no exile return pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.exile_entry_index is None:
        raise HTTPException(status_code=400, detail="exile_entry_index is required")
    if not session.game.confirm_linked_exile_return(req.seat, req.exile_entry_index):
        raise HTTPException(status_code=400, detail="invalid card choice")


@action_handler("exiled_card_return_confirm")
def _action_exiled_card_return_confirm(session, req, seat_type):
    # Dimensional Breach: the upkeep's player picks which of their own exiled
    # cards returns to the battlefield. ``exile_entry_index`` is a position in
    # the prompt's exile-record list; the engine re-checks it against the same
    # rule the prompt was drawn from, and there is no decline.
    pending = next(
        (c for c in session.game.pending_choices_of("exiled_card_return")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no exiled card return pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.exile_entry_index is None:
        raise HTTPException(status_code=400, detail="exile_entry_index is required")
    if not session.game.confirm_exiled_card_return(req.seat, req.exile_entry_index):
        raise HTTPException(status_code=400, detail="invalid card choice")


@action_handler("library_end_confirm")
def _action_library_end_confirm(session, req, seat_type):
    # Ether Well: top or bottom. `to_bottom` is the field Dream Cache's answer
    # already carries for the same question one zone over -- a second field
    # meaning "which end of a library" would be a second answer to it.
    pending = next(
        (c for c in session.game.pending_choices_of("library_end_choice")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no library end choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not session.game.confirm_library_end_choice(
        req.seat, bool(req.to_bottom)
    ):
        raise HTTPException(status_code=400, detail="invalid library end choice")


@action_handler("graveyard_pile_confirm")
def _action_graveyard_pile_confirm(session, req, seat_type):
    # Ebony Charm: which graveyard "a single graveyard" means. The seat is sent
    # on `chosen_seat` rather than `target_seat` for `player_choice_confirm`'s
    # reason -- a chosen player is not a target (CR 601.2c declares none) -- and
    # the engine re-checks it against the piles that still hold a legal card, so
    # a stale answer is refused rather than applied to an emptied graveyard.
    pending = next(
        (c for c in session.game.pending_choices_of("graveyard_pile_choice")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no graveyard pile choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.chosen_seat is None:
        raise HTTPException(status_code=400, detail="chosen_seat is required")
    if not session.game.confirm_graveyard_pile_choice(req.seat, req.chosen_seat):
        raise HTTPException(status_code=400, detail="invalid graveyard choice")


@action_handler("graveyard_exile_confirm")
def _action_graveyard_exile_confirm(session, req, seat_type):
    # Rysorian Badger: the seat picks which cards in the defending player's
    # graveyard to exile. The engine re-checks the picks against the same
    # candidate rule the prompt was drawn from, so a client sending the whole
    # pile cannot widen the choice — and the empty answer is legal here,
    # because the sentence says "up to".
    pending = next(
        (c for c in session.game.pending_choices_of("graveyard_exile_pick")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no graveyard choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.graveyard_indices is None:
        raise HTTPException(status_code=400, detail="graveyard_indices is required")
    if not session.game.confirm_graveyard_exile_pick(
        req.seat, req.graveyard_indices
    ):
        raise HTTPException(status_code=400, detail="invalid card choice")


@action_handler("entry_exile_confirm")
def _action_entry_exile_confirm(session, req, seat_type):
    # Frankenstein's Monster: the entry cost ("exile X creature cards from your
    # graveyard") and the counter each exiled card buys, in one answer - they
    # are one decision made as the permanent enters (CR 614.1c), and sending
    # them apart would leave the creature on the battlefield at a size nobody
    # chose. The engine re-checks every index against the graveyard positions
    # the printed noun phrase admits, so the prompt's list is a hint.
    if req.entry_exile_picks is None:
        raise HTTPException(status_code=400, detail="entry_exile_picks is required")
    picks = [
        {"index": pick.index, "counter": pick.counter}
        for pick in req.entry_exile_picks
    ]
    if not session.game.resolve_pending_choice("entry_exile", req.seat, picks=picks):
        raise HTTPException(
            status_code=400,
            detail=(
                "no entry exile is pending for you, or those cards and counters "
                "are not the ones offered"
            ),
        )

@action_handler("entry_reveal_confirm")
def _action_entry_reveal_confirm(session, req, seat_type):
    # Amplify (CR 702.38a): the hand slots revealed as the creature enters,
    # none included. The engine re-checks each against the cards that share a
    # creature type with it, so the prompt's list is a hint.
    if req.hand_indices is None:
        raise HTTPException(status_code=400, detail="hand_indices is required")
    if not session.game.resolve_pending_choice(
        "entry_reveal", req.seat, hand_indices=list(req.hand_indices)
    ):
        raise HTTPException(status_code=400, detail=(
            "no amplify reveal is pending for you, or those cards are not "
            "the ones offered"
        ))

@action_handler("dismiss_hand_reveal")
def _action_dismiss_hand_reveal(session, req, seat_type):
    session.game.dismiss_hand_reveal(req.seat)


@action_handler("dismiss_face_down_look")
def _action_dismiss_face_down_look(session, req, seat_type):
    session.game.dismiss_face_down_look(req.seat)
