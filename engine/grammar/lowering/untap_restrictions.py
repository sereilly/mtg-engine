"""Lowering the untap **restrictions** (CR 502.3).

Split out of ``lowering/tapping.py`` at the thousand-line cap, along the
boundary that module's own docstring already drew and then argued against: the
restrictions lived with the tap that causes them because both are about a
permanent's status (CR 110.5). They are not the same question. CR 701.26a is a
keyword action a resolving effect performs *now* — turn this permanent
sideways — and everything left in ``tapping`` performs one. CR 502.3 is
"effects can keep one or more of a player's permanents from untapping": a
continuous effect (CR 611.2a) whose only observable moment is a turn-based
action a turn or more later, so every production here lowers to a **record**
somebody else reads back — a marker on the restricted permanent, a counter's
name it travels with, or an id on the source that is holding it down.

The name is the one ``engine/untap_restrictions.py`` already carries, which is
the same sentence read off a permanent's *own printed line* rather than left
behind by a resolving spell ("This creature doesn't untap during your untap
step"). Reusing it is the mirror re-forming rather than forking, exactly as
``counters``, ``tapping`` and ``upkeep`` each did when they left a module.

The two halves share no helper and no name in either direction, checked at the
split: the one thing they had in common was the scratchpad key a tap records
what it chose under, and that already lived in ``_events.py`` under the same
spelling — a second copy of one record key, which is the bug class this package
keeps finding. Asymmetric like ``zones``, ``types`` and ``destruction``: the
parse side stays in ``effects/tapping.py``, where "tap it" and "it doesn't
untap" are printed in one sentence on Frost Breath, Telekinesis and Mind Whip
and read by productions that share a subject reader.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction, TAPPED_THIS_WAY_OBJECTS
from .. import ast
from ..errors import LoweringError
from ._common import (
    _describe_targets, _is_source, _names_several_targets,
    _restrictions_beyond, testable_filter_payload
)
from ._events import (_RECORDED_PERMANENTS, _TAPPED_PERMANENTS,
                      binds_block_pair)


def _lower_untap_restriction(
    node: "ast.DoesntUntapNextStep | ast.DoesntUntapWhileCounter",
    produced: frozenset[str],
    event: str | None = None,
    event_subject: object | None = None,
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
    return _lower_doesnt_untap_next_step(node, produced, event, event_subject)


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
    node: ast.DoesntUntapNextStep,
    produced: frozenset[str],
    event: str | None = None,
    event_subject: object | None = None,
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
    # "**This creature** … doesn't untap during your next untap step." (Deep
    # Spawn, Homarid Warrior.) The sentence names the ability's own permanent,
    # which is neither a back-reference nor a choice — so there is no producer
    # to require and nothing to describe for a picker, and the handler reads
    # ``context.source_permanent``.
    # Not the bare pronoun, which also carries ``is_source`` and means the
    # opposite thing — "it" names what the sentence in front of it tapped, and
    # reading the two as one would point the marker at the ability's own
    # permanent (the very confusion ``bare_pronoun`` above is written to avoid).
    own_source = _is_source(subject) and not bare_pronoun
    # "**Each attacking creature** … doesn't untap during its controller's next
    # untap step." (Spore Cloud.) A *sweep*: nothing was chosen and nothing was
    # recorded, so the set is whatever the board holds when the spell resolves.
    # Its own branch beside the target and the back-reference, told apart by the
    # printed quantifier exactly as those two are — and it carries no ``targets``
    # description, because a sweep announces nothing (CR 601.2c).
    swept = (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier in ("all", "each")
        and not subject.targeted
    )
    # "Whenever this creature blocks a creature, **that creature** doesn't
    # untap during its controller's next untap step." (Labyrinth Minotaur.) A
    # fifth referent, and the one no sentence in the line names: the creature
    # is the *trigger's* — CR 509.1a's other side of the block — so it is
    # neither chosen here nor recorded by an earlier step, and the printed
    # "that" is what tells it from the bound plural above.
    #
    # ``binds_block_pair`` rather than the kind alone, for the reason that
    # function exists: CR 509.3c/509.3d make a bare "becomes blocked" firing
    # name several creatures and a narrowed one name exactly the creature that
    # admitted it, and the two spellings share a kind. A bare firing here would
    # hold down whichever blocker happened to be first.
    bound_pair = (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "that"
        and not subject.targeted
        and binds_block_pair(event, event_subject)
    )
    # "Whenever a player taps a snow land for mana, … **That land** doesn't
    # untap during its controller's next untap step." (Winter's Night.) A
    # sixth referent, and the block pair's twin one event over: the land is the
    # *trigger's* — the one whose tapping announced it — so it is neither
    # chosen here nor recorded by an earlier step, and the printed "that" is
    # again what tells it from the bound plural.
    #
    # The event is required rather than defaulted, exactly as the mana clause
    # beside it in the same sentence requires it: under any other condition
    # there is no tapped land for the marker to land on, and guessing one would
    # hold down whichever permanent the resolution happened to be holding.
    bound_tapped_land = (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "that"
        and not subject.targeted
        and event == "land_tapped_for_mana"
    )
    if not bare_pronoun and not chosen and not own_source and not swept and (
        not bound_pair
    ) and not bound_tapped_land and (
        not isinstance(subject, ast.TargetSpec) or subject.quantifier != "those"
    ):
        raise LoweringError(
            "this sentence acts on the objects the previous one chose, and its "
            "subject does not name them",
            node=node,
        )
    if swept:
        # The handler asks ``subject_matches`` with the resolving seat as
        # observer, so a key outside what that answers would be carried and
        # ignored — the marker landing on permanents the printed phrase
        # excludes, which for a sweep is every permanent on the table.
        described = testable_filter_payload(
            subject.filter,
            refusal="the untap marker cannot test this restriction",
            node=node,
            require_narrowing=False,
        )
        return (
            OracleInstruction(
                "skip_next_untap", "",
                {**described, "sweep": True, "untap_steps": node.count},
            ),
        )
    if node.count < 1:
        raise LoweringError("a skipped-untap count of none is no restriction", node=node)
    # CR 701.43a's "your", carried as a seat the handler freezes. Absent for the
    # per-creature spelling, which leaves every payload written before this word
    # existed byte-identical — and the untap step reads an unseated marker as
    # "the controller's next untap step", which is what that spelling means.
    seated = {"whose_untap_step": "controller"} if node.whose == "you" else {}
    if own_source:
        if _restrictions_beyond(
            subject.filter, frozenset({"card_types", "is_source"})
        ):
            raise LoweringError(
                "the source names itself and carries no narrowing", node=node
            )
        return (
            OracleInstruction(
                "skip_next_untap", "",
                {"subject": "source", "untap_steps": node.count, **seated},
            ),
        )
    if chosen:
        # The handler tests the noun phrase with ``subject_matches``, so a key
        # outside what that answers would be carried and ignored — the marker
        # landing on permanents the printed phrase excludes.
        described = testable_filter_payload(
            subject.filter,
            refusal="the untap marker cannot test this restriction",
            node=node,
            require_narrowing=False,
        )
        payload: dict[str, object] = {
            **described, "untap_steps": node.count, **seated,
        }
        _describe_targets(payload, subject)
        return (OracleInstruction("skip_next_untap", "", payload),)
    if bound_tapped_land:
        # The trigger already required the noun ("taps a **snow land**"), so
        # the phrase restates what was bound rather than narrowing it — and a
        # narrowing beyond the card type would be carried and never read, which
        # is this family's standing refusal. The land itself comes from the
        # tap-for-mana seam, which is the only code that knows which one it was.
        if _restrictions_beyond(subject.filter, frozenset({"card_types"})):
            raise LoweringError(
                "the land a tap-for-mana trigger bound carries no narrowing "
                "the marker could honour", node=node,
            )
        return (
            OracleInstruction(
                "skip_next_untap", "",
                {"subject": "tapped_land", "untap_steps": node.count, **seated},
            ),
        )
    if bound_pair:
        # The trigger already required the noun, so the phrase restates what
        # was bound rather than choosing again — but a narrowing beyond the
        # card type would be carried and never read, which is this family's
        # standing refusal. The handler reads the pair through
        # ``block_pair_permanents``, the one reader of both fire sites.
        if _restrictions_beyond(subject.filter, frozenset({"card_types"})):
            raise LoweringError(
                "the creature a block trigger bound carries no narrowing the "
                "marker could honour", node=node,
            )
        return (
            OracleInstruction(
                "skip_next_untap", "",
                {"subject": "block_pair", "untap_steps": node.count, **seated},
            ),
        )
    if not bare_pronoun and _restrictions_beyond(subject.filter, frozenset({"card_types"})):
        raise LoweringError(
            "a bound plural carries no narrowing the marker could honour", node=node
        )
    # Which record the bound plural reads, in printed-order preference. Two
    # steps can tap: a target ("Tap target creature. **It** doesn't untap…",
    # Frost Breath, Telekinesis) and a sweep ("tap all creatures that blocked
    # this creature this turn. **They** don't untap…", Joven's Ferrets). One
    # ordered pair rather than a widened `_RECORDED_PERMANENTS` lookup, because
    # this sentence only ever names what a *tap* recorded — a counter placement
    # or a reanimation in the same effect would be a different set, and the
    # sibling `DoesntUntapWhileCounter` is the node written for those.
    recorded = next(
        (
            key for key in (_TAPPED_PERMANENTS, TAPPED_THIS_WAY_OBJECTS)
            if key in produced
        ),
        None,
    )
    if recorded is None:
        # "Whenever this creature attacks, … **it** doesn't untap during your
        # next untap step." (Spectral Bears.) Idiom 20: a pronoun names the
        # object the sentence already named, and under a trigger that object is
        # whatever the condition was about. The parse side has already pointed
        # the word at it where the condition named something *other* than the
        # source (``rebinding.rebind_pronoun_to_event_subject`` swaps the
        # pronoun's filter and this branch never sees it), so a bare pronoun
        # that survives into a trigger's effect names the source and nothing
        # else — there is nothing left for the word to mean.
        #
        # Only under a trigger. With no event the sentence is a spell's or an
        # activated ability's, where "it" is Frost Breath's back-reference to
        # what the sentence in front of it tapped and a missing producer is a
        # marker that would land on nothing.
        if bare_pronoun and event is not None:
            return (
                OracleInstruction(
                    "skip_next_untap", "",
                    {"subject": "source", "untap_steps": node.count, **seated},
                ),
            )
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
            {
                "permanents_from": recorded,
                "untap_steps": node.count,
                **seated,
            },
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
    # "**For as long as this creature remains tapped, target tapped creature**
    # doesn't untap during its controller's untap step." (Giant Oyster.) The
    # other printed word order, and the other subject with it: where Phyrexian
    # Gremlins restates a permanent the sentence before it tapped, this sentence
    # does the choosing itself (CR 602.2b). Same instruction — the handler has
    # always read ``context.target_permanent_id`` — plus a target description,
    # so the picker offers the phrase the card prints instead of nothing.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "target"
        and subject.targeted
    ):
        if subject.count != 1 or _names_several_targets(subject):
            # One permanent per lock: the source records a single id, so a
            # counted phrase would hold down whichever one the resolver
            # returned first.
            raise LoweringError(
                "the linked untap restriction holds one permanent", node=node
            )
        # The handler tests the noun phrase with ``subject_matches``, so a key
        # outside what that answers would be carried and ignored — the lock
        # landing on a permanent the printed phrase excludes. The same refusal
        # the chosen ``skip_next_untap`` above makes, for the same reason.
        described = testable_filter_payload(
            subject.filter,
            refusal="the linked untap restriction cannot test this narrowing",
            node=node,
            require_narrowing=False,
        )
        payload: dict[str, object] = dict(described)
        _describe_targets(payload, subject)
        if "targets" not in payload:
            raise LoweringError(
                "this untap restriction names no target it can hold", node=node
            )
        return (
            OracleInstruction("restrict_untap_while_source_tapped", "", payload),
        )
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
    #
    # "**That creature** doesn't untap…" (Whip Vine) is the third spelling of
    # that one back-reference: the demonstrative with its noun written out. The
    # noun is a *restatement* of the choice the sentence before it already made
    # — the tap named a creature — so it narrows nothing, which is why the card
    # type is the one honoured field and every other one still refuses. Read as
    # a narrowing it refused a card whose whole ability the handler already
    # implements; read as a wildcard it would let "that artifact" hold down a
    # creature.
    if isinstance(subject, ast.TargetSpec) and subject.quantifier == "that":
        if _restrictions_beyond(subject.filter, frozenset({"card_types"})):
            raise LoweringError(
                "a bound object carries no narrowing this lock could honour",
                node=node,
            )
        return (OracleInstruction("restrict_untap_while_source_tapped", "", {}),)
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
