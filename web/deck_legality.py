"""MTG constructed format legality / banlist rules.

Per-card legality comes straight from Scryfall's ``legalities`` map, which is
already loaded on every catalog card (``CardDefinition.raw["legalities"]``).
This module layers the *deck-construction* rules on top of that: minimum/maximum
deck size (CR 100.2a, 100.5), the four-of copy limit counted across deck *and*
sideboard (CR 100.2a, 100.4a), the fifteen-card sideboard cap (CR 100.4a),
singleton formats, and the restricted list. Basic lands are exempt from the copy
limit (CR 100.2a), as are cards that opt out in their own text.

The ``FORMATS`` table is the single source of truth for the rule parameters. It
is shipped to the browser verbatim in the card-catalog payload, where
``web/static/legality.js`` runs the identical checks for personal (localStorage)
decks. Keep the two validators in step when changing the rules.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Each format: `scryfall_key` is the key to read out of a card's `legalities`
# map (None means "no legality checking"); `min_deck`/`max_deck` bound the deck
# size; `max_copies` is the per-card limit (counted across deck + sideboard);
# `max_sideboard` caps the sideboard (None = unchecked, 0 = no sideboard at all);
# `singleton` forces a hard 1-of.
FORMATS: list[dict[str, Any]] = [
    {"key": "casual", "label": "Casual (no restrictions)", "scryfall_key": None,
     "min_deck": 0, "max_deck": None, "max_copies": 99, "max_sideboard": None, "singleton": False},
    {"key": "standard", "label": "Standard", "scryfall_key": "standard",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False},
    {"key": "pioneer", "label": "Pioneer", "scryfall_key": "pioneer",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False},
    {"key": "modern", "label": "Modern", "scryfall_key": "modern",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False},
    {"key": "legacy", "label": "Legacy", "scryfall_key": "legacy",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False},
    {"key": "vintage", "label": "Vintage", "scryfall_key": "vintage",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False},
    {"key": "pauper", "label": "Pauper", "scryfall_key": "pauper",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False},
    {"key": "premodern", "label": "Premodern", "scryfall_key": "premodern",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False},
    {"key": "oldschool", "label": "Old School 93/94", "scryfall_key": "oldschool",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False},
    # CR 903.5a: exactly 100 cards; CR 903.5e: Commander games do not use sideboards.
    {"key": "commander", "label": "Commander", "scryfall_key": "commander",
     "min_deck": 100, "max_deck": 100, "max_copies": 1, "max_sideboard": 0, "singleton": True},
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


def _tally(entries: Iterable[Mapping[str, Any]] | None) -> tuple[dict[str, int], int]:
    """Sum an entry list into {casefolded name -> count} plus a grand total."""
    counts: dict[str, int] = {}
    total = 0
    for entry in entries or ():
        name = str(entry.get("name", "")).strip()
        count = int(entry.get("count", 0) or 0)
        if not name or count <= 0:
            continue
        counts[name.casefold()] = counts.get(name.casefold(), 0) + count
        total += count
    return counts, total


def validate_deck(
    entries: Iterable[Mapping[str, Any]],
    fmt_key: str | None,
    catalog_by_name: Mapping[str, Mapping[str, Any]],
    sideboard: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check a deck (and its sideboard) against a format's construction rules.

    ``catalog_by_name`` maps casefolded card name -> catalog payload entry (the
    dict built by ``_build_catalog_payload``, which carries ``legalities``).
    Cards absent from the catalog are skipped here — they are surfaced
    separately as "not in catalog" and shouldn't be double-flagged as illegal.

    Per CR 100.4a the copy limit applies to the combined deck and sideboard,
    while the minimum/maximum deck size (CR 100.2a, 100.5) counts the main deck
    only.

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
    main_counts, main_total = _tally(entries)
    side_counts, side_total = _tally(sideboard)

    # Main-deck order first, then sideboard-only cards, so messages read in the
    # order the user built the deck.
    names = list(main_counts) + [n for n in side_counts if n not in main_counts]
    for key in names:
        card = catalog_by_name.get(key)
        if card is None:
            continue
        display = card.get("name", key)
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
        in_side = side_counts.get(key, 0)
        count = main_counts.get(key, 0) + in_side
        if limit is not None and count > limit:
            # CR 100.4a — name the sideboard when it contributes to the overage.
            where = " across deck and sideboard" if in_side and main_counts.get(key) else ""
            if status == "restricted":
                problems.append(f"{display} is restricted to 1 copy in {label} (deck has {count}{where}).")
            elif limit == 1:
                problems.append(f"{display}: {count} copies{where} exceed the 1-of limit in {label}.")
            else:
                problems.append(f"{display}: {count} copies{where} exceed the {limit}-copy limit in {label}.")
            illegal.append(display)

    if main_total < fmt["min_deck"]:
        problems.append(f"Deck has {main_total} card(s); {label} requires at least {fmt['min_deck']}.")
    if fmt["max_deck"] is not None and main_total > fmt["max_deck"]:
        problems.append(f"Deck has {main_total} card(s); {label} allows at most {fmt['max_deck']}.")

    max_side = fmt.get("max_sideboard")
    if max_side is not None and side_total > max_side:
        if max_side == 0:
            problems.append(f"{label} does not use a sideboard (sideboard has {side_total} card(s)).")
        else:
            problems.append(f"Sideboard has {side_total} card(s); {label} allows at most {max_side}.")

    result["legal"] = not problems
    return result
