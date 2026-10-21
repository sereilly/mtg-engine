"""Fusing a sequence: printed steps that cannot be lowered one at a time.

``statement_dispatch``'s ``Sequence`` arm asks every fuser before it lowers a
single step, and the first to answer claims the sentence whole;
``lowering/sequences``' ``_lower_steps`` runs only when every one of them has
declined. That is this module's subject — **a sentence whose steps cannot be
lowered one at a time** — and each fuser says why its pair cannot be two
instructions. Every reason here is one of three things a step-by-step lowering
has no channel for:

* a printed "**another** target" across clauses (CR 601.2c). One announcement
  with a slot per clause, where every one-target handler resolves through
  ``_one_choice`` and reads the *first* slot for both: the two-target pump
  (Rookie Mistake), the keyword move (Phyrexian Splicer), the tap and bite
  (Deadshot), and the destroy repeated once per additional payment (Primitive
  Justice). ``_targets._refuse_unfused_distinctness`` refuses whatever of that
  shape no fuser here claimed, and the dispatcher asks it after all of them on
  purpose;
* a pronoun whose antecedent is the step in front of it rather than the
  ability's source (Venarian Gold's "it");
* a count that crosses the sentence boundary and is known only once the first
  step's choice is answered (Siege Striker's "for each creature tapped this
  way").

Split out of ``lowering/sequences`` at Torment's Phase 0, at 981 of the
thousand-line guard with no group owning it. That module's docstring said
"**a fuser lives with the sequence it folds, not with the verb it folds**",
and every one of the six is there because of it: Venarian Gold's came out of
``counters`` and Primitive Justice's out of ``destruction`` at Mirage,
Deadshot's and Phyrexian Splicer's were written there at Tempest, and Siege
Striker's and Rookie Mistake's came out of ``characteristics`` at Stronghold to
join their tap-and-payoff and keyword twins. The rule stands, and this is where
it points now — a fuser's home is the shape it reads, never the verb inside it,
and the shape is this family's. What it got wrong was the file. The composer
and the fusers are *alternative* lowerings of one node, tried in a fixed order
by a third module: neither calls the other, they share no helper, and the call
graph fell apart along exactly that line. The composer is the half that grows,
so it kept the name.

Not every fuser the dispatcher asks is here. ``hand``'s draw-and-discard pair,
``exile``'s Swords to Plowshares, ``stack``'s Lofty Denial, ``linked_exile``'s
Portcullis and ``fighting``'s prepare-then-interact live with their families,
and this split moved what was in ``sequences`` and nothing else. The nearest of
them to this module is ``fighting._fused_prepare_then_interact`` — Deadshot's
sentence with a pump or a counter where the tap is — which ``fighting``'s own
docstring keeps with the fight it produces.

``lower_statement`` arrives as a **parameter** to the one fuser that needs it,
``_fused_cost_repeated_destroys``, whose riders are arbitrary statements — for
``lowering/sequences``' reason: a family cannot import the dispatcher back. The
other fusers take the steps and nothing else, which is why the dispatcher calls
them from one loop and that one beside it.

Lowering-only, like ``loops`` and ``sequences``: the parse side builds the
``ast.Sequence`` (``grammar/sequences.py``), and whether it fuses is first
asked here.
"""

from __future__ import annotations

from ...oracle_types import (COST_TARGET_BASE, COST_TARGET_PER,
                             OracleInstruction)
from .. import ast
from ..errors import LoweringError
from ..phrases import is_pt_counter
from ._common import (
    _optional_slot_key,
    _filter_payload, _is_enchanted, _is_source,
    _is_target, _restrictions_beyond,
    SEVERAL_DESTROY_NARROWINGS, _signed, testable_filter_payload
)
from ._cost_records import optional_cost_key

# Venarian Gold's fuser left `lowering/counters.py` when that module crossed the
# thousand-line guard again, on the boundary its own docstring already drew: it
# cites `_lower_steps`' discipline for "if you do", and the antecedent of a
# pronoun is a fact about the sequence, not about what the second step happens
# to place. It went to `lowering/sequences` and came on here with the rest.


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
    reason below: three targeted destroys lowered as three steps all
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
    leftovers = _restrictions_beyond(filt, SEVERAL_DESTROY_NARROWINGS)
    if leftovers:
        raise LoweringError(
            "the several-target destroy cannot narrow by: " + ", ".join(leftovers),
            node=first,
        )
    described = testable_filter_payload(
        filt,
        refusal="the several-target destroy cannot test this restriction",
        node=first,
        require_narrowing=False,
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


def _fused_tap_then_bite(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"Tap target creature. **It** deals damage equal to its power to another
    target creature." (Deadshot.) One sentence pair, two chosen creatures.

    A fuser rather than two ordinary steps for ``_fused_two_target_pump``'s
    reason exactly: the second clause prints "**another** target", so the two
    clauses name two different permanents, and every one-target handler
    resolves through ``_one_choice`` — which reads the *first* entry of the
    list. Lowered plainly, Deadshot would tap a creature and then have it bite
    itself, on a card compiling supported.

    The slot-per-clause shape is what the fusion buys, and it is spelled with
    the two payloads the engine already has rather than a new kind: the tap step
    carries **no** ``targets`` description at all — so it resolves through
    ``_one_choice`` onto slot 0, which is the creature the sentence tapped — and
    the bite step carries the two-slot description ``target_bites_target``
    already reads (biter first, bitten second). One picker, announced by the
    bite step, and ``targeting._from_instructions`` finds it because the tap
    step describes nothing.

    "It" is the tapped creature: the first clause is the only prior choice in
    the sentence, so the pronoun has exactly one referent. Gated on the
    *pronoun* rather than on a repeated noun phrase, because a second printed
    "target creature" would be a second announcement (CR 601.2c) and a
    different card.
    """
    if len(steps) != 2:
        return None
    first, second = steps
    if not isinstance(first, ast.Tap) or not isinstance(second, ast.DealDamage):
        return None
    if not _is_target(first.subject):
        return None
    assert isinstance(first.subject, ast.TargetSpec)
    if first.subject.distinct_from_prior:
        # "Tap **another** target creature" opening a sentence has no prior
        # choice to differ from.
        return None
    if first.matching_tapped_land_mana:
        # "Tap target land. Add mana of that land's type." — a different
        # sentence with a rider this fusion carries nowhere.
        return None
    if not (
        isinstance(second.amount, ast.ThatMuch)
        and second.amount.source == "its_power"
        and not second.amount.bonus
    ):
        return None
    if second.riders != ast.DamageRiders():
        return None
    source = second.source
    if not (
        isinstance(source, ast.TargetSpec)
        and source.quantifier == "it"
        and source.filter.is_source
    ):
        return None
    if len(second.recipients) != 1:
        return None
    bitten = second.recipients[0]
    if not isinstance(bitten, ast.TargetSpec) or not bitten.targeted:
        return None
    if not bitten.distinct_from_prior:
        # Without the printed "another", CR 601.2c lets the two instances of
        # "target" name the same permanent — which is a card that taps a
        # creature and has it bite itself, and not this one. Refusing here
        # leaves the sentence to `_refuse_unfused_distinctness`, whose message
        # names the real gap.
        return None
    biter_filter = _filter_payload(first.subject.filter)
    return (
        OracleInstruction("sequence", "", {"steps": (
            OracleInstruction("tap_target_permanent", "", dict(biter_filter)),
            OracleInstruction("target_bites_target", "", {
                "targets": {
                    "quantifier": "target",
                    "kind": "object",
                    "filter": biter_filter,
                    "filters": [
                        biter_filter,
                        _filter_payload(bitten.filter),
                    ],
                    "count": 2,
                    # The printed "another" the branch above requires, carried
                    # into the payload the announcement gate reads — the same
                    # rider ``_fused_two_target_pump`` records and this fusion
                    # dropped. Deadshot without it taps a creature and has it
                    # bite itself for nothing, which is a legal announcement of
                    # a card that does not exist.
                    "distinct": True,
                    **_optional_slot_key((first.subject, bitten)),
                },
            }),
        )}),
    )


def _fused_two_target_keyword_move(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"Until end of turn, target creature with the chosen ability **loses it**
    and **another target creature gains it**." (Phyrexian Splicer.)

    One sentence, two chosen creatures, and one keyword that leaves the first
    and lands on the second. A fuser for ``_fused_two_target_pump``'s reason
    exactly — the printed "another" (CR 601.2c) means the clauses name different
    permanents, and every one-target keyword handler resolves through
    ``_one_choice``, which reads the first entry of the list. Lowered as two
    ordinary steps the card would take the ability off a creature and give it
    straight back.

    **Here rather than in ``lowering/keywords``**, which is this module's own
    rule: a fuser lives with the sequence it folds, not with the verb it folds.
    What it reads is a shape — a removal and a grant naming the same word — and
    the keyword inside is one leaf of that shape.

    The word itself is in neither clause: both print the pronoun, and what it
    names is the option the *activation* chose (CR 601.2b, through CR 602.2b),
    recorded on the ability's own source. So the instruction carries no keyword
    at all, and the handler reads one. Both halves must print the pronoun: a
    move whose halves named different abilities would be two effects sharing a
    sentence, and one printed word with one pronoun would be a card that takes
    flying off one creature and gives something else to another.
    """
    if len(steps) != 2:
        return None
    first, second = steps
    if not isinstance(first, ast.LoseKeyword) or not isinstance(second, ast.GainKeyword):
        return None
    if not (first.chosen_ability and second.chosen_ability):
        return None
    if first.keywords or second.keywords:
        # Belt and braces: the productions that set the flag pass no keywords,
        # and a node carrying both would be two readings of one clause.
        return None
    if not _is_target(first.subject) or not _is_target(second.subject):
        return None
    assert isinstance(first.subject, ast.TargetSpec)
    assert isinstance(second.subject, ast.TargetSpec)
    if first.subject.distinct_from_prior:
        raise LoweringError(
            'the first clause of a sentence cannot name "another" target',
            node=first,
        )
    if not second.subject.distinct_from_prior:
        # Without the printed "another", CR 601.2c lets the two instances of
        # "target" name one permanent — a creature losing an ability and
        # regaining it, which is not this card. Refusing without consuming
        # leaves the sentence to `_refuse_unfused_distinctness`, whose message
        # names the real gap.
        return None
    if not first.subject.filter.chosen_keyword:
        # "**target creature with the chosen ability** loses it." The narrowing
        # is what makes the removal legal at announcement (CR 601.2c): without
        # it the picker would offer a creature that has nothing to lose, and
        # the ability would resolve having moved nothing.
        raise LoweringError(
            "a keyword move takes it from a creature the phrase says has it",
            node=first,
        )
    for clause in (first, second):
        if clause.duration.kind not in ("until_end_of_turn", "this_turn"):
            # A durationless half is a continuous effect and a mismatched pair
            # is two effects sharing a sentence — `_fused_two_target_pump`'s
            # two refusals, and for its reasons.
            raise LoweringError(
                "a keyword move needs an until-end-of-turn duration on both "
                "clauses",
                node=clause,
            )
    return (
        OracleInstruction("move_chosen_keyword_between_targets", "", {
            "duration": "end_of_turn",
            "targets": {
                "quantifier": "target",
                "kind": "object",
                # `filter` is the shape every one-slot reader expects;
                # `filters` is what the picker and the handler read per slot.
                # Both are emitted for `_fused_two_target_pump`'s reason.
                "filter": _filter_payload(first.subject.filter),
                "filters": [
                    _filter_payload(first.subject.filter),
                    _filter_payload(second.subject.filter),
                ],
                "count": 2,
                **_optional_slot_key((first.subject, second.subject)),
                # The printed "another" (CR 601.2c), carried rather than folded
                # into a filter: it is a relation between two slots, not a
                # property of one permanent.
                "distinct": True,
            },
        }),
    )


def _fused_tap_any_number_then_pump(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"You may tap any number of untapped creatures you control. This creature
    gets +1/+1 until end of turn for each creature tapped this way." (Siege
    Striker.)

    **One instruction, because the count crosses the sentence boundary.** The
    second sentence is sized by what the first one tapped, and the first one is a
    choice made at resolution — so lowered as two steps the pump would run before
    the seat had answered, and there would be nothing for "this way" to count.
    Rewind's ``untap_up_to`` says in its own registration that it deliberately
    does not suspend the resolution "because the untap is the last step of the
    effect that armed it"; here it is not, and fusing is the cheaper of the two
    answers — the choice's resolver taps *and* pumps, so no value has to survive
    a suspension.

    The printed "untapped" is carried explicitly rather than through the filter
    payload: ``ObjectFilter.to_payload`` emits ``tapped_only`` when ``tapped`` is
    True and **nothing** when it is False, so passing the payload alone would
    reduce "untapped creatures you control" to "creatures you control". For the
    tap that is nearly harmless — tapping a tapped creature does nothing — but
    the *count* is the card, and it would count creatures that were already
    tapped.
    """
    if len(steps) != 2:
        return None
    optional, payoff = steps
    if not isinstance(payoff, ast.Pump) or not payoff.per_each_tapped_this_way:
        return None
    if not isinstance(optional, ast.May) or optional.cost is not None:
        raise LoweringError(
            '"for each creature tapped this way" needs a tap in front of it',
            node=payoff,
        )
    tap = optional.action
    if not isinstance(tap, ast.Tap) or not isinstance(tap.subject, ast.TargetSpec):
        raise LoweringError(
            '"for each creature tapped this way" counts a tap, and the sentence '
            "in front of it is not one",
            node=payoff,
        )
    spec = tap.subject
    if spec.quantifier != "any_number":
        raise LoweringError(
            "the tapped-this-way count reads a resolution-time pick", node=payoff
        )
    if not _is_source(payoff.subject):
        raise LoweringError(
            "the tapped-this-way pump applies to the ability's own source",
            node=payoff,
        )
    if payoff.duration.kind != "until_end_of_turn":
        raise LoweringError(
            "a tapped-this-way pump needs an end-of-turn duration", node=payoff
        )
    if payoff.x_definition is not None:
        raise LoweringError(
            "a tapped-this-way pump is sized by the tap, not by a where-clause",
            node=payoff,
        )
    leftover = _restrictions_beyond(
        spec.filter, frozenset({"card_types", "controller", "tapped", "type_match"})
    )
    if leftover:
        raise LoweringError(
            "the any-number tap cannot narrow by: " + ", ".join(leftover), node=payoff
        )
    return (
        OracleInstruction("tap_any_number_then_pump_self", "", {
            "filter": _filter_payload(spec.filter),
            # See the docstring: the payload cannot carry "untapped".
            "untapped_only": spec.filter.tapped is False,
            "power": _signed(payoff.power, payoff.power_negative),
            "toughness": _signed(payoff.toughness, payoff.toughness_negative),
        }),
    )


def _fused_two_target_pump(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"<target A> gets +P/+T and **another target** B gets +P/+T", one sentence,
    two chosen creatures. (Rookie Mistake.)

    One instruction, because the second clause names a *second* target: lowered
    as two steps, both pumps resolve through `_one_choice`, which takes the first
    entry of the target list — so the card would compile supported and put both
    boosts on one creature.

    The distinctness is the trigger for fusing rather than a detail of it. Two
    targeted pumps in one sentence *without* the printed "another" are refused
    outright: CR 601.2c lets two instances of the word "target" name the same
    object, so that shape needs a picker told about two slots, and falling
    through to the ordinary step lowering is the silent double pump above. No
    card in the pool prints it, so the refusal costs nothing and closes the near
    miss.
    """
    if len(steps) != 2:
        return None
    first, second = steps
    if not isinstance(first, ast.Pump) or not isinstance(second, ast.Pump):
        return None
    if not _is_target(first.subject) or not _is_target(second.subject):
        return None
    assert isinstance(first.subject, ast.TargetSpec)
    assert isinstance(second.subject, ast.TargetSpec)
    if first.subject.distinct_from_prior:
        # "Another target creature … and target creature …" — the first clause
        # of a sentence has no prior choice to differ from.
        raise LoweringError(
            'the first clause of a sentence cannot name "another" target',
            node=first,
        )
    if not second.subject.distinct_from_prior:
        raise LoweringError(
            "two targeted pumps in one sentence name two targets only when the "
            'second prints "another"',
            node=second,
        )
    if first.duration.kind != "until_end_of_turn" or second.duration.kind != "until_end_of_turn":
        # A durationless half is a continuous effect (`_durationless_reason`);
        # a mismatched pair is two different effects sharing a sentence.
        raise LoweringError(
            "a two-target pump needs an until-end-of-turn duration on both clauses",
            node=second,
        )
    if first.x_definition is not None or second.x_definition is not None:
        raise LoweringError(
            "a where-clause defines one X, which two pumped targets would share",
            node=second,
        )
    slots = tuple(
        {
            "power": _signed(node.power, node.power_negative),
            "toughness": _signed(node.toughness, node.toughness_negative),
        }
        for node in (first, second)
    )
    return (
        OracleInstruction("pump_targets_until_eot", "", {
            "slots": slots,
            "targets": {
                "quantifier": "target",
                "kind": "object",
                # `filter` is the shape every one-slot reader expects; `filters`
                # is what the picker and the handler read per slot. Both are
                # emitted for the same reason `target_bites_target` emits both.
                "filter": _filter_payload(first.subject.filter),
                "filters": [
                    _filter_payload(first.subject.filter),
                    _filter_payload(second.subject.filter),
                ],
                "count": 2,
                **_optional_slot_key((first.subject, second.subject)),
                # The printed "another" (CR 601.2c), carried rather than folded
                # into a filter: it is a relation between two slots, not a
                # property of one permanent, so `permanent_matches_filter` could
                # never test it.
                "distinct": True,
            },
        }),
    )
