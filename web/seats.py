"""Who is sitting at a seat, whether they are still in the game, and
whether the game should stop for them.

Three questions the rest of the web layer asks constantly and that need no card
data to answer: what kind of seat this is (human / AI / open), whether a player
has lost (CR 104.3), and whether phase advancement should hold priority rather
than run on. They are kept together, and kept free of dependencies, because
every other module asks at least one of them.
"""

from __future__ import annotations

from .session_store import Session


def _seat_type(session: Session, seat: int) -> str:
    return session.seat_types.get(seat) or session.seat_types.get(str(seat), "human")


def _player_has_lost(game, seat: int) -> bool:
    """Whether the player in *seat* has lost the game.

    Uses the engine's own state-based-action flag when set, and otherwise
    falls back to the 0-or-less-life rule — honoring replacement effects such as
    Lich's "You don't lose the game for having 0 or less life." so dropping to 0
    life does not hand the game to the opponent."""
    player = game.players[seat]
    if getattr(player, "lost", False):
        return True
    if player.life <= 0 and not game._player_controls_text(
        player, "you don't lose the game for having 0 or less life"
    ):
        return True
    return False


def _winner(session: Session) -> int | None:
    """Seat of the game's winner, ``-1`` for a draw, or None while play
    continues. Rule 104.2a generalized to any player count: the game is only
    decided once a single seat remains — in Free-For-All the first elimination
    must NOT finish the game (the dead player spectates until the end)."""
    lost = [_player_has_lost(session.game, i) for i in range(len(session.game.players))]
    alive = [i for i, has_lost in enumerate(lost) if not has_lost]
    if not alive:
        return -1
    if len(alive) == 1 and len(lost) > 1:
        return alive[0]
    return None


def _loser(session: Session) -> int | None:
    """Return the seat of the losing player, or None when the game was a draw
    or is not yet decided."""
    win = _winner(session)
    if win is None or win == -1:
        return None
    return 1 - win


def _first_opponent_seat(game, seat: int) -> int | None:
    """A living opposing seat for *seat* — the only other seat in a 2-player
    game, or the first still-alive opponent (turn order) in Free-For-All.
    Returns None if no opposing seat exists."""
    for offset in range(1, len(game.players)):
        candidate = (seat + offset) % len(game.players)
        if not _player_has_lost(game, candidate):
            return candidate
    return None


def _rematch_human_seats(session: Session) -> list[int]:
    """Joined human seats whose agreement is needed to start a rematch."""
    return [
        s for s in sorted(session.joined_seats)
        if _seat_type(session, s) == "human"
    ]


def _build_rematch_info(session: Session, viewer_seat: int | None) -> dict | None:
    """Serialize coordinated-rematch state for human_vs_human games.

    Only meaningful once the game is finished; clients use it to drive the
    "Play Again" / "Accept Rematch" / "Waiting for opponent…" button states.
    """
    if session.mode != "human_vs_human":
        return None
    needed = _rematch_human_seats(session)
    you_requested = viewer_seat is not None and viewer_seat in session.rematch_votes
    opponent_requested = any(
        s in session.rematch_votes for s in needed if s != viewer_seat
    )
    return {
        "votes": sorted(session.rematch_votes),
        "needed": needed,
        "you_requested": you_requested,
        "opponent_requested": opponent_requested,
    }


def _has_human_opponent(session: Session) -> bool:
    """True when a human shares the table with the active (AI) player."""
    active = session.game.active_player_index
    return any(
        _seat_type(session, s) == "human"
        for s in range(len(session.game.players))
        if s != active
    )


def _hold_priority_for_human(session: Session) -> bool:
    """During the AI's turn, hand priority to a human opponent so they may act at a
    step they flagged on the phase rail.

    The active player (AI) passes first, leaving priority with the human exactly as a
    real priority window would — when the human later passes, both players will have
    passed and the phase advances normally. Returns True if priority was handed off.
    """
    game = session.game
    human_seat = next(
        (
            s
            for s in range(len(game.players))
            if s != game.active_player_index and _seat_type(session, s) == "human"
        ),
        None,
    )
    if human_seat is None:
        return False
    if not game._receives_priority(game.current_step):
        return False
    if game.priority_player_index != game.active_player_index:
        game.start_priority_window(game.active_player_index)
    game.pass_priority(game.active_player_index)
    return True


def _ai_should_hold(session: Session, step: str) -> bool:
    """True when the human asked (via the phase rail) to receive priority at `step`
    on the AI's turn and that step actually grants priority."""
    return (
        step in session.opponent_stop_steps
        and session.game._receives_priority(step)
        and _has_human_opponent(session)
    )


def _self_should_hold(session: Session, step: str) -> bool:
    """True when the human asked (via the phase rail) to receive a priority window at
    `step` on their OWN turn — for steps the server would otherwise resolve itself
    (upkeep, draw) — and that step actually grants priority."""
    return (
        step in session.self_stop_steps
        and session.game._receives_priority(step)
        and _seat_type(session, session.game.active_player_index) == "human"
    )
