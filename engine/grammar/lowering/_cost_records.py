"""What a **cost** records when it is paid, and how a sentence names it back.

The other side of the colon from ``_records.py``, and split out of it at ULG
wave 1 when that module reached one line under the size guard. The seam is the
one its docstring has drawn since it was written: ``_PRODUCES`` is keyed by
*instruction kind*, because a step of an effect is an instruction — and nothing
here can be, because a cost is charged by ``engine/mixins/stack/activation.py``
and ``casting.py`` on the way to the stack (CR 601.2h, CR 602.2b) rather than by
anything the dispatcher runs. One table keyed by a **cost node type**, three key
names beside it, and the one function that spells a CR 601.2b optional cost the
same way on both sides of the sentence that reads it.

A **floor**, not a family: six lowering families and ``lower.py`` read one of
these and none of them reads the other way. Importers were pointed here rather
than left going through ``_records`` — a re-export is a hop that is invisible
until somebody greps for the writer, which is precisely the complaint
``_records``' own docstring makes about the fourteen key names it used to reach
through ``_events``.
"""

from __future__ import annotations

from .. import ast
from ..errors import LoweringError


#: Which scratchpad key an activation **cost** writes when it is paid. The twin
#: of ``_PRODUCES`` for the cost side of a colon, and separate from it for the
#: same reason the two sides are separate: a cost is charged by
#: ``engine/mixins/stack/activation.py`` rather than by an instruction, so there
#: is no instruction kind to key it on. Land's Edge's "the discarded card" reads
#: the record this names; a cost added here needs the activation path to record
#: it under the same key, or the condition would compile and read nothing.
#:
#: Beside ``_PRODUCES`` because it is the same question about the other side of
#: the colon, and this module is the one home for "what does a step record?".
#: It sat in `lower.py` while that file was the only reader; the table is a
#: registry either way, and `lower.py` is dispatch.
#: The scratchpad key an untap cost writes. Named rather than spelled twice
#: because three files read it — the table below, the mana lowering's gate and
#: the activation path that writes it — and the failure a third spelling
#: produces is a gate that always refuses.
UNTAPPED_FOR_COST = "untapped_for_cost"
#: The scratchpad key a sacrifice cost writes, named here for
#: ``UNTAPPED_FOR_COST``'s reason one line up: the mana lowering gates on it now
#: ("Add one mana of any type **the sacrificed land** could produce",
#: Squandered Resources), so a second spelling would be a gate that always
#: refuses.
SACRIFICED_FOR_COST = "sacrificed_for_cost"
#: The scratchpad key a **discard** cost writes, named here for the two above's
#: reason and to end a spelling this table had got wrong. The payment path has
#: recorded ``discarded_for_cost`` since Land's Edge; this table declared
#: ``discarded_cards``, a string nothing writes and nothing else reads — so the
#: producer gate in ``_record_conditions`` was asking about a key that could
#: never appear anywhere but in these two files. It worked only because both
#: halves of the question used the same wrong word.
#:
#: Pyromancy is why it matters now: a second reader of the same channel
#: (``_counted_damage._lower_cost_discard_damage``) makes "which key does a
#: discard cost write?" a question with more than one asker, and two answers is
#: how one of them comes to gate on nothing.
DISCARDED_FOR_COST = "discarded_for_cost"

_COST_PRODUCES: dict[type, str] = {
    ast.DiscardCost: DISCARDED_FOR_COST,
    # "Sacrifice a creature: … **If the sacrificed creature was a Thrull**, …"
    # (Ebon Praetor.) The activation path records the permanent the cost ate
    # under ``sacrificed_for_cost``, and the cast path records the same key
    # for an additional cost (``engine/mixins/stack/casting.py``).
    #
    # **Nothing gates on this row today, and that is the honest state rather
    # than an oversight.** ``CostObjectWas`` reads both this channel and the
    # exile one, and it cannot use ``produced``: for a *spell* the cost is a
    # different printed line of the card, which the clause being lowered
    # cannot see, so the gate would refuse Soul Exchange outright. The row
    # stays because it states what the payment path writes, and the reader
    # that would use it is named: ``SacrificedForCost`` (the *amount* — Life
    # Chisel, Diamond Valley) has no check that its ability sacrifices
    # anything at all, and threading ``produced`` into that branch is what
    # this row is for.
    ast.SacrificeCost: SACRIFICED_FOR_COST,
    # "{T}, **Untap a tapped land an opponent controls**: Add one mana of any
    # type **that land** could produce." (Benthic Explorers.) The land the cost
    # untapped, recorded by the activation path so the effect's back-reference
    # has something to name — and, unlike the two rows above, this row really is
    # a gate: the phrase is only meaningful on an ability whose own cost untaps
    # something, and `_lower_add_mana` refuses it without this key.
    ast.UntapPermanentCost: UNTAPPED_FOR_COST,
}


#: Each payment channel's record, as the ``x_from_count`` key the resolution
#: evaluator (``handlers._common.count_from_payload``) reads it under and the
#: characteristics that evaluator can actually answer off it. A sacrificed or a
#: tapped permanent is carried as the ``Permanent``, so its computed P/T is
#: there (CR 608.2h's last-known information for the sacrifice; a plain read for
#: the tap); an exiled or a discarded *card* has no computed characteristics at
#: all (CR 613.1) and keeps only its printed mana value (CR 202.3).
#:
#: One table, so every family that spends a cost record asks the same question
#: of it: the damage lowering's per-channel readability sets are read off these
#: rows (``_counted_damage``), and a where-clause's X reads them through
#: :func:`cost_record_spec`. A characteristic emitted outside its row is a card
#: that reports supported and computes zero.
COST_RECORD_CHANNELS: dict[type, tuple[str, frozenset[str]]] = {
    ast.SacrificedForCost: (
        "cost_sacrifice_characteristic",
        frozenset({"mana_value", "power", "toughness"}),
    ),
    ast.TappedForCost: (
        "cost_tap_characteristic",
        frozenset({"mana_value", "power", "toughness"}),
    ),
    ast.ExiledForCost: ("cost_exile_characteristic", frozenset({"mana_value"})),
    ast.DiscardedForCost: ("cost_discard_characteristic", frozenset({"mana_value"})),
}


def cost_record_spec(definition, node) -> dict[str, object] | None:
    """The ``x_from_count`` spec for a quantity a **cost** recorded, or None
    when *definition* names no payment channel.

    "{1}{B}, Discard a creature card: Volrath the Fallen gets +X/+X until end
    of turn, where X is **the discarded card's mana value**." The number is
    read off the record the activation path kept, at resolution, through the
    same evaluator every other channel reader goes through — so a pump's X and
    a damage's amount cannot read one record two ways. A characteristic the
    evaluator cannot answer refuses, naming the channel.
    """
    row = COST_RECORD_CHANNELS.get(type(definition))
    if row is None:
        return None
    key, readable = row
    if definition.characteristic not in readable:
        raise LoweringError(
            f"no handler reads {definition.characteristic!r} back from a "
            f"{type(definition).__name__} record",
            node=node,
        )
    return {key: definition.characteristic}


def optional_cost_key(symbols: str) -> str:
    """The canonical spelling a CR 601.2b optional additional cost is recorded
    and read back under.

    Here rather than in either family that needs it — ``loops`` lowers "for each
    additional {1}{R} you paid" and ``game`` lowers "plus an additional 3 life
    for each …" — because a fragment two families need cannot live in one of
    them. And here rather than in ``_common`` because it is the same question
    this module already answers: what a step wrote down and how a later sentence
    names it. The step in this case is the *cast* (CR 601.2b), and the record is
    on the stack item's choices rather than in the resolution scratchpad,
    because the mana pool that paid the cost empties at the end of that step
    (CR 500.5).

    Through the same two functions ``cast_costs`` spells its offers with
    (``mana_cost_from_symbols`` then ``mana_cost_label``), so the sentence that
    spends the count and the payment that made it name the offer identically
    however the card printed it. Two readers would be two answers, and the quiet
    one is a loop that never runs.

    Raises when the printed run holds a symbol no payment can spend ({X}, a
    hybrid): the same refusal ``cast_costs`` makes of the offer itself, so a
    sentence cannot read back a cost that side declined to charge.
    """
    from ...mana_payment import mana_cost_from_symbols, mana_cost_label

    parsed = mana_cost_from_symbols(symbols)
    if not parsed:
        raise LoweringError(
            f"no payment spends {symbols!r}, so nothing records paying it"
        )
    return mana_cost_label(parsed)
