from __future__ import annotations

from dataclasses import dataclass, field
import random
import secrets

from engine import Game, PlayerState
from engine.game_history import GameHistory
from engine.models import CardDefinition

from .deck_builder import build_deck_from_entries, build_random_deck
from .deck_store import DeckStore, deck_sideboard
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
    # Networked lobby (human_vs_human, or free_for_all with an open non-host human
    # seat): False while waiting for every human seat to join AND for a joined
    # player to explicitly start the game. True immediately for modes/configs that
    # have nothing to wait for (human_vs_ai, ai_vs_ai, legacy no-pregame clients,
    # FFA where every non-host seat is AI).
    game_started: bool = True
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
    # Those decks' inline sideboards ("outside the game", CR 100.4), kept for the
    # same reason.
    host_deck_sideboard: list[dict] | None = None
    guest_deck_sideboard: list[dict] | None = None
    # Display names for the lobby roster (see SeatConfig.deck_name); the server
    # has no other way to know a personal deck's name.
    host_deck_name: str | None = None
    guest_deck_name: str | None = None
    # Coordinated rematch (human_vs_human): seats that have requested a rematch on the
    # finished game. When every joined human seat has voted, the game is rebuilt.
    rematch_votes: set[int] = field(default_factory=set)
    cleanup_required_discards: int = 0
    cleanup_selected_indices: list[int] = field(default_factory=list)
    untap_required_lands: int = 0
    untap_candidate_indices: list[int] = field(default_factory=list)
    untap_selected_indices: list[int] = field(default_factory=list)
    # Old Man of the Sea: tapped permanents whose controller may choose not to
    # untap them this turn ({"index", "name"} each). Set at the start of a human
    # turn; answered by the optional_untap_confirm action (keep-tapped indices).
    optional_untap_pending: list[dict] = field(default_factory=list)
    upkeep_pay_choices: list[dict] = field(default_factory=list)
    upkeep_resolved_choices: dict[str, bool] = field(default_factory=dict)
    # Optional ("you may") upkeep triggers awaiting a yes/no decision (e.g. Nether
    # Shadow returning from the graveyard), and the answers collected so far.
    optional_trigger_choices: list[dict] = field(default_factory=list)
    optional_trigger_resolved: dict[str, bool] = field(default_factory=dict)
    # Target chosen alongside an accepted optional trigger (Vesuvan Doppelganger's
    # upkeep re-copy): card name -> (seat, battlefield index).
    optional_trigger_targets: dict[str, tuple[int, int]] = field(default_factory=dict)
    # "Pay any amount of mana to prevent that much damage" upkeep triggers (Power
    # Leak). Each choice carries the card name and the max preventable damage; the
    # player's chosen amount per card is collected in the resolved map.
    upkeep_mana_prevention_choices: list[dict] = field(default_factory=list)
    upkeep_mana_prevention_resolved: dict[str, int] = field(default_factory=dict)
    island_sanctuary_pending: bool = False
    # Lord of the Pit: a mandatory upkeep sacrifice pauses the beginning phase for
    # the human to choose which creature. This records (marker, player_index) so
    # the post-sacrifice resume (draw step + main phase) can finish the phase once
    # the choice is confirmed. None when no such pause is outstanding.
    pending_post_sacrifice: tuple[str, int] | None = None
    # Time Vault: the begin-of-turn "skip your turn to untap" decision. Holds the
    # permanent names offering the skip while the human decides; cleared once they
    # skip or decline. `time_vault_resolved_turn` records the turn already decided
    # so the prompt isn't re-shown after a decline.
    time_vault_pending: list[str] = field(default_factory=list)
    time_vault_resolved_turn: int | None = None
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
    # Host setting: every player decides keep/mulligan at once instead of in
    # turn order. mulligan_offer_seat is unused; per-seat bottom selections run
    # concurrently in the dicts below (seat -> required count / selected hand
    # indices) while other seats may still be deciding.
    simultaneous_mulligan: bool = False
    mulligan_bottom_required_by_seat: dict[int, int] = field(default_factory=dict)
    mulligan_bottom_selected_by_seat: dict[int, list[int]] = field(default_factory=dict)
    # Free-For-All only (mode == "free_for_all"): per-seat config, one entry per
    # seat, kept (like host_deck_id/host_colors/etc. for the 2-player modes) so a
    # rematch can rebuild fresh (reshuffled) decks for the same seats. Empty for
    # every other mode.
    seat_names: list[str] = field(default_factory=list)
    seat_is_ai: list[bool] = field(default_factory=list)
    seat_deck_ids: list[str | None] = field(default_factory=list)
    seat_colors: list[int] = field(default_factory=list)
    seat_deck_cards_list: list[list[dict] | None] = field(default_factory=list)
    seat_deck_sideboards: list[list[dict] | None] = field(default_factory=list)
    seat_deck_names: list[str | None] = field(default_factory=list)


class SessionStore:
    def __init__(self, catalog: list[CardDefinition], deck_store: DeckStore | None = None):
        self.catalog = catalog
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
            return build_deck_from_entries(self.catalog, cards, seed)
        if deck_id and self.deck_store is not None:
            deck = self.deck_store.get(deck_id)
            return build_deck_from_entries(self.catalog, deck.get("cards", []), seed)
        deck, _ = build_random_deck(self.catalog, colors, seed)
        return deck

    def _build_seat_sideboard(
        self,
        deck_id: str | None,
        cards: list[dict] | None = None,
        sideboard: list[dict] | None = None,
    ):
        """The seat's "outside the game" cards (CR 100.4). Unshuffled — a
        sideboard has no order, and the player sees all of it when choosing.
        Mirrors _build_seat_deck's precedence: inline entries (personal deck)
        first, then the saved deck's; a random deck has no sideboard."""
        entries = sideboard if sideboard else None
        if entries is None and not cards and deck_id and self.deck_store is not None:
            entries = deck_sideboard(self.deck_store.get(deck_id))
        if not entries:
            return []
        return build_deck_from_entries(self.catalog, entries, seed=None)

    def create(self, request: CreateSessionRequest) -> Session:
        if request.mode == "free_for_all":
            return self._create_ffa(request)

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
        # join and a player explicitly starts it. Legacy/test clients (no pregame)
        # keep the immediate-start behavior.
        lobby_needed = request.mode == "human_vs_human" and use_pregame

        host_deck_cards = _entries_to_dicts(request.host_deck_cards)
        guest_deck_cards = _entries_to_dicts(request.guest_deck_cards)
        host_deck_sideboard = _entries_to_dicts(request.host_deck_sideboard)
        guest_deck_sideboard = _entries_to_dicts(request.guest_deck_sideboard)

        host_deck = self._build_seat_deck(
            request.host_deck_id, request.host_colors, seed, host_deck_cards
        )
        host_side = self._build_seat_sideboard(
            request.host_deck_id, host_deck_cards, host_deck_sideboard
        )
        if lobby_needed:
            guest_deck: list = []
            guest_side: list = []
        else:
            guest_deck = self._build_seat_deck(
                request.guest_deck_id, request.guest_colors, seed + 1, guest_deck_cards
            )
            guest_side = self._build_seat_sideboard(
                request.guest_deck_id, guest_deck_cards, guest_deck_sideboard
            )

        p1 = PlayerState(name=request.host_name, library=host_deck, sideboard=host_side)
        p2 = PlayerState(name=guest_name, library=guest_deck, sideboard=guest_side)

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
            simultaneous_mulligan=use_pregame and request.simultaneous_mulligan,
            game_started=not lobby_needed,
            host_deck_id=request.host_deck_id,
            host_colors=request.host_colors,
            guest_deck_id=request.guest_deck_id,
            guest_colors=request.guest_colors,
            host_deck_cards=host_deck_cards,
            guest_deck_cards=guest_deck_cards,
            host_deck_sideboard=host_deck_sideboard,
            guest_deck_sideboard=guest_deck_sideboard,
            host_deck_name=request.host_deck_name,
            guest_deck_name=None if lobby_needed else request.guest_deck_name,
        )

        if not lobby_needed:
            self._begin_pregame(session)

        self._sessions[sid] = session
        return session

    def _create_ffa(self, request: CreateSessionRequest) -> Session:
        """Free-For-All (3-4 players): one PlayerState per seat, each seat
        independently Human or AI with its own deck. Seat 0 (the host) and every
        AI seat are configured up front and are at the table immediately; a
        non-host Human seat is left open for a networked join (unless pregame is
        disabled, matching the legacy pass-and-play behavior where the host
        configures every seat's name/deck up front)."""
        seats = request.seats or []
        if not (3 <= len(seats) <= 4):
            raise ValueError("Free-For-All sessions need 3 or 4 seats")

        sid = secrets.token_urlsafe(8)
        seed = self._resolve_seed(request)

        seat_names = [seat.name or f"Player {i + 1}" for i, seat in enumerate(seats)]
        seat_is_ai = [seat.is_ai for seat in seats]
        seat_deck_ids = [seat.deck_id for seat in seats]
        seat_colors = [seat.colors for seat in seats]
        seat_deck_cards_list = [_entries_to_dicts(seat.deck_cards) for seat in seats]
        seat_deck_sideboards = [_entries_to_dicts(seat.deck_sideboard) for seat in seats]
        seat_deck_names = [seat.deck_name for seat in seats]

        use_pregame = request.enable_pregame
        open_seats = {i for i in range(len(seats)) if i != 0 and not seat_is_ai[i]}
        lobby_needed = use_pregame and bool(open_seats)

        players = []
        for i in range(len(seats)):
            if i in open_seats and lobby_needed:
                players.append(PlayerState(name=seat_names[i], library=[]))
            else:
                players.append(
                    PlayerState(
                        name=seat_names[i],
                        library=self._build_seat_deck(
                            seat_deck_ids[i], seat_colors[i], seed + i, seat_deck_cards_list[i]
                        ),
                        sideboard=self._build_seat_sideboard(
                            seat_deck_ids[i], seat_deck_cards_list[i], seat_deck_sideboards[i]
                        ),
                    )
                )
        game = Game(players=players, enforce_mana_costs=True)

        seat_types = {i: ("ai" if seat_is_ai[i] else "human") for i in range(len(seats))}
        joined_seats = set(range(len(seats)))
        if lobby_needed:
            joined_seats -= open_seats

        session = Session(
            id=sid,
            mode="free_for_all",
            host_name=seat_names[0],
            guest_name=seat_names[1] if len(seat_names) > 1 else "",
            game=game,
            current_turn=0,
            joined_seats=joined_seats,
            seat_types=seat_types,
            seed=seed,
            use_pregame=use_pregame,
            simultaneous_mulligan=use_pregame and request.simultaneous_mulligan,
            game_started=not lobby_needed,
            seat_names=seat_names,
            seat_is_ai=seat_is_ai,
            seat_deck_ids=seat_deck_ids,
            seat_colors=seat_colors,
            seat_deck_cards_list=seat_deck_cards_list,
            seat_deck_sideboards=seat_deck_sideboards,
            seat_deck_names=seat_deck_names,
        )

        if not lobby_needed:
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
            # (Legacy no-pregame human/test sessions keep seat 0 as the actor.) FFA
            # can equally start on an AI seat (or a non-zero human seat), so it needs
            # the same alignment.
            if session.mode in ("ai_vs_ai", "free_for_all"):
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

    def open_human_seats(self, session: Session) -> list[int]:
        """Human seats that haven't joined yet — the lobby's open slots."""
        return sorted(
            i for i, t in session.seat_types.items()
            if t == "human" and i not in session.joined_seats
        )

    def join(
        self,
        session_id: str,
        guest_name: str,
        guest_deck_id: str | None = None,
        guest_colors: int = 2,
        guest_deck_cards: list[dict] | None = None,
        guest_deck_name: str | None = None,
        guest_deck_sideboard: list[dict] | None = None,
    ) -> tuple[Session, int]:
        session = self.get(session_id)
        open_seats = self.open_human_seats(session)
        if not open_seats:
            raise ValueError("no open seat to join")
        target = open_seats[0]

        guest_deck_cards = _entries_to_dicts(guest_deck_cards)
        guest_deck_sideboard = _entries_to_dicts(guest_deck_sideboard)
        session.joined_seats.add(target)
        session.game.players[target].name = guest_name
        if session.mode == "free_for_all":
            session.seat_names[target] = guest_name
            session.seat_deck_ids[target] = guest_deck_id
            session.seat_colors[target] = guest_colors
            session.seat_deck_cards_list[target] = guest_deck_cards
            session.seat_deck_sideboards[target] = guest_deck_sideboard
            session.seat_deck_names[target] = guest_deck_name
        else:
            session.guest_name = guest_name
            session.guest_deck_id = guest_deck_id
            session.guest_colors = guest_colors
            session.guest_deck_cards = guest_deck_cards
            session.guest_deck_sideboard = guest_deck_sideboard
            session.guest_deck_name = guest_deck_name

        # Only rebuild the library while the lobby is still open. In the legacy
        # (no-lobby) path the deck was already built — and possibly dealt from —
        # at creation time, so overwriting it here would clobber live game state.
        if not session.game_started:
            session.game.players[target].library = self._build_seat_deck(
                guest_deck_id, guest_colors, session.seed + target, guest_deck_cards
            )
            session.game.players[target].sideboard = self._build_seat_sideboard(
                guest_deck_id, guest_deck_cards, guest_deck_sideboard
            )

        return session, target

    def start(self, session: Session, seat: int) -> Session:
        """Explicitly start a game once every human seat has joined. Any joined
        seat may call this; it's idempotent so two players clicking Start at
        once is harmless."""
        if seat not in session.joined_seats:
            raise ValueError("seat has not joined this session")
        if self.open_human_seats(session):
            raise ValueError("not all players have joined yet")
        if not session.game_started:
            session.game_started = True
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
        if session.mode == "free_for_all":
            players = [
                PlayerState(
                    name=session.seat_names[i],
                    library=self._build_seat_deck(
                        session.seat_deck_ids[i], session.seat_colors[i], seed + i,
                        session.seat_deck_cards_list[i],
                    ),
                    sideboard=self._build_seat_sideboard(
                        session.seat_deck_ids[i], session.seat_deck_cards_list[i],
                        session.seat_deck_sideboards[i],
                    ),
                )
                for i in range(len(session.seat_names))
            ]
            session.game = Game(players=players, enforce_mana_costs=True)
        else:
            host_deck = self._build_seat_deck(
                session.host_deck_id, session.host_colors, seed, session.host_deck_cards
            )
            guest_deck = self._build_seat_deck(
                session.guest_deck_id, session.guest_colors, seed + 1, session.guest_deck_cards
            )
            p1 = PlayerState(
                name=session.host_name,
                library=host_deck,
                sideboard=self._build_seat_sideboard(
                    session.host_deck_id, session.host_deck_cards, session.host_deck_sideboard
                ),
            )
            p2 = PlayerState(
                name=session.guest_name,
                library=guest_deck,
                sideboard=self._build_seat_sideboard(
                    session.guest_deck_id, session.guest_deck_cards, session.guest_deck_sideboard
                ),
            )
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
        session.optional_trigger_targets = {}
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
        # simultaneous_mulligan itself is a host setting and survives restarts;
        # only the per-seat progress resets.
        session.mulligan_bottom_required_by_seat = {}
        session.mulligan_bottom_selected_by_seat = {}
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
