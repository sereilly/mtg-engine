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
#   new_color        the replacement colour/land-type word a text-change spell
#                    or ability was announced with (Magical Hack, Sleight of
#                    Mind), and the colour an "of any one color" mana effect
#                    names. Never "the color of your choice": CR 608.2d asks
#                    that while the effect is applied (``choose_color``), and it
#                    is not something CR 601.2 / 602.2b announce.
#   old_color        the word being *replaced* by a text change; new_color is
#                    what replaces it
#   color_override   the colour an *effect* made this object while it was on
#                    the stack (the Lace cycle: "target spell becomes red"),
#                    read by ``_stack_item_colors``. Its own key, not
#                    new_color, because what a spell was announced with and
#                    what was done to it are two facts — one key made Sleight
#                    of Mind cast to write "red" a red spell.
#   color_effect     beside color_override: how long that effect lasts and when
#                    it was created (``color_changes.recolor_spell`` writes
#                    both), so it can go on applying to the permanent the
#                    spell becomes (CR 400.7a) with its own duration and its
#                    own timestamp (CR 613.7b)
#   divided_targets  a divided spell's full cross-seat target list (Fireball,
#                    Volcanic Eruption) as (seat, battlefield_index) pairs, where
#                    a (seat, None) entry is that player's face. Takes precedence
#                    over target_player_index / target_permanent_index.
#   chosen_source    "a source of your choice" (Jade Monolith, the source-of-
#                    choice prevention spells): a battlefield Permanent or a
#                    stack spell's CardDefinition
CHOICE_KEYS = (
    "new_color", "old_color", "color_override", "color_effect",
    "divided_targets", "chosen_source",
    # "For each additional {1}{R} you paid, …" (Primitive Justice, Taste of
    # Paradise); "If this spell's additional cost was paid, …" (Undergrowth).
    # An *offer* the caster took, counted — not an object a cost ate like the
    # channels below, but the same shape and here for the same reason: the mana
    # pool empties at the end of the step (CR 500.5) and the announcement is the
    # only record that the price was paid at all. Keyed by the cost's canonical
    # spelling: ``{"{1}{R}": 2}``.
    "additional_costs_paid",
    # What a printed additional cost ate on the way to the stack (CR 601.2b) —
    # not a choice about the *effect*, but the same shape: something decided
    # while casting that the resolution has to be able to read back. It is a
    # ``Permanent`` that is no longer on any battlefield, so this is the only
    # place it survives (CR 608.2h last-known information).
    "sacrificed_for_cost",
    # The land a printed **untap** cost paid with (Benthic Explorers: "{T},
    # Untap a tapped land an opponent controls: Add one mana of any type **that
    # land** could produce"). The odd one out on this channel: it is still on
    # the battlefield when the effect reads it, so this is not last-known
    # information — it is a *back-reference*. "That land" names the one the cost
    # untapped, and a board scan at resolution would name whichever tapped land
    # of an opponent's happens to match then, which after the payment is a
    # different one.
    "untapped_for_cost",
    # The creature a printed **tap** cost paid with (Unerring Sling: "{3}, {T},
    # Tap an untapped creature you control: This artifact deals damage equal to
    # **the tapped creature's** power to …"). Beside ``untapped_for_cost`` and
    # the odd one out for the same reason: the creature is still on the
    # battlefield at resolution, so this is a back-reference rather than
    # last-known information — a board scan would name whichever creature its
    # controller happens to have tapped since.
    "tapped_for_cost",
    # The cards a printed **discard** cost ate, same channel and same reason:
    # "If the discarded card was a land card" (Land's Edge) is asked when the
    # card is already in a graveyard, which CR 400.7 makes a different object.
    # A list, because the cost's count is payload — one card today, N the day a
    # card prints "Discard two cards:".
    "discarded_for_cost",
    # How many counters a printed "Remove any number of" — or "Remove **all**"
    # (Essence Bottle, Torture Chamber) — "<kind> counters from this permanent"
    # cost actually took. A number rather than an object, and on this channel
    # for the same reason as the two above: the counters are off the permanent
    # before the ability reaches the stack, so nothing on the board can be
    # counted at resolution.
    "counters_removed_for_cost",
    # Every permanent an "any number of <noun phrase>" sacrifice cost ate
    # (Sword of the Ages). A list beside ``sacrificed_for_cost``'s single
    # permanent rather than a widening of it: the two are different costs — one
    # names a permanent the payer chooses, the other a *set* whose size the
    # payer chooses — and a card can print both, as this one does.
    "sacrificed_set_for_cost",
    # What a printed **exile** cost ate (City of Shadows, Necropolis). Same
    # channel and same reason as the three above: the object is out of the game
    # before the ability reaches the stack, and "where X is **the exiled card's**
    # mana value" is asked once it is (CR 608.2h). A ``CardDefinition``, not a
    # ``Permanent``, because the graveyard spelling of the cost never had one.
    "exiled_for_cost",
    # Every card a **counted** exile cost ate ("Exile two creature cards from a
    # single graveyard", Night Soil). A list beside ``exiled_for_cost``'s single
    # object for the reason ``sacrificed_set_for_cost`` sits beside
    # ``sacrificed_for_cost``: one names the object the payer chose, the other
    # the whole set, and a reader of "the exiled card" must not be handed a list
    # it would then treat as one card.
    "exiled_set_for_cost",
    # The cards a printed **mill** cost put into the payer's graveyard ("{T},
    # Mill a card: For each colored mana symbol in **the milled card's** mana
    # cost, …", Charmed Pendant). A list for ``discarded_for_cost``'s reason,
    # and on this channel for the others': by resolution the card is one of
    # however many are in the graveyard, and only the payment knows which.
    "milled_for_cost",
    # CR 107.4b's symbols a printed mana cost actually consumed ("Note the type
    # of mana spent to pay this activation cost", Jeweled Amulet, Ice Cauldron).
    # A symbol dict, and on this channel for the three above's reason: the pool
    # empties at the end of the step (CR 500.5), so by resolution nothing in the
    # game state can say what paid. Measured as the difference the payment made
    # rather than read off the cost — a generic pip says how much is owed and
    # never which symbol covers it.
    "mana_spent_for_cost",
    # How much of X each colour paid, for a cast whose X is colour-restricted
    # ("Spend only black and/or red mana on X." — Soul Burn, Drain Life). Its
    # own channel beside ``mana_spent_for_cost`` above rather than a widening of
    # it, because it is a different question: that one is what the whole cost
    # consumed, measured as a pool delta, and a delta cannot say whether a black
    # unit paid X, the mandatory {B} pip or the generic {2}. This is the
    # allocation the payment was *built* from, so "the amount of {B} spent on X"
    # is exact.
    "x_mana_spent",
    # Whether the spell was cast at a time a sorcery could **not** have been
    # (Mirage's five flash Auras: "If you cast it any time a sorcery couldn't
    # have been cast, …"). On this channel for the same reason as every cost
    # spoil above it: CR 601.3d's timing is a fact about the moment of
    # announcement, and by resolution the stack has emptied down to this spell
    # and the step may have moved on — so nothing in the game state can be asked
    # the question afterwards. `engine/cast_timing.py` names the key and reads
    # the sentence; the permanent's resolution copies the answer onto the
    # permanent and the cleanup step acts on it.
    "cast_at_instant_speed",
    # The creature type a printed additional cost made the caster choose
    # (CR 601.2b: "As an additional cost to cast this spell, choose a creature
    # type" — Caller of the Hunt). On this channel for the cost spoils' reason
    # exactly, with the object they record replaced by a word: the choice is
    # made while the spell is being cast and nothing in the game state can be
    # asked for it afterwards — the spell has no permanent yet, and the
    # permanent it becomes is a new object (CR 400.7).
    #
    # Spelled the same as the permanent metadata key `subject_filters` reads
    # ("creatures **of the chosen type**"), deliberately: the resolution copies
    # this value straight onto the entering permanent, and one word from the
    # announcement to the matcher is what keeps a cast-time choice and an
    # entry-time choice (An-Zerrin Ruins) answerable by one reader.
    "chosen_creature_type",
    # The announcement named **no target, legally** ("up to one target
    # creature" at zero — CR 601.2c, CR 115.6). Not a choice beyond the target
    # but the record that the target choice was *made and came back empty*,
    # which the empty target fields cannot say: they are just as empty for a
    # bare headless announcement that leaves the pick to its handler. On this
    # dict because it is the one thing that reaches the handler from the stack
    # item with no second field to keep in step. ``oracle_types`` names the
    # key and holds its one reader.
    "named_no_target",
    # Every seat a **several-role** announcement named, one entry per role in
    # role order with ``None`` where the role is not a player ("…creatures
    # **target player** controls … creatures **another target player**
    # controls", Cultural Exchange). A target rather than a choice beyond one,
    # and on this channel for ``divided_targets``' reason: it is the other
    # announcement that names several players, and ``target_player_index`` is
    # one seat. Written only where there are two or more seat roles —
    # ``targeting.ROLE_SEATS`` names the key and says who reads it.
    "role_seats",
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
    # A list when the mode names several targets ("up to two target creatures",
    # Fatal Lore) — the same shape, and for the same reason, that `StackItem`
    # carries below: several chosen objects may sit on two battlefields, which
    # one seat index cannot say.
    target_permanent_index: int | list[int] | None = None
    target_permanent_id: int | list[int | None] | None = None
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
    # CR 601.2a's bookkeeping: which zone the card was cast from. "hand"
    # for the ordinary case; "graveyard"/"exile" when a permission effect
    # (engine/cast_permissions.py) opened the zone. What "if this spell was
    # cast from anywhere other than your hand" reads.
    cast_from_zone: str = "hand"
    # "If that spell would be put into your graveyard, exile it instead."
    # (Chandra, Flame's Catalyst's −2.) Stamped at cast time from the
    # permission grant; every place a spell's card leaves the stack for the
    # graveyard — resolution, countering — routes on it.
    exile_instead_of_graveyard: bool = False
    # CR 702.34a: this spell's **flashback cost was paid** — "exile this card
    # instead of putting it *anywhere else* any time it would leave the stack."
    # Wider than the rider above, which speaks only of a graveyard: a countered
    # spell a card sends to its owner's library (Memory Lapse) or hand
    # (Unsubstantiate) is neither, and a flashed-back one goes to exile all the
    # same. Stamped at cast time beside that rider (a flashback cast carries
    # both, so every site that bins to a graveyard is already right) and read
    # through ``flashback.leaves_stack_to_exile`` by the sites that send a
    # card somewhere else. Never set on a copy: CR 707.10, a copy is not cast.
    flashback: bool = False
    # "The next instant or sorcery spell you cast this turn can't be countered."
    # (Overmaster.) The name of the effect that made **this** spell
    # uncounterable as it was cast (``counter_conditions.spend_next_spell_
    # promises``), read by ``counter_conditions.cant_be_countered``. An effect
    # on the object, not a choice: never carried to a copy (CR 707.2 copies
    # printed values and decisions, and "other effects … are not copied").
    uncounterable_by: str | None = None
    # For a triggered ability on the stack: event data captured at fire time that the
    # effect handler reads at resolution (e.g. the dead creature's name, the damage
    # amount, the player who was dealt damage, an optional-pay cost).
    trigger_context: dict | None = None
    # CR 603.7d: what a **delayed** triggered ability's creating effect had
    # in its resolution scratchpad, frozen when the ability was created.
    #
    # Its own field rather than the trigger context above, because the two
    # are different questions and the readers are told apart by which one
    # they ask: ``amount_from_trigger`` / ``bound_permanent_id`` are about
    # the firing *event*, while ``amount_from`` / ``permanents_from`` are
    # about an earlier step of the same *effect* -- and for a delayed
    # ability that earlier step ran a turn ago, so its record can only have
    # travelled here. Left empty the second kind reads nothing and the
    # ability does nothing: Melee's "remove those creatures from combat"
    # and Cycle of Life's counter both resolved onto an empty scratchpad.
    captured_results: dict = field(default_factory=dict)
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
    # CR 108.3: the seat that **owns** this object's card, which is where
    # CR 400.3 sends it whenever it leaves the stack for a graveyard, a hand, a
    # library or exile — resolving (CR 608.2n), countered (CR 701.6a), removed
    # with every target illegal (CR 608.2b), exiled by an effect or by "end the
    # turn" (CR 724.1b), or bounced. Left off, it is the caster, which is right
    # for every spell cast out of its caster's own hand and is what
    # ``__post_init__`` fills in. The cast path sets it when a permission opened
    # *another* seat's zone (Psychic Theft, Grinning Totem): the caster
    # controls the spell (CR 108.4) and does not own it, and every bin site used
    # to read ``caster_index`` as the owner, so a stolen Shock resolved into the
    # thief's graveyard.
    #
    # Fixed at construction, never recomputed from ``caster_index``: an effect
    # that changes who controls a spell does not change who owns its card.
    owner_index: int | None = None
    # CR 113.3b against 113.3c: this object is an **activated** ability — put
    # on the stack by a player announcing it (CR 602.2), with every target it
    # has chosen by that player and checked by the announcement gate. Set by
    # the three activation paths and by nothing else, so a triggered ability
    # and a hook-keyed object read False.
    #
    # A positive mark rather than "an ability that is not a trigger": the
    # effect label says ``triggered_`` for most triggers and not for all of
    # them, both kinds carry their printed line, and the reader that needs
    # this (``legality_resolution.vanished_graveyard_target_refusal``) must not answer for
    # a trigger — a trigger's target is stamped at its fire site, which is the
    # bug ROADMAP's CR 608.2b entry declines the rule over.
    activated: bool = False
    # CR 603.3d: this **triggered** ability's targets were *chosen for it* as
    # it was put on the stack — out of the list ``_trigger_target_candidates``
    # enumerates, by the ``trigger_target`` prompt's answer or its default —
    # rather than stamped by the fire site that announced it. The other half
    # of ``activated`` above, and positive for the same reason: a fire site's
    # stamp may be a slot nobody chose (the death sweep records the dying
    # permanent itself), so "has a target on it" says nothing about whether a
    # player picked it. Set by the two answers that record a chosen target
    # (``_resolve_trigger_target`` / ``_resolve_trigger_targets`` — unless the
    # answer is a default taken while a permanent was on its way to a
    # graveyard, ``Game.departing``, when the picker's list was the board
    # before the event), by
    # ``_stack_push`` for an entry trigger whose permanent spell named the
    # target and whose own list accepted it (``cast_announcement_fault``), by
    # the upkeep step for a pick made at its target prompt and accepted the
    # same way (``_enqueue_triggered_ability(targets_chosen=)``), and by
    # nothing else; what CR 608.2b may be asked of is
    # ``activated or targets_chosen`` (``legality.announced_by_a_choice``).
    targets_chosen: bool = False
    # CR 613.7d: when this object was put on the stack — the timestamp of the
    # continuous effect of any static ability it has that functions there
    # (CR 113.6b, CR 613.7a; ``engine/stack_statics.py``). Stamped by
    # ``Game._stack_push`` for an object that prints such an ability and left
    # None for every other one, because nothing else on the stack is ordered
    # by a timestamp. Without it the ability Torrent of Lava grants every
    # creature had no place in layer 6, and survived a loss of all abilities
    # that was newer than the spell.
    timestamp: int | None = None

    def __post_init__(self) -> None:
        if self.owner_index is None:
            self.owner_index = self.caster_index

    @property
    def is_ability(self) -> bool:
        """Whether this stack object is an ability rather than a spell.

        CR 113.3: an activated or triggered ability on the stack is not a spell,
        and two readers care which — the client's stack item type, and
        "becomes the target of **a spell**" (Forsaken Wastes), whose whole
        narrowing is this question. One property rather than two spellings of
        the same conjunction: a card that fires on one and not the other cannot
        disagree with the label the player is shown.

        A property, not a field, so nothing has to set it and it cannot go stale
        on an item some fire site built by hand.
        """
        return self.ability_instruction is not None or self.hook_key is not None


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
    # The same, for a target that is a **card in a graveyard** — carried over
    # from ``StackItem.target_graveyard_card`` unchanged (see there for why a
    # graveyard needs its own identity at all).
    #
    # A one-target graveyard spell never needed it: the resolution re-locates
    # the stamp into ``target_permanent_index`` before any handler runs, and
    # ``target`` says whose pile. A **roles** announcement can mix the two
    # zones — Goblin Welder names an artifact on a battlefield and an artifact
    # card in a graveyard — and then the index alone cannot say which slot
    # counts into which list, nor whose graveyard the second one is. So the
    # stamps travel, positionally, in role order, with ``None`` in every slot
    # whose object is a permanent.
    target_graveyard_card: object = None
    x_value: int | None = None
    source_permanent: Permanent | None = None
    # The printed line of the activated ability being resolved, carried through
    # from ``StackItem.ability_text`` unchanged. One fact, one name — this is
    # the same string that field holds, not a second reading of the card.
    #
    # "This creature **loses this ability**" (Tempest's Licids) is what needs
    # it: the ability that goes away is the one that ran, and a handler matching
    # by text would have to guess between two lines whose printed words differ
    # only in a mana symbol. None for a spell and for a triggered ability,
    # neither of which has one.
    ability_text: str | None = None
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
    # ``(target, target_permanent_id, target_permanent_index)`` as a several-
    # **role** announcement left them, saved by
    # ``handlers/control_flow._role_scoped`` when it narrows the channels above
    # to one role's object. None until a role scopes the context. Every later
    # role is resolved against this rather than against the narrowed channels:
    # a branch inside one role's scope can spend another role (Crooked Scales'
    # toll buys a repeat of the whole flip, opponent's creature included).
    announced_targets: tuple | None = None
    # **This resolution's targets were chosen by a player's announcement** —
    # a spell (CR 601.2c) or an activated ability (CR 602.2b), whose every
    # owed target was named by its caller or defaulted from the picker's own
    # list as it was announced (``engine/bare_announcements.py``). So what the
    # object did not name, nothing names: the target resolver
    # (``handlers/_common.pick_target_permanent``) answers with the announced
    # permanent or with nobody, and never looks along a battlefield for
    # another.
    #
    # False for a triggered ability, a delayed one, and every context a turn
    # step or a hook builds by hand: a trigger's target is chosen at its fire
    # site (CR 603.3d), which is its own seam and still leaves some of them
    # unannounced (``_UNANNOUNCED_TRIGGER_TARGETS``).
    announced: bool = False


def chosen_damage_source(
    game: Game,
    *,
    seat: int | None = None,
    permanent_index: int | None = None,
    stack_index: int | None = None,
):
    """The object a "source of your choice" announcement named, or None.

    CR 609.7a: a chosen damage source may be a permanent or a spell on the
    stack, and the two arrive on different fields — ``seat`` plus
    ``permanent_index`` for the first, a bottom-first ``stack_index`` for the
    second. A spell is recorded as its ``CardDefinition``, which is the source
    a spell deals its damage with (CR 109.5) and the identity
    ``damage_redirects.source_matches`` then compares.

    Here rather than in either announcement path because **both** write the
    ``chosen_source`` key declared above this file's dataclasses:
    ``mixins/stack/activation.py`` has since Jade Monolith, and
    ``mixins/stack/casting.py`` since Kor Chant — and a second copy of six
    lines is how the two would come to disagree about which end of the stack an
    index counts from. The permanent is resolved through ``permanent_at``, the
    control seam's bounds-checked reader, rather than by subscripting a
    battlefield list.

    None is a legal outcome: an announcement that named no source (an AI, a
    headless call) has made no choice, and each reader decides what that means
    for its own card — a ``uses=1`` shield falls back to answering any source,
    a record that lasts the whole turn arms nothing.
    """
    if seat is not None and permanent_index is not None:
        # The seat is bounds-checked here and the slot inside ``permanent_at``.
        # Not belt and braces: ``controlled_by`` subscripts ``game.players``
        # directly, so a seat past the table raises and a *negative* one wraps
        # round to the last seat — which for an out-of-range announcement would
        # arm the record against a permanent on somebody else's board rather
        # than against nothing.
        if not (isinstance(seat, int) and 0 <= seat < len(game.players)):
            return None
        return game.permanent_at(seat, permanent_index)
    if stack_index is not None and 0 <= stack_index < len(game.stack):
        return game.stack[stack_index].card
    return None


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
