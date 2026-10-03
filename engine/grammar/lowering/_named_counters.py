"""Placing a counter that has **no rules meaning of its own** (CR 122.1).

The branches of ``counters.py`` that open on ``not is_pt_counter``, cut where
that file's own gates already cut them — the move ``_plus_one_counters`` made
along ``if node.counter != "+1/+1"``, one gate further up. A CR 122.1a counter
carries its power and toughness in its *name* and is written through
``Game.place_pt_counters``; a wind, soul, charge or fade counter carries
nothing, sits in ``engine/named_counters.py``'s open store, and means whatever
the card's other lines say about it. Two stores and two writes, which is what
the block-pair branch that stayed behind says of its twin here: "CR 122.1a
makes the two placements two different writes".

So the line is the one ``counter_removal`` and ``_counter_stores`` each left
the same file along — *what the payload asks for* — read a third time. Every
instruction built here is ``add_named_counter_to_self`` or
``add_named_counter_to_target``, and nothing else in the package builds
either; every instruction ``counters.py`` still builds is one a P/T pair can
ride. The call graph agrees as far as it can: ``_EVENT_SUBJECT_OBJECTS``,
``_REANIMATED_PERMANENTS``, ``trigger_quantity_key`` and the ordered target
*roles* were read by these branches and by no other.

What did **not** come is the placement on "each creature blocking or blocked by
this creature" (Dread Wight), although its kind has the word in it: its gate
used to read ``not is_pt_counter`` and no longer does, so it dispatches on the
subject and carries either kind of counter as payload — which is ``counters``'
question rather than this one's.

**Two entry points rather than one**, for ``_bound_exiles``' reason exactly.
``_lower_put_counter`` reads four of these ahead of every P/T branch and the
fifth — the other half of a block — after "the other" of a chosen pair, the
combat set and the delayed binding, none of which asks what kind the counter
is. One function would have moved that branch across all three, which is a
behaviour change dressed as a split; so each entry is called from the place its
branches have always been read, and each returns None where the sentence is not
its own.

**A floor, not a family**, for ``_counter_stores``' reason: ``counters`` reads
it from inside ``_lower_put_counter`` and it reads nothing back, and inside a
package a module a family imports cannot itself be one. It takes the name of
the store it writes to, ``engine/named_counters.py``, rather than inventing a
second word for the same counters.

**No parse-side mirror, deliberately**, for ``counter_removal``'s reason:
``effects/counters.py`` reads every one of these placements with the production
it already has.

Split out at the Phase 0 before Nemesis, with ``counters.py`` 22 lines under
the thousand-line guard and the set's headline mechanic due to land in it from
several groups at once: fading's counter and Mana Cache's charge counter are
both of this kind, so this is the half that grows.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction, X_FROM_COUNT
from ...subject_filters import object_only_filter
from .. import ast
from ..errors import LoweringError
from ..phrases import is_pt_counter
from ._amounts import count_filter_on_frozen_seat, count_spec
from ._common import (
    PRIMARY_TARGET_ROLE, _amount_payload, _describe_targets, _filter_payload,
    _is_source, _is_target, _names_several_targets, describe_target_roles,
    refuse_untestable,
)
from ._events import (
    _EVENT_SUBJECT_OBJECTS, _REANIMATED_PERMANENTS, binds_block_pair,
    trigger_quantity_key,
)


def lower_named_placement(
    node: ast.PutCounter,
    event: str | None,
    produced: frozenset[str],
    trigger_event: str | None,
) -> tuple[OracleInstruction, ...] | None:
    """A named counter on the one object the sentence names, or None.

    Four readings, in the printed-specificity order ``_lower_put_counter`` has
    always read them in: the object the firing event was about, the permanent an
    earlier step returned, the ability's own source, and a target the ability
    chose. None where the sentence is none of them — a P/T pair, an "up to", or
    a subject no branch here reads — and the caller carries on down its own
    list from the line it called this on.

    *event* is the trigger kind filtered by ``whole_effect`` and *trigger_event*
    the unfiltered one, exactly as the caller receives them: the first picks a
    dispatch path, the second names the number the firing carried.
    """
    # "Whenever a permanent becomes tapped, put a wind counter on **it**."
    # (Freyalise's Winds.) The pronoun was rebound to the *event's* subject by
    # `rebinding.rebind_pronoun_to_event_subject`, so it is neither the source
    # nor a target — nothing was chosen, and nothing may be: the object is the
    # one the event was about, frozen into the announcement by
    # `become_tapped` (CR 603.10).
    #
    # Gated on the event, exactly as the "that player" recipients one module
    # over are: under any other trigger the same word names an object no fire
    # site recorded, and the handler would put the counter on nothing while the
    # card compiled clean.
    if (
        not is_pt_counter(node.counter)
        and not node.up_to
        and isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "it"
        and not node.subject.filter.is_source
    ):
        if event not in _EVENT_SUBJECT_OBJECTS:
            raise LoweringError(
                "\"it\" names the object the event was about, and this event "
                "records none",
                node=node,
            )
        if not isinstance(node.count, ast.Fixed):
            raise LoweringError(
                "a named counter is placed a fixed number at a time", node=node
            )
        described = _filter_payload(node.subject.filter)
        if object_only_filter(described) is None:
            # The rebound filter re-states what the event's own narrowing
            # already selected, so it is carried and re-checked rather than
            # dropped — a word consumed and never read is a word that could be
            # deleted with no change to what the card does.
            raise LoweringError(
                "the counter's subject carries a restriction the resolution "
                "cannot test", node=node,
            )
        payload: dict[str, object] = {
            "counter": node.counter,
            "count": node.count.value,
            "on_event_subject": True,
        }
        if described:
            payload["filter"] = described
        return (OracleInstruction("add_named_counter_to_target", "", payload),)
    # A **named** counter on the source ("put a soul counter on this Equipment",
    # Malefic Scythe). CR 122.1 counters with no rules meaning of their own:
    # engine/named_counters.py holds them, and what they mean is whatever the
    # card's other lines say about them. Only on the source, because that is the
    # only permanent the placement can name without a picker.
    # "When this creature dies, … **return it to the battlefield** under your
    # control **and put a death counter on it**." (Bogardan Phoenix.) The
    # pronoun names the permanent the step in front of it created, not the
    # ability's own source — the source is the object that died, and CR 400.7
    # makes what came back a different one. Placed on the source it is a counter
    # on a permanent that is not on the battlefield, which reads as placed in
    # the log and is gone the next time anything looks: the Phoenix returns for
    # ever.
    #
    # Gated on ``_REANIMATED_PERMANENTS`` alone rather than on the whole
    # recorded set: only a step that *put the source back* changes what the
    # pronoun means, and "put a soul counter on this Equipment" after a tap
    # still means the Equipment.
    if (
        not is_pt_counter(node.counter)
        and not node.up_to
        and _is_source(node.subject)
        and isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "it"
        and _REANIMATED_PERMANENTS in produced
        and isinstance(node.count, ast.Fixed)
    ):
        payload: dict[str, object] = {
            "counter": node.counter,
            "count": node.count.value,
            "permanents_from": _REANIMATED_PERMANENTS,
        }
        return (OracleInstruction("add_named_counter_to_target", "", payload),)
    if not is_pt_counter(node.counter) and not node.up_to and _is_source(node.subject):
        # "{X}{1}, {T}: Put **X** charge counters on this artifact."
        # (Ventifact Bottle.) The count is the cast's announced X, which is
        # the same value the P/T branch above already spends and which the
        # handler resolves through ``context.x_value`` like every other
        # amount. The refusal below is what a count this branch cannot read
        # at all still gets.
        # "Whenever you're dealt damage, put **that many** vitality counters on
        # this Aura." (Living Artifact.) The number the firing event carried,
        # frozen into the trigger's context by the fire site — the same third
        # channel `_plus_one_counters` reads for Light of Promise, and here for
        # the same reason: the sentence has no earlier step of its own to have
        # recorded anything, so a scratchpad read would place zero while
        # reporting itself resolved. The bare back-reference only; a named
        # source or a printed bonus is a different number.
        event_key = trigger_quantity_key(trigger_event)
        extra: dict[str, object] = {}
        if isinstance(node.count, ast.Fixed):
            placed: int | str = node.count.value
        elif isinstance(node.count, ast.Var):
            placed = node.count.name
        elif (
            event_key is not None
            and isinstance(node.count, ast.ThatMuch)
            and node.count.source is None
            and not node.count.bonus
        ):
            placed = "trigger_count"
            extra["amount_from_trigger"] = event_key
        elif isinstance(node.count, ast.CountOf):
            # "…put a charge counter on this enchantment **for each untapped
            # land that player controls**." (Mana Cache.) A board count taken as
            # the placement resolves (CR 107.3), through the one spec every
            # counted quantity uses: the handler reads "x" and the dispatch
            # point fills it from ``x_from_count``, exactly as a where-clause's
            # X is filled. "That player" is the seat the firing event froze —
            # *trigger_event*, the unfiltered kind, because the count is part
            # of this clause wherever in the sentence it sits.
            placed = "x"
            extra[X_FROM_COUNT] = count_spec(
                count_filter_on_frozen_seat(node.count.filter, trigger_event, node),
                node,
            )
        else:
            raise LoweringError(
                "a named counter is placed a fixed or variable number at a "
                "time", node=node,
            )
        return (
            OracleInstruction(
                "add_named_counter_to_self", "",
                {"counter": node.counter, "count": placed, **extra},
            ),
        )
    # The same CR 122.1 marker on a permanent the ability **chose** ("put a
    # matrix counter on target creature", Life Matrix). The self branch above
    # says it lands only on the source because that is the only permanent a
    # placement can name without a picker — this is the picker, so the noun
    # phrase is payload and the counter's word stays payload too.
    #
    # Gated on `TESTABLE_SUBJECT_FILTER_KEYS` for the reason CLAUDE.md records:
    # a restriction the matcher cannot test is one the resolution would ignore,
    # which offers the player a wider set of targets than the card prints. A
    # phrase with no card type is refused for the same reason the loyalty picker
    # refuses one — it would offer every permanent on the board.
    if (
        not is_pt_counter(node.counter)
        and not node.up_to
        and _is_target(node.subject)
        and not _names_several_targets(node.subject)
    ):
        assert isinstance(node.subject, ast.TargetSpec)
        # "Put X glyph counters on target creature **that target Wall blocked
        # this turn**" (Glyph of Delusion). The noun phrase names a second
        # target of a different kind, so the description is ordered *roles*
        # rather than one filter — and the count may be the sentence's X,
        # because the where-clause behind it reads a characteristic of the
        # role this effect acts on rather than a number the caster announced.
        #
        # Before the fixed-count refusal below and before the testable-key
        # gate, because both are true of a one-target description and neither
        # is the question here: the relation has no filter form at all
        # (``subject_matches`` answers about one permanent; this is a record on
        # the *other* target), so falling through would drop it and offer every
        # creature on the board.
        roles_payload: dict[str, object] = {
            "counter": node.counter,
            "count": _amount_payload(node.count),
            "subject_role": PRIMARY_TARGET_ROLE,
        }
        if describe_target_roles(roles_payload, node.subject):
            for role in roles_payload["targets"]["roles"]:
                refuse_untestable(
                    role["filter"],
                    refusal="a named-counter target role cannot test this "
                            "restriction",
                    node=node,
                )
                if not role["filter"].get("type_filter"):
                    raise LoweringError(
                        "a named-counter target role with no card type would "
                        "offer every permanent", node=node,
                    )
            return (
                OracleInstruction("add_named_counter_to_target", "", roles_payload),
            )
        if not isinstance(node.count, ast.Fixed):
            raise LoweringError(
                "a named counter is placed a fixed number at a time", node=node
            )
        if not node.subject.filter.card_types:
            raise LoweringError(
                "a named-counter target with no card type would offer every "
                "permanent",
                node=node,
            )
        payload: dict[str, object] = {
            "counter": node.counter, "count": node.count.value,
        }
        _describe_targets(payload, node.subject)
        described = (payload.get("targets") or {}).get("filter") or {}
        refuse_untestable(
            described,
            refusal="the named-counter target cannot test this restriction",
            node=node,
        )
        return (OracleInstruction("add_named_counter_to_target", "", payload),)
    return None


def lower_named_block_pair_placement(
    node: ast.PutCounter,
    trigger_event: str | None,
    event_subject: object | None,
) -> tuple[OracleInstruction, ...] | None:
    """A named counter on the other half of a block the trigger froze, or None.

    Its own entry rather than a fifth branch of :func:`lower_named_placement`,
    because ``_lower_put_counter`` reads it *after* three branches that do not
    ask what kind the counter is — "the other" of a chosen pair, the combat set
    and the delayed binding — and immediately ahead of the P/T twin that stayed
    there. Called from that line, so nothing changed places.
    """
    # "…put four **fungus** counters on **that creature**." (Mindbender
    # Spores.) The other half of the block CR 509.3a-d announced, which the
    # trigger froze — the referent `pump_block_pair` already acts on, and never
    # a choice. `binds_block_pair` rather than the kind alone, for that
    # helper's reason: a bare firing has several blockers and no way to say
    # which one the words name. Named counters only — a P/T pair is
    # `place_pt_counters`' question and wants that channel.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
        and not node.up_to
        and not node.then_double
        and not is_pt_counter(node.counter)
        and binds_block_pair(trigger_event, event_subject)
    ):
        if not isinstance(node.count, ast.Fixed) or node.count.value < 1:
            raise LoweringError("a bound placement counts a fixed number", node=node)
        described = _filter_payload(node.subject.filter)
        if object_only_filter(described) is None:
            raise LoweringError(
                "the counter's subject carries a restriction the resolution "
                "cannot test", node=node,
            )
        return (OracleInstruction("add_named_counter_to_target", "", {
            "counter": node.counter, "count": node.count.value,
            "on_block_pair": True, **({"filter": described} if described else {}),
        }),)
    return None
