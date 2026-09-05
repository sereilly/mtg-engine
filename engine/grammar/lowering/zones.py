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
from ._deaths import BOUND_CARD_EVENTS
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS, dropped_narrowings, _describe_targets,
    _filter_payload, _is_target, _restrictions_beyond, refuse_untestable
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
        if node.bottom_instead_colors:
            # The rider is read by the battlefield tuck alone; this handler
            # moves several cards at once and has no one object to ask about.
            # Refused rather than dropped, for the reason the branch that
            # carries it gives.
            raise LoweringError(
                "the graveyard tuck reads no end swap", node=node
            )
        return _lower_graveyard_cards_on_library_top(node)
    if not _is_target(node.target):
        raise LoweringError("the tuck handler resolves one chosen creature", node=node)
    assert isinstance(node.target, ast.TargetSpec)
    filt = node.target.filter
    if filt.zone != "battlefield" or filt.is_card:
        raise LoweringError(
            "the tuck handler moves a permanent, not a card in a zone", node=node
        )
    payload: dict[str, object] = {}
    _describe_targets(payload, node.target)
    # The printed noun phrase, whatever it is: "target **artifact or
    # enchantment**" (Disempower), "target **land**" (Fallow Earth), "target
    # creature" (Teferi, Timeless Voyager). The type used to be pinned to
    # creature here *and* in the handler, so the two Mirage cards refused at a
    # noun the tuck has no opinion about — CR 400.3's owner lookup and the
    # library move are the same for every permanent type.
    #
    # Idiom 2 as always: a narrowing the matcher cannot test would be dropped,
    # and a dropped narrowing on a *target* is a spell that moves a permanent
    # its own text did not admit.
    described = (payload.get("targets") or {}).get("filter") or {}
    refuse_untestable(described, refusal="the tuck cannot narrow by", node=node)
    # "If that creature is red, **you may put it on the bottom** of its owner's
    # library instead." (Ether Well.) One move with two possible ends, so the
    # rider is payload on the same instruction — and it is carried or the line
    # refuses, because a consumed-and-dropped rider here is a card that never
    # offers the choice it prints.
    if node.bottom_instead_colors:
        if not node.bottom_instead_optional:  # pragma: no cover - parse refuses
            raise LoweringError(
                "only an offered end swap is implemented", node=node
            )
        payload["bottom_instead_colors"] = list(node.bottom_instead_colors)
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
    # "from **an opponent's** graveyard … on top of **their** library"
    # (Misinformation) and "from **a player's** graveyard … **their** library"
    # (Lodestone Bauble). Neither chooses a player: the cards are the targets
    # and the pile is wherever they lie, so the seat is read off the chosen
    # slots exactly as it is for the chosen-player spelling above — what the
    # words add is a *restriction on which piles may be chosen from*, which
    # rides the payload and reaches the picker. The destination still has to
    # agree with the source for the reason the two seats above do: a sentence
    # pairing one player's graveyard with another's library is a card nobody
    # has printed.
    elif owner_kind == "opponent" and node.to_owner == "owner":
        graveyard_owner = "an_opponent"
    elif owner_kind == "owner" and node.to_owner == "owner":
        graveyard_owner = "any_player"
    else:
        raise LoweringError(
            "the graveyard-to-library handler reads one player's graveyard into "
            "that same player's library",
            node=node,
        )
    if len(filt.card_types) > 1:
        raise LoweringError(
            "the graveyard-to-library handler narrows by one card type", node=node
        )
    # "up to three target **cards**" (Misinformation) — a head noun with no card
    # type at all, which is not the absence of a narrowing but a narrowing that
    # says "any card". The predicate every reader of this instruction shares
    # already has the key; what it lacked was a lowering willing to emit it, so
    # a bare "cards" reached "narrows by one card type" and refused.
    any_card = not filt.card_types
    leftover = _restrictions_beyond(
        filt,
        frozenset({"card_types", "is_card", "zone", "zone_owner", "supertypes"}),
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
                # The narrowing, in the key names ``graveyard_card_matches``
                # reads — one predicate for the picker, the cast-time re-check
                # and the handler, which is what stops the three disagreeing
                # about which cards this line may name.
                **({"any_card": True} if any_card else {"card_type": filt.card_types[0]}),
                # "up to four target **basic** land cards" (Lodestone Bauble).
                # A supertype is read off the printed type line, which for a
                # card in a graveyard is the whole of what there is (CR 613.1),
                # so it is testable in that zone for exactly the reason the card
                # type is — and dropping it would let the Bauble return any
                # land, which is a strictly better card than the one printed.
                **({"supertypes": list(filt.supertypes)} if filt.supertypes else {}),
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
                # reason the node records: CR 701.24a shuffles the library once.
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
    """"Then that player shuffles." (Prophecy.) CR 701.24 with nothing moving.

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

#: The `zones` half of `lowering/categories.INSTRUCTION_CATEGORIES`, here
#: rather than there for the reason that table's two earlier splits both
#: record: what a wrapper carries belongs beside what builds one, and the
#: family name is reused so the mirror re-forms instead of forking.
#:
#: The line is this module's own docstring, read as a question about a *kind*
#: rather than about a sentence: a zone change names **two** zones, the one an
#: object leaves and the one it goes to, and that pair is what picks the
#: handler — where every kind left in `categories` acts on an object where it
#: stands. It is 121 of the table's 380 rows and the largest category by a
#: factor of three, which is why this is the seam that pays.
#:
#: `categories` composes the two into one `INSTRUCTION_CATEGORIES`, so there is
#: still exactly one table and exactly one row per kind; the address every
#: reader uses is unchanged.
ZONE_INSTRUCTION_CATEGORIES: dict[str, str] = {
    "bin_revealed_card": "zones",
    "choose_card_name": "zones",
    "graveyard_top_to_library": "zones",
    "shuffle_graveyard_into_library": "zones",
    "shuffle_hand_into_library": "zones",
    "shuffle_hand_cards_into_library": "zones",
    # CR 701.24 with nothing moving into the library (Prophecy's third
    # sentence). The same category as the two above: what it touches is a zone.
    "shuffle_library": "zones",
    "exile_any_number_of_own_tokens": "zones",
    "put_graveyard_cards_on_library_top": "zones",
    "draw_then_discard_self": "zones",
    "discard_then_draw_that_many": "zones",
    "sacrifice_self": "zones",
    # The controller-chosen sacrifice (Dire Fleet Warmonger's optional cost).
    "sacrifice_matching_permanent": "zones",
    # "…sacrifice any number of creatures with total power 12 or greater"
    # (Phyrexian Dreadnought). The same category as every other sacrifice, so
    # GRAMMAR_CATEGORIES is unchanged: what differs is how the price is counted,
    # not what happens to the permanents.
    "sacrifice_permanents_totalling": "zones",
    "sacrifice_attached_permanent": "zones",
    "discard_target_cards": "zones",
    # The controller's own chosen discard (Jeskai Elder's if-you-do branch).
    "discard_controller_cards": "zones",
    # "Each player may discard up to three cards." (Mind Bomb.) One prompt
    # per seat, and a discard like every other one in this category.
    "each_player_discards_up_to_cards": "zones",
    # "Each player may draw up to two cards." (Truce.) The discard's twin one
    # zone over, and the same category: a card moving between a library and a
    # hand.
    "each_player_draws_up_to_cards": "zones",
    "draw_up_to_cards": "zones",
    # "Each opponent discards two cards." (Bad Deal) — one pending discard
    # choice per opponent, same flow as the targeted form.
    "each_opponent_discards_cards": "zones",
    "discard_x_target_cards": "zones",
    "opponent_discards_random_card_on_damage": "zones",
    # Looking at a hand reads a hidden zone; the legacy rule and the handler
    # both live in the engine's zones modules.
    "exile_target_graveyard": "zones",
    # Sword of the Ages: what the ability's own cost sacrificed, exiled out of
    # the graveyard the cost put it in.
    "exile_cost_sacrifices": "zones",
    # "Target player reveals their hand." (Inquisition.) The reveal on its own
    # (CR 701.20) — a zone becoming public, the same family as the paragraph
    # below it, so GRAMMAR_CATEGORIES is unchanged.
    "reveal_hand": "zones",
    # "…play with their hand revealed for as long as this creature remains on
    # the battlefield." (Stromgald Spy.) CR 701.20a's reveal made continuous —
    # the same zone becoming public, so the same category.
    "reveal_hand_while_source_present": "zones",
    "reveal_hand_and_choose": "zones",
    # CR 701.20, the reveal on its own (Amnesia, Rag Man). The same category as
    # the template above, so GRAMMAR_CATEGORIES is unchanged: what moves is
    # information about a hand either way.
    "reveal_hand": "zones",
    # "Target player reveals a card at random from their hand." (Wand of Ith.)
    # The same zone made public one card at a time, and the same category for
    # that reason.
    "reveal_random_card_from_hand": "zones",
    # "…discards it unless they pay 1 life." The offer and its declined branch
    # are one instruction because the branch acts on a card only the offer knows
    # — the same reason `unless_player_pays` carries its own unpaid steps.
    "discard_revealed_unless_pay_life": "zones",
    # Sirocco: the plural of the row above, one offer per revealed card the
    # printed phrase names. Same category, so GRAMMAR_CATEGORIES is unchanged.
    "discard_revealed_matching_unless_pay_life": "zones",
    "discard_bound_revealed_card": "zones",
    # "…discards **all nonland cards**" (Amnesia). A discard like the counted
    # ones beside it; only who picks differs, and here nobody does.
    "discard_all_matching_cards": "zones",
    "look_at_target_hand": "zones",
    "look_at_target_library_top": "zones",
    # "…You may put that card on the bottom of that player's library"
    # (Coral Fighters): the same look with the one offer that moves a card.
    "look_at_library_top_then_bottom": "zones",
    # "…, then put them back in any order" (Natural Selection, Portent). The
    # look above with the rearrangement switched on — same prompt, same zone,
    # so the same family.
    "reorder_target_library_top": "zones",
    # A library search moves a card between hidden zones — same module, same
    # category as the other zone-change handlers.
    "search_library": "zones",
    # The cast-from-exile/graveyard subsystem (both Chandras, M21): two exiles
    # that record what they moved, and the permission their later sentences
    # grant over it. All zone work — the permission is about which zone a card
    # may be cast from — so no new category and GRAMMAR_CATEGORIES is unchanged.
    "exile_top_of_library": "zones",
    "exile_entire_library": "zones",
    "exile_random_card_from_hand": "zones",
    "exile_chosen_card_from_hand": "zones",
    "put_exiled_with_source": "zones",
    "exile_graveyard_until_leaves": "zones",
    "exile_until_leaves_or_untaps": "zones",
    "exchange_ownership_unless_paid": "zones",
    "ante_or_exchange_ownership": "zones",
    "random_reveal_ownership_exchange": "zones",
    "take_ownership_of_exiled": "zones",
    "return_exiled_source_to_graveyard": "zones",
    "transmute_by_sacrifice": "zones",
    "rebalance_lands": "zones",
    "place_held_card": "zones",
    "look_top_pick_to_hand": "zones",
    "look_top_exile_random": "zones",
    "search_and_exile_matching": "zones",
    "grant_cast_permission": "zones",
    "grant_look_at_exiled_cards": "zones",
    # The planeswalker block's one-shot zone movers (M21 loyalty abilities).
    "each_player_discards_a_card": "zones",
    "discard_hand": "zones",
    "put_target_on_library_top": "zones",
    # "Choose two cards in your hand drawn this turn." (Sylvan Library.) A
    # pick out of a hidden zone that moves nothing; the sentence after it is
    # what moves anything.
    "choose_cards_in_hand": "zones",
    "put_iterated_card_on_library": "zones",
    "put_graveyard_card_on_library_bottom": "zones",
    "put_top_of_graveyard_on_library_bottom": "zones",
    # Unsubstantiate: a spell unstacked to its owner's hand, or a creature bounced.
    "return_spell_or_creature_to_hand": "zones",
    "put_cards_from_hand_onto_battlefield": "zones",
    # "…put **a** permanent card from their hand onto the battlefield."
    # (Eureka.) The chosen-card twin of the sweep above: same zone change, one
    # card, and the seat picks which.
    "put_chosen_card_from_hand_onto_battlefield": "zones",
    "reveal_top_to_hand_or_bottom": "zones",
    # The bare reveal (Track Down). Same category as the template above: both
    # look at the top of a library, and what differs is what the card's other
    # sentences then do about it.
    "reveal_top_of_library": "zones",
    "reveal_until_match": "zones",
    "name_and_strip": "zones",
    # "Choose a card name. Target opponent reveals X cards at random from their
    # hand. Then that player discards all cards with that name revealed this
    # way." (Nebuchadnezzar.) The same category as the naming paragraph above:
    # what it does is move cards out of a hidden zone.
    "name_and_random_reveal": "zones",
    # Petra Sphinx's guess. "zones" like the reveals above it: what the card
    # does is look at the top of a library and move that card somewhere, and
    # the name is only what decides which somewhere.
    "name_then_reveal_top": "zones",
    # Demonic Consultation, beside it: the same guess, taken against your own
    # library and paid for with its top cards.
    "name_then_consult": "zones",
    # Necropotence, exiling what its controller just discarded.
    "exile_bound_card_from_graveyard": "zones",
    # Necropotence again, the other half: what its own exile put aside comes
    # back at its controller\'s next end step.
    "put_exiled_cards_into_zone": "zones",
    # "Put the top card of the exiled pile into its owner's hand."
    # (Mangara's Tome.) CR 610.3's linked pile, so the same category as
    # the search that made it.
    "put_exiled_pile_top_into_hand": "zones",
    # "The next time you would draw a card this turn, instead ..."
    # (Mangara's Tome.) A wrapper like `create_delayed_trigger`, and the
    # gate walks into it for the same reason: what the line touches is
    # what the armed effect touches.
    "arm_draw_replacement": "zones",
    # Forgotten Lore: an opponent picks out of your graveyard, again for
    # each payment, and the pick the loop stopped on is the one you keep.
    "repeated_graveyard_pick": "zones",
    # The sentence that ends that loop. Its own kind because it is reached
    # from two places — the decline branch and an exhausted graveyard — and
    # a handler cannot be half a handler.
    "finish_repeated_graveyard_pick": "zones",
    "exile_all_matching": "zones",
    # "…then **the chosen permanents** phase out." (Equipoise.) The same zone
    # question as every other phase-out beside it — CR 702.26 is not a zone
    # change, and this table is where the family says so — with the set read
    # off a record rather than off a target.
    "phase_out_recorded_permanents": "zones",
    "phase_out_target": "zones",
    # "Until your next upkeep, target permanent **can't phase out**." (Spatial
    # Binding.) Beside the phasing actions rather than with the combat
    # restrictions: what it forbids is a CR 702.26 event, not a declaration.
    "forbid_phase_out": "zones",
    "phase_out_opponent_creatures": "zones",
    # CR 702.26's other two printed subjects (Mirage): the ability's own source
    # ("This creature phases out") and a sweep over a printed noun phrase ("All
    # lands you control phase out").
    "phase_out_self": "zones",
    "phase_out_matching": "zones",
    # "Enchanted creature phases out" (Vanishing): the Aura's attachment, known
    # from the source rather than chosen, so the same category and its own kind.
    "phase_out_enchanted": "zones",
    # "Simultaneously, all phased-out creatures phase in and all creatures
    # with phasing phase out." (Time and Tide.) The same family: what the
    # sentence does is move permanents in and out of play, and doing both at
    # once is a property of the moment rather than of the effect.
    "phase_in_and_out_matching": "zones",

    # "…and **that creature** phase out" (Dream Fighter): the creature the
    # block trigger bound, beside the sweep and the source above it.
    "phase_out_block_pair": "zones",
    "draw_target_cards": "zones",
    "draw_controller_cards": "zones",
    "mill_target_player": "zones",
    "look_top_cycle_and_stack": "zones",
    "separate_library_top_into_piles": "zones",
    "mill_until_matching": "zones",
    "put_milled_card_onto_battlefield": "zones",
    "put_hand_cards_on_library": "zones",
    # Scry moves cards within one library (CR 701.22a) — the same family as
    # mill and draw, so no new category and GRAMMAR_CATEGORIES is unchanged.
    "scry": "zones",
    "exile_creature_gain_life_equal_to_power": "zones",
    "exile_target_creature_until_eot": "zones",
    # The permanent exiles. Same category as the temporary one, so
    # GRAMMAR_CATEGORIES is unchanged — exile is a zone change either way, and
    # a second switch would let one of the two be gated off without the other.
    "exile_target_permanent": "zones",
    "exile_self": "zones",
    # "Exile that token" (Stangg) — the token this same effect created, by the
    # id the token maker recorded. A zone change like the two beside it.
    "exile_created_token": "zones",
    "exile_target_graveyard_card": "zones",
    # "…exile up to two target creature cards from defending player's
    # graveyard" (Rysorian Badger) — the counted twin of the row above, whose
    # picks are made through a prompt.
    "exile_cards_from_graveyard": "zones",
    "exile_graveyard_cards": "zones",
    # "When that creature dies this turn, exile **it**" (Whippoorwill) — the
    # card the delayed ability was bound to, out of the graveyard the death put
    # it in.
    "exile_bound_card": "zones",
    # "Put it into your graveyard." (All Hallow's Eve, from exile.) The
    # ability's own source moving zones — the same category as the self-exile
    # above, because it is the same kind of move made by the same kind of
    # sentence; the destination is payload.
    "put_self_into_zone": "zones",
    # "Each player returns all creature cards from their graveyard to the
    # battlefield." (All Hallow's Eve.) A sweep reanimation, filed with the
    # targeted graveyard returns beside it for the reason the two exiles share
    # a category: what varies is which cards, not what happens to them.
    "return_all_cards_from_graveyard": "zones",
    "return_creature_from_graveyard_to_hand": "zones",
    # "…return a card from your graveyard to your hand **for each card
    # discarded this way**." (Recall.) The same zone change, counted by an
    # earlier step's answer and chosen while the spell resolves rather than at
    # cast time. Same category, so GRAMMAR_CATEGORIES is unchanged.
    "return_chosen_cards_from_graveyard_to_hand": "zones",
    "reanimate_creature": "zones",
    # "Return target Aura card from your graveyard to the battlefield
    # attached to Hakim." The same zone change with CR 303.4f's attachment
    # folded into the entry, so the category is unchanged and
    # GRAMMAR_CATEGORIES gains nothing.
    "reanimate_aura_onto_source": "zones",
    "reanimate_bound_card": "zones",
    # A card returning *itself* from the graveyard (Silversmote Ghoul). Same
    # category as every other zone change: what differs is which object moves,
    # not what kind of effect it is — so GRAMMAR_CATEGORIES is unchanged and one
    # switch cannot gate half of "zones" off.
    "return_self_from_graveyard": "zones",
    "return_bound_card_to_owners_hand": "zones",
    "return_source_card_to_owners_hand": "zones",
    "return_source_card_to_battlefield": "zones",
    "bounce_target_creature": "zones",
    # "Return to your hand all enchantments you both own and control" (Remove
    # Enchantments) — the sweep twin of the bounce above.
    "return_all_matching": "zones",
    # "Return a creature you control to its owner's hand" (Shrieking Drake) —
    # the same move again, over the permanents a `choose_permanents` step in
    # front of it recorded rather than over a target or a sweep.
    "return_recorded_permanents_to_hand": "zones",
    # "{W}: Return **enchanted creature** to its owner's hand." (Sun Clasp.)
    "return_attached_permanent_to_hand": "zones",
    # "During your next untap step, as you untap your permanents, return this
    # land to its owner's hand." (Undiscovered Paradise.)
    "return_self_instead_of_untapping": "zones",
    # "Whenever a land is tapped for mana, return it to its owner's hand."
    # (Storm Cauldron.) The "zones" family rather than "mana": the trigger
    # fires on a mana event and the effect is a zone change. Resolved inline at
    # the same seam as its neighbour above and for the same reason — a land is
    # tapped for mana part-way through paying a cost, before the spell it pays
    # for is on the stack, so there is no stack to enqueue onto.
    "return_tapped_land_to_hand": "zones",
}
