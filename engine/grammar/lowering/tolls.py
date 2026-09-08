"""Lowering the **toll** — "unless <player> <pays a price>" and its refusal.

The mirror of ``grammar/tolls.py``, re-formed rather than forked: that module
was split off ``sentence_clauses`` for exactly this family and states its
subject in one sentence — *what price is offered, to whom, and what does paying
it buy*. These four are the lowering half of the same question, and until Urza's
Saga's second wave they sat in ``lowering/board.py``, whose own docstring called
them out as "the one place that split cut a production family in half rather
than along it". They are cut along it now.

The family is an **offer whose refusal is the effect**, which is why the three
printed verbs travel together rather than with the verbs they name: "sacrifice
this permanent unless you pay", "destroy this creature unless you pay", and the
per-payer form "for each land, destroy that land unless any player pays 1 life".
Lowering any one of them as a sacrifice or a destruction would put the *price*
in one family and the *consequence* in another.

``_per_payer_count`` stayed behind. It reads an ``ast.Sacrifice`` for
``_lower_sacrifice``'s own per-recipient count and no toll here calls it —
measured at the split rather than assumed, which is the check that keeps a
seam from taking a neighbour with it.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import OracleInstruction
from ...subject_filters import object_only_filter
from .. import ast
from ..errors import LoweringError
from ._common import _filter_payload, _full_mana_payload, _is_source
from ._events import PUT_FROM_HAND_PERMANENTS


def _lower_sacrifice_unless_pay(
    node: ast.SacrificeUnlessPay, produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """"Sacrifice this <permanent> unless you pay <cost>."

    Two handlers exist and the noun picks between them — an enchantment's
    prompt is a different registry entry from any other permanent's. Both
    sacrifice the source, so only a self-referential subject is accepted;
    sacrificing something *chosen* needs the pending-choice queue.

    **Both of those kinds are dispatched by the upkeep registry and by nothing
    else**, which is why the pronoun branch below cannot use them. "It" after a
    step that put a card onto the battlefield is not the source at all — the
    source is the spell — and a lowering that read it as one would emit an
    instruction with no ``EFFECT_HANDLERS`` entry: a card compiling supported
    and doing nothing, which is the shape ``--hollow-lines`` exists to find.

    *produced* is what earlier steps of the same sentence recorded, which is the
    whole of what tells the pronoun apart: with no such record "it" has no
    referent but the source, and the branch refuses.
    """
    subject = node.subject
    # "…sacrifice **it** unless you pay its mana cost reduced by {2}" (Flash).
    # The pronoun names the permanent the step in front of it created, and the
    # cost is read off that same permanent. Decomposed into the offer machinery
    # rather than fused, because nothing dispatches the fused kinds outside the
    # upkeep registry — and because ``may`` already implements an offer with a
    # penalty on the decline, which is exactly what "unless" says.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "it"
        and PUT_FROM_HAND_PERMANENTS in produced
    ):
        cost: dict[str, object] = {"mana": _full_mana_payload(node.cost)}
        if node.cost_from == "its_mana_cost":
            # The printed number is the *reduction*; the cost itself is the
            # permanent's own mana cost, which is not knowable until the seat
            # has picked a card. So the payload says where to read it and by
            # how much to reduce it, and `handlers/control_flow._resolve_cost`
            # does the arithmetic at resolution.
            cost = {
                "cost_from": PUT_FROM_HAND_PERMANENTS,
                "reduced_by": _full_mana_payload(node.cost),
            }
        elif node.cost_from is not None:
            raise LoweringError(
                f"no offer reads a cost from {node.cost_from!r}", node=node
            )
        return (
            OracleInstruction(
                "may", "",
                {
                    "actor": "you",
                    "cost": cost,
                    "otherwise": (
                        OracleInstruction(
                            "sacrifice_recorded_permanent", "",
                            {"permanents_from": PUT_FROM_HAND_PERMANENTS},
                        ),
                    ),
                },
            ),
        )
    if node.cost_from is not None:
        raise LoweringError(
            "a derived cost is read off a permanent an earlier step of this "
            "sentence created", node=node,
        )
    if not _is_source(subject):
        raise LoweringError("no handler for sacrificing a chosen permanent", node=node)
    types = subject.filter.card_types if isinstance(subject, ast.TargetSpec) else ()
    kind = (
        "upkeep_pay_or_sacrifice_enchantment"
        if types == ("enchantment",)
        else "upkeep_pay_or_sacrifice_self"
    )
    return (OracleInstruction(kind, "", {"mana": _full_mana_payload(node.cost)}),)

def _lower_pay_or_sacrifice_greatest_mana_value(
    node: "ast.PayOrSacrificeGreatestManaValue",
) -> tuple[OracleInstruction, ...]:
    """Tariff's paragraph → one instruction, whose handler is a loop.

    Juxtapose's paragraph one production down decomposes at *lowering* time,
    because it names exactly two seats and the card says which. This one names
    "each player", so how many pairs of steps there are is not knowable until
    the spell resolves — which is why the loop is the handler's and the payload
    is only the printed noun. What the loop then runs is the same machinery
    Juxtapose and Flash already use, per seat: a ``choose_permanent`` narrowed
    to that seat's greatest-mana-value permanents and asked ``only_on_tie``,
    then a ``may`` whose cost is read off what that step recorded
    (``cost_from``, Flash's key) with ``sacrifice_recorded_permanent`` on the
    decline (Retribution's).

    So there is no new mechanism here at all, and deliberately: the tie-break
    sentence *is* the prompt, and the toll's unprinted cost is the one
    ``_derived_cost`` already computes off a recorded permanent.
    """
    return (
        OracleInstruction(
            "each_player_pays_or_sacrifices_greatest", "",
            {"card_type": node.card_type},
        ),
    )

def _lower_destroy_unless_pay(
    node: ast.DestroyUnlessPay, event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """"At the beginning of your upkeep, destroy this creature unless you pay
    {3}{B}{B}{B}. If this creature is destroyed this way, it deals 7 damage to
    you." (Cosmic Horror.)

    Fused, like the sacrifice twin above and for the same reason: the upkeep
    dispatcher is keyed on (trigger condition, instruction kind) pairs whose
    handlers run the whole pay-or-consequence prompt. The event is threaded
    down here rather than inferred, exactly as `_lower_damage_unless_pay` does
    it — the handler takes its seat and its mana from the upkeep context, so
    under any other trigger there is nothing to dispatch to and the line must
    refuse rather than compile into a card that does nothing.
    """
    if not _is_source(node.subject):
        raise LoweringError(
            "the pay-or-destroy prompt destroys the ability's own source", node=node
        )
    if event != "upkeep_self":
        raise LoweringError(
            f"no handler pairs {event!r} with a pay-or-destroy prompt", node=node
        )
    payload: dict[str, object] = {"mana": _full_mana_payload(node.cost)}
    if node.damage_if_destroyed is not None:
        payload["damage_if_destroyed"] = node.damage_if_destroyed
    # "…{1} for each music counter on it" — the same `per_counter` key
    # `engine/cumulative_upkeep.scaled_cost` already reads, so the escalation is
    # one implementation rather than a second multiplier beside it.
    if node.per_counter is not None:
        payload["per_counter"] = node.per_counter
    return (OracleInstruction("upkeep_pay_or_destroy_self", "", payload),)

def _lower_destroy_each_unless_paid(
    node: ast.DestroyEachUnlessPaid,
) -> tuple[OracleInstruction, ...]:
    """"For each land, destroy that land unless any player pays 1 life."
    (Cleansing.)

    One instruction rather than a sweep plus a rider: the offer is made about
    one permanent at a time, so the loop and the buyout are the same effect and
    nothing but the handler can hold the record of which members were bought.

    The noun phrase is gated by ``object_only_filter`` for the reason the
    forced-sacrifice prompt is: the loop walks every battlefield with no
    observer seat and no source to compare against, so a narrowing the matcher
    could only answer relative to one of those would be dropped — and a dropped
    narrowing on a sweep takes the board rather than doing less.

    **"…that dealt damage to this creature this turn" is the one exception, and
    it is an exception because it is not a narrowing of the sweep — it *is* the
    set.** "When this creature dies, … for each creature that dealt damage to
    this creature this turn, destroy that creature unless its controller pays 2
    life." (Giant Albatross.) A relation to the ability's own source, which
    ``to_payload`` has no key for (``_filters.CONDITIONALLY_EMITTED_FIELDS``
    names it so that every lowering but the one written for it refuses the
    phrase); it is lifted off the filter here and carried as its own payload
    key, exactly as Brine Hag's base-P/T rewrite carries the same relation. The
    handler reads the record the damage seam kept on the victim
    (``damaged_by_sources_this_turn``) rather than scanning a battlefield, which
    is the only reading available at all: this trigger fires on a death, so by
    resolution the source is a card in a graveyard (CR 603.10, idiom 6).
    """
    filt = node.filter
    from_damage_record = filt.dealt_damage_to_source_this_turn
    if from_damage_record:
        filt = dataclasses.replace(filt, dealt_damage_to_source_this_turn=False)
    described = object_only_filter(_filter_payload(filt))
    if described is None:
        raise LoweringError(
            "the per-permanent buyout cannot test this restriction", node=node
        )
    if node.payer not in ("any_player", "controller"):
        raise LoweringError(
            f"no buyout is offered to {node.payer!r}", node=node
        )
    payload: dict[str, object] = {
        "filter": dict(described), "life": int(node.life),
    }
    if node.payer != "any_player":
        # Absent still means "any player", so Cleansing's payload stays
        # byte-identical and the handler's APNAP round is what an absent key
        # keeps meaning.
        payload["payer"] = node.payer
    if from_damage_record:
        payload["from_damage_record"] = True
    if node.no_regen:
        payload["bypass_regeneration"] = True
    return (OracleInstruction("destroy_each_unless_life_paid", "", payload),)
