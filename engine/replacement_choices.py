"""Replacement effects that need a decision from a player (CR 614, 616.1).

Some replacement effects are optional ("you *may* put it on top of your library
instead") or let the affected player choose among outcomes ("look at the top X
cards of your library, draw one of them"). A plain interceptor cannot apply
those: ``apply_replacements`` returns synchronously, while the answer arrives on
a later request from a human.

Such an interceptor *offers* a choice instead. An interactive seat gets it
queued on ``game.pending_replacement_choices`` and the event is suspended until
:meth:`Game.resolve_replacement_choice` answers it; an AI or headless seat takes
the recorded ``default_option`` immediately. Both paths finish through the same
registered resolver, so there is one completion path to keep correct rather than
an inline branch and a ``confirm_`` method that must agree forever.

A queued offer is a prompt like any on ``Game.pending_choices``, and it waits
the same way (CR 608.2): it records the stack object resolving as it was
offered (``_stack_item``), which stays on the stack until its last decision is
answered; it suspends the loop the event was a step of, so "draw, then discard"
does not discard before the draw is decided; and its answer runs inside the
one answer envelope (``PendingChoicesMixin._answer_pending_choice``), which
resumes that loop and releases the object.

Adding an interactive replacement is therefore two registrations — an
interceptor that offers the choice and a resolver that applies it — and no new
``Game`` field, prompt plumbing, or confirm method.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .entry_awaiting import ENTRY_EVENT


@dataclass
class ReplacementChoice:
    """A suspended replacement waiting on its chooser.

    kind           -- stable id; selects the resolver and lets the web layer
                      recognize the prompt
    player_index   -- the seat that chooses
    options        -- labels in the order the chooser sees them; the answer is
                      an index into this tuple
    default_option -- what a non-interactive seat takes. Choices are offered by
                      effects that are optional or beneficial, so this is the
                      option a player would normally take, not a null action.
    data           -- per-kind payload the resolver needs (the discarded card,
                      sideboard positions, draws queued behind this one)
    """

    kind: str
    player_index: int
    options: tuple[str, ...]
    default_option: int = 0
    data: dict = field(default_factory=dict)


# (game, choice, option_index) -> cards drawn while applying the choice.
Resolver = Callable[[Any, ReplacementChoice, int], int]

CHOICE_RESOLVERS: dict[str, Resolver] = {}


def replacement_choice(kind: str) -> Callable[[Resolver], Resolver]:
    """Register the resolver that applies a *kind* of choice once answered.

    A duplicate kind raises at import: two resolvers for one kind would make
    which one runs depend on import order, and the loser would fail silently.
    """

    def decorator(fn: Resolver) -> Resolver:
        if kind in CHOICE_RESOLVERS:
            raise ValueError(
                f"replacement choice {kind!r} already resolved by "
                f"{CHOICE_RESOLVERS[kind].__name__}"
            )
        CHOICE_RESOLVERS[kind] = fn
        return fn

    return decorator


def resolve_choice(game, choice: ReplacementChoice, option_index: int) -> int:
    """Apply *choice* with the chosen option. Returns cards drawn (0 for
    choices that draw nothing)."""
    resolver = CHOICE_RESOLVERS.get(choice.kind)
    if resolver is None:  # pragma: no cover - guarded by the duplicate check
        raise KeyError(f"no resolver registered for replacement choice {choice.kind!r}")
    return resolver(game, choice, option_index)


#: The data key a prompt carries when a **draw** armed it: the seat whose draw
#: is not finished until the prompt is answered. Stamped where a prompt is
#: queued (here and in ``Game.arm_pending_choice``) while that seat's draw
#: machinery is running, and read by ``Game._draw_prompt_open`` — CR 121.2
#: makes a multi-card draw that many individual draws, so the next one must
#: not begin while this one still owes a decision. Engine-private (the leading
#: underscore keeps it off every client payload).
DRAW_OF = "_draw_of"


def stamp_draw_of(game, choice) -> None:
    """Mark *choice* as owed by the draw in progress, if one is."""
    scopes = getattr(game, "draw_scopes", None)
    if scopes and DRAW_OF not in choice.data:
        choice.data[DRAW_OF] = scopes[-1]


#: The data keys a prompt carries for **what was resolving** when it was
#: armed: the seat whose spell or ability armed it (CR 109.5) and what that
#: object targets (CR 115.1, ``Game.resolving_targets``' entry). Read back
#: by ``Game._answer_inside_its_window``, which pushes both for the length of
#: the answer: the answer re-runs the event that asked and the loop behind it
#: (``engine/resumption.py``), after the instruction that armed it has
#: returned and both seams are empty. Engine-private (leading underscore).
CAUSE_SEAT = "_cause_seat"
RESOLVING_TARGETS = "_resolving_targets"


def stamp_resolving(game, choice) -> None:
    """Stamp *choice* with what was resolving as it was armed (``CAUSE_SEAT``,
    ``RESOLVING_TARGETS``) — on either queue, by the one helper, since an
    answer on either re-runs the same kind of work."""
    seats = getattr(game, "resolving_seats", None)
    if seats and CAUSE_SEAT not in choice.data:
        choice.data[CAUSE_SEAT] = seats[-1]
    # Only a resolution that chose something: an empty entry pushed back is
    # the same answer as none, and the prompt's data stays what it was.
    targets = getattr(game, "resolving_targets", None)
    if targets and targets[-1] and RESOLVING_TARGETS not in choice.data:
        choice.data[RESOLVING_TARGETS] = targets[-1]
    # …and the event putting permanents onto the battlefield that was open
    # (CR 603.6a, ``entry_awaiting.ENTRY_EVENT``): the answer is one more part
    # of it, so what it puts down — and what the loop it resumes puts down —
    # enters with the rest ("each player may put …", Show and Tell).
    event = getattr(game, "entry_batch", None)
    if event is not None and not event.closed and ENTRY_EVENT not in choice.data:
        choice.data[ENTRY_EVENT] = event


def offer_replacement_choice(game, choice: ReplacementChoice) -> tuple[bool, int]:
    """Present *choice* to its chooser.

    Returns ``(suspended, drawn)``. For an interactive seat the choice is queued
    and ``(True, 0)`` is returned — the event is suspended and the caller must
    not carry on with it. For any other seat the default is applied at once and
    the resolver's result comes back with ``suspended`` False.
    """
    if choice.player_index not in game.interactive_seats:
        return False, resolve_choice(game, choice, choice.default_option)
    stamp_draw_of(game, choice)
    # Which stack object is still resolving because of this offer (CR 608.2):
    # the stamp ``Game.arm_pending_choice`` gives a prompt on the other queue,
    # for the same reason — the interceptor that offers it knows nothing about
    # the stack. Every kind on this queue holds priority, so no kind is asked.
    # Unstamped, Shock finished resolving and went to the graveyard while
    # Blood of the Martyr's "you may have that damage dealt to you instead"
    # was still owed, and Mox Diamond's spell had left the stack with its
    # discard toll unanswered.
    resolving = getattr(game, "resolving_stack_item", None)
    if resolving is not None and "_stack_item" not in choice.data:
        choice.data["_stack_item"] = resolving
    # …and the seat and targets of what was resolving, which this queue
    # never stamped: damage dealt from a Blood of the Martyr answer mid-
    # Fireball was nobody's (CR 109.5), as the other queue's was until kg3.
    stamp_resolving(game, choice)
    game.pending_replacement_choices.append(choice)
    return True, 0


def pending_choices_for(game, kind: str, player_index: int | None = None) -> list[ReplacementChoice]:
    """Queued choices of *kind*, oldest first, optionally for one seat."""
    return [
        choice
        for choice in game.pending_replacement_choices
        if choice.kind == kind
        and (player_index is None or choice.player_index == player_index)
    ]
