"""Guards for behavioural equivalence (engine/behaviour_signature.py).

Equivalence is used to decide that a card needs no separate manual verification
because a verified peer already exercises its engine paths. That makes the
signature a correctness claim, and its failure mode is silent: if it stops
distinguishing two behaviours, coverage *rises* and nothing looks wrong.

So there are two kinds of guard here — a snapshot ratchet over the whole set of
classes, and explicit pairs that must never merge. The pairs are the ones a real
signature bug produced: dropping produced_mana, activated payloads, and the
oracle text the text-keyed channels read made the engine declare Flight
equivalent to Control Magic.
"""

import json
from pathlib import Path

import pytest

from engine.behaviour_signature import behaviour_signature
from engine.card_loader import load_catalog

SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "behaviour_classes_snapshot.json"


@pytest.fixture(scope="module")
def catalog_by_name():
    return {card.name: card for card in load_catalog()}


def _current_classes() -> set[frozenset[str]]:
    from engine.behaviour_signature import behaviour_classes

    return {frozenset(names) for names in behaviour_classes(load_catalog()).values() if len(names) > 1}


def test_behaviour_classes_match_the_reviewed_snapshot():
    """The classes are a ratchet. A class that gains a member means two cards
    the engine used to treat differently now look identical — which silently
    inflates how much of the pool counts as verified. Review the change, then
    `python scripts/behaviour_classes.py --accept`."""
    snapshot = {frozenset(entry) for entry in json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))}
    current = _current_classes()

    added = sorted(sorted(c) for c in current - snapshot)
    removed = sorted(sorted(c) for c in snapshot - current)

    assert not added, f"new/changed behaviour classes (review, then --accept): {added}"
    assert not removed, f"behaviour classes that vanished (review, then --accept): {removed}"


# (a, b, why they are genuinely different) — every one of these was merged by a
# real signature bug, so each names the input that must stay in the signature.
MUST_DIFFER = [
    ("Flight", "Control Magic", "aura behaviour lives in oracle text, not the instruction"),
    ("Forest", "Badlands", "one colour of mana produced vs two"),
    ("Sol Ring", "Mox Emerald", "{C}{C} vs a single mana"),
    ("Lightning Bolt", "Healing Salve", "damage vs life gain"),
    ("Grizzly Bears", "Air Elemental", "a keyword is a different engine path"),
    ("Wall of Stone", "Hill Giant", "defender changes what the combat code does"),
]


@pytest.mark.parametrize("first,second,why", MUST_DIFFER)
def test_distinct_behaviours_never_share_a_signature(catalog_by_name, first, second, why):
    assert behaviour_signature(catalog_by_name[first]) != behaviour_signature(
        catalog_by_name[second]
    ), f"{first} and {second} must not be equivalent: {why}"


# Pairs that SHOULD be equivalent: the whole point is that values the engine
# handles generically don't make a new behaviour.
MUST_MATCH = [
    ("Grizzly Bears", "Hill Giant", "vanilla creatures differing only in power/toughness"),
    ("Aladdin's Ring", "Rod of Ruin", "same activated damage ability, different constants"),
    ("Circle of Protection: Black", "Circle of Protection: Red", "colour is data, not control flow"),
    ("Stone Rain", "Sinkhole", "destroy target land"),
]


@pytest.mark.parametrize("first,second,why", MUST_MATCH)
def test_generic_values_do_not_create_a_new_behaviour(catalog_by_name, first, second, why):
    assert behaviour_signature(catalog_by_name[first]) == behaviour_signature(
        catalog_by_name[second]
    ), f"{first} and {second} should be equivalent: {why}"


def test_every_class_is_non_trivial():
    """A class must group cards that really are alike. An empty signature —
    one that captured nothing and matched everything — would show up as a
    single enormous class, so cap how much of the pool any one class may hold."""
    catalog = load_catalog()
    largest = max((len(c) for c in _current_classes()), default=0)

    assert largest <= len(catalog) // 10, (
        f"largest behaviour class holds {largest} of {len(catalog)} cards — the "
        "signature is probably not distinguishing enough"
    )
