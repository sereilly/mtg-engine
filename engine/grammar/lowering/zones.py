"""Lowering the zone changes: where an object goes (CR 400).

Split out of `lowering/board.py` when that file crossed 1,000 lines. A family
rather than an arbitrary cut: everything here answers one question — which zone
does this object end up in — and none of it touches the battlefield state the
rest of `board` is about (tapping, destruction, regeneration, control).

It had no twin in `effects/` for most of its life: a `return`/`exile`/`put`
parses in one small production, and the work is all on this side, deciding
*which* handler moves the object and refusing the shapes none implement. The
twin arrived at Weatherlight, when `effects/library.py` crossed the guard and
the shuffles came out under this module's name — so the mirror re-formed rather
than forking, and neither half imports the other.

The `zones` rows of `categories.INSTRUCTION_CATEGORIES` sat at the bottom of
this file until Tempest's Phase 0 and are now `_zone_categories.py`, a third of
the module gone in one cut: a registry with no call graph, against the dispatch
that is everything left here. `categories` still composes the two, so there is
one table and one row per kind and no reader's address changed.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from ...subject_filters import card_only_filter
from .. import ast
from ..errors import LoweringError
from ...damage_deaths import DAMAGED_BY_SOURCE_DIED
from ._deaths import BOUND_CARD_EVENTS
from ._events import binds_block_pair
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS, dropped_narrowings, _describe_targets,
    _filter_payload, _is_source, _is_target, _restrictions_beyond, _targets_only,
    graveyard_position_payload, refuse_untestable
)


def _lower_put_on_library_top(
    node: ast.PutOnLibraryTop,
    event: str | None = None,
    event_subject: object | None = None,
) -> tuple[OracleInstruction, ...]:
    """"Put target creature on top of its owner's library." (Teferi, Timeless
    Voyager's −3.) One chosen battlefield creature; the owner is resolved by
    the handler (CR 400.3), which is why no player rides the payload.

    Three other subjects reach the same destination and each names its object a
    different way, which is why *event* travels with the node: the source
    itself ("Put **this creature** on top of its owner's library" — Thalakos
    Mistfolk), the source under a trigger that has already killed it ("When
    this creature dies, you may put **it** …" — Avenging Angel), and the
    creature a block pair bound ("…becomes blocked by a creature, put **that
    creature** …" — Elven Warhounds).
    """
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
    # "Put **this creature** on top of its owner's library" (Thalakos Mistfolk)
    # and "…you may put **it** …" under a dies trigger (Avenging Angel — the
    # noun parser marks that pronoun `is_source`, so both arrive here as one).
    # Its own kind rather than the tuck below, for
    # ``return_source_card_to_owners_hand``'s reason two families over: the
    # sentence names **no source zone**, so it must reach the object wherever it
    # actually is (CR 608.2). Mistfolk's is on the battlefield; the Angel's is a
    # card in a graveyard by the time its trigger resolves, and a handler that
    # resolved a battlefield permanent would silently do nothing for it.
    if _is_source(node.target):
        if node.bottom_instead_colors or node.to_owner != "owner":
            # Refused rather than dropped: a dropped end swap is a card that
            # never offers the choice it prints.
            raise LoweringError(
                "the self tuck reads no end swap and no fixed seat", node=node
            )
        return (OracleInstruction("put_source_card_on_library_top", "", {}),)

    # "Whenever this creature becomes blocked by a creature, put **that
    # creature** on top of its owner's library." (Elven Warhounds.) The other
    # half of the pair the trigger bound — not a target, so no `targets`
    # description is emitted and no picker is raised, exactly as the tap one
    # family over reads the identical noun phrase. ``binds_block_pair`` rather
    # than the kind alone, for the reason that helper exists: CR 509.3c/509.3d
    # make a *bare* "becomes blocked" fire once with several blockers and no way
    # to say which one "that creature" is.
    if (
        isinstance(node.target, ast.TargetSpec)
        and node.target.quantifier == "that"
        and not node.target.targeted
        and binds_block_pair(event, event_subject)
    ):
        if node.bottom_instead_colors or node.to_owner != "owner":
            raise LoweringError(
                "the bound tuck reads no end swap and no fixed seat", node=node
            )
        bound: dict[str, object] = {"subject": "block_pair"}
        described = _filter_payload(node.target.filter)
        refuse_untestable(described, refusal="the tuck cannot narrow by", node=node)
        bound.update(described)
        return (OracleInstruction("put_target_on_library_top", "", bound),)

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
    # "Any number of" (Drafna's Restoration), "up to three" (Reinforcements)
    # and the bare "target" (Volrath's Stronghold) are the three quantifiers
    # this handler can honour, and all three are a *count* over the same chosen
    # list — the slot resolver takes ``count`` slots and moves exactly what it
    # was handed. What is refused is a quantifier that chooses nothing: "all"
    # names a set the sentence never asked anybody to pick, and the handler has
    # no picker to fill from it.
    #
    # "target" used to be refused here on the reading that this handler moves a
    # list and that sentence moves one card. It moves one card *because the
    # list is one long*: the description carries the printed quantifier through
    # to the picker, so the difference between "target" and "up to one" is
    # whether the announcement may be empty (CR 601.2c / CR 602.2b), which is
    # the gate's question rather than this handler's.
    if subject.quantifier not in ("any_number", "up_to", "target"):
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
    return (
        OracleInstruction(
            "put_graveyard_cards_on_library_top", "",
            {
                **_chosen_graveyard_cards(filt, subject, node),
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
            },
        ),
    )


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
        # "…put **all** land cards from it onto the battlefield." (Manabond.)
        # The sweep spelling of the same move, and the count is the whole
        # difference: "up to N" is a ceiling the seat may answer under, and
        # "all" is every card the phrase names with nothing to decide. Carried
        # as its own key rather than as a very large count, so the handler
        # cannot be asked how many "all" is on a hand it has not seen yet.
        if target.quantifier not in ("up_to", "all") or not filt.is_card:
            raise LoweringError(
                "the from-hand handler reads 'up to N … cards' or 'all … cards'",
                node=node,
            )
        # Anything the phrase printed beyond its card type has to survive into
        # the payload — the handler tests only the type, so an adjective
        # dropped here is a hand emptied wider than the sentence says.
        if _restrictions_beyond(
            filt, frozenset({"is_card", "zone", "zone_owner", "card_types"})
        ):
            raise LoweringError(
                "the from-hand sweep cannot test that card phrase", node=node
            )
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
                    **({"all": True} if target.quantifier == "all" else {}),
                },
            ),
        )
    if filt.zone == "graveyard":
        # "**Each player** puts a creature card from their graveyard onto the
        # battlefield." (Exhume.) Nothing is targeted and nothing is chosen by
        # the caster: every seat picks out of its own pile, which is why it is
        # its own kind rather than the reanimation below with a wider payload —
        # that handler resolves one announced target, and this one arms a
        # prompt per player.
        #
        # The actor and the possessive are checked **against each other**, the
        # way the sweep reanimation one family over checks them: "each player …
        # their graveyard" is one claim said twice, and a pairing this cannot
        # resolve refuses rather than picking a half. A card printing the
        # possessive without the subject would be the caster raiding the table.
        if node.actor is not None and node.actor.kind == "each_player":
            owner = filt.zone_owner.kind if filt.zone_owner is not None else None
            if owner not in ("owner", "each_player"):
                raise LoweringError(
                    "\"each player\" puts a card out of their own graveyard",
                    node=node,
                )
            if _is_target(target) or target.quantifier not in ("a", "an"):
                raise LoweringError(
                    "the per-seat reanimation reads an article, not a target",
                    node=node,
                )
            if node.under_your_control or node.under_owners_control or node.gains:
                raise LoweringError(
                    "the per-seat reanimation reads no rider", node=node
                )
            if not filt.is_card or filt.card_types != ("creature",):
                raise LoweringError(
                    "the per-seat reanimation only moves creature cards",
                    node=node,
                )
            if _restrictions_beyond(
                filt, frozenset({"is_card", "zone", "zone_owner", "card_types"})
            ):
                raise LoweringError(
                    "the per-seat reanimation cannot test that card phrase",
                    node=node,
                )
            return (
                OracleInstruction(
                    "each_player_reanimates", "", {"card_type": "creature"},
                ),
            )
        if node.actor is not None and node.actor.kind != "you":
            raise LoweringError(
                f"no graveyard-entry handler is performed by {node.actor.kind!r}",
                node=node,
            )
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
    replaced the first time a card says "target player's".

    "Shuffle **all creature cards** from your graveyard into your library."
    (Barishi.) The narrowed pile, on the key ``graveyard_card_matches``
    already reads — the same predicate the graveyard-to-hand returns ask, so
    "creature card" means one thing in this engine wherever it is printed. Only
    a phrase that predicate can test is admitted: the alternative is a filter
    parsed and dropped, which for this sentence is a card shuffling its owner's
    lands and spells back in as well.
    """
    payload: dict[str, object] = {"whose": node.whose.kind}
    if node.chosen is not None:
        # "**Target player shuffles up to three target cards** from their
        # graveyard into their library." (Gaea's Blessing.) The moving subset
        # chosen rather than described, with the payload half
        # ``put_graveyard_cards_on_library_top`` builds for the identical noun
        # phrase one destination over. ``graveyard_owner`` is the chosen seat
        # rather than the printed pronoun: CR 404.1 makes that seat's library
        # the only one those cards can be shuffled into.
        if node.whose.kind != "target_player":
            raise LoweringError(
                "a chosen-card graveyard shuffle names the player it targets",
                node=node,
            )
        payload["whose"] = payload["graveyard_owner"] = "target_player"
        payload.update(_chosen_graveyard_cards(node.chosen.filter, node.chosen, node))
        return (OracleInstruction("shuffle_graveyard_into_library", "", payload),)
    if node.cards is not None:
        filt = node.cards
        # Read field by field rather than through ``_filter_payload``, which
        # speaks the *battlefield* matcher's key names and refuses a
        # graveyard-scoped phrase outright. The reader here is
        # ``graveyard_card_matches``, whose keys these are — the same predicate
        # the graveyard-to-hand returns ask, so "creature card" means one thing
        # in this engine wherever it is printed.
        unread = _restrictions_beyond(
            filt,
            frozenset({"is_card", "zone", "zone_owner", "card_types",
                       "supertypes", "subtypes", "colors"}),
        )
        if unread:
            raise LoweringError(
                "the graveyard shuffle cannot narrow by: " + ", ".join(unread),
                node=node,
            )
        cards: dict[str, object] = {}
        if len(filt.card_types) > 1:
            cards["card_types"] = list(filt.card_types)
        elif filt.card_types:
            cards["card_type"] = filt.card_types[0]
        if filt.subtypes:
            cards["graveyard_subtypes"] = list(filt.subtypes)
        if filt.colors:
            cards["graveyard_colors"] = list(filt.colors)
        if filt.supertypes:
            cards["supertypes"] = list(filt.supertypes)
        if not cards:
            raise LoweringError(
                "the graveyard shuffle's noun phrase narrows nothing at all",
                node=node,
            )
        payload["cards"] = cards
    return (
        OracleInstruction("shuffle_graveyard_into_library", "", payload),
    )


def _lower_shuffle_source_into_library(
    node: ast.ShuffleSourceIntoLibrary,
) -> tuple[OracleInstruction, ...]:
    """"When this creature dies, shuffle **it** into its owner's library."
    (Alabaster Dragon.)

    The seat is on the payload for ``_lower_shuffle_graveyard_into_library``'s
    reason, and refused when it is not the owner's: CR 404.1 put the card in
    its owner's graveyard, so "its owner's library" is the one library this
    sentence can reach, and a card printing "your library" would be a different
    card the moment a creature changed hands.
    """
    if node.owner.kind != "owner":
        raise LoweringError(
            f"no handler shuffles this card into {node.owner.kind!r}'s library",
            node=node,
        )
    return (
        OracleInstruction("shuffle_source_card_into_library", "", {}),
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


def _lower_exile_graveyard_position(
    node: ast.ExileGraveyardPosition,
) -> tuple[OracleInstruction, ...]:
    """"Exile the bottom card of target player's graveyard." (Phyrexian
    Furnace.) The same phrase Barrow Ghoul and Circling Vultures print as the
    price of an "unless you ..." offer, which reaches here through the ``May``
    the board family decomposes them into.

    Through the same payload gate the cost side runs
    (``_filters.graveyard_position_payload``), so an effect and a cost printing
    one sentence cannot name different cards — and so a narrowing the card
    matcher cannot test refuses the line rather than being dropped where it is
    tested.
    """
    payload = graveyard_position_payload(node.position)
    if payload is None:
        raise LoweringError(
            "no exile handler reads this graveyard position", node=node
        )
    if node.position.owner.kind == "target_player":
        # The seat is chosen (CR 115.1), so the *card* targets even though
        # nothing about the cards themselves is chosen — the picker reads
        # ``targets`` and would otherwise offer Phyrexian Furnace no player at
        # all, which is the ability activating against whoever the resolution
        # happened to be carrying.
        payload.update(_targets_only(node.position.owner))
    return (OracleInstruction("exile_graveyard_position", "", payload),)
