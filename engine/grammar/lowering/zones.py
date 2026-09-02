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
from ...damage_deaths import DAMAGED_BY_SOURCE_DIED
from ._events import BOUND_CARD_EVENTS
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
    # Which of the two handlers reads this sentence is decided by the **zone**
    # the noun phrase names, not by the quantifier. It was decided by "any
    # number" alone, which is a fact about how many cards move rather than about
    # where they come from — so "put **up to three** target creature cards from
    # your graveyard on top of your library" (Reinforcements) fell through to the
    # battlefield tuck and refused, naming a creature it never mentioned.
    if (
        isinstance(node.target, ast.TargetSpec)
        and (node.target.filter.zone == "graveyard" or node.target.filter.is_card)
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
    # "Any number of" (Drafna's Restoration) and "up to three" (Reinforcements)
    # are the two ceilings this handler can honour. Any other quantifier names a
    # different set — "target" is one card and "all" chooses nothing — and the
    # handler resolves a *list* of chosen slots, so it would either move one card
    # where the sentence said several or move several where it said one.
    if subject.quantifier not in ("any_number", "up_to"):
        raise LoweringError(
            "the graveyard-to-library handler moves a chosen list of cards",
            node=node,
        )
    if not filt.is_card or filt.zone != "graveyard":
        raise LoweringError(
            "the graveyard-to-library handler reads cards in a graveyard", node=node
        )
    # Two seats the sentence can name, and the printed destination has to agree
    # with the printed source: "target player's graveyard … their library"
    # (Drafna's Restoration) follows whoever was chosen, "your graveyard … your
    # library" (Reinforcements) is the ability's controller both times. A
    # sentence pairing one with the other would move cards between two players'
    # zones, which is a card nobody has printed and a handler this one is not.
    owner_kind = filt.zone_owner.kind if filt.zone_owner is not None else None
    if owner_kind == "target_player" and node.to_owner == "owner":
        graveyard_owner = "target_player"
    elif owner_kind == "you" and node.to_owner == "you":
        graveyard_owner = "you"
    else:
        raise LoweringError(
            "the graveyard-to-library handler reads one player's graveyard into "
            "that same player's library",
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
                # Whose graveyard, and therefore whose library. Emitted always
                # rather than only for the newer reading, because the handler
                # reading a missing key as "the chosen target player" is exactly
                # the silent default this pair of seats exists to remove.
                "graveyard_owner": graveyard_owner,
                # "Any number" prints no ceiling, so the only cap is how many
                # legal targets there are — a number the picker knows and this
                # lowering does not. "Up to three" (Reinforcements) prints one,
                # and it rides the same description every counted target list
                # uses.
                "targets": (
                    {"quantifier": "any_number", "kind": "card", "unbounded": True}
                    if subject.quantifier == "any_number"
                    else {
                        "quantifier": "up_to", "kind": "card",
                        "count": int(subject.count or 1),
                    }
                ),
            },
        ),
    )


def _lower_put_onto_battlefield(
    node: ast.PutOntoBattlefield, event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """The three "put … onto the battlefield" shapes the pool prints:

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
    if target.quantifier == "that" and filt.is_card:
        # "Put **that card** onto the battlefield under your control." (Seraph,
        # Krovikan Vampire.) The bound object, not a choice: the firing event
        # named the creature that died, and by the time this resolves its card
        # is in a graveyard. So the handler reads it out of the trigger's
        # context by identity rather than off a target index or a zone scan —
        # the arrangement ``return_bound_card_to_owners_hand`` already uses for
        # the same phrase and the same reason.
        #
        # Gated on the event recording one, exactly as the bound-card return is:
        # under any other event these words name a card nobody wrote down, and
        # the handler would find nothing while the card compiled supported.
        from_ledger = event == DAMAGED_BY_SOURCE_DIED
        if not from_ledger and event not in BOUND_CARD_EVENTS:
            raise LoweringError(
                "'that card' names the firing event's object, and this event "
                "records none",
                node=node,
            )
        if not node.under_your_control:
            raise LoweringError(
                "the bound-card reanimation only puts it under your control",
                node=node,
            )
        if _restrictions_beyond(filt, frozenset({"is_card"})) or node.gains:
            raise LoweringError(
                "the bound-card reanimation honours no further narrowing",
                node=node,
            )
        payload: dict[str, object] = {}
        if from_ledger:
            # Krovikan Vampire's "that card" is not one the fire site froze — no
            # end step freezes a card — but the one its own intervening-if
            # found, in the ledger on the ability's source. Payload, so one
            # handler reads either record rather than two kinds doing the same
            # move from two places.
            payload["from_damage_deaths"] = True
        if node.sacrifice_when_control_lost:
            # The rider is carried out by the instruction that makes the
            # permanent, because there is no permanent to link until it does
            # (``engine/linked_sacrifice.py``).
            payload["sacrifice_when_control_lost"] = True
        return (OracleInstruction("reanimate_bound_card", "", payload),)
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
    if node.count is not None:
        # "Shuffle **a card** from your hand into your library."
        # (Lat-Nam's Legacy.) Its own kind rather than a count on the sweep
        # above, because a counted subset of a hidden zone is a *decision*
        # (CR 402.1: only its owner may look) where a whole hand is a move. The
        # handler arms the prompt that asks it; the sweep above has nothing to
        # ask.
        if node.then_draw:
            # "…then draws that many cards" counts what the whole-hand move
            # took. Behind a printed number the phrase would be that number
            # said twice, and no card prints the pair — so it refuses rather
            # than guessing which of the two the sentence meant.
            raise LoweringError(
                "a counted shuffle has no 'that many' to draw", node=node
            )
        if node.whose.kind != "you":
            raise LoweringError(
                "a counted shuffle into a library is the controller's own hand",
                node=node,
            )
        return (
            OracleInstruction(
                "shuffle_hand_cards_into_library", "", {"amount": node.count},
            ),
        )
    return (
        OracleInstruction(
            "shuffle_hand_into_library",
            "",
            {
                "whose": node.whose.kind,
                "then_draw": node.then_draw,
                # "…their hand **and graveyard** into their library."
                # (Diminishing Returns.) A second pile in the same move, and a
                # flag on the same instruction rather than a second one for the
                # reason the node records: CR 701.19 shuffles the library once.
                "with_graveyard": node.with_graveyard,
            },
        ),
    )


#: The seats a bare shuffle can name. "You" is the imperative's subject; the
#: other three are a player an earlier sentence of the same effect chose, which
#: the handler reads off the resolution's target. A reference outside this — an
#: "each opponent", say — is a loop the handler does not have, and a shuffle
#: taken on one library while the card names several is the direction nothing
#: crashes and the card is quietly a different card.
_SHUFFLE_LIBRARY_PLAYERS = frozenset(
    {"you", "that_player", "target_player", "target_opponent"}
)


#: The seats a reveal of a library's top card can name — the same four the
#: shuffle below admits, and for the same reason: a reveal opens one library,
#: and a reference the handler cannot resolve is a card revealed off the wrong
#: deck and recorded under a name every sentence behind it then reads.
_REVEAL_TOP_PLAYERS = frozenset(
    {"you", "that_player", "target_player", "target_opponent"}
)


def _lower_reveal_top_of_library(
    node: ast.RevealTop,
) -> tuple[OracleInstruction, ...]:
    """"Reveal the top card of target opponent's library." (Prophecy.)
    "Reveal the top card of your library." (Track Down.)

    CR 701.20a: the card is shown and moves nowhere, so the effect is the
    record it leaves — which is why *whose* library it came off has to reach
    the handler. Unstated, the handler reads the caster's own deck, and a
    Prophecy that revealed its controller's top card would gain life off the
    wrong library and shuffle a deck nobody looked at.

    ``whose`` is emitted only when the card names somebody else, so every
    reveal written before this keeps a byte-identical payload and the
    behaviour signatures do not move.
    """
    if node.player.kind not in _REVEAL_TOP_PLAYERS:
        raise LoweringError(
            f"no handler reveals the top of {node.player.kind!r}'s library",
            node=node,
        )
    if node.player.kind == "you":
        return (OracleInstruction("reveal_top_of_library", "", {}),)
    payload: dict[str, object] = {"whose": node.player.kind}
    if node.player.kind != "that_player":
        _describe_targets(payload, node.player)
    return (OracleInstruction("reveal_top_of_library", "", payload),)


def _lower_shuffle_library(node: ast.ShuffleLibrary) -> tuple[OracleInstruction, ...]:
    """"Then that player shuffles." (Prophecy.) CR 701.16 with nothing moving.

    Whose library is payload, exactly as the two shuffles above carry whose
    pile moves. ``that_player`` is deliberately **not** described as a target:
    it names a seat an earlier sentence of this same effect already chose, and
    describing it would raise a second picker for a target the spell has.
    """
    if node.whose.kind not in _SHUFFLE_LIBRARY_PLAYERS:
        raise LoweringError(
            f"no handler shuffles {node.whose.kind!r}'s library", node=node
        )
    payload: dict[str, object] = {"whose": node.whose.kind}
    if node.whose.kind in ("target_player", "target_opponent"):
        # A shuffle that *chooses* its player is the one spelling that needs a
        # picker; the sentence naming one an earlier step chose does not.
        _describe_targets(payload, node.whose)
    return (OracleInstruction("shuffle_library", "", payload),)


def _lower_ante_offer_ownership_exchange(
    node: "ast.AnteOfferOwnershipExchange",
) -> tuple[OracleInstruction, ...]:
    """Timmerian Fiends. The printed card type is payload, described the way
    every other object target is so the activation picker, the CR 602.2b
    legality gate and the handler all ask one question."""
    return (
        OracleInstruction(
            "ante_or_exchange_ownership", "",
            {
                "type_word": node.type_word,
                "targets": {
                    "quantifier": "target",
                    "kind": "object",
                    "filter": {"type_filter": node.type_word},
                },
                "type_filter": node.type_word,
            },
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
