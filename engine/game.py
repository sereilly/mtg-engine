from __future__ import annotations

import re
from dataclasses import dataclass, field

from .classifier import CardClassification, classify_card
from .models import CardDefinition, Permanent, PlayerState
from .oracle import OracleInstruction, compile_card_oracle, lex_oracle_text

_MANA_SYMBOLS = ("W", "U", "B", "R", "G", "C")
_EOT_METADATA_KEYS = (
    "gains_flying_until_eot",
    "gains_banding_until_eot",
    "cant_be_blocked_until_eot",
    "must_attack_until_eot",
    "destroy_if_did_not_attack_eot",
    "redirect_one_damage_to_owner_until_eot",
)

_TURN_PHASES: tuple[str, ...] = (
    "beginning",
    "precombat_main",
    "combat",
    "postcombat_main",
    "ending",
)

_PHASE_STEPS: dict[str, tuple[str, ...]] = {
    "beginning": ("untap", "upkeep", "draw"),
    "precombat_main": ("precombat_main",),
    "combat": (
        "beginning_of_combat",
        "declare_attackers",
        "declare_blockers",
        "combat_damage",
        "end_of_combat",
    ),
    "postcombat_main": ("postcombat_main",),
    "ending": ("end", "cleanup"),
}

# Untap and cleanup are the regular no-priority steps in this simplified engine.
_NO_PRIORITY_STEPS = {"untap", "cleanup"}


@dataclass
class SimulationResult:
    card_name: str
    supported: bool
    effect_kind: str
    details: str


@dataclass
class StackItem:
    card: CardDefinition
    caster_index: int
    target_player_index: int | None
    target_permanent_index: int | None
    x_value: int | None
    ability_instruction: OracleInstruction | None = None
    ability_effect_kind: str | None = None
    source_permanent: Permanent | None = None


@dataclass
class OracleExecutionContext:
    caster: PlayerState
    target: PlayerState
    card: CardDefinition
    target_permanent_index: int | None = None
    x_value: int | None = None
    source_permanent: Permanent | None = None


class OracleStateMachine:
    def __init__(self, game: Game, context: OracleExecutionContext) -> None:
        self.game = game
        self.context = context
        self.state = "ready"

    def run(self, instruction: OracleInstruction) -> tuple[bool, str]:
        self.state = "running"
        supported, details = self.game._execute_oracle_instruction(instruction, self.context)
        self.state = "completed" if supported else "failed"
        return supported, details


@dataclass
class Game:
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

    def __post_init__(self) -> None:
        # Preserve legacy external phase naming while internally tracking phase/step.
        self._set_phase_and_step(self.current_turn_phase, self.current_step)
        if self._receives_priority(self.current_step):
            self.start_priority_window(self.active_player_index)

    def _find_controlled_permanent(
        self,
        controller: PlayerState,
        permanent_name: str,
        permanent_index: int | None = None,
    ) -> tuple[int, Permanent] | None:
        if permanent_index is not None:
            if permanent_index < 0 or permanent_index >= len(controller.battlefield):
                return None
            permanent = controller.battlefield[permanent_index]
            if permanent.card.name != permanent_name:
                return None
            return permanent_index, permanent

        for idx, permanent in enumerate(controller.battlefield):
            if permanent.card.name == permanent_name:
                return idx, permanent
        return None

    def _is_summoning_sick(self, permanent: Permanent) -> bool:
        if permanent.card.primary_type != "creature":
            return False
        if self._has_keyword(permanent, "Haste"):
            return False
        return permanent.metadata.get("summoning_sickness_turn") == self.turn

    def _put_permanent_onto_battlefield(
        self,
        controller_index: int,
        permanent: Permanent,
        target_player_index: int | None,
    ) -> None:
        self.players[controller_index].battlefield.append(permanent)
        self._initialize_permanent_state(permanent, controller_index, target_player_index)

    def _public_phase_name(self, phase: str, step: str) -> str:
        if phase in {"precombat_main", "postcombat_main"}:
            return "main"
        if phase == "combat":
            return "combat"
        if phase == "ending" and step in {"end", "cleanup"}:
            return step
        if phase == "beginning" and step in {"untap", "upkeep", "draw"}:
            return step
        return step

    def _set_phase_and_step(self, phase: str, step: str) -> None:
        self.current_turn_phase = phase
        self.current_step = step
        self.current_phase = self._public_phase_name(phase, step)

    def _receives_priority(self, step: str) -> bool:
        return step not in _NO_PRIORITY_STEPS

    def _make_expiry_tag(self, edge: str, phase: str, step: str) -> str:
        return f"{edge}:{phase}:{step}"

    def _expire_tagged_effects(self, tag: str) -> None:
        for player in self.players:
            for permanent in player.battlefield:
                expires = permanent.metadata.get("expires_at")
                if expires != tag:
                    continue
                key = permanent.metadata.get("expires_key")
                if isinstance(key, str):
                    permanent.metadata.pop(key, None)
                permanent.metadata.pop("expires_at", None)
                permanent.metadata.pop("expires_key", None)

    def _on_step_or_phase_begin(self, phase: str, step: str) -> None:
        # 500.4
        self._expire_tagged_effects(self._make_expiry_tag("begin_step", phase, step))
        self._expire_tagged_effects(self._make_expiry_tag("begin_phase", phase, step))

    def _on_step_or_phase_end(self, phase: str, step: str) -> None:
        # 500.5 and 500.5a
        self._expire_tagged_effects(self._make_expiry_tag("end_step", phase, step))
        self._expire_tagged_effects(self._make_expiry_tag("end_phase", phase, step))
        if phase == "combat" and step == "end_of_combat":
            self._expire_tagged_effects("end_of_combat")
        self.clear_mana_pools()

    def _resolve_priority_window(self) -> None:
        # 500.2 simplified: both players pass in succession once the stack is empty.
        while True:
            self.resolve_stack()
            if not self.stack:
                return

    def start_priority_window(self, starting_player_index: int | None = None) -> None:
        player_index = self.active_player_index if starting_player_index is None else starting_player_index
        if player_index < 0 or player_index >= len(self.players):
            self.priority_player_index = None
            self.priority_pass_count = 0
            return
        self.priority_player_index = player_index
        self.priority_pass_count = 0

    def clear_priority_window(self) -> None:
        self.priority_player_index = None
        self.priority_pass_count = 0

    def has_priority(self, player_index: int) -> bool:
        return self.priority_player_index == player_index

    def note_priority_action_taken(self, player_index: int) -> None:
        if self.priority_player_index is None:
            self.start_priority_window(player_index)
            return
        if self.priority_player_index != player_index:
            raise ValueError("player does not have priority")
        # 117.3c: after casting/activating, that player gets priority again.
        self.priority_pass_count = 0

    def _next_player_index(self, player_index: int) -> int:
        if len(self.players) <= 1:
            return player_index
        return (player_index + 1) % len(self.players)

    def pass_priority(self, player_index: int) -> str:
        if self.priority_player_index is None:
            raise ValueError("no active priority window")
        if self.priority_player_index != player_index:
            raise ValueError("player does not have priority")

        self.priority_pass_count += 1
        self.log.append(f"{self.players[player_index].name} passed priority")

        if self.priority_pass_count < len(self.players):
            self.priority_player_index = self._next_player_index(player_index)
            return "passed"

        # All players have passed in succession.
        self.priority_pass_count = 0
        if self.stack:
            self.resolve_top_of_stack()
            # 117.3b: active player gets priority after a spell/ability resolves.
            self.priority_player_index = self.active_player_index
            return "resolved_top"

        self.priority_player_index = self.active_player_index
        return "all_passed_empty"

    def add_extra_turn(self, player_index: int) -> None:
        # 500.7 most recently created turn occurs first.
        self.extra_turn_queue.append(player_index)
        self.extra_turns[player_index] = self.extra_turns.get(player_index, 0) + 1

    def add_extra_phase(
        self,
        after_phase: str,
        phase_name: str,
        steps: tuple[str, ...] | None = None,
        controller_index: int | None = None,
        only_on_controllers_turn: bool = False,
    ) -> bool:
        # 500.10a
        if only_on_controllers_turn and controller_index is not None and controller_index != self.active_player_index:
            return False
        self.extra_phases_after.setdefault(after_phase, []).insert(0, phase_name)
        if steps is not None:
            self.custom_phase_steps[phase_name] = tuple(steps)
        return True

    def add_extra_step(
        self,
        step_name: str,
        *,
        after_step: str | None = None,
        before_step: str | None = None,
        controller_index: int | None = None,
        only_on_controllers_turn: bool = False,
    ) -> bool:
        # 500.9 and 500.10a
        if only_on_controllers_turn and controller_index is not None and controller_index != self.active_player_index:
            return False
        if after_step is None and before_step is None:
            raise ValueError("either after_step or before_step must be provided")
        anchor = after_step if after_step is not None else f"before:{before_step}"
        self.extra_steps_after.setdefault(anchor, []).insert(0, step_name)
        return True

    def add_additional_step_after_phase(
        self,
        after_phase: str,
        step_name: str,
        *,
        controller_index: int | None = None,
        only_on_controllers_turn: bool = False,
    ) -> bool:
        # 500.10: create the containing phase with only the specified step.
        phase_name = f"extra_phase_for_{step_name}_{len(self.custom_phase_steps)}"
        return self.add_extra_phase(
            after_phase=after_phase,
            phase_name=phase_name,
            steps=(step_name,),
            controller_index=controller_index,
            only_on_controllers_turn=only_on_controllers_turn,
        )

    def skip_next_turn(self, player_index: int, count: int = 1) -> None:
        # 500.11
        self.skip_turn_counts[player_index] = self.skip_turn_counts.get(player_index, 0) + max(0, count)

    def skip_next_phase(self, phase_name: str, count: int = 1) -> None:
        self.skip_phase_counts[phase_name] = self.skip_phase_counts.get(phase_name, 0) + max(0, count)

    def skip_next_step(self, step_name: str, count: int = 1) -> None:
        self.skip_step_counts[step_name] = self.skip_step_counts.get(step_name, 0) + max(0, count)

    def _consume_skip(self, bucket: dict[object, int], key: object) -> bool:
        amount = bucket.get(key, 0)
        if amount <= 0:
            return False
        if amount == 1:
            bucket.pop(key, None)
        else:
            bucket[key] = amount - 1
        return True

    def _phase_steps(self, phase: str) -> tuple[str, ...]:
        base = list(self.custom_phase_steps.get(phase, _PHASE_STEPS.get(phase, (phase,))))
        expanded: list[str] = []
        for step in base:
            expanded.extend(self.extra_steps_after.pop(f"before:{step}", []))
            if not self._consume_skip(self.skip_step_counts, step):
                expanded.append(step)
            expanded.extend(self.extra_steps_after.pop(step, []))
        return tuple(expanded)

    def _next_phase_after(self, phase: str) -> str | None:
        extras = self.extra_phases_after.get(phase, [])
        if extras:
            candidate = extras.pop(0)
            if not extras:
                self.extra_phases_after.pop(phase, None)
            return candidate

        if phase not in _TURN_PHASES:
            return None
        idx = _TURN_PHASES.index(phase)
        if idx + 1 >= len(_TURN_PHASES):
            return None
        return _TURN_PHASES[idx + 1]

    def next_unskipped_phase_after(self, phase: str) -> str | None:
        candidate = self._next_phase_after(phase)
        while candidate is not None and self._consume_skip(self.skip_phase_counts, candidate):
            candidate = self._next_phase_after(candidate)
        return candidate

    def _compute_next_active_player(self) -> int:
        if self.extra_turn_queue:
            chosen = self.extra_turn_queue.pop()
            pending = self.extra_turns.get(chosen, 0)
            if pending > 0:
                self.extra_turns[chosen] = pending - 1
            return chosen

        # Legacy extra turn effects can still increment this map directly.
        pending_legacy = self.extra_turns.get(self.active_player_index, 0)
        if pending_legacy > 0:
            self.extra_turns[self.active_player_index] = pending_legacy - 1
            return self.active_player_index

        candidate = 1 - self.active_player_index
        while self.skip_turn_counts.get(candidate, 0) > 0:
            self._consume_skip(self.skip_turn_counts, candidate)
            candidate = 1 - candidate
        return candidate

    def _enter_main_phase(self, *, precombat: bool) -> None:
        phase = "precombat_main" if precombat else "postcombat_main"
        step = phase
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        if self._receives_priority(step):
            self.start_priority_window(self.active_player_index)

    def _close_current_priority_step(self) -> None:
        phase = self.current_turn_phase
        step = self.current_step
        if self._receives_priority(step):
            self._resolve_priority_window()
            self.clear_priority_window()
        self._on_step_or_phase_end(phase, step)

    def _enter_combat_step(self, step: str) -> None:
        if step == "beginning_of_combat":
            self._reset_combat_state(clear_damage_marked=False)
        if step == "declare_attackers":
            self.combat_attackers_locked = False
            self.combat_blockers_locked = False
            if self.combat_defending_player_index is None:
                self.combat_defending_player_index = 1 - self.active_player_index
        if step == "declare_blockers":
            self.combat_blockers_locked = not bool(self.combat_attackers)
        self._set_phase_and_step("combat", step)
        self._on_step_or_phase_begin("combat", step)
        if self._receives_priority(step):
            self.start_priority_window(self.active_player_index)

    def _has_any_legal_attacker(self, attacker_index: int, defender_index: int) -> bool:
        if attacker_index < 0 or attacker_index >= len(self.players):
            return False
        if defender_index < 0 or defender_index >= len(self.players):
            return False
        if attacker_index == defender_index:
            return False

        attacker_player = self.players[attacker_index]
        for attacker in attacker_player.battlefield:
            if attacker.card.primary_type != "creature":
                continue
            if attacker.tapped:
                continue
            if self.can_attack(attacker, defender_index):
                return True
        return False

    def _has_any_legal_block(self, defender_index: int) -> bool:
        if defender_index < 0 or defender_index >= len(self.players):
            return False
        if self.active_player_index < 0 or self.active_player_index >= len(self.players):
            return False

        self._prune_combat_state()
        if not self.combat_attackers:
            return False

        defender = self.players[defender_index]
        attacker_controller = self.players[self.active_player_index]
        for blocker in defender.battlefield:
            if blocker.card.primary_type != "creature" or blocker.tapped:
                continue
            for attacker_idx in self.combat_attackers:
                if attacker_idx < 0 or attacker_idx >= len(attacker_controller.battlefield):
                    continue
                attacker = attacker_controller.battlefield[attacker_idx]
                if self._can_block_attacker(blocker, attacker):
                    return True
        return False

    def advance_combat_phase(self) -> None:
        combat_steps = list(self._phase_steps("combat"))
        if self.current_turn_phase != "combat":
            self._enter_combat_step(combat_steps[0])
            return

        try:
            idx = combat_steps.index(self.current_step)
        except ValueError:
            self._enter_combat_step(combat_steps[0])
            return

        if self.current_step == "end_of_combat":
            self.end_combat(step_already_started=True)
            self._enter_main_phase(precombat=False)
            return
        if self.current_step == "declare_attackers" and not self.combat_attackers_locked:
            defender_index = self.combat_defending_player_index
            if not isinstance(defender_index, int):
                defender_index = 1 - self.active_player_index
                self.combat_defending_player_index = defender_index

            if self._has_any_legal_attacker(self.active_player_index, defender_index):
                return

            self.combat_attackers = {}
            self.combat_blockers = {}
            self.combat_attackers_locked = True
            self.combat_blockers_locked = True
            self._prune_combat_state()
            attacker_name = self.players[self.active_player_index].name
            self.log.append(f"{attacker_name} has no valid attackers; declare attackers step skipped")
        if self.current_step == "declare_blockers" and not self.combat_blockers_locked:
            defender_index = self.combat_defending_player_index
            if isinstance(defender_index, int) and not self._has_any_legal_block(defender_index):
                self.combat_blockers = {}
                self.combat_blockers_locked = True
                self._prune_combat_state()
                defender_name = self.players[defender_index].name
                self.log.append(f"{defender_name} has no valid blockers; declare blockers step skipped")
            else:
                return
        if self.current_step == "declare_blockers" and self.combat_blockers_locked and not self.combat_attackers:
            defender_index = self.combat_defending_player_index
            if isinstance(defender_index, int):
                defender_name = self.players[defender_index].name
                self.log.append(f"{defender_name} has no valid blockers; declare blockers step skipped")
        if self.current_step == "combat_damage" and not self.combat_damage_resolved:
            return  # Awaiting manual damage assignment

        if self.current_step == "declare_attackers":
            self.log.append(
                f"Declare attackers step complete: {len(self.combat_attackers)} attacker(s) declared"
            )
        if self.current_step == "declare_blockers":
            self.log.append(
                f"Declare blockers step complete: {len(self.combat_blockers)} blocker(s) declared"
            )

        # Close current combat step, then enter the next one.
        if self._receives_priority(self.current_step):
            self._resolve_priority_window()
        self._on_step_or_phase_end("combat", self.current_step)

        next_idx = idx + 1
        if next_idx >= len(combat_steps):
            self._enter_main_phase(precombat=False)
            return
        if combat_steps[next_idx] == "combat_damage":
            self.combat_damage_resolved = False
            self.combat_first_strike_done = False
        self._enter_combat_step(combat_steps[next_idx])

        # Auto-resolve and skip combat_damage when no manual assignment is needed.
        if combat_steps[next_idx] == "combat_damage" and not self._needs_manual_damage_assignment():
            auto = self._build_auto_damage_assignment()
            self.resolve_combat_damage(self.active_player_index, attacker_damage=auto)
            if not self.combat_damage_resolved:  # first-strike pass; do second
                self.resolve_combat_damage(self.active_player_index, attacker_damage=auto)
            if self._receives_priority("combat_damage"):
                self._resolve_priority_window()
            self._on_step_or_phase_end("combat", "combat_damage")
            eoc_idx = next_idx + 1
            if eoc_idx >= len(combat_steps):
                self._enter_main_phase(precombat=False)
                return
            self._enter_combat_step(combat_steps[eoc_idx])

    def start_turn(self, player_index: int) -> None:
        self.active_player_index = player_index
        self.lands_played_this_turn[player_index] = 0
        self.resolve_untap_step(player_index)
        self.resolve_upkeep(player_index)
        self.resolve_draw_step(player_index)
        self._enter_main_phase(precombat=True)

    def start_next_turn(self) -> int:
        self.turn += 1
        next_player = self._compute_next_active_player()
        self.start_turn(next_player)
        return next_player

    def cast_from_hand(
        self,
        caster_index: int,
        card_name: str,
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        x_value: int | None = None,
    ) -> SimulationResult:
        queued = self.queue_from_hand(
            caster_index,
            card_name,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            x_value=x_value,
        )
        if not queued.supported:
            return queued

        self.resolve_stack()
        self.clear_priority_window()
        return SimulationResult(queued.card_name, True, queued.effect_kind, "resolved")

    def activate_permanent_ability(
        self,
        controller_index: int,
        permanent_name: str,
        target_player_index: int | None = None,
        permanent_index: int | None = None,
        mana_color: str | None = None,
    ) -> SimulationResult:
        queued = self.queue_permanent_ability(
            controller_index,
            permanent_name,
            target_player_index=target_player_index,
            permanent_index=permanent_index,
            mana_color=mana_color,
        )
        if not queued.supported:
            return queued
        if queued.details == "queued":
            self.resolve_stack()
            self.clear_priority_window()
            return SimulationResult(queued.card_name, True, queued.effect_kind, "resolved")
        return queued

    def queue_permanent_ability(
        self,
        controller_index: int,
        permanent_name: str,
        target_player_index: int | None = None,
        permanent_index: int | None = None,
        mana_color: str | None = None,
    ) -> SimulationResult:
        controller = self.players[controller_index]
        resolved = self._find_controlled_permanent(controller, permanent_name, permanent_index)
        if resolved is None:
            raise ValueError(f"Permanent not found: {permanent_name}")
        _, permanent = resolved

        program = compile_card_oracle(permanent.card)
        target_idx = target_player_index if target_player_index is not None else (1 - controller_index)
        target_player = self.players[target_idx]



        # Special handling for Basalt Monolith: only allow tap if untapped, untap if tapped
        if permanent.card.name == "Basalt Monolith" and len(program.activated_abilities) == 2:
            tap_ability = None
            untap_ability = None
            for ab in program.activated_abilities:
                if ab.cost.requires_tap:
                    tap_ability = ab
                elif ab.cost.mana.get("generic", 0) == 3 and not ab.cost.requires_tap:
                    untap_ability = ab
            if not permanent.tapped:
                ability = tap_ability
            else:
                ability = untap_ability
            # If trying to tap when tapped, or untap when untapped, block
            if ability is None:
                self.log.append(f"No implemented activated ability for {permanent.card.name} in current state")
                return SimulationResult(permanent.card.name, False, "unsupported", "ability not implemented")
            if ability == tap_ability and permanent.tapped:
                self.log.append(f"Cannot tap Basalt Monolith when already tapped")
                return SimulationResult(permanent.card.name, False, "unsupported", "already tapped")
            if ability == untap_ability and not permanent.tapped:
                self.log.append(f"Cannot untap Basalt Monolith when already untapped")
                return SimulationResult(permanent.card.name, False, "unsupported", "already untapped")
        else:
            ability = next((item for item in program.activated_abilities if item.supported and item.instruction is not None), None)

        if ability is None or ability.instruction is None:
            self.log.append(f"No implemented activated ability for {permanent.card.name}")
            return SimulationResult(permanent.card.name, False, "unsupported", "ability not implemented")

        if ability.instruction.kind == "grant_banding_to_target":
            has_valid_target = any(perm.card.primary_type == "creature" for perm in target_player.battlefield)
            if not has_valid_target:
                details = "no valid creature target for banding effect"
                self.log.append("No valid creature target for banding effect")
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        required_cost = dict(ability.cost.mana)
        requires_tap = ability.cost.requires_tap
        if self.enforce_mana_costs and any(required_cost.values()):
            if not self._pay_mana_cost(controller, required_cost):
                details = f"insufficient mana to activate {permanent.card.name}"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        if requires_tap:
            if self._is_summoning_sick(permanent):
                details = f"{permanent.card.name} has summoning sickness"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            if permanent.tapped:
                details = f"{permanent.card.name} is already tapped"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            permanent.tapped = True

        instruction = ability.instruction
        if (
            instruction.kind in {"sacrifice_self_for_mana", "add_mana_from_text"}
            and instruction.payload.get("any_color", False)
        ):
            selected_color = self._normalize_mana_color(mana_color)
            if selected_color is not None:
                instruction = OracleInstruction(
                    instruction.kind,
                    instruction.value,
                    {**instruction.payload, "color": selected_color},
                )


        mana_like_kinds = {
            "add_mana_from_text",
            "sacrifice_self_for_mana",
            "sacrifice_creature_for_black_mana",
        }
        if instruction.kind in mana_like_kinds:
            # For Basalt Monolith, block add_mana_from_text if untapped is required and it's already untapped
            if permanent.card.name == "Basalt Monolith" and instruction.kind == "add_mana_from_text" and not permanent.tapped:
                self.log.append(f"Cannot tap Basalt Monolith for mana when already untapped")
                return SimulationResult(permanent.card.name, False, "unsupported", "already untapped")
            state_machine = OracleStateMachine(
                self,
                OracleExecutionContext(
                    caster=controller,
                    target=target_player,
                    card=permanent.card,
                    source_permanent=permanent,
                ),
            )
            supported, details = state_machine.run(instruction)
            return SimulationResult(permanent.card.name, supported, ability.effect_kind, details)

        self.stack.append(
            StackItem(
                card=permanent.card,
                caster_index=controller_index,
                target_player_index=target_idx,
                target_permanent_index=None,
                x_value=None,
                ability_instruction=instruction,
                ability_effect_kind=ability.effect_kind,
                source_permanent=permanent,
            )
        )
        self.log.append(f"{permanent.card.name} ability added to stack")
        return SimulationResult(permanent.card.name, True, ability.effect_kind, "queued")

    def _normalize_mana_color(self, mana_color: str | None) -> str | None:
        if mana_color is None:
            return None
        color = mana_color.strip().upper()
        if color not in {"W", "U", "B", "R", "G"}:
            raise ValueError(f"Invalid mana color: {mana_color}")
        return color

    def tap_permanent(
        self,
        controller_index: int,
        permanent_name: str,
        permanent_index: int | None = None,
    ) -> bool:
        controller = self.players[controller_index]
        resolved = self._find_controlled_permanent(controller, permanent_name, permanent_index)
        permanent = resolved[1] if resolved else None
        if permanent is None or permanent.tapped:
            return False

        permanent.tapped = True
        self.log.append(f"{controller.name} tapped {permanent_name}")
        return True

    def queue_from_hand(
        self,
        caster_index: int,
        card_name: str,
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        x_value: int | None = None,
    ) -> SimulationResult:
        caster = self.players[caster_index]
        try:
            hand_index = next(i for i, card in enumerate(caster.hand) if card.name == card_name)
        except StopIteration as exc:
            raise ValueError(f"Card not in hand: {card_name}") from exc

        card = caster.hand[hand_index]
        classification = classify_card(card)
        extra_generic_tax = 0

        if self.enforce_mana_costs and card.primary_type == "land":
            lands_played = self.lands_played_this_turn.get(caster_index, 0)
            if lands_played >= 1 and self._fastbond_count(caster_index) <= 0:
                details = "already played a land this turn"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        if "W" in card.colors:
            has_gloom = any(
                perm.card.name == "Gloom"
                for player in self.players
                for perm in player.battlefield
            )
            if has_gloom:
                extra_generic_tax = 3
                self.log.append(f"{card.name} is taxed by Gloom")

        # Accept cards with supported triggered abilities (match classifier logic)
        if not classification.supported:
            if classification.reason == "unsupported triggered ability":
                from .oracle import compile_card_oracle
                program = compile_card_oracle(card)
                if any(getattr(program, "triggered_abilities", ())):
                    if any(t.supported for t in program.triggered_abilities):
                        return SimulationResult(card.name, True, program.effect_kind, "supported triggered ability")
            self.log.append(f"Unsupported card: {card.name} ({classification.reason})")
            return SimulationResult(card.name, False, classification.effect_kind, classification.reason)

        resolved_x_value = x_value
        if resolved_x_value is None and "{X}" in card.mana_cost.upper():
            resolved_x_value = self._infer_x_value(caster, card.mana_cost, extra_generic_tax)

        if self.enforce_mana_costs and card.primary_type != "land":
            cost = self._parse_mana_cost(card.mana_cost, x_value=resolved_x_value, extra_generic=extra_generic_tax)
            if not self._pay_mana_cost(caster, cost):
                details = f"insufficient mana for {card.name}"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        card = caster.hand.pop(hand_index)

        if card.primary_type != "land":
            self.stack.append(
                StackItem(
                    card=card,
                    caster_index=caster_index,
                    target_player_index=target_player_index,
                    target_permanent_index=target_permanent_index,
                    x_value=resolved_x_value,
                )
            )
            self.log.append(f"{card.name} added to stack")
            return SimulationResult(card.name, True, classification.effect_kind, "queued")

        self._resolve_card(
            caster_index=caster_index,
            card=card,
            classification=classification,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            x_value=resolved_x_value,
        )
        return SimulationResult(card.name, True, classification.effect_kind, "resolved")

    def _infer_x_value(self, player: PlayerState, mana_cost: str, extra_generic: int = 0) -> int:
        required = self._parse_mana_cost(mana_cost, x_value=0, extra_generic=extra_generic)
        temp = {symbol: player.mana_pool.get(symbol, 0) for symbol in ("W", "U", "B", "R", "G", "C")}

        if temp.get("W", 0) < required["W"]:
            return 0
        if temp.get("U", 0) < required["U"]:
            return 0
        if temp.get("B", 0) < required["B"]:
            return 0
        if temp.get("G", 0) < required["G"]:
            return 0
        if temp.get("C", 0) < required["C"]:
            return 0

        available_red = temp.get("R", 0)
        if player.can_spend_white_as_red:
            available_red += temp.get("W", 0)
        if available_red < required["R"]:
            return 0

        temp["W"] -= required["W"]
        temp["U"] -= required["U"]
        temp["B"] -= required["B"]
        temp["G"] -= required["G"]
        temp["C"] -= required["C"]

        red_to_pay = required["R"]
        from_red = min(temp.get("R", 0), red_to_pay)
        temp["R"] -= from_red
        red_to_pay -= from_red
        if red_to_pay > 0:
            if not player.can_spend_white_as_red:
                return 0
            if temp.get("W", 0) < red_to_pay:
                return 0
            temp["W"] -= red_to_pay

        available_generic = sum(max(0, temp.get(sym, 0)) for sym in ("C", "W", "U", "B", "R", "G"))
        if available_generic < required["generic"]:
            return 0

        return available_generic - required["generic"]

    def _parse_mana_cost(self, mana_cost: str, x_value: int | None, extra_generic: int = 0) -> dict[str, int]:
        required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": max(0, extra_generic)}
        if not mana_cost:
            return required

        for token in re.findall(r"\{([^}]+)\}", mana_cost.upper()):
            if token.isdigit():
                required["generic"] += int(token)
                continue
            if token == "X":
                required["generic"] += max(0, x_value or 0)
                continue
            if token in {"W", "U", "B", "R", "G", "C"}:
                required[token] += 1
        return required

    def _pay_mana_cost(self, player: PlayerState, required: dict[str, int]) -> bool:
        pool = player.mana_pool

        if pool.get("W", 0) < required["W"]:
            return False
        if pool.get("U", 0) < required["U"]:
            return False
        if pool.get("B", 0) < required["B"]:
            return False
        if pool.get("G", 0) < required["G"]:
            return False
        if pool.get("C", 0) < required["C"]:
            return False

        available_red = pool.get("R", 0)
        if player.can_spend_white_as_red:
            available_red += pool.get("W", 0)
        if available_red < required["R"]:
            return False

        temp = {symbol: pool.get(symbol, 0) for symbol in ("W", "U", "B", "R", "G", "C")}
        temp["W"] -= required["W"]
        temp["U"] -= required["U"]
        temp["B"] -= required["B"]
        temp["G"] -= required["G"]
        temp["C"] -= required["C"]

        red_to_pay = required["R"]
        from_red = min(temp.get("R", 0), red_to_pay)
        temp["R"] -= from_red
        red_to_pay -= from_red
        if red_to_pay > 0:
            if not player.can_spend_white_as_red:
                return False
            if temp.get("W", 0) < red_to_pay:
                return False
            temp["W"] -= red_to_pay

        generic = required["generic"]
        if generic > 0:
            available_generic = sum(max(0, temp.get(sym, 0)) for sym in ("C", "W", "U", "B", "R", "G"))
            if available_generic < generic:
                return False

            for sym in ("C", "W", "U", "B", "R", "G"):
                spend = min(temp.get(sym, 0), generic)
                temp[sym] -= spend
                generic -= spend
                if generic == 0:
                    break

        player.mana_pool = temp
        return True

    def resolve_stack(self) -> None:
        while self.stack:
            self.resolve_top_of_stack()

    def resolve_top_of_stack(self) -> bool:
        if not self.stack:
            return False

        item = self.stack.pop()
        if item.ability_instruction is not None:
            caster = self.players[item.caster_index]
            target_idx = item.target_player_index if item.target_player_index is not None else (1 - item.caster_index)
            target = self.players[target_idx]
            state_machine = OracleStateMachine(
                self,
                OracleExecutionContext(
                    caster=caster,
                    target=target,
                    card=item.card,
                    target_permanent_index=item.target_permanent_index,
                    x_value=item.x_value,
                    source_permanent=item.source_permanent,
                ),
            )
            supported, details = state_machine.run(item.ability_instruction)
            if supported:
                self.log.append(f"{item.card.name} ability resolved")
            else:
                self.log.append(f"{item.card.name} ability fizzled: {details}")
            return True

        classification = classify_card(item.card)
        self._resolve_card(
            caster_index=item.caster_index,
            card=item.card,
            classification=classification,
            target_player_index=item.target_player_index,
            target_permanent_index=item.target_permanent_index,
            x_value=item.x_value,
        )
        return True

    def _resolve_card(
        self,
        caster_index: int,
        card: CardDefinition,
        classification: CardClassification,
        target_player_index: int | None,
        target_permanent_index: int | None = None,
        x_value: int | None = None,
    ) -> None:
        caster = self.players[caster_index]
        primary_type = card.primary_type

        if primary_type in {"land", "creature", "artifact", "enchantment"}:
            permanent = Permanent(card=card)
            if x_value is not None:
                permanent.metadata["cast_x_value"] = x_value
            self._put_permanent_onto_battlefield(caster_index, permanent, target_player_index)
            self.log.append(f"{caster.name} put {card.name} onto battlefield")
            self._apply_global_buff(caster, card)
            self._apply_aura_effect(caster_index, permanent, target_player_index, target_permanent_index)
            self._apply_cast_triggers(caster_index, card)
            self._refresh_dynamic_creatures()
            if primary_type == "land":
                if self.enforce_mana_costs:
                    self.lands_played_this_turn[caster_index] = self.lands_played_this_turn.get(caster_index, 0) + 1
                    if self.lands_played_this_turn.get(caster_index, 0) > 1:
                        fastbond_count = self._fastbond_count(caster_index)
                        if fastbond_count > 0:
                            damage = self._prevent_damage(caster, fastbond_count)
                            if damage > 0:
                                caster.life -= damage
                            self.log.append(f"Fastbond dealt {damage} damage to {caster.name}")
                self._process_land_enters(caster_index)
            return

        # Sorceries and instants resolve immediately in this basic engine.
        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        target = self.players[target_idx]

        self._apply_spell_text(
            caster,
            target,
            card,
            target_permanent_index=target_permanent_index,
            x_value=x_value,
        )
        caster.graveyard.append(card)
        self.log.append(f"{card.name} resolved and moved to graveyard")

    def _select_executable_instruction(self, card: CardDefinition) -> OracleInstruction | None:
        program = compile_card_oracle(card)
        return next((instruction for instruction in program.instructions if instruction.kind != "spell_pattern"), None)

    def _execute_oracle_instruction(
        self,
        instruction: OracleInstruction,
        context: OracleExecutionContext,
    ) -> tuple[bool, str]:
        caster = context.caster
        target = context.target
        card = context.card
        source_permanent = context.source_permanent
        x_value = context.x_value

        if instruction.kind == "untap_self":
            if source_permanent is None:
                return False, "ability not implemented"
            if not source_permanent.tapped:
                return False, f"{card.name} is already untapped"
            source_permanent.tapped = False
            self.log.append(f"{card.name} untapped itself")
            return True, "resolved"
        target = context.target
        card = context.card
        source_permanent = context.source_permanent
        x_value = context.x_value

        if instruction.kind == "draw_target_cards":
            amount = instruction.payload.get("amount", 0)
            count = max(0, x_value or 0) if amount == "x" else int(amount)
            drawn = target.draw(count)
            self.log.append(f"{target.name} drew {drawn} cards")
            return True, "resolved"

        if instruction.kind == "discard_hand_ante_then_draw_seven":
            while caster.hand:
                caster.graveyard.append(caster.hand.pop(0))
            if caster.library:
                caster.graveyard.append(caster.library.pop(0))
            drawn = caster.draw(7)
            self.log.append(f"{card.name} resolved: discarded hand and drew {drawn} cards")
            return True, "resolved"

        if instruction.kind == "each_player_antes_top_card":
            anted = 0
            for player in self.players:
                if player.library:
                    player.graveyard.append(player.library.pop(0))
                    anted += 1
            self.log.append(f"{card.name} anted {anted} card(s) in simplified model")
            return True, "resolved"

        if instruction.kind == "exchange_ante_with_top_library":
            if caster.library:
                caster.graveyard.append(caster.library.pop(0))
                self.log.append(f"{card.name} exchanged top library card with simulated ante zone")
            else:
                self.log.append(f"{card.name} resolved with no library card to exchange")
            return True, "resolved"

        if instruction.kind == "copy_top_stack_spell":
            if self.stack:
                copied = self.stack[-1]
                self._apply_spell_text(caster, target, copied.card, x_value=copied.x_value)
                self.log.append(f"{card.name} copied {copied.card.name}")
            else:
                self.log.append(f"{card.name} resolved with no spell to copy")
            return True, "resolved"

        if instruction.kind == "balance_resources":
            min_lands = min(sum(1 for perm in player.battlefield if perm.card.primary_type == "land") for player in self.players)
            min_creatures = min(sum(1 for perm in player.battlefield if perm.card.primary_type == "creature") for player in self.players)
            min_hand = min(len(player.hand) for player in self.players)
            for player in self.players:
                lands_kept = 0
                creatures_kept = 0
                survivors: list[Permanent] = []
                for permanent in player.battlefield:
                    if permanent.card.primary_type == "land":
                        if lands_kept < min_lands:
                            lands_kept += 1
                            survivors.append(permanent)
                        else:
                            player.graveyard.append(permanent.card)
                        continue
                    if permanent.card.primary_type == "creature":
                        if creatures_kept < min_creatures:
                            creatures_kept += 1
                            survivors.append(permanent)
                        else:
                            player.graveyard.append(permanent.card)
                        continue
                    survivors.append(permanent)
                player.battlefield = survivors
                while len(player.hand) > min_hand:
                    player.graveyard.append(player.hand.pop(0))
            self.log.append("Balance normalized lands, creatures, and hands")
            return True, "resolved"

        if instruction.kind == "grant_unlimited_blocking":
            blocker = next((perm for perm in target.battlefield if perm.card.primary_type == "creature"), None)
            if blocker is not None:
                blocker.metadata["must_block_all_until_eot"] = True
            self.log.append(f"{card.name} created a forced blocking assignment")
            return True, "resolved"

        if instruction.kind == "randomize_blockers":
            self.log.append(f"{card.name} set up random pile blocking this turn")
            return True, "resolved"

        if instruction.kind == "remove_creature_from_combat":
            removed = next((perm for perm in target.battlefield if perm.card.primary_type == "creature"), None)
            if removed is not None:
                removed.metadata["removed_from_combat"] = True
            self.log.append(f"{card.name} removed a blocker from combat")
            return True, "resolved"

        if instruction.kind == "left_right_combat_division":
            self.log.append(f"{card.name} established left/right combat division")
            return True, "resolved"

        if instruction.kind == "deal_damage":
            amount = instruction.payload.get("amount", 0)
            damage = max(0, x_value or 0) if amount == "x" else int(amount)
            damage = self._prevent_damage(target, damage)
            if damage > 0:
                target.life -= damage
            if source_permanent is not None:
                self.log.append(f"{card.name} dealt {damage} damage")
            else:
                self.log.append(f"{target.name} took {damage} damage")
            return True, "resolved"

        if instruction.kind == "deal_damage_and_self_damage":
            damage = self._prevent_damage(target, int(instruction.payload.get("amount", 0)))
            if damage > 0:
                target.life -= damage
            caster.life -= int(instruction.payload.get("self_damage", 0))
            self.log.append(f"{card.name} dealt {damage} damage and 3 self-damage")
            return True, "resolved"

        if instruction.kind == "reanimate_creature":
            reanimated = self._reanimate_creature_to_battlefield(caster)
            self.log.append("Reanimated creature to battlefield" if reanimated else "No creature to reanimate")
            return True, "resolved"

        if instruction.kind == "bounce_target_creature":
            bounced = self._bounce_target_creature(target)
            self.log.append("Returned creature to hand" if bounced else "No creature to return")
            return True, "resolved"

        if instruction.kind == "prevent_all_combat_damage":
            self.combat_damage_prevented_until_eot = True
            self.log.append("Combat damage prevented until end of turn")
            return True, "resolved"

        if instruction.kind == "wheel_of_fortune":
            for player in self.players:
                while player.hand:
                    player.graveyard.append(player.hand.pop(0))
                player.draw(7)
            self.log.append("Wheel effect resolved for all players")
            return True, "resolved"

        if instruction.kind == "timetwister":
            for player in self.players:
                pool = player.library + player.hand + player.graveyard
                player.library = list(pool)
                player.hand = []
                player.graveyard = []
                player.draw(7)
            self.log.append("Timetwister effect resolved for all players")
            return True, "resolved"

        if instruction.kind == "tutor_top_card":
            if caster.library:
                caster.hand.append(caster.library.pop(0))
            self.log.append(f"{caster.name} tutored a card")
            return True, "resolved"

        if instruction.kind == "grant_extra_turn":
            caster_index = self.players.index(caster)
            self.add_extra_turn(caster_index)
            self.log.append(f"{caster.name} gained an extra turn")
            return True, "resolved"

        if instruction.kind == "reorder_target_library_top":
            top = target.library[:3]
            rest = target.library[3:]
            target.library = list(reversed(top)) + rest
            self.log.append(f"{card.name} reordered top {len(top)} cards of {target.name}'s library")
            return True, "resolved"

        if instruction.kind == "mark_text_modified":
            if target.battlefield:
                target.battlefield[0].metadata["text_modified"] = True
            self.log.append(f"{card.name} applied a text change effect")
            return True, "resolved"

        if instruction.kind == "peek_hand_and_force_play":
            seen = len(target.hand)
            if target.hand:
                played = target.hand.pop(0)
                target.graveyard.append(played)
                self.log.append(f"{card.name} forced {target.name} to play {played.name}")
            else:
                self.log.append(f"{card.name} looked at {target.name}'s hand ({seen} cards)")
            return True, "resolved"

        if instruction.kind == "sacrifice_creature_for_black_mana":
            sacrificed = self._sacrifice_creature_for_mana(caster)
            if sacrificed is not None:
                caster.mana_pool["B"] += int(sacrificed.cmc)
                self.log.append(f"{caster.name} sacrificed {sacrificed.name} for {int(sacrificed.cmc)} black mana")
            else:
                self.log.append(f"{caster.name} had no creature to sacrifice")
            return True, "resolved"

        if instruction.kind == "recolor_target_from_text":
            symbol = str(instruction.payload.get("target_color", ""))
            changed = self._apply_color_override(target, symbol) if symbol else False
            self.log.append("Changed target color" if changed else "No valid permanent to recolor")
            return True, "resolved"

        if instruction.kind == "destroy_all_creatures":
            for player in self.players:
                survivors: list[Permanent] = []
                for permanent in player.battlefield:
                    if permanent.card.primary_type == "creature" and permanent.regeneration_shield > 0:
                        permanent.regeneration_shield -= 1
                        permanent.tapped = True
                        survivors.append(permanent)
                    elif permanent.card.primary_type == "creature":
                        player.graveyard.append(permanent.card)
                    else:
                        survivors.append(permanent)
                player.battlefield = survivors
            self.log.append("All creatures were destroyed")
            return True, "resolved"

        if instruction.kind == "destroy_all_artifacts_creatures_enchantments":
            for player in self.players:
                survivors: list[Permanent] = []
                for permanent in player.battlefield:
                    primary_type = permanent.card.primary_type
                    if primary_type == "creature" and permanent.regeneration_shield > 0:
                        permanent.regeneration_shield -= 1
                        permanent.tapped = True
                        survivors.append(permanent)
                    elif primary_type in {"artifact", "creature", "enchantment"}:
                        player.graveyard.append(permanent.card)
                    else:
                        survivors.append(permanent)
                player.battlefield = survivors
            self.log.append("All artifacts, creatures, and enchantments were destroyed")
            return True, "resolved"

        if instruction.kind == "destroy_all_lands":
            for player in self.players:
                survivors: list[Permanent] = []
                for permanent in player.battlefield:
                    if permanent.card.primary_type == "land":
                        player.graveyard.append(permanent.card)
                    else:
                        survivors.append(permanent)
                player.battlefield = survivors
            self.log.append("All lands were destroyed")
            return True, "resolved"

        if instruction.kind == "destroy_target_permanent":
            destroyed = self._destroy_target_permanent(
                target,
                type_filter=instruction.payload.get("type_filter"),
                color_filter=instruction.payload.get("color_filter"),
                target_permanent_index=context.target_permanent_index,
            )
            if destroyed:
                if source_permanent is not None:
                    self.log.append(f"{card.name} destroyed {destroyed.name}")
                else:
                    self.log.append(f"Destroyed {destroyed.name}")
            else:
                self.log.append("No valid target permanent found")
            return True, "resolved"

        if instruction.kind == "return_creature_from_graveyard_to_hand":
            returned = self._return_creature_from_graveyard(caster)
            self.log.append("Returned creature from graveyard" if returned else "No creature to return")
            return True, "resolved"

        if instruction.kind == "discard_target_cards":
            actual = min(int(instruction.payload.get("amount", 0)), len(target.hand))
            for _ in range(actual):
                discarded = target.hand.pop(0)
                target.graveyard.append(discarded)
            self.log.append(f"{target.name} discarded {actual} cards")
            return True, "resolved"

        if instruction.kind == "target_loses_life":
            amount = int(instruction.payload.get("amount", 0))
            before = target.life
            target.life -= amount
            self.log.append(f"{card.name}: {target.name} lost {amount} life ({before} -> {target.life})")
            return True, "resolved"

        if instruction.kind == "target_gains_life":
            amount = instruction.payload.get("amount", 0)
            life_gain = max(0, x_value or 0) if amount == "x" else int(amount)
            before = target.life
            target.life += life_gain
            self.log.append(f"{card.name}: {target.name} gained {life_gain} life ({before} -> {target.life})")
            return True, "resolved"

        if instruction.kind == "untap_target_land":
            untapped = False
            for perm in target.battlefield:
                if perm.card.primary_type == "land":
                    perm.tapped = False
                    untapped = True
                    break
            self.log.append("Untapped target land" if untapped else "No land to untap")
            return True, "resolved"

        if instruction.kind == "untap_target_permanent":
            untapped = self._tap_or_untap_target(target, make_tapped=False)
            self.log.append("Untapped target permanent" if untapped else "No valid permanent to untap")
            return True, "resolved"

        if instruction.kind == "tap_target_permanent":
            tapped = self._tap_or_untap_target(target, make_tapped=True)
            self.log.append("Tapped target permanent" if tapped else "No valid permanent to tap")
            return True, "resolved"

        if instruction.kind == "grant_prevention_shield":
            amount = int(instruction.payload.get("amount", 0))
            recipient = target if source_permanent is not None else caster
            recipient.damage_prevention_pool += amount
            if source_permanent is not None and instruction.payload.get("protection_kind") == "color":
                self.log.append("Color protection shield granted")
            elif source_permanent is not None:
                self.log.append("Prevention shield granted by activated ability")
            else:
                self.log.append(f"{caster.name} gains prevention shield for {amount} damage")
            return True, "resolved"

        if instruction.kind == "grant_forcefield_shield":
            caster.combat_damage_cap_one_charges += 1
            self.log.append("Forcefield shield granted")
            return True, "resolved"

        if instruction.kind == "grant_regeneration_to_target_creature":
            regenerated = self._grant_regeneration_shield(target)
            self.log.append("Regeneration shield granted" if regenerated else "No valid creature to regenerate")
            return True, "resolved"

        if instruction.kind == "grant_regeneration_to_self":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.regeneration_shield += 1
            self.log.append(f"{card.name} gains regeneration shield")
            return True, "resolved"

        if instruction.kind == "pump_self":
            if source_permanent is None:
                return False, "ability not implemented"
            power_delta = int(instruction.payload.get("power", 0))
            toughness_delta = int(instruction.payload.get("toughness", 0))
            source_permanent.power_bonus += power_delta
            source_permanent.toughness_bonus += toughness_delta
            source_permanent.metadata["temporary_power_bonus_until_eot"] = int(
                source_permanent.metadata.get("temporary_power_bonus_until_eot", 0)
            ) + power_delta
            source_permanent.metadata["temporary_toughness_bonus_until_eot"] = int(
                source_permanent.metadata.get("temporary_toughness_bonus_until_eot", 0)
            ) + toughness_delta
            self.log.append(
                f"{card.name} gets +{int(instruction.payload.get('power', 0))}/+{int(instruction.payload.get('toughness', 0))} until end of turn"
            )
            return True, "resolved"

        if instruction.kind == "grant_self_flying_until_eot":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.metadata["gains_flying_until_eot"] = True
            self.log.append(f"{card.name} gains flying until end of turn")
            return True, "resolved"

        if instruction.kind == "grant_banding_to_target":
            target_creature = next((perm for perm in target.battlefield if perm.card.primary_type == "creature"), None)
            if target_creature is None:
                self.log.append("No valid creature target for banding effect")
                return False, "no valid creature target for banding effect"
            target_creature.metadata["gains_banding_until_eot"] = True
            self.log.append(f"{target_creature.card.name} gains banding until end of turn")
            return True, "resolved"

        if instruction.kind == "add_counter_to_self":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.power_bonus += int(instruction.payload.get("power", 0))
            source_permanent.toughness_bonus += int(instruction.payload.get("toughness", 0))
            self.log.append(f"{card.name} gets a +1/+1 counter")
            return True, "resolved"

        if instruction.kind == "sacrifice_self_for_mana":
            if source_permanent is None:
                return False, "ability not implemented"
            caster.mana_pool[str(instruction.payload.get("color", "G"))] += int(instruction.payload.get("amount", 0))
            caster.graveyard.append(source_permanent.card)
            caster.battlefield = [perm for perm in caster.battlefield if perm is not source_permanent]
            self.log.append(f"{card.name} sacrificed for mana")
            return True, "resolved"

        if instruction.kind == "draw_controller_cards":
            drawn = caster.draw(int(instruction.payload.get("amount", 0)))
            self.log.append(f"{card.name} drew {drawn} card")
            return True, "resolved"

        if instruction.kind == "grant_unblockable_to_low_power_target":
            target_creature = next(
                (perm for perm in target.battlefield if perm.card.primary_type == "creature" and perm.effective_power <= 2),
                None,
            )
            if target_creature is not None:
                target_creature.metadata["cant_be_blocked_until_eot"] = True
                self.log.append(f"{target_creature.card.name} can't be blocked this turn")
            else:
                self.log.append("No valid low-power creature for unblockable effect")
            return True, "resolved"

        if instruction.kind == "change_target_land_type":
            target_land = next((perm for perm in target.battlefield if perm.card.primary_type == "land"), None)
            if target_land is not None:
                target_land.metadata["land_type_override"] = str(instruction.payload.get("land_type", "forest"))
                self.log.append(f"{target_land.card.name} became a Forest")
            else:
                self.log.append("No target land for Forest effect")
            return True, "resolved"

        if instruction.kind == "mark_non_wall_target_to_attack":
            target_creature = next(
                (
                    perm
                    for perm in target.battlefield
                    if perm.card.primary_type == "creature" and "wall" not in perm.card.type_line.lower()
                ),
                None,
            )
            if target_creature is not None:
                target_creature.metadata["must_attack_until_eot"] = True
                target_creature.metadata["destroy_if_did_not_attack_eot"] = True
                self.log.append(f"{target_creature.card.name} marked to attack this turn")
            else:
                self.log.append("No non-Wall target for Nettling Imp effect")
            return True, "resolved"

        if instruction.kind == "grant_flying_and_delayed_destruction":
            if source_permanent is None:
                return False, "ability not implemented"
            target_creature = next(
                (
                    perm
                    for perm in caster.battlefield
                    if perm.card.primary_type == "creature" and perm.effective_toughness < source_permanent.effective_power
                ),
                None,
            )
            if target_creature is not None:
                target_creature.metadata["gains_flying_until_eot"] = True
                target_creature.metadata["destroy_at_next_end_step"] = True
                self.log.append(f"{target_creature.card.name} gains temporary flying and delayed destruction")
            else:
                self.log.append("No valid target for Stone Giant effect")
            return True, "resolved"

        if instruction.kind == "redirect_one_damage_to_owner":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.metadata["redirect_one_damage_to_owner_until_eot"] = int(
                source_permanent.metadata.get("redirect_one_damage_to_owner_until_eot", 0)
            ) + 1
            self.log.append(f"{card.name} will redirect next 1 damage to its owner")
            return True, "resolved"

        if instruction.kind == "animate_self_until_end_of_combat":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.metadata["absolute_power"] = int(instruction.payload.get("power", 0))
            source_permanent.metadata["absolute_toughness"] = int(instruction.payload.get("toughness", 0))
            source_permanent.metadata["animate_until_end_of_combat"] = True
            self.log.append(f"{card.name} is animated until end of combat")
            return True, "resolved"

        if instruction.kind == "create_wasp_token":
            controller_index = self.players.index(caster)
            wasp = CardDefinition(
                name="Wasp",
                mana_cost="",
                cmc=0.0,
                type_line="Artifact Creature — Insect",
                oracle_text="Flying",
                colors=(),
                color_identity=(),
                keywords=("Flying",),
                produced_mana=(),
                raw={"name": "Wasp", "type_line": "Artifact Creature — Insect", "power": "1", "toughness": "1"},
            )
            self._put_permanent_onto_battlefield(controller_index, Permanent(card=wasp), None)
            self.log.append(f"{card.name} created a Wasp token")
            return True, "resolved"

        if instruction.kind == "look_at_target_hand":
            seen = len(target.hand)
            self.log.append(f"{card.name} looked at {target.name}'s hand ({seen} cards)")
            return True, "resolved"

        if instruction.kind == "add_mire_counter_to_target_land":
            target_land = next(
                (
                    perm
                    for perm in target.battlefield
                    if perm.card.primary_type == "land"
                    and "swamp" not in perm.card.type_line.lower()
                ),
                None,
            )
            if target_land is not None:
                target_land.metadata["land_type_override"] = "swamp"
                target_land.metadata["mire_counter"] = True
                self.log.append(f"{target_land.card.name} became a Swamp due to mire counter")
            else:
                self.log.append("No valid non-Swamp land for mire counter")
            return True, "resolved"

        if instruction.kind == "add_mana_from_text":
            self._add_mana_from_text(
                caster,
                str(instruction.payload.get("oracle_text", card.oracle_text)),
                preferred_color=str(instruction.payload.get("color", "")) or None,
            )
            self.log.append(f"{card.name} produced mana")
            return True, "resolved"

        if instruction.kind == "counter_top_stack_spell":
            if self.stack:
                countered = self.stack.pop()
                self.players[countered.caster_index].graveyard.append(countered.card)
                self.log.append(f"{card.name} countered {countered.card.name}")
            else:
                self.log.append(f"{card.name} resolved with no spell to counter")
            return True, "resolved"

        self.log.append(f"Resolved supported pattern for {card.name} without state mutation")
        return True, "resolved"

    def _apply_spell_text(
        self,
        caster: PlayerState,
        target: PlayerState,
        card: CardDefinition,
        target_permanent_index: int | None = None,
        x_value: int | None = None,
    ) -> None:
        instruction = self._select_executable_instruction(card)
        if instruction is None:
            self.log.append(f"Resolved supported pattern for {card.name} without state mutation")
            return

        state_machine = OracleStateMachine(
            self,
            OracleExecutionContext(
                caster=caster,
                target=target,
                card=card,
                target_permanent_index=target_permanent_index,
                x_value=x_value,
            ),
        )
        state_machine.run(instruction)

    def _destroy_target_permanent(
        self,
        target: PlayerState,
        type_filter: str | None = None,
        color_filter: str | None = None,
        target_permanent_index: int | None = None,
    ) -> CardDefinition | None:
        if target_permanent_index is not None:
            if 0 <= target_permanent_index < len(target.battlefield):
                permanent = target.battlefield[target_permanent_index]
                if type_filter and permanent.card.primary_type != type_filter:
                    return None
                if color_filter and color_filter not in permanent.card.colors:
                    return None
                removed = target.battlefield.pop(target_permanent_index)
                target.graveyard.append(removed.card)
                return removed.card
            return None

        for idx, permanent in enumerate(target.battlefield):
            if type_filter and permanent.card.primary_type != type_filter:
                continue
            if color_filter and color_filter not in permanent.card.colors:
                continue
            removed = target.battlefield.pop(idx)
            target.graveyard.append(removed.card)
            return removed.card

        return None

    def _tap_or_untap_target(self, target: PlayerState, make_tapped: bool) -> bool:
        for permanent in target.battlefield:
            permanent.tapped = make_tapped
            return True
        return False

    def _grant_regeneration_shield(self, target: PlayerState) -> bool:
        for permanent in target.battlefield:
            if permanent.card.primary_type == "creature":
                permanent.regeneration_shield += 1
                return True
        return False

    def _prevent_damage(self, target: PlayerState, damage: int) -> int:
        if damage > 1 and target.combat_damage_cap_one_charges > 0:
            target.combat_damage_cap_one_charges -= 1
            damage = 1
        if damage <= 0 or target.damage_prevention_pool <= 0:
            return damage
        prevented = min(damage, target.damage_prevention_pool)
        target.damage_prevention_pool -= prevented
        return damage - prevented

    def _add_mana_from_text(self, controller: PlayerState, text: str, preferred_color: str | None = None) -> None:
        # Prefer lexing the oracle text for mana symbols
        try:
            tokens = lex_oracle_text(text)
        except Exception:
            tokens = ()

        mana_tokens = [t.value for t in tokens if t.kind == "mana"]
        if mana_tokens:
            for raw in mana_tokens:
                sym = raw.strip("{}")
                if sym in {"W", "U", "B", "R", "G", "C"}:
                    controller.mana_pool[sym] += 1
            return

        normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if "one mana of any color" in normalized:
            selected_color = self._normalize_mana_color(preferred_color) or "G"
            controller.mana_pool[selected_color] += 1

    def _return_creature_from_graveyard(self, caster: PlayerState) -> bool:
        for idx, card in enumerate(caster.graveyard):
            if card.primary_type == "creature":
                caster.hand.append(caster.graveyard.pop(idx))
                return True
        return False

    def _reanimate_creature_to_battlefield(self, caster: PlayerState) -> bool:
        for idx, card in enumerate(caster.graveyard):
            if card.primary_type == "creature":
                revived = caster.graveyard.pop(idx)
                controller_index = self.players.index(caster)
                self._put_permanent_onto_battlefield(controller_index, Permanent(card=revived), None)
                return True
        return False

    def _bounce_target_creature(self, target: PlayerState) -> bool:
        for idx, permanent in enumerate(target.battlefield):
            if permanent.card.primary_type == "creature":
                target.hand.append(permanent.card)
                target.battlefield.pop(idx)
                return True
        return False

    def _sacrifice_creature_for_mana(self, caster: PlayerState) -> CardDefinition | None:
        for idx, permanent in enumerate(caster.battlefield):
            if permanent.card.primary_type == "creature":
                removed = caster.battlefield.pop(idx)
                caster.graveyard.append(removed.card)
                return removed.card
        return None

    def _apply_color_override(self, target: PlayerState, symbol: str) -> bool:
        """Apply a colour override to the first permanent on *target*'s battlefield."""
        if not symbol:
            return False
        if target.battlefield:
            target.battlefield[0].metadata["color_override"] = symbol
            return True
        return False

    def clear_mana_pools(self) -> None:
        for player in self.players:
            for symbol in _MANA_SYMBOLS:
                player.mana_pool[symbol] = 0

    def resolve_upkeep(self, player_index: int) -> None:
        phase = "beginning"
        step = "upkeep"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        for controller in self.players:
            for permanent in controller.battlefield:
                program = compile_card_oracle(permanent.card)
                for trig in program.triggered_abilities:
                    if trig.instruction is None:
                        continue
                    kind = trig.instruction.kind
                    cond = trig.condition.kind

                    if cond == "upkeep_self" and kind == "upkeep_pay_or_sacrifice_enchantment":
                        mana: dict[str, int] = trig.instruction.payload.get("mana", {})
                        paid = True
                        for sym, count in mana.items():
                            if sym == "generic":
                                continue
                            if controller.mana_pool.get(sym, 0) < count:
                                paid = False
                                break
                        if paid:
                            for sym, count in mana.items():
                                if sym != "generic":
                                    controller.mana_pool[sym] = controller.mana_pool.get(sym, 0) - count
                            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
                        else:
                            controller.battlefield = [p for p in controller.battlefield if p is not permanent]
                            controller.graveyard.append(permanent.card)
                            self.log.append(f"{controller.name} sacrificed {permanent.card.name} on upkeep")
                        break

                    if cond == "upkeep_chosen" and kind == "upkeep_chosen_player_hand_overflow_damage":
                        chosen = permanent.metadata.get("chosen_player_index")
                        if chosen != player_index:
                            break
                        victim = self.players[player_index]
                        damage = max(0, len(victim.hand) - 4)
                        if damage > 0:
                            damage = self._prevent_damage(victim, damage)
                            if damage > 0:
                                victim.life -= damage
                        self.log.append(f"{permanent.card.name} dealt {damage} upkeep damage")
                        break

                    if cond == "upkeep_self" and kind == "upkeep_pay_or_deal_damage_to_controller":
                        mana = trig.instruction.payload.get("mana", {})
                        damage_amt = int(trig.instruction.payload.get("damage", 0))
                        paid = all(
                            controller.mana_pool.get(sym, 0) >= count
                            for sym, count in mana.items()
                            if sym != "generic"
                        )
                        if paid:
                            for sym, count in mana.items():
                                if sym != "generic":
                                    controller.mana_pool[sym] = controller.mana_pool.get(sym, 0) - count
                            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
                        else:
                            controller.life -= damage_amt
                            self.log.append(f"{permanent.card.name} dealt {damage_amt} upkeep damage to {controller.name}")
                        break

                    if cond == "upkeep_self" and kind == "upkeep_pay_or_tap_and_sacrifice_opponent_land":
                        mana = trig.instruction.payload.get("mana", {})
                        paid = all(
                            controller.mana_pool.get(sym, 0) >= count
                            for sym, count in mana.items()
                            if sym != "generic"
                        )
                        if paid:
                            for sym, count in mana.items():
                                if sym != "generic":
                                    controller.mana_pool[sym] = controller.mana_pool.get(sym, 0) - count
                            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
                        else:
                            permanent.tapped = True
                            opponent = next((p for p in self.players if p is not controller), None)
                            if opponent is not None:
                                for idx, land in enumerate(opponent.battlefield):
                                    if land.card.primary_type == "land":
                                        removed = opponent.battlefield.pop(idx)
                                        opponent.graveyard.append(removed.card)
                                        self.log.append(f"{permanent.card.name} forced sacrifice of {removed.card.name}")
                                        break
                        break

                    if cond == "upkeep_self" and kind == "upkeep_sacrifice_other_creature_or_deal_damage":
                        other_idx = next(
                            (
                                i
                                for i, perm in enumerate(controller.battlefield)
                                if perm is not permanent and perm.card.primary_type == "creature"
                            ),
                            None,
                        )
                        if other_idx is not None:
                            sacrificed = controller.battlefield.pop(other_idx)
                            controller.graveyard.append(sacrificed.card)
                            self.log.append(f"{controller.name} sacrificed {sacrificed.card.name} for {permanent.card.name}")
                        else:
                            alt_damage = int(trig.instruction.payload.get("damage", 0))
                            controller.life -= alt_damage
                            self.log.append(f"{permanent.card.name} dealt {alt_damage} upkeep damage to {controller.name}")
                        break

                    if cond == "upkeep_self" and kind == "upkeep_pay_or_sacrifice_self":
                        mana = trig.instruction.payload.get("mana", {})
                        paid = all(
                            controller.mana_pool.get(sym, 0) >= count
                            for sym, count in mana.items()
                            if sym != "generic"
                        )
                        if paid:
                            for sym, count in mana.items():
                                if sym != "generic":
                                    controller.mana_pool[sym] = controller.mana_pool.get(sym, 0) - count
                            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
                        else:
                            controller.battlefield = [p for p in controller.battlefield if p is not permanent]
                            controller.graveyard.append(permanent.card)
                            self.log.append(f"{controller.name} sacrificed {permanent.card.name} on upkeep")
                        break

                    if cond == "no_islands" and kind == "sacrifice_self":
                        has_island = any(
                            perm.card.primary_type == "land"
                            and (
                                "island" in perm.card.type_line.lower()
                                or perm.metadata.get("land_type_override") == "island"
                            )
                            for perm in controller.battlefield
                        )
                        if not has_island:
                            controller.battlefield = [p for p in controller.battlefield if p is not permanent]
                            controller.graveyard.append(permanent.card)
                            self.log.append(f"{controller.name} sacrificed {permanent.card.name} for lacking an Island")
                        break

        if self._receives_priority(step):
            self._resolve_priority_window()
        self._on_step_or_phase_end(phase, step)

    def resolve_end_step(self, player_index: int) -> None:
        phase = "ending"
        step = "end"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        destroyed_names: list[str] = []
        for controller in self.players:
            survivors: list[Permanent] = []
            for permanent in controller.battlefield:
                if permanent.metadata.get("destroy_at_next_end_step"):
                    controller.graveyard.append(permanent.card)
                    destroyed_names.append(permanent.card.name)
                else:
                    survivors.append(permanent)
            controller.battlefield = survivors

        for name in destroyed_names:
            self.log.append(f"{name} was destroyed at end step")
        if self._receives_priority(step):
            self.start_priority_window(self.active_player_index)

    def close_end_step(self) -> None:
        if self.current_turn_phase != "ending" or self.current_step != "end":
            return
        if self._receives_priority(self.current_step):
            self.clear_priority_window()
        self._on_step_or_phase_end("ending", "end")

    def resolve_cleanup_step(
        self,
        player_index: int,
        discard_hand_indices: list[int] | None = None,
        defer_discard_selection: bool = False,
    ) -> bool:
        phase = "ending"
        step = "cleanup"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)

        active_player = self.players[player_index]
        cleanup_completed = True
        if not active_player.has_no_max_hand_size:
            max_hand_size = 7
            excess = max(0, len(active_player.hand) - max_hand_size)
            if excess:
                if discard_hand_indices is not None:
                    unique_indices = sorted(set(discard_hand_indices))
                    if len(unique_indices) != excess:
                        raise ValueError(f"expected {excess} cleanup discards, got {len(unique_indices)}")
                    if any(index < 0 or index >= len(active_player.hand) for index in unique_indices):
                        raise ValueError("cleanup discard index out of range")
                    for hand_index in sorted(unique_indices, reverse=True):
                        discarded = active_player.hand.pop(hand_index)
                        active_player.graveyard.append(discarded)
                    self.log.append(f"{active_player.name} discarded {excess} card(s) in cleanup")
                elif defer_discard_selection:
                    cleanup_completed = False
                else:
                    for _ in range(excess):
                        discarded = active_player.hand.pop(0)
                        active_player.graveyard.append(discarded)
                    self.log.append(f"{active_player.name} discarded {excess} card(s) in cleanup")

        self.combat_damage_prevented_until_eot = False
        for player in self.players:
            player.damage_prevention_pool = 0
            player.combat_damage_cap_one_charges = 0
            for permanent in player.battlefield:
                permanent.damage_marked = 0
                temp_power = int(permanent.metadata.pop("temporary_power_bonus_until_eot", 0))
                temp_toughness = int(permanent.metadata.pop("temporary_toughness_bonus_until_eot", 0))
                if temp_power:
                    permanent.power_bonus -= temp_power
                if temp_toughness:
                    permanent.toughness_bonus -= temp_toughness
                for key in _EOT_METADATA_KEYS:
                    permanent.metadata.pop(key, None)
        self._reset_combat_state(clear_damage_marked=False)
        self._on_step_or_phase_end(phase, step)
        return cleanup_completed

    def _initialize_permanent_state(
        self,
        permanent: Permanent,
        caster_index: int,
        target_player_index: int | None,
    ) -> None:
        if permanent.card.primary_type == "creature":
            permanent.metadata["summoning_sickness_turn"] = self.turn
        program = compile_card_oracle(permanent.card)
        text = program.normalized_text

        # enters tapped (static creature/permanent lines or normalized text)
        if any(line for line in program.static_lines if "enters tapped" in line) or (
            "enters tapped" in text and "unless" not in text
        ):
            permanent.tapped = True

        # choose opponent on enter
        if "as this artifact enters, choose an opponent" in text:
            chosen = target_player_index if target_player_index is not None else (1 - caster_index)
            permanent.metadata["chosen_player_index"] = chosen

        # enters with fixed counters
        if any("enters with seven +1/+0 counters on it" == line for line in program.static_lines) or "enters with seven +1/+0 counters on it" in text:
            permanent.power_bonus += 7

        # enters with X +1/+1 counters
        if any("enters with x +1/+1 counters on it" == line for line in program.static_lines) or "enters with x +1/+1 counters on it" in text:
            x_value = permanent.metadata.get("cast_x_value")
            if isinstance(x_value, int) and x_value > 0:
                permanent.power_bonus += x_value
                permanent.toughness_bonus += x_value

        # copy-as-enter creature
        if any("you may have this creature enter as a copy of any creature on the battlefield" == line for line in program.static_lines) or "you may have this creature enter as a copy of any creature on the battlefield" in text:
            source = next(
                (
                    perm
                    for player in self.players
                    for perm in player.battlefield
                    if perm is not permanent and perm.card.primary_type == "creature"
                ),
                None,
            )
            if source is not None:
                permanent.metadata["copied_from"] = source.card.name
                permanent.metadata["absolute_power"] = source.effective_power
                permanent.metadata["absolute_toughness"] = source.effective_toughness

        # copy-as-enter enchantment
        if "you may have this enchantment enter as a copy of any artifact on the battlefield" in text:
            source = next(
                (
                    perm
                    for player in self.players
                    for perm in player.battlefield
                    if perm is not permanent and perm.card.primary_type == "artifact"
                ),
                None,
            )
            if source is not None:
                permanent.metadata["copied_from"] = source.card.name
                if "power" in source.card.raw and str(source.card.raw.get("power", "")).isdigit():
                    permanent.metadata["absolute_power"] = source.effective_power
                if "toughness" in source.card.raw and str(source.card.raw.get("toughness", "")).isdigit():
                    permanent.metadata["absolute_toughness"] = source.effective_toughness

        if any(instr.kind == "spell_pattern" and instr.value == "you have no maximum hand size" for instr in program.instructions) or "you have no maximum hand size" in text:
            self.players[caster_index].has_no_max_hand_size = True

        if "you may spend white mana as though it were red mana" in text:
            self.players[caster_index].can_spend_white_as_red = True

    def _apply_cast_triggers(self, caster_index: int, card: CardDefinition) -> None:
        if card.primary_type != "enchantment":
            return

        caster = self.players[caster_index]
        for permanent in caster.battlefield:
            if permanent.card.name == "Verduran Enchantress":
                drawn = caster.draw(1)
                self.log.append(f"Verduran Enchantress trigger: {caster.name} drew {drawn} card")

    def _refresh_dynamic_creatures(self) -> None:
        all_permanents = [perm for player in self.players for perm in player.battlefield]
        kormus_active = any(perm.card.name == "Kormus Bell" for perm in all_permanents)
        living_lands_active = any(perm.card.name == "Living Lands" for perm in all_permanents)

        for player in self.players:
            non_wall_creatures = sum(
                1
                for perm in player.battlefield
                if perm.card.primary_type == "creature" and "wall" not in perm.card.type_line.lower()
            )
            swamp_count = sum(
                1
                for perm in player.battlefield
                if "swamp" in perm.card.type_line.lower() or perm.metadata.get("land_type_override") == "swamp"
            )
            plague_rats_total = sum(
                1 for p in self.players for perm in p.battlefield if perm.card.name == "Plague Rats"
            )

            for permanent in player.battlefield:
                prog = compile_card_oracle(permanent.card)
                instr_kinds = {instr.kind for instr in prog.instructions}

                if "dynamic_pt_non_wall_creatures" in instr_kinds:
                    permanent.metadata["absolute_power"] = non_wall_creatures
                    permanent.metadata["absolute_toughness"] = non_wall_creatures

                if "dynamic_pt_plague_rats" in instr_kinds:
                    permanent.metadata["absolute_power"] = plague_rats_total
                    permanent.metadata["absolute_toughness"] = plague_rats_total

                if "dynamic_pt_swamps" in instr_kinds:
                    permanent.metadata["absolute_power"] = swamp_count
                    permanent.metadata["absolute_toughness"] = swamp_count

                if "conditional_swamp_bonus" in instr_kinds:
                    previous = int(permanent.metadata.get("conditional_swamp_bonus", 0))
                    if previous:
                        permanent.power_bonus -= previous
                        permanent.toughness_bonus -= previous
                    current = 1 if swamp_count > 0 else 0
                    if current:
                        permanent.power_bonus += current
                        permanent.toughness_bonus += current
                    permanent.metadata["conditional_swamp_bonus"] = current

                if kormus_active and "swamp" in permanent.card.type_line.lower() and permanent.card.primary_type == "land":
                    permanent.metadata["land_animated"] = True
                    permanent.metadata["absolute_power"] = 1
                    permanent.metadata["absolute_toughness"] = 1
                    permanent.metadata["color_override"] = "B"

                if living_lands_active and "forest" in permanent.card.type_line.lower() and permanent.card.primary_type == "land":
                    permanent.metadata["land_animated"] = True
                    permanent.metadata["absolute_power"] = 1
                    permanent.metadata["absolute_toughness"] = 1

    def _has_keyword(self, permanent: Permanent, keyword: str) -> bool:
        lower_keyword = keyword.lower()
        if any(item.lower() == lower_keyword for item in permanent.card.keywords):
            return True
        if lower_keyword == "flying" and permanent.metadata.get("gains_flying_until_eot", False):
            return True
        # Fall back to oracle program static lines (e.g. test cards that put keyword in oracle_text)
        program = compile_card_oracle(permanent.card)
        return any(
            i.kind in ("keyword_line", "static_line") and lower_keyword in i.value
            for i in program.instructions
        )

    def _reset_combat_state(self, clear_damage_marked: bool) -> None:
        self.combat_attackers = {}
        self.combat_blockers = {}
        self.combat_defending_player_index = None
        self.combat_damage_resolved = False
        self.combat_first_strike_done = False
        self.combat_attackers_locked = False
        self.combat_blockers_locked = False
        for player in self.players:
            for permanent in player.battlefield:
                permanent.attacking = False
                permanent.defending_player_index = None
                permanent.blocked = False
                permanent.blocking_attacker_controller = None
                permanent.blocking_attacker_index = None
                if clear_damage_marked:
                    permanent.damage_marked = 0

    def _prune_combat_state(self) -> None:
        if self.active_player_index < 0 or self.active_player_index >= len(self.players):
            self._reset_combat_state(clear_damage_marked=False)
            return
        active = self.players[self.active_player_index]
        if self.combat_defending_player_index is None:
            if self.combat_attackers or self.combat_blockers:
                self._reset_combat_state(clear_damage_marked=False)
            return
        if self.combat_defending_player_index < 0 or self.combat_defending_player_index >= len(self.players):
            self._reset_combat_state(clear_damage_marked=False)
            return
        defender = self.players[self.combat_defending_player_index]

        valid_attackers: dict[int, int] = {}
        for attacker_idx, defending_idx in self.combat_attackers.items():
            if defending_idx != self.combat_defending_player_index:
                continue
            if attacker_idx < 0 or attacker_idx >= len(active.battlefield):
                continue
            attacker = active.battlefield[attacker_idx]
            if attacker.card.primary_type != "creature":
                continue
            valid_attackers[attacker_idx] = defending_idx
        self.combat_attackers = valid_attackers

        valid_blockers: dict[int, int] = {}
        for blocker_idx, attacker_idx in self.combat_blockers.items():
            if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                continue
            blocker = defender.battlefield[blocker_idx]
            if blocker.card.primary_type != "creature":
                continue
            if attacker_idx not in self.combat_attackers:
                continue
            valid_blockers[blocker_idx] = attacker_idx
        self.combat_blockers = valid_blockers

        for player in self.players:
            for permanent in player.battlefield:
                permanent.attacking = False
                permanent.defending_player_index = None
                permanent.blocked = False
                permanent.blocking_attacker_controller = None
                permanent.blocking_attacker_index = None

        for attacker_idx, defending_idx in self.combat_attackers.items():
            attacker = active.battlefield[attacker_idx]
            attacker.attacking = True
            attacker.defending_player_index = defending_idx
            attacker.blocked = any(value == attacker_idx for value in self.combat_blockers.values())

        for blocker_idx, attacker_idx in self.combat_blockers.items():
            blocker = defender.battlefield[blocker_idx]
            blocker.blocking_attacker_controller = self.active_player_index
            blocker.blocking_attacker_index = attacker_idx

    def _can_block_attacker(self, blocker: Permanent, attacker: Permanent) -> bool:
        if attacker.metadata.get("cant_be_blocked_until_eot"):
            return False

        attacker_program = compile_card_oracle(attacker.card)
        attacker_kinds = {i.kind for i in attacker_program.instructions}

        if "cant_be_blocked" in attacker_kinds:
            return False

        attacker_has_flying = self._has_keyword(attacker, "flying")
        blocker_has_flying = self._has_keyword(blocker, "flying")
        blocker_has_reach = self._has_keyword(blocker, "reach")
        if attacker_has_flying and not (blocker_has_flying or blocker_has_reach):
            return False

        if "cant_be_blocked_by_walls" in attacker_kinds and "wall" in blocker.card.type_line.lower():
            return False
        return True

    def _destroy_marked_creatures(self) -> None:
        for player in self.players:
            survivors: list[Permanent] = []
            for permanent in player.battlefield:
                if permanent.card.primary_type != "creature":
                    survivors.append(permanent)
                    continue
                if permanent.damage_marked < permanent.effective_toughness:
                    survivors.append(permanent)
                    continue
                if permanent.regeneration_shield > 0:
                    permanent.regeneration_shield -= 1
                    permanent.damage_marked = 0
                    permanent.tapped = True
                    survivors.append(permanent)
                    continue
                player.graveyard.append(permanent.card)
                self.log.append(f"{permanent.card.name} died from combat damage")
            player.battlefield = survivors

    def declare_attackers(
        self,
        controller_index: int,
        attacker_indices: list[int],
        defending_player_index: int | None = None,
    ) -> tuple[bool, str]:
        if self.current_turn_phase != "combat" or self.current_step != "declare_attackers":
            return False, "attackers can only be declared during declare_attackers"
        if controller_index != self.active_player_index:
            return False, "only the active player may declare attackers"

        defender_idx = defending_player_index if defending_player_index is not None else 1 - controller_index
        if defender_idx < 0 or defender_idx >= len(self.players) or defender_idx == controller_index:
            return False, "invalid defending player"

        controller = self.players[controller_index]
        unique_indices = sorted(set(attacker_indices))
        required_attackers: list[str] = []
        for idx, attacker in enumerate(controller.battlefield):
            if attacker.card.primary_type != "creature" or attacker.tapped:
                continue
            if idx in unique_indices:
                continue
            if self.can_attack(attacker, defender_idx) and self._must_attack_if_able(attacker):
                required_attackers.append(attacker.card.name)
        if required_attackers:
            if len(required_attackers) == 1:
                return False, f"{required_attackers[0]} must attack if able"
            names = ", ".join(required_attackers)
            return False, f"{names} must attack if able"

        for idx in unique_indices:
            if idx < 0 or idx >= len(controller.battlefield):
                return False, "attacker index out of range"
            attacker = controller.battlefield[idx]
            if attacker.card.primary_type != "creature":
                return False, "only creatures can attack"
            if attacker.tapped:
                return False, f"{attacker.card.name} is tapped"
            if not self.can_attack(attacker, defender_idx):
                return False, f"{attacker.card.name} cannot attack"

        self.combat_defending_player_index = defender_idx
        self.combat_attackers = {idx: defender_idx for idx in unique_indices}
        self.combat_blockers = {}
        self.combat_damage_resolved = False
        self.combat_first_strike_done = False
        self.combat_attackers_locked = True
        self.combat_blockers_locked = False
        self._prune_combat_state()

        for idx in unique_indices:
            attacker = controller.battlefield[idx]
            attacker.tapped = True

        self._prune_combat_state()
        self.log.append(f"{controller.name} declared {len(unique_indices)} attacker(s)")
        return True, "declared attackers"

    def declare_blockers(self, controller_index: int, blocker_to_attacker: dict[int, int]) -> tuple[bool, str]:
        if self.current_turn_phase != "combat" or self.current_step != "declare_blockers":
            return False, "blockers can only be declared during declare_blockers"
        if self.combat_defending_player_index is None:
            return False, "no defending player set"
        if controller_index != self.combat_defending_player_index:
            return False, "only defending player may declare blockers"

        self._prune_combat_state()
        defender = self.players[controller_index]
        attacker_controller = self.players[self.active_player_index]
        assignments: dict[int, int] = {}

        for blocker_idx, attacker_idx in blocker_to_attacker.items():
            if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                return False, "blocker index out of range"
            if attacker_idx not in self.combat_attackers:
                return False, "blocker assigned to non-attacker"
            blocker = defender.battlefield[blocker_idx]
            attacker = attacker_controller.battlefield[attacker_idx]
            if blocker.card.primary_type != "creature":
                return False, "only creatures can block"
            if blocker.tapped:
                return False, f"{blocker.card.name} is tapped"
            if not self._can_block_attacker(blocker, attacker):
                return False, f"{blocker.card.name} cannot block {attacker.card.name}"
            assignments[blocker_idx] = attacker_idx

        self.combat_blockers = assignments
        self.combat_blockers_locked = True
        self._prune_combat_state()
        self.log.append(f"{defender.name} declared {len(assignments)} blocker(s)")
        return True, "declared blockers"

    def _combat_blockers_for_attacker(self, attacker_idx: int) -> list[int]:
        return [blocker_idx for blocker_idx, a_idx in self.combat_blockers.items() if a_idx == attacker_idx]

    def _needs_manual_damage_assignment(self) -> bool:
        """Return True when any blocked attacker has 2+ blockers, requiring player input."""
        for attacker_idx in self.combat_attackers:
            if len(self._combat_blockers_for_attacker(attacker_idx)) >= 2:
                return True
        return False

    def _build_auto_damage_assignment(self) -> dict[int, dict[int, int]]:
        """Build a damage assignment dict for simple cases (each attacker has at most 1 blocker)."""
        if not self.combat_attackers:
            return {}
        attacker_controller = self.players[self.active_player_index]
        assignment: dict[int, dict[int, int]] = {}
        for attacker_idx in self.combat_attackers:
            if attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            blockers = self._combat_blockers_for_attacker(attacker_idx)
            if len(blockers) == 1:
                blocker_idx = blockers[0]
                assign = max(0, attacker.effective_power)
                # For trample assign only lethal to the blocker; the remainder
                # flows to the defending player via the existing trample logic.
                defending_index = self.combat_defending_player_index
                if self._has_keyword(attacker, "trample") and defending_index is not None:
                    defending_player = self.players[defending_index]
                    if blocker_idx < len(defending_player.battlefield):
                        blocker = defending_player.battlefield[blocker_idx]
                        lethal = max(0, blocker.effective_toughness - blocker.damage_marked)
                        assign = min(assign, lethal)
                assignment[attacker_idx] = {blocker_idx: assign}
        return assignment

    def resolve_combat_damage(self, controller_index: int, attacker_damage: dict[int, dict[int, int]] | None = None) -> tuple[bool, str]:
        if self.current_turn_phase != "combat" or self.current_step != "combat_damage":
            return False, "combat damage can only be resolved during combat_damage"
        if controller_index != self.active_player_index:
            return False, "only active player may assign combat damage"
        if self.combat_damage_resolved:
            return False, "combat damage already resolved"

        self._prune_combat_state()
        if not self.combat_attackers:
            self.combat_damage_resolved = True
            return True, "no attackers"

        attacker_controller = self.players[self.active_player_index]
        defending_index = self.combat_defending_player_index
        if defending_index is None:
            return False, "no defending player"
        defender = self.players[defending_index]

        def participates_in_first_strike(perm: Permanent) -> bool:
            return self._has_keyword(perm, "first strike") or self._has_keyword(perm, "double strike")

        def participates_in_second_strike(perm: Permanent) -> bool:
            return self._has_keyword(perm, "double strike") or (
                not self._has_keyword(perm, "first strike") and not self._has_keyword(perm, "double strike")
            )

        if attacker_damage is None:
            attacker_damage = {}

        attacker_passes: list[int] = []
        blocker_passes: list[int] = []
        for attacker_idx in self.combat_attackers:
            if attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            blockers = self._combat_blockers_for_attacker(attacker_idx)
            if blockers:
                for blocker_idx in blockers:
                    if blocker_idx < len(defender.battlefield):
                        blocker = defender.battlefield[blocker_idx]
                        if participates_in_first_strike(attacker) or participates_in_first_strike(blocker):
                            attacker_passes.append(attacker_idx)
                            blocker_passes.append(blocker_idx)
                            break

        has_first_strike_pass = bool(attacker_passes)
        run_first_pass = has_first_strike_pass and not self.combat_first_strike_done

        attacker_damage_events: list[tuple[int, int, int]] = []
        defender_damage_events: list[tuple[int, int]] = []

        for attacker_idx in sorted(self.combat_attackers):
            if attacker_idx < 0 or attacker_idx >= len(attacker_controller.battlefield):
                continue
            attacker = attacker_controller.battlefield[attacker_idx]
            if attacker.effective_power <= 0:
                continue
            if run_first_pass and not participates_in_first_strike(attacker):
                continue
            if not run_first_pass and has_first_strike_pass and not participates_in_second_strike(attacker):
                continue

            blockers = self._combat_blockers_for_attacker(attacker_idx)
            power_left = attacker.effective_power
            if not blockers:
                if self.combat_damage_prevented_until_eot:
                    continue
                damage = self._prevent_damage(defender, power_left)
                if damage > 0:
                    defender_damage_events.append((defending_index, damage))
                continue

            requested = attacker_damage.get(attacker_idx, {})
            assigned_total = 0
            block_order = sorted(blockers)
            for blocker_idx in block_order:
                if blocker_idx >= len(defender.battlefield):
                    continue
                blocker = defender.battlefield[blocker_idx]
                lethal = max(0, blocker.effective_toughness - blocker.damage_marked)
                requested_damage = int(requested.get(blocker_idx, 0))
                if requested_damage < 0:
                    return False, "combat damage assignment cannot be negative"
                if requested_damage > power_left:
                    return False, "assigned combat damage exceeds attacker power"
                if not self._has_keyword(attacker, "trample") and requested_damage > 0 and requested_damage < lethal:
                    return False, "must assign lethal to each blocker in order"
                assigned_total += requested_damage
                power_left -= requested_damage
                if requested_damage > 0:
                    attacker_damage_events.append((defending_index, blocker_idx, requested_damage))

            if assigned_total > attacker.effective_power:
                return False, "assigned combat damage exceeds attacker power"
            if self._has_keyword(attacker, "trample") and power_left > 0 and not self.combat_damage_prevented_until_eot:
                trample_damage = self._prevent_damage(defender, power_left)
                if trample_damage > 0:
                    defender_damage_events.append((defending_index, trample_damage))

        for blocker_idx, attacker_idx in sorted(self.combat_blockers.items()):
            if blocker_idx < 0 or blocker_idx >= len(defender.battlefield):
                continue
            if attacker_idx < 0 or attacker_idx >= len(attacker_controller.battlefield):
                continue
            blocker = defender.battlefield[blocker_idx]
            attacker = attacker_controller.battlefield[attacker_idx]
            if blocker.effective_power <= 0:
                continue
            if run_first_pass and not participates_in_first_strike(blocker):
                continue
            if not run_first_pass and has_first_strike_pass and not participates_in_second_strike(blocker):
                continue
            attacker.damage_marked += blocker.effective_power

        for defending_idx, blocker_idx, damage in attacker_damage_events:
            if defending_idx >= len(self.players):
                continue
            defending_player = self.players[defending_idx]
            if blocker_idx < 0 or blocker_idx >= len(defending_player.battlefield):
                continue
            defending_player.battlefield[blocker_idx].damage_marked += damage

        total_player_damage = sum(dmg for _, dmg in defender_damage_events)
        for _, damage in defender_damage_events:
            defender.life -= damage

        self._destroy_marked_creatures()
        self._prune_combat_state()

        if total_player_damage > 0:
            self.log.append(
                f"{defender.name} took {total_player_damage} combat damage (life: {defender.life + total_player_damage} → {defender.life})"
            )

        if run_first_pass:
            self.combat_first_strike_done = True
            self.log.append("Resolved first strike combat damage")
            return True, "resolved first strike combat damage"

        self.combat_damage_resolved = True
        self.log.append("Resolved combat damage")
        return True, "resolved combat damage"

    def get_combat_state(self) -> dict[str, object]:
        self._prune_combat_state()
        return {
            "defending_player_index": self.combat_defending_player_index,
            "attackers": [{"attacker_index": k, "defending_player_index": v} for k, v in sorted(self.combat_attackers.items())],
            "blockers": [{"blocker_index": k, "attacker_index": v} for k, v in sorted(self.combat_blockers.items())],
            "damage_resolved": self.combat_damage_resolved,
            "first_strike_done": self.combat_first_strike_done,
            "attackers_locked": self.combat_attackers_locked,
            "blockers_locked": self.combat_blockers_locked,
        }

    def can_attack(self, attacker: Permanent, defending_player_index: int) -> bool:
        if self._is_summoning_sick(attacker):
            return False

        program = compile_card_oracle(attacker.card)
        instr_kinds = {i.kind for i in program.instructions}

        if "cant_attack_without_island" in instr_kinds:
            defending = self.players[defending_player_index]
            has_island = any("island" in perm.card.type_line.lower() for perm in defending.battlefield)
            return has_island

        if "cant_attack" in instr_kinds:
            return False

        if "Defender" in attacker.card.keywords and not attacker.metadata.get("can_attack_as_though_no_defender"):
            return False
        return True

    def _must_attack_if_able(self, attacker: Permanent) -> bool:
        if attacker.metadata.get("must_attack_until_eot"):
            return True
        program = compile_card_oracle(attacker.card)
        return any(i.kind == "must_attack_each_combat" for i in program.instructions)

    def resolve_draw_step(self, player_index: int) -> int:
        phase = "beginning"
        step = "draw"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        player = self.players[player_index]
        bonus = 0
        for controller in self.players:
            for permanent in controller.battlefield:
                if permanent.card.name == "Howling Mine" and not permanent.tapped:
                    bonus += 1
        drawn = player.draw(1 + bonus)
        self.log.append(f"{player.name} drew {drawn} card(s) in draw step")
        if self._receives_priority(step):
            self._resolve_priority_window()
        self._on_step_or_phase_end(phase, step)
        return drawn

    def get_untap_land_selection_options(self, player_index: int) -> dict[str, object] | None:
        player = self.players[player_index]
        all_permanents = [perm for pl in self.players for perm in pl.battlefield]

        if any(perm.card.name == "Stasis" for perm in all_permanents):
            return None

        max_untap_lands = 999
        if any(perm.card.name == "Winter Orb" and not perm.tapped for perm in all_permanents):
            max_untap_lands = 1

        if max_untap_lands >= 999:
            return None

        candidate_indices = [
            idx
            for idx, permanent in enumerate(player.battlefield)
            if permanent.card.primary_type == "land" and permanent.tapped
        ]
        if len(candidate_indices) <= max_untap_lands:
            return None

        return {
            "max_count": max_untap_lands,
            "candidate_indices": candidate_indices,
        }

    def resolve_untap_step(self, player_index: int, selected_land_indices: list[int] | None = None) -> int:
        phase = "beginning"
        step = "untap"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        player = self.players[player_index]
        all_permanents = [perm for pl in self.players for perm in pl.battlefield]

        if any(perm.card.name == "Stasis" for perm in all_permanents):
            self.log.append(f"{player.name} skipped untap due to Stasis")
            return 0

        max_untap_creatures = 999
        if any(perm.card.name == "Smoke" for perm in all_permanents):
            max_untap_creatures = 1

        max_untap_lands = 999
        if any(perm.card.name == "Winter Orb" and not perm.tapped for perm in all_permanents):
            max_untap_lands = 1

        selected_lands: set[int] | None = None
        if selected_land_indices is not None:
            selected_lands = set()
            for idx in selected_land_indices:
                if idx < 0 or idx >= len(player.battlefield):
                    raise ValueError("selected land index out of range")
                permanent = player.battlefield[idx]
                if permanent.card.primary_type != "land":
                    raise ValueError("selected permanent is not a land")
                if not permanent.tapped:
                    continue
                selected_lands.add(idx)

            if max_untap_lands < 999 and len(selected_lands) > max_untap_lands:
                raise ValueError(f"cannot untap more than {max_untap_lands} land(s)")

        meekstone_active = any(perm.card.name == "Meekstone" for perm in all_permanents)

        untapped = 0
        creatures_untapped = 0
        lands_untapped = 0
        for idx, permanent in enumerate(player.battlefield):
            if not permanent.tapped:
                continue

            if permanent.card.primary_type == "creature":
                if meekstone_active and permanent.effective_power >= 3:
                    continue
                if creatures_untapped >= max_untap_creatures:
                    continue
                creatures_untapped += 1

            if permanent.card.primary_type == "land":
                if selected_lands is not None and idx not in selected_lands:
                    continue
                if lands_untapped >= max_untap_lands:
                    continue
                lands_untapped += 1

            permanent.tapped = False
            untapped += 1

        self.log.append(f"{player.name} untapped {untapped} permanent(s)")
        self._on_step_or_phase_end(phase, step)
        return untapped

    def tap_land_for_mana(
        self,
        player_index: int,
        land_name: str,
        chosen_color: str = "G",
        permanent_index: int | None = None,
    ) -> bool:
        player = self.players[player_index]
        resolved = self._find_controlled_permanent(player, land_name, permanent_index)
        land = resolved[1] if resolved else None
        if land is not None and land.card.primary_type != "land":
            land = None
        if land is None or land.tapped:
            return False

        land.tapped = True
        mana_symbol = chosen_color
        if land.card.produced_mana:
            if chosen_color in land.card.produced_mana:
                mana_symbol = chosen_color
            else:
                mana_symbol = land.card.produced_mana[0]
        else:
            land_types = [str(land.metadata.get("land_type_override", "")).lower(), land.card.type_line.lower()]
            if any("plains" in value for value in land_types):
                mana_symbol = "W"
            elif any("island" in value for value in land_types):
                mana_symbol = "U"
            elif any("swamp" in value for value in land_types):
                mana_symbol = "B"
            elif any("mountain" in value for value in land_types):
                mana_symbol = "R"
            elif any("forest" in value for value in land_types):
                mana_symbol = "G"
        player.mana_pool[mana_symbol] = player.mana_pool.get(mana_symbol, 0) + 1

        all_permanents = [perm for pl in self.players for perm in pl.battlefield]
        if any(perm.card.name == "Mana Flare" for perm in all_permanents):
            player.mana_pool[mana_symbol] = player.mana_pool.get(mana_symbol, 0) + 1

        self.log.append(f"{player.name} tapped {land_name} for mana")
        return True

    def end_combat(self, step_already_started: bool = False) -> None:
        phase = "combat"
        step = "end_of_combat"
        if not step_already_started:
            self._set_phase_and_step(phase, step)
            self._on_step_or_phase_begin(phase, step)
        for player in self.players:
            for permanent in player.battlefield:
                if permanent.metadata.get("animate_until_end_of_combat"):
                    permanent.metadata.pop("animate_until_end_of_combat", None)
                    permanent.metadata.pop("absolute_power", None)
                    permanent.metadata.pop("absolute_toughness", None)
        self.combat_damage_prevented_until_eot = False
        for player in self.players:
            player.combat_damage_cap_one_charges = 0
        self._reset_combat_state(clear_damage_marked=False)
        if self._receives_priority(step):
            self._resolve_priority_window()
        self._on_step_or_phase_end(phase, step)

    def _process_land_enters(self, land_controller_index: int) -> None:
        for controller in self.players:
            for permanent in controller.battlefield:
                program = compile_card_oracle(permanent.card)
                if not any(t.condition.kind == "land_enters" for t in program.triggered_abilities):
                    continue
                victim = self.players[land_controller_index]
                damage = self._prevent_damage(victim, 2)
                if damage > 0:
                    victim.life -= damage
                self.log.append(f"{permanent.card.name} triggered for {damage} damage")

    def _fastbond_count(self, player_index: int) -> int:
        if player_index < 0 or player_index >= len(self.players):
            return 0
        return sum(1 for permanent in self.players[player_index].battlefield if permanent.card.name == "Fastbond")

    def _apply_global_buff(self, caster: PlayerState, source: CardDefinition) -> None:
        program = compile_card_oracle(source)
        for instr in program.instructions:
            if instr.kind == "animate_all_swamps":
                self._refresh_dynamic_creatures()
                return
            if instr.kind == "animate_all_forests":
                self._refresh_dynamic_creatures()
                return
            if instr.kind == "buff_attacking_creatures":
                for permanent in caster.battlefield:
                    if permanent.card.primary_type == "creature":
                        permanent.power_bonus += int(instr.payload.get("power", 0))
                return
            if instr.kind == "buff_untapped_creatures":
                for permanent in caster.battlefield:
                    if permanent.card.primary_type == "creature" and not permanent.tapped:
                        permanent.toughness_bonus += int(instr.payload.get("toughness", 0))
                return
            if instr.kind == "buff_creatures_global":
                color_sym = instr.payload.get("color")
                power_bonus = int(instr.payload.get("power", 0))
                toughness_bonus = int(instr.payload.get("toughness", 0))
                target_players = self.players if instr.payload.get("all") else [caster]
                for player in target_players:
                    for permanent in player.battlefield:
                        if permanent.card.primary_type != "creature":
                            continue
                        if color_sym and color_sym not in permanent.card.colors:
                            continue
                        permanent.power_bonus += power_bonus
                        permanent.toughness_bonus += toughness_bonus
                return

    def _apply_aura_effect(
        self,
        caster_index: int,
        aura_permanent: Permanent,
        target_player_index: int | None,
        target_permanent_index: int | None = None,
    ) -> None:
        program = compile_card_oracle(aura_permanent.card)
        text = program.normalized_text
        if not any(instr.kind == "spell_pattern" and instr.value.startswith("enchant") for instr in program.instructions):
            return

        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        target_player = self.players[target_idx]

        if text.startswith("enchant creature"):
            # Special-case reanimation-style Auras (e.g., Animate Dead) which target a
            # creature card in a graveyard and return it to the battlefield attached
            # to this Aura. Detect the presence of the reanimation language and
            # handle it by moving a creature card from the target player's
            # graveyard to the caster's battlefield and attaching the Aura.
            # Prefer the parsed instruction if available
            has_reanimate = any(instr.kind == "reanimate_creature" for instr in program.instructions)
            if has_reanimate or ("creature card in a graveyard" in text and "return enchanted creature card to the battlefield" in text):
                # find a creature card in the target player's graveyard
                revived_card = None
                for idx, card in enumerate(target_player.graveyard):
                    if card.primary_type == "creature":
                        revived_card = target_player.graveyard.pop(idx)
                        break
                if revived_card is None:
                    return

                # Put the revived creature onto the battlefield under the caster's control
                revived_perm = Permanent(card=revived_card)
                self._put_permanent_onto_battlefield(caster_index, revived_perm, None)
                # Attach the Aura to the revived permanent (store references in metadata)
                aura_permanent.metadata["attached_to"] = revived_perm
                revived_perm.metadata["attached_aura"] = aura_permanent
                # Apply the -1/-0 penalty from Animate Dead's text if present
                if "enchanted creature gets -1/-0" in text or "enchanted creature gets -1/ -0" in text:
                    revived_perm.power_bonus += -1

                self.log.append(f"{aura_permanent.card.name} reanimated {revived_card.name} and attached to aura")
                return

            # Normal enchant-creature behavior: attach to a creature already on the battlefield
            target_creature = next(
                (perm for perm in target_player.battlefield if perm.card.primary_type == "creature"),
                None,
            )
            if not target_creature:
                return

            # Handle numeric static buffs like "gets +1/+1" using normalized text
            buff_match = re.search(r"gets \+(-?\d+)/\+(-?\d+)", text)
            if buff_match:
                target_creature.power_bonus += int(buff_match.group(1))
                target_creature.toughness_bonus += int(buff_match.group(2))

            # Handle Aspect of Wolf style dynamic buff text:
            # "Enchanted creature gets +X/+Y, where X is half the number of Forests you control, rounded down, and Y is half the number of Forests you control, rounded up."
            # Compute forest count controlled by the aura's controller (caster_index)
            if "half the number of forests you control" in text:
                caster_controller = self.players[caster_index]
                forests = sum(
                    1
                    for perm in caster_controller.battlefield
                    if perm.card.primary_type == "land"
                    and (
                        "forest" in perm.card.type_line.lower()
                        or perm.metadata.get("land_type_override") == "forest"
                    )
                )
                x = forests // 2
                y = (forests + 1) // 2
                target_creature.power_bonus += int(x)
                target_creature.toughness_bonus += int(y)

            # Landwalk/protection patterns are recognized in the compiled program;
            # fall back to normalized-text checks for logging when necessary.
            if any(instr.kind == "spell_pattern" and instr.value.startswith("has ") and "walk" in instr.value for instr in program.instructions) or ("has " in text and "walk" in text):
                self.log.append(f"{target_creature.card.name} gains landwalk from {aura_permanent.card.name}")

            if any("protection from" in instr.value for instr in program.instructions if instr.kind == "spell_pattern") or ("has protection from" in text):
                self.log.append(f"{target_creature.card.name} gains protection from aura")

        elif text.startswith("enchant land"):
            self.log.append(f"{aura_permanent.card.name} enchants a land (mana bonus handling is simplified)")
        elif text.startswith("enchant wall"):
            target_wall = next(
                (perm for perm in target_player.battlefield if "wall" in perm.card.type_line.lower()),
                None,
            )
            if target_wall:
                target_wall.metadata["can_attack_as_though_no_defender"] = True
                self.log.append(f"{target_wall.card.name} can attack as though it didn't have defender")
        elif text.startswith("enchant artifact"):
            # Attach this Aura to the specified artifact (or first artifact found)
            target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
            target_player = self.players[target_idx]

            target_artifact = None
            if target_permanent_index is not None:
                if 0 <= target_permanent_index < len(target_player.battlefield):
                    candidate = target_player.battlefield[target_permanent_index]
                    if candidate.card.primary_type == "artifact":
                        target_artifact = candidate
            if target_artifact is None:
                target_artifact = next((perm for perm in target_player.battlefield if perm.card.primary_type == "artifact"), None)

            if target_artifact is None:
                return

            # Attach metadata links
            aura_permanent.metadata["attached_to"] = target_artifact
            target_artifact.metadata["attached_aura"] = aura_permanent

            # If the artifact isn't already a creature, make it an artifact creature
            if target_artifact.card.primary_type != "creature":
                new_type_line = target_artifact.card.type_line
                if "creature" not in new_type_line.lower():
                    new_type_line = (new_type_line + " Creature").strip()

                new_raw = dict(target_artifact.card.raw)
                power = toughness = int(target_artifact.card.cmc)
                new_raw["power"] = str(power)
                new_raw["toughness"] = str(toughness)

                new_card = CardDefinition(
                    name=target_artifact.card.name,
                    mana_cost=target_artifact.card.mana_cost,
                    cmc=target_artifact.card.cmc,
                    type_line=new_type_line,
                    oracle_text=target_artifact.card.oracle_text,
                    colors=target_artifact.card.colors,
                    color_identity=target_artifact.card.color_identity,
                    keywords=target_artifact.card.keywords,
                    produced_mana=target_artifact.card.produced_mana,
                    raw=new_raw,
                )

                target_artifact.card = new_card
                self.log.append(f"{aura_permanent.card.name} animated {target_artifact.card.name} into an artifact creature")

