"""Ingest a Magic set into the engine's card format.

The card files began as raw Scryfall API dumps: 57+ fields per card, of which
the engine and web app read about twenty. The rest — `prices`, `purchase_uris`,
`related_uris`, `multiverse_ids`, `artist_ids`, `image_status`, `edhrec_rank`,
and friends — are roughly two thirds of the bytes on disk and are retained
whole in memory by ``CardDefinition.raw``. At the full 26,000-card pool that is
the difference between a catalog you can hold in a web worker and one you
can't, and `prices` additionally guarantees a full-file diff on every refresh.

Two modes:

``--from-existing`` (default)
    Prune the committed snapshot in place. No network, so oracle text cannot
    drift — the same cards compile to byte-identical programs, which
    ``tests/engine/test_card_format.py`` asserts.

``--fetch``
    Download the set from Scryfall. Use for a set the repo doesn't have yet;
    re-fetching an existing set may pull Oracle templating updates, which is a
    real content change and should be reviewed as one.

Usage::

    python scripts/ingest_set.py LEA                 # slim the committed file
    python scripts/ingest_set.py --all               # slim every set in the manifest
    python scripts/ingest_set.py 3ED --fetch         # add a new set
    python scripts/ingest_set.py --all --check       # report savings, write nothing

``--all`` means both manifest roles — the shipped ``sets`` and the ingested-but-
unshipped ``measured`` ones. Everywhere else that distinction is load-bearing
(``load_catalog`` must not reach a measured set), but a card file is a card file
as far as its *format* goes, and the file this script skips is the file no
format guard is measuring.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.card_loader import manifest_measured_sets, manifest_sets  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CARDS_DIR = REPO_ROOT / "cards"

SCRYFALL_API = "https://api.scryfall.com"
USER_AGENT = "MTGSimulacrum-Ingest/1.0"
REQUEST_DELAY_SECONDS = 0.11

# Every field the engine, the web layer, or the deck builder actually reads.
# Anything not listed is dropped. Keep this list minimal and justified — it is
# the whole point of the format.
KEEP_FIELDS: tuple[str, ...] = (
    # Identity and rules text — the engine's input.
    "name", "mana_cost", "cmc", "type_line", "oracle_text",
    "colors", "color_identity", "keywords", "produced_mana",
    "power", "toughness", "loyalty",
    # Multi-face layouts: without these a split/transform card loads blank.
    "layout", "card_faces",
    # Printing identity. oracle_id is the stable per-card key used for reprint
    # dedupe; set/collector_number identify this particular printing.
    "oracle_id", "set", "set_name", "collector_number", "rarity",
    # Web layer: card art, the deck builder's format legality, and the
    # "view on Scryfall" link.
    "image_uris", "legalities", "scryfall_uri",
    # engine/tokens.py reads all_parts to find a card's associated token.
    "all_parts",
)

# Sub-keys kept inside nested objects, so image_uris doesn't drag in six
# resolutions the UI never requests.
KEEP_IMAGE_URIS: tuple[str, ...] = ("small", "normal", "large", "art_crop")
KEEP_FACE_FIELDS: tuple[str, ...] = (
    "name", "mana_cost", "type_line", "oracle_text", "power", "toughness",
    "colors", "loyalty", "image_uris",
)


def _get_json(url: str) -> dict:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_set(code: str) -> list[dict]:
    """Every card in a set, in collector-number order."""
    params = urllib.parse.urlencode(
        {"q": f"set:{code}", "unique": "prints", "order": "set"}
    )
    url = f"{SCRYFALL_API}/cards/search?{params}"
    cards: list[dict] = []
    while url:
        time.sleep(REQUEST_DELAY_SECONDS)
        payload = _get_json(url)
        cards.extend(payload.get("data", []))
        url = payload.get("next_page") if payload.get("has_more") else None
    return cards


def slim_card(entry: dict) -> dict:
    """Project one card onto KEEP_FIELDS, pruning nested objects too."""
    out: dict = {}
    for field in KEEP_FIELDS:
        if field not in entry:
            continue
        value = entry[field]
        if field == "image_uris" and isinstance(value, dict):
            value = {k: v for k, v in value.items() if k in KEEP_IMAGE_URIS}
        elif field == "card_faces" and isinstance(value, list):
            faces = []
            for face in value:
                if not isinstance(face, dict):
                    continue
                slim_face = {k: v for k, v in face.items() if k in KEEP_FACE_FIELDS}
                if isinstance(slim_face.get("image_uris"), dict):
                    slim_face["image_uris"] = {
                        k: v for k, v in slim_face["image_uris"].items()
                        if k in KEEP_IMAGE_URIS
                    }
                faces.append(slim_face)
            value = faces
        elif field == "all_parts" and isinstance(value, list):
            value = [
                {k: v for k, v in part.items() if k in ("component", "name", "type_line")}
                for part in value
                if isinstance(part, dict)
            ]
        out[field] = value
    return out


def _registered_entries() -> list[dict]:
    """Every set the manifest knows about, shipped or merely measured.

    Both roles are card files on disk, and this script is about the *file*, not
    about whether a player may deck it. Reading only ``sets`` is how M21 —
    ingested for measurement — stopped being covered by ``--all`` the day it was
    added, without anyone editing this script. `scripts/set_argument.py` exists
    because a second copy of the registry is the thing that goes stale; the copy
    here was the last one, and it had already drifted.
    """
    return manifest_sets() + manifest_measured_sets()


def _set_path(code: str) -> Path:
    """The card file for *code*, from the manifest where the manifest knows it.

    The composed fallback is for a set that is *being added* and so has no entry
    to look up yet — the one honest reason to spell a card filename, and the
    exemption `tests/engine/test_script_set_argument.py` names.
    """
    for entry in _registered_entries():
        if entry["code"].lower() == code.lower():
            return CARDS_DIR / entry["file"]
    return CARDS_DIR / f"{code.upper()}_cards.json"


def _report(code: str, before: int, after: int) -> None:
    saved = before - after
    pct = (100.0 * saved / before) if before else 0.0
    print(
        f"{code}: {before / 1024:.0f} KB -> {after / 1024:.0f} KB "
        f"({pct:.0f}% smaller)"
    )


def ingest(code: str, *, fetch: bool, check: bool) -> int:
    path = _set_path(code)

    if fetch:
        cards = fetch_set(code)
        if not cards:
            print(f"FAIL: Scryfall returned no cards for set {code!r}")
            return 1
        before = len(json.dumps(cards).encode("utf-8"))
    else:
        if not path.exists():
            print(f"FAIL: {path} does not exist (use --fetch to download it)")
            return 1
        cards = json.loads(path.read_text(encoding="utf-8"))
        before = path.stat().st_size

    slimmed = [slim_card(entry) for entry in cards]
    payload = json.dumps(slimmed, indent=2, ensure_ascii=False) + "\n"
    after = len(payload.encode("utf-8"))
    _report(code, before, after)

    if check:
        return 0

    path.write_text(payload, encoding="utf-8")
    print(f"  wrote {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", nargs="?", help="set code, e.g. LEA")
    parser.add_argument("--all", action="store_true", help="every set in the manifest")
    parser.add_argument(
        "--fetch", action="store_true",
        help="download from Scryfall instead of slimming the committed file",
    )
    parser.add_argument(
        "--check", action="store_true", help="report sizes without writing"
    )
    args = parser.parse_args()

    if args.all:
        codes = [entry["code"] for entry in _registered_entries()]
    elif args.code:
        codes = [args.code]
    else:
        parser.error("give a set code or --all")
        return 2

    status = 0
    for code in codes:
        status |= ingest(code, fetch=args.fetch, check=args.check)
    return status


if __name__ == "__main__":
    sys.exit(main())
