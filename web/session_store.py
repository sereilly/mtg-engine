from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import secrets

from engine import Game, PlayerState
from engine.game_history import GameHistory

from .deck_builder import build_random_deck
from .schemas import CreateSessionRequest


@dataclass
class Session:
    id: str
    mode: str
    host_name: str
    guest_name: str
    game: Game
    current_turn: int = 0
    status: str = "active"
    # hvh: seat1 joins later. other modes are immediately joined.
    joined_seats: set[int] = field(default_factory=lambda: {0})
    seat_types: dict[int, str] = field(default_factory=dict)
    cleanup_required_discards: int = 0
    cleanup_selected_indices: list[int] = field(default_factory=list)
    untap_required_lands: int = 0
    untap_candidate_indices: list[int] = field(default_factory=list)
    untap_selected_indices: list[int] = field(default_factory=list)
    upkeep_pay_choices: list[dict] = field(default_factory=list)
    upkeep_resolved_choices: dict[str, bool] = field(default_factory=dict)
    history: GameHistory = field(default_factory=GameHistory)
    card_positions: dict[str, dict[str, float]] = field(default_factory=dict)


class SessionStore:
    def __init__(self, cards_path: Path):
        self.cards_path = cards_path
        self._sessions: dict[str, Session] = {}

    def create(self, request: CreateSessionRequest) -> Session:
        sid = secrets.token_urlsafe(8)

        seed = self._resolve_seed(request)

        guest_name = request.guest_name
        if request.mode in {"human_vs_ai", "ai_vs_ai"} and guest_name.strip() in {"", "Player 2"}:
            guest_name = "AI"

        host_deck, _ = build_random_deck(self.cards_path, request.host_colors, seed)
        guest_deck, _ = build_random_deck(self.cards_path, request.guest_colors, seed + 1)

        p1 = PlayerState(name=request.host_name, library=host_deck)
        p2 = PlayerState(name=guest_name, library=guest_deck)
        p1.draw(7)
        p2.draw(7)

        game = Game(players=[p1, p2], enforce_mana_costs=True)

        seat_types = {0: "human", 1: "human"}
        joined_seats: set[int] = {0}
        if request.mode == "human_vs_ai":
            seat_types[1] = "ai"
            joined_seats.add(1)
        elif request.mode == "ai_vs_ai":
            seat_types[0] = "ai"
            seat_types[1] = "ai"
            joined_seats = {0, 1}

        session = Session(
            id=sid,
            mode=request.mode,
            host_name=request.host_name,
            guest_name=guest_name,
            game=game,
            joined_seats=joined_seats,
            seat_types=seat_types,
        )
        self._sessions[sid] = session
        return session

    def _resolve_seed(self, request: CreateSessionRequest) -> int:
        if request.use_custom_seed:
            if request.custom_seed is not None:
                return request.custom_seed
            if request.seed is not None:
                return request.seed

        if request.seed is not None:
            return request.seed

        return secrets.randbits(32)

    def get(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            raise KeyError("session not found")
        return self._sessions[session_id]

    def join(self, session_id: str, guest_name: str) -> Session:
        session = self.get(session_id)
        if session.mode != "human_vs_human":
            return session
        session.joined_seats.add(1)
        session.guest_name = guest_name
        session.game.players[1].name = guest_name
        return session
