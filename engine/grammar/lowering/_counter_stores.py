"""Lowering counters whose **kind names a store**, not a marker.

Split out of ``lowering/counters.py`` when Mirage took that module back through
the 1,000-line cap, and along the boundary ``counter_removal.py`` recorded when
it left the same file: *different payload vocabularies*. A CR 122.1a placement
asks which object and how many, and what the counter then does is a layer-7d
consequence the continuous system computes. These two ask neither — they ask
**which store tracks this kind**, and refuse by name when nothing does:

- **Loyalty** (CR 306.5b/306.5c). A planeswalker's loyalty is its life total
  *and* the price of its abilities, spent by the activation path and read by the
  state-based sweep. Nothing about power or toughness is involved.
- **Poison** (CR 122.1f, CR 704.5c). A counter on a **player**, which CR 122.1's
  own first sentence separates from a counter on an object — and in this engine
  they are not even the same field: one is ``PlayerState.poison_counters`` and
  the other is a permanent's metadata.

That shared refusal is what makes them one family rather than two leftovers:
both dispatch on the counter's printed *name* because that name is the whole of
what the sentence is about, where every branch left behind dispatches on the
subject's shape and treats the name as data. A kind admitted here with no store
behind it would compile onto a field nobody sweeps — a counter placed, reported,
and doing nothing at all.

**A floor, not a family**, for ``_bound_returns.py``'s reason exactly: the
loyalty placement is reached from inside ``counters._lower_put_counter`` — the
printed kind is settled before the subject is looked at — so ``counters`` reads
this and it reads nothing back, and inside a package a module a family imports
cannot itself be one.

**No parse-side mirror, deliberately**, for ``counter_removal.py``'s reason:
``effects/counters.py`` reads every one of these placements with the productions
it already has, and the lowering side carries families the parse side does not.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS
from .. import ast
from ..errors import LoweringError
from ._common import _amount_payload, _is_source, _restrictions_beyond
from ._events import frozen_seat_record

# The ObjectFilter fields the loyalty-counter picker reads. Only what the pool
# actually prints ("a Liliana planeswalker you control"): a filter with no card
# behind it is untested by construction, and `_restrictions_beyond` turns every
# other field — present today or added to the AST later — into a refusal rather
# than a silently wider effect.
_LOYALTY_PICKER_HONOURED = frozenset({"card_types", "subtypes", "controller"})


def lower_loyalty_counters(
    node: ast.PutCounter,
) -> tuple[OracleInstruction, ...]:
    """``Put <N> loyalty counter(s) on <planeswalker>.`` (CR 306.5c.)

    Called from :func:`counters._lower_put_counter` the moment the printed kind
    is ``loyalty``, ahead of every branch there, because the kind is what decides
    this and not the subject: the source's own loyalty lives on the permanent
    (``metadata["loyalty_counters"]``) and a *chosen* permanent's is the same key
    reached through the picker.
    """
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


def _lower_player_gets_counters(
    node: ast.PlayerGetsCounters, event: str | None
) -> tuple[OracleInstruction, ...]:
    """``That player gets a poison counter.`` (Pit Scorpion, and the ability
    Serpent Generator's tokens carry.)

    Poison is the one player counter with a store behind it
    (``PlayerState.poison_counters``, read by the CR 704.5c / 122.1f sweep in
    ``mixins/game_ending.py``), so any other kind refuses by name rather than
    compiling onto a field nobody sweeps. "That player" is a reading of the
    trigger that fired — the damaged player's seat, frozen by
    ``damage_events._announce`` — and "**defending player**" (Swamp Mosquito) is
    CR 506.2's, frozen by the combat fire site. ``_events.frozen_seat_record``
    says which record a printed word names, so under an event that froze neither
    the words name a player nobody recorded and the sentence refuses.
    """
    if node.counter != "poison":
        raise LoweringError(
            f"no store tracks {node.counter!r} counters on a player", node=node
        )
    amount = _amount_payload(node.count)
    if not isinstance(amount, int) or amount <= 0:
        raise LoweringError("a player-counter count is a fixed number", node=node)
    who = frozen_seat_record(node.player.kind, event)
    if who is None:
        raise LoweringError(
            "a player counter lands on the seat the firing event froze, and "
            "this player reference has none under this event",
            node=node,
        )
    return (
        OracleInstruction(
            "player_gets_poison_counters", "", {"amount": amount, "player": who},
        ),
    )
