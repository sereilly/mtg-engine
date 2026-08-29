"""Lowering combat restrictions (CR 506, 509).

"Can't attack unless …", "can't be blocked by …", and the unblockable grant
whose power limit the handler hardcodes — recorded here as a value so the
lowering can check it rather than assume it.
"""

from ...oracle_types import OracleInstruction
from ...subject_filters import (OBJECT_ONLY_FILTER_KEYS,
                                TESTABLE_SUBJECT_FILTER_KEYS,
                                untestable_filter_keys)
from .. import ast
from ..errors import LoweringError
from ._common import (
    _filter_payload,
    _is_source,
    _REST_OF_TURN,
    _is_target,
    _restrictions_beyond,
    _targets_only,
)
from ._events import (
    _TAPPED_PERMANENTS,
    _UNTAPPED_PERMANENTS,
    binds_block_pair,
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
    # "Creatures can't attack this turn." (Festival.) The attack twin of the
    # blanket can't-block below, and the same three gates for the same reasons:
    # a duration, a plural subject, and a filter the enforcing gate can test.
    # The gate here is `declare_attackers_step.can_attack`, which tests a filter
    # payload through `subject_matches` — so what it may carry is wider than the
    # blocker gate's three keys, and is held to `TESTABLE_SUBJECT_FILTER_KEYS`
    # for the reason that set exists: a narrowing the matcher cannot test would
    # ground creatures the card never named.
    if node.kind == "cant_attack_until_eot":
        payload = dict(node.payload)
        if payload.get("duration") not in _REST_OF_TURN:
            raise LoweringError(
                "a blanket can't-attack with no end-of-turn duration is a "
                "static ability",
                node=node,
            )
        if not isinstance(node.subject, ast.TargetSpec) or node.subject.quantifier != "all":
            raise LoweringError(
                "the blanket can't-attack reads a plural subject", node=node
            )
        described = _filter_payload(node.subject.filter)
        untestable = untestable_filter_keys(described)
        if untestable:
            raise LoweringError(
                "the attack gate cannot test this restriction: "
                + ", ".join(sorted(untestable)),
                node=node,
            )
        return (
            OracleInstruction("cant_attack_until_eot", "", {"filter": described}),
        )
    # "This creature can't attack unless you sacrifice two Islands." (Leviathan
    # — "This cost is paid as attackers are declared".) CR 508.1g. The filter is
    # held to what the *charger* can test: `_sacrifice_candidate_indices` reads
    # a payload through the same matcher every other sacrifice does, and a
    # narrowing it cannot answer would either charge the wrong permanents or
    # charge none — so an untestable key refuses the line rather than riding
    # along.
    if node.kind == "cant_attack_unless_sacrifice":
        payload = dict(node.payload)
        if not _is_source(node.subject):
            raise LoweringError(
                "the attack cost is paid by the source's controller and "
                "restricts the source",
                node=node,
            )
        described = _filter_payload(payload["sacrifice_filter"])
        untestable = untestable_filter_keys(described, allowed=OBJECT_ONLY_FILTER_KEYS)
        if untestable:
            raise LoweringError(
                "the attack cost cannot be charged against: "
                + ", ".join(sorted(untestable)),
                node=node,
            )
        return (
            OracleInstruction(
                "cant_attack_unless_sacrifice", "",
                {"filter": described, "count": int(payload["sacrifice_count"])},
            ),
        )
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
            if not described or set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
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
    (Disharmony) / "…tap the creature, remove it from combat…" (Imprison).
    CR 506.4c.

    Two refusals, each a way the sentence could otherwise mean more than it
    says — the discipline ``_lower_doesnt_untap_next_step`` states:

    * The subject must be the pronoun "it": the pool prints this sentence only
      as the tail of a conjunction whose head chose the object. A chosen
      target here would be a second, independent choice the card never
      offered (False Orders makes one, and stays a name-keyed hook).
    * A producer must have recorded which permanent that was — whichever of
      the two spellings wrote it, since a tap and an untap both record what
      they affected. The handler reads ids out of the resolution scratchpad,
      and with nothing recorded it would remove nothing while the card
      compiled clean.
    """
    subject = node.subject
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier != "it":
        raise LoweringError(
            "remove-from-combat acts on the object the sentence already chose",
            node=node,
        )
    # **Whichever record the step in front of it wrote.** Disharmony untaps its
    # creature and Imprison taps its own; both sentences then say "remove it
    # from combat", and "it" is what that step affected either way. Asked of
    # `_RECORDED_PERMANENTS` — the keys that hold permanents by id — rather than
    # of one spelling, because naming one producer here would refuse the other
    # card for saying "tap" where this one said "untap".
    source = next(
        (key for key in (_UNTAPPED_PERMANENTS, _TAPPED_PERMANENTS) if key in produced),
        None,
    )
    if source is None:
        raise LoweringError(
            "back-reference to a permanent this effect recorded, with no "
            "producer in this effect",
            node=node,
        )
    return (
        OracleInstruction("remove_from_combat", "", {"permanents_from": source}),
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


def _lower_attacking_doesnt_tap(
    node: ast.AttackingDoesntTap,
) -> tuple[OracleInstruction, ...]:
    """"Attacking doesn't cause creatures you control to tap this combat if
    Johan is untapped." (Johan; CR 508.1f.)

    Two noun phrases, both payload. **Which creatures** the exemption reaches is
    the sentence's subject; **what must stay true** for it to apply is the
    trailing "if …", which is read as a noun phrase about the effect's own
    source rather than as a condition evaluated once. That difference is the
    card: Johan's creatures attack untapped only while Johan himself is
    untapped, so a condition tested at resolution and then forgotten would keep
    the exemption running after he attacked.

    Both are held to ``TESTABLE_SUBJECT_FILTER_KEYS``, the same gate every other
    printed noun phrase passes: a narrowing the matcher cannot test is one the
    declare-attackers step would silently ignore, and an exemption that reaches
    a *wider* set than the card prints is the one failure a combat rule must
    never have.
    """
    subject = node.subject
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier not in ("all", "each"):
        raise LoweringError(
            "an attack-tap exemption names a set of creatures, not one of them",
            node=node,
        )
    if subject.targeted:
        raise LoweringError("an attack-tap exemption does not target", node=node)
    described = subject.filter.to_payload()
    leftover = set(described) - TESTABLE_SUBJECT_FILTER_KEYS
    if leftover:
        raise LoweringError(
            "the attack-tap exemption cannot narrow by: " + ", ".join(sorted(leftover)),
            node=node,
        )
    payload: dict[str, object] = {"filter": described}
    if node.gate_state is not None:
        payload["gate_filter"] = _attack_tap_gate_filter(node)
    return (OracleInstruction("exempt_from_attack_tapping", "", payload),)


def _attack_tap_gate_filter(node: ast.AttackingDoesntTap) -> dict[str, object]:
    """The trailing "if …" as a noun phrase tested against the effect's source.

    "If Johan is untapped" says the same thing as the adjective in "untapped
    creature you control", so it lowers to the same filter key and is answered
    by the same matcher — which is what lets the declare-attackers step ask it
    again at every declaration instead of once at resolution. A state the filter
    has no field for refuses by name rather than being dropped.
    """
    try:
        probe = ast.ObjectFilter(**{node.gate_state: not node.gate_negated})
    except TypeError:
        raise LoweringError(
            f"no permanent filter describes {node.gate_state!r}", node=node
        ) from None
    described = probe.to_payload()
    leftover = set(described) - TESTABLE_SUBJECT_FILTER_KEYS
    if not described or leftover:
        raise LoweringError(
            f"no testable filter says {'not ' if node.gate_negated else ''}"
            f"{node.gate_state!r} of a permanent",
            node=node,
        )
    return described


def _lower_assigns_no_combat_damage(
    node: ast.AssignsNoCombatDamage,
) -> tuple[OracleInstruction, ...]:
    """"This creature assigns no combat damage this turn." (Floral Spuzzem.)

    The subject must be the effect's own source and the window must be the rest
    of the turn, because those are the two things the record behind it can say:
    it is a mark on one permanent, swept by the cleanup step with the rest of
    the turn's marks. A sentence naming somebody else's creature, or a window
    the sweep does not end, refuses rather than lowering onto a record that
    would answer a different question.
    """
    if not _is_source(node.subject):
        raise LoweringError(
            "only the effect's own source can be marked as assigning no "
            "combat damage", node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "an assigns-no-combat-damage mark lasts the rest of the turn and "
            "nothing else ends it", node=node,
        )
    return (OracleInstruction("assign_no_combat_damage_until_eot", "", {}),)
