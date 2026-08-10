"""Single write API for basic-land-type changes (CR 613 layer 4, CR 305.7).

"Enchanted land is a Swamp" (Evil Presence), "that land is a Swamp for as long
as it has a mire counter on it" (Cyclopean Tomb), "target land becomes a Forest
until this creature leaves the battlefield" (Gaea's Liege), "All Mountains are
Plains" (Conversion). Each *sets* a land's subtype, and CR 305.7 makes that a
replacement: the land no longer has its old land types.

The engine used to record all of them by stamping one string on the land, so
every effect had to remember to un-stamp exactly what it stamped — and could
only ever un-stamp everything. Two of those effects on one land meant the second
silently overwrote the first, and whichever ended first took the other with it.

This module records each one as a **contribution**: what it makes the land, who
made it, and when (CR 613.7). ``layer_bridge.collect_type_effects`` turns each
contribution into its own layer-4 effect, so the layer engine — not the order
the writes happened to run in — decides which applies last. Removal is dropping
one contribution, which is why nothing here has a delta to get wrong: an
effect ending restores whatever the *other* contributions still say, not the
printed type line.

Two channels, for the same reason ``engine/keywords.py`` has two: a recorded
effect is stamped once and lives until its source ends it, while a *derived*
one (Conversion's static ability) is recomputed from the board on every
continuous-effects refresh and would otherwise accumulate one entry per pass,
forever.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .continuous import next_timestamp

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import Permanent

# Key under which a land's ordered, recorded type changes live.
LAND_TYPE_EFFECTS = "land_type_effects"

# Key under which the *derived* ones live — a static ability's, rebuilt from the
# board each recompute. Split from the recorded channel so the rebuild cannot
# turn into an accumulation.
DERIVED_LAND_TYPES = "derived_land_type_changes"

# Key under which a static source's own timestamp lives (CR 613.7a: a static
# ability's continuous effect has the timestamp of the object it is on). Stamped
# once, the first time the static applies, so the derived contribution it
# rebuilds every refresh keeps a stable place in the order.
STATIC_SOURCE_TIMESTAMP = "static_land_type_timestamp"

# The source label for Cyclopean Tomb's mire counter. The counter, not the
# artifact, is what the type change hangs on ("for as long as it has a mire
# counter on it"), so the Tomb leaving the battlefield does not end it.
MIRE_COUNTER = "mire counter"


def _same_source(recorded: Any, wanted: Any) -> bool:
    """Identity for live objects, equality for the string labels.

    ``Permanent`` is a plain dataclass, so ``==`` would deep-compare two
    permanents — including metadata holding references back to permanents.
    Sources are compared by identity for that reason; a label is a str and has
    no identity worth preserving across a copy.
    """
    if isinstance(wanted, str) or isinstance(recorded, str):
        return isinstance(recorded, str) and isinstance(wanted, str) and recorded == wanted
    return recorded is wanted


def change_land_type(
    perm: Permanent, land_type: str, *, source: Any, label: str = ""
) -> None:
    """Layer 4: *perm*'s land subtype becomes *land_type* from now (CR 613.7b).

    *source* is whatever ends the effect — the Aura, the activating creature, or
    a label such as :data:`MIRE_COUNTER` for a change that outlives its card.
    Passing the same source twice replaces its earlier contribution rather than
    stacking a second one, because one effect applies once however often it is
    re-resolved.
    """
    lowered = str(land_type).strip().lower()
    if not lowered:
        return
    effects = [
        entry
        for entry in (perm.metadata.get(LAND_TYPE_EFFECTS) or [])
        if not _same_source(entry.get("source"), source)
    ]
    effects.append(
        {
            "land_type": lowered,
            "source": source,
            "timestamp": next_timestamp(),
            "label": label,
        }
    )
    perm.metadata[LAND_TYPE_EFFECTS] = effects


def end_land_type_change(perm: Permanent, *, source: Any) -> bool:
    """Drop *source*'s contribution (CR 611.3: the duration ended).

    Returns whether anything was dropped, so a caller that logs the reversion
    still knows it happened. What the land is afterwards is whatever the
    remaining contributions say — this does not restore the printed type, and
    that is the point: an Evil Presence Swamp survives Gaea's Liege's Forest
    ending.
    """
    effects = perm.metadata.get(LAND_TYPE_EFFECTS)
    if not effects:
        return False
    remaining = [
        entry for entry in effects if not _same_source(entry.get("source"), source)
    ]
    if len(remaining) == len(effects):
        return False
    if remaining:
        perm.metadata[LAND_TYPE_EFFECTS] = remaining
    else:
        perm.metadata.pop(LAND_TYPE_EFFECTS, None)
    return True


def clear_derived_land_types(perm: Permanent) -> None:
    """Drop the contributions derived from the current board (CR 611.3b).

    Called by the same function that rebuilds them; splitting the clear from the
    rebuild is how a derived channel turns into an accumulating one.
    """
    perm.metadata.pop(DERIVED_LAND_TYPES, None)


def add_derived_land_type(
    perm: Permanent, land_type: str, *, timestamp: int, label: str = ""
) -> None:
    """Layer 4: *perm* is *land_type* for as long as a static keeps saying so."""
    derived = perm.metadata.setdefault(DERIVED_LAND_TYPES, [])
    derived.append(
        {
            "land_type": str(land_type).strip().lower(),
            "source": label,
            "timestamp": int(timestamp),
            "label": label,
        }
    )


def static_source_timestamp(source: Permanent) -> int:
    """*source*'s own timestamp, stamped the first time its static applies.

    CR 613.7a gives a static ability's continuous effect the timestamp of the
    object the ability is on. The engine has no general per-permanent timestamp
    yet, so this stands in for one: stable across refreshes (which is what the
    derived channel needs) and ordered against everything else by when the
    static first mattered.
    """
    stamp = source.metadata.get(STATIC_SOURCE_TIMESTAMP)
    if stamp is None:
        stamp = next_timestamp()
        source.metadata[STATIC_SOURCE_TIMESTAMP] = stamp
    return int(stamp)


def land_type_changes(perm: Permanent) -> tuple[dict, ...]:
    """Every layer-4 land-type contribution on *perm*, in **storage** order.

    Deliberately not sorted here. Each contribution becomes its own
    :class:`ContinuousEffect` carrying its own timestamp, and CR 613.7 is what
    orders them — sorting first would make the timestamps decorative, since the
    two channels' storage order would then be doing the work and a
    contribution stamped wrongly would still come out right. The recorded and
    derived channels are concatenated precisely so that storage order and
    timestamp order need not agree.

    Read by ``layer_bridge`` and nothing else: "what type is this?" has one
    answer, ``Permanent.has_type`` / ``Permanent.basic_land_types``, and a
    second reader of this list would be a second opinion about CR 305.7.
    """
    return (
        *(perm.metadata.get(LAND_TYPE_EFFECTS) or ()),
        *(perm.metadata.get(DERIVED_LAND_TYPES) or ()),
    )


__all__ = [
    "DERIVED_LAND_TYPES", "LAND_TYPE_EFFECTS", "MIRE_COUNTER",
    "STATIC_SOURCE_TIMESTAMP", "add_derived_land_type", "change_land_type",
    "clear_derived_land_types", "end_land_type_change", "land_type_changes",
    "static_source_timestamp",
]
