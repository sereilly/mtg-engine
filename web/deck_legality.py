"""MTG constructed format legality / banlist rules.

Per-card legality comes straight from Scryfall's ``legalities`` map, which is
already loaded on every catalog card (``CardDefinition.raw["legalities"]``).
This module layers the *deck-construction* rules on top of that: minimum/maximum
deck size, the four-of copy limit, singleton formats, and the restricted list.

The ``FORMATS`` table is the single source of truth for the rule parameters. It
is shipped to the browser verbatim in the card-catalog payload, where
``web/static/legality.js`` runs the identical checks for personal (localStorage)
decks. Keep the two validators in step when changing the rules.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Each format: `scryfall_key` is the key to read out of a card's `legalities`
# map (None means "no legality checking"); `min_deck`/`max_deck` bound the deck
# size; `max_copies` is the per-card limit; `singleton` forces a hard 1-of.
FORMATS: list[dict[str, Any]] = [
    {"key": "casual", "label": "Casual (no restrictions)", "scryfall_key": None,
     "min_deck": 0, "max_deck": None, "max_copies": 99, "singleton": False},
    {"key": "standard", "label": "Standard", "scryfall_key": "standard",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "singleton": False},
    {"key": "pioneer", "label": "Pioneer", "scryfall_key": "pioneer",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "singleton": False},
    {"key": "modern", "label": "Modern", "scryfall_key": "modern",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "singleton": False},
    {"key": "legacy", "label": "Legacy", "scryfall_key": "legacy",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "singleton": False},
    {"key": "vintage", "label": "Vintage", "scryfall_key": "vintage",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "singleton": False},
    {"key": "pauper", "label": "Pauper", "scryfall_key": "pauper",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "singleton": False},
    {"key": "premodern", "label": "Premodern", "scryfall_key": "premodern",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "singleton": False},
    {"key": "oldschool", "label": "Old School 93/94", "scryfall_key": "oldschool",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "singleton": False},
    {"key": "commander", "label": "Commander", "scryfall_key": "commander",
     "min_deck": 100, "max_deck": 100, "max_copies": 1, "singleton": True},
]

FORMATS_BY_KEY: dict[str, dict[str, Any]] = {f["key"]: f for f in FORMATS}
DEFAULT_FORMAT = "casual"


def normalize_format(key: str | None) -> str:
    """Coerce a (possibly stale/unknown) format key to a known one."""
    if key and key in FORMATS_BY_KEY:
        return key
    return DEFAULT_FORMAT


def card_status(card: Mapping[str, Any], fmt: Mapping[str, Any]) -> str:
    """Legality of a single card in a format.

    Returns one of ``legal`` / ``restricted`` / ``banned`` / ``not_legal``,
    read straight from the card's Scryfall ``legalities`` map. A format with no
    ``scryfall_key`` (Casual) treats every card as legal.
    """
    key = fmt.get("scryfall_key")
    if key is None:
        return "legal"
    legalities = card.get("legalities") if isinstance(card, Mapping) else None
    value = (legalities or {}).get(key)
    if value in ("legal", "restricted", "banned"):
        return value
    return "not_legal"


def _is_basic_land(card: Mapping[str, Any]) -> bool:
    type_line = str(card.get("type_line") or "").lower()
    return "basic" in type_line and "land" in type_line


def _any_number_allowed(card: Mapping[str, Any]) -> bool:
    # Cards like Relentless Rats / Shadowborn Apostle opt out of the four-of rule.
    return "a deck can have any number of cards named" in str(card.get("oracle_text") or "").lower()


def effective_max_copies(card: Mapping[str, Any], fmt: Mapping[str, Any], status: str) -> int | None:
    """Copy limit for a legal/restricted card, or ``None`` for unlimited."""
    if _is_basic_land(card) or _any_number_allowed(card):
        return None
    limit = int(fmt["max_copies"])
    if status == "restricted":
        limit = min(limit, 1)
    if fmt.get("singleton"):
        limit = min(limit, 1)
    return limit


def validate_deck(
    entries: Iterable[Mapping[str, Any]],
    fmt_key: str | None,
    catalog_by_name: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Check a deck against a format's construction rules.

    ``catalog_by_name`` maps casefolded card name -> catalog payload entry (the
    dict built by ``_build_catalog_payload``, which carries ``legalities``).
    Cards absent from the catalog are skipped here — they are surfaced
    separately as "not in catalog" and shouldn't be double-flagged as illegal.

    Returns ``{"format", "legal", "problems": [str], "illegal_names": [str]}``.
    """
    fmt = FORMATS_BY_KEY[normalize_format(fmt_key)]
    result: dict[str, Any] = {
        "format": fmt["key"],
        "legal": True,
        "problems": [],
        "illegal_names": [],
    }
    if fmt["scryfall_key"] is None:
        return result

    problems: list[str] = result["problems"]
    illegal: list[str] = result["illegal_names"]
    label = fmt["label"]
    total = 0
    for entry in entries:
        name = str(entry.get("name", "")).strip()
        count = int(entry.get("count", 0) or 0)
        if not name or count <= 0:
            continue
        total += count
        card = catalog_by_name.get(name.casefold())
        if card is None:
            continue
        display = card.get("name", name)
        status = card_status(card, fmt)
        if status == "banned":
            problems.append(f"{display} is banned in {label}.")
            illegal.append(display)
            continue
        if status == "not_legal":
            problems.append(f"{display} is not legal in {label}.")
            illegal.append(display)
            continue
        limit = effective_max_copies(card, fmt, status)
        if limit is not None and count > limit:
            if status == "restricted":
                problems.append(f"{display} is restricted to 1 copy in {label} (deck has {count}).")
            elif limit == 1:
                problems.append(f"{display}: {count} copies exceed the 1-of limit in {label}.")
            else:
                problems.append(f"{display}: {count} copies exceed the {limit}-copy limit in {label}.")
            illegal.append(display)

    if total < fmt["min_deck"]:
        problems.append(f"Deck has {total} card(s); {label} requires at least {fmt['min_deck']}.")
    if fmt["max_deck"] is not None and total > fmt["max_deck"]:
        problems.append(f"Deck has {total} card(s); {label} allows at most {fmt['max_deck']}.")

    result["legal"] = not problems
    return result
