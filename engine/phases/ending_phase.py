from __future__ import annotations

"""Ending phase (CR 512).

The ending phase contains the end step and the cleanup step, each implemented in
its own module (``end_step``, ``cleanup_step``). This engine has no
ending-phase-level turn-based action beyond those two steps, so this mixin is the
taxonomy placeholder that ties the phase together.
"""


class EndingPhaseMixin:
    pass
