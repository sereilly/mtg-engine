"""An X a ``where`` clause defines by a **record** of what already happened.

The half of ``where_x``'s definitions that is not answered by looking at the
game as the clause resolves. Four kinds of record:

* what an earlier step of **this same effect** wrote down (CR 608.2) — "the
  number of creatures that died this way" (Hellfire), "Islands tapped this way"
  (Monsoon), "cards revealed this way" (Cinder Seer), "the milled card's mana
  value" (Infernal Genesis);
* what the spell's or the ability's own **cost** ate (CR 601.2h) — "the exiled
  card's mana value" (Necropolis), "the sacrificed creature's mana value"
  (Burnt Offering), "the total power of the creatures sacrificed this way"
  (Sword of the Ages);
* what the **turn** tallied — "creatures that died under your control this
  turn" (Liliana's Standard Bearer), "damage dealt to this creature this turn"
  (Blazing Effigy);
* what was settled **as the source entered** — "the life paid as this artifact
  entered" (Phyrexian Processor).

``where_x`` keeps the other half — a count of a zone and the arithmetic over
it, the counters on the source, a characteristic of the object the sentence
named — and hands every clause down to :func:`lower_record_definition` once.

Pre-split out of ``where_x`` at the Phase 0 before Odyssey, with that module 35
lines under the thousand-line guard and several of the wave's groups due to add
a definition to it. The seam is not the size and was not drawn here:

* ``ast/records.py`` states it for a *question* — "what stays there is a
  condition answered by looking at the game *now* … and what moved is a
  condition answered by looking at a record of something that has already been
  done" — and ``_record_conditions`` beside this module is that cut on the
  lowering side. ``grammar/records.py`` states it for a *quantity*: what stays
  in ``amounts`` is a quantity the sentence states, "and what moved is a
  quantity the sentence *refers* to". This is the lowering of that quantity in
  the one printed position that wraps a whole sentence.
* ``_counted_pumps._x_definition_spec`` — a where-clause read off a ``Pump`` node
  instead of round a sentence — already divides its definitions by a parameter.
  It reads a board on any call (a count, a maximum, the source's counters, the
  named object's characteristic) and a record only when its caller passes
  ``recorded`` (a cost's, a step's count, a recorded card's mana value): a
  continuous recompute can ask the board again and cannot ask a record again.
* The parse side is part-way there. ``grammar/where_x.py`` imports four of its
  record readers from ``records`` and ``cost_records`` and still reads the
  "this way" participles and three more itself.

The measurement agreed with the prose. Of what ``where_x`` imported,
``_counted_damage``, ``_records``, ``_common`` and ``tapped_this_way_record``
were read by these functions alone; ``count_spec``, the two seat rewrites,
``TARGET_OPPONENT_SCOPE``, ``X_FROM_COUNT`` and ``dataclasses`` by the half
that stayed alone; and beyond the node and error types the halves share exactly
``_mentions_x`` and ``_stamp_x_from_count`` — the check and the stamp every
where-clause makes.

Order is not part of the division. ``lower_where_x`` read these branches
interleaved with its own, and each one answers a node class no other branch on
either side answers — two of them under a printed "<n> plus", which both halves
unwrap and neither answers by itself — so which half reads a clause first
cannot change what either says. The hand-down sits where the first of them was.

**The name.** The mirror's word is ``records``, and ``lowering/_records.py`` is
taken by the ``_PRODUCES`` table, so this carries the word and says what it
holds — the move ``_record_keys`` and ``_record_conditions`` made. One word,
four questions: what a step records, what the key is called, what a sentence
may *ask* of it, and what an X may be *defined* as from it.

A **floor**, not a family, on ``_recipients``' footing: ``where_x`` is its one
reader, a family may not import a sibling, and nothing here reads back.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._amounts import _mentions_x, _stamp_x_from_count, tapped_this_way_record
from ._common import _restrictions_beyond
from ._cost_records import cost_record_spec
from ._records import produced_keys


def lower_record_definition(
    node: ast.WhereX,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...] | None:
    """*inner* with the X a **record** defines stamped onto it, or None when
    the clause's definition is not a record's.

    The one entry point. ``where_x.lower_where_x`` asks it of every clause
    ahead of its own readings and takes None as "not yours" — the contract
    ``lower_counted_gain`` has with ``_lower_gain_life``. A definition that *is*
    a record's and cannot be answered refuses in the branch that read it rather
    than returning None, which would hand the card on to the count's refusal
    with the wrong reason on it.

    The firing event is not passed, because nothing here reads one; a reading
    that comes to need it takes it as a parameter.
    """
    damage = _damage_dealt_definition(node.definition)
    if damage is not None:
        return _lower_where_x_damage_dealt(node, damage, inner)
    if isinstance(node.definition, ast.CountOfDeaths):
        return _lower_where_x_deaths(node, inner, produced)
    if isinstance(node.definition, ast.CountOfDeathsThisWay):
        return _lower_where_x_this_way(node, inner, produced)
    if isinstance(node.definition, ast.CountOfTapsThisWay):
        return _lower_where_x_tapped_this_way(node, inner, produced)
    # "…, where X is the number of cards **revealed this way**." (Cinder Seer,
    # Ivy Seer, Nightshade Seer and their three Scents.) The one definition
    # here that is a plain number rather than a set or a characteristic: the
    # parse resolved the printed noun and participle to a scratchpad key, so
    # what is left to check is that a step of this effect writes it.
    if isinstance(node.definition, ast.ThatMuch):
        return _lower_where_x_recorded(node, inner, produced)
    # "…where X is **the milled card's mana value**." (Infernal Genesis.) A
    # characteristic of the cards a step of this effect recorded; the same
    # producer gate as the count above.
    if isinstance(node.definition, ast.RecordedCardManaValue):
        key = node.definition.record
        if key not in (produced | _records_within(inner)):
            raise LoweringError(
                f"back-reference to {key!r} with no producer in this effect",
                node=node,
            )
        if not _mentions_x(inner):
            raise LoweringError("a where-clause defined an X nothing reads", node=node)
        return _stamp_x_from_count(inner, {"recorded_card_mana_value": key})
    # "…where X is **the exiled card's mana value**" (Necropolis), "…**1 plus**
    # the exiled creature's mana value" (Food Chain), "…the sacrificed
    # creature's mana value" (Burnt Offering), "…the discarded card's mana
    # value", "…the tapped creature's power". What the spell's or the ability's
    # own cost ate (CR 601.2h) — last-known information the payment path
    # recorded (CR 608.2h), which nothing on a board answers for.
    #
    # Through ``_cost_records.cost_record_spec``, the reader the form riding a
    # ``Pump`` node asks: this arm read two of the four channels itself (and
    # their "<n> plus"), that one read all four and no constant, so "the
    # discarded card's mana value" sized Volrath's pump and refused a damage.
    # The table behind it holds each channel to the characteristics the
    # evaluator answers; one outside its row refuses there, naming the channel.
    paid = cost_record_spec(node.definition, node)
    if paid is not None:
        if not _mentions_x(inner):
            raise LoweringError("a where-clause defined an X nothing reads", node=node)
        return _stamp_x_from_count(inner, paid)
    if isinstance(node.definition, ast.LifePaidAsEntered):
        return _lower_where_x_life_paid(node, inner)
    if isinstance(node.definition, ast.TotalPowerSacrificedThisWay):
        return _lower_where_x_sacrificed_power(node, inner)
    return None


def _lower_where_x_life_paid(
    node: ast.WhereX, inner: tuple[OracleInstruction, ...]
) -> tuple[OracleInstruction, ...]:
    """"…, where X is the life paid as this artifact entered."
    (Phyrexian Processor.)

    Not a count of anything and not a recompute: the number was chosen once, as
    a CR 614.1c replacement while the permanent was entering, and is read
    unchanged however many activations later. So it travels as a ``source_record``
    — the same channel Spiny Starfish's regeneration tally already rides — and
    the evaluator reads it off the ability's own source.

    Beside the two cost channels rather than under ``count_spec`` for that
    reason: a cost is paid as *this* ability is activated and a count is taken
    as it resolves, while this was settled before either happened.
    """
    from ...enter_effects import LIFE_PAID_AS_ENTERED

    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(inner, {"source_record": LIFE_PAID_AS_ENTERED})


def _lower_where_x_sacrificed_power(
    node: ast.WhereX, inner: tuple[OracleInstruction, ...]
) -> tuple[OracleInstruction, ...]:
    """"…where X is the total power of the creatures sacrificed this way."
    (Sword of the Ages.)

    Not a count of a set on any board, so it carries no owner and no zone: the
    creatures were eaten by this ability's own cost (CR 601.2h) and are cards in
    a graveyard by the time X is read. What is summed is their last power on the
    battlefield (CR 608.2h), recorded as the cost was charged.

    Only "creatures" is admitted, because that is the only set the cost charger
    records — a card printing another noun would be aggregating over a payment
    nothing kept, and lowering refuses rather than reading a zero.
    """
    filt = node.definition.filter
    if filt.card_types != ("creature",) or _restrictions_beyond(
        filt, frozenset({"card_types"})
    ):
        raise LoweringError(
            "the sacrificed total is read off creatures and nothing narrower",
            node=node,
        )
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(inner, {"cost_sacrifices_power": True})


def _lower_where_x_deaths(
    node: ast.WhereX,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"…where X is the number of creatures that died under your control this
    turn." (Liliana's Standard Bearer.)

    The count is a per-seat turn history (``engine/models.py``'s
    ``creatures_died_under_your_control_this_turn``, kept since round 14 because
    the game-wide tally cannot answer "under your control"), so it reads a
    counter rather than a zone. Only the bare creature filter is admitted: the
    tracker counts creatures and nothing narrower, and a narrowing it cannot
    apply would be counted as if it were not there.
    """
    filt = node.definition.filter
    if filt.to_payload() != {"type_filter": "creature"} or filt.zone != "battlefield":
        raise LoweringError(
            "the death tracker counts creatures and cannot be narrowed", node=node
        )
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(inner, {"history": "creatures_died_under_your_control"})


def _lower_where_x_this_way(
    node: ast.WhereX,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"…, where X is the number of creatures that **died this way**."
    (Hellfire.)

    A back-reference, not a count of a zone: the objects are exactly the ones
    an earlier step of this same effect destroyed, and by the time this is asked
    they are in graveyards. So it is stamped like every other where-clause and
    resolved at the same dispatch point, reading the scratchpad key the sweep
    handlers write.

    Refused without a producer, for the reason every back-reference in this file
    is: "this way" with no earlier step names nothing, and `count_from_payload`
    would answer 0 — a card that reports supported and deals three damage
    flat.

    Only the bare creature filter is admitted. The record is a *number*, not the
    set, so a narrower noun phrase ("the number of **black** creatures that died
    this way") is a question nothing can re-ask — it would be counted as though
    the narrowing were not there.
    """
    filt = node.definition.filter
    if filt.to_payload() != {"type_filter": "creature"} or filt.zone != "battlefield":
        raise LoweringError(
            "'died this way' counts what the earlier step destroyed and cannot "
            "be narrowed further", node=node,
        )
    if "destroyed_this_way" not in produced:
        raise LoweringError(
            "'died this way' with no earlier step in this effect that destroyed "
            "anything", node=node,
        )
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(inner, {"back_reference": "destroyed_this_way"})


def _records_within(instructions: tuple[OracleInstruction, ...]) -> frozenset[str]:
    """Every scratchpad key *instructions* and their nested steps record.

    "This way" names an earlier step of the **same effect**, and *produced* — the
    set threaded between the sentences of a paragraph — cannot see inside the
    sentence the where-clause wraps. Hellfire prints the sweep and the count in
    two sentences, so the thread carried it; Monsoon prints "tap all untapped
    Islands … **and** this enchantment deals X damage …, where X is the number
    of Islands tapped this way" as one, and the producer is a step of the very
    tuple being stamped.

    Read through ``_PRODUCES`` like every other question about what a step
    records, so a producer has one declaration however deeply it is nested.
    """
    keys: set[str] = set()
    for instruction in instructions:
        keys |= produced_keys(instruction)
        for key in ("steps", "then", "else", "otherwise", "action"):
            nested = instruction.payload.get(key)
            if (
                isinstance(nested, tuple) and nested
                and isinstance(nested[0], OracleInstruction)
            ):
                keys |= _records_within(nested)
    return frozenset(keys)


def _lower_where_x_recorded(
    node: ast.WhereX,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"…, where X is the number of cards **revealed this way**." (Cinder Seer.)

    ``_lower_where_x_this_way`` with the narrowing question already settled:
    the parse resolved the printed noun *and* participle together against
    ``where_x.accept_this_way_count``'s table, so by the time the node is built
    the words have been checked against the record they name and what arrives
    is a key. What is left is the gate every back-reference in this file
    carries — a step of this same effect has to write it — and it is asked of
    ``produced`` **and** of the sentence being stamped, because a card may
    print the producer and the reader as two sentences (the five Seers, whose
    activated ability is a paragraph) or as one.

    A printed bonus refuses: "where X is the number of cards revealed this way
    **plus one**" is a number no card prints here, and the ``x_from_count``
    spec's ``plus`` is written by the arithmetic unwrapping in
    ``where_x.lower_where_x``, not by this channel.
    """
    if node.definition.source is None or node.definition.bonus:
        raise LoweringError(
            "a where-clause reads a named record with no printed bonus",
            node=node,
        )
    if node.definition.source not in (produced | _records_within(inner)):
        raise LoweringError(
            f"back-reference to {node.definition.source!r} with no producer in "
            "this effect",
            node=node,
        )
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(inner, {"back_reference": node.definition.source})


def _lower_where_x_tapped_this_way(
    node: ast.WhereX,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"…, where X is the number of Islands **tapped this way**." (Monsoon.)

    ``_lower_where_x_this_way`` one verb over, and refused on the same three
    questions. What the sweep tapped is not what the board now holds tapped —
    an Island that was already tapped is not one this effect turned, and CR
    611.2c fixed the set when the effect began — so the number can only come
    from the record the sweep wrote.

    Only the bare head noun is admitted, for the reason the death form states:
    the record is a *number*, not the set, so a narrower noun phrase would be
    counted as though the narrowing were not there. The sweep's own narrowings
    ("untapped", "that player controls") are exactly the ones the card leaves
    off the where-clause, which is why the head noun is enough.
    """
    record = tapped_this_way_record(
        node.definition.filter, produced | _records_within(inner), node,
    )
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(inner, {"back_reference": record})


def _damage_dealt_definition(definition) -> "tuple[ast.DamageDealtThisTurn, int] | None":
    """The damage history a where-clause defines, and the constant added to it.

    "…where X is **3 plus** the amount of damage dealt …" (Blazing Effigy). The
    sum is unwrapped here rather than in the branch below, exactly as
    ``lower_where_x`` unwraps ``ast.Times``: the base belongs to the clause, not
    to the history, and a definition that is a sum over anything *else* falls
    through to the readings and the refusals behind this one rather than
    silently losing its left half.
    """
    base = 0
    if isinstance(definition, ast.Plus) and isinstance(definition.left, ast.Fixed):
        base = int(definition.left.value)
        definition = definition.right
    if isinstance(definition, ast.DamageDealtThisTurn):
        return definition, base
    return None


def _lower_where_x_damage_dealt(
    node: ast.WhereX,
    damage: "tuple[ast.DamageDealtThisTurn, int]",
    inner: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """"…, where X is 3 plus the amount of damage dealt to this creature this
    turn by other sources named ~." (Blazing Effigy.)

    Stamped like every other where-clause and resolved at the same single
    dispatch point; what differs is only what is read. The record is
    ``engine/damage_ledger.py`` — a history, because the creature the clause
    asks about is in a graveyard by the time a dies-trigger asks, and the damage
    marked on it went with it (CR 400.7).

    Every narrowing the words printed rides on the spec, ``base`` included, so
    the reader applies all of them or none: a base honoured at one return site
    and forgotten at another is the dropped-rider bug with an arithmetic face,
    and here it is the difference between three damage and none.
    """
    definition, base = damage
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(
        inner,
        {
            "damage_ledger": {
                "recipient": definition.recipient,
                "source_name": definition.source_name,
                "others_only": definition.others_only,
                "base": base,
            }
        },
    )
