"""Fourth Edition — the set that ships without implementing a card.

Every one of 4ED's 368 unique cards was already in the pool: it is a pure
reprint set, drawing from Alpha through The Dark and adding nothing of its own.
So there are no per-card tests here, and their absence is the point — a test
asserting that Air Elemental flies would be a fifth copy of one written for
Alpha, and `tests/sets/README.md`'s whole reason for existing is that the pool
is going to 137 sets.

What is 4ED-specific is its *relationship* to the pool, and that is what this
file pins. Those facts are load-bearing in a way per-card tests are not: they
are why the set had no backlog, why the hook-reliance ALL row did not move when
it promoted, and why its position in the manifest changes no card's origin. All
of that is silently wrong the day the premise stops holding, and the premise
lives in a Scryfall fetch nobody re-reads.
"""

from __future__ import annotations

import collections
import json

from engine.card_loader import manifest_set_path, manifest_sets
from engine.oracle import compile_card_oracle


def _codes_before(code: str) -> list[str]:
    """The manifest is printing-ordered, so "earlier" is "further left"."""
    codes = [entry["code"] for entry in manifest_sets()]
    return codes[: codes.index(code)]


def test_fourth_edition_is_entirely_reprints(set_cards):
    """The premise everything else here rests on. If a re-fetch ever adds a
    card that is new to the pool, this fails and the reasoning in ROADMAP's 4ED
    entry — no backlog, no ALL movement, no new origins — has to be redone
    rather than inherited."""
    earlier = {
        card.oracle_id
        for code in _codes_before("4ED")
        for card in set_cards(code)
        if card.oracle_id
    }
    novel = sorted(
        card.name for card in set_cards("4ED") if card.oracle_id not in earlier
    )
    assert not novel, f"4ED cards with no earlier printing in the pool: {novel}"


def test_the_set_is_368_unique_cards_from_378_printings(set_cards, catalog_by_name):
    """The two numbers the census reports differ, and the gap is the basic
    lands: five names printed with three arts each dedupe to five cards. Worth
    pinning because "378 vs 368" otherwise reads as ten cards going missing —
    and because the dedupe happens in the loader, so the raw file is the only
    place the printing count is still visible."""
    raw = json.loads(manifest_set_path("4ED").read_text(encoding="utf-8"))
    assert len(raw) == 378
    assert len(set_cards("4ED")) == 368

    counts = collections.Counter(entry["name"] for entry in raw)
    repeated = sorted(name for name, n in counts.items() if n > 1)
    assert repeated == ["Forest", "Island", "Mountain", "Plains", "Swamp"]
    for name in repeated:
        assert catalog_by_name[name].original_printing == "lea"


def test_no_card_is_originally_printed_in_fourth_edition(set_cards, catalog_by_name):
    """CR-visible consequence: "originally printed in" effects (City in a
    Bottle, Golgothian Sylex) read `printings[0]`, so a reprint set that ever
    became a card's origin would change what they sacrifice.

    This does **not** check that 4ED sits at the right manifest index, and the
    difference matters. Probed by appending 4ED after M21 and re-running: this
    file and `test_card_format.py` both stay green, because every 4ED card has
    an earlier printing and so no ordering of the manifest can make 4ED an
    origin. The prefix guard that catches a misplaced *original* set is
    structurally silent here. Manifest order is asserted directly instead, in
    `test_manifest_roles.test_the_shipped_sets_are_in_printing_order`."""
    origins = {
        card.name: catalog_by_name[card.name].original_printing
        for card in set_cards("4ED")
    }
    assert "4ed" not in set(origins.values()), {
        name: origin for name, origin in origins.items() if origin == "4ed"
    }


def test_promoting_the_set_actually_recorded_its_printings(set_cards, catalog_by_name):
    """The positive half of the test above, and the reason it means anything:
    "no card originates in 4ED" also passes if the set was never loaded. Every
    4ED card must carry `4ed` in `printings` — that, not its origin, is what
    the promotion added."""
    missing = sorted(
        card.name
        for card in set_cards("4ED")
        if "4ed" not in catalog_by_name[card.name].printings
    )
    assert not missing, f"4ED cards the catalog does not record a 4ed printing for: {missing}"


def test_every_card_ships_supported(set_cards, catalog_by_name):
    """What promotion claims. The pool-wide guards assert it of the catalog;
    this asserts it of the set, by name, so a card dropped from the catalog
    fails here rather than passing by absence."""
    unsupported = sorted(
        card.name
        for card in set_cards("4ED")
        if not compile_card_oracle(catalog_by_name[card.name]).supported
    )
    assert not unsupported, f"unsupported 4ED cards: {unsupported}"
