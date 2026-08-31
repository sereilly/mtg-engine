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


#: The keys a sacrifice cost carries *beside* its filter rather than inside
#: it: "another" is an identity comparison against the source and "of their
#: choice" is whose decision it is, and neither is something a matcher can
#: test. Here rather than in `board`, with the reducer that reads it, because
#: two families now charge a printed sacrifice (`board` and `damage`) and a
#: fragment two families need does not live in one of them.
_SACRIFICE_CARRIED = frozenset({"exclude_self", "their_choice"})


def _forced_sacrifice_filter(filt: ast.ObjectFilter) -> dict | None:
    """The filter payload the forced-sacrifice prompt should list, or None when
    the noun phrase says something the prompt cannot test.

    Two shapes are refused before the key check, because both would reduce to an
    *empty* payload — a prompt listing every permanent on the board:

    - a self-referential or enchanted subject ("sacrifice **this** creature",
      Sea Serpent), which is a different instruction entirely and is read below;
    - a phrase naming neither a card type nor a subtype, which would let the
      prompt eat anything on the board. A *subtype* alone is a real set and
      names it exactly — "two Swamps" (Mold Demon) is the whole cost, and it
      says nothing about card types because on that card it does not need to.
    """
    if filt.is_source or filt.is_enchanted or not (filt.card_types or filt.subtypes):
        return None
    from ...subject_filters import object_only_filter

    payload = dict(filt.to_payload())
    # "…sacrifices a third of the creatures **they control** of their choice."
    # (Pox.) CR 701.21a: a player can only ever sacrifice a permanent they
    # control, and the prompt offers exactly the payer's own board — so the
    # printed possessive restates the rule rather than narrowing it, and
    # dropping it here is reading the phrase rather than losing part of it.
    # Only the two spellings that can name the payer: any other controller
    # falls through to `object_only_filter`, which has no seat to test one
    # against and refuses.
    if payload.get("controller") in ("you", "that_player"):
        payload.pop("controller")
    return object_only_filter(payload, carried_separately=_SACRIFICE_CARRIED)
