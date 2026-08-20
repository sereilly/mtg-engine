"""Decisions a player owes part-way through a spell, an ability, or a turn step.

Every interactive choice in this engine has the same five parts:

1. something **arms** it (a handler, an upkeep effect, an entry replacement);
2. an interactive seat **answers** it, through a web action;
3. every other seat takes a deterministic **default**, so AI and headless play
   never block;
4. the web layer **renders** it for the seat that owes it;
5. every other action by that seat is **refused** until it is answered.

Those five used to be five unrelated places — a one-card ``pending_*`` field on
``Game``, a ``confirm_*`` method, an ``auto_resolve_*`` method, a branch in the
state serializer and a branch in the action guard — with nothing tying them
together. The failure modes are silent and asymmetric: forget the default and an
AI seat stalls the game forever; forget the guard and a player acts around their
own prompt; forget the renderer and the prompt is never shown. Primal Clay's
"choose your body" prompt had the last three missing, so it was armed for a human
and then neither displayed nor cleared.

They are one table now. A choice is a :class:`PendingChoice` on
``Game.pending_choices``; a :class:`ChoiceSpec` registered here says how to
answer it, what a non-interactive seat does instead, and how the web layer
treats it. The three cascades in ``web/prompts.py`` loop over the queue instead of
naming each kind, so adding an interactive choice is one ``register_choice``
call plus the code that arms it — and
``tests/engine/test_pending_choices.py`` fails if any part is missing.

``engine/replacement_choices.py`` holds the same shape for replacement effects
(CR 614) that suspend on a decision. Its ``ReplacementChoice`` carries the same
``kind`` / ``player_index`` / ``data`` attributes, so the generic web machinery
here works over both queues without an adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class PendingChoice:
    """A decision queued on the seat that owes it.

    kind          -- stable id; selects the spec and names the prompt
    player_index  -- the seat that chooses
    data          -- per-kind payload. Keys starting with ``_`` are private to
                     the engine (live ``Permanent`` / ``StackItem`` references)
                     and are stripped before the prompt reaches a client.
    """

    kind: str
    player_index: int
    data: dict = field(default_factory=dict)


# (game, choice, response) -> was the answer accepted? A rejected answer leaves
# the choice queued, so a malformed request cannot silently drop a prompt.
Resolver = Callable[[Any, PendingChoice, dict], bool]
# (game, choice) -> None. The deterministic answer for a non-interactive seat.
Defaulter = Callable[[Any, PendingChoice], None]


@dataclass(frozen=True)
class ChoiceSpec:
    """Everything the engine and the web layer need to know about one kind.

    action           -- the ``ActionKind`` that answers this prompt
    also_answers     -- further ``ActionKind``s the gate accepts while this
                        prompt is open (a search's "fail to find" decline is a
                        second answer, not a way around the prompt)
    prompt_key       -- key the state payload carries the rendered prompt under
    blocked_detail   -- the 400 message when the owing seat tries to do
                        something else first. ``None`` means answering is not
                        forced (a notification, or a choice the game can carry
                        on around).
    default_at_arm   -- a non-interactive seat never queues this at all: the
                        default is taken the moment it is armed. Used where the
                        prompt interrupts a resolution that has to finish now.
                        Kinds without it stay queued for every seat and are
                        drained by ``auto_resolve_pending_choices``.
    blocks_every_seat-- the whole game waits, not just the choosing seat.
    spectator_visible-- a seatless viewer (spectator, single-payload API) sees
                        the prompt too.
    hidden_for_ai    -- suppress the prompt when the owing seat is AI-controlled.
    is_open          -- extra "still owed" test. Word of Command records the
                        caster's answer while its spell keeps waiting on the
                        stack, so the object stays queued after it is answered.
    suspends         -- arming this stops the *loop* the effect was a step of
                        (``engine/resumption.py``) until it is answered, and
                        answering resumes it. Set it for any prompt whose answer
                        decides what a **later step of the same resolution**
                        sees. Opt-in rather than universal because the kinds
                        that complete inline (``sacrifice``, ``discard``,
                        ``mana_payment``) have callers written around finishing
                        immediately.
    """

    kind: str
    resolve: Resolver
    default: Defaulter
    action: str
    prompt_key: str
    also_answers: tuple[str, ...] = ()
    blocked_detail: str | None = None
    default_at_arm: bool = False
    blocks_every_seat: bool = False
    spectator_visible: bool = False
    hidden_for_ai: bool = True
    is_open: Callable[[Any, PendingChoice], bool] | None = None
    suspends: bool = False

    def open_for(self, game, choice) -> bool:
        """Whether *choice* is still waiting on its seat."""
        return self.is_open is None or bool(self.is_open(game, choice))


CHOICE_SPECS: dict[str, ChoiceSpec] = {}


def register_choice(
    kind: str,
    *,
    resolve: Resolver,
    default: Defaulter,
    action: str,
    prompt_key: str,
    also_answers: tuple[str, ...] = (),
    blocked_detail: str | None = None,
    default_at_arm: bool = False,
    blocks_every_seat: bool = False,
    spectator_visible: bool = False,
    hidden_for_ai: bool = True,
    is_open: Callable[[Any, PendingChoice], bool] | None = None,
    suspends: bool = False,
) -> ChoiceSpec:
    """Register the one spec for a kind of pending choice.

    A duplicate kind raises at import, matching ``@parse_rule`` and
    ``@replacement_choice``: two specs for one kind would make which resolver
    runs depend on import order, and the loser would fail silently.
    """
    if kind in CHOICE_SPECS:
        raise ValueError(f"pending choice {kind!r} is already registered")
    spec = ChoiceSpec(
        kind=kind,
        resolve=resolve,
        default=default,
        action=action,
        prompt_key=prompt_key,
        also_answers=also_answers,
        blocked_detail=blocked_detail,
        default_at_arm=default_at_arm,
        blocks_every_seat=blocks_every_seat,
        spectator_visible=spectator_visible,
        hidden_for_ai=hidden_for_ai,
        is_open=is_open,
        suspends=suspends,
    )
    CHOICE_SPECS[kind] = spec
    return spec


def spec_for(kind: str) -> ChoiceSpec:
    spec = CHOICE_SPECS.get(kind)
    if spec is None:  # pragma: no cover - guarded by the registry guard test
        raise KeyError(f"no spec registered for pending choice {kind!r}")
    return spec


def public_data(choice) -> dict:
    """A choice's payload with the engine-private keys removed.

    Private keys hold live ``Permanent`` / ``StackItem`` references, which are
    neither JSON-serializable nor any of a client's business.
    """
    return {k: v for k, v in choice.data.items() if not k.startswith("_")}
