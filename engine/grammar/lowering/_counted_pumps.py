"""How large a P/T modification a clause computes, and how long it lasts.

A **floor**, not a family: `characteristics.py` reads it and it reads nothing
back — inside `lowering/` a module a family imports has to sit below the
families, which is `_counted_damage`'s reason one family over and `_bites`' and
`_sweeps`' before it.

Split out of `characteristics.py` at the 1,000-line guard, along exactly the
line `_counted_damage` was split from `damage.py` along — CR 107.2/107.3's:
a printed quantity that is **counted**, off a board or out of the resolution's
own scratchpad, **against the sentence that spends it**. `_amounts` keeps the
quantity (`count_spec`, the halving, the printed P/T change); every sentence in
`characteristics.py` that *spent* a count was a pump sentence, and those are
here. The mirror of that split, one CR layer over: 613 layer 7c rather than
120.

`_TARGET_PUMP_DURATIONS` came with them rather than staying behind, and it is
the second half of the title. Every reading here has to ask which sweep takes
the boost back before it can emit anything, and a table left on the other side
of the cut would be a family importing a floor importing that family. It is one
table with one reader on each side of the seam, which is what a floor is for.

That is the half that **grows with the pool**, the playbook's tiebreak when both
halves are dispatch: this file is one branch per printed shape of counted pump —
the milled-this-way record, the team buff, the bound target, the event's own
subject, the source — and a set adds a shape to it far oftener than it teaches
`count_spec` a new zone.
"""

import dataclasses

from ...oracle_types import MILLED_THIS_WAY, OracleInstruction
from ...subject_filters import object_only_filter
from .. import ast
from ..errors import LoweringError
from ._amounts import count_spec, _per_each_amount, _per_each_offset
from ._common import (chargeable_card_filter, _describe_targets,
                      _filter_payload, _is_enchanted, _is_source,
                      _is_target)
from ._events import _EVENT_SUBJECT_OBJECTS

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
        # "**Each** attacking creature gets …" (Mercadia's Downfall) against
        # "Attacking creatures get …" (Márton Stromgald): two printed spellings
        # of one set, and the noun parser keeps them apart because elsewhere the
        # words differ. Here they cannot: a sweep over every member of a class
        # is the same sweep however the class was written, and reading only one
        # of them left the other refused on its quantifier.
        and node.subject.quantifier in ("all", "each")
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


def _lower_pump_per_milled(node: ast.Pump) -> tuple[OracleInstruction, ...]:
    """"…**it** gets +1/+0 until end of turn **for each creature card put into
    your graveyard this way**." (Song of Blood, in the sentence its delayed
    ability carries.)

    A one-shot boost on the ability's own source, sized by a back-reference —
    the same ``pump_self`` shape the "for each" branch below already emits, and
    the same ``x_from_count`` channel; only where the number comes from
    differs. So it is a branch rather than a kind: what an instruction *does*
    is unchanged, and only the count is read out of a record instead of off a
    board.

    Three refusals, each because the alternative is a card doing something it
    did not print:

    - **No duration** would be a continuous contribution whose size is a frozen
      record, which the layer-7 refresh would keep re-applying for the rest of
      the game.
    - **A subject that is not the source** points a boost at a permanent this
      instruction cannot address; the "for each" branch below refuses the same
      shape for the same reason.
    - **A narrowing the card matcher cannot answer** would be dropped, and a
      dropped narrowing here counts every milled card as a creature card.

    The producer gate is **not** here, and that is the one thing this lowering
    cannot check: the sentence is compiled on its own by
    ``oracle._parse_delayed_attack_trigger``, which never sees the "Mill four
    cards." in front of it. ``oracle._split_trailing_delayed_trigger`` is where
    the two halves meet and is where the record is required to exist.
    """
    if node.duration.kind is None:
        raise LoweringError(
            'a "this way" pump with no duration would be a continuous effect '
            "sized by a frozen record", node=node,
        )
    duration = _TARGET_PUMP_DURATIONS.get(node.duration.kind)
    if duration is None or not _is_source(node.subject):
        raise LoweringError(
            'a "put into your graveyard this way" pump is a one-shot boost on '
            "its own source", node=node,
        )
    # Through the one gate every printed **card** phrase runs through, not
    # `_filter_payload` — that wrapper refuses a card-scoped filter on purpose,
    # because the handlers it feeds search the battlefield, and here the card
    # scope is the whole point. It also refuses a phrase that never printed the
    # word "card": a mill puts cards into a graveyard, and "for each creature
    # put into your graveyard this way" is a sentence about permanents that
    # nothing here could answer.
    described = chargeable_card_filter(node.per_each_milled.filter)
    if not described:
        raise LoweringError(
            "a milled-card count cannot test this restriction", node=node
        )
    return (
        OracleInstruction("pump_self", "", {
            # The sign rides inside `times_x`, exactly as the "for each" branch
            # below relies on — so the negation flags must not be emitted too.
            "power": _per_each_amount(node.power, node.power_negative, node),
            "toughness": _per_each_amount(
                node.toughness, node.toughness_negative, node
            ),
            "x_from_count": {
                "recorded_cards": MILLED_THIS_WAY, "filter": described,
            },
        }),
    )


def lower_counted_pump(
    node: ast.Pump, event: str | None = None,
) -> tuple[OracleInstruction, ...] | None:
    """The readings of a pump whose **size is a count**, or None for a pump
    whose size is printed.

    None rather than a refusal, because this is the head of
    ``characteristics._lower_pump``'s branch list and not the whole of it: a
    sentence with no "for each" in it has simply not reached its reading yet.
    Every shape that *is* counted either answers here or refuses here — a
    counted pump that fell through would be sized by the printed number alone,
    which is a silent +0/+0 or a bonus one instead of a bonus per creature.
    """

    if node.per_each_milled is not None:
        return _lower_pump_per_milled(node)
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
            # "Whenever a Sliver becomes blocked, **that Sliver** gets +1/+1
            # until end of turn **for each creature blocking it**." (Spined
            # Sliver.) A fifth reading, and the second whose subject is neither
            # the source nor a class. The branch above and this one print the
            # same two pronouns and mean the same relation by them; what differs
            # is who chose the object. Barreling Attack's was *targeted*, so the
            # count waits for a picker; this one was chosen by nobody — the
            # trigger fired about it (CR 603.10), and the fire site froze its id
            # before the effect existed.
            #
            # Gated on `_EVENT_SUBJECT_OBJECTS` rather than on the printed word,
            # exactly as the keyword removal and the copy one family over are:
            # under any other trigger "that Sliver" names an object no fire site
            # recorded, and the pump would land on nothing while the card
            # compiled clean.
            #
            # The noun phrase is carried and re-checked at resolution rather
            # than dropped, for that removal's reason: it restates the trigger's
            # own narrowing, and a word consumed and never read is a word that
            # could be deleted with no change to what the card does.
            if (
                isinstance(node.subject, ast.TargetSpec)
                and node.subject.quantifier == "that"
                and not node.subject.targeted
                and node.per_each.blocking_bound_target
                and node.duration.kind is not None
                and event in _EVENT_SUBJECT_OBJECTS
            ):
                duration = _TARGET_PUMP_DURATIONS.get(node.duration.kind)
                if duration is None:
                    raise LoweringError(
                        "no pump handler ends at this duration", node=node
                    )
                described = _filter_payload(node.subject.filter)
                if object_only_filter(described) is None:
                    raise LoweringError(
                        "the event subject's pump carries a restriction the "
                        "resolution cannot test", node=node,
                    )
                # The same rewrite the two branches around this one make,
                # pointed at the third referent: "blocking it" is a relation to
                # one named permanent, and `count_from_payload` resolves
                # `blocking_source` against whichever permanent the handler
                # hands it — here the event's subject, which is what the kind
                # says and why no `relative_to` marker is needed.
                counted = dataclasses.replace(
                    node.per_each,
                    blocking_bound_target=False, blocking_source=True,
                )
                subject_payload: dict[str, object] = {
                    "power": _per_each_amount(
                        node.power, node.power_negative, node
                    ),
                    "toughness": _per_each_amount(
                        node.toughness, node.toughness_negative, node
                    ),
                    "x_from_count": count_spec(
                        counted, node, offset=_per_each_offset(node)
                    ),
                    "duration": duration,
                }
                if described:
                    subject_payload["filter"] = described
                return (
                    OracleInstruction("pump_event_subject", "", subject_payload),
                )
            # "**Enchanted creature** gets +1/+1 for each other creature you
            # control." (Vampirism.) The same CR 613 layer-7c contribution the
            # source-subject branch below produces, landing on the permanent
            # this one is attached to — which is what `subject: "attached"`
            # says, exactly as a `conditional_static` says it. The count is
            # still the *Aura's* (CR 109.5: "you" is the ability's controller),
            # so nothing about the spec changes; only who the delta is added
            # to.
            #
            # Durationless only. A "for each" pump on the host **with** a
            # duration is a one-shot, and the persistent channel this kind
            # writes to has no end-of-turn sweep — it would be a permanent
            # bonus on a card that printed "until end of turn".
            if _is_enchanted(node.subject) and node.duration.kind is None:
                return (
                    OracleInstruction("dynamic_pt_bonus", "", {
                        "power": _per_each_amount(
                            node.power, node.power_negative, node
                        ),
                        "toughness": _per_each_amount(
                            node.toughness, node.toughness_negative, node
                        ),
                        "x_from_count": count_spec(
                            node.per_each, node, offset=_per_each_offset(node)
                        ),
                        "subject": "attached",
                    }),
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
    return None
