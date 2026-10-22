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
``aura_attachment.attach_aura``.

A spell is an object too
------------------------

"Target **spell** or permanent becomes red" recolours an object on the stack,
which has no metadata and no layers: its record is two keys of
``StackItem.choices``, written by :func:`recolor_spell` and read by
:func:`spell_color_change` — the answer ``Game._stack_item_colors`` gives every
"counter target red spell", protection and colour condition. It was one key
written from a handler, which is why it carried neither a duration nor a
timestamp, and why the effect ended the moment the spell stopped being one:
CR 400.7a says it "continue[s] to apply to the permanent that spell becomes",
and :func:`carry_spell_color_change` is that sentence — the effect written onto
the permanent through :func:`change_color` with the duration it was created
with and the stamp it was created at (CR 613.7b), so a Lace cast at a creature
spell is still a Lace when the creature arrives.
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


def change_color(
    perm: Permanent, colors: Any, *, until_eot: bool = False,
    created_at: int | None = None,
) -> int:
    """Layer 5: *perm* becomes *colors* from now (CR 613.7b). Returns the stamp.

    *colors* is stored as given — a symbol, a sequence of symbols, or the empty
    tuple for colourless — and never ``None``, which is "no effect" and the one
    value the reader takes for an empty slot.

    A second write to the same slot replaces the first and takes a fresh
    timestamp. Both would have ended together, so the earlier one could never
    again be the effect that applies last.

    *created_at* is the stamp of an effect that **already exists** and is only
    now reaching this permanent: one that changed a permanent spell on the
    stack and continues to apply to what the spell became (CR 400.7a). Its
    timestamp is the time it was created (CR 613.7b), not the time its object
    changed zones, so :func:`carry_spell_color_change` hands the old stamp on
    and no fresh one is drawn. Nothing else passes it.
    """
    if colors is None:
        raise ValueError(
            "change_color needs a colour; None is an empty slot, and CR 105.2c's "
            "colourless is the empty tuple"
        )
    value_key, stamp_key, _label = _SLOTS[1 if until_eot else 0]
    stamp = next_timestamp() if created_at is None else int(created_at)
    perm.metadata[value_key] = colors
    perm.metadata[stamp_key] = stamp
    return stamp


#: Beside :data:`COLOR_OVERRIDE` in a **spell's** ``StackItem.choices``: how
#: long each effect on it lasts and when it was created, in a permanent's own
#: two slots — ``{"indefinite": {"color", "timestamp"}, "until_eot": {…}}``,
#: either or both. The value key keeps the shape it has always had (the symbol
#: of the effect that applies last, or the printed word for colourless),
#: because the wire and a good many tests read it back; this is everything a
#: permanent's two slots and two stamps say that one symbol cannot.
#:
#: Two slots for the reason a permanent has two: a Lace and an Illusion on one
#: creature spell are two effects that end at different moments, and the Lace
#: is what is left when the turn-long one ends.
SPELL_COLOR_EFFECT = "color_effect"

#: The two slot names of :data:`SPELL_COLOR_EFFECT`, in :data:`_SLOTS` order.
_SPELL_SLOTS = ("indefinite", "until_eot")

#: How a spell's record spells CR 105.2c's colourless — the printed word
#: (``grammar.ast.COLORLESS``), where a permanent's slot holds the empty tuple.
#: One translation, in :func:`_spell_record_colors`: read raw, the word is a
#: non-empty value that every "is this spell colourless?" reader takes for a
#: sixth colour.
_COLORLESS_WORD = "colorless"


def _spell_record_colors(recorded: Any) -> tuple[str, ...]:
    """A spell's recorded value as the set of colours it names."""
    if recorded == _COLORLESS_WORD:
        return ()
    return _as_colors(recorded)


def recolor_spell(item: Any, color: Any, *, until_eot: bool = False) -> int:
    """The spell *item* becomes *color* (CR 105.3: the new colour replaces the
    ones it had). Returns the effect's stamp.

    **The one write of a stack object's colour record.** *color* is a mana
    symbol, or the printed word for colourless ("Target spell becomes
    colorless", Ersatz Gnomes). *until_eot* is the printed duration ("…becomes
    the color of your choice **until end of turn**", Illusion): on the stack it
    changes nothing a reader can see, since a spell does not outlive the turn
    it was cast in, and it is the whole difference once the spell is a
    permanent (:func:`carry_spell_color_change`).
    """
    stamp = next_timestamp()
    effects = dict(item.choices.get(SPELL_COLOR_EFFECT) or {})
    effects[_SPELL_SLOTS[1 if until_eot else 0]] = {
        "color": color, "timestamp": stamp,
    }
    item.choices[SPELL_COLOR_EFFECT] = effects
    # The newest effect has the latest timestamp, so it is the one that
    # applies last (CR 613.7) — whichever slot it is in.
    item.choices[COLOR_OVERRIDE] = color
    return stamp


def forget_spell_color_change(item: Any) -> None:
    """Drop every colour effect recorded on the spell *item*.

    For a **copy**: the record rides ``StackItem.choices``, which a copy takes
    whole (CR 707.10: the decisions made for the spell), and an effect that
    recoloured the original is not one of them — CR 707.2 copies the printed
    values, "other effects … are not copied".
    """
    item.choices.pop(COLOR_OVERRIDE, None)
    item.choices.pop(SPELL_COLOR_EFFECT, None)


def spell_color_change(item: Any) -> tuple[str, ...] | None:
    """The colours an effect made the spell *item*, or None where none did.

    The empty tuple is an answer — a spell made colourless has no colours
    (CR 105.2c) — which is why the caller must test for None and not for
    truth. The record for colourless is a non-empty word, and returned as it
    was stored it made the spell *the colour "colorless"*.
    """
    recorded = (getattr(item, "choices", None) or {}).get(COLOR_OVERRIDE)
    if not recorded:
        return None
    return _spell_record_colors(recorded)


def carry_spell_color_change(choices: dict | None, perm: Permanent) -> bool:
    """CR 400.7a: a colour effect on a permanent spell goes on applying to the
    permanent the spell becomes. Returns whether there was one to carry.

    *choices* is the resolving spell's own (``StackItem.choices``), handed over
    where the permanent is built and before it enters, so an entry replacement
    reads the colour the permanent arrives with. Each effect keeps its duration
    — a Lace is indefinite and stays; Illusion's ends at this turn's cleanup
    with every other turn-long recolour — and the stamp it was created with,
    so two of them on one spell are ordered on the permanent exactly as they
    were on the stack.

    A record written without the effect key (a board built by hand) is an
    indefinite effect older than anything the clock has stamped, which is how
    an unstamped slot already reads.
    """
    choices = choices or {}
    recorded = choices.get(COLOR_OVERRIDE)
    if not recorded:
        return False
    effects = choices.get(SPELL_COLOR_EFFECT) or {
        _SPELL_SLOTS[0]: {"color": recorded, "timestamp": 0},
    }
    for slot in _SPELL_SLOTS:
        effect = effects.get(slot)
        if not effect:
            continue
        colors = _spell_record_colors(effect.get("color"))
        change_color(
            perm,
            # One colour is stored as its symbol, as every one-colour writer
            # of the slot stores it; colourless is the empty tuple.
            colors[0] if len(colors) == 1 else colors,
            until_eot=slot == _SPELL_SLOTS[1],
            created_at=int(effect.get("timestamp") or 0),
        )
    return True


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
    "SPELL_COLOR_EFFECT", "UNTIL_EOT_KEYS", "add_derived_color_change",
    "carry_spell_color_change", "change_color", "clear_derived_color_changes",
    "color_changes", "forget_spell_color_change", "recolor_spell",
    "spell_color_change",
]
