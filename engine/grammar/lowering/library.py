"""Lowering the hidden-zone flows: search, reveal, look-at, and exile linkage.

Every shape here pivots on a pile of cards in a hidden zone offered through a
picker or a permission — a library search, a revealed hand, the top cards
looked at, a graveyard exiled wholesale, cards exiled *with* a permanent and
castable while it stays. The search filter fields the flow can actually honour
are closed sets, because a filter it cannot honour must refuse rather than be
dropped.
"""

import dataclasses

from ...oracle_types import PER_OBJECT_SEAT_RECORDS, OracleInstruction
from ...search_filters import SEARCH_COMPARISONS, SEARCH_RESTRICTIONS
from ...subject_filters import card_only_filter
from .. import ast
from ..errors import LoweringError
from ._common import (
    chargeable_card_filter,
    _filter_payload,
    _amount_payload,
    _describe_targets,
    _is_target,
    _restrictions_beyond,
    _targets_only,
    count_spec,
)
from ._events import (
    _back_reference_payload,
)


def _lower_reveal_until(
    node: ast.RevealUntil, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """Transmogrify's reveal-until-match, as one instruction.

    Demands the producer, like every other back-reference: "that creature's
    controller" is the seat the *exile* step recorded, and without that step
    there is nobody to read the library of — the effect would silently fall back
    to the caster, which is the opposite player from the one the card names.
    """
    if node.whose == "exiled_permanent_controller" and node.whose not in produced:
        raise LoweringError(
            "\"that creature's controller\" with no exile before it", node=node,
        )
    described = card_only_filter(node.filter.to_payload())
    if described is None:
        raise LoweringError(
            "the reveal cannot test this restriction on a card", node=node,
        )
    return (
        OracleInstruction(
            "reveal_until_match", "",
            {
                "whose": node.whose,
                "filter": described,
                "destination": node.destination,
                "rest": node.rest,
            },
        ),
    )


def _lower_reveal_top(node: ast.RevealTopToHandOrBottom) -> tuple[OracleInstruction, ...]:
    """"Reveal the top card of your library. If it's a <filter> card, put it
    into your hand. Otherwise, put it on the bottom of your library." (Garruk,
    Savage Herald's +1.) The filter is the whole decision, so it is carried as
    payload the handler tests with primary_type."""
    if not node.filter.is_card or len(node.filter.card_types) != 1:
        raise LoweringError("the reveal-top handler tests one card type", node=node)
    return (
        OracleInstruction(
            "reveal_top_to_hand_or_bottom", "", {"card_type": node.filter.card_types[0]}
        ),
    )


# The ``ObjectFilter`` fields the revealed-hand picker can test. The exclusion
# is the only narrowing any printing of this template uses, and
# `search_filters.search_matches` is what tests it — so a field outside this set
# refuses the line rather than leaving the caster choosing from the whole hand
# while the card claims a restriction. Same rule the search lowering follows,
# and the same predicate underneath it.
_REVEALED_HAND_FIELDS = frozenset({"excluded_types", "is_card"})


def _lower_reveal_hand(node: ast.RevealHand) -> tuple[OracleInstruction, ...]:
    """"Target player **reveals their hand**" (CR 701.16), on its own.

    The first half of Amnesia and Rag Man, lowered as its own step so the
    discard behind it is the ordinary discard instruction rather than a second
    fused kind. Only a *chosen* player has a handler: "each player reveals their
    hand" would be a loop nothing here performs, and "you reveal your hand"
    reveals a zone the revealer already sees.

    The whole payload is who reveals, because a reveal narrows nothing and
    chooses nothing — what the sentence after it does with the revealed hand is
    that sentence's business, and on Inquisition that is an ordinary counted
    damage.
    """
    if node.player.kind not in ("target_player", "target_opponent"):
        raise LoweringError(
            f"no handler reveals {node.player.kind!r}'s hand", node=node
        )
    return (OracleInstruction("reveal_hand", "", _targets_only(node.player)),)


def _lower_reveal_random_from_hand(
    node: "ast.RevealRandomFromHand",
) -> tuple[OracleInstruction, ...]:
    """"Target player **reveals a card at random from their hand**." (Wand of
    Ith.) One card nobody chose, and the record it leaves is the one every "if
    it's a …" already reads, so the sentences behind it need no new referent.

    Only a *chosen* player, for ``_lower_reveal_hand``'s reason: "you" would be
    revealing a card to the player already holding it.
    """
    if node.player.kind not in ("target_player", "target_opponent"):
        raise LoweringError(
            f"no handler reveals a card from {node.player.kind!r}'s hand",
            node=node,
        )
    return (
        OracleInstruction(
            "reveal_random_card_from_hand", "", _targets_only(node.player)
        ),
    )


def _lower_discard_revealed_unless_pay_life(
    node: "ast.DiscardRevealedUnlessPayLife", produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"That player **discards it unless they pay 1 life**." (Wand of Ith.)

    ``produced`` is the whole gate, and the same one ``RevealedCardIs`` takes:
    "it" names the card a reveal earlier in this effect recorded, and with no
    reveal in front of it there is nothing to discard — an offer bought off
    against nothing would charge a player life for keeping a card that was
    never named.
    """
    if "revealed_card" not in produced:
        raise LoweringError(
            "'it' with nothing in this effect that revealed a card", node=node
        )
    if node.player.kind not in ("target_player", "that_player", "target_opponent"):
        raise LoweringError(
            f"no handler makes {node.player.kind!r} discard the revealed card",
            node=node,
        )
    payload: dict[str, object] = {}
    if node.mana_value_of_revealed:
        payload["life"] = "revealed_mana_value"
    else:
        amount = _amount_payload(node.amount)
        if not isinstance(amount, int) or amount < 0:
            raise LoweringError("a life payment is a printed number", node=node)
        payload["life"] = amount
    return (
        OracleInstruction("discard_revealed_unless_pay_life", "", payload),
    )


def _lower_reveal_hand_and_choose(
    node: ast.RevealHandAndChoose,
) -> tuple[OracleInstruction, ...]:
    """"Target opponent reveals their hand. You choose a noncreature, nonland
    card from it. That player discards that card." (Duress.)

    One instruction for the whole template: the reveal is what makes the choice
    legal, and the discard is what the choice was for, so splitting them would
    put a chosen card between two instructions with nothing carrying it.
    """
    leftover = _restrictions_beyond(node.filter, _REVEALED_HAND_FIELDS)
    if leftover:
        raise LoweringError(
            "the revealed-hand picker cannot narrow by: " + ", ".join(leftover),
            node=node,
        )
    payload: dict[str, object] = {"fate": node.fate}
    if node.filter.excluded_types:
        payload["exclude_types"] = list(node.filter.excluded_types)
    _describe_targets(payload, node.player)
    return (OracleInstruction("reveal_hand_and_choose", "", payload),)


def _lower_exile_graveyard(node: ast.ExileGraveyard) -> tuple[OracleInstruction, ...]:
    """"Exile target player's graveyard." (Tormod's Crypt.)

    The whole zone, so there is no filter to carry and no card to resolve —
    only which player's graveyard, which is the target description.
    """
    return (
        OracleInstruction("exile_target_graveyard", "", _targets_only(node.player)),
    )


def _lower_look_at_hand(node: ast.LookAtHand) -> tuple[OracleInstruction, ...]:
    """"Look at target player's hand." (Glasses of Urza.)

    ``look_at_target_hand`` reads one chosen player off the resolution context
    and builds a single reveal from their hand. "Each opponent's hand" would
    need a loop it does not have and "your hand" is not an effect at all, so
    only the targeted form has a contract to lower onto.
    """
    if node.player.kind != "target_player":
        raise LoweringError(
            f"no handler for looking at {node.player.kind!r}'s hand", node=node
        )
    return (OracleInstruction("look_at_target_hand", "", _targets_only(node.player)),)


def _lower_look_at_library_top(
    node: ast.LookAtLibraryTop,
) -> tuple[OracleInstruction, ...]:
    """"Look at the top five cards of target player's library. You may then
    have that player shuffle that library." (Visions.)

    Only a chosen player has a contract to lower onto, for the reason
    :func:`_lower_look_at_hand` gives: the handler reads one player off the
    resolution context, and "each opponent" would need a loop it does not have.

    How many cards and whether the shuffle is offered are both payload. The
    number is obvious; the offer is the one that matters, because the handler
    that reads it today derived the same fact for Natural Selection by matching
    a substring of the card's oracle text — a card printing the offer in any
    other words would have been given a prompt with the option missing.
    """
    if node.player.kind != "target_player":
        raise LoweringError(
            f"no handler looks at the top of {node.player.kind!r}'s library", node=node
        )
    if not isinstance(node.count, ast.Fixed):
        raise LoweringError("the library look needs a printed number", node=node)
    payload: dict[str, object] = {
        "amount": node.count.value,
        "may_shuffle": node.may_shuffle,
    }
    payload.update(_targets_only(node.player))
    return (OracleInstruction("look_at_target_library_top", "", payload),)


# Restrictions the search flow can honour. `card_type` is compared against the
# card's `primary_type`, and `is_card` only says the noun phrase named cards —
# which a library holds by definition (CR 400.1). The rest come from
# `search_filters.SEARCH_RESTRICTIONS`, the one predicate the engine, the AI and
# the web picker all answer with, so this set cannot claim a restriction nobody
# tests. Every other field of the noun phrase is still refused by
# _restrictions_beyond, because nothing in the flow tests one: the player would
# simply be offered their whole library.
_SEARCH_HONOURED_FILTER_FIELDS = (
    frozenset({"card_types", "is_card", "supertypes"}) | SEARCH_RESTRICTIONS
)


def _lower_search_library(node: ast.SearchLibrary) -> tuple[OracleInstruction, ...]:
    """"Search your library for a card, put that card into your hand, then
    shuffle." (Demonic Tutor.)

    ``search_library`` arms ``pending_search_library``. A single-find search is
    answered by ``confirm_search_library``, which moves exactly **one** card
    and shuffles; a counted one ("up to two basic land cards", Cultivate) is
    answered whole by ``confirm_search_library_picks`` — every find in one
    answer — and which find fills which printed slot is then asked through the
    ``search_destination`` prompt. That is the flow's whole contract, so the
    two halves the parser read are checked against it here rather than
    dropped: a destination other than the searcher's own hand has no flow, and
    a restriction the picker cannot test would leave the player choosing from
    their entire library while the card still reported as supported.

    ``count`` is emitted even though only the UI displays it — the legacy rule
    wrote it and the payload has to stay byte-identical — but it is pinned to
    1, the number the confirm flow actually moves.
    """
    if node.player.kind != "you":
        raise LoweringError(
            f"no flow searches {node.player.kind!r}'s library", node=node
        )
    # Two destinations have a flow: the searcher's own hand (Demonic Tutor)
    # and the battlefield ("search your library for a creature card, put it
    # onto the battlefield" — Garruk, Unleashed's emblem). Anywhere else
    # refuses rather than landing the card in the wrong zone.
    to_battlefield = node.to.name == "battlefield"
    if not to_battlefield and (
        node.to.name != "hand" or node.to.owner is None or node.to.owner.kind != "you"
    ):
        raise LoweringError(
            "the search flow puts the found card into the searcher's own hand", node=node
        )
    filt = node.filter
    if not filt.is_card:
        # "Search your library for a creature" would be a permanent; a library
        # holds cards. Refusing keeps the noun phrase's head word load-bearing.
        raise LoweringError("a library holds cards, not permanents", node=node)
    leftover = _restrictions_beyond(filt, _SEARCH_HONOURED_FILTER_FIELDS)
    if leftover:
        raise LoweringError(
            "the search picker cannot test this restriction: " + ", ".join(leftover),
            node=node,
        )
    if len(filt.card_types) > 1:
        # The picker compares one `primary_type`, so a union would silently
        # widen to whichever type happened to be written first.
        raise LoweringError("the search picker tests one card type", node=node)
    card_type = filt.card_types[0] if filt.card_types else "any"
    restrictions: dict[str, object] = {}
    if filt.named is not None:
        restrictions["named"] = filt.named
    if filt.mana_value is not None:
        # A comparison the predicate cannot apply, or a bound that is not a
        # number ("with mana value X"), refuses rather than lowering to a search
        # that ignores the half of the sentence that made the card printable.
        value = _amount_payload(filt.mana_value.value)
        if filt.mana_value.op not in SEARCH_COMPARISONS or not isinstance(value, int):
            raise LoweringError(
                "the search picker cannot test this mana value: "
                f"{filt.mana_value.op} {value}",
                node=node,
            )
        restrictions["mana_value"] = {"op": filt.mana_value.op, "value": value}
    if filt.supertypes:
        # "a **basic** land card" — printed on the type line, so the picker can
        # read it off a card in a library where no computed characteristic is
        # available (CR 613.1).
        restrictions["supertypes"] = list(filt.supertypes)
    if filt.subtypes:
        # "a **Shrine** card" (Sanctum of All). Off the same printed line and
        # for the same reason. The field being *honoured* and the key being
        # *emitted* are two separate things, and this is the second: a filter
        # admitted by the gate above but left out here is a search that narrows
        # nothing while the card reports supported — the dropped-rider bug the
        # deletion probe exists to catch, and did.
        restrictions["subtypes"] = list(filt.subtypes)
    # One entry per find, in the printed order: how many are found and where each
    # goes are the same fact, so a card that names two destinations cannot lower
    # to a search that finds one.
    destinations = [_SEARCH_DESTINATIONS[node.to.name]]
    for zone in node.extra_destinations:
        if zone.name not in _SEARCH_DESTINATIONS:
            raise LoweringError(
                f"the search flow has no destination {zone.name!r}", node=node
            )
        if zone.name == "hand" and (zone.owner is None or zone.owner.kind != "you"):
            raise LoweringError(
                "the search flow puts a found card into the searcher's own hand",
                node=node,
            )
        destinations.append(_SEARCH_DESTINATIONS[zone.name])
    # "a card named A **and/or** a card named B" (Alpine Houndmaster): one find
    # per printed name, each optional. The names replace the single `named`
    # restriction rather than joining it — the flow drops each name as it is
    # used, so a `named` alongside them would narrow every find to the first.
    if node.named_alternatives:
        restrictions.pop("named", None)
        restrictions["named_among"] = list(node.named_alternatives)
        destinations = destinations * len(node.named_alternatives)
    payload: dict[str, object] = {"count": len(destinations), "card_type": card_type}
    if len(destinations) > 1:
        payload["destinations"] = destinations
        # One flag per destination, whatever the printed spelling gave: the
        # named-alternatives form multiplied the destinations above and prints no
        # "tapped" at all, and a short list would leave the last find reading a
        # flag that is not there.
        flags = list(node.tapped)
        payload["tapped"] = (flags + [False] * len(destinations))[:len(destinations)]
        # "and/or" is an "up to" in two words: either, both or neither is a
        # legal answer, so the flow must let the player stop.
        if node.up_to or node.named_alternatives:
            payload["up_to"] = True
    # These keys are emitted only when the card carries them, so the payload of
    # every search printed before this change — Demonic Tutor's — stays
    # byte-identical and a behaviour signature does not move.
    if node.reveal:
        # "…, reveal it/those cards, …" (CR 701.20): the find is shown to every
        # player, which the flow records as a reveal event for the UI. Emitted
        # only when printed — a tutor that does not reveal shows nothing.
        payload["reveal"] = True
    if restrictions:
        payload["restrictions"] = restrictions
    if node.graveyard:
        payload["zones"] = ("library", "graveyard")
    if to_battlefield and len(destinations) == 1:
        payload["destination"] = "battlefield"
        # "…put it onto the battlefield **tapped**" (Fabled Passage). Emitted
        # only when the card prints it, so every search written before this
        # keeps a byte-identical payload — and emitted at all, because a word
        # the production consumes and the payload drops is a land that enters
        # untapped while the card says otherwise.
        if any(node.tapped):
            payload["enters_tapped"] = True
        # "Then if you control four or more lands, untap that land." (Fabled
        # Passage.) The rider travels with the search because the land it
        # untaps is the one the search found; the count is taken when the find
        # is made (CR 608.2), which is after the land has entered — so the land
        # counts itself, and four means three plus this one.
        if node.untap_found_if is not None:
            counted = node.untap_found_filter or ast.ObjectFilter()
            payload["untap_found_if"] = {
                "threshold": _amount_payload(node.untap_found_if.value),
                "filter": count_spec(counted, node),
            }
    return (OracleInstruction("search_library", "", payload),)


#: The zone names the search flow can put a found card into. A name outside this
#: refuses rather than landing the card somewhere the flow does not implement.
_SEARCH_DESTINATIONS = {"hand": "hand", "battlefield": "battlefield"}


def _lower_exile_top_of_library(node: ast.ExileTopOfLibrary) -> tuple[OracleInstruction, ...]:
    """"Exile the top three cards of your library." (Chandra, Heart of Fire's
    +1.) The handler records what it exiled under ``exiled_cards``, which is
    what makes a following "you may play cards exiled this way" lowerable —
    see ``_lower_cast_permission``'s producer check."""
    amount = _amount_payload(node.count)
    if not isinstance(amount, int) or amount <= 0:
        raise LoweringError(
            "the top-of-library exile handler takes a fixed count", node=node
        )
    payload: dict = {"amount": amount}
    if node.face_down:
        payload["face_down"] = True
    return (OracleInstruction("exile_top_of_library", "", payload),)


#: Where a linked pile can be sent. Payload, not part of the kind: a second
#: card printing the sentence with another destination needs no code. A zone
#: outside this refuses, because a pile put somewhere the handler cannot reach
#: is a pile silently left in exile. A library is deliberately not here: a card
#: put into one has to go somewhere in it, and no printing of this sentence says
#: where.
_LINKED_EXILE_DESTINATIONS = frozenset({"hand", "graveyard", "battlefield"})


def _lower_put_exiled_with_source(
    node: ast.PutExiledWithSource,
) -> tuple[OracleInstruction, ...]:
    """"Put all cards exiled with this artifact into their owner's hand."
    (Knowledge Vault.)

    The owner reference is checked rather than dropped: every printing of this
    sentence sends each card to *its own* owner's zone (CR 400.3), and a
    wording naming one player would be a different effect the handler does not
    implement.
    """
    zone = node.zone
    if zone.name not in _LINKED_EXILE_DESTINATIONS:
        raise LoweringError(
            f"a linked exile cannot be put into the {zone.name}", node=node
        )
    if zone.owner is None or zone.owner.kind != "owner":
        raise LoweringError(
            "a linked exile goes to each card's own owner's zone", node=node
        )
    return (
        OracleInstruction("put_exiled_with_source", "", {"zone": zone.name}),
    )


# Restrictions the exile-search picker tests (engine/search_filters.py's
# vocabulary is not reused because this picker admits a *union* of card types,
# which the single-tutor flow deliberately refuses).
_SEARCH_EXILE_HONOURED = frozenset({"card_types", "colors", "is_card", "type_match"})


def _lower_search_and_exile(node: ast.SearchAndExile) -> tuple[OracleInstruction, ...]:
    """"Search your graveyard and library for any number of red instant and/or
    sorcery cards, exile them, then shuffle." (Chandra, Heart of Fire's −9.)

    Arms the multi-select search choice; the picks are validated against the
    same payload by the resolver, the AI default and the web renderer, so
    every seat answers the same search. A restriction the picker cannot test
    refuses rather than being dropped.
    """
    filt = node.filter
    if not filt.is_card:
        raise LoweringError("a search finds cards, not permanents", node=node)
    leftover = _restrictions_beyond(filt, _SEARCH_EXILE_HONOURED)
    if leftover:
        raise LoweringError(
            "the exile-search picker cannot test this restriction: "
            + ", ".join(leftover),
            node=node,
        )
    payload: dict[str, object] = {
        "zones": ("graveyard", "library"),
        "card_types": tuple(filt.card_types),
        "colors": tuple(filt.colors),
    }
    return (OracleInstruction("search_and_exile_matching", "", payload),)


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


def _lower_exile_graveyard_until_leaves(
    node: ast.ExileGraveyardUntilLeaves,
) -> tuple[OracleInstruction, ...]:
    """"Exile all creature cards with mana value 3 or less from your graveyard
    **until this artifact leaves the battlefield**." (Idol of Endurance.)

    A linked exile (CR 400.7): the cards are held by the *permanent*, so both
    halves of the card read one pile — what comes back when the Idol dies is
    what its ability could cast while it lived.
    """
    return (
        OracleInstruction(
            "exile_graveyard_until_leaves", "",
            {"filter": _linked_exile_filter(node.filter)},
        ),
    )


def _lower_transmute_by_sacrifice(
    node: "ast.TransmuteBySacrifice",
) -> tuple[OracleInstruction, ...]:
    """Transmute Artifact. Both printed nouns ride the payload; everything else
    the sentence says was required by the production that read it, so there is
    nothing left here to drop."""
    from ...subject_filters import object_only_filter

    sacrificed = _filter_payload(node.sacrificed)
    if object_only_filter(sacrificed) is None:
        # The sacrifice prompt is handed a set of the player's own permanents
        # and no observer, so a narrowing it cannot test would be dropped where
        # it is charged — the same refusal every sacrifice cost makes.
        raise LoweringError(
            "the sacrifice half of this effect cannot test that phrase", node=node
        )
    found = chargeable_card_filter(node.found)
    if found is None:
        raise LoweringError(
            "the search half of this effect cannot test that phrase", node=node
        )
    return (
        OracleInstruction(
            "transmute_by_sacrifice", "",
            {"sacrifice_filter": sacrificed, "search_filter": found},
        ),
    )


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
        if not (node.until_end_of_turn or node.until_source_grants_again):
            raise LoweringError(
                "an exiled-cards permission without its printed duration "
                "would outlive the card that granted it",
                node=node,
            )
        return (
            OracleInstruction(
                "grant_cast_permission", "",
                {
                    "zone": "exile",
                    "mode": node.mode,
                    "cards_from": "exiled_cards",
                    "duration": (
                        "end_of_turn" if node.until_end_of_turn
                        else "until_source_grants_again"
                    ),
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


def _lower_look_top_pick(
    node: ast.LookTopPickToHand, event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"Look at the top three cards of your library. Put one of those cards
    into your hand and the rest on the bottom of your library in any order.
    …" (See the Truth.) The handler asks its controller through the
    pending-choice queue when cast from the hand, and skips the choice
    entirely when the cast came from anywhere else — the conditional reads
    ``OracleExecutionContext.cast_from_zone``."""
    payload: dict[str, object] = {}
    # "Look at **that many** cards" (Garruk's Harbinger): the count is the
    # firing event's number, read out of the trigger's captured context by the
    # same channel every other back-reference uses. Demanded of the event rather
    # than assumed: under a trigger that records no quantity the words name
    # nothing, and a silent zero would look at no cards at all.
    if isinstance(node.count, ast.ThatMuch):
        payload.update(_back_reference_payload(node.count, frozenset(), event))
    else:
        amount = _amount_payload(node.count)
        if not isinstance(amount, int) or amount <= 0:
            raise LoweringError("the look-top pick takes a fixed count", node=node)
        payload["amount"] = amount
    if node.filters:
        described = [chargeable_card_filter(filt) for filt in node.filters]
        if any(entry is None for entry in described):
            raise LoweringError(
                "the pick cannot test this restriction on a card", node=node
            )
        payload["filters"] = tuple(described)
    if node.optional:
        payload["optional"] = True
    if node.rest_order != "any":
        payload["rest_order"] = node.rest_order
    if node.rest_destination != "library_bottom":
        payload["rest_destination"] = node.rest_destination
    if node.all_to_hand_if_cast_elsewhere:
        payload["all_to_hand_if_cast_elsewhere"] = True
    return (OracleInstruction("look_top_pick_to_hand", "", payload),)


def _lower_graveyard_pick_onto_battlefield(
    node: ast.PutOntoBattlefield,
) -> tuple[OracleInstruction, ...] | None:
    """"Put **a** creature card from the graveyard of <player> onto the
    battlefield **under its owner's control**." (Glyph of Reincarnation.)

    Here rather than beside the rest of the "put … onto the battlefield" family
    in ``lowering/zones``, because what it emits decides the family: no
    ``target`` is printed, so the card is not chosen until the effect resolves
    (CR 115.1b), and a pick made during resolution out of a named zone is a
    *search prompt* — the same instruction ``_lower_search_library`` above
    emits, narrowed to a graveyard. Sending it to the reanimation handler
    instead would have made it a cast-time target, which is a different card:
    the graveyard it comes out of is named by a referent nobody can evaluate
    until the earlier sentence has run.

    Returns None for every other "put onto the battlefield", so ``lower.py``
    falls through to that family and a line this is not keeps the refusal it
    already had.
    """
    target = node.target
    if not isinstance(target, ast.TargetSpec) or _is_target(target):
        return None
    filt = target.filter
    if filt.zone != "graveyard" or filt.zone_owner is None:
        return None
    record = PER_OBJECT_SEAT_RECORDS.get(filt.zone_owner.kind)
    if record is None:
        # Every *other* graveyard referent — "your graveyard", "that player's"
        # — is a seat the resolving player knows without any earlier step
        # having recorded it, and none of them is this shape. Handing them back
        # rather than refusing keeps this production additive.
        return None
    if not filt.is_card or filt.card_types != ("creature",):
        raise LoweringError(
            "this graveyard pick only moves creature cards", node=node
        )
    if _restrictions_beyond(
        filt, frozenset({"card_types", "is_card", "zone", "zone_owner"})
    ):
        raise LoweringError(
            "no graveyard pick reads a card narrowed this way", node=node
        )
    if not node.under_owners_control:
        # The card enters under whoever owns the graveyard it left, and that is
        # what the printed rider says. A sentence naming some *other* seat would
        # need a second reference here rather than this one standing in for it.
        raise LoweringError(
            "this graveyard pick only puts the card back under its owner's "
            "control", node=node,
        )
    return (
        OracleInstruction(
            "search_library",
            "",
            {
                "count": 1,
                "card_type": "creature",
                # A graveyard is an open zone, so nothing is revealed and
                # nothing is shuffled — the prompt is a pick, and the resolver
                # already tells the two apart by the zone it was armed with.
                "zones": ["graveyard"],
                "restrictions": {},
                "destination": "battlefield",
                # Whose graveyard, and whose battlefield. The same seat by
                # CR 404.1 — a card in a graveyard is in its owner's — but
                # written twice because the card prints both halves, and a
                # reader that inferred the second would be inferring it for
                # every card that names only the first.
                "zone_owner": record,
                "battlefield_owner": record,
            },
        ),
    )
