"""``tests.helpers.resolve_stack`` — the drain a test must use, and why.

``while game.stack: game.resolve_top_of_stack()`` is a **latent hang**, and the
hang is the engine being correct. CR 608.2 says a resolution is not over until
its last instruction is done and CR 117.3b says nobody receives priority until
then, so an object that stopped to ask a seat something stays on the stack and
``resolve_top_of_stack`` reports False for it. The bare loop then spins on a
stack that never empties: no failure, no output, the whole suite wedged on one
test. It costs nothing until a card in the test's pool starts asking something,
which is why it survives review — the loop was correct on the day it was
written.

These tests pin the two halves of the helper's contract: it drains what the
bare loop drains, and where the bare loop would spin it either makes progress
through the registry's defaults or fails saying what is owed.
"""

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition
from tests.helpers import _mk_card, resolve_stack


def _duel(*, interactive: set[int] | None = None) -> Game:
    p1, p2 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(
        players=[p1, p2],
        interactive_seats=set() if interactive is None else interactive,
    )
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game


@pytest.mark.cr("608.2")
def test_an_empty_stack_resolves_nothing_and_returns_zero():
    """The degenerate case the bare loop also gets right, pinned so the helper
    cannot start requiring a non-empty stack."""
    assert resolve_stack(_duel()) == 0


@pytest.mark.cr("608.2", "117.3b")
def test_a_prompt_owed_mid_resolution_is_answered_rather_than_spun_on():
    """The hazard itself, in the shape that hangs.

    A seat is owed a decision that records the object which armed it, so the
    object is held on the stack (CR 608.2) and no step advances (CR 117.3b).
    ``resolve_top_of_stack`` reports False for exactly as long as the prompt is
    owed, which is forever if nobody answers it — the bare loop's spin.

    The helper answers through ``auto_resolve_pending_choices``, the same
    default path an AI or headless seat takes, so the stack drains and the test
    sees the answer a non-interactive game would have given.
    """
    game = _duel()
    library = [_mk_card(n, "Artifact") for n in ("A", "B", "C")]
    game.players[0].library = list(library)
    game.players[0].hand = [_mk_card("X", "Artifact"), _mk_card("Y", "Artifact")]

    game.arm_pending_choice("hand_to_library", 0, count=1)
    assert game.pending_choices, "the rig must actually owe a decision"

    resolve_stack(game)

    assert game.pending_choices == [], "the helper left a prompt owed"


@pytest.mark.cr("608.2")
def test_a_stack_that_stops_moving_fails_instead_of_hanging():
    """The other half: a stack that cannot progress and has nothing to answer.

    That is a bug in the engine or the rig rather than in the test, and the
    helper's job is to make it a *failure* — naming what the game is waiting on
    — instead of a run that never ends. Anything that swallows this and returns
    quietly would put the hang back one level up.
    """

    class _Stuck(Game):
        def resolve_top_of_stack(self, pause_for_choices: bool = False) -> bool:
            return False

    game = _Stuck(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.stack.append(object())

    with pytest.raises(AssertionError, match="stopped moving"):
        resolve_stack(game)


@pytest.mark.cr("608.2")
def test_the_iteration_bound_is_a_failure_and_not_a_silent_return():
    """A drain that makes progress forever is still a hang, so the bound fails
    too. Reported separately from the stuck case because the causes differ: this
    one is a loop that keeps producing work, that one is work nothing can do."""

    class _Endless(Game):
        def resolve_top_of_stack(self, pause_for_choices: bool = False) -> bool:
            self.stack.append(object())
            return True

    game = _Endless(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.stack.append(object())

    with pytest.raises(AssertionError, match="did not drain"):
        resolve_stack(game, limit=10)
