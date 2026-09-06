"""What the **next** damage a named source deals does differently, as state.

``engine/shields.py`` is what a prevention shield *is* and ``engine/prevention.py``
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
``CardDefinition`` (CR 109.5) — one object per *card*, shared by every copy in
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

#: Both keys, for the end-of-turn sweep that is these records' whole duration.
#: Named as a pair so the sweep cannot pick up one of them and leave the other
#: running for the rest of the game — the failure a second spelling produces
#: here is a coin flip whose losing half never expires.
NEXT_DAMAGE_KEYS = (DAMAGE_DOUBLED_NEXT, DAMAGE_PREVENTED_NEXT)


def arm(source: Any, key: str, times: int = 1) -> bool:
    """Record that *source*'s next *times* damage events carry the *key* rider.

    False when there is nothing to write on — a source that is not a permanent
    (see the module docstring) or no source at all, which is what an effect
    whose choice found nothing hands over. The caller logs; refusing here is
    what keeps a marker off a shared ``CardDefinition``.
    """
    metadata = getattr(source, "metadata", None)
    if metadata is None or getattr(source, "permanent_id", None) is None:
        return False
    metadata[key] = int(metadata.get(key) or 0) + int(times)
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
    remaining = armed(source, key) - 1
    if remaining > 0:
        metadata[key] = remaining
    else:
        metadata.pop(key, None)
