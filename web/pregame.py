"""Everything before turn one: the coin flip and the mulligan rounds
(CR 103.5, London mulligan).

One function per transition, so the state machine reads as its own sequence
rather than as branches buried in the action dispatch: offer, take or keep,
bottom the extras, start the game. :func:`_pregame_auto_advance` is what a table
with no interactive seat owed a decision runs, so nothing waits on a prompt
nobody owns.
"""

from __future__ import annotations

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
        if not info["is_my_turn"]:
            info["waiting_for"] = winner_name

    elif phase == "mulligan" and session.simultaneous_mulligan:
        # Everyone decides at once, so the phase is per-viewer: deciding seats
        # see the keep/mulligan prompt, seats that kept after a mulligan see
        # their own bottom_select, and finished seats see who is still pending.
        info["simultaneous"] = True
        players = session.game.players
        if viewer_seat is not None and viewer_seat in session.mulligan_bottom_required_by_seat:
            selected = session.mulligan_bottom_selected_by_seat.get(viewer_seat, [])
            info["phase"] = "bottom_select"
            info["bottom_seat"] = viewer_seat
            info["bottom_name"] = players[viewer_seat].name
            info["is_my_turn"] = True
            info["required_count"] = session.mulligan_bottom_required_by_seat[viewer_seat]
            info["selected_indices"] = list(selected)
            info["selected_count"] = len(selected)
        elif viewer_seat is not None and viewer_seat not in session.mulligan_kept_seats:
            info["offer_seat"] = viewer_seat
            info["offer_name"] = players[viewer_seat].name
            info["is_my_turn"] = True
            info["mulligans_taken"] = players[viewer_seat].mulligans_taken
        else:
            pending = [
                i
                for i in range(len(players))
                if i not in session.mulligan_kept_seats
                or i in session.mulligan_bottom_required_by_seat
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
        if not info["is_my_turn"]:
            info["waiting_for"] = offer_name

    elif phase == "bottom_select":
        bottom = session.mulligan_bottom_seat
        bottom_name = session.game.players[bottom].name if bottom is not None else None
        info["bottom_seat"] = bottom
        info["bottom_name"] = bottom_name
        info["is_my_turn"] = viewer_seat is not None and viewer_seat == bottom
        info["required_count"] = session.mulligan_bottom_required
        info["selected_indices"] = list(session.mulligan_bottom_selected)
        info["selected_count"] = len(session.mulligan_bottom_selected)
        if not info["is_my_turn"]:
            info["waiting_for"] = bottom_name

    return info


def _pregame_enter_mulligan(session: Session, starting_player: int) -> None:
    session.pregame_starting_player = starting_player
    session.game.deal_opening_hands(starting_player)
    session.pregame_phase = "mulligan"
    # Simultaneous mode: no single offer seat — every seat decides at once and
    # per-seat progress lives in mulligan_kept_seats / *_by_seat dicts.
    session.mulligan_offer_seat = None if session.simultaneous_mulligan else starting_player
    session.mulligan_kept_seats = set()
    session.mulligan_bottom_required_by_seat = {}
    session.mulligan_bottom_selected_by_seat = {}


def _pregame_advance_mulligan_offer(session: Session) -> None:
    n = len(session.game.players)
    current = session.mulligan_offer_seat or 0
    for _ in range(n):
        current = (current + 1) % n
        if current not in session.mulligan_kept_seats:
            session.mulligan_offer_seat = current
            session.pregame_phase = "mulligan"
            return
    _pregame_start_game(session)


def _pregame_keep_player(session: Session, seat: int) -> None:
    player = session.game.players[seat]
    session.mulligan_kept_seats.add(seat)
    if session.simultaneous_mulligan:
        # Bottom selection runs per-seat and concurrently: this seat picks its
        # bottom cards while the others may still be deciding keep/mulligan.
        if player.mulligans_taken > 0:
            session.mulligan_bottom_required_by_seat[seat] = player.mulligans_taken
            session.mulligan_bottom_selected_by_seat[seat] = []
        else:
            session.game.keep_hand(seat)
        _pregame_check_simultaneous_done(session)
        return
    if player.mulligans_taken > 0:
        session.pregame_phase = "bottom_select"
        session.mulligan_bottom_seat = seat
        session.mulligan_bottom_required = player.mulligans_taken
        session.mulligan_bottom_selected = []
    else:
        session.game.keep_hand(seat)
        _pregame_advance_mulligan_offer(session)


def _pregame_check_simultaneous_done(session: Session) -> None:
    """Simultaneous mode: the game starts once every seat has kept and no seat
    still owes bottom cards."""
    if len(session.mulligan_kept_seats) < len(session.game.players):
        return
    if session.mulligan_bottom_required_by_seat:
        return
    _pregame_start_game(session)


def _pregame_confirm_bottom_simultaneous(session: Session, seat: int) -> None:
    player = session.game.players[seat]
    required = session.mulligan_bottom_required_by_seat.get(seat, 0)
    indices = sorted(set(session.mulligan_bottom_selected_by_seat.get(seat, [])), reverse=True)
    # Safety: if somehow fewer cards are selected, auto-fill from end of hand
    if len(indices) < required:
        extras = [i for i in range(len(player.hand) - 1, -1, -1) if i not in set(indices)]
        indices = sorted(set(indices) | set(extras[: required - len(indices)]), reverse=True)
    cards_to_bottom = [player.hand.pop(i) for i in indices]
    player.library.extend(cards_to_bottom)
    session.game.keep_hand(seat)
    session.mulligan_bottom_required_by_seat.pop(seat, None)
    session.mulligan_bottom_selected_by_seat.pop(seat, None)
    _pregame_check_simultaneous_done(session)


def _pregame_confirm_bottom(session: Session) -> None:
    seat = session.mulligan_bottom_seat
    player = session.game.players[seat]
    required = session.mulligan_bottom_required
    indices = sorted(set(session.mulligan_bottom_selected), reverse=True)
    # Safety: if somehow fewer cards are selected, auto-fill from end of hand
    if len(indices) < required:
        extras = [i for i in range(len(player.hand) - 1, -1, -1) if i not in set(indices)]
        indices = sorted(set(indices) | set(extras[: required - len(indices)]), reverse=True)
    cards_to_bottom = [player.hand.pop(i) for i in indices]
    player.library.extend(cards_to_bottom)
    session.game.keep_hand(seat)
    session.mulligan_bottom_seat = None
    session.mulligan_bottom_required = 0
    session.mulligan_bottom_selected = []
    _pregame_advance_mulligan_offer(session)


def _pregame_start_game(session: Session) -> None:
    starting_player = session.pregame_starting_player or 0
    session.pregame_phase = None
    session.current_turn = starting_player
    session.game.active_player_index = starting_player
    session.game.start_priority_window(starting_player)


def _pregame_auto_advance(session: Session) -> None:
    for _ in range(20):
        if session.pregame_phase == "coin_flip":
            winner = session.coin_flip_winner
            if winner is None or _seat_type(session, winner) != "ai":
                break
            _pregame_enter_mulligan(session, winner)

        elif session.pregame_phase == "mulligan" and session.simultaneous_mulligan:
            # Every AI seat keeps its hand right away; the phase then waits on
            # the remaining human seats (each prompted concurrently).
            pending_ai = [
                i
                for i in range(len(session.game.players))
                if i not in session.mulligan_kept_seats and _seat_type(session, i) == "ai"
            ]
            if not pending_ai:
                break
            for i in pending_ai:
                _pregame_keep_player(session, i)

        elif session.pregame_phase == "mulligan":
            offer = session.mulligan_offer_seat
            if offer is None or _seat_type(session, offer) != "ai":
                break
            _pregame_keep_player(session, offer)

        elif session.pregame_phase == "bottom_select":
            bottom = session.mulligan_bottom_seat
            if bottom is None or _seat_type(session, bottom) != "ai":
                break
            n = session.mulligan_bottom_required
            player = session.game.players[bottom]
            session.mulligan_bottom_selected = list(
                range(max(0, len(player.hand) - n), len(player.hand))
            )
            _pregame_confirm_bottom(session)

        else:
            break
