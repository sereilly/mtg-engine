"""Rendering, gating and auto-answering the prompts a seat owes.

``engine/pending_choices.py`` is the registry: one :class:`ChoiceSpec` per kind
of interactive decision, saying how it is answered, what a non-interactive seat
does instead, which action answers it and what message refuses everything else.
This module is the web half's three loops, which used to be three hand-written
cascades in ``app.py``, one branch per prompt:

* :func:`render_prompts`     — the payload the board UI reads, per viewer
* :func:`blocking_prompt`    — the prompt that refuses an action, if any
* :func:`auto_resolve_ai_prompts` — every AI-owned prompt takes its default

Those three plus the registry's ``resolve``/``default`` are the five parts a
prompt needs. They used to be five unrelated edits; a prompt with any of them
missing looked fine until it was played (Primal Clay shipped with three
missing). ``tests/engine/test_pending_choices.py`` now fails if a kind is
registered with no renderer, or armed with no spec.

The renderers they call, one per kind, are three modules by what a prompt is
answered with — ``prompt_cards``, ``prompt_board`` and ``prompt_values`` —
registered in ``prompt_registry``'s table, which this module imports them to
fill. Renderers take the *list* of that kind's currently visible choices,
because a seat can owe several of the same prompt at once (the colour rods)
and the board shows them as one panel.
"""

from __future__ import annotations

from typing import Any, Callable

from engine.pending_choices import CHOICE_SPECS

from .prompt_registry import PROMPT_RENDERERS, PromptContext

# The renderers, one module per kind of answer. Imported for their
# registration side effect: each ``@prompt_renderer`` fills PROMPT_RENDERERS,
# which ``render_prompts`` reads, and ``tests/engine/test_pending_choices.py``
# is what notices a kind left with none.
from . import prompt_board, prompt_cards, prompt_values  # noqa: F401


# ---------------------------------------------------------------------------
# The three loops
# ---------------------------------------------------------------------------

def visible_choices(ctx: PromptContext, spec) -> list:
    """The choices of *spec*'s kind this viewer may see.

    A prompt belongs to the seat that owes it. A seatless viewer (a spectator,
    or the single-payload API) sees only the kinds marked ``spectator_visible``,
    and an AI seat's prompt is hidden unless the kind says otherwise — the AI
    answers it itself, so showing it would be a prompt nobody can act on.
    """
    out = []
    for kind_spec, choice in ctx.game.iter_pending_prompts():
        if kind_spec is not spec:
            continue
        if ctx.viewer_seat is None:
            if not spec.spectator_visible:
                continue
        elif ctx.viewer_seat != choice.player_index:
            continue
        if spec.hidden_for_ai and ctx.seat_type(choice.player_index) == "ai":
            continue
        if not spec.open_for(ctx.game, choice):
            continue
        out.append(choice)
    return out


def render_prompts(ctx: PromptContext) -> dict:
    """``{prompt_key: payload or None}`` for every registered kind.

    Every key is always present, so the board UI never has to tell "no prompt"
    from "this build doesn't know that prompt".
    """
    payloads: dict[str, dict | None] = {}
    for kind, spec in CHOICE_SPECS.items():
        choices = visible_choices(ctx, spec)
        renderer = PROMPT_RENDERERS.get(kind)
        payloads[spec.prompt_key] = renderer(ctx, choices) if (choices and renderer) else None
    return payloads


def blocking_prompt(game, seat: int, action: str, exempt_actions: frozenset[str]) -> tuple[Any, Any] | None:
    """The first prompt that refuses *action* from *seat*, as ``(spec, choice)``.

    A kind with no ``blocked_detail`` never refuses anything: it is a
    notification, or a decision the rest of the game can carry on around.
    """
    for spec, choice in game.iter_pending_prompts():
        if spec.blocked_detail is None:
            continue
        if not spec.blocks_every_seat and choice.player_index != seat:
            continue
        if not spec.open_for(game, choice):
            continue
        if action in exempt_actions or action == spec.action or action in spec.also_answers:
            continue
        return spec, choice
    return None


def auto_resolve_ai_prompts(game, seat_type: Callable[[int], str]) -> None:
    """Take the default on every prompt owed by an AI seat.

    Generic over the queue, so a new prompt is covered the moment it is
    registered. That matters more than it sounds: a prompt with no auto-answer
    does not misbehave, it *stalls the game forever* on an AI seat, and only in
    a session where that card happens to be drawn.
    """
    # Answering one prompt can arm the next (a search that finds a card that
    # discards), so drain until nothing AI-owned is left. The bound is a
    # backstop against a default that fails to clear its own prompt.
    for _ in range(100):
        target = next(
            (
                choice
                for _spec, choice in game.iter_pending_prompts()
                if seat_type(choice.player_index) == "ai"
            ),
            None,
        )
        if target is None:
            return
        game.auto_resolve_choice(target)
