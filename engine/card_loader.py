from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence, Union

from .models import CardDefinition


REQUIRED_FIELDS = ("name", "mana_cost", "cmc", "type_line")


def _to_tuple_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(v) for v in value)


def _load_one(path: str | Path) -> list[CardDefinition]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cards: list[CardDefinition] = []
    for entry in raw:
        for field in REQUIRED_FIELDS:
            if field not in entry:
                raise ValueError(f"Card is missing required field: {field}")

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
            )
        )
    return cards


def load_cards(path: Union[str, Path, Sequence[Union[str, Path]]]) -> list[CardDefinition]:
    """Load one set JSON, or concatenate several (a later set's card with the
    same name as an earlier one is dropped — first occurrence, e.g. the
    original LEA printing, wins)."""
    paths = [path] if isinstance(path, (str, Path)) else list(path)
    cards: list[CardDefinition] = []
    seen_names: set[str] = set()
    for one_path in paths:
        for card in _load_one(one_path):
            if card.name in seen_names:
                continue
            seen_names.add(card.name)
            cards.append(card)
    return cards
