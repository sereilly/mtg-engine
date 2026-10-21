"""Process-wide ground every other web module stands on.

The card pool and the three stores are built once at import and shared by every
request; :func:`_require_session` and :func:`_save_snapshot` are the two things
every layer does to a session. Nothing here imports another ``web`` module, so
this is the bottom of the layering and cannot take part in a cycle.
"""

from __future__ import annotations

import functools
from pathlib import Path
from threading import Lock, RLock

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from engine.card_loader import load_cards, manifest_set_paths
from engine.behaviour_signature import peers_by_card
from engine.faces import face_cards, name_aliases
from engine.oracle import simple_card_keywords

from .deck_store import DeckStore
from .session_store import Session, SessionStore
from .verification_store import VerificationStore


ROOT = Path(__file__).resolve().parent.parent

# Every set JSON that makes up the card pool, in printing order, read from
# cards/manifest.json — the single registry of which sets the engine ships.
# Adding a set means ingesting it and appending one manifest entry, not editing
# this list and the five other copies of it that used to exist. CARD_CATALOG and
# every store below derive from it, loaded once at process startup. Reprints
# dedupe to one card (first printing wins), so Beta/Unlimited contribute only
# their two cards missing from Alpha.
CARD_PATHS = manifest_set_paths()

DECKS_DIR = ROOT / "decks"

VERIFICATION_PATH = ROOT / "card_verification.json"

VERIFICATION_MD_PATH = ROOT / "CARD_VERIFICATION.md"

STATIC_DIR = Path(__file__).resolve().parent / "static"

CARD_CATALOG = load_cards(CARD_PATHS)

CARD_BY_NAME = {card.name.casefold(): card for card in CARD_CATALOG}
# A split card answers to more spellings than the one it is printed with
# (CR 709.4a gives it two names, and a decklist may write either, or both with
# one slash). Each finds the *card* — never shadowing a card that really is
# called that, which is what ``setdefault`` is for.
for _card in CARD_CATALOG:
    for _alias in name_aliases(_card):
        CARD_BY_NAME.setdefault(_alias.casefold(), _card)

# The halves of the pool's split cards, by their own names: the **spell** a
# name names, where ``CARD_BY_NAME`` answers the card. A cast names a half
# (CR 709.3), so a route handed a spell name — the cast-spec endpoint, the
# Debug Menu's free cast — asks :func:`spell_by_name`.
SPELL_BY_NAME = {
    face.name.casefold(): face
    for card in CARD_CATALOG
    for face in face_cards(card)
}


def spell_by_name(name: str):
    """The spell *name* names: a split card's half by the half's name, and
    otherwise the catalog card (which for a split card's whole spelling is the
    card itself — not a spell, and the cast path says so). None if unknown."""
    key = str(name).strip().casefold()
    return SPELL_BY_NAME.get(key) or CARD_BY_NAME.get(key)


CARD_SEARCH_ORDER = sorted(CARD_CATALOG, key=lambda card: card.name)

# Unique catalog card names in display order (some cards share a name across printings).
CATALOG_CARD_NAMES = list(dict.fromkeys(card.name for card in CARD_SEARCH_ORDER))

# Behavioural peers, computed once at startup like the catalog itself: it is a
# pure function of the card pool, and recomputing it per request would compile
# every card's oracle program again.
BEHAVIOUR_PEERS = peers_by_card(CARD_CATALOG)

# The cards the verification tracker auto-passes, name -> the keyword abilities
# that are the whole of the card's printed text (empty for a card with no
# abilities at all). Also a pure function of the pool, computed once for the
# same reason. See engine.oracle.simple_card_keywords for the criterion.
AUTO_PASSES: dict[str, tuple[str, ...]] = {
    card.name: keywords
    for card in CARD_SEARCH_ORDER
    if (keywords := simple_card_keywords(card)) is not None
}

deck_store = DeckStore(DECKS_DIR)

verification_store = VerificationStore(VERIFICATION_PATH)

store = SessionStore(catalog=CARD_CATALOG, deck_store=deck_store)


def _save_snapshot(session: Session) -> None:
    session.history.save(session)


def _require_session(session_id: str) -> Session:
    try:
        return store.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


#: One lock per session id, taken by every route that reads or moves that
#: session's game (:func:`one_request_at_a_time`).
_SESSION_LOCKS: dict[str, RLock] = {}
_SESSION_LOCKS_GUARD = Lock()


def session_lock(session_id: str) -> RLock:
    """The lock a request about *session_id* holds while it runs."""
    with _SESSION_LOCKS_GUARD:
        return _SESSION_LOCKS.setdefault(session_id, RLock())


def one_request_at_a_time(endpoint):
    """Run a session route under that session's lock, and hand FastAPI a
    payload that no later request can change.

    Found at Torment's Phase 5 (2026-10-21) by reading the browser's own
    responses: a ``GET …/state`` answered "declare blockers" with a log that
    already ended "Declare blockers step complete", at the length of the
    state *after* the action that leaves the step — a payload of two moments.
    The log is the client's version guard, so it rendered as current; the
    client's automatic sender for a stalled declare-blockers step decided on
    it and sent ``next_phase``, and the server applied that to the game it
    actually had, which was the player's second main phase — left unplayed.

    Two ways a payload was torn, and this closes both:

    * the routes are plain ``def`` functions, run in a thread pool, so a read
      and an action for the same game ran at the same time and the state was
      read part-way through the action — the lock makes a read see the game
      between actions only, and two actions never interleave;
    * FastAPI encodes a route's return value *after* the route returns, and
      the state payload holds the game's own log list (``"log":
      session.game.log``), so the next action's lines were appended to a
      response already built — encoding under the lock takes the snapshot.

    Measured in-process (a driver sending the browser's automatic actions,
    two readers polling the state): 25 of ~500 reads were of no state between
    actions before, 0 after.

    An ``RLock``, so a route that reaches another locked route's code on the
    same thread does not wait on itself. The event stream is not wrapped: it
    lives for the whole game and reads no game state.
    """

    @functools.wraps(endpoint)
    def serialized(session_id: str, *args, **kwargs):
        with session_lock(session_id):
            result = endpoint(session_id, *args, **kwargs)
            if isinstance(result, (dict, list)):
                result = jsonable_encoder(result)
            return result

    serialized.holds_session_lock = True
    return serialized
