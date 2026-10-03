"""Cards exiled *with* a source, and where a linked pile goes next (CR 610.3).

Split out of `lowering/exile.py` at Tempest's Phase 0, and the cut is not a new
line: it is the section divider that module had carried whole since the block
arrived, header and reason together —

    "Cards exiled *with* a source, and the permission to cast them.

    Moved here whole from `lowering/library.py` when that module crossed the
    thousand-line guard. Its docstring named its family 'search, reveal,
    look-at, **and exile linkage**', and the trailing conjunct is what had
    stopped being a lodger: every shape below pivots on the linked-exile record
    (`engine/linked_exile.py`) and on what may later be cast out of it, which is
    this module's stated subject and not that one's. The cut is where the call
    graph already fell apart — nothing left in `library` calls anything below
    and nothing below calls anything left there, which is what the family rule
    requires of two families in one package."

Read a second time, that paragraph is the argument for this file: the block was
a lodger in `library` for the same reason it was a lodger in `exile`, and the
call graph fell apart in the same place both times — `exile` moves an object
*into* the exile zone and refuses the shapes no handler implements, where every
production here starts from a pile that is already there and asks whose it is,
where it goes, and what may be done with it. Neither module calls the other, at
either split.

Its **permission** half has already gone: `_lower_cast_permission` left for
`permissions` when `exile` crossed the guard at Alliances, so the divider's
title is one clause out of date and this file is the other clause of it.

The name is `engine/linked_exile.py`'s — the record every shape here pivots on
— so the mirror re-forms rather than forking a third word for one subject, the
same reuse `untap_restrictions` and `base_pt` make of their engine modules.
`effects/` and `ast/` have no `linked_exile`, for `permissions`' reason: the
guard fired on the lowerings, and the nodes are cards in a zone that sit
perfectly well beside the other card ones.

A family rather than a floor: nothing in `lowering/` reads these, `by_node` and
`statement_dispatch_naming` reach them through the package's flat re-export, and
they read no sibling family back.
"""

from __future__ import annotations

from ...oracle_types import EXILED_BY_SEAT, OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (
    _amount_payload, _filter_payload, _restrictions_beyond,
    chargeable_card_filter,
)
from ._events import (EVENT_SUBJECT_PLAYER, EXILED_THIS_WAY_OBJECTS,
                      _EVENT_SUBJECT_OBJECTS, _EVENT_SUBJECT_PLAYERS)
from ._piles import _SEARCH_EXILE_HONOURED, _linked_exile_filter


def _lower_exile_entire_library(
    node: ast.ExileEntireLibrary, event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """"That player exiles all cards from their library." (Thought Lash.)

    Whose library rides the ``recipient`` key the mill and the life loss
    already use — one convention for "who does this happen to" rather than a
    second per family.

    "That player" is the seat the *firing event* named, frozen into the
    trigger's context by the fire site (CR 603.10), so it is admitted only
    under an event that freezes one. Read as the resolving player instead, a
    card naming somebody else would empty its own controller's library — and
    for this effect that is the game, not a smaller effect.
    """
    kind = node.player.kind
    if kind == "you":
        recipient = "caster"
    elif kind == "that_player":
        if event not in _EVENT_SUBJECT_PLAYERS:
            raise LoweringError(
                "no event named {!r} freezes the seat 'that player' names".format(event),
                node=node,
            )
        recipient = EVENT_SUBJECT_PLAYER
    else:
        raise LoweringError(
            f"no handler empties the library of {kind!r}", node=node
        )
    return (
        OracleInstruction("exile_entire_library", "", {"recipient": recipient}),
    )


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
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """"Put all cards exiled with this artifact into their owner's hand."
    (Knowledge Vault.)

    The owner reference is checked rather than dropped: every printing of this
    sentence sends each card to *its own* owner's zone (CR 400.3), and a
    wording naming one player would be a different effect the handler does not
    implement.

    "Return **a card you own** exiled with this artifact to **your** hand"
    (Gustha's Scepter) is the one wording that legitimately names a player, and
    only because it has already narrowed the pile to that player's own cards:
    "your hand" and "its owner's hand" are then the same zone by construction,
    which is why the two clauses are read together rather than either being
    admitted alone.
    """
    zone = node.zone
    if zone.name not in _LINKED_EXILE_DESTINATIONS:
        raise LoweringError(
            f"a linked exile cannot be put into the {zone.name}", node=node
        )
    owner_kind = zone.owner.kind if zone.owner is not None else None
    # "Return **a card** exiled with this enchantment **to the battlefield**."
    # (Purgatory.) The one destination with no possessive to print — a
    # battlefield is nobody's zone — so CR 110.2a decides instead: the card
    # enters under the control of the player the effect instructed to put it
    # there, which is this ability's controller. Recorded rather than left to
    # the handler's default, which is the card's *owner*: the two coincide for
    # every printing of this sentence in the pool and would silently diverge
    # the moment one did not.
    under_controller = (
        # "…to the battlefield **under your control**" (Cold Storage): the
        # printed clause, on a sweep. Read before the inference below it, and
        # not folded into it: that one reads an *absent* possessive on a chosen
        # card (Purgatory), and Safe Haven prints "under its owner's control"
        # onto the same sweep — so on this shape the seat has to come from the
        # words rather than from their absence.
        node.under_your_control
        or (node.chosen and zone.name == "battlefield" and owner_kind is None)
    )
    if not under_controller and owner_kind != "owner" and not (
        (node.chosen or node.others_only) and owner_kind == "you"
    ):
        raise LoweringError(
            "a linked exile goes to each card's own owner's zone", node=node
        )
    if node.others_only:
        # "Put **all other** cards you own exiled with this enchantment into
        # your hand." (Duplicity.) A back-reference, demanded like every other
        # one: "other" is other than the cards a step of *this* effect exiled,
        # and with no such step the word excludes nothing — the sweep would
        # hand back the cards the sentence in front of it had just taken, and
        # the enchantment would compile clean and do nothing at all.
        if "exiled_entries" not in produced:
            raise LoweringError(
                "'all other cards' names an exile this effect did not perform",
                node=node,
            )
    payload: dict[str, object] = {"zone": zone.name}
    if node.others_only:
        payload["others_only"] = True
        # "…cards **you own**…" on a sweep. The sweep sends every card to its
        # own owner, so this narrows *which* cards move rather than where they
        # go — the same key the chosen form carries, because the handler asks
        # one question.
        if node.owned_by_you:
            payload["owned_by_chooser"] = True
    # "Return **each creature card** exiled with this artifact…" (Cold Storage).
    # The printed narrowing, carried onto the instruction rather than dropped:
    # the pile is whatever the linked twin put there, and a card whose types
    # changed while it was exiled is exactly where "creature card" stops being
    # a description of the whole pile.
    if node.card_type is not None:
        payload["card_type"] = node.card_type
    if node.under_your_control and not node.chosen:
        # The sweep's seat (CR 110.2a). The chosen form ships the same fact
        # under `under_control_of` below; both spell it the same way for the
        # handler, which asks one question.
        payload["under_control_of"] = "chooser"
    if node.chosen:
        payload["one_of"] = True
        # "…a card **you own**…" (Gustha's Scepter) narrows the pile to the
        # chooser's own cards; Purgatory prints no such clause and its pile
        # holds every card the enchantment exiled. A narrowing applied where the
        # card prints none would leave a card in exile the sentence says comes
        # back.
        if node.owned_by_you:
            payload["owned_by_chooser"] = True
        if under_controller:
            payload["under_control_of"] = "chooser"
    return (
        OracleInstruction("put_exiled_with_source", "", payload),
    )


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
        "zones": tuple(node.zones),
        "card_types": tuple(filt.card_types),
        "colors": tuple(filt.colors),
    }
    if node.count is not None:
        # "…for **three** cards" (Foresight). A ceiling and not a requirement
        # (CR 701.23b), emitted only when printed so every payload written for
        # the "any number of" spelling stays byte-identical.
        payload["maximum"] = node.count
    if node.face_down_pile:
        # "…exile them in a face-down pile" (Mangara's Tome). The finds become
        # a **linked** pile on the exiling permanent (CR 610.3), which is the
        # only thing a later "the exiled pile" can name — so a card printing
        # the phrase with no permanent behind it (an instant) would exile face
        # down into nothing, and the handler refuses there rather than here,
        # where the source is not yet known.
        payload["face_down_pile"] = True
    if node.shuffle_pile:
        payload["shuffle_pile"] = True
    return (OracleInstruction("search_and_exile_matching", "", payload),)


def _lower_put_exiled_pile_top_into_hand(
    node: "ast.PutExiledPileTopIntoHand",
) -> tuple[OracleInstruction, ...]:
    """"Put the top card of the exiled pile into its owner's hand." (Mangara's
    Tome.) No payload: the pile is CR 610.3's linked record on the ability's
    own source, so which cards and whose are read at resolution rather than
    described here."""
    return (OracleInstruction("put_exiled_pile_top_into_hand", "", {}),)


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


def _lower_put_exiled_card_into_zone(
    node: "ast.PutExiledCardIntoZone", produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """``Put that card into your hand.`` (Necropotence, inside its delay.)
    ``If you haven't played it, put it into its owner's graveyard.``
    (Grinning Totem, inside its delay.)

    Here rather than in the dispatch chain for the reason every other lowering
    is in a family: the chain routes, and the *rules* about which destination a
    handler implements are exile's business. It moves an object out of the
    exile zone, which is this module's own line.
    """
    # The producer gate every back-reference makes: "that card" / "it" names
    # what a step of this same effect exiled, and a sentence with no exile
    # behind it would put nothing anywhere while the card compiled supported.
    if "exiled_cards" not in produced:
        raise LoweringError(
            "'that card' names a card no step of this effect exiled", node=node
        )
    zone = node.zone
    owner = zone.owner.kind if zone.owner is not None else None
    # Two destinations, and the possessive each is printed with is part of it.
    # "Put that card into **your** hand" (Necropotence) is the caster's; "put it
    # into **its owner's** graveyard" (Grinning Totem) is the card's owner's,
    # which is a different seat the moment the card came out of somebody else's
    # library — CR 400.3, and the whole reason that card can be played from a
    # pile the caster does not own. A third spelling refuses rather than landing
    # the card in a zone no handler implements.
    if zone.name == "hand" and owner == "you":
        payload: dict[str, object] = {"zone": "hand"}
    elif zone.name == "hand" and owner == "owner" and node.only_if_unplayed:
        # "…if you haven't cast the card, return it to **its owner's** hand."
        # (Psychic Theft.) The seat whose exile held it, not the caster's.
        payload = {"zone": "hand", "to_owner": True}
    elif zone.name == "graveyard" and owner in ("owner", "you"):
        payload = {"zone": "graveyard"}
    else:
        raise LoweringError(
            f"no handler puts an exiled card into {owner!r}'s {zone.name}",
            node=node,
        )
    if node.only_if_unplayed:
        payload["only_if_unplayed"] = True
    return (OracleInstruction("put_exiled_cards_into_zone", "", payload),)


def _lower_put_exiled_pile_on_library(
    node: "ast.PutExiledPileOnLibrary",
) -> tuple[OracleInstruction, ...]:
    """"Then look at the exiled cards and put them on top of your library in
    any order." (Scroll Rack.)

    One instruction for both clauses, for the node's reason: the look is what
    makes the order a choice, because CR 406.3 hides the pile from everybody
    including the seat that made it.

    Nothing to check but the position, which the production has already read
    against a closed list — the pile is the record's answer, so there is no
    filter and no target for the lowering to refuse.
    """
    return (
        OracleInstruction(
            "put_exiled_pile_on_library", "", {"position": node.position},
        ),
    )


#: Where a per-seat pile can be sent. The sibling of
#: :data:`_LINKED_EXILE_DESTINATIONS` above and deliberately narrower: the one
#: printing in the pool says "onto the battlefield", and a destination with no
#: handler behind it would leave the cards in exile while the card compiled
#: supported.
_EXILED_THIS_WAY_DESTINATIONS = frozenset({"battlefield", "hand"})


def _lower_put_exiled_this_way(
    node: "ast.PutExiledThisWay", produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """"Each player … **puts all cards they exiled this way onto the
    battlefield**." (Living Death.)

    Here rather than in ``exile`` for this module's stated line: the pile is
    already in exile and the sentence asks whose it is and where it goes, which
    is every production in this file. What makes it this file's rather than
    ``_lower_put_exiled_with_source``'s is *which* record answers "whose" — a
    linked pile is keyed on the exiling permanent (CR 610.3), and this one is
    keyed on the **seat**, because the exiling step was a sweep a sorcery
    performed and a sorcery is no permanent to hang a record on.

    The producer gate every back-reference in this grammar makes: "exiled this
    way" names what a step of *this same effect* exiled, and with no such step
    the words name nothing — the sentence would put nothing anywhere while the
    card reported supported, which is the failure this repo's whole
    back-reference convention exists to make loud.

    The **destination seat is not payload**, and that is the one thing worth
    saying twice. Each seat puts back its own pile, so CR 110.2a hands each
    player control of what they put there; ``who`` says the loop runs per seat
    and the seat that put a card there is the seat it enters under. A single
    ``under_control_of`` here would be the mass-reanimation card turned into
    the one-player-takes-everything card, which is a different and much better
    spell.
    """
    zone = node.zone
    if zone.name not in _EXILED_THIS_WAY_DESTINATIONS:
        raise LoweringError(
            f"no handler puts an exiled pile into the {zone.name}", node=node
        )
    # A battlefield is nobody's zone (CR 400.1), so a printed possessive on it
    # would be naming a seat this sentence has already named with its subject.
    # A **hand** is somebody's (CR 402.1), and the possessive it prints has to
    # agree with the subject for the reason the pronoun in front of "exiled
    # this way" does: "each player … returns to **their** hand" is one claim
    # said twice, and a hand named for anybody else would be every player
    # handing one seat the table's cards.
    if zone.name == "battlefield":
        if zone.owner is not None:
            raise LoweringError(
                "the battlefield is nobody's zone", node=node
            )
    elif zone.owner is None or zone.owner.kind not in ("you", "owner"):
        # A **hand** is somebody's zone (CR 402.1) where a battlefield is
        # nobody's, so this destination prints a possessive and the possessive
        # has to be the pile's own owner's. Agreement with the subject is
        # already the *parse*'s answer — ``_matching_possessive`` admits
        # "their" only for a named seat and "your" only for the unnamed one,
        # and either normalises to ``you`` meaning "the sentence's own actor" —
        # so what is left here is refusing a third party's zone, which would be
        # every player handing one seat the table's cards.
        raise LoweringError(
            "the exiled-pile return names the pile's own owner's zone",
            node=node,
        )
    if EXILED_BY_SEAT not in produced:
        raise LoweringError(
            "'cards they exiled this way' names an exile this effect did not "
            "perform",
            node=node,
        )
    actor = node.actor.kind if node.actor is not None else "you"
    if actor not in ("each_player", "you"):
        raise LoweringError(
            f"no handler gives a per-seat exile pile back to {actor!r}",
            node=node,
        )
    # Through the same *card* gate every printed card phrase runs through: the
    # pile is a list of cards in a zone with no computed characteristics
    # (CR 613.1), so a narrowing the card matcher cannot answer would be
    # dropped where it is tested and give back a wider pile than the card
    # names.
    described = chargeable_card_filter(node.filter)
    if described is None:
        raise LoweringError(
            "the exiled-pile return cannot read this card phrase", node=node
        )
    payload: dict[str, object] = {"zone": zone.name, "who": actor}
    if described:
        payload["filter"] = described
    return (OracleInstruction("put_exiled_this_way", "", payload),)


def _lower_each_player_claims_exiled_card(
    node: "ast.EachPlayerClaimsExiledCard", produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """"Exile all nontoken permanents. **Starting with you, each player chooses
    one of the exiled cards and puts it onto the battlefield tapped under their
    control.**" (Thieves' Auction.)

    Moved here from ``lowering/exile.py`` at Nemesis's second wave, when that
    module reached the guard a third time — and the move is a correction rather
    than a cut. ``exile``'s docstring says everything left in it "chooses its
    object out of the game … nothing below reads a record", and this read one:
    it starts from a pile an earlier step already put in exile and asks who
    takes which card out of it, which is the opening sentence of this module.
    It is :func:`_lower_put_exiled_this_way`'s neighbour by subject — Living
    Death hands each seat back its own pile, this hands the table one pile in
    turns.

    One instruction, and the repeat clause behind the sentence is a key on it
    rather than a wrapper around it — ``_lower_repeat_process``'s argument one
    card over: the loop ends when the pile empties, which is something only the
    thing handing out the cards can see, and a round that emptied it part-way
    has to stop mid-round rather than after it.

    Refused without a producer, as every back-reference in this grammar is: "the
    exiled cards" names what a step of *this same effect* exiled, and with no
    such step the words name nothing — a spell that reports supported and hands
    out nothing at all.

    ``until_pile_empty`` is carried even when it is False, because the two
    readings are genuinely different cards: without the clause each seat takes
    exactly one card and the rest stay exiled.
    """
    if EXILED_THIS_WAY_OBJECTS not in produced:
        raise LoweringError(
            "'one of the exiled cards' names what an earlier step of this "
            "effect exiled, and no step of it exiles anything", node=node,
        )
    if node.chooser.kind != "each_player":
        raise LoweringError(
            "a pick out of the exiled pile is made by every seat in turn",
            node=node,
        )
    return (
        OracleInstruction(
            "claim_exiled_cards_in_turn", "",
            {
                # "Starting with you" — CR 101.4 orders a multi-seat decision
                # from the active player and this names the seat that put the
                # effect on the stack. The same seat for a sorcery, not the
                # same rule, which is why the word is carried.
                "claim_order": (
                    node.starting_with.kind if node.starting_with else None
                ),
                "tapped": node.tapped,
                "until_pile_empty": node.until_pile_empty,
            },
        ),
    )


def _fused_exile_event_subject_until_source_leaves(
    steps: tuple, event: str | None = None
) -> tuple[OracleInstruction, ...] | None:
    """"Whenever a creature enters, …, **exile that creature. Return that card
    to the battlefield under its owner's control when this artifact leaves the
    battlefield.**" (Portcullis.)

    Two printed sentences and one CR 610.3 *linked* pair: the second refers to
    exactly the object the first moved and to nothing else. Fused because the
    decomposition has nowhere to go — a delayed ability would have to bind a
    card the exile step has no channel to hand it, and this engine already owns
    the pairing under one record (``engine/linked_exile.py``, whose entries the
    single leaves-the-battlefield transition gives back). Two mechanisms for one
    relation is how a return comes to fire twice, or not at all.

    Here rather than in ``lowering/exile.py`` because that is what this module
    is: the exile family moves an object *into* the zone and refuses what no
    handler implements, and every production here is about a card that is
    linked to a source. It is also the family boundary in the other direction —
    ``exile`` may not import ``hand``, ``linked_exile`` or any other family, so
    a production needing this file's subject belongs in this file.

    Returning None rather than raising leaves a near-miss to the ordinary step
    lowering, which refuses it by name.
    """
    if len(steps) != 2 or event not in _EVENT_SUBJECT_OBJECTS:
        return None
    exiled, delayed = steps
    if not isinstance(exiled, ast.Exile) or not isinstance(
        delayed, ast.CreateDelayedTrigger
    ):
        return None
    if exiled.counters or exiled.face_down or exiled.same_zone:
        return None
    if exiled.duration.kind is not None or exiled.actor is not None:
        return None
    subject = exiled.subject
    if not (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "that"
        and not subject.targeted
        and subject.count == 1
        and subject.filter.card_types
    ):
        return None
    # The delay watches the ability's **own source** and fires once, which is
    # what ``ends_on=LEAVES`` means on the record. A delay watching anything
    # else, or one carrying a stated duration, is a different sentence and
    # refuses rather than being read as this one.
    if (
        delayed.event != "bound_permanent_leaves_battlefield"
        or delayed.watches != "source"
        or not delayed.once
        or delayed.duration != "until_it_triggers"
    ):
        return None
    ret = delayed.effect
    if not isinstance(ret, ast.ReturnToZone):
        return None
    if ret.to is None or ret.to.name != "battlefield" or ret.to.owner is not None:
        return None
    # "…under **its owner's** control", which is the seat the record already
    # returns a linked card under. Any other seat is a phrase this rule has not
    # read, and taking it as the owner would hand the creature to the wrong
    # player.
    if ret.under_control_of is None or ret.under_control_of.kind != "owner":
        return None
    if ret.entering_tapped or ret.entering_counters or ret.repetitions:
        return None
    returned = ret.subject
    if not (
        isinstance(returned, ast.TargetSpec)
        and returned.quantifier == "that"
        and not returned.targeted
        and returned.filter.is_card
    ):
        return None
    return (
        OracleInstruction(
            "exile_event_subject", "", {"until_source_leaves": True},
        ),
    )
