"""CR 603.3b: a controller orders the triggered abilities they put on the
stack together.

    603.3b If multiple abilities have triggered since the last time a player
    received priority, the abilities are placed on the stack in a two-part
    process. First, each player, in APNAP order, puts each triggered ability
    they control with a trigger condition that isn't another ability
    triggering on the stack in any order they choose. … Second, each player,
    in APNAP order, puts all remaining triggered abilities they control on
    the stack in any order they choose.

This engine put a controller's simultaneous triggers on the stack in the order
its fire sites happened to collect them, and nobody was asked. On its own
upkeep Tangle Wire's tap resolved on top of its fade removal, so it always
tapped one more permanent than its controller might have chosen; two entry
triggers of one permanent resolved first-printed first.

**What "together" is.** Triggers go on the stack one push at a time
(``Game._stack_push``, the one place an object goes there), from fire sites
spread through the engine: a batch of one event, a permanent's own entry, a
death inside a sweep, an attack declaration, the upkeep step. So the question
is not asked at a fire site. A **window** is opened around each unit of the
game that sets off triggers before anybody can receive priority — one event's
batch, one resolution, one state-based sweep, one turn-based action, one
entry, the triggers a cast held back (``putting_triggers_on_stack``) — and the
push records every triggered object it puts on the stack while one is open.
Windows nest: an inner one joins the outer, and the outermost decides. That is
CR 603.3b's "since the last time a player received priority", cut at the
moments this engine can name; the window does not reach across a resolution
and the state-based check that follows it, which the rule would join.

**How it is asked: after the push, before anything resolves.** When the
outermost window closes, each seat that put two or more triggers on the stack
in it is offered ``order_triggers`` (one prompt per seat, APNAP order). Until
it is answered none of those objects may resolve — the prompt names them as
``_trigger_items`` and ``Game.announcement_choice_for`` reads that, which is
the hold every resolution loop already respects for an owed mode or target
(they have not finished being put on the stack). The answer permutes them among
the stack slots they already occupy, so nothing else on the stack moves. The
objects were pushed first because a push is where CR 603.3c-d choose each
one's mode and targets, and every prompt already armed there keeps working
unchanged; the rule's own order — each object's targets chosen as it is put
on — differs only in which question is on screen first.

**Between players, APNAP** (:func:`restore_apnap`). One batch was already
sorted active player first; a window holding several batches was not — two
creatures dying to one combat damage step announce two deaths, each a batch
with both players' Soul Nets, and the four went on A, B, A, B. Measured over
the seven seeded simulator sets: 23 moments with two players' triggers, one
interleaved (7ED). The window's objects are regrouped among their own slots
before anybody is asked, every seat's own order kept.

**Who is asked.** The registry's ``default_at_arm`` answers for every seat
nobody is asking, at the moment of arming, with **the order the fire sites
produced** — so an AI or headless game is untouched, and a seeded run
reproduces byte for byte. An AI that orders by value is a separate piece of
work (``engine/ai_*.py``).

**When asking is pointless.** Several instances of one ability of one source
(Soul Net watching two creatures die, Planar Void two cards) differ only in the
event each is about; and the same printed ability of two copies of one card,
set off by the same event and aimed at the same thing, cannot be told apart in
either order. Neither is asked (:func:`interchangeable`).

**The second part of the rule has no card.** No supported card in the pool has
a trigger condition that is another ability triggering (Psychic Battle's is a
player choosing targets; Sanctum of All's sentence makes an ability trigger an
additional time, which CR 603.2d counts and this engine counts in
``additional_triggers``). So there is one round, and
``tests/engine/test_trigger_order_census.py`` names the census that says so.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .game import Game

#: The ``pending_choices`` kind.
ORDER_TRIGGERS = "order_triggers"


def is_triggered_object(item) -> bool:
    """Whether *item* is a triggered ability as it is put on the stack.

    CR 113.3: an ability that is not activated. A copy is not put on the stack
    by triggering (CR 707.10), and a spell is not an ability at all.
    """
    return (
        item is not None
        and item.is_ability
        and not item.activated
        and not item.is_copy
    )


def _on_stack(game: "Game", item) -> bool:
    return any(entry is item for entry in game.stack)


def _targets(item) -> tuple:
    stack_target = item.target_stack_item
    return (
        item.target_player_index,
        item.target_permanent_id
        if not isinstance(item.target_permanent_id, list)
        else tuple(item.target_permanent_id),
        id(stack_target) if stack_target is not None else None,
    )


def interchangeable(items) -> bool:
    """Whether every order of *items* is the same game.

    Two shapes, both of one printed ability: instances from **one source**
    (CR 603.2c, a "whenever" that saw several events at once, or CR 603.2d's
    additional instances), and copies of **one card** each set off by the
    same event and aimed at the same thing. Anything else — two different
    abilities, one of them aimed elsewhere, or one about a different event of
    a different object — is a choice.
    """
    first = items[0]
    printed = (first.card.name, first.ability_text or "")
    if any((item.card.name, item.ability_text or "") != printed for item in items[1:]):
        return False
    if all(item.source_permanent is first.source_permanent for item in items[1:]):
        return True
    return all(
        _targets(item) == _targets(first)
        and (item.trigger_context or {}) == (first.trigger_context or {})
        for item in items[1:]
    )


def _live(game: "Game", collected) -> list:
    """*collected* still on the stack, each once, in the order pushed."""
    seen: list = []
    for item in collected:
        if not any(item is kept for kept in seen) and _on_stack(game, item):
            seen.append(item)
    return seen


def restore_apnap(game: "Game", collected) -> bool:
    """Put one window's triggers back in APNAP order between players.

    CR 603.3b: the active player puts theirs on the stack first, then each
    other player in turn order — so the active player's resolve last. One
    batch is already sorted that way (``_enqueue_triggered_batch``), but a
    window can hold several: two creatures dying to one combat damage step
    each announce their own death, and each announcement is a batch with both
    players' watchers in it, so the four Soul Net triggers went on AP, NAP,
    AP, NAP. Each seat's own triggers keep their order; only the seats are
    regrouped, among the slots the window's objects already occupy. True when
    anything moved.
    """
    live = _live(game, collected)
    if len({item.caster_index for item in live}) < 2:
        return False
    rank = {
        seat: place
        for place, seat in enumerate(game.apnap_seats(include_lost=True))
    }
    slots = sorted(
        index for index, entry in enumerate(game.stack)
        if any(entry is item for item in live)
    )
    current = [game.stack[slot] for slot in slots]
    wanted = sorted(
        current, key=lambda item: rank.get(item.caster_index, len(rank)),
    )
    if all(a is b for a, b in zip(current, wanted)):
        return False
    for slot, item in zip(slots, wanted):
        game.stack[slot] = item
    return True


def order_groups(game: "Game", collected) -> list[tuple[int, list]]:
    """``(seat, objects top first)`` for each seat with a choice to make.

    Over what is **still on the stack**: an object removed as it was put there
    (no legal target or mode, CR 603.3c-d) is not one anybody orders. Seats in
    APNAP order (CR 101.4), which is the order the rule has them choose in.
    """
    seen = _live(game, collected)
    by_seat: dict[int, list] = {}
    for item in seen:
        by_seat.setdefault(item.caster_index, []).append(item)
    positions = {id(entry): index for index, entry in enumerate(game.stack)}
    groups = []
    for seat in game.apnap_seats(by_seat, include_lost=True):
        items = by_seat.get(seat) or []
        if len(items) < 2 or interchangeable(items):
            continue
        items.sort(key=lambda item: -positions[id(item)])
        groups.append((seat, items))
    return groups


def trigger_label(item) -> dict:
    """What a prompt shows for one object: whose, and what it says."""
    source = item.source_permanent
    return {
        "card_name": item.card.name,
        "text": item.ability_text or "",
        "source_id": getattr(source, "permanent_id", None),
    }


def offer_trigger_order(game: "Game", collected) -> None:
    """Arm ``order_triggers`` for each seat that put two or more
    distinguishable triggers on the stack together.

    ``_stack_item`` is set to None on purpose: putting triggers on the stack
    happens *after* a resolution (CR 603.3), so the prompt holds no resolving
    object open. The objects it orders are held instead, through
    ``_trigger_items``. A draw in progress does not wait for it either
    (``DRAW_OF``) — ordering triggers is not a step of any draw.
    """
    from .replacement_choices import DRAW_OF

    for seat, items in order_groups(game, collected):
        game.arm_pending_choice(
            "order_triggers", seat,
            triggers=[trigger_label(item) for item in items],
            _trigger_items=tuple(items),
            _stack_item=None,
            **{DRAW_OF: None},
        )


def live_trigger_indices(game: "Game", choice) -> list[int]:
    """Which of the prompt's objects are still on the stack, as indices into
    its offered list (the order it was offered in: top first)."""
    return [
        index
        for index, item in enumerate(choice.data.get("_trigger_items") or ())
        if _on_stack(game, item)
    ]


def order_is_open(game: "Game", choice) -> bool:
    """A choice is owed while two of its objects are still there to order.

    A choice that records no objects at all is taken at its word: there is
    nothing known to have left."""
    if choice.data.get("_trigger_items") is None:
        return True
    return len(live_trigger_indices(game, choice)) >= 2


def apply_trigger_order(game: "Game", choice, order) -> bool:
    """Put the prompt's objects in *order* — indices into the offered list,
    **the first resolving first** — among the stack slots they occupy.

    Refused unless *order* is a permutation of the offered indices, or of the
    ones still on the stack (what the prompt shows once one has left): a short
    or repeated list names an order of some other set of objects.
    """
    items = list(choice.data.get("_trigger_items") or ())
    try:
        chosen = [int(index) for index in order]
    except (TypeError, ValueError):
        return False
    live = [index for index, item in enumerate(items) if _on_stack(game, item)]
    if sorted(chosen) == list(range(len(items))):
        chosen = [index for index in chosen if index in live]
    elif sorted(chosen) != live:
        return False
    slots = [
        index for index, entry in enumerate(game.stack)
        if any(entry is item for item in items)
    ]
    top_first = [items[index] for index in chosen]
    for slot, item in zip(slots, reversed(top_first)):
        game.stack[slot] = item
    return True
