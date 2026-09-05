"""Lowering ``Repeat this process …`` — the sentence that says the sentences
before it happen again.

The mirror of ``grammar/repeats.py``, and it carries that module's whole
argument: three cards print the words and no two of them are the same
mechanism, so they are one family and three lowerings rather than one
production with a flag. A round of offers repeated while anybody took it
(Eureka), one seat's decision taken again after every round (Forbidden Ritual)
and a printed list of parameters that is not a loop at all (Equipoise) share
the printed word and nothing else.

``_lower_repeat_process`` arrived here from ``lowering/game.py``, where it had
been the only member of a section called "a round of offers, repeated" — a
family of one, with its parse half in ``parser.py`` and no mirror at all. It
moved the moment the family had a second member, which is the point at which
the boundary becomes information rather than a guess.

Each lowering takes the statement lowering as a **parameter**: a repeated
process is a whole statement, reading one is the dispatcher's job, and this
module sits below it (see ``engine/ARCHITECTURE.md`` on taking the recursion
back as an argument).
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError


def _lower_repeat_process(node: ast.RepeatProcess, lower) -> tuple[OracleInstruction, ...]:
    """"Starting with you, each player may put a permanent card from their hand
    onto the battlefield. Repeat this process until no one puts a card onto the
    battlefield." (Eureka.)

    The offer and the repetition are one instruction, because the repetition is
    a property of the round rather than a step after it: what ends the loop is a
    whole round nobody took, which only the thing running the round can see.

    *lower* is the statement lowering, handed in rather than imported — this
    module sits below the dispatcher that owns it (see ``engine/ARCHITECTURE.md``
    on taking the recursion back as a parameter).

    Everything about the offer is checked rather than assumed. A cost, an
    if-you-do branch or a decline branch would each be a printed clause this
    instruction has nowhere to put; an act outside ``REPEATABLE_OFFERS`` has no
    record saying whether a seat took it, so the loop could not end on anything
    but its first round.
    """
    from ...repeated_offers import REPEATABLE_OFFERS

    offer = node.round
    if not isinstance(offer, ast.May) or offer.action is None:
        raise LoweringError("'repeat this process' repeats an offer", node=node)
    if offer.cost is not None or offer.then or offer.otherwise or offer.reflexive:
        raise LoweringError(
            "no handler repeats an offer carrying branches of its own", node=node
        )
    if offer.actor.kind != "each_player":
        raise LoweringError(
            "a repeated round is offered to every seat", node=node
        )
    steps = lower(offer.action, frozenset(), whole_effect=False)
    if len(steps) != 1:
        raise LoweringError("no handler repeats more than one act per seat", node=node)
    step = steps[0]
    if step.kind not in REPEATABLE_OFFERS:
        raise LoweringError(
            f"{step.kind!r} records nothing about whether a seat took it, so a "
            "round of it could never be the last one",
            node=node,
        )
    return (
        OracleInstruction(
            "repeat_offer_round", "",
            {
                "actor": offer.actor.kind,
                # "Starting with you" — CR 101.4's default is the active player,
                # and this says the seat that put the effect on the stack. The
                # same seat for a sorcery, not the same rule.
                "offer_order": offer.starting_with.kind if offer.starting_with else None,
                "action": (
                    OracleInstruction(
                        step.kind, step.value, {**step.payload, "optional": True}
                    ),
                ),
            },
        ),
    )


def _card_types_in(node) -> set[tuple[str, ...]]:
    """Every non-empty ``ObjectFilter.card_types`` tuple inside *node*.

    A walk over the dataclass fields rather than a list of the nodes that carry
    a filter, for ``_round_every_half``'s stated reason one package over: a
    statement class added later is covered by default instead of silently
    keeping the type the round was printed with.
    """
    if isinstance(node, ast.ObjectFilter):
        found = {node.card_types} if node.card_types else set()
        return found | _card_types_in_fields(node)
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        return _card_types_in_fields(node)
    if isinstance(node, tuple):
        return set().union(*(_card_types_in(item) for item in node)) if node else set()
    return set()


def _card_types_in_fields(node) -> set[tuple[str, ...]]:
    found: set[tuple[str, ...]] = set()
    for field in dataclasses.fields(node):
        found |= _card_types_in(getattr(node, field.name))
    return found


def _with_card_type(node, printed: tuple[str, ...], replacement: str):
    """*node* with every ``card_types`` equal to *printed* set to *replacement*.

    The substitution the printed clause names, made on the AST rather than on
    the lowered payloads: a payload is stringly typed and a walk over one would
    have to guess which of its keys is a card type, where a node says so.
    """
    if isinstance(node, ast.ObjectFilter) and node.card_types == printed:
        node = dataclasses.replace(node, card_types=(replacement,))
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        return dataclasses.replace(node, **{
            field.name: _with_card_type(
                getattr(node, field.name), printed, replacement
            )
            for field in dataclasses.fields(node)
        })
    if isinstance(node, tuple):
        return tuple(_with_card_type(item, printed, replacement) for item in node)
    return node


def _lower_repeat_for_types(
    node: ast.RepeatForEachType, lower
) -> tuple[OracleInstruction, ...]:
    """"…choose a land that player controls, then the chosen permanents phase
    out. **Repeat this process for artifacts and creatures.**" (Equipoise.)

    Not a loop and not one instruction: the parameters are printed, so this is
    the round's own instructions once per type, in the order the card names
    them. Every reader downstream — the picker, the effect labels, the AI's
    valuation — then sees ordinary steps rather than a wrapper it would have to
    learn, which is what a repetition known at parse time buys over one that is
    not.

    The substitution is checked rather than assumed. The round must name
    **exactly one** card type, in however many noun phrases: Equipoise says
    "land" twice, in the count and in the choice, and both have to move together
    or the card would count lands and phase out artifacts. A round naming two
    types, or none, is a sentence this rewrite cannot state, so it refuses.

    The record the rounds write is deliberately **shared**. "The chosen
    permanents" is one key every round appends to, so round three's phase-out
    names rounds one and two's picks as well — and phases out nothing for them,
    because CR 702.26b has already made those permanents not exist. That is the
    printed reading rather than an accident of the key: a permanent already
    phased out is not something a later sentence can phase out again, and the
    handler skips whatever is no longer on the battlefield for exactly that
    reason.
    """
    printed = _card_types_in(node.round)
    if len(printed) != 1:
        raise LoweringError(
            "a repeated process names one card type to substitute, not "
            f"{len(printed)}",
            node=node,
        )
    (only,) = printed
    if len(only) != 1:
        raise LoweringError(
            "a repeated process substitutes a single card type", node=node
        )
    steps: list[OracleInstruction] = []
    for card_type in (only[0], *node.types):
        round_ = (
            node.round if card_type == only[0]
            else _with_card_type(node.round, only, card_type)
        )
        lowered = lower(round_, frozenset(), whole_effect=False)
        if not lowered:
            raise LoweringError(
                f"the process for {card_type!r} lowers to nothing", node=node
            )
        steps.extend(lowered)
    return tuple(steps)


def _lower_repeat_optional_process(
    node: ast.RepeatOptionalProcess, lower
) -> tuple[OracleInstruction, ...]:
    """"Sacrifice a nontoken permanent. If you do, target opponent loses 2 life
    unless that player sacrifices a permanent of their choice or discards a
    card. **You may repeat this process any number of times.**" (Forbidden
    Ritual.)

    The round and the repetition are one instruction, for
    :func:`_lower_repeat_process`'s reason and a second one of its own. The
    first: the repetition is a property of the process rather than a step after
    it. The second: the decision is taken *between* rounds, so whatever asks it
    has to be holding the round it would run — a `may` beside the steps could
    only ever offer one more.

    Nothing about the round is checked beyond it lowering to something, and
    that is the difference from Eureka's clause rather than an omission there.
    That one needs a record saying whether a seat took the offer, because
    without one the loop could not end; this one ends on an answer, so any
    process at all is a process this can repeat. What is refused is the empty
    one — a loop with no steps in it is a sentence that reports supported and
    does nothing, however many times it is asked to.
    """
    steps = lower(node.round, frozenset(), whole_effect=False)
    if not steps:
        raise LoweringError(
            "a repeated process with no effect in it", node=node
        )
    return (
        OracleInstruction("repeat_optional_process", "", {"steps": steps}),
    )
