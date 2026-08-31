"""What a permanent damaged this turn and then outlived.

"Whenever a creature dealt damage by this creature this turn **dies**…"
(Seraph, Sengir Vampire) is announced by the death itself, and the fire site has
the dying card in hand. "At the beginning of each end step, **if** a creature
dealt damage by this creature this turn **died**…" (Krovikan Vampire) asks the
same question a whole step later, when the permanent is gone and the
``damaged_by_sources_this_turn`` record it carried has gone with it.

So the damage relation is recorded a second time, on the other object: each
damager keeps the *cards* of the creatures it damaged that died. The cards,
because a card is the only part of a dead creature that survives (CR 400.7) and
because "put **that card** onto the battlefield" is exactly what the sentence
behind the condition does with it.

Written where the death happens (``mixins/helpers._permanent_to_graveyard``) and
swept at cleanup with the record it mirrors (``mixins/_constants``): the two are
halves of one turn-scoped fact, and a ledger that outlived the damage record
would reanimate a creature on a turn nothing had died on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import CardDefinition, Permanent

#: Where the ledger is stamped. Named here rather than spelled at each of the
#: three readers, because a second spelling is how a record and its reader come
#: apart -- the write site, the condition evaluator and the reanimation all use
#: this one.
DAMAGED_CREATURES_THAT_DIED = "damaged_creatures_that_died_this_turn"

#: The lowered condition kind the intervening-if becomes. One constant for the
#: lowering that writes it and the evaluator that reads it.
DAMAGED_BY_SOURCE_DIED = "damaged_by_source_died_this_turn"


def creatures_it_damaged_that_died(permanent: "Permanent | None") -> list["CardDefinition"]:
    """The cards of the creatures *permanent* damaged this turn that have died.

    An empty list for no permanent at all, which is the honest answer for an
    ability whose source has left: it damaged nothing since, and the record went
    with it.
    """
    if permanent is None:
        return []
    recorded = permanent.metadata.get(DAMAGED_CREATURES_THAT_DIED)
    return list(recorded) if recorded else []


__all__ = [
    "DAMAGED_BY_SOURCE_DIED", "DAMAGED_CREATURES_THAT_DIED",
    "creatures_it_damaged_that_died",
]
