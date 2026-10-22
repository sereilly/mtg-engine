"""CR 603.8's state triggers: the latch, and the sweep that watches *other*
permanents.

    603.8. Some triggered abilities trigger when a game state … is true, rather
    than triggering when an event occurs. These abilities trigger as soon as the
    game state matches the condition. … A state-triggered ability doesn't
    trigger again until the ability has resolved, has been countered, or has
    otherwise left the stack. Then, if the object with the ability is still in
    the same zone and the game state still matches its trigger condition, the
    ability will trigger again.

A state has no fire site, so every one of these is announced from the
state-based sweep (``mixins/game_ending.check_state_based_actions``) — and a
sweep runs again and again over a board that has not changed, so each needs to
remember that it has already announced. That memory is the **latch**: a set of
keys on the source permanent, one per ability (or, below, one per ability and
watched permanent).

**What releases it.** The sweeps release a latch when the state stops matching,
which is the half that makes a state trigger fire once per crossing. The rule's
other half was missing: an ability that was **countered**, or left the stack any
other way without resolving, has not been dealt with — and with the state still
true the rule says it triggers again. Latched on the state alone, it never did:
counter Homarid's "remove all tide counters" and the Homarid sat at four
counters for the rest of the game; ten shipped cards behaved that way when this
module was written. So the latch key rides the stack object
(:data:`STATE_TRIGGER_LATCH` in its trigger context) and the two ways an
ability leaves the stack unresolved — ``Game.counter_stack_object`` and CR
608.2b's all-targets-illegal removal — hand the object to
:func:`release_latch`.

**What deliberately does not.** A *resolved* ability whose state is still true
should also trigger again by the letter of the rule. It does not here, and that
is a stated bound rather than an oversight: every state trigger in the pool
either ends its own state as it resolves (it removes the counters, or its
source leaves) or prints an intervening "if" that its own effect makes false
(the Opal and Veiled enchantments become creatures), so nothing printed can
observe the difference — and re-arming on resolution without also asking that
"if" at the sweep would announce the same do-nothing ability on every pass.
``tests/rules/test_state_trigger_latch.py`` holds both halves over the pool.

**The watched sweep.** "Whenever **a creature** has four or more fuse counters
on it, …" (Bomb Squad) is the first state trigger about a permanent other than
its source, and it lives here whole rather than as a sixth block in the
state-based sweep: the state is true *per watched permanent*, so the latch is
keyed by the permanent as well as the ability — two creatures over the line are
two triggers, and one of them leaving re-arms neither.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .oracle_types import EVENT_SUBJECT_LAST_KNOWN

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent


#: The trigger-context key a state trigger's stack object carries its latch
#: key under, so the object can release it if it leaves the stack unresolved.
STATE_TRIGGER_LATCH = "state_trigger_latch"

#: Where a permanent keeps the set of latch keys its abilities hold. The name
#: the sweeps in ``mixins/game_ending.py`` have always used.
_ANNOUNCED = "_state_trigger_announced"

#: The condition kind ``engine/trigger_conditions.py``'s table gives "whenever <noun
#: phrase> has N or more K counters on it".
WATCHED_COUNTER_THRESHOLD = "permanent_counters_reach_threshold"


def is_latched(permanent: "Permanent", key) -> bool:
    """Whether *permanent*'s ability *key* has announced and not been released."""
    return key in (permanent.metadata.get(_ANNOUNCED) or ())


def latch(permanent: "Permanent", key) -> None:
    permanent.metadata[_ANNOUNCED] = (
        set(permanent.metadata.get(_ANNOUNCED) or ()) | {key}
    )


def unlatch(permanent: "Permanent", key) -> None:
    held = permanent.metadata.get(_ANNOUNCED)
    if held and key in held:
        permanent.metadata[_ANNOUNCED] = set(held) - {key}


def release_latch(item) -> None:
    """*item* has left the stack **without resolving** (CR 603.8): its ability
    may trigger again.

    Called from the seams where that happens, never from a resolution. A stack
    object that is not a state trigger carries no key and this does nothing; a
    *copy* of one is not the ability having triggered (CR 707.10), so it holds
    no latch to give back — releasing on it would let the original's source
    announce a second instance while the first is still on the stack.
    """
    if item is None or getattr(item, "is_copy", False):
        return
    key = (getattr(item, "trigger_context", None) or {}).get(STATE_TRIGGER_LATCH)
    source = getattr(item, "source_permanent", None)
    if key is not None and source is not None:
        unlatch(source, key)


def announce_watched_counter_thresholds(game: "Game") -> bool:
    """Put "whenever <noun phrase> has N or more K counters on it" on the stack
    for every permanent that has crossed the line since the last sweep.

    Returns whether anything was announced.

    One trigger per (ability, watched permanent). The context freezes what the
    effect's "it" and "that creature" name: the id (CR 400.7 — an index is not
    an identity) and **the object itself**, because the sentence goes on using
    the creature after destroying it and CR 608.2h reads an object that has
    left as it last existed. Its controller's seat is stamped beside them for
    the readers of "that creature's controller" every subject event has
    (``_frozen_seats._EVENT_SUBJECT_CONTROLLERS``) — but Bomb Squad's own
    damage does not read it: the creature is still on the battlefield while
    the trigger waits, and "its controller" behind "that creature deals" is
    whoever that is as the damage is dealt.

    The observer for the noun phrase is the source's controller (CR 109.5), so
    "a creature **you control**" is narrowed by whoever controls the watcher.
    """
    from .named_counters import counters_on
    from .oracle import compile_card_oracle
    from .subject_filters import subject_matches

    events: list[dict] = []
    for source in list(game.all_permanents()):
        observer = game.controller_index_of(source)
        if observer is None:
            continue
        for trig in compile_card_oracle(source.effective_card).triggered_abilities:
            if trig.condition.kind != WATCHED_COUNTER_THRESHOLD:
                continue
            payload = trig.condition.payload
            kind = str(payload.get("counter_kind", ""))
            wanted = payload.get("counter_count")
            described = payload.get("countered_filter")
            # A row that arrives without its number or its noun phrase is
            # refused rather than defaulted: a threshold read as zero, or a
            # filter read as "everything", is a trigger on the whole board.
            if (
                trig.instruction is None
                or not isinstance(wanted, int)
                or wanted <= 0
                or not kind
                or not described
            ):
                continue
            over = {
                watched.permanent_id: watched
                for watched in game.all_permanents()
                if counters_on(watched, kind) >= wanted
                and subject_matches(
                    game, watched, described, observer=observer, source=source
                )
            }
            # CR 603.8: the ability may trigger again for a permanent once its
            # state has stopped matching — it dropped under the line, stopped
            # answering the noun phrase, or left (a permanent that comes back
            # is a new object with a new id, and was never latched).
            ability = (WATCHED_COUNTER_THRESHOLD, trig.source_line)
            for key in list(source.metadata.get(_ANNOUNCED) or ()):
                if (
                    isinstance(key, tuple)
                    and key[:2] == ability
                    and key[2] not in over
                ):
                    unlatch(source, key)
            for permanent_id, watched in over.items():
                key = (*ability, permanent_id)
                if is_latched(source, key):
                    continue
                latch(source, key)
                events.append({
                    "controller_index": observer,
                    "source_permanent": source,
                    "card": source.card,
                    "instruction": trig.instruction,
                    "effect_kind": trig.effect_kind,
                    "ability_text": trig.source_line,
                    "trigger_context": {
                        STATE_TRIGGER_LATCH: key,
                        "event_subject_permanent_id": permanent_id,
                        "event_subject_controller": game.controller_index_of(watched),
                        EVENT_SUBJECT_LAST_KNOWN: watched,
                    },
                })
    if events:
        game._enqueue_triggered_batch(events)
    return bool(events)


__all__ = [
    "STATE_TRIGGER_LATCH",
    "WATCHED_COUNTER_THRESHOLD",
    "announce_watched_counter_thresholds",
    "is_latched",
    "latch",
    "release_latch",
    "unlatch",
]
