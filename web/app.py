from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles

from engine import Game
from engine.models import Permanent, PlayerState

from .deck_builder import build_random_deck
from .schemas import CreateSessionRequest, GameActionRequest, JoinSessionRequest, RandomDeckRequest
from .session_store import Session, SessionStore


ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "lea_cards.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"

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


def _serialize_state(session: Session, viewer_seat: int | None) -> dict:
    win = _winner(session)
    if win is not None:
        session.status = "finished"

    return {
        "session_id": session.id,
        "mode": session.mode,
        "status": session.status,
        "current_phase": session.game.current_phase,
        "current_turn": session.current_turn,
        "turn_number": session.game.turn,
        "joined_seats": sorted(session.joined_seats),
        "seat_types": session.seat_types,
        "players": [
            _serialize_player(session.game.players[0], viewer_seat, 0),
            _serialize_player(session.game.players[1], viewer_seat, 1),
        ],
        "stack": [_serialize_stack_item(item, session.game) for item in reversed(session.game.stack)],
        "log": session.game.log[-80:],
        "winner": win,
    }


def _default_target(card_name: str, caster_index: int) -> int:
    if card_name in {"Ancestral Recall", "Healing Salve", "Stream of Life"}:
        return caster_index
    return 1 - caster_index


def _can_cast(game: Game, caster_index: int, card_name: str) -> bool:
    opponent = game.players[1 - caster_index]
    if card_name == "Unsummon":
        return any(perm.card.primary_type == "creature" for perm in opponent.battlefield)
    if card_name == "Disenchant":
        return any(perm.card.primary_type in {"artifact", "enchantment"} for perm in opponent.battlefield)
    return True


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


def _ai_step(session: Session) -> None:
    seat = session.current_turn
    player = session.game.players[seat]

    castable = None
    for card in player.hand:
        if card.primary_type == "land":
            castable = card
            break
        if _can_cast(session.game, seat, card.name):
            castable = card
            break

    if castable is not None:
        target = _default_target(castable.name, seat)
        session.game.cast_from_hand(seat, castable.name, target_player_index=target)

    for perm in player.battlefield:
        if perm.tapped:
            continue
        if perm.card.name == "Prodigal Sorcerer":
            session.game.activate_permanent_ability(seat, "Prodigal Sorcerer", target_player_index=1 - seat)
            break
        if perm.card.name == "Jayemdae Tome" and player.library:
            session.game.activate_permanent_ability(seat, "Jayemdae Tome", target_player_index=seat)
            break
        if perm.card.name == "Black Lotus":
            session.game.activate_permanent_ability(seat, "Black Lotus", target_player_index=seat)
            break


def _end_turn(session: Session) -> None:
    session.game.clear_mana_pools()
    session.current_turn = 1 - session.current_turn
    session.game.turn += 1
    session.game.lands_played_this_turn[session.current_turn] = 0
    if session.current_turn in session.joined_seats:
        session.game.resolve_untap_step(session.current_turn)
        session.game.resolve_upkeep(session.current_turn)
        session.game.resolve_draw_step(session.current_turn)
        session.game.current_phase = "main"


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
def create_session(req: CreateSessionRequest):
    session = store.create(req)
    join_url = f"/index.html?session={session.id}"
    return {
        "session_id": session.id,
        "join_url": join_url,
        "seat": 0,
        "state": _serialize_state(session, viewer_seat=0),
    }


@app.post("/api/sessions/{session_id}/join")
def join_session(session_id: str, req: JoinSessionRequest):
    session = _require_session(session_id)
    session = store.join(session_id, req.guest_name)
    return {
        "session_id": session.id,
        "seat": 1,
        "state": _serialize_state(session, viewer_seat=1),
    }


@app.get("/api/sessions/{session_id}/state")
def get_state(session_id: str, seat: int | None = Query(default=None, ge=0, le=1)):
    session = _require_session(session_id)
    return _serialize_state(session, viewer_seat=seat)


@app.post("/api/sessions/{session_id}/action")
def do_action(session_id: str, req: GameActionRequest):
    session = _require_session(session_id)
    if session.status == "finished":
        raise HTTPException(status_code=400, detail="game already finished")

    if req.seat not in session.joined_seats:
        raise HTTPException(status_code=400, detail="seat has not joined")

    seat_type = session.seat_types.get(req.seat, "human")

    if req.action in {"cast", "activate", "end_turn"} and seat_type != "human":
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
        result = session.game.cast_from_hand(req.seat, req.card_name, target_player_index=target, x_value=req.x_value)
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
            )
            if not result.supported:
                raise HTTPException(status_code=400, detail=result.details)

    elif req.action == "end_turn":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        _end_turn(session)

    elif req.action == "ai_step":
        if session.seat_types.get(session.current_turn) != "ai":
            raise HTTPException(status_code=400, detail="current turn is not AI")
        _ai_step(session)
        _end_turn(session)

    else:
        raise HTTPException(status_code=400, detail="unknown action")

    return _serialize_state(session, viewer_seat=req.seat)


@app.post("/api/sessions/{session_id}/run-ai")
def run_ai(session_id: str, steps: int = Query(default=1, ge=1, le=200)):
    session = _require_session(session_id)
    for _ in range(steps):
        if session.status == "finished":
            break
        if session.seat_types.get(session.current_turn) != "ai":
            break
        _ai_step(session)
        _end_turn(session)
        if _winner(session) is not None:
            session.status = "finished"
            break
    return _serialize_state(session, viewer_seat=None)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
