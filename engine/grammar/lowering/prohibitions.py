"""``<subject> can't be <participle>`` — the prohibitions (CR 509.1b, CR 701.19).

Split off ``lowering/combat.py`` at Visions' first wave, when Heat Wave's
board-wide block restriction took that module past the thousand-line guard; it
had been sitting nineteen lines under it. The line is the printed voice, and it
is a real one: everything left in ``combat`` lowers what a permanent may or may
not **do** — attack, block, be declared, be removed from combat — where every
production here lowers what may not be done **to** one. "Can't be blocked" is
not a restriction on the creature it is printed on, it is a restriction on
everybody else's blockers, and "can't be regenerated" is a restriction on a
replacement effect nobody has arranged yet.

The name is ``permissions``' mirror, one package over on the same list: that
family grants a player something the rules alone would not allow (CR 601.3),
and this one withholds something they would otherwise have. The parse side
keeps ``_parse_cant_be`` in ``effects/combat.py``, where the sentence is one
branch of the "can't" verb table — the same asymmetry ``life``, ``counters``,
``base_pt`` and ``tokens`` each record, and for their reason: the guard fired
on the lowerings.

A family rather than a floor, because ``combat`` does not read it —
``grammar/statement_dispatch.py`` reaches ``_lower_cant_be`` directly, one
layer up — so nothing here is below anything and no lowering family imports
it.
"""

from ...oracle_types import OracleInstruction
from ...subject_filters import (OBJECT_ONLY_FILTER_KEYS,
                                TESTABLE_SUBJECT_FILTER_KEYS)
from .. import ast
from ..errors import LoweringError
from ._common import (
    _REST_OF_TURN,
    _describe_several_targets,
    _describe_targets,
    _filter_payload,
    _is_source,
    _is_target,
    _names_several_targets,
    _targets_only,
)
from ._events import binds_block_pair


def _is_block_pair_reference(subject: ast.Recipient) -> bool:
    """Whether *subject* is the bare "that creature" a block trigger bound.

    Bare is the whole of it: the handler acts on the creature the fire site
    recorded and tests nothing, so a narrowing printed here would be carried
    into a payload nobody reads. Compared for equality against the exact filter
    for the reason :func:`_lower_cant_be` gives — a field added to the AST later
    cannot slip past an equality check the way it can past a field-by-field
    probe.
    """
    return (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "that"
        and not subject.targeted
        and subject.filter == ast.ObjectFilter(card_types=("creature",))
    )


def _lower_cant_be(
    node: ast.CantBe,
    event: str | None = None,
    event_subject: object | None = None,
) -> tuple[OracleInstruction, ...]:
    """"Target creature can't be regenerated/blocked this turn."

    Both handlers act on one creature chosen as the ability is activated and
    honour **no** payload filter — they set a flag on whatever
    ``resolve_target_permanent`` returns. So every restriction the noun phrase
    carries has to be checked here or it would be silently dropped, which is why
    the subject's filter is compared for *equality* against the exact shape each
    handler implements rather than probed field by field: a filter field added
    to the AST later cannot slip through an equality check.

    *event* is the trigger kind the restriction is an effect of, for the reason
    ``_lower_combat_restriction`` above takes one: a subject printed as a bare
    back-reference means the creature *that* trigger bound, and under any other
    trigger it means nothing at all.
    """
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "a restriction with no end-of-turn duration is a static ability, "
            "which needs the CR 613 layers engine",
            node=node,
        )
    # "This creature can't be blocked this turn." (Ghostly Pilferer.) The
    # ability's own source, which is not a target at all — nothing is chosen, so
    # there is no picker and no legality check. Its own instruction kind rather
    # than a flag on the targeted one, the same split "exile it" makes: a
    # handler that resolves a target and one that reads
    # ``context.source_permanent`` share nothing beyond the flag they set.
    if _is_source(node.subject) and node.action == "blocked":
        return (OracleInstruction("grant_unblockable_to_self", "", {}),)
    # "{1}: This creature can't be regenerated this turn." (Clergy of the Holy
    # Nimbus.) The same split one line up, for the other action: the targeted
    # printing picks a creature and this one names the ability's own source, so
    # there is no picker, no legality check and no filter to honour.
    if _is_source(node.subject) and node.action == "regenerated":
        return (OracleInstruction("deny_regeneration_to_self", "", {}),)
    # "Whenever this creature blocks or becomes blocked by a creature, **that
    # creature** can't be regenerated this turn." (Lim-Dûl's Cohort.) The third
    # subject the same action can have, and the only one that is neither chosen
    # nor the source: the other half of the blocking pair, which is a fact only
    # the trigger knows.
    #
    # `binds_block_pair` rather than the kind alone, for the reason it exists —
    # a bare "becomes blocked" firing has several blockers and no way to say
    # which one "that creature" is (CR 509.3c/509.3d), so the sentence would
    # deny regeneration to whichever the fire site happened to list first.
    if node.action == "regenerated" and _is_block_pair_reference(node.subject):
        if not binds_block_pair(event, event_subject):
            raise LoweringError(
                "only a blocks-or-blocked trigger that names one creature "
                "records which creature 'that creature' was",
                node=node,
            )
        return (OracleInstruction("deny_regeneration_to_block_pair", "", {}),)
    # "**X target creatures** with power 2 or less can't be blocked this turn."
    # (Runed Arch.) The one restriction whose handler resolves a list, so the
    # several-target shape is admitted here and nowhere else — every other
    # branch below reads one chosen permanent, and a list arriving at one of
    # those would be collected by the picker and dropped by the handler.
    several = (
        node.action == "blocked"
        and node.by is None
        and isinstance(node.subject, ast.TargetSpec)
        and node.subject.targeted
        and _names_several_targets(node.subject)
    )
    if not (_is_target(node.subject) or several):
        raise LoweringError("no handler for restricting a non-targeted subject", node=node)
    assert isinstance(node.subject, ast.TargetSpec)
    filt = node.subject.filter

    if node.action == "regenerated":
        if filt != ast.ObjectFilter(card_types=("creature",)):
            raise LoweringError(
                "deny_regeneration_to_target honours no target restriction", node=node
            )
        return (
            OracleInstruction("deny_regeneration_to_target", "", _targets_only(node.subject)),
        )

    if node.action == "blocked":
        if node.except_by is not None:
            # "Target creature can't be blocked this turn **except by Walls**."
            # (Joven's Tools.) The granted twin of
            # ``cant_be_blocked_except_by``, and a different instruction from
            # the blacklist beside it for the reason those are two kinds: a
            # blacklist lets everything unnamed through and a whitelist lets
            # none of it through, so a lowering shared between them would give
            # one of the two cards the other's effect.
            if filt != ast.ObjectFilter(card_types=("creature",)):
                raise LoweringError(
                    "the granted blocker whitelist is armed on one "
                    "unnarrowed target creature",
                    node=node,
                )
            if (
                not isinstance(node.except_by, ast.TargetSpec)
                or node.except_by.targeted
                or node.except_by.quantifier not in ("all", "each")
            ):
                raise LoweringError(
                    "the granted blocker whitelist describes a class of "
                    "blocker rather than choosing one",
                    node=node,
                )
            allowed = _filter_payload(node.except_by.filter)
            # A key the blockers step cannot test would be carried and ignored,
            # which on a *whitelist* widens the class allowed through — and an
            # empty description would allow everything, which is the card
            # doing nothing at all.
            #
            # ``OBJECT_ONLY_FILTER_KEYS``, not the wider set: this record is a
            # list of filters on the *attacker*, and the blockers step asks it
            # with neither an observer nor a source, because neither is
            # recoverable — the seat "you control" would name is whoever
            # activated the granting ability, and that is not in the record. A
            # relative narrowing would therefore be dropped at the gate, so it
            # refuses here instead (idiom 2).
            if not allowed or set(allowed) - OBJECT_ONLY_FILTER_KEYS:
                raise LoweringError(
                    "the granted blocker whitelist cannot test this noun "
                    "phrase",
                    node=node,
                )
            payload = _targets_only(node.subject)
            # A **list**, the shape `cant_be_blocked_except_by` already uses for
            # the static printing: the union spelling ("Walls and/or creatures
            # with flying") is the same reader on that side, and one shape is
            # what lets the blockers step ask both with one loop.
            payload["allowed_blockers"] = [allowed]
            return (
                OracleInstruction(
                    "grant_cant_be_blocked_except_by_until_eot", "", payload
                ),
            )
        if node.by is not None:
            # "Target creature can't be blocked **by Walls** this turn."
            # (Tower of Coireall.) The blocker class is payload, exactly as it
            # is on the static printings `engine/combat_restrictions.py`
            # derives — a card naming another subtype, colour or card type is
            # the same restriction, and spelling the noun into the kind would
            # make each printed word a new kind and a new enforcement branch.
            if filt != ast.ObjectFilter(card_types=("creature",)):
                raise LoweringError(
                    "the granted blocker restriction is armed on one "
                    "unnarrowed target creature",
                    node=node,
                )
            if (
                not isinstance(node.by, ast.TargetSpec)
                or node.by.targeted
                or node.by.quantifier not in ("all", "each")
            ):
                raise LoweringError(
                    "the granted blocker restriction describes a class of "
                    "blocker rather than choosing one",
                    node=node,
                )
            described = _filter_payload(node.by.filter)
            # The blockers step tests the phrase with `subject_matches`, so a
            # key outside what that answers would be carried and ignored — and
            # a *dropped* narrowing here makes the creature unblockable by
            # everything, which is the widening direction.
            #
            # ``OBJECT_ONLY_FILTER_KEYS`` for the reason written on the
            # whitelist above: the granted record travels on the attacker and
            # is asked with no observer and no source, so a relative narrowing
            # is one this gate cannot honour rather than one it merely has not
            # met yet.
            if not described or set(described) - OBJECT_ONLY_FILTER_KEYS:
                raise LoweringError(
                    "the granted blocker restriction cannot test this noun "
                    "phrase",
                    node=node,
                )
            payload = _targets_only(node.subject)
            payload["blocker_filter"] = described
            return (
                OracleInstruction(
                    "grant_cant_be_blocked_by_until_eot", "", payload
                ),
            )
        # "Target creature can't be blocked this turn." (Teleport) / "…with
        # **power 2 or less**…" (Dwarven Warriors, Runed Arch) / "…**you
        # control**…" (Goblin Sappers). One production and one handler: what
        # differs between those printings is the noun phrase, which is payload
        # the matcher already answers.
        #
        # It used to be two kinds, the second with "power 2 or less" written as
        # a literal in its own handler *and* again in legality.py's enumerator —
        # so a card printing another threshold, or any other narrowing, refused.
        # The reason given was that a power comparison had no payload form;
        # `ObjectFilter.to_payload` grew one, and the refusal outlived it.
        #
        # The whole noun phrase rides the payload and the handler re-tests it at
        # resolution, so a narrowing is never merely *offered* correctly: CR
        # 608.2b's re-check is what stops a creature that has grown past the
        # bound between activation and resolution from being made unblockable.
        described = _filter_payload(filt)
        if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
            raise LoweringError(
                "the unblockable grant cannot test this noun phrase", node=node
            )
        payload = dict(described)
        if several:
            _describe_several_targets(payload, node.subject)
        else:
            _describe_targets(payload, node.subject)
        return (OracleInstruction("grant_unblockable_to_target", "", payload),)

    raise LoweringError(f"no handler for a {node.action!r} restriction", node=node)
