"""The CR 104.1 substitution both flip cards share.

``engine/dexterity.py`` is not an implementation of a rule — it is a house
rule standing in for a physical action the engine cannot perform. These tests
pin the substitution's own contract, so that the two cards using it cannot
drift apart the way two hand-rolled ``random.sample`` calls would.
"""

from __future__ import annotations

import random

import pytest

from engine.dexterity import FLIP_TURNS_OVER, flip_lands_on


def test_a_flip_lands_on_no_more_than_the_maximum():
    for seed in range(50):
        random.seed(seed)
        assert len(flip_lands_on(list(range(10)), maximum=3)) <= 3


def test_a_flip_lands_on_at_least_the_minimum_when_there_is_room():
    for seed in range(50):
        random.seed(seed)
        assert len(flip_lands_on(list(range(10)), minimum=1, maximum=3)) >= 1


def test_the_size_varies_rather_than_being_fixed():
    """A substitution that always picked the maximum would pass both bounds
    checks above and be a different house rule."""
    sizes = set()
    for seed in range(50):
        random.seed(seed)
        sizes.add(len(flip_lands_on(list(range(10)), minimum=1, maximum=3)))
    assert sizes == {1, 2, 3}, sizes


def test_a_minimum_is_clamped_to_what_is_on_the_board():
    """Falling Star lands on "one to three" creatures, but a board with one
    creature has one to give and an empty board has none. Clamping rather than
    raising is what lets the caller state the card's own numbers."""
    random.seed(0)
    assert flip_lands_on([], minimum=1, maximum=3) == []
    assert len(flip_lands_on(["only"], minimum=1, maximum=3)) == 1


def test_a_flip_never_lands_on_the_same_object_twice():
    for seed in range(20):
        random.seed(seed)
        hits = flip_lands_on(list(range(5)), minimum=1, maximum=5)
        assert len(hits) == len(set(hits))


def test_the_flip_is_drawn_from_the_seeded_module_rng():
    """``run_ai_simulation`` seeds ``random``; a private Random here would
    silently break the determinism every AI regression test depends on."""
    random.seed(7)
    first = flip_lands_on(list(range(10)), minimum=1, maximum=3)
    random.seed(7)
    assert flip_lands_on(list(range(10)), minimum=1, maximum=3) == first


def test_the_flip_is_treated_as_turning_over():
    """Both cards gate their effect on the card turning completely over. The
    engine treats that as met — a second invented probability on top of the
    landing would make either card untestable without pinning a seed."""
    assert FLIP_TURNS_OVER is True
