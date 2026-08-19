"""Format-legality / banlist checks for deck construction (web/deck_legality.py)
plus the API surface that exposes it (catalog legalities, deck-summary legality)."""

from fastapi.testclient import TestClient

import web.app as web_app
from web.app import app, _deck_summary
from web.deck_legality import FORMATS, normalize_format, card_status, validate_deck


client = TestClient(app)


def _catalog(*cards: dict) -> dict:
    """Build a casefolded name->entry map like _build_catalog_payload produces."""
    return {c["name"].casefold(): c for c in cards}


def _card(name, legal, *, type_line="Creature - Test", oracle_text="", key="modern",
          mana_cost=""):
    # ``mana_cost`` is where CR 903.4 reads a card's colour identity from, so a
    # Commander-format fixture needs one to be anything but colourless.
    return {"name": name, "type_line": type_line, "oracle_text": oracle_text,
            "mana_cost": mana_cost, "legalities": {key: legal}}


# ── Per-card status ─────────────────────────────────────────────────────────

def test_card_status_reads_scryfall_map():
    fmt = next(f for f in FORMATS if f["key"] == "modern")
    assert card_status(_card("A", "legal"), fmt) == "legal"
    assert card_status(_card("A", "banned"), fmt) == "banned"
    assert card_status(_card("A", "restricted", key="vintage"),
                       next(f for f in FORMATS if f["key"] == "vintage")) == "restricted"


def test_card_status_missing_key_is_not_legal():
    fmt = next(f for f in FORMATS if f["key"] == "modern")
    assert card_status({"name": "A", "legalities": {}}, fmt) == "not_legal"


def test_casual_format_treats_everything_legal():
    fmt = next(f for f in FORMATS if f["key"] == "casual")
    assert card_status(_card("A", "banned"), fmt) == "legal"


# ── Deck validation ─────────────────────────────────────────────────────────

def test_banned_card_flagged():
    cat = _catalog(_card("Bad Card", "banned"))
    res = validate_deck([{"name": "Bad Card", "count": 1}], "modern", cat)
    assert res["legal"] is False
    assert "Bad Card" in res["illegal_names"]
    assert any("banned" in p for p in res["problems"])


def test_not_legal_card_flagged():
    cat = _catalog(_card("Old Card", "not_legal"))
    res = validate_deck([{"name": "Old Card", "count": 1}], "modern", cat)
    assert any("not legal" in p for p in res["problems"])


def test_four_of_copy_limit():
    cat = _catalog(_card("Grizzly Bears", "legal"))
    ok = validate_deck([{"name": "Grizzly Bears", "count": 4}], "modern", cat)
    assert ok["illegal_names"] == []  # 4 is fine (deck-size problem aside)
    bad = validate_deck([{"name": "Grizzly Bears", "count": 5}], "modern", cat)
    assert "Grizzly Bears" in bad["illegal_names"]
    assert any("4-copy" in p for p in bad["problems"])


def test_basic_land_exempt_from_copy_limit():
    cat = _catalog(_card("Forest", "legal", type_line="Basic Land - Forest"))
    res = validate_deck([{"name": "Forest", "count": 30}], "modern", cat)
    assert res["illegal_names"] == []


def test_any_number_card_exempt_from_copy_limit():
    cat = _catalog(_card("Relentless Rats", "legal",
                         oracle_text="A deck can have any number of cards named Relentless Rats."))
    res = validate_deck([{"name": "Relentless Rats", "count": 20}], "modern", cat)
    assert res["illegal_names"] == []


def test_restricted_limits_to_one_copy():
    cat = _catalog(_card("Ancestral Recall", "restricted", key="vintage"))
    ok = validate_deck([{"name": "Ancestral Recall", "count": 1}], "vintage", cat)
    assert ok["illegal_names"] == []
    bad = validate_deck([{"name": "Ancestral Recall", "count": 2}], "vintage", cat)
    assert any("restricted to 1" in p for p in bad["problems"])


def test_singleton_format_allows_one_copy():
    cat = _catalog(_card("Sol Ring", "legal", key="commander"))
    bad = validate_deck([{"name": "Sol Ring", "count": 2}], "commander", cat)
    assert "Sol Ring" in bad["illegal_names"]
    assert any("1-of" in p for p in bad["problems"])


def test_deck_size_minimum():
    cat = _catalog(_card("Grizzly Bears", "legal"))
    res = validate_deck([{"name": "Grizzly Bears", "count": 4}], "modern", cat)
    assert any("at least 60" in p for p in res["problems"])


def test_commander_deck_size_maximum():
    cat = _catalog(_card("Forest", "legal", type_line="Basic Land - Forest", key="commander"))
    res = validate_deck([{"name": "Forest", "count": 100}], "commander", cat)
    assert any("at most 99" in p for p in res["problems"])


def test_casual_deck_always_legal():
    cat = _catalog(_card("Bad Card", "banned"))
    res = validate_deck([{"name": "Bad Card", "count": 40}], "casual", cat)
    assert res["legal"] is True
    assert res["problems"] == []


def test_unknown_card_not_double_flagged():
    res = validate_deck([{"name": "Nonexistent", "count": 4}], "modern", {})
    # Unknown cards are surfaced separately; only the deck-size rule fires here.
    assert res["illegal_names"] == []
    assert all("banned" not in p and "not legal" not in p for p in res["problems"])


# ── Sideboard rules (CR 100.4a, 903.5e) ─────────────────────────────────────

def test_sideboard_limited_to_fifteen_cards():
    cat = _catalog(_card("Grizzly Bears", "legal"))
    side = [{"name": "Grizzly Bears", "count": 4} for _ in range(4)]  # 16 cards
    res = validate_deck([], "modern", cat, side)
    assert any("Sideboard has 16 card(s)" in p and "at most 15" in p for p in res["problems"])


def test_fifteen_card_sideboard_is_fine():
    cat = _catalog(_card("Forest", "legal", type_line="Basic Land - Forest"))
    res = validate_deck([{"name": "Forest", "count": 60}], "modern", cat,
                        [{"name": "Forest", "count": 15}])
    assert res["legal"] is True


def test_copy_limit_counts_deck_plus_sideboard():
    cat = _catalog(_card("Grizzly Bears", "legal"))
    res = validate_deck([{"name": "Grizzly Bears", "count": 3}], "modern", cat,
                        [{"name": "Grizzly Bears", "count": 2}])
    assert "Grizzly Bears" in res["illegal_names"]
    assert any("5 copies across deck and sideboard" in p for p in res["problems"])


def test_sideboard_only_card_still_checked():
    cat = _catalog(_card("Bad Card", "banned"), _card("Grizzly Bears", "legal"))
    res = validate_deck([], "modern", cat, [{"name": "Bad Card", "count": 1}])
    assert "Bad Card" in res["illegal_names"]
    # A sideboard-only overage reads without the "across" wording.
    over = validate_deck([], "modern", cat, [{"name": "Grizzly Bears", "count": 5}])
    assert any("5 copies exceed the 4-copy limit" in p for p in over["problems"])


def test_sideboard_does_not_count_toward_minimum_deck_size():
    cat = _catalog(_card("Forest", "legal", type_line="Basic Land - Forest"))
    res = validate_deck([{"name": "Forest", "count": 55}], "modern", cat,
                        [{"name": "Forest", "count": 15}])
    assert any("Deck has 55 card(s)" in p and "at least 60" in p for p in res["problems"])


def test_commander_has_no_sideboard():
    cat = _catalog(_card("Sol Ring", "legal", key="commander"))
    res = validate_deck([], "commander", cat, [{"name": "Sol Ring", "count": 1}])
    assert any("does not use a sideboard" in p for p in res["problems"])


# ── Command zone (CR 903.5a) ────────────────────────────────────────────────

def test_commander_requires_a_designated_commander():
    cat = _catalog(_card("Forest", "legal", type_line="Basic Land - Forest", key="commander"))
    res = validate_deck([{"name": "Forest", "count": 99}], "commander", cat)
    assert any("requires 1 designated commander" in p for p in res["problems"])


def test_commander_with_one_designated_commander_is_fine():
    # The commander is green, so CR 903.5d admits the Forests: each colour of
    # mana they could produce is in its colour identity.
    cat = _catalog(
        _card("Forest", "legal", type_line="Basic Land - Forest", key="commander"),
        _card("Green Legend", "legal", type_line="Legendary Creature - Human",
              key="commander", mana_cost="{2}{G}"),
    )
    res = validate_deck(
        [{"name": "Forest", "count": 99}], "commander", cat,
        commander=[{"name": "Green Legend", "count": 1}],
    )
    assert res["legal"] is True, res["problems"]


def test_other_formats_do_not_use_a_commander():
    cat = _catalog(_card("Grizzly Bears", "legal"))
    res = validate_deck(
        [{"name": "Grizzly Bears", "count": 60}], "modern", cat,
        commander=[{"name": "Grizzly Bears", "count": 1}],
    )
    assert any("does not use a commander" in p for p in res["problems"])


def test_copy_limit_counts_deck_plus_commander():
    cat = _catalog(_card("Sol Ring", "legal", key="commander"))
    res = validate_deck(
        [{"name": "Sol Ring", "count": 1}], "commander", cat,
        commander=[{"name": "Sol Ring", "count": 1}],
    )
    assert "Sol Ring" in res["illegal_names"]
    assert any("2 copies across deck and commander" in p for p in res["problems"])


def test_casual_sideboard_unbounded():
    cat = _catalog(_card("Grizzly Bears", "legal"))
    res = validate_deck([], "casual", cat, [{"name": "Grizzly Bears", "count": 40}])
    assert res["legal"] is True


def test_deck_summary_validates_sideboard():
    deck = {
        "id": "d3",
        "name": "Fat Sideboard",
        "cards": [{"name": "Mountain", "count": 60}],
        "sideboard": [{"name": "Mountain", "count": 16}],
        "format": "premodern",
    }
    summary = _deck_summary(deck)
    assert summary["legality"]["legal"] is False
    assert any("Sideboard has 16 card(s)" in p for p in summary["legality"]["problems"])


def test_normalize_format_falls_back_to_casual():
    assert normalize_format("nonsense") == "casual"
    assert normalize_format(None) == "casual"
    assert normalize_format("modern") == "modern"


# ── Real-catalog integration (uses the loaded card pool) ────────────────────

def test_black_lotus_banned_in_legacy_restricted_in_vintage():
    cat = web_app.CATALOG_BY_NAME
    legacy = validate_deck([{"name": "Black Lotus", "count": 1}], "legacy", cat)
    assert "Black Lotus" in legacy["illegal_names"]
    vintage_two = validate_deck([{"name": "Black Lotus", "count": 2}], "vintage", cat)
    assert "Black Lotus" in vintage_two["illegal_names"]
    vintage_one = validate_deck([{"name": "Black Lotus", "count": 1}], "vintage", cat)
    assert "Black Lotus" not in vintage_one["illegal_names"]


# ── API surface ─────────────────────────────────────────────────────────────

def test_catalog_includes_legalities_and_formats():
    resp = client.get("/api/cards/catalog")
    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload["formats"], list)
    assert {f["key"] for f in payload["formats"]} >= {"casual", "modern", "legacy", "vintage", "commander"}
    lotus = next((c for c in payload["cards"] if c["name"] == "Black Lotus"), None)
    assert lotus is not None
    assert lotus["legalities"].get("legacy") == "banned"


def test_deck_summary_includes_format_and_legality():
    deck = {
        "id": "testdeck",
        "name": "Power Deck",
        "cards": [{"name": "Black Lotus", "count": 1}],
        "format": "legacy",
    }
    summary = _deck_summary(deck)
    assert summary["format"] == "legacy"
    assert summary["legality"]["legal"] is False
    assert "Black Lotus" in summary["legality"]["illegal_names"]


def test_deck_summary_defaults_to_casual_when_unset():
    deck = {"id": "d2", "name": "No Format", "cards": [{"name": "Black Lotus", "count": 4}]}
    summary = _deck_summary(deck)
    assert summary["format"] == "casual"
    assert summary["legality"]["legal"] is True
