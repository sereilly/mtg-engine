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

from ...oracle_types import OracleInstruction, REVEALED_TOP_CARDS_BY_SEAT
from ...subject_filters import SOURCE_RESOLVED_CARD_KEYS, card_only_filter
from .. import ast
from ..errors import LoweringError
from ...damage_deaths import DAMAGED_BY_SOURCE_DIED
from ._deaths import BOUND_CARD_EVENTS
from ._events import binds_block_pair
from ._piles import _chosen_graveyard_cards
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS, dropped_narrowings, _describe_several_targets,
    _describe_targets, _filter_payload, _is_source, _is_target,
    _names_several_targets, _restrictions_beyond, _targets_only,
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

    # "Put **all enchantments** on top of their owners' libraries." (Harmonic
    # Convergence.) The sweep twin of the tuck below, and its own kind for
    # ``return_all_matching``'s reason one family over: nothing is chosen, so no
    # picker is derived and the target description that would raise one is not
    # emitted. A count on the tuck would have been a spell whose client asks for
    # a target it never names.
    if (
        isinstance(node.target, ast.TargetSpec)
        and node.target.quantifier in ("all", "each")
        and not node.target.targeted
    ):
        if node.bottom_instead_colors or node.to_owner != "owner":
            # Both riders are about **one** object — an end swap asks a colour
            # of the card it is moving, and a fixed seat contradicts a sweep
            # that follows each object to its own owner (CR 400.3). Refused
            # rather than dropped: a dropped rider is a card that never offers
            # the choice it prints.
            raise LoweringError(
                "the sweep tuck reads no end swap and no fixed seat", node=node
            )
        filt = node.target.filter
        if filt.zone != "battlefield" or filt.is_card:
            raise LoweringError(
                "the sweep tuck moves permanents, not cards in a zone", node=node
            )
        swept = _filter_payload(filt)
        refuse_untestable(
            swept, refusal="the sweep tuck cannot narrow by", node=node
        )
        return (
            OracleInstruction(
                "put_all_matching_on_library_top", "", {"filter": swept}
            ),
        )
    # "Put **two target lands** on top of their owners' libraries." (Plow
    # Under.) A chosen *list*, which is the same shape "up to two target
    # creatures" is one family over — so it opts into the several-target
    # description rather than the singular one, and the handler's list branch
    # reads it. Without the opt-in ``_describe_targets`` emits nothing at all
    # and the card would tuck one land of the two it names.
    if _names_several_targets(node.target):
        assert isinstance(node.target, ast.TargetSpec)
        if node.bottom_instead_colors or node.to_owner != "owner":
            # Both riders are about **one** object, the reason the sweep above
            # refuses them: an end swap asks a colour of the card it is moving,
            # and a fixed seat contradicts a list that follows each object to
            # its own owner (CR 400.3).
            raise LoweringError(
                "the several-target tuck reads no end swap and no fixed seat",
                node=node,
            )
        if node.target.filter.zone != "battlefield" or node.target.filter.is_card:
            raise LoweringError(
                "the several-target tuck moves permanents, not cards in a zone",
                node=node,
            )
        several: dict[str, object] = {}
        _describe_several_targets(several, node.target)
        refuse_untestable(
            (several.get("targets") or {}).get("filter") or {},
            refusal="the several-target tuck cannot narrow by", node=node,
        )
        return (OracleInstruction("put_target_on_library_top", "", several),)
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




def _lower_put_onto_battlefield(
    node: ast.PutOntoBattlefield, event: str | None = None,
    produced: frozenset[str] = frozenset(),
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
    if node.tapped and not (
        filt.zone == "hand" and target.quantifier in ("a", "an") and filt.is_card
    ):
        # "…onto the battlefield **tapped**." Only the from-hand pick below
        # carries the word to its resolver (Terrain Generator); every other
        # branch here would put the card in untapped, which is a different and
        # better card than the one printed.
        raise LoweringError(
            "only the from-hand pick puts a card onto the battlefield tapped",
            node=node,
        )
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
            # "…a creature card **of the chosen type** from your hand" (Belbe's
            # Portal). The type is a CR 614.1c record on the ability's source,
            # which no card in a hand can answer — so the key rides past the
            # card-only gate and the handler turns it into an ordinary subtype
            # off that source before any matcher is asked. Named here, because
            # each name is a claim that the resolver really does that.
            described = card_only_filter(
                payload, carried_separately=SOURCE_RESOLVED_CARD_KEYS
            )
            if described is None or dropped_narrowings(filt, payload):
                raise LoweringError(
                    "the from-hand pick cannot test that card phrase", node=node
                )
            pick_payload: dict[str, object] = {
                "card_filter": described,
                # An empty type list with is_card means "permanent
                # cards", the same reading the sweep below takes.
                "permanents_only": not filt.card_types,
                "whose": "offered" if filt.zone_owner.kind == "owner" else "you",
            }
            if node.tapped:
                # Emitted only when printed, so every pick compiled before this
                # keeps a byte-identical payload.
                pick_payload["tapped"] = True
            if node.attached_to_source:
                # "…onto the battlefield **attached to this creature**."
                # (Academy Researchers.) CR 303.4f: the Aura arrives already
                # attached, so the host is part of the offer rather than a step
                # behind it — and it is part of what may be *picked*, because
                # CR 303.4a lets an Aura be put onto the battlefield only
                # attached to something its enchant ability can enchant. The
                # handler resolves the source and narrows the candidates
                # through the one enchant gate the cast, the sweep and the two
                # pickers already ask.
                pick_payload["attach_to"] = "source"
            return (
                OracleInstruction(
                    "put_chosen_card_from_hand_onto_battlefield",
                    "",
                    pick_payload,
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
                    "each_player_takes_from_graveyard", "",
                    {
                        "card_type": "creature",
                        "count": 1,
                        "up_to": False,
                        "destination": "battlefield",
                    },
                ),
            )
        if node.actor is not None and node.actor.kind != "you":
            raise LoweringError(
                f"no graveyard-entry handler is performed by {node.actor.kind!r}",
                node=node,
            )
        if not _is_target(target) or not filt.is_card:
            raise LoweringError("the reanimation handler reads one chosen card", node=node)
        # "target **Aura** card from a graveyard" (Iridescent Drake). CR 205.3b
        # makes "Aura" a subtype, so the phrase narrows by neither of the two
        # things this branch could read: it refused with "only moves creature
        # cards" on a filter whose ``card_types`` was empty. What the handler
        # reads is a type word plus a ``graveyard_card_matches`` spec, and both
        # go through readers that answer a subtype as readily as a card type —
        # so the narrowing is carried rather than widened away, and the guard
        # below is what makes that safe: a narrowing dropped here is a card the
        # picker offers that the sentence never named.
        if _restrictions_beyond(
            filt,
            frozenset({"is_card", "zone", "zone_owner", "card_types", "subtypes"}),
        ):
            raise LoweringError(
                "the reanimation handler cannot test that card phrase", node=node
            )
        if len(filt.card_types) > 1:
            raise LoweringError(
                "the reanimation handler moves one kind of card", node=node
            )
        if not filt.card_types and not filt.subtypes:
            raise LoweringError(
                "the reanimation handler reads a described card", node=node
            )
        payload: dict[str, object] = {
            # "from a graveyard" (no owner) widens the search to every
            # player's graveyard; "under your control" is CR 400.3's
            # exception spelled out, honored by the handler.
            "any_graveyard": filt.zone_owner is None,
            "under_your_control": node.under_your_control,
            "gains": list(node.gains),
        }
        # Written only when the phrase is not the creature the handler already
        # defaults to, so every reanimation compiled before this one keeps a
        # byte-identical payload.
        if filt.card_types and filt.card_types != ("creature",):
            payload["card_type"] = filt.card_types[0]
        if filt.subtypes:
            # On the key ``graveyard_card_matches`` reads — the one predicate
            # the picker, the re-check and the handler all ask, so "Aura card"
            # cannot mean one thing to the offer and another to the resolution.
            # With no card type printed the subtype is also the word the
            # handler *searches* by: ``card_has_type`` reads the printed line
            # (CR 613.1 leaves a card in a graveyard nothing else), and that
            # line names the subtype, so the two readers ask one question.
            payload["graveyard_subtypes"] = list(filt.subtypes)
            if not filt.card_types:
                payload["card_type"] = filt.subtypes[0]
        if node.attached_to_source:
            # "…onto the battlefield under your control **attached to this
            # creature**." (Iridescent Drake.) CR 303.4: an Aura *enters*
            # attached, so this rides the entry rather than being a step behind
            # it — the same key the from-hand pick above carries, because it is
            # the same clause about the same host. (That pick's comment cites
            # 303.4f, which is the rule for an effect that names **no** host and
            # leaves the choice to the player; both of these name one.)
            payload["attach_to"] = "source"
        return (OracleInstruction("reanimate_creature", "", payload),)
    # "…put **those cards** onto the battlefield **under their owners'
    # control**." (Game Preserve.) The cards an earlier step of this same
    # resolution revealed off the top of every library, each going back to the
    # seat whose library it came off — CR 110.2a's "unless the effect states
    # otherwise", and this sentence is that statement.
    #
    # Gated on that step having run: "those cards" names nothing on its own, and
    # ``produced`` is what proves the reveal is in front of it — the same
    # producer discipline every other back-reference in this package follows.
    # Without it a card printing the sentence alone would compile clean and put
    # nothing, which is the shape ``--hollow-lines`` exists to find.
    if (
        isinstance(node.target, ast.TargetSpec)
        and node.target.quantifier == "those"
        and node.under_owners_control
        and not node.under_your_control
    ):
        if REVEALED_TOP_CARDS_BY_SEAT not in produced:
            raise LoweringError(
                "\"those cards\" needs an earlier step of this effect that "
                "revealed one per player",
                node=node,
            )
        if node.gains or node.attached_to_source or node.sacrifice_when_control_lost:
            raise LoweringError(
                "the per-owner battlefield entry reads no rider", node=node
            )
        return (
            OracleInstruction("put_revealed_top_cards_onto_battlefield", "", {}),
        )
    raise LoweringError("no handler for this battlefield entry", node=node)








#: The seats a reveal of a library's top card can name — the same four the
#: shuffle below admits, and for the same reason: a reveal opens one library,
#: and a reference the handler cannot resolve is a card revealed off the wrong
#: deck and recorded under a name every sentence behind it then reads.
_REVEAL_TOP_PLAYERS = frozenset(
    {"you", "that_player", "target_player", "target_opponent",
     # "**Each player** reveals the top card of their library." (Game
     # Preserve.) One library per seat rather than one library, which is why
     # the handler records ``{seat: card}`` for it: the sentence behind it
     # names every card at once and puts each under a different player's
     # control.
     "each_player"},
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
    if node.player.kind == "each_player":
        # No target is described: "each player" names every seat rather than
        # choosing one (CR 115.1), so there is nothing for a picker to offer.
        return (
            OracleInstruction("reveal_top_of_library", "", {"whose": "each_player"}),
        )
    payload: dict[str, object] = {"whose": node.player.kind}
    if node.player.kind != "that_player":
        _describe_targets(payload, node.player)
    return (OracleInstruction("reveal_top_of_library", "", payload),)


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


#: The role dependency "…in **that player's** graveyard", where *that player*
#: is the seat an earlier role's own noun phrase bound ("target artifact **a
#: player controls**").
#:
#: Spelled with the ``_role`` suffix every dependency in a roles description
#: carries, which is what ``targeting.role_dependency`` finds it by; the answer
#: behind the name is one entry in ``targeting.ROLE_RELATION_TESTS``, read by
#: the picker, by the announcement gate and by the CR 608.2b re-check alike.
IN_GRAVEYARD_OF_ROLE = "in_graveyard_of_role"


def _lower_sacrifice_and_return_targets(
    node: ast.SacrificeAndReturnTargets,
) -> tuple[OracleInstruction, ...]:
    """"Choose target artifact a player controls and target artifact card in
    that player's graveyard. If both targets are still legal as this ability
    resolves, that player simultaneously sacrifices the artifact and returns
    the artifact card to the battlefield." (Goblin Welder.)

    **One instruction, because it is one announcement.** The two targets are
    chosen together (CR 601.2c through CR 602.2b) and the second's legal set is
    decided by the first, which is exactly the ordered-**roles** description the
    picker already walks — so the slots go there rather than into two steps of a
    sequence, where nothing could enumerate the second against the first.

    The second role is a card in a graveyard rather than a permanent, and it is
    described with the same keys ``graveyard_card_matches`` reads everywhere
    else. That predicate is what the picker offers by, what the announcement
    gate admits by and what the resolution re-checks by; a payload written in
    this module's own spelling would be a fourth reading of "which cards may be
    chosen", which is this repo's recurring defect.
    """
    from ._described_returns import _graveyard_to_hand_payload

    sacrificed = _filter_payload(node.sacrificed.filter)
    noun = sacrificed.get("type_filter") or sacrificed.get("subtype_filter")
    if not isinstance(noun, str):
        raise LoweringError(
            "a sacrificed target role needs a printed noun to be asked for",
            node=node,
        )
    returned_filter = node.returned.filter
    # Every narrowing on the graveyard slot that ``graveyard_card_matches``
    # cannot test. Refused rather than dropped, in the direction this grammar
    # always fails: a card in a graveyard has no power, no tapped state and no
    # controller (CR 613.1 reads its printed line and nothing else), so a
    # phrase carrying one of those is a card this lowering does not implement
    # rather than a card it implements loosely.
    if _restrictions_beyond(
        returned_filter,
        {
            "card_types", "type_match", "subtypes", "subtype_match",
            "supertypes", "colors", "zone", "zone_owner", "is_card",
        },
    ):
        raise LoweringError(
            "no graveyard picker reads this narrowing", node=node
        )
    described = _graveyard_to_hand_payload(returned_filter)
    if returned_filter.colors:
        described = {
            **described, "graveyard_colors": list(returned_filter.colors),
        }
    returned_noun = described.get("card_type")
    if not isinstance(returned_noun, str):
        raise LoweringError(
            "a returned target role needs a printed card type to be asked for",
            node=node,
        )
    # The role *names* are the printed nouns, which is what the picker shows the
    # activator ("Choose the artifact card for Goblin Welder (2 of 2)"). They
    # have to differ — a roles walk turns a name back into a slot — and here the
    # word "card" is exactly what the card prints to tell its two targets apart.
    payload: dict[str, object] = {
        "targets": {
            "kind": "roles",
            "roles": [
                {
                    "role": noun,
                    "kind": "object",
                    "count": 1,
                    "filter": sacrificed,
                },
                {
                    "role": f"{returned_noun} card",
                    "kind": "graveyard_card",
                    "count": 1,
                    **described,
                    IN_GRAVEYARD_OF_ROLE: noun,
                },
            ],
        },
    }
    if not node.must_all_be_legal:
        # The same two verbs **without** "if both targets are still legal" is a
        # different card: CR 608.2b would let it resolve one half — sacrifice
        # the artifact and return nothing, or the reverse — and nothing here
        # does that. Refused by name rather than lowered onto the handler
        # below, which does neither half and would be stricter than the rule in
        # the direction that takes a player's artifact for nothing.
        raise LoweringError(
            "no handler resolves this weld one target at a time", node=node
        )
    # CR 608.2b removes an ability from the stack only when *every* target is
    # illegal. This card is stricter, so the rider is carried onto the payload
    # the handler reads rather than folded into the meaning of the kind:
    # dropped, the ability would sacrifice an artifact and return nothing, and
    # a second card printing the looser sentence has somewhere to say so.
    payload["all_targets_required"] = True
    return (
        OracleInstruction("sacrifice_and_return_targets", "", payload),
    )


def _lower_random_graveyard_card_fate(
    node: ast.RandomGraveyardCardFate,
) -> tuple[OracleInstruction, ...]:
    """Search for Survivors' paragraph, as one instruction: shuffle the
    caster's graveyard, take a card at random, and send it to the battlefield
    when it has the printed type, to exile otherwise. The type is payload; the
    two destinations are the node's fixed words and the kind's meaning."""
    return (
        OracleInstruction(
            "move_random_graveyard_card", "",
            {"shuffle_first": True, "card_type": node.card_type},
        ),
    )
