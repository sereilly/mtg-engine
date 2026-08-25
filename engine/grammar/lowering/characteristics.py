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

from ...oracle_types import (BLOCK_PAIR_SUBJECT, SUBJECT_FROM_TRIGGER,
                             OracleInstruction)
from .. import ast
from ..errors import LoweringError
from ..vocabulary import IMPLEMENTED_KEYWORDS
from ._events import binds_block_pair
from ._common import (
    _amount_payload,
    _describe_several_targets,
    _describe_targets,
    _durationless_reason,
    _filter_payload,
    _is_enchanted,
    _is_source,
    _is_target,
    _names_several_targets,
    _restrictions_beyond,
    _signed,
    count_spec,
)


def _static_x_amount(amount: ast.Amount, negative: bool, node) -> int | str:
    """One half of a computed static bonus: the string "x" or a literal.

    A negated X refuses. The refresh resolves the amount against the computed
    value and nothing carries a sign for it, so admitting "-X/-0" here would be
    a bonus applied with the wrong sign — the direction that makes a creature
    bigger when the card shrinks it.
    """
    if isinstance(amount, ast.Var):
        if negative:
            raise LoweringError("a static computed bonus cannot be negative", node=node)
        return "x"
    if isinstance(amount, ast.Fixed):
        return -amount.value if negative else amount.value
    raise LoweringError("a static computed bonus needs X or a number", node=node)


def _x_definition_spec(definition: ast.Amount, node) -> dict:
    """The spec behind a where-clause's X, whichever aggregate it names."""
    if isinstance(definition, ast.GreatestPowerAmong):
        return count_spec(definition.filter, node, aggregate="greatest_power")
    if isinstance(definition, ast.ColorsAmong):
        return count_spec(definition.filter, node, aggregate="distinct_colors")
    if isinstance(definition, ast.CountOf):
        return count_spec(definition.filter, node)
    if isinstance(definition, ast.ManaValueOfSubject):
        # "…, where X is **its** mana value" (Great Defender, Subdue, Kry
        # Shield). Not an aggregate over a set: the object is the one the
        # sentence already named, and the resolution reads the characteristic
        # off it (CR 202.3, so off the card rather than off the battlefield).
        return {"object_mana_value": "target"}
    raise LoweringError("only a count or a maximum can define X here", node=node)


def _lower_become_creature(
    node: ast.BecomeCreature,
) -> tuple[OracleInstruction, ...]:
    """"…becomes a 3/3 Sphinx creature with flying in addition to its other
    types until end of turn." (Riddleform.)

    Only the source animates. The handler sets the P/T on ``source_permanent``
    and the layer bridge reads the rest off one metadata record, so a sentence
    animating anything else would be pointed at the wrong permanent — refused
    rather than silently redirected.
    """
    if not _is_source(node.subject):
        raise LoweringError(
            "only the source animates itself until end of turn", node=node
        )
    return (
        OracleInstruction(
            "animate_self_until_eot", "",
            {
                "power": node.power,
                "toughness": node.toughness,
                "subtypes": list(node.subtypes),
                "keywords": list(node.keywords),
                # "…a 2/2 Assembly-Worker **artifact** creature" — the types the
                # animation adds beside "creature", which the layer-4 collector
                # reads off the same record.
                "card_types": list(node.card_types),
            },
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
        if not on_source and not _is_target(node.subject):
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
        return (OracleInstruction("pump_target_creature_until_eot", "", payload),)

    # "White creatures get +1/+1", "Attacking creatures get +2/+0 until end of turn"
    if isinstance(node.subject, ast.TargetSpec) and node.subject.quantifier == "all":
        filt = node.subject.filter
        if filt.card_types != ("creature",):
            raise LoweringError("global buff on a non-creature scope", node=node)
        leftover = _restrictions_beyond(
            filt,
            frozenset({
                "card_types", "colors", "controller", "attacking", "blocking",
                "other_than_source",
            }),
        )
        if leftover:
            raise LoweringError(
                "the global buff cannot narrow by: " + ", ".join(leftover), node=node
            )
        payload = {"power": power, "toughness": toughness}
        if filt.colors:
            payload["color"] = filt.colors[0]
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

    # The toughness-only computed forms (Sentinel, Wall of Tombstones).
    if node.power is not None or node.toughness is None:
        raise LoweringError(
            "a computed base-P/T rewrite sets toughness alone", node=node
        )
    if node.duration.kind is not None:
        raise LoweringError(
            f"no computed base-toughness rewrite expires at {node.duration.kind}",
            node=node,
        )
    bonus = 0
    amount = node.toughness
    if isinstance(amount, ast.Plus):
        if not isinstance(amount.left, ast.Fixed):
            raise LoweringError("the printed addend has to be a number", node=node)
        bonus = amount.left.value
        amount = amount.right

    # "1 plus the power of target creature blocking or blocked by this
    # creature" (Sentinel). The quantity carries the sentence's target; the
    # in-combat relation rides the instruction as its own key, because no read
    # of the chosen creature alone can answer it — engine/legality.py tests it
    # at activation and the handler again at resolution.
    if isinstance(amount, ast.PowerOfSubject):
        spec = amount.subject
        if spec.quantifier != "target":
            raise LoweringError("the power read needs a chosen creature", node=node)
        filt = spec.filter
        leftover = _restrictions_beyond(
            filt, frozenset({"card_types", "in_combat_with_source"})
        )
        if leftover or filt.card_types != ("creature",):
            raise LoweringError(
                "the target-power rewrite reads a creature, optionally in "
                "combat with the source", node=node,
            )
        stripped = dataclasses.replace(spec, filter=dataclasses.replace(
            filt, in_combat_with_source=False
        ))
        payload = {
            "bonus": bonus,
            "in_combat_with_source": filt.in_combat_with_source,
        }
        _describe_targets(payload, stripped)
        return (
            OracleInstruction("set_source_base_toughness_from_target_power", "", payload),
        )

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


_KEYWORD_GRANTS: dict[tuple[str, str], str] = {
    ("flying", "target"): "grant_target_flying_until_eot",
    ("flying", "self"): "grant_self_flying_until_eot",
    ("banding", "target"): "grant_banding_to_target",
}


def _lower_gain_keyword(node: ast.GainKeyword) -> tuple[OracleInstruction, ...]:
    # "gains **your choice of** deathtouch or lifelink" (Alchemist's Gift). A
    # choice between two effects is `choose_one` — the composition seam
    # (engine/handlers/control_flow.py) that a modal ability already uses — so
    # there is no per-keyword prompt, no new pending-choice kind, and the
    # non-interactive default is the one already stated for a mode: the first
    # printed. Lowering each alternative through this same function is what
    # keeps a keyword the engine cannot grant refusing the whole line rather
    # than being offered as an option that does nothing.
    if node.choose_one:
        alternatives = tuple(
            dataclasses.replace(node, keywords=(keyword,), choose_one=False)
            for keyword in node.keywords
        )
        modes = []
        for alternative in alternatives:
            lowered = _lower_gain_keyword(alternative)
            if len(lowered) != 1:
                raise LoweringError("a keyword choice needs one instruction per option", node=node)
            modes.append({"label": alternative.keywords[0], "instruction": lowered[0]})
        return (OracleInstruction("choose_one", "", {"modes": tuple(modes)}),)
    if node.duration.kind is None:
        # "…and that creature gains flying." (Cocoon's hatch, bound to the
        # enchanted creature by the rider that read it.) A one-shot grant with
        # no stated duration lasts as long as the object (CR 611.2c's last
        # bullet: no duration and no source dependence means it holds until
        # the object leaves) — recorded on the *creature* through the layer-6
        # write API, which is what lets it outlive the Aura that granted it.
        if _is_enchanted(node.subject):
            leftover = _restrictions_beyond(
                node.subject.filter, frozenset({"card_types", "is_enchanted"})
            )
            if leftover:
                raise LoweringError(
                    "the enchanted keyword grant cannot narrow by: "
                    + ", ".join(leftover),
                    node=node,
                )
            if len(node.keywords) != 1:
                raise LoweringError(
                    "the enchanted keyword grant takes one keyword", node=node
                )
            keyword = node.keywords[0]
            if keyword not in IMPLEMENTED_KEYWORDS:
                raise LoweringError(
                    f"granting {keyword!r} needs the keyword implemented", node=node
                )
            return (
                OracleInstruction(
                    "grant_keyword_to_attached", "", {"keyword": keyword}
                ),
            )
        reason = _durationless_reason(node.subject)
        if reason.startswith("continuous pump"):
            reason = "continuous keyword grant needs the CR 613 layers engine"
        raise LoweringError(reason, node=node)
    # "…gains forestwalk **until your next upkeep**." (Erhnam Djinn.) Every
    # grant kind below ends at the cleanup step, so lowering this duration onto
    # one would grant the keyword for the rest of the turn and take it away a
    # step early — a card doing less than it prints, silently.
    #
    # The duration became parseable when Xenic Poltergeist needed it, which is
    # the widened-gate hazard in miniature: the phrase used to fail
    # full-token consumption, so `card_hooks.CARD_LINE_INSTRUCTIONS` claimed
    # Erhnam Djinn's line and the upkeep registry expired the grant correctly.
    # Refusing here hands the line back to that hook. Deleting the hook in
    # favour of a general "until your next upkeep" grant is worth doing and is
    # not this round's work — and until it is done, refusing is the only answer
    # that does not quietly shorten the card.
    if node.duration.kind == "until_your_next_upkeep":
        raise LoweringError(
            "no keyword-grant handler expires at the granting player's next upkeep",
            node=node,
        )
    # "Creatures you control gain flying until end of turn." (Basri, Devoted
    # Paladin's −6.) A team grant locked in at resolution (CR 611.2c) — its own
    # kind, resolved over the controller's board by the handler.
    #
    # "**Permanents** you control gain hexproof and indestructible" (Heroic
    # Intervention) is the same grant over a wider board, and the width is the
    # only difference — so it is a payload key rather than a second kind. The
    # key is emitted only for the wider reading, which leaves every payload
    # written before it byte-identical, and the handler defaults to creatures.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "all"
        and node.subject.filter.card_types in ((), ("creature",))
        and node.subject.filter.controller == "you"
        and node.duration.kind in ("until_end_of_turn", "this_turn")
    ):
        leftover = _restrictions_beyond(
            node.subject.filter, frozenset({"card_types", "controller"})
        )
        if leftover:
            raise LoweringError(
                "the team keyword grant cannot narrow by: " + ", ".join(leftover),
                node=node,
            )
        for keyword in node.keywords:
            if keyword not in IMPLEMENTED_KEYWORDS:
                raise LoweringError(
                    f"granting {keyword!r} needs the keyword implemented", node=node
                )
        team_payload: dict[str, object] = {"keywords": tuple(node.keywords)}
        if not node.subject.filter.card_types:
            team_payload["every_permanent"] = True
        return (OracleInstruction("grant_team_keyword_until_eot", "", team_payload),)
    scope = "self" if _is_source(node.subject) else ("target" if _is_target(node.subject) else None)
    if scope is None:
        raise LoweringError("unsupported keyword-grant subject", node=node)
    if len(node.keywords) == 1:
        kind = _KEYWORD_GRANTS.get((node.keywords[0], scope))
        if kind is not None:
            return (OracleInstruction(kind, "", {}),)
    # Any other grant rides the generic payload pair, gated on the keyword
    # registry: `grant_keyword` puts the word into layer 6 for anything, but a
    # word whose behaviour is not built would be a grant of nothing — the same
    # silent wrongness the printed-keyword gate refuses. Several keywords in
    # one sentence ("gains hexproof and indestructible") are one instruction
    # carrying them all.
    for keyword in node.keywords:
        if _granted_keyword_name(keyword) not in IMPLEMENTED_KEYWORDS:
            raise LoweringError(
                f"granting {keyword!r} needs the keyword implemented", node=node
            )
    payload: dict[str, object] = {"keywords": tuple(node.keywords)}
    if scope == "self":
        return (OracleInstruction("grant_self_keyword_until_eot", "", payload),)
    assert isinstance(node.subject, ast.TargetSpec)
    _describe_targets(payload, node.subject)
    return (OracleInstruction("grant_target_keyword_until_eot", "", payload),)


def _granted_keyword_name(keyword: str) -> str:
    """The registry name of a granted keyword, without its argument.

    "Protection from black" is the keyword *protection* with a quality attached
    (CR 702.16a); the registry lists the ability, not every quality it can name.
    The gate compared the whole compound string, so **every** granted protection
    was refused as an unimplemented keyword — a printed one has worked since the
    keyword gate was written, which is what made the asymmetry invisible.
    """
    return "protection" if keyword.startswith("protection from ") else keyword


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


def _lower_lose_keyword(node: ast.LoseKeyword) -> tuple[OracleInstruction, ...]:
    """"It loses indestructible until end of turn." (Soul Sear, bound to the
    damage sentence's target by the pronoun rider.)

    The mirror of the targeted grant: `remove_keyword` puts the removal into
    layer 6, so it composes with grants by timestamp rather than by flag
    fights. Gated on IMPLEMENTED_KEYWORDS exactly like the grant — removing a
    word whose behaviour is not built would report a removal of nothing.
    """
    if node.duration.kind not in ("until_end_of_turn", "this_turn"):
        raise LoweringError(
            "a durationless keyword loss is a static ability, which needs the "
            "CR 613 layers engine",
            node=node,
        )
    if not _is_target(node.subject):
        raise LoweringError("no handler removes a keyword from this subject", node=node)
    for keyword in node.keywords:
        if keyword not in IMPLEMENTED_KEYWORDS:
            raise LoweringError(
                f"removing {keyword!r} needs the keyword implemented", node=node
            )
    payload: dict[str, object] = {"keywords": tuple(node.keywords)}
    assert isinstance(node.subject, ast.TargetSpec)
    _describe_targets(payload, node.subject)
    return (OracleInstruction("remove_target_keyword_until_eot", "", payload),)


def _lower_become_color(
    node: ast.BecomeColor,
    event: str | None = None,
    event_subject: object | None = None,
) -> tuple[OracleInstruction, ...]:
    """The Lace cycle, and the five Legends colour spells beside it.

    Two instructions, told apart by the *duration* rather than by the number of
    targets: an indefinite change writes the permanent colour channel and a
    turn-long one writes the until-end-of-turn channel the cleanup step sweeps,
    and layer 5 reads both (`engine/layer_bridge.py`). One handler covers one
    target or several, since a single chosen slot is a list of one.
    """
    if node.duration.kind in ("until_end_of_turn", "this_turn"):
        if not isinstance(node.subject, ast.TargetSpec) or not node.subject.targeted:
            raise LoweringError(
                "no handler recolours an object nobody targeted", node=node
            )
        payload: dict[str, object] = {"target_color": node.color}
        if _names_several_targets(node.subject):
            _describe_several_targets(payload, node.subject)
        return (OracleInstruction("recolor_targets_until_eot", "", payload),)
    if node.duration.kind is not None:
        raise LoweringError(
            f"no handler recolours for {node.duration.kind!r}", node=node
        )
    if not isinstance(node.subject, ast.TargetSpec) or node.subject.quantifier != "target":
        # "…**that creature** becomes green" (Aisling Leprechaun). Nobody chose
        # it, so there is no target — but a block trigger *bound* it, and under
        # one of those events the pronoun names exactly one creature. The
        # binding travels as payload rather than as a second instruction kind:
        # which object an effect acts on is not a different effect.
        if (
            binds_block_pair(event, event_subject)
            and isinstance(node.subject, ast.TargetSpec)
            and node.subject.quantifier == "that"
        ):
            return (
                OracleInstruction(
                    "recolor_target_from_text", "",
                    {
                        "target_color": node.color,
                        SUBJECT_FROM_TRIGGER: BLOCK_PAIR_SUBJECT,
                    },
                ),
            )
        raise LoweringError("no handler for recolouring a non-targeted object", node=node)
    # Deliberately *not* described for engine/targeting.py. The Lace cycle
    # targets "spell or permanent" — a union of a stack object and a
    # battlefield object that the `targets` vocabulary cannot express. Emitting
    # the generic object shape would derive "permanent" and drop spells on the
    # stack from the picker, so the description is omitted and legality.py
    # keeps answering `spell_or_permanent` until the vocabulary grows.
    return (OracleInstruction("recolor_target_from_text", "", {"target_color": node.color}),)


def _lower_change_text(node: ast.ChangeText) -> tuple[OracleInstruction, ...]:
    """``Change the text of target spell or permanent …`` (CR 612).

    No ``targets`` description is emitted, for the reason the Lace cycle
    established: the vocabulary has no way to say "a spell on the stack *or* a
    permanent", so describing it at all would drop one of the two zones from the
    picker. ``engine/legality.py`` keeps answering ``spell_or_permanent``.
    """
    if not _is_target(node.subject):
        raise LoweringError("a text change has to name what it changes", node=node)
    return (OracleInstruction("mark_text_modified", "", {"mode": node.mode}),)


#: Durations a gained type may carry. "Permanently" is the absent kind, which
#: is what Ashnod's Transmogrant prints — the creature stays an artifact long
#: after the Transmogrant has been sacrificed.
_GAINED_TYPE_DURATIONS = frozenset({None, "until_end_of_turn", "until_your_next_upkeep"})


def _lower_gain_type(node: ast.GainType) -> tuple[OracleInstruction, ...]:
    """Ashnod's Transmogrant / Xenic Poltergeist.

    The subject must be a chosen target or the pronoun bound by an earlier
    sentence of the same effect: the handler adds the record to *one* permanent,
    and a quantified subject would name a set it cannot reach.
    """
    if node.duration.kind not in _GAINED_TYPE_DURATIONS:
        raise LoweringError(
            f"no handler holds a gained type for {node.duration.kind}", node=node
        )
    payload: dict[str, object] = {
        "card_types": list(node.card_types),
        "duration": node.duration.kind or "permanent",
        "pt_from_mana_value": bool(node.pt_from_mana_value),
    }
    if isinstance(node.subject, ast.TargetSpec) and node.subject.quantifier in ("target", "that"):
        if node.subject.quantifier == "target":
            _describe_targets(payload, node.subject)
        return (OracleInstruction("gain_type", "", payload),)
    raise LoweringError("a gained type needs a single named permanent", node=node)
