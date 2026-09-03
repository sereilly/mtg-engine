"""Lowering the loops: one sentence performed once per member of a set.

Split out of `control_flow.py` at the thousand-line guard, along the line that
module's own docstring already drew. `control_flow` is named after the
*composers* — `sequence`, `may`, `one_of` — the shapes that decide **whether**
and **in what order** a sentence runs. A loop decides **how many times**, and
what it iterates is a set: seats (CR 101.4's turn order), permanents the board
holds when the ability resolves (CR 611.2c), or a number an earlier step
recorded.

That is one question with one answer — "what is the set?" — and every function
here is a different reading of it, which is why the three lower onto one
`for_each` instruction with different iterator payloads. Nothing here reads an
offer and nothing in `control_flow` reads a set, so the split is along a real
boundary rather than a size.

Each takes its body **already lowered**: `lower.py` reads the sentence inside
the loop, exactly as it does for the composers next door, so this module needs
no parser handed down.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import _filter_payload
from ._events import _COUNTERS_PLACED_THIS_WAY
from ._records import optional_cost_key


def _lower_for_each_player(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """"**For each player,** this enchantment deals 1 damage to that player
    unless they pay {B} or {3}." (Lim-Dûl's Hex.)

    A loop over *seats* rather than over objects. The same ``for_each`` the
    object loops lower onto, with the seat set as the iterator — and the
    handler binds each seat as "that player" while its iteration runs, which is
    what the printed back-reference means and the only way one sentence can
    name a different player each time round.

    Refused for any other player reference: "for each opponent" is a real set
    and lowers here too, but a reference naming *one* seat is not a loop at all
    and would repeat the sentence once against a seat nobody chose.
    """
    if node.iterator.kind not in _LOOPED_SEAT_SETS:
        raise LoweringError(
            f"no loop repeats an effect over the {node.iterator.kind}", node=node
        )
    if not inner:
        raise LoweringError("a per-player loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {"iterator": {"players": node.iterator.kind}, "effect": inner},
        ),
    )


#: The player references that name a *set* of seats a loop can walk. The same
#: two ``handlers/control_flow._offered_seats`` enumerates, and deliberately no
#: more: a reference naming one seat is not a loop.
_LOOPED_SEAT_SETS = frozenset({"each_player", "each_opponent"})


def _lower_for_each_matching(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """"**For each attacking creature without flying,** its controller may pay
    {1}." (Tidal Flats.) "**For each attacking red creature,** prevent all
    combat damage that would be dealt by that creature this turn unless its
    controller pays {2}{R}." (Heroism.)

    A loop over what the **board** holds when the ability resolves — the fourth
    kind of iterator beside the recorded sets, the count and the seats, and the
    one the handler has always had a branch for and nothing could reach.

    The filter is the whole iterator payload, which is what the handler matches
    each permanent against; every key in it therefore has to be one
    ``subject_matches`` answers, or the loop would run over a strictly larger
    set than the phrase names — "creature **without flying**" is a layer-6
    question (CR 613.1f), and a loop that dropped it would offer Tidal Flats'
    toll to every attacker including the fliers it is printed to let through.
    """
    described = _filter_payload(node.iterator)
    if untestable_filter_keys(described):
        raise LoweringError(
            "the loop cannot test this restriction", node=node
        )
    if not inner:
        raise LoweringError("a per-object loop with no effect in it", node=node)
    return (
        OracleInstruction("for_each", "", {"iterator": described, "effect": inner}),
    )


def _lower_for_each_life_lost(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    event: str | None,
) -> tuple[OracleInstruction, ...]:
    """"**For each 1 life you lost,** sacrifice a permanent other than this
    enchantment unless you discard a card." (Oath of Lim-Dûl.)

    A loop whose iterator is a *number*, not a set — so the same ``for_each``
    the three "this way" sets lower onto, with the count coming off the firing
    event's frozen context instead of off the resolution scratchpad.

    Three refusals, each a way the sentence could otherwise mean more than it
    says:

    * the event must be one that freezes a life loss. Under any other trigger
      the phrase names a number nobody recorded, and an unwritten quantity
      reads as zero — a loop that runs no times on a card reporting supported.
    * the unit must be the printed 1. "For each **2** life you lost" is half as
      many repetitions, and the handler divides by nothing.
    * the body must lower to something, for ``_lower_for_each_chosen``'s
      reason: an empty loop is a sentence that reports supported and does not
      run.
    """
    if event != "you_lose_life":
        raise LoweringError(
            f"no event named {event!r} records the life this loop counts",
            node=node,
        )
    if node.iterator.per != 1:
        raise LoweringError(
            "this loop repeats once per 1 life lost, not per "
            f"{node.iterator.per}",
            node=node,
        )
    if not inner:
        raise LoweringError("a per-life loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {"iterator": {"repeat_from_trigger": "life_lost"}, "effect": inner},
        ),
    )


def _lower_for_each_counters_placed(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"**For each +1/+1 counter you put on a creature this way,** remove a
    +1/+1 counter from that creature at the beginning of the next cleanup step."
    (Bounty of the Hunt.)

    A loop over the *counters* an earlier step of this same resolution placed,
    one iteration per counter — so a creature given two of them is iterated
    twice and gets two delayed abilities, which is what makes the removal come
    out even with the placement.

    Refused without the producer, exactly as the three object-shaped "this way"
    windows are: with no earlier placement the words name nothing, and an empty
    loop is a sentence that reports supported and does not run. The printed
    counter kind is not checked against the record here — the record holds
    permanents, not kinds — so the check is that the *same resolution* placed
    counters at all, which is the producer, plus the body, which names the kind
    itself and removes that one.
    """
    if _COUNTERS_PLACED_THIS_WAY not in produced:
        raise LoweringError(
            "'counters put on a creature this way' needs a step of this effect "
            "that put some there",
            node=node,
        )
    if not inner:
        raise LoweringError("a per-counter loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {
                "iterator": {"produced_by": _COUNTERS_PLACED_THIS_WAY},
                "effect": inner,
            },
        ),
    )


def _lower_for_each_cost_paid(
    node: ast.ForEach,
    inner: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """"**For each additional {1}{R} you paid,** destroy another target
    artifact." (Primitive Justice, Taste of Paradise.)

    :func:`_lower_for_each_life_lost`'s twin, one channel over: a loop whose
    iterator is a number, read off what the *caster announced* as the spell was
    cast (CR 601.2b) rather than off a firing event. It is on the stack item's
    choices because the pool that paid it is empty by resolution (CR 500.4).

    No event gate, deliberately, where the life-lost loop has one: this number
    is recorded by the casting path for every spell that prints an optional
    additional cost, so there is no trigger it could be missing from. What
    there *is* to refuse is a body that lowered to nothing — an empty loop is a
    sentence that reports supported and does not run, this file's standing rule.
    """
    if not inner:
        raise LoweringError("a per-payment loop with no effect in it", node=node)
    return (
        OracleInstruction(
            "for_each", "",
            {
                "iterator": {
                    "repeat_from_cost": optional_cost_key(node.iterator.symbols)
                },
                "effect": inner,
            },
        ),
    )
