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


def _card(name, legal, *, type_line="Creature - Test", oracle_text="", key="modern"):
    return {"name": name, "type_line": type_line, "oracle_text": oracle_text,
            "legalities": {key: legal}}


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
    res = validate_deck([{"name": "Forest", "count": 101}], "commander", cat)
    assert any("at most 100" in p for p in res["problems"])


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
