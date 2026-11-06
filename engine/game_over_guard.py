"""CR 104.1: "A game ends immediately when a player wins, when the game is a
draw, or when the game is restarted." — the turn's stepping goes no further.

**One guard, on the engine's stepping, rather than one at each driver.**
Three drivers step a turn: the web layer's resumable pieces
(``web/turn_steps.py``, ``web/game_flow.py``), the headless
``Game.start_turn`` flow and the AI simulator. Each step is entered, run and
left through the engine's own entry points — ``resolve_untap_step``,
``resolve_upkeep``, ``resolve_draw_step``, ``enter_turn_phase`` and
``enter_next_turn_phase`` (every main, combat and ending phase),
``resolve_end_step``, ``resolve_cleanup_step``, the step closers and the turn's
own start — so a guard on those is a guard on every road, and a driver that
forgets to ask ``is_game_over()`` between two of them cannot walk an ended game
on. The web layer asked at *one* of its continuations (``_advance_phase``) and
not at the beginning phase's: Sulfuric Vortex took a person to 0 in their
upkeep, and the same request ran their draw step and entered the main phase
(SCG Phase 5, smoke game 2, turn 18). The combat rail already stopped itself
(``advance_combat_phase``, ``resolve_combat_damage``); this is the same rule
for every other step.

A guarded entry point, called on an ended game, changes nothing — no draw, no
step begun or ended, no trigger announced or resolved — and returns the value
its callers read as "nothing more to do here" (``ended``). Multiplayer is
unaffected: a game that one player of three has left goes on (CR 800.4a), and
``is_game_over`` is the one answer to which.

``tests/engine/test_scg_p5_game_over_stepping.py`` is the census: every
stepping entry point ``Game`` has, called on an ended game, and the guard on
each.
"""

from __future__ import annotations

import functools

#: The attribute a guarded entry point carries, read by the census.
GUARDED = "_stops_once_the_game_is_over"


def goes_no_further(ended=None):
    """Decorate a stepping entry point of ``Game``: once the game is over
    (CR 104.1) it does nothing and returns *ended* — or, when *ended* is
    callable, what it answers of the game (``start_next_turn``'s seat)."""

    def wrap(method):
        @functools.wraps(method)
        def guarded(self, *args, **kwargs):
            if self.is_game_over():
                return ended(self) if callable(ended) else ended
            return method(self, *args, **kwargs)

        setattr(guarded, GUARDED, True)
        return guarded

    return wrap
