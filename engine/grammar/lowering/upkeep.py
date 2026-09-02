"""Lowering the pay-or-consequence shapes an upkeep trigger prints.

The mirror of `grammar/upkeep.py` one package over, and the name
`lowering/categories.py` already gives the kinds these produce
(``upkeep_pay_or_deal_damage_to_controller``, ``upkeep_damage_unless_cost``,
``upkeep_pay_to_reduce_damage`` — all ``"upkeep"``) and
`engine/phases/upkeep_effects.py` gives the registry that runs them. Split out
of `damage` at the thousand-line guard (`tests/engine/test_grammar_layering.py`)
along the boundary that module already had: everything left in it is a damage
event *happening*, and these three are a damage event a player is offered the
chance not to take.

``_lower_damage_unless_pay`` is here rather than in `damage` even though one of
its two branches is reachable off a spell (Stench of Evil's "unless they pay
{2}"): it is one printed sentence whose primary dispatcher is the upkeep
registry, and splitting a production by which of its branches fired would put
half a sentence in each module. Which flow it lowers to is decided by the
trigger, which is what its own docstring says.

The **sacrifice** half of the same family (``upkeep_pay_or_sacrifice_*``) is
still in `board`, where it is one branch of the sacrifice production that reads
the whole sentence. Moving it would fork that production rather than complete
this family; it belongs here the day it stops being one branch of another
reader.

A family in the layer order's sense — it imports only the floors (`_common`,
`_events`, `_amounts`, `_sacrifices`) and no sibling family, which is what
`test_families_do_not_import_each_other` asserts of every name in
`LOWERING_FAMILIES`.
"""

from ...oracle_types import OracleInstruction, PER_OBJECT_SEAT_RECORDS
from .. import ast
from ..errors import LoweringError
from ._amounts import _damaged_player_is
from ._sacrifices import _forced_sacrifice_filter
from ._common import (
    _amount_payload,
    _full_mana_payload,
    _is_you,
)
from ._events import (
    _EVENT_SUBJECT_CONTROLLERS,
    _EVENT_SUBJECT_PLAYERS,
    EVENT_SUBJECT_CONTROLLER,
    EVENT_SUBJECT_PLAYER,
)


def _lower_damage_unless_pay(
    node: ast.DamageUnlessPay,
    event: str | None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """"<source> deals N damage to you unless you pay <cost>."

    Two engine flows implement this and the *trigger* picks between them, which
    is why the event kind is threaded down here rather than inferred from the
    clause. On an upkeep trigger the pair (condition, instruction kind) is
    looked up in engine/phases/upkeep_effects.py, so only the fused
    ``upkeep_pay_or_deal_damage_to_controller`` is dispatched; everywhere else
    the trigger resolves through EFFECT_HANDLERS, where ``self_damage_unless_pay``
    arms the pending optional-pay prompt. Emitting either one under the other's
    trigger produces a card that compiles cleanly and does nothing.
    """
    damage = node.damage
    # "…deals 2 damage to **that player** unless **they** pay {2}" (Soul
    # Barrier, Seizures): payer and recipient are one seat, the one the firing
    # event named and froze into the trigger's context (CR 603.10). Both words
    # are required to agree — a clause damaging one player while offering the
    # cost to another is a card neither flow implements.
    on_event_player = (
        isinstance(node.payer, ast.PlayerRef)
        and node.payer.kind == "that_player"
        and _damaged_player_is(damage.recipients, "that_player")
    )
    if not on_event_player:
        if not _is_you(node.payer):
            raise LoweringError(
                "both pay-or-else flows offer the cost to the ability's controller",
                node=node,
            )
        if not (len(damage.recipients) == 1 and _is_you(damage.recipients[0])):
            raise LoweringError(
                "both pay-or-else flows damage the ability's controller", node=node
            )
    if damage.riders != ast.DamageRiders():
        raise LoweringError("no pay-or-else flow carries damage riders", node=node)
    amount = _amount_payload(damage.amount)
    if not isinstance(amount, int):
        raise LoweringError("a pay-or-else flow needs a fixed damage amount", node=node)

    # "For each land destroyed this way, <source> deals 1 damage to **that
    # land's controller** unless **they** pay {2}." (Stench of Evil.) The seat
    # is neither the ability's controller nor a trigger's frozen event subject:
    # it is a fact an earlier *step of this same spell* recorded about the
    # object the loop is currently on, which is the third channel
    # `PER_OBJECT_SEAT_RECORDS` exists for. Admitted only when a step really
    # wrote that record, which is what `produced` is; without one the words
    # name nobody and the clause keeps the refusal below.
    #
    # The printed possessive collapses to `that_player` in the AST — "that
    # land's controller", "that player" and "they" are one referent to every
    # consumer — so what distinguishes this reading is the record, not the
    # spelling. A card printing a bare "that player" behind such a sweep would
    # reach it too; the handler finds no seat for the loop it is not in, and
    # does nothing, which is the safe direction.
    controller_record = PER_OBJECT_SEAT_RECORDS["controller"]
    if on_event_player and controller_record in produced:
        return (
            OracleInstruction(
                "self_damage_unless_pay", "",
                {
                    "amount": amount,
                    "cost": _generic_only(node.cost, node),
                    "payer_seat_record": controller_record,
                },
            ),
        )
    if event is None:
        raise LoweringError(
            "a pay-or-else damage prompt exists only as a trigger's own effect",
            node=node,
        )
    if event.startswith("upkeep"):
        if event != "upkeep_self":
            raise LoweringError(
                f"no upkeep handler pairs {event!r} with a pay-or-else damage prompt",
                node=node,
            )
        return (
            OracleInstruction(
                "upkeep_pay_or_deal_damage_to_controller", "",
                {"damage": amount, "mana": _full_mana_payload(node.cost)},
            ),
        )

    payload: dict[str, object] = {
        "amount": amount, "cost": _generic_only(node.cost, node),
    }
    if on_event_player:
        # Which seat is offered the cost, as payload rather than a second kind:
        # same prompt, same damage, same decline — only the player differs, and
        # the handler reads the seat off the trigger's frozen context.
        #
        # **Which** frozen key depends on the event, and this branch used to
        # name one without asking. "That player" is the seat the event was
        # *about* under an upkeep or a cast; under a tap it is the seat that
        # controlled the object the event was about, stamped under a different
        # key by a different fire site. Seizures ("whenever enchanted creature
        # becomes tapped, this Aura deals 3 damage to **that creature's
        # controller** unless that player pays {3}") compiled to the first key
        # under an event that stamps the second, so the handler found no seat
        # and the Aura did nothing at all — on every tap, since it was printed.
        if event in _EVENT_SUBJECT_PLAYERS:
            payload["payer"] = EVENT_SUBJECT_PLAYER
        elif event in _EVENT_SUBJECT_CONTROLLERS:
            payload["payer"] = EVENT_SUBJECT_CONTROLLER
        else:
            raise LoweringError(
                f"no event named {event!r} freezes the seat 'that player' names",
                node=node,
            )
    return (OracleInstruction("self_damage_unless_pay", "", payload),)


def _generic_only(cost, node) -> int:
    """The one generic number ``self_damage_unless_pay``'s prompt can charge.

    Refuses a coloured pip rather than dropping it: the prompt puts a single
    generic number on screen, so a coloured cost would be charged as {0} and the
    card would be strictly easier to buy off than it is printed.
    """
    pips = dict(cost.pips)
    generic = int(pips.pop("generic", 0))
    if pips:
        raise LoweringError(
            "the optional-pay prompt reads one generic cost, not coloured mana",
            node=node,
        )
    return generic


def _lower_damage_reduced_by_paid_mana(
    node: ast.DamageReducedByPaidMana,
) -> tuple[OracleInstruction, ...]:
    """Power Leak / Errant Minion's three sentences, with the number as payload.

    The ordinary ``deal_damage`` kind plus one key, not a kind of its own: the
    ``(upkeep_enchanted_controller, deal_damage)`` handler in
    ``engine/phases/upkeep_effects.py`` is what implements the whole clause, and
    a second kind would be a second pair in that registry doing the same thing.

    ``prevent_up_to_paid_mana`` is what that handler used to read as a substring
    of the permanent's oracle text — the gate and the dispatch agreeing by
    coincidence rather than by construction. It is payload now, so a card whose
    clause this production has *not* read cannot be reduced by a payment nobody
    offered.
    """
    if node.amount <= 0:
        raise LoweringError("the upkeep damage takes a fixed amount", node=node)
    return (
        OracleInstruction(
            "deal_damage", "",
            {"amount": node.amount, "prevent_up_to_paid_mana": True},
        ),
    )


def _lower_upkeep_damage_unless_cost(
    node: ast.UpkeepDamageUnlessCost,
) -> tuple[OracleInstruction, ...]:
    """Mishra's War Machine / Minion of Leshrac's two sentences, with the number
    and the cost as payload.

    Fused rather than composed, for the reason the damage family's "unless"
    docstring already gives about this shape: two upkeep handlers implement it
    whole, and the tap rides the *damage* branch — a `May` whose otherwise-arm
    carries a rider is the fusion with extra steps.

    The sacrifice filter goes through the forced-sacrifice reducer, the same one
    every other charged sacrifice in the engine reads, so a noun phrase the
    prompt cannot test refuses the line rather than being charged as "any
    permanent".
    """
    amount = _amount_payload(node.amount)
    if not isinstance(amount, int) or amount <= 0:
        raise LoweringError("the upkeep damage takes a fixed amount", node=node)
    payload: dict[str, object] = {"amount": amount}
    if node.taps_source:
        payload["taps_source"] = True
    if node.discard:
        payload["discard"] = node.discard
        return (OracleInstruction("upkeep_damage_unless_cost", "", payload),)
    assert node.sacrifice is not None
    described = _forced_sacrifice_filter(node.sacrifice)
    if described is None:
        raise LoweringError(
            "the upkeep alternative cannot charge this sacrifice", node=node
        )
    payload["sacrifice"] = described
    # Carried beside the filter rather than inside it: the charger compares by
    # identity against the ability's source, which no filter key can express.
    if node.sacrifice.other_than_source:
        payload["exclude_self"] = True
    return (OracleInstruction("upkeep_damage_unless_cost", "", payload),)


#: What "if you don't" does, as an instruction kind. The sacrifice arm *is*
#: cumulative upkeep — CR 702.24a's own consequence — so it lands on the kind
#: the keyword already produces and is run by the handler that already
#: implements the rule; only the counter word differs, and that is payload
#: there too. The cede arm is its own kind because nothing else does it.
_TOLL_CONSEQUENCE_KINDS = {
    "sacrifice": "cumulative_upkeep",
    "cede_control": "upkeep_counter_toll_or_cede_control",
}


def _lower_upkeep_counter_toll(
    node: ast.UpkeepCounterToll,
) -> tuple[OracleInstruction, ...]:
    """CR 702.24a's ability printed longhand (Phantasmal Sphere, Rogue
    Skycaptain).

    The escalation rides ``per_counter``, the same payload key the keyword form
    carries, so ``cumulative_upkeep.scaled_cost`` is what reads it in both
    cases — one arithmetic, asked by the prompt that quotes the cost and by the
    handler that charges it, which is what keeps what a player is shown and what
    they are charged from disagreeing.

    The cost is written through ``UpkeepCost.payload`` rather than assembled
    here, so an upkeep obligation from this production and one from the keyword
    are read back by the same function (``upkeep_costs.cost_from_payload``) —
    a payload spelled by hand here is how a cost that grows a second component
    later gets dropped on one of the two paths.
    """
    from ...upkeep_costs import UpkeepCost

    kind = _TOLL_CONSEQUENCE_KINDS.get(node.consequence)
    if kind is None:
        raise LoweringError(
            f"no upkeep handler declines this toll with {node.consequence!r}",
            node=node,
        )
    if not node.cost:
        raise LoweringError("an upkeep toll charges something", node=node)
    payload = UpkeepCost(mana=dict(node.cost)).payload()
    payload["per_counter"] = node.counter
    return (OracleInstruction(kind, "", payload),)
