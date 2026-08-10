"""CR 613 layer 2 — control-changing effects, recorded rather than performed.

Control was the last characteristic this engine *stored by doing*: "gain
control of target artifact" moved the permanent between ``player.battlefield``
lists and wrote the previous controller onto the thief, so ending the effect
meant reading that number back and moving the permanent again. That is
remember-and-undo, the same shape the single stamped land-type string had
before ``engine/land_types.py``, and it fails the same way — **two effects on
one permanent cannot both be recorded, and ending one cannot know about the
other.**

The failure is not hypothetical. With Steal Artifact and then Aladdin on the
same artifact, destroying the Aura first and losing Aladdin second handed the
artifact to a player that nothing on the board gave control to: Aladdin's
remembered "previous controller" was the Aura's controller, and the Aura was
already gone.

So a control change is a **contribution** now, exactly like a land-type change:

* ``change_control(permanent, seat, source=…)`` records one, stamped with
  CR 613.7's timestamp.
* ``end_control_change(permanent, source=…)`` drops that one and nothing else.
* ``control_changes(permanent)`` is what ``engine/layer_bridge.py`` turns into
  layer-2 :class:`~engine.continuous.ContinuousEffect` objects.

Ending an effect is then *the absence of a contribution*: whatever is left
applies, newest timestamp last, and if nothing is left the permanent reverts to
its base controller. Nobody has to remember a previous value, and nobody can
get it wrong.

``base_controller_index`` is the value layer 2 starts from — CR 613.1's
copiable characteristics, which for control means "whoever put this permanent
onto the battlefield". It is written once, when the permanent enters, and is
*not* touched by a control change; that is what makes an ended effect revert to
the right seat rather than to whichever seat happened to hold it last.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .continuous import next_timestamp

if TYPE_CHECKING:
    from .models import Permanent

# Contributions live on the *controlled* permanent, keyed by the source that
# recorded them, so a source ending its effect drops exactly its own.
CONTROL_EFFECTS = "control_effects"

# The controller before any layer-2 effect applies.
BASE_CONTROLLER = "base_controller_index"


def set_base_controller(permanent: "Permanent", seat: int) -> None:
    """Record the seat a permanent enters the battlefield under (CR 613.1)."""
    permanent.metadata[BASE_CONTROLLER] = int(seat)


def base_controller(permanent: "Permanent") -> int | None:
    """The seat layer 2 starts from, or None if this permanent never recorded
    one (a board built by hand in a test, or a permanent that predates the
    field). Callers fall back to where the permanent currently sits."""
    value = permanent.metadata.get(BASE_CONTROLLER)
    return value if isinstance(value, int) else None


def change_control(permanent: "Permanent", seat: int, *, source: "Permanent") -> None:
    """Record that *source* gives control of *permanent* to *seat*.

    One contribution per source: re-recording replaces the previous one and
    takes a fresh timestamp, which is what Ghazbán Ogre needs when the life
    lead moves from one player to another on a later upkeep.
    """
    kept = [entry for entry in control_changes(permanent) if entry["source"] is not source]
    kept.append({
        "source": source,
        "controller_index": int(seat),
        "timestamp": next_timestamp(),
    })
    permanent.metadata[CONTROL_EFFECTS] = kept


def end_control_change(permanent: "Permanent", *, source: "Permanent") -> bool:
    """Drop *source*'s contribution to *permanent*'s control. Returns whether
    there was one. Unconditional by design: a source that recorded nothing has
    nothing to end, so callers never have to check first."""
    existing = control_changes(permanent)
    kept = [entry for entry in existing if entry["source"] is not source]
    if len(kept) == len(existing):
        return False
    if kept:
        permanent.metadata[CONTROL_EFFECTS] = kept
    else:
        permanent.metadata.pop(CONTROL_EFFECTS, None)
    return True


def control_changes(permanent: "Permanent") -> list[dict]:
    """Every layer-2 contribution currently on *permanent*, oldest first."""
    entries = permanent.metadata.get(CONTROL_EFFECTS)
    if not entries:
        return []
    return sorted(entries, key=lambda entry: entry["timestamp"])


def has_control_change(permanent: "Permanent") -> bool:
    """Whether any layer-2 effect applies — the fast path every controller read
    takes, so an untouched board never pays for the layer system."""
    return bool(permanent.metadata.get(CONTROL_EFFECTS))


__all__ = [
    "BASE_CONTROLLER", "CONTROL_EFFECTS", "base_controller", "change_control",
    "control_changes", "end_control_change", "has_control_change",
    "set_base_controller",
]
