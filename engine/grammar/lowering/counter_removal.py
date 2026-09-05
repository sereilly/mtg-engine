"""Lowering counter **removal** (CR 121.3).

Split out of ``lowering/counters.py`` when Fallen Empires took that module
through the 1,000-line cap — and by three groups at once, none of which
crossed it alone: a bound subject for the placement (Soul Exchange), a
chosen one (the two Chants), and "remove **all** counters" (Homarid, Tidal
Influence). The cap fired at integration, which is the guard working: the
family boundary was already there and the collision is what surfaced it.

Putting and removing are different actions with different payload
vocabularies — a placement asks *which object and how many*, a removal asks
*which kind and whether the number is known yet* — so this is the boundary
that was there to find rather than a cut at a convenient line number.

**No parse-side mirror, deliberately.** ``effects/counters.py`` reads both
halves in 321 lines and has no reason to split; the lowering side carries
families the parse side does not for exactly this reason, and
``tests/engine/test_grammar_layering.py`` documents every one with its
reason.
"""

from __future__ import annotations

from ..phrases import is_pt_counter
from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS
from ._common import (_amount_payload, _describe_targets, _filter_payload,
                      _is_source)
from ._events import _BOUND_OBJECT_DELAYED_EVENTS

#: The player counters this engine has a store for. CR 122.1 lets a counter have
#: any name, and a player carries exactly one kind here
#: (``PlayerState.poison_counters``, read by the CR 704.5c / 122.1f sweep) — so a
#: line naming any other refuses saying which store is missing, rather than
#: compiling onto a handler that would zero a field nobody keeps.
_PLAYER_COUNTER_KINDS = frozenset({"poison"})


def _lower_player_counter_removal(
    node: ast.RemoveCounter,
) -> tuple[OracleInstruction, ...]:
    """``Target player loses all poison counters.`` (Leeches, which also prints
    the removal the other way round — ``Remove all poison counters from target
    player`` reaches the same node.)

    A counter on a **player** (CR 122.1f), which is a different store from every
    removal below: those reach a permanent's ``named_counters``, and a seat's
    poison lives on ``PlayerState.poison_counters``. So it is its own
    instruction rather than a subject the handlers below could take — one of
    them would have looked for a permanent and found a seat.

    Three refusals, each a way the sentence could otherwise mean more than it
    says: the seat must be one the ability **chose** (nothing enumerates a
    removal per member of a set), the counter must be one the engine stores, and
    the count must be "all" — a numbered removal from a player has no handler,
    and lowering one onto this would empty a pool the card meant to take two
    off.
    """
    player = node.subject
    if not isinstance(player, ast.PlayerRef) or player.kind not in (
        "target_player", "target_opponent",
    ):
        raise LoweringError(
            "no handler removes counters from this player", node=node
        )
    if node.counter not in _PLAYER_COUNTER_KINDS:
        raise LoweringError(
            f"a player has no {node.counter} counters in this engine", node=node
        )
    if not isinstance(node.count, ast.AllOf):
        raise LoweringError(
            "the only player counter removal takes all of them", node=node
        )
    payload: dict[str, object] = {"counter": node.counter}
    _describe_targets(payload, player)
    return (
        OracleInstruction("remove_all_counters_from_target_player", "", payload),
    )


def _lower_remove_counter(
    node: ast.RemoveCounter, event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """``Remove a <kind> counter from this <permanent>`` (Armageddon Clock).

    The counter's name is payload — it is the accumulating side's payload too
    (``upkeep_put_counter_on_self``), so the pair is one template rather than a
    card. What is *not* payload is the subject or the number:
    ``remove_counter_from_self`` reads the ability's own source and decrements by
    one, so anything else refuses rather than compiling onto a handler that
    would quietly do that instead.
    """
    # "**Target player** loses all poison counters." (Leeches.) A counter on a
    # seat rather than on an object, so it reaches neither the sweep below nor
    # any of the permanent removals under it — read first, because every one of
    # those asks a question about a ``TargetSpec`` and a ``PlayerRef`` would
    # fall through all of them to the source check at the bottom and refuse
    # naming the wrong thing.
    if isinstance(node.subject, ast.PlayerRef):
        return _lower_player_counter_removal(node)
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
    # "…remove a sleep counter from **that creature**." (Venarian Gold.) "That
    # creature" restates an object something earlier bound, and the only
    # trigger head that binds one is `upkeep_enchanted_controller` — its
    # sentence is *about* the enchanted creature, which is what the handler
    # reads off the source's own attachment. Under any other event the words
    # name a creature nobody recorded, so the line keeps refusing; and the
    # dispatch registry keys on the ability's whole instruction, so a nested
    # occurrence (event is None here) refuses the same way.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
        and event == "upkeep_enchanted_controller"
    ):
        if node.subject.filter != ast.ObjectFilter(card_types=("creature",)):
            raise LoweringError(
                "the attached counter removal reads the enchanted creature alone",
                node=node,
            )
        if is_pt_counter(node.counter):
            raise LoweringError(
                "a P/T counter removal needs the counter seam, which this "
                "handler does not reach",
                node=node,
            )
        if _amount_payload(node.count) != 1:
            raise LoweringError(
                "no handler removes more than one counter at a time", node=node
            )
        return (
            OracleInstruction(
                "remove_counter_from_attached", "", {"counter": node.counter}
            ),
        )
    # "When this creature leaves the battlefield or becomes untapped, remove all
    # -1/-1 counters from **the creature**." (Giant Oyster.) The object the
    # *creating* ability bound (CR 603.7c), named by id in the delayed trigger's
    # context. Its own kind beside the self-reading removal below, for
    # ``destroy_bound_permanent``'s reason: that handler empties the ability's
    # own source, which here is the Oyster rather than the creature it locked
    # down — a card that would compile clean and take its own counters off.
    #
    # Admitted only under an event whose fire site records an object, exactly as
    # the enchanted-creature row above is gated on the one trigger head that
    # binds one: everywhere else the words name a creature nobody recorded.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
        and event in _BOUND_OBJECT_DELAYED_EVENTS
    ):
        if isinstance(node.count, ast.AllOf):
            return (
                OracleInstruction(
                    "remove_all_counters_from_bound", "", {"counter": node.counter}
                ),
            )
        # "…remove **a** +1/+1 counter from that creature." (Bounty of the
        # Hunt.) The counted twin of the emptying removal above, and its own
        # kind for that one's reason: "all" is a number nobody knows until the
        # permanent is looked at, and lowering a printed count onto that handler
        # would empty a permanent the card says to decrement by one.
        amount = _amount_payload(node.count)
        if not isinstance(amount, int) or amount <= 0:
            raise LoweringError(
                "the counted bound removal takes a printed number", node=node
            )
        return (
            OracleInstruction(
                "remove_counters_from_bound", "",
                {"counter": node.counter, "amount": amount},
            ),
        )
    # "When this enchantment leaves the battlefield, remove all rust counters
    # from **all permanents**." (Corrosion.) A sweep over a described set, so
    # nothing is chosen and nothing is targeted: the handler reads the board as
    # the effect resolves (CR 611.2c) and empties every permanent the phrase
    # names. Its own kind beside the self and bound removals above for their
    # reason — those two each read one permanent the instruction already names,
    # and there is no permanent here until the board is scanned.
    #
    # Only the emptying spelling. "Remove **a** rust counter from all
    # permanents" would be a decrement over a set and no card prints it; a count
    # lowered onto this handler would empty every permanent the card says to
    # decrement by one, which is the mistake the "all"/counted pair above
    # already records.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "all"
        and isinstance(node.count, ast.AllOf)
    ):
        described = _filter_payload(node.subject.filter)
        if set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
            raise LoweringError(
                "a counter-removal sweep cannot test this restriction", node=node
            )
        return (
            OracleInstruction(
                "remove_all_counters_from_matching", "",
                {"counter": node.counter, "filter": described},
            ),
        )
    if not _is_source(node.subject):
        raise LoweringError(
            "the only counter-removal handler reads the ability's own source", node=node
        )
    if isinstance(node.count, ast.AllOf):
        # "…remove **all** tide counters from it." (Homarid, Tidal Influence.)
        # Its own kind rather than a count on the one below: that handler
        # decrements by a number the instruction already carries, and "all" is
        # a number nobody knows until the permanent is looked at — compiling it
        # onto a fixed removal would take exactly one counter off a permanent
        # the card says to empty.
        return (
            OracleInstruction(
                "remove_all_counters_from_self", "", {"counter": node.counter}
            ),
        )
    if isinstance(node.count, ast.AnyNumber):
        # "Remove **any number of** +1/+1 counters from this creature."
        # (Tetravus.) Its own kind rather than a count on the one above: that
        # handler decrements by a number it already knows, and this one has to
        # ask its controller for the number first. What it removes is recorded,
        # because the sentence after it ("create **that many** … tokens") reads
        # it back.
        return (
            OracleInstruction(
                "remove_any_number_of_counters_from_self", "", {"counter": node.counter}
            ),
        )
    if _amount_payload(node.count) != 1:
        raise LoweringError("no handler removes more than one counter at a time", node=node)
    return (
        OracleInstruction("remove_counter_from_self", "", {"counter": node.counter}),
    )


def _lower_move_counter(node: "ast.MoveCounter") -> tuple[OracleInstruction, ...]:
    """``Move a +1/+1 counter from this enchantment onto target creature.``
    (Afiya Grove.)

    Here rather than in ``lowering/counters.py`` because CR 121.6's move is a
    removal that happens to end somewhere: what decides whether anything at all
    happens is the *source's* counter store, which is this module's question,
    and the placement is the tail of it.

    Three refusals, each a way the sentence could otherwise do more than it
    says:

    * The source must be the ability's **own permanent**. Every printing of
      this sentence names it, and a wording naming something else would be an
      object nobody chose — the handler would read whatever the resolution
      context was carrying and take a counter off it.
    * The destination must be a chosen object, and its narrowing has to be one
      the picker can test, for ``_describe_targets``' standing reason: a
      restriction the picker cannot honour is a restriction dropped.
    * The count is a printed number. "Move **X** counters" would be a quantity
      the handler cannot re-ask at resolution, and a move of zero is a move
      that silently does nothing.
    """
    if not _is_source(node.source):
        raise LoweringError(
            "a counter is moved off the ability's own permanent", node=node
        )
    destination = node.destination
    if not isinstance(destination, ast.TargetSpec) or not destination.targeted:
        raise LoweringError(
            "a moved counter goes onto a chosen permanent", node=node
        )
    count = _amount_payload(node.count)
    if not isinstance(count, int) or count < 1:
        raise LoweringError(
            "a counter move carries a printed number of counters", node=node
        )
    payload: dict[str, object] = {"counter": node.counter, "count": count}
    _describe_targets(payload, destination)
    return (OracleInstruction("move_counter_from_self", "", payload),)
