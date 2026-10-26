"""Effects a resolving ability creates "for as long as this <permanent>
remains tapped" (CR 611.2b), recorded on that permanent.

"{2}, {T}: Target creature you control gets +2/-2 for as long as this artifact
remains tapped." (Ashnod's Battle Gear.) "{2}{W}, {T}: Target Soldier creature
gets +2/+2 and has vigilance for as long as this creature remains tapped."
(Pearlspear Courier.) An effect that ends on a **condition** rather than at a
step has no moment anything could schedule its removal for, so nothing is
written onto the affected permanent: each effect is an entry on the *source*,
and the two recomputes that own the layers it touches rebuild its contribution
from the entry on every pass — the P/T half in layer 7c
(``mixins/dynamic_creatures._refresh_linked_tapped_pumps``), the keyword half
in layer 6 (``mixins/lords._recalculate_lord_buffs``, the pass that owns the
derived-grant channel's clear and rebuild).

**One record for both halves**, so the P/T and the keyword a single sentence
grants cannot end at different moments: a Courier's "+2/+2 and has vigilance"
is two entries on one list, and the list is dropped whole.

**Ended, not skipped.** CR 611.2b: the duration ends when the source stops
being a tapped permanent on the battlefield, and "it doesn't start and
immediately stop again" — an entry left in place while the source is untapped
would come back to life the next time it tapped for any reason (a Courier
attacking, an Icy Manipulator tapping an artifact), which is an effect nobody
created. So :func:`end_effects_while_tapped` drops the record at the one place
a permanent becomes untapped (``Game.become_untapped``) and where it phases out
(CR 702.26f); a permanent that leaves the battlefield takes its metadata with
it and comes back a new object (CR 400.7). This is the arrangement the other
two records the same duration governs already have — the untap lock
(``handlers/tapping.end_untap_lock``) and the delayed abilities
(``delayed_triggers.end_source_tapped_delayed_triggers``).

**A duration that never starts does nothing** (CR 611.2b's first sentence):
:func:`record_while_tapped` refuses an entry when the source is not a tapped
permanent on the battlefield as the effect would begin — and when it untapped
at any moment between activation and resolution, "even if it becomes tapped
again right away" (Old Man of the Sea, 2009-10-01, the same duration on a
control change). The untap is the only moment that can be seen, so
:func:`break_pending_durations` marks the source's abilities still on the stack
then (``SOURCE_UNTAPPED`` on ``StackItem.choices``) and the resolution reads
the mark.

Several entries rather than one: each resolution creates its own effect, so two
activations that both resolve while the source stays tapped (untapped in
response and activated again) are two effects, and both apply.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .continuous import next_timestamp

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent

#: The metadata key on the **source** holding its entries, oldest first. Each
#: entry names the one permanent it is on (``target_id`` — a sweep such as
#: Thran Weaponry's records one entry per creature, because CR 611.2c fixes
#: the set as the effect begins) and what it gives: a P/T delta
#: (``power``/``toughness``) and/or layer-6 words (``keywords``), stamped with
#: the moment the effect began (``timestamp``, CR 613.7b).
EFFECTS_WHILE_TAPPED = "effects_while_tapped"

#: The ``StackItem.choices`` / ``OracleExecutionContext.choices`` key (declared
#: in ``game_types.CHOICE_KEYS``) saying the object's source has become untapped
#: since the object was put on the stack.
SOURCE_UNTAPPED = "source_untapped"


def break_pending_durations(game: "Game", permanent: "Permanent") -> int:
    """Mark every ability *permanent* has on the stack: its source untapped.

    Called from ``Game.become_untapped``, the one place a permanent becomes
    untapped, so an ability activated by tapping its source and resolving after
    an untap (and perhaps a re-tap) begins no "for as long as this remains
    tapped" effect. Every ability of the source is marked, because only the
    readers of :data:`SOURCE_UNTAPPED` ask — the mark means nothing to the
    rest. Returns how many were marked.
    """
    marked = 0
    for item in game.stack:
        if item.source_permanent is permanent:
            item.choices[SOURCE_UNTAPPED] = True
            marked += 1
    return marked


def record_while_tapped(
    game: "Game", source: "Permanent | None", entry: dict, *,
    choices: "dict | None" = None,
) -> bool:
    """Begin one effect *source* holds for as long as it remains tapped.

    Returns False, recording nothing, when the duration never starts: *source*
    is not a tapped permanent on the battlefield as the effect would begin, or
    the resolving object's *choices* say it untapped since the object was put
    on the stack (CR 611.2b).
    """
    if source is None or not game.is_on_battlefield(source) or not source.tapped:
        return False
    if (choices or {}).get(SOURCE_UNTAPPED):
        return False
    if not isinstance(entry.get("target_id"), int):
        raise ValueError(
            f"an effect while tapped names the one permanent it is on: {entry!r}"
        )
    stamped = dict(entry)
    stamped["timestamp"] = next_timestamp()
    source.metadata.setdefault(EFFECTS_WHILE_TAPPED, []).append(stamped)
    return True


def effects_while_tapped(source: "Permanent") -> tuple[dict, ...]:
    """The effects *source* is holding right now: none unless it is tapped.

    The tapped test is belt and braces — the record is dropped when the source
    untaps — so a reader can never contribute an entry its source stopped
    holding.
    """
    if not source.tapped:
        return ()
    return tuple(source.metadata.get(EFFECTS_WHILE_TAPPED) or ())


def end_effects_while_tapped(permanent: "Permanent") -> int:
    """End every effect *permanent* holds under this duration; how many went."""
    return len(permanent.metadata.pop(EFFECTS_WHILE_TAPPED, None) or ())


__all__ = [
    "EFFECTS_WHILE_TAPPED",
    "SOURCE_UNTAPPED",
    "break_pending_durations",
    "effects_while_tapped",
    "end_effects_while_tapped",
    "record_while_tapped",
]
