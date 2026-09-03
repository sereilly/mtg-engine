"""Lowering the hidden-zone flows: search, reveal and look-at.

Every shape here pivots on a pile of cards in a hidden zone offered through a
picker — a library search, a revealed hand, the top cards looked at, a
graveyard exiled wholesale. The search filter fields the flow can actually
honour are closed sets, because a filter it cannot honour must refuse rather
than be dropped.

**"and exile linkage" used to be the fourth conjunct of that first line**, and
it is `lowering/exile.py`'s now: the module crossed the thousand-line guard, and
the trailing conjunct was what had stopped being a lodger. Every shape that
moved pivots on the linked-exile record (`engine/linked_exile.py`) and on what
may later be cast out of it, which is that module's stated subject rather than
this one's, and the cut needed no import in either direction because the call
graph had already fallen apart there.
"""

from ...oracle_types import PER_OBJECT_SEAT_RECORDS, OracleInstruction
from ...search_filters import SEARCH_COMPARISONS, SEARCH_RESTRICTIONS
from ...subject_filters import card_only_filter
from .. import ast
from ..errors import LoweringError
from ._amounts import count_spec
from ._common import (
    chargeable_card_filter,
    _amount_payload,
    _describe_targets,
    _is_target,
    _restrictions_beyond,
    _targets_only,
)
from ._events import (
    _EVENT_SUBJECT_PLAYERS,
    EVENT_SUBJECT_PLAYER,
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
    node: ast.RevealHandAndChoose, event: str | None = None,
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
    # Both keys are emitted only when the card carries them, so Duress's payload
    # stays byte-identical and no behaviour signature moves.
    amount = _amount_payload(node.count)
    if amount != 1:
        payload["count"] = amount
    if not node.revealed:
        payload["looked_at"] = True
    if node.player.kind == "that_player":
        # "Look at **that player's** hand …" (Leshrac's Sigil). Nothing was
        # targeted, so there is no choice to read the seat off: it is the one
        # the firing event froze (CR 603.10), on the key its fire site stamps.
        # Refused under any other event rather than left to `context.target`,
        # which for a trigger that chose nothing is whatever the resolution
        # happened to be carrying — an opponent's hand emptied by accident.
        if event not in _EVENT_SUBJECT_PLAYERS:
            raise LoweringError(
                f"no event named {event!r} freezes the seat 'that player' names",
                node=node,
            )
        payload["victim"] = EVENT_SUBJECT_PLAYER
        return (OracleInstruction("reveal_hand_and_choose", "", payload),)
    _describe_targets(payload, node.player)
    if "targets" not in payload:
        raise LoweringError(
            f"the revealed-hand picker cannot name the {node.player.kind}",
            node=node,
        )
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
    payload = dict(_targets_only(node.player))
    if node.random_card:
        # "…**a card at random** in target player's hand" (Urza's Bauble). How
        # much of the hand is shown, emitted only when the card narrows it, so
        # Glasses of Urza's payload stays byte-identical.
        payload["random_card"] = True
    return (OracleInstruction("look_at_target_hand", "", payload),)


def _lower_separate_library_top_into_piles(
    node: "ast.SeparateLibraryTopIntoPiles",
) -> tuple[OracleInstruction, ...]:
    """Phyrexian Portal's whole procedure, one instruction.

    The splitter travels as a *targets* description rather than as a bare seat
    word, because "target opponent" is a choice made at announcement (CR
    601.2c) and the picker reads that payload - a card whose splitter was a
    literal would offer no picker and let the client send a bare activation.

    The count is payload; the shape is not. Two piles, face down, one exiled
    and the other searched is what the card *is*, and a wording that differed
    refuses at the production rather than arriving here as another key.
    """
    if node.splitter.kind not in ("target_player", "target_opponent"):
        raise LoweringError(
            f"no pile split names {node.splitter.kind!r} as its divider",
            node=node,
        )
    payload: dict[str, object] = {"count": _amount_payload(node.count)}
    _describe_targets(payload, node.splitter)
    return (
        OracleInstruction("separate_library_top_into_piles", "", payload),
    )


def _lower_look_top_cycle_for_life(
    node: "ast.LookTopCycleForLife",
) -> tuple[OracleInstruction, ...]:
    """Lim-Dul's Vault's whole procedure, one instruction (CR 701.24).

    Both numbers travel as payload for the reason every parameter in this
    pipeline does: a card cycling three cards for 2 life needs no code. What
    does *not* travel is the shape - the bottom, the shuffle and the stack on
    top are the effect itself, so a wording that sorted them elsewhere refuses
    at the production rather than arriving here as a fourth key.
    """
    return (
        OracleInstruction(
            "look_top_cycle_and_stack", "",
            {
                "count": _amount_payload(node.count),
                "life_cost": _amount_payload(node.life_cost),
            },
        ),
    )


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
    # "…then put them back in any order" is the *other* handler, not a flag on
    # this one: `may_reorder` is enforced where the prompt is answered, so a
    # card that only looks can never be handed a rearrangement.
    kind = (
        "reorder_target_library_top" if node.may_reorder
        else "look_at_target_library_top"
    )
    return (OracleInstruction(kind, "", payload),)


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
    if node.pick_destination != "hand":
        payload["pick_destination"] = node.pick_destination
    if node.all_to_hand_if_cast_elsewhere:
        payload["all_to_hand_if_cast_elsewhere"] = True
    # Who looks, when the sentence names them. Only the one seat this handler
    # can find without a second question: "target player" is chosen as the
    # ability is activated (CR 602.2b) and arrives as ``context.target``.
    # Anything else refuses rather than defaulting to the controller — a look
    # at the wrong library is a card doing something it never said, and the
    # pile is hidden, so nobody would see it happen.
    if node.looker is not None:
        if node.looker.kind != "target_player":
            raise LoweringError(
                "the look-top pick reads the library of the player the ability "
                "chose",
                node=node,
            )
        payload["looker"] = "target_player"
    return (OracleInstruction("look_top_pick_to_hand", "", payload),)


def _lower_look_top_exile_random(
    node: ast.LookTopExileRandom,
) -> tuple[OracleInstruction, ...]:
    """"Look at the top eight cards of your library. Exile four of them at
    random, then put the rest on top of your library in any order." (Orcish
    Librarian.)

    Both counts are fixed numbers the card prints. A back-reference would have
    to name an event this statement has no access to, and an X would have to
    survive to a resolution that happens after the cost is paid — neither is a
    shape any printing of this sentence has, so both refuse rather than
    resolving to a silent zero.
    """
    looked = _amount_payload(node.count)
    exiled = _amount_payload(node.exile_count)
    if not isinstance(looked, int) or looked <= 0:
        raise LoweringError("the look-and-exile takes a fixed count", node=node)
    if not isinstance(exiled, int) or exiled <= 0:
        raise LoweringError("the random exile takes a fixed count", node=node)
    if exiled > looked:
        raise LoweringError(
            "more cards are exiled than are looked at", node=node
        )
    return (
        OracleInstruction(
            "look_top_exile_random", "",
            {"amount": looked, "exile_count": exiled},
        ),
    )


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
