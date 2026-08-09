"""MTG constructed format legality / banlist rules.

Per-card legality comes straight from Scryfall's ``legalities`` map, which is
already loaded on every catalog card (``CardDefinition.raw["legalities"]``).
This module layers the *deck-construction* rules on top of that: minimum/maximum
deck size (CR 100.2a, 100.5), the four-of copy limit counted across deck *and*
sideboard (CR 100.2a, 100.4a), the fifteen-card sideboard cap (CR 100.4a),
singleton formats, and the restricted list. Basic lands are exempt from the copy
limit (CR 100.2a), as are cards that opt out in their own text.

One rule here is format-independent: CR 407.3 bars the "Remove this card from
your deck before playing if you're not playing for ante" cards from a deck or
sideboard unless the game is actually played for ante. It is checked even for
Casual (which has no banlist at all), and the offending names are reported
separately as ``ante_names`` so the game-setup UI can gate deck *selection* on
the host's "Playing for ante" setting rather than only warn about it.

The ``FORMATS`` table is the single source of truth for the rule parameters. It
is shipped to the browser verbatim in the card-catalog payload, where
``web/static/legality.js`` runs the identical checks for personal (localStorage)
decks. Keep the two validators in step when changing the rules.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from engine.ante import is_ante_card

# Each format: `scryfall_key` is the key to read out of a card's `legalities`
# map (None means "no legality checking"); `min_deck`/`max_deck` bound the deck
# (library) size; `max_copies` is the per-card limit (counted across deck +
# sideboard + commander); `max_sideboard` caps the sideboard (None = unchecked,
# 0 = no sideboard at all); `singleton` forces a hard 1-of; `min_commander`/
# `max_commander` bound the command zone (0/0 = format has no command zone).
FORMATS: list[dict[str, Any]] = [
    {"key": "casual", "label": "Casual (no restrictions)", "scryfall_key": None,
     "min_deck": 0, "max_deck": None, "max_copies": 99, "max_sideboard": None, "singleton": False,
     "min_commander": 0, "max_commander": 0},
    {"key": "standard", "label": "Standard", "scryfall_key": "standard",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False,
     "min_commander": 0, "max_commander": 0},
    {"key": "pioneer", "label": "Pioneer", "scryfall_key": "pioneer",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False,
     "min_commander": 0, "max_commander": 0},
    {"key": "modern", "label": "Modern", "scryfall_key": "modern",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False,
     "min_commander": 0, "max_commander": 0},
    {"key": "legacy", "label": "Legacy", "scryfall_key": "legacy",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False,
     "min_commander": 0, "max_commander": 0},
    {"key": "vintage", "label": "Vintage", "scryfall_key": "vintage",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False,
     "min_commander": 0, "max_commander": 0},
    {"key": "pauper", "label": "Pauper", "scryfall_key": "pauper",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False,
     "min_commander": 0, "max_commander": 0},
    {"key": "premodern", "label": "Premodern", "scryfall_key": "premodern",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False,
     "min_commander": 0, "max_commander": 0},
    {"key": "oldschool", "label": "Old School 93/94", "scryfall_key": "oldschool",
     "min_deck": 60, "max_deck": None, "max_copies": 4, "max_sideboard": 15, "singleton": False,
     "min_commander": 0, "max_commander": 0},
    # CR 903.5a: a 99-card library plus exactly 1 designated commander in the
    # command zone (100 cards total); CR 903.5e: Commander games do not use
    # sideboards.
    {"key": "commander", "label": "Commander", "scryfall_key": "commander",
     "min_deck": 99, "max_deck": 99, "max_copies": 1, "max_sideboard": 0, "singleton": True,
     "min_commander": 1, "max_commander": 1},
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


def _join_zones(zones: list[str]) -> str:
    """English-join zone names for an overage message ("deck and sideboard",
    "deck, sideboard, and commander"). Empty/single-item lists join to ""."""
    if len(zones) < 2:
        return ""
    if len(zones) == 2:
        return f"{zones[0]} and {zones[1]}"
    return f"{', '.join(zones[:-1])}, and {zones[-1]}"


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


def deck_ante_names(
    catalog_by_name: Mapping[str, Mapping[str, Any]],
    *zones: Iterable[Mapping[str, Any]] | None,
) -> list[str]:
    """The ante cards (CR 407.3) present anywhere in the given zones, by display
    name. Cards absent from the catalog can't be checked and are skipped."""
    names: list[str] = []
    for zone in zones:
        counts, _ = _tally(zone)
        for key in counts:
            card = catalog_by_name.get(key)
            if card is None or not is_ante_card(card):
                continue
            display = str(card.get("name", key))
            if display not in names:
                names.append(display)
    return names


def validate_deck(
    entries: Iterable[Mapping[str, Any]],
    fmt_key: str | None,
    catalog_by_name: Mapping[str, Mapping[str, Any]],
    sideboard: Iterable[Mapping[str, Any]] | None = None,
    commander: Iterable[Mapping[str, Any]] | None = None,
    playing_for_ante: bool = False,
) -> dict[str, Any]:
    """Check a deck (and its sideboard/command zone) against a format's rules.

    ``catalog_by_name`` maps casefolded card name -> catalog payload entry (the
    dict built by ``_build_catalog_payload``, which carries ``legalities``).
    Cards absent from the catalog are skipped here — they are surfaced
    separately as "not in catalog" and shouldn't be double-flagged as illegal.

    Per CR 100.4a the copy limit applies to the combined deck, sideboard, and
    command zone, while the minimum/maximum deck size (CR 100.2a, 100.5) counts
    the main deck (library) only.

    ``playing_for_ante`` reflects whether the game this deck is headed for is
    played for ante (CR 407.1). When False — the default, and what the deck
    editor shows — the ante cards are illegal in the deck and the sideboard
    alike (CR 407.3).

    Returns ``{"format", "legal", "problems": [str], "illegal_names": [str],
    "ante_names": [str]}``.
    """
    fmt = FORMATS_BY_KEY[normalize_format(fmt_key)]
    # Each zone is walked twice (ante check, then the format checks), so a
    # one-shot iterable is materialized before anything consumes it.
    entries = list(entries or ())
    sideboard = list(sideboard or ())
    commander = list(commander or ())
    result: dict[str, Any] = {
        "format": fmt["key"],
        "legal": True,
        "problems": [],
        "illegal_names": [],
        # Reported whether or not they're currently a problem, so the caller can
        # tell "this deck needs an ante game" from "this deck is broken".
        "ante_names": deck_ante_names(catalog_by_name, entries, sideboard, commander),
    }
    # CR 407.3 is not a format rule — it holds in Casual (which has no banlist)
    # exactly as it does in Vintage, so it is checked before the format bailout.
    if not playing_for_ante:
        for name in result["ante_names"]:
            result["problems"].append(
                f"{name} must be removed from the deck unless the game is played for ante."
            )
            result["illegal_names"].append(name)
    if fmt["scryfall_key"] is None:
        result["legal"] = not result["problems"]
        return result

    problems: list[str] = result["problems"]
    illegal: list[str] = result["illegal_names"]
    label = fmt["label"]
    main_counts, main_total = _tally(entries)
    side_counts, side_total = _tally(sideboard)
    cmd_counts, cmd_total = _tally(commander)

    # Main-deck order first, then sideboard/commander-only cards, so messages
    # read in the order the user built the deck.
    names = list(main_counts)
    names += [n for n in side_counts if n not in main_counts]
    names += [n for n in cmd_counts if n not in main_counts and n not in side_counts]
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
        in_cmd = cmd_counts.get(key, 0)
        count = main_counts.get(key, 0) + in_side + in_cmd
        if limit is not None and count > limit:
            # CR 100.4a — name the zones that actually contribute to the overage.
            zones = []
            if main_counts.get(key):
                zones.append("deck")
            if in_side:
                zones.append("sideboard")
            if in_cmd:
                zones.append("commander")
            where = f" across {_join_zones(zones)}" if len(zones) > 1 else ""
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

    min_cmd = fmt.get("min_commander", 0)
    max_cmd = fmt.get("max_commander", 0)
    if max_cmd == 0 and cmd_total > 0:
        problems.append(f"{label} does not use a commander (commander zone has {cmd_total} card(s)).")
    elif cmd_total > max_cmd:
        problems.append(f"Commander zone has {cmd_total} card(s); {label} allows at most {max_cmd}.")
    elif cmd_total < min_cmd:
        problems.append(f"{label} requires {min_cmd} designated commander card(s) (found {cmd_total}).")

    # An ante card is typically banned in the format too, so it can be flagged
    # twice (each with its own reason) — the name itself is listed once.
    result["illegal_names"] = list(dict.fromkeys(illegal))
    result["legal"] = not problems
    return result
