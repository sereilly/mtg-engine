"""The offers that are really a prompt: an optional action whose own ceiling
already permits zero.

Split out of ``lowering/control_flow`` at the thousand-line guard, along a line
all five of these functions had already written into their own docstrings.
"Each player may discard **up to** three cards" (Mind Bomb) is one decision and
not two: "up to three" already lets a seat discard none, so the "may" in front
of it adds no answer the discard prompt does not already have. Collapsing the
pair is what makes the *next* sentence work — a prompt suspends the resolution
until every seat has answered (CR 608.2) where an offer does not, and "damage
equal to 3 minus the number of cards they discarded this way" has to run after
the answers rather than before them.

Each is a recogniser and nothing else: it reads one ``ast.May``, returns the
collapsed instruction when the whole sentence is that one narrow shape, and
returns None otherwise — leaving the ordinary offer in place, which is what
refuses by name when a card prints a cost, an if-you-do or an otherwise beside
the ceiling. Nothing here lowers a branch, so ``lower_statement`` never arrives.
That inversion is ``control_flow``'s, and its absence is the clearest evidence
these are a floor under the family rather than a second half of it.

A floor for ``_bound_returns``' reason exactly: ``control_flow`` is its only
reader and a family may not import a sibling. What stays there is the offer
itself — who is asked, what it costs, and which of its branches runs.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import (COUNTERED_SPELL_CONTROLLER, REVEALED_BY_SEAT,
                             REVEALED_HAND_CARDS_BY_SEAT, OracleInstruction)
from ...subject_filters import card_only_filter, untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ..vocabulary import PERMANENT_CARD_TYPES
from ._common import _filter_payload, _restrictions_beyond
from ._filters import _PAYLOAD_HONOURED_FILTER_FIELDS


#: The actors that name a *set* of seats, spelled here as the lowering sees them.
#: The handler has its own copy of this reading (``handlers/control_flow``'s
#: ``_EACH_ACTORS``) because it is answering a different question — which seats
#: to arm — and the two are checked against each other by the pool rather than
#: by a shared constant this module would have to import upwards.
_EACH_SEAT_ACTORS = frozenset({"each_player", "each_opponent"})


def _each_player_optional_discard(
    node: ast.May,
) -> tuple[OracleInstruction, ...] | None:
    """"Each player may discard **up to** three cards." (Mind Bomb.)

    One prompt per seat rather than an offer per seat, because the offer and the
    ceiling are the same decision: "up to three" already lets a player discard
    none, so the "may" in front of it adds no answer the discard prompt does not
    already have. Collapsing them is what makes the sentence behind it work —
    a discard prompt suspends the resolution until every seat has answered
    (CR 608.2), where an offer does not, and "…damage equal to 3 minus the
    number of cards **they** discarded this way" has to run after the answers
    rather than before them.

    Deliberately narrow. It returns None — leaving the ordinary offer — unless
    the whole sentence is that one shape: an unconditional offer, made to a set
    of seats, of a chosen discard with a printed ceiling and nothing behind it.
    An offer with a cost, an if-you-do or an otherwise is a second decision that
    the discard prompt genuinely cannot carry.
    """
    action = node.action
    if (
        node.cost is not None
        or node.then is not None
        or node.otherwise is not None
        or node.reflexive is not None
        or node.starting_with is not None
        or not isinstance(node.actor, ast.PlayerRef)
        or node.actor.kind not in _EACH_SEAT_ACTORS
        or not isinstance(action, ast.Discard)
        or not isinstance(action.player, ast.PlayerRef)
        or action.player.kind != "you"
        or not action.up_to
        or action.at_random
        or action.whole_hand
        or action.filter is not None
        or not isinstance(action.count, ast.Fixed)
    ):
        return None
    return (
        OracleInstruction(
            "each_player_discards_up_to_cards", "",
            {"actor": node.actor.kind, "amount": action.count.value},
        ),
    )


def _each_player_optional_pay_mana(
    node: ast.May,
) -> tuple[OracleInstruction, ...] | None:
    """"Each player may pay any amount of mana." (Liege of the Hollows.)

    :func:`_each_player_optional_discard`'s shape one cost over, and collapsed
    for its two reasons. Zero is already a legal answer to "any amount", so the
    "may" adds no answer the payment prompt does not have; and the sentence
    behind it ("… equal to the amount of mana **they paid this way**") has to
    run after every seat has answered. (An ordinary ``optional_pay`` offer
    suspends its resolution too since Judgment's W2G2, so that half of the
    reason is now shared; the first half is why the collapse stays.)

    Deliberately narrow, exactly as the discard's collapse is: an offer with a
    cost, an if-you-do or an otherwise is a second decision this prompt cannot
    carry, so the ordinary offer is left in place and refuses by name.
    """
    action = node.action
    if (
        node.cost is not None
        or node.then is not None
        or node.otherwise is not None
        or node.reflexive is not None
        or node.starting_with is not None
        or not isinstance(node.actor, ast.PlayerRef)
        or node.actor.kind not in _EACH_SEAT_ACTORS
        or not isinstance(action, ast.PayAnyAmountOfMana)
        or action.player.kind != "you"
    ):
        return None
    return (
        OracleInstruction(
            "each_player_pays_any_mana", "", {"actor": node.actor.kind},
        ),
    )


def _each_player_optional_draw(
    node: ast.May,
) -> tuple[OracleInstruction, ...] | None:
    """"Each player may draw **up to two** cards." (Truce.)

    :func:`_each_player_optional_discard`'s twin one zone over, collapsed for
    that function's two reasons. The offer and the ceiling are one decision —
    "up to two" already lets a player draw none, so the "may" adds no answer the
    prompt does not have — and the sentence *behind* it reads the answers: "For
    each card less than two a player draws this way, that player gains 2 life"
    has to run after every seat has said how many, which an offer does not wait
    for and a suspending prompt does.

    Deliberately narrow, exactly as its two siblings are: an offer with a cost,
    an if-you-do or an otherwise is a second decision the prompt cannot carry,
    and the sentence keeps the ordinary offer.
    """
    action = node.action
    if (
        node.cost is not None
        or node.then is not None
        or node.otherwise is not None
        or node.reflexive is not None
        or node.starting_with is not None
        or not isinstance(node.actor, ast.PlayerRef)
        or node.actor.kind not in _EACH_SEAT_ACTORS
        or not isinstance(action, ast.Draw)
        or not isinstance(action.player, ast.PlayerRef)
        or action.player.kind != "you"
        or not action.up_to
        or not isinstance(action.count, ast.Fixed)
    ):
        return None
    return (
        OracleInstruction(
            "each_player_draws_up_to_cards", "",
            {"actor": node.actor.kind, "amount": action.count.value},
        ),
    )


def _referent_seat_optional_draw(
    node: ast.May, produced: frozenset[str],
) -> tuple[OracleInstruction, ...] | None:
    """"**Its controller** may draw up to two cards …" (Arcane Denial.)

    :func:`_each_player_optional_draw`'s sibling with **one** seat instead of a
    set, and the same collapse for the same two reasons: "up to two" already
    lets the seat draw none, so the offer in front of it adds no answer the
    ``draw_up_to`` prompt does not have, and the prompt suspends the resolution
    (CR 608.2e) where a plain offer does not.

    "Its controller" is the countered spell's, and it is read off the record the
    counter wrote rather than off the board — which is the whole reason this is
    gated on *produced*. CR 108.4 gives a card in a graveyard no controller at
    all, and this sentence is printed inside a delay: by the time it runs, a
    turn has passed and the spell is a card nobody controls. With no counter in
    front of it the words name a seat nothing recorded, so the sentence keeps
    the refusal it has today rather than drawing for whoever happens to be
    ``context.target``.

    Deliberately narrow, exactly as its three siblings are: an offer with a
    cost, an if-you-do or an otherwise is a second decision the prompt cannot
    carry.
    """
    action = node.action
    if (
        node.cost is not None
        or node.then is not None
        or node.otherwise is not None
        or node.reflexive is not None
        or node.starting_with is not None
        or not isinstance(node.actor, ast.PlayerRef)
        or node.actor.kind != "controller"
        or COUNTERED_SPELL_CONTROLLER not in produced
        or not isinstance(action, ast.Draw)
        or not isinstance(action.player, ast.PlayerRef)
        or action.player.kind != "you"
        or not action.up_to
        or not isinstance(action.count, ast.Fixed)
    ):
        return None
    return (
        OracleInstruction(
            "draw_up_to_cards", "",
            {
                "amount": action.count.value,
                "drawer_seat_record": COUNTERED_SPELL_CONTROLLER,
            },
        ),
    )


#: The actors that are a **target the announcement chose** (CR 601.2c /
#: 602.2b): one seat, held in ``context.target`` for the whole resolution.
_TARGETED_ACTORS = frozenset({"target_opponent", "target_player"})


#: The set-of-seats actors whose offer the handler makes **performed by** the
#: seat it is put to (``_offer_to_seat`` rebinds ``caster`` for them), so a
#: pile the action names with "their" is that seat's own.
_SELF_PERFORMING_SEAT_SETS = frozenset({"each_player", "each_opponent"})


def _with_exiled_pile_of(node: ast.May, owner: ast.PlayerRef) -> ast.May:
    """*node* with its offered exile's graveyard rewritten to *owner*."""
    action = node.action
    return dataclasses.replace(node, action=dataclasses.replace(
        action, subject=dataclasses.replace(
            action.subject, filter=dataclasses.replace(
                action.subject.filter, zone_owner=owner,
            ),
        ),
    ))


def _is_their_own_graveyard_card(subject) -> bool:
    """Whether *subject* is "a <card> from **their** graveyard" — one chosen
    card out of a pile named by the pronoun (which the noun parser spells as
    the owner's)."""
    return (
        isinstance(subject, ast.TargetSpec)
        and not subject.targeted
        and subject.quantifier in ("a", "an")
        and subject.filter.zone == "graveyard"
        and subject.filter.is_card
        and getattr(subject.filter.zone_owner, "kind", None) == "owner"
    )


def offered_seat_performs(node: ast.May) -> ast.May:
    """"**Target opponent** may draw a card." (Phelddagrif, Soldevi Heretic,
    Questing Phelddagrif.) *node* with the offer's bare imperative given the
    subject the sentence gives it.

    The parser reads "draw a card" inside the offer as it reads it anywhere —
    a bare imperative, so ``Draw(player=you)`` (CR 608.2c: an effect with no
    printed subject is its controller's). But the sentence has a subject and it
    is printed: the seat that is offered is the seat that draws. Left alone the
    action lowered to ``draw_controller_cards``, so the opponent was asked and
    the ability's **own controller drew** — three shipped activations that
    handed their controller the card the text gives away, on a card that
    compiled supported with every sentence claimed.

    Fixed here, in the node, rather than by moving ``context.caster`` when the
    offer is taken (which is what ``_offer_to_seat`` does for a *set* of
    seats). The other two cards in the pool that offer something to a targeted
    seat are why: Amulet of Quoz's decline branch is "**you** flip a coin" and
    Soul Echo's action is a choice about damage "dealt to **you**" — both say
    "you" of the ability's controller in so many words, and a moved caster
    would hand the flip and the counters to the opponent. So only the subject
    of the one clause that had none is rewritten, to the seat the announcement
    chose; the offer keeps its own target description beside it, and both name
    the same announcement.

    **Draw alone, and anything else refuses.** A bare imperative of another
    kind ("target opponent may discard a card") has the same missing subject
    and no reading here; admitting it would be the controller performing an
    action the card offers somebody else, silently, which is the defect this
    function exists for.

    **An offer to a set of seats names the pile the same way, and resolves it
    differently.** "Whenever this creature attacks or blocks, **any player**
    may exile a card from **their** graveyard." (Carrion Rats, Carrion Wurm.)
    ``handlers/control_flow._offer_to_seat`` moves ``context.caster`` onto each
    offered seat for these actors, so the seat that takes the offer is the
    resolution's "you" while it performs — the pile is rewritten to that, and
    the pick comes out of the graveyard of whoever said yes.
    """
    if (
        isinstance(node.actor, ast.PlayerRef)
        and node.actor.kind in _SELF_PERFORMING_SEAT_SETS
        and isinstance(node.action, ast.Exile)
        and _is_their_own_graveyard_card(node.action.subject)
    ):
        return _with_exiled_pile_of(node, ast.PlayerRef("you"))
    if not (
        isinstance(node.actor, ast.PlayerRef)
        and node.actor.kind in _TARGETED_ACTORS
    ):
        return node
    action = node.action
    # "**Target opponent** may exile a card from **their** graveyard."
    # (Gravestorm.) The same missing subject one clause over: the bare exile
    # names its pile with a pronoun, and the pronoun is the seat the offer
    # names. Rewritten to that seat so the lowering reads one printed owner —
    # the node ``tolls.accept_graveyard_exile_price`` builds for "unless that
    # player exiles a card from their graveyard".
    if isinstance(action, ast.Exile) and _is_their_own_graveyard_card(action.subject):
        return _with_exiled_pile_of(node, node.actor)
    performer = getattr(action, "player", None)
    if not (isinstance(performer, ast.PlayerRef) and performer.kind == "you"):
        # No action, or one that names its own seat ("…may ante the top card of
        # **their** library"): nothing here is missing a subject.
        return node
    if not isinstance(action, ast.Draw):
        raise LoweringError(
            "no handler has a targeted player perform this offered action",
            node=node,
        )
    return dataclasses.replace(
        node, action=dataclasses.replace(action, player=node.actor)
    )


def each_seat_pays_its_own_toll(node: ast.May) -> ast.May:
    """"When this creature enters, **each opponent** sacrifices a permanent of
    their choice **unless they pay {3}**." (Rishadan Brigand, Cutpurse,
    Footpad.) *node* with the toll put to every seat of the set, each paying
    for itself.

    The trailing toll reads "they" as the pronoun every "unless they pay"
    starts as (``that_player``), and the sentence it trails names a **set of
    seats** — so the pronoun is each of them in turn (CR 118.12a: "[do
    something] unless [a player does something else]" is "[that player] may
    [do something else]; if they don't, [do something]", once per player the
    sentence is about). Left as ``that_player`` the offer went to whichever
    seat the resolution's target channel held, and that one seat's decline
    made **every** opponent sacrifice: at three seats the second opponent was
    never asked.

    So the actor becomes the set and the penalty's performer becomes the
    offered seat — spelled ``you``, because ``handlers/control_flow.
    _offer_to_seat`` moves ``caster`` onto each seat of a set while its copy
    of the offer resolves, which is what :func:`offered_seat_performs`'
    graveyard rewrite relies on too. A sacrifice alone: it is the one penalty
    a set of seats pays this way in the pool, and any other body naming a set
    under the pronoun refuses rather than charging one seat's decline to all
    of them.
    """
    if not (
        isinstance(node.actor, ast.PlayerRef)
        and node.actor.kind == "that_player"
        and node.action is None
        and node.then is None
        and node.reflexive is None
    ):
        return node
    body = node.otherwise
    performer = getattr(body, "player", None)
    if not (
        isinstance(performer, ast.PlayerRef)
        and performer.kind in _SELF_PERFORMING_SEAT_SETS
    ):
        return node
    if not isinstance(body, ast.Sacrifice):
        raise LoweringError(
            "\"unless they pay\" behind a set of seats is offered per seat, "
            "and only a sacrifice is performed by the seat that declined",
            node=node,
        )
    return dataclasses.replace(
        node,
        actor=performer,
        otherwise=dataclasses.replace(body, player=ast.PlayerRef("you")),
    )


#: The actors the firing event named whose offer the handler makes **performed
#: by** the seat it is put to — ``handlers/control_flow._EVENT_ACTORS``, which
#: rebinds ``caster`` for them whenever the offer carries an action (Pillar
#: Tombs of Aku, Apathy). Spelled as the two strings rather than imported, for
#: the reason ``_SELF_PERFORMING_SEAT_SETS`` above is: the constants live a
#: family over.
_PERFORMING_EVENT_ACTORS = frozenset({"event_subject_player", "event_subject_controller"})


def event_seat_performs(node: ast.May, actor: str) -> ast.May:
    """*node* with "their graveyard" read as the performer's own pile, where
    the offer's resolved *actor* is a seat the firing event froze.

    "At the beginning of combat on each opponent's turn, **that player may
    exile a card from their graveyard**." (Web of Inertia.) The noun parser
    spells "their" as the owner's; under an offer to "that player" there was no
    reading of it, and the line refused. The handler makes the event's seat the
    performer of an offer with an action — so the seat taking it is the
    resolution's "you" while it acts, and the pile is rewritten to that, exactly
    as :func:`offered_seat_performs` rewrites it for an offer to every seat
    (Carrion Rats). The pick then comes out of the graveyard of the seat that
    said yes, and out of nobody else's.

    Every other actor, and every other action, is left alone.
    """
    if (
        actor in _PERFORMING_EVENT_ACTORS
        and isinstance(node.action, ast.Exile)
        and _is_their_own_graveyard_card(node.action.subject)
    ):
        return _with_exiled_pile_of(node, ast.PlayerRef("you"))
    return node


def without_restated_target(
    action: "tuple[OracleInstruction, ...]", announced: "dict | None",
) -> "tuple[OracleInstruction, ...]":
    """*action* with the offer's own announcement described once.

    The other half of :func:`offered_seat_performs`. The re-pointed draw lowers
    as "target opponent draws a card" and so describes a target of its own —
    the *same* one the offer around it already describes, since the sentence
    prints the word once. Two descriptions of one announcement read as two
    announcements: ``describe_sequence_target_roles`` counts described slots,
    and Soldevi Heretic ("Prevent the next 2 damage … to **target creature**
    this turn. **Target opponent** may draw a card.") stopped being the
    creature-and-player pair it is the moment its draw said "target" a second
    time. So the step keeps its kind — the handler reads the chosen seat off
    the context either way — and the offer keeps the one description.
    """
    if not announced:
        return action
    return tuple(
        OracleInstruction(step.kind, step.value, {
            key: value for key, value in step.payload.items() if key != "targets"
        })
        if step.payload.get("targets") == announced else step
        for step in action
    )


def _each_player_optional_graveyard_exile(
    node: ast.May,
) -> tuple[OracleInstruction, ...] | None:
    """"Each player may exile **any number of** cards from their graveyard."
    (Grave Consequences.)

    :func:`_each_player_optional_discard`'s twin one zone over, collapsed for
    its two reasons. "Any number" already lets a seat exile none, so the "may"
    adds no answer the graveyard pick does not have; and the sentence behind it
    ("Then each player loses 1 life for each card in their graveyard") has to
    run after every seat has answered, which the ``graveyard_exile_pick``
    prompt waits for (it suspends) and an offer per seat does not.

    The pile is each seat's **own** ("their"), and the instruction is the
    graveyard exile every other unannounced pick lowers onto
    (``exile_cards_from_graveyard``), with the seat set as its pile owner and
    no printed count: the ceiling is each pile's size, which only the
    resolution knows.

    Deliberately narrow, exactly as its siblings are: an offer with a cost, an
    if-you-do or an otherwise is a second decision the pick cannot carry; a
    narrowing beyond one card type, a duration, counters or a face-down rider
    is a shape the pick does not perform, and the ordinary offer refuses it.
    """
    action = node.action
    if (
        node.cost is not None
        or node.then is not None
        or node.otherwise is not None
        or node.reflexive is not None
        or node.starting_with is not None
        or not isinstance(node.actor, ast.PlayerRef)
        or node.actor.kind not in _EACH_SEAT_ACTORS
        or not isinstance(action, ast.Exile)
        or action.actor is not None
        or action.duration.kind is not None
        or action.counters
        or action.face_down
        or action.same_zone
        or not isinstance(action.subject, ast.TargetSpec)
    ):
        return None
    spec = action.subject
    filt = spec.filter
    if (
        spec.targeted
        or spec.quantifier != "any_number"
        or filt.zone != "graveyard"
        or not filt.is_card
        or getattr(filt.zone_owner, "kind", None) != "owner"
    ):
        return None
    if len(filt.card_types) > 1 or _restrictions_beyond(
        filt, frozenset({"card_types", "zone", "zone_owner", "is_card"})
    ):
        raise LoweringError(
            "the each-player graveyard exile reads one card type", node=node
        )
    pile: dict[str, object] = {
        "graveyard_owner": node.actor.kind,
        "up_to": True,
        "any_number": True,
    }
    if filt.card_types:
        pile["card_type"] = filt.card_types[0]
    else:
        # ``graveyard_card_matches`` reads an absent type as "creature card";
        # "cards" names any card, said out loud.
        pile["any_card"] = True
    return (OracleInstruction("exile_cards_from_graveyard", "", pile),)


#: The scratchpad key the each-seat hand pick records ``{seat: [cards]}``
#: under for the put behind it — Stronghold Gambit's spelling of the same
#: per-seat pick, so one record has one name.
_CHOSEN_HAND_CARDS_BY_SEAT = "chosen_hand_cards_by_seat"


def _their_hand_card_filter(filt: "ast.ObjectFilter", node, what: str) -> dict:
    """The card filter an each-seat pick out of "their hand" tests, or a
    refusal naming the word it cannot honour.

    ``to_payload`` emits nothing for a relative narrowing, so the printed
    phrase is held to what a card in a hand can answer before the payload is
    built — the reveal lowering's own gate, for its reason: a pick offering a
    wider set than the card prints is a card that cheats."""
    leftover = _restrictions_beyond(
        filt, _PAYLOAD_HONOURED_FILTER_FIELDS | {"is_card", "zone", "zone_owner"}
    )
    if leftover:
        raise LoweringError(f"the {what} does not honour {leftover[0]!r}", node=node)
    payload = filt.to_payload()
    payload.pop("zone", None)
    payload.pop("zone_owner", None)
    described = card_only_filter(payload)
    if described is None:
        raise LoweringError(
            f"the {what} cannot test this restriction on a card in a hand",
            node=node,
        )
    return described


def _is_plain_each_seat_offer(node: ast.May) -> bool:
    """An unconditional offer to a set of seats with nothing beside its action
    — the shape every collapse in this module reads."""
    return (
        node.cost is None
        and node.then is None
        and node.otherwise is None
        and node.reflexive is None
        and node.starting_with is None
        and isinstance(node.actor, ast.PlayerRef)
        and node.actor.kind in _EACH_SEAT_ACTORS
    )


def _each_seat_optional_hand_reveal(
    node: ast.May,
) -> tuple[OracleInstruction, ...] | None:
    """"**Each player may** reveal any number of creature cards from their
    hand." (Kamahl's Summons.)

    :func:`_each_player_optional_discard`'s shape one verb over, collapsed for
    its two reasons: "any number" already lets a seat reveal none, so the "may"
    adds no answer the hand pick does not have; and the sentence behind it
    ("…for each card **they** revealed this way") has to run after every seat
    has answered, which the pick waits for (it suspends) and an offer per seat
    does not. The seats are asked one at a time in APNAP order
    (``resumption.ask_in_turn_order``) — a reveal is public, so a later seat
    chooses knowing what an earlier one showed (CR 101.4b) — and each answer is
    recorded per seat (``REVEALED_BY_SEAT``, ``REVEALED_HAND_CARDS_BY_SEAT``).

    Only "their" hand and only "any number of": a printed count is a second
    shape the record does not distinguish, and refuses through the ordinary
    offer.
    """
    action = node.action
    if not (
        _is_plain_each_seat_offer(node)
        and isinstance(action, ast.RevealCardsFromHand)
        and action.count is None
        and getattr(action.filter.zone_owner, "kind", None) == "owner"
    ):
        return None
    return (
        OracleInstruction(
            "reveal_cards_from_hand", "",
            {
                "card_filter": _their_hand_card_filter(
                    action.filter, node, "each-seat reveal"
                ),
                "any_number": True,
                "reveal": True,
                "result_key": REVEALED_HAND_CARDS_BY_SEAT,
                "count_key": REVEALED_BY_SEAT,
                "actor": node.actor.kind,
            },
        ),
    )


def _each_seat_optional_put_from_hand(
    node: ast.May,
) -> tuple[OracleInstruction, ...] | None:
    """"When this creature enters, **each opponent may** put any number of
    artifact, creature, enchantment, and/or land cards from their hand onto
    the battlefield." (Tempting Wurm.)

    "Any number" already lets a seat put none, so the offer and the pick are
    one decision — collapsed for :func:`_each_player_optional_discard`'s
    reason. And the cards enter **together**: each seat chooses in APNAP order
    (CR 101.4; the picks may stay face down, CR 101.4a) and then the actions
    happen simultaneously, which is two steps — Stronghold Gambit's per-seat
    hand pick (``choose_cards_in_hand``, recorded per seat) and its put of the
    recorded cards (``put_chosen_hand_cards_onto_battlefield``), each card
    under its owner's control. An Aura among them is attached as it enters to
    something already on the battlefield (CR 303.4f), or stays in hand.

    Only the bare entry: a printed "tapped", a controller, a gained ability or
    an attachment is a rider the put does not carry, and the ordinary offer
    refuses it by name.
    """
    action = node.action
    if not (
        _is_plain_each_seat_offer(node)
        and isinstance(action, ast.PutOntoBattlefield)
        and isinstance(action.target, ast.TargetSpec)
    ):
        return None
    target = action.target
    filt = target.filter
    if (
        target.targeted
        or target.quantifier != "any_number"
        or filt.zone != "hand"
        or not filt.is_card
        or getattr(filt.zone_owner, "kind", None) != "owner"
    ):
        return None
    if (
        action.under_your_control
        or action.under_owners_control
        or action.gains
        or action.sacrifice_when_control_lost
        or action.attached_to_source
        or action.attached_to_chosen is not None
        or action.entering_colors
        or action.entering_subtypes
        or getattr(action, "tapped", False)
        or getattr(action, "actor", None) is not None
    ):
        raise LoweringError(
            "the each-seat put from hand carries no entry rider", node=node
        )
    described = _their_hand_card_filter(filt, node, "each-seat put from hand")
    if not filt.card_types:
        # "…may put any number of **Goblin** cards from their hand onto the
        # battlefield": a creature type with no card type is any card with the
        # subtype (CR 205.3m), a Kindred instant among them, which CR 400.4a
        # keeps in the hand. The pick offers only what could enter — CR
        # 110.4a's "permanent card", the reading the chosen put one branch
        # over (``zones``' "up to N", ``type_filter`` of the six) and the
        # single pick (``permanents_only``) take — which for "any number" is
        # the same outcome: a card picked that cannot enter would stay where
        # it is. The put behind it asks ``permanent_cards`` again regardless.
        described = {**described, "type_filter": list(PERMANENT_CARD_TYPES)}
    return (
        OracleInstruction("sequence", "", {"steps": (
            OracleInstruction(
                "choose_cards_in_hand", "",
                {
                    "card_filter": described,
                    "any_number": True,
                    "result_key": _CHOSEN_HAND_CARDS_BY_SEAT,
                    "actor": node.actor.kind,
                    # CR 101.4a: a card chosen out of a hand may stay face
                    # down as it is chosen; it is public once it enters.
                    "hidden": True,
                },
            ),
            OracleInstruction(
                "put_chosen_hand_cards_onto_battlefield", "",
                {"cards_from": _CHOSEN_HAND_CARDS_BY_SEAT, "card_filter": described},
            ),
        )}),
    )


def _each_player_optional_tap(
    node: ast.May,
) -> tuple[OracleInstruction, ...] | None:
    """"Each player may tap **any number** of untapped white creatures they
    control." (Raiding Party.)

    :func:`_each_player_optional_discard`'s twin one zone over, and the same
    collapse for the same reason: the offer and the ceiling are one decision.
    "Any number" already lets a seat tap none, so the "may" in front of it adds
    no answer the tap prompt does not already have — and collapsing them is what
    makes the sentence behind it work, because the tap prompt suspends the
    resolution until every seat has answered (CR 608.2e) where an offer does
    not. "For each creature tapped this way, that player chooses…" has to run
    after the answers rather than before them.

    Deliberately narrow, exactly as the discard is: an offer with a cost, an
    if-you-do or an otherwise is a second decision the tap prompt genuinely
    cannot carry, and the sentence keeps the ordinary offer.

    Written here rather than in the tapping family because what it recognises is
    a ``May`` — the collapse is about the offer, and the instruction it emits is
    the one the tap handler already reads.
    """
    action = node.action
    if (
        node.cost is not None
        or node.then is not None
        or node.otherwise is not None
        or node.reflexive is not None
        or node.starting_with is not None
        or not isinstance(node.actor, ast.PlayerRef)
        or node.actor.kind not in _EACH_SEAT_ACTORS | {"you"}
        or not isinstance(action, ast.Tap)
        or not isinstance(action.subject, ast.TargetSpec)
    ):
        return None
    spec = action.subject
    if spec.targeted or spec.quantifier != "any_number":
        return None
    # Every narrowing the prompt can actually test, and nothing else. The pick
    # is offered from a list ``subject_matches`` builds, so a key it cannot
    # answer would be a phrase silently dropped — and on a *choice* a dropped
    # narrowing offers permanents the card never named.
    leftovers = _restrictions_beyond(
        spec.filter,
        frozenset({"card_types", "type_match", "subtypes", "colors",
                   "controller", "tapped"}),
    )
    if leftovers:
        raise LoweringError(
            "the any-number tap cannot narrow by: " + ", ".join(leftovers),
            node=node,
        )
    described = _filter_payload(spec.filter)
    if untestable_filter_keys(described):
        raise LoweringError(
            "the any-number tap cannot test this restriction", node=node
        )
    return (
        OracleInstruction(
            "tap_any_number_matching", "",
            {
                "filter": described,
                # ``ObjectFilter.to_payload`` emits ``untapped_only`` for the
                # tri-state's False half, and the prompt reads it there — this
                # is the same fact carried where the *prompt* reads it, which
                # is a second channel the handler already had for Siege
                # Striker. The count is what the card is about, so a dropped
                # "untapped" would offer creatures already tapped and buy their
                # controller two Plains apiece for nothing.
                "untapped_only": spec.filter.tapped is False,
                "who": node.actor.kind,
            },
        ),
    )
