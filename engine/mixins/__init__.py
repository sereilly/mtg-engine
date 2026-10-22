# Mixin classes for the Game dataclass.
# Per-phase / per-step turn-structure mixins live in engine.phases, not here.
# Stack mixins (casting, activation, resolution, pending choices) live in
# engine.mixins.stack, one per stage of an object's life on the stack; the
# pending choices are a package of their own, one mixin per prompt family.
from .game_ending import GameEndingMixin
from .turn_management import TurnManagementMixin
from .phase_steps import PhaseStepsMixin
from .stack import (
    AbilityActivationMixin,
    PendingChoicesMixin,
    ReplacementChoicesMixin,
    LibrarySearchChoicesMixin,
    LibraryChoicesMixin,
    HandChoicesMixin,
    PileChoicesMixin,
    ValueChoicesMixin,
    CardNameChoicesMixin,
    NumberChoicesMixin,
    PermanentChoicesMixin,
    PaymentChoicesMixin,
    OptionalPayChoicesMixin,
    TriggerChoicesMixin,
    SpellChoicesMixin,
    SacrificeChoicesMixin,
    SpellCastingMixin,
    StackResolutionMixin,
)
from .oracle_instructions import OracleInstructionsMixin
# A permanent's state, its board-wide statics and its recompute: one mixin
# per subject (see permanent_state.py's docstring).
from .permanent_state import PermanentStateMixin
from .entry_choices import EntryChoicesMixin
from .board_statics import BoardStaticsMixin
from .dynamic_creatures import DynamicCreaturesMixin
from .lords import LordBuffsMixin
from .protection import ProtectionMixin
from .effects import EffectsMixin
from .draws_and_discards import DrawsAndDiscardsMixin
# The general helpers, and the seams that came out of them (see helpers.py's
# docstring): control and addressing, the zone funnels, deaths, and the stack
# push with its target announcements.
from .helpers import GameHelpersMixin
from .control_seam import ControlSeamMixin
from .zone_funnels import ZoneFunnelsMixin
from .deaths import DeathsMixin
from .target_announcements import TargetAnnouncementsMixin
