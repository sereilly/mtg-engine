"""Regression: a fused ``sequence`` dropped its trigger's intervening-if.

CR 603.4's condition is attached by ``lower_ability`` to every *top-level*
instruction a line lowers to. A line that lowers to two of them — "put a +1/+1
counter on this creature **and** untap it" — is then wrapped in a single
``sequence`` by ``engine/oracle.py``, and the wrapper is the new top level. Both
readers of the gate look at the top level: the end step's scan decides whether to
enqueue the trigger at all, and ``mixins/stack/resolution.py`` re-checks it as
the ability resolves. A wrapper that did not carry the gate therefore put the
condition somewhere nothing reads.

Sabertooth Mauler is what that cost: a supported card whose end-step trigger was
in none of the step's scans, so it entered play and did nothing at all — the
silent wrongness this repo's first standing invariant forbids, and the Nine Lives
class the roadmap has been finding one card at a time.

Written to fail on the old code: the first test asserts the counter *and* the
untap, and the old engine produced neither.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState


def _mauler_board(set_pool, died):
    pool = set_pool("M21")
    mauler = Permanent(card=pool["Sabertooth Mauler"])
    p1 = PlayerState(name="P1", battlefield=[mauler])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.interactive_seats = {0}
    game.start_turn(0)
    # After the untap step, which would otherwise undo it.
    mauler.tapped = True
    if died:
        victim = Permanent(card=pool["Alpine Watchdog"])
        p1.battlefield.append(victim)
        game._permanent_to_graveyard(p1, victim)
    return game, mauler


def test_sabertooth_mauler_counters_and_untaps_after_a_death(set_pool):
    game, mauler = _mauler_board(set_pool, died=True)

    game.resolve_end_step(0)
    game._settle()

    assert int(mauler.metadata.get("plus_counters", 0)) == 1
    assert not mauler.tapped


def test_sabertooth_mauler_is_silent_with_no_death(set_pool):
    """The other half: the gate now reaches the step, so it also has to refuse."""
    game, mauler = _mauler_board(set_pool, died=False)

    game.resolve_end_step(0)
    game._settle()

    assert int(mauler.metadata.get("plus_counters", 0)) == 0
    assert mauler.tapped
