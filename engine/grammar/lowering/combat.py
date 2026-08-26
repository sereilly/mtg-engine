"""Lowering combat restrictions (CR 506, 509).

"Can't attack unless …", "can't be blocked by …", and the unblockable grant
whose power limit the handler hardcodes — recorded here as a value so the
lowering can check it rather than assume it.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (
    _is_source,
    _REST_OF_TURN,
    _is_target,
    _restrictions_beyond,
    _targets_only,
)
from ._events import (
    _UNTAPPED_PERMANENTS,
)


# The restriction `grant_unblockable_to_low_power_target` hardcodes, in
# engine/handlers/combat.py *and* again in engine/legality.py's target
# enumerator. Written out here so the mismatch is checked rather than assumed.
_UNBLOCKABLE_POWER_LIMIT = ast.Comparison("le", ast.Fixed(2))


#: Trigger events whose fire site stamps the *blocked* creatures onto the
#: stack item (``blocked_permanent_ids``), so an effect may say "that creature"
#: about the other half of the blocking pair and mean it. The block-pair
#: destroy events (`_BLOCK_PAIR_EVENTS`, lowering/board.py) are a different
#: binding — those push the paired creature as the item's *target* — which is
#: why this is its own set rather than a reuse of that one.
_BLOCKED_SUBJECT_EVENTS = frozenset({"creature_blocks"})


def _lower_combat_restriction(
    node: ast.CombatRestriction, event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """``can't attack unless …`` / ``can't block creatures with power N …``.

    Lowers to the instruction kinds the combat steps already dispatch on, with
    the payloads ``engine/combat_restrictions.py`` produces for the legacy path
    — byte for byte, so the differential can hold the two to agreement rather
    than merely to "both did something".

    *event* is the trigger kind when the restriction is a trigger's effect —
    what "that creature" is allowed to refer back to.
    """
    # "That creature can't attack during its controller's next turn." (Wall of
    # Dust.) A one-shot stamp on the creature the trigger blocked, resolved by
    # the handler from the ids the fire site recorded — so the subject must be
    # the bare back-reference (anything more would be a narrowing nothing
    # tests), and the event must be one whose fire site records those ids: on
    # any other trigger the handler would find nothing and the card would
    # compile clean while restricting nobody.
    if node.kind == "cant_attack_during_controllers_next_turn":
        subject = node.subject
        if (
            not isinstance(subject, ast.TargetSpec)
            or subject.quantifier != "that"
            or subject.filter != ast.ObjectFilter(card_types=("creature",))
        ):
            raise LoweringError(
                "the next-turn attack restriction reads the creature its "
                "trigger already named",
                node=node,
            )
        if event not in _BLOCKED_SUBJECT_EVENTS:
            raise LoweringError(
                "only a blocks trigger records which creature 'that creature' "
                "was",
                node=node,
            )
        return (
            OracleInstruction("cant_attack_during_controllers_next_turn", "", {}),
        )
    # "Creatures without flying can't block this turn." (Destructive
    # Tampering's second mode) — a one-shot, turn-scoped blanket over the
    # subject, not a property of a permanent: the payload carries the filter
    # the blocker gate tests, and cleanup sweeps the state it arms. The gate
    # tests card types and (without-)keywords; any other narrowing refuses
    # rather than being dropped.
    if node.kind == "cant_block_until_eot":
        payload = dict(node.payload)
        if payload.get("duration") not in _REST_OF_TURN:
            raise LoweringError(
                "a blanket can't-block with no end-of-turn duration is a "
                "static ability",
                node=node,
            )
        if not isinstance(node.subject, ast.TargetSpec) or node.subject.quantifier != "all":
            raise LoweringError(
                "the blanket can't-block reads a plural subject", node=node
            )
        filt = node.subject.filter
        leftover = _restrictions_beyond(
            filt, frozenset({"card_types", "with_keywords", "without_keywords"})
        )
        if leftover:
            raise LoweringError(
                "the blocker gate cannot test this restriction: " + ", ".join(leftover),
                node=node,
            )
        return (
            OracleInstruction(
                "cant_block_until_eot", "",
                {
                    "filter": {
                        "type_filter": filt.card_types[0] if filt.card_types else "creature",
                        "with_keywords": list(filt.with_keywords),
                        "without_keywords": list(filt.without_keywords),
                    }
                },
            ),
        )
    return (OracleInstruction(node.kind, "", dict(node.payload)),)


def _lower_cant_be(node: ast.CantBe) -> tuple[OracleInstruction, ...]:
    """"Target creature can't be regenerated/blocked this turn."

    Both handlers act on one creature chosen as the ability is activated and
    honour **no** payload filter — they set a flag on whatever
    ``resolve_target_permanent`` returns. So every restriction the noun phrase
    carries has to be checked here or it would be silently dropped, which is why
    the subject's filter is compared for *equality* against the exact shape each
    handler implements rather than probed field by field: a filter field added
    to the AST later cannot slip through an equality check.
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
    if not _is_target(node.subject):
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
        # The unrestricted printing — "Target creature can't be blocked this
        # turn." (Teleport). There is nothing beyond the creature type for a
        # handler to honour, so the target description *is* the whole payload
        # and engine/targeting.py can raise the picker from it.
        if filt == ast.ObjectFilter(card_types=("creature",)):
            return (
                OracleInstruction(
                    "grant_unblockable_to_target", "", _targets_only(node.subject)
                ),
            )
        # The trap: the handler's "power 2 or less" is a literal in its own
        # source, not something it reads from the payload. A card reading
        # "power 3 or less" would compile cleanly and get the wrong threshold,
        # so the parsed comparison is checked against the hardcoded one.
        if filt.power != _UNBLOCKABLE_POWER_LIMIT:
            raise LoweringError(
                "grant_unblockable_to_low_power_target hardcodes 'power 2 or "
                "less'; no handler implements another threshold",
                node=node,
            )
        if filt != ast.ObjectFilter(card_types=("creature",), power=_UNBLOCKABLE_POWER_LIMIT):
            raise LoweringError(
                "grant_unblockable_to_low_power_target honours no further target "
                "restriction",
                node=node,
            )
        # Deliberately *not* described for engine/targeting.py. `ObjectFilter.
        # to_payload` has no vocabulary for a power comparison, so the
        # description would read "target creature" and the picker would offer
        # creatures the ability cannot legally affect. legality.py keeps
        # answering this one until the description vocabulary grows.
        return (OracleInstruction("grant_unblockable_to_low_power_target", "", {}),)

    raise LoweringError(f"no handler for a {node.action!r} restriction", node=node)


def _lower_remove_from_combat(
    node: ast.RemoveFromCombat, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """"Untap target attacking creature **and remove it from combat**."
    (Disharmony, CR 506.4c.)

    Two refusals, each a way the sentence could otherwise mean more than it
    says — the discipline ``_lower_doesnt_untap_next_step`` states:

    * The subject must be the pronoun "it": the pool prints this sentence only
      as the tail of a conjunction whose head chose the object. A chosen
      target here would be a second, independent choice the card never
      offered (False Orders makes one, and stays a name-keyed hook).
    * A producer must have recorded which permanent that was. The handler
      reads ids out of the resolution scratchpad, and with nothing recorded
      it would remove nothing while the card compiled clean.
    """
    subject = node.subject
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier != "it":
        raise LoweringError(
            "remove-from-combat acts on the object the sentence already chose",
            node=node,
        )
    if _UNTAPPED_PERMANENTS not in produced:
        raise LoweringError(
            f"back-reference to {_UNTAPPED_PERMANENTS!r} with no producer in "
            "this effect",
            node=node,
        )
    return (
        OracleInstruction(
            "remove_from_combat", "", {"permanents_from": _UNTAPPED_PERMANENTS}
        ),
    )


def _lower_attack_as_though(node: ast.AttackAsThough) -> tuple[OracleInstruction, ...]:
    """"…can attack this turn as though it didn't have defender."
    (Wall of Wonder.)

    Refuses on two axes, both by name. The **ignored ability** must be one the
    declare-attackers step actually asks about: defender is the only keyword
    that stops an attack by itself, so a permission naming any other word would
    be a clause the engine consumed and nothing acted on. The **duration** must
    be this turn's, because the permission is recorded on the permanent and
    swept by the cleanup step — a durationless printing is the Aura's static
    ability (``engine/auras.py``), which is derived while it is attached rather
    than stamped.
    """
    if node.ignored_keyword != "defender":
        raise LoweringError(
            f"no attack permission ignores {node.ignored_keyword!r}", node=node
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "a durationless attack permission is a static ability, which the "
            "Aura derivation owns rather than an instruction",
            node=node,
        )
    if not _is_source(node.subject):
        raise LoweringError(
            "no handler grants an attack permission to this subject", node=node
        )
    return (OracleInstruction("attack_as_though_no_defender_until_eot", "", {}),)
