"""Lowering CR 702.26: a permanent that is treated as though it doesn't exist.

Phasing out and in, the simultaneous swap Time and Tide prints, and the
"can't phase out" prohibition.

Split off ``lowering/board.py`` at Visions' third wave, when two groups'
additions summed past the thousand-line guard at **integration** — on nobody's
branch, for the third time in this set. The line is CR 702.26's own and it is a
real one: a phased-out permanent has not moved zone and has not changed
controller (CR 702.26d — which is why a phase-out must not detach an Aura, the
bug that had Cloak of Invisibility destroying itself every turn), where
everything left in ``board`` regenerates, sacrifices, bounces, exchanges control
or puts a card on the bottom of a library.

A family rather than a floor: ``board`` does not read it, and the parse half
stays in ``effects/board.py``, where a phasing sentence is read beside the other
things that happen to a permanent where it stands. Asymmetric like ``zones``,
``library``, ``mana``, ``redirection``, ``delayed`` and ``prohibitions`` — the
guard fired on the lowerings.
"""

from ...oracle_types import CHOSEN_THIS_WAY_OBJECTS, OracleInstruction
from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS
from .. import ast
from ..errors import LoweringError
from ._common import (_describe_targets, _filter_payload, _is_enchanted,
                      _is_source, _is_target)
from ._events import binds_block_pair
from ._filters import _restrictions_beyond, split_bound_card_type


#: The printed durations a phase-out lock can carry, mapped to the key the
#: record is filed under. Held to ``engine/phasing_locks.LOCK_DURATIONS`` by
#: ``tests/engine/test_phasing_locks.py``: a duration admitted here with no
#: sweep behind it would be a restriction that outlives what the card said,
#: which is the same rule ``keywords.KEYWORD_GRANT_DURATIONS`` states one
#: channel over.
#: One row, because the pool prints one window — see that frozenset for why a
#: second is a card's arrival rather than a line here.
_PHASE_OUT_LOCK_DURATIONS: dict[str, str] = {
    "until_your_next_upkeep": "your_next_upkeep",
}


def _lower_phase_out(
    node: ast.PhaseOut,
    event: str | None = None,
    event_subject: object | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """CR 702.26's two printed shapes: one chosen creature (Teferi, Master of
    Time's −3) and a swept set belonging to a targeted opponent with the
    can't-phase-in rider (Teferi, Timeless Voyager's −8)."""
    subject = node.subject
    # "…then **the chosen permanents** phase out." (Equipoise.) The set the step
    # in front of this one recorded, which is neither a target nor a sweep —
    # the tap family's "those creatures" one printed spelling over, and read the
    # same way: through the record, gated on a step of this effect having
    # written one. Without the gate the words name nothing and the sentence
    # would report supported and phase out an empty set.
    if isinstance(subject, ast.TargetSpec) and subject.quantifier == "chosen":
        if CHOSEN_THIS_WAY_OBJECTS not in produced:
            raise LoweringError(
                "\"the chosen permanents\" names objects no step of this "
                "effect chose", node=node,
            )
        if node.cant_phase_in_until_your_next_turn:
            raise LoweringError(
                "the phase-in block rider only rides the opponent sweep", node=node
            )
        return (
            OracleInstruction(
                "phase_out_recorded_permanents", "",
                {"permanents_from": CHOSEN_THIS_WAY_OBJECTS},
            ),
        )
    if _is_target(subject):
        assert isinstance(subject, ast.TargetSpec)
        if node.cant_phase_in_until_your_next_turn:
            raise LoweringError(
                "the phase-in block rider only rides the opponent sweep", node=node
            )
        payload: dict[str, object] = {}
        _describe_targets(payload, subject)
        return (OracleInstruction("phase_out_target", "", payload),)
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "each"
        and subject.filter.card_types == ("creature",)
        and subject.filter.controller == "target_opponent"
    ):
        return (
            OracleInstruction(
                "phase_out_opponent_creatures",
                "",
                {
                    "cant_phase_in_until_your_next_turn": node.cant_phase_in_until_your_next_turn,
                    "targets": {"quantifier": "target", "kind": "player", "opponents_only": True},
                },
            ),
        )
    # "**This creature** phases out." (Mist Dragon's activated ability, Crystal
    # Golem's end-step trigger, Vaporous Djinn's and Warping Wurm's upkeep, and
    # the win half of Frenetic Efreet's coin flip.) The commonest printed shape
    # in Mirage and the one the target branch above could not read: the sentence
    # names no target at all, so there was nothing for `_describe_targets` to
    # describe.
    if _is_source(subject):
        if node.cant_phase_in_until_your_next_turn:
            raise LoweringError(
                "the phase-in block rider only rides the opponent sweep", node=node
            )
        return (OracleInstruction("phase_out_self", "", {}),)
    # "{U}{U}: **Enchanted creature** phases out." (Vanishing.) The Aura's own
    # attachment, which is neither a target nor the source: the sentence names
    # nothing to pick and the permanent is known from the attachment, so it is
    # its own kind for the reason `untap_enchanted_creature` and
    # `grant_regeneration_to_enchanted_creature` are — routing it through the
    # targeted kind would phase out whatever the resolution happened to hold.
    if _is_enchanted(subject):
        if node.cant_phase_in_until_your_next_turn:
            raise LoweringError(
                "the phase-in block rider only rides the opponent sweep", node=node
            )
        # Idiom 2: the noun is the attachment's own, so "creature" is the only
        # word the attachment already answers. Anything further ("enchanted
        # **untapped** creature") would be a narrowing nothing here tests, and a
        # dropped narrowing on an attachment phases out a permanent the card
        # did not name.
        if _restrictions_beyond(subject.filter, frozenset({"card_types", "is_enchanted"})):
            raise LoweringError(
                "the enchanted phase-out reads no narrowing beyond the noun",
                node=node,
            )
        return (OracleInstruction("phase_out_enchanted", "", {}),)
    # "**All lands you control** phase out." (Taniwha.) A sweep over a printed
    # noun phrase, so the noun phrase is payload and a card printing a different
    # one needs no code here.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier in ("all", "each")
        and not subject.targeted
    ):
        from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS

        # "All nontoken permanents **of that type** phase out." (Teferi's
        # Realm.) The phrase has no payload form of its own, so it is split off
        # and carried as the recorded-choice key the matcher resolves against
        # the ability's source.
        narrowed, bound = split_bound_card_type(subject.filter)
        described = {**_filter_payload(narrowed), **bound}
        # Idiom 2 again: a restriction the matcher cannot test is one the
        # handler would drop, and a dropped narrowing on a *sweep* phases out
        # strictly more of the board than the card prints — here, everyone's
        # lands rather than the controller's.
        leftover = set(described) - TESTABLE_SUBJECT_FILTER_KEYS
        if leftover:
            raise LoweringError(
                "the phase-out sweep cannot narrow by: " + ", ".join(sorted(leftover)),
                node=node,
            )
        if node.cant_phase_in_until_your_next_turn:
            raise LoweringError(
                "the phase-in block rider only rides the opponent sweep", node=node
            )
        return (
            OracleInstruction("phase_out_matching", "", {"filter": described}),
        )
    # "This creature and **that creature** phase out." (Dream Fighter.) The
    # other half of the block CR 509.3a-d announced, which the trigger froze —
    # the same referent `pump_block_pair` and `grant_keyword_to_block_pair`
    # already act on, and read by the one function that knows how the two fire
    # sites bind it (`handlers/_common.block_pair_permanents`).
    #
    # `binds_block_pair` rather than the kind alone, for the reason that helper
    # exists: a *bare* becomes-blocked firing has several blockers and no way to
    # say which one "that creature" is, so the sentence is admitted only where
    # the printed noun phrase narrowed the condition to one.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "that"
        and not subject.targeted
    ):
        if not binds_block_pair(event, event_subject):
            raise LoweringError(
                "\"that creature\" phases out only under a block trigger that "
                "names one creature",
                node=node,
            )
        if _restrictions_beyond(subject.filter, frozenset({"card_types"})):
            raise LoweringError(
                "the bound phase-out reads no narrowing beyond the noun", node=node
            )
        if node.cant_phase_in_until_your_next_turn:
            raise LoweringError(
                "the phase-in block rider only rides the opponent sweep", node=node
            )
        return (OracleInstruction("phase_out_block_pair", "", {}),)
    raise LoweringError("no handler phases out this subject", node=node)

def _lower_simultaneous_phasing(
    node: ast.SimultaneousPhasing,
) -> tuple[OracleInstruction, ...]:
    """Time and Tide, CR 702.26. One instruction, because "simultaneously" is
    what the sentence says and a pair of instructions in a sequence would apply
    in order — phasing a creature in and then straight back out.

    Both noun phrases are payload and both are gated on the keys the matcher can
    actually test, for the reason every sweep in this file is: a dropped
    narrowing here does not phase out fewer permanents, it phases out more.
    """
    from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS

    returning = _filter_payload(node.returning)
    leaving = _filter_payload(node.leaving.filter)
    if node.leaving.quantifier not in ("all", "each") or node.leaving.targeted:
        raise LoweringError(
            "the phasing swap's outgoing half names a described set, not a "
            "chosen permanent",
            node=node,
        )
    for described in (returning, leaving):
        leftover = set(described) - TESTABLE_SUBJECT_FILTER_KEYS
        if leftover:
            raise LoweringError(
                "the phasing swap cannot narrow by: " + ", ".join(sorted(leftover)),
                node=node,
            )
    return (
        OracleInstruction(
            "phase_in_and_out_matching", "",
            {"returning": returning, "leaving": leaving},
        ),
    )

def _lower_cant_phase_out(node: ast.CantPhaseOut) -> tuple[OracleInstruction, ...]:
    """"Until your next upkeep, target permanent **can't phase out**."
    (Spatial Binding, CR 702.26.)

    A lock recorded on the chosen permanent rather than a continuous effect,
    because what it modifies is not a characteristic: nothing about the
    permanent changes, and the only observable moment is a phasing event a turn
    or more later — the shape ``untap_restrictions`` takes for CR 502.3 one step
    over.

    The duration is required. ``engine/phasing_locks.py`` files the record under
    the sweep that ends it, so a printed window with no sweep refuses here
    rather than being recorded and never lifted.
    """
    duration = _PHASE_OUT_LOCK_DURATIONS.get(node.duration.kind or "")
    if duration is None:
        raise LoweringError(
            "a phase-out lock needs a printed duration a sweep ends", node=node
        )
    if not _is_target(node.subject):
        # Every other subject is a sentence nobody prints, and reading one as
        # the target would lock whatever the resolution happened to be holding.
        raise LoweringError(
            "the phase-out lock is placed on a chosen permanent", node=node
        )
    assert isinstance(node.subject, ast.TargetSpec)
    payload: dict[str, object] = {"duration": duration}
    _describe_targets(payload, node.subject)
    return (OracleInstruction("forbid_phase_out", "", payload),)
