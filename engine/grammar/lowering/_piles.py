"""How a **pile of cards** is described to a payload — a lowering floor.

Two leaves, both read by more than one family and neither belonging to either
of them:

* :func:`_linked_exile_filter` reduces a noun phrase to the payload a picker
  over a *zone* can test — the linked-exile record (CR 610.3) on one side, the
  cast permission that reads that same record on the other.
* :data:`_SEARCH_EXILE_HONOURED` is the set of narrowings a card-pile picker
  can answer at all.
* :func:`_sweep_graveyard_actor` reconciles *who empties a pile* with *whose
  pile it is* — read by `returns`' sweeps and by `exile`'s, which is exactly
  the two-families shape this floor exists for.
* :data:`OWN_PILE_SEATS`, :func:`frozen_pile_record` and
  :func:`one_card_pile_pick` say *whose* graveyard one unannounced card is
  picked out of — the picker's own, or a seat the firing event recorded — and
  build the payload naming it. Here since Odyssey, when `exile` grew three
  spellings of that one pick (Rotting Giant, Gravestorm, Zombie Cannibal).

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
from ._common import _restrictions_beyond, chargeable_card_filter
from ._frozen_seats import frozen_seat_record


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


#: Added at Urza's Destiny's wave-1 integration, when the shuffles left
#: `zones`: this leaf is read by `zones`' "put a graveyard's chosen cards on
#: top of a library" and by `shuffles`' "shuffle a graveyard into a library",
#: which are now two families. A leaf two families read cannot live in either
#: without one importing the other, which is what this floor is for.
def _chosen_graveyard_cards(
    filt: ast.ObjectFilter, subject: ast.TargetSpec, node
) -> dict[str, object]:
    """The payload half naming **which cards in a graveyard were chosen** — the
    narrowing and the target description, in the key names
    ``graveyard_card_matches`` reads and ``_graveyard_to_library_spec`` derives
    a picker from. One definition, because two sentences name the same set and
    differ only in what then happens to it: "put ... on top of their library in
    any order" (Drafna's Restoration) and "shuffles ... into their library"
    (Gaea's Blessing). A second copy would be a second answer to which cards the
    line may name, and the picker, the cast-time re-check and the handler all
    read it. A head noun with no card type (Misinformation's bare "cards") is
    not the absence of a narrowing but a narrowing saying "any card"; a
    supertype (Lodestone Bauble's "basic land cards") is read off the printed
    type line, which for a card in a graveyard is the whole of what there is
    (CR 613.1). Dropping either is a strictly better card than the one printed.
    """
    if len(filt.card_types) > 1:
        raise LoweringError(
            "the graveyard-to-library handler narrows by one card type", node=node
        )
    leftover = _restrictions_beyond(
        filt,
        frozenset({"card_types", "is_card", "zone", "zone_owner", "supertypes"}),
    )
    if leftover:
        raise LoweringError(
            f"the graveyard-to-library handler does not honour {leftover[0]!r}",
            node=node,
        )
    return {
        **(
            {"card_type": filt.card_types[0]} if filt.card_types
            else {"any_card": True}
        ),
        **({"supertypes": list(filt.supertypes)} if filt.supertypes else {}),
        # "Any number" prints no ceiling, so the only cap is how many legal
        # targets there are — a number the picker knows and this lowering does
        # not. "Up to three" (Reinforcements) prints one, and it rides the same
        # description every counted target list uses.
        # The **printed** quantifier, not "up_to" for everything counted: a
        # bare "target creature card" (Volrath's Stronghold) is a target the
        # announcement must fill and "up to one" is one it may decline, and
        # CR 602.2b refuses the activation of the first with nothing paid. The
        # count is the same number either way, so every card written before
        # "target" was admitted here sends a byte-identical payload.
        "targets": (
            {"quantifier": "any_number", "kind": "card", "unbounded": True}
            if subject.quantifier == "any_number"
            else {
                "quantifier": subject.quantifier, "kind": "card",
                "count": int(subject.count or 1),
            }
        ),
    }


#: Whose pile an **unannounced** pick of one card comes out of when the seat
#: performing the exile picks from its *own* graveyard: ``{printed owner:
#: payload value}``. "You may exile a land card from **your** graveyard"
#: (Forgotten Harvest) is the resolution's controller; "**target opponent**
#: may exile a card from their graveyard" (Gravestorm) is the seat the offer
#: was made to, which the offer leaves in ``context.target``. A different value
#: rather than "you" for that seat, because the handler reads "you" as the
#: caster.
OWN_PILE_SEATS = {
    "you": "you",
    "target_opponent": "offered_player",
    "target_player": "offered_player",
}


def frozen_pile_record(owner, event: str | None) -> str | None:
    """Which **recorded** seat's graveyard a printed possessive names under
    *event*, as the payload value the handler reads — or None when the firing
    event froze no seat for it.

    "Whenever this creature deals combat damage to a player, you may exile
    target card from **that player's** graveyard." (Zombie Cannibal.) The pile
    is not chosen and not the controller's: it is the seat the event was about
    (``frozen_seat_record`` — the damaged player for "that player", CR 506.2's
    defender for "defending player"), so a card cannot come out of anybody
    else's graveyard however the pick is made.

    "That player's" and "their" reach here as the noun parser's ``owner``
    (``zones.accept_zone_possessive`` reads the two as one node), so the word
    asked of the event is "that player".
    """
    kind = getattr(owner, "kind", None)
    word = {"owner": "that_player"}.get(kind, kind)
    return None if word is None else frozen_seat_record(word, event)


def one_card_pile_pick(filt: ast.ObjectFilter, pile_owner: str, node) -> dict[str, object]:
    """The payload for **one card, picked as the effect resolves, out of one
    named graveyard** — ``exile_cards_from_graveyard``'s keys with a count of
    one and no ``targets`` description, so the handler prompts over exactly
    that pile.

    One builder for the three piles that print it (your own, the seat an offer
    was made to, a seat the event recorded), so the narrowing they may carry is
    one answer: a single card type or none, and anything else refuses rather
    than being picked from a wider set than the card names.

    Key order is the one this payload has always had — the differential
    compares reprs, and a reordering moves every card that prints it.
    """
    leftover = _restrictions_beyond(
        filt, frozenset({"card_types", "zone", "zone_owner", "is_card"})
    )
    if leftover or len(filt.card_types) > 1:
        raise LoweringError(
            "the chosen graveyard exile reads one card type", node=node
        )
    chosen: dict[str, object] = {
        "count": 1, "graveyard_owner": pile_owner, "up_to": False,
    }
    if filt.card_types:
        chosen["card_type"] = filt.card_types[0]
    else:
        chosen["any_card"] = True
    return chosen


def _sweep_graveyard_actor(node, subject) -> str | None:
    """Who performs a sweep out of a graveyard — ``"each_player"``, ``"you"``,
    or None when the sentence's two halves cannot be reconciled.

    The actor and the graveyard's possessive are checked **against each other**
    rather than either being read alone: "each player … from their graveyard"
    is one claim said twice, and who returns the cards is the whole difference
    between All Hallow's Eve and a card that wins the game. One function
    because the two destinations ask it identically — a second copy is how the
    battlefield sweep and the hand sweep end up disagreeing about whose pile
    they empty.
    """
    actor = node.actor.kind if node.actor is not None else None
    owner = (
        subject.filter.zone_owner.kind
        if subject.filter.zone_owner is not None
        else None
    )
    if actor == "each_player" and owner in ("owner", "each_player"):
        return "each_player"
    # "Return all basic land cards from **all graveyards** …" (Planar Birth).
    # The plural pile with no printed subject in front of it: the spell's
    # controller performs the move, but every graveyard on the table is swept,
    # which is the same set of piles "each player … their graveyard" names.
    # Read here rather than as a second `who`, because what the handler does
    # with the pair is identical — each card comes back under its own player's
    # side either way, and that is CR 400.3 rather than a choice this sentence
    # makes.
    if actor is None and owner == "each_player":
        return "each_player"
    if actor is None and owner == "you":
        return "you"
    return None
