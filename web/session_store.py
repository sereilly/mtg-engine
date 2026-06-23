from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import random
import secrets

from engine import Game, PlayerState
from engine.game_history import GameHistory

from .deck_builder import build_deck_from_entries, build_random_deck
from .deck_store import DeckStore
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
    # Seed used to build decks / drive the coin flip. Kept so the guest deck (built
    # at join time for networked human_vs_human) stays deterministic with the host.
    seed: int = 0
    use_pregame: bool = False
    # Networked human_vs_human only: the guest deck arrives with the join request,
    # so the game is held until the opponent joins.  False once they have.
    awaiting_opponent: bool = False
    # Deck selections kept so a rematch can rebuild fresh (reshuffled) decks for the
    # same two players. guest_* is filled at join time for networked human_vs_human.
    host_deck_id: str | None = None
    host_colors: int = 2
    guest_deck_id: str | None = None
    guest_colors: int = 2
    # Inline cards for personal (browser-only) decks that have no server-side id.
    # Kept so a rematch can rebuild the same deck off a new seed.
    host_deck_cards: list[dict] | None = None
    guest_deck_cards: list[dict] | None = None
    # Coordinated rematch (human_vs_human): seats that have requested a rematch on the
    # finished game. When every joined human seat has voted, the game is rebuilt.
    rematch_votes: set[int] = field(default_factory=set)
    cleanup_required_discards: int = 0
    cleanup_selected_indices: list[int] = field(default_factory=list)
    untap_required_lands: int = 0
    untap_candidate_indices: list[int] = field(default_factory=list)
    untap_selected_indices: list[int] = field(default_factory=list)
    upkeep_pay_choices: list[dict] = field(default_factory=list)
    upkeep_resolved_choices: dict[str, bool] = field(default_factory=dict)
    # Optional ("you may") upkeep triggers awaiting a yes/no decision (e.g. Nether
    # Shadow returning from the graveyard), and the answers collected so far.
    optional_trigger_choices: list[dict] = field(default_factory=list)
    optional_trigger_resolved: dict[str, bool] = field(default_factory=dict)
    # "Pay any amount of mana to prevent that much damage" upkeep triggers (Power
    # Leak). Each choice carries the card name and the max preventable damage; the
    # player's chosen amount per card is collected in the resolved map.
    upkeep_mana_prevention_choices: list[dict] = field(default_factory=list)
    upkeep_mana_prevention_resolved: dict[str, int] = field(default_factory=dict)
    island_sanctuary_pending: bool = False
    # Debug toggle: when True, the AI declares every legal attacker each combat
    # instead of its normal risk-weighted choice. Set via the in-game Debug Menu.
    force_ai_attack_all: bool = False
    # Engine step names a human wants to stop at on the opponent's (AI's) turn,
    # set from the phase-rail hold-priority toggles. The AI hands the human
    # priority at these steps instead of advancing past them.
    opponent_stop_steps: set[str] = field(default_factory=set)
    # Engine step names a human wants a priority window at on their OWN turn,
    # set from the phase-rail hold-priority toggles. The server opens a window at
    # these steps (e.g. upkeep, draw) instead of resolving straight into the main phase.
    self_stop_steps: set[str] = field(default_factory=set)
    history: GameHistory = field(default_factory=GameHistory)
    # Pregame state (used when enable_pregame=True).  None once the game starts.
    pregame_phase: str | None = None  # "coin_flip", "mulligan", "bottom_select"
    coin_flip_winner: int | None = None
    pregame_starting_player: int | None = None
    # On a rematch the previous game's loser, rather than a coin flip, decides
    # who plays first. When set, _begin_pregame skips the flip and hands that
    # seat the first-player choice; coin_flip_is_loser_choice drives the UI text.
    regame_first_chooser: int | None = None
    coin_flip_is_loser_choice: bool = False
    mulligan_offer_seat: int | None = None
    mulligan_kept_seats: set[int] = field(default_factory=set)
    mulligan_bottom_seat: int | None = None
    mulligan_bottom_required: int = 0
    mulligan_bottom_selected: list[int] = field(default_factory=list)


class SessionStore:
    def __init__(self, cards_path: Path, deck_store: DeckStore | None = None):
        self.cards_path = cards_path
        self.deck_store = deck_store
        self._sessions: dict[str, Session] = {}

    def _build_seat_deck(
        self,
        deck_id: str | None,
        colors: int,
        seed: int,
        cards: list[dict] | None = None,
    ):
        # Inline cards (a personal/browser deck) win over a server-side id.
        if cards:
            return build_deck_from_entries(self.cards_path, cards, seed)
        if deck_id and self.deck_store is not None:
            deck = self.deck_store.get(deck_id)
            return build_deck_from_entries(self.cards_path, deck.get("cards", []), seed)
        deck, _ = build_random_deck(self.cards_path, colors, seed)
        return deck

    def create(self, request: CreateSessionRequest) -> Session:
        sid = secrets.token_urlsafe(8)

        seed = self._resolve_seed(request)

        guest_name = request.guest_name
        if request.mode in {"human_vs_ai", "ai_vs_ai"} and guest_name.strip() in {"", "Player 2"}:
            guest_name = "AI"

        seat_types = {0: "human", 1: "human"}
        joined_seats: set[int] = {0}
        if request.mode == "human_vs_ai":
            seat_types[1] = "ai"
            joined_seats.add(1)
        elif request.mode == "ai_vs_ai":
            seat_types[0] = "ai"
            seat_types[1] = "ai"
            joined_seats = {0, 1}

        use_pregame = request.enable_pregame and request.mode != "ai_vs_ai"

        # Networked human_vs_human: the joining player chooses their own name and
        # deck, so defer building the guest deck (and starting the game) until they
        # join.  Legacy/test clients (no pregame) keep the immediate-start behavior.
        awaiting_opponent = request.mode == "human_vs_human" and use_pregame

        host_deck_cards = _entries_to_dicts(request.host_deck_cards)
        guest_deck_cards = _entries_to_dicts(request.guest_deck_cards)

        host_deck = self._build_seat_deck(
            request.host_deck_id, request.host_colors, seed, host_deck_cards
        )
        if awaiting_opponent:
            guest_deck: list = []
        else:
            guest_deck = self._build_seat_deck(
                request.guest_deck_id, request.guest_colors, seed + 1, guest_deck_cards
            )

        p1 = PlayerState(name=request.host_name, library=host_deck)
        p2 = PlayerState(name=guest_name, library=guest_deck)

        game = Game(players=[p1, p2], enforce_mana_costs=True)

        session = Session(
            id=sid,
            mode=request.mode,
            host_name=request.host_name,
            guest_name=guest_name,
            game=game,
            current_turn=0,
            joined_seats=joined_seats,
            seat_types=seat_types,
            seed=seed,
            use_pregame=use_pregame,
            awaiting_opponent=awaiting_opponent,
            host_deck_id=request.host_deck_id,
            host_colors=request.host_colors,
            guest_deck_id=request.guest_deck_id,
            guest_colors=request.guest_colors,
            host_deck_cards=host_deck_cards,
            guest_deck_cards=guest_deck_cards,
        )

        if not awaiting_opponent:
            self._begin_pregame(session)

        self._sessions[sid] = session
        return session

    def _begin_pregame(self, session: Session) -> None:
        """Start the game once all decks are known (immediately, or once the
        networked opponent has joined)."""
        game = session.game
        seed = session.seed
        if session.use_pregame:
            chooser = session.regame_first_chooser
            if chooser is not None:
                # Rematch: the previous loser chooses who plays first — no flip.
                game.log.append(
                    f"{game.players[chooser].name} lost the last game and chooses who plays first"
                )
                session.pregame_phase = "coin_flip"
                session.coin_flip_winner = chooser
                session.coin_flip_is_loser_choice = True
            else:
                # Rule 103.1: flip coin and record the winner; hand dealing is deferred
                # until the winner chooses to go first or second.
                flip_rng = random.Random(seed + 2)
                coin_flip_winner = flip_rng.randrange(len(game.players))
                game.log.append(
                    f"Coin flip: {game.players[coin_flip_winner].name} wins the coin flip!"
                )
                session.pregame_phase = "coin_flip"
                session.coin_flip_winner = coin_flip_winner
                session.coin_flip_is_loser_choice = False
        else:
            # Skip interactive pregame (ai_vs_ai or legacy clients).
            starting_player = game.select_starting_player(rng=random.Random(seed + 2))
            game.deal_opening_hands(starting_player)
            for i in range(len(game.players)):
                game.keep_hand(i)
            session.current_turn = starting_player
            # Align the engine's active player and priority window with the chosen
            # starter. The Game constructor defaults both to seat 0, so without this
            # an AI-vs-AI game where seat 1 wins the flip deadlocks: current_turn is
            # 1 but priority sits with 0, so neither the AI step nor the UI advances.
            # (Legacy no-pregame human/test sessions keep seat 0 as the actor.)
            if session.mode == "ai_vs_ai":
                game.active_player_index = starting_player
                game.start_priority_window(starting_player)

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

    def join(
        self,
        session_id: str,
        guest_name: str,
        guest_deck_id: str | None = None,
        guest_colors: int = 2,
        guest_deck_cards: list[dict] | None = None,
    ) -> Session:
        session = self.get(session_id)
        if session.mode != "human_vs_human":
            return session

        guest_deck_cards = _entries_to_dicts(guest_deck_cards)
        already_joined = 1 in session.joined_seats
        session.joined_seats.add(1)
        session.guest_name = guest_name
        session.game.players[1].name = guest_name
        # Remember the guest's deck choice so a rematch can rebuild it.
        session.guest_deck_id = guest_deck_id
        session.guest_colors = guest_colors
        session.guest_deck_cards = guest_deck_cards

        # Networked flow: the guest's deck travels with the join request. Build it
        # now (deterministically off the host's seed) and start the game.
        if session.awaiting_opponent and not already_joined:
            session.game.players[1].library = self._build_seat_deck(
                guest_deck_id, guest_colors, session.seed + 1, guest_deck_cards
            )
            session.awaiting_opponent = False
            self._begin_pregame(session)

        return session

    def restart(self, session: Session, first_chooser: int | None = None) -> Session:
        """Rebuild a fresh game in the same session for a coordinated rematch.

        Keeps the same two players, seat assignments, and deck selections, but
        reshuffles both decks off a new seed and replays the pregame (mulligans).
        When ``first_chooser`` is given (the previous game's loser) that seat
        chooses who plays first instead of a coin flip. All per-game transient
        state on the session is reset.
        """
        seed = secrets.randbits(32)
        host_deck = self._build_seat_deck(
            session.host_deck_id, session.host_colors, seed, session.host_deck_cards
        )
        guest_deck = self._build_seat_deck(
            session.guest_deck_id, session.guest_colors, seed + 1, session.guest_deck_cards
        )
        p1 = PlayerState(name=session.host_name, library=host_deck)
        p2 = PlayerState(name=session.guest_name, library=guest_deck)
        session.game = Game(players=[p1, p2], enforce_mana_costs=True)
        session.seed = seed
        session.current_turn = 0
        session.status = "active"
        session.rematch_votes = set()
        session.cleanup_required_discards = 0
        session.cleanup_selected_indices = []
        session.untap_required_lands = 0
        session.untap_candidate_indices = []
        session.untap_selected_indices = []
        session.upkeep_pay_choices = []
        session.upkeep_resolved_choices = {}
        session.optional_trigger_choices = []
        session.optional_trigger_resolved = {}
        session.island_sanctuary_pending = False
        session.force_ai_attack_all = False
        session.history = GameHistory()
        session.pregame_phase = None
        session.coin_flip_winner = None
        session.pregame_starting_player = None
        session.regame_first_chooser = first_chooser
        session.coin_flip_is_loser_choice = False
        session.mulligan_offer_seat = None
        session.mulligan_kept_seats = set()
        session.mulligan_bottom_seat = None
        session.mulligan_bottom_required = 0
        session.mulligan_bottom_selected = []
        self._begin_pregame(session)
        return session


def _entries_to_dicts(entries) -> list[dict] | None:
    """Normalize inline deck cards (DeckCardEntry models or dicts) to plain
    [{"name", "count"}] dicts, or None when no inline deck was supplied."""
    if not entries:
        return None
    out: list[dict] = []
    for entry in entries:
        if hasattr(entry, "model_dump"):
            entry = entry.model_dump()
        out.append({"name": entry["name"], "count": entry["count"]})
    return out
