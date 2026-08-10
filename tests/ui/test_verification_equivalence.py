"""The derived `equivalent` status (web/verification_report.py + behaviour_signature).

An untested card whose behaviour class already contains a *passing* card is
reported as `equivalent` rather than `untested`: the engine resolves it through
the same code paths, so a separate manual pass would exercise nothing new.

The whole current pool is marked passing, so nothing in production data
exercises this. These drive it directly, with the store patched, and pin the
properties that make the status honest — above all that it is derived rather
than stored, so it can never be mistaken for a human check and it follows its
peer if that peer's result changes.
"""

import pytest

import web.app as web_app
from web.app import _verification_listing

# Aladdin's Ring and Rod of Ruin share a behaviour class: the same activated
# damage ability, differing only in constants. See BEHAVIOUR_CLASSES.md.
CARD = "Aladdin's Ring"
PEER = "Rod of Ruin"


@pytest.fixture
def results(monkeypatch):
    """A verification store holding only what a test puts in it."""
    state: dict[str, dict] = {}
    monkeypatch.setattr(web_app.verification_store, "results", lambda: state)
    return state


def _entry(cards, name):
    return next(c for c in cards if c["card_name"] == name)


def test_untested_card_with_a_passing_peer_is_reported_equivalent(results):
    results[PEER] = {"status": "pass", "reason": "", "updated_at": 0.0}

    cards, counts = _verification_listing()
    entry = _entry(cards, CARD)

    assert entry["status"] == "equivalent"
    assert entry["equivalent_to"] == PEER, "the peer it rests on is named"
    assert counts["equivalent"] >= 1


def test_equivalence_does_not_apply_without_a_passing_peer(results):
    """A class where nobody has been verified confers nothing — equivalence
    propagates verification, it does not create it."""
    cards, _ = _verification_listing()

    assert _entry(cards, CARD)["status"] == "untested"
    assert _entry(cards, PEER)["status"] == "untested"


def test_a_failing_peer_confers_nothing(results):
    """Only a *passing* peer counts. Deriving from a known-broken card would
    launder a failure into coverage."""
    results[PEER] = {"status": "fail", "reason": "broken", "updated_at": 0.0}

    cards, _ = _verification_listing()

    assert _entry(cards, CARD)["status"] == "untested"


def test_the_derived_status_follows_its_peer(results):
    """Because it is computed on read rather than written down, demoting the
    peer immediately withdraws the claim from everything resting on it."""
    results[PEER] = {"status": "pass", "reason": "", "updated_at": 0.0}
    assert _entry(_verification_listing()[0], CARD)["status"] == "equivalent"

    results[PEER] = {"status": "fail", "reason": "regression", "updated_at": 1.0}

    assert _entry(_verification_listing()[0], CARD)["status"] == "untested"


def test_a_recorded_result_always_wins_over_equivalence(results):
    """If a human actually checked the card, that is what the tracker shows —
    a derived status must never overwrite or mask a real one."""
    results[PEER] = {"status": "pass", "reason": "", "updated_at": 0.0}
    results[CARD] = {"status": "fail", "reason": "found a bug", "updated_at": 1.0}

    entry = _entry(_verification_listing()[0], CARD)

    assert entry["status"] == "fail"
    assert entry["reason"] == "found a bug"
    assert entry["equivalent_to"] is None


def test_equivalence_is_never_written_to_the_store(results):
    """The JSON is the record of what people checked. Reading the listing must
    not add derived entries to it, or the two claims become indistinguishable
    the moment the file is reloaded."""
    results[PEER] = {"status": "pass", "reason": "", "updated_at": 0.0}

    _verification_listing()

    assert set(results) == {PEER}


def test_a_card_with_no_behavioural_peer_stays_untested(results):
    """Most cards are behaviourally unique — equivalence must not quietly
    cover them."""
    results[PEER] = {"status": "pass", "reason": "", "updated_at": 0.0}

    cards, _ = _verification_listing()

    # Shahrazad's subgame simplification is its own behaviour.
    assert _entry(cards, "Shahrazad")["status"] == "untested"
