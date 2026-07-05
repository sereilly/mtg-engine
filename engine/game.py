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
    lands_played_this_turn: dict[int, int] = field(default_factory=dict)
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
    # Maps defending player index -> {blocker battlefield idx -> attacker battlefield
    # idx list}. Nested by defender because CR 802 (attack multiple players) lets 2+
    # defenders declare blocks in the same combat, and blocker battlefield indices
    # are only unambiguous within one defender's own battlefield. A blocker almost
    # always blocks one attacker; a creature that "can block an additional creature"
    # (Two-Headed Giant of Foriys) may block more (CR 509.1b).
    combat_blockers: dict[int, dict[int, list[int]]] = field(default_factory=dict)
    # Populated only when exactly one distinct defending player exists this combat
    # (2-player games, or a 3+ player combat where a single opponent was attacked).
    # The authoritative source for "who is under attack" with 2+ defenders is
    # ``combat_attackers`` (attacker idx -> defender idx); see
    # ``CombatPhaseMixin.combat_defending_players()``.
    combat_defending_player_index: int | None = None
    # CR 802.4: defending players still under attack this combat that have already
    # declared blocks (or been auto-skipped for having no legal blocks) during the
    # declare-blockers step's APNAP-ordered declarations.
    combat_blockers_declared_by: set[int] = field(default_factory=set)
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
    # ``combat_multiblock_damage`` is the defending player's pre-committed division
    # of a blocker's combat damage among the 2+ attackers it blocks (CR 510.1d,
    # Two-Headed Giant of Foriys). Maps blocker index -> {attacker index: damage}.
    combat_multiblock_damage: dict[int, dict[int, int]] = field(default_factory=dict)
    # Camouflage: set to the turn number when cast. While it matches the current
    # turn, the defending player's blocks are assigned randomly by pile (CR — the
    # spell replaces the declare-blockers step) instead of chosen.
    camouflage_active_turn: int | None = None
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
    # A forced sacrifice (Lich: "sacrifice that many nontoken permanents") awaiting
    # the sacrificing player's choice of which permanent(s). Shape: {"player_index",
    # "count", "reason"}. Only armed for seats in ``interactive_seats`` (human
    # players); AI/headless play resolves the sacrifice inline with a deterministic
    # heuristic (permanents whose death loses the game are kept for last).
    pending_sacrifice: dict | None = None
    # Seats controlled by a human, set by the web layer each action. Empty in
    # headless/AI play, so forced sacrifices there resolve inline without a prompt.
    interactive_seats: set[int] = field(default_factory=set)
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
    # Shape: {"player_index", "card_name", "land_owner_index", "land_index"}. The
    # land type is NOT changed until the choice is confirmed (confirm_land_type), so
    # the spell never visibly resolves the change before the prompt is answered; an
    # AI controller's choice is auto-resolved deterministically by the web layer.
    pending_land_type_choice: dict | None = None
    # Power Sink: "Counter target spell unless its controller pays {X}." After Power
    # Sink resolves, the targeted spell stays on the stack while its controller is
    # asked to pay {X} (tap lands, then pay or decline). Shape: {"player_index",
    # "amount", "card_name" (the counter spell), "stack_item" (the target spell)}.
    # Headless/AI play auto-resolves this deterministically (pay if able, else the
    # spell is countered and the rider applies).
    pending_mana_payment: dict | None = None
    # Kudzu: "That land's controller may attach this Aura to a land of their
    # choice." After the enchanted land is destroyed, a human controller picks the
    # land to re-enchant. Shape: {"player_index", "aura"} (the detached Permanent).
    # AI/headless play re-attaches deterministically without arming this.
    pending_kudzu_reattach: dict | None = None
    # Illusionary Mask: "{X}: you may cast a creature card whose cost X could pay,
    # face down as a 2/2." Awaiting the controller's choice of which hand creature.
    # Shape: {"player_index", "max_cmc", "card_name"}. The controller may decline.
    pending_face_down_cast: dict | None = None
    # Word of Command: "Look at target opponent's hand and choose a card; that
    # player plays it." Awaiting the caster's choice of which of the target's cards
    # to force. Shape: {"caster_index", "target_index", "card_name", "hand"}.
    pending_word_of_command: dict | None = None
    # Library of Leng: "If an effect causes you to discard a card, discard it, but
    # you may put it on top of your library instead of into your graveyard." The
    # replacement is optional, so a human controller is prompted per discarded card
    # (random/forced/cleanup discards where the card is already determined). Each
    # entry: {"player_index", "card"}; the card sits here (in no zone) until
    # confirm_leng_discard routes it. AI/headless play resolves the choice inline
    # with the beneficial top-of-library default, so this is only armed for seats
    # in ``interactive_seats``.
    pending_leng_discards: list[dict] = field(default_factory=list)
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
    # Delayed token creation from a "dies" trigger whose token appears at the
    # beginning of the next end step (Rukh Egg), by which time the source
    # permanent is long gone — each entry is {"controller_index", "name",
    # "power", "toughness", "type_line", "colors", "keywords"}. Populated in
    # _permanent_to_graveyard, drained in resolve_end_step.
    pending_end_step_tokens: list = field(default_factory=list)
    # Nafs Asp: "that player loses N life at the beginning of their next draw
    # step unless they pay {cost} before that draw step." Each entry is
    # {"player_index", "amount", "cost", "source_name"}. Populated by the
    # arm_draw_step_life_loss_unless_pay handler, resolved in resolve_draw_step.
    pending_draw_step_life_loss: list = field(default_factory=list)

    def __post_init__(self) -> None:
        # Preserve legacy external phase naming while internally tracking phase/step.
        self._set_phase_and_step(self.current_turn_phase, self.current_step)
        if self._receives_priority(self.current_step):
            self.start_priority_window(self.active_player_index)
        self.check_state_based_actions()


