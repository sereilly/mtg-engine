from __future__ import annotations

import socket
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles

from engine import Game
from engine.ai_policy import (
    choose_activation_action,
    choose_cast_action,
    choose_combat_blockers,
    choose_combat_instant_cast_action,
)
from engine.card_loader import load_cards
from engine.models import Permanent, PlayerState

from .deck_builder import build_random_deck
from .schemas import CreateSessionRequest, GameActionRequest, JoinSessionRequest, RandomDeckRequest
from .session_store import Session, SessionStore


ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "lea_cards.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"
CARD_CATALOG = load_cards(CARDS_PATH)
CARD_BY_NAME = {card.name.casefold(): card for card in CARD_CATALOG}
CARD_SEARCH_ORDER = sorted(CARD_CATALOG, key=lambda card: card.name)

app = FastAPI(title="Magic LEA Web App")
store = SessionStore(cards_path=CARDS_PATH)


@app.middleware("http")
async def _no_cache_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/index.html", "/app.js", "/styles.css"} or request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


def _serialize_permanent(perm: Permanent) -> dict:
    image_uris = perm.card.raw.get("image_uris") if isinstance(perm.card.raw, dict) else None
    image_uri = image_uris.get("normal") if isinstance(image_uris, dict) else None
    large_image_uri = image_uris.get("large") if isinstance(image_uris, dict) else None
    return {
        "name": perm.card.name,
        "type": perm.card.type_line,
        "tapped": perm.tapped,
        "power": perm.effective_power,
        "toughness": perm.effective_toughness,
        "mana_cost": perm.card.mana_cost,
        "oracle_text": perm.card.oracle_text,
        "image_uri": image_uri,
        "large_image_uri": large_image_uri,
        "attacking": perm.attacking,
        "defending_player_index": perm.defending_player_index,
        "blocked": perm.blocked,
        "blocking_attacker_controller": perm.blocking_attacker_controller,
        "blocking_attacker_index": perm.blocking_attacker_index,
        "damage_marked": perm.damage_marked,
    }


def _serialize_card(card) -> dict:
    image_uris = card.raw.get("image_uris") if isinstance(card.raw, dict) else None
    image_uri = image_uris.get("normal") if isinstance(image_uris, dict) else None
    large_image_uri = image_uris.get("large") if isinstance(image_uris, dict) else None
    return {
        "name": card.name,
        "type": card.type_line,
        "mana_cost": card.mana_cost,
        "oracle_text": card.oracle_text,
        "image_uri": image_uri,
        "large_image_uri": large_image_uri,
    }


def _serialize_card_summary(card) -> dict:
    image_uris = card.raw.get("image_uris") if isinstance(card.raw, dict) else None
    image_uri = image_uris.get("normal") if isinstance(image_uris, dict) else None
    return {
        "name": card.name,
        "type": card.type_line,
        "mana_cost": card.mana_cost,
        "oracle_text": card.oracle_text,
        "image_uri": image_uri,
    }


def _search_cards(query: str, limit: int) -> list[dict]:
    term = query.strip().casefold()
    if not term:
        return [_serialize_card_summary(card) for card in CARD_SEARCH_ORDER[:limit]]

    starts_with: list = []
    contains: list = []
    for card in CARD_SEARCH_ORDER:
        lowered = card.name.casefold()
        if lowered.startswith(term):
            starts_with.append(card)
        elif term in lowered:
            contains.append(card)

    ranked = starts_with + contains
    return [_serialize_card_summary(card) for card in ranked[:limit]]


def _serialize_mana_pool(player: PlayerState) -> dict:
    mana = dict(player.mana_pool)
    for symbol in ("W", "U", "B", "R", "G", "C"):
        mana.setdefault(symbol, 0)
    return mana


def _serialize_stack_item(item, game: Game) -> dict:
    target_name = None
    if item.target_player_index is not None and 0 <= item.target_player_index < len(game.players):
        target_name = game.players[item.target_player_index].name
    return {
        "card": _serialize_card(item.card),
        "caster_index": item.caster_index,
        "caster_name": game.players[item.caster_index].name,
        "target_player_index": item.target_player_index,
        "target_player_name": target_name,
        "x_value": item.x_value,
    }


def _serialize_player(player: PlayerState, viewer_seat: int | None, seat: int) -> dict:
    if viewer_seat == seat:
        hand = [_serialize_card(card) for card in player.hand]
    else:
        hand = ["<hidden>"] * len(player.hand)

    return {
        "name": player.name,
        "life": player.life,
        "hand": hand,
        "hand_count": len(player.hand),
        "deck": {"count": len(player.library)},
        "library_count": len(player.library),
        "graveyard": [_serialize_card(card) for card in player.graveyard],
        "exile": [_serialize_card(card) for card in player.exile],
        "battlefield": [_serialize_permanent(perm) for perm in player.battlefield],
        "mana_pool": _serialize_mana_pool(player),
    }


def _winner(session: Session) -> int | None:
    life0 = session.game.players[0].life
    life1 = session.game.players[1].life
    if life0 <= 0 and life1 <= 0:
        return -1
    if life0 <= 0:
        return 1
    if life1 <= 0:
        return 0
    return None


def _cleanup_discard_requirement(session: Session) -> int:
    if session.game.current_phase != "cleanup":
        return 0
    active = session.game.players[session.current_turn]
    if active.has_no_max_hand_size:
        return 0
    return max(0, len(active.hand) - 7)


def _clear_cleanup_selection(session: Session) -> None:
    session.cleanup_required_discards = 0
    session.cleanup_selected_indices = []


def _clear_untap_selection(session: Session) -> None:
    session.untap_required_lands = 0
    session.untap_candidate_indices = []
    session.untap_selected_indices = []


def _untap_land_selection_requirement(session: Session) -> int:
    if session.game.current_step != "untap":
        return 0
    if session.current_turn < 0 or session.current_turn >= len(session.game.players):
        return 0
    options = session.game.get_untap_land_selection_options(session.current_turn)
    if not options:
        return 0
    max_count = int(options.get("max_count", 0))
    return max(0, max_count)


def _begin_turn(session: Session, player_index: int, defer_untap_selection: bool) -> bool:
    game = session.game
    game.active_player_index = player_index
    game.lands_played_this_turn[player_index] = 0

    if defer_untap_selection:
        options = game.get_untap_land_selection_options(player_index)
        if options:
            game._set_phase_and_step("beginning", "untap")
            session.untap_required_lands = int(options["max_count"])
            session.untap_candidate_indices = [int(idx) for idx in options["candidate_indices"]]
            session.untap_selected_indices = []
            return False

    _clear_untap_selection(session)
    game.resolve_untap_step(player_index)
    game.resolve_upkeep(player_index)
    game.resolve_draw_step(player_index)
    game._enter_main_phase(precombat=True)
    return True


def _start_next_turn(session: Session) -> None:
    _clear_cleanup_selection(session)
    _clear_untap_selection(session)
    session.game.active_player_index = session.current_turn
    session.game.turn += 1
    session.current_turn = session.game._compute_next_active_player()
    should_defer_untap = _seat_type(session, session.current_turn) == "human"
    _begin_turn(session, session.current_turn, defer_untap_selection=should_defer_untap)


def _seat_type(session: Session, seat: int) -> str:
    return session.seat_types.get(seat) or session.seat_types.get(str(seat), "human")


def _serialize_state(session: Session, viewer_seat: int | None) -> dict:
    win = _winner(session)
    if win is not None:
        session.status = "finished"

    cleanup_info = None
    cleanup_required = _cleanup_discard_requirement(session)
    untap_required = _untap_land_selection_requirement(session)
    if viewer_seat == session.current_turn and cleanup_required > 0:
        valid_indices = [
            idx
            for idx in sorted(set(session.cleanup_selected_indices))
            if 0 <= idx < len(session.game.players[viewer_seat].hand)
        ]
        session.cleanup_selected_indices = valid_indices
        session.cleanup_required_discards = cleanup_required
        cleanup_info = {
            "required_count": cleanup_required,
            "selected_indices": valid_indices,
            "selected_count": len(valid_indices),
        }
    else:
        _clear_cleanup_selection(session)

    untap_info = None
    untap_required = _untap_land_selection_requirement(session)
    if viewer_seat == session.current_turn and untap_required > 0:
        valid_candidates = [
            idx
            for idx in sorted(set(session.untap_candidate_indices))
            if 0 <= idx < len(session.game.players[viewer_seat].battlefield)
            and session.game.players[viewer_seat].battlefield[idx].card.primary_type == "land"
            and session.game.players[viewer_seat].battlefield[idx].tapped
        ]
        session.untap_candidate_indices = valid_candidates

        valid_selected = [idx for idx in sorted(set(session.untap_selected_indices)) if idx in set(valid_candidates)]
        if len(valid_selected) > untap_required:
            valid_selected = valid_selected[:untap_required]
        session.untap_selected_indices = valid_selected
        session.untap_required_lands = untap_required
        untap_info = {
            "max_count": untap_required,
            "candidate_indices": valid_candidates,
            "selected_indices": valid_selected,
            "selected_count": len(valid_selected),
        }

    return {
        "session_id": session.id,
        "mode": session.mode,
        "status": session.status,
        "current_phase": session.game.current_phase,
        "current_turn_phase": session.game.current_turn_phase,
        "current_step": session.game.current_step,
        "current_turn": session.current_turn,
        "turn_number": session.game.turn,
        "joined_seats": sorted(session.joined_seats),
        "seat_types": session.seat_types,
        "players": [
            _serialize_player(session.game.players[0], viewer_seat, 0),
            _serialize_player(session.game.players[1], viewer_seat, 1),
        ],
        "stack": [_serialize_stack_item(item, session.game) for item in reversed(session.game.stack)],
        "combat": session.game.get_combat_state(),
        "log": session.game.log[-80:],
        "winner": win,
        "cleanup_discard": cleanup_info,
        "untap_land_selection": untap_info,
    }


def _default_target(card_name: str, caster_index: int) -> int:
    if card_name in {"Ancestral Recall", "Healing Salve", "Stream of Life"}:
        return caster_index
    return 1 - caster_index


def _find_card_in_hand(player: PlayerState, card_name: str):
    return next((card for card in player.hand if card.name == card_name), None)


def _find_controlled_permanent(
    player: PlayerState,
    permanent_name: str | None,
    permanent_index: int | None,
) -> tuple[int, Permanent] | None:
    if permanent_index is not None:
        if permanent_index < 0 or permanent_index >= len(player.battlefield):
            return None
        permanent = player.battlefield[permanent_index]
        if permanent_name and permanent.card.name != permanent_name:
            return None
        return permanent_index, permanent

    if permanent_name is None:
        return None

    for idx, permanent in enumerate(player.battlefield):
        if permanent.card.name == permanent_name:
            return idx, permanent
    return None


def _detect_local_ip() -> str:
    # Prefer the routed interface address so other devices on LAN can reach us.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass

    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip:
            return ip
    except OSError:
        pass

    return "127.0.0.1"


def _build_join_url(request: Request, session_id: str) -> str:
    base_url = request.base_url
    if request.url.hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
        local_ip = _detect_local_ip()
        if local_ip and local_ip != "127.0.0.1":
            base_url = base_url.replace(hostname=local_ip)

    return f"{str(base_url).rstrip('/')}/index.html?session={session_id}"


def _ai_step(session: Session) -> None:
    seat = session.current_turn

    cast_action = choose_cast_action(session.game, seat)
    if cast_action is not None:
        card_to_cast = session.game.players[seat].hand[cast_action.hand_index]
        for permanent_index in cast_action.land_tap_indices:
            permanent = session.game.players[seat].battlefield[permanent_index]
            session.game.tap_land_for_mana(seat, permanent.card.name, permanent_index=permanent_index)
        session.game.cast_from_hand(
            seat,
            card_to_cast.name,
            target_player_index=cast_action.target_player_index,
            x_value=cast_action.x_value,
        )

    activation_action = choose_activation_action(session.game, seat)
    if activation_action is not None:
        for permanent_index in activation_action.land_tap_indices:
            permanent = session.game.players[seat].battlefield[permanent_index]
            session.game.tap_land_for_mana(seat, permanent.card.name, permanent_index=permanent_index)
        session.game.activate_permanent_ability(
            seat,
            activation_action.permanent_name,
            target_player_index=activation_action.target_player_index,
            permanent_index=activation_action.permanent_index,
        )


def _end_turn(session: Session, allow_manual_cleanup_selection: bool = False) -> bool:
    if session.game.current_turn_phase in {"precombat_main", "postcombat_main"}:
        session.game._close_current_priority_step()
    if session.game.current_turn_phase == "combat":
        session.game.end_combat()
    if session.game.current_step != "end":
        session.game.resolve_end_step(session.current_turn)
    should_defer_cleanup = allow_manual_cleanup_selection and _seat_type(session, session.current_turn) == "human"
    cleanup_completed = session.game.resolve_cleanup_step(
        session.current_turn,
        defer_discard_selection=should_defer_cleanup,
    )
    if not cleanup_completed:
        session.cleanup_required_discards = _cleanup_discard_requirement(session)
        session.cleanup_selected_indices = []
        return False
    _start_next_turn(session)
    return True


def _advance_phase(session: Session) -> None:
    game = session.game
    phase = game.current_turn_phase
    step = game.current_step

    if phase == "precombat_main":
        game._close_current_priority_step()
        game.advance_combat_phase()
        _clear_cleanup_selection(session)
        return
    if phase == "combat":
        if step == "declare_blockers":
            combat_state = game.get_combat_state()
            defender_index = combat_state.get("defending_player_index")
            if isinstance(defender_index, int) and _seat_type(session, defender_index) == "ai":
                if not combat_state.get("blockers_locked", False):
                    blocker_pairs = choose_combat_blockers(game, defender_index)
                    ok, _ = game.declare_blockers(defender_index, blocker_pairs)
                    if not ok and blocker_pairs:
                        ok, _ = game.declare_blockers(defender_index, {})
                    if not ok:
                        # Safety valve: never let AI declaration failures deadlock combat progression.
                        game.combat_blockers = {}
                        game.combat_blockers_locked = True
                        game._prune_combat_state()
                    instant_action = choose_combat_instant_cast_action(game, defender_index)
                    if instant_action is not None:
                        card_to_cast = game.players[defender_index].hand[instant_action.hand_index]
                        for permanent_index in instant_action.land_tap_indices:
                            permanent = game.players[defender_index].battlefield[permanent_index]
                            game.tap_land_for_mana(defender_index, permanent.card.name, permanent_index=permanent_index)
                        game.cast_from_hand(
                            defender_index,
                            card_to_cast.name,
                            target_player_index=instant_action.target_player_index,
                            x_value=instant_action.x_value,
                        )
                        return
        game.advance_combat_phase()
        return
    if phase == "postcombat_main":
        game._close_current_priority_step()
        game.resolve_end_step(session.current_turn)
        _clear_cleanup_selection(session)
        return
    if step == "end":
        should_defer_cleanup = _seat_type(session, session.current_turn) == "human"
        cleanup_completed = game.resolve_cleanup_step(
            session.current_turn,
            defer_discard_selection=should_defer_cleanup,
        )
        if not cleanup_completed:
            session.cleanup_required_discards = _cleanup_discard_requirement(session)
            session.cleanup_selected_indices = []
            return
        _start_next_turn(session)
        return
    if step == "cleanup":
        if _cleanup_discard_requirement(session) > 0:
            raise HTTPException(status_code=400, detail="select cleanup discards before advancing")
        _start_next_turn(session)
        return


def _require_session(session_id: str) -> Session:
    try:
        return store.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


@app.post("/api/decks/random")
def random_deck(req: RandomDeckRequest):
    deck, colors = build_random_deck(CARDS_PATH, req.colors, req.seed)
    land_count = sum(1 for c in deck if c.primary_type == "land")
    return {
        "colors": colors,
        "deck": [c.name for c in deck],
        "count": len(deck),
        "land_count": land_count,
    }


@app.post("/api/sessions")
def create_session(req: CreateSessionRequest, request: Request):
    session = store.create(req)
    join_url = _build_join_url(request, session.id)
    return {
        "session_id": session.id,
        "join_url": join_url,
        "seat": 0,
        "state": _serialize_state(session, viewer_seat=0),
    }


@app.post("/api/sessions/{session_id}/join")
def join_session(session_id: str, req: JoinSessionRequest, request: Request):
    session = _require_session(session_id)
    session = store.join(session_id, req.guest_name)
    return {
        "session_id": session.id,
        "join_url": _build_join_url(request, session.id),
        "seat": 1,
        "state": _serialize_state(session, viewer_seat=1),
    }


@app.get("/api/sessions/{session_id}/state")
def get_state(session_id: str, seat: int | None = Query(default=None, ge=0, le=1)):
    session = _require_session(session_id)
    return _serialize_state(session, viewer_seat=seat)


@app.get("/api/cards/search")
def search_cards(query: str = Query(default=""), limit: int = Query(default=16, ge=1, le=50)):
    return {"cards": _search_cards(query, limit)}


@app.post("/api/sessions/{session_id}/action")
def do_action(session_id: str, req: GameActionRequest):
    session = _require_session(session_id)
    if session.status == "finished":
        raise HTTPException(status_code=400, detail="game already finished")

    if req.seat not in session.joined_seats:
        raise HTTPException(status_code=400, detail="seat has not joined")

    seat_type = _seat_type(session, req.seat)

    cleanup_required = _cleanup_discard_requirement(session)
    untap_required = _untap_land_selection_requirement(session)
    if (
        cleanup_required > 0
        and req.action == "cast"
        and req.seat == session.current_turn
        and session.game.current_phase == "cleanup"
        and req.card_name
    ):
        active_hand = session.game.players[session.current_turn].hand
        selected = set(session.cleanup_selected_indices)
        matching_indices = [idx for idx, card in enumerate(active_hand) if card.name == req.card_name]
        preferred_index = next((idx for idx in matching_indices if idx not in selected), None)
        if preferred_index is None and matching_indices:
            preferred_index = matching_indices[0]
        if preferred_index is not None:
            req = req.model_copy(update={"action": "cleanup_select", "hand_index": preferred_index})

    if cleanup_required > 0 and req.action not in {"cleanup_select", "debug_add_to_hand", "debug_cast_free"}:
        raise HTTPException(status_code=400, detail="select cleanup discards before other actions")

    if untap_required > 0 and req.action not in {"untap_select", "untap_confirm", "debug_add_to_hand", "debug_cast_free"}:
        raise HTTPException(status_code=400, detail="select untap lands before other actions")

    if req.action in {
        "cast",
        "activate",
        "end_turn",
        "next_phase",
        "declare_attackers",
        "declare_blockers",
        "assign_combat_damage",
        "untap_select",
        "untap_confirm",
    } and seat_type != "human":
        raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")

    if req.action == "cast":
        if not req.card_name:
            raise HTTPException(status_code=400, detail="card_name is required")

        caster = session.game.players[req.seat]
        card = _find_card_in_hand(caster, req.card_name)
        if card is None:
            raise HTTPException(status_code=400, detail="card not in hand")

        is_instant = card.primary_type == "instant"
        if req.seat != session.current_turn and not is_instant:
            raise HTTPException(status_code=400, detail="non-instant spells can only be cast on your turn")

        if card.primary_type in {"land", "sorcery", "creature", "artifact", "enchantment"}:
            if req.seat != session.current_turn:
                raise HTTPException(status_code=400, detail="can only cast this card on your turn")
            if session.game.current_phase != "main":
                raise HTTPException(status_code=400, detail="can only cast this card during main phase")
            if session.game.stack:
                raise HTTPException(status_code=400, detail="can only cast this card when stack is empty")

        target = req.target_seat if req.target_seat is not None else _default_target(req.card_name, req.seat)
        result = session.game.cast_from_hand(
            req.seat,
            req.card_name,
            target_player_index=target,
            target_permanent_index=req.permanent_index,
            x_value=req.x_value,
        )
        if not result.supported:
            raise HTTPException(status_code=400, detail=result.details)

    elif req.action == "tap":
        if req.permanent_name is None and req.permanent_index is None:
            raise HTTPException(status_code=400, detail="permanent_name or permanent_index is required")
        controller = session.game.players[req.seat]
        resolved = _find_controlled_permanent(controller, req.permanent_name, req.permanent_index)
        if resolved is None:
            raise HTTPException(status_code=400, detail="permanent not found")
        permanent_index, permanent = resolved

        if permanent.card.primary_type == "land":
            tapped = session.game.tap_land_for_mana(
                req.seat,
                permanent.card.name,
                permanent_index=permanent_index,
            )
        else:
            tapped = session.game.tap_permanent(
                req.seat,
                permanent.card.name,
                permanent_index=permanent_index,
            )
        if not tapped:
            raise HTTPException(status_code=400, detail="failed to tap permanent")

    elif req.action == "activate":
        if req.permanent_name is None and req.permanent_index is None:
            raise HTTPException(status_code=400, detail="permanent_name or permanent_index is required")
        controller = session.game.players[req.seat]
        resolved = _find_controlled_permanent(controller, req.permanent_name, req.permanent_index)
        if resolved is None:
            raise HTTPException(status_code=400, detail="permanent not found")
        permanent_index, permanent = resolved

        if permanent.card.primary_type == "land":
            tapped = session.game.tap_land_for_mana(
                req.seat,
                permanent.card.name,
                permanent_index=permanent_index,
            )
            if not tapped:
                raise HTTPException(status_code=400, detail="failed to tap land for mana")
        else:
            target = req.target_seat if req.target_seat is not None else 1 - req.seat
            result = session.game.activate_permanent_ability(
                req.seat,
                permanent.card.name,
                target_player_index=target,
                permanent_index=permanent_index,
                mana_color=req.mana_color,
            )
            if not result.supported:
                raise HTTPException(status_code=400, detail=result.details)

    elif req.action == "end_turn":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        _end_turn(session, allow_manual_cleanup_selection=True)

    elif req.action == "next_phase":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        _advance_phase(session)

    elif req.action == "declare_attackers":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        ok, details = session.game.declare_attackers(
            req.seat,
            req.attacker_indices or [],
            defending_player_index=req.target_seat,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=details)

    elif req.action == "declare_blockers":
        defender_seat = session.game.combat_defending_player_index
        if defender_seat is None:
            raise HTTPException(status_code=400, detail="no combat attackers declared")
        if req.seat != defender_seat:
            raise HTTPException(status_code=400, detail="only defending player may declare blockers")
        raw_pairs = req.blocker_pairs or {}
        blocker_pairs = {int(k): int(v) for k, v in raw_pairs.items()}
        ok, details = session.game.declare_blockers(req.seat, blocker_pairs)
        if not ok:
            raise HTTPException(status_code=400, detail=details)

    elif req.action == "assign_combat_damage":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        attacker_damage_raw = req.attacker_damage or {}
        attacker_damage = {
            int(attacker_idx): {int(blocker_idx): int(value) for blocker_idx, value in blockers.items()}
            for attacker_idx, blockers in attacker_damage_raw.items()
        }
        ok, details = session.game.resolve_combat_damage(req.seat, attacker_damage=attacker_damage)
        if not ok:
            raise HTTPException(status_code=400, detail=details)

    elif req.action == "cleanup_select":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        if session.game.current_phase != "cleanup":
            raise HTTPException(status_code=400, detail="cleanup selection is only available during cleanup")
        if req.hand_index is None:
            raise HTTPException(status_code=400, detail="hand_index is required")

        active_hand = session.game.players[session.current_turn].hand
        if req.hand_index < 0 or req.hand_index >= len(active_hand):
            raise HTTPException(status_code=400, detail="hand_index out of range")

        required = _cleanup_discard_requirement(session)
        if required <= 0:
            raise HTTPException(status_code=400, detail="no cleanup discard is required")

        selected = sorted(set(session.cleanup_selected_indices))
        if req.hand_index in selected:
            selected = [idx for idx in selected if idx != req.hand_index]
        else:
            if len(selected) >= required:
                raise HTTPException(status_code=400, detail="already selected required cleanup discards")
            selected.append(req.hand_index)
            selected = sorted(set(selected))

        session.cleanup_selected_indices = selected
        session.cleanup_required_discards = required

        if len(selected) == required:
            session.game.resolve_cleanup_step(session.current_turn, discard_hand_indices=selected)
            _start_next_turn(session)

    elif req.action == "untap_select":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        if session.game.current_step != "untap":
            raise HTTPException(status_code=400, detail="untap selection is only available during untap")
        if req.permanent_index is None:
            raise HTTPException(status_code=400, detail="permanent_index is required")

        required = _untap_land_selection_requirement(session)
        if required <= 0:
            raise HTTPException(status_code=400, detail="no untap land selection is required")

        candidates = set(session.untap_candidate_indices)
        if req.permanent_index not in candidates:
            raise HTTPException(status_code=400, detail="permanent is not a valid untap land choice")

        selected = sorted(set(session.untap_selected_indices))
        if req.permanent_index in selected:
            selected = [idx for idx in selected if idx != req.permanent_index]
        else:
            if len(selected) >= required:
                raise HTTPException(status_code=400, detail="already selected maximum untap lands")
            selected.append(req.permanent_index)
            selected = sorted(set(selected))

        session.untap_selected_indices = selected
        session.untap_required_lands = required

    elif req.action == "untap_confirm":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        if session.game.current_step != "untap":
            raise HTTPException(status_code=400, detail="untap confirmation is only available during untap")

        required = _untap_land_selection_requirement(session)
        if required <= 0:
            raise HTTPException(status_code=400, detail="no untap land selection is required")

        selected = sorted(set(session.untap_selected_indices))
        if len(selected) > required:
            raise HTTPException(status_code=400, detail="selected too many lands to untap")

        try:
            session.game.resolve_untap_step(session.current_turn, selected_land_indices=selected)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        _clear_untap_selection(session)
        session.game.resolve_upkeep(session.current_turn)
        session.game.resolve_draw_step(session.current_turn)
        session.game._enter_main_phase(precombat=True)

    elif req.action == "ai_step":
        if _seat_type(session, session.current_turn) != "ai":
            raise HTTPException(status_code=400, detail="current turn is not AI")
        _ai_step(session)
        _end_turn(session)

    elif req.action == "debug_add_to_hand":
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue debug action for AI seat")
        if not req.card_name:
            raise HTTPException(status_code=400, detail="card_name is required")

        card = CARD_BY_NAME.get(req.card_name.strip().casefold())
        if card is None:
            raise HTTPException(status_code=404, detail="card not found")

        player = session.game.players[req.seat]
        player.hand.append(card)
        session.game.log.append(f"[Debug] {player.name} added {card.name} to hand.")

    elif req.action == "debug_cast_free":
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue debug action for AI seat")
        if not req.card_name:
            raise HTTPException(status_code=400, detail="card_name is required")

        card = CARD_BY_NAME.get(req.card_name.strip().casefold())
        if card is None:
            raise HTTPException(status_code=404, detail="card not found")

        player = session.game.players[req.seat]
        player.hand.append(card)
        target = req.target_seat if req.target_seat is not None else _default_target(card.name, req.seat)
        x_value = req.x_value if req.x_value is not None else (0 if "{X}" in (card.mana_cost or "") else None)

        original_enforce_mana_costs = session.game.enforce_mana_costs
        try:
            session.game.enforce_mana_costs = False
            result = session.game.cast_from_hand(
                req.seat,
                card.name,
                target_player_index=target,
                target_permanent_index=req.permanent_index,
                x_value=x_value,
            )
        finally:
            session.game.enforce_mana_costs = original_enforce_mana_costs

        if not result.supported:
            # Roll back the injected card if the cast did not complete.
            for idx in range(len(player.hand) - 1, -1, -1):
                if player.hand[idx].name == card.name:
                    del player.hand[idx]
                    break
            raise HTTPException(status_code=400, detail=result.details)

        session.game.log.append(f"[Debug] {player.name} cast {card.name} for free.")

    else:
        raise HTTPException(status_code=400, detail="unknown action")

    return _serialize_state(session, viewer_seat=req.seat)


@app.post("/api/sessions/{session_id}/run-ai")
def run_ai(session_id: str, steps: int = Query(default=1, ge=1, le=200)):
    session = _require_session(session_id)
    for _ in range(steps):
        if session.status == "finished":
            break
        if _seat_type(session, session.current_turn) != "ai":
            break
        _ai_step(session)
        _end_turn(session)
        if _winner(session) is not None:
            session.status = "finished"
            break
    return _serialize_state(session, viewer_seat=None)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
