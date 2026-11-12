"""Which CR 116 special action an AI seat takes, if any.

``engine/special_actions.py`` offers a seat the actions CR 116.2c–e describe —
Circling Vultures' discard, a Licid's "you may pay {C} to end this effect",
Volrath's Curse's and Lost in Thought's "…for that player to ignore this
effect until end of turn", Damping Engine's — and the browser shows a person
each one. **No AI path took any of them**, so a creature under Volrath's
Curse never attacked again in a simulated game however little the price was:
the offer was made every main phase (26 times in one three-game TMP run with
the Curse pinned, `w2g3` measure) and nothing answered it.

Weighed the way a cast is: carried out on a scratch copy of the game
(``ai_rehearsal.rehearse``) against the same copy with nothing done, **with the
turn's combat fought on both** (``through_combat``), because what the CR 116.2d
offers buy is a creature's attack this turn and the fight is where that is
worth anything. What the action costs is in the reading where the standing can
see it — a sacrificed permanent leaves the board — and is added where it
cannot: cards exiled out of the taker's own graveyard are priced as a toll
prices them (``ai_offer_answers._toll_loss_price``, the precedent this decision
follows), since no standing counts a graveyard — and one the seat could still
cast from there (flashback) as the card in hand it nearly is.

**Only the offers whose good the rehearsal can see are weighed**
(:data:`WEIGHED_OFFERS`), by kind — never by card:

* ``ignore_attached_static_until_eot`` (CR 116.2d, Volrath's Curse, Lost in
  Thought): the attack it frees is fought in the rehearsal. Weighed.
* ``ignore_board_static_until_eot`` (Damping Engine): what it buys is the casts
  the prohibition stops, which a rehearsal of the action alone does not make —
  it would always read as a permanent given up for nothing. Not weighed.
* ``end_own_continuous_effect`` (the Licids, CR 116.2c): ending the effect is
  worth something mostly *in response* — the host about to die — and this
  chooser is asked in a main phase. Not weighed.
* Circling Vultures' discard (CR 116.2e) is a hand card's action, not a
  permanent's offer; nothing in a main phase prices a discard for its own sake.
* ``turn_face_up`` (CR 702.37e, 116.2b): turning a face-down permanent with a
  morph ability face up. What it buys is the face-up creature, in the fight and
  after it, which is what the rehearsal reads. Weighed.

Each of those is a finding left measured, not a branch here: a kind joins the
set the day something can price what it buys.

The defending seat is not asked: an Aura's "can't block" is ignored in the
opponent's turn, between attackers and blockers, and a rehearsal that declares
the defender's blocks from that step does not exist (``ai_rehearsal`` fights a
combat only from a main phase).

**In response** (:func:`choose_response_special_action`, asked by
``ai_priority.act_at_priority`` in its ``"response"`` window — another seat's
object on top of the stack): a special action needs only priority (CR 116.2b:
"Turning a face-down creature face up is a special action. A player can take
this action any time they have priority"), and a morph's turn-up is most of what an instant-speed answer
is — "When this creature is turned face up, copy target instant or sorcery
spell" (Mischievous Quanar), "counter target spell" (Voidmage Apprentice),
"change the target of target spell or ability with a single target"
(Willbender), "regenerate target creature" (Daru Mender), a body that no
longer dies to the burn spell aimed at it. Only the main phase asked, so no AI
seat ever turned one up over a spell (kg4). Weighed by the same rehearsal,
against the table where the object resolves with nothing done
(:data:`RESPONSE_OFFERS`).
"""

from __future__ import annotations

from dataclasses import dataclass

from .ai_offer_readers import TollLoss
from .ai_offer_answers import _toll_loss_price
from .ai_rehearsal import (
    combat_is_still_to_come,
    deliberating,
    has_a_creature_to_fight_with,
    rehearse,
    rehearsing,
)
from .ai_standing import CARD_WORTH, permanent_loss, priced_as_their_blanks
from .face_down import TURN_FACE_UP
from .game import Game
from .special_actions import (
    available_permanent_special_actions,
    take_permanent_special_action,
)
from .ai_player_control import plays_for_another

#: The offer kinds this chooser weighs — the ones whose good a rehearsal run
#: through the turn's fight can see. See the module docstring for the kinds
#: left out and why.
WEIGHED_OFFERS = frozenset({
    "ignore_attached_static_until_eot",
    # CR 702.37e: turning a face-down permanent face up for its morph cost.
    # What it buys is the face-up creature — its power, toughness and
    # abilities through the layers — on the board and in the turn's fight,
    # which is exactly what a rehearsal through combat reads.
    TURN_FACE_UP,
})

#: The offer kinds weighed **in response** to another seat's object
#: (:func:`choose_response_special_action`): the ones whose good a rehearsal
#: of that object's resolution can see. ``ignore_attached_static_until_eot``
#: buys an attack, which no response is made before; a Licid's
#: ``end_own_continuous_effect`` would be read here too (its host about to
#: die), and is left for the round that measures it.
RESPONSE_OFFERS = frozenset({TURN_FACE_UP})


@dataclass(frozen=True)
class SpecialActionChoice:
    """One special action a seat has decided to take: the permanent making
    the offer (by id, CR 400.7), the offer's kind, and the permanent paying a
    "sacrifice a permanent of their choice" price (by id; None when the offer
    charges none). ``worth`` is what the rehearsal measured, net of the price
    it could not see."""

    permanent_id: int
    kind: str
    name: str
    sacrificed_id: int | None
    worth: float
    #: The X announced for a price printing ``{X}`` (CR 107.3d; "Morph
    #: {X}{B}{B}", Bane of the Living), the size whose rehearsal read best;
    #: None for every price without one.
    x_value: int | None = None


#: The most sizes of X one offer is rehearsed at, largest first (see
#: :func:`_x_sizes`). Each is a whole rehearsal through the turn's fight.
_MAX_X_SIZES = 4


@dataclass(frozen=True)
class _Taken:
    """The shape a rehearsal reads off what it carried out (``supported``,
    ``details``) — the engine's special-action seam answers with a refusal or
    None instead of a ``SimulationResult``."""

    supported: bool
    details: str


def choose_special_action(game: Game, seat: int) -> SpecialActionChoice | None:
    """The special action *seat* takes now, or None.

    Asked in *seat*'s own main phase with its combat still ahead
    (``combat_is_still_to_come``) — the only moment the attack an offer frees
    can be fought — and only of what the engine offers it right now
    (``available_permanent_special_actions``, the gate the action asks), so
    the seat must hold priority (CR 116.2d). Each offer is rehearsed through
    the fight against the table with nothing taken; the best one that leaves
    the seat ahead is taken.
    """
    if rehearsing() or not combat_is_still_to_come(game, seat):
        return None
    if not has_a_creature_to_fight_with(game, seat):
        return None
    entries = [
        entry for entry in available_permanent_special_actions(game, seat)
        if entry["kind"] in WEIGHED_OFFERS
    ]
    if not entries:
        return None
    best: SpecialActionChoice | None = None
    with deliberating():
        for entry in entries:
            for x_value in _x_sizes(entry):
                choice = _weighed(game, seat, entry, x_value)
                if choice is not None and (best is None or choice.worth > best.worth):
                    best = choice
    return best


def holds_a_response_special_action(game: Game, seat: int) -> bool:
    """The cheap question before :func:`choose_response_special_action`:
    whether *seat* controls a face-down permanent — the only kind of
    permanent making a :data:`RESPONSE_OFFERS` offer — so a response window
    with none costs no listing of the board's offers."""
    from .face_down import is_face_down

    return any(is_face_down(permanent) for permanent in game.controlled_by(seat))


def choose_response_special_action(game: Game, seat: int) -> SpecialActionChoice | None:
    """The special action *seat* takes **in response** to the object on top
    of the stack — another seat's (``ai_priority.instant_speed_window``'s
    ``"response"``) — or None.

    What the engine offers it right now (``available_permanent_special_actions``,
    the gate the action asks: priority, the morph cost payable), of the kinds
    a response can price (:data:`RESPONSE_OFFERS`), each rehearsed against the
    table where the stack resolves with nothing taken — the turn-up's trigger
    put on the stack above the object it answers (CR 116.3, 603.3) and
    resolved first; the best one that leaves the seat ahead is taken. In the
    declare-attackers step before the blocks (``ai_rehearsal.blocks_owed``, an
    attack trigger answered) the copies fight the rest of that combat, which
    they owe once their stacks resolve; a declared combat's damage is dealt
    on the way to the end of the turn either way.
    """
    if rehearsing() or not game.stack or game.stack[-1].caster_index == seat:
        return None
    if plays_for_another(game, seat):
        return None
    from .ai_rehearsal import blocks_owed

    entries = [
        entry for entry in available_permanent_special_actions(game, seat)
        if entry["kind"] in RESPONSE_OFFERS
    ]
    if not entries:
        return None
    through_combat = blocks_owed(game)
    best: SpecialActionChoice | None = None
    with deliberating():
        for entry in entries:
            for x_value in _x_sizes(entry):
                choice = _weighed(
                    game, seat, entry, x_value, through_combat=through_combat,
                )
                if choice is not None and (best is None or choice.worth > best.worth):
                    best = choice
    return best


def special_action_in_response(
    game: Game, seat: int,
) -> "tuple[SpecialActionChoice, _Taken] | None":
    """Ask :func:`choose_response_special_action` for *seat* and take what it
    chooses: ``(choice, result)`` — the result in the shape every door of
    ``ai_priority.act_at_priority`` answers with (``supported``,
    ``details``) — or None when it chose nothing.

    **The seat asked holds priority** (CR 116.2b). The engine's priority
    round asks its driver ``(game, seat)`` without writing the seat into
    ``priority_player_index`` (``Game.offer_priority``), and the offer's gate
    asks that field (``special_actions.permanent_special_action_refusal``): so while
    the round is being driven, or with nobody recorded, the field names the
    seat for the length of this question and is put back exactly as it was
    afterwards — :func:`special_action_before_combat`'s arrangement. Recorded
    for another seat outside a driven round, the seat is not asked."""
    held = (game.priority_player_index, game.priority_pass_count)
    if held[0] not in (None, seat) and not game.driving_priority:
        return None
    if held[0] != seat:
        game.start_priority_window(seat)
    try:
        choice = choose_response_special_action(game, seat)
        if choice is None:
            return None
        refusal = take_chosen_special_action(game, seat, choice)
        return choice, _Taken(refusal is None, refusal or "taken")
    finally:
        if held[0] != seat:
            game.priority_player_index, game.priority_pass_count = held


def _x_sizes(entry: dict) -> "tuple[int | None, ...]":
    """The X values *entry* is rehearsed at: ``(None,)`` for a price printing
    no ``{X}``; otherwise the largest the seat can pay (``max_x``, which the
    offer's listing computed through the seam's own payment plan) and the
    sizes below it, largest first, at most :data:`_MAX_X_SIZES` of them.

    Several rather than the largest alone because a bigger X is not always
    better for its taker: "all creatures get -X/-X" (Bane of the Living)
    reaches the taker's own board as well, and the rehearsal is what reads
    where the trade turns. 0 is offered last when it fits — the creature face
    up with nothing else — so a board where every X hurts still weighs the
    body by itself.
    """
    if not entry.get("x_symbols"):
        return (None,)
    top = max(0, int(entry.get("max_x") or 0))
    sizes = list(range(top, max(-1, top - _MAX_X_SIZES), -1))
    if 0 not in sizes:
        sizes[-1] = 0
    return tuple(sizes)


def _sacrifice_pick(game: Game, seat: int, entry: dict) -> "int | None | bool":
    """Which permanent pays *entry*'s "sacrifice a permanent of their choice"
    price, by id; None when the offer charges no sacrifice; False when nothing
    can pay it.

    The seat's own choice ("…of their choice"), over the offer's own list: the
    permanent whose loss its standing feels least
    (``ai_standing.permanent_loss`` — a land beyond the ones a seat needs
    before anything it uses), the engine's deterministic order
    (``Game.sacrifice_preference_key``) between equals. Never the permanent
    making the offer or the one it is attached to, which are what the action
    is being taken *for*: freeing a creature by sacrificing it buys nothing.
    """
    from .handlers._targets import attached_host

    choices = entry.get("sacrifice_choices")
    if choices is None:
        return None
    source = game.permanent_by_id(entry["permanent_id"])
    host = attached_host(game, source, last_known=False) if source is not None else None
    spared = {
        permanent.permanent_id for permanent in (source, host) if permanent is not None
    }
    candidates = [
        permanent
        for choice in choices
        if choice["permanent_id"] not in spared
        for permanent in (game.permanent_by_id(choice["permanent_id"]),)
        if permanent is not None
    ]
    if not candidates:
        return False
    return min(
        candidates,
        key=lambda permanent: (
            permanent_loss(game, seat, permanent),
            game.sacrifice_preference_key(permanent),
        ),
    ).permanent_id


def _weighed(
    game: Game, seat: int, entry: dict, x_value: "int | None" = None,
    *, through_combat: bool = True,
) -> SpecialActionChoice | None:
    """*entry* rehearsed through the turn's fight (at X = *x_value* for a
    price printing ``{X}``), or None when it is not worth taking.
    *through_combat* False reads it without a fight declared on the way — a
    response, whose good is what the stack's resolution leaves."""
    victim_id = _sacrifice_pick(game, seat, entry)
    if victim_id is False:
        return None

    def perform(table):
        source = table.permanent_by_id(entry["permanent_id"])
        if source is None:
            return _Taken(False, "the offer has gone")
        sacrificed = (
            table.permanent_by_id(victim_id) if isinstance(victim_id, int) else None
        )
        refusal = take_permanent_special_action(
            table, seat, source, entry["kind"], sacrificed=sacrificed,
            x_value=x_value,
        )
        return _Taken(refusal is None, refusal or "taken")

    # A turn-up is weighed with the permanent at its blank's cost on both
    # copies: what it buys is the face-up creature, not its card's mana value
    # (``ai_standing.priced_as_their_blanks``).
    priced = (entry["permanent_id"],) if entry["kind"] == TURN_FACE_UP else ()
    with priced_as_their_blanks(priced):
        rehearsal = rehearse(
            game, seat, perform, spell_name=None, leaves_hand=False,
            label=f"{entry['name']}'s special action",
            key=(
                "special_action", seat, entry["permanent_id"], entry["kind"],
                victim_id, x_value, through_combat,
            ),
            through_combat=through_combat,
        )
    if rehearsal is None or not rehearsal.accepted or not rehearsal.changed:
        return None
    worth = rehearsal.swing - _graveyard_price(game, seat, entry)
    if worth <= 0.0:
        return None
    return SpecialActionChoice(
        permanent_id=entry["permanent_id"], kind=entry["kind"], name=entry["name"],
        sacrificed_id=victim_id if isinstance(victim_id, int) else None,
        worth=worth, x_value=x_value,
    )


def special_action_before_combat(
    game: Game, seat: int,
) -> "tuple[SpecialActionChoice, str | None] | None":
    """Ask :func:`choose_special_action` for *seat* in its main phase and take
    what it chooses: ``(choice, the engine's refusal or None)``, or None when
    it chose nothing.

    A special action is taken by a player **with priority** (CR 116.2c-d), and
    the active player holds it in its own main phase while the stack is empty
    (CR 117.3a). A table that has recorded nobody holding it (the simulator's
    main phase, where every cast settles its own window; a web game between
    requests) has the window opened for the seat to be asked in and put back
    exactly as it was afterwards; a table where another seat holds priority is
    not asked at all. The one entry point the simulator and the web AI seat
    share.
    """
    # CR 723.5: a seat another player decides for plays nothing
    # optional for itself (``ai_player_control``'s measured policy).
    if plays_for_another(game, seat):
        return None
    if game.stack:
        return None
    held = (game.priority_player_index, game.priority_pass_count)
    if held[0] is None:
        game.start_priority_window(seat)
    elif held[0] != seat:
        return None
    try:
        choice = choose_special_action(game, seat)
        if choice is None:
            return None
        return choice, take_chosen_special_action(game, seat, choice)
    finally:
        if held[0] is None:
            game.priority_player_index, game.priority_pass_count = held


def _graveyard_price(game: Game, seat: int, entry: dict) -> float:
    """What the cards *entry*'s "exile N cards from their graveyard" price
    takes are worth — the part of the price no standing sees, since none
    counts a graveyard.

    The cards are the ones the take gives up when it is named none
    (``ai_prompt_readers.graveyard_price_order``, least valuable first), each
    priced as a toll prices one (``ai_offer_answers._toll_loss_price``) — except a
    card its owner could still cast from there (flashback, CR 702.34a), which
    that order calls a spell the seat still holds and which is priced as one:
    a card in hand (``ai_standing.CARD_WORTH``).
    """
    from .ai_prompt_readers import graveyard_price_order
    from .flashback import has_flashback

    count = int(entry.get("exile_from_graveyard") or 0)
    if count <= 0:
        return 0.0
    pile = game.players[seat].graveyard
    taken = graveyard_price_order(game, seat, list(range(len(pile))))[:count]
    castable = sum(
        1 for slot in taken if has_flashback(pile[slot], game=game, owner_seat=seat)
    )
    return (
        _toll_loss_price(game, seat, TollLoss(exiled_from_graveyard=count - castable))
        + castable * CARD_WORTH
    )


def take_chosen_special_action(
    game: Game, seat: int, choice: SpecialActionChoice,
) -> str | None:
    """Carry out *choice* on *game*: the engine's refusal, or None. The one
    executor the simulator and the web AI seat share."""
    source = game.permanent_by_id(choice.permanent_id)
    if source is None:
        return f"{choice.name} is no longer on the battlefield"
    sacrificed = (
        game.permanent_by_id(choice.sacrificed_id)
        if choice.sacrificed_id is not None else None
    )
    if choice.sacrificed_id is not None and sacrificed is None:
        return "the permanent chosen to pay for it has gone"
    return take_permanent_special_action(
        game, seat, source, choice.kind, sacrificed=sacrificed,
        x_value=choice.x_value,
    )


__all__ = [
    "RESPONSE_OFFERS",
    "SpecialActionChoice",
    "WEIGHED_OFFERS",
    "choose_response_special_action",
    "choose_special_action",
    "holds_a_response_special_action",
    "special_action_before_combat",
    "special_action_in_response",
    "take_chosen_special_action",
]
