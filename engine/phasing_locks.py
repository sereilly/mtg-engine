""""Target permanent **can't phase out**." (Spatial Binding, CR 702.26.)

The mirror of the ``phase_in_blocked`` marker Teferi, Timeless Voyager's rider
already writes, and a module of its own for the reason ``shields.py`` is one:
the record carries its **lifetime**, so a lock is added by writing one entry and
ended by the sweep that names that duration — never by a clearing line somebody
has to remember to add to a turn step.

**Two readers, and the second is the point.** ``resolve_phasing_for`` was
already asking ``metadata["cant_phase_out"]`` before this file existed, with
nothing in the engine writing it: a read with no writer, and a restriction that
would have been half enforced the moment one arrived. CR 702.26a's alternation
is only one of the ways a permanent phases out — Reality Ripple, Mist Dragon,
Vaporous Djinn, Warping Wurm, Frenetic Efreet and Taniwha all phase something
out on their own account — and a lock enforced at the untap step alone is one
the target's controller escapes by activating an ability. So the question is
asked at ``Game.phase_out_permanent``, the one transition every phase-out
passes through, and the untap step asks the same predicate.

The lock is on the **permanent**, which CR 400.7 makes the right object: a
permanent that leaves and comes back is a new one and is not the one the spell
named. A phase-out is *not* a zone change (CR 702.26b), so a permanent already
phased out keeps its lock and its id — which is what a card printing "can't
phase in" would need, and is not what Spatial Binding asks for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import Permanent

#: The metadata key. One list of entries rather than a bare flag, because two
#: Spatial Bindings on one permanent are two effects with two windows (CR
#: 611.2), and a flag the first one to expire cleared would let the target phase
#: out while the second was still running.
PHASE_OUT_LOCKS = "cant_phase_out"

#: The durations this lock can carry, each naming the sweep that ends it.
#: ``keywords.KEYWORD_GRANT_DURATIONS``' rule in miniature: a duration nothing
#: ends is a restriction that outlives what the card said, so an unlisted one
#: raises rather than being recorded and forgotten.
#:
#: One entry, because the pool prints one window. "Until end of turn" would want
#: a cleanup sweep and this record cannot take the blanket one — the key holds a
#: *list*, and popping it at cleanup would drop a "your next upkeep" lock five
#: turns early. So the second duration arrives with the card that prints it and
#: with the sweep that ends it, rather than being listed now and untested by
#: construction.
LOCK_DURATIONS: frozenset[str] = frozenset({"your_next_upkeep"})


def forbid_phase_out(
    permanent: "Permanent", *, duration: str, seat: int | None = None
) -> None:
    """Record that *permanent* can't phase out until *duration* ends.

    *seat* is whose step ends it — CR 109.5's controller of the ability, not of
    the affected permanent, which is the distinction "until **your** next
    upkeep" turns on and the same one ``keywords.SEATED_GRANT_DURATIONS`` draws.
    """
    if duration not in LOCK_DURATIONS:
        raise ValueError(f"no sweep ends a phase-out lock at {duration!r}")
    if duration == "your_next_upkeep" and seat is None:
        raise ValueError("a 'your next upkeep' phase-out lock needs the seat")
    entry: dict = {"duration": duration}
    if seat is not None:
        entry["seat"] = seat
    permanent.metadata.setdefault(PHASE_OUT_LOCKS, []).append(entry)


def phase_out_forbidden(permanent) -> bool:
    """Whether any live lock stops *permanent* phasing out.

    Tolerates the legacy shape — a bare truthy value under the same key — so a
    test or a fixture that sets the flag by hand still reads as locked. That is
    the reading ``resolve_phasing_for`` gave the key before this file existed,
    and nothing should start passing because a record grew structure.
    """
    locks = getattr(permanent, "metadata", {}).get(PHASE_OUT_LOCKS)
    if isinstance(locks, list):
        return bool(locks)
    return bool(locks)


def expire_phase_out_locks(
    permanent: "Permanent", duration: str, *, seat: int | None = None
) -> None:
    """Drop the locks *duration* (and *seat*) ends, from one permanent."""
    locks = permanent.metadata.get(PHASE_OUT_LOCKS)
    if not isinstance(locks, list):
        return
    kept = [
        entry for entry in locks
        if not (
            entry.get("duration") == duration
            and (seat is None or entry.get("seat") == seat)
        )
    ]
    if kept:
        permanent.metadata[PHASE_OUT_LOCKS] = kept
    else:
        permanent.metadata.pop(PHASE_OUT_LOCKS, None)
