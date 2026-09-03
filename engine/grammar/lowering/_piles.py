"""How a **pile of cards** is described to a payload — a lowering floor.

Two leaves, both read by more than one family and neither belonging to either
of them:

* :func:`_linked_exile_filter` reduces a noun phrase to the payload a picker
  over a *zone* can test — the linked-exile record (CR 610.3) on one side, the
  cast permission that reads that same record on the other.
* :data:`_SEARCH_EXILE_HONOURED` is the set of narrowings a card-pile picker
  can answer at all.

A floor rather than a family, for ``_amounts``' reason one module over: both
halves of the ``exile``/``permissions`` split ask them, and a leaf two families
read cannot live in either without one importing the other. It carries no
lowering of its own — nothing here produces an ``OracleInstruction`` — which is
what keeps it a vocabulary rather than a third family.
"""

from __future__ import annotations

import dataclasses

from .. import ast
from ..errors import LoweringError
from ._common import chargeable_card_filter


# Restrictions the exile-search picker tests (engine/search_filters.py's
# vocabulary is not reused because this picker admits a *union* of card types,
# which the single-tutor flow deliberately refuses).
_SEARCH_EXILE_HONOURED = frozenset({"card_types", "colors", "is_card", "type_match"})


def _linked_exile_filter(filt: ast.ObjectFilter) -> dict:
    """The payload for a filter over cards in a **zone**, or a refusal.

    The zone words are read by the production and so are honoured here; what is
    left has to be answerable of a card that has no battlefield object behind it,
    which is the one question ``chargeable_card_filter`` exists to settle. Going
    through it rather than round the side means "creature cards with mana value 3
    or less" narrows the same way whether it is being exiled, discarded as a cost,
    or offered by a picker.
    """
    default = ast.ObjectFilter()
    described = chargeable_card_filter(
        dataclasses.replace(
            filt, zone=default.zone, zone_owner=default.zone_owner, is_card=True
        )
    )
    if described is None:
        raise LoweringError(
            "the linked exile cannot test this restriction on a card in a zone",
            node=filt,
        )
    return described
