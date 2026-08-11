"""Lowering what a permanent is: P/T, keywords, colour, text, counters.

Pump and base-P/T setting (CR 613 layer 7), keyword grants, colour and printed-
text changes, and counters — including the per-death repetition, whose exact
subject is compared for equality rather than pattern-matched, so a card with a
*narrower* subject cannot silently take the same handler.

A continuous effect with no duration is refused here rather than lowered, and
`_durationless_reason` in `_common` says why per subject: the refusal names
what is missing instead of producing an effect that never ends.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (
    _amount_payload,
    _describe_targets,
    _durationless_reason,
    _is_enchanted,
    _is_source,
    _is_target,
    _signed,
)


def _lower_pump(node: ast.Pump) -> tuple[OracleInstruction, ...]:
    power = _signed(node.power, node.power_negative)
    toughness = _signed(node.toughness, node.toughness_negative)

    if node.duration.kind is None:
        raise LoweringError(_durationless_reason(node.subject), node=node)

    if _is_enchanted(node.subject):
        return (
            OracleInstruction(
                "pump_enchanted_creature", "", {"power": power, "toughness": toughness}
            ),
        )
    if _is_source(node.subject):
        return (OracleInstruction("pump_self", "", {"power": power, "toughness": toughness}),)
    if _is_target(node.subject):
        assert isinstance(node.subject, ast.TargetSpec)
        payload: dict[str, object] = {"power": power, "toughness": toughness}
        payload["blocking_only"] = bool(node.subject.filter.blocking)
        _describe_targets(payload, node.subject)
        return (OracleInstruction("pump_target_creature_until_eot", "", payload),)

    # "White creatures get +1/+1", "Attacking creatures get +2/+0 until end of turn"
    if isinstance(node.subject, ast.TargetSpec) and node.subject.quantifier == "all":
        filt = node.subject.filter
        if filt.card_types != ("creature",):
            raise LoweringError("global buff on a non-creature scope", node=node)
        payload = {"power": power, "toughness": toughness}
        if filt.colors:
            payload["color"] = filt.colors[0]
        payload["all"] = filt.controller != "you"
        if filt.attacking:
            payload["attacking_only"] = True
        if filt.blocking:
            payload["blocking_only"] = True
        return (OracleInstruction("buff_creatures_global", "", payload),)

    raise LoweringError("unsupported pump subject", node=node)


def _lower_set_base_pt(node: ast.SetBasePT) -> tuple[OracleInstruction, ...]:
    if node.duration.kind != "until_end_of_turn":
        raise LoweringError("base P/T change needs an end-of-turn duration", node=node)
    if not _is_target(node.subject):
        raise LoweringError("base P/T change on a non-target subject", node=node)
    assert isinstance(node.subject, ast.TargetSpec)
    filt = node.subject.filter
    payload: dict[str, object] = {
        "power": _amount_payload(node.power) if node.power is not None else None,
        "toughness": _amount_payload(node.toughness) if node.toughness is not None else None,
        "exclude_self": filt.other_than_source,
    }
    if node.toughness is None:
        payload["attacking_only"] = bool(filt.attacking)
        payload["flying_only"] = filt.with_keywords == ("flying",)
    return (OracleInstruction("set_base_pt_target_until_eot", "", payload),)


_KEYWORD_GRANTS: dict[tuple[str, str], str] = {
    ("flying", "target"): "grant_target_flying_until_eot",
    ("flying", "self"): "grant_self_flying_until_eot",
    ("banding", "target"): "grant_banding_to_target",
}


def _lower_gain_keyword(node: ast.GainKeyword) -> tuple[OracleInstruction, ...]:
    if node.duration.kind is None:
        reason = _durationless_reason(node.subject)
        if reason.startswith("continuous pump"):
            reason = "continuous keyword grant needs the CR 613 layers engine"
        raise LoweringError(reason, node=node)
    if len(node.keywords) != 1:
        raise LoweringError("multi-keyword grant has no instruction kind", node=node)
    scope = "self" if _is_source(node.subject) else ("target" if _is_target(node.subject) else None)
    if scope is None:
        raise LoweringError("unsupported keyword-grant subject", node=node)
    kind = _KEYWORD_GRANTS.get((node.keywords[0], scope))
    if kind is None:
        raise LoweringError(f"no handler for granting {node.keywords[0]!r} to {scope}", node=node)
    return (OracleInstruction(kind, "", {}),)


def _lower_put_counter(node: ast.PutCounter) -> tuple[OracleInstruction, ...]:
    if not _is_source(node.subject):
        raise LoweringError("counters on a non-source subject", node=node)
    if node.counter != "+1/+1" or node.up_to:
        raise LoweringError(f"no handler for {node.counter} counters", node=node)
    if not isinstance(node.count, ast.Fixed) or node.count.value != 1:
        raise LoweringError("variable counter counts have no handler", node=node)
    return (OracleInstruction("add_counter_to_self", "", {"power": 1, "toughness": 1}),)


# Counter placements repeated once per creature that died this turn, keyed by
# the counter's printed name — the only thing that differs between the two
# cards written this way, and what decides which handler runs. Both handlers
# read the death count from the trigger's own context rather than from the
# payload, so the payloads here are the legacy rules' literals and nothing
# more.
_PER_DEATH_COUNTERS: dict[str, tuple[str, dict[str, object]]] = {
    # Scavenging Ghoul — regeneration fuel, spent by its own activated ability.
    "corpse": ("add_corpse_counters_for_each_creature_died", {}),
    # Khabál Ghoul — P/T counters.
    "+1/+1": ("add_plus1_counters_for_each_creature_died", {"power": 1, "toughness": 1}),
}

# The exact subject both handlers act on. Compared for equality rather than
# probed field by field, so a filter field added to the AST later refuses by
# default instead of being ignored by a lowering written before it existed.
_PER_DEATH_SUBJECT = ast.TargetSpec(
    "this", ast.ObjectFilter(card_types=("creature",), is_source=True)
)

# Both handlers count *every* creature that died, with no narrowing available
# to them, so any filtered set has to refuse rather than over-count.
_ANY_CREATURE_DIED = ast.DiedThisTurn(ast.ObjectFilter(card_types=("creature",)))


def _lower_remove_counter(node: ast.RemoveCounter) -> tuple[OracleInstruction, ...]:
    """``Remove a <kind> counter from this <permanent>`` (Armageddon Clock).

    The counter's name is payload — it is the accumulating side's payload too
    (``upkeep_put_counter_on_self``), so the pair is one template rather than a
    card. What is *not* payload is the subject or the number:
    ``remove_counter_from_self`` reads the ability's own source and decrements by
    one, so anything else refuses rather than compiling onto a handler that
    would quietly do that instead.
    """
    if not _is_source(node.subject):
        raise LoweringError(
            "the only counter-removal handler reads the ability's own source", node=node
        )
    if _amount_payload(node.count) != 1:
        raise LoweringError("no handler removes more than one counter at a time", node=node)
    return (
        OracleInstruction("remove_counter_from_self", "", {"counter": node.counter}),
    )


def _lower_for_each(node: ast.ForEach) -> tuple[OracleInstruction, ...]:
    """"…put a <kind> counter on this creature for each creature that died this
    turn." (Scavenging Ghoul, Khabál Ghoul.)

    The legacy registry needed a whole-sentence substring rule per card, and the
    +1/+1 one carries a comment saying it must out-rank the plain "put a +1/+1
    counter on this creature" rule — which sits 96,500 order slots away, because
    the two rules are unrelated except that one is a prefix of the other. Losing
    that race would drop the per-death scaling and put down a single counter.
    Here the "for each …" clause is a node, so the two shapes are simply
    different ASTs and there is no race to lose.

    Everything else refuses, because neither handler reads anything from its
    payload: the subject, the multiplier and the counted set are all fixed in
    the handler's own source, so a clause differing in any of them would be
    executed as if it had not.
    """
    if node.iterator != _ANY_CREATURE_DIED:
        raise LoweringError("no handler repeats an effect over this set", node=node)
    placement = node.effect
    if not isinstance(placement, ast.PutCounter):
        raise LoweringError("no handler repeats this effect per death", node=node)
    if placement.subject != _PER_DEATH_SUBJECT:
        raise LoweringError(
            "the per-death counter handlers only ever reach their own source", node=node
        )
    if placement.up_to or placement.count != ast.Fixed(1):
        raise LoweringError("no handler places more than one counter per death", node=node)
    found = _PER_DEATH_COUNTERS.get(placement.counter)
    if found is None:
        raise LoweringError(
            f"no handler places {placement.counter!r} counters per death", node=node
        )
    kind, payload = found
    return (OracleInstruction(kind, "", dict(payload)),)


def _lower_become_color(node: ast.BecomeColor) -> tuple[OracleInstruction, ...]:
    """The Lace cycle. `recolor_target_from_text` re-reads the card's own text
    to find the colour, so the payload only names it; the subject must still be
    a chosen target, since the handler recolours what was targeted."""
    if not isinstance(node.subject, ast.TargetSpec) or node.subject.quantifier != "target":
        raise LoweringError("no handler for recolouring a non-targeted object", node=node)
    # Deliberately *not* described for engine/targeting.py. The Lace cycle
    # targets "spell or permanent" — a union of a stack object and a
    # battlefield object that the `targets` vocabulary cannot express. Emitting
    # the generic object shape would derive "permanent" and drop spells on the
    # stack from the picker, so the description is omitted and legality.py
    # keeps answering `spell_or_permanent` until the vocabulary grows.
    return (OracleInstruction("recolor_target_from_text", "", {"target_color": node.color}),)


def _lower_change_text(node: ast.ChangeText) -> tuple[OracleInstruction, ...]:
    """``Change the text of target spell or permanent …`` (CR 612).

    No ``targets`` description is emitted, for the reason the Lace cycle
    established: the vocabulary has no way to say "a spell on the stack *or* a
    permanent", so describing it at all would drop one of the two zones from the
    picker. ``engine/legality.py`` keeps answering ``spell_or_permanent``.
    """
    if not _is_target(node.subject):
        raise LoweringError("a text change has to name what it changes", node=node)
    return (OracleInstruction("mark_text_modified", "", {"mode": node.mode}),)
