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


def manifest_set_paths(manifest_path: str | Path = MANIFEST_PATH) -> list[Path]:
    """Every set JSON listed in ``cards/manifest.json``, in printing order.

    The manifest is the single registry of which sets the engine ships. Before
    it existed the same ordered list was copy-pasted across the web app, the
    test fixtures, and five scripts, so adding a set meant editing all of them.
    """
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    base = Path(manifest_path).parent
    return [base / entry["file"] for entry in manifest["sets"]]


def load_catalog(manifest_path: str | Path = MANIFEST_PATH) -> list[CardDefinition]:
    """The full card pool described by the manifest, deduped across reprints."""
    return load_cards(manifest_set_paths(manifest_path))
