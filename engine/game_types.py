from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .models import CardDefinition, Permanent, PlayerState
from .oracle import OracleInstruction

if TYPE_CHECKING:
    from .game import Game


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
    # target_permanent_index may be a single int or a list of ints for multi-target spells
    target_permanent_index: int | list[int] | None
    x_value: int | None
    ability_instruction: OracleInstruction | None = None
    ability_effect_kind: str | None = None
    source_permanent: Permanent | None = None
    target_stack_name: str | None = None
    # Direct reference to the stack item this spell/ability targets (Counterspell,
    # Fork). Lets the effect act on the chosen spell rather than the top of stack.
    target_stack_item: "StackItem | None" = None
    ability_text: str | None = None
    new_color: str | None = None
    # The "from" color/land-type word for a text-change spell (Magical Hack /
    # Sleight of Mind): the word being replaced. new_color is the replacement.
    old_color: str | None = None
    # Chosen mode of a "Choose one —" modal spell, as an index into the card's
    # compiled OracleProgram.modes. None for non-modal spells (resolve mode 0).
    chosen_mode_index: int | None = None


@dataclass
class OracleExecutionContext:
    caster: PlayerState
    target: PlayerState
    card: CardDefinition
    # target_permanent_index may be a single int or a list of ints for multi-target spells
    target_permanent_index: int | list[int] | None = None
    x_value: int | None = None
    source_permanent: Permanent | None = None
    new_color: str | None = None
    # The "from" word for a text-change spell (Magical Hack / Sleight of Mind).
    old_color: str | None = None
    # The chosen target spell/ability on the stack (Counterspell, Fork).
    stack_target: "StackItem | None" = None


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
