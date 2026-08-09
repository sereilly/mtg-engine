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

Adding an interactive replacement is therefore two registrations — an
interceptor that offers the choice and a resolver that applies it — and no new
``Game`` field, prompt plumbing, or confirm method.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


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


def offer_replacement_choice(game, choice: ReplacementChoice) -> tuple[bool, int]:
    """Present *choice* to its chooser.

    Returns ``(suspended, drawn)``. For an interactive seat the choice is queued
    and ``(True, 0)`` is returned — the event is suspended and the caller must
    not carry on with it. For any other seat the default is applied at once and
    the resolver's result comes back with ``suspended`` False.
    """
    if choice.player_index not in game.interactive_seats:
        return False, resolve_choice(game, choice, choice.default_option)
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
