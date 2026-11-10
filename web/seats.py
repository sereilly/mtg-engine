"""Who is sitting at a seat, whether they are still in the game, and
whether the game should stop for them.

Three questions the rest of the web layer asks constantly and that need no card
data to answer: what kind of seat this is (human / AI / open), whether a player
has lost (CR 104.3), and whether phase advancement should hold priority rather
than run on. They are kept together, and kept free of dependencies, because
every other module asks at least one of them.
"""

from __future__ import annotations

from engine.game_result_bans import player_cant_lose
from engine.player_control import decided_by

from .session_store import Session


def _sitter_type(session: Session, seat: int) -> str:
    """Who **sits** at *seat* — "human", "ai" or "open" — as the session was
    configured: the identity questions (who is a person at this table, whose
    vote a rematch needs) ask this."""
    return session.seat_types.get(seat) or session.seat_types.get(str(seat), "human")


def _seat_type(session: Session, seat: int) -> str:
    """Who **decides** for *seat* right now: the kind of seat its decider sits
    at (``Game.decider_of``, CR 723.5) — the sitter's own kind except during
    a turn another player controls (Mindslaver). Every "does the AI act for
    this seat, or is a person asked" question in the web layer asks this, so
    a person controlling an AI seat's turn is asked that seat's decisions and
    an AI controlling a person's turn plays it."""
    game = getattr(session, "game", None)
    decider = game.decider_of(seat) if game is not None and isinstance(seat, int) else seat
    return _sitter_type(session, decider)


def _mark_interactive_seats(session: Session) -> None:
    """Tell the engine which seats a person sits at
    (``Game.interactive_seats``), so a decision owed to one of them — or to a
    seat one of them controls this turn (``Game.asks_a_person``, CR 723) — is
    asked rather than defaulted. Before anything the server runs for a seat: every
    action (``actions.do_action``), and turn 1's beginning phase, which a
    route may run before any action has been sent
    (``turn_steps._begin_first_turn``)."""
    session.game.interactive_seats = {
        s for s in range(len(session.game.players)) if _sitter_type(session, s) == "human"
    }


def _player_has_lost(game, seat: int) -> bool:
    """Whether the player in *seat* has lost the game.

    Uses the engine's own state-based-action flag when set, and otherwise
    falls back to the 0-or-less-life rule — honoring replacement effects such as
    Lich's "You don't lose the game for having 0 or less life." so dropping to 0
    life does not hand the game to the opponent."""
    player = game.players[seat]
    if getattr(player, "lost", False):
        return True
    # "You can't lose the game …" (Platinum Angel): the fallback is CR 704.5a
    # read early, so it asks the same ban the engine's loss funnel asks
    # (``engine/game_result_bans.py``) — without it a player at 0 life behind
    # an Angel was shown the game as lost while the engine played on.
    if player.life <= 0 and not game._player_controls_text(
        player, "you don't lose the game for having 0 or less life"
    ) and not player_cant_lose(game, seat):
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


def _rematch_first_chooser(session: Session) -> tuple[int | None, str | None]:
    """Who chooses who plays first in the next game of the match, and why
    (CR 103.1): "the loser of the previous game chooses … If the previous game
    was a draw, the player who made the choice in that game makes the choice
    in this game." The choice in that game was ``coin_flip_winner``'s — the
    flip's winner, or a rematch's chooser, which is the seat that field names
    for the whole game. ``(None, None)`` when nobody can be named (a draw with
    no recorded chooser), which falls back to a flip."""
    loser = _loser(session)
    if loser is not None:
        return loser, "loser"
    if _winner(session) == -1 and session.coin_flip_winner is not None:
        return session.coin_flip_winner, "draw"
    return None, None


def _rematch_human_seats(session: Session) -> list[int]:
    """Joined human seats whose agreement is needed to start a rematch."""
    return [
        s for s in sorted(session.joined_seats)
        if _sitter_type(session, s) == "human"
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


def _declaration_owed(game) -> bool:
    """Whether the step's turn-based action is still to be made: the
    declare attackers step with no attack declared, or the declare blockers
    step with the blocks not all declared (CR 508.1, 509.1). Nobody holds
    priority until it is (CR 117.3a gives priority in a step "after any
    turn-based actions … have been dealt with"), so neither seat is handed
    it — the AI asks this before acting (``game_flow._ai_holds_priority``)
    and the phase rail's hold before handing the person priority
    (``game_flow._hold_at_flagged_step``)."""
    if game.current_turn_phase != "combat":
        return False
    if game.current_step == "declare_attackers":
        return not game.combat_attackers_locked
    if game.current_step == "declare_blockers":
        return not game.combat_blockers_locked
    return False


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


def controlled_seat_refusal(
    session: Session, seat: int, action: str, controller_seat: int | None,
    exempt: frozenset[str] = frozenset(),
) -> str | None:
    """Why an action for *seat* is refused under CR 723 (Mindslaver), or None.

    *controller_seat* is the sender when it acts for a seat it controls (the
    request's ``controller_seat``); absent, the seat acts for itself.

    * A controller acting for another seat must be the seat deciding for it
      now (``Game.decider_of``), and may do anything that seat may — except
      concede for it: "the controller of another player can't make that
      player concede" (CR 723.6).
    * A seat another player controls makes none of its own decisions
      (CR 723.5) — but "a player may concede the game at any time, even if
      they are controlled by another player" (CR 723.6). Its ``ai_step`` and
      the Debug Menu's actions (*exempt*) decide nothing for anybody and are
      let through: the first is how the client of a person an AI controls
      asks the AI to play the turn.
    """
    game = session.game
    decider = game.decider_of(seat)
    if controller_seat is not None and controller_seat != seat:
        if controller_seat not in session.joined_seats:
            return "seat has not joined"
        if decider != controller_seat:
            return "you do not control that player this turn"
        if action == "concede":
            return "you can't make the player you control concede (CR 723.6)"
        return None
    if decider != seat and action not in {"concede", "ai_step"} | set(exempt):
        return (
            f"{game.players[decider].name} controls you this turn (CR 723.5); "
            "you may only concede"
        )
    return None


def acting_seat_for(session: Session, viewer_seat: int | None, owed_seat) -> int | None:
    """The seat a person deciding for more than one seat (CR 723.8: their
    own, and the one they control this turn) acts as right now, or None when
    *viewer_seat*'s decider decides for nobody else.

    Asked for the decider of the viewer, so the person reads the same answer
    whichever of the two seats they are looking through. In order: the seat
    that owes the decision holding the game (*owed_seat*, the payload's
    ``prompt_owed_by``), the seat a declaration is owed by (CR 508.1 the
    active player's attack, CR 509.1 a defending player's blocks), the seat
    holding priority, and otherwise the active player (CR 723.3: the
    controlled player is still the active player)."""
    game = session.game
    if viewer_seat is None or not 0 <= viewer_seat < len(game.players):
        return None
    decider = game.decider_of(viewer_seat)
    seats = decided_by(game, decider)
    if len(seats) == 1:
        return None
    if owed_seat in seats:
        return owed_seat
    if _declaration_owed(game):
        if game.current_step == "declare_attackers":
            active = game.active_player_index
            return active if active in seats else decider
        defending = sorted(set(seats) & game.combat_defending_players())
        return defending[0] if defending else decider
    holder = game.priority_player_index
    if holder in seats:
        return holder
    active = game.active_player_index
    return active if active in seats else decider
