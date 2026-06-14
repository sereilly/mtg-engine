from __future__ import annotations

import asyncio
import json
import os
import random
import socket
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

from engine import Game
from engine.game_history import GameHistory
from engine.ai_policy import (
    choose_activation_action,
    choose_attackers,
    choose_cast_action,
    choose_combat_blockers,
    choose_combat_instant_cast_action,
    choose_reorder_library_order,
    choose_search_library_index,
)
from engine.card_loader import load_cards
from engine.classifier import classify_card
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle

from .deck_builder import build_random_deck
from .deck_store import (
    DeckImportError,
    DeckNotFoundError,
    DeckStore,
    fetch_moxfield_deck,
    parse_decklist_text,
)
from .schemas import (
    CreateSessionRequest,
    DeckImportRequest,
    DeckSaveRequest,
    GameActionRequest,
    JoinSessionRequest,
    RandomDeckRequest,
    RematchRequest,
    VerificationRequest,
)
from .session_store import Session, SessionStore
from .verification_store import VerificationStore


ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "lea_cards.json"
DECKS_DIR = ROOT / "decks"
VERIFICATION_PATH = ROOT / "card_verification.json"
VERIFICATION_MD_PATH = ROOT / "CARD_VERIFICATION.md"
STATIC_DIR = Path(__file__).resolve().parent / "static"
CARD_CATALOG = load_cards(CARDS_PATH)
CARD_BY_NAME = {card.name.casefold(): card for card in CARD_CATALOG}
CARD_SEARCH_ORDER = sorted(CARD_CATALOG, key=lambda card: card.name)
# Unique catalog card names in display order (some cards share a name across printings).
CATALOG_CARD_NAMES = list(dict.fromkeys(card.name for card in CARD_SEARCH_ORDER))

app = FastAPI(title="Magic LEA Web App")
deck_store = DeckStore(DECKS_DIR)

# The on-disk `decks/` folder is the *shared* deck pool — read-only to browser
# clients, who keep their own (personal) decks in localStorage. Only a server
# operator who launches the app with MAGIC_ALLOW_SHARED_DECK_WRITES=1 (or code
# calling DeckStore directly) may create/update/delete shared decks via the API.
ALLOW_SHARED_DECK_WRITES = os.getenv("MAGIC_ALLOW_SHARED_DECK_WRITES") == "1"


def _require_shared_writes() -> None:
    if not ALLOW_SHARED_DECK_WRITES:
        raise HTTPException(
            status_code=403,
            detail="Shared decks are read-only. Save to your personal decks instead.",
        )
verification_store = VerificationStore(VERIFICATION_PATH)
store = SessionStore(cards_path=CARDS_PATH, deck_store=deck_store)
_session_event_queues: dict[str, set[asyncio.Queue[dict[str, str]]]] = defaultdict(set)


@app.middleware("http")
async def _no_cache_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/index.html", "/app.js", "/battlefield-canvas.js", "/deck-editor.js", "/personal-decks.js", "/styles.css"} or request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


# Keywords surfaced on battlefield cards and the card preview. Order here is the
# order they render in. Passed through the engine's keyword logic so granted
# keywords (auras, "until end of turn" pumps) appear and removed ones disappear.
_DISPLAY_KEYWORDS = (
    "Flying", "First Strike", "Double Strike", "Trample", "Deathtouch",
    "Reach", "Vigilance", "Haste", "Defender", "Banding", "Fear",
    "Lifelink", "Shroud", "Protection", "Rampage", "Flanking",
    "Plainswalk", "Islandwalk", "Swampwalk", "Mountainwalk", "Forestwalk",
)


def _effective_keywords(perm: Permanent, game: Game) -> list[str]:
    """The keywords a creature currently has, reflecting grants and removals.

    Only creatures get a keyword strip; for anything else this is empty. Each
    candidate is resolved through ``game._has_keyword`` so aura-granted and
    "until end of turn" keywords show up, and Layer 6 removal effects (e.g.
    Earthbind stripping Flying) take it back off.
    """
    if "creature" not in perm.card.type_line.lower():
        return []
    keywords = [kw for kw in _DISPLAY_KEYWORDS if game._has_keyword(perm, kw)]
    if perm.metadata.get("loses_flying") or perm.metadata.get("loses_flying_until_eot"):
        keywords = [kw for kw in keywords if kw.lower() != "flying"]
    return keywords


def _serialize_permanent(perm: Permanent, game: Game) -> dict:
    image_uris = perm.card.raw.get("image_uris") if isinstance(perm.card.raw, dict) else None
    image_uri = image_uris.get("normal") if isinstance(image_uris, dict) else None
    large_image_uri = image_uris.get("large") if isinstance(image_uris, dict) else None

    # Resolve aura attachment: find the battlefield index and seat of the attached target
    attached_to = perm.metadata.get("attached_to")
    attached_to_index: int | None = None
    attached_to_seat: int | None = None
    if attached_to is not None:
        for seat_idx, player in enumerate(game.players):
            if attached_to in player.battlefield:
                attached_to_index = player.battlefield.index(attached_to)
                attached_to_seat = seat_idx
                break

    return {
        "name": perm.card.name,
        "type": perm.card.type_line,
        "tapped": perm.tapped,
        "power": perm.effective_power,
        "toughness": perm.effective_toughness,
        "mana_cost": perm.card.mana_cost,
        "oracle_text": perm.card.oracle_text,
        "keywords": _effective_keywords(perm, game),
        "image_uri": image_uri,
        "large_image_uri": large_image_uri,
        "attacking": perm.attacking,
        "defending_player_index": perm.defending_player_index,
        "blocked": perm.blocked,
        "blocking_attacker_controller": perm.blocking_attacker_controller,
        "blocking_attacker_index": perm.blocking_attacker_index,
        "damage_marked": perm.damage_marked,
        "summoning_sick": game._is_summoning_sick(perm),
        "is_token": bool(perm.metadata.get("is_token", False)),
        "is_aura": "aura" in perm.card.type_line.lower(),
        "attached_to_index": attached_to_index,
        "attached_to_seat": attached_to_seat,
        "produced_mana": list(perm.effective_produced_mana),
    }


# Maps an effect instruction kind to the client target-prompt kind a modal mode
# uses, so the UI can route the right targeting flow after a mode is chosen.
_MODE_TARGET_KIND_OVERRIDES = {
    "counter_top_stack_spell": "stack",
    "copy_top_stack_spell": "stack",
}


def _mode_target_kind(instruction) -> str:
    """The client targeting kind for one modal mode's instruction."""
    if instruction is None:
        return "none"
    kind = instruction.kind
    if kind in _MODE_TARGET_KIND_OVERRIDES:
        return _MODE_TARGET_KIND_OVERRIDES[kind]
    if kind == "destroy_target_permanent":
        type_filter = instruction.payload.get("type_filter")
        if type_filter == "creature":
            return "creature"
        if type_filter == "artifact":
            return "artifact"
        return "permanent"
    if kind == "grant_prevention_shield":
        # "...dealt to you this turn" goes to the controller (no target choice);
        # "...dealt to any target" lets the caster shield a creature or a player.
        if instruction.payload.get("to_self") or instruction.payload.get("protection_kind"):
            return "none"
        return "any"
    # Life gain / loss, draws, discards, etc. all designate a target player.
    return "player"


def _serialize_modes(card) -> list[dict]:
    """Selectable modes of a "Choose one —" modal spell, or [] when not modal."""
    program = compile_card_oracle(card)
    if not program.modes:
        return []
    return [
        {
            "index": index,
            "label": mode.label,
            "supported": mode.supported,
            "target_kind": _mode_target_kind(mode.instruction),
        }
        for index, mode in enumerate(program.modes)
    ]


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
        "colors": list(card.colors),
        "modes": _serialize_modes(card),
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
        "modes": _serialize_modes(card),
    }


def _search_cards(query: str, limit: int, *, untested_only: bool = False) -> list[dict]:
    term = query.strip().casefold()
    if untested_only:
        tested = verification_store.results()
        candidates = [card for card in CARD_SEARCH_ORDER if card.name not in tested]
    else:
        candidates = CARD_SEARCH_ORDER

    if not term:
        return [_serialize_card_summary(card) for card in candidates[:limit]]

    starts_with: list = []
    contains: list = []
    for card in candidates:
        lowered = card.name.casefold()
        if lowered.startswith(term):
            starts_with.append(card)
        elif term in lowered:
            contains.append(card)

    ranked = starts_with + contains
    return [_serialize_card_summary(card) for card in ranked[:limit]]


def _build_catalog_payload() -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()
    for card in CARD_SEARCH_ORDER:
        if card.name in seen:
            continue
        seen.add(card.name)
        classification = classify_card(card)
        raw = card.raw if isinstance(card.raw, dict) else {}
        image_uris = raw.get("image_uris") if isinstance(raw.get("image_uris"), dict) else {}
        entries.append(
            {
                "name": card.name,
                "mana_cost": card.mana_cost,
                "cmc": card.cmc,
                "type_line": card.type_line,
                "oracle_text": card.oracle_text,
                "colors": list(card.colors),
                "color_identity": list(card.color_identity),
                "keywords": list(card.keywords),
                "power": raw.get("power"),
                "toughness": raw.get("toughness"),
                "rarity": raw.get("rarity"),
                "image_uri": image_uris.get("normal"),
                "large_image_uri": image_uris.get("large"),
                "supported": classification.supported,
                "unsupported_reason": None if classification.supported else classification.reason,
            }
        )
    return entries


CATALOG_PAYLOAD = _build_catalog_payload()
CATALOG_BY_NAME = {entry["name"].casefold(): entry for entry in CATALOG_PAYLOAD}


def _resolve_deck_entries(entries: list[dict]) -> list[dict]:
    """Resolve deck entries against the catalog, attaching a status to each."""
    resolved: list[dict] = []
    for entry in entries:
        name = str(entry.get("name", "")).strip()
        count = int(entry.get("count", 0))
        if not name or count <= 0:
            continue
        match = CATALOG_BY_NAME.get(name.casefold())
        if match is None:
            resolved.append({"name": name, "count": count, "status": "unknown"})
        else:
            status = "ok" if match["supported"] else "unsupported"
            resolved.append({"name": match["name"], "count": count, "status": status})
    return resolved


def _deck_summary(deck: dict) -> dict:
    entries = _resolve_deck_entries(deck.get("cards", []))
    colors: set[str] = set()
    for entry in entries:
        match = CATALOG_BY_NAME.get(entry["name"].casefold())
        if match:
            colors.update(match["color_identity"])
    return {
        "id": deck["id"],
        "name": deck["name"],
        "description": deck.get("description", ""),
        "card_count": sum(e["count"] for e in entries),
        "colors": [c for c in ("W", "U", "B", "R", "G") if c in colors],
        "unsupported_count": sum(e["count"] for e in entries if e["status"] == "unsupported"),
        "unknown_count": sum(e["count"] for e in entries if e["status"] == "unknown"),
        "updated_at": deck.get("updated_at"),
        # Decks served from the on-disk store are the shared pool. Personal decks
        # live in the client's browser and are never returned by these endpoints.
        "scope": "shared",
    }


def _deck_detail(deck: dict) -> dict:
    detail = _deck_summary(deck)
    detail["cards"] = _resolve_deck_entries(deck.get("cards", []))
    return detail


def _serialize_mana_pool(player: PlayerState) -> dict:
    mana = dict(player.mana_pool)
    for symbol in ("W", "U", "B", "R", "G", "C"):
        mana.setdefault(symbol, 0)
    return mana


def _notify_session_change(session_id: str, reason: str) -> None:
    queues = _session_event_queues.get(session_id)
    if not queues:
        return

    event = {"reason": reason}
    for queue in tuple(queues):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            continue


async def _stream_session_events(session_id: str):
    queue: asyncio.Queue[dict[str, str]] = asyncio.Queue(maxsize=1)
    _session_event_queues[session_id].add(queue)
    try:
        yield ": connected\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield f"event: state\ndata: {json.dumps(event)}\n\n"
    finally:
        queues = _session_event_queues.get(session_id)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            _session_event_queues.pop(session_id, None)


def _serialize_stack_item(item, game: Game) -> dict:
    target_name = None
    if item.target_player_index is not None and 0 <= item.target_player_index < len(game.players):
        if item.card.primary_type in ("instant", "sorcery"):
            target_name = game.players[item.target_player_index].name
    item_type = "ability" if item.ability_instruction is not None else "spell"
    is_triggered = bool(item.ability_effect_kind and item.ability_effect_kind.startswith("triggered_"))
    label = item.card.name if item_type == "spell" else f"{item.card.name} ability"

    target_permanent_name = None
    target_permanent_seat = None
    if isinstance(item.target_permanent_index, int) and item.target_player_index is not None:
        p_idx = item.target_player_index
        if 0 <= p_idx < len(game.players):
            bf = game.players[p_idx].battlefield
            if 0 <= item.target_permanent_index < len(bf):
                target_permanent_name = bf[item.target_permanent_index].card.name
                target_permanent_seat = p_idx

    source_permanent_seat = None
    source_permanent_index = None
    if item.source_permanent is not None:
        for seat_idx, player in enumerate(game.players):
            for perm_idx, perm in enumerate(player.battlefield):
                if perm is item.source_permanent:
                    source_permanent_seat = seat_idx
                    source_permanent_index = perm_idx
                    break
            if source_permanent_index is not None:
                break

    return {
        "type": item_type,
        "is_triggered": is_triggered,
        "label": label,
        "card": _serialize_card(item.card),
        "caster_index": item.caster_index,
        "caster_name": game.players[item.caster_index].name,
        "target_player_index": item.target_player_index,
        "target_player_name": target_name,
        "target_stack_name": item.target_stack_name,
        "target_permanent_index": item.target_permanent_index,
        "target_permanent_name": target_permanent_name,
        "target_permanent_seat": target_permanent_seat,
        "source_permanent_seat": source_permanent_seat,
        "source_permanent_index": source_permanent_index,
        "ability_text": item.ability_text,
        "x_value": item.x_value,
    }


def _serialize_player(
    player: PlayerState,
    viewer_seat: int | None,
    seat: int,
    game: Game,
    playable_hand_indices: list[int] | None = None,
) -> dict:
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
        "battlefield": [_serialize_permanent(perm, game) for perm in player.battlefield],
        "mana_pool": _serialize_mana_pool(player),
        "playable_hand_indices": playable_hand_indices if viewer_seat == seat else [],
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


def _clear_upkeep_pay_choices(session: Session) -> None:
    session.upkeep_pay_choices = []
    session.upkeep_resolved_choices = {}


def _has_island_sanctuary(game, player_index: int) -> bool:
    return any(p.card.name == "Island Sanctuary" for p in game.players[player_index].battlefield)


def _upkeep_pay_pending(session: Session) -> list[dict]:
    """Return pay-or-sacrifice choices that still need a player decision."""
    if session.game.current_step != "upkeep":
        return []
    return [
        c for c in session.upkeep_pay_choices
        if c["card_name"] not in session.upkeep_resolved_choices
    ]


def _advance_after_upkeep_choices(session: Session) -> None:
    """Called once all upkeep pay-or-sacrifice choices are resolved."""
    choices = dict(session.upkeep_resolved_choices)
    _clear_upkeep_pay_choices(session)
    session.game.resolve_upkeep(session.current_turn, human_choices=choices)
    if _seat_type(session, session.current_turn) == "human" and _has_island_sanctuary(session.game, session.current_turn):
        session.island_sanctuary_pending = True
        return
    session.game.resolve_draw_step(session.current_turn)
    session.game._enter_main_phase(precombat=True)


def _build_upkeep_pay_info(session: Session, viewer_seat: int | None) -> dict | None:
    """Serialize pending upkeep pay state for the game-state response."""
    if not session.upkeep_pay_choices:
        return None
    if viewer_seat != session.current_turn:
        return None
    pending = _upkeep_pay_pending(session)
    return {
        "choices": session.upkeep_pay_choices,
        "resolved": session.upkeep_resolved_choices,
        "pending": pending,
    }


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
        if not info["is_my_turn"]:
            info["waiting_for"] = winner_name

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
    session.mulligan_offer_seat = starting_player
    session.mulligan_kept_seats = set()


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
    if player.mulligans_taken > 0:
        session.pregame_phase = "bottom_select"
        session.mulligan_bottom_seat = seat
        session.mulligan_bottom_required = player.mulligans_taken
        session.mulligan_bottom_selected = []
    else:
        session.game.keep_hand(seat)
        _pregame_advance_mulligan_offer(session)


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

    if _seat_type(session, player_index) == "human":
        choices = game.get_upkeep_pay_triggers(player_index)
        if choices:
            session.upkeep_pay_choices = choices
            session.upkeep_resolved_choices = {}
            game._set_phase_and_step("beginning", "upkeep")
            return False

    _clear_upkeep_pay_choices(session)

    # On the AI's turn, pause to hand a human priority at the upkeep step if flagged.
    if _ai_should_hold(session, "upkeep"):
        game.resolve_upkeep(player_index, defer_priority=True)
        _hold_priority_for_human(session)
        return True

    game.resolve_upkeep(player_index)
    if _seat_type(session, player_index) == "human" and _has_island_sanctuary(game, player_index):
        session.island_sanctuary_pending = True
        return False

    if _ai_should_hold(session, "draw"):
        game.resolve_draw_step(player_index, defer_priority=True)
        _hold_priority_for_human(session)
        return True

    game.resolve_draw_step(player_index)
    game._enter_main_phase(precombat=True)
    return True


def _start_next_turn(session: Session) -> None:
    _clear_cleanup_selection(session)
    _clear_untap_selection(session)
    _clear_upkeep_pay_choices(session)
    session.island_sanctuary_pending = False
    session.game.active_player_index = session.current_turn
    session.game.turn += 1
    session.current_turn = session.game._compute_next_active_player()
    should_defer_untap = _seat_type(session, session.current_turn) == "human"
    _begin_turn(session, session.current_turn, defer_untap_selection=should_defer_untap)


def _seat_type(session: Session, seat: int) -> str:
    return session.seat_types.get(seat) or session.seat_types.get(str(seat), "human")


def _can_afford_with_pool(pool: dict, cost: dict, player: PlayerState) -> bool:
    """Check whether `pool` can pay `cost` without mutating either."""
    temp = dict(pool)
    for sym in ("W", "U", "B", "G", "C"):
        if temp.get(sym, 0) < cost.get(sym, 0):
            return False

    available_red = temp.get("R", 0)
    if player.can_spend_white_as_red:
        available_red += temp.get("W", 0)
    if available_red < cost.get("R", 0):
        return False

    temp["W"] -= cost.get("W", 0)
    temp["U"] -= cost.get("U", 0)
    temp["B"] -= cost.get("B", 0)
    temp["G"] -= cost.get("G", 0)
    temp["C"] -= cost.get("C", 0)

    red_to_pay = cost.get("R", 0)
    from_red = min(temp.get("R", 0), red_to_pay)
    temp["R"] = temp.get("R", 0) - from_red
    red_to_pay -= from_red
    if red_to_pay > 0:
        if not player.can_spend_white_as_red or temp.get("W", 0) < red_to_pay:
            return False
        temp["W"] -= red_to_pay

    generic = cost.get("generic", 0)
    if generic > 0:
        available = sum(max(0, temp.get(s, 0)) for s in ("C", "W", "U", "B", "R", "G"))
        if available < generic:
            return False

    return True


def _compute_playable_hand_indices(session: Session, player_index: int) -> list[int]:
    """Return hand indices the player can legally cast right now (considering timing,
    mana already in pool plus potential mana from untapped lands, and restrictions)."""
    game = session.game
    player = game.players[player_index]

    # Bail under blocking UI states where casting is not possible
    if session.pregame_phase is not None:
        return []
    if _cleanup_discard_requirement(session) > 0:
        return []
    if _untap_land_selection_requirement(session) > 0:
        return []
    if _upkeep_pay_pending(session):
        return []
    if session.island_sanctuary_pending:
        return []
    if game.pending_search_library is not None:
        return []
    if game.pending_reorder_library is not None:
        return []

    if not game.has_priority(player_index):
        return []

    # Potential mana = current pool + what each untapped land could produce
    potential_pool: dict[str, int] = dict(player.mana_pool)
    for perm in player.battlefield:
        if not perm.tapped and perm.card.primary_type == "land":
            for color in perm.effective_produced_mana:
                sym = color.upper()
                potential_pool[sym] = potential_pool.get(sym, 0) + 1

    has_gloom = any(
        perm.card.name == "Gloom"
        for p in game.players
        for perm in p.battlefield
    )
    fastbond_count = game._fastbond_count(player_index)
    lands_played = game.lands_played_this_turn.get(player_index, 0)
    current_turn = session.current_turn
    is_main_phase = game.current_phase == "main"
    stack_empty = not game.stack

    playable = []
    for i, card in enumerate(player.hand):
        classification = classify_card(card)
        if not classification.supported:
            continue

        is_instant = card.primary_type == "instant"

        # Non-instant spells require it to be your turn
        if player_index != current_turn and not is_instant:
            continue

        # Sorcery-speed: must be main phase with empty stack on your turn
        if card.primary_type in {"land", "sorcery", "creature", "artifact", "enchantment"}:
            if player_index != current_turn or not is_main_phase or not stack_empty:
                continue

        # Card-specific timing restriction
        if "cast this spell only during your declare attackers step" in card.oracle_text.lower():
            if game.current_step != "declare_attackers" or game.active_player_index != player_index:
                continue

        # Target validation (aura enchant targets, removal targets, counter targets, etc.)
        target_ok, _ = game._validate_cast_targets(card, player_index, None)
        if not target_ok:
            continue

        # Land play restriction (1 per turn unless Fastbond)
        if card.primary_type == "land":
            if lands_played >= 1 and fastbond_count <= 0:
                continue

        # Mana affordability for non-land cards
        if card.primary_type != "land" and game.enforce_mana_costs:
            extra_tax = 3 if (has_gloom and "W" in card.colors) else 0
            # Use x_value=0 so X spells are shown as playable (castable at X=0)
            cost = game._parse_mana_cost(card.mana_cost, x_value=0, extra_generic=extra_tax)
            if not _can_afford_with_pool(potential_pool, cost, player):
                continue

        playable.append(i)

    return playable


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

    search_library_info = None
    pending_search = session.game.pending_search_library
    if pending_search is not None:
        caster_seat = pending_search["caster_index"]
        if viewer_seat is None or viewer_seat == caster_seat:
            caster = session.game.players[caster_seat]
            search_library_info = {
                "caster_seat": caster_seat,
                "count": pending_search["count"],
                "card_type": pending_search["card_type"],
                "cards": [_serialize_card_summary(card) for card in caster.library],
            }

    reorder_library_info = None
    pending_reorder = session.game.pending_reorder_library
    if pending_reorder is not None and _seat_type(session, pending_reorder["caster_index"]) != "ai":
        caster_seat = pending_reorder["caster_index"]
        if viewer_seat is None or viewer_seat == caster_seat:
            target = session.game.players[pending_reorder["target_index"]]
            top_count = pending_reorder["top_count"]
            reorder_library_info = {
                "caster_seat": caster_seat,
                "target_seat": pending_reorder["target_index"],
                "top_count": top_count,
                "may_shuffle": bool(pending_reorder.get("may_shuffle")),
                "target_name": target.name,
                "cards": [_serialize_card_summary(card) for card in target.library[:top_count]],
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
        "priority_player": session.game.priority_player_index,
        "priority_pass_count": session.game.priority_pass_count,
        "joined_seats": sorted(session.joined_seats),
        "seat_types": session.seat_types,
        "awaiting_opponent": session.awaiting_opponent,
        "players": [
            _serialize_player(
                session.game.players[0], viewer_seat, 0, session.game,
                _compute_playable_hand_indices(session, 0) if viewer_seat == 0 else [],
            ),
            _serialize_player(
                session.game.players[1], viewer_seat, 1, session.game,
                _compute_playable_hand_indices(session, 1) if viewer_seat == 1 else [],
            ),
        ],
        "stack": [_serialize_stack_item(item, session.game) for item in reversed(session.game.stack)],
        "combat": session.game.get_combat_state(),
        "log": session.game.log,
        "winner": win,
        "rematch": _build_rematch_info(session, viewer_seat),
        "cleanup_discard": cleanup_info,
        "untap_land_selection": untap_info,
        "upkeep_pay": _build_upkeep_pay_info(session, viewer_seat),
        "island_sanctuary_pending": session.island_sanctuary_pending and viewer_seat == session.current_turn,
        "search_library": search_library_info,
        "reorder_library": reorder_library_info,
        "pregame": _build_pregame_info(session, viewer_seat),
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


def _build_join_url(request: Request, session_id: str) -> str:
    return f"{str(request.base_url).rstrip('/')}/index.html?session={session_id}"


def _detect_local_ip() -> str | None:
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
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass

    return None


def _build_lan_join_url(request: Request, session_id: str) -> str | None:
    local_ip = _detect_local_ip()
    if not local_ip:
        return None

    if (request.url.hostname or "") == local_ip:
        return None

    lan_base_url = request.base_url.replace(hostname=local_ip)
    return f"{str(lan_base_url).rstrip('/')}/index.html?session={session_id}"


def _auto_resolve_ai_pending_search(session: Session) -> None:
    """Resolve a pending library search immediately when the searcher is an AI seat."""
    game = session.game
    while True:
        pending = game.pending_search_library
        if pending is None:
            return
        caster_seat = pending["caster_index"]
        if _seat_type(session, caster_seat) != "ai":
            return
        caster = game.players[caster_seat]
        choice = choose_search_library_index(game, caster_seat, card_type=pending.get("card_type", "any"))
        if choice is None:
            random.shuffle(caster.library)
            game.pending_search_library = None
            game.log.append(f"{caster.name} searched their library and found nothing")
            continue
        if not game.confirm_search_library(caster_seat, choice):
            game.pending_search_library = None
            return


def _auto_resolve_ai_pending_reorder(session: Session) -> None:
    """Resolve a pending library reorder immediately when the caster is an AI seat.

    AI players take the action headlessly — no "Reorder top of library" UI is shown.
    """
    game = session.game
    pending = game.pending_reorder_library
    if pending is None:
        return
    caster_seat = pending["caster_index"]
    if _seat_type(session, caster_seat) != "ai":
        return
    new_order = choose_reorder_library_order(
        game, caster_seat, pending["target_index"], pending["top_count"]
    )
    if not game.confirm_reorder_library(caster_seat, new_order):
        game.pending_reorder_library = None


def _auto_resolve_ai_pending(session: Session) -> None:
    """Resolve any AI-owned pending choices (library search, library reorder)."""
    _auto_resolve_ai_pending_search(session)
    _auto_resolve_ai_pending_reorder(session)


def _ai_step(session: Session) -> bool:
    """Run one AI action for the current turn.

    Returns True when the AI has nothing more to do this turn (caller should end
    the turn).  Returns False when the AI queued a spell and passed priority to a
    human opponent — the turn must NOT be ended yet; the human must act first.
    """
    seat = session.current_turn
    game = session.game

    _auto_resolve_ai_pending(session)

    has_human_opponent = any(
        _seat_type(session, s) == "human"
        for s in range(len(game.players))
        if s != seat
    )

    if game.priority_player_index is not None and game.priority_player_index != seat:
        return False

    # choose_cast_action covers sorcery-speed plays (enchantments, sorceries,
    # creatures, artifacts, lands), which are legal only during the active player's
    # main phase with an empty stack. Without this guard the AI would, e.g., drop an
    # enchantment during the combat damage step. Instants are handled separately via
    # _ai_respond_to_priority / the declare-blockers window.
    sorcery_speed_ok = (
        game.active_player_index == seat
        and game.current_step in ("precombat_main", "postcombat_main")
        and not game.stack
    )
    cast_action = choose_cast_action(game, seat) if sorcery_speed_ok else None
    if cast_action is not None:
        card_to_cast = game.players[seat].hand[cast_action.hand_index]
        for permanent_index in cast_action.land_tap_indices:
            permanent = game.players[seat].battlefield[permanent_index]
            game.tap_land_for_mana(seat, permanent.card.name, permanent_index=permanent_index)

        if has_human_opponent:
            result = game.queue_from_hand(
                seat,
                card_to_cast.name,
                target_player_index=cast_action.target_player_index,
                target_permanent_index=cast_action.target_permanent_index,
                x_value=cast_action.x_value,
            )
            if result.supported:
                game.note_priority_action_taken(seat)
                game.pass_priority(seat)
                return False  # paused — human has priority over the spell on the stack
        else:
            game.cast_from_hand(
                seat,
                card_to_cast.name,
                target_player_index=cast_action.target_player_index,
                target_permanent_index=cast_action.target_permanent_index,
                x_value=cast_action.x_value,
            )
            _auto_resolve_ai_pending(session)

    activation_action = choose_activation_action(game, seat)
    if activation_action is not None:
        for permanent_index in activation_action.land_tap_indices:
            permanent = game.players[seat].battlefield[permanent_index]
            game.tap_land_for_mana(seat, permanent.card.name, permanent_index=permanent_index)
        game.activate_permanent_ability(
            seat,
            activation_action.permanent_name,
            target_player_index=activation_action.target_player_index,
            permanent_index=activation_action.permanent_index,
        )
        _auto_resolve_ai_pending(session)

    return True



def _ai_respond_to_priority(session: Session, seat: int) -> str | None:
    game = session.game
    if not game.has_priority(seat):
        return None

    instant_action = choose_combat_instant_cast_action(game, seat)
    if instant_action is not None:
        card_to_cast = game.players[seat].hand[instant_action.hand_index]
        for permanent_index in instant_action.land_tap_indices:
            permanent = game.players[seat].battlefield[permanent_index]
            game.tap_land_for_mana(seat, permanent.card.name, permanent_index=permanent_index)
        result = game.queue_from_hand(
            seat,
            card_to_cast.name,
            target_player_index=instant_action.target_player_index,
            x_value=instant_action.x_value,
        )
        if result.supported:
            game.note_priority_action_taken(seat)

    if game.has_priority(seat):
        return game.pass_priority(seat)
    return None


def _auto_advance_after_all_passed(session: Session, pass_result: str | None) -> None:
    if pass_result != "all_passed_empty":
        return

    # Advance turn structure automatically after both players pass with an empty stack.
    _advance_phase(session)


def _run_priority_exchange(session: Session, acting_seat: int) -> None:
    result = session.game.pass_priority(acting_seat)

    while True:
        _auto_resolve_ai_pending(session)
        _auto_advance_after_all_passed(session, result)

        ai_priority_seat = session.game.priority_player_index
        if (
            result == "passed"
            and ai_priority_seat is not None
            and _seat_type(session, ai_priority_seat) == "ai"
            and (ai_priority_seat != session.current_turn or bool(session.game.stack))
        ):
            result = _ai_respond_to_priority(session, ai_priority_seat)
            continue

        break


def _end_turn(session: Session, allow_manual_cleanup_selection: bool = False) -> bool:
    if session.game.current_turn_phase in {"precombat_main", "postcombat_main"}:
        session.game._close_current_priority_step()
    if session.game.current_turn_phase == "combat":
        session.game.end_combat()
    if session.game.current_step != "end":
        session.game.resolve_end_step(session.current_turn)
    session.game.close_end_step()
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


def _has_human_opponent(session: Session) -> bool:
    """True when a human shares the table with the active (AI) player."""
    active = session.game.active_player_index
    return any(
        _seat_type(session, s) == "human"
        for s in range(len(session.game.players))
        if s != active
    )


def _ai_declare_attackers(session: Session) -> None:
    """Active-player (AI) declares attackers — the declare-attackers turn-based action."""
    game = session.game
    if game.current_step != "declare_attackers" or game.combat_attackers_locked:
        return
    if _seat_type(session, game.active_player_index) != "ai":
        return
    attacker_indices = choose_attackers(game, game.active_player_index)
    ok, _ = game.declare_attackers(game.active_player_index, attacker_indices)
    if not ok:
        game.declare_attackers(game.active_player_index, [])


def _ai_assign_combat_damage(session: Session) -> None:
    """Active-player (AI) assigns combat damage — the turn-based action the engine
    defers to a player when an attacker is blocked by two or more creatures."""
    game = session.game
    if game.current_step != "combat_damage" or game.combat_damage_resolved:
        return
    if _seat_type(session, game.active_player_index) != "ai":
        return
    auto = game._build_auto_damage_assignment()
    game.resolve_combat_damage(game.active_player_index, attacker_damage=auto)
    if not game.combat_damage_resolved:
        # First-strike pass resolved; resolve the regular-damage pass too.
        game.resolve_combat_damage(game.active_player_index, attacker_damage=auto)


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


def _advance_ai_turn(session: Session) -> None:
    """Advance the AI's turn through its non-main steps after it has finished acting
    in the current step.

    Pauses to hand a human priority at any step they flagged on the phase rail. Stops
    when a new main phase begins (so the AI can cast there on the next step), when the
    turn ends, or when human input is required (e.g. declaring blockers).
    """
    for _safety in range(20):
        game = session.game
        step = game.current_step

        if _ai_should_hold(session, step):
            # Resolve the active player's turn-based action (declaring attackers)
            # before handing priority to the human.
            if step == "declare_attackers":
                _ai_declare_attackers(session)
            if _hold_priority_for_human(session):
                return

        prev_turn = session.current_turn
        prev_phase = game.current_turn_phase
        prev_step = step
        _advance_phase(session)

        if session.current_turn != prev_turn:
            return  # the AI's turn has ended
        if (
            session.game.current_turn_phase == prev_phase
            and session.game.current_step == prev_step
        ):
            return  # stuck waiting for human input (e.g. declare blockers)
        # Stop at a main phase so the AI casts there (driven by the next ai_step).
        if session.game.current_step in ("precombat_main", "postcombat_main"):
            return


def _advance_phase(session: Session) -> None:
    game = session.game
    phase = game.current_turn_phase
    step = game.current_step

    if phase == "beginning" and step in ("upkeep", "draw"):
        # Resume after a held upkeep/draw step on the AI's turn: close it and move on,
        # holding again at the draw step if the human flagged it.
        game.close_beginning_step()
        if step == "upkeep" and _ai_should_hold(session, "draw"):
            game.resolve_draw_step(session.current_turn, defer_priority=True)
            _hold_priority_for_human(session)
            return
        if step == "upkeep":
            game.resolve_draw_step(session.current_turn)
        game._enter_main_phase(precombat=True)
        return

    if phase == "precombat_main":
        game._close_current_priority_step()
        game.advance_combat_phase()
        _clear_cleanup_selection(session)
        return
    if phase == "combat":
        if (
            step == "combat_damage"
            and not game.combat_damage_resolved
            and _seat_type(session, game.active_player_index) == "ai"
        ):
            # No human is assigning damage for the active AI. Resolve combat damage
            # with a sensible default assignment so a multi-blocked attacker (which
            # the engine defers for manual assignment) doesn't deadlock the step.
            _ai_assign_combat_damage(session)
        if step == "declare_attackers" and not game.combat_attackers_locked:
            _ai_declare_attackers(session)
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
        game.close_end_step()
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


def _save_snapshot(session: Session) -> None:
    session.history.save(session)


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


@app.get("/api/cards/catalog")
def get_card_catalog():
    return {"cards": CATALOG_PAYLOAD}


def _verification_listing() -> tuple[list[dict], dict[str, int]]:
    """Merge recorded results with the full catalog so every card is represented."""
    results = verification_store.results()
    cards: list[dict] = []
    counts = {"pass": 0, "fail": 0, "untested": 0}
    for name in CATALOG_CARD_NAMES:
        entry = results.get(name)
        status = entry["status"] if entry else "untested"
        counts[status] = counts.get(status, 0) + 1
        cards.append(
            {
                "card_name": name,
                "status": status,
                "reason": entry.get("reason", "") if entry else "",
                "updated_at": entry.get("updated_at") if entry else None,
            }
        )
    return cards, counts


def _write_verification_markdown() -> None:
    """Regenerate the human-readable master tracking document."""
    cards, counts = _verification_listing()
    lines = [
        "# Card Verification Tracker",
        "",
        "Master record of which cards have been manually validated in-game. "
        "Generated automatically — edit results via the in-game Debug Menu.",
        "",
        f"- Total cards: **{len(cards)}**",
        f"- Passed: **{counts['pass']}**",
        f"- Failed: **{counts['fail']}**",
        f"- Untested: **{counts['untested']}**",
        "",
        "| Card | Status | Failure reason |",
        "| --- | --- | --- |",
    ]
    badge = {"pass": "✅ pass", "fail": "❌ fail", "untested": "⬜ untested"}
    for card in cards:
        reason = (card["reason"] or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {card['card_name']} | {badge[card['status']]} | {reason} |")
    VERIFICATION_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


@app.get("/api/verification")
def get_verification():
    cards, counts = _verification_listing()
    return {"cards": cards, "counts": counts, "total": len(cards)}


@app.get("/api/verification/next-untested")
def get_next_untested():
    results = verification_store.results()
    untested = [name for name in CATALOG_CARD_NAMES if name not in results]
    if not untested:
        raise HTTPException(status_code=404, detail="all cards have been tested")
    return {"card_name": random.choice(untested), "remaining": len(untested)}


@app.post("/api/verification")
def record_verification(req: VerificationRequest):
    try:
        entry = verification_store.record(req.card_name, req.status, req.reason or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _write_verification_markdown()
    return entry


@app.get("/api/decks")
def list_decks():
    return {"decks": [_deck_summary(deck) for deck in deck_store.list()]}


@app.post("/api/decks")
def create_deck(req: DeckSaveRequest):
    _require_shared_writes()
    deck = deck_store.create(
        req.name.strip() or "Untitled Deck",
        [c.model_dump() for c in req.cards],
        req.description.strip(),
    )
    return _deck_detail(deck)


@app.get("/api/decks/{deck_id}")
def get_deck(deck_id: str):
    try:
        deck = deck_store.get(deck_id)
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=404, detail="deck not found") from exc
    return _deck_detail(deck)


@app.put("/api/decks/{deck_id}")
def update_deck(deck_id: str, req: DeckSaveRequest):
    _require_shared_writes()
    try:
        deck = deck_store.update(
            deck_id,
            req.name.strip() or "Untitled Deck",
            [c.model_dump() for c in req.cards],
            req.description.strip(),
        )
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=404, detail="deck not found") from exc
    return _deck_detail(deck)


@app.delete("/api/decks/{deck_id}")
def delete_deck(deck_id: str):
    _require_shared_writes()
    try:
        deck_store.delete(deck_id)
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=404, detail="deck not found") from exc
    return {"ok": True}


@app.post("/api/decks/import")
def import_deck(req: DeckImportRequest):
    """Parse a pasted decklist or fetch a Moxfield deck. Does not save anything;
    returns resolved entries so the editor can show unsupported/unknown cards."""
    warnings: list[str] = []
    if req.url and req.url.strip():
        try:
            name, entries = fetch_moxfield_deck(req.url.strip())
        except DeckImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif req.text and req.text.strip():
        entries, warnings = parse_decklist_text(req.text)
        name = "Imported Deck"
    else:
        raise HTTPException(status_code=400, detail="provide a decklist text or a Moxfield URL")

    resolved = _resolve_deck_entries(entries)
    if not resolved:
        raise HTTPException(status_code=400, detail="no cards found in the deck list")
    return {
        "name": name,
        "cards": resolved,
        "warnings": warnings,
        "unknown_count": sum(e["count"] for e in resolved if e["status"] == "unknown"),
        "unsupported_count": sum(e["count"] for e in resolved if e["status"] == "unsupported"),
    }


@app.post("/api/sessions")
def create_session(req: CreateSessionRequest, request: Request):
    try:
        session = store.create(req)
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=400, detail="selected deck not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _pregame_auto_advance(session)
    join_url = _build_join_url(request, session.id)
    lan_join_url = _build_lan_join_url(request, session.id)
    return {
        "session_id": session.id,
        "join_url": join_url,
        "lan_join_url": lan_join_url,
        "seat": 0,
        "state": _serialize_state(session, viewer_seat=0),
    }


@app.post("/api/sessions/{session_id}/join")
def join_session(session_id: str, req: JoinSessionRequest, request: Request):
    session = _require_session(session_id)
    try:
        session = store.join(
            session_id,
            req.guest_name,
            req.guest_deck_id,
            req.guest_colors,
            req.guest_deck_cards,
        )
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=400, detail="selected deck not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _pregame_auto_advance(session)
    _notify_session_change(session.id, "join")
    join_url = _build_join_url(request, session.id)
    lan_join_url = _build_lan_join_url(request, session.id)
    return {
        "session_id": session.id,
        "join_url": join_url,
        "lan_join_url": lan_join_url,
        "seat": 1,
        "state": _serialize_state(session, viewer_seat=1),
    }


@app.post("/api/sessions/{session_id}/rematch")
def rematch_session(session_id: str, req: RematchRequest):
    session = _require_session(session_id)
    if session.mode != "human_vs_human":
        raise HTTPException(status_code=400, detail="rematch is only available in human vs human games")
    if req.seat not in session.joined_seats:
        raise HTTPException(status_code=400, detail="seat has not joined")
    if _winner(session) is None and session.status != "finished":
        raise HTTPException(status_code=400, detail="game is not finished")

    session.rematch_votes.add(req.seat)
    needed = _rematch_human_seats(session)

    if all(s in session.rematch_votes for s in needed):
        store.restart(session)
        _pregame_auto_advance(session)
        _notify_session_change(session.id, "rematch_start")
    else:
        _notify_session_change(session.id, "rematch_vote")

    return _serialize_state(session, viewer_seat=req.seat)


@app.get("/api/sessions/{session_id}/events")
async def stream_session_events(session_id: str):
    _require_session(session_id)
    return StreamingResponse(
        _stream_session_events(session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/sessions/{session_id}/state")
def get_state(session_id: str, seat: int | None = Query(default=None, ge=0, le=1)):
    session = _require_session(session_id)
    return _serialize_state(session, viewer_seat=seat)


@app.get("/api/cards/search")
def search_cards(
    query: str = Query(default=""),
    limit: int = Query(default=16, ge=1, le=50),
    untested_only: bool = Query(default=False),
):
    return {"cards": _search_cards(query, limit, untested_only=untested_only)}


@app.post("/api/sessions/{session_id}/action")
def do_action(session_id: str, req: GameActionRequest):
    session = _require_session(session_id)
    if session.status == "finished":
        raise HTTPException(status_code=400, detail="game already finished")

    if session.awaiting_opponent:
        raise HTTPException(status_code=400, detail="waiting for opponent to join")

    if req.seat not in session.joined_seats:
        raise HTTPException(status_code=400, detail="seat has not joined")

    _pregame_actions = {
        "coin_flip_choose",
        "mulligan_take",
        "mulligan_keep",
        "mulligan_bottom_select",
        "mulligan_bottom_confirm",
    }
    if session.pregame_phase is not None and req.action not in _pregame_actions | {"debug_add_to_hand", "debug_cast_free"}:
        raise HTTPException(status_code=400, detail="pregame not complete")

    if session.pregame_phase is None:
        _save_snapshot(session)

    seat_type = _seat_type(session, req.seat)

    # Remember the human's phase-rail hold-priority preferences so the AI can stop
    # at them even on steps (turn start, end step) it would otherwise resolve itself.
    if req.stop_steps is not None:
        session.opponent_stop_steps = set(req.stop_steps)

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

    if _upkeep_pay_pending(session) and req.action not in {"pay_upkeep", "sacrifice_upkeep", "tap", "activate", "debug_add_to_hand", "debug_cast_free"}:
        raise HTTPException(status_code=400, detail="resolve upkeep payment before other actions")

    if session.island_sanctuary_pending and req.action not in {"island_sanctuary_skip", "island_sanctuary_draw", "debug_add_to_hand", "debug_cast_free"}:
        raise HTTPException(status_code=400, detail="choose Island Sanctuary draw option before other actions")

    _auto_resolve_ai_pending(session)
    if session.game.pending_search_library is not None and req.action not in {"search_library_confirm", "debug_add_to_hand", "debug_cast_free"}:
        raise HTTPException(status_code=400, detail="complete library search before other actions")
    if session.game.pending_reorder_library is not None and req.action not in {"reorder_library_confirm", "debug_add_to_hand", "debug_cast_free"}:
        raise HTTPException(status_code=400, detail="complete library reorder before other actions")

    if req.action in {
        "cast",
        "activate",
        "pass_priority",
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
        if not session.game.has_priority(req.seat):
            raise HTTPException(status_code=400, detail="you do not currently have priority")

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
        # The client sends a top-first stack index (0 = topmost). The engine stack
        # is bottom-first, so convert before queueing.
        engine_stack_index = None
        if req.target_stack_index is not None:
            engine_stack_index = len(session.game.stack) - 1 - req.target_stack_index
        result = session.game.queue_from_hand(
            req.seat,
            req.card_name,
            target_player_index=target,
            target_permanent_index=req.permanent_index,
            x_value=req.x_value,
            new_color=req.mana_color,
            target_stack_index=engine_stack_index,
            mode_index=req.mode_index,
        )
        if not result.supported:
            raise HTTPException(status_code=400, detail=result.details)
        session.game.note_priority_action_taken(req.seat)

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
                chosen_color=req.mana_color or "G",
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
                chosen_color=req.mana_color or "G",
                permanent_index=permanent_index,
            )
            if not tapped:
                raise HTTPException(status_code=400, detail="failed to tap land for mana")
        else:
            if not session.game.has_priority(req.seat):
                raise HTTPException(status_code=400, detail="you do not currently have priority")
            target = req.target_seat if req.target_seat is not None else 1 - req.seat
            result = session.game.queue_permanent_ability(
                req.seat,
                permanent.card.name,
                target_player_index=target,
                permanent_index=permanent_index,
                mana_color=req.mana_color,
                target_permanent_index=req.target_permanent_index,
            )
            if not result.supported:
                raise HTTPException(status_code=400, detail=result.details)
            session.game.note_priority_action_taken(req.seat)

    elif req.action == "pass_priority":
        try:
            _run_priority_exchange(session, req.seat)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    elif req.action == "end_turn":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        if not session.game.has_priority(req.seat):
            raise HTTPException(status_code=400, detail="you do not currently have priority")
        if session.game.stack:
            raise HTTPException(status_code=400, detail="cannot end turn while stack is not empty")
        _end_turn(session, allow_manual_cleanup_selection=True)

    elif req.action == "next_phase":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        if session.game.current_turn_phase in {"precombat_main", "combat", "postcombat_main"}:
            if not session.game.has_priority(req.seat):
                raise HTTPException(status_code=400, detail="you do not currently have priority")
            if session.game.stack:
                raise HTTPException(status_code=400, detail="cannot advance phase while stack is not empty")
        _advance_phase(session)

    elif req.action == "declare_attackers":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        if not session.game.has_priority(req.seat):
            raise HTTPException(status_code=400, detail="you do not currently have priority")
        ok, details = session.game.declare_attackers(
            req.seat,
            req.attacker_indices or [],
            defending_player_index=req.target_seat,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=details)
        session.game.note_priority_action_taken(req.seat)

    elif req.action == "declare_blockers":
        defender_seat = session.game.combat_defending_player_index
        if defender_seat is None:
            raise HTTPException(status_code=400, detail="no combat attackers declared")
        if req.seat != defender_seat:
            raise HTTPException(status_code=400, detail="only defending player may declare blockers")
        # Declaring blockers is the defending player's turn-based action, not a
        # priority action: the defender declares even while the active player
        # (e.g. an attacking AI) holds priority. Requiring priority here wrongly
        # blocked the human defender from confirming blockers on the AI's turn.
        raw_pairs = req.blocker_pairs or {}
        blocker_pairs = {int(k): int(v) for k, v in raw_pairs.items()}
        ok, details = session.game.declare_blockers(req.seat, blocker_pairs)
        if not ok:
            raise HTTPException(status_code=400, detail=details)
        # After blockers are declared the active player receives priority (704-step
        # priority window), so the AI's turn can resume / the attacker may respond.
        session.game.start_priority_window(session.game.active_player_index)

    elif req.action == "assign_combat_damage":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        if not session.game.has_priority(req.seat):
            raise HTTPException(status_code=400, detail="you do not currently have priority")
        attacker_damage_raw = req.attacker_damage or {}
        attacker_damage = {
            int(attacker_idx): {int(blocker_idx): int(value) for blocker_idx, value in blockers.items()}
            for attacker_idx, blockers in attacker_damage_raw.items()
        }
        ok, details = session.game.resolve_combat_damage(req.seat, attacker_damage=attacker_damage)
        if not ok:
            raise HTTPException(status_code=400, detail=details)
        session.game.note_priority_action_taken(req.seat)

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

        choices = session.game.get_upkeep_pay_triggers(session.current_turn)
        if choices and _seat_type(session, session.current_turn) == "human":
            session.upkeep_pay_choices = choices
            session.upkeep_resolved_choices = {}
            session.game._set_phase_and_step("beginning", "upkeep")
        else:
            _clear_upkeep_pay_choices(session)
            session.game.resolve_upkeep(session.current_turn)
            if _seat_type(session, session.current_turn) == "human" and _has_island_sanctuary(session.game, session.current_turn):
                session.island_sanctuary_pending = True
            else:
                session.game.resolve_draw_step(session.current_turn)
                session.game._enter_main_phase(precombat=True)

    elif req.action == "pay_upkeep":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        if not _upkeep_pay_pending(session):
            raise HTTPException(status_code=400, detail="no upkeep payment required")
        if not req.card_name:
            raise HTTPException(status_code=400, detail="card_name is required")

        pending = {c["card_name"]: c for c in _upkeep_pay_pending(session)}
        if req.card_name not in pending:
            raise HTTPException(status_code=400, detail="card not awaiting upkeep payment")

        choice = pending[req.card_name]
        controller = session.game.players[req.seat]
        for sym, count in choice["mana"].items():
            if sym != "generic" and controller.mana_pool.get(sym, 0) < count:
                raise HTTPException(status_code=400, detail=f"not enough {sym} mana to pay upkeep for {req.card_name}")

        session.upkeep_resolved_choices[req.card_name] = True

        if not _upkeep_pay_pending(session):
            _advance_after_upkeep_choices(session)

    elif req.action == "sacrifice_upkeep":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        if not _upkeep_pay_pending(session):
            raise HTTPException(status_code=400, detail="no upkeep payment required")
        if not req.card_name:
            raise HTTPException(status_code=400, detail="card_name is required")

        pending = {c["card_name"]: c for c in _upkeep_pay_pending(session)}
        if req.card_name not in pending:
            raise HTTPException(status_code=400, detail="card not awaiting upkeep payment")

        session.upkeep_resolved_choices[req.card_name] = False

        if not _upkeep_pay_pending(session):
            _advance_after_upkeep_choices(session)

    elif req.action in {"island_sanctuary_skip", "island_sanctuary_draw"}:
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        if not session.island_sanctuary_pending:
            raise HTTPException(status_code=400, detail="no Island Sanctuary choice pending")
        session.island_sanctuary_pending = False
        skip = req.action == "island_sanctuary_skip"
        session.game.resolve_draw_step(session.current_turn, sanctuary_choice=skip)
        session.game._enter_main_phase(precombat=True)

    elif req.action == "search_library_confirm":
        pending = session.game.pending_search_library
        if pending is None:
            raise HTTPException(status_code=400, detail="no library search pending")
        if req.seat != pending["caster_index"]:
            raise HTTPException(status_code=400, detail="not your library search")
        if req.hand_index is None:
            raise HTTPException(status_code=400, detail="hand_index (library card index) is required")
        ok = session.game.confirm_search_library(req.seat, req.hand_index)
        if not ok:
            raise HTTPException(status_code=400, detail="invalid library card index")

    elif req.action == "reorder_library_confirm":
        pending = session.game.pending_reorder_library
        if pending is None:
            raise HTTPException(status_code=400, detail="no library reorder pending")
        if req.seat != pending["caster_index"]:
            raise HTTPException(status_code=400, detail="not your library reorder")
        if req.card_order is None:
            raise HTTPException(status_code=400, detail="card_order is required")
        ok = session.game.confirm_reorder_library(req.seat, req.card_order, shuffle=bool(req.shuffle))
        if not ok:
            raise HTTPException(status_code=400, detail="invalid card order")

    elif req.action == "ai_step":
        if _seat_type(session, session.current_turn) != "ai":
            raise HTTPException(status_code=400, detail="current turn is not AI")
        if _ai_step(session):
            # The AI finished acting in the current step. Hold here if the human
            # flagged this (main) step; otherwise leave it and advance the turn,
            # pausing at any later step they flagged.
            step = session.game.current_step
            if _ai_should_hold(session, step):
                if step == "declare_attackers":
                    _ai_declare_attackers(session)
                _hold_priority_for_human(session)
            else:
                _advance_phase(session)
                _advance_ai_turn(session)

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
        if not session.game.has_priority(req.seat):
            raise HTTPException(status_code=400, detail="you do not currently have priority")

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
            result = session.game.queue_from_hand(
                req.seat,
                card.name,
                target_player_index=target,
                target_permanent_index=req.permanent_index,
                x_value=x_value,
                mode_index=req.mode_index,
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

        session.game.note_priority_action_taken(req.seat)
        session.game.log.append(f"[Debug] {player.name} cast {card.name} for free.")

    elif req.action == "debug_cast_free_opponent":
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue debug action for AI seat")
        if not req.card_name:
            raise HTTPException(status_code=400, detail="card_name is required")

        opponent_seat = 1 - req.seat
        card = CARD_BY_NAME.get(req.card_name.strip().casefold())
        if card is None:
            raise HTTPException(status_code=404, detail="card not found")

        opponent = session.game.players[opponent_seat]
        opponent.hand.append(card)
        target = req.target_seat if req.target_seat is not None else _default_target(card.name, opponent_seat)
        x_value = req.x_value if req.x_value is not None else (0 if "{X}" in (card.mana_cost or "") else None)

        # Debug exception: casting for the opponent is allowed even on your own turn,
        # when priority belongs to you. Hand the opponent a priority window so the cast
        # is accepted and the resulting game state (caster holds priority) is correct.
        saved_priority_player_index = session.game.priority_player_index
        session.game.start_priority_window(opponent_seat)

        original_enforce_mana_costs = session.game.enforce_mana_costs
        try:
            session.game.enforce_mana_costs = False
            result = session.game.queue_from_hand(
                opponent_seat,
                card.name,
                target_player_index=target,
                target_permanent_index=req.permanent_index,
                x_value=x_value,
                mode_index=req.mode_index,
            )
        finally:
            session.game.enforce_mana_costs = original_enforce_mana_costs

        if not result.supported:
            # Roll back the injected card and priority window if the cast did not complete.
            session.game.priority_player_index = saved_priority_player_index
            for idx in range(len(opponent.hand) - 1, -1, -1):
                if opponent.hand[idx].name == card.name:
                    del opponent.hand[idx]
                    break
            raise HTTPException(status_code=400, detail=result.details)

        # The spell is now on the stack under a temporary priority window we handed
        # the opponent so the cast would be accepted. Hand priority back to the acting
        # (human) player: it's their turn, so the AI opponent would never get a turn to
        # pass and the spell would strand on the stack. With priority restored the human
        # resolves it by passing, exactly like a spell they cast themselves.
        session.game.start_priority_window(req.seat)
        session.game.log.append(f"[Debug] {opponent.name} cast {card.name} for free.")

    elif req.action == "debug_add_mana":
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue debug action for AI seat")
        color = (req.mana_color or "").strip().upper()
        if color not in {"W", "U", "B", "R", "G", "C"}:
            raise HTTPException(status_code=400, detail="invalid mana color")

        # target_seat selects whose pool to add to; default to the acting seat.
        target = req.target_seat if req.target_seat is not None else req.seat
        player = session.game.players[target]
        player.mana_pool[color] += 1
        session.game.log.append(f"[Debug] Added {{{color}}} to {player.name}'s mana pool.")

    elif req.action == "coin_flip_choose":
        if session.pregame_phase != "coin_flip":
            raise HTTPException(status_code=400, detail="not in coin flip phase")
        if req.seat != session.coin_flip_winner:
            raise HTTPException(status_code=400, detail="only the coin flip winner can choose")
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")
        choice = req.hand_index  # 0 = go first, 1 = go second
        if choice not in (0, 1):
            raise HTTPException(status_code=400, detail="hand_index must be 0 (go first) or 1 (go second)")
        starting_player = req.seat if choice == 0 else (1 - req.seat)
        session.game.log.append(
            f"{session.game.players[req.seat].name} chooses to go {'first' if choice == 0 else 'second'}"
        )
        _pregame_enter_mulligan(session, starting_player)
        _pregame_auto_advance(session)

    elif req.action == "mulligan_take":
        if session.pregame_phase != "mulligan":
            raise HTTPException(status_code=400, detail="not in mulligan phase")
        if req.seat != session.mulligan_offer_seat:
            raise HTTPException(status_code=400, detail="not your turn to decide on mulligan")
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")
        if not session.game.pregame_mulligan_draw(req.seat):
            raise HTTPException(status_code=400, detail="cannot take another mulligan (7 mulligans taken)")

    elif req.action == "mulligan_keep":
        if session.pregame_phase != "mulligan":
            raise HTTPException(status_code=400, detail="not in mulligan phase")
        if req.seat != session.mulligan_offer_seat:
            raise HTTPException(status_code=400, detail="not your turn to decide on mulligan")
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")
        _pregame_keep_player(session, req.seat)
        _pregame_auto_advance(session)

    elif req.action == "mulligan_bottom_select":
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
        selected = session.mulligan_bottom_selected
        if req.hand_index in selected:
            selected.remove(req.hand_index)
        else:
            selected.append(req.hand_index)

    elif req.action == "mulligan_bottom_confirm":
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

    else:
        raise HTTPException(status_code=400, detail="unknown action")

    _notify_session_change(session.id, "action")
    return _serialize_state(session, viewer_seat=req.seat)


@app.post("/api/sessions/{session_id}/run-ai")
def run_ai(session_id: str, steps: int = Query(default=1, ge=1, le=200)):
    session = _require_session(session_id)
    _save_snapshot(session)
    for _ in range(steps):
        if session.status == "finished":
            break
        if _seat_type(session, session.current_turn) != "ai":
            break
        if not _ai_step(session):
            break
        # Advance through combat before ending the turn
        _advance_phase(session)  # close precombat_main, enter combat
        for _safety in range(8):
            if session.game.current_turn_phase != "combat":
                break
            prev_step = session.game.current_step
            _advance_phase(session)
            if session.game.current_step == prev_step:
                break  # no progress; safety exit
        _end_turn(session)
        if _winner(session) is not None:
            session.status = "finished"
            break
    _notify_session_change(session.id, "action")
    return _serialize_state(session, viewer_seat=None)


@app.post("/api/sessions/{session_id}/undo")
def undo_action(session_id: str, seat: int | None = Query(default=None, ge=0, le=1)):
    session = _require_session(session_id)
    if not session.history.can_undo():
        raise HTTPException(status_code=400, detail="nothing to undo")

    snapshot = session.history.undo()
    session.game = snapshot.game
    session.current_turn = snapshot.current_turn
    session.status = snapshot.status
    session.cleanup_required_discards = snapshot.cleanup_required_discards
    session.cleanup_selected_indices = snapshot.cleanup_selected_indices
    session.untap_required_lands = snapshot.untap_required_lands
    session.untap_candidate_indices = snapshot.untap_candidate_indices
    session.untap_selected_indices = snapshot.untap_selected_indices
    session.upkeep_pay_choices = snapshot.upkeep_pay_choices
    session.upkeep_resolved_choices = snapshot.upkeep_resolved_choices
    session.island_sanctuary_pending = snapshot.island_sanctuary_pending

    _notify_session_change(session.id, "undo")
    return _serialize_state(session, viewer_seat=seat)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
