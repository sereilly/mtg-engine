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

from ...oracle_types import COUNTERED_SPELL_CONTROLLER, OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import _filter_payload, _restrictions_beyond


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
    run after every seat has answered, which a prompt does and an ordinary
    ``optional_pay`` offer — whose spec does not suspend — does not.

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
