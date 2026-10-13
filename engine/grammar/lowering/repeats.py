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
from ._records import produced_keys


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


def _lower_repeat_process_request(
    node: "ast.RepeatProcessRequest",
) -> tuple[OracleInstruction, ...]:
    """"…unless you pay {3} **and repeat this process**." (Crooked Scales.)

    The **sixth** printed "repeat this process" and the only one whose lowering
    produces no loop. The five above each hold the round they repeat, because
    each is printed as a clause *about* that round; this one is printed inside
    a price, two branches down inside the last of three sentences, and what it
    names — "this process" — is the whole printed effect. Nothing at this depth
    is holding that.

    So it lowers to a *request*: one instruction that records, in the
    resolution's own scratchpad, that the round asked for another. The loop is
    put round the line by ``grammar/lower._lower_line_statement`` — the one
    function that has every instruction a line lowered to, which is the same
    reason CR 601.2c's roles walk runs there — and its handler reads the record
    at the end of each round.

    Splitting it that way is what keeps the coin flip honest. The request is
    made only on the branch that ran, so a round that won the flip never writes
    the key and the loop stops; a round that lost it and was paid for does, and
    the loop runs the *whole* process again — the flip included, which is what
    "this process" says and what a loop holding only the last sentence could
    not do.
    """
    return (OracleInstruction("request_process_repeat", "", {}),)


def _lower_repeat_process_while(
    node: ast.RepeatProcessWhile, lower, lower_condition, produced, event,
) -> tuple[OracleInstruction, ...]:
    """"Target player mills two cards. **If two cards that share a color were
    milled this way, repeat this process.**" (Grindstone.)

    The round and its stopping question are one instruction, for
    :func:`_lower_repeat_process`'s reason: the question is about what the
    round just did, so whatever asks it has to be holding the round it would
    run again.

    Two things are checked and both are the difference between a loop and a
    hang. The round must **produce** every record the condition reads — a
    condition asked of a record nothing writes answers the same way for ever,
    which is either one round or none of them ending. And the records the round
    writes are named in the payload as ``resets``, because "milled **this
    way**" means *this round's* cards: without the clearing, round two would be
    asked about round one's mill as well and Grindstone would never stop on a
    library it had already emptied of shared colours.

    ``produced`` is the effect's own set *plus* what the round writes, because
    the condition is printed after the round and reads it.
    """
    steps = lower(node.round, produced, event=event, whole_effect=False)
    if not steps:
        raise LoweringError(
            "a repeated process with no effect in it", node=node
        )
    written = frozenset(
        key for step in steps for key in produced_keys(step)
    )
    condition = lower_condition(node.condition, produced | written, event)
    return (
        OracleInstruction(
            "repeat_process_while", "",
            {
                "steps": steps,
                "condition": condition,
                "resets": tuple(sorted(written)),
            },
        ),
    )


def _instructions_within(instruction: OracleInstruction):
    """*instruction* and every instruction it carries, at any depth.

    A walk over the payload's values rather than over a table of wrapper
    kinds: that table is the dispatcher's (``grammar/lower.WRAPPER_KINDS``),
    which this family sits below, and what is asked here needs no key names —
    only "is there one of these anywhere inside". A wrapper added later is
    covered by construction.
    """
    yield instruction
    pending = [instruction.payload]
    while pending:
        value = pending.pop()
        if isinstance(value, OracleInstruction):
            yield from _instructions_within(value)
        elif isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)


#: The kinds that ask a seat something **without stopping the steps behind
#: them** (an ``optional_pay`` does not suspend; see
#: ``handlers/control_flow._offer_to_seat``). A round may end in one — its
#: branches are where the round ends — but may not hold one anywhere else.
_UNSUSPENDED_OFFERS = frozenset({"may", "unless_player_pays"})

#: The step that is the end of one round: see ``_with_round_end``.
_END_OF_ROUND = OracleInstruction("end_process_round", "", {})


def _with_round_end(step: OracleInstruction) -> tuple[OracleInstruction, ...]:
    """*step*, the last of a round, with the round's end put on **every way
    out of it**.

    "Repeat this process until …" is asked when the round is over, and a round
    whose last sentence is an offer is over when the offer is *answered* — by
    which time the handler that ran the round has long returned. So the
    question cannot be a line after the round; it has to ride whichever branch
    the answer runs. A conditional ends on both its arms, a sequence on its
    last step, an offer on its accept branch and on its decline branch, and
    anything else simply has the end behind it.

    Rebuilt rather than mutated, for ``stamp_payload_key``'s reason: an
    instruction is shared by every copy of its card.
    """
    payload = step.payload
    if step.kind == "sequence" and payload.get("steps"):
        steps = tuple(payload["steps"])
        return (OracleInstruction(step.kind, step.value, {
            **payload, "steps": steps[:-1] + _with_round_end(steps[-1]),
        }),)
    if step.kind == "if_then":
        arms = {
            arm: (
                tuple(payload.get(arm) or ())[:-1]
                + _with_round_end(tuple(payload[arm])[-1])
                if payload.get(arm) else (_END_OF_ROUND,)
            )
            for arm in ("then", "else")
        }
        return (OracleInstruction(step.kind, step.value, {**payload, **arms}),)
    if step.kind == "may":
        # On the accept side the end goes behind everything accepting does —
        # ``then`` runs after ``action`` — and the decline side gains a branch
        # it did not print, which is the point: declining ends the round too.
        return (OracleInstruction(step.kind, step.value, {
            **payload,
            "then": tuple(payload.get("then") or ()) + (_END_OF_ROUND,),
            "otherwise": tuple(payload.get("otherwise") or ()) + (_END_OF_ROUND,),
        }),)
    if any(
        inner.kind in _UNSUSPENDED_OFFERS for inner in _instructions_within(step)
    ):
        raise LoweringError(
            f"a round ending in {step.kind!r} asks a seat something this "
            "cannot find the end of"
        )
    return (step, _END_OF_ROUND)


def _lower_repeat_process_until(
    node: "ast.RepeatProcessUntil", lower, lower_condition, produced, event,
) -> tuple[OracleInstruction, ...]:
    """"Exile the top card of your library. You may put that card into your
    hand unless it has the same name as another card exiled this way. **Repeat
    this process until you put a card into your hand or you exile two cards
    with the same name, whichever comes first.**" (Tainted Pact.)

    :func:`_lower_repeat_process_while` read the other way round, and held to
    the same two checks for the same reason — they are the difference between
    a loop and a hang. Every stopping clause must read a record **the round
    writes**: one asked of a record nothing writes answers False for ever. And
    the records the round writes are named as ``resets``, which the handler
    both clears before each round and reads after it: a round that wrote none
    of them did nothing, and a process that can no longer be performed is not
    repeated (CR 101.3) — which is what ends this card on an empty library.

    Two more are this loop's own. The stopping clauses are asked at the *end*
    of the round, so the end is lowered onto every way out of the round's last
    step (:func:`_with_round_end`); and a step that asks without suspending
    anywhere **but** last is refused, because the clauses would be asked
    before that answer existed.
    """
    steps = lower(node.round, produced, event=event, whole_effect=False)
    if not steps:
        raise LoweringError("a repeated process with no effect in it", node=node)
    written = frozenset(
        key
        for step in steps
        for inner in _instructions_within(step)
        for key in produced_keys(inner)
    )
    if not written:
        raise LoweringError(
            "a repeated process that records nothing can never be seen to "
            "have stopped", node=node,
        )
    for step in steps[:-1]:
        if any(
            inner.kind in _UNSUSPENDED_OFFERS
            for inner in _instructions_within(step)
        ):
            raise LoweringError(
                "an offer that is not the round's last step would be answered "
                "after the round was asked whether it had ended", node=node,
            )
    parts = (
        node.condition.conditions
        if isinstance(node.condition, ast.SomeOf) else (node.condition,)
    )
    until = tuple(
        lower_condition(part, produced | written, event) for part in parts
    )
    try:
        body = tuple(steps[:-1]) + _with_round_end(steps[-1])
    except LoweringError as refusal:
        raise LoweringError(str(refusal), node=node) from None
    return (
        OracleInstruction(
            "repeat_process_until", "",
            {
                "steps": body,
                "until": until,
                "resets": tuple(sorted(written)),
            },
        ),
    )


def _lower_repeat_until_pile_chosen(
    node: "ast.RepeatUntilPileChosen", lower, produced,
) -> tuple[OracleInstruction, ...]:
    """"Starting with you, each player chooses one of the exiled cards and puts
    it onto the battlefield tapped under their control. **Repeat this process
    until all cards exiled this way have been chosen.**" (Thieves' Auction.)

    The round and the repetition are one instruction, for
    :func:`_lower_repeat_process`'s reason: what ends the loop is a fact only
    the thing running the round can see — here the pile it is handing out
    running empty — and this bound also ends a round *part-way*, which a
    wrapper around the round could not express at all.

    So the clause is lowered by setting the round's own flag and lowering that,
    rather than by building a second instruction. What is checked is that the
    round really is a pick out of the pile the clause names: a repeat clause
    about "cards exiled this way" behind any other sentence would be a loop with
    no bound in reach, and the refusal is the loud direction.
    """
    round_ = node.round
    if not isinstance(round_, ast.EachPlayerClaimsExiledCard):
        raise LoweringError(
            "'until all cards exiled this way have been chosen' bounds a pick "
            "out of that same pile, and this sentence makes none", node=node,
        )
    return lower(
        dataclasses.replace(round_, until_pile_empty=True),
        produced, whole_effect=False,
    )
