"""Lowering the fight (CR 701.14), and the prepare-then-interact pair.

Split out of `damage` the second time that module reached the thousand-line
guard, along the line the CR draws between them: CR 120 is a source dealing
damage to a recipient, CR 701.14 is a **keyword action** — two creatures dealing
damage to *each other*, and doing it atomically (CR 701.14b: if either has left
the battlefield or stopped being a creature, neither deals any). That atomicity
is why `ast.Fight` is one node rather than two damage steps, and it is the same
reason these lowerings share not one helper with the dealing half.

`_fused_prepare_then_interact` is here rather than with the pump it reads
because what it *produces* is the two-fighter pair: the setup is one of several
interchangeable openings, and the exchange is the whole point of the
instruction.

The parse side keeps `Fight` with damage (`effects/damage.py`), where it reads
the same recipient vocabulary — the fourth lowering-only family, for the same
reason as `prevention` and `redirection` before it.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (
    _REST_OF_TURN,
    _amount_payload,
    _describe_targets,
    _filter_payload,
    _is_source,
    _is_target,
)
from ...subject_filters import (unimplemented_filter_keywords,
                                untestable_filter_keys)


def _fused_prepare_then_interact(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"<do something to target 1>. Then <target 1> <fights|bites> target 2."
    (Primal Might, Hunter's Edge.)

    One instruction, because the second sentence's subject **is** the first
    sentence's target: "Then **it** fights…" and "Then **that creature** deals
    damage…" name a creature nobody picks a second time. Lowered as two steps
    the pair compiles cleanly and does the wrong thing — Primal Might did,
    pumping whichever creature its single picker offered and then fighting
    nobody (round 39).

    The two slots are *differently* restricted ("target creature you control",
    "target creature you don't control"), which is what the per-slot `filters`
    of round 40 are for.

    Returning None rather than raising leaves a near-miss to the ordinary step
    lowering, which refuses it by name.
    """
    if len(steps) != 2:
        return None
    setup, interaction = steps

    if isinstance(setup, ast.Pump):
        first = setup.subject
        if setup.duration.kind not in _REST_OF_TURN or setup.power_negative:
            return None
        prepare: dict[str, object] = {
            "kind": "pump",
            "power": _amount_payload(setup.power),
            "toughness": _amount_payload(setup.toughness),
        }
    elif isinstance(setup, ast.PutCounter):
        first = setup.subject
        if setup.counter != "+1/+1" or setup.up_to or setup.then_double:
            return None
        if not isinstance(setup.count, ast.Fixed) or setup.count.value != 1:
            return None
        prepare = {"kind": "counter"}
    else:
        return None

    if isinstance(interaction, ast.Fight):
        subject, second, mode = interaction.subject, interaction.opponent, "fight"
    elif isinstance(interaction, ast.DealDamage):
        # "…deals damage equal to its power to <target 2>" — the one-way half.
        if (
            not isinstance(interaction.amount, ast.ThatMuch)
            or interaction.amount.source != "its_power"
            or len(interaction.recipients) != 1
            or interaction.riders != ast.DamageRiders()
        ):
            return None
        subject, second, mode = (
            interaction.source, interaction.recipients[0], "bite"
        )
    else:
        return None

    # The second sentence has to be *about* the first one's target: either the
    # bare "it"/self reference or the bound "that <noun>". Anything else names
    # something this instruction does not resolve.
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier not in (
        "this", "it", "that"
    ):
        return None
    if subject.quantifier in ("this", "it") and not subject.filter.is_source:
        return None
    if not _is_target(first) or not _is_target(second):
        return None
    assert isinstance(first, ast.TargetSpec) and isinstance(second, ast.TargetSpec)
    return (
        OracleInstruction(
            "prepare_then_interact", "",
            {
                "prepare": prepare,
                "mode": mode,
                "targets": {
                    "quantifier": "target",
                    "kind": "object",
                    "filter": _filter_payload(first.filter),
                    "filters": [
                        _filter_payload(first.filter),
                        _filter_payload(second.filter),
                    ],
                    "count": 2,
                },
            },
        ),
    )


def _two_target_fight(node: ast.Fight) -> tuple[OracleInstruction, ...] | None:
    """"Target creature you control fights target creature an opponent
    controls." (Triangle of War.) Or None when the sentence is not that shape.

    CR 701.14's exchange with **neither** fighter being the ability's source:
    two announcements (CR 601.2c), made independently and answered by a
    two-slot picker, exactly as ``target_bites_target`` answers the one-way
    version of the same sentence. That is why it is its own kind rather than a
    payload key on ``source_fights_target`` — that handler reads one fighter
    off the context and offers one prompt, and a second slot is not something a
    key can add to it.

    Both slots must be *targeted*. "Target creature you control fights another
    creature" would be a different card — CR 601.2c announces nothing for the
    second phrase, so the choice would be made at resolution — and this kind
    builds a cast/activation-time picker for both, so admitting the untargeted
    phrase would raise a prompt for a choice the card never announces.

    The two slots are *differently* restricted, which is the whole point of the
    per-slot ``filters`` list ``target_bites_target`` already carries: one
    filter for both would offer the caster's own board for the second pick and
    let the artifact fight two of its controller's creatures together.
    """
    first, second = node.subject, node.opponent
    if not _is_target(first) or not _is_target(second):
        return None
    assert isinstance(first, ast.TargetSpec) and isinstance(second, ast.TargetSpec)
    if not (first.targeted and second.targeted):
        return None
    described = [_filter_payload(first.filter), _filter_payload(second.filter)]
    for slot in described:
        # Every key has to be one ``subject_matches`` can test, for this
        # package's standing reason: a narrowing the resolution cannot re-check
        # is one the handler would silently drop, and here dropping "an
        # opponent controls" is an artifact that fights its own controller's
        # two creatures against each other.
        if untestable_filter_keys(slot):
            raise LoweringError(
                "the two-target fight cannot test: "
                + ", ".join(sorted(untestable_filter_keys(slot))),
                node=node,
            )
        # And whether it can answer the **value**, not just know the key: a
        # keyword no behaviour is registered under makes ``_has_keyword`` say
        # no for everything, so "target creature **without** flying you
        # control" would offer the whole board. The picker enumerates from the
        # same filter, so an inert word widens what may be *chosen* and not
        # merely what resolves.
        unknown = unimplemented_filter_keywords(slot)
        if unknown:
            raise LoweringError(
                "the two-target fight cannot test the keyword(s): "
                + ", ".join(sorted(unknown)),
                node=node,
            )
    return (
        OracleInstruction(
            "target_fights_target", "",
            {
                "targets": {
                    "quantifier": "target",
                    "kind": "object",
                    "filter": described[0],
                    "filters": described,
                    "count": 2,
                },
            },
        ),
    )


def _lower_fight(
    node: ast.Fight, whole_effect: bool = True
) -> tuple[OracleInstruction, ...]:
    """"This creature fights another target creature." (Brash Taunter.)

    Only the shape where the ability's own source is one of the two fighters:
    the other is a chosen target, so one picker answers the whole clause. A
    fight between *two* chosen creatures picks twice and is a different
    instruction; refusing it here keeps the difference visible rather than
    quietly fighting the source instead.

    ``whole_effect`` is what separates the two spellings of "it". On a
    permanent's own ability it is the source; as the *second sentence* of a
    spell — "Target creature you control gets +X/+X … **Then it** fights up to
    one target creature you don't control" (Primal Might) — it back-references
    the target the first sentence chose, and a sorcery has no source permanent
    at all. Lowered as this instruction, Primal Might pumped whichever creature
    the single picker offered and then fought nobody: supported, and doing
    something else. The fused two-target pair is what that card wants.
    """
    if not whole_effect:
        raise LoweringError(
            "\"it fights\" after another sentence names that sentence's target, "
            "which needs the two-target fused pair",
            node=node,
        )
    if not _is_source(node.subject):
        two = _two_target_fight(node)
        if two is not None:
            return two
        raise LoweringError(
            "only a fight with the ability's own source has a handler", node=node
        )
    if not _is_target(node.opponent):
        raise LoweringError("the creature fought must be a chosen target", node=node)
    assert isinstance(node.opponent, ast.TargetSpec)
    payload: dict[str, object] = {
        "exclude_self": bool(node.opponent.filter.other_than_source),
    }
    _describe_targets(payload, node.opponent)
    return (OracleInstruction("source_fights_target", "", payload),)
