"""Cards chosen out of a hand, and where they go — other than a discard.

The handler twin of ``engine/grammar/lowering/hand.py``: a pick out of a hidden
zone (CR 400.2), made by the hand's owner as the effect resolves, then moved —
onto the battlefield (Eureka, Ugin's −10, Stronghold Gambit), into exile (Ice
Cauldron, Mind Swords, Elkin Lair's card at random) or onto the library
(Brainstorm, Sylvan Library's "put the card on top") — or only shown
(Metalworker, Stronghold Gambit's reveal of the picks). The candidate readers
(:func:`put_from_hand_candidates`, :func:`exile_from_hand_candidates`,
:func:`chosen_hand_card_candidates`) are public because the prompt renderer and
the resolver in ``engine/mixins/stack/choices.py`` both ask them, so what a seat
is offered and what it may answer cannot disagree.

Split out of ``zones.py`` at the 2,000-line cap's split round. Discarding is
``discards.py``'s, and a whole hand revealed — or one card of it at random — is
``reveal.py``'s.
"""

from __future__ import annotations

import dataclasses
import random
from typing import TYPE_CHECKING

from ..models import Permanent
from ..oracle_types import (HAND_CARDS_TO_LIBRARY, REVEALED_HAND_CARDS,
                            REVEALED_THIS_WAY)
from ..search_filters import card_has_type
from ._amounts import resolve_amount
from ._chosen import _resolve_chosen_subtype
from ._filters import _card_matches_filter
from ._targets import frozen_that_player_seat
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


# CR 110.4: the card types that are permanents — what "permanent card" means
# when Ugin's −10 reads your hand.
_PERMANENT_TYPES = ("artifact", "creature", "enchantment", "land", "planeswalker")


@effect_handler("put_cards_from_hand_onto_battlefield")
def put_cards_from_hand_onto_battlefield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put up to seven permanent cards from your hand onto the battlefield."
    (Ugin, the Spirit Dragon's −10.) Non-interactive seats take every eligible
    card up to the cap, in hand order — "up to" makes any subset legal, and
    more battlefield is the default the AI already plays toward.

    "…put **all** land cards from it onto the battlefield." (Manabond.) The
    sweep spelling, and nothing is chosen at all: every card the phrase names
    goes. ``all`` rather than a very large count, because a count is a number
    the lowering would have to know before the hand is in view — and a ceiling
    read as a sweep, or a sweep read as a ceiling, is the same card playing two
    different ways.
    """
    caster = context.caster
    count = int(instruction.payload.get("count", 0))
    wanted_types = tuple(instruction.payload.get("card_types") or ())
    permanents_only = bool(instruction.payload.get("permanents_only"))

    def eligible(card) -> bool:
        if wanted_types:
            return card.primary_type in wanted_types
        if permanents_only:
            return card.primary_type in _PERMANENT_TYPES
        return True

    eligible_cards = [card for card in caster.hand if eligible(card)]
    chosen = (
        eligible_cards if instruction.payload.get("all")
        else eligible_cards[:count]
    )
    caster_index = game.players.index(caster)
    for card in chosen:
        game.take_card_from_hand(caster, card)
        game._put_permanent_onto_battlefield(caster_index, Permanent(card=card), None)
        game.log.append(f"{caster.name} put {card.name} onto the battlefield")
    if not chosen:
        game.log.append(f"{caster.name} put no cards onto the battlefield")
    return True, "resolved"


def exile_from_hand_candidates(game, payload: dict, player) -> list[int]:
    """The hand slots "you may exile a <filter> card from your hand" may be
    answered with (Ice Cauldron).

    Public for ``put_from_hand_candidates``' reason exactly: the renderer shows
    the seat what it may pick and the resolver checks what came back, and a list
    built twice is a list that can be offered wider than it is checked.
    """
    described = payload.get("card_filter") or {}
    return [
        index
        for index, card in enumerate(player.hand)
        if _card_matches_filter(card, described, game=game, owner=player)
    ]


@effect_handler("exile_chosen_card_from_hand")
def exile_chosen_card_from_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"You may exile a nonland card from your hand." (Ice Cauldron.)

    The card is chosen on resolution out of a hidden zone, so the pick *is* the
    effect and it goes through the pending-choice queue. The offer suspends the
    resolution: the sentence behind it — "you may cast that card for as long as
    it remains exiled" — reads what this exiled, and a step that ran before the
    answer would grant permission over an empty list.

    Nothing eligible is an offer never made rather than an offer declined, the
    same rule ``put_chosen_card_from_hand_onto_battlefield`` states beside it.
    """
    caster = context.caster
    seat = game.players.index(caster)
    payload = dict(instruction.payload)
    if payload.get("face_down") and context.source_permanent is None:
        # CR 406.3's rider needs a permanent to be recorded on, exactly as the
        # library-top exile beside it does: with nothing to link the entry to,
        # the card cannot be hidden, and exiling it face *up* is a different
        # effect. So the exile does not happen at all rather than happening in
        # full view.
        game.log.append("the face-down exile has no permanent to be linked to")
        return True, "resolved"
    if not exile_from_hand_candidates(game, payload, caster):
        game.log.append(
            f"{context.card.name}: {caster.name} has no card to exile"
        )
        return True, "resolved"
    game.arm_pending_choice(
        "exile_from_hand_choice", seat,
        card_name=context.card.name,
        _payload=payload,
        _context=context,
        _source_permanent=context.source_permanent,
    )
    return True, "resolved"


@effect_handler("exile_cards_from_hand")
def exile_cards_from_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each player exiles two cards from their hand." (Mind Swords.)

    Each seat chooses out of its own hidden hand (CR 400.2), in turn order from
    the active player (CR 101.4), so this arms the pick
    ``exile_chosen_card_from_hand`` already arms — the **mandatory** printing of
    it, which has no Decline — once per card owed. One card at a time rather
    than a new multi-card prompt: the chooser sees the whole hand at each pick,
    so nothing is decided with less information than one simultaneous pick of
    two would give, and the prompt, its renderer and its non-interactive
    default (the lowest-index eligible card) are the ones that already exist.

    CR 608.2's "as much as possible": a seat holding fewer eligible cards than
    the printed number exiles every one it has, and a seat with none is
    logged and skipped. The cards leave through the hand seam in the prompt's
    resolver, never by an identity filter over the hand.

    "**Target opponent** exiles a card from their hand." (Parallax Nexus.) The
    announced seat alone (``actor: target``), read off the resolution's chosen
    player — the same prompt, armed once. A target that is no player at all by
    now is CR 608.2b's "does nothing" rather than a fall back to every seat.

    **Linked when the source is a permanent** (CR 607.2a), exactly as
    ``exile_target_permanent`` records its exile and for its reason: the entry
    carries no ``ends_on``, so it is inert for every card that never asks, and
    it is the whole of Parallax Nexus's leave trigger — "each player returns to
    their hand all cards they own exiled with it" drains an empty pile without
    it, and the cards a Nexus took would stay in exile for ever. A spell (Mind
    Swords) has no permanent to link to, and its exile stays unlinked.
    """
    payload = instruction.payload
    amount = int(payload.get("amount", 1) or 0)
    caster_index = game.players.index(context.caster)
    if payload.get("actor") == "target":
        chosen = context.target
        if not any(chosen is seated for seated in game.players):
            game.log.append(
                f"{getattr(context.card, 'name', '')}: no player to exile a card"
            )
            return True, "resolved"
        candidates = {
            next(i for i, seated in enumerate(game.players) if seated is chosen)
        }
    elif payload.get("actor") == "each_opponent":
        candidates = set(game.opponents_of(caster_index))
    else:
        candidates = set(range(len(game.players)))
    count = len(game.players)
    active = game.active_player_index or 0
    seats = sorted(
        (seat for seat in candidates if not game.players[seat].lost),
        key=lambda seat: ((seat - active) % count, seat),
    )
    pick = {
        "optional": False,
        "card_filter": dict(payload.get("card_filter") or {}),
    }
    card_name = getattr(context.card, "name", "")
    for seat in seats:
        player = game.players[seat]
        owed = min(amount, len(exile_from_hand_candidates(game, pick, player)))
        if owed <= 0:
            game.log.append(f"{card_name}: {player.name} has no card to exile")
            continue
        game.log.append(
            f"{card_name}: {player.name} exiles {owed} card(s) from their hand"
        )
        for _ in range(owed):
            game.arm_pending_choice(
                "exile_from_hand_choice", seat,
                card_name=card_name,
                _payload=pick,
                _context=context,
                _source_permanent=context.source_permanent,
            )
    return True, "resolved"


def put_from_hand_candidates(game, payload: dict, player) -> list[int]:
    """The hand slots a "put a … card from your hand onto the battlefield" offer
    may be answered with.

    Public because two callers need it and one rule has to answer both: the
    prompt renderer, which shows the seat what it may pick, and the resolver,
    which checks what came back. A list built twice is a list that can be
    offered wider than it is checked.
    """
    described = payload.get("card_filter") or {}
    permanents_only = bool(payload.get("permanents_only"))
    # "…put an Aura card from your hand onto the battlefield **attached to this
    # creature**." (Academy Researchers.) CR 303.4a: an Aura may be put onto the
    # battlefield only attached to an object its own enchant ability can
    # enchant, so a card the host cannot legally carry is not among the answers
    # — offering it would put an Aura into play attached to nothing, which
    # CR 704.5m bins on the next sweep with the card already out of the hand.
    #
    # The host arrives as an **id** stamped on the payload when the offer was
    # armed, because this function is called again to check the answer and by
    # then the permanent may have moved (CR 400.7 — an index is not an
    # identity). A host that has gone leaves nothing legal to pick, which is the
    # direction that offers nothing rather than the whole hand.
    from ..auras import enchant_card_refusal

    host_id = payload.get("attach_to_permanent_id")
    host = game.permanent_by_id(host_id) if isinstance(host_id, int) else None
    seat = game.players.index(player) if player in game.players else None
    if host_id is not None and (host is None or seat is None):
        return []
    return [
        index
        for index, card in enumerate(player.hand)
        if _card_matches_filter(card, described, game=game, owner=player)
        and (not permanents_only or card.primary_type in _PERMANENT_TYPES)
        and (
            host is None
            or enchant_card_refusal(game, card, seat, host) is None
        )
    ]


@effect_handler("put_chosen_card_from_hand_onto_battlefield")
def put_chosen_card_from_hand_onto_battlefield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…put **a** permanent card from their hand onto the battlefield."
    (Eureka.)

    One card, and the seat picks which — so the pick *is* the effect, and it is
    a prompt rather than a slice off the front of the hand like the "up to N"
    sweep above. ``optional`` (the sentence said "may") adds declining to the
    answers; without it the seat must pick, and only an empty candidate list
    ends it.

    "their hand" is the hand of the seat the offer was made to, which is
    ``context.target`` once a multi-seat offer has rebound it; "your hand" is
    the caster's. The payload says which, because the two are different
    sentences.
    """
    payload = instruction.payload
    player = context.target if payload.get("whose") == "offered" else context.caster
    seat = game.players.index(player)
    if payload.get("attach_to") == "source":
        # "…attached to **this creature**." (Academy Researchers.) The host is
        # the ability's own source, frozen onto the payload by **id** here —
        # the one moment it is in hand — so the candidate rule, the prompt and
        # the answer check all resolve the same permanent however long the seat
        # takes to answer. A source that has already left names no host, and
        # CR 303.4a leaves nothing that could legally be put onto the
        # battlefield.
        source = context.source_permanent
        if source is None or not game.is_on_battlefield(source):
            game.log.append(
                f"{context.card.name}: it is no longer on the battlefield"
            )
            return True, "resolved"
        payload = {**payload, "attach_to_permanent_id": source.permanent_id}
        instruction = dataclasses.replace(instruction, payload=payload)
    # "…a creature card **of the chosen type**" (Belbe's Portal). The word is
    # the CR 614.1c record on the ability's source, resolved here into an
    # ordinary ``subtype_filter`` and frozen onto the payload for the
    # ``attach_to`` reason above: the candidate rule, the prompt and the answer
    # check all re-run off this payload, and none of them holds the source. The
    # source is read even if it has left the battlefield — the chosen type is
    # its last known information (CR 608.2h). No record leaves the key in place,
    # and ``_card_matches_filter`` then refuses every card: nothing is offered
    # rather than the whole hand.
    from ..subject_filters import SOURCE_RESOLVED_CARD_KEYS

    described = payload.get("card_filter") or {}
    if any(described.get(key) for key in SOURCE_RESOLVED_CARD_KEYS):
        payload = {
            **payload,
            "card_filter": _resolve_chosen_subtype(
                dict(described), context.source_permanent
            ),
        }
    if not put_from_hand_candidates(game, payload, player):
        # Nothing to pick. Not an offer declined — an offer never made, which is
        # the same rule ``handlers/control_flow._offer_to_seat`` states for an
        # action cost nobody can pay.
        game.log.append(
            f"{player.name} has no card {context.card.name} could put onto the battlefield"
        )
        return True, "resolved"
    game.arm_put_from_hand_choice(seat, payload, context)
    return True, "resolved"


def chosen_hand_card_candidates(game, payload: dict, player) -> list[int]:
    """The hand slots "choose N cards in your hand …" may be answered with.

    Public and singular for ``put_from_hand_candidates``' reason: the prompt
    renderer shows the seat what it may pick and the resolver checks what came
    back, and a list built twice is a list that can be offered wider than it is
    checked.

    Two narrowings, and they are asked of different things. The printed noun
    phrase is a question about the *card* and goes through the shared card
    matcher. "Drawn this turn" is not a question about the card at all —
    nothing on its face answers it and ``_card_matches_filter`` has no player to
    ask — so it is answered here, against the record every draw path already
    feeds (``PlayerState.cards_drawn_this_turn``). By identity, never by name: a
    second copy of a card drawn this turn is a different object and was not
    drawn.
    """
    described = payload.get("card_filter") or {}
    drawn_this_turn = bool(payload.get("drawn_this_turn"))
    provenance = player.cards_drawn_this_turn if drawn_this_turn else ()
    # "…chooses one card **of each color** from it" (Noxious Vapors). The pick
    # is an assignment to printed slots, so a card is a candidate only if some
    # slot describes it — a land or an artifact is no colour and is never
    # offered. *Which* sets of candidates are answers is the matching's
    # question (``Game.match_hand_slots``), not this list's.
    slot_filters = hand_slot_filters(payload)
    return [
        index
        for index, card in enumerate(player.hand)
        if _card_matches_filter(card, described, game=game, owner=player)
        and (
            not drawn_this_turn
            or any(card is drawn for drawn in provenance)
        )
        and (
            slot_filters is None
            or any(
                _card_matches_filter(card, slot, game=game, owner=player)
                for slot in slot_filters
            )
        )
    ]


def hand_slot_filters(payload: dict) -> "list[dict] | None":
    """The printed keeps of a slotted hand pick, one filter per keep — or
    ``None`` for the ordinary counted pick, which has none.

    ``keep_chosen_sacrifice_rest``'s shape (``[{"count": n, "filter": {…}}]``)
    read the way ``Game._keep_slot_filters`` reads it, so one printed keep is
    one slot whichever zone the sentence is about.
    """
    slots = payload.get("slots")
    if not slots:
        return None
    expanded: list[dict] = []
    for slot in slots:
        expanded.extend(
            [dict(slot.get("filter") or {})] * max(0, int(slot.get("count", 0)))
        )
    return expanded


@effect_handler("choose_cards_in_hand")
def choose_cards_in_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose two cards in your hand drawn this turn." (Sylvan Library.)

    Nothing moves: the pick is recorded under the key the lowering named, and
    the sentence after it ("for each of those cards, …") is what acts on them.
    The cards themselves are recorded rather than hand indices — a hand index
    stops naming the same card the moment anything leaves the hand, which the
    very next step does.

    CR 608.2's "as much as possible": a hand holding fewer eligible cards than
    the printed number chooses all of them rather than none.

    "**Each player** chooses a card in their hand." (Stronghold Gambit.) One
    prompt per living seat in APNAP order (CR 101.4), each out of that seat's
    own hand, all armed at once — CR 101.4a keeps the cards face down as they
    are chosen, so no seat's pick waits on another's — and recorded per seat
    (``{seat: [cards]}``) because every answer is its own. The resolution waits
    for the last of them (the kind suspends).
    """
    payload = instruction.payload
    if payload.get("actor") == "each_player":
        from .control_flow import _offered_seats

        result_key = str(payload.get("result_key") or "chosen_hand_cards")
        by_seat: dict[int, list] = {}
        context.results[result_key] = by_seat
        for seat in _offered_seats(game, "each_player", context):
            player = game.players[seat]
            by_seat[seat] = []
            if not chosen_hand_card_candidates(game, payload, player):
                game.log.append(
                    f"{context.card.name}: {player.name} has no card to choose"
                )
                continue
            game.arm_choose_cards_in_hand(seat, payload, context)
        return True, "resolved"
    player = context.caster
    seat = game.players.index(player)
    candidates = chosen_hand_card_candidates(game, payload, player)
    result_key = str(payload.get("result_key") or "chosen_hand_cards")
    if not candidates:
        context.results[result_key] = []
        game.log.append(
            f"{context.card.name}: {player.name} has no card to choose"
        )
        return True, "resolved"
    game.arm_choose_cards_in_hand(seat, payload, context)
    return True, "resolved"


def _chosen_cards_still_in_hand(game, record: dict) -> list[tuple[int, object]]:
    """``(seat, card)`` for every card a per-seat hand pick recorded that is
    still in that seat's hand, in APNAP order.

    By identity against the seat's *own* hand: every copy of a card in a hand is
    one shared object, and two players' decks built from one catalog share the
    object across hands too, so "is it still there" is only answerable per
    seat. A card that left between the pick and now is not revealed and does
    not compete (CR 608.2: do as much as possible).
    """
    out: list[tuple[int, object]] = []
    for seat in sorted(record, key=lambda s: (
        (s - (game.active_player_index or 0)) % max(len(game.players), 1), s
    )):
        if not (isinstance(seat, int) and 0 <= seat < len(game.players)):
            continue
        hand = game.players[seat].hand
        for card in record.get(seat) or ():
            if any(card is held for held in hand):
                out.append((seat, card))
    return out


@effect_handler("reveal_chosen_hand_cards")
def reveal_chosen_hand_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Then each player reveals their chosen card." (Stronghold Gambit.)

    Every hidden pick made public at once (CR 701.20a), through the one reveal
    feed the web layer reads — one event per seat, because each player reveals
    their own. Nothing moves; the sentence after this one reads the same record.
    """
    record = context.results.get(str(instruction.payload.get("cards_from"))) or {}
    shown: dict[int, list[str]] = {}
    for seat, card in _chosen_cards_still_in_hand(game, record):
        shown.setdefault(seat, []).append(card.name)
    for seat, names in shown.items():
        game.record_reveal(seat, names)
        game.log.append(
            f"{game.players[seat].name} reveals {', '.join(names)} "
            f"({context.card.name})"
        )
    if not shown:
        game.log.append(f"{context.card.name}: no player revealed a card")
    return True, "resolved"


#: CR 110.4a: "an artifact, battle, creature, enchantment, land, or
#: planeswalker card" — a card that could be put onto the battlefield.
_PERMANENT_CARD_TYPES = (
    "artifact", "battle", "creature", "enchantment", "land", "planeswalker",
)


@effect_handler("put_chosen_hand_cards_onto_battlefield")
def put_chosen_hand_cards_onto_battlefield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"The owner of each creature card revealed this way with the lowest mana
    value puts it onto the battlefield." (Stronghold Gambit.)

    Only the recorded cards compete, and only those the printed phrase admits
    (``_card_matches_filter``, the card-in-a-zone matcher) — a revealed land is
    not in the comparison at all, so it cannot be "the lowest". The superlative
    is then asked of the survivors and **every** card tied at the extreme
    enters, because "each … with the lowest mana value" names all of them.
    Mana value is the printed one (CR 202.3), which is all a card in a hand has.

    Each enters under its **owner**, who is the player the sentence makes put
    it there (CR 110.2a), out of that owner's hand through the hand seam.
    """
    payload = instruction.payload
    record = context.results.get(str(payload.get("cards_from"))) or {}
    if isinstance(record, (list, tuple)):
        # "Reveal a card in your hand, then put that card onto the
        # battlefield …" (Retraced Image.) A one-hand record
        # (``reveal_cards_from_hand``'s), which is the revealing seat's — the
        # resolving player's.
        record = {game.players.index(context.caster): list(record)}
    described = payload.get("card_filter") or {}
    entrants = [
        (seat, card)
        for seat, card in _chosen_cards_still_in_hand(game, record)
        if _card_matches_filter(
            card, described, game=game, owner=game.players[seat]
        )
    ]
    superlative = payload.get("superlative") or {}
    if entrants and superlative:
        if superlative.get("characteristic") != "mana_value":
            # The lowering admits nothing else; a hand-built payload naming a
            # characteristic no card in a hand has puts nothing in rather than
            # guessing which card was meant.
            game.log.append(f"{context.card.name}: nothing to compare")
            return True, "resolved"
        pick = min if superlative.get("extreme") == "least" else max
        best = pick(int(getattr(card, "cmc", 0) or 0) for _, card in entrants)
        entrants = [
            (seat, card) for seat, card in entrants
            if int(getattr(card, "cmc", 0) or 0) == best
        ]
    if not entrants:
        game.log.append(f"{context.card.name}: no revealed card enters")
        return True, "resolved"
    for seat, card in entrants:
        owner = game.players[seat]
        if not any(card_has_type(card, kind) for kind in _PERMANENT_CARD_TYPES):
            # CR 400.4a: "If an instant or sorcery card would enter the
            # battlefield, it remains in its previous zone." A revealed instant
            # whose name a permanent shares (a token or a copy can carry one)
            # stays in its owner's hand.
            game.log.append(
                f"{card.name} can't enter the battlefield and stays in "
                f"{owner.name}'s hand (400.4a)"
            )
            continue
        if not game.take_card_from_hand(owner, card):
            continue
        game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
        game.log.append(
            f"{owner.name} puts {card.name} onto the battlefield ({context.card.name})"
        )
    return True, "resolved"


@effect_handler("reveal_cards_from_hand")
def reveal_cards_from_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Reveal any number of artifact cards in your hand." (Metalworker, the
    five Urza's Destiny Seers, their five Scents and Rofellos's Gift.)

    Nothing moves and nothing is spent: the seat picks a subset of its own
    hand, those cards become public (CR 701.20a), and the sentence after this
    one reads the count off the record. The pick goes through the same queued
    choice Sylvan Library's does — one prompt for "which cards in your hand",
    with the printed offer ("any number of" against a count) and the printed
    verb as payload — because what differs between the two sentences is data
    and not a mechanism.

    ``chosen_hand_card_candidates`` is the one rule that says which cards the
    printed noun phrase admits, so the list offered and the list an answer is
    checked against cannot be two lists.

    An empty candidate set answers itself: nought is a legal answer to "any
    number", so there is nothing to ask and both records are written where the
    effect stands. Written rather than left absent, because an absent key is a
    back-reference with no producer — which is a refusal, not a zero.
    """
    payload = instruction.payload
    player = context.caster
    seat = game.players.index(player)
    candidates = chosen_hand_card_candidates(game, payload, player)
    if not candidates:
        context.results[str(payload.get("result_key") or REVEALED_HAND_CARDS)] = []
        context.results[str(payload.get("count_key") or REVEALED_THIS_WAY)] = 0
        game.log.append(
            f"{context.card.name}: {player.name} reveals no cards"
        )
        return True, "resolved"
    game.arm_choose_cards_in_hand(seat, payload, context)
    return True, "resolved"


@effect_handler("put_iterated_card_on_library")
def put_iterated_card_on_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put the card on top of your library." (Sylvan Library.)

    "The card" is the object the enclosing repetition is on, so this reads
    ``context.iteration_target`` and refuses to guess without one: a sentence
    naming a loop's object outside a loop names nothing, and picking some card
    out of the hand instead would be a card doing something it never says.

    Through ``Game.put_card_into_library`` rather than by moving the card
    itself, because CR 903.9b's return to the command zone has no single fire
    site and this is one more of them.
    """
    card = context.iteration_target
    if card is None:
        game.log.append(
            f"{context.card.name}: no card for this step to move"
        )
        return True, "resolved"
    player = context.caster
    if not any(c is card for c in player.hand):
        # It left the hand between the choice and this step. CR 608.2: do as
        # much as possible, which here is nothing.
        game.log.append(
            f"{context.card.name}: {getattr(card, 'name', 'that card')} is no "
            f"longer in {player.name}'s hand"
        )
        return True, "resolved"
    game.take_card_from_hand(player, card)
    position = "bottom" if str(instruction.payload.get("position", "top")) == "bottom" else "top"
    game.put_card_into_library(player, card, position)
    game.log.append(
        f"{context.card.name}: {player.name} put {card.name} on "
        f"{'the bottom' if position == 'bottom' else 'top'} of their library"
    )
    return True, "resolved"


@effect_handler("exile_random_card_from_hand")
def exile_random_card_from_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"At the beginning of each player's upkeep, **that player exiles a card at
    random from their hand**." (Elkin Lair.)

    One card nobody chose, out of a hand nobody looked at — CR 701.13a's exile
    over a random pick, which is why the seat is not asked anything and no
    prompt is armed. Recorded under the one ``exiled_cards`` key every other
    exile writes, so the two sentences behind it ("the player may play that
    card", "if the player hasn't played the card…") read the referent this
    engine already has rather than a second one.

    **Whose hand is payload**, under the same ``recipient`` key the mill, the
    discard and Thought Lash's library exile use, and the seat is the one the
    firing event froze (``frozen_that_player_seat``). A seat that cannot be
    resolved exiles
    *nothing* rather than falling back to the ability's controller: on this card
    the controller's own hand is the wrong hand three times in four, and taking
    a card out of it at random is not a smaller effect, it is a different one.

    The card is popped **by index**, not by value: a hand is the one zone where
    two copies of a card are the same object (a deck repeats one immutable
    ``CardDefinition``), so ``list.remove`` would take whichever came first.
    ``random.randrange`` rather than a private RNG, for the reason every other
    random pick among the handlers uses it — ``run_ai_simulation`` seeds the module
    RNG and a seed has to replay a run exactly.
    """
    recipient = str(instruction.payload.get("recipient") or "caster")
    if recipient == "event_subject_player":
        seat = frozen_that_player_seat(game, context)
        if seat is None:
            game.log.append(
                f"{context.card.name}: no player was named to exile a card"
            )
            return True, "resolved"
        victim = game.players[seat]
    else:
        victim = context.caster
    if not victim.hand:
        game.log.append(f"{victim.name} has no cards in hand to exile")
        context.results["exiled_cards"] = []
        return True, "resolved"
    index = random.randrange(len(victim.hand))
    card = victim.hand[index]
    victim.hand.pop(index)
    victim.exile.append(card)
    context.results["exiled_cards"] = [card]
    game.log.append(
        f"{victim.name} exiled {card.name} at random from their hand"
    )
    return True, "resolved"


@effect_handler("put_hand_cards_on_library")
def put_hand_cards_on_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Brainstorm: "…then put two cards from your hand on top of your library
    in any order." Stunted Growth: "Target player chooses three cards from
    their hand and puts them on top of their library in any order."

    The seat that owns the hand chooses which cards and in what order, so this
    arms a prompt rather than moving anything: a hand is a hidden zone and
    nothing but its owner can read it.

    **Not a discard.** CR 701.9a makes discarding a specific action that
    abilities watch — Necropotence exiles what you discard, Library of Leng
    redirects it — and none of that is happening here. Reusing the discard
    prompt with its ``to_library`` flag would have fired every one of those on a
    Brainstorm.

    Fewer cards in hand than the card names is not a failure: CR 608.2 does as
    much as it can.
    """
    recipient = instruction.payload.get("recipient")
    if recipient == "caster":
        player = context.caster
    elif recipient == "event_subject_player":
        # "At the beginning of each player's draw step, **that player** puts the
        # cards in their hand on the bottom of their library." (Teferi's Puzzle
        # Box.) The seat the fire site froze (CR 603.10), not the source's
        # controller and not `context.target` — a trigger that chose nothing
        # leaves whatever the resolution was already carrying there, which is
        # the wrong hand on every draw step but one. Through the one reader
        # every "that player" in this package goes through, so the phrase has
        # one answer.
        seat = frozen_that_player_seat(game, context)
        player = None if seat is None else game.players[seat]
    else:
        player = context.target
    if player is None or player not in game.players:
        game.log.append(f"{context.card.name}: no player to put cards back")
        return True, "resolved"
    if instruction.payload.get("whole_hand"):
        # "**the cards from** their hand" (Jester's Mask) — every one of them,
        # counted now rather than printed on the card. There is still an order
        # to choose (CR 401.4), which is what the prompt is for.
        actual = len(player.hand)
    else:
        amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
        actual = min(amount, len(player.hand))
    # How many actually went, recorded for the step that reads it back:
    # "Search that player's library for **that many** cards." Written before the
    # prompt is armed and whatever the answer is, because the number is settled
    # here — the prompt only decides the order.
    context.results[HAND_CARDS_TO_LIBRARY] = actual
    if actual <= 0:
        game.log.append(f"{player.name} has no cards to put back")
        return True, "resolved"
    game.arm_pending_choice(
        "hand_to_library", game.players.index(player), count=actual,
        # "…both on top of your library **or both on the bottom**" (Dream
        # Cache), "…on **the bottom** of their library in any order" (Teferi's
        # Puzzle Box). Carried onto the prompt so what the player is offered and
        # what an answer is checked against are one rule: without the key the
        # resolver refuses a bottoming answer outright, and with the wrong one
        # it would let a Puzzle Box be answered onto the top.
        **({"destination": instruction.payload["destination"]}
           if instruction.payload.get("destination") else {}),
    )
    game.log.append(
        f"{player.name} must choose {actual} card(s) to put back on their library"
    )
    return True, "pending_hand_to_library"
