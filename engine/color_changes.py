"""Single write API for colour-changing effects (CR 613 layer 5, CR 105.3).

"Target spell or permanent becomes white" (the Lace cycle), "One or more
target creatures become black until end of turn" (Touch of Darkness), "…becomes
a 2/2 green creature" (Quirion Druid), "All Swamps are 1/1 black creatures"
(Kormus Bell). Each *sets* a permanent's colour — CR 105.3: "the new color
replaces all previous colors the object had" — so two of them on one permanent
do not commute, and CR 613.7 says which applies last: the one with the later
timestamp.

The engine used to record them by writing a metadata key from eight places,
none of which recorded *when*. The layer bridge then had nothing to order by
and gave each **channel** a constant instead — a permanent's own chosen colour
before an indefinite recolour, before a turn-long one, before any board-wide
static — so which effect won was decided by what kind of effect it was. Under a
Shifting Sky naming white, Singe's "becomes black until end of turn" did
nothing; a lace cast after a turn-long recolour lost to it.
Eight writers is one missing write API (``engine/pt.py``, for the same reason):
the stamp is *inside* :func:`change_color`, so no caller can forget it, and
``tests/engine/test_color_write_seam.py`` fails a ninth direct write.

Two recorded slots and a derived channel
----------------------------------------

* ``color_override`` — a resolved effect that lasts **indefinitely**.
* ``color_override_until_eot`` — one that lasts **until end of turn**; the
  cleanup step sweeps it (``mixins/_constants._EOT_METADATA_KEYS``), stamp and
  all.
* ``derived_color_changes`` — what a **static** keeps saying (Kormus Bell's
  black Swamps), cleared and rebuilt from the board on every continuous-effects
  refresh and carrying its source's timestamp (CR 613.7a). It was written into
  the indefinite slot, where it overwrote a lace that was there first and took
  that lace away with it when the Bell left.

A slot holds one effect, and that loses nothing: every effect in a slot ends at
the same moment (never; at cleanup), so of two in one slot the earlier can
never apply last again and CR 613.7 has no further use for it. That is a fact
about **two durations**, held to the pool by
``tests/engine/test_color_write_seam.py``. A third duration ("until your next
turn") is a third slot with its own sweep — or the day these become a list of
contributions, the way ``engine/control.py`` and ``engine/land_types.py`` hold
theirs.

What is stored in a slot is unchanged from before the stamp existed (a mana
symbol, a tuple or list of them, or the **empty tuple** for CR 105.2c's
colourless), because the web payload and a great many tests read it back.

Everything else that reaches layer 5 is derived where it is read
(``layer_bridge.collect_color_effects``) and stamped from the object it is on:
a board-wide static and a permanent's own "is the chosen color" by
``Permanent.timestamp`` (CR 613.7a, 613.7d), an Aura by the moment it became
attached (CR 613.7e) — which is that same field, re-stamped by
``auras.attach_aura``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .continuous import next_timestamp

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import Permanent

#: A resolved colour effect with no duration ("…becomes white"; CR 611.2a's
#: "lasts indefinitely").
COLOR_OVERRIDE = "color_override"

#: A resolved colour effect that ends at cleanup (CR 514.2).
COLOR_OVERRIDE_UNTIL_EOT = "color_override_until_eot"

#: When each slot was last written (CR 613.7b). Beside the value rather than
#: folded into it, so the value keeps the shape everything reads back.
COLOR_OVERRIDE_TIMESTAMP = "color_override_timestamp"
COLOR_OVERRIDE_UNTIL_EOT_TIMESTAMP = "color_override_until_eot_timestamp"

#: What the board's statics say this permanent's colour is, rebuilt each
#: refresh. A list of ``{"colors", "timestamp", "label"}``.
DERIVED_COLOR_CHANGES = "derived_color_changes"

#: The two recorded slots, in the order a pair of *unstamped* values applies —
#: indefinite, then turn-long — which is the order they had while this was a
#: pair of constants.
_SLOTS = (
    (COLOR_OVERRIDE, COLOR_OVERRIDE_TIMESTAMP, "colour change"),
    (
        COLOR_OVERRIDE_UNTIL_EOT, COLOR_OVERRIDE_UNTIL_EOT_TIMESTAMP,
        "colour change until end of turn",
    ),
)

#: Every key the cleanup step ends a turn-long colour effect by dropping: the
#: value and its stamp together, so an effect that has ended leaves nothing
#: behind for a later reader to find.
UNTIL_EOT_KEYS = (COLOR_OVERRIDE_UNTIL_EOT, COLOR_OVERRIDE_UNTIL_EOT_TIMESTAMP)


def change_color(perm: Permanent, colors: Any, *, until_eot: bool = False) -> int:
    """Layer 5: *perm* becomes *colors* from now (CR 613.7b). Returns the stamp.

    *colors* is stored as given — a symbol, a sequence of symbols, or the empty
    tuple for colourless — and never ``None``, which is "no effect" and the one
    value the reader takes for an empty slot.

    A second write to the same slot replaces the first and takes a fresh
    timestamp. Both would have ended together, so the earlier one could never
    again be the effect that applies last.
    """
    if colors is None:
        raise ValueError(
            "change_color needs a colour; None is an empty slot, and CR 105.2c's "
            "colourless is the empty tuple"
        )
    value_key, stamp_key, _label = _SLOTS[1 if until_eot else 0]
    stamp = next_timestamp()
    perm.metadata[value_key] = colors
    perm.metadata[stamp_key] = stamp
    return stamp


def clear_derived_color_changes(perm: Permanent) -> None:
    """Drop the contributions derived from the current board (CR 611.3b).

    Called by the same function that rebuilds them, which is what keeps a
    derived channel from turning into an accumulating one.
    """
    perm.metadata.pop(DERIVED_COLOR_CHANGES, None)


def add_derived_color_change(
    perm: Permanent, colors: Any, *, timestamp: int, label: str = ""
) -> None:
    """Layer 5: *perm* is *colors* for as long as a static keeps saying so.

    *timestamp* is the **source's** (CR 613.7a: a static ability's continuous
    effect has the timestamp of the object the ability is on), never a fresh
    one — a contribution rebuilt on every refresh would otherwise be the newest
    effect on the board each time anything happened.
    """
    perm.metadata.setdefault(DERIVED_COLOR_CHANGES, []).append({
        "colors": _as_colors(colors),
        "timestamp": int(timestamp),
        "label": label,
    })


def color_changes(perm: Permanent) -> tuple[dict, ...]:
    """Every recorded and derived layer-5 contribution on *perm*, in
    **storage** order — ``{"colors", "timestamp", "label"}`` each.

    Deliberately not sorted, for ``land_types.land_type_changes``' reason: each
    becomes its own :class:`~engine.continuous.ContinuousEffect` carrying its
    own timestamp, and CR 613.7 is what orders them. Read by
    ``layer_bridge.collect_color_effects`` and nothing else — "what colour is
    this?" has one answer (``Game._effective_colors``).

    A slot written without a stamp (a board built by hand) reads as timestamp
    0: an effect older than anything the clock has stamped.
    """
    found = []
    for value_key, stamp_key, label in _SLOTS:
        value = perm.metadata.get(value_key)
        # ``is not None``, not truthiness: the **empty tuple** is a real answer
        # — CR 105.2c's colourless, which "becomes colorless" (Raging Spirit,
        # Ersatz Gnomes) writes as an object with no colours rather than as a
        # sixth colour.
        if value is None:
            continue
        found.append({
            "colors": _as_colors(value),
            "timestamp": int(perm.metadata.get(stamp_key) or 0),
            "label": label,
        })
    found.extend(perm.metadata.get(DERIVED_COLOR_CHANGES) or ())
    return tuple(found)


def _as_colors(value: Any) -> tuple[str, ...]:
    """A slot's value as the set of colours it names.

    A *set* where the card offered one ("becomes the color or colors of your
    choice", Dream Coat) — CR 105.2 makes an object of two colours one object,
    not two effects. Normalised here rather than at every write, because this
    is the one reader.
    """
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(value)
    return (value,)


__all__ = [
    "COLOR_OVERRIDE", "COLOR_OVERRIDE_TIMESTAMP", "COLOR_OVERRIDE_UNTIL_EOT",
    "COLOR_OVERRIDE_UNTIL_EOT_TIMESTAMP", "DERIVED_COLOR_CHANGES",
    "UNTIL_EOT_KEYS", "add_derived_color_change", "change_color",
    "clear_derived_color_changes", "color_changes",
]
