"""Guard: every delayed-trigger event has a fire site, and the entry is one shape.

``tests/engine/test_trigger_dispatchers.py`` asks of an ordinary trigger
condition whether anything in the engine ever *announces* it. A delayed
triggered ability (CR 603.7) needs the same question asked one step earlier:
it is created by a resolving effect and then belongs to no permanent, so the
battlefield scan that announces every other trigger cannot reach it. An event
armed with no fire site behind it is an ability that waits forever — the card
compiles, the log says it was created, and nothing ever happens.

The question is deliberately weak, for the reason the trigger-dispatcher guard
gives: a fire site is a call to ``fire_delayed_triggers``, a comparison inside
the declare-attackers loop, or something not yet written, and a list of
mechanisms goes stale like a list of fire sites. So the test asks only whether
the event's name appears in ``engine/`` outside the module that declares it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from engine.delayed_triggers import (DELAYED_EVENTS, DelayedTrigger,
                                     expire_delayed_triggers)

ENGINE = Path(__file__).resolve().parent.parent.parent / "engine"
DECLARING = {"delayed_triggers.py"}


def _sources() -> list[tuple[str, str]]:
    return [
        (str(path.relative_to(ENGINE)), path.read_text(encoding="utf-8"))
        for path in ENGINE.rglob("*.py")
        if path.name not in DECLARING
    ]


@pytest.mark.parametrize("event", sorted(DELAYED_EVENTS))
def test_every_delayed_event_is_named_outside_its_declaration(event):
    """A delayed event nothing else in the engine names has no fire site."""
    citing = [name for name, text in _sources() if event in text]
    assert citing, (
        f"delayed event {event!r} is declared in DELAYED_EVENTS "
        f"({DELAYED_EVENTS[event]}) but no module in engine/ names it — an "
        "ability armed on it would wait forever"
    )


def test_the_registry_is_not_empty():
    """A vacuous parametrization would pass every row above."""
    assert len(DELAYED_EVENTS) >= 6


def test_two_identical_entries_are_distinct_objects():
    """The expiry sweep removes the entry that fired, not every entry equal to
    it. Two copies of one spell resolved against one creature arm two abilities
    with every field equal; a value comparison would drop both — the look-alike
    bug this codebase keeps finding, in a list instead of on a battlefield."""
    first = DelayedTrigger(controller_index=0, event="bound_permanent_dies",
                           instruction=None, bound_permanent_id=7)
    second = dataclasses.replace(first)

    assert first != second
    assert [entry for entry in (first, second) if entry is not first] == [second]


def test_an_undurationed_entry_outlives_the_turn():
    """CR 603.7b: "this turn" is a stated duration and expires; an ability
    naming a future step is still waiting for it."""

    class _Game:
        delayed_triggers = [
            DelayedTrigger(0, "bound_permanent_dies", None, duration="end_of_turn"),
            DelayedTrigger(0, "controllers_next_main_phase", None,
                           duration="until_it_triggers"),
        ]

    game = _Game()
    expire_delayed_triggers(game)

    assert [entry.event for entry in game.delayed_triggers] == [
        "controllers_next_main_phase"
    ]
