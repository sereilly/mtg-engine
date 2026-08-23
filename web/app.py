"""The FastAPI app: the one place a route is declared.

``web/app.py`` used to be the whole web layer — ~4,950 lines holding
serialization, turn driving, the AI loop, the pregame state machine, the debug
menu and the action dispatch alongside the routes. Those are
:mod:`web.serialization`, :mod:`web.game_flow`, :mod:`web.pregame`,
:mod:`web.debug_actions`, :mod:`web.actions` and the rest of the modules
imported below, layered in the order :data:`web.LAYERS` declares: a module may
only import from one beneath it, which is what keeps the split acyclic and is
guarded by ``tests/ui/test_web_layering.py``.

What is left here is what a route needs and nothing else: the app object, the
no-cache middleware, the shared-deck write gate, the join-URL builders (which
read the incoming ``Request``), and one thin handler per path.
"""

from __future__ import annotations

import ipaddress
import os
import random
import socket

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

from .deck_builder import build_random_deck
from .deck_legality import FORMATS, normalize_format
from .deck_store import (
    DeckImportError,
    DeckNotFoundError,
    fetch_moxfield_deck,
    parse_decklist_text,
)
from .schemas import (
    CreateSessionRequest,
    DeckImportRequest,
    DeckSaveRequest,
    JoinSessionRequest,
    RandomDeckRequest,
    RawStateRequest,
    RejoinSessionRequest,
    RematchRequest,
    StartGameRequest,
    VerificationRequest,
)

from .runtime import (
    AUTO_PASSES,
    CARD_BY_NAME,
    CARD_CATALOG,
    CATALOG_CARD_NAMES,
    STATIC_DIR,
    _require_session,
    _save_snapshot,
    deck_store,
    store,
    verification_store,
)
from .events import _notify_session_change, _stream_session_events
from .presence import (
    _stream_session_events_with_presence,
    mark_seat_connected,
    seat_is_connected,
)
from .seats import _loser, _rematch_human_seats, _seat_type, _winner
from engine.oracle import compile_card_oracle
from .serialization import _serialize_modes
from .catalog import (
    CATALOG_PAYLOAD,
    _deck_detail,
    _deck_summary,
    _resolve_deck_entries,
    _search_cards,
)
from .verification_report import _verification_listing, write_verification_markdown
from .pregame import _pregame_auto_advance
from .turn_steps import _end_turn
from .game_flow import _advance_phase, _ai_step
from .state_view import build_state
from .debug_actions import _apply_raw_state
from .actions import do_action

# Names other code reaches for through ``web.app`` — ``from web.app import
# _end_turn``, ``web_app._advance_phase`` — that app.py itself no longer uses.
# Re-exported so the split needs no edit outside web/; new code should import
# from the module that owns the name.
from .runtime import CARD_PATHS
from .seats import _player_has_lost
from .serialization import (
    _DISPLAY_KEYWORDS,
    _effective_keywords,
    _serialize_permanent,
    _serialize_player,
    _serialize_stack_item,
    _text_change_replacements,
)
from .catalog import CATALOG_BY_NAME
from .turn_steps import _begin_turn, _gather_upkeep_decisions


app = FastAPI(title="MTG Simulacrum")

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


# Third-party assets served from web/static/. Pinned by version and never edited
# here, so they are the one thing in the shell that *should* stay cacheable.
_VENDORED_ASSETS = frozenset({"anime.min.js"})

# The app shell — the files we author and edit, which must never be served from
# a stale browser cache. Derived from the directory rather than listed, because
# the list was the bug: it named five of the eight first-party scripts
# `index.html` loads, and `/sfx.js`, `/music.js` and `/legality.js` were quietly
# cacheable while their siblings were not. Adding the three missing names would
# have restored that gap the next time a script was added; asking the filesystem
# cannot fall behind the filesystem.
#
# Only the top level, and only markup/style/script: `images/`, `music/`, `sfx/`
# and `symbols/` are media that never change under an unchanged name, and
# no-storing them would re-download megabytes on every poll.
def _app_shell_paths() -> frozenset[str]:
    shell = {
        f"/{entry.name}"
        for entry in STATIC_DIR.iterdir()
        if entry.is_file()
        and entry.suffix in {".html", ".css", ".js"}
        and entry.name not in _VENDORED_ASSETS
    }
    # `html=True` on the static mount serves index.html at the bare root too.
    shell.add("/")
    return frozenset(shell)


_NO_CACHE_PATHS = _app_shell_paths()


@app.middleware("http")
async def _no_cache_assets(request: Request, call_next):
    response = await call_next(request)
    # Matches on `path`, so the `?v=` cache-busting query strings `index.html`
    # carries are invisible here — which is why they and this middleware do not
    # interfere, and why the `?v=` strings are not a substitute for it.
    if request.url.path in _NO_CACHE_PATHS or request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


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


def _detect_public_ipv6() -> str | None:
    """Best-effort discovery of this machine's global (public) IPv6 address.

    The UDP connect never sends a packet; it only asks the OS which source
    address it would route through, which for IPv6 is the public address.
    """
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
            sock.connect(("2001:4860:4860::8888", 80))
            raw = sock.getsockname()[0]
    except OSError:
        return None

    try:
        addr = ipaddress.IPv6Address(raw.split("%")[0])
    except ValueError:
        return None
    if not addr.is_global:
        return None
    return str(addr)


def _build_public_join_url(request: Request, session_id: str) -> str | None:
    ipv6 = _detect_public_ipv6()
    if not ipv6:
        return None

    port = request.url.port
    netloc = f"[{ipv6}]" + (f":{port}" if port else "")
    return f"{request.url.scheme}://{netloc}/index.html?session={session_id}"


@app.post("/api/decks/random")
def random_deck(req: RandomDeckRequest):
    deck, colors = build_random_deck(CARD_CATALOG, req.colors, req.seed)
    land_count = sum(1 for c in deck if c.primary_type == "land")
    return {
        "colors": colors,
        "deck": [c.name for c in deck],
        "count": len(deck),
        "land_count": land_count,
    }


@app.get("/api/cards/catalog")
def get_card_catalog():
    return {"cards": CATALOG_PAYLOAD, "formats": FORMATS}


@app.get("/api/verification")
def get_verification():
    cards, counts = _verification_listing()
    return {"cards": cards, "counts": counts, "total": len(cards)}


@app.get("/api/verification/next-untested")
def get_next_untested():
    # An auto-passed card (no abilities, or keywords only) is never offered:
    # there is nothing card-specific to check. An `equivalent` card still is —
    # that status is weaker than a check, and a real check upgrades it.
    results = verification_store.results()
    untested = [
        name for name in CATALOG_CARD_NAMES if name not in results and name not in AUTO_PASSES
    ]
    if not untested:
        raise HTTPException(status_code=404, detail="all cards have been tested")
    return {"card_name": random.choice(untested), "remaining": len(untested)}


@app.post("/api/verification")
def record_verification(req: VerificationRequest):
    try:
        entry = verification_store.record(req.card_name, req.status, req.reason or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_verification_markdown()
    return entry


@app.get("/api/decks")
def list_decks():
    # The full detail, card lists included, not just the summary: the host
    # page's deck pickers validate every deck against the *format the game will
    # be played in*, which is a different question from the one the deck was
    # saved under and so cannot be answered by the summary's stored legality.
    # Personal (localStorage) decks already carry their lists, so this is also
    # what makes the two scopes the same shape in the browser.
    return {"decks": [_deck_detail(deck) for deck in deck_store.list()]}


@app.post("/api/decks")
def create_deck(req: DeckSaveRequest):
    _require_shared_writes()
    deck = deck_store.create(
        req.name.strip() or "Untitled Deck",
        [c.model_dump() for c in req.cards],
        req.description.strip(),
        normalize_format(req.format),
        [c.model_dump() for c in req.sideboard],
        [c.model_dump() for c in req.commander],
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
            normalize_format(req.format),
            [c.model_dump() for c in req.sideboard],
            [c.model_dump() for c in req.commander],
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
            name, entries, sideboard, commander = fetch_moxfield_deck(req.url.strip())
        except DeckImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif req.text and req.text.strip():
        entries, warnings, sideboard, commander = parse_decklist_text(req.text)
        name = "Imported Deck"
    else:
        raise HTTPException(status_code=400, detail="provide a decklist text or a Moxfield URL")

    resolved = _resolve_deck_entries(entries)
    if not resolved:
        raise HTTPException(status_code=400, detail="no cards found in the deck list")
    return {
        "name": name,
        "cards": resolved,
        "sideboard": _resolve_deck_entries(sideboard),
        "commander": _resolve_deck_entries(commander),
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
    public_join_url = _build_public_join_url(request, session.id)
    return {
        "session_id": session.id,
        "join_url": join_url,
        "lan_join_url": lan_join_url,
        "public_join_url": public_join_url,
        "seat": 0,
        "state": build_state(session, viewer_seat=0),
    }


@app.post("/api/sessions/{session_id}/join")
def join_session(session_id: str, req: JoinSessionRequest, request: Request):
    session = _require_session(session_id)
    try:
        session, seat = store.join(
            session_id,
            req.guest_name,
            req.guest_deck_id,
            req.guest_colors,
            req.guest_deck_cards,
            req.guest_deck_name,
            req.guest_deck_sideboard,
            req.guest_deck_commander,
        )
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=400, detail="selected deck not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _pregame_auto_advance(session)
    _notify_session_change(session.id, "join")
    join_url = _build_join_url(request, session.id)
    lan_join_url = _build_lan_join_url(request, session.id)
    public_join_url = _build_public_join_url(request, session.id)
    return {
        "session_id": session.id,
        "join_url": join_url,
        "lan_join_url": lan_join_url,
        "public_join_url": public_join_url,
        "seat": seat,
        "state": build_state(session, viewer_seat=seat),
    }


@app.post("/api/sessions/{session_id}/rejoin")
def rejoin_session(session_id: str, req: RejoinSessionRequest, request: Request):
    """Take a seat back in a game already in progress — same name, same deck,
    same board; nothing is rebuilt. The seat must be a joined human seat with
    no live event stream (its player is gone), so a connected player cannot be
    displaced. Before the game starts the path is ``/join`` instead: a lobby
    player who vanishes is unseated and their slot is simply open again."""
    session = _require_session(session_id)
    if not session.game_started:
        raise HTTPException(status_code=400, detail="the game has not started — join it instead")
    if req.seat >= len(session.game.players):
        raise HTTPException(status_code=400, detail="seat out of range for this session")
    if session.seat_types.get(req.seat) != "human":
        raise HTTPException(status_code=400, detail="an AI seat cannot be rejoined")
    if req.seat not in session.joined_seats:
        raise HTTPException(status_code=400, detail="seat has not joined this session")
    if seat_is_connected(session_id, req.seat):
        raise HTTPException(
            status_code=400,
            detail=f"{session.game.players[req.seat].name} is still connected",
        )
    mark_seat_connected(session_id, req.seat)
    return {
        "session_id": session.id,
        "join_url": _build_join_url(request, session.id),
        "lan_join_url": _build_lan_join_url(request, session.id),
        "public_join_url": _build_public_join_url(request, session.id),
        "seat": req.seat,
        "state": build_state(session, viewer_seat=req.seat),
    }


@app.post("/api/sessions/{session_id}/start")
def start_session(session_id: str, req: StartGameRequest):
    session = _require_session(session_id)
    try:
        store.start(session, req.seat)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _pregame_auto_advance(session)
    _notify_session_change(session.id, "start")
    return build_state(session, viewer_seat=req.seat)


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
        # The previous game's loser, not a coin flip, chooses who plays first.
        # Capture it before restart() resets the board (and the life totals).
        loser_seat = _loser(session)
        store.restart(session, first_chooser=loser_seat)
        _pregame_auto_advance(session)
        _notify_session_change(session.id, "rematch_start")
    else:
        _notify_session_change(session.id, "rematch_vote")

    return build_state(session, viewer_seat=req.seat)


@app.post("/api/sessions/{session_id}/restart")
def restart_match(session_id: str, req: RematchRequest):
    """Restart the current match in-place (from the Settings panel).

    Unlike ``/rematch`` (which requires the game to be finished and both humans to
    agree), this immediately rebuilds the same board — same players, seats, and
    decks — for a new game. All connected seats are notified via the
    ``match_restart`` stream reason so every client can announce the reset.
    """
    session = _require_session(session_id)
    if req.seat not in session.joined_seats:
        raise HTTPException(status_code=400, detail="seat has not joined")

    store.restart(session)
    _pregame_auto_advance(session)
    _notify_session_change(session.id, "match_restart")
    return build_state(session, viewer_seat=req.seat)


@app.get("/api/sessions/{session_id}/events")
async def stream_session_events(session_id: str, seat: int | None = Query(default=None, ge=0)):
    session = _require_session(session_id)
    # A seat on the stream is how the server knows that player is connected:
    # this stream closing, and staying closed past the presence grace period,
    # is what marks the seat disconnected (web/presence.py). A spectator sends
    # no seat and is nobody's presence.
    if seat is not None and seat < len(session.game.players):
        stream = _stream_session_events_with_presence(session_id, seat)
    else:
        stream = _stream_session_events(session_id)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/sessions/{session_id}/state")
def get_state(session_id: str, seat: int | None = Query(default=None, ge=0)):
    session = _require_session(session_id)
    if seat is not None and seat >= len(session.game.players):
        raise HTTPException(status_code=400, detail="seat out of range for this session")
    return build_state(session, viewer_seat=seat)


@app.get("/api/sessions/{session_id}/card_target_spec")
def get_card_target_spec(
    session_id: str,
    card_name: str = Query(...),
    seat: int = Query(..., ge=0),
):
    """The cast target spec (kind + enumerated legal targets) for a card cast by
    ``seat`` in this session. Hand cards already carry this in the serialized
    state; this lets the debug "cast for free" flow — whose card comes from a
    session-less catalog search — drive the same backend-authoritative targeting."""
    session = _require_session(session_id)
    if seat >= len(session.game.players):
        raise HTTPException(status_code=400, detail="seat out of range for this session")
    card = CARD_BY_NAME.get(card_name.strip().casefold())
    if card is None:
        raise HTTPException(status_code=404, detail="card not found")
    return {
        "name": card.name,
        "target_spec": session.game.cast_target_spec(seat, card),
        "modes": _serialize_modes(card, session.game, seat),
        # Whether more than one of those modes may be chosen (CR 700.2d). The
        # client fetches the spec before it opens the mode prompt, so this is
        # where the prompt learns to be a multi-select.
        "modes_at_least": compile_card_oracle(card).modes_at_least,
    }


@app.post("/api/sessions/{session_id}/raw-state")
def set_raw_state(session_id: str, req: RawStateRequest):
    session = _require_session(session_id)
    _apply_raw_state(session, req.state)
    _notify_session_change(session.id, "raw_state")
    return build_state(session, viewer_seat=req.seat)


@app.get("/api/cards/search")
def search_cards(
    query: str = Query(default=""),
    limit: int = Query(default=16, ge=1, le=50),
    untested_only: bool = Query(default=False),
):
    return {"cards": _search_cards(query, limit, untested_only=untested_only)}


# The single game-action endpoint. Its 70-branch dispatch over ActionKind is
# web.actions.do_action; the path is declared here so app.py stays the one
# place a route is registered.
app.post("/api/sessions/{session_id}/action")(do_action)


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
    return build_state(session, viewer_seat=None)


@app.post("/api/sessions/{session_id}/undo")
def undo_action(session_id: str, seat: int | None = Query(default=None, ge=0)):
    session = _require_session(session_id)
    if seat is not None and seat >= len(session.game.players):
        raise HTTPException(status_code=400, detail="seat out of range for this session")
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
    session.optional_trigger_choices = snapshot.optional_trigger_choices
    session.optional_trigger_resolved = snapshot.optional_trigger_resolved
    session.upkeep_mana_prevention_choices = snapshot.upkeep_mana_prevention_choices
    session.upkeep_mana_prevention_resolved = snapshot.upkeep_mana_prevention_resolved
    session.upkeep_decisions_deferred = snapshot.upkeep_decisions_deferred
    session.island_sanctuary_pending = snapshot.island_sanctuary_pending
    session.paused_beginning_phase = snapshot.paused_beginning_phase

    _notify_session_change(session.id, "undo")
    return build_state(session, viewer_seat=seat)


@app.get("/api/music")
def list_music():
    """Return the available background-music tracks (mp3s in static/music)."""
    music_dir = STATIC_DIR / "music"
    if not music_dir.is_dir():
        return {"tracks": []}
    tracks = sorted(
        f"/music/{p.name}" for p in music_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".mp3"
    )
    return {"tracks": tracks}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
