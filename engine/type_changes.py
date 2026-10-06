"""Single write API for type-changing effects that are not land types
(CR 613 layer 4, CR 205.1).

"That creature becomes an artifact in addition to its other types" (Ashnod's
Transmogrant), "Target nonsnow basic land becomes snow" / "Target snow land is
no longer snow" (Arcum's Weathervane), "it becomes an Aura enchantment" (the
Licids), "…as a non-Aura enchantment" (Takklemaggot). Each is a continuous
effect a resolution creates, and CR 613.7b gives it a timestamp "at the time
it's created" — which is what orders it against every other layer-4 effect on
the same permanent.

The engine used to record them by appending a dict to a metadata list from five
places (``handlers/board_misc.py`` ×4, ``handlers/zones.py`` ×1), none of which
recorded *when*. The layer bridge had nothing to order by and gave both lists
the constant 0 — every addition before every removal, whichever came first — so
a Snow-Covered Forest thawed by the Weathervane and then frozen again was not
snow, and a land frozen under Melting ("All lands are no longer snow") stayed
thawed although the freeze was the later effect. Five writers is one missing
write API (``engine/pt.py``, ``engine/color_changes.py``, for the same reason):
the stamp is *inside* :func:`gain_types` / :func:`lose_types`, so no caller can
forget it, and ``tests/engine/test_type_write_seam.py`` fails a sixth direct
write.

Two recorded lists and the derived half
---------------------------------------

* ``gained_types`` — one record per effect that **added** a card type, subtype
  or supertype. A list, because two effects may each add a type and neither
  replaces the other; each record carries its own duration, so the sweep that
  ends it knows which ones it owns.
* ``lost_types`` — the mirror: one record per effect that took one **away**.
* The **derived** half is what a board-wide static keeps saying, rebuilt by
  ``engine/type_statics.py`` on every continuous-effects refresh and never
  recorded: a supertype a static removes (``derived_lost_supertypes``, Melting),
  and — for the statics whose contribution already lives on another channel
  (a land animator's flag, a global static's source list) — the *place in the
  order* each took (``static_type_order``). Both carry an **applied-order
  key**, ``(timestamp, order)``: the timestamp the effect applied at, which is
  its source's (CR 613.7a) unless it waited on an effect it depends on
  (CR 613.8b), and its position among the statics applied at that moment.

Land types are ``engine/land_types.py``'s (CR 305.7 makes them a replacement
with rules of its own), a card-type *set* is one stamped slot with one writer
(``layer_bridge.SET_CARD_TYPES``), and an animation's record is
``handlers/board_misc._animation_record``'s. ``layer_bridge.collect_type_effects``
reads all of them and is the only reader of what is recorded here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Iterable

from .continuous import next_timestamp

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import Permanent

#: Types an effect added to a permanent, with what else the same sentence
#: said. One record per effect.
GAINED_TYPES = "gained_types"

#: Types an effect took *away* from a permanent, the mirror of the above and a
#: list for the same reason. One record per effect, so the removal ends by
#: dropping the contribution rather than by remembering what was there.
LOST_TYPES = "lost_types"

#: Supertypes a board-wide **static** takes away ("All lands are no longer
#: snow", Melting), rebuilt from the board by ``engine/type_statics.py`` on every
#: recompute. A list of ``{"supertype", "timestamp", "order", "label"}``: the
#: word, and the applied-order key the layer bridge re-applies it at. It held
#: bare words, which the bridge could only apply at the constant 0 — behind
#: nothing, so in front of nothing, and a supertype an effect added *after* the
#: static arrived was taken away by it all the same.
DERIVED_LOST_SUPERTYPES = "derived_lost_supertypes"

#: Where each board-wide static whose layer-4 contribution is read off another
#: channel took its place in the order: ``{key: (timestamp, order)}``, rebuilt
#: with the rest of the derived half. The key is :data:`LAND_ANIMATION_ORDER`
#: for a land animator's "is a creature" and the source's ``permanent_id`` for
#: a global static's (Conspiracy, Dralnu's Crusade, Titania's Song,
#: Opalescence).
STATIC_TYPE_ORDER = "static_type_order"

#: The :data:`STATIC_TYPE_ORDER` key of a land animator's contribution. One key
#: rather than one per animator: every animator adds the same card type, and
#: additions commute, so the earliest place any of them took is the place the
#: land became a creature.
LAND_ANIMATION_ORDER = "land_animation"


def _record(
    perm: "Permanent", key: str, *, card_types: Iterable[str],
    subtypes: Iterable[str], supertypes: Iterable[str], source: str,
    extra: dict[str, Any],
) -> int:
    stamp = next_timestamp()
    record: dict[str, Any] = {
        "card_types": [str(word).lower() for word in card_types],
        "subtypes": [str(word).lower() for word in subtypes],
        "supertypes": [str(word).lower() for word in supertypes],
        "source": source,
        # CR 613.7b: stamped as the effect is created, off the one clock every
        # layer's effects and every permanent's own timestamp come from.
        "timestamp": stamp,
        **extra,
    }
    perm.metadata.setdefault(key, []).append(record)
    return stamp


def gain_types(
    perm: "Permanent", *, card_types: Iterable[str] = (),
    subtypes: Iterable[str] = (), supertypes: Iterable[str] = (),
    source: str = "effect", **extra: Any,
) -> int:
    """Layer 4: *perm* gains these types from now (CR 613.7b). Returns the stamp.

    An **addition** (CR 205.1b). *extra* rides on the record for whoever ends
    the effect — ``duration`` and ``seat`` for the two turn-structure sweeps,
    ``pt_from_mana_value`` for the layer-7b half of the same sentence, a marker
    for an effect its controller may pay to end — and is never read here.
    """
    return _record(
        perm, GAINED_TYPES, card_types=card_types, subtypes=subtypes,
        supertypes=supertypes, source=source, extra=extra,
    )


def lose_types(
    perm: "Permanent", *, card_types: Iterable[str] = (),
    subtypes: Iterable[str] = (), supertypes: Iterable[str] = (),
    source: str = "effect", **extra: Any,
) -> int:
    """Layer 4: *perm* loses these types from now (CR 613.7b). Returns the stamp.

    The removing half, in the same layer and on the same clock as
    :func:`gain_types` — so of "is no longer snow" and "becomes snow" on one
    land, the later one is what the land is.
    """
    return _record(
        perm, LOST_TYPES, card_types=card_types, subtypes=subtypes,
        supertypes=supertypes, source=source, extra=extra,
    )


def gained_types(perm: "Permanent") -> tuple[dict, ...]:
    """Every recorded addition on *perm*, in storage order.

    Not sorted, for ``land_types.land_type_changes``' reason: each becomes its
    own :class:`~engine.continuous.ContinuousEffect` carrying its own
    timestamp, and CR 613.7 is what orders them. A record written without a
    stamp (a board built by hand) reads as timestamp 0: an effect older than
    anything the clock has stamped.
    """
    return tuple(perm.metadata.get(GAINED_TYPES) or ())


def lost_types(perm: "Permanent") -> tuple[dict, ...]:
    """Every recorded removal on *perm*, in storage order."""
    return tuple(perm.metadata.get(LOST_TYPES) or ())


def end_type_changes(
    perm: "Permanent", ended: Callable[[dict], bool]
) -> int:
    """Drop every recorded type change on *perm* that *ended* says is over, and
    report how many went (CR 611.2a: the duration ended).

    Both lists, because a duration is a property of the effect and not of the
    direction it changed a type in — "…is no longer snow until end of turn"
    would be a removal the cleanup step has to end exactly as it ends an
    addition. Nothing is restored: what the permanent is afterwards is whatever
    the remaining contributions say.
    """
    dropped = 0
    for key in (GAINED_TYPES, LOST_TYPES):
        records = perm.metadata.get(key)
        if not records:
            continue
        kept = [record for record in records if not ended(record)]
        dropped += len(records) - len(kept)
        if kept:
            perm.metadata[key] = kept
        else:
            perm.metadata.pop(key, None)
    return dropped


# ---------------------------------------------------------------------------
# The derived half: what the board's statics say, rebuilt every refresh
# ---------------------------------------------------------------------------


def clear_derived_type_changes(perm: "Permanent") -> None:
    """Drop the contributions derived from the current board (CR 611.3b).

    Called by the same pass that rebuilds them, which is what keeps a derived
    channel from turning into an accumulating one.
    """
    perm.metadata.pop(DERIVED_LOST_SUPERTYPES, None)
    perm.metadata.pop(STATIC_TYPE_ORDER, None)


def add_derived_lost_supertype(
    perm: "Permanent", supertype: str, *, timestamp: int, order: int = 0,
    label: str = "",
) -> None:
    """Layer 4: *perm* is no longer *supertype* for as long as a static keeps
    saying so.

    *timestamp* and *order* are the applied-order key — the **source's**
    timestamp (CR 613.7a) unless the effect waited on one it depends on, never
    a fresh one: a contribution rebuilt on every refresh would otherwise be the
    newest effect on the board each time anything happened.
    """
    perm.metadata.setdefault(DERIVED_LOST_SUPERTYPES, []).append({
        "supertype": str(supertype).lower(),
        "timestamp": int(timestamp),
        "order": int(order),
        "label": label,
    })


def derived_lost_supertypes(perm: "Permanent") -> tuple[dict, ...]:
    """Every supertype a board-wide static is taking away from *perm*."""
    return tuple(perm.metadata.get(DERIVED_LOST_SUPERTYPES) or ())


def set_static_type_order(
    perm: "Permanent", key: Any, *, timestamp: int, order: int
) -> None:
    """Record where the static named *key* applied to *perm* in layer 4.

    The first place wins: a key is one contribution, and a second static
    writing the same key (two land animators) adds the same type again, which
    changes nothing after the first.
    """
    perm.metadata.setdefault(STATIC_TYPE_ORDER, {}).setdefault(
        key, (int(timestamp), int(order))
    )


def static_type_order(perm: "Permanent", key: Any) -> tuple[int, int] | None:
    """The applied-order key the static named *key* took on *perm*, or None
    when no refresh has placed it (a board built by hand)."""
    return (perm.metadata.get(STATIC_TYPE_ORDER) or {}).get(key)


__all__ = [
    "DERIVED_LOST_SUPERTYPES", "GAINED_TYPES", "LAND_ANIMATION_ORDER",
    "LOST_TYPES", "STATIC_TYPE_ORDER", "add_derived_lost_supertype",
    "clear_derived_type_changes", "derived_lost_supertypes",
    "end_type_changes", "gain_types", "gained_types", "lose_types",
    "lost_types", "set_static_type_order", "static_type_order",
]
