"""Lowering the zone changes: where an object goes (CR 400).

Split out of `lowering/board.py` when that file crossed 1,000 lines. A family
rather than an arbitrary cut: everything here answers one question — which zone
does this object end up in — and none of it touches the battlefield state the
rest of `board` is about (tapping, destruction, regeneration, control).

It has no twin in `effects/`, and that is deliberate rather than an oversight.
The parsing side of these templates is small — one `return`/`exile`/`put`
production each, all still in `effects/board.py` — while the lowering side is
where the work is, because every one of them has to decide *which* handler moves
the object and refuse the shapes none of them implement. A near-empty
`effects/zones.py` would buy the symmetry and cost the thing symmetry is for.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from ...subject_filters import card_only_filter
from .. import ast
from ..errors import LoweringError
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS,
    dropped_narrowings,
    _describe_targets,
    _filter_payload,
    _is_target,
    _restrictions_beyond,
)


# The filter both exile shapes are compared against. Two readers, one
# definition — an equality check written twice is two chances to widen one
# of them.


def _lower_put_on_library_top(node: ast.PutOnLibraryTop) -> tuple[OracleInstruction, ...]:
    """"Put target creature on top of its owner's library." (Teferi, Timeless
    Voyager's −3.) One chosen battlefield creature; the owner is resolved by
    the handler (CR 400.3), which is why no player rides the payload."""
    if (
        isinstance(node.target, ast.TargetSpec)
        and node.target.quantifier == "any_number"
    ):
        return _lower_graveyard_cards_on_library_top(node)
    if not _is_target(node.target):
        raise LoweringError("the tuck handler resolves one chosen creature", node=node)
    assert isinstance(node.target, ast.TargetSpec)
    filt = node.target.filter
    if filt.card_types != ("creature",) or filt.zone != "battlefield" or filt.is_card:
        raise LoweringError("the tuck handler reads battlefield creatures", node=node)
    payload: dict[str, object] = {}
    _describe_targets(payload, node.target)
    return (OracleInstruction("put_target_on_library_top", "", payload),)


def _lower_ownership_exchange_unless_paid(
    node: "ast.OwnershipExchangeUnlessPaid",
) -> tuple[OracleInstruction, ...]:
    """Bronze Tablet. The life total and the target's noun phrase are payload;
    every other word was required by the production that read it."""
    from ...subject_filters import object_only_filter

    described = _filter_payload(node.target, carried_separately=frozenset({"owner"}))
    described.pop("owner", None)
    if object_only_filter(described) is None:
        raise LoweringError(
            "the ownership exchange cannot test that phrase", node=node
        )
    payload: dict[str, object] = {
        "life": node.life,
        # The ownership half is carried separately from the rest of the filter:
        # the picker and the handler both ask `subject_matches`, which needs the
        # ability's controller to answer "an opponent owns" at all.
        "owner": node.target.owner,
        "filter": described,
    }
    _describe_targets(
        payload,
        ast.TargetSpec("target", node.target, targeted=True),
        carried_separately=frozenset({"owner"}),
    )
    return (OracleInstruction("exchange_ownership_unless_paid", "", payload),)


def _lower_graveyard_cards_on_library_top(
    node: ast.PutOnLibraryTop,
) -> tuple[OracleInstruction, ...]:
    """"Put any number of target artifact cards from target player's graveyard
    on top of their library in any order." (Drafna's Restoration.)

    A different handler from the tuck above, not a count on it: that one moves
    a *permanent* off the battlefield, and this moves **cards** out of a
    graveyard — different zone, different objects, and a graveyard slot is not
    a battlefield slot (CR 400.1).

    Narrowed to exactly what the handler reads. "Their library" and "its
    owner's library" are the same place here (CR 404.1 puts a card in the
    graveyard of the player who owns it), so no player rides the payload; the
    seat comes from the spell's chosen target player.
    """
    subject = node.target
    assert isinstance(subject, ast.TargetSpec)
    filt = subject.filter
    if not subject.targeted:
        raise LoweringError(
            "the graveyard-to-library handler moves chosen cards", node=node
        )
    if not filt.is_card or filt.zone != "graveyard":
        raise LoweringError(
            "the graveyard-to-library handler reads cards in a graveyard", node=node
        )
    if filt.zone_owner is None or filt.zone_owner.kind != "target_player":
        raise LoweringError(
            "the graveyard-to-library handler reads a chosen player's graveyard",
            node=node,
        )
    if len(filt.card_types) != 1:
        raise LoweringError(
            "the graveyard-to-library handler narrows by one card type", node=node
        )
    leftover = _restrictions_beyond(
        filt, frozenset({"card_types", "is_card", "zone", "zone_owner"})
    )
    if leftover:
        raise LoweringError(
            f"the graveyard-to-library handler does not honour {leftover[0]!r}",
            node=node,
        )
    return (
        OracleInstruction(
            "put_graveyard_cards_on_library_top", "",
            {
                "card_type": filt.card_types[0],
                # "In any order" is the printed rider, and it is the *only*
                # thing that says the controller decides the sequence. Recorded
                # rather than consumed: a card printing it and one not printing
                # it are different cards, and the handler reads the order the
                # targets were named in.
                "in_any_order": node.in_any_order,
                # Unbounded rather than a maximum: "any number" prints no
                # ceiling, so the only cap is how many legal targets there are —
                # a number the picker knows and this lowering does not.
                "targets": {"quantifier": "any_number", "kind": "card", "unbounded": True},
            },
        ),
    )


def _lower_put_onto_battlefield(node: ast.PutOntoBattlefield) -> tuple[OracleInstruction, ...]:
    """The two "put … onto the battlefield" shapes the pool prints:

    * "Put up to seven permanent cards from your hand onto the battlefield."
      (Ugin, the Spirit Dragon's −10) — an up-to-N sweep of the caster's own
      hand, chosen by its controller.
    * "Put target creature card from a graveyard onto the battlefield under
      your control." (Liliana, Waker of the Dead's emblem) — a one-card
      reanimation from any graveyard, with any granted keywords riding along
      ("It gains haste.").
    """
    target = node.target
    if not isinstance(target, ast.TargetSpec):
        raise LoweringError("no handler puts that onto the battlefield", node=node)
    filt = target.filter
    if filt.zone == "hand":
        if filt.zone_owner is None or filt.zone_owner.kind not in ("you", "owner"):
            raise LoweringError("only your own hand has a handler here", node=node)
        # "…put **a** permanent card from their hand onto the battlefield."
        # (Eureka.) One card, chosen — where the sweep below takes a whole
        # "up to N" slice with nothing to decide. The pick is the effect, so it
        # is its own instruction rather than a count of one handed to the sweep:
        # the seat picks a card, and declining is one of the answers whenever
        # the sentence that carried this said "may".
        #
        # "their hand" is the hand of whoever the offer was made to, which is
        # why the owner spelling is admitted at all; "your hand" is the caster's.
        if target.quantifier in ("a", "an") and filt.is_card:
            # The zone and its owner are read on the two lines above, so they
            # are honoured in the sense this check means; anything *else* the
            # phrase printed has to survive into the payload, because a
            # narrowing dropped here is a card the seat may pick that the
            # sentence never offered.
            if _restrictions_beyond(
                filt, _PAYLOAD_HONOURED_FILTER_FIELDS | {"is_card", "zone", "zone_owner"}
            ):
                raise LoweringError(
                    "the from-hand pick cannot test that card phrase", node=node
                )
            payload = filt.to_payload()
            payload.pop("zone", None)
            payload.pop("zone_owner", None)
            described = card_only_filter(payload)
            if described is None or dropped_narrowings(filt, payload):
                raise LoweringError(
                    "the from-hand pick cannot test that card phrase", node=node
                )
            return (
                OracleInstruction(
                    "put_chosen_card_from_hand_onto_battlefield",
                    "",
                    {
                        "card_filter": described,
                        # An empty type list with is_card means "permanent
                        # cards", the same reading the sweep below takes.
                        "permanents_only": not filt.card_types,
                        "whose": "offered" if filt.zone_owner.kind == "owner" else "you",
                    },
                ),
            )
        if filt.zone_owner.kind != "you":
            raise LoweringError("only your own hand has a handler here", node=node)
        if target.quantifier != "up_to" or not filt.is_card:
            raise LoweringError("the from-hand handler reads 'up to N … cards'", node=node)
        return (
            OracleInstruction(
                "put_cards_from_hand_onto_battlefield",
                "",
                {
                    "count": target.count,
                    "card_types": list(filt.card_types),
                    # An empty type list with is_card means "permanent cards" —
                    # the handler holds the CR 110.4 list of permanent types.
                    "permanents_only": not filt.card_types,
                },
            ),
        )
    if filt.zone == "graveyard":
        if not _is_target(target) or not filt.is_card:
            raise LoweringError("the reanimation handler reads one chosen card", node=node)
        if filt.card_types != ("creature",):
            raise LoweringError("the reanimation handler only moves creature cards", node=node)
        return (
            OracleInstruction(
                "reanimate_creature",
                "",
                {
                    # "from a graveyard" (no owner) widens the search to every
                    # player's graveyard; "under your control" is CR 400.3's
                    # exception spelled out, honored by the handler.
                    "any_graveyard": filt.zone_owner is None,
                    "under_your_control": node.under_your_control,
                    "gains": list(node.gains),
                },
            ),
        )
    raise LoweringError("no handler for this battlefield entry", node=node)

def _lower_shuffle_graveyard_into_library(
    node: ast.ShuffleGraveyardIntoLibrary,
) -> tuple[OracleInstruction, ...]:
    """Feldon's Cane. Whose graveyard is on the payload even though only one
    value is printed today — the alternative is a kind that would have to be
    replaced the first time a card says "target player's"."""
    return (
        OracleInstruction(
            "shuffle_graveyard_into_library", "", {"whose": node.whose.kind}
        ),
    )


def _lower_shuffle_hand_into_library(
    node: ast.ShuffleHandIntoLibrary,
) -> tuple[OracleInstruction, ...]:
    """Winds of Change.

    Whose hands move is payload, the way the graveyard shuffle above carries
    whose graveyard does — and the draw rides the same instruction rather than
    following it, because the number it draws is the number this move made.
    Only the two subjects the handler loops over are admitted: "target player"
    would name a seat the handler does not resolve, and a subject it cannot
    resolve is a shuffle taken on the wrong library.
    """
    if node.whose.kind not in ("each_player", "you"):
        raise LoweringError(
            f"no handler shuffles {node.whose.kind!r}'s hand into their library",
            node=node,
        )
    return (
        OracleInstruction(
            "shuffle_hand_into_library",
            "",
            {"whose": node.whose.kind, "then_draw": node.then_draw},
        ),
    )


def _lower_random_reveal_ownership_exchange(
    node: "ast.RandomRevealOwnershipExchange",
) -> tuple[OracleInstruction, ...]:
    """Tempest Efreet. The life total is payload; the target is the printed
    "target opponent", described the way every other player target is so the
    activation picker and the handler ask one question."""
    return (
        OracleInstruction(
            "random_reveal_ownership_exchange", "",
            {
                "life": node.life,
                "targets": {
                    "quantifier": "target",
                    "kind": "player",
                    "opponents_only": True,
                },
            },
        ),
    )
