# Mixin classes for the Game dataclass.
# Per-phase / per-step turn-structure mixins live in engine.phases, not here.
# Stack mixins (casting, activation, resolution, pending choices) live in
# engine.mixins.stack, one per stage of an object's life on the stack, each
# with the parts split out of it at the 2,000-line cap beside it; the
# pending choices are a package of their own, one mixin per prompt family.
from .game_ending import GameEndingMixin
from .turn_management import TurnManagementMixin
# Tapping a land for mana, and the CR 106.12 event the tap raises: split out
# of turn_management.py (see each module's docstring).
from .land_mana_taps import LandManaTapsMixin
from .land_tapped_for_mana import LandTappedForManaMixin
from .phase_steps import PhaseStepsMixin
from .stack import (
    AbilityActivationMixin,
    ActivationPaymentMixin,
    CardActivationMixin,
    ActivationChecksMixin,
    ActivationChargesMixin,
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
    AdditionalCastCostsMixin,
    AlternativeCastCostsMixin,
    CastTargetValidationMixin,
    PoolPaymentMixin,
    CastAnnouncementMixin,
    StackResolutionMixin,
    TriggerTargetsMixin,
    TriggeredAbilitiesMixin,
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
