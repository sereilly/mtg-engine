"""Lowering counters: putting, removing, and repeating per death (CR 122).

A counter is a marker placed on an object (CR 122.1); the P/T it may carry is
a consequence the layers compute, not the effect itself, which is why this is
its own family on the lowering side — it split out of `characteristics.py`
when the two together crossed the thousand-line cap. The per-death repetition
compares its exact subject for equality rather than pattern-matching it, so a
card with a *narrower* subject cannot silently take the same handler.
"""

import dataclasses

from ...oracle_types import OracleInstruction
from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS, object_only_filter
from .. import ast
from ..errors import LoweringError
from ..phrases import PAIR_ORDINALS, is_pt_counter
from ._common import (
    PRIMARY_TARGET_ROLE,
    _amount_payload,
    _describe_several_targets,
    _describe_targets,
    _filter_payload,
    _is_enchanted,
    _is_source,
    _is_target,
    _names_several_targets,
    _restrictions_beyond,
    describe_target_roles,
)
from ._events import (
    _BOUND_OBJECT_DELAYED_EVENTS,
    CHOSEN_PERMANENT,
    OTHER_CHOSEN_PERMANENT,
    EVENT_SUBJECT_CONTROLLER,
    _DAMAGED_PLAYER_EVENTS,
    _EVENT_SUBJECT_OBJECTS,
    _RECORDED_PERMANENTS,
)


#: Whose creature an *unchosen* counter placement lands on, and the word the
#: ``choose_permanent`` prompt names that seat by. "a creature **you** control"
#: is the effect's own controller; "a creature **they** control" is the seat the
#: firing event was about, which is the only reading of "they" a toll's price
#: can have — the offer was made to that player and the price comes out of their
#: own board. A controller word outside this table refuses, because a prompt
#: armed on the wrong seat is a player paying somebody else's price.
_COUNTER_CHOOSERS: dict[str, str] = {
    "you": "you",
    "that_player": EVENT_SUBJECT_CONTROLLER,
}


# The ObjectFilter fields the loyalty-counter picker reads. Only what the pool
# actually prints ("a Liliana planeswalker you control"): a filter with no card
# behind it is untested by construction, and `_restrictions_beyond` turns every
# other field — present today or added to the AST later — into a refusal rather
# than a silently wider effect.
_LOYALTY_PICKER_HONOURED = frozenset({"card_types", "subtypes", "controller"})

#: The scratchpad key a granted CR 615 shield is recorded under
#: (``handlers/prevention.PREVENTION_SHIELD_RESULT``), spelled here rather than
#: imported because a lowering may not reach into the handlers. The two are held
#: together by ``lowering/_records._PRODUCES``, which is what the ``produced``
#: check below reads — a key that stopped being written would take the gate with
#: it rather than leaving a back-reference pointing at nothing.
PREVENTION_SHIELD_RECORD = "prevention_shield"


def _amount_value(amount) -> int:
    """A fixed Amount as a plain int, for a payload that carries a number."""
    return amount.value if isinstance(amount, ast.Fixed) else 0


def _lower_put_counter(
    node: ast.PutCounter,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    if node.distributed:
        # "Distribute X +1/+1 counters among any number of target creatures."
        # (Spoils of War.) CR 601.2d's other half — the caster announces the
        # division as part of casting, exactly as a divided damage spell's
        # caster does, so the shares travel on the same ``divided_targets`` list
        # and this carries the same ``divided`` target description. Ahead of
        # every branch below, all of which describe one permanent.
        if node.up_to or node.then_double or node.cap is not None:
            raise LoweringError(
                "a distributed placement carries no rider", node=node
            )
        filt = node.subject.filter
        if _restrictions_beyond(filt, frozenset({"card_types"})) or (
            filt.card_types != ("creature",)
        ):
            raise LoweringError(
                "the distributed counters land on creatures", node=node
            )
        if isinstance(node.count, ast.Fixed):
            placed: int | str = node.count.value
        elif isinstance(node.count, ast.Var):
            placed = node.count.name
        else:
            raise LoweringError(
                "a distributed placement counts a fixed or variable number",
                node=node,
            )
        return (
            OracleInstruction("add_counter_to_target", "", {
                "counter": node.counter,
                "count": placed,
                "targets": {
                    "quantifier": "divided",
                    "kind": "divided",
                    "division": "chosen",
                    "filter": {"type_filter": "creature"},
                },
            }),
        )
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
    if not is_pt_counter(node.counter) and not node.up_to and _is_source(node.subject):
        if not isinstance(node.count, ast.Fixed):
            raise LoweringError("a named counter is placed a fixed number at a time", node=node)
        return (
            OracleInstruction(
                "add_named_counter_to_self", "",
                {"counter": node.counter, "count": node.count.value},
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
                if set(role["filter"]) - TESTABLE_SUBJECT_FILTER_KEYS:
                    raise LoweringError(
                        "a named-counter target role cannot test this "
                        "restriction", node=node,
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
        if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
            raise LoweringError(
                "the named-counter target cannot test this restriction", node=node
            )
        return (OracleInstruction("add_named_counter_to_target", "", payload),)
    # "Put up to X +1/+0 counters on this creature. This ability can't cause the
    # total number of +1/+0 counters on this creature to be greater than N."
    # (Clockwork Beast prints seven, Clockwork Avian four.) The cap is payload,
    # which is the whole reason this is a production: the two cards differ by a
    # number, and the number used to be baked into a card-name-keyed hook whose
    # key spelled out "seven".
    #
    # The cap is **required**. Without it the ability would put counters on
    # without limit, which is a card doing more than it prints — so a bare
    # "put up to X +1/+0 counters" keeps refusing.
    if node.counter == "+1/+0" and _is_source(node.subject) and node.cap is not None:
        return (
            OracleInstruction(
                "add_power_counters_to_self", "",
                {
                    "amount": "x" if isinstance(node.count, ast.Var) else _amount_value(node.count),
                    "cap": node.cap,
                    "up_to": bool(node.up_to),
                },
            ),
        )
    # A CR 122.1a counter on the permanent this Aura enchants (Spirit Shackle's
    # -0/-2, Unstable Mutation's -1/-1). No target is chosen — an Aura's effect
    # on its own host names one permanent — so it is its own handler beside
    # `untap_enchanted_creature` and `grant_regeneration_to_enchanted_creature`,
    # and the counter's *name* is payload: CR 122.1a reads the numbers off the
    # name, so a card printing any other pair needs nothing here.
    # "…put a -1/-1 counter on **that creature**." (Unstable Mutation;
    # Takklemaggot prints the identical sentence with a -0/-1 pair.) The mirror
    # of the removal branch far below, and bound the same way: "that creature"
    # restates an object something earlier in the line bound, and the only
    # trigger head in the pool that binds one is `upkeep_enchanted_controller`
    # — its sentence is *about* the enchanted creature, which is exactly what
    # `add_pt_counters_to_attached` reads off the source's own attachment. Under
    # any other event the words name a creature nobody recorded, so the line
    # keeps refusing; and the dispatch registry keys on the ability's whole
    # instruction, so a nested occurrence (event is None here) refuses too.
    #
    # It falls through to the `_is_enchanted` branch below, which is the same
    # placement under the printed spelling "on enchanted creature" — one
    # instruction for both wordings, with the CR 122.1a pair as payload. This is
    # what `add_minus1_counter_to_enchanted` used to be: an instruction kind
    # with the counter baked into its *name*, reached by a card-name hook that
    # spelled out "-1/-1", so Takklemaggot's one-word-different sentence had
    # nowhere to go.
    if (
        is_pt_counter(node.counter)
        and not node.up_to
        and isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
        and event == "upkeep_enchanted_controller"
    ):
        if node.subject.filter != ast.ObjectFilter(card_types=("creature",)):
            raise LoweringError(
                "the attached counter placement reads the enchanted creature alone",
                node=node,
            )
        if not isinstance(node.count, ast.Fixed):
            raise LoweringError(
                "a counter on the enchanted permanent is placed a fixed "
                "number at a time",
                node=node,
            )
        return (
            OracleInstruction(
                "add_pt_counters_to_attached", "",
                {"counter": node.counter, "count": node.count.value},
            ),
        )
    if is_pt_counter(node.counter) and not node.up_to and _is_enchanted(node.subject):
        if not isinstance(node.count, ast.Fixed):
            raise LoweringError(
                "a counter on the enchanted permanent is placed a fixed "
                "number at a time",
                node=node,
            )
        return (
            OracleInstruction(
                "add_pt_counters_to_attached", "",
                {"counter": node.counter, "count": node.count.value},
            ),
        )
    # "That player chooses and sacrifices one of those creatures. Put a -1/-1
    # counter on **the other**." (Retribution.) The member of the chosen pair
    # the sacrifice did not take, recorded by the pick that took the other one
    # — the only step holding both halves.
    #
    # Read before the block-pair reading of the same printed word, and
    # producer-gated so the two cannot collide: "the other" under a trigger
    # that bound a blocking pair still means that pair, because no step of such
    # an ability records a chosen remainder.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "other"
        and not node.subject.targeted
        and OTHER_CHOSEN_PERMANENT in produced
    ):
        if _restrictions_beyond(node.subject.filter, frozenset({"card_types"})):
            raise LoweringError(
                "\"the other\" carries no narrowing the placement could honour",
                node=node,
            )
        if node.up_to or node.then_double or node.cap is not None:
            raise LoweringError(
                "a counter on the other half of a chosen pair carries no rider",
                node=node,
            )
        if not isinstance(node.count, ast.Fixed):
            raise LoweringError(
                "a counter on the other half of a chosen pair is placed a fixed "
                "number at a time",
                node=node,
            )
        other_payload: dict[str, object] = {
            "counter": node.counter, "permanents_from": OTHER_CHOSEN_PERMANENT,
        }
        if node.count.value != 1:
            other_payload["count"] = node.count.value
        return (OracleInstruction("add_counter_to_target", "", other_payload),)
    # "Return target creature card from your graveyard to the battlefield. Put
    # a +2/+2 counter on **that creature** …" (Soul Exchange.) The bound object
    # is a permanent an earlier step of this effect *created*, not the ability's
    # target — the target is a card in a graveyard, and a counter on it would
    # land on nothing. So the placement reads the record that step wrote, the
    # same ``permanents_from`` reading the grant one family over already makes.
    #
    # Read before the targeted branch below and before the "+1/+1 only" gate
    # further down, both of which are about a *chosen* creature: with nothing
    # recorded the words keep their old reading and refuse there, naming what is
    # missing.
    if (
        is_pt_counter(node.counter)
        and not node.up_to
        and isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
        and not node.subject.targeted
        and (produced & _RECORDED_PERMANENTS)
    ):
        if _restrictions_beyond(node.subject.filter, frozenset({"card_types"})):
            raise LoweringError(
                "a bound object carries no narrowing the placement could "
                "honour", node=node,
            )
        recorded = tuple(sorted(produced & _RECORDED_PERMANENTS))
        if len(recorded) != 1:
            raise LoweringError(
                "\"that creature\" is ambiguous: several earlier steps "
                "recorded objects", node=node,
            )
        if not isinstance(node.count, ast.Fixed):
            raise LoweringError(
                "a counter on a bound object is placed a fixed number at a "
                "time", node=node,
            )
        bound_payload: dict[str, object] = {
            "counter": node.counter, "permanents_from": recorded[0],
        }
        if node.count.value != 1:
            bound_payload["count"] = node.count.value
        return (OracleInstruction("add_counter_to_target", "", bound_payload),)
    # "Put a **-0/-1** counter on target creature blocking or blocked by this
    # creature." (Lesser Werewolf.) The same placement as the +1/+1 branch far
    # below — one counter, on one chosen creature — differing only in the CR
    # 122.1a pair the counter's *name* carries, which `place_pt_counters` reads.
    # So it is that branch's instruction with the kind as payload, and a card
    # printing any other pair needs nothing here.
    #
    # It is read above the +1/+1 gate rather than folded into that branch so
    # that every payload written before it stays byte-identical: the +1/+1 form
    # keeps emitting `power`/`toughness` and no `counter` key, and the handler
    # defaults to the kind those two have always meant.
    #
    # The in-combat relation is the same one Sentinel's rewrite carries and is
    # carried the same way — stripped from the target description, because no
    # read of the chosen creature alone can answer it, and re-asked by
    # `legality.py` at activation and by the handler at resolution.
    if (
        is_pt_counter(node.counter)
        and node.counter != "+1/+1"
        and not node.up_to
        and _is_target(node.subject)
        and not _names_several_targets(node.subject)
    ):
        assert isinstance(node.subject, ast.TargetSpec)
        # "Put **X** +0/+1 counters on target creature, where X is that
        # creature's mana value." (Living Armor.) The number is payload on the
        # same instruction rather than a second kind: what changes is how many
        # of one counter go on one creature, and the where-clause behind the X
        # is resolved at the single dispatch point like every other one. A
        # printed count of 1 keeps emitting no ``count`` key at all, so every
        # payload written before this stays byte-identical.
        if isinstance(node.count, ast.Fixed):
            placed: int | str = node.count.value
        elif isinstance(node.count, ast.Var):
            placed = node.count.name
        else:
            raise LoweringError(
                "a counter of this kind is placed a fixed or variable number "
                "at a time", node=node,
            )
        filt = node.subject.filter
        leftover = _restrictions_beyond(
            filt, frozenset({"card_types", "in_combat_with_source"})
        )
        if leftover or filt.card_types != ("creature",):
            raise LoweringError(
                "the counter lands on a creature, optionally one in combat "
                "with the source",
                node=node,
            )
        stripped = dataclasses.replace(node.subject, filter=dataclasses.replace(
            filt, in_combat_with_source=False
        ))
        payload: dict[str, object] = {"counter": node.counter}
        if placed != 1:
            payload["count"] = placed
        if filt.in_combat_with_source:
            payload["in_combat_with_source"] = True
        _describe_targets(payload, stripped)
        return (OracleInstruction("add_counter_to_target", "", payload),)
    # "Put **X +0/+1** counters on this creature." (Necropolis.) The source's
    # own twin of the targeted branch above, and payload for the same reasons:
    # which CR 122.1a pair the counter names, and how many of it, are the whole
    # of what differs. A printed +1/+1 keeps the branch below it byte for byte,
    # so nothing written before this changes shape.
    if (
        is_pt_counter(node.counter)
        and node.counter != "+1/+1"
        and not node.up_to
        and _is_source(node.subject)
    ):
        if isinstance(node.count, ast.Fixed):
            placed_on_self: int | str = node.count.value
        elif isinstance(node.count, ast.Var):
            placed_on_self = node.count.name
        else:
            raise LoweringError(
                "a counter on the source is placed a fixed or variable number "
                "at a time", node=node,
            )
        payload: dict[str, object] = {"counter": node.counter}
        if placed_on_self != 1:
            payload["count"] = placed_on_self
        return (OracleInstruction("add_counter_to_self", "", payload),)
    # "…put a +0/+1 counter on **that creature** for each 1 damage prevented
    # this way." (Sacred Boon.) A CR 122.1a counter on the object an earlier
    # step of the same effect shielded, one per point that shield absorbed. Read
    # before the "+1/+1 only" refusal below, which was written for a printed
    # count and would report the pair as unimplemented.
    #
    # ``produced`` is the whole gate on the back-reference: the words "this way"
    # name what an earlier step recorded, and with no such step they name
    # nothing — a zero the card never printed.
    if (
        is_pt_counter(node.counter)
        and not node.up_to
        and isinstance(node.count, ast.ThatMuch)
        and node.count.source == PREVENTION_SHIELD_RECORD
    ):
        if PREVENTION_SHIELD_RECORD not in produced:
            raise LoweringError(
                "no earlier step of this effect armed a shield to count",
                node=node,
            )
        if (
            not isinstance(node.subject, ast.TargetSpec)
            or node.subject.quantifier != "that"
            or _restrictions_beyond(node.subject.filter, frozenset({"card_types"}))
        ):
            raise LoweringError(
                "the counters land on the creature the shield was armed on",
                node=node,
            )
        return (
            OracleInstruction(
                "add_pt_counters_per_damage_prevented", "",
                {"counter": node.counter},
            ),
        )
    # "Put a paralyzation counter on **each creature blocking or blocked by
    # this creature**." (Dread Wight.) The CR 122.1 marker of the two branches
    # above, on a set named by a combat relation to the ability's own source
    # (CR 509) rather than by any characteristic its members carry — the same
    # subject `destroy_creatures_in_combat_with_source` (Abu Ja'far) and
    # `grant_keyword_to_creatures_in_combat_with_source` (Spitting Slug) act on,
    # so it is the third member of that family rather than a shape of its own.
    #
    # Nothing is described for a picker: the relation is not a filter any
    # candidate answers, and there is no choice to make. The gates are the two
    # its siblings use — a narrowing beyond the card type would be carried and
    # dropped, which would mark a strictly larger set than the card names.
    #
    # **The counter's kind is payload here, P/T pair included**: "put a -0/-2
    # counter on each creature blocking or blocked by this creature" (Greater
    # Werewolf) is Dread Wight's sentence with a CR 122.1a counter in it, and
    # nothing about the *subject* changes. The gate used to read
    # `not is_pt_counter`, which made the pair a different effect and refused
    # the card; the two placements differ only in what
    # ``named_counters.add_counters`` does with the word, which is one store's
    # business rather than the grammar's.
    if (
        not node.up_to
        and isinstance(node.subject, ast.TargetSpec)
        and not node.subject.targeted
        and node.subject.quantifier in ("all", "each")
        and node.subject.filter.in_combat_with_source
    ):
        leftover = _restrictions_beyond(
            node.subject.filter,
            frozenset({"card_types", "in_combat_with_source"}),
        )
        if leftover or node.subject.filter.card_types != ("creature",):
            raise LoweringError(
                "the combat-pair counter placement reads creatures in combat "
                "with its source and nothing narrower",
                node=node,
            )
        if not isinstance(node.count, ast.Fixed):
            raise LoweringError(
                "a named counter is placed a fixed number at a time", node=node
            )
        return (
            OracleInstruction(
                "add_named_counter_to_creatures_in_combat_with_source", "",
                {"counter": node.counter, "count": node.count.value},
            ),
        )
    # "…unless the player **puts a -1/-1 counter on a creature they control**"
    # (Thelon's Chant, Tourach's Chant.) A CR 122.1a counter on a creature
    # nobody targeted and nobody named: the sentence says only *whose*, so the
    # seat it names picks one while the effect resolves (CR 608.2d).
    #
    # Two steps, the pairing ``choose_permanent`` + a step reading its answer
    # that ``lowering/control_changes.py`` already makes for Preacher: the pick
    # may have to stop and ask, and a handler that stops cannot also place the
    # counter. Refused where the phrase names no seat at all — "put a counter on
    # a creature" with no controller word is every creature on the table, and a
    # prompt listing them is a choice the card never offered.
    if (
        is_pt_counter(node.counter)
        and not node.up_to
        and isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "a"
        and not node.subject.targeted
        and node.subject.filter.controller in _COUNTER_CHOOSERS
    ):
        if _restrictions_beyond(
            node.subject.filter, frozenset({"card_types", "controller"})
        ):
            raise LoweringError(
                "the chosen counter placement reads a seat's own permanents "
                "and nothing narrower",
                node=node,
            )
        if not isinstance(node.count, ast.Fixed) or node.count.value != 1:
            raise LoweringError(
                "a chosen counter placement places one counter", node=node
            )
        chooser = _COUNTER_CHOOSERS[node.subject.filter.controller]
        described = _filter_payload(
            dataclasses.replace(node.subject.filter, controller=None)
        )
        return (
            OracleInstruction(
                "choose_permanent", "",
                {
                    "result_key": CHOSEN_PERMANENT,
                    "chooser": chooser,
                    # The candidates come off the *chooser's* own battlefield,
                    # which is what "they control" says. Naming the seat twice —
                    # once to ask and once to draw from — is how a three-seat
                    # game ends up asking one player about another's creatures.
                    "controlled_by": "chooser",
                    "filter": described,
                    "prompt": f"Choose a creature to put a {node.counter} counter on.",
                },
            ),
            OracleInstruction(
                "add_counter_to_target", "",
                {"counter": node.counter, "permanents_from": CHOSEN_PERMANENT},
            ),
        )
    # "…at the beginning of each of your draw steps, put a -1/-1 counter on
    # **that creature**." (Giant Oyster.) The object the *creating* ability
    # bound (CR 603.7c), named by id in the delayed trigger's context — never a
    # choice, so nothing is described for a picker. Its own kind beside the
    # targeted placement for ``destroy_bound_permanent``'s reason, and admitted
    # only under an event whose fire site records an object: everywhere else
    # "that" has no referent and the counter would land on whatever the
    # resolution context happened to hold.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
        and event in _BOUND_OBJECT_DELAYED_EVENTS
    ):
        if node.up_to or node.then_double:
            raise LoweringError(
                "a bound placement carries no rider", node=node
            )
        if not is_pt_counter(node.counter):
            # ``Game.place_pt_counters`` derives the P/T from the counter's own
            # name (CR 122.1a) and has nowhere to put a counter that has none.
            # Refused rather than compiled onto it, which would raise mid-
            # resolution.
            raise LoweringError(
                f"no handler puts a {node.counter} counter on a bound object",
                node=node,
            )
        if not isinstance(node.count, ast.Fixed) or node.count.value < 1:
            raise LoweringError(
                "a bound placement counts a fixed number", node=node
            )
        return (
            OracleInstruction("add_counter_to_bound_permanent", "", {
                "counter": node.counter,
                "count": node.count.value,
                **_filter_payload(node.subject.filter),
            }),
        )
    if node.counter != "+1/+1" or node.up_to:
        raise LoweringError(f"no handler for {node.counter} counters", node=node)
    if isinstance(node.count, ast.ThatMuch) and _is_source(node.subject):
        # "…put **that many** +1/+1 counters on this creature." (Tetravus.) The
        # number is the one the step before it recorded, so it rides the payload
        # as the same back-reference key the token maker's "that many" reads —
        # one phrase, one meaning, wherever in a sentence it appears.
        return (
            OracleInstruction(
                "add_counter_to_self", "",
                {"power": 1, "toughness": 1, "count": "trigger_count"},
            ),
        )
    if not isinstance(node.count, ast.Fixed) or node.count.value != 1:
        raise LoweringError("variable counter counts have no handler", node=node)
    if _is_source(node.subject):
        return (
            OracleInstruction("add_counter_to_self", "", {"power": 1, "toughness": 1}),
        )
    # "…put a +1/+1 counter on **the first** creature." (Infinite Authority.)
    # One member of the pair a block trigger bound, named by position. Nothing
    # is chosen: the ids were frozen when the earlier step of this same effect
    # armed the destruction, and `produced` is what proves that step ran — the
    # phrase names nothing on its own, and an unbound pair member would send the
    # counter to whatever the stack item happened to be pointing at.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier in PAIR_ORDINALS
    ):
        if node.subject.quantifier != "first":
            # "the other creature" under this producer is the one the earlier
            # step marked for destruction; a counter on it is a sentence no card
            # prints and nothing here would carry out.
            raise LoweringError(
                "only the trigger's own creature takes a counter this way",
                node=node,
            )
        if "end_of_combat_destruction" not in produced:
            raise LoweringError(
                "a pair member with no earlier step in this effect that bound "
                "a pair", node=node,
            )
        if node.subject.filter.to_payload() != {"type_filter": "creature"}:
            raise LoweringError(
                "a bound pair member names what the trigger bound and cannot "
                "be narrowed further", node=node,
            )
        return (
            OracleInstruction(
                "add_counter_to_target", "",
                {
                    "power": 1, "toughness": 1,
                    "pair_member": node.subject.quantifier,
                    "produced_by": "end_of_combat_destruction",
                },
            ),
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


def _lower_player_gets_counters(
    node: ast.PlayerGetsCounters, event: str | None
) -> tuple[OracleInstruction, ...]:
    """``That player gets a poison counter.`` (Pit Scorpion, and the ability
    Serpent Generator's tokens carry.)

    Poison is the one player counter with a store behind it
    (``PlayerState.poison_counters``, read by the CR 704.5c / 122.1f sweep in
    ``mixins/game_ending.py``), so any other kind refuses by name rather than
    compiling onto a field nobody sweeps. "That player" is a reading of the
    trigger that fired — the damaged player's seat, frozen into the trigger's
    context by ``damage_events._announce`` — so under any other event the words
    name a player nobody recorded, and the sentence refuses the same way the
    on-damage discard does.
    """
    if node.counter != "poison":
        raise LoweringError(
            f"no store tracks {node.counter!r} counters on a player", node=node
        )
    amount = _amount_payload(node.count)
    if not isinstance(amount, int) or amount <= 0:
        raise LoweringError("a player-counter count is a fixed number", node=node)
    if node.player.kind != "that_player" or event not in _DAMAGED_PLAYER_EVENTS:
        raise LoweringError(
            "the poison handler reads the damaged player out of a damage "
            "trigger's context; no other player reference has one",
            node=node,
        )
    return (
        OracleInstruction(
            "player_gets_poison_counters", "",
            {"amount": amount, "player": "damaged_player"},
        ),
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
