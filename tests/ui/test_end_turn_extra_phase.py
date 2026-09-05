"""The End Turn button and CR 500.8's extra phases.

``web/turn_steps._end_turn`` jumps from wherever the active player is standing
to the ending phase, which is why pressing it in a precombat main phase skips
that turn's own combat. That is the button's job — ``next_phase`` is the control
that walks CR 500.1's order one phase at a time — and it stays a jump.

What changed under it is that the turn's plan can now hold a phase no rule put
there: Relentless Assault's "there is an additional combat phase followed by an
additional main phase" (CR 500.8). Skipping the turn's own combat is the button
working; skipping one a card created is the player losing something they paid
for, so the jump names it in the log rather than swallowing it.
"""

from __future__ import annotations

from engine import Game, PlayerState
from web.session_store import Session
from web.turn_steps import _end_turn


def _session() -> Session:
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.begin_turn_bookkeeping(0)
    game._set_phase_and_step("beginning", "untap")
    game.enter_next_turn_phase("beginning")
    return Session(
        id="s", mode="human_vs_ai", host_name="P1", guest_name="P2", game=game,
        seat_types={0: "human", 1: "ai"},
    )


def _end_turn_lines(session: Session) -> list[str]:
    before = len(session.game.log)
    _end_turn(session)
    return session.game.log[before:]


def test_an_ordinary_end_turn_says_nothing_about_extra_phases():
    """The turn's own combat is skipped and always was, so saying so on every
    press would be noise that trains people to skim the log."""
    session = _session()
    assert session.game.current_turn_phase == "precombat_main"

    lines = _end_turn_lines(session)

    assert not [line for line in lines if "CR 500.8" in line]


def test_ending_the_turn_names_the_extra_phases_it_skips():
    """CR 500.8's insertion, jumped over. The log is where every other thing the
    turn does to itself is named."""
    session = _session()
    assert session.game.add_extra_phase("precombat_main", "combat") is True
    assert session.game.add_extra_phase("combat", "postcombat_main") is True
    assert session.game.extra_phases_remaining() == ["combat", "postcombat_main"]

    lines = _end_turn_lines(session)

    skipped = [line for line in lines if "CR 500.8" in line]
    assert skipped == [
        "P1 ended the turn, skipping the extra combat phase, main phase "
        "(CR 500.8)"
    ]


def test_the_next_turn_does_not_inherit_the_skipped_plan():
    """The plan is per turn — ``begin_turn_bookkeeping`` re-derives it — so the
    phases this button discarded do not turn up on somebody else's turn."""
    session = _session()
    session.game.add_extra_phase("precombat_main", "combat")

    _end_turn(session)

    assert session.game.extra_phases_remaining() == []
