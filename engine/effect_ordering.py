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

**The choice is asked, and asking needs nothing to be undone.** 616.1e is the
affected player's, and :func:`apply_in_order` puts it to them through the
``ask`` hook. What makes that possible without continuations or snapshots is the
first point above: predicates are pure, so at the moment a contended round is
reached, *nothing has happened yet*. The process can be abandoned there and the
whole event re-run later against the same state, arriving at the same round with
the same contenders and the answer now recorded. Suspending is free precisely
because there is nothing to roll back.

The caller supplies the re-run, because an event is more than its replacements —
a draw nothing replaces still has to draw — and only the caller knows what doing
it again means. A caller that cannot offer one (damage: its callers read the
number back for trample, lifelink and triggers, and would have to defer all of
that too) simply does not, and every seat takes the default. That is a missing
capability at one declared place rather than a branch scattered through the
process.

A non-interactive seat is never asked, so AI and headless play stay entirely
synchronous.

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
    #: The process stopped to ask the affected player which effect applies
    #: first. **Nothing was applied** — see :func:`apply_in_order` for why that
    #: is what makes suspending safe. The caller must not carry on with the
    #: event; answering the prompt restarts it.
    suspended: bool = False
    #: Rounds that contended but took the default because the process was
    #: already under way (CR 616.2 can make a fresh effect applicable after one
    #: has been applied, and by then the prefix is no longer pure). Empty for
    #: every card in this pool; recorded rather than asserted so the day one
    #: arrives it is visible instead of silent.
    unasked: list[tuple[str, ...]] = field(default_factory=list)

    @property
    def had_a_choice(self) -> bool:
        """Whether the affected player was ever in a position to choose."""
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


#: Returned by an ``ask`` hook that has queued a prompt instead of answering.
SUSPENDED = object()


def choose_effect(game, chooser_index: int | None, candidates: list[Candidate]) -> Candidate:
    """The default choice (CR 616.1e): the lowest ``order``.

    What a non-interactive seat takes, and what every seat takes on an event
    that cannot suspend to ask. Any single order is a legal set of 616.1e
    choices, so this is a correct game, just not always the one the player
    would have picked.
    """
    return min(candidates, key=lambda candidate: candidate.order)


def apply_in_order(
    game,
    event: dict,
    candidates: list[Candidate],
    *,
    chooser_index: int | None = None,
    stop: Callable[[Any, dict], bool] | None = None,
    ask: Callable[[Any, int | None, list[Candidate]], Any] | None = None,
) -> OrderingTrace:
    """Apply *candidates* to *event* following CR 616.1.

    Each round re-asks every candidate whether it still applies (616.1f),
    because the previous application may have changed the answer. ``stop`` ends
    the process early — a consumed event has nothing left for anything to
    modify.

    ``ask`` is how the affected player is consulted (616.1e). It is called only
    on a round with more than one applicable effect, and only **before anything
    has been applied**. It returns the chosen candidate, or :data:`SUSPENDED`
    to mean "a prompt is queued; stop".

    That "before anything has been applied" restriction is the whole trick, and
    it is worth being explicit about why it is safe rather than merely
    convenient. Every ``applies`` predicate is pure, so the work done before the
    first application is *nothing at all* — the process can be abandoned
    mid-round and re-run from the top later against the same game state and
    reach the same round with the same contenders. Suspending needs no snapshot,
    no continuation and no rollback, because there is nothing yet to undo.

    Once one effect has been applied that is no longer true, so a later round
    that contends takes the default and is recorded in ``trace.unasked``. In
    this pool that cannot happen: applying an effect only ever makes predicates
    go true→false, so if any round contends the first one did.
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
        if len(applicable) == 1:
            chosen = applicable[0]
        elif ask is None or trace.applied:
            if ask is not None:
                trace.unasked.append(tuple(c.key for c in applicable))
            chosen = choose_effect(game, chooser_index, applicable)
        else:
            answer = ask(game, chooser_index, applicable)
            if answer is SUSPENDED:
                trace.suspended = True
                return trace
            chosen = answer
        chosen.apply(game, event)
        trace.applied.append(chosen.key)
        # An effect applies once per event. Re-gathering is about the *others*
        # becoming (in)applicable, not about running this one again.
        remaining = [c for c in remaining if c is not chosen]
    return trace  # pragma: no cover - MAX_ROUNDS is a backstop
