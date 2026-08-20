"""Process-wide ground every other web module stands on.

The card pool and the three stores are built once at import and shared by every
request; :func:`_require_session` and :func:`_save_snapshot` are the two things
every layer does to a session. Nothing here imports another ``web`` module, so
this is the bottom of the layering and cannot take part in a cycle.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from engine.card_loader import load_cards, manifest_set_paths
from engine.behaviour_signature import peers_by_card
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
