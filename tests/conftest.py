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
def all_set_paths() -> list[Path]:
    """Every set JSON in printing order — the whole card pool, from
    ``cards/manifest.json``.

    Distinct from ``card_paths`` (LEA only), which the per-card test files want
    so their name lookups stay unambiguous. Pool-wide guards (the grammar
    differential and coverage ratchet) use this instead, so a new set is
    covered by them the moment it is added to the manifest rather than when
    someone remembers to widen a hardcoded list.
    """
    from engine.card_loader import manifest_set_paths

    return manifest_set_paths()


@pytest.fixture(scope="session")
def catalog(all_set_paths):
    """The whole deduped card pool, as the web app loads it."""
    return load_cards(all_set_paths)


@pytest.fixture(scope="session")
def catalog_by_name(catalog):
    return {card.name: card for card in catalog}


@pytest.fixture(scope="session")
def all_cards(card_paths):
    return load_cards(card_paths)


@pytest.fixture(scope="session")
def cards(all_cards):
    """LEA cards keyed by name — replaces the module-scoped copies that each
    regression file used to declare."""
    return {c.name: c for c in all_cards}


@pytest.fixture(scope="session")
def leb_path() -> Path:
    return Path(__file__).resolve().parent.parent / "cards" / "LEB_cards.json"


@pytest.fixture(scope="session")
def unlimited_path() -> Path:
    return Path(__file__).resolve().parent.parent / "cards" / "2ED_cards.json"


@pytest.fixture(scope="session")
def leb_cards(leb_path):
    """Limited Edition Beta cards, kept separate from all_cards/cards (the LEA
    pool) — Beta is Alpha plus its two missing cards, so mixing it into the
    LEA fixtures would silently double most lookups."""
    return load_cards(leb_path)


@pytest.fixture(scope="session")
def leb_by_name(leb_cards):
    return {c.name: c for c in leb_cards}


@pytest.fixture(scope="session")
def unlimited_cards(unlimited_path):
    """Unlimited Edition cards — the same card list as Beta, reprinted."""
    return load_cards(unlimited_path)


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
