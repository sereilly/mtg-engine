"""CR 611.3a — continuous effects apply dynamically, so recomputing must be idempotent.

Static and conditional P/T effects are *derived*: every recompute clears the
channel they contribute to and rebuilds it from the current board. The
alternative — adding to a persistent bonus and subtracting it again next time —
requires every effect to record exactly what it contributed, and any mismatch
compounds, because CR 611.3a means the recompute runs constantly.

That is not hypothetical. Aspect of Wolf shipped with under-recorded stacking
(tests/regressions/test_batch17.py). These tests pin the general property
rather than the individual cards: refreshing repeatedly must not drift, and a
condition becoming false must remove its bonus without anything having to undo
it.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent


def _board(cards, arn, *, forests: int = 0):
    """A board with Kird Ape (+1/+2 while you control a Forest), a Giant
    Tortoise (+0/+2 while untapped), and *forests* Forests."""
    ape = Permanent(card=arn["Kird Ape"])
    tortoise = Permanent(card=arn["Giant Tortoise"])
    lands = [Permanent(card=cards["Forest"]) for _ in range(forests)]
    p1 = PlayerState(name="P1", battlefield=[ape, tortoise, *lands], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    return game, p1, ape, tortoise


@pytest.mark.cr("611.3a")
def test_repeated_recomputes_do_not_drift(cards, arn_by_name):
    """The property that matters: recomputing N times equals recomputing once."""
    game, _, ape, tortoise = _board(cards, arn_by_name, forests=1)

    game._recompute_continuous_effects()
    first = (ape.effective_power, ape.effective_toughness,
             tortoise.effective_power, tortoise.effective_toughness)

    for _ in range(25):
        game._recompute_continuous_effects()

    assert (ape.effective_power, ape.effective_toughness,
            tortoise.effective_power, tortoise.effective_toughness) == first


@pytest.mark.cr("611.3a")
def test_a_conditional_bonus_appears_and_disappears_with_its_condition(cards, arn_by_name):
    game, p1, ape, _ = _board(cards, arn_by_name, forests=0)

    game._recompute_continuous_effects()
    without_forest = (ape.effective_power, ape.effective_toughness)

    p1.battlefield.append(Permanent(card=cards["Forest"]))
    game._recompute_continuous_effects()
    with_forest = (ape.effective_power, ape.effective_toughness)
    assert with_forest[0] == without_forest[0] + 1
    assert with_forest[1] == without_forest[1] + 2

    # Removing the Forest must restore the original values exactly — nothing
    # has to remember what was added in order to take it back.
    p1.battlefield = [perm for perm in p1.battlefield if perm.card.name != "Forest"]
    game._recompute_continuous_effects()
    assert (ape.effective_power, ape.effective_toughness) == without_forest


@pytest.mark.cr("611.3a")
def test_a_state_dependent_bonus_tracks_the_state(cards, arn_by_name):
    """Giant Tortoise is bigger only while untapped, so tapping and untapping it
    must move the bonus with no bookkeeping.

    The sizes come from the card rather than being written in here: the point
    is that the bonus tracks the state and that untapping restores exactly what
    tapping removed, however large it is.
    """
    game, _, _, tortoise = _board(cards, arn_by_name)
    printed = tortoise.card.base_toughness

    game._recompute_continuous_effects()
    untapped = tortoise.effective_toughness
    assert untapped > printed, "the untapped bonus should apply"

    tortoise.tapped = True
    game._recompute_continuous_effects()
    assert tortoise.effective_toughness == printed

    tortoise.tapped = False
    game._recompute_continuous_effects()
    assert tortoise.effective_toughness == untapped


@pytest.mark.cr("611.3a")
def test_derived_bonuses_do_not_leak_into_the_counter_channel(cards, arn_by_name):
    """``power_bonus`` means counters and other permanent modifications. A
    continuous effect writing there is what created the compounding bug, so it
    must stay clean however many times the board is recomputed."""
    game, _, ape, tortoise = _board(cards, arn_by_name, forests=2)

    for _ in range(10):
        game._recompute_continuous_effects()

    for perm in (ape, tortoise):
        assert perm.power_bonus == 0, f"{perm.card.name} leaked into power_bonus"
        assert perm.toughness_bonus == 0, f"{perm.card.name} leaked into toughness_bonus"


@pytest.mark.cr("611.3a")
def test_counters_and_derived_bonuses_add_together(cards, arn_by_name):
    """A +1/+1 counter is not a continuous effect — it lives on the permanent.
    Both channels must apply."""
    game, _, ape, _ = _board(cards, arn_by_name, forests=1)

    game._recompute_continuous_effects()
    before = ape.effective_power

    ape.power_bonus += 3  # a counter, not an effect
    game._recompute_continuous_effects()
    assert ape.effective_power == before + 3
