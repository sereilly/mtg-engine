"""Lowering what a permanent is: P/T, keywords, colour, printed text.

Pump and base-P/T setting (CR 613 layer 7), keyword grants and removals
(layer 6), colour and type changes (layers 4 and 5) and text changes (layer 3).
Counters — CR 122, a different thing from a characteristic, however often a
counter is what carries one — lower in `counters.py`; this module crossed the
thousand-line cap when they shared it.

A continuous effect with no duration is refused here rather than lowered, and
`_durationless_reason` in `_common` says why per subject: the refusal names
what is missing instead of producing an effect that never ends.
"""

import dataclasses

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._amounts import (
    count_spec,
    _per_each_amount,
    _per_each_offset,
    _static_x_amount,
    _x_definition_spec,
)
from ._common import (
    _amount_payload,
    _describe_targets,
    _durationless_reason,
    _filter_payload,
    _is_enchanted,
    _is_source,
    _is_target,
    _restrictions_beyond,
    _signed,
)


#: The printed durations a *targeted* pump has a sweep for, mapped to the
#: `pt.TEMPORARY_PT_CHANNELS` channel that records it. "This turn" and "until
#: end of turn" are the same moment for a modification (CR 514.2's cleanup step
#: is where both end); everything absent from this table refuses.
_TARGET_PUMP_DURATIONS: dict[str, str] = {
    "until_end_of_turn": "end_of_turn",
    "this_turn": "end_of_turn",
    "until_end_of_combat": "end_of_combat",
}


def _is_global_per_each_buff(node: ast.Pump) -> bool:
    """Whether a "for each" pump is the one-shot **team** shape.

    "Other attacking creatures get +1/+1 until end of turn for each attacking
    creature other than Márton Stromgald." The subject is a class, so the
    global-buff branch owns the noun phrase; the duration is required, because
    `buff_creatures_global` walks the board once and stamps a temporary boost —
    with no duration the sentence would be a continuous anthem whose size
    recomputes, which that handler cannot be.
    """
    return (
        node.per_each is not None
        and isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "all"
        and not node.subject.targeted
        and node.duration.kind is not None
    )


def _resolve_per_each_pronoun(node: ast.Pump) -> ast.Pump:
    """"**It** gets -2/-1 … for each creature blocking **it**" (Johtull Wurm).

    One sentence, one pronoun. The noun parser reads "blocking it" as a
    relation to whatever the sentence *bound* — which is right for Feint, whose
    earlier sentence chose a target — but this branch has already required the
    pump's own subject to be the ability's source, and the two "it"s cannot
    name different objects. So the relation is rewritten onto the source here,
    where that is known, rather than in the parser, where it is not.

    A rewrite rather than a second parse rule, because the printed words are
    identical: what decides the referent is the rest of the sentence.
    """
    filt = node.per_each
    if filt is None or not filt.blocking_bound_target:
        return node
    return dataclasses.replace(
        node,
        per_each=dataclasses.replace(
            filt, blocking_bound_target=False, blocking_source=True
        ),
    )


def _lower_pump(node: ast.Pump) -> tuple[OracleInstruction, ...]:
    if node.per_each_tapped_this_way:
        # "…for each creature tapped **this way**" reaching here means no fuser
        # claimed the sentence, so there is no tap in front of it and nothing for
        # the phrase to count. Dropped, the pump is a silent +0/+0 on a card that
        # reported supported — a back-reference names its producer or refuses
        # (idiom #7).
        raise LoweringError(
            "\"for each creature tapped this way\" with no tap in this effect",
            node=node,
        )
    if node.per_each is not None:
        # "This creature gets +2/+2 **for each Aura attached to it**" (Rabid
        # Wombat). A CR 613 layer-7c contribution whose *size* is a count, like
        # the where-clause form below it — only the spelling of the
        # multiplication differs, so it lands on the same ``dynamic_pt_bonus``
        # kind and the same shared count spec.
        #
        # Three readings, and everything outside them refuses rather than
        # falling through: without a duration and on the source it is that
        # continuous bonus; with a duration and on the source it is a one-shot
        # `pump_self` sized the same way; and with a duration on a *class* it is
        # the global buff below, which is the one shape whose subject is not the
        # source at all. A subject that is neither points a bonus at a permanent
        # nothing refreshes.
        if not _is_global_per_each_buff(node):
            # "…**it** gets +1/+1 until end of turn for each creature blocking
            # **it**." (Barreling Attack, in the sentence a delayed ability
            # carries.) A fourth reading, and the first whose subject is neither
            # the source nor a class: one sentence, one pronoun, and the object
            # both name is the creature the effect *targets*. The count is
            # therefore measured against that permanent rather than against the
            # ability's own source — which on this card is a spell in a
            # graveyard by the time the ability fires, and blocks nothing.
            #
            # The same rewrite `_resolve_per_each_pronoun` makes for the
            # source-subject spelling, pointed at the other referent, and the
            # marker is what tells the handler to defer the count until it has
            # resolved the target.
            if (
                _is_target(node.subject)
                and node.per_each.blocking_bound_target
                and node.duration.kind is not None
            ):
                duration = _TARGET_PUMP_DURATIONS.get(node.duration.kind)
                if duration is None:
                    raise LoweringError(
                        "no pump handler ends at this duration", node=node
                    )
                counted = dataclasses.replace(
                    node.per_each,
                    blocking_bound_target=False, blocking_source=True,
                )
                payload: dict[str, object] = {
                    "power": _per_each_amount(
                        node.power, node.power_negative, node
                    ),
                    "toughness": _per_each_amount(
                        node.toughness, node.toughness_negative, node
                    ),
                    "x_from_count": {
                        **count_spec(counted, node, offset=_per_each_offset(node)),
                        "relative_to": "pumped_target",
                    },
                    "duration": duration,
                }
                _describe_targets(payload, node.subject)
                return (
                    OracleInstruction(
                        "pump_target_creature_until_eot", "", payload
                    ),
                )
            if not _is_source(node.subject):
                raise LoweringError(
                    'a "for each" pump is only a continuous bonus on its own '
                    "source or a one-shot buff on a named class", node=node,
                )
            node = _resolve_per_each_pronoun(node)
            if node.duration.kind is not None:
                # "…**it gets +1/+0 until end of turn** for each other attacking
                # Aurochs." A duration makes it a one-shot pump rather than a
                # continuous contribution, and `pump_self` already boosts the
                # source until end of turn with a computed size — the
                # where-clause branch below hands it the very same
                # `x_from_count` spec. What differs is only how the
                # multiplication is *spelled*: "+X/+0, where X is the number of
                # …" and "+1/+0 for each …" are one amount, and
                # `resolve_amount`'s `times_x` is where the printed repetition
                # size already lives.
                duration = _TARGET_PUMP_DURATIONS.get(node.duration.kind)
                if duration is None:
                    raise LoweringError(
                        "no pump handler ends at this duration", node=node
                    )
                return (
                    # The sign is already inside `times_x`, which is what
                    # `dynamic_pt_bonus` below relies on — so the negation flags
                    # `pump_self` reads must *not* be emitted here as well. They
                    # were, and the handler negated a second time: "it gets
                    # -2/-1 until end of turn for each creature blocking it
                    # beyond the first" (Johtull Wurm) would have *grown* the
                    # wurm. Latent until that card, because every earlier one
                    # reaching this branch printed a plus.
                    OracleInstruction("pump_self", "", {
                        "power": _per_each_amount(
                            node.power, node.power_negative, node
                        ),
                        "toughness": _per_each_amount(
                            node.toughness, node.toughness_negative, node
                        ),
                        "x_from_count": count_spec(
                            node.per_each, node, offset=_per_each_offset(node)
                        ),
                    }),
                )
            return (
                OracleInstruction("dynamic_pt_bonus", "", {
                    # The printed number sizes *one* repetition. Carried as an
                    # amount rather than folded into the spec's multiplier: the
                    # spec is one count and the two halves may scale
                    # differently.
                    "power": _per_each_amount(node.power, node.power_negative, node),
                    "toughness": _per_each_amount(
                        node.toughness, node.toughness_negative, node
                    ),
                    "x_from_count": count_spec(
                        node.per_each, node, offset=_per_each_offset(node)
                    ),
                }),
            )
    if node.duration.kind is None:
        # "This creature gets +X/+0, where X is the greatest power among
        # creature cards in your graveyard." (Carrion Grub.) A pump with no
        # duration is a *continuous* effect, which is why the general case
        # refuses — but one on the ability's own source, with its size computed
        # from a spec the shared evaluator reads, is exactly the CR 613 layer 7c
        # contribution the P/T refresh already rebuilds every recompute
        # (engine/mixins/permanent_state.py). What made it unreachable was not
        # the layer, it was having no way to say how big it is.
        if node.x_definition is not None and _is_source(node.subject):
            return (
                OracleInstruction("dynamic_pt_bonus", "", {
                    "power": _static_x_amount(node.power, node.power_negative, node),
                    "toughness": _static_x_amount(
                        node.toughness, node.toughness_negative, node
                    ),
                    "x_from_count": _x_definition_spec(node.x_definition, node),
                }),
            )
        # "{1}{R}: This creature gets +2/+0 …" (Goblin Ski Patrol) — a
        # *resolved* ability's modification with no duration printed, which
        # CR 611.2b makes one that lasts indefinitely. It is not the continuous
        # effect the refusal below is about: a static ability contributes
        # afresh on every layer recompute and is refused one layer up
        # (`_lower_static_ability`), while this is a one-shot the persistent
        # 7c channel already holds — the same channel a +1/+1 counter writes to,
        # and the one `engine/pt.py` documents as "one-shot modifications that
        # stay until something removes them".
        #
        # Only on the ability's own source. A durationless pump on a *target* or
        # on a class is the same rule and would be lowered the same way, but no
        # card in the pool prints one, and a branch with nothing behind it is a
        # claim nothing checks.
        if _is_source(node.subject):
            return (
                OracleInstruction("pump_self", "", {
                    "power": _signed(node.power, node.power_negative),
                    "toughness": _signed(node.toughness, node.toughness_negative),
                    # Named rather than left absent: every payload written
                    # before this branch means end of turn, so the handler's
                    # default has to stay that, and an indefinite one has to say
                    # so out loud.
                    "duration": "indefinite",
                }),
            )
        raise LoweringError(_durationless_reason(node.subject), node=node)

    if node.x_definition is not None:
        # "gets -X/-X until end of turn, where X is the number of cards in
        # your graveyard" (Liliana, Waker of the Dead). X is defined by a
        # count, so the payload carries what to count and the handler computes
        # it at resolution; the sign travels separately because _signed cannot
        # negate a variable.
        # "…**it** gets +X/+0 until end of turn, where X is the number of other
        # attacking creatures." (Alpine Houndmaster.) The subject is the
        # ability's own source, not a chosen target — a temporary pump on the
        # source is what `pump_self` already does, and what was missing was only
        # a way to say how big it is. Its own kind rather than a flag, for the
        # reason the base-P/T pair is two kinds: one asks a picker which
        # permanent and the other asks the context for the source.
        on_source = _is_source(node.subject)
        # "…**That creature** gets +0/+X until end of turn, where X is its mana
        # value." (Kry Shield.) The bound object the sentence in front of it
        # already targeted, not a second choice — so no ``targets`` description
        # is emitted and the handler acts on the ability's one target, the way
        # ``gain_type`` reads the same pronoun. A bound object carries no
        # narrowing to honour, so a restated adjective refuses rather than being
        # dropped.
        bound = (
            isinstance(node.subject, ast.TargetSpec)
            and node.subject.quantifier == "that"
            and not _restrictions_beyond(node.subject.filter, frozenset({"card_types"}))
        )
        if not on_source and not bound and not _is_target(node.subject):
            raise LoweringError("a where-clause pump needs a single target", node=node)
        # Whichever definition the clause carried — a count, a maximum, or a
        # characteristic of the object the sentence named. Through the one spec
        # builder rather than a type test here, which is what kept "where X is
        # its mana value" out of a sentence that reads a where-clause perfectly
        # well; `_x_definition_spec` refuses what it cannot build.
        definition_spec = _x_definition_spec(node.x_definition, node)
        # Only the characteristics the card writes as X are variable: "+X/+0"
        # pumps power alone, so the literal half stays literal.
        payload: dict[str, object] = {
            "power": "x" if isinstance(node.power, ast.Var) else _signed(
                node.power, node.power_negative
            ),
            "toughness": "x" if isinstance(node.toughness, ast.Var) else _signed(
                node.toughness, node.toughness_negative
            ),
            "power_negative": node.power_negative,
            "toughness_negative": node.toughness_negative,
            # The one spec every reader of a computed amount agrees on. The
            # graveyard-only restriction that stood here was the handler's own
            # counter talking; with the shared evaluator behind it, the zone is
            # data like everything else.
            "x_from_count": definition_spec,
        }
        if on_source:
            # ``pump_self`` already boosts the source until end of turn; what was
            # missing was a way to say how big, which is the same
            # ``x_from_count`` spec every other computed amount carries. A second
            # kind would be the same handler with the number arriving by a
            # different road.
            return (OracleInstruction("pump_self", "", payload),)
        assert isinstance(node.subject, ast.TargetSpec)
        if not bound:
            _describe_targets(payload, node.subject)
        return (OracleInstruction("pump_target_creature_until_eot", "", payload),)

    power = _signed(node.power, node.power_negative)
    toughness = _signed(node.toughness, node.toughness_negative)

    if _is_enchanted(node.subject):
        return (
            OracleInstruction(
                "pump_enchanted_creature", "", {"power": power, "toughness": toughness}
            ),
        )
    if _is_source(node.subject):
        return (OracleInstruction("pump_self", "", {"power": power, "toughness": toughness}),)
    if _is_target(node.subject):
        assert isinstance(node.subject, ast.TargetSpec)
        payload: dict[str, object] = {"power": power, "toughness": toughness}
        payload["blocking_only"] = bool(node.subject.filter.blocking)
        _describe_targets(payload, node.subject)
        if node.duration.kind == "while_source_tapped":
            # Its own kind rather than a flag on the until-end-of-turn one:
            # that handler writes a delta the cleanup step subtracts, and this
            # effect must not be written as a delta at all — it is rebuilt from
            # the source's record on every recompute, so it ends the instant
            # the source untaps rather than at the next cleanup.
            return (
                OracleInstruction("pump_target_while_source_tapped", "", payload),
            )
        # Which sweep takes the boost back. Only the durations
        # ``pt.TEMPORARY_PT_CHANNELS`` has a channel for are admitted: every
        # other one used to fall through to the end-of-turn kind with no trace
        # in the payload that a word had been read, so "until end of combat"
        # (Glyph of Destruction) lasted a whole turn and "until your next
        # upkeep" (Gabriel Angelfire) lasted until this one ended.
        duration = _TARGET_PUMP_DURATIONS.get(node.duration.kind)
        if duration is None:
            raise LoweringError(
                f"no sweep ends a target's pump at {node.duration.kind}", node=node
            )
        if duration != "end_of_turn":
            payload["duration"] = duration
        return (OracleInstruction("pump_target_creature_until_eot", "", payload),)

    # "White creatures get +1/+1", "Attacking creatures get +2/+0 until end of turn"
    if isinstance(node.subject, ast.TargetSpec) and node.subject.quantifier == "all":
        filt = node.subject.filter
        if filt.card_types != ("creature",):
            raise LoweringError("global buff on a non-creature scope", node=node)
        leftover = _restrictions_beyond(
            filt,
            frozenset({
                "card_types", "colors", "excluded_colors", "controller",
                "attacking", "blocking", "other_than_source", "subtypes",
                "excluded_types",
                # "all attacking creatures **with flanking**" (Telim'Tor),
                # "Creatures **with flying** get +1/+0" (Aether Storm's
                # neighbours). A layer-6 question (CR 613.1f), so a creature
                # *granted* the word is in the set and a printed one that lost
                # it is not -- which is exactly why it cannot be answered off
                # the printed keyword list and has to reach the handler as
                # payload.
                "with_keywords",
            }),
        )
        if leftover:
            raise LoweringError(
                "the global buff cannot narrow by: " + ", ".join(leftover), node=node
            )
        payload = {"power": power, "toughness": toughness}
        # "…**for each attacking creature other than Márton Stromgald**". The
        # printed P/T sizes one repetition and the count multiplies it, exactly
        # as it does on the two source-shaped branches above — the same
        # `times_x` amount and the same shared count spec, so one printed clause
        # means one number wherever it is printed. The whole set is fixed at
        # resolution (CR 611.2c), which is what makes a one-shot buff the right
        # handler for it.
        if node.per_each is not None:
            payload["power"] = _per_each_amount(node.power, node.power_negative, node)
            payload["toughness"] = _per_each_amount(
                node.toughness, node.toughness_negative, node
            )
            payload["x_from_count"] = count_spec(
                node.per_each, node, offset=_per_each_offset(node)
            )
        if filt.colors:
            payload["color"] = filt.colors[0]
        # "**Nonwhite** creatures get -1/-1 until end of turn." (Holy Light.)
        # The negative twin of the colour above, and it must be carried rather
        # than dropped for the reason every refusal in this file names: an
        # ignored exclusion is a strictly wider sweep than the card prints, and
        # here it is the sweep that debuffs the caster's own white team. A
        # colourless creature is nonwhite (CR 105.2c), which falls out of
        # testing membership rather than absence.
        if filt.excluded_colors:
            payload["exclude_colors"] = list(filt.excluded_colors)

        # "Other **Orc** creatures get +1/+1 until end of turn." (Orc General.)
        # The subtype is payload, tested through ``has_type`` like every other
        # type question in this handler, so a card naming another tribe needs
        # nothing here. It is a list because the noun phrase already reads a
        # union ("Djinn or Efreet"), and the alternatives are OR'd exactly as
        # the permanent matcher OR's them.
        if filt.subtypes:
            payload["subtypes"] = list(filt.subtypes)
        # "…all attacking creatures **with flanking** get +1/+1 until end of
        # turn." (Telim'Tor.) Carried rather than dropped for this file's
        # standing reason: an ignored narrowing is a strictly wider sweep than
        # the card prints -- here Telim'Tor pumping the defending player's
        # blockers is not on the table, but it would pump every attacker in a
        # multiplayer combat. The word is validated against
        # ``IMPLEMENTED_KEYWORDS`` because a word no behaviour is registered
        # under makes ``_has_keyword`` answer no for everything, which turns
        # the buff into a no-op the card reports as supported.
        if filt.with_keywords:
            from ...subject_filters import unimplemented_filter_keywords

            unknown = unimplemented_filter_keywords(
                {"with_keywords": list(filt.with_keywords)}
            )
            if unknown:
                raise LoweringError(
                    "the global buff cannot test the keyword(s): "
                    + ", ".join(sorted(unknown)),
                    node=node,
                )
            payload["with_keywords"] = list(filt.with_keywords)
        # "**Nonartifact** creatures get -1/-1 until end of turn." (Stench of
        # Decay.) The type twin of ``exclude_colors`` above, and it is the same
        # argument for carrying it: the noun phrase already read the exclusion,
        # and dropping it here is a strictly wider sweep than the card prints —
        # here one that also shrinks the caster's own artifact creatures.
        # Tested through ``has_type`` rather than the printed type line, so a
        # creature *animated* into an artifact escapes and one that stopped
        # being one is caught (CR 613 layer 4).
        if filt.excluded_types:
            payload["exclude_types"] = list(filt.excluded_types)
        payload["all"] = filt.controller != "you"
        # "**Other** creatures you control get +1/+0" (Bolt Hound). Dropped, the
        # Hound buffed itself as well: a strictly better card than the one
        # printed. Emitted only when set, so every payload written before this
        # key existed is byte-identical.
        if filt.other_than_source:
            payload["exclude_self"] = True
        # "Creatures your opponents control get -2/-2 until end of turn"
        # (Massacre Wurm's entry). `all` cannot say this: it means "every
        # player's", which would debuff the caster's own board too. Emitted
        # only when the scope is opponents, so every payload written before
        # this key existed is byte-identical.
        if filt.controller == "opponent":
            payload["opponents_only"] = True
        if filt.attacking:
            payload["attacking_only"] = True
        if filt.blocking:
            payload["blocking_only"] = True
        return (OracleInstruction("buff_creatures_global", "", payload),)

    raise LoweringError("unsupported pump subject", node=node)


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
                # The printed "another" (CR 601.2c), carried rather than folded
                # into a filter: it is a relation between two slots, not a
                # property of one permanent, so `permanent_matches_filter` could
                # never test it.
                "distinct": True,
            },
        }),
    )


def _lower_set_base_pt(node: ast.SetBasePT) -> tuple[OracleInstruction, ...]:
    if node.duration.kind != "until_end_of_turn":
        raise LoweringError("base P/T change needs an end-of-turn duration", node=node)
    # "…**creatures you control** have base power and toughness X/X" (Jolrael).
    # A sweep rather than a target, and the same layer-7b write applied to each
    # — so it is a second kind rather than a flag, because the two resolve
    # completely differently: one asks a picker which permanent, the other asks
    # the board which permanents.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier in ("all", "each")
    ):
        filt = node.subject.filter
        leftover = _restrictions_beyond(filt, frozenset({"card_types", "controller"}))
        if leftover or filt.card_types != ("creature",) or filt.controller != "you":
            raise LoweringError(
                "the team base-P/T handler covers the creatures you control",
                node=node,
            )
        if node.power is None or node.toughness is None:
            raise LoweringError(
                "the team base-P/T handler sets both characteristics", node=node
            )
        return (
            OracleInstruction("set_team_base_pt_until_eot", "", {
                "power": _amount_payload(node.power),
                "toughness": _amount_payload(node.toughness),
            }),
        )
    if not _is_target(node.subject):
        raise LoweringError("base P/T change on a non-target subject", node=node)
    assert isinstance(node.subject, ast.TargetSpec)
    filt = node.subject.filter
    payload: dict[str, object] = {
        "power": _amount_payload(node.power) if node.power is not None else None,
        "toughness": _amount_payload(node.toughness) if node.toughness is not None else None,
        "exclude_self": filt.other_than_source,
    }
    if node.toughness is None:
        payload["attacking_only"] = bool(filt.attacking)
        payload["flying_only"] = filt.with_keywords == ("flying",)
    return (OracleInstruction("set_base_pt_target_until_eot", "", payload),)


def _lower_change_base_pt(node: ast.ChangeBasePT) -> tuple[OracleInstruction, ...]:
    """The CR 613.4b rewrite template, in Legends' four printings.

    Each branch checks the whole of what it read — the subject, every filter
    restriction, the value's shape and the duration — and refuses by name
    otherwise, because a rewrite that quietly dropped a restriction would set
    the wrong creature's base P/T forever.
    """
    # "…of all creatures that dealt damage to it this turn to 0/2" (Brine
    # Hag): a sweep over the damage record the source carries, not a target.
    if isinstance(node.subject, ast.TargetSpec) and node.subject.quantifier in ("all", "each"):
        filt = node.subject.filter
        if not filt.dealt_damage_to_source_this_turn:
            raise LoweringError(
                "a base-P/T rewrite over a set reads the damage record; "
                "this set names something else", node=node,
            )
        leftover = _restrictions_beyond(
            filt, frozenset({"card_types", "dealt_damage_to_source_this_turn"})
        )
        if leftover or filt.card_types != ("creature",):
            raise LoweringError(
                "the damage-record rewrite covers creatures alone", node=node
            )
        if node.duration.kind is not None:
            raise LoweringError(
                f"no damage-record rewrite expires at {node.duration.kind}", node=node
            )
        if not (isinstance(node.power, ast.Fixed) and isinstance(node.toughness, ast.Fixed)):
            raise LoweringError(
                "the damage-record rewrite takes a printed P/T pair", node=node
            )
        return (
            OracleInstruction("set_base_pt_of_creatures_that_damaged_source", "", {
                "power": node.power.value,
                "toughness": node.toughness.value,
            }),
        )

    if not _is_source(node.subject):
        raise LoweringError(
            "a base-P/T rewrite changes its own source or the damage record",
            node=node,
        )

    # "…to the power and toughness of target creature other than ~ until the
    # end of your next upkeep" (Halfdane): both stats read off one chosen
    # creature when the trigger resolves.
    if node.from_pt_of is not None:
        if node.duration.kind != "until_end_of_your_next_upkeep":
            raise LoweringError(
                "a copied base P/T is implemented for the end of the next "
                f"upkeep, not {node.duration.kind or 'indefinitely'}", node=node,
            )
        spec = node.from_pt_of
        if not (isinstance(spec, ast.TargetSpec) and spec.quantifier == "target"):
            raise LoweringError("a copied base P/T needs a chosen creature", node=node)
        filt = spec.filter
        leftover = _restrictions_beyond(
            filt, frozenset({"card_types", "other_than_source"})
        )
        if leftover or filt.card_types != ("creature",):
            raise LoweringError(
                "the copied-P/T handler reads a creature, optionally excluding "
                "the source", node=node,
            )
        payload: dict[str, object] = {"exclude_self": filt.other_than_source}
        _describe_targets(payload, spec)
        return (
            OracleInstruction(
                "set_source_base_pt_from_target_until_next_upkeep", "", payload
            ),
        )

    # The computed forms that read a **chosen creature** (Sentinel, Sworn
    # Defender). One or both stats, each read off the same target: the quantity
    # carries the sentence's target, so two targets would be two pickers for a
    # card that names one.
    read = _reads_a_target_characteristic(node)
    if read is not None:
        return read

    # The toughness-only computed form over a count (Wall of Tombstones).
    if node.power is not None or node.toughness is None:
        raise LoweringError(
            "a computed base-P/T rewrite sets toughness alone", node=node
        )
    if node.duration.kind is not None:
        raise LoweringError(
            f"no computed base-toughness rewrite expires at {node.duration.kind}",
            node=node,
        )
    bonus, amount = _split_printed_addend(node, node.toughness)

    # "1 plus the number of creature cards in your graveyard" (Wall of
    # Tombstones). `count_spec` is the shared reader, so the count means what
    # it means everywhere else — and refuses the zones and narrowings the
    # counter cannot take.
    if isinstance(amount, ast.CountOf):
        return (
            OracleInstruction("set_source_base_toughness_from_count", "", {
                "bonus": bonus,
                "count": count_spec(amount.filter, node),
            }),
        )
    raise LoweringError(
        f"no base-toughness rewrite reads a {type(amount).__name__}", node=node
    )


#: Which durations a base-P/T rewrite read off a chosen creature is implemented
#: for, and the ``until_eot`` flag each becomes. ``None`` is the absent clause,
#: which CR 611.2a makes "permanently" (Sentinel's "this effect lasts
#: indefinitely" is reminder text for it); Sworn Defender prints the turn.
#: A table rather than two ifs so a third duration refuses by name instead of
#: falling into whichever branch was written first.
_BASE_PT_READ_DURATIONS = {None: False, "until_end_of_turn": True}


def _split_printed_addend(node, amount):
    """``(bonus, rest)`` for "N plus <quantity>" — the printed constant in front
    of a read quantity, and the quantity itself. ``(0, amount)`` when there is
    no sum."""
    if isinstance(amount, ast.Plus):
        if not isinstance(amount.left, ast.Fixed):
            raise LoweringError("the printed addend has to be a number", node=node)
        return amount.left.value, amount.right
    return 0, amount


def _characteristic_read(node, amount):
    """One stat's ``{"characteristic", "offset"}`` payload plus the ``TargetSpec``
    it reads, or None when *amount* reads no chosen object.

    The printed constant reaches the payload from either of the two places a
    card puts it: in front of the phrase ("**1 plus** the power of …", Sentinel)
    or behind it ("the toughness of … **minus 1**", Sworn Defender). Summing
    them here is what makes those one arithmetic rather than two payload keys
    that a handler could read one of and drop the other.
    """
    bonus, rest = _split_printed_addend(node, amount)
    if not isinstance(rest, ast.CharacteristicOfTarget):
        return None
    return rest.subject, {
        "characteristic": rest.characteristic,
        "offset": bonus + rest.offset,
    }


def _reads_a_target_characteristic(node) -> tuple[OracleInstruction, ...] | None:
    """Sentinel's "change this creature's base toughness to 1 plus the power of
    target creature blocking or blocked by this creature" and Sworn Defender's
    "this creature's power becomes the toughness of target creature blocking or
    being blocked by this creature minus 1 …, and its toughness becomes 1 plus
    the power of that creature …" — one instruction for both.

    Returns None without complaint when neither stat reads a chosen object, so
    the count form below keeps its own refusals.

    The **in-combat relation** rides the instruction as its own key rather than
    the filter, because no read of the chosen creature alone can answer it:
    ``engine/legality.py`` tests it at activation and the handler again at
    resolution (CR 608.2b). Both stats must name the same ``TargetSpec`` — the
    parse binds the second clause's pronoun to the first clause's choice, and
    two different specs here would mean the sentence somehow named two.
    """
    reads = {
        stat: _characteristic_read(node, amount)
        for stat, amount in (("power", node.power), ("toughness", node.toughness))
        if amount is not None
    }
    named = {stat: read for stat, read in reads.items() if read is not None}
    if not named:
        return None
    if len(named) != len(reads):
        raise LoweringError(
            "a rewrite reading a chosen creature reads it for every stat it "
            "sets", node=node,
        )
    specs = [spec for spec, _ in named.values()]
    if any(spec is not specs[0] for spec in specs[1:]):
        raise LoweringError(
            "both halves of this rewrite have to read the same creature",
            node=node,
        )
    spec = specs[0]
    if spec.quantifier != "target":
        raise LoweringError(
            "a characteristic read needs a chosen creature", node=node
        )
    if node.duration.kind not in _BASE_PT_READ_DURATIONS:
        raise LoweringError(
            f"no rewrite read off a chosen creature expires at "
            f"{node.duration.kind}", node=node,
        )
    filt = spec.filter
    leftover = _restrictions_beyond(
        filt, frozenset({"card_types", "in_combat_with_source"})
    )
    if leftover or filt.card_types != ("creature",):
        raise LoweringError(
            "the characteristic-read rewrite reads a creature, optionally in "
            "combat with the source", node=node,
        )
    stripped = dataclasses.replace(spec, filter=dataclasses.replace(
        filt, in_combat_with_source=False
    ))
    payload: dict[str, object] = {
        "in_combat_with_source": filt.in_combat_with_source,
        "until_eot": _BASE_PT_READ_DURATIONS[node.duration.kind],
    }
    for stat, (_spec, read) in named.items():
        payload[stat] = read
    _describe_targets(payload, stripped)
    return (OracleInstruction("set_source_base_pt_from_target", "", payload),)






def _lower_double_power(node: ast.DoublePower) -> tuple[OracleInstruction, ...]:
    """"Double the power of target creature until end of turn." (Unleash Fury.)

    The duration is required, and required to be this one: a *permanent*
    doubling is a continuous effect the layer system would have to own, and
    reading it as an until-end-of-turn boost would give the card back at
    cleanup something it never said it would.
    """
    if node.duration.kind not in ("until_end_of_turn", "this_turn"):
        raise LoweringError(
            "a durationless power doubling is a continuous effect, which needs "
            "the CR 613 layers engine",
            node=node,
        )
    if not _is_target(node.subject):
        raise LoweringError("power doubling on a non-target subject", node=node)
    assert isinstance(node.subject, ast.TargetSpec)
    payload: dict[str, object] = {}
    _describe_targets(payload, node.subject)
    return (OracleInstruction("double_target_power_until_eot", "", payload),)


def _lower_switch_pt(node: ast.SwitchPT) -> tuple[OracleInstruction, ...]:
    """``Switch target creature's power and toughness until end of turn.``
    (Transmutation.)

    The duration is required and required to be this one for the reason the
    power doubling's is: the 7d flag is swept by the cleanup step
    (``_EOT_METADATA_KEYS``), so a durationless switch would silently end with
    the turn anyway — a card printed without the clause needs the layer system
    to hold the effect, not this instruction.
    """
    if node.duration.kind not in ("until_end_of_turn", "this_turn"):
        raise LoweringError(
            "a durationless power/toughness switch is a continuous effect, "
            "which needs the CR 613 layers engine",
            node=node,
        )
    payload: dict[str, object] = {}
    if _is_source(node.subject):
        return (OracleInstruction("switch_self_pt_until_eot", "", payload),)
    if not _is_target(node.subject):
        raise LoweringError(
            "no handler switches the power and toughness of this subject", node=node
        )
    assert isinstance(node.subject, ast.TargetSpec)
    _describe_targets(payload, node.subject)
    return (OracleInstruction("switch_target_pt_until_eot", "", payload),)




def _lower_change_text(node: ast.ChangeText) -> tuple[OracleInstruction, ...]:
    """``Change the text of target spell or permanent …`` (CR 612).

    For the Lace cycle's own wording no ``targets`` description is emitted: the
    vocabulary has no way to say "a spell on the stack *or* a permanent", so
    describing it at all would drop one of the two zones from the picker, and
    ``engine/legality.py`` keeps answering ``spell_or_permanent``.

    A **narrowed** subject is the opposite case. "Change the text of target
    white enchantment you control that doesn't have cumulative upkeep"
    (Balduvian Shaman) names a set of permanents and nothing on the stack, so
    the description is what carries the printed restriction to the picker and
    to the resolution check. Left off, the ability would have read as the Lace
    cycle's and been aimable at any permanent on the board — a restriction the
    card prints and nothing enforces.
    """
    if not _is_target(node.subject):
        raise LoweringError("a text change has to name what it changes", node=node)
    payload: dict[str, object] = {"mode": node.mode}
    assert isinstance(node.subject, ast.TargetSpec)
    if _filter_payload(node.subject.filter):
        _describe_targets(payload, node.subject)
    return (OracleInstruction("mark_text_modified", "", payload),)
