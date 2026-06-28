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
from .legality import LegalityMixin
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
    LegalityMixin,
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
    # Raging River (CR 702 left/right division). When active, each defending player
    # splits their non-flying creatures into a "left" and a "right" pile, and the
    # attacking player labels each attacker; an attacker may then only be blocked by
    # flyers or creatures in the matching pile. ``combat_defender_piles`` maps a
    # defender creature index → "left"/"right"; ``combat_attacker_piles`` maps an
    # attacker index → "left"/"right".
    combat_left_right_active: bool = False
    combat_left_right_defender_index: int | None = None
    # Set once each player commits their piles, so the web prompt stops re-showing
    # (otherwise the seeded default piles make the prompt look perpetually pending).
    combat_left_right_defender_locked: bool = False
    combat_left_right_attacker_locked: bool = False
    combat_defender_piles: dict[int, str] = field(default_factory=dict)
    combat_attacker_piles: dict[int, str] = field(default_factory=dict)
    priority_player_index: int | None = None
    priority_pass_count: int = 0
    untapped_lands_at_turn_start: dict[int, int] = field(default_factory=dict)
    pending_search_library: dict | None = None
    pending_reorder_library: dict | None = None
    # A non-random "discards a card" effect (Disrupting Scepter) awaiting the
    # discarding player's choice of which card(s), and — if they control Library of
    # Leng — whether to put each on top of their library instead of the graveyard.
    # Shape: {"player_index", "count", "allow_top_of_library"}.
    pending_discard: dict | None = None
    # Balance: each player sacrifices lands/creatures and discards down to the
    # lowest count, choosing which. Shape: {"plans": {player_index: {"lands": n,
    # "creatures": n, "hand": n}}} where each n is how many to remove of that type.
    pending_balance: dict | None = None
    # "You may pay {1}. If you do, gain N life" triggers that fire when a spell
    # resolves (the color rods: Wooden Sphere, Throne of Bone, …). Each entry is
    # {"card_name", "player_index", "cost", "life"} awaiting a yes/no decision.
    pending_optional_pays: list[dict] = field(default_factory=list)
    # Glasses of Urza / Jayemdae-style "look at target player's hand": the most
    # recent reveal, surfaced to the UI as {"viewer_index", "target_index",
    # "card_names"}. Cleared once the viewer dismisses it.
    pending_hand_reveal: dict | None = None
    # Phantasmal Terrain: "As this Aura enters, choose a basic land type." Awaiting
    # the controller's choice of which basic land type the enchanted land becomes.
    # Shape: {"player_index", "card_name", "land_owner_index", "land_index"}. A
    # provisional default ("island") is applied immediately so headless/AI play is
    # deterministic; a human may override it via confirm_land_type.
    pending_land_type_choice: dict | None = None
    # Kudzu: "That land's controller may attach this Aura to a land of their
    # choice." After the enchanted land is destroyed, a human controller picks the
    # land to re-enchant. Shape: {"player_index", "aura"} (the detached Permanent).
    # AI/headless play re-attaches deterministically without arming this.
    pending_kudzu_reattach: dict | None = None
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


