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


def manifest_set(code: str, manifest_path: str | Path = MANIFEST_PATH) -> dict:
    """One set's manifest entry, by its code (``"ARN"``).

    Raises on an unknown code, naming the ones that exist. A missing set that
    resolved to an empty pool would make every test over it pass vacuously,
    which is the same silent-wrongness the engine refuses everywhere else.
    """
    entries = manifest_sets(manifest_path)
    wanted = code.strip().upper()
    for entry in entries:
        if entry["code"].upper() == wanted:
            return entry
    known = ", ".join(entry["code"] for entry in entries)
    raise KeyError(f"no set {code!r} in the manifest; it ships {known}")


def manifest_set_path(code: str, manifest_path: str | Path = MANIFEST_PATH) -> Path:
    """The JSON for one set, by its code (``"ARN"``). Raises on an unknown code."""
    return Path(manifest_path).parent / manifest_set(code, manifest_path)["file"]


def manifest_set_codes(manifest_path: str | Path = MANIFEST_PATH) -> list[str]:
    """Every set code the engine ships, in printing order."""
    return [entry["code"] for entry in manifest_sets(manifest_path)]


def manifest_set_paths(manifest_path: str | Path = MANIFEST_PATH) -> list[Path]:
    """Every set JSON listed in ``cards/manifest.json``, in printing order.

    The manifest is the single registry of which sets the engine ships. Before
    it existed the same ordered list was copy-pasted across the web app, the
    test fixtures, and five scripts, so adding a set meant editing all of them.
    """
    base = Path(manifest_path).parent
    return [base / entry["file"] for entry in manifest_sets(manifest_path)]


def load_catalog(manifest_path: str | Path = MANIFEST_PATH) -> list[CardDefinition]:
    """The full card pool described by the manifest, deduped across reprints."""
    return load_cards(manifest_set_paths(manifest_path))
