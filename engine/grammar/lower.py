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
"""

import dataclasses

from ..oracle_types import OracleInstruction
from . import ast
from .derived import derived_instruction_for_line
from .errors import LoweringError
from .statics import _lower_static_ability
from .lowering.control_flow import (_lower_steps)
from .lowering import (
    GRAMMAR_ONLY_PAYLOAD_KEYS,
    INSTRUCTION_CATEGORIES,
    categories_of,
    _COST_PRODUCES,
    _fused_upkeep_pay_to_untap,

    _lower_modal_head,
    _lower_condition,
)


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
    return lower_statement(
        statement, produced, event=event, event_subject=event_subject
    )


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
    """
    if isinstance(statement, (ast.Sequence, ast.Conjunction)):
        return statement
    changed = False
    updates: dict[str, object] = {}
    for field in dataclasses.fields(statement):
        spec = getattr(statement, field.name, None)
        if not isinstance(spec, ast.TargetSpec) or not spec.targeted:
            continue
        if not spec.filter.blocking_bound_target:
            continue
        updates[field.name] = dataclasses.replace(
            spec,
            filter=dataclasses.replace(
                spec.filter, blocking_bound_target=False, blocking_source=True
            ),
        )
        changed = True
    return dataclasses.replace(statement, **updates) if changed else statement


def lower_ability(
    node: ast.AbilityNode, *, event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """Lower a whole ability line. Keyword and static lines carry no
    instructions of their own — they are recorded by the compiler as keyword or
    static lines instead.

    *event* names the **position** the line occupies when that position froze a
    seat or an object the sentence can refer back to. A trigger reads its own
    from ``node.event.kind``; an effect line has none of its own, and the one
    caller that supplies one is the modal assembly in ``engine/oracle.py``,
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
                node.intervening_if, event=node.event.kind
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
        return _lower_line_statement(
            _rebind_blocking_pronoun(node.statement), produced=produced
        )
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
]
