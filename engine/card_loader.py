from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Sequence, Union

from .models import CardDefinition, CardFace

REQUIRED_FIELDS = ("name", "mana_cost", "cmc", "type_line")

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "cards" / "manifest.json"


def _to_tuple_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(v) for v in value)


def _optional_str(entry: dict, key: str) -> str | None:
    value = entry.get(key)
    return None if value is None else str(value)


def _load_faces(entry: dict) -> tuple[CardFace, ...]:
    """Parse ``card_faces`` for multi-face layouts.

    Split/flip/transform/adventure cards carry empty top-level
    ``mana_cost``/``oracle_text``; without this the compiler would see a card
    with no text and classify it a supported vanilla.
    """
    faces = entry.get("card_faces")
    if not isinstance(faces, list):
        return ()
    return tuple(
        CardFace(
            name=str(face.get("name", "")),
            mana_cost=str(face.get("mana_cost", "")),
            type_line=str(face.get("type_line", "")),
            oracle_text=str(face.get("oracle_text", "")),
            power=_optional_str(face, "power"),
            toughness=_optional_str(face, "toughness"),
        )
        for face in faces
        if isinstance(face, dict)
    )


def _load_one(path: str | Path) -> list[CardDefinition]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cards: list[CardDefinition] = []
    for entry in raw:
        for field in REQUIRED_FIELDS:
            if field not in entry:
                raise ValueError(f"Card is missing required field: {field}")

        set_code = str(entry.get("set", ""))
        cards.append(
            CardDefinition(
                name=str(entry["name"]),
                mana_cost=str(entry.get("mana_cost", "")),
                cmc=float(entry.get("cmc", 0.0)),
                type_line=str(entry["type_line"]),
                oracle_text=str(entry.get("oracle_text", "")),
                colors=_to_tuple_list(entry.get("colors")),
                color_identity=_to_tuple_list(entry.get("color_identity")),
                keywords=_to_tuple_list(entry.get("keywords")),
                produced_mana=_to_tuple_list(entry.get("produced_mana")),
                raw=entry,
                power=_optional_str(entry, "power"),
                toughness=_optional_str(entry, "toughness"),
                loyalty=_optional_str(entry, "loyalty"),
                layout=str(entry.get("layout", "normal")),
                faces=_load_faces(entry),
                oracle_id=str(entry.get("oracle_id", "")),
                set_code=set_code,
                collector_number=str(entry.get("collector_number", "")),
                printings=(set_code,) if set_code else (),
            )
        )
    return cards


def load_cards(path: Union[str, Path, Sequence[Union[str, Path]]]) -> list[CardDefinition]:
    """Load one set JSON, or concatenate several.

    Reprints collapse to a single card: the first occurrence wins (the original
    printing, given files are passed in printing order) and every later set it
    appears in is recorded in ``printings``. Effects that care about where a
    card was *originally* printed read ``printings[0]``; recording them is what
    keeps that answer stable when a reprint set is added to the pool.

    Dedupe is by ``oracle_id`` when the data has it, falling back to name.
    """
    paths = [path] if isinstance(path, (str, Path)) else list(path)
    cards: list[CardDefinition] = []
    index_by_key: dict[str, int] = {}
    printings: list[list[str]] = []

    for one_path in paths:
        for card in _load_one(one_path):
            key = card.oracle_id or card.name
            existing = index_by_key.get(key)
            if existing is not None:
                if card.set_code and card.set_code not in printings[existing]:
                    printings[existing].append(card.set_code)
                continue
            index_by_key[key] = len(cards)
            cards.append(card)
            printings.append([card.set_code] if card.set_code else [])

    return [
        replace(card, printings=tuple(codes))
        for card, codes in zip(cards, printings)
    ]


def set_code_for_expansion_name(
    name: str, manifest_path: str | Path = MANIFEST_PATH
) -> str | None:
    """The set code a printed expansion *name* refers to, or None.

    "…with a name originally printed in the **Antiquities** expansion"
    (Golgothian Sylex) / "…in the **Arabian Nights** expansion" (City in a
    Bottle) / Homelands' Apocalypse Chime. The card prints the set's name and
    every reader downstream wants its code, and the manifest already holds
    both — so the mapping is a projection of the registry rather than a second
    table that could disagree with it about what a set is called.

    Both manifest roles are searched. Whether a player may deck the set is not
    the question here: the card asks where a *name was originally printed*,
    which is a fact about card data, and is true of a measured set exactly as
    it is of a shipped one. (The same reasoning `ingest_set.py --all` uses.)
    """
    wanted = " ".join((name or "").strip().lower().split())
    if not wanted:
        return None
    for entry in manifest_sets(manifest_path) + manifest_measured_sets(manifest_path):
        if str(entry.get("name", "")).strip().lower() == wanted:
            return str(entry["code"]).lower()
    return None


def manifest_sets(manifest_path: str | Path = MANIFEST_PATH) -> list[dict]:
    """Every set entry in ``cards/manifest.json``, in printing order.

    The one place the manifest file is read; everything below is a projection of
    it. An entry carries the set's ``code``, ``name``, ``released`` date and
    ``file``, so a caller that wants to *name* the set in output — a script
    reporting which pool it just covered — does not have to open the manifest
    a second time and risk disagreeing with this one about what ships.
    """
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return list(manifest["sets"])


def manifest_set(
    code: str,
    manifest_path: str | Path = MANIFEST_PATH,
    *,
    include_measured: bool = False,
) -> dict:
    """One set's manifest entry, by its code (``"ARN"``).

    Raises on an unknown code, naming the ones that exist. A missing set that
    resolved to an empty pool would make every test over it pass vacuously,
    which is the same silent-wrongness the engine refuses everywhere else.

    *include_measured* also resolves the ingested-but-unshipped sets, and the
    default is False for the same reason it is on ``manifest_set_paths`` — a
    caller that has not thought about the split means "what the engine plays".
    The reporting scripts pass True: `support_report.py` naming the unsupported
    cards in a set is the tool you use *while* implementing it, and a set under
    `measured` is precisely one nobody has implemented yet. Reading a card file
    is not shipping it; ``load_catalog`` is the seam that decides what a player
    can deck, and it does not come through here.
    """
    entries = list(manifest_sets(manifest_path))
    if include_measured:
        entries += manifest_measured_sets(manifest_path)
    wanted = code.strip().upper()
    for entry in entries:
        if entry["code"].upper() == wanted:
            return entry
    shipped = ", ".join(entry["code"] for entry in manifest_sets(manifest_path))
    if not include_measured:
        raise KeyError(f"no set {code!r} in the manifest; it ships {shipped}")
    measured = ", ".join(
        entry["code"] for entry in manifest_measured_sets(manifest_path)
    )
    known = f"it ships {shipped}" + (f" and measures {measured}" if measured else "")
    raise KeyError(f"no set {code!r} in the manifest; {known}")


def manifest_set_path(
    code: str,
    manifest_path: str | Path = MANIFEST_PATH,
    *,
    include_measured: bool = False,
) -> Path:
    """The JSON for one set, by its code (``"ARN"``). Raises on an unknown code.

    *include_measured* passes through to ``manifest_set``, for the same caller:
    the per-set test fixtures resolve a measured set because a card lands with
    its focused test *while* the set is being implemented, and a set under
    ``measured`` is precisely one mid-implementation. Reading a card file is
    not shipping it; ``load_catalog`` decides what a player can deck and does
    not come through here. Everything else keeps the False default.
    """
    entry = manifest_set(code, manifest_path, include_measured=include_measured)
    return Path(manifest_path).parent / entry["file"]


def manifest_set_codes(manifest_path: str | Path = MANIFEST_PATH) -> list[str]:
    """Every set code the engine ships, in printing order."""
    return [entry["code"] for entry in manifest_sets(manifest_path)]


def manifest_measured_sets(manifest_path: str | Path = MANIFEST_PATH) -> list[dict]:
    """Sets ingested for *measurement* but not shipped.

    A second role in the same registry, not a second registry. The engine plays
    ``sets``, and that list is held at 100% supported — the web app offers those
    cards to players, and two guards
    (``tests/engine/test_front_end_safety.py``, ``tests/engine/test_card_format.py``)
    fail if a card in it is unsupported.

    A newly ingested set cannot meet that bar on the day it arrives, and the
    numbers that say how far off it is are the reason to ingest it. So it lands
    here: the coverage instruments read it, ``load_catalog`` does not, and it
    moves up to ``sets`` when the support work is done. Without this split the
    only two options are shipping a set the app cannot play or not measuring it
    at all.
    """
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return list(manifest.get("measured", ()))


def register_measured_set(
    entry: dict, manifest_path: str | Path = MANIFEST_PATH
) -> None:
    """Add *entry* to the manifest's ``measured`` role, ordered by release.

    The write lives beside the readers on purpose: this module is the one
    parser of the registry, and a script composing its own JSON edit would be
    the same second copy a spelled-out filename is. ``scripts/ingest_set.py
    --register`` is the caller; before it, the registration step was a hand
    edit of ``cards/manifest.json``.

    Only the ``measured`` role is written. Promotion to ``sets`` stays a
    reviewed hand move at the printing-ordered index — it is the claim that
    every card in the set is supported, and two guards check that claim.
    """
    required = ("code", "name", "released", "file")
    missing = [key for key in required if key not in entry]
    if missing:
        raise ValueError(f"manifest entry is missing {missing}")
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    taken = {e["code"] for e in manifest["sets"]} | {
        e["code"] for e in manifest["measured"]
    }
    if entry["code"] in taken:
        raise ValueError(
            f"{entry['code']} is already registered in the manifest — a set "
            "holds one role at a time, and promotion is a reviewed hand move"
        )
    measured = manifest["measured"]
    index = next(
        (
            i
            for i, existing in enumerate(measured)
            if existing["released"] > entry["released"]
        ),
        len(measured),
    )
    measured.insert(index, {key: entry[key] for key in required})
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def manifest_measured_codes(manifest_path: str | Path = MANIFEST_PATH) -> list[str]:
    """Every set code ingested for measurement but not shipped."""
    return [entry["code"] for entry in manifest_measured_sets(manifest_path)]


def manifest_set_paths(
    manifest_path: str | Path = MANIFEST_PATH,
    *,
    include_measured: bool = False,
) -> list[Path]:
    """Every shipped set JSON in ``cards/manifest.json``, in printing order.

    The manifest is the single registry of which sets the engine ships. Before
    it existed the same ordered list was copy-pasted across the web app, the
    test fixtures, and five scripts, so adding a set meant editing all of them.

    *include_measured* additionally returns the ingested-but-unshipped sets, and
    exists for the coverage instruments alone. It defaults to False so that
    every existing caller — ``load_catalog`` above all, and through it the web
    app, the fixtures and the support report — keeps meaning "what the engine
    plays". Widening this by default is how an unsupported card would reach a
    player's deck.
    """
    base = Path(manifest_path).parent
    entries = manifest_sets(manifest_path)
    if include_measured:
        entries = entries + manifest_measured_sets(manifest_path)
    return [base / entry["file"] for entry in entries]


def load_catalog(manifest_path: str | Path = MANIFEST_PATH) -> list[CardDefinition]:
    """The full card pool described by the manifest, deduped across reprints."""
    return load_cards(manifest_set_paths(manifest_path))
