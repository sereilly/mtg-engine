"""Lowering a **search** (CR 701.23): a look through a whole zone for a card.

Split out of ``library.py`` at Visions' first wave, when that module reached the
thousand-line guard — and the name is not new: ``effects/search.py`` has carried
it on the parse side since Mirage, so this re-forms the mirror rather than
forking a third vocabulary for one printed idiom.

The seam is the one the parse side had already drawn. ``library`` is about a
pile of cards a flow *shows* somebody — a revealed hand, the top cards looked
at, a graveyard exiled wholesale — where a search is about a pile nobody may
see at all: CR 701.23a lets the searcher look through every card in the zone,
CR 701.23b lets them fail to find, and what the flow has to carry is therefore
which cards the phrase admits and where each find lands. Different question,
different closed sets, and the two halves share no reader.

The filter fields a search can honour are closed sets for the reason
``library``'s docstring gives its own: a field the picker cannot test would
leave the player choosing from their entire library while the card still
reported supported.
"""

from ...oracle_types import OracleInstruction
from ...search_filters import SEARCH_COMPARISONS, SEARCH_RESTRICTIONS
from .. import ast
from ..errors import LoweringError
from ._amounts import count_spec
from ._common import (
    _amount_payload,
    _describe_targets,
    _restrictions_beyond,
)
from ._events import _back_reference_payload


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
    # "…then shuffle and put that card on top" (the three Mirage tutors). A
    # third destination with a flow, and the only one whose *order* is part of
    # the effect: the card is placed after the shuffle, so it is on top rather
    # than somewhere random. The parse side carries no owner on this zone —
    # the library just shuffled is the searcher's by construction.
    to_library_top = node.to.name == "library_top"
    if not to_battlefield and not to_library_top and (
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
    # A printed union of types ("an artifact or enchantment card", Enlightened
    # Tutor) is carried as a tuple. It used to refuse — "the search picker tests
    # one card type" — which was true of `search_matches` and is not any more:
    # that predicate reads the key as an OR, the same reading it gives
    # `any_colors` beside it, so a union narrows the search rather than widening
    # it. Emitted as a bare word for the single-type case, so every payload
    # written before this branch existed is byte-identical.
    card_type = (
        tuple(filt.card_types) if len(filt.card_types) > 1
        else filt.card_types[0] if filt.card_types
        else "any"
    )
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
    if filt.colors:
        # "a **blue** instant card" (Merchant Scroll). The card's own colour
        # (CR 202.2), which a card in a library has and a computed
        # characteristic is not — the same admission the supertype and subtype
        # above get, and emitted here for the same reason the subtype's comment
        # gives: honoured and emitted are two facts, and a filter admitted by
        # the gate and dropped from the payload is a tutor for *any* instant
        # while the card still reports supported.
        #
        # ``any_colors``, not ``colors``: a multi-colour filter means "green
        # **or** white" here exactly as it does in ``ObjectFilter.to_payload``,
        # which emits that case under this name for every other matcher in the
        # engine. Spelling it the same way is what stops one field meaning
        # "or" to the battlefield and "and" to a library.
        restrictions["any_colors"] = list(filt.colors)
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
    if node.unbounded:
        # "…for **any number of** Goblin cards" (Goblin Recruiter). The ceiling
        # is the zone rather than the card, and only the resolution knows how
        # many cards a library holds — so the count travels as the printed word
        # and the handler resolves it, exactly as ``amount_from`` does for a
        # count an earlier step recorded. A number here would be a ceiling this
        # card does not print.
        payload["count"] = "any"
        payload["up_to"] = True
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
    if to_library_top:
        payload["destination"] = "library_top"
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
#: The third is "on top of your library" (the three Mirage tutors), and it is
#: the one whose *order* is part of the effect: the flow shuffles first and
#: places the find after, so the card is on top rather than back in the deck.
_SEARCH_DESTINATIONS = {
    "hand": "hand", "battlefield": "battlefield", "library_top": "library_top",
}

#: The same question for a search of *somebody else's* library. Exile is here
#: and not above because only this sentence prints it, and the hand is the
#: searched player's rather than the searcher's — which is what
#: `search_filters.landing_seat` already answers, so the zone name is the whole
#: of the difference.
_OTHER_SEARCH_DESTINATIONS = frozenset({"exile", "hand"})

#: The player references whose seat the search flow can name. "You" is
#: deliberately absent: that sentence is `_lower_search_library`'s, and reaching
#: it from here would be a second reading of one template.
_OTHER_SEARCH_PLAYERS = frozenset({"target_player", "target_opponent", "that_player"})


def _lower_search_player_library(
    node: ast.SearchPlayerLibrary, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """"Search target player's library for three cards and exile them. Then
    that player shuffles." (Jester's Cap.)

    The same ``search_library`` instruction the own-library tutor produces, with
    the seat whose zone is opened carried as payload — CR 608.2c makes the
    ability's controller the chooser either way, so what changes is one number
    the flow already reads (``engine/search_filters.searched_seat``) and not the
    flow.

    Both printed seats resolve to the ability's *target*: "target player's
    library" chooses one, and Jester's Mask's "that player" names the one its
    own first sentence already chose, which is the same seat. A reference that
    could be a third player refuses, because a search opening the wrong
    library is a strictly different card and silently so.
    """
    if node.player.kind not in _OTHER_SEARCH_PLAYERS:
        raise LoweringError(
            f"no flow searches {node.player.kind!r}'s library", node=node
        )
    if node.to.name not in _OTHER_SEARCH_DESTINATIONS:
        raise LoweringError(
            f"the search flow has no destination {node.to.name!r}", node=node
        )
    if node.to.name == "hand" and (
        node.to.owner is None or node.to.owner.kind not in _OTHER_SEARCH_PLAYERS
    ):
        # "…puts those cards into **their** hand" is the searched player's, which
        # is where `landing_seat` sends a find by default. Any other owner is a
        # third seat the flow has no way to name.
        raise LoweringError(
            "this search puts its finds into the searched player's own hand",
            node=node,
        )
    leftover = _restrictions_beyond(node.filter, _SEARCH_HONOURED_FILTER_FIELDS)
    if leftover:
        raise LoweringError(
            "the search picker cannot test this restriction: " + ", ".join(leftover),
            node=node,
        )
    if len(node.filter.card_types) > 1:
        raise LoweringError("the search picker tests one card type", node=node)
    payload: dict[str, object] = {
        "card_type": node.filter.card_types[0] if node.filter.card_types else "any",
        "destination": node.to.name,
        # The one key that makes this a search of somebody else's library. Read
        # by the handler into `zone_seat`, which the resolver, the AI's default
        # and the web picker all already ask.
        "zone_owner_target": True,
    }
    if isinstance(node.count, ast.ThatMuch):
        # "for **that many** cards" (Jester's Mask): the size of a hand an
        # earlier step of this same effect emptied. Demanded of that step rather
        # than assumed, exactly as every other back-reference is — a search for
        # a number nobody recorded would look for none.
        payload.update(_back_reference_payload(node.count, produced, None))
    else:
        amount = _amount_payload(node.count)
        if not isinstance(amount, int) or amount <= 0:
            raise LoweringError(
                "this search takes a fixed count or a recorded one", node=node
            )
        payload["count"] = amount
    if node.player.kind != "that_player":
        # "target player's library" is a cast-time choice the picker must offer;
        # "that player's" names one an earlier sentence of the same effect
        # already made. Describing the second would raise a second picker for a
        # target the ability already has.
        _describe_targets(payload, node.player)
    return (OracleInstruction("search_library", "", payload),)
