"""Handlers for the pregame flow: the coin flip and the mulligan rounds
(CR 103.5, ``web/pregame.py``). The only specs registered with
``pregame=True`` - everything else waits until the game proper has begun.
"""

from __future__ import annotations

from fastapi import HTTPException
from .action_registry import action_handler
from .pregame import (
    _pregame_auto_advance,
    _pregame_confirm_bottom,
    _pregame_confirm_bottom_simultaneous,
    _pregame_declare_mulligan,
    _pregame_enter_mulligan,
    _pregame_keep_player,
    _round_undecided,
)


@action_handler("coin_flip_choose", pregame=True)
def _action_coin_flip_choose(session, req, seat_type):
    if session.pregame_phase != "coin_flip":
        raise HTTPException(status_code=400, detail="not in coin flip phase")
    if req.seat != session.coin_flip_winner:
        raise HTTPException(status_code=400, detail="only the coin flip winner can choose")
    if seat_type != "human":
        raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")
    choice = req.hand_index  # 0 = go first, 1 = go second
    if choice not in (0, 1):
        raise HTTPException(status_code=400, detail="hand_index must be 0 (go first) or 1 (go second)")
    if choice == 1 and len(session.game.players) != 2:
        # "Go second" only maps unambiguously to "the other player" in a
        # 2-player game; FFA doesn't offer this choice (not in MVP scope).
        raise HTTPException(status_code=400, detail="go second is only available in a 2-player game")
    starting_player = req.seat if choice == 0 else (1 - req.seat)
    session.game.log.append(
        f"{session.game.players[req.seat].name} chooses to go {'first' if choice == 0 else 'second'}"
    )
    _pregame_enter_mulligan(session, starting_player)
    _pregame_auto_advance(session)

def _require_declaring_seat(session, req, seat_type) -> None:
    """The seat may declare keep or mulligan now (CR 103.5): the sequential
    table's offered seat, or on the simultaneous table any seat of the round
    still to declare."""
    if session.pregame_phase != "mulligan":
        raise HTTPException(status_code=400, detail="not in mulligan phase")
    if session.simultaneous_mulligan:
        if req.seat in session.mulligan_kept_seats:
            raise HTTPException(status_code=400, detail="you already kept your hand")
        if req.seat in session.mulligan_declared:
            raise HTTPException(
                status_code=400,
                detail="you declared a mulligan; it is taken once every player has declared",
            )
        if req.seat not in _round_undecided(session):
            raise HTTPException(status_code=400, detail="not your turn to decide on mulligan")
    elif req.seat != session.mulligan_offer_seat:
        raise HTTPException(status_code=400, detail="not your turn to decide on mulligan")
    if seat_type != "human":
        raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")


@action_handler("mulligan_take", pregame=True)
def _action_mulligan_take(session, req, seat_type):
    _require_declaring_seat(session, req, seat_type)
    if session.game.mulligan_effective_count(req.seat) >= 7:
        # CR 103.5: "A player can take mulligans until their opening hand
        # would be zero cards, after which they may not take further
        # mulligans."
        raise HTTPException(
            status_code=400, detail="cannot take another mulligan (hand would be 0 cards)"
        )
    _pregame_declare_mulligan(session, req.seat)
    _pregame_auto_advance(session)

@action_handler("mulligan_keep", pregame=True)
def _action_mulligan_keep(session, req, seat_type):
    _require_declaring_seat(session, req, seat_type)
    _pregame_keep_player(session, req.seat)
    _pregame_auto_advance(session)

@action_handler("mulligan_bottom_select", pregame=True)
def _action_mulligan_bottom_select(session, req, seat_type):
    if session.simultaneous_mulligan:
        # Bottom selection runs inside the shared "mulligan" phase, one
        # concurrent selection per seat that kept after mulliganing.
        if session.pregame_phase != "mulligan":
            raise HTTPException(status_code=400, detail="not in bottom card selection phase")
        if req.seat not in session.mulligan_bottom_required_by_seat:
            raise HTTPException(status_code=400, detail="you have no bottom cards to select")
    else:
        if session.pregame_phase != "bottom_select":
            raise HTTPException(status_code=400, detail="not in bottom card selection phase")
        if req.seat != session.mulligan_bottom_seat:
            raise HTTPException(status_code=400, detail="not your turn to select bottom cards")
    if seat_type != "human":
        raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index is required")
    player = session.game.players[req.seat]
    if req.hand_index >= len(player.hand):
        raise HTTPException(status_code=400, detail="invalid hand index")
    selected = (
        session.mulligan_bottom_selected_by_seat[req.seat]
        if session.simultaneous_mulligan
        else session.mulligan_bottom_selected
    )
    if req.hand_index in selected:
        selected.remove(req.hand_index)
    else:
        selected.append(req.hand_index)

@action_handler("mulligan_bottom_confirm", pregame=True)
def _action_mulligan_bottom_confirm(session, req, seat_type):
    if session.simultaneous_mulligan:
        if session.pregame_phase != "mulligan":
            raise HTTPException(status_code=400, detail="not in bottom card selection phase")
        if req.seat not in session.mulligan_bottom_required_by_seat:
            raise HTTPException(status_code=400, detail="you have no bottom cards to select")
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")
        required = session.mulligan_bottom_required_by_seat[req.seat]
        if len(session.mulligan_bottom_selected_by_seat.get(req.seat, [])) != required:
            raise HTTPException(
                status_code=400,
                detail=f"must select exactly {required} card(s)",
            )
        _pregame_confirm_bottom_simultaneous(session, req.seat)
        _pregame_auto_advance(session)
    else:
        if session.pregame_phase != "bottom_select":
            raise HTTPException(status_code=400, detail="not in bottom card selection phase")
        if req.seat != session.mulligan_bottom_seat:
            raise HTTPException(status_code=400, detail="not your turn to select bottom cards")
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")
        if len(session.mulligan_bottom_selected) != session.mulligan_bottom_required:
            raise HTTPException(
                status_code=400,
                detail=f"must select exactly {session.mulligan_bottom_required} card(s)",
            )
        _pregame_confirm_bottom(session)
        _pregame_auto_advance(session)
