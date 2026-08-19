"""Lowering what a permanent is: P/T, keywords, colour, text, counters.

Pump and base-P/T setting (CR 613 layer 7), keyword grants, colour and printed-
text changes, and counters — including the per-death repetition, whose exact
subject is compared for equality rather than pattern-matched, so a card with a
*narrower* subject cannot silently take the same handler.

A continuous effect with no duration is refused here rather than lowered, and
`_durationless_reason` in `_common` says why per subject: the refusal names
what is missing instead of producing an effect that never ends.
"""

import dataclasses

from ...oracle_types import OracleInstruction
from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS
from .. import ast
from ..errors import LoweringError
from ..vocabulary import IMPLEMENTED_KEYWORDS
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
    raise LoweringError("only a count or a maximum can define X here", node=node)


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
        if not isinstance(node.x_definition, ast.CountOf):
            raise LoweringError("only a count can define X here", node=node)
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
            "x_from_count": count_spec(node.x_definition.filter, node),
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
        reason = _durationless_reason(node.subject)
        if reason.startswith("continuous pump"):
            reason = "continuous keyword grant needs the CR 613 layers engine"
        raise LoweringError(reason, node=node)
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


# The ObjectFilter fields the loyalty-counter picker reads. Only what the pool
# actually prints ("a Liliana planeswalker you control"): a filter with no card
# behind it is untested by construction, and `_restrictions_beyond` turns every
# other field — present today or added to the AST later — into a refusal rather
# than a silently wider effect.
_LOYALTY_PICKER_HONOURED = frozenset({"card_types", "subtypes", "controller"})


def _lower_put_counter(node: ast.PutCounter) -> tuple[OracleInstruction, ...]:
    # "Put a loyalty counter on Garruk." (Garruk, Unleashed's −2.) The source's
    # own loyalty lives on the permanent (metadata["loyalty_counters"],
    # CR 306.5c); a *chosen* permanent's is the same key reached through the
    # picker below.
    if node.counter == "loyalty":
        if not isinstance(node.count, ast.Fixed) or node.up_to:
            raise LoweringError("variable loyalty-counter counts have no handler", node=node)
        if _is_source(node.subject):
            return (
                OracleInstruction("add_loyalty_counters", "", {"count": node.count.value}),
            )
        # "Put a loyalty counter on a Liliana planeswalker you control."
        # (Liliana's Scrounger.) A noun phrase with no "target" in it: nothing
        # was chosen when the ability went on the stack, so the controller picks
        # at resolution out of what the phrase names then — the same split
        # `_lower_sacrifice` makes between "sacrifice this creature" and
        # "sacrifice a creature".
        if (
            isinstance(node.subject, ast.TargetSpec)
            and not node.subject.targeted
            and node.subject.quantifier not in ("all", "each")
            and node.subject.count == 1
        ):
            filt = node.subject.filter
            # Two gates, because they catch different halves of the same bug.
            #
            # `_restrictions_beyond` reads the **AST**, so a restriction
            # `to_payload` does not emit at all cannot be dropped on the floor:
            # "a planeswalker card **in your graveyard**" and "an **enchanted**
            # planeswalker" both reduce to the same payload as the plain phrase,
            # and without this they compile into a battlefield picker. The
            # honoured set is only what the pool prints, per round 43's rule that
            # a filter with no card behind it is untested by construction.
            leftovers = _restrictions_beyond(filt, _LOYALTY_PICKER_HONOURED)
            if leftovers:
                raise LoweringError(
                    f"the loyalty-counter picker does not honour {leftovers[0]!r}",
                    node=node,
                )
            if not filt.card_types:
                raise LoweringError(
                    "a loyalty-counter picker with no card type would offer "
                    "every permanent",
                    node=node,
                )
            described = filt.to_payload()
            # And the load-bearing gate CLAUDE.md names (round 34): a key
            # `subject_matches` cannot test is one the picker would silently
            # ignore, which would offer *every* planeswalker where the card names
            # one subtype. Kept beside the first so widening the honoured set
            # above can never outrun the matcher.
            if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
                raise LoweringError(
                    "the loyalty-counter picker cannot test this restriction",
                    node=node,
                )
            return (
                OracleInstruction(
                    "add_loyalty_counters_to_chosen", "",
                    {"count": node.count.value, "filter": described},
                ),
            )
        raise LoweringError(
            "loyalty counters land on the ability's own source or on one "
            "permanent its controller chooses",
            node=node,
        )
    if node.counter != "+1/+1" or node.up_to:
        raise LoweringError(f"no handler for {node.counter} counters", node=node)
    if not isinstance(node.count, ast.Fixed) or node.count.value != 1:
        raise LoweringError("variable counter counts have no handler", node=node)
    if _is_source(node.subject):
        return (
            OracleInstruction("add_counter_to_self", "", {"power": 1, "toughness": 1}),
        )
    if _names_several_targets(node.subject):
        # "Put a +1/+1 counter on each of up to two target creatures" (Basri's
        # Aegis, Basri's Acolyte). Same instruction as the single-target form —
        # the effect is identical and only the number of targets differs, which
        # is payload — but described with `_describe_several_targets`, the
        # opt-in that tells the handler to resolve a list and the picker to
        # collect up to that many.
        assert isinstance(node.subject, ast.TargetSpec)
        several: dict[str, object] = {"power": 1, "toughness": 1}
        _describe_several_targets(several, node.subject)
        return (OracleInstruction("add_counter_to_target", "", several),)
    if _is_target(node.subject):
        # "Put a +1/+1 counter on target creature [you control]." The kind
        # predates this lowering: Dwarven Weaponsmith's hook has always emitted
        # it, so the grammar joins the same handler rather than minting a
        # second name for the same effect.
        assert isinstance(node.subject, ast.TargetSpec)
        payload: dict[str, object] = {"power": 1, "toughness": 1}
        # "…, then double the number of +1/+1 counters on that creature."
        # (Invigorating Surge.) Payload on the same instruction, because the
        # doubling is about the creature this one just chose — a second
        # instruction would have to re-find it, and "that creature" names no
        # target of its own. Emitted only when printed, so every payload
        # written before it is byte-identical.
        if node.then_double:
            payload["then_double"] = True
        _describe_targets(payload, node.subject)
        return (OracleInstruction("add_counter_to_target", "", payload),)
    if isinstance(node.subject, ast.TargetSpec) and node.subject.quantifier in (
        "all",
        "each",
    ):
        # "Put a +1/+1 counter on each creature you control." Only the
        # own-side creature sweep has a handler; a wider scope refuses.
        filt = node.subject.filter
        if filt.card_types != ("creature",) or filt.controller != "you":
            raise LoweringError("counters on a scope no handler sweeps", node=node)
        return (
            OracleInstruction(
                "add_counter_to_each_you_control", "", {"power": 1, "toughness": 1}
            ),
        )
    raise LoweringError("counters on a non-source subject", node=node)


# Counter placements repeated once per creature that died this turn, keyed by
# the counter's printed name — the only thing that differs between the two
# cards written this way, and what decides which handler runs. Both handlers
# read the death count from the trigger's own context rather than from the
# payload, so the payloads here are the legacy rules' literals and nothing
# more.
_PER_DEATH_COUNTERS: dict[str, tuple[str, dict[str, object]]] = {
    # Scavenging Ghoul — regeneration fuel, spent by its own activated ability.
    "corpse": ("add_corpse_counters_for_each_creature_died", {}),
    # Khabál Ghoul — P/T counters.
    "+1/+1": ("add_plus1_counters_for_each_creature_died", {"power": 1, "toughness": 1}),
}

# The exact subject both handlers act on. Compared for equality rather than
# probed field by field, so a filter field added to the AST later refuses by
# default instead of being ignored by a lowering written before it existed.
_PER_DEATH_SUBJECT = ast.TargetSpec(
    "this", ast.ObjectFilter(card_types=("creature",), is_source=True)
)

# Both handlers count *every* creature that died, with no narrowing available
# to them, so any filtered set has to refuse rather than over-count.
_ANY_CREATURE_DIED = ast.DiedThisTurn(ast.ObjectFilter(card_types=("creature",)))


def _lower_remove_counter(node: ast.RemoveCounter) -> tuple[OracleInstruction, ...]:
    """``Remove a <kind> counter from this <permanent>`` (Armageddon Clock).

    The counter's name is payload — it is the accumulating side's payload too
    (``upkeep_put_counter_on_self``), so the pair is one template rather than a
    card. What is *not* payload is the subject or the number:
    ``remove_counter_from_self`` reads the ability's own source and decrements by
    one, so anything else refuses rather than compiling onto a handler that
    would quietly do that instead.
    """
    # "Remove two loyalty counters from each planeswalker." (Pestilent Haze's
    # second mode.) A sweep, not a choice: every planeswalker on every
    # battlefield loses that many, and CR 704.5i collects the ones that hit
    # zero. Only the loyalty/planeswalker pairing has a handler — loyalty is
    # the one counter kind whose storage the handler knows how to reach.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "each"
        and node.counter == "loyalty"
    ):
        if node.subject.filter.card_types != ("planeswalker",):
            raise LoweringError(
                "the loyalty sweep removes from planeswalkers alone", node=node
            )
        amount = _amount_payload(node.count)
        if not isinstance(amount, int) or amount <= 0:
            raise LoweringError("the loyalty sweep takes a fixed count", node=node)
        return (
            OracleInstruction(
                "remove_loyalty_from_each_planeswalker", "", {"amount": amount}
            ),
        )
    if not _is_source(node.subject):
        raise LoweringError(
            "the only counter-removal handler reads the ability's own source", node=node
        )
    if _amount_payload(node.count) != 1:
        raise LoweringError("no handler removes more than one counter at a time", node=node)
    return (
        OracleInstruction("remove_counter_from_self", "", {"counter": node.counter}),
    )


def _lower_for_each(node: ast.ForEach) -> tuple[OracleInstruction, ...]:
    """"…put a <kind> counter on this creature for each creature that died this
    turn." (Scavenging Ghoul, Khabál Ghoul.)

    The legacy registry needed a whole-sentence substring rule per card, and the
    +1/+1 one carries a comment saying it must out-rank the plain "put a +1/+1
    counter on this creature" rule — which sits 96,500 order slots away, because
    the two rules are unrelated except that one is a prefix of the other. Losing
    that race would drop the per-death scaling and put down a single counter.
    Here the "for each …" clause is a node, so the two shapes are simply
    different ASTs and there is no race to lose.

    Everything else refuses, because neither handler reads anything from its
    payload: the subject, the multiplier and the counted set are all fixed in
    the handler's own source, so a clause differing in any of them would be
    executed as if it had not.
    """
    if node.iterator != _ANY_CREATURE_DIED:
        raise LoweringError("no handler repeats an effect over this set", node=node)
    placement = node.effect
    if not isinstance(placement, ast.PutCounter):
        raise LoweringError("no handler repeats this effect per death", node=node)
    if placement.subject != _PER_DEATH_SUBJECT:
        raise LoweringError(
            "the per-death counter handlers only ever reach their own source", node=node
        )
    if placement.up_to or placement.count != ast.Fixed(1):
        raise LoweringError("no handler places more than one counter per death", node=node)
    found = _PER_DEATH_COUNTERS.get(placement.counter)
    if found is None:
        raise LoweringError(
            f"no handler places {placement.counter!r} counters per death", node=node
        )
    kind, payload = found
    return (OracleInstruction(kind, "", dict(payload)),)


def _lower_become_color(node: ast.BecomeColor) -> tuple[OracleInstruction, ...]:
    """The Lace cycle. `recolor_target_from_text` re-reads the card's own text
    to find the colour, so the payload only names it; the subject must still be
    a chosen target, since the handler recolours what was targeted."""
    if not isinstance(node.subject, ast.TargetSpec) or node.subject.quantifier != "target":
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
