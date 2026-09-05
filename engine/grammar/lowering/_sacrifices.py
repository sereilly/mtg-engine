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


def _names_a_set(filt: ast.ObjectFilter) -> bool:
    """Whether the noun phrase narrows to a set on its own.

    The four axes a printed noun phrase describes a permanent class with:
    CR 205.2 card types, CR 205.3 subtypes, CR 105 colours, and the
    cross-axis union of those (``any_classes``, "an Island or blue
    permanent"). All four are in ``_PAYLOAD_HONOURED_FILTER_FIELDS``, which is
    what makes them safe to ask here: a field the payload always emits and the
    matcher always tests cannot be the narrowing that got lost.

    CR 111.1's axis is the fifth, and it was missing: "Sacrifice a **nontoken**
    permanent" (Forbidden Ritual) names every nontoken permanent, which is a
    real set and exactly what the card says. ``nontoken`` and its twin
    ``token_only`` sit in ``_PAYLOAD_HONOURED_FILTER_FIELDS`` beside ``colors``
    — ``to_payload`` emits both unconditionally and ``permanent_matches_filter``
    tests both — so neither can *be* the lost narrowing this guard is aimed at.
    Left out, the phrase was refused for saying something the payload carries
    perfectly well, which is the same false refusal ``subtype_match``,
    ``any_classes``, ``any_states`` and ``token_only`` were each added to
    ``_PAYLOAD_HONOURED_FILTER_FIELDS`` to end one gate over.
    """
    return bool(
        filt.card_types or filt.subtypes or filt.colors or filt.any_classes
        or filt.nontoken or filt.token_only
    )


def _forced_sacrifice_filter(filt: ast.ObjectFilter) -> dict | None:
    """The filter payload the forced-sacrifice prompt should list, or None when
    the noun phrase says something the prompt cannot test.

    Two shapes are refused before the key check, because both would reduce to an
    *empty* payload — a prompt listing every permanent on the board:

    - a self-referential or enchanted subject ("sacrifice **this** creature",
      Sea Serpent), which is a different instruction entirely and is read below;
    - a phrase naming none of the four ways a noun phrase can *be* a set
      **that said something else the payload lost**, which would let the prompt
      eat anything on the board. A *subtype* alone is a real set and names it
      exactly — "two Swamps" (Mold Demon) is the whole cost, and it says nothing
      about card types because on that card it does not need to. So is a
      **colour** alone: "a green or white permanent of their choice" (Dystopia)
      names every green-or-white permanent, and ``colors``/``any_classes`` sit
      in ``_PAYLOAD_HONOURED_FILTER_FIELDS`` beside ``card_types`` — emitted
      unconditionally and tested by ``permanent_matches_filter`` — so neither
      can *be* the lost narrowing this guard is aimed at. Left out, three cards
      printing "sacrifices a <colour> or <colour> permanent of their choice"
      were refused for saying something the payload carries perfectly well,
      which is the false refusal ``subtype_match`` and ``any_classes`` were each
      added to ``_PAYLOAD_HONOURED_FILTER_FIELDS`` to end one gate over.

    The generic head noun is the one empty payload that is *right*: "sacrifice
    **a permanent** other than this enchantment" (Oath of Lim-Dûl) names every
    permanent, and a prompt listing every permanent is what the card says. It
    is told apart from a lost narrowing by asking the node rather than the
    payload — every non-default field must be one the cost carries beside the
    filter, so a phrase whose restriction ``to_payload`` dropped keeps refusing.
    """
    if filt.is_source or filt.is_enchanted:
        return None
    # "…sacrifice a land **of an opponent's choice**" (Demonic Hordes). The
    # prompt is armed for the *payer*, so the rider names a chooser it cannot
    # be — and unlike "of their choice" beside it, that is a narrowing rather
    # than a restatement: which land goes is the whole of what the card asks.
    # Refused here, which is what ``phrases._parse_opponents_choice`` promises
    # every lowering downstream does with the flag.
    if filt.chosen_by_opponent:
        return None
    if not _names_a_set(filt) and _restrictions_beyond(
        filt, _SACRIFICE_CARRIED_FIELDS
    ):
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
