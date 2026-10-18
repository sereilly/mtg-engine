"""A rehearsal that raises is counted, and a simulated run that had one fails.

The policy carries a candidate cast out on a copy of the game before it
proposes it (``ai_valuation.rehearse``). A copy that raises answers None —
"this could not be weighed" — which is right for a game somebody is playing
and is also a silence: before a cast was rehearsed, an engine exception on a
card's cast was raised by the real cast and stopped a simulated run on the
spot. That was how a crash-on-cast card was found. Caught one layer down, the
same exception is a card held or cast unweighed, and nothing says why.

So each one is written down (``ai_valuation.REHEARSALS_RAISED``), and the
simulator reports what its run added (``SimulationReport.rehearsals_raised``)
with an issue per distinct one — which is what makes
``scripts/simulate_ai_games.py`` exit 1.
"""
from __future__ import annotations

from collections import Counter
from unittest import mock

import pytest

from engine import Game, PlayerState
from engine import ai_valuation
from engine.ai_policy import choose_cast_action
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import load_cards, manifest_set_path, manifest_set_paths
from engine.faces import compilation_units
from engine.handlers import EFFECT_HANDLERS
from engine.models import Permanent
from tests.helpers import _mk_creature_card, resolve_stack

ME, OPP = 0, 1


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths())):
        cards.setdefault(card.name, card)
    return cards


class damage_that_raises_in_a_rehearsal:
    """``deal_damage`` raising where a rehearsal carries it out, and working
    as it always did in the game itself — an engine bug as the policy now
    meets it: on the copy, first."""

    def __enter__(self):
        real = EFFECT_HANDLERS["deal_damage"]

        def handler(game, instruction, context):
            if ai_valuation.rehearsing():
                raise RuntimeError("the handler under test raised")
            return real(game, instruction, context)

        self.patch = mock.patch.dict(EFFECT_HANDLERS, {"deal_damage": handler})
        self.patch.start()
        self.before = Counter(ai_valuation.REHEARSALS_RAISED)
        return self

    def raised(self) -> Counter:
        return ai_valuation.REHEARSALS_RAISED - self.before

    def __exit__(self, *exc) -> None:
        self.patch.stop()


def test_a_rehearsal_that_raises_is_written_down(pool):
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState(name="AI", hand=[pool["Lightning Bolt"]], library=[forest] * 10),
        PlayerState(name="Opp", hand=[], library=[forest] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    ogre = Permanent(card=_mk_creature_card("Their Ogre", 3, 3))
    game._put_permanent_onto_battlefield(OPP, ogre, OPP)

    with damage_that_raises_in_a_rehearsal() as spy:
        action = choose_cast_action(game, ME)
        raised = spy.raised()
        # What was rehearsed, what was raised, and where it came from.
        assert raised, "a rehearsal raised and nothing recorded it"
        assert all(
            what.startswith("Lightning Bolt: RuntimeError: the handler under test raised")
            and "in handler" in what
            for what in raised
        ), dict(raised)
        # And this is the silence the record exists for: a spell that may
        # name a player or a creature, with nobody able to weigh which, is
        # **held** — every turn, for the rest of the game.
        assert action is None
    # The game itself was never touched: the same cast, made for real with the
    # handler as it is, resolves.
    result = game.cast_from_hand(
        ME, "Lightning Bolt", target_player_index=OPP,
        target_permanent_ids=[ogre.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)
    game.check_state_based_actions()
    assert ogre not in list(game.controlled_by(OPP))


def test_a_run_with_a_raised_rehearsal_is_not_ok():
    """The simulator's count: what the run added, an issue naming the card
    and the exception, and a report that is not ``ok`` — which is the exit
    code."""
    with damage_that_raises_in_a_rehearsal():
        report = run_ai_simulation(
            manifest_set_path("LEA"), games=2, seed=7, max_turns=8,
            required_cards=["Lightning Bolt"],
        )
    assert report.rehearsals_raised, "the run rehearsed no Lightning Bolt; pick another seed"
    assert all("Lightning Bolt" in what or "RuntimeError" in what
               for what in report.rehearsals_raised)
    assert not report.ok
    messages = [issue.message for issue in report.issues]
    assert any(
        "A rehearsal raised" in message and "RuntimeError" in message
        for message in messages
    ), messages
    # One issue per distinct exception, however many times it was raised.
    raised_issues = [m for m in messages if "A rehearsal raised" in m]
    assert len(raised_issues) == len(report.rehearsals_raised)


def test_a_clean_run_raises_none():
    report = run_ai_simulation(manifest_set_path("LEA"), games=2, seed=7, max_turns=8)
    assert report.rehearsals_raised == Counter()
    assert report.interaction_count > 0
