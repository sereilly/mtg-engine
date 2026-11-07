"""Each Conclave Mentor is its own effect, and each applies once (CR 616.1f).

"If you control two Conclave Mentors, the number of +1/+1 counters put on a
creature is two plus the original number. Three Conclave Mentors add three,
and so on." (Conclave Mentor's ruling, 2020-06-23.) The one registration that
stands for every copy added one in all, so two Mentors put two counters on a
creature where the card puts three — found by round kg4 `asks` classifying
the `plus1_counters` site as one effect.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


@pytest.mark.parametrize("mentors", [0, 1, 2, 3])
def test_each_mentor_adds_one_counter(set_pool, mentors):
    pool = set_pool("M21")
    bears_card = set_pool("LEA")["Grizzly Bears"]
    game = Game(players=[PlayerState("P0"), PlayerState("P1")])
    game.enforce_mana_costs = False
    for _ in range(mentors):
        game._put_permanent_onto_battlefield(0, Permanent(card=pool["Conclave Mentor"]), None)
    # An opponent's Mentor says nothing about a creature you control.
    game._put_permanent_onto_battlefield(1, Permanent(card=pool["Conclave Mentor"]), None)
    bears = Permanent(card=bears_card)
    game._put_permanent_onto_battlefield(0, bears, None)
    resolve_stack(game)

    assert game.place_plus1_counters(bears, 2) == 2 + mentors
    assert int(bears.metadata.get("plus_counters", 0) or 0) == 2 + mentors
