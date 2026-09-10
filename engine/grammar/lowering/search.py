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

from ...oracle_types import (COUNTERED_SPELL_CONTROLLER, COUNTERED_SPELL_NAME,
                             LAST_TARGET_CONTROLLER, LAST_TARGET_NAME,
                             OracleInstruction)
from ...search_filters import SEARCH_COMPARISONS, SEARCH_RESTRICTIONS
from ._deaths import BOUND_CARD_EVENTS
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
    frozenset({
        "card_types", "is_card", "supertypes", "named_as_target",
        # "…a card **with the same name as that creature**" (Remembrance). The
        # name of the object the firing event was about — honoured here and
        # gated on the event below, since the field on its own says nothing
        # about whether anything recorded one.
        "name_from_event",
    })
    | SEARCH_RESTRICTIONS
)


def _lower_search_library(
    node: ast.SearchLibrary, event: str | None = None,
) -> tuple[OracleInstruction, ...]:
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
    # "…put them into your **graveyard**, then shuffle." (Buried Alive; Entomb
    # prints the single-find spelling.) A fourth destination with a flow, and
    # the possessive is required for the hand's reason: CR 404.1 sends a card
    # to the graveyard of the player who owns it, and the only owner this flow
    # can name is the seat whose library was opened.
    to_graveyard = node.to.name == "graveyard" and (
        node.to.owner is not None and node.to.owner.kind == "you"
    )
    if not to_battlefield and not to_library_top and not to_graveyard and (
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
    # "…a card **with the same name as target nontoken creature**" (Mask of the
    # Mimic). The name is not knowable here — the target is chosen as the spell
    # is cast (CR 601.2c) — so what travels is the *question*, and the handler
    # answers it off ``context.target`` when the search is armed. A restriction
    # the picker could not test would leave the player choosing from their whole
    # library, which is what this key exists to prevent rather than to become.
    if filt.named_as_target is not None:
        if filt.named is not None:
            # Two names for one find, and only one can be honoured. Refused
            # whole rather than charged as the half that matched, which is this
            # module's rule everywhere else.
            raise LoweringError(
                "one find is named once", node=node
            )
        restrictions["named_from_target"] = True
        # Built from the filter the phrase read, through the one description
        # builder every other targeted lowering uses -- so what the picker
        # offers, what the gate admits and what the handler reads the name off
        # are one answer.
        payload_targets: dict[str, object] = {}
        _describe_targets(
            payload_targets,
            ast.TargetSpec(
                quantifier="target",
                filter=filt.named_as_target,
                targeted=True,
            ),
        )
    if filt.name_from_event:
        # "…**with the same name as that creature**" (Remembrance). The name is
        # not knowable when the card compiles, exactly as ``named_as_target``'s
        # is not: it is turned into an ordinary ``named`` where the search is
        # armed (`handlers/zones._search_restrictions`), so every seat answers
        # the same search — the engine re-checking a pick, the AI choosing and
        # the web picker offering all read ``search_matches`` and none of them
        # has a trigger context in hand.
        #
        # Gated on ``BOUND_CARD_EVENTS`` — the fire sites that actually record
        # the object — rather than on the one event this card prints, because
        # that table is the claim this reading depends on and a second list
        # would be free to disagree with it. Under any other event the words
        # name a creature nobody wrote down, and the honest answer is a refusal
        # rather than a search of the whole library.
        if event not in BOUND_CARD_EVENTS:
            raise LoweringError(
                "\"that creature\" names the firing event's object, and this "
                "event records none",
                node=node,
            )
        if filt.named is not None:
            raise LoweringError("one find is named once", node=node)
        restrictions["named_from_event"] = True
    if filt.mana_value is not None:
        # A comparison the predicate cannot apply, or a bound that is not a
        # number ("with mana value X"), refuses rather than lowering to a search
        # that ignores the half of the sentence that made the card printable.
        value = _amount_payload(filt.mana_value.value)
        # "…a creature card with mana value **X** or less" (Citanul Flute). The
        # bound is the ability's own X, which CR 601.2b fixed when the cost was
        # paid — so it is a number by the time anything looks in the library,
        # just not a number this compile can write down. It travels as the
        # literal ``"x"`` and is resolved once, where the search is armed
        # (`handlers/zones._search_restrictions`), so the picker, the AI and the
        # re-check all read one already-resolved bound rather than three
        # readings of a symbol.
        #
        # Only ``"x"``. Every other non-numeric bound still refuses, which is
        # what keeps this from becoming "any amount the payload happened to
        # carry" — a search that ignores the half of the sentence that made the
        # card printable.
        if filt.mana_value.op not in SEARCH_COMPARISONS or not (
            isinstance(value, int) or value == "x"
        ):
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
        if zone.name in ("hand", "graveyard") and (
            zone.owner is None or zone.owner.kind != "you"
        ):
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
    if filt.named_as_target is not None:
        # The spell's own target (CR 601.2c), so ``engine/targeting.py`` raises
        # the picker and ``legality`` gates the announcement — the search's find
        # is chosen at resolution and this is not that choice.
        payload.update(payload_targets)
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
    if node.exile_rest:
        # "…and exile the rest." (Doomsday.) What becomes of the searched piles
        # once the finds are out of them \u2014 a fact about the zones rather than
        # about a find, which is why it rides beside ``zones`` and not in
        # ``destinations``. Emitted only when the card prints it, so every
        # search written before this keeps a byte-identical payload.
        payload["exile_rest"] = True
    if to_library_top:
        payload["destination"] = "library_top"
    if to_graveyard and len(destinations) == 1:
        # The single-find spelling (Entomb). The counted one carries its zone in
        # ``destinations`` above, which is the list `_place_found_card` walks;
        # this key is what the one-card resolver reads instead.
        payload["destination"] = "graveyard"
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
    found = OracleInstruction("search_library", "", payload)
    if not node.discard_after:
        return (found,)
    # "…, **discard a card at random**, then shuffle." (Gamble.) Two
    # instructions, not one fused kind: the discard is an ordinary discard and
    # the search is an ordinary search, and what makes the card a gamble is
    # only the *order* — the tutored card is in the hand by the time the random
    # pick is made, because the search's prompt is answered before the sentence
    # behind it runs (CR 608.2, CR 117.3b).
    #
    # The printed shuffle sits between them on the card and nowhere in the IR,
    # because the flow shuffles as the find is confirmed; there is no
    # observable difference, since a shuffle of a library changes nothing about
    # a hand.
    #
    # The two kinds are the ones "discard a card at random" and "discard a
    # card" already lower to on their own, so a card printing the chosen
    # spelling gets the chosen handler rather than a random discard nobody
    # asked for.
    discard = (
        OracleInstruction(
            "discard_x_target_cards", "",
            {"amount": node.discard_after, "who": "caster"},
        )
        if node.discard_after_at_random
        else OracleInstruction(
            "discard_controller_cards", "", {"amount": node.discard_after},
        )
    )
    return (found, discard)


#: The zone names the search flow can put a found card into. A name outside this
#: refuses rather than landing the card somewhere the flow does not implement.
#: The third is "on top of your library" (the three Mirage tutors), and it is
#: the one whose *order* is part of the effect: the flow shuffles first and
#: places the find after, so the card is on top rather than back in the deck.
#: The fourth is the searcher's own graveyard (Buried Alive, Entomb) — an
#: ordered zone too (CR 404.1), but its order is not this card's business:
#: nothing is placed relative to what is already there, so each find is simply
#: put in, through ``put_card_into_graveyard``.
_SEARCH_DESTINATIONS = {
    "hand": "hand", "battlefield": "battlefield", "library_top": "library_top",
    "graveyard": "graveyard",
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


#: The scratchpad key a **held** search writes its finds under, and the one the
#: pick behind it reads. Spelled once, here, for ``_records``' standing reason:
#: a channel written at one end and read at the other is a channel that can be
#: renamed at one end.
HELD_SEARCH_PILE = "held_search_pile"


def _lower_search_reveal_opponent_chooses(
    node: "ast.SearchRevealOpponentChooses",
) -> tuple[OracleInstruction, ...]:
    """"Search your library for three cards and reveal them. Target opponent
    chooses one. Put that card into your hand and the rest into your graveyard.
    Then shuffle." (Intuition.)

    **Two instructions, and that is the whole design.** The pile is found by one
    seat and disposed of by another, and both halves already exist: the search
    is the standing ``search_library`` with its finds *held* — Transmute
    Artifact's word for a find whose destination is a later step's decision —
    and the pick is the standing ``reveal_top_opponent_chooses``, which has
    carried a chosen card's fate and the rest's since Phyrexian Grimoire. What
    is new is one payload key on each: where the held pile is written, and
    where it is read.

    Fusing them into one handler is what the naming family's own docstring
    warns against — "the lowering carries the bounds of the choice and nothing
    else" — and it would be a third implementation of a search and a pick.

    ``up_to`` is deliberately **absent**: CR 701.23d makes a search for a bare
    quantity find that many, or as many as possible, and the resolver enforces
    that floor for exactly the searches that omit the key. Every counted search
    printed before this one says "up to" or "any number of".

    The chooser is required to be a targeted opponent, for
    ``_lower_reveal_top_opponent_chooses``' reason word for word: CR 608.2c
    makes the ability's controller the actor for anything the sentence does not
    say otherwise about, so a seat this cannot name would silently become the
    chooser — which on this card is the caster choosing which of their own
    three finds they keep.
    """
    if node.chooser.kind != "target_opponent":
        raise LoweringError(
            f"no flow lets {node.chooser.kind!r} choose from a searched pile",
            node=node,
        )
    count = _amount_payload(node.count)
    if not isinstance(count, int) or count <= 0:
        raise LoweringError(
            "the searched pile is a fixed number of cards", node=node
        )
    search = OracleInstruction(
        "search_library", "",
        {
            "count": count,
            "card_type": "any",
            # One entry per find, which is what drives the counted answer — the
            # whole pick list in one action, validated together.
            "destinations": ["held"] * count,
            "tapped": [False] * count,
            # "…and **reveal them**." CR 701.20a: the finds are shown to every
            # player when the search ends.
            "reveal": True,
            "record_key": HELD_SEARCH_PILE,
        },
    )
    pick: dict[str, object] = {
        "count": count,
        "cards_from": HELD_SEARCH_PILE,
        "fate": node.fate,
        "other_fate": node.other_fate,
    }
    _describe_targets(pick, node.chooser)
    return (
        OracleInstruction(
            "sequence", "",
            {
                "steps": (
                    search,
                    OracleInstruction("reveal_top_opponent_chooses", "", pick),
                ),
            },
        ),
    )


#: The seats a strip-by-name can open the zones of. "You" is deliberately
#: absent: no card asks its own controller to lose every copy of a card they
#: just chose, and a seat this cannot name is a search of the wrong library —
#: strictly a different card, and silently so.
_STRIP_PLAYERS = frozenset({
    "target_player", "target_opponent", "that_player",
    # "Search **its controller's** graveyard, hand, and library …" (Eradicate,
    # Scour, Splinter, Sowing Salt, Quash.) The possessive names the object the
    # sentence in front of this one chose, so the seat is not on the payload at
    # all — it comes off the same record pair the name does, below. Admitted
    # here rather than beside them because this set is about which *printed*
    # references have a reading, and this one does.
    "controller",
})

#: What "…with the same name as that **<noun>**" reads, as
#: ``printed noun -> (name record, seat record)``.
#:
#: Two rows because two kinds of object can be behind the sentence and they are
#: recorded by handlers in different modules: an exile or a destroy writes down
#: the permanent it chose, and a counter writes down the spell it chose. A spell
#: on the stack is not a permanent (CR 111.1), which is the same reason
#: ``oracle_types`` keeps the two seat keys apart, and one shared row would let
#: "that creature" behind a counterspell take the stack reading.
#:
#: The seat travels with the name rather than being looked up separately,
#: because the two answer one question — whose zones hold the copies of the
#: object this spell just dealt with — and a pair that could come apart would
#: let a strip open the right library and search it for nothing.
_STRIP_NAME_RECORDS: dict[str, tuple[str, str]] = {
    "spell": (COUNTERED_SPELL_NAME, COUNTERED_SPELL_CONTROLLER),
    "*": (LAST_TARGET_NAME, LAST_TARGET_CONTROLLER),
}


def _lower_strip_cards_with_chosen_name(
    node: "ast.StripCardsWithChosenName", produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"Search that player's graveyard, hand, and library for all cards with the
    same name as the chosen card and exile them. Then that player shuffles."
    (Lobotomy.)

    ``produced`` is the whole gate. The name is the one an earlier step of this
    same spell recorded (``chosen_card_name``), and with no such step the words
    name nothing — the search would then match no card and the spell would
    resolve, report supported and do nothing at all. Refused by name instead,
    exactly as ``_lower_reveal_top_sorting_by_chosen_name`` refuses "that name"
    with no naming step in front of it.

    CR 701.23c is about this card by name: a hand with no cards in it makes the
    quality *undefined*, and the searcher still searches and finds nothing. That
    is the handler's business, not this one's — what is refused here is a
    sentence with no naming step at all, which is a different thing from a
    naming step that named nothing.

    "That player" is the seat the sentence in front of this one targeted, which
    is the same reference ``_lower_search_player_library`` reads for Jester's
    Mask — so no target is described here and no second picker is raised.
    """
    if node.player.kind not in _STRIP_PLAYERS:
        raise LoweringError(
            f"no flow strips {node.player.kind!r}'s zones", node=node
        )
    payload: dict[str, object] = {"zones": list(node.zones)}
    if node.name_of is not None:
        # "…with the same name as **that creature**" (Eradicate, and its four
        # siblings). The same gate as Lobotomy's below and the same reason for
        # it — the name is a record an earlier step wrote — asked of the pair
        # the printed noun names. Both keys are required: a step that recorded
        # only one of them is a strip that opens a library and searches it for
        # nothing, which is the silent half-effect this whole function refuses.
        name_record, seat_record = _STRIP_NAME_RECORDS.get(
            node.name_of, _STRIP_NAME_RECORDS["*"]
        )
        if name_record not in produced or seat_record not in produced:
            raise LoweringError(
                f'"that {node.name_of}" names an object no step of this spell '
                "recorded",
                node=node,
            )
        payload["name_record"] = name_record
        payload["seat_record"] = seat_record
        if node.player.kind != "controller":
            # "**Its** controller" is the possessive that reads a record. A
            # sentence naming a seat outright ("that player's graveyard") after
            # a step that chose an *object* is naming somebody the record does
            # not answer for, and taking the record anyway would open a library
            # the card never pointed at.
            raise LoweringError(
                "a strip by a recorded name opens that object's controller's "
                f"zones, not {node.player.kind!r}'s",
                node=node,
            )
        return (
            OracleInstruction("strip_cards_with_chosen_name", "", payload),
        )
    if node.player.kind == "controller":
        # The other direction of the pair above: "its controller" with nothing
        # for "its" to point at. Lobotomy's reading names the seat it searched
        # outright, so this possessive belongs to the recorded-name branch and
        # to nothing else.
        raise LoweringError(
            '"its controller" names an object this sentence never mentions',
            node=node,
        )
    if "chosen_card_name" not in produced:
        raise LoweringError(
            "\"the chosen card\" names a card no step of this spell chose",
            node=node,
        )
    if node.player.kind != "that_player":
        _describe_targets(payload, node.player)
    return (
        OracleInstruction("strip_cards_with_chosen_name", "", payload),
    )
