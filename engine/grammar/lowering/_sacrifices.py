"""What a printed "sacrifice <noun phrase>" cost may be paid with.

A leaf beside ``_common``, not a family: two lowering families now charge a
printed sacrifice — ``board`` for "unless you sacrifice two Islands" and
``damage`` for "unless you sacrifice a creature other than this creature" — and
the family rule is that families do not import each other, so a fragment two of
them need sits underneath both however small it is. ``_amounts`` is the same
shape one round earlier.

The reduction itself is ``subject_filters.object_only_filter``: the charger has
no observer and no source, so a key it cannot test would be handed over and
silently ignored. What the two keys below carry is not a narrowing lost —
"another" is an identity comparison the charger makes against the ability's own
source, and "of their choice" is whose decision it is.
"""

from __future__ import annotations

from .. import ast
from ._common import _restrictions_beyond


#: The keys a sacrifice cost carries *beside* its filter rather than inside
#: it: "another" is an identity comparison against the source and "of their
#: choice" is whose decision it is, and neither is something a matcher can
#: test. Here rather than in `board`, with the reducer that reads it, because
#: two families now charge a printed sacrifice (`board` and `damage`) and a
#: fragment two families need does not live in one of them.
_SACRIFICE_CARRIED = frozenset({"exclude_self", "their_choice"})

#: The same two, spelled as the AST fields they come from. Two spellings
#: because the two readers below ask at two moments — one about the payload
#: that came out, one about the node that went in — and a field with no
#: payload key is exactly what the second one is looking for.
_SACRIFICE_CARRIED_FIELDS = frozenset({"other_than_source", "their_choice"})


def _forced_sacrifice_filter(filt: ast.ObjectFilter) -> dict | None:
    """The filter payload the forced-sacrifice prompt should list, or None when
    the noun phrase says something the prompt cannot test.

    Two shapes are refused before the key check, because both would reduce to an
    *empty* payload — a prompt listing every permanent on the board:

    - a self-referential or enchanted subject ("sacrifice **this** creature",
      Sea Serpent), which is a different instruction entirely and is read below;
    - a phrase naming neither a card type nor a subtype **that said something
      else the payload lost**, which would let the prompt eat anything on the
      board. A *subtype* alone is a real set and names it exactly — "two
      Swamps" (Mold Demon) is the whole cost, and it says nothing about card
      types because on that card it does not need to.

    The generic head noun is the one empty payload that is *right*: "sacrifice
    **a permanent** other than this enchantment" (Oath of Lim-Dûl) names every
    permanent, and a prompt listing every permanent is what the card says. It
    is told apart from a lost narrowing by asking the node rather than the
    payload — every non-default field must be one the cost carries beside the
    filter, so a phrase whose restriction ``to_payload`` dropped keeps refusing.
    """
    if filt.is_source or filt.is_enchanted:
        return None
    if not (filt.card_types or filt.subtypes) and _restrictions_beyond(
        filt, _SACRIFICE_CARRIED_FIELDS
    ):
        return None
    from ...subject_filters import object_only_filter

    return object_only_filter(filt.to_payload(), carried_separately=_SACRIFICE_CARRIED)
