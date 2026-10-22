"""Counter **removal** (CR 122.1), and counters moved off one object onto
another.

"Remove a counter from this creature", "remove all counters from …", "remove
any number of counters", loyalty taken off each planeswalker, every rust
counter off every permanent (Corrosion), and counters moved (CR 122.5): one
from the source onto a target (Afiya Grove), every one onto the source (Spike
Cannibal). A removal asks *which
kind and whether the number is known yet*, where a placement asks *which
object and how many* — the boundary the lowering side split at, and the
handler twin of ``engine/grammar/lowering/counter_removal.py``.

Gathered at the 2,000-line cap's split round from ``board_misc.py``, which
held all but one of them, and ``pump.py`` (Corrosion's sweep).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..oracle_types import COUNTERS_REMOVED
from ..exiled_records import source_object
from ..named_counters import counters_on, remove_counters
from ._amounts import resolve_amount
from ._targets import frozen_that_player_seat, resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("remove_loyalty_from_each_planeswalker")
def remove_loyalty_from_each_planeswalker(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Remove two loyalty counters from each planeswalker." (Pestilent Haze's
    second mode.) Loyalty is its counters (CR 306.5c); the walkers this
    empties are collected by the state-based sweep (CR 704.5i) after the
    spell finishes, not here."""
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    touched = 0
    for permanent in game.all_permanents():
        if not permanent.has_type("planeswalker"):
            continue
        current = int(permanent.metadata.get("loyalty_counters", 0))
        permanent.metadata["loyalty_counters"] = max(0, current - amount)
        touched += 1
        game.log.append(
            f"{context.card.name}: {permanent.card.name} loses {amount} loyalty "
            f"({permanent.metadata['loyalty_counters']} left)"
        )
    if not touched:
        game.log.append(f"{context.card.name}: no planeswalkers to strip")
    return True, "resolved"


@effect_handler("remove_counter_from_self")
def remove_counter_from_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Armageddon Clock: "Remove a doom counter from this artifact."

    The counter's name is payload, matching the accumulation side
    (phases/upkeep_effects.py), so the pair is one template rather than a card.
    Removing from zero is a no-op, not a negative count.

    The source may be a card in **exile** rather than a permanent — All
    Hallow's Eve's upkeep trigger takes a scream counter off a card in a zone
    with no objects in it. ``exiled_records.source_object`` is the one reader
    that answers for both, and it answers with something carrying ``.card`` and
    ``.metadata``, which is all this function ever needed. The gate on the
    optional spelling of this same removal (``offers._action_is_takeable``)
    reads it too, so "is there a counter to remove" and "remove the counter"
    cannot disagree about where the counters are.
    """
    permanent = source_object(context)
    if permanent is None:
        return True, "resolved"
    counter = str(instruction.payload.get("counter", "doom"))
    # Through the one counter reader, not this file's own spelling of the key.
    # ``counters_on`` asks ``pt.pt_counter_key``, which is where a counter with
    # rules meaning is recorded (CR 122.1a) — reading ``"<kind>_counters"``
    # here would answer zero for exactly those kinds, silently, because a
    # missing key is a legal zero.
    current = counters_on(permanent, counter)
    if current <= 0:
        # The record "if you can't" reads (Cocoon): removing from zero is a
        # no-op, and it is also the removal *not happening*.
        context.results["removed_counter"] = False
        game.log.append(f"{permanent.card.name} has no {counter} counter to remove")
        return True, "resolved"
    context.results["removed_counter"] = True
    # Through the one removal seam (`named_counters.remove_counters`), which is
    # also what records that this was the *last* counter of its kind — Divine
    # Intervention's trigger reads that record from the state-based sweep.
    left = remove_counters(permanent, counter)
    game.log.append(
        f"Removed a {counter} counter from {permanent.card.name} "
        f"({left} left)"
    )
    return True, "resolved"


@effect_handler("move_counter_from_self")
def move_counter_from_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Move a +1/+1 counter from this enchantment onto target creature."
    (Afiya Grove.)

    **CR 122.5 makes this one action**, and that is the whole reason it is one
    handler rather than a ``sequence`` of the removal and the placement beside
    it: with no counter on the source the move does not happen at all, where
    two composed steps would put a counter on the target anyway — an Afiya
    Grove that never runs dry.

    The order is the rule too. The counter comes off first, so the number
    placed is the number actually taken; a source holding fewer than the
    sentence names gives up what it has and the target receives exactly that.

    Reads and writes through the shared counter seams
    (``named_counters.counters_on`` / ``remove_counters`` and
    ``Game.place_pt_counters``), so a P/T counter brings its layer 7c
    contribution with it in both directions (CR 122.1a) and the last-counter
    record every state trigger reads is written where it always is.
    """
    source = context.source_permanent
    if source is None:
        game.log.append(f"{context.card.name}: no permanent to move a counter from")
        return True, "resolved"
    counter = str(instruction.payload.get("counter", "+1/+1"))
    wanted = int(instruction.payload.get("count", 1) or 1)
    held = counters_on(source, counter)
    if held <= 0:
        # CR 122.5: nothing to move means nothing happens — to *either* end.
        game.log.append(
            f"{source.card.name} has no {counter} counter to move"
        )
        return True, "resolved"
    moving = min(held, wanted)
    # The printed noun phrase, through the one reader the picker enumerated
    # with — Reality Ripple's lesson: a handler that pins a type the payload
    # does not say declines targets the picker legitimately offered.
    from ..subject_filters import subject_matches

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    creature = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described,
            observer=game.players.index(context.caster), source=source,
        ),
    )
    if creature is None:
        # The destination has left (CR 608.2b). The counter stays where it is:
        # a move with nowhere to land is not a removal.
        game.log.append(f"{context.card.name}: nothing left to move a counter onto")
        return True, "no target"
    remove_counters(source, counter, moving)
    game.place_pt_counters(creature, counter, moving)
    game.log.append(
        f"Moved {moving} {counter} counter(s) from {source.card.name} "
        f"onto {creature.card.name}"
    )
    return True, "resolved"


@effect_handler("move_all_counters_to_self")
def move_all_counters_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When this creature enters, move all +1/+1 counters from all creatures
    onto it." (Spike Cannibal.)

    :func:`move_counter_from_self` read from the other end — the destination is
    the ability's own source and the sources are a *described* set, so nothing
    is chosen and nothing is targeted and the board is read as the effect
    resolves (CR 611.2c).

    **CR 122.5 makes it one action**, which is why it is one handler rather than
    a counter sweep composed with a placement: the number placed is exactly the
    number the board gave up, and an emptied board places nothing at all. The
    same reason ``move_counter_from_self`` is one handler, over a set.

    The source is skipped rather than counted. Moving a counter from a permanent
    onto itself does nothing (CR 122.5 — it is one object), and the Spike is a
    creature the phrase names: taking its counters off and putting the same
    number back is the same answer with a state-trigger event in the middle that
    never happened.

    Reads and writes through the shared counter seams
    (``named_counters.counters_on`` / ``remove_counters`` and
    ``Game.place_pt_counters``), so a P/T counter brings its layer 7c
    contribution with it in both directions (CR 122.1a).
    """
    from ..subject_filters import subject_matches

    destination = context.source_permanent
    if destination is None or not game.is_on_battlefield(destination):
        game.log.append(f"{context.card.name}: nothing to move the counters onto")
        return True, "resolved"
    counter = str(instruction.payload.get("counter", "+1/+1"))
    described = dict(instruction.payload.get("filter") or {})
    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )
    taken = 0
    for perm in game.all_permanents():
        if perm is destination:
            continue
        if not subject_matches(
            game, perm, described, observer=observer, source=destination
        ):
            continue
        held = counters_on(perm, counter)
        if held <= 0:
            continue
        remove_counters(perm, counter, held)
        taken += held
    if taken <= 0:
        game.log.append(f"{context.card.name}: no {counter} counters to move")
        return True, "resolved"
    game.place_pt_counters(destination, counter, taken)
    game.log.append(
        f"Moved {taken} {counter} counter(s) onto {destination.card.name}"
    )
    return True, "resolved"


@effect_handler("remove_all_counters_from_bound")
def remove_all_counters_from_bound(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When this creature leaves the battlefield or becomes untapped, remove
    all -1/-1 counters from the creature." (Giant Oyster.)

    :func:`remove_all_counters_from_self`'s bound-object twin, and its own kind
    for the reason ``destroy_bound_permanent`` is one: the object is the one the
    *creating* ability bound (CR 603.7c), carried by id in the delayed trigger's
    context, and the self-reading handler would empty the ability's own source
    instead — the Oyster rather than the creature it locked down.

    Through the same one removal seam (``named_counters.remove_counters``), so
    the P/T the counters were carrying (CR 122.1a, layer 7d) comes off with them
    and the emptied-kind record every state trigger reads is written.

    A creature already gone has no counters to take off, which is CR 608.2b
    doing as much as it can.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("bound_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    counter = str(instruction.payload.get("counter", ""))
    held = counters_on(victim, counter)
    if held <= 0:
        game.log.append(
            f"{victim.card.name} has no {counter} counters to remove"
        )
        return True, "resolved"
    remove_counters(victim, counter, held)
    game.log.append(
        f"Removed all {held} {counter} counters from {victim.card.name} "
        f"({context.card.name})"
    )
    return True, "resolved"


@effect_handler("remove_counters_from_bound")
def remove_counters_from_bound(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…remove a +1/+1 counter from **that creature** at the beginning of the
    next cleanup step." (Bounty of the Hunt.)

    :func:`remove_all_counters_from_bound`'s counted twin, and its own kind for
    that pair's stated reason one way round: "all" is a number nobody knows
    until the permanent is looked at, and a printed count lowered onto that
    handler would empty a permanent the card says to decrement by one.

    Through the same one removal seam (``named_counters.remove_counters``), so
    the P/T the counters were carrying (CR 122.1a, layer 7d) comes off with them
    and the emptied-kind record every state trigger reads is written.

    Takes as many as are there when fewer remain, which is CR 608.2b doing as
    much as it can — the creature may have lost counters to something else since
    the ability was created, and a creature already gone has none to take off.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("bound_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    counter = str(instruction.payload.get("counter", ""))
    wanted = max(0, int(instruction.payload.get("amount", 1)))
    taking = min(wanted, counters_on(victim, counter))
    if taking <= 0:
        game.log.append(
            f"{victim.card.name} has no {counter} counters to remove"
        )
        return True, "resolved"
    remove_counters(victim, counter, taking)
    game.log.append(
        f"Removed {taking} {counter} counter(s) from {victim.card.name} "
        f"({context.card.name})"
    )
    return True, "resolved"


@effect_handler("remove_all_counters_from_event_subject")
def remove_all_counters_from_event_subject(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever a creature has four or more fuse counters on it, **remove all
    fuse counters from it** and destroy it." (Bomb Squad.)

    :func:`remove_all_counters_from_bound`'s twin one record over: the object
    is the one the *trigger's own event* was about, carried by id in the
    trigger's context, where that handler reads the object a delayed ability's
    creator bound. Its own kind for the reason that one is — the self-reading
    removal would empty the ability's source, which here is Bomb Squad rather
    than the creature it lit.

    Through the one removal seam (``named_counters.remove_counters``), so a P/T
    counter's layer-7d bonus comes off with it and the emptied-kind record the
    state sweep reads is written.

    A creature already gone has no counters to take off (CR 122.2: they ceased
    to exist with the zone change), which is CR 608.2c doing as much as it can
    — the second of two Bomb Squads' triggers resolves into exactly this.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("event_subject_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the permanent it named is gone")
        return True, "resolved"
    counter = str(instruction.payload.get("counter", ""))
    held = counters_on(victim, counter)
    if held <= 0:
        game.log.append(
            f"{victim.card.name} has no {counter} counters to remove"
        )
        return True, "resolved"
    remove_counters(victim, counter, held)
    game.log.append(
        f"Removed all {held} {counter} counters from {victim.card.name} "
        f"({context.card.name})"
    )
    return True, "resolved"


@effect_handler("remove_all_counters_from_self")
def remove_all_counters_from_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Remove all tide counters from it." (Homarid, Tidal Influence.)

    The emptying twin of :func:`remove_counter_from_self`, and its own kind
    because "all" is a number nobody knows until the permanent is looked at.
    Through the same one removal seam (``named_counters.remove_counters``), so
    the *last counter removed* record every state trigger reads is written here
    too — a hand-rolled ``metadata[key] = 0`` would empty the store and tell
    nobody.

    Removing from zero is a no-op, not a failure: CR 608.2b does as much as
    possible, and the rest of the resolution still runs.
    """
    permanent = source_object(context)
    if permanent is None:
        return True, "resolved"
    counter = str(instruction.payload.get("counter", ""))
    held = counters_on(permanent, counter)
    if held <= 0:
        context.results["removed_counter"] = False
        # Zero is a real answer, and it has to be *written*: "add {C} for
        # each charge counter removed this way" over an empty artifact adds
        # nothing, and a missing record and a recorded zero must not be told
        # apart by the sentence behind this one.
        context.results[COUNTERS_REMOVED] = 0
        game.log.append(f"{permanent.card.name} has no {counter} counters to remove")
        return True, "resolved"
    context.results["removed_counter"] = True
    # "…remove all charge counters from it. **Add {C} for each charge counter
    # removed this way.**" (Ventifact Bottle.) How many came off, for the
    # sentence behind this one: by the time it runs the counters are gone, so
    # counting the artifact would be the exact complement of what it asks.
    context.results[COUNTERS_REMOVED] = held
    remove_counters(permanent, counter, held)
    game.log.append(
        f"Removed all {held} {counter} counters from {permanent.card.name}"
    )
    return True, "resolved"


@effect_handler("remove_any_number_of_counters_from_self")
def remove_any_number_of_counters_from_self(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Tetravus: "Remove **any number of** +1/+1 counters from this creature."

    Its own handler rather than a count on the one above, because the number is
    not on the card: its controller picks it at resolution, bounded by what is
    actually there (CR 701.x — you cannot remove counters that are not on the
    permanent). The choice suspends the resolution, so the sentence after it —
    "create **that many** … tokens" — runs against the answer rather than
    against a number nobody has given yet.

    What is removed is recorded under ``trigger_count``, which is the key the
    token maker's "that many" already reads.
    """
    permanent = context.source_permanent
    if permanent is None:
        return True, "resolved"
    counter = str(instruction.payload.get("counter", "+1/+1"))
    if counter != "+1/+1":
        # Only the +1/+1 store has a counted remover; a named counter would be
        # taken off a record this handler does not reach.
        game.log.append(
            f"{permanent.card.name}: no counted remover for {counter} counters"
        )
        return True, "resolved"
    available = int(permanent.metadata.get("plus_counters", 0))
    seat = game.controller_index_of(permanent)
    if seat is None or available <= 0:
        context.results["trigger_count"] = 0
        return True, "resolved"
    game.arm_pending_choice(
        "number_choice", seat,
        card_name=permanent.card.name, permanent=permanent,
        minimum=0, maximum=available,
        # The "may" in front of this sentence has already asked whether to do it
        # at all, so a seat that got here said yes — and the default that keeps
        # faith with that answer is "all of them", not "none", which would make
        # accepting the offer do nothing.
        default_number=available,
        remove_counters=True, results=context.results,
    )
    return True, "resolved"


@effect_handler("remove_all_counters_from_matching")
def remove_all_counters_from_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When this enchantment leaves the battlefield, remove all rust counters
    from **all permanents**." (Corrosion.)

    The sweep twin of ``counters.add_counter_to_each_matching`` and written against
    it: the set is a *description*, nothing is targeted and nothing is chosen,
    and the board is read as the effect resolves (CR 611.2c). Which is why the
    printed noun phrase travels as a filter the shared matcher tests rather than
    being baked into the kind's name.

    Empties rather than decrements: "all" is a number nobody knows until each
    permanent is looked at, which is the whole reason this is not the counted
    removal one function over.

    The source has usually left the battlefield by the time this resolves - the
    trigger is a leaves-the-battlefield one - so nothing here reads it.
    """
    from ..named_counters import counters_on, remove_counters
    from ..subject_filters import subject_matches

    kind = str(instruction.payload.get("counter", ""))
    filters = dict(instruction.payload.get("filter") or {})
    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )
    # "…remove all hourglass counters from permanents **that player**
    # controls." (Temporal Distortion.) The seat whose upkeep fired the
    # trigger, which only the resolution holding the trigger's context can
    # name — ``subject_matches`` refuses the word without it, so the sweep
    # removed nothing and every permanent a player had tapped stayed tapped
    # for the rest of the game.
    that_player = frozen_that_player_seat(game, context)
    cleared: list[str] = []
    for perm in game.all_permanents():
        if not subject_matches(
            game, perm, filters, observer=observer,
            source=context.source_permanent, that_player=that_player,
        ):
            continue
        held = counters_on(perm, kind)
        if held <= 0:
            continue
        remove_counters(perm, kind, held)
        cleared.append(perm.card.name)
    if cleared:
        game.log.append(
            f"{context.card.name} removed every {kind} counter from "
            + ", ".join(cleared)
        )
    else:
        game.log.append(f"{context.card.name}: no {kind} counters to remove")
    return True, "resolved"
