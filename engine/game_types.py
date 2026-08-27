from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

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
CHOICE_KEYS = (
    "new_color", "old_color", "divided_targets", "chosen_source",
    # What a printed additional cost ate on the way to the stack (CR 601.2b) —
    # not a choice about the *effect*, but the same shape: something decided
    # while casting that the resolution has to be able to read back. It is a
    # ``Permanent`` that is no longer on any battlefield, so this is the only
    # place it survives (CR 608.2h last-known information).
    "sacrificed_for_cost",
    # The cards a printed **discard** cost ate, same channel and same reason:
    # "If the discarded card was a land card" (Land's Edge) is asked when the
    # card is already in a graveyard, which CR 400.7 makes a different object.
    # A list, because the cost's count is payload — one card today, N the day a
    # card prints "Discard two cards:".
    "discarded_for_cost",
    # How many counters a printed "Remove any number of <kind> counters from
    # this permanent" cost actually took (the five Mana Batteries). A number
    # rather than an object, and on this channel for the same reason as the two
    # above: the counters are off the permanent before the ability reaches the
    # stack, so nothing on the board can be counted at resolution.
    "counters_removed_for_cost",
)


@dataclass(frozen=True)
class GraveyardTarget:
    """One card in one graveyard, named so the name survives the wait on the stack.

    The graveyard's answer to ``permanent_id``, and it has to be a different
    answer: ``load_cards`` dedupes by ``oracle_id``, so two copies of one card
    in one graveyard are literally one ``CardDefinition`` object and neither an
    id nor ``is`` can tell them apart. What can is *order* — ``ordinal`` is
    which copy of ``card``, counting from the bottom of the pile, which is
    stable under every other card leaving.

    The residual, stated rather than hidden: with two copies of one card in one
    graveyard the engine cannot know which of them left, because they are the
    same object. Resolution therefore clamps to the last surviving copy and
    reports "gone" only when *no* copy remains — the one case it can establish.
    """

    seat: int
    card: CardDefinition
    ordinal: int = 0


@dataclass
class ChosenMode:
    """One mode of a "Choose one or more —" spell, with the targets it chose.

    CR 601.2b picks the modes as the spell is cast and CR 601.2c picks each
    mode's targets right after, so a mode and its targets are chosen together
    and have to travel together: two modes of Sublime Epiphany may name two
    different objects on two different boards, which the item's single
    ``target_player_index`` cannot say.

    ``index`` is a position in the card's compiled ``OracleProgram.modes``.
    """

    index: int
    target_player_index: int | None = None
    target_permanent_index: int | None = None
    target_permanent_id: int | None = None
    # Resolved against the stack at cast time, exactly as the item's own
    # ``target_stack_item`` is: a stack index is a position in a list that
    # anything resolving in response renumbers.
    target_stack_item: "StackItem | None" = None


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
    # The same target when the chosen index is a slot in a *graveyard* rather
    # than on a battlefield (CR 601.2c). A card there has no ``permanent_id`` to
    # stamp, so the identity is a :class:`GraveyardTarget`. Same shape as the
    # index beside it (one, a list, or None), for the same reason: a graveyard
    # index is a position in a list, and anything leaving that zone in response
    # renumbers every later slot exactly as the battlefield does.
    target_graveyard_card: "GraveyardTarget | list[GraveyardTarget | None] | None" = None
    ability_instruction: OracleInstruction | None = None
    ability_effect_kind: str | None = None
    source_permanent: Permanent | None = None
    # Direct reference to the stack item this spell/ability targets (Counterspell,
    # Fork). Lets the effect act on the chosen spell rather than the top of stack.
    target_stack_item: "StackItem | None" = None
    ability_text: str | None = None
    # Chosen mode of a "Choose one —" modal spell, as an index into the card's
    # compiled OracleProgram.modes. None for non-modal spells (resolve mode 0).
    #
    # Still here, and still one index, because everything that reads a *single*
    # mode reads it: the graveyard-target stamp, the copy handlers, the AI. For
    # a multi-mode spell it holds the first chosen mode, so those readers see
    # what they always saw rather than a shape they were never written for.
    chosen_mode_index: int | None = None
    # "Choose one **or more** —" (Sublime Epiphany, CR 700.2d). Every chosen
    # mode with its own targets, in **printed** order — CR 608.2c resolves the
    # modes in the order they are written on the card, not the order the caster
    # named them. Empty for every spell that is not multi-mode, which is what
    # keeps the single-mode path byte-identical.
    chosen_modes: tuple[ChosenMode, ...] = ()
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
    # This object's instructions have run and it is on the stack only because
    # somebody still owes a decision it asked for (CR 608.2: the resolution is
    # not over until its last instruction is done; CR 117.3b: nobody receives
    # priority until then). It is the flag rather than the queue that says so,
    # because the two can disagree in one direction that matters: an answer path
    # that forgets to release the object would otherwise leave it looking
    # unresolved, and the next priority pass would run its instructions a second
    # time. Held means resolved — the only thing left is to leave.
    resolution_held: bool = False
    # The last step of a held *spell's* resolution — CR 608.2n, the card going
    # to its owner's graveyard — deferred until the last prompt is answered.
    # Binning at the usual point put the card in two zones at once: on the
    # stack, held, and in the graveyard, with the log already saying "resolved
    # and moved to graveyard" while the discard it asked for was still owed.
    # ``_release_stack_item`` runs it and clears it; None for an ability, or a
    # spell nothing held.
    finish_resolution: Callable[[], None] | None = None


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
    # Which zone the resolving spell was cast from ("hand" unless a permission
    # effect opened another; see StackItem.cast_from_zone). What "if this
    # spell was cast from anywhere other than your hand" (See the Truth)
    # reads.
    cast_from_zone: str = "hand"
    # Scratchpad for values one instruction produces and a later instruction in
    # the same resolution consumes ("deals X damage… you gain that much life").
    # Compositional effects need this: once "deal damage and gain life" is two
    # instructions instead of one fused kind, the second needs to know what the
    # first actually did. Keyed by result name, e.g. "damage_dealt".
    results: dict = field(default_factory=dict)
    # The object currently being iterated by a "for each …" instruction.
    iteration_target: Permanent | None = None
    # The seats an earlier step recorded **about that object**, resolved for the
    # iteration in progress. ``results`` holds those records whole — a
    # ``{permanent_id: seat}`` map written by the step that knew the answer — and
    # inside a loop over exactly those objects the map has one entry that
    # matters. A reader would otherwise need the loop's object *and* the record's
    # shape to ask a question that has one answer, which is two things to get
    # wrong; the loop resolves it once and every reader asks by name.
    #
    # Empty outside a loop, so the readers that consult it fall through to the
    # trigger context exactly as they did before it existed.
    iteration_seats: dict = field(default_factory=dict)


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
