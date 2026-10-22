"""The auto-tap: which permanents a seat taps to pay for one action, drawn up
and carried out **by the server**.

A card glows in a hand when its seat *could* pay for it — the pool plus what a
tap would add (``state_view._card_castable_now`` asking
``engine.board_payment.board_can_pay``). A click on it sends the cast, the
engine spends the **pool** (CR 601.2h; producing the mana is the player's own
prior action), and a pool that cannot pay is refused "insufficient mana". The
browser then offers to do the tapping — and it kept its own planner for that
(``computeAutoTapPlan`` in ``app.js``): lands only, one mana a land, the colour
read off the printed ``produced_mana`` summary, the printed mana cost. Four
second opinions about questions the engine answers. Measured on the tree where
the highlight first counted a Sol Ring, over ten boards and 119 costs: of
**194** (board, card) pairs the state called castable, the dialog's own plan
paid for **92** — 77 said "insufficient mana" with the button disabled (a Sol
Ring, a Llanowar Elves, a Birds of Paradise, a Mana Flare's second mana) and
25 fired taps that did not pay (a painland asked for its colour through a
route that carries no ability and so made {C}; a City of Brass whose trigger
was on the stack when the cast arrived).

**So the plan lives here and the client renders it.** Two entry points, one
body:

* ``pay_from_board`` — called by an action handler whose request carries
  ``auto_tap``, at the point where every gate of its own has passed and the
  engine is about to be asked. It learns what the engine would charge, plans
  the taps, and makes them; the handler then announces as it always did.
* ``recording_taps`` — the preview (``actions.preview_payment``) runs that
  same handler on a scratch copy inside this block and reports what was
  tapped and whether the action then went through. The dialog's promise is
  therefore not a prediction: it is what happened on a copy of this table.

**What the action costs is the engine's answer, taken by asking it.** The
total a cast pays is settled deep in ``cast_from_hand`` — taxes scoped to what
the spell targets, a commander's, a kicker's symbols, a buyback's reduction,
the split of an X — and a second assembly of it here would be the planner the
browser just lost. Instead the announcement is rehearsed on a scratch copy
(``ai_rehearsal.scratch_copy``, the copy the policy's own rehearsals take)
whose ``_pay_mana_cost`` is wrapped to note each payment it could not make:
the engine's own ``required`` and ``PaymentPurpose``, at CR 601.2f's moment.
Every mana payment a cast or an activation makes goes through that one
method, and the census test fails the day one does not.

**The plan is the AI's** (``ai_payment._PaymentPlanner``): the exact matching
(``mana_payment.plan_payment``) over what each land's tap makes through the
tap seam (``board_payment.land_tap_yields``) and every non-land source whose
whole cost is {T}, with the colour to ask each for. One planner and two
payers, so a board the AI seat taps correctly is one a person's auto-tap
does. **Never a source that is sacrificed**: the AI weighs giving up a Black
Lotus and a button labelled "Auto-Tap" does not make that choice for a
person, which is also where the highlight draws its line.

**And the taps are the engine's own** (``ai_payment.tap_planned_lands``): a
land through the tap seam with the ability that makes the planned colour, a
Llanowar Elves through ``activate_permanent_ability`` — a mana ability, which
resolves inline (CR 605.3b). Nothing here writes to a mana pool.

Tapped *before* the announcement rather than inside it, which is the order
every payment in this app has always had (the AI's included). CR 601.2g puts
mana abilities inside the cast, so a trigger a tap sets off (City of Brass)
is on the stack under the spell here where the rule would put it above; the
web's own "stack must be empty" gate has already passed by then, which is
what refused the cast when the browser sent the taps first.
"""

from __future__ import annotations

import random
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace

from engine.ai_payment import _PaymentPlanner, _paying_for, tap_planned_lands
from engine.ai_rehearsal import mid_resolution, scratch_copy
from engine.models import Permanent
from engine.restricted_mana import CAST

#: The action kinds whose handler pays mana and reads ``auto_tap``.
PAYING_ACTIONS: frozenset[str] = frozenset(
    {"cast", "activate", "activate_hand", "activate_emblem"}
)

#: Where a preview collects what ``pay_from_board`` did on its copy.
_TAPS: ContextVar["dict | None"] = ContextVar("payment_plan_taps", default=None)


@contextmanager
def recording_taps():
    """Run a block, collecting what ``pay_from_board`` does inside it:
    ``taps``, a descriptor of every permanent it tapped, and ``cost``, the
    mana the engine asked the pool for (the symbol dict the payment itself
    was handed — taxes, reductions, a kicker and an announced X included), or
    None where the pool was never short."""
    record: dict = {"taps": [], "cost": None}
    token = _TAPS.set(record)
    try:
        yield record
    finally:
        _TAPS.reset(token)


def trial_copy(game):
    """A copy of *game* an announcement can be carried out on with nothing
    reaching the original — the same seats interactive, so what would stop
    for a person on the table stops on the copy."""
    trial = scratch_copy(game)
    trial.interactive_seats = set(game.interactive_seats)
    return trial


def unpaid_costs(game, announce):
    """``(result, asked)``: what *announce* returns on a scratch copy of
    *game*, and every mana payment it asked the pool for and was refused —
    ``(required, purpose)`` pairs, in the order the engine tried them (an X
    that may be split among colours is tried split by split)."""
    trial = trial_copy(game)
    asked: list[tuple[dict, object]] = []
    pay = trial._pay_mana_cost

    def recording(player, required, *, purpose=None):
        paid = pay(player, required, purpose=purpose)
        if not paid:
            asked.append((dict(required), purpose))
        return paid

    trial._pay_mana_cost = recording
    # A copy must not spend the real game's randomness (the policy's own
    # rehearsals make the same save and restore).
    sequence = random.getstate()
    try:
        result = announce(trial)
    finally:
        random.setstate(sequence)
    return result, asked


def planned_taps(game, seat: int, required: dict, purpose):
    """``(slots, colours)`` in tap order for a payment of *required*, or None
    when what *seat* could tap does not pay it. Read-only."""
    player = game.players[seat]
    if purpose is not None and purpose.kind == CAST:
        with _paying_for(purpose.card):
            planner = _PaymentPlanner(game, player)
    else:
        source = getattr(purpose, "source", None)
        if isinstance(source, Permanent):
            # The purpose was noted on the copy; the plan is drawn on the game.
            source = game.permanent_by_id(source.permanent_id)
        planner = _PaymentPlanner(game, player, paying_for=source)
    # A person's auto-tap never gives a permanent up (see the module's note).
    planner.sacrificed = []
    found = planner.plan(required)
    if not found or not found[0]:
        return None
    return _sparing(planner, required, found)


def _sparing(planner, required: dict, found):
    """*found* without any source the payment does not need.

    The planner reaches for every land before the first non-land source and
    stops when the cost is covered, so a source that makes two can arrive
    after the lands had nearly paid: {3} over two Forests and a Sol Ring was
    all three tapped and a {G} left floating. Each planned source is tried
    without — a creature or an artifact before a land, since a land costs
    nothing to tap — and dropped where the rest still pay.
    """
    planned = set(found[0])
    kept = [source for source in planner.sources if source.slot in planned]
    for candidate in sorted(kept, key=lambda source: -source.rank):
        rest = [source for source in kept if source is not candidate]
        again = planner._plan_with(rest, required)
        if again is not None and again[0]:
            kept, found = rest, again
    return found


def _describe(game, seat: int, slots, colours) -> list[dict]:
    """The plan as the client is shown it: each permanent by its stable id,
    with the colour it will be asked for."""
    described = []
    for slot, colour in zip(slots, colours):
        permanent = game.permanent_at(seat, slot)
        if permanent is None:
            continue
        described.append({
            "id": permanent.permanent_id,
            "name": permanent.card.name,
            "mana_color": colour,
            "land": bool(permanent.has_type("land")),
        })
    return described


def pay_from_board(game, seat: int, announce) -> None:
    """Tap what *seat*'s board must for *announce* to be paid — or nothing.

    *announce* takes a game and makes the engine call the handler is about to
    make (a cast, an activation); it is run once on a scratch copy to learn
    what the pool is short of. Nothing is tapped unless a whole plan exists:
    a pool that already pays, a refusal that is not about mana, and a cost no
    tapping covers each leave the board as it was, and the handler's own call
    then says what the engine says.
    """
    if not game.enforce_mana_costs or mid_resolution(game):
        return
    result, asked = unpaid_costs(game, announce)
    if result.supported or not asked:
        return
    sink = _TAPS.get()
    if sink is not None:
        sink["cost"] = dict(asked[0][0])
    for required, purpose in asked:
        found = planned_taps(game, seat, required, purpose)
        if found is not None:
            break
    else:
        return
    slots, colours = found
    taps = _describe(game, seat, slots, colours)
    tap_planned_lands(
        game, seat,
        SimpleNamespace(land_tap_indices=tuple(slots), land_tap_colors=tuple(colours)),
    )
    if sink is not None:
        sink["cost"] = dict(required)
        sink["taps"].extend(taps)


__all__ = [
    "PAYING_ACTIONS", "pay_from_board", "planned_taps", "recording_taps",
    "trial_copy", "unpaid_costs",
]
