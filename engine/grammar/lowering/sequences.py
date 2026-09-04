"""Lowering the ``sequence`` composer: what a step records, and whose branch it is.

Split out of ``lowering/control_flow`` at the thousand-line guard, along the
line that module's own docstring already draws — it names three composers
(``sequence``, ``may``, ``one_of``) and ``for_each`` had already left as
``lowering/loops``. What stays there is the two *offers*; what moves here is the
sequence: threading each step's records forward, and folding a step that reads
an offer's record into the branch that writes it.

The half that grows with the pool, which is why it is the half that moved
(SET_PLAYBOOK's rule for a cut where both halves are dispatch): every round that
teaches a sentence to read what the sentence in front of it did lands here.

``lower_statement`` arrives as a **parameter**, for the reason it does one
module over: a step is a whole sentence, reading one is ``lower.py``'s job, and
the caller hands its own parser down rather than being imported back.

**A fuser lives with the sequence it folds, not with the verb it folds.**
``_fused_cost_repeated_destroys`` came here at Mirage's second-wave integration,
when ``destruction`` crossed the size guard with no branch at fault, and it is
the same move ``_fused_tap_enchanted_then_counters`` made out of ``counters`` on
one of those branches. What it reads is a *shape* — an offer step and the steps
that repeat under it — and the destroy inside is one leaf of that shape. Its one
piece of destroy-specific data travelled with it, because nothing else read it:
that is what made this a move rather than a cut.
"""

from __future__ import annotations

from ...oracle_types import (COST_TARGET_BASE, COST_TARGET_PER,
                             OracleInstruction)
from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS
from .. import ast
from ..errors import LoweringError
from ..phrases import is_pt_counter
from ._common import (_describe_several_targets, _filter_payload,
                      _is_enchanted, _is_target, _names_several_targets,
                      _restrictions_beyond)
from ._records import optional_cost_key, primary_produced, produced_keys

#: The branches of a ``may`` whose records are visible to the steps *after* it.
#: The offer's action and its "if you do" consequence are steps of this same
#: resolution, so a later sentence naming what they recorded ("**those cards**"
#: after "you may draw two additional cards. If you do, choose two cards…") is
#: naming something this effect really does write.
#:
#: ``reflexive`` is deliberately absent, for the reason ``_lower_may`` gives
#: about threading *into* it: it is a separate ability under CR 603.12 with a
#: scratchpad of its own. ``otherwise`` is absent from *this* tuple and has one
#: of its own below, because its records are visible on a different condition.
_MAY_BRANCHES_VISIBLE_AFTER = ("action", "then")

#: The branch whose records are visible only to a step that runs *because the
#: offer was declined*. "Target opponent may ante the top card of their library.
#: **If they don't, you flip a coin.** If you win the flip, that player loses
#: the game." (Amulet of Quoz.) The flip is written by the decline branch, so
#: the sentences reading it are steps of that branch however they were
#: punctuated -- the mirror of the fold below, one branch over, and the reason
#: it is a tuple of its own rather than a third entry above: a step is folded
#: into whichever branch actually writes what it reads, and the two branches
#: never both run.
_MAY_DECLINE_BRANCH = ("otherwise",)


def _records_produced(
    instruction: OracleInstruction,
    branches: tuple[str, ...] = _MAY_BRANCHES_VISIBLE_AFTER,
) -> frozenset[str]:
    """The scratchpad keys *instruction* may write, its own and its offer's.

    An offer records nothing itself, so a step after "you may … If you do,
    choose two cards in your hand" would otherwise see an empty set and refuse
    the back-reference that follows it. What is threaded is only the
    *possibility*: a declined offer writes nothing and the loop after it runs
    over nothing, which is what the card says happens.

    Read through ``_PRODUCES`` at every level rather than a second table, so an
    instruction's record has one declaration however deeply it is nested.

    *branches* is which of an offer's branches to look inside. The caller asks
    twice, once per fold target, because the answer decides which branch a later
    step belongs in.
    """
    keys = set(produced_keys(instruction))
    if instruction.kind == "may":
        for branch in branches:
            for nested in instruction.payload.get(branch) or ():
                keys |= _records_produced(nested, branches)
    if instruction.kind == "choose_one":
        # "**Destroy all green creatures or all white creatures.** They can't
        # be regenerated. You lose 2 life for each creature that died this
        # way." (Reign of Terror.) The choice records nothing itself, so the
        # sentence behind it saw an empty set and refused a back-reference the
        # mode in front of it certainly writes.
        #
        # A union across the modes, exactly as the offer above is: what is
        # threaded is the *possibility* that the record exists. A mode that
        # writes nothing leaves the key absent at resolution, and every reader
        # in this engine already answers an absent record with the number the
        # card means — the sweep destroyed nothing, so nothing is counted.
        for mode in instruction.payload.get("modes") or ():
            nested = mode.get("instruction") if isinstance(mode, dict) else None
            if nested is not None:
                keys |= _records_produced(nested, branches)
    return frozenset(keys)


def _references_record(instruction: OracleInstruction, keys: frozenset[str]) -> bool:
    """Whether *instruction*, or anything nested in it, reads one of *keys*.

    A back-reference is a payload entry naming the scratchpad key it reads —
    ``{"produced_by": …}`` for a loop's set, ``{"key": …}`` for an "if you do".
    Both are matched by *value*, not by which key spells them, because what
    matters is that the name of a record turns up somewhere in the payload at
    all; a lowering that names one under a third spelling would be folded here
    too rather than silently missed.
    """

    def walk(value) -> bool:
        if isinstance(value, OracleInstruction):
            return walk(value.payload)
        if isinstance(value, dict):
            return any(
                (isinstance(v, str) and v in keys) or walk(v) for v in value.values()
            )
        if isinstance(value, (tuple, list)):
            return any(walk(item) for item in value)
        return False

    return walk(instruction.payload)


def _fold_into_offer(
    instructions: tuple[OracleInstruction, ...],
    offer_index: int,
    folded: tuple[OracleInstruction, ...],
    branch: str = "then",
) -> tuple[OracleInstruction, ...]:
    """*instructions* with *folded* appended to one of the offer's branches.

    "You may draw two additional cards. If you do, choose two cards in your
    hand drawn this turn. **For each of those cards, …**" (Sylvan Library.) The
    third sentence reads what the second one recorded, and the second one only
    happens if the offer is taken — so it is a step of the offer's consequence
    however it was punctuated. Left as a sibling step it runs *before* the
    offer is answered: an offer to an interactive seat arms a prompt and
    returns, so the sequence would carry on to the loop with nothing chosen and
    then report itself resolved.

    Folding is what keeps the order right without making every optional cost in
    the game suspend the resolution it is part of. The alternative — a
    ``suspends`` flag on the offer's prompt — stops loops that have no such
    dependency at all, which is a change to every "you may" in the pool made on
    the strength of one card.
    """
    offer = instructions[offer_index]
    # *branch* is "then" for a step reading what the offer's action recorded and
    # "otherwise" for one reading what its decline recorded (Amulet of Quoz's
    # coin flip). The same argument either way: the step runs exactly when the
    # branch that writes what it reads runs.
    kept = tuple(offer.payload.get(branch) or ()) + folded
    rebuilt = OracleInstruction(offer.kind, offer.value, {**offer.payload, branch: kept})
    return instructions[:offer_index] + (rebuilt,) + instructions[offer_index + 1:]


def _lower_steps(
    steps: tuple[ast.Statement, ...],
    produced: frozenset[str],
    event: str | None = None,
    event_subject: object | None = None,
    *,
    lower_statement,
) -> tuple[OracleInstruction, ...]:
    """Lower consecutive steps, threading what each one records forward."""
    instructions: tuple[OracleInstruction, ...] = ()
    last_produced: str | None = None
    # The most recent offer whose branches record something, and what they
    # record. A later step reading one of those names is a step of that offer's
    # consequence, whatever the punctuation says.
    offer_index: int | None = None
    offer_keys: frozenset[str] | None = None
    # The same, for the offer's *decline* branch. Tracked apart from the pair
    # above because a step is folded into the branch that writes what it reads.
    decline_keys: frozenset[str] | None = None
    # The step this one follows, for the one rider below that has to know what
    # the sentence in front of it *was* rather than only what it recorded.
    previous: ast.Statement | None = None
    for step in steps:
        # "Destroy target creature. **If a white creature dies this way,**
        # <effect>." (Cinder Cloud; Kaervek's Purge prints "if that creature
        # dies this way".) The condition names the destroy family's own record,
        # so it is the *same set* "for each creature that died this way"
        # iterates — and lowering it to that loop is what gives the arm its
        # per-object reads ("the creature's power", "that creature's
        # controller"), which no `if_then` branch can supply.
        #
        # An "if" is not a "for each" in general: over a sweep the loop would
        # repeat what the card does once. So it is admitted only after a
        # **single-target** destroy, where the record can hold at most one
        # object and the two readings coincide exactly. A sweep printing this
        # sentence refuses, naming the reason.
        if isinstance(step, ast.Conditional) and isinstance(
            step.condition, ast.DiedThisWay
        ):
            if step.otherwise is not None:
                raise LoweringError(
                    "'dies this way' has no reading for an else branch",
                    node=step,
                )
            if not (
                isinstance(previous, ast.Destroy)
                and isinstance(previous.subject, ast.TargetSpec)
                and previous.subject.quantifier == "target"
                and not previous.also_targets
            ):
                raise LoweringError(
                    "'if <noun> dies this way' reads the one permanent the "
                    "sentence in front of it destroyed, and that sentence "
                    "destroys none or several",
                    node=step,
                )
            # Lowered through the ordinary dispatcher rather than by calling
            # the destroy family's loop lowering directly: `control_flow` and
            # `destruction` are two families and families do not import each
            # other. `lower_statement` is already this function's parameter, and
            # it is what makes the two spellings reach *one* lowering — which is
            # the whole point of rewriting the node instead of building the
            # instruction here.
            instructions += lower_statement(
                ast.ForEach(step.condition, step.then), produced,
                event=event, event_subject=event_subject, whole_effect=False,
            )
            previous = step
            last_produced = None
            continue
        # "…**If you do**, …" after an action that was not optional. The branch
        # asks whether the step before it took place, and this is the one place
        # that knows which step that was *and* what it records — so the pairing
        # is made here rather than in a field on the node, where it would be a
        # second copy of ``_PRODUCES`` free to disagree with the first.
        if isinstance(step, ast.Conditional) and isinstance(
            step.condition, (ast.ItHappened, ast.CouldNot)
        ):
            could_not = isinstance(step.condition, ast.CouldNot)
            if last_produced is None:
                raise LoweringError(
                    ("\"if you can't\"" if could_not else '"if you do"')
                    + " after a step that records nothing has no "
                    "condition to test",
                    node=step,
                )
            branch = lower_statement(
                step.then, produced, event=event, event_subject=event_subject, whole_effect=False
            )
            # "**If the player does**, <A>. **If they don't**, <B>."
            # (Takklemaggot.) One record, read twice — the second rider folded
            # itself onto the first's node rather than becoming a step, because
            # by then ``last_produced`` names the choice and nothing else could
            # say what "don't" is the complement of.
            otherwise = lower_statement(
                step.otherwise, produced, event=event,
                event_subject=event_subject, whole_effect=False,
            ) if step.otherwise is not None else ()
            condition: dict[str, object] = {
                "kind": "it_happened", "key": last_produced,
            }
            # "If you **can't**" runs the branch exactly when the record says
            # the step did not happen — one condition kind, negated, so the
            # two riders cannot drift apart in what they read.
            if could_not:
                condition["negated"] = True
            payload: dict[str, object] = {"condition": condition, "then": branch}
            if otherwise:
                payload["else"] = otherwise
            instructions += (OracleInstruction("if_then", "", payload),)
            # Deliberately *not* cleared: a second rider on the same step is the
            # printed pair above, and clearing the record here is what used to
            # make "If they don't" a branch with no condition to test.
            continue
        lowered = lower_statement(step, produced, event=event, event_subject=event_subject, whole_effect=False)
        # A step reading a record only an earlier offer's branch writes belongs
        # *inside* that offer — see ``_fold_into_offer``.
        if offer_index is not None and offer_keys and all(
            _references_record(instruction, offer_keys) for instruction in lowered
        ):
            instructions = _fold_into_offer(instructions, offer_index, lowered)
            last_produced = None
            continue
        # "...If they don't, you flip a coin. If you win the flip, ..." (Amulet
        # of Quoz.) A step reading only what the *decline* branch records
        # belongs inside it, for the reason above exactly: left as a sibling it
        # runs whether or not the offer was taken, and reads a coin flip that
        # never happened.
        if offer_index is not None and decline_keys and all(
            _references_record(instruction, decline_keys) for instruction in lowered
        ):
            instructions = _fold_into_offer(
                instructions, offer_index, lowered, branch="otherwise"
            )
            last_produced = None
            continue
        last_produced = None
        offer_index = offer_keys = decline_keys = None
        for position, instruction in enumerate(lowered):
            # Two different questions, and they take different answers. What is
            # *available* to a back-reference includes what an offer's branches
            # write; what "if you do" tests is this step's own record, because
            # the rider asks whether **this** step happened.
            inner = _records_produced(instruction)
            produced = produced | inner
            result = primary_produced(instruction.kind)
            if result is not None:
                last_produced = result
            declined = _records_produced(instruction, _MAY_DECLINE_BRANCH)
            # The decline branch's records are threaded forward too. What makes
            # that safe is the fold above, which puts a step reading one of them
            # *inside* the branch that writes it.
            produced = produced | declined
            if instruction.kind == "may" and (inner or declined):
                offer_index = len(instructions) + position
                offer_keys = inner
                decline_keys = declined - inner
        instructions += lowered
        previous = step
    return instructions

# A **fusion** of two consecutive steps, which is this module's own subject
# rather than the counter family's: `_lower_steps` above threads what each step
# records forward and folds a step into the branch that wrote what it reads, and
# this is the same question asked about a *pronoun* — "it" after a tap of the
# enchanted creature names that creature and not the Aura. It left
# `lowering/counters.py` when that module crossed the thousand-line guard again,
# and the boundary is the one this function's own docstring already drew: it
# cites `_lower_steps`' discipline, and the antecedent of a pronoun is a fact
# about the sequence, not about what the second step happens to place.


def _fused_tap_enchanted_then_counters(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"Tap enchanted creature and put X sleep counters on it." (Venarian Gold.)

    Fused because of the pronoun. The noun parser reads a bare "it" as the
    ability's own source, which in this sentence is the *Aura* — so lowered
    step by step the counters would land on the Aura while the card puts them
    on the creature it tapped. The antecedent is the step in front of it, and
    this is the one place that knows what that step was (the same discipline
    ``_lower_steps`` states for "if you do"), so the pairing is made here:
    after a tap of the enchanted creature, "it" is that creature.

    Only the pronoun spelling is claimed. "…put three pupa counters on **this
    Aura**" (Cocoon) names the source outright and lowers step by step to the
    self placement, exactly as printed. Anything the attached placement cannot
    honour — an "up to", a doubling rider, a cap, a count that is not a number
    or X — returns to the generic path, whose refusals name what is missing.
    """
    if len(steps) != 2:
        return None
    tap, put = steps
    if not isinstance(tap, ast.Tap) or not _is_enchanted(tap.subject):
        return None
    if not isinstance(put, ast.PutCounter):
        return None
    subject = put.subject
    if not (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "it"
        and subject.filter.is_source
    ):
        return None
    if is_pt_counter(put.counter) or put.up_to or put.then_double or put.cap is not None:
        return None
    if isinstance(put.count, ast.Fixed):
        count: object = put.count.value
    elif isinstance(put.count, ast.Var):
        count = "x"
    else:
        return None
    return (
        OracleInstruction("tap_enchanted_creature", "", {}),
        OracleInstruction(
            "add_named_counter_to_attached", "",
            {"counter": put.counter, "count": count},
        ),
    )


#: The filter keys ``destroy_target_permanent``'s several-target branch tests in
#: full, and therefore the only ones a fused announcement may narrow by. The
#: same set the ``_names_several_targets`` branch of :func:`_lower_destroy`
#: states inline, named once because two readings of "what may a list of destroy
#: targets be narrowed by" is one reading too many -- and the direction the
#: second one drifts is a narrowing dropped from a sweep, which destroys
#: permanents the card does not name.
_SEVERAL_DESTROY_NARROWINGS = frozenset({
    "card_types", "supertypes", "subtypes", "colors", "controller",
    "other_than_source",
})


def _repeated_destroy_clause(
    step: ast.Statement,
) -> tuple[str, ast.Destroy, tuple[ast.Statement, ...]] | None:
    """Split "**for each additional {1}{R} you paid,** destroy another target
    artifact[, and <rider>]" into (offer, the destroy, the riders).

    None for any other step, which is how the fuser below declines a sentence it
    does not recognise instead of half-reading one.
    """
    if not isinstance(step, ast.ForEach):
        return None
    if not isinstance(step.iterator, ast.EachAdditionalCostPaid):
        return None
    body = step.effect
    riders: tuple[ast.Statement, ...] = ()
    if isinstance(body, ast.Sequence):
        if not body.steps:
            return None
        body, riders = body.steps[0], body.steps[1:]
    if not isinstance(body, ast.Destroy):
        return None
    return step.iterator.symbols, body, riders


def _fused_cost_repeated_destroys(
    steps: tuple[ast.Statement, ...],
    lower_statement,
) -> tuple[OracleInstruction, ...] | None:
    """"Destroy target artifact. **For each additional {1}{R} you paid, destroy
    another target artifact. For each additional {1}{G} you paid, destroy
    another target artifact, and you gain 1 life.**" (Primitive Justice.)

    One announcement, not three. CR 601.2b announces the optional additional
    costs and CR 601.2c then fixes the number of targets -- so by the time the
    caster is asked what to destroy, the spell wants exactly
    ``1 + n({1}{R}) + n({1}{G})`` artifacts, and the printed "**another**" makes
    them distinct (CR 601.2c: "the same target can't be chosen multiple times
    for any one instance of the word 'target'"). That is a *list*, which
    ``destroy_target_permanent`` has resolved since Avalanche; what is new here
    is only where its length comes from.

    Fusing rather than a slot per clause, for :func:`_fused_two_target_pump`'s
    reason one family over: three targeted destroys lowered as three steps all
    resolve through ``_one_choice``, which reads the *first* entry of the target
    list -- so the card would compile supported and destroy one artifact three
    times. ``_refuse_unfused_distinctness`` refuses exactly that, and says in
    its own docstring that a shape which grows a fused lowering is claimed above
    it and never reaches it. This is that shape.

    **The riders keep their loop and move behind the destroy.** "…, and you gain
    1 life" happens once per {1}{G} paid, so it stays inside a ``for_each`` over
    that offer; what it loses is its position *between* the destroys. Nothing
    can observe the difference: no player receives priority inside a resolution
    (CR 117.3b) and state-based actions are not checked until it ends
    (CR 704.3), so the only ordering a spell's own steps can expose is one step
    reading what an earlier one did -- and a life gain reads no artifact.

    **Destroy only**, though the shape is the verb's to share: this is a several
    -target announcement, and only a handler that resolves a *list* may be given
    one (``_describe_several_targets`` states the rule and
    ``_names_several_targets`` enforces it everywhere else). A second verb is one
    branch here the day its handler reads a list; admitting one now would fuse
    three targets onto a handler that reads the first.

    Refuses rather than declines where the sentence is *nearly* this shape,
    because a decline falls through to the unfused refusal and the card is then
    reported unsupported for the wrong reason:

    * a first clause printing "another" has no prior choice to differ from;
    * a repeated clause that does **not** print it names a target CR 601.2c
      would let collide with the first, which is the silent double destroy;
    * clauses whose noun phrases differ are two announcements rather than one
      list -- one filter cannot describe both, and the picker would offer
      whichever noun the fuse happened to keep.
    """
    if len(steps) < 2:
        return None
    first, rest = steps[0], steps[1:]
    if not isinstance(first, ast.Destroy) or first.delay or first.also_targets:
        return None
    if not _is_target(first.subject):
        return None
    repeats = [_repeated_destroy_clause(step) for step in rest]
    if any(found is None for found in repeats):
        return None
    assert isinstance(first.subject, ast.TargetSpec)
    if first.subject.distinct_from_prior:
        raise LoweringError(
            'the first clause of a sentence cannot name "another" target',
            node=first,
        )
    per_offer: dict[str, int] = {}
    riders: list[OracleInstruction] = []
    for offer, destroy, tail in repeats:
        if destroy.delay or destroy.also_targets or not _is_target(destroy.subject):
            return None
        assert isinstance(destroy.subject, ast.TargetSpec)
        if not destroy.subject.distinct_from_prior:
            raise LoweringError(
                "a destroy repeated per additional payment names a *new* target "
                'only when it prints "another"', node=destroy,
            )
        if (
            destroy.subject.filter != first.subject.filter
            or destroy.no_regen != first.no_regen
        ):
            raise LoweringError(
                "the clauses of one target announcement must name one noun "
                "phrase", node=destroy,
            )
        key = optional_cost_key(offer)
        if key in per_offer:
            # Two clauses reading back one offer would each add to the count
            # while the picker showed one number. ``cast_costs`` refuses the
            # same collision on the announcing side, for the same reason: one
            # key, one count, and no way to say which clause spent it.
            raise LoweringError(
                "one additional cost cannot size two target clauses",
                node=destroy,
            )
        per_offer[key] = 1
        if tail:
            riders.append(
                OracleInstruction(
                    "for_each", "",
                    {
                        "iterator": {"repeat_from_cost": key},
                        "effect": lower_statement(
                            ast.Sequence(tail) if len(tail) > 1 else tail[0],
                            frozenset(), whole_effect=False,
                        ),
                    },
                )
            )
    filt = first.subject.filter
    leftovers = _restrictions_beyond(filt, _SEVERAL_DESTROY_NARROWINGS)
    if leftovers:
        raise LoweringError(
            "the several-target destroy cannot narrow by: " + ", ".join(leftovers),
            node=first,
        )
    described = _filter_payload(filt)
    if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
        raise LoweringError(
            "the several-target destroy cannot test this restriction", node=first
        )
    payload: dict[str, object] = dict(described)
    if first.no_regen:
        payload["bypass_regeneration"] = True
    payload["targets"] = {
        "quantifier": first.subject.quantifier,
        "kind": "object",
        "filter": _filter_payload(filt),
        # The size of the announcement as the *arithmetic*, not as a number:
        # what the caster paid is unknown until they announce it, and the
        # picker, the cast gate and the AI all resolve it through one reader
        # (``oracle_types.cost_target_count``).
        "count": {COST_TARGET_BASE: 1, COST_TARGET_PER: per_offer},
        # The printed "another" (CR 601.2c), carried rather than folded into the
        # filter for ``_fused_two_target_pump``'s reason: it is a relation
        # between slots, not a property of one permanent, so
        # ``permanent_matches_filter`` could never test it.
        "distinct": True,
    }
    return (OracleInstruction("destroy_target_permanent", "", payload), *riders)
