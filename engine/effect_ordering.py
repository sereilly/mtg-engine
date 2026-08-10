"""CR 616.1 — choosing which applicable effect to apply, and in what order.

When two or more replacement (CR 614) and/or prevention (CR 615) effects are
attempting to modify one event, the rules do **not** fix an order. The affected
object's controller — or the affected player — chooses one to apply; the chosen
one is applied; and then the process repeats over whatever is *still* applicable
(616.1f). Any single fixed order is one legal set of those choices, which is why
running a hardcoded cascade is usually right and occasionally not.

This module is that process, and it is the only place either registry decides
what runs next. Both feed it: ``engine/prevention.py`` (CR 615 shields) and
``engine/replacements.py`` (CR 614), with ``engine/damage_events.py`` putting a
damage event's members of both into the one candidate list the rule describes.
Three things follow from putting the process here:

**Applicability is separable from application.** An effect used to answer "do I
apply?" by applying itself — the guard and the work were one function, so there
was no way to ask how many effects were in contention without running one. Each
registration now carries an ``applies`` predicate, and the guard *moved* there
rather than being copied: the interceptor body starts after the decision, so the
two cannot disagree. That is the whole reason 616.1 was unimplementable before.

**616.1f is real.** Applying one effect can change which others apply — a
partial replacement lowers the amount, a shield is consumed, a redirect moves
the damage to a different recipient. The loop re-gathers after every
application instead of walking a list decided up front.

**The choice has one seat.** :func:`choose_effect` is where the affected player
would be asked. It takes the default today — the documented order below — and
the reason is not that the choice does not matter but that a damage event cannot
currently suspend: prevention runs inside ``_deal_damage_to_player``, which
returns an ``int`` to callers deep in combat and resolution loops. Asking a
human there needs the event to be resumable, which is its own piece of work.
Where an event *can* suspend, replacement choices already prompt properly — see
``engine/replacement_choices.py``.

So the ordering half of 616.1 is implemented and the asking half has one
documented seat rather than being spread across two cascades. That is the
distinction the roadmap's phase 5 was tracking.

Note that 616.1 is not the *only* sequencing a damage event has. CR 120.4 splits
one into "damage is dealt" and "what was dealt is processed into its results",
and 616.1 runs inside each half. ``engine/damage_events.py`` holds that
structure; this module is only the choosing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class Candidate:
    """One effect that could modify the event in front of it.

    key           -- stable id, used in logs and by the choice seat
    order         -- the default order, which is what a non-interactive seat
                     chooses. Lower runs first.
    applies       -- ``(game, event) -> bool``. Pure: it must not consume a
                     shield, move damage, or draw a card, because it is asked
                     about effects that may then not be chosen.
    apply         -- ``(game, event) -> outcome``. Runs only once chosen, and
                     may assume ``applies`` just returned True.
    label         -- human-readable, for the log and any future prompt
    """

    key: str
    order: int
    applies: Callable[[Any, dict], bool]
    apply: Callable[[Any, dict], Any]
    label: str = ""


@dataclass
class OrderingTrace:
    """What the loop did, for tests and logs. Cheap to build and easy to assert
    on: the interesting property of a 616.1 implementation is the *sequence* of
    choices, which is otherwise invisible in the final numbers."""

    applied: list[str] = field(default_factory=list)
    contended: list[tuple[str, ...]] = field(default_factory=list)

    @property
    def had_a_choice(self) -> bool:
        """Whether the affected player was ever in a position to choose. This
        is the signal a prompt would hang off."""
        return any(len(round_) > 1 for round_ in self.contended)


# Upper bound on 616.1f iterations. Each application should reduce the
# applicable set, so this is a backstop against an effect whose predicate stays
# True after it runs — a bug, but one that must not hang the game.
MAX_ROUNDS = 64


def affected_seat(game, affected) -> int | None:
    """The seat CR 616.1 gives the choice to: the affected player, or the
    affected permanent's controller.

    Duck-typed on identity rather than on a type, so this module keeps importing
    nothing from the engine and both registries can share one answer to "whose
    choice is this?" — a question every candidate list has to answer the same
    way or the prompt would go to different seats depending on which registry
    happened to gather the event.

    None when the event names no affected object, or names one that has left the
    battlefield: the process still runs, it just has no seat to ask.
    """
    if affected is None:
        return None
    for index, player in enumerate(game.players):
        if player is affected:
            return index
    for index, player in enumerate(game.players):
        if any(permanent is affected for permanent in player.battlefield):
            return index
    return None


def choose_effect(game, chooser_index: int | None, candidates: list[Candidate]) -> Candidate:
    """Which of several applicable effects to apply next (CR 616.1e).

    The affected player's choice. Today every seat takes the documented default
    — the lowest ``order`` — because the events this runs inside cannot suspend
    to ask (see the module docstring). This is the one function to change when
    they can, and ``OrderingTrace.had_a_choice`` already records when the
    question was live.
    """
    return min(candidates, key=lambda candidate: candidate.order)


def apply_in_order(
    game,
    event: dict,
    candidates: list[Candidate],
    *,
    chooser_index: int | None = None,
    stop: Callable[[Any, dict], bool] | None = None,
) -> OrderingTrace:
    """Apply *candidates* to *event* following CR 616.1.

    Each round re-asks every candidate whether it still applies (616.1f),
    because the previous application may have changed the answer. ``stop`` ends
    the process early — a consumed event has nothing left for anything to
    modify.
    """
    trace = OrderingTrace()
    remaining = list(candidates)
    for _ in range(MAX_ROUNDS):
        if stop is not None and stop(game, event):
            return trace
        applicable = [c for c in remaining if c.applies(game, event)]
        if not applicable:
            return trace
        trace.contended.append(tuple(c.key for c in applicable))
        chosen = (
            applicable[0]
            if len(applicable) == 1
            else choose_effect(game, chooser_index, applicable)
        )
        chosen.apply(game, event)
        trace.applied.append(chosen.key)
        # An effect applies once per event. Re-gathering is about the *others*
        # becoming (in)applicable, not about running this one again.
        remaining = [c for c in remaining if c is not chosen]
    return trace  # pragma: no cover - MAX_ROUNDS is a backstop
