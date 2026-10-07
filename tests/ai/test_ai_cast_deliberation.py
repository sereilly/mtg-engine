"""One cast decision reads the table with nothing cast **once**.

Every card ``choose_cast_action`` weighs is measured against the same table
with nothing cast (``ai_valuation.rehearse``), and that reading is a copy of
the game run out to the end of its turn. Each card took its own: the
deliberation that keeps the reading (``ai_valuation.deliberating``) was opened
per card, so a hand of two removal spells read one table twice.

It is cost and nothing else, and the tests here say so two ways: the count of
copies a decision takes, and the decision itself against the one each card
weighed in a deliberation of its own would have made. What that buys in a
whole game is small and is measured in the round's report rather than here —
a limited deck seldom holds two instants it can afford at once.
"""
from __future__ import annotations

from collections import Counter
from unittest import mock

import pytest

from engine import Game, PlayerState
from engine import ai_policy, ai_valuation
from engine.ai_policy import cast_announcement, choose_cast_action
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from tests.helpers import _mk_creature_card

ME, OPP = 0, 1


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths())):
        cards.setdefault(card.name, card)
    return cards


def _table(pool, hand, mine=(), theirs=(), *, costs: bool = False) -> Game:
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState(name="AI", hand=list(hand), library=[forest] * 20),
        PlayerState(name="Opp", hand=[], library=[forest] * 20),
    ])
    game.enforce_mana_costs = costs
    game.interactive_seats = set()
    for seat, cards in ((ME, mine), (OPP, theirs)):
        for card in cards:
            permanent = Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, seat)
            permanent.metadata["summoning_sickness_turn"] = -99
    return game


class _Counted:
    """How many scratch copies were taken, and how many of them were a
    reading of the table with nothing cast."""

    def __init__(self) -> None:
        self.tally: Counter = Counter()
        real_copy = ai_valuation.scratch_copy_with
        real_untouched = ai_valuation._untouched
        real_rehearse = ai_valuation._rehearse

        def copy(game, carried):
            self.tally["copies"] += 1
            return real_copy(game, carried)

        def untouched(game, **asked):
            before = self.tally["copies"]
            reading = real_untouched(game, **asked)
            self.tally["baselines"] += self.tally["copies"] - before
            return reading

        def rehearse(*args, **asked):
            self.tally["rehearsals"] += 1
            return real_rehearse(*args, **asked)

        self.patches = [
            mock.patch.object(ai_valuation, "scratch_copy_with", copy),
            mock.patch.object(ai_valuation, "_untouched", untouched),
            mock.patch.object(ai_valuation, "_rehearse", rehearse),
        ]

    def __enter__(self) -> Counter:
        for patch in self.patches:
            patch.start()
        return self.tally

    def __exit__(self, *exc) -> None:
        for patch in reversed(self.patches):
            patch.stop()


def _removal_hand(pool) -> list:
    return [pool["Terror"], pool["Lightning Bolt"], pool["Swords to Plowshares"]]


def _their_creatures() -> list:
    return [_mk_creature_card("Their Ogre", 3, 3), _mk_creature_card("Their Bear", 2, 2)]


def test_a_hand_of_removal_reads_the_untouched_table_once(pool):
    """Three removal spells and two creatures to aim them at: every one of
    those rehearsals is measured against the same table with nothing cast,
    and it was read once per card — three times."""
    game = _table(pool, _removal_hand(pool), theirs=_their_creatures())
    with _Counted() as tally:
        action = choose_cast_action(game, ME)
    assert action is not None
    # Each spell was weighed at each creature and as the cast it would be.
    assert tally["rehearsals"] >= 6, dict(tally)
    assert tally["baselines"] == 1, dict(tally)
    assert tally["copies"] == tally["rehearsals"] + 1, dict(tally)


@pytest.mark.parametrize("costs", [False, True], ids=["free", "paid"])
def test_the_decision_is_the_one_each_card_weighed_alone_would_make(pool, costs):
    """Sharing the reading decides nothing: the cast proposed is the cast
    proposed with every card in a deliberation of its own, which is what
    `_choose_cast_action` is when nothing has opened one around it."""
    lands = [pool["Swamp"], pool["Mountain"], pool["Plains"], pool["Swamp"]]
    for hand in (
        _removal_hand(pool),
        [pool["Lightning Bolt"], pool["Lightning Bolt"]],
        [pool["Terror"], pool["Giant Growth"], pool["Mind Rot"]],
    ):
        def table() -> Game:
            return _table(
                pool, hand, mine=[*lands, _mk_creature_card("My Bear", 2, 2)],
                theirs=_their_creatures(), costs=costs,
            )

        def proposal(game, choose):
            # Slots, not ids: two tables built alike number their permanents
            # differently (CR 400.7's counter is the process's).
            action = choose(game, ME)
            assert action is not None
            named = [
                (game.controller_index_of(named), game.battlefield_index_of(named))
                for named in map(game.permanent_by_id, action.target_permanent_ids or ())
            ]
            return {**cast_announcement(action), "target_permanent_ids": named,
                    "card": action.card_name, "score": action.score,
                    "taps": action.land_tap_indices}

        together = proposal(table(), choose_cast_action)
        apart = proposal(table(), ai_policy._choose_cast_action)
        assert together == apart, (hand, together, apart)


def test_one_announcement_paid_for_two_ways_is_two_rehearsals(pool):
    """What a rehearsal is kept under inside a deliberation: the announcement
    **and the plan that pays for it**. A card priced twice (a free cast that
    takes a kicker is priced again as an ordinary one) announces the same
    thing over two payments, and the lands left untapped are what the
    resolution has to spend — so the second is not the first read back."""
    bolt = pool["Lightning Bolt"]
    game = _table(
        pool, [bolt], mine=[pool["Mountain"], pool["Mountain"]],
        theirs=_their_creatures(), costs=True,
    )
    action = choose_cast_action(game, ME)
    assert action is not None and action.land_tap_indices == (0,)
    other = ai_policy.replace(action, land_tap_indices=(1,))
    with _Counted() as tally, ai_valuation.deliberating():
        for planned in (action, action, other, other):
            rehearsal = ai_policy._rehearse_announcement(
                game, ME, bolt, cast_announcement(planned), planned=planned,
            )
            assert rehearsal is not None and rehearsal.accepted
    assert tally["rehearsals"] == 2, dict(tally)
