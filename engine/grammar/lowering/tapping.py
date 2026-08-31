"""Lowering for tapping and untapping (CR 701.20, 701.21).

Split out of ``board`` when that module reached the thousand-line guard. Tapping
is a permanent's **status** (CR 110.5) — orthogonal to what `board` otherwise
covers, which is a permanent's existence and who controls it: destruction,
sacrifice, control change, attachment, phasing. Nothing here reads any of those
and none of them reads this; the five productions shared the module and no
helper.

The untap *restrictions* live here too rather than with the tap that causes
them, because "doesn't untap during its controller's next untap step" is a fact
about the same status, recorded on the permanent and read by the untap step.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS, object_only_filter
from ._common import (
    _describe_several_targets,
    _describe_targets,
    _full_mana_payload,
    _is_enchanted,
    _is_you,
    _targets_only,
    _filter_payload,
    _is_source,
    _is_target,
    _names_several_targets,
    _restrictions_beyond,
    _targets_payload,
)
from ._events import (_EVENT_SUBJECT_PLAYERS, _RECORDED_PERMANENTS,
                      EVENT_SUBJECT_PLAYER, names_attached_permanent)

#: The scratchpad key a tap records what it chose under, so a later sentence
#: ("**it** doesn't untap…") can name the same permanents.
_TAPPED_PERMANENTS = "tapped_permanents"

def _lower_tap(
    node: ast.Tap | ast.Untap,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    if not isinstance(node.subject, ast.TargetSpec):
        raise LoweringError("tap/untap needs an object target", node=node)
    spec = node.subject
    # "…and tap **those creatures**." (Dread Wight.) The bound plural: the set
    # is whatever the sentence in front of this one acted on (CR 611.2c fixed
    # it when the effect began), so nothing is chosen and nothing is swept —
    # the handler reads the record. Asked first, because the branches below
    # read a bound quantifier as nothing they know and would refuse by the
    # wrong name.
    if spec.quantifier == "those" and not spec.targeted:
        if not isinstance(node, ast.Tap):
            raise LoweringError("no handler untaps a bound set", node=node)
        # "Those creatures" restates a set an earlier step chose, so there is
        # nothing here for an adjective to narrow — a filter carrying one would
        # be dropped, and the tap would reach permanents the printed phrase
        # excludes. The same gate ``_lower_doesnt_untap_next_step`` applies to
        # the identical noun phrase.
        if _restrictions_beyond(spec.filter, frozenset({"card_types"})):
            raise LoweringError(
                "a bound plural carries no narrowing the tap could honour",
                node=node,
            )
        recorded = tuple(sorted(produced & _RECORDED_PERMANENTS))
        if not recorded:
            raise LoweringError(
                "\"those creatures\" names objects nothing in this effect "
                "recorded", node=node,
            )
        if len(recorded) != 1:
            raise LoweringError(
                "\"those creatures\" is ambiguous: several earlier steps "
                "recorded objects", node=node,
            )
        return (
            OracleInstruction(
                "tap_recorded_permanents", "", {"permanents_from": recorded[0]}
            ),
        )
    # "…and you tap **that creature**." (Mind Whip.) Under a trigger whose
    # condition already named the permanent the source is attached to, the
    # repeated noun is that permanent — the one reader for both spellings, so
    # this and "tap enchanted creature" cannot come to mean different things.
    # Asked before the branches below, which read a bound quantifier as nothing
    # they know and would refuse a sentence the engine implements.
    if names_attached_permanent(spec, event):
        return (
            OracleInstruction(
                "untap_enchanted_creature" if isinstance(node, ast.Untap)
                else "tap_enchanted_creature",
                "",
                {},
            ),
        )

    # "Untap this artifact" (Basalt Monolith), "untap enchanted creature" and
    # "Tap this creature" (Seasoned Hallowblade) name their subject without a
    # target being chosen — the source and the enchanted permanent are known —
    # so each has its own handler.
    if isinstance(node, ast.Untap):
        if _is_source(spec):
            return (OracleInstruction("untap_self", "", {}),)
        if _is_enchanted(spec):
            return (OracleInstruction("untap_enchanted_creature", "", {}),)
    elif _is_source(spec):
        return (OracleInstruction("tap_self", "", {}),)
    elif _is_enchanted(spec):
        # "When this Aura enters, tap enchanted creature." (Paralyze, Venarian
        # Gold, Cocoon.) The tap twin of the enchanted untap above, for the
        # same reason: the subject is the source's own attachment, so no
        # target exists to route through the targeted tap.
        return (OracleInstruction("tap_enchanted_creature", "", {}),)

    # "Untap up to four lands." (Rewind.) No "target" is printed: nothing is
    # chosen as the spell is cast — the controller picks the lands as it
    # resolves (a pending choice), which is why this branch demands the spec
    # be *untargeted* and why it never reaches engine/targeting.py.
    if (
        isinstance(node, ast.Untap)
        and spec.quantifier == "up_to"
        and not spec.targeted
        and spec.filter.card_types == ("land",)
        and spec.filter == ast.ObjectFilter(card_types=("land",))
    ):
        return (
            OracleInstruction(
                "untap_up_to_matching",
                "",
                {"amount": spec.count, "filter": {"type_filter": "land"}},
            ),
        )
    # "Untap all lands you control." (Reset.) "Tap all legendary creatures."
    # (Arena of the Ancients.) A sweep over a described set: untargeted, so
    # nothing is chosen and every matching permanent is affected. Two gates,
    # the pairing round 68 established: `_restrictions_beyond` reads the AST so
    # a narrowing `to_payload` never emits cannot vanish silently, and the key
    # check holds the payload to what `subject_matches` demonstrates — a key
    # outside that set is one the handler would quietly ignore, which would
    # tap or untap a strictly larger set than the card prints. The honoured
    # fields are only what the pool prints (round 43's rule): a bare type, a
    # supertype (Arena of the Ancients' "legendary"), a colour ("Tap all
    # **blue** creatures", Riptide) and a controller ("you control", Reset).
    # The colour rides as ``color_filter``, which ``subject_matches`` answers
    # through CR 613 layer 5 - so a creature whose colour was changed is swept
    # by what it is, not by what it was printed as.
    # "Tap all creatures blocking target attacking creature." (Feint.) A sweep
    # whose set is not described by any characteristic of its members: they are
    # named by a *relation* to another object the same sentence chooses. So the
    # nested phrase is promoted to the instruction's target description — the
    # attacking creature is what the spell picks (CR 601.2c), and
    # engine/targeting.py derives the picker from that key without knowing this
    # kind exists — and the outer phrase rides as the filter the blockers are
    # tested against.
    #
    # Read before the plain sweep below, which would otherwise refuse the line
    # by name. Only `card_types` beyond the relation, which is round 43's rule:
    # the pool prints "creatures blocking …" and nothing narrower, and a
    # narrowing the handler does not apply would tap a strictly larger set than
    # the card names.
    if (
        isinstance(node, ast.Tap)
        and spec.quantifier in ("all", "each")
        and not spec.targeted
        and spec.filter.blocking_target is not None
    ):
        leftovers = _restrictions_beyond(
            spec.filter, frozenset({"card_types", "blocking_target"})
        )
        if leftovers:
            raise LoweringError(
                "the blocker sweep cannot narrow by: " + ", ".join(leftovers),
                node=node,
            )
        blocked = spec.filter.blocking_target
        blocked_payload = _filter_payload(blocked)
        if set(blocked_payload) - TESTABLE_SUBJECT_FILTER_KEYS:
            raise LoweringError(
                "the blocker sweep cannot test what it blocks", node=node
            )
        described = _filter_payload(
            dataclasses.replace(spec.filter, blocking_target=None)
        )
        if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
            raise LoweringError(
                "the blocker sweep cannot test this restriction", node=node
            )
        payload: dict[str, object] = dict(described)
        payload["targets"] = {
            "quantifier": "target",
            "kind": "object",
            "filter": blocked_payload,
        }
        return (OracleInstruction("tap_creatures_blocking_target", "", payload),)
    if spec.quantifier in ("all", "each") and not spec.targeted:
        # Two checks and they ask different things, which is why both stay.
        # This one is about the **AST**: a field of `ObjectFilter` that
        # `to_payload` does not carry would be a restriction dropped before the
        # matcher ever saw it (round 4's ``_FilterDraft`` bug class), so a field
        # is listed here only once it has been seen to reach the payload. The
        # one below is about the payload: `subject_matches` must be able to test
        # every key in it.
        #
        # "Tap all **Islands**" (Curse of Marit Lage) is why `subtypes` is here.
        # It reaches the payload as `subtype_filter`, which the matcher tests
        # through layer 4 like every other computed type — the same read
        # `supertypes` beside it already relied on.
        # "Tap all **untapped** Islands that player controls" (Monsoon) is why
        # `tapped` is here. It reaches the payload as `untapped_only` — the
        # tri-state's False half, which had no key at all until Enthralling Hold
        # — and `subject_matches` tests it like any other state word. For a tap
        # the narrowing looks harmless (tapping a tapped permanent does
        # nothing), but the *count* behind it is the card, and dropping the word
        # would have counted Islands that were already tapped.
        leftovers = _restrictions_beyond(
            spec.filter,
            frozenset({
                "card_types", "supertypes", "subtypes", "colors", "controller",
                "tapped",
            }),
        )
        if leftovers:
            raise LoweringError(
                "the tap/untap sweep cannot narrow by: " + ", ".join(leftovers),
                node=node,
            )
        described = _filter_payload(spec.filter)
        if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
            raise LoweringError(
                "the tap/untap sweep cannot test this restriction", node=node
            )
        kind = "tap_all_matching" if isinstance(node, ast.Tap) else "untap_all_matching"
        return (OracleInstruction(kind, "", described),)
    if _names_several_targets(spec):
        # "Tap up to two target creatures." (Frost Breath.) The same instruction
        # as the one-target tap — the effect per permanent is identical — with
        # the several-targets opt-in, which is what says the handler resolves a
        # list and the picker collects up to N.
        #
        # Gated to exactly what that handler reads: a *targeted* "up to N" over
        # creatures. `_describe_several_targets` refuses the untargeted spelling
        # itself ("up to four lands", Rewind, is chosen on resolution), and the
        # filter equality keeps a narrowing the handler's
        # `permanent_matches_filter` plus its two seat tests cannot answer from
        # compiling into a wider tap.
        if (
            isinstance(node, ast.Tap)
            and spec.filter.card_types == ("creature",)
            and not _restrictions_beyond(
                spec.filter, frozenset({"card_types", "controller", "other_than_source"})
            )
        ):
            several = _filter_payload(spec.filter)
            _describe_several_targets(several, spec)
            return (OracleInstruction("tap_target_permanent", "", several),)
        # "Untap X target lands." (Candelabra of Tawnos.) Untap reaches the same
        # several-targets opt-in the tap above uses: `untap_target_permanent`
        # resolves a list when the description says there is one.
        #
        # Gated the same way, and for the same reason — the filter must be one
        # the handler's `permanent_matches_filter` can answer in full, or a
        # narrowing would be dropped and the untap would reach more permanents
        # than the card names.
        if (
            isinstance(node, ast.Untap)
            and not _restrictions_beyond(
                spec.filter, frozenset({"card_types", "controller", "other_than_source"})
            )
        ):
            several = _filter_payload(spec.filter)
            _describe_several_targets(several, spec)
            return (OracleInstruction("untap_target_permanent", "", several),)
        raise LoweringError("no handler taps or untaps several targets", node=node)
    if not _is_target(spec):
        raise LoweringError("no handler for non-targeted tap/untap", node=node)
    payload = _filter_payload(spec.filter)

    if isinstance(node, ast.Tap):
        # The handler tests the noun phrase with `subject_matches`, so a key
        # outside what that answers would be carried and ignored — the tap
        # reaching more permanents than the card names. Same gate, same reason,
        # as the sweep above.
        if set(payload) - TESTABLE_SUBJECT_FILTER_KEYS:
            raise LoweringError("the tap cannot test this restriction", node=node)
        tap_payload = dict(payload)
        _describe_targets(tap_payload, spec)
        return (OracleInstruction("tap_target_permanent", "", tap_payload),)

    # Untap has two handlers with different reach: the generic one ignores
    # filters entirely, so a restricted untap must route to the land-specific
    # handler or refuse. Lowering "untap target land" to the generic kind would
    # let it untap a creature.
    if not payload:
        return (OracleInstruction("untap_target_permanent", "", _targets_only(spec)),)
    if payload == {"type_filter": "land"}:
        return (OracleInstruction("untap_target_land", "", _targets_only(spec)),)
    # Every other narrowing rides the generic handler, which applies it. It used
    # to refuse here because that handler ignored filters entirely — lowering
    # "untap target land" onto it would have untapped a creature — and the land
    # form above keeps its own handler so its payload stays byte-identical.
    # The handler tests the noun phrase with `subject_matches`, so the gate is
    # what that answers — the same gate the tap above uses, and for the same
    # reason. It used to be the object-only subset, which refused "untap target
    # attacking creature **you control**" (Ebony Horse): a seat comparison is
    # something the resolution can make and the pure matcher cannot.
    if set(payload) - TESTABLE_SUBJECT_FILTER_KEYS:
        raise LoweringError("no untap handler honors this restriction", node=node)
    untap_payload = dict(payload)
    _describe_targets(untap_payload, spec)
    return (OracleInstruction("untap_target_permanent", "", untap_payload),)


def _lower_untap_chosen_by_paying(
    node: ast.UntapChosenByPaying, event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"…may choose any number of tapped creatures without flying they control
    and pay {2} for each creature chosen this way. If the player does, untap
    those creatures." (Mudslide.)

    Onto ``untap_up_to_matching`` — the prompt that already picks any subset of
    a described set by id and untaps it — with two payload keys rather than a
    kind of its own: *how many* may be chosen (here, however many there are)
    and *what each one costs*. That is the whole difference from Rewind, and a
    second kind would be a second prompt, a second renderer and a second
    action for one added price.

    Two refusals, each a way the sentence could otherwise mean more than it
    says:

    * the noun phrase must be one the picker can test. A narrowing it cannot
      would be handed over and ignored, and "any tapped creature" is a strictly
      larger set than "any tapped creature **without flying**".
    * the payer must be a seat something froze. "That player" under a trigger
      that recorded nobody is a prompt armed on whichever seat the resolution
      happened to carry.
    """
    described = _filter_payload(node.subject)
    if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
        raise LoweringError(
            "the untap picker cannot test this restriction", node=node
        )
    payload: dict[str, object] = {
        # "**Any number**", so the cap is however many the board holds — a
        # number only the resolution can know. The string says so; the handler
        # counts them.
        "amount": "any",
        "filter": described,
        "cost_each": _full_mana_payload(node.cost_each),
    }
    if node.payer.kind == "that_player":
        if event not in _EVENT_SUBJECT_PLAYERS:
            raise LoweringError(
                f"no event named {event!r} freezes the seat 'that player' names",
                node=node,
            )
        payload["who"] = EVENT_SUBJECT_PLAYER
    elif not _is_you(node.payer):
        raise LoweringError(
            f"no untap toll is offered to the {node.payer.kind}", node=node
        )
    return (OracleInstruction("untap_up_to_matching", "", payload),)


def _lower_untap_restriction(
    node: "ast.DoesntUntapNextStep | ast.DoesntUntapWhileCounter",
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """The family entry point: one printed sentence saying a permanent will not
    untap, in either of the two shapes whose subject an earlier step chose.

    A dispatcher rather than two entries in ``lower.py``'s table because the
    two nodes take the same arguments and answer the same question — *which*
    permanents, and what ends the restriction — and because ``produced`` is the
    gate for both.
    """
    if isinstance(node, ast.DoesntUntapWhileCounter):
        return _lower_doesnt_untap_while_counter(node, produced)
    return _lower_doesnt_untap_next_step(node, produced)


def _lower_doesnt_untap_while_counter(
    node: ast.DoesntUntapWhileCounter, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """"Each of those creatures doesn't untap during its controller's untap
    step **for as long as it has a paralyzation counter on it**." (Dread
    Wight.)

    A continuous effect with no end date (CR 611.2b): it stops applying when
    the permanent stops carrying the counter, which is a fact the untap step
    re-asks every turn rather than a marker anything clears. So the counter's
    name is the whole payload beside the set, and the very ability the same
    card grants — "{4}: Remove a paralyzation counter from this creature" — is
    what ends it.

    The three refusals are ``_lower_doesnt_untap_next_step``'s, for its
    reasons: the subject must be the **bound plural** (a chosen target would be
    a second, independent choice the card never offered), it may carry no
    narrowing beyond its card type (there is nothing left for an adjective to
    narrow, and a dropped one would reach permanents the phrase excludes), and
    a producer must have run in this same effect (the handler reads the set out
    of the resolution scratchpad, and with nothing recorded it marks nothing
    while the card compiles clean).
    """
    subject = node.subject
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier != "those":
        raise LoweringError(
            "this sentence acts on the objects an earlier one chose, and its "
            "subject does not name them",
            node=node,
        )
    if _restrictions_beyond(subject.filter, frozenset({"card_types"})):
        raise LoweringError(
            "a bound plural carries no narrowing the marker could honour",
            node=node,
        )
    recorded = tuple(sorted(produced & _RECORDED_PERMANENTS))
    if not recorded:
        raise LoweringError(
            "\"those creatures\" names objects nothing in this effect recorded",
            node=node,
        )
    if len(recorded) != 1:
        raise LoweringError(
            "\"those creatures\" is ambiguous: several earlier steps recorded "
            "objects", node=node,
        )
    return (
        OracleInstruction(
            "restrict_untap_while_counter", "",
            {"counter": node.counter, "permanents_from": recorded[0]},
        ),
    )


def _lower_doesnt_untap_next_step(
    node: ast.DoesntUntapNextStep, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """"Those creatures don't untap during their controller's next untap step."
    (Frost Breath.)

    Three refusals, and each is a way the sentence could otherwise mean more than
    it says:

    * The subject must be the **bound plural** ("those creatures"). A chosen
      target would be a second, independent choice the card never offered; the
      quantifier is what tells them apart.
    * The subject may carry no restriction beyond its card type. "Those
      creatures" restates what the previous sentence already chose, so there is
      nothing here for an adjective to narrow — a filter carrying one would be
      dropped, and the effect would reach permanents the printed adjective
      excludes.
    * A **producer must have run** in this same effect. The handler reads the
      list out of the resolution scratchpad, and with nothing recorded it marks
      nothing while the card compiles clean. This is the same discipline
      ``_back_reference_payload`` applies to "that much".
    """
    subject = node.subject
    # "**It** doesn't untap during its controller's next two untap steps."
    # (Telekinesis.) The singular twin of "those creatures": the bare pronoun,
    # which after a sentence that tapped something names what was tapped. It is
    # told apart from "this creature" by the quantifier the pronoun carries —
    # the printed word for the source is a noun phrase and reads as ``"this"``,
    # and reading them as one would point the marker at the ability's own
    # permanent. The empty filter is kept beside it because that is what makes
    # the pronoun *bare*: "it" narrowed by anything is a phrase this production
    # has not met.
    bare_pronoun = (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "it"
        and subject.filter.is_source
        and subject.filter.to_payload() == {}
    )
    # "**Target creature** doesn't untap during its controller's next untap
    # step." (Barl's Cage.) The whole sentence, with nothing in front of it —
    # so the subject is a choice this ability makes rather than one an earlier
    # step recorded, and there is no producer to require. The two readings are
    # told apart by the printed quantifier and nothing else, which is why the
    # target form carries a ``targets`` description and the bound one carries
    # none: emitting both would ask for a creature the sentence never chooses.
    chosen = (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "target"
        and subject.targeted
    )
    if not bare_pronoun and not chosen and (
        not isinstance(subject, ast.TargetSpec) or subject.quantifier != "those"
    ):
        raise LoweringError(
            "this sentence acts on the objects the previous one chose, and its "
            "subject does not name them",
            node=node,
        )
    if node.count < 1:
        raise LoweringError("a skipped-untap count of none is no restriction", node=node)
    if chosen:
        described = _filter_payload(subject.filter)
        # The handler tests the noun phrase with ``subject_matches``, so a key
        # outside what that answers would be carried and ignored — the marker
        # landing on permanents the printed phrase excludes.
        if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
            raise LoweringError(
                "the untap marker cannot test this restriction", node=node
            )
        payload: dict[str, object] = {**described, "untap_steps": node.count}
        _describe_targets(payload, subject)
        return (OracleInstruction("skip_next_untap", "", payload),)
    if not bare_pronoun and _restrictions_beyond(subject.filter, frozenset({"card_types"})):
        raise LoweringError(
            "a bound plural carries no narrowing the marker could honour", node=node
        )
    if _TAPPED_PERMANENTS not in produced:
        raise LoweringError(
            f"back-reference to {_TAPPED_PERMANENTS!r} with no producer in this effect",
            node=node,
        )
    return (
        OracleInstruction(
            "skip_next_untap", "",
            # ``untap_steps``, not ``steps``: that name is reserved — it is
            # where ``engine/handlers/control_flow.py`` carries a composed
            # effect's nested instructions, and every reader that walks a
            # program recurses into it.
            {"permanents_from": _TAPPED_PERMANENTS, "untap_steps": node.count},
        ),
    )


def _lower_tap_or_untap(node: ast.TapOrUntap) -> tuple[OracleInstruction, ...]:
    """"Tap or untap target <objects>." (Twiddle.)

    The toggle used to honour no restriction at all — ``predicate=lambda p:
    True`` — so any filter had to refuse: "tap or untap target **creature**"
    lowered onto it would have let the card untap a land while still reporting
    supported. It reads the filter now (Tolarian Kraken), the same way the plain
    ``tap_target_permanent`` beside it does, so the narrowing is carried rather
    than refused.

    What still refuses is a narrowing the *matcher* cannot test. The handler asks
    ``subject_matches`` with the resolving seat as its observer, so a *relative*
    phrase is answerable too — "target artifact **an opponent controls**"
    (Hyperion Blacksmith) is a seat comparison, and the picker carries the same
    restriction through the ``opponent_only`` flag ``engine/targeting.py``
    derives, so the list offered and the list accepted are the same list. The
    gate is therefore `TESTABLE_SUBJECT_FILTER_KEYS`, not the object-only
    subset: anything outside it would be dropped where it is applied.
    """
    spec = node.subject
    if not isinstance(spec, ast.TargetSpec) or spec.quantifier != "target":
        raise LoweringError("no handler for a non-targeted tap-or-untap", node=node)
    described = _filter_payload(spec.filter)
    if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
        raise LoweringError("no tap-or-untap handler honours this restriction", node=node)
    payload = _targets_only(spec)
    payload.update(described)
    return (OracleInstruction("tap_or_untap_target", "", payload),)


def _fused_upkeep_pay_to_untap(
    node: ast.TriggeredAbilityNode,
) -> tuple[OracleInstruction, ...] | None:
    """"At the beginning of your upkeep, you may pay {N}. If you do, untap this
    <permanent>." (Mana Vault, Basalt Monolith, Brass Man, Island Fish Jasconius.)

    Fused for the reason every upkeep shape is fused: the dispatcher in
    ``engine/phases/upkeep_effects.py`` is keyed on the (trigger condition,
    instruction kind) pair, and ``upkeep_pay_to_untap_self``'s handler
    implements the whole prompt — the pay/decline choice, the affordability
    check and the untap. A decomposed ``may(pay, untap_self)`` is a truer
    reading of the sentence and has no handler at all.

    Recognised on the **node**, before ``lower_statement`` runs, because two of
    the four cards would never reach a post-hoc check: the generic ``may``
    lowering refuses a coloured optional cost outright (Island Fish Jasconius
    pays {U}{U}{U}), and the refusal is right for every other card that takes
    that path. Only the fused kind's own handler knows how to charge one.

    Returns None — not a refusal — for anything that is not exactly this shape,
    so a near miss ("…untap target creature", "…and you gain 1 life") drops back
    to the ordinary lowering and is refused there by name.
    """
    # "At the beginning of the upkeep of **enchanted creature's controller**,
    # **that player** may pay {4}. If the player does, untap the creature."
    # (Paralyze.) The same sentence with the offer made to somebody else and the
    # untap landing on the attached permanent, which is a second dispatcher in
    # the same registry (``upkeep_pay_to_untap_enchanted``) rather than a second
    # shape — so it is one production with two rows, and the row decides both
    # who is offered and which kind comes out.
    #
    # Fused for a sharper version of the reason above: the decomposed
    # ``may(pay, untap)`` reads "the creature" as the **source**, which on an
    # Aura is the Aura, and the upkeep step gathers this trigger by instruction
    # kind — so the truer-looking reading is a card that compiles clean, is
    # never gathered, and never offers the payment at all.
    if node.intervening_if is not None:
        return None
    fused_kind = {
        "upkeep_self": "upkeep_pay_to_untap_self",
        "upkeep_enchanted_controller": "upkeep_pay_to_untap_enchanted",
    }.get(node.event.kind)
    if fused_kind is None:
        return None
    statement = node.statement
    if not isinstance(statement, ast.May):
        return None
    if statement.action is not None or statement.otherwise is not None:
        return None
    if not isinstance(statement.cost, ast.ManaCost):
        return None
    offered_to_you = node.event.kind == "upkeep_self"
    if _is_you(statement.actor) is not offered_to_you:
        # Whose upkeep it is decides who is offered: "your upkeep" offers you,
        # the enchanted controller's offers "that player". A row whose actor
        # does not match its condition is a sentence neither handler implements.
        return None
    # The consequence is untapping one permanent and nothing else, and *which*
    # permanent is the row's: `upkeep_pay_to_untap_self` untaps ``ctx.permanent``
    # and `…_enchanted` untaps what it is attached to. Neither untap lowering is
    # consulted here — the fused handlers do the untapping themselves — so the
    # subject is checked against the object that row's handler moves rather than
    # against what any untap lowering would accept.
    #
    # Paralyze prints "untap **the** creature", which is a pronoun
    # (`references.py`) and is rebound to the trigger's event subject — the
    # enchanted creature. So the enchanted row's subject is the attached
    # permanent, not the source; reading it as the source only ever worked while
    # the event carried no subject for the pronoun to be pointed at.
    then = statement.then
    if not isinstance(then, ast.Untap):
        return None
    subject_ok = (
        _is_enchanted(then.subject) if fused_kind == "upkeep_pay_to_untap_enchanted"
        else _is_source(then.subject)
    )
    if not subject_ok:
        return None
    return (
        OracleInstruction(
            fused_kind, "", {"mana": _full_mana_payload(statement.cost)}
        ),
    )


def _lower_doesnt_untap_while_source_tapped(
    node: ast.DoesntUntapWhileSourceTapped,
) -> tuple[OracleInstruction, ...]:
    """Phyrexian Gremlins. The subject is the permanent the sentence before it
    tapped — a back-reference, so nothing is described for the picker: the
    choice was made by that sentence and describing it again would ask for a
    second one."""
    subject = node.subject
    # "Tap target artifact. **It** doesn't untap …" — the pronoun refers to the
    # permanent the sentence before it chose. The noun parser collapses a bare
    # "it" onto the same self-reference shape the card's own name produces, so
    # what is required here is that shape and nothing narrower: an adjective
    # would be restating a choice already made, and a *chosen* subject would be
    # a second target the card never offered.
    #
    # The handler reads the chosen target and does nothing when there is none,
    # which is the failing-safe direction — this sentence is only printed after
    # one that chooses.
    if not (
        isinstance(subject, ast.TargetSpec)
        # "**It** doesn't untap…" or the card naming itself — both spellings of
        # the same back-reference, which is why the pronoun's own quantifier is
        # accepted beside "this".
        and subject.quantifier in ("this", "it")
        and subject.filter == ast.ObjectFilter(is_source=True)
    ):
        raise LoweringError(
            "the linked untap restriction acts on the permanent the previous "
            "sentence tapped",
            node=node,
        )
    return (OracleInstruction("restrict_untap_while_source_tapped", "", {}),)
