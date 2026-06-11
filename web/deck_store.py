from __future__ import annotations

import json
import re
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path


_DECKLIST_LINE = re.compile(r"^(?:(\d+)\s*[xX]?\s+)?(.+?)$")
_SET_SUFFIX = re.compile(r"\s+\((?:[A-Za-z0-9]{2,6})\)(?:\s+[\w\-★]+)?\s*$")
_SECTION_HEADERS = {"deck", "mainboard", "main", "commander", "companion"}
_STOP_HEADERS = {"sideboard", "maybeboard", "considering", "tokens"}

_MOXFIELD_URL = re.compile(r"moxfield\.com/decks/([A-Za-z0-9_-]+)")
_MOXFIELD_API = "https://api2.moxfield.com/v3/decks/all/{deck_id}"


class DeckNotFoundError(KeyError):
    pass


class DeckImportError(ValueError):
    pass


class DeckStore:
    """Persists decks as JSON files in a directory.

    Deck shape: {"id": str, "name": str, "cards": [{"name": str, "count": int}],
                 "created_at": float, "updated_at": float}
    """

    def __init__(self, decks_dir: Path):
        self.decks_dir = decks_dir
        self.decks_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, deck_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "", deck_id)
        if not safe or safe != deck_id:
            raise DeckNotFoundError(deck_id)
        return self.decks_dir / f"{safe}.json"

    def list(self) -> list[dict]:
        decks = []
        for path in sorted(self.decks_dir.glob("*.json")):
            try:
                deck = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(deck, dict) and deck.get("id") and deck.get("name") is not None:
                decks.append(deck)
        decks.sort(key=lambda d: str(d.get("name", "")).casefold())
        return decks

    def get(self, deck_id: str) -> dict:
        path = self._path(deck_id)
        if not path.exists():
            raise DeckNotFoundError(deck_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def create(self, name: str, cards: list[dict]) -> dict:
        deck = {
            "id": secrets.token_urlsafe(8).replace("-", "a").replace("_", "b"),
            "name": name,
            "cards": _normalize_cards(cards),
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        self._path(deck["id"]).write_text(json.dumps(deck, indent=2), encoding="utf-8")
        return deck

    def update(self, deck_id: str, name: str, cards: list[dict]) -> dict:
        deck = self.get(deck_id)
        deck["name"] = name
        deck["cards"] = _normalize_cards(cards)
        deck["updated_at"] = time.time()
        self._path(deck_id).write_text(json.dumps(deck, indent=2), encoding="utf-8")
        return deck

    def delete(self, deck_id: str) -> None:
        path = self._path(deck_id)
        if not path.exists():
            raise DeckNotFoundError(deck_id)
        path.unlink()


def _normalize_cards(cards: list[dict]) -> list[dict]:
    merged: dict[str, int] = {}
    order: list[str] = []
    for entry in cards:
        name = str(entry.get("name", "")).strip()
        count = int(entry.get("count", 0))
        if not name or count <= 0:
            continue
        if name not in merged:
            merged[name] = 0
            order.append(name)
        merged[name] += count
    return [{"name": name, "count": merged[name]} for name in order]


def parse_decklist_text(text: str) -> tuple[list[dict], list[str]]:
    """Parse a pasted decklist into [(name, count)] entries.

    Accepts common formats: "4 Lightning Bolt", "4x Lightning Bolt",
    "Lightning Bolt", MTGA/Moxfield exports with set codes ("4 Bolt (LEA) 123").
    Lines after a Sideboard/Maybeboard header are ignored.
    Returns (entries, warnings).
    """
    entries: list[dict] = []
    warnings: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("//", "#")):
            continue
        header = line.rstrip(":").casefold()
        if header in _STOP_HEADERS:
            break
        if header in _SECTION_HEADERS:
            continue
        match = _DECKLIST_LINE.match(line)
        if not match:
            warnings.append(f"Could not parse line: {raw_line}")
            continue
        count = int(match.group(1)) if match.group(1) else 1
        name = _SET_SUFFIX.sub("", match.group(2)).strip()
        if not name:
            warnings.append(f"Could not parse line: {raw_line}")
            continue
        entries.append({"name": name, "count": count})
    return _normalize_cards(entries), warnings


def fetch_moxfield_deck(url: str) -> tuple[str, list[dict]]:
    """Fetch a public Moxfield deck. Returns (deck_name, entries)."""
    match = _MOXFIELD_URL.search(url)
    if not match:
        raise DeckImportError("Not a valid Moxfield deck URL (expected moxfield.com/decks/...)")
    deck_id = match.group(1)

    request = urllib.request.Request(
        _MOXFIELD_API.format(deck_id=deck_id),
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise DeckImportError("Moxfield deck not found (is it public?)") from exc
        raise DeckImportError(f"Moxfield request failed (HTTP {exc.code})") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DeckImportError(f"Could not reach Moxfield: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DeckImportError("Moxfield returned an unexpected response") from exc

    name = str(payload.get("name") or "Imported Deck")
    entries: list[dict] = []

    boards = payload.get("boards")
    if isinstance(boards, dict):
        mainboard = boards.get("mainboard")
        cards = mainboard.get("cards") if isinstance(mainboard, dict) else None
        if isinstance(cards, dict):
            for item in cards.values():
                if not isinstance(item, dict):
                    continue
                card = item.get("card")
                card_name = card.get("name") if isinstance(card, dict) else None
                quantity = item.get("quantity", 0)
                if card_name and isinstance(quantity, int) and quantity > 0:
                    entries.append({"name": str(card_name), "count": quantity})

    if not entries and isinstance(payload.get("mainboard"), dict):
        # Older API shape: top-level mainboard dict keyed by card name.
        for card_name, item in payload["mainboard"].items():
            quantity = item.get("quantity", 0) if isinstance(item, dict) else 0
            if isinstance(quantity, int) and quantity > 0:
                entries.append({"name": str(card_name), "count": quantity})

    if not entries:
        raise DeckImportError("No mainboard cards found in the Moxfield deck")

    return name, _normalize_cards(entries)
