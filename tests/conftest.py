from __future__ import annotations

from pathlib import Path

import pytest

from engine import load_cards


@pytest.fixture(scope="session")
def lea_path() -> Path:
    return Path(__file__).resolve().parent.parent / "lea_cards.json"


@pytest.fixture(scope="session")
def all_cards(lea_path):
    return load_cards(lea_path)
