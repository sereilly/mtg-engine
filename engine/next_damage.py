"""What the **next** damage a named source deals does differently, as state.

``engine/shields.py`` is what a prevention shield *is* and ``engine/prevention/``
what one *does*; ``engine/damage_redirects.py`` is the same split for a redirect.
This module is that pair a third time, for the one printed shape neither of them
can hold: an effect that waits for **one source's** next damage event and changes
it, wherever that damage was headed.

    "Choose a source you control and flip a coin. If you win the flip, the next
    time that source would deal damage this turn, it deals double that damage
    instead. If you lose the flip, the next time it would deal damage this turn,
    prevent that damage."  (Desperate Gambit.)

Both halves name the same three things and neither names a fourth:

- **whose damage** — one chosen source, and nothing else;
- **how many times** — once ("the next time");
- **how long** — this turn.

What they do *not* name is a recipient. Every :class:`~engine.shields.Shield`
hangs off the player or permanent it protects, because CR 615.1 puts a shield
"around whatever they're affecting" — and this sentence affects the *source*,
not anything it might hit. ``DamageRedirect.any_recipient`` (Reflect Damage)
already met the same wall on the redirect side and answered it by living on the
seat that armed it and being found by a scan; here the answer is one step
simpler, because there is an object the effect is genuinely about.

**So the record lives on the source.** That is not a shortcut around the two
collections above, it is the shape ``engine/damage_events.py`` already uses for
exactly this sentence: ``_DEALER_RIDERS`` are "markers on the **damager**,
naming the riders its damage carries for the rest of the turn" (Runesword), swept
with the turn by ``mixins/_constants._EOT_METADATA_KEYS``. Desperate Gambit's two
branches are riders its damage carries for the rest of the turn, said in the same
words about the same object. Three consequences come free:

- CR 400.7 gives the lifetime its outer bound: a permanent that leaves and comes
  back is a new object with no markers, which is exactly what "that source"
  stops meaning when the chosen permanent dies;
- the turn boundary is the existing sweep rather than a new one;
- nothing is added to ``PlayerState``, to ``Game``, or to either collection whose
  every reader would then have to learn about a shield with no recipient.

**Only a permanent can carry one.** A spell's source is its printed
``CardDefinition`` (CR 120.7) — one object per *card*, shared by every copy in
every deck in the process — so a marker written on one would be a marker on all
of them, and the "next damage" of a Lightning Bolt would double for the other
three in the deck. ``arm`` therefore takes only an object with ``metadata`` and
says so; the choice that feeds it offers permanents alone.

**Purity.** :func:`armed` computes and :func:`spend` mutates, for the reason
``Shield.would_prevent`` and ``Shield.spend`` are split: CR 616.1 counts the
effects contending over a damage event before any of them runs
(``engine/effect_ordering.py``), so the predicate half of both interceptors calls
only the first. A predicate that decremented would spend the rider on an effect
the player was merely asked about.

Counts rather than flags. Two Desperate Gambits on one source are two effects
(CR 614.5 applies each once), so the record is how many times the rider still
has to fire.
"""

from __future__ import annotations

from typing import Any

#: "…the next time that source would deal damage this turn, it **deals double
#: that damage** instead." CR 614's amount replacement, spent once.
DAMAGE_DOUBLED_NEXT = "next_damage_it_deals_is_doubled"

#: "…the next time it would deal damage this turn, **prevent that damage**."
#: CR 615's prevention, spent once, and with no recipient recorded anywhere —
#: the damage is prevented whoever it was headed for.
DAMAGE_PREVENTED_NEXT = "next_damage_it_deals_is_prevented"

#: "…the next time that creature would deal **combat** damage this turn, it
#: deals double that damage instead." / "…prevent that damage." (Impulsive
#: Maneuvers.) The same two riders narrowed by CR 510.2's word, which is a
#: property of the *event* rather than of either end of it — so it is a second
#: pair of records on the same object rather than a flag beside the first: a
#: source carrying a combat rider and an unnarrowed one is carrying two
#: effects, and one count with a flag could not say which of them a ping
#: ability's damage spends.
COMBAT_DAMAGE_DOUBLED_NEXT = "next_combat_damage_it_deals_is_doubled"
COMBAT_DAMAGE_PREVENTED_NEXT = "next_combat_damage_it_deals_is_prevented"

#: The combat-narrowed twin of each unnarrowed rider.
_COMBAT_ONLY = {
    DAMAGE_DOUBLED_NEXT: COMBAT_DAMAGE_DOUBLED_NEXT,
    DAMAGE_PREVENTED_NEXT: COMBAT_DAMAGE_PREVENTED_NEXT,
}

_RIDER_KEYS = (
    DAMAGE_DOUBLED_NEXT, DAMAGE_PREVENTED_NEXT,
    COMBAT_DAMAGE_DOUBLED_NEXT, COMBAT_DAMAGE_PREVENTED_NEXT,
)


def names_key(key: str) -> str:
    """Where the cards that armed *key*'s riders are named, beside the count:
    a list, oldest first, one entry per rider (``""`` for one armed with no
    card to name). CR 616.1e's ``effect_order`` option names the card that
    generated the effect (``effect_ordering.option_text``) — the count alone
    names nothing, and the object it sits on is the *source* the rider
    watches, not what armed it (Desperate Gambit's option read "(Warmonger)")."""
    return f"{key}_by"


#: Every key, for the end-of-turn sweep that is these records' whole duration.
#: Named together so the sweep cannot pick up one of them and leave another
#: running for the rest of the game — the failure a second spelling produces
#: here is a coin flip whose losing half never expires. The name records go
#: with their counts for the same reason.
NEXT_DAMAGE_KEYS = _RIDER_KEYS + tuple(names_key(key) for key in _RIDER_KEYS)


def rider_key(key: str, *, combat_only: bool = False) -> str:
    """The record *key*'s rider is written under: itself, or its
    combat-narrowed twin when the sentence printed "combat damage"."""
    return _COMBAT_ONLY[key] if combat_only else key


def _spent_in(moment: Any, source: Any, key: str, *, combat: bool) -> bool:
    """Whether the dealing *moment* has already spent one of *source*'s riders
    of *key*'s kind (or, for combat damage, its combat-narrowed twin). Pure.

    CR 615.8 / CR 614: "the next time that source would deal damage" is one
    **instance**, and one instance of damage from a source is everything it
    deals in one simultaneous dealing (the project owner's ruling,
    2026-11-07) — so a rider spent on one chunk of a dealing carries over to
    the source's other chunks of it (``SimultaneousDamage.next_time_riders``),
    and the dealing's finish is the end of it. *moment* is the dealing
    (``damage_redirects.dealing_moment``), None outside one."""
    return bool(_spent_rows(moment, source, key, combat=combat))


def _spent_rows(moment: Any, source: Any, key: str, *, combat: bool) -> list:
    """The ``(source, key, name)`` rows of :func:`_spent_in`. Pure."""
    spent = getattr(moment, "next_time_riders", None)
    if not spent:
        return []
    keys = (key, _COMBAT_ONLY[key]) if combat else (key,)
    return [row for row in spent if row[0] is source and row[1] in keys]


def armed_for_event(source: Any, key: str, *, combat: bool, moment: Any = None) -> int:
    """How many riders of *key*'s kind answer to **this** damage event. Pure.

    The unnarrowed rider answers to every event; the combat-narrowed one only
    to combat damage. The interceptors' predicate half. A rider spent on an
    earlier chunk of the dealing *moment* still answers (:func:`_spent_in`).
    """
    count = armed(source, key)
    if combat:
        count += armed(source, _COMBAT_ONLY[key])
    if _spent_in(moment, source, key, combat=combat):
        count += 1
    return count


def spend_for_event(source: Any, key: str, *, combat: bool, moment: Any = None) -> None:
    """Charge one rider of *key*'s kind against this event. The mutating half.

    The combat-narrowed rider first where both are armed and the event is
    combat damage: it is the one that could not have applied to anything else,
    so spending it leaves the wider rider for the source's next damage of any
    kind — the order its controller would choose (CR 616.1e).

    Inside a dealing (*moment*) the rider is spent once for the whole of it:
    the first chunk charges it and records it on the dealing, and the source's
    later chunks of that dealing charge nothing (:func:`_spent_in`).
    """
    if _spent_in(moment, source, key, combat=combat):
        return
    narrowed = _COMBAT_ONLY[key]
    charged = narrowed if combat and armed(source, narrowed) > 0 else key
    name = (_names(source, charged) or [""])[0]
    spend(source, charged)
    spent = getattr(moment, "next_time_riders", None)
    if spent is not None:
        spent.append((source, charged, name))


def names_for_event(source: Any, key: str, *, combat: bool, moment: Any = None) -> list[str]:
    """The cards that armed the riders of *key*'s kind answering **this**
    event (:func:`armed_for_event`'s riders), for CR 616.1e's option to name
    beside its label. Pure. A rider armed with no card names nothing."""
    names = list(_names(source, key))
    if combat:
        names += _names(source, _COMBAT_ONLY[key])
    names += [row[2] for row in _spent_rows(moment, source, key, combat=combat)]
    return [name for name in names if name]


def _names(source: Any, key: str) -> list[str]:
    """*key*'s name record on *source*, aligned with its count. Pure."""
    metadata = getattr(source, "metadata", None)
    if not metadata:
        return []
    return list(metadata.get(names_key(key)) or ())[:armed(source, key)]


def arm(source: Any, key: str, times: int = 1, *, by: str | None = None) -> bool:
    """Record that *source*'s next *times* damage events carry the *key* rider,
    armed by the card named *by* (:func:`names_key`).

    False when there is nothing to write on — a source that is not a permanent
    (see the module docstring) or no source at all, which is what an effect
    whose choice found nothing hands over. The caller logs; refusing here is
    what keeps a marker off a shared ``CardDefinition``.
    """
    metadata = getattr(source, "metadata", None)
    if metadata is None or getattr(source, "permanent_id", None) is None:
        return False
    names = _names(source, key)
    names += [""] * (armed(source, key) - len(names)) + [str(by or "")] * int(times)
    metadata[key] = int(metadata.get(key) or 0) + int(times)
    metadata[names_key(key)] = names
    return True


def armed(source: Any, key: str) -> int:
    """How many of *source*'s next damage events still carry *key*. Pure."""
    metadata = getattr(source, "metadata", None)
    if not metadata:
        return 0
    return max(0, int(metadata.get(key) or 0))


def spend(source: Any, key: str) -> None:
    """Charge one instance of *key* against *source*. The mutating half.

    The key is dropped at zero rather than left holding one, so nothing has to
    distinguish "armed none" from "never armed" — the same courtesy
    ``shields.drop_spent`` does for a shield that is used up.
    """
    metadata = getattr(source, "metadata", None)
    if not metadata:
        return
    names = _names(source, key)[1:]
    remaining = armed(source, key) - 1
    if remaining > 0:
        metadata[key] = remaining
        metadata[names_key(key)] = names
    else:
        metadata.pop(key, None)
        metadata.pop(names_key(key), None)
