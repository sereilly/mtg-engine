"""The action-handler registry ``do_action`` dispatches through.

One ``ActionSpec`` per ``ActionKind``, registered with :func:`action_handler`
exactly as the engine's ``@effect_handler`` registers instruction kinds: adding
an action means adding an entry, never another arm on a hand-ordered if/elif
chain — the shape ``engine/parsing/`` was deleted for, and the shape
``web/actions.py``'s dispatch used to be.

The spec carries the two gates the shared preamble applies *around* the
handler, so they are data the dispatcher reads rather than code each branch
repeats:

- ``human_only`` — the exact 400 detail a non-human seat gets. Two spellings
  exist ("human action" for the priority/combat actions, "debug action" for
  the Debug Menu), so the message lives on the spec to keep every response
  byte-identical to the chain it replaced.
- ``pregame`` — whether the action may run while ``session.pregame_phase`` is
  set. Registry-derived, so the pregame gate can no longer drift from the
  handlers the way a hand-kept set beside the chain could.

``concede`` is deliberately NOT here: CR 104.3a makes it available at any
time, so it runs in the preamble before the pregame gate and the snapshot,
and owns its notify reason. The guard test allowlists it by name.

Handlers take ``(session, req, seat_type)`` and raise ``HTTPException`` to
refuse; the shared tail (notify + ``build_state``) stays in ``do_action``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


ActionHandler = Callable[..., None]


@dataclass(frozen=True)
class ActionSpec:
    handler: ActionHandler
    #: The 400 detail a non-human seat gets, or None when any seat may act.
    human_only: str | None = None
    #: Whether the action may run while the session is still in pregame.
    pregame: bool = False


ACTION_HANDLERS: dict[str, ActionSpec] = {}

HUMAN_ONLY = "cannot issue human action for AI seat"
DEBUG_ONLY = "cannot issue debug action for AI seat"


def action_handler(
    *kinds: str, human_only: str | None = None, pregame: bool = False
) -> Callable[[ActionHandler], ActionHandler]:
    """Register a handler for one or more action kinds.

    A duplicate kind raises at import, exactly as ``effect_handler`` does —
    two handlers for one action is a dispatch nobody can reason about.
    """

    def register(func: ActionHandler) -> ActionHandler:
        for kind in kinds:
            if kind in ACTION_HANDLERS:
                raise ValueError(f"duplicate action handler for {kind!r}")
            ACTION_HANDLERS[kind] = ActionSpec(
                handler=func, human_only=human_only, pregame=pregame
            )
        return func

    return register
