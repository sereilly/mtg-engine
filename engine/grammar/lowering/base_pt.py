"""Lowering CR 613.4b: what a permanent's base power and toughness **are**.

Split out of ``characteristics.py`` at Mirage's third wave, the second time that
module crossed the thousand-line guard and along a line CR 613 already draws.
What stays there **modifies** a characteristic -- a pump (7c), a switch (7d), a
doubling, a colour, a text change -- and what left **replaces** the printed
value: "has base power and toughness 0/2" and "change the base power and
toughness of ... to 0/2" are one write in two printed word orders, and they are
the only two productions in this grammar that reach ``pt.set_base_pt``.

The name is the one ``engine/pt.py`` and ``engine/handlers/base_pt.py`` already
carry for that channel, so the mirror re-forms rather than forking a third
vocabulary.

A family rather than a floor: nothing in ``lowering/`` reads it. ``by_node``
dispatches here by node type through the package's flat re-export, exactly as
it dispatches to the half left behind.
"""

import dataclasses

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._amounts import count_spec
from ._common import (
    _amount_payload,
    _describe_targets,
    _is_source,
    _is_target,
    _restrictions_beyond,
)


#: The base-P/T durations something actually ends, mapped to the word the
#: handler passes on. A table rather than an ``in`` test because that is the
#: whole content of the gate: a duration admitted with no sweep behind it is a
#: rewrite that never expires, which is ``engine/pt.py``'s recorded bug for the
#: 7c channels one layer over.
_BASE_PT_DURATIONS: dict[str, str] = {
    "until_end_of_turn": "end_of_turn",
    # "...until your next upkeep" (Cycle of Life). Swept in the upkeep step's
    # own ``your_next_upkeep`` loop, beside the keyword and type grants that
    # answer to the same printed words.
    "until_your_next_upkeep": "your_next_upkeep",
}

#: The noun-phrase narrowings a base-P/T rewrite can honour, in the picker and
#: at resolution both. Anything else refuses: ``_restrictions_beyond`` is the
#: gate, and without one this lowering read three fields off the filter and
#: dropped every other restriction the phrase carried.
_BASE_PT_TARGET_NARROWINGS = frozenset({
    "card_types",             # "target **creature**"
    "other_than_source",      # "...other than this creature" (Sorceress Queen)
    "attacking",              # "target **attacking** creature" (Singing Tree)
    "with_keywords",          # "...**with flying**" (Island of Wak-Wak)
    "controller",             # "...**you control**" (Chariot of the Sun)
    "cast_by_you_this_turn",  # "...**you cast this turn**" (Cycle of Life)
})


def _lower_set_base_pt(node: ast.SetBasePT) -> tuple[OracleInstruction, ...]:
    duration = _BASE_PT_DURATIONS.get(node.duration.kind)
    if duration is None:
        raise LoweringError("base P/T change needs an end-of-turn duration", node=node)
    # "…**creatures you control** have base power and toughness X/X" (Jolrael).
    # A sweep rather than a target, and the same layer-7b write applied to each
    # — so it is a second kind rather than a flag, because the two resolve
    # completely differently: one asks a picker which permanent, the other asks
    # the board which permanents.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier in ("all", "each")
    ):
        filt = node.subject.filter
        leftover = _restrictions_beyond(filt, frozenset({"card_types", "controller"}))
        if leftover or filt.card_types != ("creature",) or filt.controller != "you":
            raise LoweringError(
                "the team base-P/T handler covers the creatures you control",
                node=node,
            )
        if node.power is None or node.toughness is None:
            raise LoweringError(
                "the team base-P/T handler sets both characteristics", node=node
            )
        if duration != "end_of_turn":
            # The other duration's sweep reads a stamp written on **one**
            # permanent; nothing writes one over a described set, so admitting
            # the word here would be a board-wide rewrite that never ends.
            raise LoweringError(
                "the team base-P/T handler lasts until end of turn", node=node
            )
        return (
            OracleInstruction("set_team_base_pt_until_eot", "", {
                "power": _amount_payload(node.power),
                "toughness": _amount_payload(node.toughness),
            }),
        )
    if not _is_target(node.subject):
        raise LoweringError("base P/T change on a non-target subject", node=node)
    assert isinstance(node.subject, ast.TargetSpec)
    filt = node.subject.filter
    # The gate that was missing: the payload was built from three named fields
    # and every other restriction the noun phrase carried was silently dropped,
    # so a card printing one would have rewritten any creature at all -- the
    # printed restriction enforced by nothing, which a lowering refuses rather
    # than widens.
    leftover = _restrictions_beyond(filt, _BASE_PT_TARGET_NARROWINGS)
    if leftover:
        raise LoweringError(
            f"a base-P/T rewrite carries no {sorted(leftover)} narrowing",
            node=node,
        )
    payload: dict[str, object] = {
        "power": _amount_payload(node.power) if node.power is not None else None,
        "toughness": _amount_payload(node.toughness) if node.toughness is not None else None,
        "exclude_self": filt.other_than_source,
    }
    if node.toughness is None:
        payload["attacking_only"] = bool(filt.attacking)
        payload["flying_only"] = filt.with_keywords == ("flying",)
    # "...target creature **you control**" (Chariot of the Sun). Carried rather
    # than left to the sibling step that happens to print it too: a card whose
    # *only* targeting step is this one would have offered any creature at all.
    # Emitted only when set, so the three cards that print no seat stay
    # byte-identical.
    if filt.controller is not None:
        payload["controller"] = filt.controller
    if filt.cast_by_you_this_turn:
        payload["cast_by_you_this_turn"] = True
    # Omitted at the default, so every instruction written before the second
    # duration existed stays byte-identical -- the rule ``count_spec``'s omitted
    # keys follow, and the reason ``oracle_diff`` stays quiet about cards this
    # change is not about.
    if duration != "end_of_turn":
        payload["duration"] = duration
    return (OracleInstruction("set_base_pt_target_until_eot", "", payload),)


def _lower_change_base_pt(node: ast.ChangeBasePT) -> tuple[OracleInstruction, ...]:
    """The CR 613.4b rewrite template, in Legends' four printings.

    Each branch checks the whole of what it read — the subject, every filter
    restriction, the value's shape and the duration — and refuses by name
    otherwise, because a rewrite that quietly dropped a restriction would set
    the wrong creature's base P/T forever.
    """
    # "…of all creatures that dealt damage to it this turn to 0/2" (Brine
    # Hag): a sweep over the damage record the source carries, not a target.
    if isinstance(node.subject, ast.TargetSpec) and node.subject.quantifier in ("all", "each"):
        filt = node.subject.filter
        if not filt.dealt_damage_to_source_this_turn:
            raise LoweringError(
                "a base-P/T rewrite over a set reads the damage record; "
                "this set names something else", node=node,
            )
        leftover = _restrictions_beyond(
            filt, frozenset({"card_types", "dealt_damage_to_source_this_turn"})
        )
        if leftover or filt.card_types != ("creature",):
            raise LoweringError(
                "the damage-record rewrite covers creatures alone", node=node
            )
        if node.duration.kind is not None:
            raise LoweringError(
                f"no damage-record rewrite expires at {node.duration.kind}", node=node
            )
        if not (isinstance(node.power, ast.Fixed) and isinstance(node.toughness, ast.Fixed)):
            raise LoweringError(
                "the damage-record rewrite takes a printed P/T pair", node=node
            )
        return (
            OracleInstruction("set_base_pt_of_creatures_that_damaged_source", "", {
                "power": node.power.value,
                "toughness": node.toughness.value,
            }),
        )

    if not _is_source(node.subject):
        raise LoweringError(
            "a base-P/T rewrite changes its own source or the damage record",
            node=node,
        )

    # "…to the power and toughness of target creature other than ~ until the
    # end of your next upkeep" (Halfdane): both stats read off one chosen
    # creature when the trigger resolves.
    if node.from_pt_of is not None:
        if node.duration.kind != "until_end_of_your_next_upkeep":
            raise LoweringError(
                "a copied base P/T is implemented for the end of the next "
                f"upkeep, not {node.duration.kind or 'indefinitely'}", node=node,
            )
        spec = node.from_pt_of
        if not (isinstance(spec, ast.TargetSpec) and spec.quantifier == "target"):
            raise LoweringError("a copied base P/T needs a chosen creature", node=node)
        filt = spec.filter
        leftover = _restrictions_beyond(
            filt, frozenset({"card_types", "other_than_source"})
        )
        if leftover or filt.card_types != ("creature",):
            raise LoweringError(
                "the copied-P/T handler reads a creature, optionally excluding "
                "the source", node=node,
            )
        payload: dict[str, object] = {"exclude_self": filt.other_than_source}
        _describe_targets(payload, spec)
        return (
            OracleInstruction(
                "set_source_base_pt_from_target_until_next_upkeep", "", payload
            ),
        )

    # The computed forms that read a **chosen creature** (Sentinel, Sworn
    # Defender). One or both stats, each read off the same target: the quantity
    # carries the sentence's target, so two targets would be two pickers for a
    # card that names one.
    read = _reads_a_target_characteristic(node)
    if read is not None:
        return read

    # The toughness-only computed form over a count (Wall of Tombstones).
    if node.power is not None or node.toughness is None:
        raise LoweringError(
            "a computed base-P/T rewrite sets toughness alone", node=node
        )
    if node.duration.kind is not None:
        raise LoweringError(
            f"no computed base-toughness rewrite expires at {node.duration.kind}",
            node=node,
        )
    bonus, amount = _split_printed_addend(node, node.toughness)

    # "1 plus the number of creature cards in your graveyard" (Wall of
    # Tombstones). `count_spec` is the shared reader, so the count means what
    # it means everywhere else — and refuses the zones and narrowings the
    # counter cannot take.
    if isinstance(amount, ast.CountOf):
        return (
            OracleInstruction("set_source_base_toughness_from_count", "", {
                "bonus": bonus,
                "count": count_spec(amount.filter, node),
            }),
        )
    raise LoweringError(
        f"no base-toughness rewrite reads a {type(amount).__name__}", node=node
    )


#: Which durations a base-P/T rewrite read off a chosen creature is implemented
#: for, and the ``until_eot`` flag each becomes. ``None`` is the absent clause,
#: which CR 611.2a makes "permanently" (Sentinel's "this effect lasts
#: indefinitely" is reminder text for it); Sworn Defender prints the turn.
#: A table rather than two ifs so a third duration refuses by name instead of
#: falling into whichever branch was written first.
_BASE_PT_READ_DURATIONS = {None: False, "until_end_of_turn": True}


def _split_printed_addend(node, amount):
    """``(bonus, rest)`` for "N plus <quantity>" — the printed constant in front
    of a read quantity, and the quantity itself. ``(0, amount)`` when there is
    no sum."""
    if isinstance(amount, ast.Plus):
        if not isinstance(amount.left, ast.Fixed):
            raise LoweringError("the printed addend has to be a number", node=node)
        return amount.left.value, amount.right
    return 0, amount


def _characteristic_read(node, amount):
    """One stat's ``{"characteristic", "offset"}`` payload plus the ``TargetSpec``
    it reads, or None when *amount* reads no chosen object.

    The printed constant reaches the payload from either of the two places a
    card puts it: in front of the phrase ("**1 plus** the power of …", Sentinel)
    or behind it ("the toughness of … **minus 1**", Sworn Defender). Summing
    them here is what makes those one arithmetic rather than two payload keys
    that a handler could read one of and drop the other.
    """
    bonus, rest = _split_printed_addend(node, amount)
    if not isinstance(rest, ast.CharacteristicOfTarget):
        return None
    return rest.subject, {
        "characteristic": rest.characteristic,
        "offset": bonus + rest.offset,
    }


def _reads_a_target_characteristic(node) -> tuple[OracleInstruction, ...] | None:
    """Sentinel's "change this creature's base toughness to 1 plus the power of
    target creature blocking or blocked by this creature" and Sworn Defender's
    "this creature's power becomes the toughness of target creature blocking or
    being blocked by this creature minus 1 …, and its toughness becomes 1 plus
    the power of that creature …" — one instruction for both.

    Returns None without complaint when neither stat reads a chosen object, so
    the count form below keeps its own refusals.

    The **in-combat relation** rides the instruction as its own key rather than
    the filter, because no read of the chosen creature alone can answer it:
    ``engine/legality.py`` tests it at activation and the handler again at
    resolution (CR 608.2b). Both stats must name the same ``TargetSpec`` — the
    parse binds the second clause's pronoun to the first clause's choice, and
    two different specs here would mean the sentence somehow named two.
    """
    reads = {
        stat: _characteristic_read(node, amount)
        for stat, amount in (("power", node.power), ("toughness", node.toughness))
        if amount is not None
    }
    named = {stat: read for stat, read in reads.items() if read is not None}
    if not named:
        return None
    if len(named) != len(reads):
        raise LoweringError(
            "a rewrite reading a chosen creature reads it for every stat it "
            "sets", node=node,
        )
    specs = [spec for spec, _ in named.values()]
    if any(spec is not specs[0] for spec in specs[1:]):
        raise LoweringError(
            "both halves of this rewrite have to read the same creature",
            node=node,
        )
    spec = specs[0]
    if spec.quantifier != "target":
        raise LoweringError(
            "a characteristic read needs a chosen creature", node=node
        )
    if node.duration.kind not in _BASE_PT_READ_DURATIONS:
        raise LoweringError(
            f"no rewrite read off a chosen creature expires at "
            f"{node.duration.kind}", node=node,
        )
    filt = spec.filter
    leftover = _restrictions_beyond(
        filt, frozenset({"card_types", "in_combat_with_source"})
    )
    if leftover or filt.card_types != ("creature",):
        raise LoweringError(
            "the characteristic-read rewrite reads a creature, optionally in "
            "combat with the source", node=node,
        )
    stripped = dataclasses.replace(spec, filter=dataclasses.replace(
        filt, in_combat_with_source=False
    ))
    payload: dict[str, object] = {
        "in_combat_with_source": filt.in_combat_with_source,
        "until_eot": _BASE_PT_READ_DURATIONS[node.duration.kind],
    }
    for stat, (_spec, read) in named.items():
        payload[stat] = read
    _describe_targets(payload, stripped)
    return (OracleInstruction("set_source_base_pt_from_target", "", payload),)
