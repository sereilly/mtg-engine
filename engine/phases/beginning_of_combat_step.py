from __future__ import annotations

"""Beginning of combat step (CR 507).

In this engine the beginning of combat step has no dedicated turn-based action;
entering it simply resets combat state (handled by ``_enter_combat_step`` in
``combat_phase``) and opens a priority window. "At the beginning of combat"
triggered abilities, if any, are placed on the stack through the generic trigger
machinery. This mixin is the taxonomy placeholder for that step.
"""


class BeginningOfCombatStepMixin:
    pass
