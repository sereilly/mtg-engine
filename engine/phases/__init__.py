"""Turn phases and steps (CR 500–514).

Each phase, and each step within a phase, lives in its own module here as a small
mixin class composed onto the :class:`~engine.game.Game`. The taxonomy mirrors
the comprehensive rules turn structure:

    Beginning phase        beginning_phase
      ├─ Untap step        untap_step
      ├─ Upkeep step       upkeep_step
      └─ Draw step         draw_step
    Precombat main phase   precombat_main_phase
    Combat phase           combat_phase
      ├─ Beginning of combat   beginning_of_combat_step
      ├─ Declare attackers     declare_attackers_step
      ├─ Declare blockers      declare_blockers_step
      ├─ Combat damage         combat_damage_step
      └─ End of combat         end_of_combat_step
    Postcombat main phase  postcombat_main_phase
    Ending phase           ending_phase
      ├─ End step          end_step
      └─ Cleanup step      cleanup_step

Cross-cutting turn-structure navigation (priority windows, phase/step ordering,
extra turns/phases/steps, skips) is not tied to a single phase and remains in
``engine.mixins.phase_steps``.
"""

from .beginning_phase import BeginningPhaseMixin
from .untap_step import UntapStepMixin
from .upkeep_step import UpkeepStepMixin
from .draw_step import DrawStepMixin
from .precombat_main_phase import PrecombatMainPhaseMixin
from .combat_phase import CombatPhaseMixin
from .beginning_of_combat_step import BeginningOfCombatStepMixin
from .declare_attackers_step import DeclareAttackersStepMixin
from .declare_blockers_step import DeclareBlockersStepMixin
from .combat_damage_step import CombatDamageStepMixin
from .end_of_combat_step import EndOfCombatStepMixin
from .postcombat_main_phase import PostcombatMainPhaseMixin
from .ending_phase import EndingPhaseMixin
from .end_step import EndStepMixin
from .cleanup_step import CleanupStepMixin

__all__ = [
    "BeginningPhaseMixin",
    "UntapStepMixin",
    "UpkeepStepMixin",
    "DrawStepMixin",
    "PrecombatMainPhaseMixin",
    "CombatPhaseMixin",
    "BeginningOfCombatStepMixin",
    "DeclareAttackersStepMixin",
    "DeclareBlockersStepMixin",
    "CombatDamageStepMixin",
    "EndOfCombatStepMixin",
    "PostcombatMainPhaseMixin",
    "EndingPhaseMixin",
    "EndStepMixin",
    "CleanupStepMixin",
]
