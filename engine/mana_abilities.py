"""What a mana ability is (CR 605.1a), and what running one inline needs.

A question about an **ability**, asked of its compiled program and never of
the board: whether it could add mana, requires no target, is no loyalty
ability, and moves no card to or from a library. :func:`is_mana_ability` is
the one predicate, because the harder of its callers is a *restriction* —
"activated abilities can't be activated unless they're mana abilities"
(Faith's Fetters) — and a second reading would shut off an ability the rules
leave open, or leave one open they shut. The library criterion's effect half
is asked **fail-closed** (:data:`LIBRARY_SAFE_ZONE_KINDS`, each entry a card
somebody read; ``tests/engine/test_mana_ability_library_criterion.py``).

Beside it, what the readers of that predicate share: a land's intrinsic mana
ability as an ability object (:data:`INTRINSIC_LAND_MANA_ABILITY`, CR 305.6),
whether a card has an activated ability that isn't one (Tsabo's Web), the
walk into every step an instruction carries (:func:`_every_nested_step`, read
by the mana readers next door), and the two facts a site that runs a mana
ability without the stack needs — whether it asks a player anything
(:func:`carries_an_offer`, Rhystic Cave) and its colour choice answered by the
colour named with the activation (:func:`answer_color_choices`, CR 605.3b).

It shared ``engine/mana_payment.py`` with the payment until the split round
before Fifth Dawn, and neither half read the other: the payment plans a cost
from a pool and a list of lands and never asks what an ability is, and this
reads an ability and never a cost. Its readers are the activation path, the
tap seam (``mixins/land_mana_taps.py``), the CR 602.5 prohibitions, the AI's
mana sources, and the readers beside the payment (``board_payment``,
``mana_wants``, ``mana_drawbacks``, ``mana_could_produce``).
"""

from __future__ import annotations

# `grammar.lower` rather than `lowering.categories` or `lowering.control_flow`
# for the step walk: it has lived in both, and each move took the old address
# with it. The name has one home and this is it.
from .grammar.lower import (
    OFFER_BRANCH_KEYS, WRAPPER_KINDS, nested_instructions, offer_branches,
)
from .grammar.lowering.categories import INSTRUCTION_CATEGORIES
from .oracle_types import OracleInstruction


#: Instruction kinds that put mana into a pool. CR 605.1a's "could add mana to
#: a player's mana pool" is a question about what the ability *does*, so it is
#: asked of the compiled program rather than of the printed words — a land that
#: says "add {G}" and one that says "add one mana of any color" are the same
#: kind of ability and neither spells the test out.
MANA_PRODUCING_KINDS: frozenset[str] = frozenset({
    "add_mana_from_text",
    "sacrifice_creature_for_mana",
    "sacrifice_self_for_mana",
    "channel_life_for_mana",
})

#: Costs that move a card to or from a library, as fields of
#: ``ActivatedAbilityCost`` - each a count, zero for "no such cost". CR 605.1a's
#: fourth criterion (in the rules since the September 2026 edition): an
#: activated ability is a mana ability only if "its cost and effect don't move
#: any card to or from a library". Milling (Millikin, Charmed Pendant) and
#: exiling the top of a library move one *from* it; a card put from a hand on
#: top moves one *to* it, and so do cards put from a graveyard on the bottom
#: (Battlefield Scrounger).
LIBRARY_MOVING_COSTS: tuple[str, ...] = (
    "mill_cards", "exile_top_of_library", "hand_to_library_top",
    "graveyard_to_library_bottom",
)

#: The effect half of the same criterion, asked **the other way round**. Every
#: effect that moves a card between zones lowers into one grammar category
#: (:data:`_ZONE_MOVING_CATEGORY`, 166 kinds), and a step of that category
#: beside an add-mana step is *presumed* to move a card to or from a library
#: unless it is one of these - the zone-moving steps the pool's mana abilities
#: carry that have been read and do not:
#:
#: * ``sacrifice_self`` - battlefield to graveyard (Gemstone Mine and the five
#:   storage lands sacrifice themselves when the last counter is gone);
#: * ``return_self_instead_of_untapping`` - battlefield to hand, later
#:   (Undiscovered Paradise);
#: * ``reveal_cards_from_hand`` - nothing moves (Metalworker).
#:
#: Presumed, because the two ways of being wrong are not alike. A mana ability
#: read as an ordinary one still works, through the stack; an ordinary ability
#: read as a mana ability can be activated in the middle of a payment and
#: cannot be responded to, which is the card doing more than it prints with
#: nothing to show for it. A draw is the step the pool actually carries ("Add
#: one mana of any color. **Draw a card.**" - Chromatic Sphere, Odyssey's five
#: Eggs), and a set collected off the pool would have held that one kind and
#: called "{T}: Add {G}. Mill a card." a mana ability the day it was printed.
#: ``tests/engine/test_mana_ability_library_criterion.py`` holds every such
#: step in either manifest role to a reviewed verdict, so an entry is added
#: here by reading a card, never by default.
LIBRARY_SAFE_ZONE_KINDS: frozenset[str] = frozenset({
    "sacrifice_self",
    "return_self_instead_of_untapping",
    "reveal_cards_from_hand",
})

#: The grammar category of an effect that moves a card between zones
#: (``lowering/categories.INSTRUCTION_CATEGORIES``).
_ZONE_MOVING_CATEGORY = "zones"

#: A step that sets up a **later** ability rather than doing its work now. CR
#: 603.7: "An effect may create a delayed triggered ability that can do
#: something at a later time" - the delayed ability is another ability, with its
#: own resolution, and what *it* moves is not moved by the cost or the effect of
#: the ability that created it. So "Add one mana of any color. Draw a card at
#: the beginning of the next turn's upkeep." (Barbed Sextant, Astrolabe) is a
#: mana ability and "Add one mana of any color. Draw a card." (Chromatic Sphere)
#: is not. No ruling says so of the Sextant by name; the Sphere's, Millikin's
#: and Selvala's (all 2026-08-05) are each about a card moved as the ability is
#: activated or resolves, and the mischief the criterion answers - a card drawn
#: or revealed in the middle of paying for something - is one a draw at the next
#: upkeep cannot do.
_LATER_ABILITY_KINDS: frozenset[str] = frozenset({"create_delayed_trigger"})


def has_nonmana_activated_ability(card) -> bool:
    """Whether *card* has an activated ability that isn't a mana ability
    (CR 602.1, CR 605.1a) — "each land with an activated ability that isn't a
    mana ability" (Tsabo's Web).

    Asked of the **compiled program**, which is where a keyword that is an
    activated ability has already been written out as one: cycling is
    CR 702.29a's "[cost], Discard this card: Draw a card", so a cycling land
    answers yes although the ability never functions on the battlefield — the
    rule asks what the object *has*, not what it could activate right now.
    A basic land's intrinsic mana ability (CR 305.6) is no activated ability
    the program carries and would be a mana ability if it were, so a Forest
    answers no either way.

    Pass a permanent's ``effective_card``, never its printed one: an ability
    gained or lost since it entered counts as it is now.
    """
    from .oracle import compile_card_oracle

    return any(
        not is_mana_ability(ability)
        for ability in compile_card_oracle(card).activated_abilities
    )


def _intrinsic_land_mana_ability():
    from .activated_ability_cost import ActivatedAbilityCost
    from .oracle_types import ParsedActivatedAbility

    return ParsedActivatedAbility(
        source_line="",
        normalized_effect="",
        supported=True,
        cost=ActivatedAbilityCost(mana={}, requires_tap=True),
        effect_kind="activated_mana",
        instruction=OracleInstruction("add_mana_from_text", "", {}),
    )


#: CR 305.6's "{T}: Add [mana symbol]" — the mana ability a basic land type
#: gives a land, which no text carries and so no compiled program holds. A
#: question asked *of an ability* (CR 602.5's prohibitions: "can't be
#: activated", "unless they're mana abilities", "with {T} in their costs") has
#: to be handed one, and a Forest has nothing else to hand: this is that
#: ability as the rules define it — a {T} cost, no other, an effect that adds
#: mana and targets nothing, and no printed line for a clause to sit on. What
#: it adds is not here (the land's summary and its types say that); it is the
#: answer to what kind of ability tapping the land activates.
INTRINSIC_LAND_MANA_ABILITY = _intrinsic_land_mana_ability()


def is_mana_ability(ability) -> bool:
    """Whether *ability* is a mana ability (CR 605.1a).

    Three clauses, and only two of them can be answered here. It must be able to
    add mana, which the instruction kind says; it must not target, which the
    payload says. The third — "not a loyalty ability" — is a property of the
    cost, and a loyalty ability never produces mana in this pool, so asking the
    kind answers it too.

    Its own function because two callers need the same answer and the harder one
    is a *restriction*: "activated abilities can't be activated unless they're
    mana abilities" (Faith's Fetters) is a rule about this predicate, and a
    second reading of it would shut off an ability the rules leave open — or,
    worse, leave one open that should be shut.

    **It takes an ability or a bare instruction, and it used to take only one.**
    ``getattr(ability, "instruction", None)`` is None for an ``OracleInstruction``,
    so the four call sites in ``ai_policy``/``ai_valuation`` that pass one — every
    caller on the AI side — got False for every mana ability there is. Nothing
    raised and nothing was missing; the AI simply never recognised a mana ability
    through those paths.

    **And "could add mana when it resolves" is asked of the whole effect, not of
    its first step.** "{T}: Add {W} or {U}. This land deals 1 damage to you"
    (Adarkar Wastes and the four other Ice Age painlands) and "{T}: Add {U} or
    {B}. Put a depletion counter on this land" (the five depletion lands) lower
    to a ``sequence``, whose kind is not in :data:`MANA_PRODUCING_KINDS` — so
    twelve shipped cards answered False here. That is CR 605.1a read backwards:
    the rule asks whether the ability *could* add mana, and a two-step effect
    whose first step does is a mana ability with a drawback, which is the whole
    design of both cycles. The consequence was silent in the direction that does
    more work — they used the stack (CR 605.3a says they must not), Imprison's
    "a {T} ability that isn't a mana ability" would have fired on them, and an
    effect shutting off everything but mana abilities shut them off too.

    The no-target clause is asked of every step for the same reason: a sentence
    that adds mana and then targets something is not a mana ability, and asking
    only the outer instruction would have admitted it.

    **And "doesn't require a target" is not the same question as "carries a
    ``targets`` payload"** (CR 605.5a). That key is how a lowering spells a
    targeted *object*; a targeted **player** is spelled as a payload value out
    of the lowering's own reference vocabulary — ``"target"``,
    ``"target_player"``, ``"target_opponent"`` — on whatever key the effect
    happens to use. Witch Engine's "Target opponent gains control of this
    creature" arrives as ``{"who": "target_opponent"}`` and so read as a mana
    ability, which is the one card in the pool that is famously *not* one for
    exactly this reason. Asked by value at any depth rather than by naming the
    keys, because the key is the effect's business and the word is the rule's.

    **The loyalty clause is real, and it is the third one this function used to
    say it could skip.** The docstring above claimed "a loyalty ability never
    produces mana in this pool, so asking the kind answers it too" — measurably
    false: Chandra, Heart of Fire's "−9: … Add six {R}" is shipped, and it read
    as a mana ability. A loyalty cost is a property of the **cost**, so it can
    only be answered when this is handed an ability; given a bare
    ``OracleInstruction`` there is no cost to read and the caller gets the
    other two clauses alone. That is the honest answer rather than a silent
    one — the four AI call sites pass a bare instruction and no planeswalker
    reaches them.

    **And an ability that moves a card to or from a library is not a mana
    ability** — the fourth criterion, which CR 605.1a has carried since the
    September 2026 edition: "…and its cost and effect don't move any card to
    or from a library." It first reached this function as a *ruling* (Millikin,
    2026-08-05: "not a mana ability. Players can respond to it, and it can't be
    activated in the middle of paying for a cost"), while the rules file this
    repo shipped was the April edition, and was held to the one cost that
    ruling was written about. Both halves are asked now:

    * the **cost** (:data:`LIBRARY_MOVING_COSTS`) — a mill, the top of a
      library exiled, a card put on top of one. A property of the cost, like
      the loyalty clause, so a caller holding a bare instruction is not told;
    * the **effect** (:func:`moves_a_library_card`) — "Add one mana of any
      color. Draw a card." (Chromatic Sphere, the five Eggs). Asked of the
      steps the ability carries out *as it resolves*: a delayed ability it
      sets up is another ability (:data:`_LATER_ABILITY_KINDS`, with the
      reasoning), so Barbed Sextant's draw at the next upkeep leaves its mana
      ability one. And asked fail-closed: a zone-moving step that nobody has
      read is presumed to reach a library (:data:`LIBRARY_SAFE_ZONE_KINDS`).

    It is those cards' printed reminder text made true: an ability that uses
    the stack is activated whenever its controller has priority, which is
    "only as an instant". The rule's last sentence — "Do not take into account
    replacement effects that may apply, other than self-replacement effects" —
    is why this reads the compiled ability and never the board: a mana ability
    whose draw something would replace is still not a mana ability, and one
    that a replacement would *make* draw still is.
    """
    instruction = getattr(ability, "instruction", ability)
    if instruction is None or not hasattr(instruction, "kind"):
        return False
    cost = getattr(ability, "cost", None)
    if getattr(cost, "loyalty", None) is not None:
        return False
    if any(getattr(cost, field, 0) for field in LIBRARY_MOVING_COSTS):
        return False
    steps = (instruction, *_every_nested_step(instruction))
    if not any(step.kind in MANA_PRODUCING_KINDS for step in steps):
        return False
    if moves_a_library_card(instruction):
        return False
    return not any(
        (step.payload or {}).get("targets") or _names_a_target(step.payload)
        for step in steps
    )


def moves_a_library_card(instruction) -> bool:
    """Whether resolving *instruction* moves a card to or from a library, as
    far as CR 605.1a's fourth criterion is concerned: any step it carries out
    now (:func:`steps_carried_out_now`) that moves a card between zones and is
    not one of :data:`LIBRARY_SAFE_ZONE_KINDS`."""

    return any(
        INSTRUCTION_CATEGORIES.get(step.kind) == _ZONE_MOVING_CATEGORY
        and step.kind not in LIBRARY_SAFE_ZONE_KINDS
        for step in steps_carried_out_now(instruction)
    )


def steps_carried_out_now(instruction) -> tuple:
    """*instruction* and every step inside it that happens as it resolves —
    :func:`_every_nested_step` that does not open a step which only sets up a
    later ability (:data:`_LATER_ABILITY_KINDS`).

    The walk CR 605.1a's fourth criterion needs and the first three do not:
    "could add mana" and "doesn't require a target" are true of an ability
    whatever part of it says so, while "its … effect [doesn't] move any card to
    or from a library" is about what this ability's own resolution does.
    """
    if instruction is None or not hasattr(instruction, "kind"):
        return ()
    found = [instruction]
    if instruction.kind in _LATER_ABILITY_KINDS:
        return tuple(found)

    inner = nested_instructions(instruction)
    if inner is None:
        inner = offer_branches(instruction)
    for step in inner or ():
        found.extend(steps_carried_out_now(step))
    return tuple(found)


def carries_an_offer(instruction) -> bool:
    """Whether any step of *instruction* asks a player something — an offer
    (``may``) or a toll (``unless_player_pays``).

    A mana ability may (CR 605.1a is silent on it): "Add one mana of that color
    **unless any player pays {1}**" (Rhystic Cave). What such an ability cannot
    be is run by a path that has to finish before it returns — the tap seam,
    part-way through a payment — because the mana does not exist until every
    seat it asks has answered.
    """

    if instruction is None or not hasattr(instruction, "kind"):
        return False
    return any(
        step.kind in OFFER_BRANCH_KEYS
        for step in (instruction, *_every_nested_step(instruction))
    )


#: How a lowering spells "this names a target" as a payload **value**, at any
#: depth. Collected off the pool rather than invented: these three are the only
#: ``target``-prefixed strings any compiled payload in either manifest role
#: holds as a value, and every one of them is CR 115's word.
_TARGET_REFERENCE_WORDS: frozenset[str] = frozenset({
    "target", "target_player", "target_opponent",
})


def _names_a_target(value) -> bool:
    """Whether *value* holds one of :data:`_TARGET_REFERENCE_WORDS` anywhere.

    Values only — a payload **key** named ``targets_filter`` or ``target_color``
    describes a target the sentence has already announced elsewhere or a colour
    the effect asks about, and reading keys would make every "change the colour
    of target permanent" rider answer this question twice.
    """
    if isinstance(value, str):
        return value in _TARGET_REFERENCE_WORDS
    if isinstance(value, dict):
        return any(_names_a_target(inner) for inner in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_names_a_target(inner) for inner in value)
    return False


def _every_nested_step(instruction) -> tuple:
    """Every instruction inside *instruction*, at any depth.

    Through the grammar's own reader of what a control-flow instruction
    contains, so "which keys hold steps" has one answer here: a branch key
    added there and not here would be an effect this predicate cannot see into.

    Named apart from ``instruction_targets._nested_steps`` on purpose. That one walks a
    single level off a *third* copy of the step-key table
    (``instruction_targets._WRAPPER_STEP_KEYS``), and this one walks all of them off the
    grammar's; sharing the name would be one word for two facts, which is the
    shape ``_per_recipient_count`` was recorded under in SET_PLAYBOOK's Known
    gaps until VIS wave 4 split it into ``_amounts._recipient_seat_count`` and
    ``_sweeps._per_recipient_multiplier``. That the two tables exist at all is
    the real debt, and it belongs to whoever next needs a third reader.
    """
    inner = nested_instructions(instruction)
    # **And an offer's branches**, which the category walk must not open and
    # this one must. "Add one mana of that color **unless any player pays
    # {1}**" (Rhystic Cave) puts the whole of its mana behind a toll, and CR
    # 605.1a asks whether the ability *could* add mana — it could, and
    # "regardless of … timing restrictions (such as 'Activate only as an
    # instant')" (CR 605.1) it is a mana ability. Opening the two offer kinds
    # moved no compiled ability's answer in either manifest role but the Cave's.
    if inner is None:
        inner = offer_branches(instruction)
    if not inner:
        return ()
    found: list = []
    for step in inner:
        found.append(step)
        found.extend(_every_nested_step(step))
    return tuple(found)


def answer_color_choices(instruction, color: str | None):
    """*instruction* with every "Choose a color" its controller makes answered
    by *color* — the colour named with a **mana ability's** activation.

    CR 605.3b: a mana ability does not use the stack and resolves the moment it
    is activated, so the colour its activator names with the activation is the
    answer to the choice it makes as it resolves (CR 608.2d). "{T}: Choose a
    color. Add one mana of that color unless any player pays {1}" (Rhystic
    Cave). Called only by the two sites that run a mana ability inline — the
    activation path's CR 605.3b branch and the tap seam — so an ability that
    goes on the stack keeps asking at resolution.

    A choice somebody *else* makes (a ``chooser`` on the payload) is left to
    ask, and so is any step this walk cannot see into: unanswered is the
    prompt, which is the safe direction. Rebuilt rather than mutated, because a
    compiled instruction is shared by every copy of the card.
    """
    if not color or instruction is None:
        return instruction
    if instruction.kind == "choose_color":
        if (instruction.payload or {}).get("chooser"):
            return instruction
        return OracleInstruction(
            instruction.kind, instruction.value,
            {**instruction.payload, "color": color},
        )
    keys = WRAPPER_KINDS.get(instruction.kind) or OFFER_BRANCH_KEYS.get(instruction.kind)
    if not keys:
        return instruction
    changed = {
        key: tuple(
            answer_color_choices(step, color)
            for step in instruction.payload.get(key) or ()
        )
        for key in keys
        if instruction.payload.get(key)
    }
    if all(
        new is old
        for key, steps in changed.items()
        for new, old in zip(steps, instruction.payload.get(key) or ())
    ):
        return instruction
    return OracleInstruction(
        instruction.kind, instruction.value, {**instruction.payload, **changed}
    )


__all__ = [
    "INTRINSIC_LAND_MANA_ABILITY", "LIBRARY_MOVING_COSTS", "LIBRARY_SAFE_ZONE_KINDS",
    "MANA_PRODUCING_KINDS", "answer_color_choices", "carries_an_offer",
    "has_nonmana_activated_ability", "is_mana_ability", "moves_a_library_card",
    "steps_carried_out_now",
]
