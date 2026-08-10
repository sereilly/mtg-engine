"""The card pool and the decks built from it, as the client sees them.

What a client needs *before* a session exists: the browsable catalog payload
(built once at import, like the pool it derives from), card search, and turning
a saved or personal decklist into resolved entries with a colour/type summary.
"""

from __future__ import annotations

from engine.card_loader import load_cards
from engine.classifier import classify_card

from .deck_legality import normalize_format, validate_deck
from .deck_store import deck_commander, deck_sideboard

from .runtime import CARD_PATHS, CARD_SEARCH_ORDER, verification_store
from .serialization import _serialize_card_summary


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


def _build_set_memberships() -> dict[str, list[dict]]:
    """Map card name -> every set it was printed in, in printing order.

    ``CARD_CATALOG`` dedupes reprints by name (first printing wins), so the
    catalog card's own ``set``/``image_uri`` only reflect the first printing.
    The deck editor's set filter needs full membership — a Beta filter should
    show all of Beta, not just the two cards missing from Alpha — and each
    printing carries its own art so the UI can show the filtered set's version.
    """
    memberships: dict[str, list[dict]] = {}
    for path in CARD_PATHS:
        for card in load_cards(path):
            raw = card.raw if isinstance(card.raw, dict) else {}
            code = raw.get("set")
            if not code:
                continue
            printings = memberships.setdefault(card.name, [])
            if all(printing["code"] != code for printing in printings):
                image_uris = raw.get("image_uris") if isinstance(raw.get("image_uris"), dict) else {}
                printings.append(
                    {
                        "code": code,
                        "name": raw.get("set_name"),
                        "image_uri": image_uris.get("normal"),
                        "large_image_uri": image_uris.get("large"),
                        "scryfall_uri": raw.get("scryfall_uri"),
                    }
                )
    return memberships


def _build_catalog_payload() -> list[dict]:
    memberships = _build_set_memberships()
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
                "set": raw.get("set"),
                "set_name": raw.get("set_name"),
                "sets": memberships.get(card.name, []),
                "colors": list(card.colors),
                "color_identity": list(card.color_identity),
                "keywords": list(card.keywords),
                "power": raw.get("power"),
                "toughness": raw.get("toughness"),
                "rarity": raw.get("rarity"),
                "legalities": raw.get("legalities") or {},
                "image_uri": image_uris.get("normal"),
                "large_image_uri": image_uris.get("large"),
                "scryfall_uri": raw.get("scryfall_uri"),
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
    fmt = normalize_format(deck.get("format"))
    legality = validate_deck(
        deck.get("cards", []), fmt, CATALOG_BY_NAME, deck_sideboard(deck), deck_commander(deck),
    )
    return {
        "id": deck["id"],
        "name": deck["name"],
        "description": deck.get("description", ""),
        "format": fmt,
        "legality": legality,
        # CR 407.3: the ante cards anywhere in this deck. The game-setup deck
        # pickers refuse a deck that has any unless the host is playing for ante.
        "ante_names": legality.get("ante_names", []),
        "card_count": sum(e["count"] for e in entries),
        "colors": [c for c in ("W", "U", "B", "R", "G") if c in colors],
        "unsupported_count": sum(e["count"] for e in entries if e["status"] == "unsupported"),
        "unknown_count": sum(e["count"] for e in entries if e["status"] == "unknown"),
        "sideboard_count": sum(e["count"] for e in deck_sideboard(deck)),
        "commander_count": sum(e["count"] for e in deck_commander(deck)),
        "updated_at": deck.get("updated_at"),
        # Decks served from the on-disk store are the shared pool. Personal decks
        # live in the client's browser and are never returned by these endpoints.
        "scope": "shared",
    }


def _deck_detail(deck: dict) -> dict:
    detail = _deck_summary(deck)
    detail["cards"] = _resolve_deck_entries(deck.get("cards", []))
    detail["sideboard"] = _resolve_deck_entries(deck_sideboard(deck))
    detail["commander"] = _resolve_deck_entries(deck_commander(deck))
    return detail
