"""Lowering **permission** sentences (CR 601.3) — "you may cast/play/look at".

Split out of ``lowering/exile.py`` at Alliances' third wave, when that module
crossed the 1,000-line guard on Gustha's Scepter's face-down exile. The line is
the CR's own: everything left in ``exile`` **moves an object** into or out of
the exile zone (CR 406), where every production here moves nothing at all — it
grants a player permission to do something the rules alone would not allow, and
the objects it names are wherever they already were.

The two halves share no lowering. What they do share is how a pile of cards is
described to a payload, and that lives one floor down in ``_piles`` rather than
in either of them, because a leaf two families read cannot live in one without
the other importing it.

``mode="look"`` is here for the same reason the cast permissions are: "You may
look at it for as long as it remains exiled" (Gustha's Scepter) is CR 611.2a's
duration over a CR 406.3 face-down card, one printed sentence away from Ice
Cauldron's "you may cast that card for as long as it remains exiled" — but it
lowers to its **own** instruction kind, so a seat that may see a card can never
be found to have permission to cast it.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import _restrictions_beyond
from ._piles import _SEARCH_EXILE_HONOURED, _linked_exile_filter


def _lower_cast_from_exiled_with(
    node: ast.CastFromExiledWith,
) -> tuple[OracleInstruction, ...]:
    """"Until end of turn, you may cast a creature spell from among cards exiled
    with this artifact without paying its mana cost." (Idol of Endurance.)

    Not a new mechanism: this is CR 601.3 permission over the exile zone, which
    ``grant_cast_permission`` already is. What differs is only which pile —
    ``cards_from`` names it, where "exiled_cards" reads a step of this same
    effect and "exiled_with_source" reads the permanent's own linked pile.
    """
    return (
        OracleInstruction(
            "grant_cast_permission", "",
            {
                "zone": "exile",
                "mode": "cast",
                "cards_from": "exiled_with_source",
                "filter": _linked_exile_filter(node.filter),
                "free": node.free,
                "duration": "end_of_turn",
            },
        ),
    )


#: Which printed duration an "exiled this way" permission carries, keyed by the
#: three flags the parser sets. A key with two of them set is deliberately
#: absent: a sentence stating two durations is one this cannot honour, and
#: picking either would be a permission that ends at a moment the card does not
#: name.
_EXILED_PERMISSION_DURATIONS: dict[tuple[bool, bool, bool, bool], str] = {
    (True, False, False, False): "end_of_turn",
    (False, True, False, False): "until_source_grants_again",
    (False, False, True, False): "your_next_upkeep",
    # "…for as long as it remains exiled" (Ice Cauldron). Nothing sweeps it:
    # ``cast_permissions._covers`` re-checks the card is still in the granted
    # zone on every read, which *is* the printed duration. Stated rather than
    # lowered as "no duration", which is what a card saying nothing means.
    (False, False, False, True): "while_exiled",
}


def _lower_cast_permission(
    node: ast.CastPermission, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """A cast-or-play permission sentence (CR 601.3), one instruction kind for
    all its printed forms — the differences are payload:

    * ``exiled_this_way`` reads the cards a step of this same effect exiled,
      so it demands the producer exactly as "that much" life does — a
      permission with nothing to permit is the sentence read wrong;
    * ``target_card`` carries the chosen graveyard card and the "exile it
      instead" rider, and deliberately no duration (CR 611.2a);
    * ``spells_from_hand`` is a cost waiver and must carry one, or it would
      state the rules default.
    """
    if node.mode == "look":
        # "You may look at it for as long as it remains exiled." (Gustha's
        # Scepter.) Its own kind rather than ``grant_cast_permission`` with a
        # third mode: the cast permission is a CR 601.3 answer to "may I put
        # this on the stack?", read by ``engine/cast_permissions.py`` every
        # time a cast is proposed, and a seat that may *see* a card may not
        # thereby cast it. Routed here so no reading of this sentence can
        # reach that one.
        if node.what != "exiled_this_way":
            raise LoweringError(
                "a look permission reads the cards this effect exiled", node=node
            )
        if "exiled_cards" not in produced:
            raise LoweringError(
                "back-reference to the exiled card with no exile in this effect",
                node=node,
            )
        if not node.while_exiled:
            # The one duration this is printed with. Refused rather than
            # defaulted for ``_EXILED_PERMISSION_DURATIONS``' reason: a look
            # that outlives the exile is a card the seat keeps reading after it
            # has gone back to a hand nobody may see.
            raise LoweringError(
                "a look permission lasts for as long as the card remains exiled",
                node=node,
            )
        return (
            OracleInstruction(
                "grant_look_at_exiled_cards", "",
                {"cards_from": "exiled_cards", "duration": "while_exiled"},
            ),
        )
    if node.what == "exiled_this_way":
        if "exiled_cards" not in produced:
            raise LoweringError(
                "back-reference to 'cards exiled this way' with no exile "
                "in this effect",
                node=node,
            )
        # A *stated* duration is required (CR 611.2a), but there are now two of
        # them. Without one the permission outlives the card that granted it;
        # read as the wrong one it is wrong in a stated direction — end-of-turn
        # discards Furious Rise's card at the next cleanup, and no-duration
        # leaves every card it has ever exiled playable at once.
        # A *stated* duration is required (CR 611.2a), and there are three of
        # them now. Which one is load-bearing: end-of-turn discards Elkin
        # Bottle's card at this cleanup, your-next-upkeep keeps it a turn, and
        # no-duration leaves every card the source ever exiled playable at once.
        stated = _EXILED_PERMISSION_DURATIONS.get(
            (
                node.until_end_of_turn,
                node.until_source_grants_again,
                node.until_your_next_upkeep,
                node.while_exiled,
            )
        )
        if stated is None:
            raise LoweringError(
                "an exiled-cards permission needs exactly one printed duration, "
                "or it would outlive the card that granted it",
                node=node,
            )
        return (
            OracleInstruction(
                "grant_cast_permission", "",
                {
                    "zone": "exile",
                    "mode": node.mode,
                    "cards_from": "exiled_cards",
                    "duration": stated,
                },
            ),
        )

    if node.what == "target_card":
        spec = node.target
        filt = spec.filter if spec is not None else None
        if node.mode != "cast" or filt is None:
            raise LoweringError("a targeted permission casts a chosen card", node=node)
        if filt.zone != "graveyard" or filt.zone_owner is None or filt.zone_owner.kind != "you":
            raise LoweringError(
                "the graveyard cast permission reads the caster's own "
                f"graveyard, not the {filt.zone}",
                node=node,
            )
        leftover = _restrictions_beyond(
            filt, _SEARCH_EXILE_HONOURED | {"zone", "zone_owner"}
        )
        if leftover:
            raise LoweringError(
                "the graveyard cast picker cannot test this restriction: "
                + ", ".join(leftover),
                node=node,
            )
        return (
            OracleInstruction(
                "grant_cast_permission", "",
                {
                    "zone": "graveyard",
                    "mode": "cast",
                    "target_graveyard_card": True,
                    "card_types": tuple(filt.card_types),
                    "colors": tuple(filt.colors),
                    "exile_instead": node.exile_instead,
                    "duration": "end_of_turn" if node.until_end_of_turn else None,
                },
            ),
        )

    if node.what == "spells_from_hand":
        if not node.free:
            raise LoweringError(
                "a hand permission without a cost waiver states the rules "
                "default",
                node=node,
            )
        if not node.until_end_of_turn:
            raise LoweringError(
                "an unbounded cost waiver is a different card", node=node
            )
        return (
            OracleInstruction(
                "grant_cast_permission", "",
                {
                    "zone": "hand",
                    "mode": "cast",
                    "free": True,
                    "duration": "end_of_turn",
                },
            ),
        )

    raise LoweringError(f"no cast-permission lowering for {node.what!r}", node=node)
