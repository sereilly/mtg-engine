from __future__ import annotations

from pathlib import Path

import pytest

from engine import load_cards


@pytest.fixture(scope="session")
def lea_path() -> Path:
    return Path(__file__).resolve().parent.parent / "cards" / "LEA_cards.json"


@pytest.fixture(scope="session")
def card_paths(lea_path) -> list[Path]:
    """Every set JSON the test suite loads, in printing order. A new set adds
    its JSON here (or a set-specific fixture list) so `all_cards`/`cards`
    grow to cover it without touching individual test files."""
    return [lea_path]


@pytest.fixture(scope="session")
def all_cards(card_paths):
    return load_cards(card_paths)


@pytest.fixture(scope="session")
def cards(all_cards):
    """LEA cards keyed by name — replaces the module-scoped copies that each
    regression file used to declare."""
    return {c.name: c for c in all_cards}


@pytest.fixture(scope="session")
def arn_path() -> Path:
    return Path(__file__).resolve().parent.parent / "cards" / "ARN_cards.json"


@pytest.fixture(scope="session")
def arn_cards(arn_path):
    """Arabian Nights cards, kept separate from all_cards/cards (the LEA pool)
    so ARN-specific tests can't accidentally interact with the wider LEA
    fixture set."""
    return load_cards(arn_path)


@pytest.fixture(scope="session")
def arn_by_name(arn_cards):
    return {c.name: c for c in arn_cards}
