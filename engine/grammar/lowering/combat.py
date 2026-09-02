"""Lowering combat restrictions (CR 506, 509).

"Can't attack unless …", "can't be blocked by …", and the unblockable grant
whose power limit the handler hardcodes — recorded here as a value so the
lowering can check it rather than assume it.
"""

import dataclasses

from ...oracle_types import OracleInstruction
from ...subject_filters import (OBJECT_ONLY_FILTER_KEYS,
                                TESTABLE_SUBJECT_FILTER_KEYS,
                                untestable_filter_keys)
from .. import ast
from ..errors import LoweringError
from ._common import (
    _describe_several_targets,
    _describe_targets,
    _filter_payload,
    _is_enchanted,
    _is_source,
    _REST_OF_TURN,
    _is_target,
    _names_several_targets,
    _restrictions_beyond,
    _targets_only,
)
from ._events import (
    _TAPPED_PERMANENTS,
    _UNTAPPED_PERMANENTS,
    binds_block_pair,
)




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
    # "…unless defending player controls an Island" (Sea Serpent) / "…if
    # defending player controls an untapped creature with power 3 or greater"
    # (Goblin Mutant). One kind, one payload: the printed noun phrase and the
    # polarity. It was five basic land *words* welded into a `land_type`
    # string, because the enforcing check scanned the defender's lands by name —
    # so a card naming any other kind of permanent had nowhere to go, and this
    # production refused a phrase the noun parser reads perfectly well.
    #
    # The land scoping the old check spelled out is CR 205.3i's, not this
    # payload's: a land subtype can only be on a land, so "an Island" describes
    # a land whether or not the word is repeated.
    if node.kind == "cant_attack_unless_defender_controls":
        payload = dict(node.payload)
        if not _is_source(node.subject):
            raise LoweringError(
                "the defender-board restriction is read off the creature it "
                "restricts",
                node=node,
            )
        described = _filter_payload(payload["subject"])
        # Idiom 2: the gate tests the phrase with `subject_matches`, so a key
        # that matcher cannot answer would be carried and ignored — and ignoring
        # a narrowing *lifts* the restriction (every board satisfies "controls
        # something"), which is the widening direction.
        untestable = untestable_filter_keys(described)
        if untestable or not described:
            raise LoweringError(
                "the attack gate cannot test what the defender controls: "
                + (", ".join(sorted(untestable)) or "nothing was described"),
                node=node,
            )
        return (
            OracleInstruction(
                "cant_attack_unless_defender_controls", "",
                {"subject": described, "required": bool(payload["required"])},
            ),
        )
    # "Green creatures can't attack unless their controller sacrifices a land of
    # their choice **for each green creature they control that's attacking**."
    # (Flooded Woodlands, Reclamation.) The board-wide twin of Leviathan's cost
    # above: the sentence is printed on a permanent naming a *class*, the payer
    # is that class's controller, and the cost is charged once per attacking
    # member — which is exactly the per-attacker shape `_attack_costs_of`
    # already returns, so the charge and the gate need nothing new.
    if node.kind == "creatures_cant_attack_unless_sacrifice":
        payload = dict(node.payload)
        spec = node.subject
        if not isinstance(spec, ast.TargetSpec) or spec.quantifier != "all":
            raise LoweringError(
                "the board-wide attack cost restricts a printed class of "
                "creatures",
                node=node,
            )
        # The "for each" tail says what the cost scales with, and the only
        # scaling this shape has a charge for is **one per attacking member of
        # the very class the sentence restricts**. Held by equality against the
        # subject with those two words lifted off: a tail naming anything else
        # is a different card, and admitting it would charge for the wrong set
        # while the card compiled clean. Equality rather than a field-by-field
        # probe for the reason `_lower_cant_be` gives — a filter field added to
        # the AST later cannot slip through one.
        per = payload["per"]
        if per.attacking is not True or per.controller != "that_player":
            raise LoweringError(
                "the scaling tail counts the attacking members its controller "
                "controls",
                node=node,
            )
        if dataclasses.replace(per, attacking=None, controller=None) != spec.filter:
            raise LoweringError(
                "the scaling tail names a different set than the restriction",
                node=node,
            )
        subject = _filter_payload(spec.filter)
        untestable = untestable_filter_keys(subject)
        if untestable or not subject:
            raise LoweringError(
                "the attack gate cannot test the restricted class: "
                + (", ".join(sorted(untestable)) or "nothing was described"),
                node=node,
            )
        # "…a land **of their choice**". Lifted off rather than carried: it says
        # the paying player picks, which is what the charger does already
        # (`default_sacrifice_pick` stands in for a chooser it can hand off to),
        # so a payload key would be one nothing reads. What is *not* satisfied
        # by that is somebody else picking, and `chosen_by_opponent` is outside
        # the allowed set below, so it refuses.
        #
        # Named at the call site because ``_filter_payload`` now refuses the
        # word outright: it is the caller's claim that the choice is really
        # made somewhere, and an unnamed key is a refusal.
        described = _filter_payload(
            payload["sacrifice_filter"],
            carried_separately=frozenset({"their_choice"}),
        )
        described.pop("their_choice", None)
        untestable = untestable_filter_keys(described, allowed=OBJECT_ONLY_FILTER_KEYS)
        if untestable:
            raise LoweringError(
                "the attack cost cannot be charged against: "
                + ", ".join(sorted(untestable)),
                node=node,
            )
        return (
            OracleInstruction(
                "creatures_cant_attack_unless_sacrifice", "",
                {
                    "subject": subject,
                    "filter": described,
                    "count": int(payload["sacrifice_count"]),
                },
            ),
        )
    # "This creature can't block white creatures with power 2 or greater."
    # (Orcish Veteran.) The printed noun phrase as the filter list the
    # enforcement site tests against the *attacker*, byte for byte the payload
    # `engine/combat_restrictions.py` builds for the same sentence — a list
    # because the union spelling ("Walls and/or creatures with flying") is the
    # same reader on the other side, and one shape is what keeps the two
    # producers comparable.
    if node.kind == "cant_block_subject":
        from ...subject_filters import unimplemented_filter_keywords

        described = _filter_payload(dict(node.payload)["blockees"])
        # A keyword no behaviour is registered under makes the filter inert, not
        # unreadable — `Game._has_keyword` answers no for every creature — so the
        # restriction would forbid nothing while the card reported supported.
        # The same check `engine/combat_restrictions.py` makes of the same
        # sentence, through the same reader.
        inert = unimplemented_filter_keywords(described)
        if inert:
            raise LoweringError(
                "the blocker gate cannot answer this keyword: "
                + ", ".join(sorted(inert)),
                node=node,
            )
        untestable = untestable_filter_keys(described)
        if untestable or not described:
            # Idiom 2: the gate tests the phrase with `subject_matches`, and an
            # untestable key would be carried and ignored — which for a *block*
            # restriction is the widening direction, a creature that may block
            # attackers the card forbids it.
            raise LoweringError(
                "the blocker gate cannot test what this creature can't block: "
                + (", ".join(sorted(untestable)) or "nothing was described"),
                node=node,
            )
        if not _is_source(node.subject):
            raise LoweringError(
                "this block restriction is read off the creature it restricts",
                node=node,
            )
        return (
            OracleInstruction(
                "cant_block_subject", "", {"blockee_filters": [described]}
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
        if not isinstance(node.subject, ast.TargetSpec):
            raise LoweringError(
                "the blanket can't-block reads a plural subject", node=node
            )
        # "**Target creature** can't block this turn." (Panic.) The same printed
        # sentence about one chosen creature rather than a described set, and a
        # different effect for it: the blanket arms a board-wide filter the
        # blocker gate tests, where this marks the one permanent the spell
        # chose. Two kinds, because the dispatch really is different — folding
        # them would make a targeted restriction reach every creature the noun
        # phrase describes, which on "target creature" is all of them.
        if node.subject.quantifier == "target":
            targeted: dict[str, object] = {}
            _describe_targets(targeted, node.subject)
            return (
                OracleInstruction("target_cant_block_until_eot", "", targeted),
            )
        if node.subject.quantifier != "all":
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
        OracleInstruction(
            "remove_from_combat", "",
            {
                "permanents_from": source,
                # The printed "…and creatures it was blocking … become
                # unblocked" (Imprison). CR 509.1h is the default and this is
                # the sentence that overrides it, so the *card* decides rather
                # than the removal.
                "frees_blocked_attackers": node.frees_blocked_attackers,
            },
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
    # "…you may have **it** assign no combat damage this turn" on an Aura
    # (Cloak of Confusion), where the pronoun was rebound to the permanent the
    # Aura is attached to. The same mark on a different permanent, so the
    # subject is payload rather than a second kind — and it is *which*
    # permanent, not a filter: nothing here chooses.
    if _is_enchanted(node.subject):
        subject = "attached"
    elif (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
    ):
        # "…when **target creature you control** attacks and isn't blocked, **it**
        # assigns no combat damage this turn" (Delif's Cone, Delif's Cube). The
        # delay's opener chose the creature and `rebinding` pointed the pronoun
        # at it (CR 603.7c), so the mark goes on the object the ability is
        # *about* rather than on its source — which for the Cube is the artifact
        # that armed it and is not a creature at all.
        subject = "bound"
    elif _is_source(node.subject):
        subject = ""
    else:
        raise LoweringError(
            "only the effect's own source or the permanent it is attached to "
            "can be marked as assigning no combat damage", node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "an assigns-no-combat-damage mark lasts the rest of the turn and "
            "nothing else ends it", node=node,
        )
    payload = {"subject": subject} if subject else {}
    return (OracleInstruction("assign_no_combat_damage_until_eot", "", payload),)


def _lower_force_chosen_creature_to_attack(
    node: ast.ForceChosenCreatureToAttack,
) -> tuple[OracleInstruction, ...]:
    """Nettling Imp / Norritt's three sentences, as the one instruction the
    engine already had a handler, a target spec and a legality rule for.

    Fused rather than composed into a ``sequence``, and this is the shape the
    composition rule asks for rather than an exception to it: the second and
    third sentences have no subject of their own to compose over — both name
    the creature the first one chose — and the third is conditional on what
    that creature did about the second. Three instructions would need a
    scratchpad key to pass the chosen creature between them and a fourth to
    remember the requirement, which is a fused instruction with extra steps.

    Arcum's Whistle puts a price on it — "That player may pay {X}, where X is
    that creature's mana value. **If they don't pay**, …" — and that half *is*
    composed, through the ordinary offer: the requirement is the offer's
    declined branch and nothing else about it changes. ``that_player`` is the
    seat the ability's own target names (the creature's controller, which this
    template's noun phrase already fixes as the active player), and the price is
    the one computed amount every other offer carries.
    """
    requirement = OracleInstruction("mark_non_wall_target_to_attack", "", {})
    if not node.unless_controller_pays_mana_value:
        return (requirement,)
    return (
        OracleInstruction("may", "", {
            "actor": "that_player",
            "cost": {"generic": "x"},
            "x_from_count": {
                "object_characteristic": {
                    "object": "target", "characteristic": "mana_value",
                    "offset": 0,
                },
            },
            # The **declined** branch, which is where the target lives:
            # `targeting._from_instructions` reads an offer's `otherwise` last
            # and for exactly this reason — CR 601.2c picks the creature as the
            # ability is activated, before anyone is offered the payment.
            "otherwise": (requirement,),
        }),
    )


def _lower_choose_blocks_for_defenders(
    node: ast.ChooseBlocksForDefenders,
) -> tuple[OracleInstruction, ...]:
    """"You choose which creatures block this combat and how those creatures
    block." (Melee.) CR 509.1a's chooser, substituted for this combat.

    Refuses the turn-scoped printing ("this turn", Master Warcraft): the
    substitution is *combat*-scoped state, cleared when the combat phase begins
    and again when it ends, and a turn-scoped one would either have to survive
    that reset or quietly stop applying at the second combat of a turn. Neither
    is what the words say, so the card refuses naming its clause rather than
    working for one combat out of two.
    """
    if node.duration.kind != "until_end_of_combat":
        raise LoweringError(
            "a block-chooser substitution is combat-scoped; nothing carries "
            "one across a combat boundary",
            node=node,
        )
    return (OracleInstruction("choose_blocks_for_defenders", "", {}),)


def _lower_reassign_blockers_between_attackers(
    node: ast.ReassignBlockersBetweenAttackers,
) -> tuple[OracleInstruction, ...]:
    """"Choose two target blocked attacking creatures. If each of those
    creatures could be blocked by all creatures that the other is blocked by,
    …" (General Jarkeld.)

    Two targets of one kind, so the description is the homogeneous one rather
    than Sorrow's Path's ordered roles: neither slot's legal set depends on what
    was chosen for the other. The *relation* between them is a condition the
    handler checks at resolution (CR 608.2b), not a narrowing the picker could
    apply — "could be blocked by all creatures that the other is blocked by" is
    a question about a pair, and a picker that tried to enforce it would have to
    answer it before the pair existed.

    Both printed narrowings are carried and both are testable
    (``TESTABLE_SUBJECT_FILTER_KEYS``): an attacker that is not blocked has no
    blockers to hand over, and one that is not attacking is not in this combat
    at all. A narrowing the matcher could not test would be a restriction the
    dispatcher then ignored, which is the wider-than-printed reading this file
    refuses everywhere.
    """
    subject = node.subject
    if not _names_several_targets(subject) or subject.count != 2:
        raise LoweringError(
            "this reassignment is announced with exactly two chosen attackers",
            node=node,
        )
    filter_payload = _filter_payload(subject.filter)
    untestable = untestable_filter_keys(filter_payload)
    if untestable:
        raise LoweringError(
            f"nothing tests {sorted(untestable)!r} on a chosen attacker",
            node=node,
        )
    if not (filter_payload.get("attacking_only") and filter_payload.get("blocked_only")):
        raise LoweringError(
            "the reassignment moves blockers between *blocked attacking* "
            "creatures; a wider phrase would move blockers off creatures the "
            "sentence never named",
            node=node,
        )
    payload: dict[str, object] = dict(filter_payload)
    _describe_several_targets(payload, subject)
    return (
        OracleInstruction("reassign_blockers_between_attackers", "", payload),
    )
