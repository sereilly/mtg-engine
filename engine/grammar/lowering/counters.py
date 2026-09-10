"""Lowering counter **placements** (CR 122): a marker put on an object.

A counter is a marker placed on an object (CR 122.1); the P/T it may carry is
a consequence the layers compute, not the effect itself, which is why this is
its own family on the lowering side — it split out of `characteristics.py`
when the two together crossed the thousand-line cap. The per-death repetition
compares its exact subject for equality rather than pattern-matching it, so a
card with a *narrower* subject cannot silently take the same handler.

Two neighbours have since left along boundaries this docstring used to name,
and the pattern in both is *what the payload asks for*: removal
(``counter_removal.py``) asks which kind and whether the number is known yet
where a placement asks which object and how many, and the counters whose kind
**is** a store — loyalty and poison (``counter_stores.py``) — ask which store
tracks that name and nothing at all about an object's characteristics. What is
left dispatches on the shape of the subject and carries the kind as data, which
is what makes a card printing a counter nobody has named work for free.
"""

import dataclasses

from ...oracle_types import OracleInstruction
from ...subject_filters import object_only_filter
from .. import ast
from ..errors import LoweringError
from ..phrases import is_pt_counter
from ._common import (
    PRIMARY_TARGET_ROLE, _amount_payload,
    _describe_targets, _filter_payload, divided_target_description,
    _is_enchanted, _is_source, _is_target, _names_several_targets,
    _restrictions_beyond, describe_target_roles, refuse_untestable
)
from ._records import counts_prevented_damage, names_the_shielded_object
from ._sweeps import lower_counter_sweep
from ._plus_one_counters import lower_plus_one_placement
from ._counter_stores import lower_loyalty_counters
from ._events import (CHOSEN_PERMANENT, OTHER_CHOSEN_PERMANENT, EVENT_SUBJECT_CONTROLLER, _EVENT_SUBJECT_OBJECTS, binds_block_pair, _REANIMATED_PERMANENTS, _RECORDED_PERMANENTS)
from ._delays import (_BOUND_OBJECT_DELAYED_EVENTS)
from ._seats import _CHOOSER_SEATS


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


#: The trigger heads whose sentence is *about* the enchanted permanent, so a
#: bare "that creature" in the effect names it. Both are conditions an Aura
#: prints about its own host: the upkeep of that host's controller (Unstable
#: Mutation, Takklemaggot) and a death the host caused (Vampiric Embrace).
#:
#: A set rather than a bare comparison because the second entry proved the first
#: was a list of one: under any event *not* here the words name a permanent
#: nobody recorded, and the branch below must keep refusing rather than reading
#: the source's attachment on faith.
_ATTACHED_COUNTER_TRIGGERS: frozenset[str] = frozenset({
    "upkeep_enchanted_controller",
    "creature_dealt_damage_by_attached_dies",
})



def _lower_chosen_counter_placement(
    node: ast.PutCounter,
) -> tuple[OracleInstruction, ...]:
    """"Put a +1/+1 counter on target creature **of defending player's
    choice**." (Erithizon.)

    A placement whose object somebody *other than the ability's controller*
    picks. CR 602.3 is the rule that has room for it — an ability may say one of
    its controller's opponents does something the controller would normally do,
    and choosing the target is exactly that — so the sentence is two steps
    rather than one: the prompt that asks the named seat, and the placement that
    reads what it answered.

    The **same two steps** Crashing Boars, The Abyss, Preacher and Nova Pentacle
    already lower to, through the same ``choose_permanent`` kind, the same
    ``_CHOOSER_SEATS`` row and the same ``attach_host`` record. That is why the
    seat table moved down to ``_seats``: this is the second family to need it,
    and a second copy of it would answer differently the first time a row was
    added to one of them.

    Nothing is gated on the *event* here, deliberately, because the handler is
    where the seat is resolved and it already refuses to fall back: a chooser no
    firing named answers None and the prompt is reported as a choice nobody
    could make, never handed to the ability's controller — the one seat the card
    has just said must not choose. Gating here as well would be a second answer
    to one question.

    A **P/T pair only**: the recorded-permanent branch of
    ``add_counter_to_target`` writes through ``Game.place_pt_counters``, which
    derives the power and toughness from the counter's own name (CR 122.1a) and
    has nowhere to put a counter that has none.
    """
    seat = _CHOOSER_SEATS.get(node.chooser.kind)
    if seat is None:
        raise LoweringError(
            f"no prompt asks {node.chooser.kind!r} to choose a permanent",
            node=node,
        )
    if not is_pt_counter(node.counter):
        raise LoweringError(
            f"no chosen placement puts a {node.counter} counter on a permanent",
            node=node,
        )
    if node.up_to or node.then_double or node.cap is not None or node.distributed:
        raise LoweringError("a chosen placement carries no rider", node=node)
    if not isinstance(node.count, ast.Fixed) or node.count.value < 1:
        raise LoweringError("a chosen placement counts a fixed number", node=node)
    if not isinstance(node.subject, ast.TargetSpec):
        raise LoweringError("a chosen placement names a permanent", node=node)
    described = _filter_payload(node.subject.filter)
    if object_only_filter(described) is None:
        # The prompt enumerates candidates with no observer and no source, so a
        # narrowing it cannot test would be dropped — an offer of every creature
        # on the table where the card printed a restriction.
        raise LoweringError(
            "the choice carries a restriction the prompt cannot test", node=node
        )
    chosen: dict[str, object] = {
        "filter": described,
        "result_key": CHOSEN_PERMANENT,
        "prompt": f"Choose a creature to put a {node.counter} counter on.",
        "chooser": seat,
        "optional": False,
    }
    return (
        OracleInstruction("sequence", "", {"steps": (
            OracleInstruction("choose_permanent", "", chosen),
            OracleInstruction("add_counter_to_target", "", {
                "counter": node.counter,
                "count": node.count.value,
                "permanents_from": CHOSEN_PERMANENT,
            }),
        )}),
    )


def _lower_put_counter(
    node: ast.PutCounter,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
    event_subject: object | None = None,
    #: The trigger kind unfiltered by `whole_effect` — see the caller.
    trigger_event: str | None = None,
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
        # "among one or two target creatures" (Contagion) — CR 601.2c's ceiling,
        # shaped by `divided_target_description`, which is where the four
        # readers of these keys and the reason they share them are recorded.
        return (
            OracleInstruction("add_counter_to_target", "", {
                "counter": node.counter,
                "count": placed,
                "targets": divided_target_description(
                    "creature", max_targets=node.subject.max_count,
                ),
            }),
        )
    if node.chooser is not None:
        return _lower_chosen_counter_placement(node)
    # "Put a loyalty counter on Garruk." (Garruk, Unleashed's −2.)
    # CR 306.5c: loyalty is a *store* — a planeswalker's life total and the
    # price of its abilities — so the whole placement is decided by the
    # printed kind rather than by the subject, which is why it lives with the
    # poison placement in `_counter_stores` and is dispatched here, ahead of
    # every branch below that treats the kind as data.
    if node.counter == "loyalty":
        return lower_loyalty_counters(node)
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
        if isinstance(node.count, ast.Fixed):
            placed: int | str = node.count.value
        elif isinstance(node.count, ast.Var):
            placed = node.count.name
        else:
            raise LoweringError(
                "a named counter is placed a fixed or variable number at a "
                "time", node=node,
            )
        return (
            OracleInstruction(
                "add_named_counter_to_self", "",
                {"counter": node.counter, "count": placed},
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
    #
    # "Whenever a creature dealt damage by enchanted creature this turn dies,
    # put a +1/+1 counter on **that creature**." (Vampiric Embrace.) The second
    # trigger head that binds the enchanted creature, and the word points at it
    # for the same reason it does above: English's "that" takes the nearest
    # antecedent noun phrase, which is "enchanted creature".
    #
    # Reading it as the creature that *died* is the alternative, and it is not a
    # close call. Sengir Vampire prints this exact ability on the creature
    # itself and puts the counter on **this** creature; this Aura is that card
    # granted, so the word names the same permanent. And the other reading is
    # not merely different, it is inert: CR 122.1a does let a +X/+Y counter sit
    # on a creature card outside the battlefield, but CR 400.7 makes the card
    # that returns a new object with no memory of it, so nothing that counter
    # modified is ever read — a card that reports supported and does nothing,
    # which is the failure this whole package is arranged to make loud.
    if (
        is_pt_counter(node.counter)
        and not node.up_to
        and isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
        and event in _ATTACHED_COUNTER_TRIGGERS
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
        # The two printed *exclusions* are here because the pure matcher
        # already answers them off the permanent alone — "target **nonartifact,
        # nonblack** creature that attacked you this turn" (Jabari's Influence)
        # — so admitting them costs the placement nothing and refusing them
        # cost the card. The seat-relative record beside them is stripped and
        # carried, exactly as the in-combat relation is and for its reason: no
        # read of the chosen creature alone can answer it.
        leftover = _restrictions_beyond(
            filt,
            frozenset({
                "card_types", "in_combat_with_source",
                "excluded_types", "excluded_colors", "attacked_you_this_turn",
                # "Put a +2/+2 counter on target **Chimera** creature."
                # (Visions' four Chimeras.) A printed creature type, which
                # ``to_payload`` emits as ``subtype_filter`` and both readers of
                # the description honour — ``permanent_matches_filter`` at
                # resolution and ``targeting.py``'s picker at activation — so
                # admitting it costs the placement nothing. It was the one
                # narrowing this branch refused while the payload carried it
                # perfectly well, which is a false refusal rather than a silent
                # drop: four cards printing one sentence, unsupported for a word
                # the matcher already tests.
                #
                # ``subtype_match`` travels with it for the reason
                # ``_PAYLOAD_HONOURED_FILTER_FIELDS`` keeps the pair together —
                # two adjacent subtypes are a conjunction the payload spells
                # differently, and the field naming which spelling it is has to
                # be honoured wherever ``subtypes`` is.
                "subtypes", "subtype_match",
            }),
        )
        if leftover or filt.card_types != ("creature",):
            raise LoweringError(
                "the counter lands on a creature, optionally one in combat "
                "with the source",
                node=node,
            )
        stripped = dataclasses.replace(node.subject, filter=dataclasses.replace(
            filt, in_combat_with_source=False, attacked_you_this_turn=False,
        ))
        payload: dict[str, object] = {"counter": node.counter}
        if placed != 1:
            payload["count"] = placed
        if filt.in_combat_with_source:
            payload["in_combat_with_source"] = True
        if filt.attacked_you_this_turn:
            payload["attacked_you_this_turn"] = True
        _describe_targets(payload, stripped)
        return (OracleInstruction("add_counter_to_target", "", payload),)
    # "Put **X +0/+1** counters on this creature." (Necropolis.) The source's
    # own twin of the targeted branch above, and payload for the same reasons:
    # which CR 122.1a pair the counter names, and how many of it, are the whole
    # of what differs.
    #
    # The ``+1/+1`` exclusion was written so that every payload below stayed byte
    # for byte identical, and it cost Phyrexian Devourer ("Put **X +1/+1**
    # counters on this creature, where X is the exiled card's mana value") — the
    # one counter kind the pool prints most was the one kind no variable count
    # could be placed of. So the exclusion now holds only for a count this
    # branch is not the reader of: a printed ``+1/+1`` keeps its own payload
    # shape below unless the count is a variable, which nothing below reads.
    if (
        is_pt_counter(node.counter)
        and (node.counter != "+1/+1" or isinstance(node.count, ast.Var))
        and not node.up_to
        and _is_source(node.subject)
        # Declined here or this branch claims the shield sentence below
        # (Scars of the Veteran's bare pronoun) and refuses its count.
        and not counts_prevented_damage(node)
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
        # The legacy pair for ``+1/+1``, which ``add_counter_to_self`` reads as
        # the CR 614 placement path (`place_plus1_counters`) and every payload
        # written before Necropolis carries.
        payload: dict[str, object] = (
            {"power": 1, "toughness": 1} if node.counter == "+1/+1"
            else {"counter": node.counter}
        )
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
        if not names_the_shielded_object(node.subject):
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
    # The same referent with a **P/T pair** on it: "Whenever this creature
    # becomes blocked by a creature, put a -1/-1 counter on **that creature**."
    # (Quagmire Lamprey.) Its own branch rather than a widened gate above,
    # because CR 122.1a makes the two placements two different writes —
    # `Game.place_pt_counters` derives the power and toughness from the
    # counter's own name and `add_counters` cannot, which is exactly what that
    # branch's ``is_pt_counter`` refusal says. So the pair goes to the handler
    # that owns the P/T channel (`engine/pt.py`, through `add_counter_to_target`)
    # and reads its object through the one function that knows how each fire
    # site binds it.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
        and not node.up_to
        and not node.then_double
        and is_pt_counter(node.counter)
        and binds_block_pair(trigger_event, event_subject)
    ):
        if not isinstance(node.count, ast.Fixed) or node.count.value < 1:
            raise LoweringError("a bound placement counts a fixed number", node=node)
        described = _filter_payload(node.subject.filter)
        if object_only_filter(described) is None:
            # The rebound filter re-states the event's own narrowing, so it is
            # carried and re-checked rather than dropped — the reason the named
            # placement above gives, and the reason a restriction the resolution
            # cannot test refuses rather than being ignored.
            raise LoweringError(
                "the counter's subject carries a restriction the resolution "
                "cannot test", node=node,
            )
        return (OracleInstruction("add_counter_to_target", "", {
            "counter": node.counter, "count": node.count.value,
            "on_block_pair": True, **({"filter": described} if described else {}),
        }),)
    # "You put a **-1/-1** counter on **each creature that player controls**"
    # (Misfortune). A CR 122.1a counter placed on every member of a set the
    # sentence *describes* rather than chooses (CR 611.2c: the board is read as
    # the effect resolves), which is one handler for either P/T pair and either
    # scope — read here, above the "+1/+1 only" gate, because that gate was
    # written for the placements a printed count chooses and reports every
    # other pair as unimplemented.
    #
    # The pair is payload, not a kind: `Game.place_pt_counters` derives the P/T
    # from the counter's own name, so "-1/-1 on each" and "+1/+1 on each" differ
    # by one string. A counter with no P/T at all (a fade counter, a charge
    # counter) is refused, for the reason the bound placement above refuses it.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier in ("all", "each")
        and not node.up_to
        and not node.then_double
        and node.cap is None
        and not node.distributed
    ):
        return lower_counter_sweep(node)
    # Everything past here is a **+1/+1** placement, and what is left to
    # decide is how many and on what. That is a different question from
    # every branch above — which counter the sentence names, or which
    # earlier step bound its subject — and it is the seam this file already
    # drew for itself with the gate at the top of that run. Handed down
    # rather than returned to the caller, so the printed-specificity order
    # stays one list in one place and this function keeps one exit.
    return lower_plus_one_placement(node, produced, trigger_event=trigger_event)
