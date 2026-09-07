"""``tests.helpers.resolve_stack`` — the drain a test must use, and why.

``while game.stack: game.resolve_top_of_stack()`` is a **latent hang**, and the
hang is the engine being correct. CR 608.2 says a resolution is not over until
its last instruction is done and CR 117.3b says nobody receives priority until
then, so an object that stopped to ask an interactive seat something stays on
the stack and ``resolve_top_of_stack`` reports False for it. The bare loop then
spins on a stack that never empties: no failure, no output, the whole suite
wedged on one test. It costs nothing until a card in the test's pool starts
asking something, which is why such a loop survives review — the loop was
correct on the day it was written.

These pin the whole of the helper's contract, and the third is as load-bearing
as the second. The helper answers a decision **only while it blocks the stack**:
a draft that settled the queue on every iteration broke 41 tests, because a test
that resolves a spell and then inspects what the resolution asked was reading a
prompt the helper had answered out from under it. Narrow is what makes it a safe
swap for the bare loop.
"""

import pytest

from engine import Game, PlayerState
from engine.game_types import StackItem
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


def _held_stack_item(game: Game) -> StackItem:
    """An object on the stack that has run its instructions and is waiting.

    ``resolution_held`` is what ``resolve_top_of_stack`` reads to mean "this has
    already run; it stays until it owes nobody anything", so an item in that
    state with a prompt naming it is the engine's own shape for a resolution
    paused part-way — not a stand-in for one.
    """
    item = StackItem(
        card=_mk_card("Held", "Sorcery"),
        caster_index=0,
        target_player_index=None,
        target_permanent_index=None,
        x_value=None,
    )
    item.resolution_held = True
    game.stack.append(item)
    return item


@pytest.mark.cr("608.2")
def test_an_empty_stack_resolves_nothing_and_returns_zero():
    """The degenerate case the bare loop also gets right, pinned so the helper
    cannot grow a requirement that the stack be non-empty."""
    assert resolve_stack(_duel()) == 0


@pytest.mark.cr("608.2", "117.3b")
def test_a_prompt_holding_the_stack_is_answered_rather_than_spun_on():
    """The hazard itself, in the shape that hangs.

    ``resolution_held`` plus a prompt recording the object is what the engine
    sets when a resolution stops to ask an interactive seat something: the
    object stays on the stack (CR 608.2), no step advances (CR 117.3b), and
    ``resolve_top_of_stack`` reports False for as long as the prompt is owed —
    forever, if nobody answers it. Built directly rather than through a card, so
    the test goes on testing the helper if the card that first showed this is
    ever reprinted, errata'd or fixed.
    """
    game = _duel()
    game.players[0].library = [_mk_card(n, "Artifact") for n in ("A", "B", "C")]
    game.players[0].hand = [_mk_card("X", "Artifact"), _mk_card("Y", "Artifact")]

    item = _held_stack_item(game)
    game.arm_pending_choice("hand_to_library", 0, count=1, _stack_item=item)

    assert game.resolve_top_of_stack() is False, (
        "the rig must actually reproduce the hold — without it this test would "
        "pass over a stack that was never blocked"
    )

    resolve_stack(game)

    assert game.stack == [], "the held object never left the stack"
    assert game.pending_choices == [], "the helper left the blocking prompt owed"


@pytest.mark.cr("608.2")
def test_a_prompt_that_blocks_nothing_is_left_for_the_test_to_read():
    """The deliberate limit, and it is a feature rather than an omission.

    A prompt owed with nothing on the stack is not holding a resolution open, so
    it is none of this helper's business — and answering it would silently
    change what every test that inspects a prompt after resolving can see. That
    is not hypothetical: it is the 41 failures the first draft caused.
    """
    game = _duel()
    game.players[0].library = [_mk_card(n, "Artifact") for n in ("A", "B", "C")]
    game.players[0].hand = [_mk_card("X", "Artifact")]
    game.arm_pending_choice("hand_to_library", 0, count=1)

    assert resolve_stack(game) == 0
    assert [c.kind for c in game.pending_choices] == ["hand_to_library"]


@pytest.mark.cr("608.2")
def test_a_stack_that_stops_moving_fails_instead_of_hanging():
    """A stack that cannot progress and has nothing to answer is a bug in the
    engine or the rig rather than in the test, and the helper's job is to make
    it a *failure* naming what the game waits on — not a run that never ends.
    Anything that swallowed this and returned quietly would put the hang back
    one level up."""

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
    is a loop that keeps producing work, that is work nothing can do."""

    class _Endless(Game):
        def resolve_top_of_stack(self, pause_for_choices: bool = False) -> bool:
            self.stack.append(object())
            return True

    game = _Endless(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.stack.append(object())

    with pytest.raises(AssertionError, match="did not drain"):
        resolve_stack(game, limit=10)
