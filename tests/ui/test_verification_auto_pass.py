"""The derived auto-pass (web/verification_report.py + engine.oracle.simple_card_keywords).

An untested *simple* card — no abilities at all, or nothing but keywords the
engine implements — is reported as ``pass`` without anyone checking it: its
behaviour is the generic combat and keyword code plus its printed numbers, so a
manual in-game pass would exercise no card-specific path. Like ``equivalent``
it is derived on read and never written to ``card_verification.json``, so the
human record stays distinguishable from it and a recorded result always wins.
"""

import pytest
from fastapi.testclient import TestClient

import web.app as web_app
from web.app import _verification_listing, app
from web.runtime import AUTO_PASSES

client = TestClient(app)

VANILLA = "Grizzly Bears"             # no abilities
KEYWORDED = "Baneslayer Angel"        # flying, first strike, lifelink, protection from …
NOT_SIMPLE = "Rod of Ruin"            # an activated ability: needs a real check
BASIC = "Forest"                      # only the reminder text of its intrinsic mana ability


@pytest.fixture
def results(monkeypatch):
    """A verification store holding only what a test puts in it."""
    state: dict[str, dict] = {}
    monkeypatch.setattr(web_app.verification_store, "results", lambda: state)
    return state


def _entry(cards, name):
    return next(c for c in cards if c["card_name"] == name)


def test_a_card_with_no_abilities_auto_passes(results):
    cards, counts = _verification_listing()
    entry = _entry(cards, VANILLA)

    assert entry["status"] == "pass"
    assert entry["auto_pass"] == "no abilities"
    assert entry["updated_at"] is None, "nothing was recorded for it"
    assert counts["auto_pass"] >= 1


def test_a_keyword_only_card_auto_passes_naming_its_keywords(results):
    entry = _entry(_verification_listing()[0], KEYWORDED)

    assert entry["status"] == "pass"
    assert entry["auto_pass"] == (
        "keywords only (flying, first strike, lifelink, "
        "protection from demons and from dragons)"
    )


def test_a_basic_land_auto_passes(results):
    """A basic land's only text is reminder text for CR 305.6's intrinsic mana
    ability — nothing printed, nothing card-specific to check."""
    assert _entry(_verification_listing()[0], BASIC)["auto_pass"] == "no abilities"


def test_a_card_with_a_real_ability_is_not_auto_passed(results):
    entry = _entry(_verification_listing()[0], NOT_SIMPLE)

    assert entry["status"] == "untested"
    assert entry["auto_pass"] is None


def test_auto_passes_are_counted_inside_passed(results):
    """``pass`` is the total the tracker reports; ``auto_pass`` is the share of
    it nobody checked, kept visible so the two cannot be confused."""
    cards, counts = _verification_listing()

    auto = [c for c in cards if c["auto_pass"]]
    assert counts["auto_pass"] == len(auto)
    assert counts["pass"] == len(auto), "with nothing recorded, every pass is an auto-pass"
    assert all(c["status"] == "pass" for c in auto)


def test_a_recorded_result_always_wins_over_the_auto_pass(results):
    """If a human actually checked the card — a vanilla creature whose printed
    P/T the data got wrong, say — that is what the tracker shows."""
    results[VANILLA] = {"status": "fail", "reason": "printed as 3/3", "updated_at": 1.0}

    cards, counts = _verification_listing()
    entry = _entry(cards, VANILLA)

    assert entry["status"] == "fail"
    assert entry["reason"] == "printed as 3/3"
    assert entry["auto_pass"] is None
    assert counts["fail"] == 1


def test_a_recorded_pass_is_not_double_counted_as_auto(results):
    results[VANILLA] = {"status": "pass", "reason": "", "updated_at": 1.0}

    cards, counts = _verification_listing()
    entry = _entry(cards, VANILLA)

    assert entry["status"] == "pass"
    assert entry["auto_pass"] is None
    assert counts["auto_pass"] == len(AUTO_PASSES) - 1


def test_the_auto_pass_is_never_written_to_the_store(results):
    """The JSON is the record of what people checked."""
    _verification_listing()

    assert results == {}


def test_an_auto_pass_does_not_seed_equivalence(results):
    """Equivalence propagates checks; an auto-pass is not one. With nothing
    recorded there are auto-passes but no ``equivalent`` cards at all, even
    though some simple cards share a behaviour class with other cards."""
    cards, counts = _verification_listing()

    assert counts["auto_pass"] > 0
    assert counts["equivalent"] == 0
    assert all(c["equivalent_to"] is None for c in cards)


def test_next_untested_never_offers_an_auto_passed_card(results):
    """The Debug Menu's "add an untested card" button must not keep handing
    out vanilla creatures: there is nothing to check on them."""
    seen = set()
    for _ in range(60):
        resp = client.get("/api/verification/next-untested")
        assert resp.status_code == 200
        payload = resp.json()
        seen.add(payload["card_name"])
        assert payload["card_name"] not in AUTO_PASSES
    # `remaining` is the pool it draws from, which excludes them too.
    total = len(_verification_listing()[0])
    assert payload["remaining"] == total - len(AUTO_PASSES)
    assert seen, "the endpoint draws from the non-simple pool"


def test_the_markdown_names_the_auto_pass(results, monkeypatch, tmp_path):
    import web.verification_report as report

    md = tmp_path / "CARD_VERIFICATION.md"
    monkeypatch.setattr(report, "VERIFICATION_MD_PATH", md)
    report.write_verification_markdown()
    text = md.read_text(encoding="utf-8")

    assert f"| {VANILLA} | ✅ pass | auto-pass: no abilities |" in text
    assert f"| {KEYWORDED} | ✅ pass | auto-pass: keywords only (" in text
    assert "auto-passed)" in text, "the summary line splits checked from auto-passed"
