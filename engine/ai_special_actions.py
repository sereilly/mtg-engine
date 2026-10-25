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
prices them (``ai_prompts._toll_loss_price``, the precedent this decision
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
"""

from __future__ import annotations

from dataclasses import dataclass

from .ai_prompt_readers import TollLoss
from .ai_prompts import _toll_loss_price
from .ai_rehearsal import (
    CARD_WORTH,
    combat_is_still_to_come,
    deliberating,
    has_a_creature_to_fight_with,
    permanent_loss,
    rehearse,
    rehearsing,
)
from .face_down import TURN_FACE_UP
from .game import Game
from .special_actions import (
    available_permanent_special_actions,
    take_permanent_special_action,
)

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
            choice = _weighed(game, seat, entry)
            if choice is not None and (best is None or choice.worth > best.worth):
                best = choice
    return best


def _sacrifice_pick(game: Game, seat: int, entry: dict) -> "int | None | bool":
    """Which permanent pays *entry*'s "sacrifice a permanent of their choice"
    price, by id; None when the offer charges no sacrifice; False when nothing
    can pay it.

    The seat's own choice ("…of their choice"), over the offer's own list: the
    permanent whose loss its standing feels least
    (``ai_rehearsal.permanent_loss`` — a land beyond the ones a seat needs
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


def _weighed(game: Game, seat: int, entry: dict) -> SpecialActionChoice | None:
    """*entry* rehearsed through the turn's fight, or None when it is not
    worth taking."""
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
        )
        return _Taken(refusal is None, refusal or "taken")

    rehearsal = rehearse(
        game, seat, perform, spell_name=None, leaves_hand=False,
        label=f"{entry['name']}'s special action",
        key=("special_action", seat, entry["permanent_id"], entry["kind"], victim_id),
        through_combat=True,
    )
    if rehearsal is None or not rehearsal.accepted or not rehearsal.changed:
        return None
    worth = rehearsal.swing - _graveyard_price(game, seat, entry)
    if worth <= 0.0:
        return None
    return SpecialActionChoice(
        permanent_id=entry["permanent_id"], kind=entry["kind"], name=entry["name"],
        sacrificed_id=victim_id if isinstance(victim_id, int) else None,
        worth=worth,
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
    priced as a toll prices one (``ai_prompts._toll_loss_price``) — except a
    card its owner could still cast from there (flashback, CR 702.34a), which
    that order calls a spell the seat still holds and which is priced as one:
    a card in hand (``ai_rehearsal.CARD_WORTH``).
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
    )


__all__ = [
    "SpecialActionChoice",
    "WEIGHED_OFFERS",
    "choose_special_action",
    "special_action_before_combat",
    "take_chosen_special_action",
]
