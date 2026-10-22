"""What a prompt renderer is handed, and the table of them.

``web/prompts.py``'s loops render each owed prompt by looking its kind up in
:data:`PROMPT_RENDERERS`. The renderers live in three modules, by what the
prompt is answered with — ``prompt_cards``, ``prompt_board`` and
``prompt_values`` — and each registers through :func:`prompt_renderer`. That
is why this table is a module of its own and sits below all four in
``web.LAYERS``: the renderer modules import it, and ``prompts`` imports them
so that importing it is what fills the table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from engine.pending_choices import CHOICE_SPECS


@dataclass(frozen=True)
class PromptContext:
    """What a renderer is allowed to reach for.

    Passed in rather than imported so this module has no cycle back into
    ``app.py``, and so what the presentation layer depends on stays visible.
    """

    game: Any
    viewer_seat: int | None
    serialize_card: Callable[[Any], dict]
    seat_type: Callable[[int], str]


Renderer = Callable[[PromptContext, list], "dict | None"]

PROMPT_RENDERERS: dict[str, Renderer] = {}


def prompt_renderer(kind: str) -> Callable[[Renderer], Renderer]:
    """Register the renderer for one kind of prompt.

    The kind must already be registered in the engine — a renderer for a prompt
    nothing arms is dead code that reads like coverage.
    """

    def decorator(fn: Renderer) -> Renderer:
        if kind not in CHOICE_SPECS:
            raise ValueError(f"no pending choice registered for prompt {kind!r}")
        if kind in PROMPT_RENDERERS:
            raise ValueError(f"prompt {kind!r} already rendered by {PROMPT_RENDERERS[kind].__name__}")
        PROMPT_RENDERERS[kind] = fn
        return fn

    return decorator
