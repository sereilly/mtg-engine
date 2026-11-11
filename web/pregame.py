"""Everything before turn one: the coin flip and the mulligan rounds
(CR 103.5, London mulligan).

One function per transition, so the state machine reads as its own sequence
rather than as branches buried in the action dispatch: offer, declare keep or
mulligan, take the round's mulligans, bottom the extras, start the game.
:func:`_pregame_auto_advance` is what a table with no interactive seat owed a
decision runs, so nothing waits on a prompt nobody owns.

**The mulligans go by CR 103.5's rounds.** "First, the starting player
declares whether they will take a mulligan. Then each other player in turn
order does the same. Once each player has made a declaration, all players who
decided to take mulligans do so at the same time … This process is then
repeated until no player takes a mulligan." A round is the seats still
deciding (``Session.mulligan_round_seats``, in turn order from the starting
player). A seat declares keep (:func:`_pregame_keep_player`, which bottoms what
it owes) or mulligan (:func:`_pregame_declare_mulligan`, recorded in
``Session.mulligan_declared``); once the round's last seat has declared, every
mulligan declared in it is taken together (:func:`_pregame_finish_round`) and
the seats that took one make the next round. The sequential table offers the
round's seats one at a time (``mulligan_offer_seat``); the simultaneous host
setting asks every one of them at once. Either way no mulligan is taken before
the whole round has declared, so no seat declares having seen another's next
hand — or how many mulligans that seat went on to take. Until the kg3 round the
sequential table let each seat mulligan until it kept before the next seat
declared, and the simultaneous one let a seat run through its rounds while
another was still making its first declaration; the simulator's
``ai_mulligan.take_opening_mulligans`` already took them by rounds.

An AI seat decides with ``engine/ai_mulligan.py`` — keep or mulligan, and
which cards go to the bottom — the decision the simulator asks too. How many
cards a seat owes the bottom is ``Game.mulligan_effective_count``, which counts
CR 103.5c's free first mulligan in a multiplayer or Brawl game.
"""

from __future__ import annotations

from engine.ai_mulligan import (keeps_opening_hand, opening_hand_bottom,
                                take_hand_exchanges)
from engine.mulligan_exchanges import exchange_sources

from .session_store import Session

from .seats import _seat_type


def _build_pregame_info(session: Session, viewer_seat: int | None) -> dict | None:
    phase = session.pregame_phase
    if phase is None:
        return None

    info: dict = {"phase": phase}

    if phase == "coin_flip":
        winner = session.coin_flip_winner
        winner_name = session.game.players[winner].name if winner is not None else None
        info["winner_seat"] = winner
        info["winner_name"] = winner_name
        info["is_my_turn"] = viewer_seat is not None and viewer_seat == winner
        info["is_loser_choice"] = session.coin_flip_is_loser_choice
        # "coin_flip", "loser", or "draw" (CR 103.1: after a draw the seat that
        # chose last time chooses again) — what the prompt says to each seat.
        info["choice_reason"] = session.coin_flip_choice_reason
        if not info["is_my_turn"]:
            info["waiting_for"] = winner_name

    elif phase == "mulligan" and session.simultaneous_mulligan:
        # The round's seats declare at once, so the phase is per-viewer: a seat
        # still to declare this round sees the keep/mulligan prompt, a seat
        # that kept after a mulligan sees its own bottom_select, and a seat
        # that has declared — a mulligan waiting on the round, or a keep —
        # sees who is still owed.
        info["simultaneous"] = True
        players = session.game.players
        deciding = _round_undecided(session)
        if viewer_seat is not None and viewer_seat in session.mulligan_bottom_required_by_seat:
            selected = session.mulligan_bottom_selected_by_seat.get(viewer_seat, [])
            info["phase"] = "bottom_select"
            info["bottom_seat"] = viewer_seat
            info["bottom_name"] = players[viewer_seat].name
            info["is_my_turn"] = True
            info["required_count"] = session.mulligan_bottom_required_by_seat[viewer_seat]
            info["mulligans_taken"] = players[viewer_seat].mulligans_taken
            info["selected_indices"] = list(selected)
            info["selected_count"] = len(selected)
        elif viewer_seat is not None and viewer_seat in deciding:
            info["offer_seat"] = viewer_seat
            info["offer_name"] = players[viewer_seat].name
            info["is_my_turn"] = True
            info["mulligans_taken"] = players[viewer_seat].mulligans_taken
            info.update(_keep_terms(session, viewer_seat))
            info["hand_exchange"] = _hand_exchange_offer(session, viewer_seat)
        else:
            pending = [
                i
                for i in range(len(players))
                if i in deciding or i in session.mulligan_bottom_required_by_seat
            ]
            info["is_my_turn"] = False
            info["mulligans_taken"] = 0
            info["waiting_for"] = ", ".join(players[i].name for i in pending) or None

    elif phase == "mulligan":
        offer = session.mulligan_offer_seat
        offer_name = session.game.players[offer].name if offer is not None else None
        info["offer_seat"] = offer
        info["offer_name"] = offer_name
        info["is_my_turn"] = viewer_seat is not None and viewer_seat == offer
        info["mulligans_taken"] = session.game.players[offer].mulligans_taken if offer is not None else 0
        if offer is not None:
            info.update(_keep_terms(session, offer))
        if info["is_my_turn"]:
            info["hand_exchange"] = _hand_exchange_offer(session, offer)
        else:
            info["waiting_for"] = offer_name

    elif phase == "bottom_select":
        bottom = session.mulligan_bottom_seat
        bottom_name = session.game.players[bottom].name if bottom is not None else None
        info["bottom_seat"] = bottom
        info["bottom_name"] = bottom_name
        info["is_my_turn"] = viewer_seat is not None and viewer_seat == bottom
        info["required_count"] = session.mulligan_bottom_required
        info["mulligans_taken"] = (
            session.game.players[bottom].mulligans_taken if bottom is not None else 0
        )
        info["selected_indices"] = list(session.mulligan_bottom_selected)
        info["selected_count"] = len(session.mulligan_bottom_selected)
        if not info["is_my_turn"]:
            info["waiting_for"] = bottom_name

    return info


def _may_take_mulligan(session: Session, seat: int) -> bool:
    """CR 103.5: "A player can take mulligans until their opening hand would
    be zero cards, after which they may not take further mulligans" — counted
    as CR 103.5c counts, so a multiplayer or Brawl player's free first
    mulligan buys one more. The refusal (``action_pregame``) and the offer
    (:func:`_keep_terms`) ask this one question."""
    return session.game.mulligan_effective_count(seat) < 7


def _keep_terms(session: Session, seat: int) -> dict:
    """What the seat offered keep-or-mulligan is told it is choosing between:
    ``bottom_owed``, the cards a keep now puts on the bottom
    (``Game.mulligan_effective_count`` — CR 103.5's "number of times that
    player has taken a mulligan", less CR 103.5c's free first one at a
    multiplayer or Brawl table), and ``may_mulligan``. The client read
    ``mulligans_taken`` for both until the kg3 round, so a three-seat table's
    first mulligan said it would cost a card.

    ``bottom_paid`` is what an exchange "any time you could mulligan" already
    put on the bottom for this hand (CR 103.5b, Serum Powder — the bottom
    comes first, ``Game.pregame_hand_exchange``), so the offer can tell a
    bottom paid from a mulligan that was free: the client read ``bottom_owed``
    falling to zero after an exchange as CR 103.5c's free first mulligan."""
    return {
        "bottom_owed": session.game.mulligan_bottom_owed(seat),
        "bottom_paid": int(session.game.players[seat].mulligan_bottom_paid or 0),
        "may_mulligan": _may_take_mulligan(session, seat),
    }


def _hand_exchange_offer(session: Session, seat: int) -> dict | None:
    """CR 103.5b's third answer to the keep-or-mulligan offer, where *seat*'s
    hand holds a card granting one ("any time you could mulligan … exile all
    the cards from your hand, then draw that many", Serum Powder): the hand
    slots of the cards that grant it, and how many cards the
    ``mulligan_exchange`` action must name to go to the bottom first
    (``bottom_owed`` — the exchange pays the mulligan's bottom before it
    exiles, and never with every granting card). None where no card grants
    it. **Served to that seat alone**: the slots say where a card sits in a
    hidden hand (CR 400.2)."""
    sources = exchange_sources(session.game, seat)
    if not sources:
        return None
    return {
        "source_indices": sources,
        "bottom_owed": session.game.mulligan_bottom_owed(seat),
    }


def _pregame_enter_mulligan(session: Session, starting_player: int) -> None:
    session.pregame_starting_player = starting_player
    session.game.deal_opening_hands(starting_player)
    session.mulligan_kept_seats = set()
    session.mulligan_bottom_required_by_seat = {}
    session.mulligan_bottom_selected_by_seat = {}
    session.mulligan_round = 0
    seats = len(session.game.players)
    # CR 103.5: "First, the starting player declares … Then each other player
    # in turn order does the same."
    _pregame_begin_round(
        session, [(starting_player + offset) % seats for offset in range(seats)]
    )


def _pregame_begin_round(session: Session, seats: list[int]) -> None:
    """A round of declarations among *seats* (in turn order from the starting
    player): the sequential table offers the first of them; the simultaneous
    one asks them all at once, so it has no single offer seat."""
    session.mulligan_round += 1
    session.mulligan_round_seats = list(seats)
    session.mulligan_declared = set()
    session.pregame_phase = "mulligan"
    session.mulligan_offer_seat = None if session.simultaneous_mulligan else seats[0]


def _round_undecided(session: Session) -> list[int]:
    """The seats of this round still to declare, in turn order."""
    return [
        seat for seat in session.mulligan_round_seats
        if seat not in session.mulligan_kept_seats and seat not in session.mulligan_declared
    ]


def _pregame_advance(session: Session) -> None:
    """After a declaration (or a keeping seat's bottom choice on the
    sequential table): the round's next seat to declare, or — once every seat
    of the round has declared — the round's mulligans."""
    deciding = _round_undecided(session)
    if deciding:
        if not session.simultaneous_mulligan:
            session.mulligan_offer_seat = deciding[0]
            session.pregame_phase = "mulligan"
        return
    _pregame_finish_round(session)


def _pregame_finish_round(session: Session) -> None:
    """CR 103.5: "all players who decided to take mulligans do so at the same
    time", in turn order from the starting player (the order their shuffles
    draw on the RNG), and the seats that took one declare again in the next
    round. A round in which nobody mulliganed is the last: the game starts —
    on the simultaneous table once every keeping seat has bottomed too."""
    mulliganing = [
        seat for seat in session.mulligan_round_seats if seat in session.mulligan_declared
    ]
    for seat in mulliganing:
        session.game.pregame_mulligan_draw(seat)
    if mulliganing:
        _pregame_begin_round(session, mulliganing)
        return
    session.mulligan_round_seats = []
    session.mulligan_declared = set()
    session.mulligan_offer_seat = None
    if session.simultaneous_mulligan:
        _pregame_check_simultaneous_done(session)
    else:
        _pregame_start_game(session)


def _pregame_declare_mulligan(session: Session, seat: int) -> None:
    """*seat* declares a mulligan (CR 103.5). Nothing moves yet: the mulligan
    is taken with the round's others once the round's last seat has declared,
    and the declaration is public, so it is said in the log the next seat to
    declare reads."""
    session.mulligan_declared.add(seat)
    session.game.log.append(f"{session.game.players[seat].name} will take a mulligan")
    _pregame_advance(session)


def _pregame_hand_exchange(session: Session, seat: int, bottom) -> bool:
    """*seat* takes CR 103.5b's exchange in its declaration (Serum Powder):
    the cards *bottom* names go to the bottom first, the rest of the hand is
    exiled and as many drawn (``Game.pregame_hand_exchange``). The seat has
    not declared: it is offered keep-or-mulligan again with the new hand, so
    nothing here advances the round. False when the engine refused it."""
    return session.game.pregame_hand_exchange(seat, list(bottom or ()))


def _pregame_keep_player(session: Session, seat: int) -> None:
    session.mulligan_kept_seats.add(seat)
    # CR 103.5: as many cards as mulligans taken — less the free first one
    # CR 103.5c gives a multiplayer or Brawl game, which this reads as owed,
    # and less what an exchange already bottomed (CR 103.5b).
    owed = session.game.mulligan_bottom_owed(seat)
    if session.simultaneous_mulligan:
        # Bottom selection runs per-seat and concurrently: this seat picks its
        # bottom cards while the others may still be deciding keep/mulligan.
        if owed > 0:
            session.mulligan_bottom_required_by_seat[seat] = owed
            session.mulligan_bottom_selected_by_seat[seat] = []
        else:
            session.game.keep_hand(seat)
        _pregame_advance(session)
        return
    if owed > 0:
        session.pregame_phase = "bottom_select"
        session.mulligan_bottom_seat = seat
        session.mulligan_bottom_required = owed
        session.mulligan_bottom_selected = []
    else:
        session.game.keep_hand(seat)
        _pregame_advance(session)


def _pregame_ai_decides(session: Session, seat: int) -> None:
    """An AI seat's declaration for this round: keep — through the step a
    person's keep takes, which asks it for its bottom cards if it owes any —
    when ``ai_mulligan.keeps_opening_hand`` says so, else a mulligan, taken
    with the round's others. (It says keep once no further mulligan may be
    taken, CR 103.5's hand of zero cards.) Any exchange "any time you could
    mulligan" it takes comes first (CR 103.5b, ``ai_mulligan``)."""
    take_hand_exchanges(session.game, seat)
    if keeps_opening_hand(session.game, seat):
        _pregame_keep_player(session, seat)
    else:
        _pregame_declare_mulligan(session, seat)


def _pregame_check_simultaneous_done(session: Session) -> None:
    """Simultaneous mode: the game starts once every seat has kept and no seat
    still owes bottom cards."""
    if session.pregame_phase != "mulligan":
        return
    if len(session.mulligan_kept_seats) < len(session.game.players):
        return
    if session.mulligan_bottom_required_by_seat:
        return
    _pregame_start_game(session)


def _bottom_indices(session: Session, seat: int, selected, required: int) -> list[int]:
    """The hand indices *seat* keeps its hand without: what it selected,
    highest first."""
    player = session.game.players[seat]
    indices = sorted(set(selected), reverse=True)
    # Safety: if somehow fewer cards are selected, auto-fill from end of hand
    if len(indices) < required:
        extras = [i for i in range(len(player.hand) - 1, -1, -1) if i not in set(indices)]
        indices = sorted(set(indices) | set(extras[: required - len(indices)]), reverse=True)
    return indices


def _pregame_confirm_bottom_simultaneous(session: Session, seat: int) -> None:
    required = session.mulligan_bottom_required_by_seat.get(seat, 0)
    selected = session.mulligan_bottom_selected_by_seat.get(seat, [])
    session.game.keep_opening_hand(
        seat, _bottom_indices(session, seat, selected, required)
    )
    session.mulligan_bottom_required_by_seat.pop(seat, None)
    session.mulligan_bottom_selected_by_seat.pop(seat, None)
    _pregame_check_simultaneous_done(session)


def _pregame_confirm_bottom(session: Session) -> None:
    seat = session.mulligan_bottom_seat
    session.game.keep_opening_hand(
        seat,
        _bottom_indices(
            session, seat, session.mulligan_bottom_selected,
            session.mulligan_bottom_required,
        ),
    )
    session.mulligan_bottom_seat = None
    session.mulligan_bottom_required = 0
    session.mulligan_bottom_selected = []
    _pregame_advance(session)


def _pregame_start_game(session: Session) -> None:
    """The pregame is over (CR 103.5 done): the starting player takes their
    first turn (CR 103.8). Its beginning phase is owed rather than run here
    — ``turn_steps`` is above this module in ``web.LAYERS`` — and the route or
    action that got here runs it (``turn_steps._settle_pregame``)."""
    starting_player = session.pregame_starting_player or 0
    session.pregame_phase = None
    session.current_turn = starting_player
    session.game.active_player_index = starting_player
    session.game.start_priority_window(starting_player)
    session.first_turn_owed = True


def _pregame_auto_advance(session: Session) -> None:
    # One AI step a pass — a declaration can end its round and begin the next
    # — so the bound covers the most a table can owe: up to nine declarations
    # and a bottom choice per seat (CR 103.5 stops at a hand of zero cards,
    # and CR 103.5c's free first mulligan adds one).
    for _ in range(20 * max(1, len(session.game.players))):
        if session.pregame_phase == "coin_flip":
            winner = session.coin_flip_winner
            if winner is None or _seat_type(session, winner) != "ai":
                break
            # The AI's play/draw policy: it plays first. Said in the log as a
            # person's choice is, so the seat it chose for knows why the game
            # opened on the AI's turn (a rematch the AI lost, CR 103.1).
            session.game.log.append(f"{session.game.players[winner].name} chooses to go first")
            _pregame_enter_mulligan(session, winner)

        elif session.pregame_phase == "mulligan" and session.simultaneous_mulligan:
            # Every AI seat of the round declares right away, and one that
            # kept owing cards bottoms them; the round then waits on the
            # human seats still to declare (each prompted concurrently), and
            # its mulligans are taken once the last of them has. Until the kg2
            # round an AI seat only ever kept, so a seat owing bottom cards was
            # always a person's, and nothing here answered one for an AI.
            bottoming_ai = [
                i
                for i in sorted(session.mulligan_bottom_required_by_seat)
                if _seat_type(session, i) == "ai"
            ]
            deciding_ai = [
                i for i in _round_undecided(session) if _seat_type(session, i) == "ai"
            ]
            if bottoming_ai:
                seat = bottoming_ai[0]
                session.mulligan_bottom_selected_by_seat[seat] = opening_hand_bottom(
                    session.game, seat, session.mulligan_bottom_required_by_seat[seat]
                )
                _pregame_confirm_bottom_simultaneous(session, seat)
            elif deciding_ai:
                _pregame_ai_decides(session, deciding_ai[0])
            else:
                break

        elif session.pregame_phase == "mulligan":
            offer = session.mulligan_offer_seat
            if offer is None or _seat_type(session, offer) != "ai":
                break
            _pregame_ai_decides(session, offer)

        elif session.pregame_phase == "bottom_select":
            bottom = session.mulligan_bottom_seat
            if bottom is None or _seat_type(session, bottom) != "ai":
                break
            session.mulligan_bottom_selected = opening_hand_bottom(
                session.game, bottom, session.mulligan_bottom_required
            )
            _pregame_confirm_bottom(session)

        else:
            break
