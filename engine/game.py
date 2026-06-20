from __future__ import annotations

from dataclasses import dataclass, field

# Re-exported for backwards compatibility with external importers.
from .game_types import OracleExecutionContext, OracleStateMachine, SimulationResult, StackItem
from .models import CardDefinition, PlayerState
from .mixins import (
    GameEndingMixin,
    TurnManagementMixin,
    PhaseStepsMixin,
    StackCastingMixin,
    OracleInstructionsMixin,
    PermanentStateMixin,
    EffectsMixin,
    GameHelpersMixin,
)
# Per-phase and per-step turn-structure logic (CR 500–514) lives in engine.phases,
# one mixin class per phase/step. See engine/phases/__init__.py for the taxonomy.
from .phases import (
    BeginningPhaseMixin,
    UntapStepMixin,
    UpkeepStepMixin,
    DrawStepMixin,
    PrecombatMainPhaseMixin,
    CombatPhaseMixin,
    BeginningOfCombatStepMixin,
    DeclareAttackersStepMixin,
    DeclareBlockersStepMixin,
    CombatDamageStepMixin,
    EndOfCombatStepMixin,
    PostcombatMainPhaseMixin,
    EndingPhaseMixin,
    EndStepMixin,
    CleanupStepMixin,
)



@dataclass
class Game(
    GameEndingMixin,
    # Phases and steps (CR 500–514)
    BeginningPhaseMixin,
    UntapStepMixin,
    UpkeepStepMixin,
    DrawStepMixin,
    PrecombatMainPhaseMixin,
    CombatPhaseMixin,
    BeginningOfCombatStepMixin,
    DeclareAttackersStepMixin,
    DeclareBlockersStepMixin,
    CombatDamageStepMixin,
    EndOfCombatStepMixin,
    PostcombatMainPhaseMixin,
    EndingPhaseMixin,
    EndStepMixin,
    CleanupStepMixin,
    # Cross-cutting flow and supporting machinery
    TurnManagementMixin,
    PhaseStepsMixin,
    StackCastingMixin,
    OracleInstructionsMixin,
    PermanentStateMixin,
    EffectsMixin,
    GameHelpersMixin,
):
    players: list[PlayerState]
    enforce_mana_costs: bool = False
    turn: int = 1
    current_phase: str = "main"
    current_turn_phase: str = "precombat_main"
    current_step: str = "precombat_main"
    active_player_index: int = 0
    lands_played_this_turn: dict[int, int] = field(default_factory=lambda: {0: 0, 1: 0})
    stack: list[StackItem] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    extra_turns: dict[int, int] = field(default_factory=dict)
    extra_turn_queue: list[int] = field(default_factory=list)
    current_turn_is_extra: bool = False
    # 500.7: extra turns are *inserted* after the current turn; the normal
    # turn rotation must continue from the last non-extra turn, not from the
    # player who happens to be taking an extra turn. Anchored here.
    normal_rotation_anchor: int = 0
    extra_phases_after: dict[str, list[str]] = field(default_factory=dict)
    extra_steps_after: dict[str, list[str]] = field(default_factory=dict)
    custom_phase_steps: dict[str, tuple[str, ...]] = field(default_factory=dict)
    skip_turn_counts: dict[int, int] = field(default_factory=dict)
    skip_phase_counts: dict[str, int] = field(default_factory=dict)
    skip_step_counts: dict[str, int] = field(default_factory=dict)
    combat_damage_prevented_until_eot: bool = False
    combat_attackers: dict[int, int] = field(default_factory=dict)
    combat_blockers: dict[int, int] = field(default_factory=dict)
    combat_defending_player_index: int | None = None
    combat_damage_resolved: bool = False
    combat_first_strike_done: bool = False
    combat_attackers_locked: bool = False
    combat_blockers_locked: bool = False
    # Banding (CR 702.22). ``combat_bands`` holds the attacking bands declared this
    # combat (each a list of attacker indices). ``combat_band_blocks`` maps an
    # attacker index to the blocker indices that block it via band propagation
    # (702.22h). ``combat_banding_damage`` is the defending player's pre-committed
    # damage assignment for attackers blocked by a creature with banding (702.22j).
    combat_bands: list[list[int]] = field(default_factory=list)
    combat_band_blocks: dict[int, list[int]] = field(default_factory=dict)
    combat_banding_damage: dict[int, dict[int, int]] = field(default_factory=dict)
    priority_player_index: int | None = None
    priority_pass_count: int = 0
    untapped_lands_at_turn_start: dict[int, int] = field(default_factory=dict)
    pending_search_library: dict | None = None
    pending_reorder_library: dict | None = None
    # Glasses of Urza / Jayemdae-style "look at target player's hand": the most
    # recent reveal, surfaced to the UI as {"viewer_index", "target_index",
    # "card_names"}. Cleared once the viewer dismisses it.
    pending_hand_reveal: dict | None = None
    # 610.3: tracks creatures exiled "until end of turn" — (owner_player_index, card)
    exile_until_eot: list[tuple[int, CardDefinition]] = field(default_factory=list)
    # 104.4: True when the game ends in a draw for all players
    is_draw: bool = False
    # 700.4-style turn tracking: creatures that died this turn (e.g. Scavenging Ghoul)
    creatures_died_this_turn: int = 0
    # "Rest of the game" delayed upkeep triggers left behind by a permanent that
    # has died (Cyclopean Tomb): each entry is {"controller_index", "lands"} where
    # ``lands`` are the still-mired Permanents whose mire counters must be removed
    # one-per-upkeep at the beginning of that controller's upkeeps. Populated via
    # the ON_LEAVE_BATTLEFIELD card hook and drained in resolve_upkeep.
    mire_cleanup_obligations: list = field(default_factory=list)

    def __post_init__(self) -> None:
        # Preserve legacy external phase naming while internally tracking phase/step.
        self._set_phase_and_step(self.current_turn_phase, self.current_step)
        if self._receives_priority(self.current_step):
            self.start_priority_window(self.active_player_index)
        self.check_state_based_actions()


