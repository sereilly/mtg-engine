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
no parser handed down. The one exception is the per-death counter loop at the
bottom, whose two handlers read the death count out of the trigger's own
context and take nothing from a payload — so its body is checked rather than
lowered, and it is `lower.py`'s fall-through for `ForEach`.

It arrived here from `lowering/counters.py` at Alliances' wave 3, when that
module reached the size guard. That is the mirror re-forming rather than a new
boundary: it is a `for_each` lowering and the other three already lived here,
so "which set does this sentence repeat over?" is answered in one module again.
What it repeats *is* a counter placement, which is exactly why it could sit in
either — and `lower.py` dispatching `ForEach` is what decides, since a family
named for the loop is the one that owns every reading of the loop.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import _filter_payload


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
