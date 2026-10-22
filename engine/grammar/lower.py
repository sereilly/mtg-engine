"""Lower a parsed AST into ``OracleInstruction`` sequences.

The grammar deliberately stops at the IR rather than interpreting the AST
directly against game state. Three reasons:

1. The 121 registered effect handlers encode game-rule behavior that is
   orthogonal to parsing — CR 608.2b fizzling, state-based-action batching,
   replacement-effect dispatch, divided-damage arithmetic. Re-implementing that
   inside an AST interpreter would regress it.
2. ``OracleInstruction`` has many consumers beyond resolution: ``ai_policy``
   scores by instruction kind, ``StackItem`` carries instructions,
   ``trigger_utils`` filters on them, the web layer serializes them. Keeping the
   IR stable isolates the parser rewrite from the AI and UI at the same time.
3. Strangler-fig migration needs the old and new front ends to be *comparable*.
   Both emit instructions, so "grammar agrees with the legacy rules" is a
   dataclass equality check rather than a full game simulation.

Payload keys reproduce what the legacy rules have always emitted, byte for
byte; anything new is additive and read with ``payload.get`` defaults on the
handler side.

**This file is the dispatch.** ``lower_statement`` routes one AST node to its
family, ``lower_ability`` wraps that for a whole line (the `may`, sequence and
condition wrappers, the lord-buff and static-ability readings), and
``categories_of`` answers what a lowered line touches. The per-effect lowerings
live in ``grammar/lowering/``, one module per subject, mirroring
``grammar/effects/`` name for name.

``INSTRUCTION_CATEGORIES`` and ``lower_statement`` are re-exported here because
callers outside the package import them from this module
(``tests/engine/test_grammar_categories.py``, ``grammar/__init__.py``); moving
the table did not move its address.

**What a wrapper carries is defined here**, not re-exported: ``WRAPPER_KINDS``,
the two walks that read into a lowered instruction (``nested_instructions``,
``offer_branches``) and ``categories_of`` itself, which until the Phase 0 before
Odyssey reached this module from the bottom of ``lowering/control_flow.py``.
The section's own header says why it is here and not there.
"""

import dataclasses

from ..oracle_types import OracleInstruction
from . import ast
from .derived import derived_instruction_for_line
from .errors import LoweringError
from .statics import _lower_static_ability
from .lowering._events import EVENT_PRODUCES
from .lowering._roles import describe_sequence_target_roles
from .lowering import (
    GRAMMAR_ONLY_PAYLOAD_KEYS,
    INSTRUCTION_CATEGORIES,
    _COST_PRODUCES,
    _fused_upkeep_pay_to_untap,

    _lower_modal_head,
    _lower_condition,
)


# ---------------------------------------------------------------------------
# What a wrapper carries
# ---------------------------------------------------------------------------
#
# `categories_of` walks a lowered sequence and has to look *inside* every
# composer before it can say what a line touches. Which kinds are composers,
# and under which payload keys each keeps its steps, is a fact about a lowered
# **line** rather than about any one family: the rows below are built by
# `lowering/sequences`, `loops` and `repeats`, by every family that folds two
# steps into one `sequence`, and by `wrap_requested_repeat` further down. This
# file is the one module all of them pass through, and the only one in the
# grammar that reads the table.
#
# It has had two homes before this one. It began at the bottom of
# `lowering/categories.py` and left at the thousand-line guard for
# `lowering/control_flow.py`, as "the kinds the four lowerings above emit" —
# written hours after `sequence` and `if_then` had left that module for
# `lowering/sequences`, as `for_each` already had for `loops`. So it was a
# lodger there from the day it arrived: nothing in that module called it and it
# called nothing back. It came here at the Phase 0 before Odyssey, with that
# module eight lines under the guard. Not to a module of its own under
# `lowering/`, for ``by_node.py``'s stated reason — "a module inside that
# package that no family reads would be neither a family nor a floor" — and
# that module's other rule, that a registry leaves the dispatcher, is about the
# half that grows with every card: this one has gained three rows since Mirage.
#
# Public names rather than underscore-prefixed ones: they have callers outside
# the grammar (`engine/mana_payment.py`, `scripts/parse_coverage.py`).
# Control-flow wrappers take the categories of whatever they wrap, so gating
# "damage" is enough to turn on a sequence of damage instructions without
# inventing a category nobody could reason about.
#
# ``may`` is deliberately NOT in here: it gets its own ungated category in
# `lowering/categories.py`, because an offer is not the same switch as the
# effect behind it. Wrapping it with the others would let "optional" be turned
# off under a family that is on, which is a card that performs its offer's
# consequence without asking.
WRAPPER_KINDS: dict[str, tuple[str, ...]] = {
    "sequence": ("steps",),
    "if_then": ("then", "else"),
    "for_each": ("effect",),
    # A round of offers repeated until nobody takes it (Eureka). A wrapper for
    # the same reason ``for_each`` is: what the round *does* is the act it
    # carries, and the repetition is not an effect of its own.
    "repeat_offer_round": ("action",),
    # A whole printed process its controller may run again (Forbidden Ritual).
    # The same reason again: what the process *does* is the steps it carries.
    "repeat_optional_process": ("steps",),
    # A process repeated while a condition about the round holds (Grindstone).
    # The third repeat that is a wrapper, and for the same reason as the two
    # above it: what the round *does* is the steps it carries, and the stopping
    # question is not an effect.
    "repeat_process_while": ("steps",),
    # A process a toll inside it may ask for again (Crooked Scales). The fourth
    # repeat that is a wrapper, and the same reason once more: what the round
    # *does* is the steps it carries, and asking for another is not an effect.
    "repeat_process_on_request": ("steps",),
    # A process repeated until a condition about its rounds holds (Tainted
    # Pact). The fifth repeat that is a wrapper, and the same reason again.
    "repeat_process_until": ("steps",),
}


#: Where an **offer** keeps the instructions behind its answers — the two kinds
#: ``WRAPPER_KINDS`` deliberately leaves out, for the reason its comment gives:
#: an offer is a switch of its own, so ``categories_of`` must not descend into
#: one. A reader asking what an effect *could do* has the opposite need. CR
#: 605.1a's "could add mana to a player's mana pool when it resolves" is true
#: of "{T}: Choose a color. Add one mana of that color unless any player pays
#: {1}" (Rhystic Cave), whose only mana sits behind the toll.
OFFER_BRANCH_KEYS: dict[str, tuple[str, ...]] = {
    "may": ("action", "then", "otherwise"),
    "unless_player_pays": ("unpaid", "paid"),
}


def offer_branches(instruction: OracleInstruction) -> tuple[OracleInstruction, ...] | None:
    """The instructions behind an offer's answers, or None if it is not one.

    :func:`nested_instructions`' sibling for the kinds it must not open — see
    :data:`OFFER_BRANCH_KEYS`. Separate rather than a flag on that function so
    no caller of the category walk can open an offer by accident.
    """
    keys = OFFER_BRANCH_KEYS.get(instruction.kind)
    if keys is None:
        return None
    return tuple(
        step for key in keys for step in (instruction.payload.get(key) or ())
    )


def nested_instructions(instruction: OracleInstruction) -> tuple[OracleInstruction, ...] | None:
    """The instructions a wrapper carries, or None if it is not one.

    ``choose_one`` is a wrapper too, and its options are ``{label, instruction}``
    pairs rather than a bare tuple — the modal shape the pending-choice prompt
    reads. Its categories are its options', because that is what the card can
    actually do; giving it a category of its own would say the *choosing* is the
    effect.
    """
    if instruction.kind == "create_delayed_trigger":
        # A delayed ability's effect is one instruction rather than a list, so
        # it cannot ride `WRAPPER_KINDS` above — but it is a wrapper all the
        # same, and an inner effect no category gates must ungate the line that
        # arms it. An entry with no instruction is an ability that would fire
        # into nothing, which is the empty-wrapper refusal below.
        inner = instruction.payload.get("instruction")
        return (inner,) if inner is not None else ()
    if instruction.kind == "arm_draw_replacement":
        # "The next time you would draw a card this turn, instead <effect>."
        # (Mangara's Tome.) A wrapper for ``create_delayed_trigger``'s reason
        # exactly — the effect is one instruction rather than a list, and what
        # the line touches is what the armed effect touches.
        inner = instruction.payload.get("instruction")
        return (inner,) if inner is not None else ()
    if instruction.kind == "choose_one":
        return tuple(
            mode["instruction"] for mode in instruction.payload.get("modes") or ()
        )
    nested_keys = WRAPPER_KINDS.get(instruction.kind)
    if nested_keys is None:
        return None
    nested: tuple[OracleInstruction, ...] = ()
    for key in nested_keys:
        nested += tuple(instruction.payload.get(key) or ())
    return nested


def categories_of(instructions: tuple["OracleInstruction", ...]) -> frozenset[str]:
    """Migration categories covered by a lowered instruction sequence.

    Here rather than in ``lowering/categories.py`` because that module is a
    *registry* and this is a walk: every step of it asks
    :func:`nested_instructions`, which lives in this file, and a wrapper whose
    contents it could not see would report the wrapper's own kind as the whole
    answer. The table is imported rather than the walk exported, which is the
    direction the layering allows.
    """
    found: set[str] = set()
    for instruction in instructions:
        nested_keys = nested_instructions(instruction)
        if nested_keys is not None:
            if not nested_keys:
                return frozenset({"__ungated__"})
            inner = categories_of(nested_keys)
            if "__ungated__" in inner:
                return frozenset({"__ungated__"})
            found |= inner
            continue
        category = INSTRUCTION_CATEGORIES.get(instruction.kind)
        if category is None:
            return frozenset({"__ungated__"})
        found.add(category)
    return frozenset(found)


#: Where a wrapper keeps the instructions it carries, **for rewriting** — every
#: row of :data:`WRAPPER_KINDS` plus the two an *offer* holds.
#:
#: Derived from the table above rather than copied, so a
#: wrapper added there is rewritable by construction. Here, beside
#: :func:`lower_ability`, because that function is the only caller and the only
#: place a condition and the instructions it is about are both in view. ``may`` is the difference and it is a real one:
#: ``categories_of`` must **not** descend into an offer, because the offer is
#: itself an effect with a category of its own (a prompt the card prints), while
#: a rewrite that stopped at it would leave the instruction it wraps untouched —
#: which for Carpet of Flowers is the whole ability.
_REWRITE_NESTED_KEYS: dict[str, tuple[str, ...]] = {
    **WRAPPER_KINDS,
    "may": ("action", "otherwise"),
}


def stamp_payload_key(
    instructions: tuple["OracleInstruction", ...],
    *,
    kind: str,
    key: str,
    value: object,
) -> tuple["OracleInstruction", ...]:
    """*instructions* with *key* added to every instruction of *kind*, at any
    depth.

    "At the beginning of each of your main phases, **if you haven't added mana
    with this ability this turn**, you may add X mana…" (Carpet of Flowers.)
    The clause that reads the record and the instruction that writes it are two
    halves of one printed ability, and ``lower_ability`` is the only place both
    are in view — the same pairing argument ``_lower_steps`` makes for "if you
    do" and the step it reads. The mana instruction sits inside the offer, so
    the stamp has to reach through it.

    Rebuilt rather than mutated: an ``OracleInstruction`` is shared by every
    copy of the card and its payload is read as a value everywhere.
    """
    def rewrite(instruction: "OracleInstruction") -> "OracleInstruction":
        payload = instruction.payload
        nested_keys = _REWRITE_NESTED_KEYS.get(instruction.kind)
        if nested_keys:
            changed = {
                name: tuple(rewrite(step) for step in payload.get(name) or ())
                for name in nested_keys
                if payload.get(name)
            }
            if changed:
                payload = {**payload, **changed}
        if instruction.kind == kind:
            payload = {**payload, key: value}
        if payload is instruction.payload:
            return instruction
        return OracleInstruction(instruction.kind, instruction.value, payload)

    return tuple(rewrite(instruction) for instruction in instructions)

#: The node types whose lowering is *only* a name — one AST class, one
#: function, nothing to decide. These were 78 two-line branches of the chain
#: below: 156 lines saying what a dict says in 78, growing by three every time
#: a round adds a node. Dispatching them by type is what every other seam in
#: this engine already does (`EFFECT_HANDLERS` is the one the architecture
#: notes name), and it is what the module-size guard was pointing at — the
#: families were absorbing the work; the chain grew anyway, by construction.
#:
#: The chain below keeps every branch that *decides* something: a node whose
#: lowering depends on its own fields, on the firing event, or on which of
#: several kinds it should become.
#:
#: Read before the chain, which is safe by construction rather than by
#: inspection: no class in this table appears anywhere else in the chain and
#: none of them inherits from another, so at most one branch could ever have
#: matched a given node.
from .statement_dispatch import lower_statement


#: Where a repeat request can be printed: every key an instruction carries
#: other instructions under. Derived from :data:`_REWRITE_NESTED_KEYS` — every
#: wrapper plus the offer's two branches — so a wrapper added there is searched
#: by construction, and widened by the branch keys a *decision* holds. A flat
#: set rather than a per-kind table because this is a search and not a rewrite:
#: a key an instruction does not carry simply answers nothing.
_REQUEST_SEARCH_KEYS = tuple(sorted(
    {key for keys in _REWRITE_NESTED_KEYS.values() for key in keys}
    | {"then", "else", "unpaid", "paid", "steps"}
))


def _requests_a_repeat(instruction: OracleInstruction) -> bool:
    """Whether *instruction* or anything it carries asks for another round."""
    if instruction.kind == "request_process_repeat":
        return True
    for key in _REQUEST_SEARCH_KEYS:
        for step in instruction.payload.get(key) or ():
            if isinstance(step, OracleInstruction) and _requests_a_repeat(step):
                return True
    return False


def wrap_requested_repeat(
    instructions: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """One line's steps, wrapped in the loop a ``request_process_repeat`` asks for.

    Beside :func:`_lower_line_statement`, its one caller, and for CR 601.2c's
    roles walk's reason one function down: "this process" is the **line**, and
    that is the one place holding all of it. Here rather than in
    ``lowering/repeats.py`` with the five loops it joins, because the search
    above reads :data:`_REWRITE_NESTED_KEYS` and a ``lowering/`` family may not
    import the dispatcher back.

    Returns *instructions* unchanged when no step of them asked, which is every
    line in the pool but one — so nothing else's compiled program moves. The
    search descends through every wrapper's nested instructions and through an
    offer's branches, because that is where the marker is printed: Crooked
    Scales' sits in the ``then`` of a ``may`` inside the ``then`` of an
    ``if_then``, two levels below the line.

    The loop is put **around the whole tuple** rather than around the step that
    asked. What the card repeats is the process, not the sentence that bought
    another run of it; a loop around the last sentence would re-offer the toll
    without ever flipping the coin again.
    """
    if not any(_requests_a_repeat(step) for step in instructions):
        return instructions
    return (
        OracleInstruction(
            "repeat_process_on_request", "", {"steps": tuple(instructions)}
        ),
    )


def _lower_line_statement(
    statement: ast.Statement,
    *,
    produced: frozenset[str] = frozenset(),
    event: str | None = None,
    event_subject: object | None = None,
) -> tuple[OracleInstruction, ...]:
    """Lower the statement that is a line's *whole* effect.

    Identical to :func:`lower_statement` but for the one node whose meaning
    depends on occupying the whole clause: a modal head announces how many of
    the bulleted lines *below this line* the controller picks (CR 700.2), which
    is only true when it is what the line says. Nested, it refuses — see the
    `ModalNode` branch in `lower_statement`.
    """
    if isinstance(statement, ast.ModalNode):
        return _lower_modal_head(statement)
    # CR 601.2c is about the **line**, not about any one step of it: every
    # target a spell or an ability names is chosen in one announcement, so the
    # place to notice that a line announced two is the place that has the whole
    # line's instructions. ``describe_sequence_target_roles`` returns them
    # unchanged unless exactly two of them announce a target and the two can be
    # told apart from one target named twice — see there for the two ways a
    # line proves that.
    lowered = describe_sequence_target_roles(lower_statement(
        statement, produced, event=event, event_subject=event_subject
    ))
    # …and the same argument for a **repeat printed inside a sentence**.
    # "…unless you pay {3} and repeat this process" (Crooked Scales) names the
    # whole printed effect — the coin flip two sentences back included — from
    # two branches down inside the last of them, so the loop can only be put on
    # here. ``request_process_repeat`` is the marker the price reader left; the
    # wrapper's handler runs the round again whenever a round wrote it.
    #
    # After the roles walk rather than before it: that one reads the line's own
    # steps, and a line already folded into one wrapper has none.
    return wrap_requested_repeat(lowered)


def _rebind_blocking_pronoun(statement: ast.Statement) -> ast.Statement:
    """"Destroy target creature blocking **it**." (Urborg Panther.)

    "It" is a back-reference, and the noun parser reads it as one: nothing is
    printed after the word, so the referent is whatever the sentence bound
    earlier (``blocking_bound_target``). Under an activated ability whose
    *whole* effect is this one statement there is nothing earlier — the pronoun
    cannot mean the creature being chosen, since no creature blocks itself — so
    the only object it can name is the ability's own source (CR 109.5). That is
    the relation ``blocking_source`` already carries, and the same rewrite
    ``lowering/characteristics._resolve_per_each_pronoun`` makes one file over
    for Johtull Wurm's "for each creature blocking it".

    A rewrite here rather than a second parse rule, because the printed words
    are identical: what decides the referent is the sentence around them, and
    this is where the sentence is in view.

    Narrow on purpose, in three ways, each of which is a card the rewrite must
    **not** claim:

    * Only the statement a spec *targets*. Feint's "each creature blocking it"
      targets nothing and its "it" is the previous sentence's target.
    * Only a statement that is not a sequence — a second clause could have
      bound something for the pronoun to mean.
    * Only from an activated ability. A spell's own source is a card on the
      stack, which blocks nothing, and a trigger's event may itself bind the
      object the pronoun names.

    **A recipient list is walked too, not only a bare field.** ``DealDamage``
    carries its targets as a *tuple* (``recipients``), because one sentence may
    name several — so the field scan below saw no ``TargetSpec`` at all and
    "{R}: This creature deals 1 damage to target creature blocking **it**"
    (Flowstone Salamander) reached the lowering still carrying the pronoun,
    where it refused. The three narrowings above are unchanged: every element
    is tested on its own, and an element the rewrite does not claim is left
    exactly as it was.
    """
    if isinstance(statement, (ast.Sequence, ast.Conjunction)):
        return statement

    def _rebound(spec: object) -> object:
        if not isinstance(spec, ast.TargetSpec) or not spec.targeted:
            return None
        if not spec.filter.blocking_bound_target:
            return None
        return dataclasses.replace(
            spec,
            filter=dataclasses.replace(
                spec.filter, blocking_bound_target=False, blocking_source=True
            ),
        )

    changed = False
    updates: dict[str, object] = {}
    for field in dataclasses.fields(statement):
        value = getattr(statement, field.name, None)
        if isinstance(value, tuple):
            rebound = tuple(_rebound(item) or item for item in value)
            if rebound != value:
                updates[field.name] = rebound
                changed = True
            continue
        replacement = _rebound(value)
        if replacement is not None:
            updates[field.name] = replacement
            changed = True
    return dataclasses.replace(statement, **updates) if changed else statement


def _returning_from_exile(instruction: OracleInstruction) -> OracleInstruction:
    """*instruction* with every self-return inside it reading the source out
    of **exile** — see the activated branch of :func:`lower_ability`.

    Walked by shape rather than by a table of wrapper kinds, because the
    return this is written for sits inside a delayed trigger inside an offer:
    a nested instruction is an ``OracleInstruction`` wherever a payload holds
    one, alone or in a sequence. Rebuilt, never mutated — a compiled
    instruction is shared by every copy of the card.
    """
    def walk(value):
        if isinstance(value, OracleInstruction):
            return _returning_from_exile(value)
        if isinstance(value, tuple):
            return tuple(walk(item) for item in value)
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    payload = {key: walk(value) for key, value in instruction.payload.items()}
    if instruction.kind == "return_self_from_graveyard":
        payload["from"] = "exile"
    return OracleInstruction(instruction.kind, instruction.value, payload)


def lower_ability(
    node: ast.AbilityNode, *, event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """Lower a whole ability line. Keyword and static lines carry no
    instructions of their own — they are recorded by the compiler as keyword or
    static lines instead.

    *event* names the **position** the line occupies when that position froze a
    seat or an object the sentence can refer back to. A trigger reads its own
    from ``node.event.kind``; an effect line has none of its own, and the one
    caller that supplies one is the modal assembly in ``engine/ability_lines.py``,
    where CR 700.2e's "an opponent chooses one —" makes the mode's "that
    player" name the chooser (``lowering/_events.OPPONENT_CHOSE_MODE``). It is
    ignored for every other node kind, which carry their own or none.
    """
    if isinstance(node, ast.SpellEffectLine):
        # A spell whose **whole** effect is optional used to refuse here. The
        # reason was real and is now gone: the prompt rode
        # ``pending_optional_pays``, which only the triggered-ability resolution
        # path held open, so a spell — which leaves the stack the instant it
        # resolves — queued its effect and never performed it. Since
        # ``arm_pending_choice`` stamps the resolving stack object and
        # ``ChoiceSpec.holds_priority`` keeps that object on the stack until the
        # last of its prompts is answered (CR 608.2, CR 117.3b), a spell's
        # ``may`` outlives its own resolution exactly like a trigger's. Twiddle
        # and Rebirth are the two cards that reach the shape.
        return _lower_line_statement(node.statement, event=event)
    if isinstance(node, ast.TriggeredAbilityNode):
        fused = _fused_upkeep_pay_to_untap(node)
        if fused is not None:
            return fused
        instructions = _lower_line_statement(
            node.statement, event=node.event.kind,
            event_subject=node.event.subject,
            # What the firing event itself left for the effect to read back
            # (CR 603.10) — the trigger's twin of an activation cost's records
            # one branch down, and seeded here for the same reason: this is
            # the one place the condition and the effect are both in view.
            produced=EVENT_PRODUCES.get(node.event.kind, frozenset()),
        )
        # This used to refuse every decomposed upkeep trigger — a
        # `may(pay, untap_self)` where the registry in
        # engine/phases/upkeep_effects.py wanted a fused
        # `upkeep_pay_to_untap_self` — because the registry was the *only*
        # dispatcher an upkeep trigger had, so claiming the line would have left
        # the card compiling cleanly and doing nothing.
        #
        # The upkeep step now puts an ordinary trigger on the stack (CR 603.3)
        # when the registry answers nothing, so a wrapper has somewhere to run
        # and the refusal has nothing left to protect. The registry keeps the
        # pay-or-consequence shapes, which are asked first; the fused kinds still
        # come out of `_fused_upkeep_pay_to_untap` above, unchanged.
        if node.intervening_if is not None:
            # CR 603.4: the condition is checked when the trigger would fire and
            # again on resolution. The legacy compiler dropped these outright,
            # so conditional triggers always fired.
            condition = _lower_condition(
                node.intervening_if, event=node.event.kind,
                event_subject=node.event.subject,
            )
            # CR 113.6b: "an ability that states which zones it functions in
            # functions only from those zones". Some conditions *are* that
            # statement — "if this card is in your graveyard with a creature
            # card directly above it" (Death Spark, Krovikan Horror) — and the
            # effect behind them names no source zone of its own, so this is the
            # one place the claim can be carried onto the instruction.
            #
            # The key is the same one CR 113.6m's printed "from your graveyard"
            # stamps in ``lowering/returns.py``, deliberately: the graveyard scan
            # in ``engine/events.py`` asks one question of one key, and a second
            # spelling would be an ability that functions from a graveyard by
            # one reader's reckoning and not the other's.
            zone = condition.get("functions_from")
            extra = {"functions_from": zone} if zone else {}
            # "…**if you haven't added mana with this ability this turn**…"
            # (Carpet of Flowers.) The clause reads a record that nothing else
            # in the engine writes, and the instruction that must write it is
            # the mana half of this same ability — sitting inside the offer, so
            # the stamp reaches through it (:func:`stamp_payload_key`).
            #
            # Here rather than in the mana lowering because only here are the
            # two halves in view: "add X mana of any one color" is the same
            # printed sentence on Sanctum of Fruitful Harvest, which records
            # nothing and must go on recording nothing. The same pairing
            # argument ``_lower_steps`` makes for "if you do" and the step that
            # writes what it reads.
            if condition.get("kind") == "mana_added_with_this_ability":
                from ..mana_ability_records import MANA_RECORD_PAYLOAD_KEY

                instructions = stamp_payload_key(
                    instructions,
                    kind="add_mana_from_text",
                    key=MANA_RECORD_PAYLOAD_KEY,
                    value=condition["record"],
                )
            instructions = tuple(
                OracleInstruction(
                    instruction.kind, instruction.value,
                    {**instruction.payload, "intervening_if": condition, **extra},
                )
                for instruction in instructions
            )
        return instructions
    if isinstance(node, ast.ActivatedAbilityNode):
        # An activation cost is paid before the ability goes on the stack
        # (CR 602.2b), so what it ate is a record the *effect* can read back —
        # "If the discarded card was a land card" (Land's Edge). This is the one
        # place the cost clause and the effect clause are both in view, which is
        # why the seeding happens here rather than in a field on the condition:
        # the same pairing rule `_lower_steps` follows for "if you do".
        produced = frozenset(
            _COST_PRODUCES[type(cost)]
            for cost in node.costs
            if type(cost) in _COST_PRODUCES
        )
        lowered = _lower_line_statement(
            _rebind_blocking_pronoun(node.statement), produced=produced
        )
        if any(isinstance(cost, ast.ExileSelf) for cost in node.costs):
            # "{3}{U}, **Exile this creature**: … If you do, **return this
            # card to the battlefield**." (Shifty Doppelganger.) The sentence
            # names no zone to return the card from, and the lowering reads
            # that as a graveyard — Nether Spirit's reading, right for every
            # card that prints the words anywhere else. Here the ability's own
            # cost has said where "this card" is: in exile. This is the one
            # place the cost clause and the effect clause are both in view,
            # so it is where the zone is stamped.
            lowered = tuple(_returning_from_exile(step) for step in lowered)
        return lowered
    if isinstance(node, ast.KeywordLine):
        return ()
    if isinstance(node, ast.RegistryLine):
        # Zero instructions is the correct lowering, not a gap: the line is
        # already executed by a text-keyed registry reading the card's oracle
        # text (see engine/grammar/registries.py). Emitting anything here would
        # duplicate an effect the engine is already applying.
        return ()
    if isinstance(node, ast.DerivedLine):
        # The table computed the instruction when it claimed the line; asking it
        # again is what keeps this a delegation rather than a copy. It cannot
        # answer differently — every matcher in engine/grammar/derived.py is a
        # pure function of the text the node carries verbatim — but if the table
        # is ever narrowed out from under a node, refusing here is the loud
        # failure rather than an instruction nothing derives.
        derived = derived_instruction_for_line(node.text)
        if derived is None:  # pragma: no cover - defensive
            raise LoweringError(
                f"engine/grammar/derived.py no longer derives {node.table!r} "
                "for this line",
                node=node,
            )
        return (derived[1],)
    if isinstance(node, ast.StaticAbilityNode):
        return _lower_static_ability(node)
    raise LoweringError(f"no lowering for {type(node).__name__}", node=node)


__all__ = [
    "GRAMMAR_ONLY_PAYLOAD_KEYS",
    "INSTRUCTION_CATEGORIES", "categories_of", "lower_ability", "lower_statement",
    "WRAPPER_KINDS", "OFFER_BRANCH_KEYS", "nested_instructions", "offer_branches",
]
