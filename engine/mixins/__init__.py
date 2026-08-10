# Mixin classes for the Game dataclass.
# Per-phase / per-step turn-structure mixins live in engine.phases, not here.
# Stack mixins (casting, activation, resolution, pending choices) live in
# engine.mixins.stack, one per stage of an object's life on the stack.
from .game_ending import GameEndingMixin
from .turn_management import TurnManagementMixin
from .phase_steps import PhaseStepsMixin
from .stack import (
    AbilityActivationMixin,
    PendingChoicesMixin,
    SpellCastingMixin,
    StackResolutionMixin,
)
from .oracle_instructions import OracleInstructionsMixin
from .permanent_state import PermanentStateMixin
from .effects import EffectsMixin
from .helpers import GameHelpersMixin
