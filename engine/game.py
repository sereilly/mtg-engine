from __future__ import annotations

from dataclasses import dataclass, field

# Re-exported for backwards compatibility with external importers.
from .game_types import OracleExecutionContext, OracleStateMachine, SimulationResult, StackItem
from .models import CardDefinition, PlayerState
from .mixins import (
    GameEndingMixin,
    CombatMixin,
    EndingPhaseMixin,
    UpkeepMixin,
    TurnManagementMixin,
    PhaseStepsMixin,
    StackCastingMixin,
    OracleInstructionsMixin,
    PermanentStateMixin,
    EffectsMixin,
    GameHelpersMixin,
)



@dataclass
class Game(
    GameEndingMixin,
    CombatMixin,
    EndingPhaseMixin,
    UpkeepMixin,
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
    priority_player_index: int | None = None
    priority_pass_count: int = 0
    untapped_lands_at_turn_start: dict[int, int] = field(default_factory=dict)
    pending_search_library: dict | None = None
    pending_reorder_library: dict | None = None
    # 610.3: tracks creatures exiled "until end of turn" — (owner_player_index, card)
    exile_until_eot: list[tuple[int, CardDefinition]] = field(default_factory=list)
    # 104.4: True when the game ends in a draw for all players
    is_draw: bool = False

    def __post_init__(self) -> None:
        # Preserve legacy external phase naming while internally tracking phase/step.
        self._set_phase_and_step(self.current_turn_phase, self.current_step)
        if self._receives_priority(self.current_step):
            self.start_priority_window(self.active_player_index)
        self.check_state_based_actions()


