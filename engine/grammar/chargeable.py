"""Whether the payment path can collect a printed cost object.

The three gates the cost clause asks before it admits a "Sacrifice <noun>",
"Exile <noun>" or "Put a counter on <noun>" — and they are one module because
they are one question asked in three zones: *can the charger actually enumerate
what this phrase names, and hold the payment to every narrowing it prints?*

Each of them answers by calling ``engine/oracle.py``'s own reader rather than
re-deriving a reduction here. That is the whole design: the two halves of a
cost — this one, which decides whether to admit the line, and the charger,
which collects it — must give the same answer, and they give it by being one
function. A phrase one admits and the other refuses is an ability the grammar
let through and nothing paid for, which is an ability activated for free.

Split out of `costs.py` at the size guard when the sacrifice gate grew its
battlefield-zone and unhonoured-field checks. The cut is the one the lowering
side already made: `lowering/_filters.py`'s docstring calls these "the two cost
gates that answer 'may this phrase be charged?'", so `chargeable` is the word
both halves already use rather than a new one.

Sits below `costs`, its only caller, and reads noun phrases and the filter
floor — nothing above it.
"""

from __future__ import annotations

from ..subject_filters import object_only_filter
from . import ast
from .lowering._common import (_PAYLOAD_HONOURED_FILTER_FIELDS,
                               _restrictions_beyond)


def _is_chargeable_sacrifice(filt: ast.ObjectFilter) -> bool:
    """Whether the payment path can actually collect this sacrifice cost.

    A rider the charger cannot express must refuse the line rather than be
    dropped — dropped, Portcullis Vine sacrifices any creature at all while
    still reporting supported, which is the dropped-rider bug class.

    Which riders those are is **not** decided here. This asks the charger's own
    reader (``engine/oracle.py``'s ``_chargeable_sacrifice_filter``, through the
    filter-key set it gates on), because two readers of one clause drift and the
    direction they drift in is a cost nobody pays. The word "another" is left in
    the filter: the charger has the ability's source and compares by identity.
    """
    from ..oracle import chargeable_sacrifice_payload, cost_object_is_chargeable

    if filt.is_source:
        return True
    if filt.is_enchanted:
        # "**Sacrifice enchanted creature**: …" (Betrothed of Fire). The host,
        # not a chosen permanent — CR 303.4m's "enchanted [object]" (and
        # CR 301.5f's "equipped") names one object and the attachment record
        # is the whole answer, so there is
        # nothing for a filter to narrow. It is chargeable for
        # :attr:`is_source`'s reason one branch up and charged in the same
        # field family (``ActivatedAbilityCost.sacrifice_attached``); read as a
        # *filter* it would have been "sacrifice a creature", which is the
        # printed cost with its one word dropped.
        return True
    # A permanent on a battlefield and nothing else: CR 701.21a lets a player
    # sacrifice only a permanent they control, so a phrase naming a card in a
    # zone is not a payable sacrifice at all and the reduction below would read
    # it as a permanent.
    if filt.zone != "battlefield" or filt.is_card:
        return False
    # A restriction with no ``to_payload`` key at all vanishes before any key
    # check can see it — the AST gate ``_is_chargeable_exile`` has asked since
    # it was written, missing here. It mattered less while the reduction had to
    # carry *something*, because a phrase whose only narrowing was unhonoured
    # reduced to nothing and was refused for that; with the empty reduction now
    # a real answer ("a permanent", Claws of Gix) this is the gate that keeps a
    # dropped rider from becoming a wider cost.
    if _restrictions_beyond(
        filt, _PAYLOAD_HONOURED_FILTER_FIELDS | {"zone", "zone_owner", "is_card"}
    ):
        return False
    # The charger's own reader, not a second reduction spelled here: it drops
    # ``controller`` (a sacrifice is paid off the payer's own battlefield, so
    # "creatures **you control**" narrows nothing the enumeration has not
    # already done), re-adds ``exclude_self`` (the charger holds the source and
    # compares by identity) and refuses a phrase naming anybody else's
    # permanent. Spelled here instead, the two halves disagreed about the last
    # of those: this admitted "an opponent controls" and the charger refused it,
    # which is a cost the grammar let through and nothing paid.
    carried = chargeable_sacrifice_payload(filt.to_payload())
    return cost_object_is_chargeable(carried)


def _is_chargeable_exile(filt: ast.ObjectFilter) -> bool:
    """Whether the payment path can actually collect this exile cost.

    :func:`_is_chargeable_sacrifice` one zone wider, and the same rule: the
    charger's own reader decides (``engine/oracle.py``'s
    ``chargeable_exile_payload``), so the two halves cannot answer differently.

    Two zones and no others. The battlefield is a permanent the payer controls;
    a **graveyard** is a card, and only the payer's own — "from your graveyard"
    is what Necropolis prints, and a phrase naming somebody else's pile is a
    cost this charger has no enumeration for.
    """
    from ..oracle import chargeable_exile_payload, cost_object_is_chargeable

    if filt.zone == "graveyard":
        # Whose pile. "your graveyard" (Necropolis) is the payer's own; **no
        # owner at all** is "a graveyard" — anybody's — which the charger
        # enumerates seat by seat. Anything else (a named opponent's) is a
        # phrase this charger has no enumeration for and refuses.
        if not filt.is_card:
            return False
        if filt.zone_owner is not None and filt.zone_owner.kind != "you":
            return False
    elif filt.zone == "hand":
        # "Exile **a card from your hand**" (Cadaverous Bloom). The payer's own
        # hand and no other: a hand is hidden (CR 400.2), so a cost naming
        # somebody else's would ask a player to choose a card they cannot see.
        #
        # And it returns **here**, before the type check below, because "a
        # card" is the whole of what this cost names and it is not the
        # anything-goes phrase that check refuses. That argument is about a
        # zone the payer does not choose from freely: an untyped battlefield
        # exile would let the charger eat a land the player would never have
        # given up. A hand exile eats a card its owner picks out of their own
        # hand, which is what "a card" says and what the discard cost beside it
        # has always admitted with no type printed either.
        if not filt.is_card:
            return False
        if filt.zone_owner is None or filt.zone_owner.kind != "you":
            return False
        if _restrictions_beyond(
            filt, _PAYLOAD_HONOURED_FILTER_FIELDS | {"zone", "zone_owner", "is_card"}
        ):
            return False
        return chargeable_exile_payload(filt.to_payload()) is not None
    elif filt.zone != "battlefield" or filt.is_card:
        return False
    # A restriction with no ``to_payload`` key at all would vanish before the
    # key check below ever saw it - the failure the AST gate in
    # ``subject_filter_payload`` exists for. Asked here as well, because this
    # reader does not go through that one.
    if _restrictions_beyond(
        filt, _PAYLOAD_HONOURED_FILTER_FIELDS | {"zone", "zone_owner", "is_card"}
    ):
        return False
    carried = chargeable_exile_payload(filt.to_payload())
    # The same refusal `_is_chargeable_sacrifice` makes, through the same
    # reader, so a phrase one admits and the other refuses cannot exist.
    return cost_object_is_chargeable(carried)


def _is_chargeable_counter_target(filt: ast.ObjectFilter) -> bool:
    """Whether the payment path can find the permanent this counter goes on.

    "Put a -1/-1 counter on **a creature you control**" (Wandering Mage). The
    same two questions ``_is_chargeable_sacrifice`` asks, for the same reason:
    the payer's candidates are enumerated with ``subject_matches``, so a key it
    cannot test would be dropped — and a dropped narrowing on *this* cost is a
    counter landing somewhere the card does not name **and** an ability payable
    when it should not be.

    The phrase must also pin a card type or a subtype. Without one the cost
    could be paid by putting the counter on a land, which is no cost at all for
    a card that means to shrink a creature.
    """
    if filt.is_source:
        return True
    if not (filt.card_types or filt.subtypes):
        return False
    described = filt.to_payload()
    return not _restrictions_beyond(
        filt, _PAYLOAD_HONOURED_FILTER_FIELDS
    ) and object_only_filter(
        described, carried_separately=frozenset({"controller"})
    ) is not None
