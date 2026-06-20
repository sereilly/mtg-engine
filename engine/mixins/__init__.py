# Mixin classes for the Game dataclass.
# Per-phase / per-step turn-structure mixins live in engine.phases, not here.
from .game_ending import GameEndingMixin
from .turn_management import TurnManagementMixin
from .phase_steps import PhaseStepsMixin
from .stack_casting import StackCastingMixin
from .oracle_instructions import OracleInstructionsMixin
from .permanent_state import PermanentStateMixin
from .effects import EffectsMixin
from .helpers import GameHelpersMixin
