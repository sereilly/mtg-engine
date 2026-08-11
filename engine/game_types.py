from __future__ import annotations

from dataclasses import dataclass, field
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


# Keys of StackItem.choices / OracleExecutionContext.choices, named once so the
# side that records a choice and the handler that reads it cannot drift.
# tests/engine/test_stack_item_choices.py holds the engine to this list in both
# directions, which is what makes it a declaration rather than a comment.
#
#   new_color        the replacement colour/land-type word of a recolor or
#                    text-change spell (the Lace cycle, Magical Hack, Sleight of
#                    Mind, and the "of any one color" mana spells)
#   old_color        the word being *replaced* by a text change; new_color is
#                    what replaces it
#   divided_targets  a divided spell's full cross-seat target list (Fireball,
#                    Volcanic Eruption) as (seat, battlefield_index) pairs, where
#                    a (seat, None) entry is that player's face. Takes precedence
#                    over target_player_index / target_permanent_index.
#   chosen_source    "a source of your choice" (Jade Monolith, the source-of-
#                    choice prevention spells): a battlefield Permanent or a
#                    stack spell's CardDefinition
CHOICE_KEYS = ("new_color", "old_color", "divided_targets", "chosen_source")


@dataclass
class StackItem:
    card: CardDefinition
    caster_index: int
    target_player_index: int | None
    # target_permanent_index may be a single int or a list of ints for multi-target spells
    target_permanent_index: int | list[int] | None
    x_value: int | None
    # The same target(s) by *stable identity* (CR 601.2c), stamped as the object
    # is put on the stack by ``Game._stack_push``. The index beside it is a
    # position in a battlefield list, and the whole point of the stack is that
    # time passes before this resolves: anything that leaves the battlefield in
    # between renumbers every later slot, so an index recorded at cast time can
    # resolve to a *different* permanent at resolution time. Same shape as the
    # index (an int, a list, or None) so the two stay readable side by side.
    target_permanent_id: int | list[int | None] | None = None
    ability_instruction: OracleInstruction | None = None
    ability_effect_kind: str | None = None
    source_permanent: Permanent | None = None
    # Direct reference to the stack item this spell/ability targets (Counterspell,
    # Fork). Lets the effect act on the chosen spell rather than the top of stack.
    target_stack_item: "StackItem | None" = None
    ability_text: str | None = None
    # Chosen mode of a "Choose one —" modal spell, as an index into the card's
    # compiled OracleProgram.modes. None for non-modal spells (resolve mode 0).
    chosen_mode_index: int | None = None
    # A copy of a spell (Fork): it resolves like the original but ceases to exist
    # afterward rather than going to a graveyard, and was never cast from a hand.
    is_copy: bool = False
    # CR 601.3e-adjacent bookkeeping: which zone the card was cast from. "hand"
    # for the ordinary case; "graveyard"/"exile" when a permission effect
    # (engine/cast_permissions.py) opened the zone. What "if this spell was
    # cast from anywhere other than your hand" reads.
    cast_from_zone: str = "hand"
    # "If that spell would be put into your graveyard, exile it instead."
    # (Chandra, Flame's Catalyst's −2.) Stamped at cast time from the
    # permission grant; every place a spell's card leaves the stack for the
    # graveyard — resolution, countering — routes on it.
    exile_instead_of_graveyard: bool = False
    # For a triggered ability on the stack: event data captured at fire time that the
    # effect handler reads at resolution (e.g. the dead creature's name, the damage
    # amount, the player who was dealt damage, an optional-pay cost).
    trigger_context: dict | None = None
    # A resolve-time, name-keyed hook (Rod/Cup/Sphere, Verduran Enchantress, Guardian
    # Angel). When set, resolution dispatches to TRIGGER_HOOKS[hook_key] instead of an
    # OracleInstruction, passing hook_event as the captured event payload.
    hook_key: str | None = None
    hook_event: dict | None = None
    # Everything the caster picked beyond the target itself, keyed by CHOICE_KEYS.
    # A dict rather than a field each so a card family needing a new kind of
    # choice adds a key here and a read in its handler, instead of a field on
    # this dataclass *and* one on OracleExecutionContext. Handlers already read
    # their instruction payloads this way, so it is the same idiom.
    choices: dict = field(default_factory=dict)


@dataclass
class OracleExecutionContext:
    caster: PlayerState
    target: PlayerState
    card: CardDefinition
    # target_permanent_index may be a single int or a list of ints for multi-target spells
    target_permanent_index: int | list[int] | None = None
    # The target(s) by stable identity, carried over from the stack item (see
    # StackItem.target_permanent_id). ``engine/handlers/_common.py`` prefers it
    # over the index, which is why a handler needs no new code to stop being
    # positional — it already asks ``resolve_target_permanent``.
    target_permanent_id: int | list[int | None] | None = None
    x_value: int | None = None
    source_permanent: Permanent | None = None
    # The chosen target spell/ability on the stack (Counterspell, Fork).
    stack_target: "StackItem | None" = None
    # Event data captured when a triggered ability fired, read by its effect handler
    # at resolution (see StackItem.trigger_context).
    trigger_context: dict | None = None
    # What the caster picked beyond the target, carried through from the stack
    # item unchanged. Keys are CHOICE_KEYS.
    choices: dict = field(default_factory=dict)
    # Scratchpad for values one instruction produces and a later instruction in
    # the same resolution consumes ("deals X damage… you gain that much life").
    # Compositional effects need this: once "deal damage and gain life" is two
    # instructions instead of one fused kind, the second needs to know what the
    # first actually did. Keyed by result name, e.g. "damage_dealt".
    results: dict = field(default_factory=dict)
    # The object currently being iterated by a "for each …" instruction.
    iteration_target: Permanent | None = None


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
