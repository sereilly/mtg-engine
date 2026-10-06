"""Every entry trigger in the pool, with its source destroyed in response.

`test_entry_trigger_stack_census.py` holds that an entry trigger is a stack
object (CR 603.3). This is the census that change owed and did not get: the
comparison it shipped with — 807 scenarios, the same end state by the stack as
by the old inline road — was run on a table where **nobody responds**, which is
the one table on which the timing of a trigger cannot matter. What became
possible that day is the source leaving between the trigger and its effect, and
three shipped cards did the worst available thing when it did (CR 610.3b;
`tests/rules/test_until_this_leaves_and_it_already_has.py` has the cards).

So every one is driven that way here: the permanent enters, cast and put, its
trigger is on the stack, the source goes to its owner's graveyard, and the
stack is drained. What is asserted is what a departed source can break without
any rule being consulted:

* the resolution does not raise, and the stack drains;
* no prompt is still owed — an answer that needs the departed permanent is one
  nobody can give, and the game waits on it for ever;
* **no card leaves the game** — a card recorded on a permanent that is gone is
  in no zone at all (Oubliette's creature);
* nothing is left phased out;
* nothing is in exile on a card whose entry text says it is exiled *until*
  something (Idol of Endurance).

Validated backwards: with `until_leaves_has_ended` answering "no" it names Idol
of Endurance by the last check and Oubliette by the third, on both roads.

It does not ask whether each effect is *right* with its source gone — a counter
placed "on this creature" lands on nothing either way, and that is CR 608.2h's
last-known-information question, card by card. It asks only for the failures
that are failures whatever the card says.
"""

from __future__ import annotations

import re

from engine.control import base_controller
from tests.helpers import resolve_stack

from .test_entry_trigger_stack_census import _enter, _entry_trigger_cards

#: A floor, because a sweep that reaches nothing passes. 511 on the day.
_MIN_PAIRS = 480

#: "…until this artifact leaves the battlefield", "for as long as …": a duration
#: that is not a turn. A card printing one and holding something in exile after
#: its source has gone is the CR 610.3b shape.
_NON_TURN_DURATION = re.compile(
    r"\b(?:as long as|until (?!end of turn|your next turn))", re.I
)


def _cards_in_game(game) -> int:
    """Every card in a zone. A trigger on the stack is not a card and tokens
    are not counted, so nothing a resolution does may change this number."""
    total = 0
    for player in game.players:
        total += len(player.library) + len(player.hand) + len(player.graveyard)
        total += len(player.exile) + len(player.phased_out)
    return total + sum(
        1 for permanent in game.all_permanents() if not permanent.metadata.get("is_token")
    )


def _drain(game) -> None:
    for _ in range(6):
        resolve_stack(game)
        game._settle()
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        if not game.stack and not game.pending_choices:
            return


def test_no_entry_trigger_strands_anything_when_its_source_is_destroyed_in_response():
    examined = 0
    findings: list[str] = []
    for card, _triggers in _entry_trigger_cards():
        for road in ("cast", "put"):
            entered = _enter(card, road)
            if entered is None:
                continue
            game, _executed, source = entered
            if source is None or not game.stack:
                continue
            examined += 1
            where = f"{card.name} [{road}]"
            before = _cards_in_game(game)
            owner = game.players[base_controller(source) or 0]
            game.remove_from_battlefield(source)
            game._permanent_to_graveyard(owner, source)
            try:
                _drain(game)
            except Exception as exc:  # the finding is the card's name, not a traceback
                findings.append(f"{where}: {type(exc).__name__}: {str(exc)[:160]}")
                continue
            if game.stack or game.pending_choices or game.waiting_prompt() is not None:
                findings.append(
                    f"{where}: still owed {[choice.kind for choice in game.pending_choices]}, "
                    f"{len(game.stack)} object(s) on the stack"
                )
            if _cards_in_game(game) != before:
                findings.append(
                    f"{where}: {before - _cards_in_game(game)} card(s) left the game"
                )
            phased = [p.card.name for player in game.players for p in player.phased_out]
            if phased:
                findings.append(f"{where}: {phased} left phased out")
            exiled = [c.name for player in game.players for c in player.exile]
            if exiled and _NON_TURN_DURATION.search(card.oracle_text or ""):
                findings.append(f"{where}: {exiled} exiled with nothing left to end it")

    assert examined >= _MIN_PAIRS, f"the census reached only {examined} entries"
    assert not findings, "\n".join(findings)
