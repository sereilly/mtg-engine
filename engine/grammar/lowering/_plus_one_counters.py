"""The +1/+1 placements: how many, and on what.

The tail of ``counters.py``, cut where that file's own gate already cut it —
``if node.counter != "+1/+1"``. Everything above the gate dispatches on *which
counter* the sentence names or on a subject some earlier step bound; everything
below it has settled that question and asks only two more: how many counters,
and which object takes them. Two different questions in one function is what
took the module past the thousand-line guard, and the guard is the signal that
the family stopped absorbing new work rather than a style rule.

Reached as the **last thing** ``_lower_put_counter`` does, exactly as
``lower_untargeted_return`` hands the sentence down to ``_described_returns``:
one call, one order, one answer, so the branch order the whole file depends on
stays a single list read top to bottom.

``_lower_recorded_count_placement`` came with it because it is one of those two
questions — a number an earlier step of the same resolution produced — and its
only caller is here. A floor rather than a family (``counters`` is its one
reader), which is the footing ``_bound_returns`` and ``_sweeps`` sit on.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ..phrases import PAIR_ORDINALS
from ._amounts import recorded_count_spec
from ._common import (_describe_several_targets, _describe_targets,
                      _filter_payload, _is_source, _is_target,
                      _names_several_targets)
from ._events import CHOSEN_PERMANENT, EVENT_SUBJECT_PLAYER, _EVENT_SUBJECT_PLAYERS


def _lower_recorded_count_placement(
    node: ast.PutCounter, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """"…put **that many** +1/+1 counters on this creature" (Tetravus), and
    "For each card discarded this way, put **two** +1/+1 counters on this
    creature" (Mind Maggots).

    One branch because it is one printed idea — a placement whose number an
    earlier step of the same resolution produced — and **two channels**, because
    the two sentences say different things about *which* record.

    A bare "that many" names nothing (:class:`ast.ThatMuch` carries ``None`` to
    say so), so it keeps the ``trigger_count`` key it has always had: its one
    printing is Tetravus, whose exile step writes exactly that.

    A "this way" clause **names its producer**, and the name was being thrown
    away — every ``ThatMuch`` reached this branch and left as ``trigger_count``,
    a key no discard, no destroy and no tap ever writes. Latent rather than live
    until now (Tetravus was the only card here and its record really is that
    key), and the failure it was holding is the quiet one: a counter placement
    that resolves, reports itself done and places **zero**. So a named record
    goes through ``recorded_count_spec`` onto the ``x_from_count`` channel this
    same handler already reads for Discordant Spirit — the number is taken by
    one evaluator (``count_from_payload``), which is also what carries the
    printed multiplier without a payload key of its own.
    """
    spec = recorded_count_spec(node.count, produced, node)
    if spec is None:
        if isinstance(node.count, ast.Times):
            # A factor over something that is not a recorded count — nothing
            # prints it, and reading it as the bare "that many" below would
            # place a fraction of what the card says.
            raise LoweringError(
                "a multiplied count has no recorded producer to read", node=node
            )
        return (
            OracleInstruction(
                "add_counter_to_self", "",
                {"power": 1, "toughness": 1, "count": "trigger_count"},
            ),
        )
    return (
        OracleInstruction(
            "add_counter_to_self", "",
            {"power": 1, "toughness": 1, "count": "x", "x_from_count": spec},
        ),
    )


def lower_plus_one_placement(
    node: ast.PutCounter, produced: frozenset[str],
    trigger_event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """The placements left once the counter is known to be a +1/+1 pair.

    Raises rather than returning None: by the time ``counters`` hands the
    sentence down every earlier reading has refused it, so this is the end of
    the list and a shape nothing here answers is a shape nothing answers.
    """
    if node.counter != "+1/+1" or node.up_to:
        raise LoweringError(f"no handler for {node.counter} counters", node=node)
    if isinstance(node.count, (ast.ThatMuch, ast.Times)) and _is_source(node.subject):
        return _lower_recorded_count_placement(node, produced)
    if isinstance(node.count, ast.DamageDealtThisTurn) and _is_source(node.subject):
        # "…put a +1/+1 counter on this creature **for each 1 damage dealt to
        # you this turn**." (Discordant Spirit.) The turn's damage ledger rather
        # than the resolution scratchpad the branch above reads, and it reaches
        # the same handler through the channel every computed amount in this
        # engine already uses: ``x_from_count`` defines the X, and ``count``
        # spends it. So the number is taken by ``count_from_payload`` — one
        # evaluator — instead of by a second reader written for this card.
        return (
            OracleInstruction(
                "add_counter_to_self", "",
                {
                    "power": 1, "toughness": 1, "count": "x",
                    "x_from_count": {
                        "damage_ledger": {
                            "recipient": node.count.recipient,
                            "source_name": node.count.source_name,
                            "others_only": node.count.others_only,
                            "base": 0,
                        },
                    },
                },
            ),
        )
    if isinstance(node.count, ast.CountOfDeaths) and _is_source(node.subject):
        # "…put a +1/+1 counter on ~ **for each creature put into your graveyard
        # from the battlefield this turn**." (Asmira, Holy Avenger.) The turn's
        # per-seat death tally, reached through the same `x_from_count` channel
        # as the ledger branch above and answered by the same `count_from_payload`
        # `history` key `_lower_where_x_deaths` already spends.
        #
        # Only the bare creature filter, and that refusal is
        # `_lower_where_x_deaths`'s word for word: the tally counts creatures
        # and nothing narrower, so a narrowing admitted here would be counted as
        # if it were not there — a counter placed more often than the card says.
        filt = node.count.filter
        if (
            filt.to_payload() != {"type_filter": "creature"}
            or filt.zone != "battlefield"
        ):
            raise LoweringError(
                "the death tracker counts creatures and cannot be narrowed",
                node=node,
            )
        return (
            OracleInstruction(
                "add_counter_to_self", "",
                {
                    "power": 1, "toughness": 1, "count": "x",
                    "x_from_count": {"history": f"creatures_{node.count.scope}"},
                },
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
    if (
        _is_target(node.subject)
        and getattr(node.subject.filter, "their_choice", False)
    ):
        # "At the beginning of each player's upkeep, that player may put a
        # +1/+1 counter on target creature **of their choice**." (Ley Line.)
        #
        # ``lowering/destruction._lower_destroy_of_their_choice`` word for word,
        # one verb over: the pick belongs to a seat that is not the ability's
        # controller, so the ordinary ``choose_permanent`` prompt is armed on
        # *that* seat and the placement behind it reads the recorded id through
        # ``permanents_from`` rather than a target. Both halves already exist;
        # what is new is only the pairing.
        #
        # The deviation from CR 603.3d is the one The Abyss's branch records:
        # the printed word is "target" and a triggered ability's targets are
        # chosen as it goes on the stack, but this engine announces an upkeep
        # trigger's targets from one seat — so the affected player's pick is
        # made at resolution instead. What that costs is the CR 608.2b re-check
        # and shroud on the picked creature.
        #
        # Refused under an event that froze no seat: with nobody named there is
        # nobody to ask, and a prompt armed on nobody is an effect that silently
        # does not happen. Where The Abyss also demands "that player controls",
        # this sentence narrows the candidates not at all — any creature on the
        # table is one — so the controller key is simply absent rather than
        # checked.
        #
        # The **unfiltered** trigger event, for the reason
        # ``statement_dispatch`` gives one clause up when it hands this family
        # two of them: "of their choice" under a trigger whose subject is a
        # player is a fact about the *trigger*, true of every clause beneath it,
        # and this clause is nested inside the sentence's own "that player
        # may …" — so the ``whole_effect``-filtered event is None here and a
        # gate on it would refuse the only card that prints the phrase.
        if trigger_event not in _EVENT_SUBJECT_PLAYERS:
            raise LoweringError(
                "'of their choice' names no player this placement can ask",
                node=node,
            )
        described = _filter_payload(
            node.subject.filter, carried_separately=frozenset({"their_choice"})
        )
        # Lifted rather than carried, for the destroy's reason: no candidate can
        # be asked whether it is "of their choice", so left in the payload it
        # would be a key the candidate rule cannot test.
        described.pop("their_choice", None)
        if untestable_filter_keys(described):
            raise LoweringError(
                "the counter prompt cannot test this restriction", node=node
            )
        return (
            OracleInstruction(
                "choose_permanent", "",
                {
                    "result_key": CHOSEN_PERMANENT,
                    "chooser": EVENT_SUBJECT_PLAYER,
                    "filter": described,
                    "prompt": "Choose a creature to put a +1/+1 counter on.",
                },
            ),
            OracleInstruction(
                "add_counter_to_target", "",
                {"power": 1, "toughness": 1, "permanents_from": CHOSEN_PERMANENT},
            ),
        )
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
    raise LoweringError("counters on a non-source subject", node=node)
