"""What a prompt renderer is handed, and the table of them.

``web/prompts.py``'s loops render each owed prompt by looking its kind up in
:data:`PROMPT_RENDERERS`. The renderers live in three modules, by what the
prompt is answered with — ``prompt_cards``, ``prompt_board`` and
``prompt_values`` — and each registers through :func:`prompt_renderer`. That
is why this table is a module of its own and sits below all four in
``web.LAYERS``: the renderer modules import it, and ``prompts`` imports them
so that importing it is what fills the table. The handlers that answer the
prompts are split the same way, each beside its renderer's family:
``action_prompt_cards``, ``action_prompt_board`` and ``action_prompt_values``.
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
    #: A **permanent** described as it is (``serialization
    #: ._serialize_permanent_summary``): its type line, text, colours and
    #: mana cost through the layers (CR 613). Injected for ``serialize_card``'s
    #: reason — the renderer modules sit below ``serialization`` in
    #: ``web.LAYERS`` — and needed because a permanent handed to
    #: ``serialize_card`` is described as printed: a Kormus Bell'd Swamp drawn
    #: as "Basic Land — Swamp" in a list of creatures. Read through
    #: :meth:`describe_permanent`.
    serialize_permanent: Callable[[Any], dict] | None = None
    #: A card **off the battlefield** described as its owner's statics leave it
    #: (``serialization._serialize_card_summary(card, game, owner)``): under
    #: that owner's Celestial Dawn a nonland card in their hand, library or
    #: graveyard is white (CR 613.1e), and a prompt listing another seat's
    #: cards showed them printed. Read through :meth:`owned_card`.
    serialize_owned_card: Callable[[Any, int], dict] | None = None

    def owned_card(self, card, owner) -> dict:
        """*card*, owned by *owner* (a seat index or that seat's
        ``PlayerState``), for a prompt that lists cards in a zone.

        A context built without :attr:`serialize_owned_card` (a test's), or
        an owner this game does not seat, falls back to :attr:`serialize_card`
        — the printed colours, which is what every list showed before."""
        seat = owner
        if not isinstance(seat, int):
            seat = next(
                (index for index, player in enumerate(getattr(self.game, "players", ()))
                 if player is owner),
                None,
            )
        if self.serialize_owned_card is not None and isinstance(seat, int):
            return self.serialize_owned_card(card, seat)
        return self.serialize_card(card)

    def describe_permanent(self, permanent) -> dict:
        """*permanent* for a prompt that lists permanents.

        A context built without :attr:`serialize_permanent` (a test's) falls
        back to the permanent's effective card — layers 1 and 3 and the
        granted abilities, the nearest the card renderer can come."""
        if self.serialize_permanent is not None:
            return self.serialize_permanent(permanent)
        return self.serialize_card(permanent.effective_card)


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
