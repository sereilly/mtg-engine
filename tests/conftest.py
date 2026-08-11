"""Shared fixtures.

**Per-set pools go through ``set_pool`` / ``set_cards``, not new fixtures.**
This file used to gain a path fixture, a cards fixture and a by-name fixture
every time a set was ingested — three or four declarations whose entire content
was a set code. At the 137 sets the roadmap is aiming for that is several
hundred lines of boilerplate, and every one of them is a place to forget. The
factory resolves any set through ``cards/manifest.json``, so **a new set needs
no change here at all**.

The named aliases below are grandfathered, not the pattern: they exist only
where the call sites are too numerous to be worth rewriting (``cards`` and
``all_cards`` are used ~3,600 times, ``arn_by_name`` ~590). Do not add more.

Pool-wide guards want ``catalog`` — the whole deduped pool as the web app loads
it. Per-card tests want a single set, so their name lookups stay unambiguous:
Beta is Alpha plus two cards and Unlimited is Beta reprinted, so mixing the
pools would silently double most lookups.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine import load_cards
from engine.card_loader import manifest_set_codes, manifest_set_path, manifest_set_paths


# ---------------------------------------------------------------------------
# The factory
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def set_cards():
    """``set_cards("ARN")`` — one set's cards, in printing order.

    Loads are memoized for the session, so asking for the same set from twenty
    test modules reads the JSON once. An unknown code raises, naming the codes
    that exist; resolving it to an empty pool instead would make every test
    over that set pass without testing anything.

    Measured sets resolve too: a card lands with its focused test while its
    set is still under ``measured``, so the fixture is the one caller that
    opts in. ``catalog`` / ``all_set_paths`` stay shipped-only — reading a
    card file is not shipping it.
    """
    loaded: dict[str, list] = {}

    def _load(code: str) -> list:
        key = code.strip().upper()
        if key not in loaded:
            loaded[key] = load_cards(manifest_set_path(key, include_measured=True))
        return loaded[key]

    return _load


@pytest.fixture(scope="session")
def set_pool(set_cards):
    """``set_pool("ARN")`` — one set's cards keyed by name."""
    pools: dict[str, dict] = {}

    def _pool(code: str) -> dict:
        key = code.strip().upper()
        if key not in pools:
            pools[key] = {card.name: card for card in set_cards(key)}
        return pools[key]

    return _pool


@pytest.fixture(scope="session")
def set_codes() -> list[str]:
    """Every set code the engine ships, in printing order."""
    return manifest_set_codes()


# ---------------------------------------------------------------------------
# The whole pool
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def all_set_paths() -> list[Path]:
    """Every set JSON in printing order, from ``cards/manifest.json``.

    Pool-wide guards (the grammar differential, the coverage ratchets, the
    catalog sweeps) use this, so a new set is covered by them the moment it is
    added to the manifest rather than when someone remembers to widen a list.
    """
    return manifest_set_paths()


@pytest.fixture(scope="session")
def catalog(all_set_paths):
    """The whole deduped card pool, as the web app loads it."""
    return load_cards(all_set_paths)


@pytest.fixture(scope="session")
def catalog_by_name(catalog):
    return {card.name: card for card in catalog}


# ---------------------------------------------------------------------------
# Grandfathered per-set aliases — see the module docstring. Do not add more.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def all_cards(set_cards):
    """The LEA pool: the default for per-card tests that predate the factory."""
    return set_cards("LEA")


@pytest.fixture(scope="session")
def cards(set_pool):
    """LEA cards keyed by name."""
    return set_pool("LEA")


@pytest.fixture(scope="session")
def arn_cards(set_cards):
    return set_cards("ARN")


@pytest.fixture(scope="session")
def arn_by_name(set_pool):
    return set_pool("ARN")
